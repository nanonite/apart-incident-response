"""P06 (#207): fail-closed runner and preflight for the registered
hypothesis:low discovery collection.

Offline by construction. The live transport is never constructed until every
gate has passed: authorization record in ``authorized`` state, a supplied
reference matching the registered scope digest, a green preflight, and fresh
output paths. A pending record therefore cannot make a provider call even if
``--live`` is passed.

Seeds are never substituted, and the journal is never resumed, appended,
overwritten, or extended from outcomes: it is opened with ``"x"`` so an
existing journal is an output collision and the run refuses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from apart_incident_response import jev_p04_design_classification as p04
from apart_incident_response import jev_p05_discovery_lock as p05

RUNNER_VERSION = "jev-p06-discovery-runner-v1"

REGISTRATION_PATH = str(p04.REGISTRATION_PATH)
LOCK_PATH = str(p05.LOCK_PATH)
AUTH_PATH = "runs/next-phase/jev-discovery-authorization-record-v1.json"

REGISTRATION_HASH = "6fa6149770b620cd3a026a6415f8e4d97e800e8af5237794de7b29fca6dacfac"
LOCK_HASH = "9de4a61f9d46c47b55bbe7b8da9903c677c6461bf4af353007277835ed6a18b3"
SCOPE_DIGEST = "938da9116805967253417c53709cd85d56d1913ac0142032d0d4732f50c04061"

AUTH_STATE_PENDING = "awaiting_explicit_reference"
AUTH_STATE_AUTHORIZED = "authorized"
MUST_COVER = ["stage", "route", "request_caps", "cost_caps"]

BLOCK_N = 16
INSTANCES_PER_FORM = 4
FORM_COUNT = 4
STAGE = "hypothesis:low discovery screen and optional exploratory replay"


class DiscoveryRunError(RuntimeError):
    """Fail-closed run, journal or cap violation."""


# --------------------------------------------------------------------------
# journal
# --------------------------------------------------------------------------

class DiscoveryJournal:
    """Append-only journal, one durable row per planned seed.

    Opens with ``"x"``: an existing journal is an output collision and the
    run refuses rather than resuming or appending.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.handle = path.open("x", encoding="utf-8")
        self.keys: set[str] = set()
        self.rows = 0
        self.fsync_count = 0

    def write(self, row: Mapping[str, Any]) -> None:
        key = str(row.get("instance_id"))
        if key in self.keys:
            self.close()
            raise DiscoveryRunError(f"duplicate journal key: {key}")
        self.handle.write(json.dumps(dict(row), sort_keys=True, allow_nan=False) + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.fsync_count += 1
        self.rows += 1
        self.keys.add(key)

    def close(self) -> None:
        if not self.handle.closed:
            self.handle.close()

    @staticmethod
    def read_rows(path: Path) -> list[dict[str, Any]]:
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        return [json.loads(line) for line in text.splitlines() if line.strip()]


# --------------------------------------------------------------------------
# transport (the only place a provider call can occur)
# --------------------------------------------------------------------------

class DiscoveryTransport:
    """Live transport. Never constructed until every gate has passed.

    The base class is an *unconfigured* stub: it refuses every call and stays
    ``is_configured = False``, so an authorized run against an unwired
    transport is refused before the journal is created instead of burning the
    fresh output paths on 16 seeded failures. A real transport must set
    ``is_configured = True``.
    """

    is_configured = False

    def writer_completion(self, *, request: Mapping[str, Any]) -> Mapping[str, Any]:
        raise NotImplementedError("live writer transport is not configured")

    def receiver_choice(self, *, request: Mapping[str, Any]) -> Mapping[str, Any]:
        raise NotImplementedError("live receiver transport is not configured")


# --------------------------------------------------------------------------
# caps
# --------------------------------------------------------------------------

class CapTracker:
    """Retry-inclusive request and cost caps, enforced before every call."""

    #: Every logical call may execute 1 + max_retries 2 physical attempts, so the
    #: whole retry-inclusive worst case is reserved before the call is allowed.
    MAX_PHYSICAL_PER_CALL = 3

    def __init__(self, budgets: Mapping[str, Any]) -> None:
        self.collection = budgets.get("discovery_collection") or {}
        self.cost_model = budgets.get("cost_model") or {}
        self.planned = dict(self.collection.get("planned") or {})
        self.physical = dict(self.collection.get("physical") or {})
        self.ceiling = float(self.collection.get("cost_ceiling_usd") or 0.0)
        self.reservation = dict(self.collection.get("next_call_reservation_usd") or {})
        self.physical_used = {"ling": 0, "jev": 0}
        self.planned_used = {"ling": 0, "jev": 0}
        self.cost_usd = 0.0

    def reason_before_call(self, provider: str) -> str | None:
        """Return a registered stop reason, or None when the call may proceed."""
        if provider not in self.physical_used:
            return f"unknown_provider:{provider}"
        if self.planned_used[provider] + 1 > int(self.planned.get(provider, 0)):
            return f"request_cap_planned:{provider}"
        if self.physical_used[provider] + self.MAX_PHYSICAL_PER_CALL > int(
                self.physical.get(provider, 0)):
            return f"request_cap_physical:{provider}"
        reservation = float(self.reservation.get(provider, 0.0))
        if self.cost_usd + reservation > self.ceiling:
            return f"cost_cap_before_next_call:{provider}"
        return None

    def record(self, provider: str, *, attempts: int, cost_usd: float) -> None:
        self.planned_used[provider] += 1
        self.physical_used[provider] += attempts
        self.cost_usd += float(cost_usd)

    def snapshot(self) -> dict[str, Any]:
        return {
            "planned_used": dict(self.planned_used),
            "physical_used": dict(self.physical_used),
            "planned_cap": dict(self.planned),
            "physical_cap": dict(self.physical),
            "cost_usd": round(self.cost_usd, 12),
            "cost_ceiling_usd": self.ceiling,
            "within_ceiling": self.cost_usd <= self.ceiling,
        }


# --------------------------------------------------------------------------
# loading and authorization gate
# --------------------------------------------------------------------------

def _load(root: Path, rel: str) -> dict[str, Any]:
    path = root / rel
    if not path.is_file():
        raise DiscoveryRunError(f"missing artifact: {rel}")
    return json.loads(path.read_text(encoding="utf-8"))


def scope_digest(scope: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(scope, sort_keys=True).encode("utf-8")).hexdigest()


def evaluate_authorization(auth: Mapping[str, Any], *, approval: str | None,
                           lock: Mapping[str, Any]) -> str | None:
    """Return a stop reason, or None when the record authorizes this exact scope."""
    if auth.get("state") != AUTH_STATE_AUTHORIZED:
        return "authorization_pending"
    if auth.get("authorized") is not True:
        return "authorization_flag_not_set"
    reference = auth.get("reference")
    if not isinstance(reference, str) or not reference.strip():
        return "authorization_reference_missing"
    for field in ("supplied_by", "supplied_at", "decision"):
        if not isinstance(auth.get(field), str) or not str(auth.get(field)).strip():
            return f"authorization_{field}_missing"
    if auth.get("scope_digest_sha256") != SCOPE_DIGEST:
        return "scope_digest_mismatch"
    declared = (auth.get("what_a_reference_must_state") or {}).get("scope_digest_sha256")
    if declared != SCOPE_DIGEST:
        return "scope_digest_not_echoed_in_reference"
    if auth.get("scope") != (lock.get("authorization_scope") or {}):
        return "authorization_scope_drift_from_lock"
    if auth.get("must_cover") != MUST_COVER:
        return "authorization_must_cover_drift"
    if approval is None:
        return "approval_reference_not_supplied"
    if approval.strip() != reference.strip():
        return "approval_reference_mismatch"
    return None


def _blocked(reason: str, *, auth: Mapping[str, Any] | None = None,
             extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mode": RUNNER_VERSION,
        "status": "blocked",
        "stop_reason": reason,
        "authorization_state": (auth or {}).get("state", AUTH_STATE_PENDING),
        "planned_seeds": BLOCK_N,
        "provider_calls": 0,
        "credentials_retained": False,
    }
    payload.update(dict(extra or {}))
    return payload


# --------------------------------------------------------------------------
# preflight
# --------------------------------------------------------------------------

def run_preflight(repo_root: Path, *, approval: str | None = None) -> dict[str, Any]:
    """Fail-closed offline preflight. Makes no provider call, ever."""
    root = Path(repo_root)
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

    try:
        registration = _load(root, REGISTRATION_PATH)
        lock = _load(root, LOCK_PATH)
        auth = _load(root, AUTH_PATH)
    except (DiscoveryRunError, OSError, json.JSONDecodeError) as exc:
        check("artifacts_present", False, f"{type(exc).__name__}: {exc}")
        return {"mode": f"{RUNNER_VERSION}-preflight", "ok": False, "errors": errors,
                "failed": [entry["check"] for entry in checks if not entry["ok"]],
                "checks": checks, "checks_run": len(checks), "provider_calls": 0,
                "status": "offline"}

    check("artifacts_present", True, None)
    check("registration_hash_matches_pin",
          registration.get("registration_hash") == REGISTRATION_HASH,
          registration.get("registration_hash"))
    check("registration_verifies_green",
          p04.verify_registration(registration, repo_root=root).get("ok") is True, None)
    check("lock_hash_matches_pin", lock.get("lock_hash") == LOCK_HASH,
          lock.get("lock_hash"))
    check("lock_verifies_green", p05.verify_lock(lock, repo_root=root).get("ok") is True,
          None)
    check("lock_pins_registration",
          (lock.get("locked_registration") or {}).get("registration_hash")
          == REGISTRATION_HASH, None)

    scope = lock.get("authorization_scope") or {}
    check("authorization_record_scope_matches_lock",
          auth.get("scope") == scope, None)
    check("authorization_record_scope_digest",
          auth.get("scope_digest_sha256") == SCOPE_DIGEST
          and scope_digest(scope) == SCOPE_DIGEST,
          auth.get("scope_digest_sha256"))
    check("authorization_record_must_cover",
          auth.get("must_cover") == MUST_COVER, auth.get("must_cover"))
    inferred = auth.get("may_not_be_inferred_from") or []
    check("authorization_non_inference_list",
          "this record" in inferred and "the P05 lock" in inferred
          and "credentials present in the environment" in inferred, inferred)

    state = auth.get("state")
    if state == AUTH_STATE_PENDING:
        check("pending_state_is_not_authorized",
              auth.get("authorized") is False and auth.get("reference") is None
              and auth.get("supplied_by") is None and auth.get("supplied_at") is None
              and auth.get("decision") is None, state)
    elif state == AUTH_STATE_AUTHORIZED:
        check("authorized_state_has_all_fields",
              auth.get("authorized") is True
              and bool(str(auth.get("reference") or "").strip())
              and bool(str(auth.get("supplied_by") or "").strip())
              and bool(str(auth.get("supplied_at") or "").strip())
              and bool(str(auth.get("decision") or "").strip()), state)
    else:
        check("authorization_state_known", False, state)

    if approval is not None and state == AUTH_STATE_AUTHORIZED:
        check("approval_matches_record_reference",
              approval.strip() == str(auth.get("reference") or "").strip(),
              "supplied approval does not match the record reference")

    fixed_n = registration.get("fixed_n") or {}
    manifest = fixed_n.get("manifest") or []
    check("manifest_is_16_fixed_seeds",
          len(manifest) == BLOCK_N
          and fixed_n.get("instances_per_form") == INSTANCES_PER_FORM
          and fixed_n.get("form_count") == FORM_COUNT, len(manifest))
    check("manifest_seeds_unique_and_in_window",
          len({entry.get("seed") for entry in manifest}) == BLOCK_N
          and all(85000 <= int(entry.get("seed", -1)) <= 85511 for entry in manifest),
          None)
    check("selection_rule_no_outcome_stopping",
          "no outcome-based stopping" in str(fixed_n.get("selection_rule")),
          fixed_n.get("selection_rule"))

    route = registration.get("route") or {}
    check("route_ling_paid_openrouter",
          "paid OpenRouter SKU" in str((route.get("ling") or {}).get("route"))
          and (route.get("ling") or {}).get("model") == "inclusionai/ling-3.0-flash-vl", None)
    check("route_jev_systemone",
          (route.get("jev") or {}).get("model") == "jev-1.13.0"
          and "api.typesafe.ai" in str((route.get("jev") or {}).get("endpoint")), None)

    check("request_caps_match_lock",
          scope.get("request_caps") == (lock.get("authorization_scope") or {}).get(
              "request_caps"), None)
    check("cost_caps_match_lock",
          scope.get("cost_caps") == (lock.get("authorization_scope") or {}).get(
              "cost_caps"), None)

    stops = registration.get("stops") or []
    check("registered_stops_present",
          len(stops) >= 10 and any("output collision" in str(item) for item in stops)
          and any("cost cap" in str(item) for item in stops), len(stops))

    paths = registration.get("paths") or {}
    live = [str(value) for key, value in paths.items() if key != "registration"]
    check("output_paths_registered_fresh", len(live) == 4, sorted(live))
    check("output_paths_absent", not any((root / value).exists() for value in live),
          sorted(value for value in live if (root / value).exists()))
    lifecycle = registration.get("path_lifecycle") or {}
    check("path_lifecycle_forbids_resume_append_overwrite",
          lifecycle.get("resume") is False and lifecycle.get("append") is False
          and lifecycle.get("overwrite") is False
          and lifecycle.get("path_overrides") is False, lifecycle)

    classification = registration.get("design_classification") or {}
    check("k4_pilot_preserved", classification.get("k") == 4
          and classification.get("classification") == "pilot", classification.get("k"))

    evidence = registration.get("input_evidence") or {}
    check("frozen_200_artifacts_byte_unchanged",
          p05._sha256_file(root / p04.AUDIT_PATH)
          == evidence.get("audit_200", {}).get("file_sha256")
          and p05._sha256_file(root / p04.REGISTRATION_200_PATH)
          == evidence.get("registration_200", {}).get("file_sha256"), None)

    authorization_state = evaluate_authorization(auth, approval=approval, lock=lock)
    return {"mode": f"{RUNNER_VERSION}-preflight", "ok": not errors,
            "errors": errors,
            "failed": [entry["check"] for entry in checks if not entry["ok"]],
            "checks": checks, "checks_run": len(checks),
            "authorization_state": state,
            "authorized": state == AUTH_STATE_AUTHORIZED,
            "authorization_stop_reason": authorization_state,
            "scope_digest_sha256": SCOPE_DIGEST,
            "registration_hash": REGISTRATION_HASH,
            "lock_hash": LOCK_HASH,
            "planned_seeds": BLOCK_N,
            "status": "offline", "provider_calls": 0}


# --------------------------------------------------------------------------
# execution
# --------------------------------------------------------------------------

def _seed_row(instance: Mapping[str, Any], *, sequence: int) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "stage": STAGE,
        "instance_id": instance.get("instance_id"),
        "prompt_form_id": instance.get("prompt_form_id"),
        "seed": instance.get("seed"),
        "attempted": False,
        "status": "not_attempted",
        "failure_reason": None,
        "structural_need": None,
        "emission": None,
        "ownership": None,
        "exposure": None,
        "information": None,
        "request": None,
        "cost": {"usd": 0.0, "cumulative_usd": 0.0},
        "provider_calls": 0,
    }


def execute_discovery_run(
    registration: Mapping[str, Any],
    lock: Mapping[str, Any],
    auth: Mapping[str, Any],
    *,
    repo_root: Path,
    approval: str | None,
    preflight: Mapping[str, Any],
    transport_factory: Callable[[], DiscoveryTransport] | None = None,
    journal_path: Path | None = None,
    report_path: Path | None = None,
    row_hook: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Execute the registered discovery block, or refuse before any call."""
    root = Path(repo_root)
    paths = registration.get("paths") or {}
    journal_path = journal_path or root / str(paths.get("discovery_journal", ""))
    report_path = report_path or root / str(paths.get("discovery_report", ""))

    stop = evaluate_authorization(auth, approval=approval, lock=lock)
    if stop is not None:
        return _blocked(stop, auth=auth)
    if not preflight.get("ok"):
        return _blocked("preflight_failed", auth=auth,
                        extra={"failed": preflight.get("failed")})
    if journal_path.exists():
        return _blocked("output_collision:journal_exists", auth=auth,
                        extra={"path": str(journal_path)})
    if report_path.exists():
        return _blocked("output_collision:report_exists", auth=auth,
                        extra={"path": str(report_path)})
    if transport_factory is None:
        return _blocked("transport_not_configured", auth=auth)

    manifest = list((registration.get("fixed_n") or {}).get("manifest") or [])
    if len(manifest) != BLOCK_N:
        return _blocked("manifest_drift", auth=auth, extra={"found": len(manifest)})

    caps = CapTracker(registration.get("budgets") or {})
    transport = transport_factory()
    if not getattr(transport, "is_configured", False):
        # Refuse before the journal exists: an unwired transport must never
        # consume the fresh output paths.
        return _blocked("transport_not_configured", auth=auth)
    journal = DiscoveryJournal(journal_path)
    completed = {"ok": 0, "silence": 0, "failed": 0, "not_attempted": 0}
    stop_reason: str | None = None
    provider_calls = 0

    try:
        for index, instance in enumerate(manifest):
            row = _seed_row(instance, sequence=index + 1)
            if stop_reason is None:
                reason = caps.reason_before_call("ling")
                if reason is not None:
                    stop_reason = reason
            if stop_reason is None:
                row["attempted"] = True
                try:
                    result = transport.writer_completion(
                        request={"instance_id": instance.get("instance_id"),
                                 "seed": instance.get("seed"),
                                 "model": "inclusionai/ling-3.0-flash-vl"})
                except Exception as exc:  # noqa: BLE001 - fail closed on transport error
                    row["status"] = "failed"
                    row["failure_reason"] = f"writer_error:{type(exc).__name__}"
                    completed["failed"] += 1
                    caps.record("ling", attempts=1, cost_usd=0.0)
                    if row_hook:
                        row_hook(row)
                    journal.write(row)
                    continue
                attempts = int(result.get("attempts", 1))
                provider_calls += attempts
                caps.record("ling", attempts=attempts,
                            cost_usd=float(result.get("cost_usd", 0.0)))
                emission = result.get("emission") or {}
                row["structural_need"] = bool(result.get("structural_need"))
                row["emission"] = emission
                row["ownership"] = result.get("ownership")
                row["exposure"] = result.get("exposure")
                row["information"] = result.get("information")
                row["request"] = {"provider": "ling",
                                  "model": "inclusionai/ling-3.0-flash-vl",
                                  "endpoint": "https://openrouter.ai/api/v1/chat/completions",
                                  "attempts": attempts,
                                  "request_hash": result.get("request_hash")}
                row["cost"] = {"usd": float(result.get("cost_usd", 0.0)),
                               "cumulative_usd": round(caps.cost_usd, 12)}
                row["provider_calls"] = attempts
                if not emission:
                    row["status"] = "silence"
                    completed["silence"] += 1
                else:
                    row["status"] = "ok"
                    completed["ok"] += 1
            else:
                row["failure_reason"] = f"not_attempted:{stop_reason}"
                completed["not_attempted"] += 1
            if row_hook:
                row_hook(row)
            journal.write(row)
    finally:
        journal.close()

    report = {
        "mode": RUNNER_VERSION,
        "status": "completed" if stop_reason is None else "stopped",
        "stop_reason": stop_reason,
        "stage": STAGE,
        "scope_digest_sha256": SCOPE_DIGEST,
        "registration_hash": REGISTRATION_HASH,
        "lock_hash": LOCK_HASH,
        "authorization_reference": auth.get("reference"),
        "planned_seeds": BLOCK_N,
        "journaled_seeds": journal.rows,
        "counts": completed,
        "caps": caps.snapshot(),
        "provider_calls": provider_calls,
        "seeds": [entry.get("instance_id") for entry in manifest],
        "credentials_retained": False,
    }
    return report


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="P06 discovery collection runner (offline preflight by default; "
                    "live execution requires an authorized record and --approval)")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--live", action="store_true",
                        help="execute the collection (refused unless the authorization "
                             "record is authorized and --approval matches its reference)")
    parser.add_argument("--approval", help="explicit live authorization reference")
    args = parser.parse_args(argv)
    root = Path(args.repo_root) if args.repo_root is not None else Path(
        __file__).resolve().parents[2]

    preflight = run_preflight(root, approval=args.approval)
    print(json.dumps({"mode": preflight["mode"], "ok": preflight["ok"],
                      "failed": preflight["failed"], "checks_run": preflight["checks_run"],
                      "authorization_state": preflight["authorization_state"],
                      "authorized": preflight["authorized"],
                      "authorization_stop_reason": preflight["authorization_stop_reason"],
                      "scope_digest_sha256": preflight["scope_digest_sha256"],
                      "planned_seeds": preflight["planned_seeds"],
                      "provider_calls": 0, "status": preflight["status"]},
                     indent=2, sort_keys=True, allow_nan=False))
    if not preflight["ok"]:
        return 2
    if not args.live:
        return 0

    registration = _load(root, REGISTRATION_PATH)
    lock = _load(root, LOCK_PATH)
    auth = _load(root, AUTH_PATH)
    report = execute_discovery_run(
        registration, lock, auth, repo_root=root, approval=args.approval,
        preflight=preflight,
        # Constructed only after every gate passes; a pending record never reaches it.
        transport_factory=(lambda: DiscoveryTransport()) if args.live else None)
    print(json.dumps({key: report.get(key) for key in
                      ("mode", "status", "stop_reason", "authorization_state",
                       "planned_seeds", "journaled_seeds", "provider_calls")},
                     indent=2, sort_keys=True, allow_nan=False))
    if report.get("status") == "blocked":
        return 3
    target = root / str(registration["paths"]["discovery_report"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                      encoding="utf-8")
    return 0 if report.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "RUNNER_VERSION", "REGISTRATION_PATH", "LOCK_PATH", "AUTH_PATH",
    "REGISTRATION_HASH", "LOCK_HASH", "SCOPE_DIGEST", "AUTH_STATE_PENDING",
    "AUTH_STATE_AUTHORIZED", "MUST_COVER", "BLOCK_N", "INSTANCES_PER_FORM",
    "FORM_COUNT", "STAGE", "DiscoveryRunError", "DiscoveryJournal",
    "DiscoveryTransport", "CapTracker", "scope_digest", "evaluate_authorization",
    "run_preflight", "execute_discovery_run", "main",
]
