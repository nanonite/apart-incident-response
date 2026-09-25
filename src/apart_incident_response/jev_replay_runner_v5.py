"""#197 — source-bound replay-v5 runner (offline; live gated).

Entry point for the fresh matched real/placebo/null Jev replay after the
authorized replay-v4 attempt stopped on ``provider_failure_limit``.

Split of responsibility:

- **v5 owns** registration loading, fail-closed preflight, the registered
  bounded retry pacing (2.0 s / 10.0 s), rooted output paths, report
  provenance and the CLI.
- **v4 owns** the reviewed schedule execution: frozen event-major branch order,
  the counterbalanced branch schedule, the durable append-only branch journal,
  request/state hash re-verification before every call, registered stop/retry/
  suspect/provider-failure rules and the registered equal-form analysis. That
  module is source-bound by the v5 registration and reused unchanged.

Offline by construction: no provider call happens before every preflight check
passes and an explicit runtime approval is supplied; ``live_collection_authorized``
stays false, binding this runner does not authorize execution, and the stopped
v4 outputs are never opened. No CLI path override exists.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import jev_choice as jc
from . import jev_choice_v2 as jc2
from . import jev_replay_preregistration as pr
from . import jev_replay_preregistration_v4 as prv4
from . import jev_replay_preregistration_v5 as prv5
from . import jev_replay_runner_v4 as _v4


REPLAY_RUNNER_VERSION = prv5.REPLAY_RUNNER_VERSION_V5
RUNNER_SOURCE_REL = prv5.RUNNER_SOURCE_REL_V5

# --- reviewed v4 machinery, reused unchanged -------------------------------
BranchJournal = _v4.BranchJournal
BranchJournalError = _v4.BranchJournalError
PROVIDER_FAILURE_CLASSES = _v4.PROVIDER_FAILURE_CLASSES
SUSPECT_NONTERMINAL_CLASSES = _v4.SUSPECT_NONTERMINAL_CLASSES
TERMINAL_INVALID_CLASSES = _v4.TERMINAL_INVALID_CLASSES
build_replay_plan = _v4.build_replay_plan
pre_read_state = _v4.pre_read_state
branch_choice_state = _v4.branch_choice_state
message_text_for = _v4.message_text_for
branch_metrics = _v4.branch_metrics
analyze_replay = _v4.analyze_replay


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_locked_registration(*, repo_root: Path | None = None,
                             pinned_hash: str | None = None) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    return prv5.load_locked_registration(repo_root=root, pinned_hash=pinned_hash)


def build_receiver(registration: Mapping[str, Any], *,
                   sleep_fn: Callable[[float], None] | None = None
                   ) -> jc2.JevChoiceAdapterV2:
    """Construct the registered Jev transport, including the v5 pacing."""

    protocol = registration.get("model_and_protocol") or {}
    backoff = protocol.get("backoff") or {}
    if backoff != dict(prv5.BACKOFF_V5):
        raise ValueError("registered backoff does not match the v5 bounded pacing")
    kwargs: dict[str, Any] = {
        "model": pr.JEV_REPLAY_MODEL,
        "max_physical_requests": prv4.PHYSICAL_REQUEST_CEILING,
        "max_retries": pr.JEV_REPLAY_MAX_RETRIES,
        "backoff_initial": backoff["initial_seconds"],
        "backoff_max": backoff["max_seconds"],
        "backoff_jitter": backoff["jitter"],
    }
    if sleep_fn is not None:
        kwargs["sleep_fn"] = sleep_fn
    return jc2.JevChoiceAdapterV2(jc.JevChoiceClient(**kwargs), model=pr.JEV_REPLAY_MODEL)


def verify_replay_runner_preflight(registration: Mapping[str, Any], receiver: Any, *,
                                   repo_root: Path, approval: str | None,
                                   check_credentials: bool = True,
                                   require_approval: bool = True,
                                   pinned_hash: str | None = None,
                                   journal_exists: bool | None = None,
                                   report_exists: bool | None = None) -> dict[str, Any]:
    """Named-check, fail-closed preflight; never issues a provider request."""

    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    check("runtime_approval_present", bool(approval) or not require_approval,
          None if approval else "approval required for --live")
    verification = prv5.verify_against_jev_replay_preregistration_v5(
        registration, repo_root=repo_root, require_approval=require_approval,
        journal_exists=journal_exists, report_exists=report_exists,
        check_credentials=False)
    check("registration_verifies", verification["ok"], verification["errors"])
    checks.extend(verification["checks"])
    check("registration_hash_matches",
          pinned_hash is None or registration.get("preregistration_hash") == pinned_hash,
          registration.get("preregistration_hash"))
    check("status_locked",
          registration.get("status") == prv5.JEV_REPLAY_V5_LOCKED_STATUS,
          registration.get("status"))
    check("live_collection_not_authorized",
          registration.get("live_collection_authorized") is False
          and registration.get("lock_is_not_live_authorization") is True, None)

    protocol = registration.get("model_and_protocol") or {}
    client = getattr(receiver, "client", None)
    check("jev_model_matches",
          protocol.get("model") == pr.JEV_REPLAY_MODEL
          == getattr(receiver, "model", None), protocol.get("model"))
    check("jev_endpoint_matches",
          protocol.get("endpoint") == pr.JEV_REPLAY_ENDPOINT
          == getattr(client, "endpoint", None), protocol.get("endpoint"))
    check("jev_retry_policy",
          protocol.get("max_retries") == pr.JEV_REPLAY_MAX_RETRIES
          and getattr(client, "max_retries", None) == pr.JEV_REPLAY_MAX_RETRIES
          and protocol.get("retryable_statuses") == sorted(jc.JEV_RETRYABLE_STATUSES), None)
    check("jev_bounded_pacing_enforced",
          getattr(client, "_backoff_initial", None) == prv5.BACKOFF_V5["initial_seconds"]
          and getattr(client, "_backoff_max", None) == prv5.BACKOFF_V5["max_seconds"],
          {"initial": getattr(client, "_backoff_initial", None),
           "max": getattr(client, "_backoff_max", None)})
    key = str(protocol.get("protocol_key") or "")
    check("jev_protocol_key",
          bool(key) and not jc.is_jev_protocol_key(key)
          and key == prv4.prv6_protocol_key(), key)
    check("codec_version",
          protocol.get("codec_version") == jc2.JEV_CHOICE_V2_CODEC_VERSION,
          protocol.get("codec_version"))

    caps = registration.get("caps") or {}
    partition = caps.get("provider_partition") or {}
    check("jev_physical_cap_enforced",
          getattr(client, "max_physical_requests", None) == prv4.PHYSICAL_REQUEST_CEILING
          and caps.get("physical_requests") == prv4.PHYSICAL_REQUEST_CEILING
          and partition.get("jev") == prv4.PHYSICAL_REQUEST_CEILING,
          getattr(client, "max_physical_requests", None))
    planned = caps.get("planned_calls") or {}
    check("planned_calls_51_0",
          (planned.get("jev"), planned.get("ling"), planned.get("combined")) == (51, 0, 51),
          planned)
    check("cost_caps_and_reserve",
          caps.get("cost_cap_usd") == prv4.COST_CAP_USD
          and caps.get("worst_case_cost_usd") == prv4.WORST_CASE_COST_USD
          and caps.get("worst_case_next_call_cost_usd") == prv4.NEXT_CALL_RESERVE_USD
          and float(caps.get("worst_case_cost_usd", 1e9)) <= float(caps.get("cost_cap_usd", 0.0)),
          {"cost_cap_usd": caps.get("cost_cap_usd"),
           "worst_case_cost_usd": caps.get("worst_case_cost_usd"),
           "next_call_reserve": caps.get("worst_case_next_call_cost_usd")})

    if check_credentials:
        credentials = jc.load_jev_credentials()
        check("jev_credentials_present",
              bool(credentials.present and credentials.shape_ok), credentials.redacted())

    failed = [entry["check"] for entry in checks if not entry["ok"]]
    return {"mode": f"{REPLAY_RUNNER_VERSION}-preflight", "ok": not failed,
            "failed": failed, "checks": checks,
            "registration_verification": verification}


def _blocked(reason: str, approval: str | None,
             registration: Mapping[str, Any]) -> dict[str, Any]:
    return {"mode": REPLAY_RUNNER_VERSION, "status": "blocked", "stop_reason": reason,
            "approval": approval,
            "registration_hash": registration.get("preregistration_hash"),
            "planned_events": prv4.EXPECTED_EVENT_COUNT,
            "provider_calls": 0,
            "raw_response_retained": False, "credentials_retained": False}


def _normalize(report: dict[str, Any], registration: Mapping[str, Any]) -> dict[str, Any]:
    """Stamp v5 provenance on the report produced by the shared v4 executor."""

    report["mode"] = REPLAY_RUNNER_VERSION
    report["registration_version"] = registration.get("preregistration_version")
    report["runner"] = {
        "entrypoint": RUNNER_SOURCE_REL,
        "executes_schedule_via": prv5.RUNNER_SOURCE_REL_V4,
        "bounded_pacing": dict(prv5.BACKOFF_V5),
        "note": ("v5 owns registration loading, preflight, pacing and report provenance; the "
                 "reviewed v4 executor owns schedule order, durable journaling and stop rules"),
    }
    return report


def execute(registration: Mapping[str, Any], receiver: Any, *,
            verification: Mapping[str, Any], approval: str | None,
            repo_root: Path, pinned_hash: str | None = None,
            sleep_fn: Callable[[float], None] | None = None) -> dict[str, Any]:
    """Run the frozen schedule with rooted v5 output paths."""

    outputs = registration.get("outputs") or {}
    root = Path(repo_root)
    report = _v4.execute_replay_runner(
        registration, receiver, verification=verification, approval=approval,
        pinned_hash=pinned_hash,
        journal_path=root / str(outputs.get("journal", prv5.DEFAULT_JOURNAL_V5)),
        report_path=root / str(outputs.get("report", prv5.DEFAULT_REPORT_V5)),
        sleep_fn=sleep_fn if sleep_fn is not None else time.sleep)
    if not isinstance(report, dict):  # defensive: executor always returns a dict
        raise TypeError("replay executor returned a non-mapping report")
    return _normalize(report, registration)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="#197 replay-v5 runner (offline; live gated)")
    parser.add_argument("--live", action="store_true",
                        help="execute the replay (requires --approval; never run offline)")
    parser.add_argument("--approval", help="reviewer runtime authorization reference")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--lock", action="store_true",
                        help="build and persist the offline v5 registration (never overwrites)")
    args = parser.parse_args(argv)
    root = Path(args.repo_root) if args.repo_root is not None else _repo_root()

    if args.lock:
        document = prv5.build_replay_preregistration_v5(approved=True, repo_root=root)
        prv5.write_registration(document, repo_root=root)
        print(json.dumps({"mode": REPLAY_RUNNER_VERSION, "status": "locked",
                          "path": str(prv5.DEFAULT_OUTPUT_V5),
                          "preregistration_hash": document["preregistration_hash"]},
                         indent=2, sort_keys=True))
        return 0

    try:
        registration = load_locked_registration(repo_root=root)
    except ValueError as exc:
        print(json.dumps({"mode": REPLAY_RUNNER_VERSION, "status": "blocked",
                          "stop_reason": f"registration_load_failed: {exc}",
                          "provider_calls": 0}, indent=2, sort_keys=True))
        return 2
    try:
        receiver = build_receiver(registration)
    except ValueError as exc:
        print(json.dumps({"mode": REPLAY_RUNNER_VERSION, "status": "blocked",
                          "stop_reason": f"transport_contract_failed: {exc}",
                          "provider_calls": 0}, indent=2, sort_keys=True))
        return 2
    verification = verify_replay_runner_preflight(
        registration, receiver, repo_root=root, approval=args.approval,
        check_credentials=bool(args.live), require_approval=bool(args.live),
        pinned_hash=registration.get("preregistration_hash"))
    print(json.dumps(verification, indent=2, sort_keys=True, allow_nan=False))
    if not verification["ok"]:
        return 2
    if not args.live:
        print(json.dumps({"mode": REPLAY_RUNNER_VERSION, "status": "offline",
                          "note": "preflight only; no provider call made",
                          "live_collection_authorized": False,
                          "authorizes_replay": False, "provider_calls": 0},
                         indent=2, sort_keys=True))
        return 0
    report = execute(registration, receiver, verification=verification,
                     approval=args.approval, repo_root=root,
                     pinned_hash=registration.get("preregistration_hash"))
    if report.get("status") != "blocked":
        target = root / str((registration.get("outputs") or {})["report"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                          encoding="utf-8")
    print(json.dumps({key: report.get(key) for key in
                      ("mode", "status", "stop_reason", "attempted_branches",
                       "valid_branches", "invalid_branches")},
                     indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["status"] == "completed" else (
        2 if report["status"] == "blocked" else 1)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "REPLAY_RUNNER_VERSION", "RUNNER_SOURCE_REL", "BranchJournal",
    "BranchJournalError", "PROVIDER_FAILURE_CLASSES", "SUSPECT_NONTERMINAL_CLASSES",
    "TERMINAL_INVALID_CLASSES", "build_replay_plan", "pre_read_state",
    "branch_choice_state", "message_text_for", "branch_metrics", "analyze_replay",
    "load_locked_registration", "build_receiver", "verify_replay_runner_preflight",
    "_blocked", "execute", "main",
]
