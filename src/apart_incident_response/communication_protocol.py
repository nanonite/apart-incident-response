"""Shared contract for the two-agent ISO/FULL/COMM battery.

This module is deliberately independent of the legacy C0/C1/C2 protocol.  It
contains only finite-set estimands and machine-readable treatment semantics;
model execution and task-family implementations live elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Any, Iterable, Mapping, Sequence


PROTOCOL_VERSION = "two-agent-iso-full-comm-v1"
DEPENDENCE_THRESHOLD_R = 0.10
DEPENDENCE_THRESHOLD_N = 0.50


class BatteryCondition(str, Enum):
    ISO = "ISO"
    FULL = "FULL"
    COMM = "COMM"


class DependenceRegime(str, Enum):
    R = "R"  # redundant: joint information barely narrows the set
    H = "H"  # helpful: joint information narrows the set but is not required
    N = "N"  # necessary: joint information substantially narrows the set


class ReasoningComplexity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def _count(value: int | Iterable[Any], label: str) -> int:
    count = value if isinstance(value, int) and not isinstance(value, bool) else len(set(value))
    if count < 0:
        raise ValueError(f"{label} must be non-negative")
    return count


def directional_d_idx(private: int | Iterable[Any], joint: int | Iterable[Any]) -> float | None:
    """Return normalized feasible-set reduction from private to joint.

    The denominator is the private uncertainty in bits.  A private set with
    zero or one candidate has no measurable dependence and is reported as
    ``0.0`` when the joint set is also valid, rather than manufacturing a
    division by zero.  An empty joint set is invalid and returns ``None``.
    """

    private_count = _count(private, "private feasible-set")
    joint_count = _count(joint, "joint feasible-set")
    if private_count == 0 or joint_count == 0 or joint_count > private_count:
        return None
    if private_count <= 1:
        return 0.0
    reduction_bits = math.log2(private_count) - math.log2(joint_count)
    return max(0.0, min(1.0, reduction_bits / math.log2(private_count)))


def average_d_idx(
    directional: Mapping[str, float | None] | Sequence[float | None],
) -> float | None:
    """Average measured directional reductions, preserving undefinedness."""

    values = list(directional.values()) if isinstance(directional, Mapping) else list(directional)
    usable = [value for value in values if value is not None]
    return sum(usable) / len(usable) if usable else None


def assign_dependence(d_idx: float | None) -> DependenceRegime | None:
    """Assign R/H/N from measured reduction, never from a generator label."""

    if d_idx is None or not math.isfinite(d_idx) or not 0.0 <= d_idx <= 1.0:
        return None
    if d_idx <= DEPENDENCE_THRESHOLD_R:
        return DependenceRegime.R
    if d_idx >= DEPENDENCE_THRESHOLD_N:
        return DependenceRegime.N
    return DependenceRegime.H


def c_need(p_full: float, p_iso: float) -> float:
    """Model-relative information need: P(success|FULL)-P(success|ISO)."""

    for value, name in ((p_full, "p_full"), (p_iso, "p_iso")):
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be a probability")
    return p_full - p_iso


def eta_comm(p_comm: float, p_iso: float, p_full: float) -> float | None:
    """Performance recovery, undefined when the FULL-ISO denominator is weak."""

    denominator = c_need(p_full, p_iso)
    if not math.isfinite(p_comm) or not 0.0 <= p_comm <= 1.0:
        raise ValueError("p_comm must be a probability")
    return (p_comm - p_iso) / denominator if denominator != 0.0 else None


@dataclass(frozen=True)
class CellAssignment:
    """Measured assignment for one family/complexity instance."""

    family: str
    instance_id: str
    complexity: ReasoningComplexity
    directional_d_idx: Mapping[str, float | None]
    d_idx: float | None
    regime: DependenceRegime | None
    generator_hint: str | None = None

    @classmethod
    def from_directional(
        cls,
        family: str,
        instance_id: str,
        complexity: ReasoningComplexity,
        directional: Mapping[str, float | None],
        generator_hint: str | None = None,
    ) -> "CellAssignment":
        measured = average_d_idx(directional)
        return cls(family, instance_id, complexity, dict(directional), measured,
                   assign_dependence(measured), generator_hint)

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "instance_id": self.instance_id,
            "complexity": self.complexity.value,
            "directional_d_idx": dict(self.directional_d_idx),
            "d_idx": self.d_idx,
            "regime": self.regime.value if self.regime else None,
            "generator_hint": self.generator_hint,
            "assignment_basis": "measured_feasible_set_reduction",
        }


@dataclass(frozen=True)
class BatteryProtocol:
    """Serializable preregistration contract for the new battery."""

    version: str = PROTOCOL_VERSION
    conditions: tuple[BatteryCondition, ...] = (
        BatteryCondition.ISO,
        BatteryCondition.FULL,
        BatteryCondition.COMM,
    )
    families: tuple[str, ...] = (
        "hypothesis",
        "reference",
        "planning",
        "poetry",
        "legal",
        "lexicon",
    )
    complexities: tuple[ReasoningComplexity, ...] = tuple(ReasoningComplexity)

    def __post_init__(self) -> None:
        if self.version != PROTOCOL_VERSION:
            raise ValueError(f"unsupported communication protocol: {self.version}")
        if self.conditions != tuple(BatteryCondition):
            raise ValueError("conditions must be ordered ISO, FULL, COMM")
        if len(set(self.families)) != 6:
            raise ValueError("the battery requires six distinct families")

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.version,
            "conditions": [condition.value for condition in self.conditions],
            "condition_semantics": {
                "ISO": {"private_information": True, "peer_channel": "none"},
                "FULL": {"private_information": False, "joint_information": True, "peer_channel": "not_needed"},
                "COMM": {"private_information": True, "peer_channel": "optional_message_board"},
            },
            "families": list(self.families),
            "complexities": [level.value for level in self.complexities],
            "dependence_assignment": {
                "measure": "average directional normalized feasible-set reduction",
                "R": f"d_idx <= {DEPENDENCE_THRESHOLD_R}",
                "H": f"{DEPENDENCE_THRESHOLD_R} < d_idx < {DEPENDENCE_THRESHOLD_N}",
                "N": f"d_idx >= {DEPENDENCE_THRESHOLD_N}",
            },
            "estimands": {
                "delta_i_m_bits": "log2(|S_before|)-log2(|S_after|)",
                "c_need": "P(success|FULL)-P(success|ISO)",
                "eta_comm": "(p_COMM-p_ISO)/(p_FULL-p_ISO), undefined when denominator is zero",
                "communication_efficiency": "verified useful bits / communication tokens",
            },
            "primary_contrasts": ["FULL-ISO", "COMM-ISO", "COMM recovery of FULL-ISO"],
            "invalidity_rules": [
                "empty or non-finite feasible set",
                "ambiguous or unvalidated message interpretation",
                "missing provider output or checker evidence",
                "incomplete requested logprob coverage",
            ],
            "leakage_rule": "answer keys and private solution sets never enter agent-visible artifacts",
        }


__all__ = [
    "BatteryCondition", "BatteryProtocol", "CellAssignment", "DependenceRegime",
    "ReasoningComplexity", "PROTOCOL_VERSION", "assign_dependence", "average_d_idx",
    "c_need", "directional_d_idx", "eta_comm",
]
