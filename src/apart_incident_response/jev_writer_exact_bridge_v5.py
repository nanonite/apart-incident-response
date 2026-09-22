"""#187 — exact original COMM bridge v5 (offline build, repaired).

Reproduces the original Ling COMM treatment through the **original code path**
(:class:`communication_runner.AgentContext` -> ``behavioral_discovery.treatment_prompt``
-> ``json.dumps(sort_keys=True)``): two agents (A, B) across the two registered
turns, original agent ordering, ``is_finalizer``/``finalizing_agent``, the
deterministic provider seed, 1024 max tokens and evolving peer-only board
visibility. The Jev receiver A then reads only accepted B-authored claims.

A dedicated repository-backed preflight (:func:`verify_bridge_preflight`) must
pass, with an explicit approval, before any provider call. The transports are
constructed with the registered bridge partitions and the executor independently
verifies them and enforces request/cost guards per operation.
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
from . import jev_choice_v2 as jc2
from . import jev_ling_writer_v3 as writer_v3
from . import jev_ling_writer_v5 as writer_v5
from . import jev_replay as jr
from . import jev_replay_preregistration as pr
from . import jev_writer_ladder_preregistration_v5 as prv5
from . import jev_writer_ladder_v5 as ladder
from . import task_families as tf
from .communication_events import CommunicationEventLog
from .communication_protocol import BatteryCondition
from .communication_runner import AgentContext
from .jev_choice import JevChoiceClient, load_jev_credentials
from .jev_choice_smoke import estimate_cost_usd


BRIDGE_VERSION = "exact-original-comm-bridge-v5"
RECEIVER_AGENT = bd.FINALIZER_AGENT
DEFAULT_BRIDGE_JOURNAL = Path("runs/epic-126/jev-writer-exact-bridge-v5.jsonl")
DEFAULT_BRIDGE_REPORT = Path("runs/epic-126/jev-writer-exact-bridge-report-v5.json")

#: Writer outcomes that stop the bridge before the Jev receiver is called.
STOP_WRITER_OUTCOMES = frozenset({
    writer_v5.OUTCOME_EMPTY_OUTPUT,
    writer_v5.OUTCOME_TRUNCATED_OUTPUT,
    writer_v5.OUTCOME_UNPARSED_OUTPUT,
    writer_v5.OUTCOME_INVALID_ANSWER,
    writer_v5.OUTCOME_WRITER_ERROR,
})

PRIOR_REGISTRATION_ARTIFACTS = (
    "runs/epic-126/jev-choice-replay-preregistration.json",
    "runs/epic-126/jev-choice-replay-preregistration-v2.json",
    "runs/epic-126/jev-choice-replay-preregistration-v3.json",
    "runs/epic-126/jev-writer-ladder-preregistration-v4.json",
)


@dataclass(frozen=True)
class BridgePlan:
    instance_ids: tuple[str, ...]
    planned_requests: int
    planned_cases: int
    request_cap: int
    jev_request_cap: int
    ling_request_cap: int
    cost_cap_usd: float
    worst_case_call_cost_usd: float
    registration_hash: str
    protocol_key: str
    model: str
    endpoint: str
    ling_model: str
    ling_endpoint: str

    def to_dict(self) -> dict[str, Any]:
        return {"instance_ids": list(self.instance_ids), "planned_requests": self.planned_requests,
                "planned_cases": self.planned_cases, "request_cap": self.request_cap,
                "jev_request_cap": self.jev_request_cap, "ling_request_cap": self.ling_request_cap,
                "cost_cap_usd": self.cost_cap_usd,
                "worst_case_call_cost_usd": self.worst_case_call_cost_usd,
                "registration_hash": self.registration_hash, "protocol_key": self.protocol_key,
                "model": self.model, "endpoint": self.endpoint, "ling_model": self.ling_model,
                "ling_endpoint": self.ling_endpoint}


def bridge_instances() -> list[tf.FamilyInstance]:
    from .jev_choice_pilot import pilot_instances
    return pilot_instances()


def build_bridge_plan(instances: Sequence[tf.FamilyInstance],
                      registration: Mapping[str, Any]) -> BridgePlan:
    bridge = registration.get("exact_bridge", {})
    ling = registration.get("ling_contract") or {}
    per_instance = len(ladder.EXACT_BRIDGE_AGENTS) * ladder.EXACT_BRIDGE_TURNS + 1
    return BridgePlan(instance_ids=tuple(instance.instance_id for instance in instances),
                      planned_cases=len(instances),
                      planned_requests=len(instances) * per_instance,
                      request_cap=int(bridge.get("physical_requests", 0)),
                      jev_request_cap=int(bridge.get("jev_partition", 0)),
                      ling_request_cap=int(bridge.get("ling_partition", 0)),
                      cost_cap_usd=float(bridge.get("cost_cap_usd", 0.0)),
                      worst_case_call_cost_usd=estimate_cost_usd(
                          int(registration.get("caps", {}).get("input_token_ceiling", 0))
                          * (1 + max(pr.LING_MAX_RETRIES, pr.JEV_REPLAY_MAX_RETRIES))),
                      registration_hash=str(registration.get("preregistration_hash", "")),
                      protocol_key=str((registration.get("model_and_protocol") or {}).get("protocol_key", "")),
                      model=str((registration.get("model_and_protocol") or {}).get("model", "")),
                      endpoint=str((registration.get("model_and_protocol") or {}).get("endpoint", "")),
                      ling_model=str(ling.get("model", "")), ling_endpoint=str(ling.get("endpoint", "")))


def construct_bridge_runtime(registration: Mapping[str, Any]) -> tuple[Any, Any, BridgePlan]:
    """Build the live transports using the registered bridge partitions."""

    bridge = registration.get("exact_bridge", {})
    protocol = registration.get("model_and_protocol", {})
    model = str(protocol.get("model", ""))
    receiver = jc2.JevChoiceAdapterV2(
        JevChoiceClient(model=model, max_physical_requests=int(bridge.get("jev_partition", 0))),
        model=model)
    writer = writer_v5.LingWriterClientV5(max_physical_requests=int(bridge.get("ling_partition", 0)))
    plan = build_bridge_plan(bridge_instances(), registration)
    return receiver, writer, plan


def agent_context_and_prompt(instance: tf.FamilyInstance, agent: str, turn: int,
                             board: Sequence[Mapping[str, Any]],
                             run_id: str) -> tuple[AgentContext, str]:
    """Build the prompt through the original AgentContext -> treatment_prompt path."""

    view = {**instance.agent_view(agent, "COMM"), "is_finalizer": agent == bd.FINALIZER_AGENT,
            "finalizing_agent": bd.FINALIZER_AGENT}
    visible = tuple(dict(row) for row in board if row["author"] != agent)
    context = AgentContext(run_id, instance.instance_id, agent, BatteryCondition.COMM, turn, view,
                           visible, bd.PROMPT_SCHEMA_VERSION, ladder.EXACT_BRIDGE_TOKEN_BUDGET)
    return context, json.dumps(bd.treatment_prompt(context), sort_keys=True)


def verify_bridge_preflight(plan: BridgePlan, registration: Mapping[str, Any],
                            receiver: jc2.JevChoiceAdapterV2, writer: Any, *, repo_root: Path,
                            pinned_hash: str | None = None,
                            ling_key_present: bool | None = None) -> dict[str, Any]:
    """Repository-backed bridge preflight. Returns named checks, ``ok`` and ``failed``."""

    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    result = prv5.verify_against_writer_ladder_preregistration_v5(
        registration, instance_ids=list((registration.get("manifest") or {}).get("instance_ids", [])),
        model=plan.model, endpoint=plan.endpoint, protocol_key=plan.protocol_key,
        planned_requests=plan.planned_requests, repo_root=repo_root)
    check("registration_verifies", result["ok"], result["errors"])
    check("registration_hash_matches_rebuild",
          registration.get("preregistration_hash") == result.get("registration_hash"), None)
    if pinned_hash is not None:
        check("pinned_hash_matches", plan.registration_hash == pinned_hash, plan.registration_hash)
    check("status_locked", registration.get("status") == prv5.WRITER_LADDER_LOCKED_STATUS,
          registration.get("status"))
    check("live_collection_not_authorized",
          registration.get("approval", {}).get("live_collection_authorized") is False, None)
    generator = registration.get("generator", {})
    check("source_hash_wellformed", isinstance(generator.get("source_files_hash"), str)
          and len(generator.get("source_files_hash", "")) == 64, None)
    check("treatment_hash_wellformed", isinstance(generator.get("treatment_hash"), str)
          and len(generator.get("treatment_hash", "")) == 64, None)
    manifest = registration.get("manifest", {})
    check("manifest_seventeen", len(manifest.get("instance_ids", [])) == 17,
          len(manifest.get("instance_ids", [])))
    check("forms_six", manifest.get("paired_forms") == 6
          and len(list(manifest.get("iso_form_ids", []))) == 6, None)

    protocol = registration.get("model_and_protocol", {})
    check("protocol_key_is_v2", jc2.is_jev_v2_protocol_key(plan.protocol_key), plan.protocol_key)
    check("protocol_key_not_v1", not jc.is_jev_protocol_key(plan.protocol_key), None)
    check("codec_version_is_v2",
          protocol.get("codec_version") == jc2.JEV_CHOICE_V2_CODEC_VERSION, None)
    check("model_matches", plan.model == protocol.get("model") and receiver.model == plan.model, None)
    check("endpoint_matches", plan.endpoint == protocol.get("endpoint"), None)

    bridge = registration.get("exact_bridge", {})
    client = receiver.client
    check("receiver_endpoint_matches", getattr(client, "endpoint", None) == plan.endpoint, None)
    check("receiver_retry_policy", getattr(client, "max_retries", None) == pr.JEV_REPLAY_MAX_RETRIES, None)
    check("receiver_partition_matches_bridge",
          getattr(client, "max_physical_requests", None) == plan.jev_request_cap
          == int(bridge.get("jev_partition", -1)), getattr(client, "max_physical_requests", None))
    check("writer_model_matches", getattr(writer, "model", None) == plan.ling_model, None)
    check("writer_endpoint_matches", getattr(writer, "endpoint", None) == plan.ling_endpoint, None)
    check("writer_partition_matches_bridge",
          getattr(writer, "max_physical_requests", None) == plan.ling_request_cap
          == int(bridge.get("ling_partition", -1)), getattr(writer, "max_physical_requests", None))
    check("writer_transport_version_matches",
          getattr(writer, "transport_version", None) == writer_v3.LING_WRITER_TRANSPORT_VERSION, None)
    check("writer_pacing_algorithm_matches",
          getattr(writer, "pacing_algorithm", None) == writer_v3.LING_PACING_ALGORITHM, None)
    check("writer_clock_is_monotonic",
          getattr(writer, "clock_name", None) == writer_v3.LING_MONOTONIC_CLOCK_NAME, None)
    check("writer_min_interval_matches",
          getattr(writer, "min_attempt_interval_seconds", None)
          == writer_v3.LING_MIN_ATTEMPT_INTERVAL_SECONDS, None)
    check("writer_parser_version_matches",
          getattr(writer, "writer_parser_version", None) == writer_v5.WRITER_PARSER_VERSION, None)
    check("writer_outcomes_version_matches",
          getattr(writer, "writer_outcomes_version", None) == writer_v5.WRITER_OUTCOMES_VERSION, None)
    check("seed_algorithm_matches", bridge.get("seed_algorithm") == ladder.EXACT_BRIDGE_SEED_ALGORITHM, None)
    check("token_budget_matches", bridge.get("token_budget") == ladder.EXACT_BRIDGE_TOKEN_BUDGET, None)
    check("bridge_turns_agents_match", bridge.get("turns") == ladder.EXACT_BRIDGE_TURNS
          and list(bridge.get("agents", [])) == list(ladder.EXACT_BRIDGE_AGENTS), None)

    ladder_cap = registration.get("caps", {}).get("ladder_partition", {})
    check("bridge_caps_frozen", plan.jev_request_cap == int(bridge.get("jev_partition", -1))
          and plan.ling_request_cap == int(bridge.get("ling_partition", -1))
          and plan.request_cap == int(bridge.get("physical_requests", -1))
          and plan.jev_request_cap + plan.ling_request_cap == plan.request_cap, None)
    check("combined_partition_non_overlapping",
          int(ladder_cap.get("jev", -1)) + plan.jev_request_cap
          == registration.get("caps", {}).get("provider_partition", {}).get("jev")
          and int(ladder_cap.get("ling", -1)) + plan.ling_request_cap
          == registration.get("caps", {}).get("provider_partition", {}).get("ling"), None)
    check("combined_partition_within_total",
          registration.get("caps", {}).get("provider_partition", {}).get("jev") == 250
          and registration.get("caps", {}).get("provider_partition", {}).get("ling") == 300, None)
    planned_jev = len(plan.instance_ids)
    planned_ling = len(plan.instance_ids) * len(ladder.EXACT_BRIDGE_AGENTS) * ladder.EXACT_BRIDGE_TURNS
    check("planned_within_bridge_caps",
          planned_jev <= plan.jev_request_cap and planned_ling <= plan.ling_request_cap
          and plan.planned_requests <= plan.request_cap, None)

    check("journal_path_fresh", not DEFAULT_BRIDGE_JOURNAL.exists(), str(DEFAULT_BRIDGE_JOURNAL))
    check("report_path_fresh", not DEFAULT_BRIDGE_REPORT.exists(), str(DEFAULT_BRIDGE_REPORT))
    credentials = load_jev_credentials()
    check("jev_credentials_present", bool(credentials.present and credentials.shape_ok),
          credentials.redacted())
    ling_ok = bd._api_key() is not None if ling_key_present is None else bool(ling_key_present)
    check("ling_credentials_present", ling_ok, None)
    check("prior_v1_v4_artifacts_present",
          all((repo_root / relative).is_file() for relative in PRIOR_REGISTRATION_ARTIFACTS), None)
    return {"ok": all(item["ok"] for item in checks), "checks": checks,
            "failed": [item["check"] for item in checks if not item["ok"]],
            "registration_verification": result}


def _blocked(plan: BridgePlan, reason: str, approval: str | None) -> dict[str, Any]:
    return {"mode": BRIDGE_VERSION, "status": "blocked", "stop_reason": reason, "approval": approval,
            "planned_requests": plan.planned_requests, "planned_cases": plan.planned_cases,
            "attempted_cases": 0, "physical_attempts": 0, "cases": [],
            "raw_response_retained": False, "credentials_retained": False}


def execute_bridge(plan: BridgePlan, receiver: jc2.JevChoiceAdapterV2, writer: Any,
                   verification: Mapping[str, Any], instances: Sequence[tf.FamilyInstance], *,
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
        return _blocked(plan, "bridge_partition_mismatch", approval)
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
        "mode": BRIDGE_VERSION, "status": "completed", "stop_reason": None, "approval": approval,
        "registration_hash": plan.registration_hash, "pinned_registration_hash": pinned_hash,
        "protocol_key": plan.protocol_key, "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
        "token_budget": ladder.EXACT_BRIDGE_TOKEN_BUDGET, "turns": ladder.EXACT_BRIDGE_TURNS,
        "agents": list(ladder.EXACT_BRIDGE_AGENTS),
        "seed_algorithm": ladder.EXACT_BRIDGE_SEED_ALGORITHM,
        "planned_requests": plan.planned_requests, "planned_cases": plan.planned_cases,
        "attempted_cases": 0, "receiver_valid_cases": 0, "receiver_invalid_cases": 0,
        "receiver_unattempted_cases": 0, "physical_attempts": 0,
        "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0,
        "max_physical_requests": plan.request_cap, "cost_cap_usd": plan.cost_cap_usd,
        "resolved_models": [], "writes_by_agent": {agent: 0 for agent in ladder.EXACT_BRIDGE_AGENTS},
        "rejected_writes": 0, "board_messages": 0, "verified_read_exposures": 0,
        "authoritative_i_m": 0, "i_m_bits": 0.0, "distinct_forms": 0,
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

    def cost_ok(extra_calls: int) -> bool:
        return report["estimated_cost_usd"] + plan.worst_case_call_cost_usd * extra_calls <= plan.cost_cap_usd

    forms: set[str] = set()
    try:
        for instance_id in plan.instance_ids:
            instance = by_id[instance_id]
            if report["attempted_cases"] > 0:
                sleep_fn(0.25)
            report["attempted_cases"] += 1
            forms.add(receiver.build_state(instance, RECEIVER_AGENT, "ISO").request_hash)
            run_id = f"bridge-{instance.instance_id}"
            log = CommunicationEventLog(run_id)
            board: list[dict[str, Any]] = []
            board_info: dict[str, Any] = {}
            rejected: list[dict[str, Any]] = []
            writer_outcomes: list[dict[str, Any]] = []
            invalid: str | None = None
            for turn in range(ladder.EXACT_BRIDGE_TURNS):
                for agent in ladder.EXACT_BRIDGE_AGENTS:
                    for row in [r for r in board if r["author"] != agent]:
                        read = log.peer_read(agent, board_info[row["message_id"]],
                                             exposure_id=f"turn-{turn}")
                        if read is not None:
                            report["verified_read_exposures"] += 1
                    if not cost_ok(1 + pr.LING_MAX_RETRIES):
                        report["status"], report["stop_reason"] = "stopped", "cost_cap"
                        invalid = "cost_cap"
                        break
                    _, prompt = agent_context_and_prompt(instance, agent, turn, board, run_id)
                    outcome = writer.write_outcome({
                        "prompt": prompt, "grammar": ladder.RUNG_INDEX["L4X"].grammar,
                        "private_clues": list(instance.private_clues.get(agent, ())),
                        "candidate_labels": sorted(instance.solutions),
                        "seed": bd.provider_seed(instance.instance_id, "COMM", turn, agent),
                        "max_tokens": ladder.EXACT_BRIDGE_TOKEN_BUDGET})
                    report["input_tokens"] += int(outcome.get("input_tokens") or 0)
                    report["output_tokens"] += int(outcome.get("output_tokens") or 0)
                    report["estimated_cost_usd"] = estimate_cost_usd(report["input_tokens"])
                    kind = outcome["outcome"]
                    writer_outcomes.append({"agent": agent, "turn": turn, "outcome": kind,
                                            "finish_reason": outcome.get("finish_reason"),
                                            "content_length": outcome.get("content_length"),
                                            "answer": outcome.get("answer"),
                                            "seed_sent": outcome.get("seed_sent"),
                                            "max_tokens": outcome.get("max_tokens"),
                                            "error_class": outcome.get("error_class"),
                                            "physical_attempts": outcome.get("physical_attempts")})
                    if kind == writer_v5.OUTCOME_MESSAGE_CANDIDATE \
                            and instance.holds_claim(agent, str(outcome["claim"])):
                        receiver_agent = "B" if agent == "A" else "A"
                        message_id = f"message-{agent}-{turn}"
                        text = str(outcome["claim"])
                        info = instance.information(receiver_agent, text, message_id)
                        row = {"message_id": message_id, "author": agent, "receiver": receiver_agent,
                               "text": text, "status": info.status, "delta_i_bits": info.delta_i_bits,
                               "message_tokens": len(text.split())}
                        board.append(row)
                        board_info[message_id] = info
                        report["writes_by_agent"][agent] += 1
                        report["board_messages"] += 1
                        if info.delta_i_bits is not None:
                            report["authoritative_i_m"] += 1
                            report["i_m_bits"] += float(info.delta_i_bits)
                        log.board_write(agent, info, message_tokens=row["message_tokens"],
                                        receiver_id=receiver_agent)
                    elif kind == writer_v5.OUTCOME_NON_OWNED_CLAIM:
                        report["rejected_writes"] += 1
                        rejected.append({"agent": agent, "turn": turn, "claim": outcome.get("claim")})
                        log.record("board_write_rejected", agent, status="rejected",
                                   payload={"reason": "claim_not_owned_by_writer",
                                            "raw_text": outcome.get("claim")})
                    elif kind == writer_v5.OUTCOME_DELIBERATE_SILENCE:
                        pass
                    else:
                        invalid = str(outcome.get("error_class") or kind)
                        report["status"], report["stop_reason"] = "stopped", invalid
                        break
                if invalid is not None:
                    break

            receiver_attempted = invalid is None
            receiver_row: dict[str, Any] = {
                "instance_id": instance.instance_id, "turns": ladder.EXACT_BRIDGE_TURNS,
                "agents": list(ladder.EXACT_BRIDGE_AGENTS),
                "board": list(board), "rejected": rejected,
                "board_log": [event.to_dict() for event in log.events],
                "writer_outcomes": writer_outcomes,
                "receiver_attempted": receiver_attempted,
                "receiver_valid": False, "receiver_status": None, "receiver_error_class": None,
                "normalization_tier": None, "renormalized": None, "request_hash": None,
                "state_hash": None, "protocol_key": plan.protocol_key, "resolved_model": None,
                "option_ids": sorted(instance.solutions), "target_id": instance.target,
                "selected_option_id": None, "confidence": None,
                "probabilities": {}, "raw_probabilities": {}, "probability_diagnostics": None,
                "usage": {}, "i_m_bits": None, "eligible_exposure": False,
                "provider_attempts": {"jev": int(getattr(receiver.client, "physical_attempts", 0) or 0),
                                      "ling": int(getattr(writer, "physical_attempts", 0) or 0)},
                "raw_response_retained": False, "credentials_retained": False,
            }
            if receiver_attempted:
                b_rows = [row for row in board if row["author"] == "B" and row["status"] == "accepted"]
                visible = [{"text": jr.serialize_message(str(row["text"]))} for row in b_rows]
                state = receiver.build_state(instance, RECEIVER_AGENT, "COMM", visible_messages=visible)
                receiver_row["request_hash"] = state.request_hash
                receiver_row["state_hash"] = jr.canonical_hash(state.state)
                if not cost_ok(1 + pr.JEV_REPLAY_MAX_RETRIES):
                    report["status"], report["stop_reason"] = "stopped", "cost_cap"
                else:
                    try:
                        response, _ = receiver.complete_with_raw(state)
                    except Exception as exc:
                        report["status"], report["stop_reason"] = "stopped", f"jev_{type(exc).__name__}"
                        response = None
                    if response is not None:
                        usage = dict(response.usage)
                        report["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
                        report["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
                        report["estimated_cost_usd"] = estimate_cost_usd(report["input_tokens"])
                        if response.model:
                            report["resolved_models"] = sorted(set(report["resolved_models"]) | {response.model})
                        valid = response.status == "complete"
                        receiver_row.update({
                            "receiver_status": response.status,
                            "receiver_error_class": response.error_class,
                            "receiver_valid": valid,
                            "normalization_tier": response.normalization_tier,
                            "renormalized": response.renormalized,
                            "resolved_model": response.model,
                            "selected_option_id": response.selected_option_id,
                            "confidence": response.confidence,
                            "probabilities": dict(response.probabilities),
                            "raw_probabilities": dict(response.raw_probabilities),
                            "probability_diagnostics": (response.diagnostics.to_dict()
                                                         if response.diagnostics is not None else None),
                            "usage": usage,
                        })
                        if valid and response.request_hash != state.request_hash:
                            report["status"], report["stop_reason"] = "stopped", "request_hash_drift"
                            valid = False
                        if valid:
                            report["receiver_valid_cases"] += 1
                            receiver_row["eligible_exposure"] = bool(b_rows)
                            if b_rows:
                                receiver_row["i_m_bits"] = sum(float(row["delta_i_bits"] or 0.0)
                                                               for row in b_rows)
                        else:
                            report["receiver_invalid_cases"] += 1
                            if report["status"] == "completed":
                                report["status"], report["stop_reason"] = "stopped", response.error_class
            else:
                report["receiver_unattempted_cases"] += 1
            journal(receiver_row)
            if report["status"] == "stopped":
                break
    finally:
        if handle is not None:
            handle.close()

    report["physical_attempts"] = int(getattr(receiver.client, "physical_attempts", 0) or 0) \
        + int(getattr(writer, "physical_attempts", 0) or 0)
    report["provider_attempts"] = {"jev": int(getattr(receiver.client, "physical_attempts", 0) or 0),
                                   "ling": int(getattr(writer, "physical_attempts", 0) or 0),
                                   "combined": report["physical_attempts"],
                                   "jev_partition": plan.jev_request_cap,
                                   "ling_partition": plan.ling_request_cap}
    report["distinct_forms"] = len(forms)
    report["i_m_bits"] = round(report["i_m_bits"], 9)
    if report["status"] == "completed" and report["receiver_valid_cases"] != plan.planned_cases:
        report["status"], report["stop_reason"] = "incomplete", "missing_valid_receiver"
    report["raw_response_retained"] = False
    report["credentials_retained"] = False
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="#187 exact original COMM bridge v5")
    parser.add_argument("--registration", type=Path, default=prv5.DEFAULT_OUTPUT_V5)
    parser.add_argument("--report", type=Path, default=DEFAULT_BRIDGE_REPORT)
    parser.add_argument("--journal", type=Path, default=DEFAULT_BRIDGE_JOURNAL)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--approval")
    args = parser.parse_args(argv)
    registration = json.loads(args.registration.read_text(encoding="utf-8"))
    receiver, writer, plan = construct_bridge_runtime(registration)
    verification = verify_bridge_preflight(plan, registration, receiver, writer,
                                           repo_root=Path(__file__).resolve().parents[2],
                                           pinned_hash=registration.get("preregistration_hash"))
    print(json.dumps({"mode": f"{BRIDGE_VERSION}-preflight", "ok": verification["ok"],
                      "failed": verification["failed"], "plan": plan.to_dict(),
                      "checks": verification["checks"]}, indent=2, sort_keys=True, allow_nan=False))
    if not verification["ok"]:
        return 2
    if not args.live:
        return 0
    if not args.approval:
        print(json.dumps({"mode": BRIDGE_VERSION, "status": "blocked",
                          "stop_reason": "missing_approval"}, indent=2, sort_keys=True))
        return 2
    report = execute_bridge(plan, receiver, writer, verification, bridge_instances(),
                            approval=args.approval, pinned_hash=registration.get("preregistration_hash"),
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
    "BRIDGE_VERSION", "STOP_WRITER_OUTCOMES", "DEFAULT_BRIDGE_JOURNAL", "DEFAULT_BRIDGE_REPORT",
    "PRIOR_REGISTRATION_ARTIFACTS", "BridgePlan", "bridge_instances", "build_bridge_plan",
    "construct_bridge_runtime", "agent_context_and_prompt", "verify_bridge_preflight",
    "execute_bridge", "main",
]
