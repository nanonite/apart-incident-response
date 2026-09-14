"""Separately gated, event-aligned logprob entropy extension."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping

from .communication_events import CommunicationEvent


ENTROPY_EXTENSION_VERSION = "post-read-logprob-v1"
MIN_TOPK_COVERAGE = 0.95


@dataclass(frozen=True)
class LogprobObservation:
    output_id: str
    agent_id: str
    sequence: int
    logprobs: tuple[float, ...]
    coverage: float | None
    full_logits: bool = False
    status: str = "complete"

    def entropy_bits(self) -> float | None:
        if self.status != "complete" or (not self.full_logits and (self.coverage is None or self.coverage < MIN_TOPK_COVERAGE)):
            return None
        if not self.logprobs:
            return None
        probabilities = [math.exp(value) for value in self.logprobs]
        total = sum(probabilities)
        if total <= 0 or not math.isfinite(total):
            return None
        probabilities = [value / total for value in probabilities]
        return -sum(probability * math.log2(probability) for probability in probabilities if probability > 0)


def first_post_read_outputs(events: Iterable[CommunicationEvent]) -> list[dict[str, Any]]:
    """Join each exposure to the first subsequent output that cites it."""

    rows: list[dict[str, Any]] = []
    ordered = list(events)
    reads = [event for event in ordered if event.kind == "peer_read_exposure"]
    outputs = [event for event in ordered if event.kind == "model_output"]
    for read in reads:
        output = next((event for event in outputs if event.agent_id == read.agent_id and event.sequence > read.sequence
                       and read.message_id in (event.payload or {}).get("exposed_message_ids", [])), None)
        if output is None:
            rows.append({"message_id": read.message_id, "agent_id": read.agent_id,
                         "output_id": None, "status": "missing_post_read_output"})
            continue
        payload = output.payload or {}
        coverage = payload.get("logprob_coverage")
        rows.append({"message_id": read.message_id, "agent_id": read.agent_id,
                     "output_id": output.output_id, "sequence": output.sequence,
                     "entropy_bits": payload.get("logprob_entropy_bits"),
                     "coverage": coverage,
                     "status": payload.get("logprob_status", "not_requested"),
                     "event_alignment": "first_model_output_after_peer_read"})
    return rows


def coverage_gate(observations: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(observations)
    complete = [row for row in rows if row.get("entropy_bits") is not None and
                row.get("status") in {"complete", "full_logits"}]
    return {
        "requested": len(rows), "complete": len(complete),
        "coverage_fraction": len(complete) / len(rows) if rows else 0.0,
        "status": "pass" if rows and len(complete) == len(rows) else "incomplete_logprob_coverage",
        "invalid_runs_retained": len(rows) - len(complete),
    }


def matched_placebo(real_messages: Iterable[Mapping[str, Any]], foreign_messages: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Create a timing/volume-matched placebo manifest without claiming semantic equivalence."""

    real, foreign = list(real_messages), list(foreign_messages)
    rows = []
    for index, message in enumerate(real):
        placebo = foreign[index % len(foreign)] if foreign else None
        rows.append({"index": index, "real_message_id": message.get("message_id"),
                     "placebo_message_id": placebo.get("message_id") if placebo else None,
                     "target_token_count": message.get("message_tokens"),
                     "placebo_token_count": placebo.get("message_tokens") if placebo else None,
                     "matching_status": "yoked" if placebo else "missing_placebo"})
    return rows


def entropy_extension_report(events: Iterable[CommunicationEvent], *, turn8_gate: bool = False) -> dict[str, Any]:
    observations = first_post_read_outputs(events)
    return {
        "extension_version": ENTROPY_EXTENSION_VERSION,
        "hypotheses": {
            "H0_context_perturbation": "any exposed text can alter output entropy",
            "H1_information_gain": "objective Delta I_m predicts post-read entropy change",
        },
        "event_alignment": "first_model_output_after_peer_read",
        "turn8_gate": {"enabled": turn8_gate, "separate_intervention": True},
        "coverage": coverage_gate(observations),
        "observations": observations,
        "read_event_entropy_is_not_used": True,
    }


__all__ = [
    "ENTROPY_EXTENSION_VERSION", "LogprobObservation", "coverage_gate",
    "entropy_extension_report", "first_post_read_outputs", "matched_placebo",
]
