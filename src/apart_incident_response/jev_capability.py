"""J3e — bounded Jev Choice capability/calibration probe runner (#180).

Offline by default. The preflight pins the reviewed registration hash and fails
closed; a live run additionally requires an explicit approval record. Case rows
are journaled durably; a fresh run refuses to overwrite an existing journal
(automatic resume is disabled for this small run so retry accounting cannot
silently exceed the cap). This is a repeated-query capability check: the 34
cases contain only 12 distinct request hashes and do not establish calibration.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Sequence

from .behavioral_discovery import wilson_interval
from . import jev_choice as jc
from . import jev_preregistration as jp
from .jev_choice import JevChoiceAdapter, JevChoiceClient, load_jev_credentials
from .jev_choice_smoke import estimate_cost_usd


#: The reviewed, locked registration hash from #179 (amended v2). Fail closed if it differs.
JEV_CAPABILITY_REGISTRATION_HASH = "f9cb7b314ddf816013ab1d4d671e6b147d1415c897ace0851844c39cc3c78fb5"
DEFAULT_REGISTRATION = Path("runs/epic-126/jev-choice-capability-preregistration.json")
DEFAULT_REPORT = Path("runs/epic-126/jev-choice-capability-report.json")
DEFAULT_OUTPUT = Path("runs/epic-126/jev-choice-capability.jsonl")
RELIABILITY_BINS = 5
LOG_LOSS_FLOOR = 1e-12

#: Frozen metric definitions recorded in every report so the analysis cannot
#: drift between collection and interpretation.
METRIC_DEFINITIONS = {
    "task_validity_full": "checker-accepted FULL selections divided by the fixed 17 FULL cases; a missing "
                          "or invalid FULL output counts as a failure",
    "full_vector_validity": "attempted cases returning the documented Choice envelope divided by attempted cases",
    "p_correct_full": "mean probability assigned to the true target over the 17 FULL cases; a missing or "
                      "invalid FULL output counts as 0.0",
    "p_correct_full_interval": "normal-approximation interval for the mean target probability (descriptive; "
                               "Wilson does not apply to a mean probability)",
    "brier_multiclass": "mean over the 17 FULL cases of sum_i (p_i - 1{option_i == target})^2; a missing or "
                        "invalid case scores 1.0",
    "log_loss_multiclass": "mean over the 17 FULL cases of -log(p_target); a missing or invalid case scores "
                           "-log(1e-12)",
    "selected_answer_reliability": "descriptive bins of the selected-option probability against checker "
                                   "correctness; separate from target calibration",
    "reliability_bins": "alias of selected_answer_reliability (kept for the registered metric name)",
    "repeated_prompt_limitation": "the 34 cases contain only 12 distinct request hashes (6 ISO/FULL prompt "
                                  "pairs) and 10 match the earlier wire smoke; these are repeated queries, "
                                  "not independent prompts, so no calibration is established",
}


@dataclass(frozen=True)
class CapabilityCase:
    instance_id: str
    seed: int
    condition: str
    question_id: str
    option_ids: tuple[str, ...]
    target_id: str
    request_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {"instance_id": self.instance_id, "seed": self.seed, "condition": self.condition,
                "question_id": self.question_id, "option_count": len(self.option_ids),
                "request_hash": self.request_hash}


@dataclass(frozen=True)
class CapabilityPlan:
    model: str
    endpoint: str
    protocol_key: str
    registration_hash: str
    cases: tuple[CapabilityCase, ...]
    request_cap: int
    cost_cap_usd: float
    input_token_ceiling: int
    min_interval_seconds: float

    def to_dict(self) -> dict[str, Any]:
        distinct = len({case.request_hash for case in self.cases})
        return {
            "model": self.model, "endpoint": self.endpoint, "protocol_key": self.protocol_key,
            "registration_hash": self.registration_hash, "planned_cases": len(self.cases),
            "distinct_request_hashes": distinct,
            "request_cap": self.request_cap, "cost_cap_usd": self.cost_cap_usd,
            "cost_ceiling_usd": estimate_cost_usd(self.input_token_ceiling * max(1, self.request_cap)),
            "min_interval_seconds": self.min_interval_seconds,
            "cases": [case.to_dict() for case in self.cases],
        }


def load_registration(path: Path = DEFAULT_REGISTRATION) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_capability_plan(instances: Sequence[Any], registration: Mapping[str, Any],
                          adapter: JevChoiceAdapter) -> CapabilityPlan:
    block = registration.get("jev_capability", {})
    provider = registration.get("provider_settings", {})
    caps = registration.get("caps", {})
    cases: list[CapabilityCase] = []
    for instance in instances:
        for condition in jp.JEV_CAPABILITY_CONDITIONS:
            state = adapter.build_state(instance, "A", condition)
            cases.append(CapabilityCase(instance.instance_id, instance.seed, condition, state.question_id,
                                        tuple(option.option_id for option in state.options),
                                        instance.target, state.request_hash))
    return CapabilityPlan(model=adapter.model, endpoint=getattr(adapter.client, "endpoint", jc.JEV_SYSTEMONE_ENDPOINT),
                          protocol_key=provider.get("expected_protocol_key", ""),
                          registration_hash=str(registration.get("preregistration_hash", "")),
                          cases=tuple(cases), request_cap=int(block.get("request_cap", 0)),
                          cost_cap_usd=float(block.get("cost_cap_usd", 0.0)),
                          input_token_ceiling=int(caps.get("input_token_ceiling", 0)),
                          min_interval_seconds=float(caps.get("min_interval_seconds", 0.0)))


def verify_capability_preflight(plan: CapabilityPlan, registration: Mapping[str, Any],
                               adapter: JevChoiceAdapter, credentials: Any, *, repo_root: Path,
                               pinned_hash: str = JEV_CAPABILITY_REGISTRATION_HASH) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    provider = registration.get("provider_settings", {})
    base = jp.verify_against_jev_choice_preregistration(
        registration,
        instance_ids=[case.instance_id for case in plan.cases if case.condition == "ISO"],
        model=adapter.model, endpoint=plan.endpoint, codec_version=adapter.version,
        question_id=adapter.question_id, instructions=adapter.instructions,
        planned_requests=len(plan.cases), repo_root=repo_root)
    check("registration_verifies", base["ok"], base["errors"])
    pairs = [(case.instance_id, case.condition) for case in plan.cases]
    check("case_count", len(plan.cases) == jp.JEV_CAPABILITY_PER_CELL * len(jp.JEV_CAPABILITY_CONDITIONS),
          len(plan.cases))
    check("case_records_unique", len(pairs) == len(set(pairs)), len(pairs) - len(set(pairs)))
    check("conditions_registered", {case.condition for case in plan.cases} == set(jp.JEV_CAPABILITY_CONDITIONS),
          sorted({case.condition for case in plan.cases}))
    check("single_jev_protocol_key", jc.is_jev_protocol_key(plan.protocol_key)
          and plan.protocol_key == provider.get("expected_protocol_key"), plan.protocol_key)
    check("pinned_hash_matches_reviewed", plan.registration_hash == pinned_hash,
          {"plan": plan.registration_hash, "pinned": pinned_hash})
    check("registration_hash_matches_pinned", str(registration.get("preregistration_hash", "")) == pinned_hash,
          None)
    check("planned_within_cap", len(plan.cases) <= plan.request_cap,
          {"planned": len(plan.cases), "cap": plan.request_cap})
    check("cost_ceiling_within_cap",
          estimate_cost_usd(plan.input_token_ceiling * max(1, plan.request_cap)) <= plan.cost_cap_usd, None)
    check("credentials_present", bool(getattr(credentials, "present", False)),
          getattr(credentials, "redacted", lambda: {})())
    check("credentials_shape_ok", bool(getattr(credentials, "shape_ok", False)), None)
    check("adapter_matches_registration",
          adapter.model == provider.get("model") and plan.endpoint == provider.get("endpoint")
          and adapter.version == provider.get("codec_version") and adapter.question_id == provider.get("question_id")
          and adapter.instructions == provider.get("instructions"), None)
    return {"ok": all(item["ok"] for item in checks), "checks": checks,
            "failed": [item["check"] for item in checks if not item["ok"]],
            "credentials": getattr(credentials, "redacted", lambda: {})(),
            "registration_verification": base}


def _mean_interval(values: Sequence[float]) -> list[float] | None:
    if not values:
        return None
    mean = sum(values) / len(values)
    if len(values) < 2:
        return [round(mean, 6), round(mean, 6)]
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    half = 1.96 * math.sqrt(variance / len(values))
    return [round(max(0.0, mean - half), 6), round(min(1.0, mean + half), 6)]


def _multiclass_scores(probabilities: Mapping[str, float], options: Sequence[str],
                       target: str) -> tuple[float, float]:
    brier = sum((float(probabilities.get(option, 0.0)) - (1.0 if option == target else 0.0)) ** 2
                for option in options)
    p_target = min(max(float(probabilities.get(target, 0.0)), LOG_LOSS_FLOOR), 1 - LOG_LOSS_FLOOR)
    return brier, -math.log(p_target)


def reliability_bins(pairs: Sequence[tuple[float, bool]], bins: int = RELIABILITY_BINS) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(bins):
        low = index / bins
        high = (index + 1) / bins
        bucket = [(probability, correct) for probability, correct in pairs
                  if (low < probability <= high) or (index == 0 and probability == 0.0)]
        if not bucket:
            continue
        mean_predicted = sum(probability for probability, _ in bucket) / len(bucket)
        successes = sum(1 for _, correct in bucket if correct)
        rows.append({"bin": [round(low, 3), round(high, 3)], "count": len(bucket),
                     "mean_predicted": round(mean_predicted, 6),
                     "empirical_accuracy": round(successes / len(bucket), 6),
                     "wilson": wilson_interval(successes, len(bucket))})
    return rows


def _blocked(plan: CapabilityPlan, reason: str, approval: str | None) -> dict[str, Any]:
    return {"mode": "jev-choice-capability", "status": "blocked", "stop_reason": reason,
            "decision": "stop", "approval": approval, "registration_hash": plan.registration_hash,
            "pinned_registration_hash": JEV_CAPABILITY_REGISTRATION_HASH,
            "planned_cases": len(plan.cases), "attempted_cases": 0, "valid_cases": 0,
            "physical_attempts": 0, "max_physical_requests": plan.request_cap, "cases": [],
            "metric_definitions": dict(METRIC_DEFINITIONS),
            "raw_response_retained": False, "credentials_retained": False}


def execute_capability_probe(plan: CapabilityPlan, adapter: JevChoiceAdapter, verification: Mapping[str, Any],
                             instances: Sequence[Any], *, approval: str | None,
                             pinned_hash: str = JEV_CAPABILITY_REGISTRATION_HASH,
                             journal_path: Path | None = None,
                             sleep_fn: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Run the bounded probe. Fails closed: no call unless preflight, pin and caps pass.

    Automatic resume is disabled: a fresh run refuses an existing journal so that
    prior rows cannot be miscounted as physical requests or accepted unchecked.
    """

    if not approval:
        return _blocked(plan, "missing_approval", approval)
    if not verification.get("ok"):
        return _blocked(plan, "preflight_failed", approval)
    if plan.registration_hash != pinned_hash:
        return _blocked(plan, "registration_hash_mismatch", approval)
    if getattr(adapter.client, "max_physical_requests", None) != plan.request_cap:
        return _blocked(plan, "transport_cap_not_enforced", approval)
    if journal_path is not None and journal_path.exists():
        return _blocked(plan, "output_exists", approval)

    by_id = {instance.instance_id: instance for instance in instances}
    report: dict[str, Any] = {
        "mode": "jev-choice-capability", "status": "completed", "stop_reason": None,
        "decision": "continue", "approval": approval, "registration_hash": plan.registration_hash,
        "pinned_registration_hash": pinned_hash, "model": plan.model, "endpoint": plan.endpoint,
        "protocol_key": plan.protocol_key, "planned_cases": len(plan.cases),
        "distinct_request_hashes": len({case.request_hash for case in plan.cases}),
        "attempted_cases": 0, "valid_cases": 0,
        "by_condition": {condition: {"planned": 0, "attempted": 0, "valid": 0, "invalid": 0, "successes": 0}
                         for condition in jp.JEV_CAPABILITY_CONDITIONS},
        "physical_attempts": 0, "max_physical_requests": plan.request_cap, "input_tokens": 0,
        "output_tokens": 0, "estimated_cost_usd": 0.0,
        "cost_ceiling_usd": estimate_cost_usd(plan.input_token_ceiling * max(1, plan.request_cap)),
        "cost_cap_usd": plan.cost_cap_usd, "min_interval_seconds": plan.min_interval_seconds,
        "resolved_models": [], "invalid_classes": {}, "cases": [],
        "metric_definitions": dict(METRIC_DEFINITIONS),
        "raw_response_retained": False, "credentials_retained": False,
    }
    for case in plan.cases:
        report["by_condition"][case.condition]["planned"] += 1

    handle = None
    if journal_path is not None:
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        handle = journal_path.open("x", encoding="utf-8")

    full_planned = [case for case in plan.cases if case.condition == "FULL"]
    recorded: dict[tuple[str, str], dict[str, Any]] = {}
    selected_pairs: list[tuple[float, bool]] = []
    iso_mass: list[float] = []
    issued_this_run = 0
    try:
        for case in plan.cases:
            if report["estimated_cost_usd"] >= plan.cost_cap_usd:
                report["status"], report["stop_reason"] = "stopped", "cost_cap"
                break
            if getattr(adapter.client, "physical_attempts", 0) >= plan.request_cap:
                report["status"], report["stop_reason"] = "stopped", "request_cap"
                break
            if issued_this_run > 0 and plan.min_interval_seconds > 0:
                sleep_fn(plan.min_interval_seconds)
            instance = by_id[case.instance_id]
            state = adapter.build_state(instance, "A", case.condition)
            if state.request_hash != case.request_hash:
                report["status"], report["stop_reason"] = "stopped", "request_hash_drift"
                break
            response, _ = adapter.complete_with_raw(state)
            issued_this_run += 1
            report["attempted_cases"] += 1
            report["by_condition"][case.condition]["attempted"] += 1
            usage = dict(response.usage)
            report["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
            report["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
            report["estimated_cost_usd"] = estimate_cost_usd(report["input_tokens"])
            if response.model:
                report["resolved_models"] = sorted(set(report["resolved_models"]) | {response.model})
            accepted = bool(instance.validate(response.selected_option_id or "")["accepted"]) \
                if response.status == "complete" else False
            row = {
                "instance_id": case.instance_id, "condition": case.condition,
                "request_hash": case.request_hash, "protocol_key": plan.protocol_key,
                "question_id": case.question_id, "option_ids": list(case.option_ids),
                "target_id": case.target_id, "status": response.status,
                "error_class": response.error_class, "selected_option_id": response.selected_option_id,
                "confidence": response.confidence, "accepted": accepted,
                "probabilities": dict(response.probabilities), "resolved_model": response.model,
                "usage": usage,
            }
            report["cases"].append(row)
            recorded[(case.instance_id, case.condition)] = row
            if handle is not None:
                handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            if response.status != "complete":
                report["invalid_classes"][response.error_class] = \
                    report["invalid_classes"].get(response.error_class, 0) + 1
                report["by_condition"][case.condition]["invalid"] += 1
                report["status"], report["stop_reason"] = "stopped", response.error_class
                break
            report["valid_cases"] += 1
            report["by_condition"][case.condition]["valid"] += 1
            if accepted:
                report["by_condition"][case.condition]["successes"] += 1
            if case.condition == "FULL":
                selected_pairs.append((float(response.probabilities.get(response.selected_option_id or "", 0.0)),
                                       accepted))
            else:
                iso_mass.append(sum(float(response.probabilities.get(option, 0.0))
                                    for option in instance.private_solutions["A"]))
    finally:
        if handle is not None:
            handle.close()

    report["physical_attempts"] = int(getattr(adapter.client, "physical_attempts", 0) or 0)
    attempted = report["attempted_cases"]
    full_successes = report["by_condition"]["FULL"]["successes"]
    report["full_vector_validity"] = round(report["valid_cases"] / attempted, 6) if attempted else None
    report["task_validity_full"] = round(full_successes / jp.JEV_CAPABILITY_PER_CELL, 6)
    report["task_validity_full_denominator"] = jp.JEV_CAPABILITY_PER_CELL

    target_probabilities: list[float] = []
    briers: list[float] = []
    log_losses: list[float] = []
    for case in full_planned:
        row = recorded.get((case.instance_id, "FULL"))
        if row is None or row.get("status") != "complete":
            target_probabilities.append(0.0)
            briers.append(1.0)
            log_losses.append(-math.log(LOG_LOSS_FLOOR))
            continue
        probabilities = row.get("probabilities", {})
        brier, logloss = _multiclass_scores(probabilities, case.option_ids, case.target_id)
        target_probabilities.append(float(probabilities.get(case.target_id, 0.0)))
        briers.append(brier)
        log_losses.append(logloss)
    report["p_correct_full"] = round(sum(target_probabilities) / len(full_planned), 6)
    report["p_correct_full_interval"] = _mean_interval(target_probabilities)
    report["brier_multiclass"] = round(sum(briers) / len(full_planned), 9)
    report["log_loss_multiclass"] = round(sum(log_losses) / len(full_planned), 9)
    report["selected_answer_reliability"] = reliability_bins(selected_pairs)
    report["reliability_bins"] = report["selected_answer_reliability"]
    report["iso_mass_on_consistent_set"] = round(sum(iso_mass) / len(iso_mass), 6) if iso_mass else None

    reasons: list[str] = []
    if report["status"] == "stopped":
        reasons.append(f"stop rule fired: {report['stop_reason']}")
        report["decision"] = "stop"
    else:
        full_attempted = report["by_condition"]["FULL"]["attempted"]
        if full_attempted != jp.JEV_CAPABILITY_PER_CELL:
            reasons.append(f"FULL attempts {full_attempted} != {jp.JEV_CAPABILITY_PER_CELL}")
        if report["full_vector_validity"] != 1.0:
            reasons.append("full_vector_validity < 1.0")
        if report["task_validity_full"] < 0.9:
            reasons.append("task_validity_full < 0.9")
        report["decision"] = "stop" if reasons else "continue"
    report["go_no_go"] = {
        "decision": report["decision"], "reasons": reasons,
        "distinct_request_hashes": report["distinct_request_hashes"],
        "note": "repeated-query capability check: the 34 cases are only 12 distinct request hashes, not 17 "
                "independent prompts; a passing probe does not establish calibration and does not authorize #157",
    }
    return report


class _PreflightClient:
    provider = "jev"

    def __init__(self, *, endpoint: str = jc.JEV_SYSTEMONE_ENDPOINT,
                 max_retries: int = jp.JEV_CAPABILITY_MAX_RETRIES,
                 max_physical_requests: int | None = None) -> None:
        self.endpoint = endpoint
        self.max_retries = max_retries
        self.max_physical_requests = max_physical_requests
        self.physical_attempts = 0

    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:  # pragma: no cover - never called
        raise RuntimeError("preflight client must never issue a request")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="J3e bounded Jev Choice capability/calibration probe")
    parser.add_argument("--registration", type=Path, default=DEFAULT_REGISTRATION)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--live", action="store_true", help="issue the live probe (requires --approval)")
    parser.add_argument("--approval", help="recorded reviewer approval reference; required for --live")
    args = parser.parse_args(argv)

    registration = load_registration(args.registration)
    credentials = load_jev_credentials()
    instances = jp.jev_capability_instances()
    preflight_client = _PreflightClient(max_physical_requests=jp.JEV_CAPABILITY_REQUEST_CAP)
    adapter = JevChoiceAdapter(preflight_client, model=jp.JEV_CAPABILITY_MODEL)
    plan = build_capability_plan(instances, registration, adapter)
    verification = verify_capability_preflight(plan, registration, adapter, credentials,
                                               repo_root=Path(__file__).resolve().parents[2])
    summary = {"mode": "jev-choice-capability-preflight", "ok": verification["ok"],
               "failed": verification["failed"], "plan": plan.to_dict(),
               "credentials": verification["credentials"], "checks": verification["checks"]}
    print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))
    if not verification["ok"]:
        return 2
    if not args.live:
        return 0
    if not args.approval:
        print(json.dumps({"mode": "jev-choice-capability", "status": "blocked",
                          "stop_reason": "missing_approval"}, indent=2, sort_keys=True))
        return 2
    client = JevChoiceClient(model=jp.JEV_CAPABILITY_MODEL,
                             max_physical_requests=jp.JEV_CAPABILITY_REQUEST_CAP,
                             max_retries=jp.JEV_CAPABILITY_MAX_RETRIES)
    live_adapter = JevChoiceAdapter(client, model=jp.JEV_CAPABILITY_MODEL)
    report = execute_capability_probe(plan, live_adapter, verification, instances, approval=args.approval,
                                      journal_path=args.output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "JEV_CAPABILITY_REGISTRATION_HASH", "DEFAULT_REGISTRATION", "DEFAULT_REPORT", "DEFAULT_OUTPUT",
    "RELIABILITY_BINS", "METRIC_DEFINITIONS", "CapabilityCase", "CapabilityPlan", "load_registration",
    "build_capability_plan", "verify_capability_preflight", "reliability_bins",
    "execute_capability_probe", "main",
]
