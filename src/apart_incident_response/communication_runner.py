"""Fixture-first two-agent runner for the ISO/FULL/COMM battery."""

from __future__ import annotations

from dataclasses import dataclass, field
import uuid
from typing import Any, Mapping, Protocol, Sequence

from .communication_events import CommunicationEventLog
from .communication_protocol import BatteryCondition
from .task_families import FamilyInstance


@dataclass(frozen=True)
class AgentContext:
    run_id: str
    instance_id: str
    agent_id: str
    condition: BatteryCondition
    turn: int
    task_view: Mapping[str, Any]
    visible_messages: tuple[Mapping[str, Any], ...]
    prompt_version: str
    token_budget: int


@dataclass(frozen=True)
class AgentResponse:
    answer: str | None = None
    message: str | None = None
    used_message_ids: tuple[str, ...] = ()
    output_text: str = ""
    output_logprob_entropy_bits: float | None = None
    logprob_coverage: float | None = None
    logprob_status: str = "not_requested"
    failure_reason: str | None = None


class BatteryProvider(Protocol):
    provider: str
    version: str

    def respond(self, context: AgentContext) -> AgentResponse:
        ...


class ScriptedProvider:
    """Deterministic fake provider for harness tests; not model evidence."""

    provider = "fixture"
    version = "scripted-provider-v1"

    def __init__(self, answers: Mapping[tuple[str, BatteryCondition, str], str],
                 messages: Mapping[tuple[str, BatteryCondition, str, int], str] | None = None) -> None:
        self.answers = dict(answers)
        self.messages = dict(messages or {})

    def respond(self, context: AgentContext) -> AgentResponse:
        key = (context.instance_id, context.condition, context.agent_id)
        answer = self.answers.get(key)
        message = self.messages.get((context.instance_id, context.condition, context.agent_id, context.turn))
        used = tuple(message_row["message_id"] for message_row in context.visible_messages
                     if message_row.get("author") != context.agent_id)
        return AgentResponse(answer=answer, message=message, used_message_ids=used,
                             output_text=f"fixture answer={answer!r}")


class SilentProvider:
    provider = "fixture"
    version = "silent-provider-v1"

    def respond(self, context: AgentContext) -> AgentResponse:
        return AgentResponse(output_text="fixture silence")


@dataclass(frozen=True)
class BatteryRunResult:
    run_id: str
    pair_id: str
    instance_id: str
    condition: BatteryCondition
    family: str
    seed: int
    provider: str
    provider_version: str
    prompt_version: str
    status: str
    task_success: bool
    submitted_answers: Mapping[str, str | None]
    invalid_agents: tuple[str, ...]
    event_summary: Mapping[str, Any]
    artifact: Mapping[str, Any]


class TwoAgentBatteryRunner:
    """Run new-condition triplets without touching the legacy ExperimentController."""

    def __init__(self, *, prompt_version: str = "communication-battery-prompt-v1",
                 token_budget: int = 512, turns: int = 2) -> None:
        if token_budget <= 0 or turns <= 0:
            raise ValueError("token budget and turns must be positive")
        self.prompt_version = prompt_version
        self.token_budget = token_budget
        self.turns = turns

    def run_condition(self, instance: FamilyInstance, condition: BatteryCondition,
                      provider: BatteryProvider, *, pair_id: str | None = None,
                      run_id: str | None = None) -> BatteryRunResult:
        pair = pair_id or f"pair-{instance.instance_id}"
        run = run_id or f"comm-{condition.value.lower()}-{uuid.uuid4().hex}"
        log = CommunicationEventLog(run)
        log.record("run_started", "controller", payload={"condition": condition.value,
                                                           "prompt_version": self.prompt_version,
                                                           "token_budget": self.token_budget})
        board: list[dict[str, Any]] = []
        message_info: dict[str, Any] = {}
        received_information: dict[tuple[str, str], Any] = {}
        used_outputs: list[tuple[str, str, tuple[str, ...]]] = []
        answers: dict[str, str | None] = {"A": None, "B": None}
        invalid: list[str] = []
        for turn in range(self.turns):
            for agent in ("A", "B"):
                if condition is BatteryCondition.FULL:
                    view = instance.agent_view(agent, "FULL")
                else:
                    view = instance.agent_view(agent, condition.value)
                visible = tuple(row for row in board if row["author"] != agent) if condition is BatteryCondition.COMM else ()
                for row in visible:
                    received_info = instance.information(agent, row["text"], row["message_id"])
                    received_information[(agent, row["message_id"])] = received_info
                    log.peer_read(agent, received_info, exposure_id=f"turn-{turn}")
                context = AgentContext(run, instance.instance_id, agent, condition, turn, view,
                                       visible, self.prompt_version, self.token_budget)
                try:
                    response = provider.respond(context)
                except Exception as exc:  # preserve invalid provider runs for denominator reporting
                    invalid.append(agent)
                    log.record("provider_failure", agent, status="invalid",
                               payload={"error_type": type(exc).__name__})
                    continue
                if response.failure_reason:
                    invalid.append(agent)
                    log.record("provider_failure", agent, status="invalid",
                               payload={"error_type": response.failure_reason.split(":", 1)[0]})
                output_id = f"output-{agent}-{turn}"
                log.model_output(agent, output_id,
                                 exposed_message_ids=response.used_message_ids,
                                 logprob_entropy_bits=response.output_logprob_entropy_bits,
                                 logprob_coverage=response.logprob_coverage,
                                 logprob_status=response.logprob_status)
                used_outputs.append((agent, output_id, response.used_message_ids))
                if response.answer is not None:
                    answers[agent] = response.answer
                if condition is BatteryCondition.COMM and response.message:
                    message_id = f"message-{agent}-{turn}"
                    info = instance.information(agent, response.message, message_id)
                    message_info[message_id] = info
                    row = {"message_id": message_id, "author": agent, "text": response.message,
                           "status": info.status, "delta_i_bits": info.delta_i_bits,
                           "message_tokens": len(response.message.split())}
                    board.append(row)
                    log.board_write(agent, info, message_tokens=row["message_tokens"])
        outcomes = {agent: instance.validate(answer) if answer is not None else {"accepted": False, "score": None}
                    for agent, answer in answers.items()}
        task_success = any(outcome.get("accepted", False) for outcome in outcomes.values())
        for agent, output_id, used_ids in used_outputs:
            if not outcomes[agent].get("accepted", False):
                continue
            for used_id in used_ids:
                info = received_information.get((agent, used_id))
                row = next((item for item in board if item["message_id"] == used_id), None)
                if info is None or row is None or row["author"] == agent:
                    continue
                if info.useful:
                    log.verified_use(agent, info, output_id,
                                     checker_evidence={"verified": True, "task_checker": f"{instance.family}-oracle-v1",
                                                       "answer_accepted": True})
        status = "invalid" if invalid else "completed"
        task_success = task_success and status == "completed"
        artifact = {
            "run_id": run, "pair_id": pair, "condition": condition.value,
            "family": instance.family, "instance_id": instance.instance_id, "seed": instance.seed,
            "provider": getattr(provider, "provider", type(provider).__name__),
            "provider_version": getattr(provider, "version", "unknown"),
            "prompt_version": self.prompt_version, "task_success": task_success,
            "answers_present": sorted(agent for agent, answer in answers.items() if answer is not None),
            "invalid_agents": invalid, "task": instance.public_manifest(),
            "events": log.summary(),
        }
        return BatteryRunResult(run, pair, instance.instance_id, condition, instance.family, instance.seed,
                                artifact["provider"], artifact["provider_version"], self.prompt_version,
                                status, task_success, answers, tuple(invalid), log.summary(), artifact)

    def run_triplet(self, instance: FamilyInstance, provider: BatteryProvider, *, pair_id: str | None = None) -> tuple[BatteryRunResult, ...]:
        pair = pair_id or f"pair-{instance.instance_id}"
        return tuple(self.run_condition(instance, condition, provider, pair_id=pair)
                     for condition in BatteryCondition)

    def run_paired(self, instances: Sequence[FamilyInstance], provider: BatteryProvider) -> list[BatteryRunResult]:
        """Run independent generated instances with condition-paired IDs."""

        results: list[BatteryRunResult] = []
        for instance in instances:
            results.extend(self.run_triplet(instance, provider, pair_id=f"pair-{instance.instance_id}"))
        return results


def independent_instances(family: str, seeds: Sequence[int], generator: callable) -> list[FamilyInstance]:
    """Generate once per independent seed; callers pair conditions on the ID."""

    return [generator(family, seed) for seed in seeds]


__all__ = [
    "AgentContext", "AgentResponse", "BatteryProvider", "BatteryRunResult",
    "ScriptedProvider", "SilentProvider", "TwoAgentBatteryRunner", "independent_instances",
]
