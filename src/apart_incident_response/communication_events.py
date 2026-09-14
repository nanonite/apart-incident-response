"""Append-only provenance for board exposure, model outputs, and checker use."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
import time
import uuid
from typing import Any, Iterable, Mapping

from .finite_information import MessageInformation


def _json_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class CommunicationEvent:
    event_id: str
    run_id: str
    kind: str
    agent_id: str
    sequence: int
    monotonic_ns: int
    message_id: str | None = None
    delta_i_bits: float | None = None
    message_tokens: int | None = None
    output_id: str | None = None
    status: str | None = None
    useful: bool | None = None
    payload: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CommunicationEventLog:
    """In-memory append-only log suitable for fixture runs and replay tests."""

    def __init__(self, run_id: str, clock: callable = time.monotonic_ns) -> None:
        if not run_id:
            raise ValueError("run_id is required")
        self.run_id = run_id
        self.clock = clock
        self._events: list[CommunicationEvent] = []
        self._read_keys: set[tuple[str, str, str]] = set()

    @property
    def events(self) -> tuple[CommunicationEvent, ...]:
        return tuple(self._events)

    def record(self, kind: str, agent_id: str, *, message_id: str | None = None,
               delta_i_bits: float | None = None, message_tokens: int | None = None,
               output_id: str | None = None, status: str | None = None,
               useful: bool | None = None, payload: Mapping[str, Any] | None = None) -> CommunicationEvent:
        event = CommunicationEvent(uuid.uuid4().hex, self.run_id, kind, agent_id,
                                   len(self._events), self.clock(), message_id,
                                   delta_i_bits, message_tokens, output_id, status, useful,
                                   dict(payload or {}))
        self._events.append(event)
        return event

    def board_write(self, agent_id: str, message: MessageInformation, *, message_tokens: int) -> CommunicationEvent:
        return self.record("board_write", agent_id, message_id=message.message_id,
                           delta_i_bits=message.delta_i_bits, message_tokens=message_tokens,
                           status=message.status, useful=message.useful,
                           payload={"raw_text": message.raw_text, "normalized_claim": message.normalized_claim})

    def peer_read(self, agent_id: str, message: MessageInformation, *, exposure_id: str | None = None) -> CommunicationEvent | None:
        # Re-reading an already exposed message is an idempotent read for
        # provenance; the first exposure remains the causal anchor.
        key = (agent_id, message.message_id, "default")
        if key in self._read_keys:
            return None
        self._read_keys.add(key)
        return self.record("peer_read_exposure", agent_id, message_id=message.message_id,
                           delta_i_bits=message.delta_i_bits, status=message.status,
                           payload={"exposure_id": exposure_id or "default"})

    def model_output(self, agent_id: str, output_id: str, *, exposed_message_ids: Iterable[str] = (),
                     logprob_entropy_bits: float | None = None,
                     logprob_coverage: float | None = None,
                     logprob_mass_coverage: float | None = None,
                     logprob_status: str = "not_requested", input_tokens: int | None = None,
                     output_tokens: int | None = None, cost_usd: float = 0.0) -> CommunicationEvent:
        """Record output-time probability data, never read-time entropy."""

        return self.record("model_output", agent_id, output_id=output_id,
                           payload={"exposed_message_ids": list(exposed_message_ids),
                                    "logprob_entropy_bits": logprob_entropy_bits,
                                    "logprob_coverage": logprob_coverage,
                                    "logprob_mass_coverage": logprob_mass_coverage,
                                    "logprob_status": logprob_status,
                                    "input_tokens": input_tokens, "output_tokens": output_tokens,
                                    "cost_usd": cost_usd})

    def verified_use(self, agent_id: str, message: MessageInformation, output_id: str,
                     *, checker_evidence: Mapping[str, Any]) -> CommunicationEvent:
        if not checker_evidence.get("verified", False):
            raise ValueError("useful communication requires checker evidence")
        return self.record("verified_use", agent_id, message_id=message.message_id,
                           delta_i_bits=message.delta_i_bits, output_id=output_id,
                           useful=message.useful, payload={"checker_evidence": dict(checker_evidence)})

    def replay_joins(self) -> list[dict[str, Any]]:
        writes = {event.message_id: event for event in self._events if event.kind == "board_write" and event.message_id}
        reads = [event for event in self._events if event.kind == "peer_read_exposure"]
        outputs = [event for event in self._events if event.kind == "model_output"]
        uses = [event for event in self._events if event.kind == "verified_use"]
        rows: list[dict[str, Any]] = []
        for read in reads:
            write = writes.get(read.message_id)
            if write is None:
                continue
            output = next((event for event in outputs if event.agent_id == read.agent_id and
                           event.sequence > read.sequence and read.message_id in
                           (event.payload or {}).get("exposed_message_ids", [])), None)
            use = next((event for event in uses if event.agent_id == read.agent_id and
                        event.message_id == read.message_id and
                        (output is None or event.sequence >= output.sequence)), None)
            rows.append({"message_id": read.message_id, "writer_agent": write.agent_id,
                         "reader_agent": read.agent_id, "write_sequence": write.sequence,
                         "read_sequence": read.sequence, "first_post_read_output_id": output.output_id if output else None,
                         "verified_use_sequence": use.sequence if use else None,
                         "delta_i_bits": write.delta_i_bits, "useful": use.useful if use else False,
                         "status": "joined" if output else "read_without_post_exposure_output"})
        return rows

    def summary(self) -> dict[str, Any]:
        started = next((event for event in self._events if event.kind == "run_started"), None)
        writes = [event for event in self._events if event.kind == "board_write"]
        joins = self.replay_joins()
        transmitted = [event.delta_i_bits for event in writes if event.delta_i_bits is not None]
        tokens = [event.message_tokens for event in writes if event.message_tokens]
        useful = [row for row in joins if row["useful"] and row["delta_i_bits"] is not None]
        outputs = [event for event in self._events if event.kind == "model_output"]
        logprob_rows = [event for event in outputs if (event.payload or {}).get("logprob_status") not in {None, "not_requested", "unavailable"}]
        def latency(kind: str) -> float | None:
            if started is None:
                return None
            event = next((item for item in self._events if item.kind == kind), None)
            return (event.monotonic_ns - started.monotonic_ns) / 1_000_000_000 if event else None

        return {
            "run_id": self.run_id,
            "message_count": len(writes),
            "transmitted_bits": sum(transmitted) if transmitted else 0.0,
            "verified_useful_bits": sum(row["delta_i_bits"] for row in useful),
            "communication_tokens": sum(tokens),
            "input_tokens": sum((event.payload or {}).get("input_tokens") or 0 for event in outputs),
            "output_tokens": sum((event.payload or {}).get("output_tokens") or 0 for event in outputs),
            "provider_cost_usd": sum(float((event.payload or {}).get("cost_usd") or 0.0) for event in outputs),
            "bits_per_communication_token": sum(transmitted) / sum(tokens) if sum(tokens) else None,
            "verified_use_count": len(useful),
            "logprob_output_count": len(logprob_rows),
            "logprob_complete_output_count": sum((event.payload or {}).get("logprob_status") == "complete" for event in logprob_rows),
            "logprob_coverage": [(event.payload or {}).get("logprob_coverage") for event in logprob_rows],
            "logprob_mass_coverage": [(event.payload or {}).get("logprob_mass_coverage") for event in logprob_rows],
            "first_write_latency_seconds": latency("board_write"),
            "first_read_latency_seconds": latency("peer_read_exposure"),
            "first_verified_use_latency_seconds": latency("verified_use"),
            "event_count": len(self._events),
            "joins": joins,
            "event_hash": _json_hash({"events": [event.to_dict() for event in self._events]}),
        }


__all__ = ["CommunicationEvent", "CommunicationEventLog"]
