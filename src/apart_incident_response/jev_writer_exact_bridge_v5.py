"""#187 — exact original COMM bridge v5 (offline build).

Reproduces the original Ling COMM treatment exactly enough to test whether the
earlier planning-low board use reproduces: two agents (A, B) across the
registered two turns, the original ``treatment_prompt`` JSON schema and grammar,
the deterministic provider seed, 1024 max tokens, and evolving visible-message
state. It then lets the Jev receiver read the resulting board.

Gated like the ladder: no calls without approval and a passing preflight; both
journal and report paths must be absent.
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
from . import jev_replay as jr
from . import jev_replay_preregistration as pr
from . import jev_writer_ladder_preregistration_v5 as prv5
from . import jev_writer_ladder_v5 as ladder
from . import task_families as tf
from .communication_events import CommunicationEventLog
from .jev_choice import JevChoiceClient
from .jev_choice_smoke import estimate_cost_usd


BRIDGE_VERSION = "exact-original-comm-bridge-v5"
RECEIVER_AGENT = bd.FINALIZER_AGENT
DEFAULT_BRIDGE_JOURNAL = Path("runs/epic-126/jev-writer-exact-bridge-v5.jsonl")
DEFAULT_BRIDGE_REPORT = Path("runs/epic-126/jev-writer-exact-bridge-report-v5.json")


@dataclass(frozen=True)
class BridgePlan:
    instance_ids: tuple[str, ...]
    planned_requests: int
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
                "request_cap": self.request_cap, "jev_request_cap": self.jev_request_cap,
                "ling_request_cap": self.ling_request_cap, "cost_cap_usd": self.cost_cap_usd,
                "registration_hash": self.registration_hash, "protocol_key": self.protocol_key,
                "model": self.model, "endpoint": self.endpoint, "ling_model": self.ling_model,
                "ling_endpoint": self.ling_endpoint}


def bridge_instances() -> list[tf.FamilyInstance]:
    return pilot.pilot_instances()


def build_bridge_plan(instances: Sequence[tf.FamilyInstance],
                      registration: Mapping[str, Any]) -> BridgePlan:
    caps = registration.get("caps", {})
    bridge = registration.get("exact_bridge", {})
    ling = registration.get("ling_contract") or {}
    per_instance = len(ladder.EXACT_BRIDGE_AGENTS) * ladder.EXACT_BRIDGE_TURNS + 1
    return BridgePlan(instance_ids=tuple(instance.instance_id for instance in instances),
                      planned_requests=len(instances) * per_instance,
                      request_cap=int(bridge.get("physical_requests", 0)),
                      jev_request_cap=int(bridge.get("jev_partition", 0)),
                      ling_request_cap=int(bridge.get("ling_partition", 0)),
                      cost_cap_usd=float(bridge.get("cost_cap_usd", 0.0)),
                      worst_case_call_cost_usd=estimate_cost_usd(pr.LING_MAX_TOKENS * 16),
                      registration_hash=str(registration.get("preregistration_hash", "")),
                      protocol_key=str((registration.get("model_and_protocol") or {}).get("protocol_key", "")),
                      model=str((registration.get("model_and_protocol") or {}).get("model", "")),
                      endpoint=str((registration.get("model_and_protocol") or {}).get("endpoint", "")),
                      ling_model=str(ling.get("model", "")), ling_endpoint=str(ling.get("endpoint", "")))


def _context(instance: tf.FamilyInstance, agent: str, turn: int,
             board: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    view = dict(instance.agent_view(agent, "COMM"))
    view["is_finalizer"] = agent == bd.FINALIZER_AGENT
    view["finalizing_agent"] = bd.FINALIZER_AGENT
    visible = [row for row in board if row["author"] != agent]
    return {
        "instance_id": instance.instance_id,
        "instruction": view.get("task_instruction"),
        "family": instance.family,
        "complexity": instance.complexity.value,
        "condition": "COMM",
        "turn": turn,
        "agent_id": agent,
        "role": "writer",
        "is_finalizer": agent == bd.FINALIZER_AGENT,
        "finalizing_agent": bd.FINALIZER_AGENT,
        "candidate_labels": sorted(instance.solutions),
        "joint_clues": list(view.get("joint_clues", [])),
        "private_clues": list(instance.private_clues.get(agent, ())),
        "visible_messages": [{"text": jr.serialize_message(str(row["text"]))} for row in visible],
    }


def execute_bridge(plan: BridgePlan, receiver: jc2.JevChoiceAdapterV2, writer: Any,
                   instances: Sequence[tf.FamilyInstance], *, approval: str | None,
                   pinned_hash: str | None = None, journal_path: Path | None = None,
                   report_path: Path | None = None,
                   sleep_fn: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    if not approval:
        return {"mode": BRIDGE_VERSION, "status": "blocked", "stop_reason": "missing_approval",
                "approval": approval, "cases": [], "planned_requests": plan.planned_requests,
                "physical_attempts": 0, "replay_started": False}
    if pinned_hash is not None and plan.registration_hash != pinned_hash:
        return {"mode": BRIDGE_VERSION, "status": "blocked", "stop_reason": "registration_hash_mismatch",
                "approval": approval, "cases": [], "planned_requests": plan.planned_requests,
                "physical_attempts": 0, "replay_started": False}
    if journal_path is not None and journal_path.exists():
        return {"mode": BRIDGE_VERSION, "status": "blocked", "stop_reason": "output_exists",
                "approval": approval, "cases": [], "planned_requests": plan.planned_requests,
                "physical_attempts": 0, "replay_started": False}
    if report_path is not None and report_path.exists():
        return {"mode": BRIDGE_VERSION, "status": "blocked", "stop_reason": "report_exists",
                "approval": approval, "cases": [], "planned_requests": plan.planned_requests,
                "physical_attempts": 0, "replay_started": False}

    by_id = {instance.instance_id: instance for instance in instances}
    report: dict[str, Any] = {
        "mode": BRIDGE_VERSION, "status": "completed", "stop_reason": None, "approval": approval,
        "registration_hash": plan.registration_hash, "protocol_key": plan.protocol_key,
        "token_budget": ladder.EXACT_BRIDGE_TOKEN_BUDGET, "turns": ladder.EXACT_BRIDGE_TURNS,
        "agents": list(ladder.EXACT_BRIDGE_AGENTS),
        "seed_algorithm": ladder.EXACT_BRIDGE_SEED_ALGORITHM,
        "planned_requests": plan.planned_requests, "attempted_cases": 0, "physical_attempts": 0,
        "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0,
        "max_physical_requests": plan.request_cap, "resolved_models": [],
        "writes_by_agent": {"A": 0, "B": 0}, "rejected_writes": 0, "board_messages": 0,
        "verified_read_exposures": 0, "authoritative_i_m": 0, "i_m_bits": 0.0,
        "distinct_forms": 0, "cases": [], "raw_response_retained": False, "credentials_retained": False,
    }
    handle = None
    if journal_path is not None:
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        handle = journal_path.open("x", encoding="utf-8")
    forms: set[str] = set()
    try:
        for instance_id in plan.instance_ids:
            instance = by_id[instance_id]
            if report["attempted_cases"] > 0:
                sleep_fn(0.25)
            report["attempted_cases"] += 1
            forms.add(receiver.build_state(instance, RECEIVER_AGENT, "ISO").request_hash)
            log = CommunicationEventLog(f"bridge-{instance.instance_id}")
            board: list[dict[str, Any]] = []
            rejected: list[dict[str, Any]] = []
            invalid = None
            for turn in range(ladder.EXACT_BRIDGE_TURNS):
                for agent in ladder.EXACT_BRIDGE_AGENTS:
                    for row in [r for r in board if r["author"] != agent]:
                        info = row["info"]
                        read = log.peer_read(agent, info, exposure_id=f"turn-{turn}")
                        if read is not None:
                            report["verified_read_exposures"] += 1
                    context = _context(instance, agent, turn, board)
                    prompt = ladder.ladder_prompt("L4X", context)["prompt"]
                    outcome = writer.write_outcome({**context, "prompt": prompt,
                                                    "grammar": ladder.RUNG_INDEX["L4X"].grammar,
                                                    "seed": bd.provider_seed(instance.instance_id, "COMM",
                                                                             turn, agent),
                                                    "max_tokens": ladder.EXACT_BRIDGE_TOKEN_BUDGET})
                    report["input_tokens"] += int(outcome.get("input_tokens") or 0)
                    report["output_tokens"] += int(outcome.get("output_tokens") or 0)
                    report["estimated_cost_usd"] = estimate_cost_usd(report["input_tokens"])
                    kind = outcome["outcome"]
                    if kind == "message_candidate" and instance.holds_claim(agent, str(outcome["claim"])):
                        receiver_agent = "B" if agent == "A" else "A"
                        message_id = f"message-{agent}-{turn}"
                        info = instance.information(receiver_agent, str(outcome["claim"]), message_id)
                        row = {"message_id": message_id, "author": agent, "receiver": receiver_agent,
                               "text": str(outcome["claim"]), "info": info,
                               "delta_i_bits": info.delta_i_bits}
                        board.append(row)
                        report["writes_by_agent"][agent] += 1
                        report["board_messages"] += 1
                        if info.delta_i_bits is not None:
                            report["authoritative_i_m"] += 1
                            report["i_m_bits"] += float(info.delta_i_bits)
                        log.board_write(agent, info, message_tokens=len(str(outcome["claim"]).split()),
                                        receiver_id=receiver_agent)
                    elif kind == "non_owned_claim":
                        report["rejected_writes"] += 1
                        rejected.append({"agent": agent, "turn": turn, "claim": outcome.get("claim")})
                        log.record("board_write_rejected", agent, status="rejected",
                                   payload={"reason": "claim_not_owned_by_writer",
                                            "raw_text": outcome.get("claim")})
                    elif kind == "deliberate_silence":
                        pass
                    elif kind == "writer_error":
                        report["status"], report["stop_reason"] = "stopped", str(
                            outcome.get("error_class") or kind)
                        invalid = kind
                        break
                    else:
                        report["status"], report["stop_reason"] = "stopped", kind
                        invalid = kind
                        break
                if invalid is not None:
                    break
            visible = [{"text": jr.serialize_message(str(row["text"]))} for row in board]
            response = None
            if invalid is None:
                state = receiver.build_state(instance, RECEIVER_AGENT, "COMM", visible_messages=visible)
                try:
                    response, _ = receiver.complete_with_raw(state)
                except Exception as exc:
                    report["status"], report["stop_reason"] = "stopped", f"jev_{type(exc).__name__}"
                    response = None
            if response is not None:
                report["input_tokens"] += int((response.usage or {}).get("input_tokens", 0) or 0)
                report["output_tokens"] += int((response.usage or {}).get("output_tokens", 0) or 0)
                report["estimated_cost_usd"] = estimate_cost_usd(report["input_tokens"])
                if response.model:
                    report["resolved_models"] = sorted(set(report["resolved_models"]) | {response.model})
            case_row = {"instance_id": instance.instance_id, "turns": ladder.EXACT_BRIDGE_TURNS,
                        "agents": list(ladder.EXACT_BRIDGE_AGENTS),
                        "board": [{"message_id": row["message_id"], "author": row["author"],
                                   "receiver": row["receiver"], "delta_i_bits": row["delta_i_bits"]}
                                  for row in board],
                        "rejected": rejected, "board_log": [event.to_dict() for event in log.events],
                        "receiver_attempted": invalid is None, "writer_outcome": invalid}
            report["cases"].append(case_row)
            if handle is not None:
                handle.write(json.dumps(case_row, sort_keys=True, allow_nan=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            if invalid is not None:
                break
    finally:
        if handle is not None:
            handle.close()
    report["physical_attempts"] = int(getattr(receiver.client, "physical_attempts", 0) or 0) \
        + int(getattr(writer, "physical_attempts", 0) or 0)
    report["provider_attempts"] = {"jev": int(getattr(receiver.client, "physical_attempts", 0) or 0),
                                   "ling": int(getattr(writer, "physical_attempts", 0) or 0)}
    report["distinct_forms"] = len(forms)
    report["i_m_bits"] = round(report["i_m_bits"], 9)
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
    instances = bridge_instances()
    receiver = jc2.JevChoiceAdapterV2(JevChoiceClient(model=pr.JEV_REPLAY_MODEL),
                                      model=pr.JEV_REPLAY_MODEL)
    plan = build_bridge_plan(instances, registration)
    writer = __import__("apart_incident_response.jev_ling_writer_v5",
                        fromlist=["LingWriterClientV5"]).LingWriterClientV5()
    print(json.dumps({"mode": f"{BRIDGE_VERSION}-preflight", "plan": plan.to_dict()},
                     indent=2, sort_keys=True, allow_nan=False))
    if not args.live:
        return 0
    if not args.approval:
        print(json.dumps({"mode": BRIDGE_VERSION, "status": "blocked",
                          "stop_reason": "missing_approval"}, indent=2, sort_keys=True))
        return 2
    report = execute_bridge(plan, receiver, writer, instances, approval=args.approval,
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
    "BRIDGE_VERSION", "DEFAULT_BRIDGE_JOURNAL", "DEFAULT_BRIDGE_REPORT", "BridgePlan",
    "bridge_instances", "build_bridge_plan", "execute_bridge", "main",
]
