"""#187 (repaired) — gated planning-low writer-ladder runner v5 (offline build).

Fixes the v4 contract breaks: writer-invalid outcomes never call Jev and never
count as receiver-valid; the registered stop rule is applied before Jev; L5 has
an enforced positive-control gate; and planned/attempted/valid denominators,
provider calls, tokens and cost are reported separately by rung and arm.
``L4X`` is the exact original COMM bridge and is executed by
:mod:`apart_incident_response.jev_writer_exact_bridge_v5`, not here.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Sequence

from . import behavioral_discovery as bd
from . import jev_choice as jc
from . import jev_choice_pilot as pilot
from . import jev_choice_v2 as jc2
from . import jev_ling_writer_v3 as writer_v3
from . import jev_ling_writer_v5 as writer_v5
from . import jev_replay_preregistration as pr
from . import jev_writer_ladder_preregistration_v5 as prv5
from . import jev_writer_ladder_v5 as ladder
from .jev_choice_smoke import estimate_cost_usd


LADDER_PILOT_VERSION = "planning-low-writer-ladder-pilot-v5"
RECEIVER_AGENT = "A"
WRITER_AGENT = "B"
DEFAULT_REPORT = prv5.DEFAULT_REPORT_V5
DEFAULT_JOURNAL = prv5.DEFAULT_JOURNAL_V5

#: Writer outcomes registered as stop conditions before any Jev call.
STOP_WRITER_OUTCOMES = frozenset({
    writer_v5.OUTCOME_EMPTY_OUTPUT,
    writer_v5.OUTCOME_TRUNCATED_OUTPUT,
    writer_v5.OUTCOME_UNPARSED_OUTPUT,
    writer_v5.OUTCOME_INVALID_ANSWER,
    writer_v5.OUTCOME_WRITER_ERROR,
})


def ladder_instances() -> list[Any]:
    return pilot.pilot_instances()


def _live_rungs() -> list[ladder.LadderRung]:
    return [rung for rung in ladder.LADDER_RUNGS if not rung.bridge]


@dataclass(frozen=True)
class LadderCase:
    instance_id: str
    seed: int
    rung_id: str
    arm: str
    condition: str
    prompt_form_id: str
    induced: bool


@dataclass(frozen=True)
class LadderPlan:
    cases: tuple[LadderCase, ...]
    planned_cases: int
    planned_provider_calls: int
    request_cap: int
    jev_request_cap: int
    ling_request_cap: int
    cost_cap_usd: float
    input_token_ceiling: int
    worst_case_call_cost_usd: float
    registration_hash: str
    protocol_key: str
    model: str
    endpoint: str
    ling_model: str
    ling_endpoint: str
    writer_transport_version: str
    writer_min_interval: float

    def to_dict(self) -> dict[str, Any]:
        return {"planned_cases": self.planned_cases, "planned_provider_calls": self.planned_provider_calls,
                "request_cap": self.request_cap, "jev_request_cap": self.jev_request_cap,
                "ling_request_cap": self.ling_request_cap, "cost_cap_usd": self.cost_cap_usd,
                "registration_hash": self.registration_hash, "protocol_key": self.protocol_key,
                "model": self.model, "endpoint": self.endpoint, "ling_model": self.ling_model,
                "ling_endpoint": self.ling_endpoint, "writer_transport_version": self.writer_transport_version,
                "writer_min_interval": self.writer_min_interval}


def build_ladder_plan(instances: Sequence[Any], registration: Mapping[str, Any],
                      receiver: jc2.JevChoiceAdapterV2) -> LadderPlan:
    rungs = _live_rungs()
    cases: list[LadderCase] = []
    for rung in rungs:
        for instance in instances:
            form = receiver.build_state(instance, RECEIVER_AGENT, "ISO").request_hash
            for arm in ("COMM", "COMM_CONTROL"):
                cases.append(LadderCase(instance.instance_id, instance.seed, rung.rung_id, arm,
                                        "COMM", form, rung.induced))
    caps = registration.get("caps", {})
    partition = caps.get("provider_partition") or {}
    ling = registration.get("ling_contract") or {}
    transport = registration.get("writer_transport") or {}
    return LadderPlan(cases=tuple(cases), planned_cases=len(cases),
                      planned_provider_calls=2 * len(cases),
                      request_cap=int(caps.get("physical_requests", 0)),
                      jev_request_cap=int(partition.get("jev", 0)),
                      ling_request_cap=int(partition.get("ling", 0)),
                      cost_cap_usd=float(caps.get("cost_cap_usd", 0.0)),
                      input_token_ceiling=int(caps.get("input_token_ceiling", 0)),
                      worst_case_call_cost_usd=estimate_cost_usd(int(caps.get("input_token_ceiling", 0))),
                      registration_hash=str(registration.get("preregistration_hash", "")),
                      protocol_key=str((registration.get("model_and_protocol") or {}).get("protocol_key", "")),
                      model=str((registration.get("model_and_protocol") or {}).get("model", "")),
                      endpoint=str((registration.get("model_and_protocol") or {}).get("endpoint", "")),
                      ling_model=str(ling.get("model", "")), ling_endpoint=str(ling.get("endpoint", "")),
                      writer_transport_version=str(transport.get("writer_transport_version", "")),
                      writer_min_interval=float(transport.get("min_attempt_interval_seconds", 0.0)))


def verify_ladder_preflight(plan: LadderPlan, registration: Mapping[str, Any],
                            receiver: jc2.JevChoiceAdapterV2, writer: Any, *, repo_root: Path,
                            pinned_hash: str | None = None,
                            ling_key_present: bool | None = None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    result = prv5.verify_against_writer_ladder_preregistration_v5(
        registration, instance_ids=list((registration.get("manifest") or {}).get("instance_ids", [])),
        model=plan.model, endpoint=plan.endpoint, protocol_key=plan.protocol_key,
        planned_requests=plan.planned_provider_calls, repo_root=repo_root)
    check("registration_verifies", result["ok"], result["errors"])
    if pinned_hash is not None:
        check("pinned_hash_matches", plan.registration_hash == pinned_hash, plan.registration_hash)
    check("protocol_key_is_v2", jc2.is_jev_v2_protocol_key(plan.protocol_key), plan.protocol_key)
    check("protocol_key_not_v1", not jc.is_jev_protocol_key(plan.protocol_key), plan.protocol_key)
    check("ladder_hash_matches",
          registration.get("generator", {}).get("ladder_hash") == ladder.ladder_hash(), None)
    check("writer_schema_hash_matches",
          registration.get("generator", {}).get("writer_schema_hash") == writer_v5.writer_schema_hash(), None)
    check("writer_outcomes_version_matches",
          registration.get("writer_observability", {}).get("writer_outcomes_version")
          == writer_v5.WRITER_OUTCOMES_VERSION, None)
    check("l5_gate_frozen",
          registration.get("writer_ladder", {}).get("l5_required_owned_fraction")
          == ladder.L5_REQUIRED_OWNED_FRACTION, None)
    check("models_match", receiver.model == plan.model, plan.model)
    client = receiver.client
    check("receiver_endpoint_matches", getattr(client, "endpoint", None) == plan.endpoint, None)
    check("receiver_retry_policy", getattr(client, "max_retries", None) == pr.JEV_REPLAY_MAX_RETRIES, None)
    check("receiver_partition_enforced",
          getattr(client, "max_physical_requests", None) == plan.jev_request_cap,
          getattr(client, "max_physical_requests", None))
    check("writer_model_matches", getattr(writer, "model", None) == plan.ling_model, getattr(writer, "model", None))
    check("writer_endpoint_matches", getattr(writer, "endpoint", None) == plan.ling_endpoint, None)
    check("writer_partition_enforced",
          getattr(writer, "max_physical_requests", None) == plan.ling_request_cap,
          getattr(writer, "max_physical_requests", None))
    check("writer_transport_version_matches",
          getattr(writer, "transport_version", None) == plan.writer_transport_version
          == writer_v3.LING_WRITER_TRANSPORT_VERSION, None)
    check("writer_min_interval_matches",
          getattr(writer, "min_attempt_interval_seconds", None) == plan.writer_min_interval
          == writer_v3.LING_MIN_ATTEMPT_INTERVAL_SECONDS, None)
    check("writer_pacing_algorithm_matches",
          getattr(writer, "pacing_algorithm", None) == writer_v3.LING_PACING_ALGORITHM, None)
    check("writer_clock_is_monotonic",
          getattr(writer, "clock_name", None) == writer_v3.LING_MONOTONIC_CLOCK_NAME, None)
    check("writer_outcomes_version", getattr(writer, "writer_outcomes_version", None)
          == writer_v5.WRITER_OUTCOMES_VERSION, None)
    check("partition_sums_to_cap", plan.jev_request_cap + plan.ling_request_cap == plan.request_cap, None)
    check("planned_jev_within_partition", plan.planned_cases <= plan.jev_request_cap, plan.planned_cases)
    check("planned_ling_within_partition", plan.planned_cases <= plan.ling_request_cap, plan.planned_cases)
    check("planned_within_cap", plan.planned_provider_calls <= plan.request_cap, plan.planned_provider_calls)
    check("cost_ceiling_within_cap",
          estimate_cost_usd(plan.input_token_ceiling * max(1, plan.request_cap)) <= plan.cost_cap_usd, None)
    check("forms_are_six", len({case.prompt_form_id for case in plan.cases}) == 6, None)
    check("live_rungs_are_six", len({case.rung_id for case in plan.cases}) == 6, None)
    credentials = __import__("apart_incident_response.jev_choice", fromlist=["load_jev_credentials"]
                             ).load_jev_credentials()
    check("jev_credentials_present", bool(credentials.present and credentials.shape_ok), credentials.redacted())
    ling_ok = bd._api_key() is not None if ling_key_present is None else bool(ling_key_present)
    check("ling_credentials_present", ling_ok, None)
    return {"ok": all(item["ok"] for item in checks), "checks": checks,
            "failed": [item["check"] for item in checks if not item["ok"]],
            "registration_verification": result}


def _empty_rung(rung: ladder.LadderRung, planned_cases: int) -> dict[str, Any]:
    return {
        "rung_id": rung.rung_id, "bridge": rung.bridge, "induced": rung.induced,
        "planned_cases": planned_cases, "planned_provider_calls": planned_cases * 2,
        "attempted_cases": 0, "writer_valid": 0, "writer_invalid": 0,
        "receiver_valid": 0, "receiver_invalid": 0, "receiver_unattempted": 0, "joint_valid": 0,
        "writer_outcomes": {"COMM": {outcome: 0 for outcome in writer_v5.WRITER_OUTCOMES},
                            "COMM_CONTROL": {outcome: 0 for outcome in writer_v5.WRITER_OUTCOMES}},
        "exact_owned_accepted_writes": 0, "rejected_claims": 0, "verified_read_exposures": 0,
        "authoritative_i_m": 0, "i_m_bits": 0.0, "distinct_forms": set(),
        "ling_input_tokens": 0, "ling_output_tokens": 0,
        "jev_input_tokens": 0, "jev_output_tokens": 0, "estimated_cost_usd": 0.0,
        "missingness": 0,
    }


def _blocked(plan: LadderPlan, reason: str, approval: str | None) -> dict[str, Any]:
    return {"mode": LADDER_PILOT_VERSION, "status": "blocked", "stop_reason": reason,
            "approval": approval, "planned_cases": plan.planned_cases,
            "planned_provider_calls": plan.planned_provider_calls, "cases": [],
            "physical_attempts": 0, "replay_started": False}


def execute_ladder(plan: LadderPlan, receiver: jc2.JevChoiceAdapterV2, writer: Any,
                   verification: Mapping[str, Any], instances: Sequence[Any], *,
                   approval: str | None, pinned_hash: str | None = None,
                   journal_path: Path | None = None, report_path: Path | None = None,
                   sleep_fn: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    if not approval:
        return _blocked(plan, "missing_approval", approval)
    if not verification.get("ok"):
        return _blocked(plan, "preflight_failed", approval)
    if pinned_hash is not None and plan.registration_hash != pinned_hash:
        return _blocked(plan, "registration_hash_mismatch", approval)
    if plan.jev_request_cap + plan.ling_request_cap != plan.request_cap:
        return _blocked(plan, "partition_mismatch", approval)
    if getattr(receiver.client, "max_physical_requests", None) != plan.jev_request_cap:
        return _blocked(plan, "receiver_partition_not_enforced", approval)
    if getattr(writer, "max_physical_requests", None) != plan.ling_request_cap:
        return _blocked(plan, "writer_partition_not_enforced", approval)
    if journal_path is not None and journal_path.exists():
        return _blocked(plan, "output_exists", approval)
    if report_path is not None and report_path.exists():
        return _blocked(plan, "report_exists", approval)

    by_id = {instance.instance_id: instance for instance in instances}
    per_rung_cases = plan.planned_cases // max(1, len(_live_rungs()))
    report: dict[str, Any] = {
        "mode": LADDER_PILOT_VERSION, "pilot_version": LADDER_PILOT_VERSION, "status": "completed",
        "stop_reason": None, "approval": approval, "registration_hash": plan.registration_hash,
        "pinned_registration_hash": pinned_hash, "protocol_key": plan.protocol_key,
        "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
        "writer_outcomes_version": writer_v5.WRITER_OUTCOMES_VERSION,
        "writer_transport_version": plan.writer_transport_version,
        "writer_min_interval_seconds": plan.writer_min_interval,
        "ladder_version": ladder.LADDER_VERSION, "ladder_hash": ladder.ladder_hash(),
        "planned_cases": plan.planned_cases, "planned_provider_calls": plan.planned_provider_calls,
        "attempted_cases": 0, "physical_attempts": 0, "max_physical_requests": plan.request_cap,
        "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0,
        "cost_cap_usd": plan.cost_cap_usd,
        "by_rung": {rung.rung_id: _empty_rung(rung, per_rung_cases) for rung in _live_rungs()},
        "by_tier": {"exact": 0, "complete_renormalized": 0, "not_normalized_suspect": 0,
                    "not_normalized_hard": 0, "malformed": 0},
        "resolved_models": [], "replay_started": False, "replay_ready": False,
        "l5_gate_passed": None, "voluntary_interpretation_emitted": False,
        "interpretation": {},
        "interpretation_rules": dict(ladder.INTERPRETATION_RULES),
        "note": "does not start #159; emission is not causal uptake; L5 INDUCED excluded from voluntary inference",
        "cases": [], "raw_response_retained": False, "credentials_retained": False,
    }
    handle = None
    if journal_path is not None:
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        handle = journal_path.open("x", encoding="utf-8")

    def journal(row: dict[str, Any]) -> None:
        report["cases"].append(row)
        if handle is not None:
            handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    try:
        for case in plan.cases:
            attempts = int(getattr(receiver.client, "physical_attempts", 0) or 0) \
                + int(getattr(writer, "physical_attempts", 0) or 0)
            if (attempts + 2) * plan.worst_case_call_cost_usd > plan.cost_cap_usd:
                report["status"], report["stop_reason"] = "stopped", "cost_cap"
                break
            if report["attempted_cases"] > 0:
                sleep_fn(0.25)
            instance = by_id[case.instance_id]
            rung_row = report["by_rung"][case.rung_id]
            rung_row["attempted_cases"] += 1
            report["attempted_cases"] += 1
            context = ladder.ladder_context(instance, condition=case.condition, turn=1,
                                            agent=WRITER_AGENT, role="writer")
            prompt = ladder.ladder_prompt(case.rung_id, context)
            outcome = writer.write_outcome({**context, "prompt": prompt["prompt"],
                                            "grammar": prompt["grammar"]})
            kind = outcome["outcome"]
            rung_row["writer_outcomes"][case.arm][kind] = \
                rung_row["writer_outcomes"][case.arm].get(kind, 0) + 1
            rung_row["ling_input_tokens"] += int(outcome.get("input_tokens") or 0)
            rung_row["ling_output_tokens"] += int(outcome.get("output_tokens") or 0)

            message: str | None = None
            board_log: list[dict[str, Any]] = []
            i_m_bits: float | None = None
            write_status: str | None = None
            exposure_id: str | None = None
            writer_valid = kind in (writer_v5.OUTCOME_DELIBERATE_SILENCE,
                                    writer_v5.OUTCOME_MESSAGE_CANDIDATE)
            if kind == writer_v5.OUTCOME_MESSAGE_CANDIDATE:
                claim = str(outcome["claim"])
                if not instance.holds_claim(WRITER_AGENT, claim):
                    writer_valid = False
                    write_status = "rejected"
                    rung_row["rejected_claims"] += 1
                    kind = writer_v5.OUTCOME_NON_OWNED_CLAIM
                elif case.arm == "COMM":
                    exposure_id = f"x-{instance.instance_id}-{case.rung_id}"
                    message, board_log, i_m_bits, write_status = pilot._instance_evidence(
                        instance, WRITER_AGENT, claim,
                        f"m-{instance.instance_id}-{case.rung_id}", exposure_id)
                    rung_row["exact_owned_accepted_writes"] += 1
                else:
                    write_status = "control_no_write"
                    rung_row["exact_owned_accepted_writes"] += 1  # owned completion on the control turn
            elif kind == writer_v5.OUTCOME_NON_OWNED_CLAIM:
                writer_valid = False
                write_status = "rejected"
                rung_row["rejected_claims"] += 1
            elif kind == writer_v5.OUTCOME_DELIBERATE_SILENCE:
                write_status = "silent" if case.arm == "COMM" else "control_no_write"

            if not writer_valid:
                rung_row["writer_invalid"] += 1
                rung_row["receiver_unattempted"] += 1
                rung_row["missingness"] += 1
                reason = kind if kind != writer_v5.OUTCOME_WRITER_ERROR \
                    else str(outcome.get("error_class") or kind)
                journal({
                    "instance_id": case.instance_id, "rung_id": case.rung_id, "arm": case.arm,
                    "condition": case.condition, "induced": case.induced, "voluntary": not case.induced,
                    "prompt_form_id": case.prompt_form_id, "status": "invalid",
                    "writer_outcome": kind, "error_class": reason, "receiver_attempted": False,
                    "receiver_status": None, "write_status": write_status,
                    "writer_outcome_diagnostics": _diagnostics(outcome),
                    "eligible_exposure": False, "board_log": [],
                })
                if kind in STOP_WRITER_OUTCOMES:
                    report["status"], report["stop_reason"] = "stopped", reason
                    break
                continue

            rung_row["writer_valid"] += 1
            visible = [{"text": pilot.jc_message(message)}] if message else []
            state = receiver.build_state(instance, RECEIVER_AGENT, case.condition, visible_messages=visible)
            try:
                response, _ = receiver.complete_with_raw(state)
            except Exception as exc:
                report["status"], report["stop_reason"] = "stopped", f"jev_{type(exc).__name__}"
                break
            usage = dict(response.usage)
            report["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
            report["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
            report["estimated_cost_usd"] = estimate_cost_usd(report["input_tokens"])
            rung_row["jev_input_tokens"] += int(usage.get("input_tokens", 0) or 0)
            rung_row["jev_output_tokens"] += int(usage.get("output_tokens", 0) or 0)
            rung_row["estimated_cost_usd"] = estimate_cost_usd(rung_row["jev_input_tokens"])
            if response.model:
                report["resolved_models"] = sorted(set(report["resolved_models"]) | {response.model})
            tier = response.normalization_tier
            report["by_tier"][tier] = report["by_tier"].get(tier, 0) + 1
            receiver_valid = response.status == "complete"
            if receiver_valid:
                rung_row["receiver_valid"] += 1
                rung_row["joint_valid"] += 1
            else:
                rung_row["receiver_invalid"] += 1
                rung_row["missingness"] += 1
            if write_status == "real":
                rung_row["verified_read_exposures"] += 1
            if i_m_bits is not None:
                rung_row["authoritative_i_m"] += 1
                rung_row["i_m_bits"] = round(rung_row["i_m_bits"] + float(i_m_bits), 9)
            rung_row["distinct_forms"].add(case.prompt_form_id)
            journal({
                "instance_id": case.instance_id, "rung_id": case.rung_id, "arm": case.arm,
                "condition": case.condition, "induced": case.induced, "voluntary": not case.induced,
                "prompt_form_id": case.prompt_form_id, "request_hash": state.request_hash,
                "status": response.status, "error_class": response.error_class,
                "normalization_tier": tier, "renormalized": response.renormalized,
                "probabilities": dict(response.probabilities),
                "raw_probabilities": dict(response.raw_probabilities),
                "probability_diagnostics": (response.diagnostics.to_dict()
                                             if response.diagnostics is not None else None),
                "selected_option_id": response.selected_option_id, "confidence": response.confidence,
                "usage": usage, "write_status": write_status, "writer_outcome": kind,
                "writer_outcome_diagnostics": _diagnostics(outcome),
                "claim": message, "message_id": f"m-{instance.instance_id}-{case.rung_id}" if message else None,
                "exposure_id": exposure_id, "i_m_bits": i_m_bits, "board_log": board_log,
                "eligible_exposure": bool(write_status == "real"), "receiver_attempted": True,
                "receiver_status": response.status,
            })
            if not receiver_valid:
                report["status"], report["stop_reason"] = "stopped", response.error_class
                break
    finally:
        if handle is not None:
            handle.close()

    report["physical_attempts"] = int(getattr(receiver.client, "physical_attempts", 0) or 0) \
        + int(getattr(writer, "physical_attempts", 0) or 0)
    report["provider_attempts"] = {
        "jev": int(getattr(receiver.client, "physical_attempts", 0) or 0),
        "ling": int(getattr(writer, "physical_attempts", 0) or 0),
        "combined": report["physical_attempts"],
        "jev_partition": plan.jev_request_cap, "ling_partition": plan.ling_request_cap}
    for rung_row in report["by_rung"].values():
        rung_row["distinct_forms"] = len(rung_row["distinct_forms"])
    report["forms_with_eligible_exposure"] = sum(
        1 for rung_row in report["by_rung"].values() if rung_row["verified_read_exposures"] > 0)
    report["replay_ready"] = False
    report = _apply_l5_gate(report)
    return report


def _diagnostics(outcome: Mapping[str, Any]) -> dict[str, Any]:
    return {"finish_reason": outcome.get("finish_reason"), "answer": outcome.get("answer"),
            "content_length": outcome.get("content_length"), "input_tokens": outcome.get("input_tokens"),
            "output_tokens": outcome.get("output_tokens"), "completion_tokens": outcome.get("completion_tokens"),
            "parser_classification": outcome.get("parser_classification"),
            "max_tokens": outcome.get("max_tokens"), "seed_sent": outcome.get("seed_sent"),
            "physical_attempts": outcome.get("physical_attempts"),
            "delay_diagnostics": outcome.get("diagnostics"), "raw_response_retained": False}


def _apply_l5_gate(report: dict[str, Any]) -> dict[str, Any]:
    rung = report["by_rung"].get("L5")
    if rung is None:
        report["l5_gate_passed"] = False
        report["status"], report["stop_reason"] = "inconclusive", "l5_gate_failed"
        return report
    outcomes = rung["writer_outcomes"]
    owned = outcomes["COMM"].get(writer_v5.OUTCOME_MESSAGE_CANDIDATE, 0) \
        + outcomes["COMM_CONTROL"].get(writer_v5.OUTCOME_MESSAGE_CANDIDATE, 0)
    total = rung["attempted_cases"]
    fraction = (owned / total) if total else 0.0
    passed = total > 0 and fraction >= ladder.L5_REQUIRED_OWNED_FRACTION
    report["l5_gate"] = {"owned": owned, "total": total, "fraction": fraction,
                         "required": ladder.L5_REQUIRED_OWNED_FRACTION, "passed": passed}
    report["l5_gate_passed"] = passed
    if report["status"] == "completed" and not passed:
        report["status"], report["stop_reason"] = "inconclusive", "l5_gate_failed"
    if report["status"] == "completed":
        comm_writes = {rid: row["exact_owned_accepted_writes"] for rid, row in report["by_rung"].items()}
        voluntary_silent = all(
            row["writer_outcomes"]["COMM"].get(writer_v5.OUTCOME_MESSAGE_CANDIDATE, 0) == 0
            for rid, row in report["by_rung"].items()
            if rid not in ("L5",))
        l0_writes = report["by_rung"].get("L0", {}).get("exact_owned_accepted_writes", 0)
        l4_writes = report["by_rung"].get("L4", {}).get("exact_owned_accepted_writes", 0)
        report["interpretation"] = {
            "voluntary_comm_writes_by_rung": comm_writes,
            "voluntary_all_silence": voluntary_silent,
            "l4_or_l5_writes_while_l0_silent": (l4_writes > 0 or owned > 0) and l0_writes == 0,
            "no_post_hoc_selection": True,
            "emission_is_not_causal_uptake": True,
        }
        report["voluntary_interpretation_emitted"] = True
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="#187 planning-low writer-ladder pilot v5")
    parser.add_argument("--registration", type=Path, default=prv5.DEFAULT_OUTPUT_V5)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--approval")
    args = parser.parse_args(argv)
    registration = json.loads(args.registration.read_text(encoding="utf-8"))
    instances = ladder_instances()
    receiver = jc2.JevChoiceAdapterV2(
        jc.JevChoiceClient(model=pr.JEV_REPLAY_MODEL, max_physical_requests=prv5.JEV_LADDER_REQUEST_CAP),
        model=pr.JEV_REPLAY_MODEL)
    plan = build_ladder_plan(instances, registration, receiver)
    writer = writer_v5.LingWriterClientV5(max_physical_requests=prv5.LING_LADDER_REQUEST_CAP)
    verification = verify_ladder_preflight(plan, registration, receiver, writer,
                                           repo_root=Path(__file__).resolve().parents[2],
                                           pinned_hash=registration.get("preregistration_hash"))
    print(json.dumps({"mode": f"{LADDER_PILOT_VERSION}-preflight", "ok": verification["ok"],
                      "failed": verification["failed"], "plan": plan.to_dict(),
                      "checks": verification["checks"]}, indent=2, sort_keys=True, allow_nan=False))
    if not verification["ok"]:
        return 2
    if not args.live:
        return 0
    if not args.approval:
        print(json.dumps({"mode": LADDER_PILOT_VERSION, "status": "blocked",
                          "stop_reason": "missing_approval"}, indent=2, sort_keys=True))
        return 2
    report = execute_ladder(plan, receiver, writer, verification, instances, approval=args.approval,
                            pinned_hash=registration.get("preregistration_hash"),
                            journal_path=args.journal, report_path=args.report)
    if report.get("status") != "blocked":
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                               encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "LADDER_PILOT_VERSION", "STOP_WRITER_OUTCOMES", "LadderCase", "LadderPlan", "ladder_instances",
    "build_ladder_plan", "verify_ladder_preflight", "execute_ladder", "main",
]
