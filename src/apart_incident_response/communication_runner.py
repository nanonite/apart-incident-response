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
    logprob_mass_coverage: float | None = None
    logprob_status: str = "not_requested"
    failure_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float = 0.0
    prompt_hash: str | None = None
    prompt_schema_version: str | None = None


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
    model_id: str = "unknown"


class TwoAgentBatteryRunner:
    """Run new-condition triplets without touching the legacy ExperimentController."""

    def __init__(self, *, prompt_version: str = "communication-battery-prompt-v1",
                 token_budget: int = 512, turns: int = 2, finalizing_agent: str = "A") -> None:
        if token_budget <= 0 or turns <= 0:
            raise ValueError("token budget and turns must be positive")
        self.prompt_version = prompt_version
        self.token_budget = token_budget
        self.turns = turns
        if finalizing_agent not in {"A", "B"}:
            raise ValueError("finalizing_agent must be A or B")
        self.finalizing_agent = finalizing_agent

    def run_condition(self, instance: FamilyInstance, condition: BatteryCondition,
                      provider: BatteryProvider, *, pair_id: str | None = None,
                      run_id: str | None = None, finalizer_only: bool = False) -> BatteryRunResult:
        pair = pair_id or f"pair-{instance.instance_id}"
        run = run_id or f"comm-{condition.value.lower()}-{uuid.uuid4().hex}"
        log = CommunicationEventLog(run)
        log.record("run_started", "controller", payload={"condition": condition.value,
                                                           "prompt_version": self.prompt_version,
                                                           "token_budget": self.token_budget,
                                                           "finalizing_agent": self.finalizing_agent,
                                                           "finalizer_only": finalizer_only})
        board: list[dict[str, Any]] = []
        message_info: dict[str, Any] = {}
        rejected_writes: list[dict[str, Any]] = []
        received_information: dict[tuple[str, str], Any] = {}
        read_sequences: dict[tuple[str, str], int] = {}
        used_outputs: list[tuple[str, str, tuple[str, ...], str | None]] = []
        answers: dict[str, str | None] = {"A": None, "B": None}
        invalid: list[str] = []
        agents = (self.finalizing_agent,) if finalizer_only else ("A", "B")
        for turn in range(self.turns):
            for agent in agents:
                if condition is BatteryCondition.FULL:
                    view = instance.agent_view(agent, "FULL")
                else:
                    view = instance.agent_view(agent, condition.value)
                view = {**view, "is_finalizer": agent == self.finalizing_agent,
                        "finalizing_agent": self.finalizing_agent}
                visible = tuple(row for row in board if row["author"] != agent) if condition is BatteryCondition.COMM else ()
                for row in visible:
                    received_info = instance.information(agent, row["text"], row["message_id"])
                    received_information[(agent, row["message_id"])] = received_info
                    read_event = log.peer_read(agent, received_info, exposure_id=f"turn-{turn}")
                    if read_event is not None:
                        read_sequences[(agent, row["message_id"])] = read_event.sequence
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
                                 logprob_mass_coverage=response.logprob_mass_coverage,
                                 logprob_status=response.logprob_status,
                                 input_tokens=response.input_tokens,
                                 output_tokens=response.output_tokens,
                                 cost_usd=response.cost_usd)
                used_outputs.append((agent, output_id, response.used_message_ids, response.answer))
                if response.answer is not None:
                    answers[agent] = response.answer
                if condition is BatteryCondition.COMM and response.message:
                    message_id = f"message-{agent}-{turn}"
                    if not instance.holds_claim(agent, response.message):
                        # Treatment grammar: a writer may submit only an exact claim
                        # from its own private clues. Record the rejected write
                        # explicitly instead of silently dropping or accepting it.
                        owner = instance.claim_owner(response.message)
                        log.record("board_write_rejected", agent, status="rejected",
                                   payload={"reason": "claim_not_owned_by_writer",
                                            "raw_text": response.message, "claim_owner": owner})
                        rejected_writes.append({"agent": agent, "turn": turn,
                                                "text": response.message, "claim_owner": owner,
                                                "reason": "claim_not_owned_by_writer"})
                        continue
                    receiver = "B" if agent == "A" else "A"
                    # Transmitted information is measured against the receiver's
                    # feasible set: the writer already knows its own claim, so a
                    # writer-perspective value would report zero bits even when
                    # the message genuinely narrows the peer's set.
                    info = instance.information(receiver, response.message, message_id)
                    message_info[message_id] = info
                    row = {"message_id": message_id, "author": agent, "receiver": receiver,
                           "text": response.message, "status": info.status,
                           "delta_i_bits": info.delta_i_bits,
                           "message_tokens": len(response.message.split())}
                    board.append(row)
                    log.board_write(agent, info, message_tokens=row["message_tokens"],
                                    receiver_id=receiver)
        outcomes = {agent: instance.validate(answer) if answer is not None else {"accepted": False, "score": None}
                    for agent, answer in answers.items()}
        final_outcome = outcomes[self.finalizing_agent]
        task_success = bool(final_outcome.get("accepted", False))
        output_sequences = {event.output_id: event.sequence for event in log.events if event.kind == "model_output"}
        for agent, output_id, _self_reported_ids, answer in used_outputs:
            if agent != self.finalizing_agent or not task_success:
                continue
            for (received_agent, used_id), info in received_information.items():
                if received_agent != agent:
                    continue
                row = next((item for item in board if item["message_id"] == used_id), None)
                read_sequence = read_sequences.get((agent, used_id))
                output_sequence = output_sequences.get(output_id)
                if (info is None or row is None or row["author"] == agent
                        or read_sequence is None or output_sequence is None
                        or output_sequence <= read_sequence):
                    continue
                prior_finalizer_success = any(
                    prior_agent == agent and prior_sequence < read_sequence and
                    instance.validate(prior_answer).get("accepted", False)
                    for prior_agent, prior_output, _ids, prior_answer in used_outputs
                    for prior_sequence in [output_sequences.get(prior_output)]
                    if prior_sequence is not None and prior_answer is not None
                )
                if info.useful and not prior_finalizer_success and instance.validate(answer or "").get("accepted", False):
                    log.post_read_correlation(agent, info, output_id,
                                              checker_evidence={"evidence_class": "post_read_correlation",
                                                                "task_checker": instance.checker_id,
                                                                "answer_accepted": True,
                                                                "uptake_rule": "first_checker_accepted_finalizer_output_after_peer_read",
                                                                "prior_finalizer_success": False})
        status = "invalid" if invalid else "completed"
        task_success = task_success and status == "completed"
        artifact = {
            "run_id": run, "pair_id": pair, "condition": condition.value,
            "family": instance.family, "instance_id": instance.instance_id, "seed": instance.seed,
            "provider": getattr(provider, "provider", type(provider).__name__),
            "provider_version": getattr(provider, "version", "unknown"),
            "model_id": getattr(provider, "model", "unknown"),
            "prompt_version": self.prompt_version, "task_success": task_success,
            "finalizing_agent": self.finalizing_agent,
            "answers_present": sorted(agent for agent, answer in answers.items() if answer is not None),
            "invalid_agents": invalid, "rejected_writes": rejected_writes,
            "task": instance.public_manifest(),
            "events": log.summary(),
        }
        return BatteryRunResult(run, pair, instance.instance_id, condition, instance.family, instance.seed,
                                artifact["provider"], artifact["provider_version"], self.prompt_version,
                                status, task_success, answers, tuple(invalid), log.summary(), artifact,
                                artifact["model_id"])

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
