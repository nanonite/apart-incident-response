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
import random
from typing import Any, Callable, ClassVar, Iterable, Mapping

from .communication_protocol import (
    CellAssignment,
    DependenceRegime,
    ReasoningComplexity,
)
from .finite_information import ExactInformationEvaluator, FeasibleSet, MessageInformation, MessageInterpretation


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
        if self.target not in self.joint_solutions:
            raise ValueError("target must be in the joint feasible set")
        if not self.joint_solutions <= self.solutions:
            raise ValueError("joint solutions must be a subset of the full set")
        directional = {
            agent: _d_idx(self.private_solutions[agent], self.joint_solutions)
            for agent in ("A", "B")
        }
        object.__setattr__(self, "assignment", CellAssignment.from_directional(
            self.family, self.instance_id, self.complexity, directional, self.generator_hint.value
        ))

    def agent_view(self, agent: str, condition: str) -> dict[str, Any]:
        if agent not in self.private_solutions:
            raise ValueError("agent must be A or B")
        view = {
            "family": self.family,
            "instance_id": self.instance_id,
            "complexity": self.complexity.value,
            "agent_id": agent,
            "private_clues": list(self.private_clues.get(agent, ())),
            "candidate_count": len(self.private_solutions[agent]),
            "candidate_labels": sorted(self.private_solutions[agent]),
            "task_instruction": "Choose one candidate and reply exactly as ANSWER: <candidate label>. In COMM only, you may optionally add MESSAGE: <exact private clue>; silence is allowed. Do not invent a label or claim message use.",
        }
        if condition == "FULL":
            view["joint_clues"] = [claim.text for claim in self.claims]
            view["joint_candidate_count"] = len(self.joint_solutions)
            view["joint_candidate_labels"] = sorted(self.joint_solutions)
        return view

    def public_manifest(self) -> dict[str, Any]:
        """Return safe metadata: no target, answer set, or private clue values."""

        return {
            "family": self.family,
            "instance_id": self.instance_id,
            "seed": self.seed,
            "complexity": self.complexity.value,
            "generator_hint": self.generator_hint.value,
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

    def information(self, agent: str, raw_text: str, message_id: str) -> MessageInformation:
        before = FeasibleSet.from_values(self.private_solutions[agent])
        return ExactInformationEvaluator().evaluate(before, raw_text, self.interpret(raw_text), message_id)

    def validate(self, submission: str) -> dict[str, Any]:
        accepted = submission in self.joint_solutions
        return {"accepted": accepted, "score": 1.0 if accepted else 0.0,
                "checker": f"{self.family}-oracle-v1", "submission": submission}

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
        claims = _claims_for_bits(candidates, target)
        if complexity is ReasoningComplexity.MEDIUM:
            claims = claims + (Claim("derived parity=0", lambda value: int(value.rsplit("-", 1)[-1]) % 2 == 0),)
        if complexity is ReasoningComplexity.HIGH:
            claims = claims + (Claim("chained checksum=0", lambda value: sum(map(int, value.rsplit("-", 1)[-1])) % 2 == 0),)
        return FamilyInstance("hypothesis", _instance_id("hypothesis", seed), seed, complexity, regime,
            frozenset(candidates), {"A": a, "B": b}, joint, claims,
            {"candidate_count": 8, "predicate_style": complexity.value},
            {"A": tuple(c.text for c in claims[:1]), "B": tuple(c.text for c in claims[1:2])}, target)


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
            {"A": (claims[0].text,), "B": (claims[1].text,)}, target)


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
            {"A": ("budget=valid",), "B": (claims[0].text,)}, target)


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
            {"A": (claims[0].text,), "B": (claims[1].text,)}, target,
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
            {"A": (claims[0].text,), "B": (claims[1].text,)}, target)


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
            {"A": (claims[0].text,), "B": (claims[1].text,)}, target)


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
    try:
        generator = FAMILY_GENERATORS[family]
    except KeyError as exc:
        raise ValueError(f"unknown task family: {family}") from exc
    return generator.generate(seed, regime, complexity)


def generate_grid(family: str, seed: int = 1) -> list[FamilyInstance]:
    """Generate independent deterministic fixtures for all hint x complexity cells."""

    return [generate_instance(family, seed + index, regime, complexity)
            for index, (regime, complexity) in enumerate(
                itertools.product(DependenceRegime, ReasoningComplexity)
            )]


def validate_family_grid(family: str, seed: int = 1) -> dict[str, Any]:
    instances = generate_grid(family, seed)
    return {
        "family": family,
        "instances": len(instances),
        "cells": [instance.assignment.to_dict() for instance in instances],
        "all_finite": all(instance.solutions and instance.joint_solutions for instance in instances),
        "all_valid": all(instance.validate(instance.target)["accepted"] for instance in instances),
        "unique_ids": len({instance.instance_id for instance in instances}) == len(instances),
    }


__all__ = [
    "Claim", "FamilyInstance", "FAMILY_GENERATORS", "HypothesisFamily", "LegalFamily",
    "LexiconFamily", "PlanningFamily", "PoetryFamily", "ReferenceFamily",
    "generate_grid", "generate_instance", "validate_family_grid",
]
