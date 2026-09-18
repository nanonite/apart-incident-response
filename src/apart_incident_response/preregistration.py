"""Versioned preregistration for the next (stage-2) Ling screen.

This module is offline only: it freezes the generator, treatment and analysis
state into a reviewable document and never contacts a provider. Scientific
choices that still need reviewer approval are marked ``proposed`` rather than
silently finalized.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import NormalDist
from typing import Any, Mapping, Sequence

from . import behavioral_discovery as bd
from . import task_families as tf
from .communication_protocol import BatteryCondition, ReasoningComplexity


PREREGISTRATION_VERSION = "stage2-preregistration-v1"
# Collision-free stage-2 layout: family stride 10000, complexity stride 1000, so
# the layout supports up to 999 seeds per family x complexity cell.
STAGE2_SEED_BASE = 19000
STAGE2_FAMILY_STRIDE = 10000
STAGE2_COMPLEXITY_STRIDE = 1000
STAGE2_MAX_SEEDS_PER_CELL = 999
# A separate, reserved block for the confirmatory stage (size chosen after smoke).
STAGE2_CONFIRMATORY_SEED_BASE = 50000
STAGE2_FAMILY_ORDER = ("hypothesis", "reference", "planning", "poetry", "legal", "lexicon")
STAGE2_COMPLEXITY_ORDER = (ReasoningComplexity.LOW, ReasoningComplexity.MEDIUM,
                           ReasoningComplexity.HIGH)
# Proposed: one representative per audited structural group; reference-high is
# excluded as unstable (singleton agent).
PROPOSED_REPRESENTATIVE_CELLS: tuple[tuple[str, ReasoningComplexity], ...] = (
    ("hypothesis", ReasoningComplexity.LOW),
    ("hypothesis", ReasoningComplexity.MEDIUM),
    ("reference", ReasoningComplexity.LOW),
    ("planning", ReasoningComplexity.LOW),
    ("planning", ReasoningComplexity.HIGH),
)
EXCLUDED_UNSTABLE_CELLS = ("reference:high",)
MECHANICS_SMOKE_SEEDS_PER_GROUP = 2
# Proposed numeric floor below which eta_comm is reported as undefined.
MINIMUM_EFFECTIVE_C_NEED = 0.10
SUPERSEDED_CURRENT = {"preregistration-v1.json", "treatment-schema.json",
                      "channel-audit.json", "preregistered-manifest.json"}


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cell_fingerprint(instance: tf.FamilyInstance) -> tuple[int, int, int, int, int]:
    """Structural decision-problem fingerprint independent of domain labels."""

    return (len(instance.solutions), len(instance.claims),
            len(instance.private_solutions["A"]), len(instance.private_solutions["B"]),
            len(instance.joint_solutions))


def audit_cells(families: Sequence[str] = tuple(tf.FAMILY_GENERATORS),
                complexities: Sequence[ReasoningComplexity] = tuple(ReasoningComplexity),
                seeds: Sequence[int] = (1, 2, 3)) -> dict[str, Any]:
    """Group family x complexity cells by generator-identical decision problem."""

    rows: list[dict[str, Any]] = []
    for family in families:
        for complexity in complexities:
            instances = [tf.generate_instance(family, seed, tf.DependenceRegime.N, complexity)
                         for seed in seeds]
            fingerprints = {cell_fingerprint(instance) for instance in instances}
            rows.append({
                "family": family,
                "complexity": complexity.value,
                "stable": len(fingerprints) == 1,
                "fingerprint": sorted(fingerprints)[0] if len(fingerprints) == 1 else None,
                "fingerprint_dimensions": ["candidate_count", "claim_count", "private_a_size",
                                           "private_b_size", "joint_size"],
            })
    groups: dict[str, list[str]] = {}
    for row in rows:
        if row["fingerprint"] is None:
            continue
        groups.setdefault(str(row["fingerprint"]), []).append(f"{row['family']}:{row['complexity']}")
    cosmetic = {key: members for key, members in groups.items() if len(members) > 1}
    unstable = [f"{row['family']}:{row['complexity']}" for row in rows if not row["stable"]]
    return {
        "cells": rows,
        "groups": groups,
        "cosmetic_wrapper_groups": cosmetic,
        "unstable_cells": unstable,
        "distinct_cell_count": len(groups),
        "cell_count": len(rows),
    }


def stage2_cell_seed(family: str, complexity: ReasoningComplexity, replicate: int, *,
                     seed_base: int = STAGE2_SEED_BASE) -> int:
    """Deterministic collision-free seed for one stage-2 instance."""

    if family not in STAGE2_FAMILY_ORDER:
        raise ValueError(f"unknown task family: {family}")
    if complexity not in STAGE2_COMPLEXITY_ORDER:
        raise ValueError(f"unsupported stage-2 complexity: {complexity}")
    if not 0 <= replicate < STAGE2_MAX_SEEDS_PER_CELL:
        raise ValueError(f"replicate must be in [0, {STAGE2_MAX_SEEDS_PER_CELL})")
    family_index = STAGE2_FAMILY_ORDER.index(family)
    complexity_index = STAGE2_COMPLEXITY_ORDER.index(complexity)
    return (seed_base + family_index * STAGE2_FAMILY_STRIDE
            + complexity_index * STAGE2_COMPLEXITY_STRIDE + replicate)


def assert_unique_instance_ids(instances: Sequence[tf.FamilyInstance]) -> list[str]:
    instance_ids = [instance.instance_id for instance in instances]
    duplicates = sorted({value for value in instance_ids if instance_ids.count(value) > 1})
    if duplicates:
        raise ValueError(f"stage-2 seed layout produced duplicate instance ids: {duplicates[:5]}")
    return instance_ids


def stage2_instances(seeds_per_cell: int, *,
                     cells: Sequence[tuple[str, ReasoningComplexity]] = PROPOSED_REPRESENTATIVE_CELLS,
                     seed_base: int = STAGE2_SEED_BASE) -> list[tf.FamilyInstance]:
    """Fresh stage-2 instances on a collision-free seed block disjoint from stage-1."""

    if seeds_per_cell <= 0:
        raise ValueError("seeds_per_cell must be positive")
    if seeds_per_cell > STAGE2_MAX_SEEDS_PER_CELL:
        raise ValueError(f"seeds_per_cell exceeds the collision-free layout ({STAGE2_MAX_SEEDS_PER_CELL})")
    instances: list[tf.FamilyInstance] = []
    for family, complexity in cells:
        for replicate in range(seeds_per_cell):
            instances.append(tf.generate_instance(
                family, stage2_cell_seed(family, complexity, replicate, seed_base=seed_base),
                tf.DependenceRegime.N, complexity))
    assert_unique_instance_ids(instances)
    return instances


def mechanics_smoke_instances() -> list[tf.FamilyInstance]:
    """The frozen two-seed-per-group mechanics smoke consumed by #162."""

    return stage2_instances(MECHANICS_SMOKE_SEEDS_PER_GROUP)


def holm_adjust(pvalues: Mapping[str, float]) -> dict[str, float]:
    """Holm step-down family-wise adjustment, monotone and capped at 1."""

    ordered = sorted(pvalues.items(), key=lambda item: item[1])
    total = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for index, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, (total - index) * value))
        adjusted[name] = running
    return adjusted


def mcnemar_required_pairs(psi: float, discordant_rate: float, *, alpha: float = 0.05,
                           power: float = 0.80) -> dict[str, Any]:
    """Approximate McNemar sample size from expected discordant pairs.

    ``psi`` is P(right_only | discordant); ``discordant_rate`` is the expected
    discordant-pair fraction. Formula: n_discordant =
    ((z_{a/2} sqrt(1/2) + z_b sqrt(psi(1-psi))) / (psi - 1/2))^2.
    This is a planning heuristic, marked proposed.
    """

    if not 0.5 < psi < 1.0:
        raise ValueError("psi must be in (0.5, 1)")
    if not 0.0 < discordant_rate <= 1.0:
        raise ValueError("discordant_rate must be in (0, 1]")
    z_alpha = NormalDist().inv_cdf(1 - alpha / 2)
    z_beta = NormalDist().inv_cdf(power)
    numerator = z_alpha * math.sqrt(0.5) + z_beta * math.sqrt(psi * (1 - psi))
    discordant_pairs = (numerator / (psi - 0.5)) ** 2
    return {
        "psi": psi, "expected_discordant_rate": discordant_rate,
        "alpha": alpha, "power": power,
        "required_discordant_pairs": math.ceil(discordant_pairs),
        "required_total_pairs": math.ceil(discordant_pairs / discordant_rate),
    }


def missingness_report(records: Sequence[Mapping[str, Any]], left: str,
                       right: str) -> dict[str, Any]:
    """Condition-specific missingness with an extreme-imputation sensitivity analysis."""

    attempted: dict[str, int] = {left: 0, right: 0}
    valid: dict[str, int] = {left: 0, right: 0}
    per_instance: dict[str, dict[str, set[str]]] = {}
    for record in records:
        condition = record.get("condition")
        if condition not in {left, right}:
            continue
        instance_id = str(record.get("instance_id"))
        attempted[condition] += 1
        per_instance.setdefault(instance_id, {"attempted": set(), "valid": set()})["attempted"].add(condition)
        if record.get("valid_execution") is True:
            valid[condition] += 1
            per_instance[instance_id]["valid"].add(condition)
    complete_pairs = sum(1 for entry in per_instance.values() if {left, right} <= entry["valid"])
    attempted_pairs = sum(1 for entry in per_instance.values() if entry["attempted"])
    incomplete_pairs = attempted_pairs - complete_pairs

    contrast = bd.paired_contrast(records, left, right)
    left_only = contrast["left_only"] if contrast else 0
    right_only = contrast["right_only"] if contrast else 0
    complete_difference = contrast["difference"] if contrast else None

    total = complete_pairs + incomplete_pairs
    difference_bounds = None
    if total:
        # extreme-case bounds: every incomplete pair imputed to favour the
        # right condition, then the left condition
        difference_bounds = [
            (right_only - (left_only + incomplete_pairs)) / total,
            ((right_only + incomplete_pairs) - left_only) / total,
        ]
    return {
        "attempted": attempted,
        "valid": valid,
        "invalidity_by_condition": {condition: attempted[condition] - valid[condition]
                                    for condition in (left, right)},
        "complete_pairs": complete_pairs,
        "attempted_pairs": attempted_pairs,
        "incomplete_pairs": incomplete_pairs,
        "complete_case_difference": complete_difference,
        "difference_bounds_extreme_imputation": difference_bounds,
    }


def superseded_artifacts(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.iterdir()):
        if path.name in SUPERSEDED_CURRENT or path.name.startswith("preregistration"):
            continue
        rows.append({
            "path": str(path),
            "superseded": True,
            "reason": "produced before the clue-consistent generator and leak-free treatment boundary",
        })
    return rows


def build_preregistration(*, repo_root: Path, generator_commit: str | None = None,
                          seeds_per_cell: int = MECHANICS_SMOKE_SEEDS_PER_GROUP) -> dict[str, Any]:
    src = repo_root / "src" / "apart_incident_response"
    cell_audit = audit_cells()
    smoke = stage2_instances(seeds_per_cell)
    smoke_ids = assert_unique_instance_ids(smoke)
    document: dict[str, Any] = {
        "preregistration_version": PREREGISTRATION_VERSION,
        "status": "draft_for_review",
        "generator_commit": generator_commit,
        "generator_file_sha256": file_sha256(src / "task_families.py"),
        "treatment_file_sha256": file_sha256(src / "behavioral_discovery.py"),
        "generator_version": tf.GENERATOR_VERSION,
        "checker_version": tf.CHECKER_VERSION,
        "feasible_set_definitions": {
            "solutions": "public candidate option set",
            "private_solutions": "clue-consistent candidates for the agent's own exact private clues",
            "joint_solutions": "clue-consistent candidates for the union of both agents' clues (unique target for N)",
            "channel_complete": "S_pooled == S_joint",
            "finalizer_needs_peer": "|S_A| > |S_joint|",
        },
        "scorer": {
            "criterion": "unique_joint_target",
            "accepts": "submission in joint_solutions",
            "checker": f"<family>-{tf.CHECKER_VERSION}",
        },
        "treatment_schema": bd.treatment_schema(),
        "provider_settings": {
            "endpoint": bd.ENDPOINT,
            "temperature": 0.0,
            "stream": False,
            "require_parameters": True,
            "seed_basis": "sha256(instance_id|condition|turn|agent_id)[:8]",
            "max_tokens": 1024,
            "condition_turns": {"ISO": 1, "FULL": 1, "COMM": 2, "ORACLE": 1},
        },
        "caps": {
            "min_interval_seconds": 0.25,
            "max_cost_usd": 20.0,
            "max_requests": "per-run explicit cap",
            "stop_rules": ["request_cap", "cost_cap", "repeated_http_failure",
                           "missing_checker_evidence"],
        },
        "invalidity_classes": sorted({
            "provider_execution_failure", "invalid_output_empty", "invalid_output_unparsed",
            "missing_checker_evidence", "valid_wrong_answer", "success",
            "board_write_rejected",
        }),
        "superseded_artifacts": superseded_artifacts(repo_root / "runs" / "epic-126"),
        "cell_audit": cell_audit,
        "declared_distinct_cells": {
            "status": "proposed",
            "representatives": [f"{family}:{complexity.value}"
                                for family, complexity in PROPOSED_REPRESENTATIVE_CELLS],
            "excluded_unstable": list(EXCLUDED_UNSTABLE_CELLS),
            "groups": cell_audit["groups"],
            "note": "cells sharing a fingerprint are generator-identical decision problems; "
                    "domain labels are cosmetic and must not count as independent families",
        },
        "contrasts": {
            "primary": "matched ISO -> FULL C_need on preregistered complete pairs",
            "secondary": "voluntary COMM - ISO (never pooled with inducement)",
            "diagnostics": ["ORACLE - FULL manipulation check", "INDUCED inducement (separate)"],
            "holm_scope": "only if making five confirmatory group-specific claims",
        },
        "inference": {
            "paired": "complete-pair McNemar exact plus Newcombe paired-difference interval",
            "marginals": "Wilson intervals per condition",
            "denominators": "report planned/attempted/valid/complete-pair n and invalidity by condition",
            "missingness": "condition-specific invalidity plus extreme-imputation difference bounds",
            "eta_comm": "undefined when C_need is zero or below the minimum effective C_need",
            "minimum_effective_c_need": MINIMUM_EFFECTIVE_C_NEED,
        },
        "multiplicity": {
            "method": "Holm step-down over preregistered family claims",
            "helper": "holm_adjust",
        },
        "sample_size": {
            "status": "proposed",
            "basis": "expected discordant pairs via mcnemar_required_pairs, not a default n=20",
            "confirmatory_after_smoke": True,
            "illustration": [
                mcnemar_required_pairs(psi, rate)
                for psi, rate in ((0.75, 0.40), (0.70, 0.35), (0.80, 0.30))
            ],
        },
        "stage2": {
            "layout": {
                "seed_base": STAGE2_SEED_BASE,
                "family_stride": STAGE2_FAMILY_STRIDE,
                "complexity_stride": STAGE2_COMPLEXITY_STRIDE,
                "max_seeds_per_cell": STAGE2_MAX_SEEDS_PER_CELL,
                "family_order": list(STAGE2_FAMILY_ORDER),
                "complexity_order": [value.value for value in STAGE2_COMPLEXITY_ORDER],
                "collision_free": True,
            },
            "mechanics_smoke": {
                "status": "frozen",
                "seeds_per_group": seeds_per_cell,
                "instance_ids": smoke_ids,
                "manifest_hash": hashlib.sha256(json.dumps(smoke_ids, sort_keys=True).encode()).hexdigest(),
            },
            "confirmatory": {
                "status": "proposed",
                "seed_base": STAGE2_CONFIRMATORY_SEED_BASE,
                "size_pending": True,
                "note": "choose per-cell size and spend cap after the smoke discordance and invalidity rates",
            },
        },
        "proposed_decisions": [
            "one representative per audited structural group; exclude unstable reference-high",
            "first two fresh seeds per group are a mechanics smoke, not a powered result",
            "max_tokens 1024; ISO/FULL 1 turn, COMM 2, ORACLE 1",
            "leave INDUCED out of this screen",
            "overall matched ISO->FULL is primary; Holm only for five confirmatory group claims",
            "confirmatory sample size and spend cap chosen after the smoke, on a separate seed block",
        ],
        "approval_required": True,
    }
    payload = json.dumps({key: value for key, value in document.items()
                          if key != "preregistration_hash"}, sort_keys=True)
    document["preregistration_hash"] = hashlib.sha256(payload.encode()).hexdigest()
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the stage-2 preregistration document")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--generator-commit", default=None)
    parser.add_argument("--seeds-per-cell", type=int, default=MECHANICS_SMOKE_SEEDS_PER_GROUP)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    document = build_preregistration(repo_root=args.repo_root.resolve(),
                                     generator_commit=args.generator_commit,
                                     seeds_per_cell=args.seeds_per_cell)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
                               encoding="utf-8")
    print(json.dumps({
        "preregistration_version": document["preregistration_version"],
        "status": document["status"],
        "generator_commit": document["generator_commit"],
        "generator_version": document["generator_version"],
        "checker_version": document["checker_version"],
        "distinct_cell_count": document["cell_audit"]["distinct_cell_count"],
        "cell_count": document["cell_audit"]["cell_count"],
        "smoke_instance_count": len(document["stage2"]["mechanics_smoke"]["instance_ids"]),
        "preregistration_hash": document["preregistration_hash"],
        "approval_required": document["approval_required"],
    }, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PREREGISTRATION_VERSION", "STAGE2_SEED_BASE", "STAGE2_CONFIRMATORY_SEED_BASE",
    "STAGE2_FAMILY_STRIDE", "STAGE2_COMPLEXITY_STRIDE", "STAGE2_MAX_SEEDS_PER_CELL",
    "PROPOSED_REPRESENTATIVE_CELLS", "EXCLUDED_UNSTABLE_CELLS", "MINIMUM_EFFECTIVE_C_NEED",
    "audit_cells", "assert_unique_instance_ids", "build_preregistration", "cell_fingerprint",
    "file_sha256", "holm_adjust", "main", "mcnemar_required_pairs", "mechanics_smoke_instances",
    "missingness_report", "stage2_cell_seed", "stage2_instances", "superseded_artifacts",
]
