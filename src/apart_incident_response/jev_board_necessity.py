"""J4 — offline board-necessity selection for the Jev entropy stage (#157).

No live calls. Combines the committed Ling selection evidence
(confirmatory-v3, jev-cell-selection-v1) with the #180 Jev capability journal and
report, keeping the constructs separate:

- structural peer-information need (generator channel audit),
- Ling C_need (ISO->FULL success contrast),
- voluntary board use (COMM),
- Jev ISO/FULL target probability,
- Jev decision entropy H(Choice p), recomputed from the saved full vectors.

The Jev gate is a repeated-query capability check (12 distinct request hashes, 6
prompt forms), never 17 independent confirmations, and a small p-value is never
an entropy gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from .communication_protocol import DependenceRegime, ReasoningComplexity
from . import task_families as tf
from .jev_protocol import audit_instance


BOARD_NECESSITY_VERSION = "jev-board-necessity-v1"
DEFAULT_JOURNAL = Path("runs/epic-126/jev-choice-capability.jsonl")
DEFAULT_SELECTION = Path("runs/epic-126/jev-cell-selection-v1.json")
DEFAULT_REPORT = Path("runs/epic-126/jev-board-necessity-selection.json")

JEV_J5_SEED_BASE = 72000
JEV_J5_PER_CELL = 17

#: Post-hoc selection criterion (recorded as such, not preregistered).
ISO_ENTROPY_MIN_BITS = 1.0
FULL_ENTROPY_MAX_BITS = 0.1
DELTA_ENTROPY_MIN_BITS = 1.0
ISO_CONSISTENT_MASS_MIN = 0.9
LING_HOLM_ALPHA = 0.05


def entropy_bits(probabilities: Mapping[str, float]) -> float:
    return -sum(float(value) * math.log2(float(value)) for value in probabilities.values()
                if float(value) > 0)


def validate_vector(row: Mapping[str, Any], tolerance: float = 1e-6) -> list[str]:
    """Return a list of identity/validity problems for a journal row (empty = ok)."""

    if row.get("status") != "complete":
        return [f"status={row.get('status')}"]
    probabilities = row.get("probabilities")
    option_ids = row.get("option_ids")
    if not isinstance(probabilities, Mapping) or not probabilities:
        return ["missing_probabilities"]
    if not isinstance(option_ids, list) or not option_ids:
        return ["missing_option_ids"]
    problems: list[str] = []
    if set(probabilities) != set(option_ids):
        problems.append("option_identity_mismatch")
    values = list(probabilities.values())
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
           for value in values):
        problems.append("non_finite_probability")
    if any(float(value) < 0 for value in values):
        problems.append("negative_probability")
    if abs(sum(float(value) for value in values) - 1.0) > tolerance:
        problems.append("not_normalized")
    return problems


def load_journal(path: Path = DEFAULT_JOURNAL) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _instance_index(instances: Sequence[tf.FamilyInstance]) -> dict[str, tf.FamilyInstance]:
    return {instance.instance_id: instance for instance in instances}


def iso_consistent_mass(journal: Sequence[Mapping[str, Any]],
                        instances: Sequence[tf.FamilyInstance]) -> float | None:
    by_id = _instance_index(instances)
    values = []
    for row in journal:
        if row.get("condition") != "ISO" or row.get("status") != "complete":
            continue
        instance = by_id.get(str(row.get("instance_id")))
        if instance is None:
            continue
        probabilities = row.get("probabilities") or {}
        values.append(sum(float(probabilities.get(option, 0.0)) for option in instance.private_solutions["A"]))
    return _mean(values)


def summarize_jev(journal: Sequence[Mapping[str, Any]],
                  instances: Sequence[tf.FamilyInstance]) -> dict[str, Any]:
    by_id = _instance_index(instances)
    invalid: list[str] = []
    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_instance: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in journal:
        problems = validate_vector(row)
        if problems:
            invalid.append(f"{row.get('instance_id')}:{row.get('condition')}:{problems}")
            continue
        target = str(row.get("target_id"))
        probabilities = row.get("probabilities", {})
        entry = {
            "instance_id": row.get("instance_id"), "condition": row.get("condition"),
            "target_id": target, "p_target": float(probabilities.get(target, 0.0)),
            "entropy_bits": entropy_bits(probabilities), "max_probability": max(float(v) for v in probabilities.values()),
            "accepted": bool(row.get("accepted")), "request_hash": row.get("request_hash"),
        }
        by_condition[str(row.get("condition"))].append(entry)
        by_instance[str(row.get("instance_id"))][str(row.get("condition"))] = entry

    condition_summary: dict[str, Any] = {}
    for condition, rows in by_condition.items():
        condition_summary[condition] = {
            "valid": len(rows),
            "mean_p_target": _mean([row["p_target"] for row in rows]),
            "mean_entropy_bits": _mean([row["entropy_bits"] for row in rows]),
            "entropy_bits_min": min(row["entropy_bits"] for row in rows) if rows else None,
            "entropy_bits_max": max(row["entropy_bits"] for row in rows) if rows else None,
            "accepted": sum(1 for row in rows if row["accepted"]),
            "log2_option_count": math.log2(len(by_id[str(rows[0]["instance_id"])].solutions)) if rows else None,
        }

    paired = []
    for instance_id, conditions in sorted(by_instance.items()):
        if "ISO" in conditions and "FULL" in conditions:
            iso, full = conditions["ISO"], conditions["FULL"]
            paired.append({"instance_id": instance_id, "request_hash_iso": iso["request_hash"],
                           "request_hash_full": full["request_hash"],
                           "iso_p_target": iso["p_target"], "full_p_target": full["p_target"],
                           "iso_entropy_bits": iso["entropy_bits"], "full_entropy_bits": full["entropy_bits"],
                           "delta_entropy_bits": iso["entropy_bits"] - full["entropy_bits"],
                           "iso_accepted": iso["accepted"], "full_accepted": full["accepted"]})

    prompt_forms = {tuple(sorted(by_id[iid].private_clues.get("A", ()))) for iid in by_instance
                    if iid in by_id}
    hashes = {row.get("request_hash") for row in journal}
    return {
        "journal_rows": len(journal),
        "valid_rows": sum(len(rows) for rows in by_condition.values()),
        "invalid_rows": invalid,
        "option_identity_ok": not any("option_identity" in item for item in invalid),
        "normalization_ok": not any("not_normalized" in item or "non_finite" in item or "negative" in item
                                    for item in invalid),
        "distinct_request_hashes": len(hashes),
        "distinct_prompt_forms": len(prompt_forms),
        "by_condition": condition_summary,
        "mean_delta_entropy_bits": _mean([row["delta_entropy_bits"] for row in paired]),
        "iso_consistent_mass": iso_consistent_mass(journal, instances),
        "paired_instances": paired,
    }


def structural_need(instances: Sequence[tf.FamilyInstance]) -> dict[str, Any]:
    audits = [audit_instance(instance) for instance in instances]
    return {
        "instances": len(audits),
        "all_pass": all(audit["all_pass"] for audit in audits),
        "channel_complete_count": sum(1 for audit in audits if audit["checks"]["pooled_equals_joint"]),
        "finalizer_needs_peer_count": sum(1 for audit in audits if audit["checks"]["finalizer_needs_peer"]),
        "both_agents_needed_count": sum(1 for audit in audits if audit["checks"]["both_agents_needed"]),
    }


def load_ling_cell(path: Path = DEFAULT_SELECTION, *, family: str = "planning",
                   complexity: str = "low") -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    cell_audit = document.get("cell_audit", document)
    for cell in cell_audit.get("cells", []):
        if cell.get("family") == family and cell.get("complexity") == complexity:
            return {
                "cell": f"{family}:{complexity}",
                "holm_adjusted_p": cell.get("holm_adjusted_p"),
                "significant_fwer_0_05": cell.get("significant_fwer_0_05"),
                "mcnemar_exact_p": cell.get("mcnemar_exact_p"),
                "iso_to_full": cell.get("iso_to_full"),
                "comm": cell.get("comm"),
            }
    raise ValueError(f"cell {family}:{complexity} not found in {path}")


def ceiling_assessment(jev: Mapping[str, Any], need: Mapping[str, Any],
                       ling: Mapping[str, Any]) -> dict[str, Any]:
    """Post-hoc criterion for whether planning-low supports an ISO->FULL entropy contrast."""

    iso = jev["by_condition"].get("ISO", {})
    full = jev["by_condition"].get("FULL", {})
    iso_h = iso.get("mean_entropy_bits")
    full_h = full.get("mean_entropy_bits")
    delta_h = jev.get("mean_delta_entropy_bits")
    mass = jev.get("iso_consistent_mass")
    checks = [
        {"check": "structural_need_complete",
         "ok": need.get("finalizer_needs_peer_count") == need.get("instances") and need.get("instances", 0) > 0,
         "detail": need},
        {"check": "ling_c_need_significant",
         "ok": ling.get("holm_adjusted_p") is not None and ling["holm_adjusted_p"] < LING_HOLM_ALPHA,
         "detail": ling.get("holm_adjusted_p")},
        {"check": "iso_entropy_above_floor",
         "ok": iso_h is not None and iso_h >= ISO_ENTROPY_MIN_BITS,
         "detail": iso_h},
        {"check": "full_entropy_near_ceiling",
         "ok": full_h is not None and full_h <= FULL_ENTROPY_MAX_BITS,
         "detail": full_h},
        {"check": "iso_to_full_entropy_contrast",
         "ok": delta_h is not None and delta_h >= DELTA_ENTROPY_MIN_BITS,
         "detail": delta_h},
        {"check": "iso_mass_on_consistent_set",
         "ok": mass is not None and mass >= ISO_CONSISTENT_MASS_MIN,
         "detail": mass},
    ]
    return {
        "criterion": {
            "note": "post-hoc selection criterion, not preregistered",
            "iso_entropy_min_bits": ISO_ENTROPY_MIN_BITS,
            "full_entropy_max_bits": FULL_ENTROPY_MAX_BITS,
            "delta_entropy_min_bits": DELTA_ENTROPY_MIN_BITS,
            "iso_consistent_mass_min": ISO_CONSISTENT_MASS_MIN,
            "ling_holm_alpha": LING_HOLM_ALPHA,
        },
        "checks": checks,
        "decision": "advance" if all(item["ok"] for item in checks) else "redesign",
        "rationale": (
            "The entropy experiment operates on the receiver's pre-read (ISO-like) state and uses FULL as "
            "the saturated upper bound, so a near-ceiling FULL is the expected manipulation check, not the "
            "measurement cell. Planning-low is compatible with an ISO->FULL information contrast because ISO "
            "retains substantial entropy above the floor while its mass is concentrated on the true "
            "clue-consistent set; the ceiling would disqualify the cell only if ISO entropy were near zero or "
            "ISO mass were not on the consistent set."),
    }


def proposed_j5_manifest(*, seeds_per_cell: int = JEV_J5_PER_CELL) -> dict[str, Any]:
    instances = [tf.generate_instance("planning", JEV_J5_SEED_BASE + replicate,
                                      DependenceRegime.N, ReasoningComplexity.LOW)
                 for replicate in range(seeds_per_cell)]
    instance_ids = [instance.instance_id for instance in instances]
    return {
        "status": "draft_pending_review",
        "note": "draft for review; this is not live authorization and does not authorize #158",
        "family": "planning",
        "complexity": "low",
        "regime": "N",
        "seed_base": JEV_J5_SEED_BASE,
        "seeds_per_cell": seeds_per_cell,
        "instance_ids": instance_ids,
        "manifest_hash": hashlib.sha256(json.dumps(instance_ids, sort_keys=True).encode()).hexdigest(),
        "disjoint_from": {
            "planning_low_manifest_seed_base": 70000,
            "jev_j3_block_seed_base": 71000,
            "wire_smoke_seed_base": 70000,
        },
        "arms": ["ISO (Jev receiver, pre-read)", "FULL (saturated bound)", "COMM optional board "
                 "(Ling writer / Jev receiver)", "matched real/placebo/null receiver replay"],
        "primary_contrast": "paired change in H(Choice p) and p_target from pre-read to post-read, real vs "
                            "matched placebo/null, with complete-pair reporting",
        "thresholds_draft": {
            "verified_board_use_required": "at least one accepted, owner-exact write that reaches the receiver",
            "causal_uptake": "Newcombe interval for the real-vs-placebo paired change excludes 0 at alpha=0.05",
            "no_entropy_gate_from_p_value": True,
        },
        "caps_draft": {
            "physical_requests": 300,
            "jev_cost_usd": 1.0,
            "ling": "pinned free model; OpenRouter free quota",
            "stop_rules": ["request_cap", "cost_cap", "repeated_http_failure", "contract_mismatch",
                           "model_drift", "missing_checker_evidence"],
        },
    }


def build_report(*, journal_path: Path = DEFAULT_JOURNAL, selection_path: Path = DEFAULT_SELECTION,
                 instances: Sequence[tf.FamilyInstance] | None = None) -> dict[str, Any]:
    instances = list(instances) if instances is not None else _j3_instances()
    journal = load_journal(journal_path)
    jev = summarize_jev(journal, instances)
    need = structural_need(instances)
    ling = load_ling_cell(selection_path)
    assessment = ceiling_assessment(jev, need, ling)
    holm = _holm_table(selection_path)
    decisions = []
    for cell, value in sorted(holm.items()):
        if cell == "planning:low":
            decision = "advance" if assessment["decision"] == "advance" else "redesign"
            reason = "Jev ISO/FULL entropy contrast passes the post-hoc criterion" if decision == "advance" \
                else "fails the post-hoc entropy-contrast criterion"
        elif cell == "planning:high":
            decision, reason = "hold", "planning-high validity was repaired separately; not in the Jev scope"
        else:
            decision, reason = "hold", "Ling C_need not Holm-significant on the selection screen"
        decisions.append({"cell": cell, "holm_adjusted_p": value, "decision": decision, "reason": reason})
    return {
        "version": BOARD_NECESSITY_VERSION,
        "sources": {"jev_journal": str(journal_path), "ling_selection": str(selection_path)},
        "structural_need": need,
        "jev": jev,
        "ling_selection": ling,
        "ceiling_assessment": assessment,
        "candidate_decisions": decisions,
        "causal_uptake_unknowns": [
            "confirmatory-v3 COMM shows voluntary board use but only 2/17 post-read correlation events and "
            "confounds board use with the extra finalizer turn",
            "no matched real/placebo/null receiver replay has been run, so causal message uptake is "
            "unestablished",
            "Jev has no COMM data; the message effect on H(Choice p) is untested",
        ],
        "proposed_j5_manifest": proposed_j5_manifest(),
        "notes": {
            "repeated_query_not_independent": True,
            "p_value_is_not_an_entropy_gate": True,
            "j3_outcomes_are_not_held_out_j5_evidence": True,
            "constructs_kept_separate": ["structural_need", "ling_c_need", "voluntary_board_use",
                                         "jev_target_probability", "jev_decision_entropy"],
        },
    }


def _j3_instances() -> list[tf.FamilyInstance]:
    from .jev_preregistration import jev_capability_instances
    return jev_capability_instances()


def _holm_table(selection_path: Path) -> dict[str, float]:
    document = json.loads(selection_path.read_text(encoding="utf-8"))
    cell_audit = document.get("cell_audit", document)
    return {str(key): float(value) for key, value in (cell_audit.get("holm") or {}).items()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Jev board-necessity selection (#157)")
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    report = build_report(journal_path=args.journal, selection_path=args.selection)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "version": report["version"],
        "ceiling_decision": report["ceiling_assessment"]["decision"],
        "iso_mean_entropy_bits": report["jev"]["by_condition"]["ISO"]["mean_entropy_bits"],
        "full_mean_entropy_bits": report["jev"]["by_condition"]["FULL"]["mean_entropy_bits"],
        "mean_delta_entropy_bits": report["jev"]["mean_delta_entropy_bits"],
        "distinct_request_hashes": report["jev"]["distinct_request_hashes"],
        "advancing_cells": [row["cell"] for row in report["candidate_decisions"] if row["decision"] == "advance"],
    }, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BOARD_NECESSITY_VERSION", "ISO_ENTROPY_MIN_BITS", "FULL_ENTROPY_MAX_BITS",
    "DELTA_ENTROPY_MIN_BITS", "ISO_CONSISTENT_MASS_MIN", "JEV_J5_SEED_BASE", "JEV_J5_PER_CELL",
    "entropy_bits", "validate_vector", "load_journal", "iso_consistent_mass", "summarize_jev",
    "structural_need", "load_ling_cell", "ceiling_assessment", "proposed_j5_manifest", "build_report",
    "main",
]
