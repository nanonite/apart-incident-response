"""#158 — separately gated Jev normalization repeat diagnostic (prepared only).

Repeats the identical frozen ``COMM_CONTROL`` request
(``2ba516131bdb…``, the request whose v1 vector was rejected as
``not_normalized`` and discarded) K times under the v2 capture-then-judge codec.
Every raw vector and deviation is retained, rejection rates are reported at
``1e-6, 0.01, 0.03`` and the probe stops immediately if any absolute deviation
exceeds ``0.05``.

The probe is prepared, never executed, by the offline registration work. It has
its own request and cost caps, requires a separate future live approval, and its
repetitions are stochastic repeats of one frozen request — never independent
prompt forms. No API calls unless ``--live`` and ``--approval`` are both given.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import jev_choice as jc
from . import jev_choice_v2 as jc2
from . import jev_replay_preregistration as pr
from . import jev_replay_preregistration_v2 as prv2
from .jev_choice import JevChoiceClient
from .jev_choice_smoke import estimate_cost_usd
from .communication_protocol import DependenceRegime, ReasoningComplexity
from . import task_families as tf


PROBE_VERSION = "jev-choice-normalization-probe-v2"
DEFAULT_PROBE_REPORT = Path("runs/epic-126/jev-choice-normalization-probe-report-v2.json")
DEFAULT_PROBE_JOURNAL = Path("runs/epic-126/jev-choice-normalization-probe-v2.jsonl")


def probe_state(adapter: jc2.JevChoiceAdapterV2) -> jc.ChoiceState:
    """Reconstruct the frozen COMM_CONTROL request and verify its hash."""

    instance = tf.generate_instance("planning", pr.JEV_REPLAY_SEED_BASE, DependenceRegime.N,
                                    ReasoningComplexity.LOW)
    state = adapter.build_state(instance, "A", "COMM", visible_messages=[])
    if state.request_hash != prv2.PROBE_REQUEST_HASH_FULL:
        raise ValueError(
            f"probe request hash drift: {state.request_hash} != {prv2.PROBE_REQUEST_HASH_FULL}")
    return state


def verify_probe_preflight(adapter: jc2.JevChoiceAdapterV2, *, probe: Mapping[str, Any],
                           repo_root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    state = probe_state(adapter)
    check("request_hash_matches", state.request_hash == prv2.PROBE_REQUEST_HASH_FULL,
          state.request_hash)
    check("k_within_registered_range", prv2.PROBE_K_RANGE[0] <= prv2.PROBE_K <= prv2.PROBE_K_RANGE[1],
          prv2.PROBE_K)
    check("execution_not_authorized", probe.get("execution_authorized") is False, None)
    check("live_collection_not_authorized", probe.get("live_collection_authorized") is False, None)
    check("request_cap_frozen", probe.get("caps", {}).get("physical_requests") == prv2.PROBE_REQUEST_CAP,
          probe.get("caps", {}).get("physical_requests"))
    check("cost_cap_frozen", probe.get("caps", {}).get("cost_cap_usd") == prv2.PROBE_COST_CAP_USD,
          probe.get("caps", {}).get("cost_cap_usd"))
    check("worst_case_within_cap",
          float(probe.get("caps", {}).get("worst_case_cost_usd", 1.0)) <= prv2.PROBE_COST_CAP_USD,
          probe.get("caps", {}).get("worst_case_cost_usd"))
    client = adapter.client
    check("receiver_endpoint_matches", getattr(client, "endpoint", None) == pr.JEV_REPLAY_ENDPOINT,
          getattr(client, "endpoint", None))
    check("receiver_partition_enforced",
          getattr(client, "max_physical_requests", None) == prv2.PROBE_REQUEST_CAP,
          getattr(client, "max_physical_requests", None))
    check("receiver_retry_policy", getattr(client, "max_retries", None) == prv2.PROBE_MAX_RETRIES,
          getattr(client, "max_retries", None))
    check("codec_version_is_v2", probe.get("model_and_protocol", {}).get("codec_version")
          == jc2.JEV_CHOICE_V2_CODEC_VERSION, None)
    check("not_independent_prompt_forms",
          probe.get("design", {}).get("independent_prompt_forms") is False, None)
    check("stop_rule_frozen",
          probe.get("design", {}).get("stop_if_absolute_deviation_above")
          == prv2.PROBE_STOP_ABSOLUTE_DEVIATION, None)
    return {"ok": all(item["ok"] for item in checks), "checks": checks,
            "failed": [item["check"] for item in checks if not item["ok"]]}


def _rejected_at(absolute_deviation: float | None, shape_valid: bool, tolerance: float) -> bool:
    if not shape_valid or absolute_deviation is None:
        return True
    epsilon = jc2.NORMALIZATION_BOUNDARY_EPSILON if tolerance >= jc2.PRIMARY_ACCEPTANCE_BOUND else 0.0
    return absolute_deviation > tolerance + epsilon


def _blocked(reason: str, approval: str | None) -> dict[str, Any]:
    return {"mode": "jev-choice-normalization-probe-v2", "status": "blocked", "stop_reason": reason,
            "approval": approval, "attempted": 0, "physical_attempts": 0, "records": [],
            "raw_response_retained": False, "credentials_retained": False}


def execute_probe(adapter: jc2.JevChoiceAdapterV2, verification: Mapping[str, Any], *,
                  approval: str | None, k: int = prv2.PROBE_K,
                  journal_path: Path | None = None,
                  sleep_fn: Callable[[float], None] = lambda _seconds: None) -> dict[str, Any]:
    """Run the gated repeat diagnostic. Fails closed without approval or preflight."""

    if not approval:
        return _blocked("missing_approval", approval)
    if not verification.get("ok"):
        return _blocked("preflight_failed", approval)
    if not prv2.PROBE_K_RANGE[0] <= k <= prv2.PROBE_K_RANGE[1]:
        return _blocked("k_out_of_range", approval)
    state = probe_state(adapter)
    report: dict[str, Any] = {
        "mode": "jev-choice-normalization-probe-v2", "probe_version": PROBE_VERSION,
        "status": "completed", "stop_reason": None, "approval": approval,
        "request_hash": state.request_hash, "k_planned": k, "attempted": 0,
        "physical_attempts": 0, "max_physical_requests": prv2.PROBE_REQUEST_CAP,
        "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0,
        "cost_cap_usd": prv2.PROBE_COST_CAP_USD, "records": [],
        "rejection_rates": {str(tolerance): None for tolerance in prv2.PROBE_REJECTION_RATES_AT},
        "independent_prompt_forms": False, "raw_response_retained": False,
        "credentials_retained": False,
    }
    handle = None
    if journal_path is not None:
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        handle = journal_path.open("x", encoding="utf-8")
    try:
        for index in range(k):
            if report["estimated_cost_usd"] >= prv2.PROBE_COST_CAP_USD:
                report["status"], report["stop_reason"] = "stopped", "cost_cap"
                break
            if index > 0:
                sleep_fn(0.25)
            response, _ = adapter.complete_with_raw(state)
            report["attempted"] += 1
            usage = dict(response.usage)
            report["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
            report["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
            report["estimated_cost_usd"] = estimate_cost_usd(report["input_tokens"])
            diagnostics = response.diagnostics
            record = {
                "index": index,
                "status": response.status,
                "error_class": response.error_class,
                "normalization_tier": response.normalization_tier,
                "renormalized": response.renormalized,
                "raw_probabilities": dict(response.raw_probabilities),
                "probabilities": dict(response.probabilities),
                "probability_diagnostics": diagnostics.to_dict() if diagnostics is not None else None,
            }
            report["records"].append(record)
            if handle is not None:
                handle.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            absolute = diagnostics.absolute_normalization_deviation if diagnostics is not None else None
            if absolute is not None and absolute > prv2.PROBE_STOP_ABSOLUTE_DEVIATION:
                report["status"], report["stop_reason"] = "stopped", "not_normalized_hard"
                break
    finally:
        if handle is not None:
            handle.close()
    report["physical_attempts"] = int(getattr(adapter.client, "physical_attempts", 0) or 0)
    records = report["records"]
    for tolerance in prv2.PROBE_REJECTION_RATES_AT:
        rejected = 0
        for record in records:
            diagnostics = record.get("probability_diagnostics") or {}
            shape_valid = bool(diagnostics.get("shape_valid"))
            absolute = diagnostics.get("absolute_normalization_deviation")
            if _rejected_at(absolute, shape_valid, tolerance):
                rejected += 1
        report["rejection_rates"][str(tolerance)] = (rejected / len(records)) if records else None
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="#158 gated Jev normalization repeat diagnostic")
    parser.add_argument("--probe-registration", type=Path, default=prv2.DEFAULT_PROBE_V2)
    parser.add_argument("--report", type=Path, default=DEFAULT_PROBE_REPORT)
    parser.add_argument("--journal", type=Path, default=DEFAULT_PROBE_JOURNAL)
    parser.add_argument("--live", action="store_true", help="run live (requires --approval)")
    parser.add_argument("--approval", help="recorded reviewer approval reference; required for --live")
    args = parser.parse_args(argv)
    probe = json.loads(args.probe_registration.read_text(encoding="utf-8"))
    client = JevChoiceClient(model=pr.JEV_REPLAY_MODEL, max_physical_requests=prv2.PROBE_REQUEST_CAP,
                             max_retries=prv2.PROBE_MAX_RETRIES)
    adapter = jc2.JevChoiceAdapterV2(client, model=pr.JEV_REPLAY_MODEL)
    verification = verify_probe_preflight(adapter, probe=probe,
                                          repo_root=Path(__file__).resolve().parents[2])
    print(json.dumps({"mode": "jev-choice-normalization-probe-v2-preflight", "ok": verification["ok"],
                      "failed": verification["failed"], "checks": verification["checks"],
                      "request_hash": probe_state(adapter).request_hash,
                      "k": prv2.PROBE_K, "request_cap": prv2.PROBE_REQUEST_CAP,
                      "cost_cap_usd": prv2.PROBE_COST_CAP_USD}, indent=2, sort_keys=True, allow_nan=False))
    if not verification["ok"]:
        return 2
    if not args.live:
        return 0
    if not args.approval:
        print(json.dumps({"mode": "jev-choice-normalization-probe-v2", "status": "blocked",
                          "stop_reason": "missing_approval"}, indent=2, sort_keys=True))
        return 2
    report = execute_probe(adapter, verification, approval=args.approval, journal_path=args.journal)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PROBE_VERSION", "DEFAULT_PROBE_REPORT", "DEFAULT_PROBE_JOURNAL", "probe_state",
    "verify_probe_preflight", "execute_probe", "main",
]
