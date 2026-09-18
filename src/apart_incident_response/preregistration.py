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
# Approved mechanics-smoke envelope (every physical request and retry counts).
SMOKE_MAX_PHYSICAL_REQUESTS = 60
SMOKE_MAX_COST_USD = 20.0
SMOKE_MAX_TOKENS = 1024
SMOKE_CONDITION_TURNS: dict[str, int] = {"ISO": 1, "FULL": 1, "COMM": 2}
SMOKE_MODEL = bd.DEFAULT_FREE_MODEL
SMOKE_CONDITIONS = ("ISO", "FULL", "COMM")
SMOKE_DIAGNOSTICS_NOT_RUN = ("ORACLE", "INDUCED")
# Successor/amendment registration for the seed-range protocol fix.
SUCCESSOR_VERSION = "stage2-preregistration-v2"
# Historical only: the original smoke cap is NOT the current cap.
ORIGINAL_SMOKE_CAP = 60
# Reviewer-approved cumulative cap for the repaired (signed-31-bit seed) protocol.
APPROVED_CUMULATIVE_CAP = 87
COST_CAP_USD = 20.0
CONSUMED_REQUESTS: dict[str, int] = {
    "smoke_prior": 6, "smoke_resume": 5, "diagnostics_outside_artifact": 6,
}
PLANNED_SMOKE_REQUESTS = 60
RETRY_PREFLIGHT_RESERVE = 10
NEW_REQUEST_ALLOWANCE = APPROVED_CUMULATIVE_CAP - sum(CONSUMED_REQUESTS.values())
SEED_BASIS_DESCRIPTION = (
    "sha256(instance_id|condition|turn|agent_id)[:8] masked to 0..2^31-1 (signed 31-bit)")
APPROVED_DECISIONS = (
    "five representative cells: hypothesis low/medium, reference low, planning low/high",
    "exclude unstable reference-high",
    "two fresh seeds per group, 10 instances, non-powered mechanics smoke",
    "1024 max tokens",
    "ISO/FULL one turn, COMM two",
    "INDUCED and ORACLE not run in this smoke",
    "overall matched ISO->FULL C_need is primary; voluntary COMM->ISO secondary",
    "Holm only for later five confirmatory group-specific claims",
    "minimum effective C_need 0.10 for reporting eta_comm",
    "smoke cap 60 physical requests / $20 total; retries and preflight count",
    "confirmatory sample size and spend deferred to the separate seed block after the smoke",
)
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
                          seeds_per_cell: int = MECHANICS_SMOKE_SEEDS_PER_GROUP,
                          approved: bool = False,
                          smoke_request_cap: int = SMOKE_MAX_PHYSICAL_REQUESTS,
                          smoke_cost_cap_usd: float = SMOKE_MAX_COST_USD) -> dict[str, Any]:
    src = repo_root / "src" / "apart_incident_response"
    cell_audit = audit_cells()
    smoke = stage2_instances(seeds_per_cell)
    smoke_ids = assert_unique_instance_ids(smoke)
    smoke_protocol_key = bd.current_protocol_key(
        SMOKE_MODEL, bd.BEHAVIORAL_VERSION, turns=dict(SMOKE_CONDITION_TURNS),
        max_tokens=SMOKE_MAX_TOKENS, finalizing_agent=bd.FINALIZER_AGENT)
    document: dict[str, Any] = {
        "preregistration_version": PREREGISTRATION_VERSION,
        "status": "locked_for_mechanics_smoke" if approved else "draft_for_review",
        "approval_required": not approved,
        "approval": ({"approved": True, "approved_by": "reviewer",
                      "scope": "bounded Ling mechanics smoke targeting the pinned free model"}
                     if approved else {"approved": False}),
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
            "model": SMOKE_MODEL,
            "temperature": 0.0,
            "stream": False,
            "require_parameters": True,
            "seed_basis": SEED_BASIS_DESCRIPTION,
            "max_tokens": SMOKE_MAX_TOKENS,
            "condition_turns": dict(SMOKE_CONDITION_TURNS),
            "conditions_run": list(SMOKE_CONDITIONS),
            "diagnostics_not_run": list(SMOKE_DIAGNOSTICS_NOT_RUN),
            "expected_protocol_key": smoke_protocol_key,
        },
        "caps": {
            "min_interval_seconds": 0.25,
            "max_cost_usd": 20.0,
            "max_requests": "per-run explicit cap",
            "stop_rules": ["request_cap", "cost_cap", "repeated_http_failure",
                           "missing_checker_evidence"],
            "smoke": {
                "max_physical_requests": smoke_request_cap,
                "max_cost_usd": smoke_cost_cap_usd,
                "counts_retries": True,
                "counts_preflight": True,
            },
        },
        "invalidity_classes": sorted({
            "provider_execution_failure", "invalid_output_empty", "invalid_output_unparsed",
            "missing_checker_evidence", "valid_wrong_answer", "success",
            "board_write_rejected",
        }),
        "superseded_artifacts": superseded_artifacts(repo_root / "runs" / "epic-126"),
        "cell_audit": cell_audit,
        "declared_distinct_cells": {
            "status": "approved" if approved else "proposed",
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
            "run_in_smoke": list(SMOKE_CONDITIONS),
            "not_run_in_smoke": list(SMOKE_DIAGNOSTICS_NOT_RUN),
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
                "status": "proposed_pending_smoke",
                "seed_base": STAGE2_CONFIRMATORY_SEED_BASE,
                "size_pending": True,
                "note": "choose per-cell size and spend cap after the smoke discordance and invalidity rates",
            },
        },
        "approved_decisions": list(APPROVED_DECISIONS) if approved else [],
        "pending_decisions": [
            "confirmatory sample size per cell (from observed discordant pairs)",
            "confirmatory spend cap",
        ],
        "proposed_decisions": [
            "confirmatory sample size per cell on the separate seed block",
            "confirmatory spend cap",
        ],
    }
    payload = json.dumps({key: value for key, value in document.items()
                          if key != "preregistration_hash"}, sort_keys=True)
    document["preregistration_hash"] = hashlib.sha256(payload.encode()).hexdigest()
    return document


def build_successor_preregistration(*, repo_root: Path, generator_commit: str | None = None,
                                    approved: bool = True) -> dict[str, Any]:
    """Amendment/successor registration for the seed-range protocol fix.

    Does not modify the locked v1 registration. With ``approved=True`` (default,
    reviewer-approved) it is locked for the clean-restart mechanics smoke and
    records the cumulative request-cap accounting.
    """

    base = build_preregistration(repo_root=repo_root, generator_commit=generator_commit,
                                 seeds_per_cell=MECHANICS_SMOKE_SEEDS_PER_GROUP, approved=False)
    v1_path = repo_root / "runs" / "epic-126" / "preregistration-v1.json"
    supersedes_hash = None
    if v1_path.is_file():
        try:
            supersedes_hash = json.loads(v1_path.read_text(encoding="utf-8")).get("preregistration_hash")
        except ValueError:
            supersedes_hash = None
    consumed = dict(CONSUMED_REQUESTS)
    consumed["total"] = sum(CONSUMED_REQUESTS.values())
    provider_settings = dict(base["provider_settings"])
    provider_settings["seed_basis"] = SEED_BASIS_DESCRIPTION
    provider_settings["provider_seed_algorithm"] = bd.PROVIDER_SEED_ALGORITHM
    provider_settings["provider_seed_max"] = bd.PROVIDER_SEED_MAX
    provider_settings["expected_protocol_key"] = bd.current_protocol_key(
        SMOKE_MODEL, bd.BEHAVIORAL_VERSION, turns=dict(SMOKE_CONDITION_TURNS),
        max_tokens=SMOKE_MAX_TOKENS, finalizing_agent=bd.FINALIZER_AGENT)
    request_cap_accounting = {
        "reviewer_approved_cumulative_cap": APPROVED_CUMULATIVE_CAP,
        "cost_cap_usd": COST_CAP_USD,
        "consumed": consumed,
        "new_request_allowance": NEW_REQUEST_ALLOWANCE,
        "planned_smoke_requests": PLANNED_SMOKE_REQUESTS,
        "retry_preflight_reserve": RETRY_PREFLIGHT_RESERVE,
        "clean_restart_cap": NEW_REQUEST_ALLOWANCE,
        "historical": {
            "original_smoke_cap": ORIGINAL_SMOKE_CAP,
            "note": "the original 60-request cap is retained for historical accounting only and is "
                    "not the current cap",
        },
        "note": "every physical call, including retries and preflight, counts toward the cumulative cap",
    }
    document: dict[str, Any] = dict(base)
    document.update({
        "preregistration_version": SUCCESSOR_VERSION,
        "status": "locked_for_mechanics_smoke" if approved else "draft_pending_review",
        "approval_required": not approved,
        "approval": ({
            "approved": True, "approved_by": "reviewer",
            "scope": "clean-restart mechanics smoke for the repaired signed-31-bit seed protocol",
            "cumulative_cap": APPROVED_CUMULATIVE_CAP, "cost_cap_usd": COST_CAP_USD,
            "new_request_allowance": NEW_REQUEST_ALLOWANCE,
        } if approved else {"approved": False}),
        "supersedes": {"version": base["preregistration_version"], "hash": supersedes_hash,
                       "reason": "seed-range protocol fix"},
        "amendment": {
            "reason": "provider HTTP 400 traced to provider_seed exceeding the provider signed 32-bit seed range",
            "change": "provider_seed is deterministic and bounded to 0..2^31-1",
            "seed_basis": SEED_BASIS_DESCRIPTION,
            "provider_seed_algorithm": bd.PROVIDER_SEED_ALGORITHM,
            "provider_seed_max": bd.PROVIDER_SEED_MAX,
            "evidence": "identical FULL prompt returned HTTP 400 with seed 3705292798 and succeeded with "
                        "seed 1; a simple prompt showed the same pattern",
            "inference": "the Novita signed-range limit is an empirically supported inference, not a "
                         "documented guarantee",
        },
        "provider_settings": provider_settings,
        "request_cap_accounting": request_cap_accounting,
        "clean_restart_plan": [
            "this reviewer-approved registration is locked for the mechanics smoke",
            "rebuild the frozen smoke instances and confirm the new expected_protocol_key",
            "run preflight verification against preregistration-v2.json before any provider call",
            "start a fresh artifact instead of appending to the failed stage2-smoke.jsonl",
            "stay within the 70 new physical requests (60 planned + 10 retries/preflight)",
            "stop under the same failure, request and cost rules",
        ],
    })
    payload = json.dumps({key: value for key, value in document.items()
                          if key != "preregistration_hash"}, sort_keys=True)
    document["preregistration_hash"] = hashlib.sha256(payload.encode()).hexdigest()
    return document


def verify_against_preregistration(document: Mapping[str, Any], *, instance_ids: Sequence[str],
                                   model: str, provider_version: str,
                                   condition_turns: Mapping[str, int], max_tokens: int,
                                   finalizing_agent: str = bd.FINALIZER_AGENT,
                                   planned_requests: int | None = None) -> dict[str, Any]:
    """Verify a planned smoke against the locked preregistration before any request.

    Checks approved/locked status, frozen manifest, model and treatment settings,
    the expected protocol key, and the applicable request allowance.
    """

    errors: list[str] = []
    if document.get("status") != "locked_for_mechanics_smoke":
        errors.append("preregistration is not locked for the mechanics smoke")
    expected_ids = list(document["stage2"]["mechanics_smoke"]["instance_ids"])
    if sorted(instance_ids) != sorted(expected_ids):
        errors.append(f"selected instance ids differ from the locked manifest "
                      f"({len(instance_ids)} selected vs {len(expected_ids)} expected)")
    provider_settings = document.get("provider_settings", {})
    locked_model = provider_settings.get("model")
    if model != locked_model:
        errors.append(f"model {model!r} != locked {locked_model!r}")
    if dict(condition_turns) != dict(SMOKE_CONDITION_TURNS):
        errors.append(f"condition turns {dict(condition_turns)!r} != approved "
                      f"{dict(SMOKE_CONDITION_TURNS)!r}")
    if max_tokens != SMOKE_MAX_TOKENS:
        errors.append(f"max tokens {max_tokens} != approved {SMOKE_MAX_TOKENS}")
    locked_algorithm = provider_settings.get("provider_seed_algorithm")
    if locked_algorithm is not None and locked_algorithm != bd.PROVIDER_SEED_ALGORITHM:
        errors.append(f"provider seed algorithm {bd.PROVIDER_SEED_ALGORITHM!r} != locked "
                      f"{locked_algorithm!r}")
    seed_basis = str(provider_settings.get("seed_basis", ""))
    if seed_basis and not ("2^31" in seed_basis or "31-bit" in seed_basis):
        errors.append("seed_basis does not describe the signed-31-bit mask")
    actual_key = bd.current_protocol_key(model, provider_version, turns=dict(condition_turns),
                                         max_tokens=max_tokens, finalizing_agent=finalizing_agent)
    expected_key = provider_settings.get("expected_protocol_key")
    if actual_key != expected_key:
        errors.append("protocol key differs from the locked preregistration")
    accounting = document.get("request_cap_accounting", {})
    allowance = accounting.get("new_request_allowance")
    if allowance is not None and planned_requests is not None and planned_requests > allowance:
        errors.append(f"planned requests {planned_requests} exceed the approved new allowance {allowance}")
    return {
        "ok": not errors,
        "errors": errors,
        "expected_protocol_key": expected_key,
        "actual_protocol_key": actual_key,
        "expected_instance_ids": expected_ids,
        "selected_instance_ids": list(instance_ids),
        "planned_requests": planned_requests,
        "new_request_allowance": allowance,
        "cumulative_cap": accounting.get("reviewer_approved_cumulative_cap"),
        "consumed_requests": accounting.get("consumed", {}).get("total"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the stage-2 preregistration document")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--generator-commit", default=None)
    parser.add_argument("--seeds-per-cell", type=int, default=MECHANICS_SMOKE_SEEDS_PER_GROUP)
    parser.add_argument("--approve", action="store_true",
                        help="record the reviewer approval and lock the mechanics smoke")
    parser.add_argument("--smoke-request-cap", type=int, default=SMOKE_MAX_PHYSICAL_REQUESTS)
    parser.add_argument("--smoke-cost-cap", type=float, default=SMOKE_MAX_COST_USD)
    parser.add_argument("--successor", action="store_true",
                        help="build the successor/amendment registration (does not modify v1)")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.successor:
        document = build_successor_preregistration(repo_root=args.repo_root.resolve(),
                                                   generator_commit=args.generator_commit)
    else:
        document = build_preregistration(repo_root=args.repo_root.resolve(),
                                         generator_commit=args.generator_commit,
                                         seeds_per_cell=args.seeds_per_cell,
                                         approved=args.approve,
                                         smoke_request_cap=args.smoke_request_cap,
                                         smoke_cost_cap_usd=args.smoke_cost_cap)
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
        "smoke_request_cap": document["caps"]["smoke"]["max_physical_requests"],
        "smoke_cost_cap_usd": document["caps"]["smoke"]["max_cost_usd"],
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
    "SMOKE_MAX_PHYSICAL_REQUESTS", "SMOKE_MAX_COST_USD", "SMOKE_MAX_TOKENS",
    "SMOKE_CONDITION_TURNS", "SMOKE_CONDITIONS", "SMOKE_DIAGNOSTICS_NOT_RUN", "SMOKE_MODEL",
    "SUCCESSOR_VERSION", "ORIGINAL_SMOKE_CAP", "CONSUMED_REQUESTS",
    "APPROVED_CUMULATIVE_CAP", "COST_CAP_USD", "NEW_REQUEST_ALLOWANCE",
    "PLANNED_SMOKE_REQUESTS", "RETRY_PREFLIGHT_RESERVE", "SEED_BASIS_DESCRIPTION",
    "audit_cells", "assert_unique_instance_ids", "build_preregistration",
    "build_successor_preregistration", "cell_fingerprint",
    "file_sha256", "holm_adjust", "main", "mcnemar_required_pairs", "mechanics_smoke_instances",
    "missingness_report", "stage2_cell_seed", "stage2_instances", "superseded_artifacts",
    "verify_against_preregistration",
]
