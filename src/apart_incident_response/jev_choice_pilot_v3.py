"""#186 — successor optional-board pilot runner v3 (offline build).

Successor to the stopped v2 pilot runner. It keeps the v2 capture-then-judge
runner behavior (exact and complete_renormalized valid, partitions, cost guard,
optional silence, durable partial artifacts, fresh paths) and swaps in the
pacing writer transport :class:`~apart_incident_response.jev_ling_writer_v3.
LingWriterClientV3` for the Ling/OpenRouter path only. Jev is untouched.

The runner persists sanitized per-attempt writer rate-limit diagnostics in every
journal row that involves a writer turn, and fails closed on missing approval,
failed preflight, pinned-hash mismatch, unenforced partitions, or an existing
journal. It does not start #159.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Sequence

from . import behavioral_discovery as bd
from . import jev_choice as jc
from . import jev_choice_pilot as pilot
from . import jev_choice_v2 as jc2
from . import jev_ling_writer_v3 as writer_v3
from . import jev_replay_preregistration as pr
from . import jev_replay_preregistration_v2 as prv2
from . import jev_replay_preregistration_v3 as prv3
from .jev_choice import JevChoiceClient, load_jev_credentials
from .jev_choice_smoke import estimate_cost_usd
from . import task_families as tf


PILOT_V3_VERSION = "jev-choice-pilot-v3"
ARMS = pilot.ARMS
RECEIVER_AGENT = pilot.RECEIVER_AGENT
WRITER_AGENT = pilot.WRITER_AGENT
DEFAULT_REPORT = prv3.DEFAULT_REPORT_V3
DEFAULT_JOURNAL = prv3.DEFAULT_JOURNAL_V3
PilotCase = pilot.PilotCase
PilotPlan = pilot.PilotPlan
WriterError = pilot.WriterError
LingWriterClientV3 = writer_v3.LingWriterClientV3


def pilot_instances() -> list[tf.FamilyInstance]:
    return pilot.pilot_instances()


def build_pilot_plan(instances: Sequence[tf.FamilyInstance], registration: Mapping[str, Any],
                     receiver: jc2.JevChoiceAdapterV2) -> PilotPlan:
    cases: list[PilotCase] = []
    for instance in instances:
        pre_form = receiver.build_state(instance, RECEIVER_AGENT, "ISO")
        for arm in ARMS:
            condition = {"ISO": "ISO", "FULL": "FULL", "COMM": "COMM", "COMM_CONTROL": "COMM"}[arm]
            turns = pr.JEV_REPLAY_TURNS[condition]
            form_state = receiver.build_state(instance, RECEIVER_AGENT, condition)
            cases.append(PilotCase(instance.instance_id, instance.seed, arm, condition, turns,
                                   pre_form.request_hash,
                                   form_state.request_hash if arm in ("ISO", "FULL") else "",
                                   arm in ("COMM", "COMM_CONTROL")))
    caps = registration.get("caps", {})
    partition = caps.get("provider_partition") or {}
    ling = registration.get("ling_contract") or {}
    planned = sum(case.turns for case in cases)
    return PilotPlan(cases=tuple(cases), planned_requests=planned,
                     request_cap=int(caps.get("physical_requests", 0)),
                     jev_request_cap=int(partition.get("jev", pr.JEV_REPLAY_JEV_REQUEST_CAP)),
                     ling_request_cap=int(partition.get("ling", pr.JEV_REPLAY_LING_REQUEST_CAP)),
                     cost_cap_usd=float(caps.get("cost_cap_usd", 0.0)),
                     input_token_ceiling=int(caps.get("input_token_ceiling", 0)),
                     worst_case_call_cost_usd=estimate_cost_usd(int(caps.get("input_token_ceiling", 0))),
                     registration_hash=str(registration.get("preregistration_hash", "")),
                     protocol_key=str((registration.get("model_and_protocol") or {}).get("protocol_key", "")),
                     model=str((registration.get("model_and_protocol") or {}).get("model", "")),
                     endpoint=str((registration.get("model_and_protocol") or {}).get("endpoint", "")),
                     ling_model=str(ling.get("model", "")), ling_endpoint=str(ling.get("endpoint", "")),
                     ling_prompt_template=str(ling.get("prompt_template", "")),
                     ling_max_tokens=int(ling.get("max_tokens", 0)),
                     ling_temperature=float(ling.get("temperature", 0.0)))


def verify_pilot_preflight(plan: PilotPlan, registration: Mapping[str, Any],
                           receiver: jc2.JevChoiceAdapterV2, *, repo_root: Path,
                           pinned_hash: str | None = None,
                           ling_key_present: bool | None = None, writer: Any | None = None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    provider = registration.get("model_and_protocol", {})
    registration_result = prv3.verify_against_jev_replay_preregistration_v3(
        registration, instance_ids=list((registration.get("frozen_forms") or {}).get("instance_ids", [])),
        model=plan.model, endpoint=plan.endpoint, protocol_key=plan.protocol_key,
        planned_requests=plan.planned_requests, repo_root=repo_root)
    check("registration_verifies", registration_result["ok"], registration_result["errors"])
    if pinned_hash is not None:
        check("pinned_hash_matches", plan.registration_hash == pinned_hash,
              {"plan": plan.registration_hash, "pinned": pinned_hash})
    check("protocol_key_is_v2", jc2.is_jev_v2_protocol_key(plan.protocol_key), plan.protocol_key)
    check("protocol_key_not_v1", not jc.is_jev_protocol_key(plan.protocol_key), plan.protocol_key)
    check("normalization_policy_frozen", registration.get("normalization") == prv2.normalization_policy(),
          None)
    check("models_match", receiver.model == provider.get("model") and plan.model == provider.get("model"),
          plan.model)
    check("endpoint_matches", plan.endpoint == provider.get("endpoint"), plan.endpoint)
    client = receiver.client
    check("receiver_endpoint_matches", getattr(client, "endpoint", None) == plan.endpoint,
          getattr(client, "endpoint", None))
    check("receiver_retry_policy", getattr(client, "max_retries", None) == pr.JEV_REPLAY_MAX_RETRIES,
          getattr(client, "max_retries", None))
    check("receiver_partition_enforced", getattr(client, "max_physical_requests", None) == plan.jev_request_cap,
          getattr(client, "max_physical_requests", None))
    check("planned_within_cap", plan.planned_requests <= plan.request_cap,
          {"planned": plan.planned_requests, "cap": plan.request_cap})
    check("partition_sums_to_cap", plan.jev_request_cap + plan.ling_request_cap == plan.request_cap,
          {"jev": plan.jev_request_cap, "ling": plan.ling_request_cap, "total": plan.request_cap})
    planned_jev = sum(1 for case in plan.cases)
    planned_ling = sum(1 for case in plan.cases if case.writer_required)
    check("planned_jev_within_partition", planned_jev <= plan.jev_request_cap,
          {"planned": planned_jev, "partition": plan.jev_request_cap})
    check("planned_ling_within_partition", planned_ling <= plan.ling_request_cap,
          {"planned": planned_ling, "partition": plan.ling_request_cap})
    check("cost_ceiling_within_cap",
          estimate_cost_usd(plan.input_token_ceiling * max(1, plan.request_cap)) <= plan.cost_cap_usd,
          plan.cost_cap_usd)
    check("forms_are_six", len({case.prompt_form_id for case in plan.cases}) == 6,
          len({case.prompt_form_id for case in plan.cases}))
    credentials = load_jev_credentials()
    check("jev_credentials_present", bool(credentials.present and credentials.shape_ok),
          credentials.redacted())
    ling_ok = bd._api_key() is not None if ling_key_present is None else bool(ling_key_present)
    check("ling_credentials_present", ling_ok, None)
    ling = registration.get("ling_contract") or {}
    check("ling_model_frozen", plan.ling_model and plan.ling_model == ling.get("model") == pr.LING_MODEL,
          plan.ling_model)
    check("ling_endpoint_frozen",
          plan.ling_endpoint and plan.ling_endpoint == ling.get("endpoint") == pr.LING_ENDPOINT,
          plan.ling_endpoint)
    check("ling_prompt_frozen", plan.ling_prompt_template == ling.get("prompt_template") == pr.LING_PROMPT_TEMPLATE,
          None)
    check("ling_decoding_frozen",
          plan.ling_max_tokens == ling.get("max_tokens") and plan.ling_temperature == ling.get("temperature"),
          {"max_tokens": plan.ling_max_tokens, "temperature": plan.ling_temperature})
    transport = registration.get("writer_transport") or {}
    if writer is not None:
        check("writer_model_matches", getattr(writer, "model", None) == plan.ling_model,
              getattr(writer, "model", None))
        check("writer_endpoint_matches", getattr(writer, "endpoint", None) == plan.ling_endpoint,
              getattr(writer, "endpoint", None))
        check("writer_partition_enforced",
              getattr(writer, "max_physical_requests", None) == plan.ling_request_cap,
              getattr(writer, "max_physical_requests", None))
        check("writer_transport_version_matches",
              getattr(writer, "transport_version", None) == transport.get("writer_transport_version")
              == writer_v3.LING_WRITER_TRANSPORT_VERSION, getattr(writer, "transport_version", None))
        check("writer_min_interval_matches",
              getattr(writer, "min_attempt_interval_seconds", None)
              == transport.get("min_attempt_interval_seconds")
              == writer_v3.LING_MIN_ATTEMPT_INTERVAL_SECONDS,
              getattr(writer, "min_attempt_interval_seconds", None))
        check("writer_pacing_algorithm_matches",
              getattr(writer, "pacing_algorithm", None) == transport.get("pacing_algorithm")
              == writer_v3.LING_PACING_ALGORITHM, getattr(writer, "pacing_algorithm", None))
        check("writer_clock_is_monotonic",
              getattr(writer, "clock_name", None) == transport.get("monotonic_clock")
              == writer_v3.LING_MONOTONIC_CLOCK_NAME, getattr(writer, "clock_name", None))
        check("writer_retry_policy_matches",
              getattr(writer, "max_retries", None) == transport.get("max_retries")
              and getattr(writer, "backoff_initial_seconds", None) == transport.get("backoff_initial_seconds")
              and getattr(writer, "backoff_max_seconds", None) == transport.get("backoff_max_seconds"),
              getattr(writer, "max_retries", None))
        check("writer_retry_headers_match",
              list(getattr(writer, "supported_retry_headers", ()))
              == list(transport.get("supported_retry_headers", ()))
              == list(writer_v3.LING_SUPPORTED_RETRY_HEADERS), None)
        check("writer_max_server_delay_matches",
              getattr(writer, "max_server_requested_delay_seconds", None)
              == transport.get("max_server_requested_delay_seconds")
              == writer_v3.LING_MAX_SERVER_REQUESTED_DELAY_SECONDS, None)
    return {"ok": all(item["ok"] for item in checks), "checks": checks,
            "failed": [item["check"] for item in checks if not item["ok"]],
            "registration_verification": registration_result}


def _blocked(plan: PilotPlan, reason: str, approval: str | None) -> dict[str, Any]:
    return {"mode": "jev-choice-pilot-v3", "status": "blocked", "stop_reason": reason,
            "approval": approval, "planned_requests": plan.planned_requests, "attempted_requests": 0,
            "physical_attempts": 0, "max_physical_requests": plan.request_cap, "cases": [],
            "replay_started": False, "raw_response_retained": False, "credentials_retained": False}


def _writer_call_diagnostics(writer: Any) -> list[dict[str, Any]]:
    return list(getattr(writer, "last_call_diagnostics", []) or [])


def execute_pilot(plan: PilotPlan, receiver: jc2.JevChoiceAdapterV2, writer: Any,
                  verification: Mapping[str, Any], instances: Sequence[tf.FamilyInstance], *,
                  approval: str | None, pinned_hash: str | None = None,
                  journal_path: Path | None = None, report_path: Path | None = None,
                  sleep_fn: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Run the registered v3 schedule. Fails closed without approval, preflight or partitions."""

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
    report: dict[str, Any] = {
        "mode": "jev-choice-pilot-v3", "pilot_version": PILOT_V3_VERSION, "status": "completed",
        "stop_reason": None, "approval": approval, "registration_hash": plan.registration_hash,
        "pinned_registration_hash": pinned_hash, "protocol_key": plan.protocol_key,
        "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
        "writer_transport_version": getattr(writer, "transport_version", None),
        "writer_min_interval_seconds": getattr(writer, "min_attempt_interval_seconds", None),
        "planned_requests": plan.planned_requests, "attempted_requests": 0, "physical_attempts": 0,
        "max_physical_requests": plan.request_cap, "input_tokens": 0, "output_tokens": 0,
        "estimated_cost_usd": 0.0, "cost_cap_usd": plan.cost_cap_usd,
        "by_arm": {arm: {"attempted": 0, "valid": 0, "valid_exact": 0, "valid_renormalized": 0,
                         "invalid": 0, "real_writes": 0, "reads": 0} for arm in ARMS},
        "by_tier": {"exact": 0, "complete_renormalized": 0, "not_normalized_suspect": 0,
                    "not_normalized_hard": 0, "malformed": 0},
        "renormalized_rows": 0, "material_renormalized_rows": 0,
        "suspect_rows": 0, "hard_rows": 0,
        "by_form": {}, "resolved_models": [], "replay_started": False,
        "note": "does not start #159 replay; missing form exposure makes the pilot inconclusive",
        "cases": [], "raw_response_retained": False, "credentials_retained": False,
    }
    by_form: dict[str, dict[str, Any]] = {}

    handle = None
    if journal_path is not None:
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        handle = journal_path.open("x", encoding="utf-8")
    issued = 0

    def journal(row: dict[str, Any]) -> None:
        report["cases"].append(row)
        if handle is not None:
            handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def failure_row(case: PilotCase, instance: tf.FamilyInstance, condition: str, turns_executed: int,
                    write_status: str | None, error_class: str, writer_diagnostics: Any = None,
                    **extra: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "instance_id": case.instance_id, "arm": case.arm, "condition": condition,
            "turns_registered": case.turns, "turns_executed": turns_executed,
            "prompt_form_id": case.prompt_form_id, "request_hash": None,
            "task": {"family": instance.family, "seed": instance.seed,
                     "regime": instance.assignment.regime.value,
                     "complexity": instance.complexity.value, "agent": RECEIVER_AGENT},
            "option_ids": sorted(instance.solutions), "target_id": instance.target,
            "feasible_set": sorted(instance.private_solutions[RECEIVER_AGENT]),
            "protocol_key": plan.protocol_key, "resolved_model": None,
            "status": "invalid", "error_class": error_class, "selected_option_id": None,
            "confidence": None, "probabilities": {}, "raw_probabilities": {},
            "probability_diagnostics": None, "normalization_tier": "malformed",
            "renormalized": False, "metrics": None, "usage": {},
            "write_status": write_status, "claim": None, "message_id": None, "exposure_id": None,
            "i_m_bits": None, "board_log": [], "writer_diagnostics": list(writer_diagnostics or []),
            "eligible_exposure": False,
            "provider_attempts": {"jev": int(getattr(receiver.client, "physical_attempts", 0) or 0),
                                  "ling": int(getattr(writer, "physical_attempts", 0) or 0)},
        }
        row.update(extra)
        return row

    try:
        for case in plan.cases:
            attempts_so_far = int(getattr(receiver.client, "physical_attempts", 0) or 0) \
                + int(getattr(writer, "physical_attempts", 0) or 0)
            if (attempts_so_far + case.turns) * plan.worst_case_call_cost_usd > plan.cost_cap_usd:
                report["status"], report["stop_reason"] = "stopped", "cost_cap"
                break
            if issued > 0:
                sleep_fn(0.25)
            instance = by_id[case.instance_id]
            pre_state = receiver.build_state(instance, RECEIVER_AGENT, "ISO")
            message: str | None = None
            board_log: list[dict[str, Any]] = []
            i_m_bits: float | None = None
            write_status: str | None = None
            exposure_id: str | None = None
            turns_executed = 0
            writer_error: str | None = None
            writer_diagnostics: list[dict[str, Any]] = []
            if case.writer_required:
                turns_executed += 1
                try:
                    outcome = writer.write({"instance_id": instance.instance_id, "agent_id": WRITER_AGENT,
                                            "private_clues": list(instance.private_clues.get(WRITER_AGENT, ()))})
                    writer_diagnostics = _writer_call_diagnostics(writer)
                    if case.arm == "COMM":
                        exposure_id = f"x-{instance.instance_id}"
                        message, board_log, i_m_bits, write_status = pilot._instance_evidence(
                            instance, WRITER_AGENT, outcome.get("message"),
                            f"m-{instance.instance_id}", exposure_id)
                    else:
                        write_status = "control_no_write"
                except WriterError as exc:
                    writer_error = exc.error_class
                    write_status = "writer_error"
                    writer_diagnostics = _writer_call_diagnostics(writer)
                except Exception as exc:
                    writer_error = f"writer_{type(exc).__name__}"
                    write_status = "writer_error"
                    writer_diagnostics = _writer_call_diagnostics(writer)
            visible = [{"text": pilot.jc_message(message)}] if message else []
            condition = case.condition
            state = receiver.build_state(instance, RECEIVER_AGENT, condition, visible_messages=visible)
            if case.arm in ("ISO", "FULL") and state.request_hash != case.request_hash:
                report["status"], report["stop_reason"] = "stopped", "request_hash_drift"
                break
            if writer_error is not None:
                journal(failure_row(case, instance, condition, turns_executed, write_status, writer_error,
                                    writer_diagnostics=writer_diagnostics))
                report["by_arm"][case.arm]["attempted"] += 1
                report["by_arm"][case.arm]["invalid"] += 1
                report["status"], report["stop_reason"] = "stopped", writer_error
                break
            try:
                response, _ = receiver.complete_with_raw(state)
            except Exception as exc:
                error_class = f"jev_{type(exc).__name__}"
                journal(failure_row(case, instance, condition, turns_executed, write_status, error_class,
                                    writer_diagnostics=writer_diagnostics,
                                    claim=message, message_id=f"m-{instance.instance_id}" if message else None,
                                    exposure_id=exposure_id, i_m_bits=i_m_bits, board_log=board_log,
                                    eligible_exposure=bool(write_status == "real")))
                report["by_arm"][case.arm]["attempted"] += 1
                report["by_arm"][case.arm]["invalid"] += 1
                report["status"], report["stop_reason"] = "stopped", error_class
                break
            turns_executed += 1
            issued += 1
            report["attempted_requests"] += 1
            report["by_arm"][case.arm]["attempted"] += 1
            usage = dict(response.usage)
            report["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
            report["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
            report["estimated_cost_usd"] = estimate_cost_usd(report["input_tokens"])
            if response.model:
                report["resolved_models"] = sorted(set(report["resolved_models"]) | {response.model})
            valid = response.status == "complete"
            tier = response.normalization_tier
            report["by_tier"][tier] = report["by_tier"].get(tier, 0) + 1
            arm_row = report["by_arm"][case.arm]
            if valid:
                arm_row["valid"] += 1
                if response.renormalized:
                    report["renormalized_rows"] += 1
                if tier == "exact":
                    arm_row["valid_exact"] += 1
                elif tier == "complete_renormalized":
                    arm_row["valid_renormalized"] += 1
                    report["material_renormalized_rows"] += 1
            else:
                arm_row["invalid"] += 1
                if tier == "not_normalized_suspect":
                    report["suspect_rows"] += 1
                elif tier == "not_normalized_hard":
                    report["hard_rows"] += 1
            if write_status == "real":
                arm_row["real_writes"] += 1
                arm_row["reads"] += 1
            feasible = sorted(instance.private_solutions[RECEIVER_AGENT])
            metrics = jc2.distribution_metrics(response.probabilities, target_id=instance.target,
                                               feasible_set=feasible) if valid else None
            row = {
                "instance_id": case.instance_id, "arm": case.arm, "condition": condition,
                "turns_registered": case.turns, "turns_executed": turns_executed,
                "prompt_form_id": case.prompt_form_id, "request_hash": state.request_hash,
                "task": {"family": instance.family, "seed": instance.seed,
                         "regime": instance.assignment.regime.value,
                         "complexity": instance.complexity.value, "agent": RECEIVER_AGENT},
                "pre_read_state": dict(pre_state.state), "option_ids": sorted(instance.solutions),
                "target_id": instance.target, "feasible_set": feasible,
                "protocol_key": plan.protocol_key, "resolved_model": response.model,
                "status": response.status, "error_class": response.error_class,
                "normalization_tier": tier, "renormalized": response.renormalized,
                "selected_option_id": response.selected_option_id, "confidence": response.confidence,
                "probabilities": dict(response.probabilities),
                "raw_probabilities": dict(response.raw_probabilities),
                "probability_diagnostics": (response.diagnostics.to_dict()
                                             if response.diagnostics is not None else None),
                "metrics": metrics, "usage": usage,
                "write_status": write_status, "claim": message,
                "message_id": f"m-{instance.instance_id}" if message else None,
                "exposure_id": exposure_id, "i_m_bits": i_m_bits, "board_log": board_log,
                "writer_diagnostics": writer_diagnostics,
                "eligible_exposure": bool(write_status == "real"),
            }
            journal(row)
            form = by_form.setdefault(case.prompt_form_id,
                                      {"real_writes": 0, "reads": 0, "valid": 0, "eligible_exposure": False})
            form["valid"] += int(valid)
            if write_status == "real":
                form["real_writes"] += 1
                form["reads"] += 1
                form["eligible_exposure"] = True
            if not valid:
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
        "combined": int(getattr(receiver.client, "physical_attempts", 0) or 0)
        + int(getattr(writer, "physical_attempts", 0) or 0),
        "jev_partition": plan.jev_request_cap, "ling_partition": plan.ling_request_cap}
    writer_records = list(getattr(writer, "rate_limit_records", []) or [])
    report["writer_rate_limit"] = {
        "physical_attempts": len(writer_records),
        "logical_calls": int(getattr(writer, "logical_calls", 0) or 0),
        "attempts_with_retry_header": sum(
            1 for record in writer_records
            if record.get("retry_after_present") or record.get("retry_after_ms_present")),
        "max_applied_delay_seconds": (max(record.get("delay_seconds", 0.0) or 0.0
                                          for record in writer_records) if writer_records else 0.0),
        "min_interval_seconds": getattr(writer, "min_attempt_interval_seconds", None),
        "transport_version": getattr(writer, "transport_version", None),
    }
    report["by_form"] = dict(sorted(by_form.items()))
    missing = [form for form in {case.prompt_form_id for case in plan.cases}
               if not by_form.get(form, {}).get("eligible_exposure")]
    report["forms_with_eligible_exposure"] = sum(1 for form in by_form.values() if form["eligible_exposure"])
    report["forms_missing_exposure"] = sorted(missing)
    if report["status"] == "completed" and missing:
        report["status"] = "inconclusive"
        report["stop_reason"] = "missing_verified_exposure"
    report["replay_ready"] = not missing and report["status"] == "completed"
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="#186 optional-board Ling-writer/Jev-receiver pilot v3")
    parser.add_argument("--registration", type=Path, default=prv3.DEFAULT_OUTPUT_V3)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    parser.add_argument("--live", action="store_true", help="run live (requires --approval)")
    parser.add_argument("--approval", help="recorded reviewer approval reference; required for --live")
    args = parser.parse_args(argv)
    registration = json.loads(args.registration.read_text(encoding="utf-8"))
    instances = pilot_instances()
    receiver = jc2.JevChoiceAdapterV2(
        JevChoiceClient(model=pr.JEV_REPLAY_MODEL, max_physical_requests=pr.JEV_REPLAY_JEV_REQUEST_CAP),
        model=pr.JEV_REPLAY_MODEL)
    plan = build_pilot_plan(instances, registration, receiver)
    writer = LingWriterClientV3(max_physical_requests=plan.ling_request_cap)
    verification = verify_pilot_preflight(plan, registration, receiver,
                                          repo_root=Path(__file__).resolve().parents[2],
                                          pinned_hash=registration.get("preregistration_hash"),
                                          writer=writer)
    print(json.dumps({"mode": "jev-choice-pilot-v3-preflight", "ok": verification["ok"],
                      "failed": verification["failed"], "plan": plan.to_dict(),
                      "checks": verification["checks"]}, indent=2, sort_keys=True, allow_nan=False))
    if not verification["ok"]:
        return 2
    if not args.live:
        return 0
    if not args.approval:
        print(json.dumps({"mode": "jev-choice-pilot-v3", "status": "blocked",
                          "stop_reason": "missing_approval"}, indent=2, sort_keys=True))
        return 2
    report = execute_pilot(plan, receiver, writer, verification, instances, approval=args.approval,
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
    "PILOT_V3_VERSION", "ARMS", "DEFAULT_REPORT", "DEFAULT_JOURNAL", "pilot_instances",
    "build_pilot_plan", "verify_pilot_preflight", "execute_pilot", "main",
]
