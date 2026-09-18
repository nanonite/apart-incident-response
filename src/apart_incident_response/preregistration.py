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
STAGE2_SEED_BASE = 19000
STAGE2_FAMILY_OFFSETS: dict[str, int] = {
    "hypothesis": 0, "reference": 200, "planning": 400,
    "poetry": 600, "legal": 800, "lexicon": 1000,
}
STAGE2_COMPLEXITY_OFFSETS: dict[ReasoningComplexity, int] = {
    ReasoningComplexity.LOW: 0, ReasoningComplexity.MEDIUM: 100,
}
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
    return {
        "cells": rows,
        "groups": groups,
        "cosmetic_wrapper_groups": cosmetic,
        "distinct_cell_count": len(groups),
        "cell_count": len(rows),
    }


def stage2_instances(seeds_per_cell: int, *,
                     families: Sequence[str] = tuple(tf.FAMILY_GENERATORS),
                     complexities: Sequence[ReasoningComplexity] = (
                         ReasoningComplexity.LOW, ReasoningComplexity.MEDIUM),
                     ) -> list[tf.FamilyInstance]:
    """Fresh stage-2 instances on a seed block disjoint from stage-1."""

    if seeds_per_cell <= 0:
        raise ValueError("seeds_per_cell must be positive")
    instances: list[tf.FamilyInstance] = []
    for family in families:
        if family not in STAGE2_FAMILY_OFFSETS:
            raise ValueError(f"unknown task family: {family}")
        for complexity in complexities:
            seed0 = STAGE2_SEED_BASE + STAGE2_FAMILY_OFFSETS[family] + STAGE2_COMPLEXITY_OFFSETS[complexity]
            for replicate in range(seeds_per_cell):
                instances.append(tf.generate_instance(family, seed0 + replicate,
                                                      tf.DependenceRegime.N, complexity))
    return instances


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
    """Condition-specific attempted/valid counts and complete-pair sensitivity input."""

    attempted: dict[str, int] = {left: 0, right: 0}
    valid: dict[str, int] = {left: 0, right: 0}
    for record in records:
        condition = record.get("condition")
        if condition not in {left, right}:
            continue
        attempted[condition] += 1
        if record.get("valid_execution") is True:
            valid[condition] += 1
    contrast = bd.paired_contrast(records, left, right)
    complete_pairs = contrast["n_pairs"] if contrast else 0
    return {
        "attempted": attempted, "valid": valid, "complete_pairs": complete_pairs,
        "incomplete_pairs": max(0, min(attempted.values()) - complete_pairs),
        "invalidity_by_condition": {condition: attempted[condition] - valid[condition]
                                    for condition in (left, right)},
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
                          seeds_per_cell: int = 20) -> dict[str, Any]:
    src = repo_root / "src" / "apart_incident_response"
    cell_audit = audit_cells()
    stage2 = stage2_instances(seeds_per_cell=3)
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
            "max_tokens": "frozen per run (proposed 1024)",
            "turns": "frozen per run (proposed acute COMM 2, board-free 1)",
        },
        "caps": {
            "min_interval_seconds": 0.25,
            "max_cost_usd": 20.0,
            "max_requests": "per-run explicit cap; stage-2 request cap proposed below",
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
            "groups": cell_audit["groups"],
            "note": "cells sharing a fingerprint are generator-identical decision problems; "
                    "domain labels are cosmetic and must not count as independent families",
        },
        "contrasts": {
            "primary": "matched ISO -> FULL C_need on preregistered complete pairs",
            "secondary": "voluntary COMM - ISO (never pooled with inducement)",
            "diagnostics": ["ORACLE - FULL manipulation check", "INDUCED inducement (separate)"],
        },
        "inference": {
            "paired": "complete-pair McNemar exact plus Newcombe paired-difference interval",
            "marginals": "Wilson intervals per condition",
            "denominators": "report planned/attempted/valid/complete-pair n and invalidity by condition",
            "missingness": "condition-specific invalidity and complete-pair sensitivity",
            "eta_comm": "undefined when C_need is zero or below the preregistered minimum effect",
        },
        "multiplicity": {
            "method": "Holm step-down over preregistered family claims",
            "helper": "holm_adjust",
        },
        "sample_size": {
            "status": "proposed",
            "basis": "expected discordant pairs via mcnemar_required_pairs, not a default n=20",
            "illustration": [
                mcnemar_required_pairs(psi, rate)
                for psi, rate in ((0.75, 0.40), (0.70, 0.35), (0.80, 0.30))
            ],
        },
        "stage2": {
            "seed_base": STAGE2_SEED_BASE,
            "family_offsets": STAGE2_FAMILY_OFFSETS,
            "complexity_offsets": {key.value: value for key, value in STAGE2_COMPLEXITY_OFFSETS.items()},
            "sample_instance_ids": [instance.instance_id for instance in stage2],
            "manifest_hash": hashlib.sha256(json.dumps(
                [instance.instance_id for instance in stage2], sort_keys=True).encode()).hexdigest(),
        },
        "proposed_decisions": [
            "declared distinct cell set (cosmetic wrappers collapsed)",
            "sample size / expected discordant pairs per cell",
            "stage-2 seed block and seeds per cell",
            "family-level Holm claim set",
            "max_tokens and turns per condition",
            "stage-2 request and spend caps",
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
    parser.add_argument("--seeds-per-cell", type=int, default=20)
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
        "preregistration_hash": document["preregistration_hash"],
        "approval_required": document["approval_required"],
    }, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PREREGISTRATION_VERSION", "STAGE2_SEED_BASE", "STAGE2_FAMILY_OFFSETS",
    "audit_cells", "build_preregistration", "cell_fingerprint", "file_sha256",
    "holm_adjust", "main", "mcnemar_required_pairs", "missingness_report",
    "stage2_instances", "superseded_artifacts",
]
