"""J1 — frozen finite-task and communication invariants for the planning-low cell.

Offline only. Freezes the selected planning-low generator/checker invariants and
a fresh-seed manifest for the Jev track, and records the protocol boundary that
keeps superseded pre-repair artifacts out of analysis.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import behavioral_discovery as bd
from . import task_families as tf
from .communication_protocol import DependenceRegime, ReasoningComplexity
from .task_families import FamilyInstance


JEV_PROTOCOL_VERSION = "jev-planning-low-v1"
JEV_PLANNING_LOW_SEED_BASE = 70000
SELECTED_FAMILY = "planning"
SELECTED_COMPLEXITY = ReasoningComplexity.LOW
SELECTED_REGIME = DependenceRegime.N


def planning_low_instances(seeds_per_cell: int) -> list[FamilyInstance]:
    if seeds_per_cell <= 0:
        raise ValueError("seeds_per_cell must be positive")
    instances = [tf.generate_instance(SELECTED_FAMILY, JEV_PLANNING_LOW_SEED_BASE + replicate,
                                      SELECTED_REGIME, SELECTED_COMPLEXITY)
                 for replicate in range(seeds_per_cell)]
    ids = [instance.instance_id for instance in instances]
    if len(set(ids)) != len(ids):
        raise ValueError("planning-low seed block produced duplicate instance ids")
    return instances


def _no_answer_key_exposed(instance: FamilyInstance) -> bool:
    for agent in ("A", "B"):
        for condition in ("ISO", "FULL"):
            view = instance.agent_view(agent, condition)
            if "joint_candidate_labels" in view:
                return False
            if instance.target in json.dumps(view.get("joint_clues", [])):
                return False
    manifest = instance.public_manifest()
    return instance.target not in json.dumps(manifest)


def audit_instance(instance: FamilyInstance) -> dict[str, Any]:
    analysis = instance.channel_analysis()
    checks = {
        "pooled_equals_joint": analysis["channel_complete"],
        "claims_partitioned": analysis["claims_partitioned"],
        "both_agents_needed": analysis["both_agents_needed"],
        "finalizer_needs_peer": analysis["finalizer_needs_peer"],
        "target_in_joint": instance.target in instance.joint_solutions,
        "joint_size_one": len(instance.joint_solutions) == 1,
        "no_answer_key_exposed": _no_answer_key_exposed(instance),
        "candidate_count_within_255": len(instance.solutions) <= 255,
    }
    return {
        "instance_id": instance.instance_id,
        "family": instance.family,
        "complexity": instance.complexity.value,
        "regime": instance.assignment.regime.value if instance.assignment.regime else None,
        "candidate_count": len(instance.solutions),
        "claim_count": len(instance.claims),
        "checks": checks,
        "all_pass": all(checks.values()),
    }


def audit_invariants(instances: Sequence[FamilyInstance]) -> dict[str, Any]:
    rows = [audit_instance(instance) for instance in instances]
    return {
        "protocol_version": JEV_PROTOCOL_VERSION,
        "instance_count": len(rows),
        "passing": sum(row["all_pass"] for row in rows),
        "failing_ids": [row["instance_id"] for row in rows if not row["all_pass"]],
        "rows": rows,
    }


def build_manifest(seeds_per_cell: int) -> dict[str, Any]:
    instances = planning_low_instances(seeds_per_cell)
    audit = audit_invariants(instances)
    instance_ids = [instance.instance_id for instance in instances]
    return {
        "preregistration_version": JEV_PROTOCOL_VERSION,
        "selected_cell": f"{SELECTED_FAMILY}:{SELECTED_COMPLEXITY.value}",
        "seed_base": JEV_PLANNING_LOW_SEED_BASE,
        "seeds_per_cell": seeds_per_cell,
        "instance_ids": instance_ids,
        "instance_seeds": [instance.seed for instance in instances],
        "manifest_hash": hashlib.sha256(json.dumps(instance_ids, sort_keys=True).encode()).hexdigest(),
        "frozen_versions": {
            "generator_version": tf.GENERATOR_VERSION,
            "checker_version": tf.CHECKER_VERSION,
            "treatment_prompt_schema": bd.PROMPT_SCHEMA_VERSION,
            "provider_seed_algorithm": bd.PROVIDER_SEED_ALGORITHM,
            "protocol_key": bd.current_protocol_key(bd.DEFAULT_FREE_MODEL, bd.BEHAVIORAL_VERSION,
                                                    turns=dict(bd.DEFAULT_CONDITION_TURNS),
                                                    max_tokens=1024),
        },
        "invariants": {
            "pooled_private_equals_joint": True,
            "writer_claims_from_own_private_clues": True,
            "both_agents_carry_unique_useful_information": True,
            "valid_target_no_answer_key_exposure": True,
            "audit": audit,
        },
        "communication_invariants": {
            "board_optional_primary": True,
            "writer_may_submit_only_own_exact_claim": True,
            "post_read_evidence_is_correlation_not_causal": True,
            "turn_matched_no_information_control_required": True,
        },
        "superseded_artifacts_excluded": True,
        "analysis_boundary": {
            "require_protocol_key": bd.current_protocol_key(bd.DEFAULT_FREE_MODEL, bd.BEHAVIORAL_VERSION,
                                                            turns=dict(bd.DEFAULT_CONDITION_TURNS),
                                                            max_tokens=1024),
            "note": "pre-repair artifacts (no matching protocol_key) must not enter analysis",
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="J1 planning-low invariant and manifest builder")
    parser.add_argument("--seeds-per-cell", type=int, default=17)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    manifest = build_manifest(args.seeds_per_cell)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
                               encoding="utf-8")
    print(json.dumps({
        "preregistration_version": manifest["preregistration_version"],
        "selected_cell": manifest["selected_cell"],
        "instance_count": len(manifest["instance_ids"]),
        "passing": manifest["invariants"]["audit"]["passing"],
        "manifest_hash": manifest["manifest_hash"],
    }, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "JEV_PROTOCOL_VERSION", "JEV_PLANNING_LOW_SEED_BASE", "SELECTED_FAMILY",
    "SELECTED_COMPLEXITY", "SELECTED_REGIME", "audit_instance", "audit_invariants",
    "build_manifest", "main", "planning_low_instances",
]
