"""Exact finite feasible-set and validated-message information primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
from typing import Callable, Generic, Iterable, TypeVar


T = TypeVar("T", bound=object)


@dataclass(frozen=True)
class FeasibleSet(Generic[T]):
    """A finite candidate set whose contents remain controller-side data."""

    values: frozenset[T]

    @classmethod
    def from_values(cls, values: Iterable[T]) -> "FeasibleSet[T]":
        result = frozenset(values)
        if not result:
            raise ValueError("a feasible set must not be empty")
        return cls(result)

    @property
    def count(self) -> int:
        return len(self.values)

    @property
    def entropy_bits(self) -> float:
        return math.log2(self.count)

    def constrained(self, predicate: Callable[[T], bool]) -> "FeasibleSet[T]":
        narrowed = frozenset(value for value in self.values if predicate(value))
        if not narrowed:
            raise ValueError("constraint eliminates every feasible solution")
        return FeasibleSet(narrowed)

    def digest(self) -> str:
        encoded = "\n".join(sorted(repr(value) for value in self.values)).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class MessageInterpretation:
    """Controller validation result; unknown semantics never become zero bits."""

    status: str
    predicate: Callable[[object], bool] | None = field(default=None, compare=False, repr=False)
    reason: str | None = None
    normalized_claim: str | None = None

    @classmethod
    def accepted(cls, predicate: Callable[[object], bool], claim: str) -> "MessageInterpretation":
        if not claim.strip():
            raise ValueError("accepted claims must have normalized text")
        return cls("accepted", predicate, normalized_claim=claim)

    @classmethod
    def unknown(cls, reason: str) -> "MessageInterpretation":
        return cls("unknown", reason=reason)

    @classmethod
    def invalid(cls, reason: str) -> "MessageInterpretation":
        return cls("invalid", reason=reason)


@dataclass(frozen=True)
class MessageInformation:
    message_id: str
    raw_text: str
    status: str
    before_count: int
    after_count: int | None
    delta_i_bits: float | None
    normalized_claim: str | None
    reason: str | None

    @property
    def useful(self) -> bool:
        return self.status == "accepted" and self.delta_i_bits is not None and self.delta_i_bits > 0

    def to_public_dict(self) -> dict[str, object]:
        return {
            "message_id": self.message_id,
            "raw_text": self.raw_text,
            "status": self.status,
            "before_count": self.before_count,
            "after_count": self.after_count,
            "delta_i_bits": self.delta_i_bits,
            "normalized_claim": self.normalized_claim,
            "reason": self.reason,
        }


class ExactInformationEvaluator(Generic[T]):
    """Evaluate receiver-specific information after a validated message."""

    def evaluate(
        self,
        before: FeasibleSet[T],
        raw_text: str,
        interpretation: MessageInterpretation,
        message_id: str,
    ) -> MessageInformation:
        if not isinstance(raw_text, str):
            raise TypeError("message text must be a string")
        if not message_id:
            raise ValueError("message_id is required")
        if interpretation.status != "accepted" or interpretation.predicate is None:
            return MessageInformation(message_id, raw_text, interpretation.status, before.count,
                                       None, None, interpretation.normalized_claim,
                                       interpretation.reason or "message has no unambiguous interpretation")
        narrowed = frozenset(value for value in before.values if interpretation.predicate(value))
        if not narrowed:
            return MessageInformation(message_id, raw_text, "invalid", before.count, 0, None,
                                       interpretation.normalized_claim, "contradictory claim")
        delta = math.log2(before.count) - math.log2(len(narrowed))
        return MessageInformation(message_id, raw_text, "accepted", before.count, len(narrowed),
                                   delta, interpretation.normalized_claim, None)


def information_trajectory(
    initial: FeasibleSet[T],
    messages: Iterable[tuple[str, str, MessageInterpretation]],
) -> list[MessageInformation]:
    """Apply messages in order, retaining duplicate and invalid audit rows."""

    evaluator: ExactInformationEvaluator[T] = ExactInformationEvaluator()
    current = initial
    seen_claims: set[str] = set()
    trajectory: list[MessageInformation] = []
    for message_id, raw_text, interpretation in messages:
        claim = interpretation.normalized_claim
        if interpretation.status == "accepted" and claim in seen_claims:
            interpretation = MessageInterpretation.accepted(lambda _value: True, claim or "duplicate")
        result = evaluator.evaluate(current, raw_text, interpretation, message_id)
        trajectory.append(result)
        if result.status == "accepted" and result.after_count is not None:
            if claim:
                seen_claims.add(claim)
            if result.after_count != current.count:
                current = FeasibleSet.from_values(
                    value for value in current.values if interpretation.predicate and interpretation.predicate(value)
                )
    return trajectory


__all__ = [
    "ExactInformationEvaluator", "FeasibleSet", "MessageInformation",
    "MessageInterpretation", "information_trajectory",
]
