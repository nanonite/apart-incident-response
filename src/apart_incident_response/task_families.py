"""Deterministic six-family finite task battery.

The families intentionally share one contract but not one task surface.  Each
instance has an exact controller-side solution set, a validator, and claims
that can be interpreted only through the family oracle.  Generator hints are
recorded for calibration but never determine the R/H/N assignment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import itertools
import json
import random
from typing import Any, Callable, ClassVar, Iterable, Mapping

from .communication_protocol import (
    CellAssignment,
    DependenceRegime,
    ReasoningComplexity,
)
from .finite_information import ExactInformationEvaluator, FeasibleSet, MessageInformation, MessageInterpretation


GENERATOR_VERSION = "six-family-clue-consistent-v2"
CHECKER_VERSION = "oracle-v2"
# Only necessary (N) tasks are realized: the clue-consistent generator makes the
# joint feasible set a unique target. R/H would require redundant or partially
# narrowing claims that the current construction does not implement, so they are
# rejected rather than labelled misleadingly.
SUPPORTED_REGIMES: tuple[DependenceRegime, ...] = (DependenceRegime.N,)


def _instance_id(family: str, seed: int) -> str:
    return f"{family}-{seed:08x}"


def _sets(candidates: list[str], regime: DependenceRegime, seed: int) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """Return A-private, B-private, and joint sets with deterministic overlap."""

    rng = random.Random(seed)
    shuffled = list(candidates)
    rng.shuffle(shuffled)
    if regime is DependenceRegime.R:
        joint = frozenset(candidates)
        return joint, joint, joint
    if regime is DependenceRegime.H:
        joint = frozenset(shuffled[: max(2, len(candidates) // 2)])
        return frozenset(candidates), frozenset(candidates), joint
    joint = frozenset(shuffled[:1])
    return frozenset(candidates), frozenset(candidates), joint


@dataclass(frozen=True)
class Claim:
    text: str
    predicate: Callable[[str], bool] = field(compare=False, repr=False)


@dataclass(frozen=True)
class FamilyInstance:
    family: str
    instance_id: str
    seed: int
    complexity: ReasoningComplexity
    generator_hint: DependenceRegime
    solutions: frozenset[str] = field(repr=False)
    private_solutions: Mapping[str, frozenset[str]] = field(repr=False)
    joint_solutions: frozenset[str] = field(repr=False)
    claims: tuple[Claim, ...] = field(repr=False)
    public_data: Mapping[str, Any]
    private_clues: Mapping[str, tuple[str, ...]]
    target: str = field(repr=False)
    quality: Mapping[str, Any] = field(default_factory=dict)
    assignment: CellAssignment = field(init=False)

    def __post_init__(self) -> None:
        if self.generator_hint not in SUPPORTED_REGIMES:
            raise ValueError(
                f"unsupported regime {self.generator_hint.value}: {GENERATOR_VERSION} only realizes "
                "necessary (N) tasks with a unique clue-consistent target")
        clue_consistent_a = self.clue_consistent(self.private_clues.get("A", ()))
        clue_consistent_b = self.clue_consistent(self.private_clues.get("B", ()))
        pooled = self.clue_consistent(self.pooled_private_clues())
        if not pooled:
            raise ValueError("pooled private clues exclude every candidate")
        if not pooled <= self.solutions:
            raise ValueError("clue-consistent joint set must be a subset of the full set")
        if len(pooled) != 1:
            raise ValueError(
                "necessary (N) tasks require a unique clue-consistent target; "
                f"pooled clues leave {len(pooled)} candidates")
        if self.target not in pooled:
            raise ValueError("target must be in the clue-consistent joint set")
        # The clue-consistent sets are authoritative. The declared generator sets
        # are not trusted for D_idx, receiver I_m, trajectory or scoring.
        object.__setattr__(self, "private_solutions", {"A": clue_consistent_a, "B": clue_consistent_b})
        object.__setattr__(self, "joint_solutions", pooled)
        directional = {
            agent: _d_idx(self.private_solutions[agent], self.joint_solutions)
            for agent in ("A", "B")
        }
        object.__setattr__(self, "assignment", CellAssignment.from_directional(
            self.family, self.instance_id, self.complexity, directional, self.generator_hint.value
        ))

    @property
    def checker_id(self) -> str:
        return f"{self.family}-{CHECKER_VERSION}"

    def agent_view(self, agent: str, condition: str) -> dict[str, Any]:
        if agent not in self.private_solutions:
            raise ValueError("agent must be A or B")
        view = {
            "family": self.family,
            "instance_id": self.instance_id,
            "complexity": self.complexity.value,
            "agent_id": agent,
            "generator_version": GENERATOR_VERSION,
            "private_clues": list(self.private_clues.get(agent, ())),
            # Public option set only: the controller keeps the clue-consistent
            # private feasible set separate and never exposes it as the task menu.
            "candidate_count": len(self.solutions),
            "candidate_labels": sorted(self.solutions),
            "public_option_count": len(self.solutions),
            "task_instruction": "Choose one candidate and reply exactly as ANSWER: <candidate label>. In COMM only, you may optionally add MESSAGE: <exact private clue>; silence is allowed. Do not invent a label or claim message use.",
        }
        if condition == "FULL":
            # Leak-free invariant: FULL exposes the constraints, never the joint
            # candidate set (answer key). There is no model-visible field that
            # reveals the accepted answer.
            view["joint_clues"] = [claim.text for claim in self.claims]
            view["joint_candidate_count"] = len(self.joint_solutions)
        return view

    def public_manifest(self) -> dict[str, Any]:
        """Return safe metadata: no target, answer set, or private clue values."""

        return {
            "family": self.family,
            "instance_id": self.instance_id,
            "seed": self.seed,
            "complexity": self.complexity.value,
            "generator_hint": self.generator_hint.value,
            "generator_version": GENERATOR_VERSION,
            "public_data": dict(self.public_data),
            "quality": dict(self.quality),
            "assignment": self.assignment.to_dict(),
        }

    def interpret(self, raw_text: str) -> MessageInterpretation:
        normalized = raw_text.strip().casefold()
        matches = [claim for claim in self.claims if claim.text.casefold() == normalized]
        if len(matches) != 1:
            return MessageInterpretation.unknown("claim is not an unambiguous validated family message")
        return MessageInterpretation.accepted(matches[0].predicate, matches[0].text)

    def clue_consistent(self, clues: Iterable[str]) -> frozenset[str]:
        """Candidates consistent with a set of exact claim texts."""

        predicates = {claim.text: claim.predicate for claim in self.claims}
        return frozenset(value for value in self.solutions
                         if all(predicates[text](value) for text in clues if text in predicates))

    def pooled_private_clues(self) -> tuple[str, ...]:
        """Union of both agents' private clues; the maximum a COMM channel can convey."""

        return tuple(self.private_clues.get("A", ())) + tuple(self.private_clues.get("B", ()))

    def claim_owner(self, raw_text: str) -> str | None:
        """Agent that privately holds an exact claim, or None if nobody holds it."""

        normalized = raw_text.strip().casefold()
        for agent in ("A", "B"):
            for text in self.private_clues.get(agent, ()):
                if text.strip().casefold() == normalized:
                    return agent
        return None

    def holds_claim(self, agent: str, raw_text: str) -> bool:
        """A writer may submit only an exact claim from its own private clues."""

        return self.claim_owner(raw_text) == agent

    def channel_analysis(self) -> dict[str, Any]:
        """Audit the distributed private clues against the joint feasible set.

        ``channel_complete`` requires the pooled clue-consistent set to *equal*
        the joint set, not merely contain it: a subset check passes an
        under-constrained channel that still leaves extra candidates.
        ``both_agents_needed`` requires each agent's clue set to strictly
        narrow relative to the pooled set; ``finalizer_needs_peer`` is the
        A-finalizer-specific requirement relative to the joint set.
        """

        clue_a = self.private_clues.get("A", ())
        clue_b = self.private_clues.get("B", ())
        clue_consistent_a = self.clue_consistent(clue_a)
        clue_consistent_b = self.clue_consistent(clue_b)
        pooled = self.clue_consistent(self.pooled_private_clues())
        joint = self.joint_solutions
        declared_a = self.private_solutions["A"]
        declared_b = self.private_solutions["B"]
        claim_texts = {claim.text for claim in self.claims}
        held_a = set(clue_a)
        held_b = set(clue_b)
        return {
            "private_a_size": len(clue_consistent_a),
            "private_b_size": len(clue_consistent_b),
            "pooled_size": len(pooled),
            "joint_size": len(joint),
            "clue_consistent_a": sorted(clue_consistent_a),
            "clue_consistent_b": sorted(clue_consistent_b),
            "pooled_values": sorted(pooled),
            "declared_private_a_size": len(declared_a),
            "declared_private_b_size": len(declared_b),
            "declared_matches_clue_consistent_a": clue_consistent_a == declared_a,
            "declared_matches_clue_consistent_b": clue_consistent_b == declared_b,
            "claims_partitioned": held_a.isdisjoint(held_b) and (held_a | held_b) == claim_texts,
            "covers_joint": joint <= pooled,
            "pooled_equals_joint": pooled == joint,
            "channel_complete": pooled == joint,
            "both_agents_needed": len(clue_consistent_a) > len(pooled) and len(clue_consistent_b) > len(pooled),
            "finalizer_needs_peer": len(clue_consistent_a) > len(joint),
        }

    def information(self, agent: str, raw_text: str, message_id: str) -> MessageInformation:
        before = FeasibleSet.from_values(self.private_solutions[agent])
        return ExactInformationEvaluator().evaluate(before, raw_text, self.interpret(raw_text), message_id)

    def validate(self, submission: str) -> dict[str, Any]:
        accepted = submission in self.joint_solutions
        return {"accepted": accepted, "score": 1.0 if accepted else 0.0,
                "checker": self.checker_id, "submission": submission,
                "generator_version": GENERATOR_VERSION,
                "solution_criterion": "unique_joint_target"}

    def trajectory(self, agent: str, claim_texts: Iterable[str]) -> list[MessageInformation]:
        current = FeasibleSet.from_values(self.private_solutions[agent])
        results: list[MessageInformation] = []
        for index, text in enumerate(claim_texts):
            interpretation = self.interpret(text)
            result = ExactInformationEvaluator().evaluate(current, text, interpretation, f"m-{index}")
            results.append(result)
            if result.status == "accepted" and result.after_count and interpretation.predicate:
                current = FeasibleSet.from_values(value for value in current.values if interpretation.predicate(value))
        return results


def _d_idx(private: Iterable[str], joint: Iterable[str]) -> float | None:
    private_set, joint_set = set(private), set(joint)
    if not private_set or not joint_set or not joint_set <= private_set:
        return None
    if len(private_set) <= 1:
        return 0.0
    import math
    return (math.log2(len(private_set)) - math.log2(len(joint_set))) / math.log2(len(private_set))


def _claims_for_bits(values: list[str], target: str, depth: int = 3) -> tuple[Claim, ...]:
    number = int(target.rsplit("-", 1)[-1])
    claims: list[Claim] = []
    for bit in range(depth):
        bit_value = (number >> bit) & 1
        text = f"bit{bit}={bit_value}"
        claims.append(Claim(text, lambda value, bit=bit, bit_value=bit_value: ((int(value.rsplit("-", 1)[-1]) >> bit) & 1) == bit_value))
    return tuple(claims)


class HypothesisFamily:
    name: ClassVar[str] = "hypothesis"

    @staticmethod
    def generate(seed: int, regime: DependenceRegime = DependenceRegime.N, complexity: ReasoningComplexity = ReasoningComplexity.LOW) -> FamilyInstance:
        candidates = [f"candidate-{i}" for i in range(8)]
        a, b, joint = _sets(candidates, regime, seed)
        target = sorted(joint)[seed % len(joint)]
        number = int(target.rsplit("-", 1)[-1])
        claims = _claims_for_bits(candidates, target)
        if complexity is ReasoningComplexity.MEDIUM:
            parity = number % 2
            claims = claims + (Claim(f"derived parity={parity}",
                lambda value, expected=parity: int(value.rsplit("-", 1)[-1]) % 2 == expected),)
        if complexity is ReasoningComplexity.HIGH:
            checksum = sum(int(digit) for digit in str(number)) % 2
            claims = claims + (Claim(f"chained checksum={checksum}",
                lambda value, expected=checksum: sum(int(digit) for digit in value.rsplit("-", 1)[-1]) % 2 == expected),)
        return FamilyInstance("hypothesis", _instance_id("hypothesis", seed), seed, complexity, regime,
            frozenset(candidates), {"A": a, "B": b}, joint, claims,
            {"candidate_count": 8, "predicate_style": complexity.value},
            {"A": tuple(c.text for c in claims[0::2]), "B": tuple(c.text for c in claims[1::2])}, target)


class ReferenceFamily:
    name: ClassVar[str] = "reference"

    @staticmethod
    def generate(seed: int, regime: DependenceRegime = DependenceRegime.N, complexity: ReasoningComplexity = ReasoningComplexity.LOW) -> FamilyInstance:
        candidates = [f"object-{i}" for i in range(16)]
        a, b, joint = _sets(candidates, regime, seed + 17)
        target = sorted(joint)[seed % len(joint)]
        target_number = int(target.rsplit("-", 1)[-1])
        claims = tuple(Claim(f"attribute{bit}={((target_number >> bit) & 1)}",
            lambda value, bit=bit, expected=(target_number >> bit) & 1: ((int(value.rsplit("-", 1)[-1]) >> bit) & 1) == expected)
            for bit in range(4))
        if complexity is ReasoningComplexity.HIGH:
            claims += (Claim("relation=linked", lambda value: int(value.rsplit("-", 1)[-1]) % 3 == target_number % 3),)
        return FamilyInstance("reference", _instance_id("reference", seed), seed, complexity, regime,
            frozenset(candidates), {"A": a, "B": b}, joint, claims,
            {"object_count": 16, "attribute_kinds": ["color", "shape", "relation"]},
            {"A": tuple(c.text for c in claims[0::2]), "B": tuple(c.text for c in claims[1::2])}, target)


def _plans(actions: tuple[str, ...]) -> list[str]:
    return [">".join(order) for order in itertools.permutations(actions)]


class PlanningFamily:
    name: ClassVar[str] = "planning"

    @staticmethod
    def generate(seed: int, regime: DependenceRegime = DependenceRegime.N, complexity: ReasoningComplexity = ReasoningComplexity.LOW) -> FamilyInstance:
        actions = ("inspect", "stage", "deploy") if complexity is not ReasoningComplexity.HIGH else ("inspect", "stage", "approve", "deploy")
        candidates = _plans(actions)
        a, b, joint = _sets(candidates, regime, seed + 31)
        target = sorted(joint)[seed % len(joint)]
        required = target.split(">")
        claims = tuple(Claim(f"precedes={left}>{right}", lambda value, left=left, right=right: value.index(left) < value.index(right))
                       for left, right in zip(required, required[1:]))
        claims += (Claim("budget=valid", lambda value: len(value.split(">")) == len(actions)),)
        return FamilyInstance("planning", _instance_id("planning", seed), seed, complexity, regime,
            frozenset(candidates), {"A": a, "B": b}, joint, claims,
            {"action_count": len(actions), "resource_model": "bounded-enumeration", "budget": len(actions)},
            {"A": tuple(c.text for c in claims[0::2]), "B": tuple(c.text for c in claims[1::2])}, target)


class PoetryFamily:
    name: ClassVar[str] = "poetry"

    @staticmethod
    def generate(seed: int, regime: DependenceRegime = DependenceRegime.N, complexity: ReasoningComplexity = ReasoningComplexity.LOW) -> FamilyInstance:
        skeletons = [f"skeleton-{i}" for i in range(8)]
        a, b, joint = _sets(skeletons, regime, seed + 43)
        target = sorted(joint)[seed % len(joint)]
        number = int(target.rsplit("-", 1)[-1])
        claims = (Claim(f"meter={number & 1}", lambda value, expected=number & 1: int(value.rsplit("-", 1)[-1]) & 1 == expected),
                       Claim(f"rhyme={(number >> 1) & 1}", lambda value, expected=(number >> 1) & 1: (int(value.rsplit("-", 1)[-1]) >> 1) & 1 == expected),
                       Claim(f"acrostic={(number >> 2) & 1}", lambda value, expected=(number >> 2) & 1: (int(value.rsplit("-", 1)[-1]) >> 2) & 1 == expected))
        return FamilyInstance("poetry", _instance_id("poetry", seed), seed, complexity, regime,
            frozenset(skeletons), {"A": a, "B": b}, joint, claims,
            {"skeleton_count": 8, "creative_realization": "scored separately", "hard_constraints": ["meter", "rhyme", "acrostic"]},
            {"A": tuple(c.text for c in claims[0::2]), "B": tuple(c.text for c in claims[1::2])}, target,
            {"creative_quality_is_information": False})


class LegalFamily:
    name: ClassVar[str] = "legal"

    @staticmethod
    def generate(seed: int, regime: DependenceRegime = DependenceRegime.N, complexity: ReasoningComplexity = ReasoningComplexity.LOW) -> FamilyInstance:
        outcomes = [f"disposition-{i}" for i in range(8)]
        a, b, joint = _sets(outcomes, regime, seed + 59)
        target = sorted(joint)[seed % len(joint)]
        number = int(target.rsplit("-", 1)[-1])
        claims = tuple(Claim(f"fictional_fact_{bit}={((number >> bit) & 1)}",
            lambda value, bit=bit, expected=(number >> bit) & 1: ((int(value.rsplit("-", 1)[-1]) >> bit) & 1) == expected)
            for bit in range(3))
        return FamilyInstance("legal", _instance_id("legal", seed), seed, complexity, regime,
            frozenset(outcomes), {"A": a, "B": b}, joint, claims,
            {"jurisdiction": "fictional-closed-world", "rule_engine": "legal-oracle-v1", "external_sources": False},
            {"A": tuple(c.text for c in claims[0::2]), "B": tuple(c.text for c in claims[1::2])}, target)


class LexiconFamily:
    name: ClassVar[str] = "lexicon"

    @staticmethod
    def generate(seed: int, regime: DependenceRegime = DependenceRegime.N, complexity: ReasoningComplexity = ReasoningComplexity.LOW) -> FamilyInstance:
        sequences = [f"relay-{i:02d}" for i in range(8)]
        a, b, joint = _sets(sequences, regime, seed + 71)
        target = sorted(joint)[seed % len(joint)]
        number = int(target.rsplit("-", 1)[-1])
        claims = tuple(Claim(f"relay_step_{bit}={((number >> bit) & 1)}",
            lambda value, bit=bit, expected=(number >> bit) & 1: ((int(value.rsplit("-", 1)[-1]) >> bit) & 1) == expected)
            for bit in range(3))
        return FamilyInstance("lexicon", _instance_id("lexicon", seed), seed, complexity, regime,
            frozenset(sequences), {"A": a, "B": b}, joint, claims,
            {"lexicon_size": 8, "alternation": "A->B->A->B", "dictionary_dump": "valid strategy if attempted"},
            {"A": tuple(c.text for c in claims[0::2]), "B": tuple(c.text for c in claims[1::2])}, target)


FAMILY_GENERATORS: Mapping[str, Any] = {
    "hypothesis": HypothesisFamily,
    "reference": ReferenceFamily,
    "planning": PlanningFamily,
    "poetry": PoetryFamily,
    "legal": LegalFamily,
    "lexicon": LexiconFamily,
}


def generate_instance(family: str, seed: int, regime: DependenceRegime = DependenceRegime.N,
                      complexity: ReasoningComplexity = ReasoningComplexity.LOW) -> FamilyInstance:
    if regime not in SUPPORTED_REGIMES:
        raise ValueError(
            f"unsupported regime {regime.value}: {GENERATOR_VERSION} supports "
            f"{[item.value for item in SUPPORTED_REGIMES]}")
    try:
        generator = FAMILY_GENERATORS[family]
    except KeyError as exc:
        raise ValueError(f"unknown task family: {family}") from exc
    return generator.generate(seed, regime, complexity)


def generate_grid(family: str, seed: int = 1,
                  regimes: Iterable[DependenceRegime] = SUPPORTED_REGIMES) -> list[FamilyInstance]:
    """Generate independent deterministic fixtures for supported regime x complexity cells."""

    return [generate_instance(family, seed + index, regime, complexity)
            for index, (regime, complexity) in enumerate(
                itertools.product(regimes, ReasoningComplexity)
            )]


def validate_family_grid(family: str, seed: int = 1) -> dict[str, Any]:
    instances = generate_grid(family, seed)
    return {
        "family": family,
        "generator_version": GENERATOR_VERSION,
        "supported_regimes": [item.value for item in SUPPORTED_REGIMES],
        "instances": len(instances),
        "cells": [instance.assignment.to_dict() for instance in instances],
        "all_finite": all(instance.solutions and instance.joint_solutions for instance in instances),
        "all_valid": all(instance.validate(instance.target)["accepted"] for instance in instances),
        "unique_ids": len({instance.instance_id for instance in instances}) == len(instances),
    }


def preregistered_manifest(instances: Iterable[FamilyInstance]) -> dict[str, Any]:
    """Deterministic, leak-safe manifest of frozen instances for preregistration."""

    rows: list[dict[str, Any]] = []
    for instance in instances:
        analysis = instance.channel_analysis()
        manifest = instance.public_manifest()
        manifest["channel"] = {key: analysis[key] for key in (
            "private_a_size", "private_b_size", "pooled_size", "joint_size",
            "channel_complete", "both_agents_needed", "finalizer_needs_peer")}
        rows.append(manifest)
    blob = json.dumps(rows, sort_keys=True)
    return {
        "generator_version": GENERATOR_VERSION,
        "checker_version": CHECKER_VERSION,
        "regime": "N",
        "channel_complete_required": True,
        "instance_count": len(rows),
        "instances": rows,
        "manifest_hash": hashlib.sha256((GENERATOR_VERSION + blob).encode()).hexdigest(),
        "no_live_screen": True,
    }


def audit_channel_invariants(instances: Iterable[FamilyInstance]) -> dict[str, Any]:
    """Offline audit of pooled/joint equality, peer necessity and declared-set mismatch.

    This is a protocol invariant check, not a live screen. It flags any instance
    whose pooled clue-consistent set does not *equal* the joint set, any
    instance where a single agent already suffices, and any mismatch between the
    declared ``private_solutions`` and the clue-consistent feasible set (the
    input contract for the feasible-set reconciliation work).
    """

    rows: list[dict[str, Any]] = []
    for instance in instances:
        analysis = instance.channel_analysis()
        rows.append({
            "instance_id": instance.instance_id,
            "family": instance.family,
            "complexity": instance.complexity.value,
            "regime": instance.assignment.regime.value if instance.assignment.regime else None,
            **analysis,
        })
    incomplete = [row["instance_id"] for row in rows if not row["channel_complete"]]
    declared_mismatch = [row["instance_id"] for row in rows
                         if not (row["declared_matches_clue_consistent_a"]
                                 and row["declared_matches_clue_consistent_b"])]
    singleton_agent = [row["instance_id"] for row in rows
                       if row["private_a_size"] <= 1 or row["private_b_size"] <= 1]
    unpartitioned = [row["instance_id"] for row in rows if not row["claims_partitioned"]]
    return {
        "audit_version": "channel-invariants-v1",
        "instance_count": len(rows),
        "channel_complete_count": len(rows) - len(incomplete),
        "channel_incomplete_ids": incomplete,
        "both_agents_needed_count": sum(row["both_agents_needed"] for row in rows),
        "finalizer_needs_peer_count": sum(row["finalizer_needs_peer"] for row in rows),
        "singleton_agent_ids": singleton_agent,
        "unpartitioned_claims_ids": unpartitioned,
        "declared_mismatch_count": len(declared_mismatch),
        "declared_mismatch_ids": declared_mismatch,
        "rows": rows,
        "no_live_screen": True,
    }


__all__ = [
    "Claim", "FamilyInstance", "FAMILY_GENERATORS", "HypothesisFamily", "LegalFamily",
    "LexiconFamily", "PlanningFamily", "PoetryFamily", "ReferenceFamily",
    "GENERATOR_VERSION", "CHECKER_VERSION", "SUPPORTED_REGIMES",
    "audit_channel_invariants", "generate_grid", "generate_instance",
    "preregistered_manifest", "validate_family_grid",
]
