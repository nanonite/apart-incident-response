"""Jev normalization sensitivity reporting under the registered grid (offline).

Given vectors already captured by the v2 codec, this module reports how
classification and conclusions behave at the registered tolerances
``1e-6, 0.01, 0.03, 0.05``:

- counts accepted/rejected at each tolerance (and what the accepted ones would
  have been classified as under the primary policy);
- the maximum normalization adjustment and maximum induced entropy difference;
- whether the argmax changes; and
- whether any substantive conclusion changes.

A conclusion is labelled ``unstable`` when it changes anywhere across the grid.
This is a method/diagnostic report: it is **not** a scientific conclusion, and
it must never be run to retroactively reclassify the stopped strict-v1 run
(whose rejected vector was discarded). No API calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import jev_choice_v2 as v2


SENSITIVITY_VERSION = "jev-normalization-sensitivity-v1"
SENSITIVITY_GRID = v2.SENSITIVITY_GRID
DEFAULT_DIAGNOSTICS_OUTPUT = Path("runs/epic-126/jev-choice-normalization-diagnostics-v2.json")
DEFAULT_CAPABILITY_JOURNAL = Path("runs/epic-126/jev-choice-capability.jsonl")
DEFAULT_PILOT_JOURNAL = Path("runs/epic-126/jev-choice-pilot.jsonl")


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()


def acceptance_at(diagnostics: v2.ChoiceVectorDiagnostics, tolerance: float) -> bool:
    """Whether a shape-valid vector would be accepted at a sensitivity tolerance."""

    if not diagnostics.shape_valid:
        return False
    deviation = diagnostics.absolute_normalization_deviation
    if deviation is None:
        return False
    epsilon = (v2.NORMALIZATION_BOUNDARY_EPSILON
               if tolerance >= v2.PRIMARY_ACCEPTANCE_BOUND else 0.0)
    return deviation <= tolerance + epsilon


def classification_at(diagnostics: v2.ChoiceVectorDiagnostics, tolerance: float) -> str:
    if not diagnostics.shape_valid:
        return "malformed"
    if not acceptance_at(diagnostics, tolerance):
        return "rejected_not_normalized"
    if diagnostics.absolute_normalization_deviation is not None \
            and diagnostics.absolute_normalization_deviation <= v2.EXACT_DEVIATION_TOLERANCE:
        return "exact"
    return "complete_renormalized"


def default_conclusion(accepted: Sequence[v2.ChoiceVectorDiagnostics]) -> dict[str, Any]:
    """A deliberately conservative default conclusion used when none is supplied."""

    entropies = [diagnostics.entropy_normalized_bits for diagnostics in accepted
                 if diagnostics.entropy_normalized_bits is not None]
    deviations = [diagnostics.absolute_normalization_deviation for diagnostics in accepted
                  if diagnostics.absolute_normalization_deviation is not None]
    argmax_signature = sorted({tuple(diagnostics.raw_argmax_set) for diagnostics in accepted})
    return {
        "n_accepted": len(accepted),
        "mean_entropy_bits": round(sum(entropies) / len(entropies), 9) if entropies else None,
        "max_absolute_deviation": max(deviations) if deviations else None,
        "distinct_argmax_sets": [list(row) for row in argmax_signature],
    }


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def normalization_sensitivity(vectors: Sequence[Mapping[str, Any]], *,
                              option_ids: Sequence[str] | None = None,
                              grid: Sequence[float] = SENSITIVITY_GRID,
                              conclusion_fn: Callable[[Sequence[v2.ChoiceVectorDiagnostics]],
                                                      Any] | None = None) -> dict[str, Any]:
    """Classify captured vectors at each tolerance and test conclusion stability."""

    captured: list[tuple[dict[str, Any], v2.ChoiceVectorDiagnostics]] = []
    for vector in vectors:
        expected = list(option_ids) if option_ids is not None else list(vector)
        raw, diagnostics, _ = v2.diagnose_probability_vector(vector, expected)
        captured.append((raw, diagnostics))
    diagnostics_all = [diagnostics for _, diagnostics in captured]
    conclude = conclusion_fn or default_conclusion

    per_tolerance: dict[str, dict[str, Any]] = {}
    conclusions: dict[str, Any] = {}
    for tolerance in grid:
        accepted = [diagnostics for diagnostics in diagnostics_all if acceptance_at(diagnostics, tolerance)]
        rejected = [diagnostics for diagnostics in diagnostics_all if not acceptance_at(diagnostics, tolerance)]
        adjustments = [diagnostics.normalization_adjustment for diagnostics in accepted
                       if diagnostics.normalization_adjustment is not None]
        entropy_diffs = [abs(diagnostics.entropy_raw_bits - diagnostics.entropy_normalized_bits)
                         for diagnostics in accepted
                         if diagnostics.entropy_raw_bits is not None
                         and diagnostics.entropy_normalized_bits is not None]
        argmax_changed = any(diagnostics.argmax_preserved is False for diagnostics in accepted)
        mixed_shape_validity = any(not diagnostics.shape_valid for diagnostics in diagnostics_all)
        try:
            conclusion = conclude(accepted)
        except Exception as exc:  # convergence must not crash the report
            conclusion = {"error": type(exc).__name__}
        conclusions[str(tolerance)] = conclusion
        per_tolerance[str(tolerance)] = {
            "tolerance": tolerance,
            "accepted": len(accepted),
            "rejected": len(rejected),
            "rejected_by_tier": _tier_counts(rejected),
            "rejected_by_shape": sum(1 for diagnostics in rejected if not diagnostics.shape_valid),
            "max_normalization_adjustment": max(adjustments) if adjustments else None,
            "max_induced_entropy_difference": max(entropy_diffs) if entropy_diffs else None,
            "argmax_changes": bool(argmax_changed),
            "mixed_shape_validity": bool(mixed_shape_validity),
            "accepted_classes": _class_counts(accepted, tolerance),
            "conclusion": conclusion,
            "conclusion_hash": canonical_hash(conclusion),
        }

    conclusion_hashes = {row["conclusion_hash"] for row in per_tolerance.values()}
    adjustments_all = [diagnostics.normalization_adjustment for diagnostics in diagnostics_all
                       if diagnostics.normalization_adjustment is not None]
    entropy_diffs_all = [abs(diagnostics.entropy_raw_bits - diagnostics.entropy_normalized_bits)
                         for diagnostics in diagnostics_all
                         if diagnostics.entropy_raw_bits is not None
                         and diagnostics.entropy_normalized_bits is not None]
    return {
        "sensitivity_version": SENSITIVITY_VERSION,
        "codec_version": v2.JEV_CHOICE_V2_CODEC_VERSION,
        "grid": list(grid),
        "vector_count": len(diagnostics_all),
        "per_tolerance": per_tolerance,
        "max_normalization_adjustment": max(adjustments_all) if adjustments_all else None,
        "max_induced_entropy_difference": max(entropy_diffs_all) if entropy_diffs_all else None,
        "argmax_changes": any(diagnostics.argmax_preserved is False for diagnostics in diagnostics_all),
        "conclusion_stable": len(conclusion_hashes) == 1,
        "unstable": len(conclusion_hashes) != 1,
        "note": ("method/diagnostic only; a conclusion that changes anywhere across the registered grid "
                 "is labelled unstable and is not a scientific result"),
    }


def _tier_counts(diagnostics: Sequence[v2.ChoiceVectorDiagnostics]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in diagnostics:
        counts[item.normalization_tier] = counts.get(item.normalization_tier, 0) + 1
    return dict(sorted(counts.items()))


def _class_counts(diagnostics: Sequence[v2.ChoiceVectorDiagnostics], tolerance: float) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in diagnostics:
        label = classification_at(item, tolerance)
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def journal_vectors(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Extract captured raw vectors from journal/report rows; skipped if absent."""

    vectors: list[dict[str, Any]] = []
    for row in rows:
        vector = row.get("raw_probabilities") or row.get("probabilities")
        if isinstance(vector, Mapping) and vector:
            vectors.append({str(key): value for key, value in vector.items()})
    return vectors


def build_diagnostics_document(*, capability_journal: Path = DEFAULT_CAPABILITY_JOURNAL,
                               pilot_journal: Path = DEFAULT_PILOT_JOURNAL,
                               conclusion_fn: Callable | None = None) -> dict[str, Any]:
    """Offline diagnostic over the vectors retained so far (not a conclusion)."""

    capability_rows = _read_rows(capability_journal)
    pilot_rows = _read_rows(pilot_journal)
    capability_vectors = journal_vectors(capability_rows)
    pilot_vectors = journal_vectors(pilot_rows)
    capability = normalization_sensitivity(capability_vectors, conclusion_fn=conclusion_fn)
    pilot = normalization_sensitivity(pilot_vectors, conclusion_fn=conclusion_fn)
    return {
        "sensitivity_version": SENSITIVITY_VERSION,
        "codec_version": v2.JEV_CHOICE_V2_CODEC_VERSION,
        "mode": "offline_method_diagnostic",
        "scientific_conclusion": False,
        "does_not_reclassify_stopped_v1": True,
        "note": ("the stopped strict-v1 run's rejected vector was discarded and is not reclassified here; "
                 "this report is a method diagnostic over vectors retained by capture-then-judge, not a "
                 "scientific conclusion"),
        "normalization_policy": normalization_policy_fingerprint(),
        "capability_journal": {
            "path": str(capability_journal),
            "rows": len(capability_rows),
            "vectors": len(capability_vectors),
            "report": capability,
        },
        "pilot_journal": {
            "path": str(pilot_journal),
            "rows": len(pilot_rows),
            "vectors": len(pilot_vectors),
            "report": pilot,
        },
    }


def normalization_policy_fingerprint() -> dict[str, Any]:
    return {
        "exact_deviation_tolerance": v2.EXACT_DEVIATION_TOLERANCE,
        "primary_acceptance_bound": v2.PRIMARY_ACCEPTANCE_BOUND,
        "quantization_bound": v2.QUANTIZATION_BOUND,
        "hard_deviation_ceiling": v2.HARD_DEVIATION_CEILING,
        "boundary_epsilon": v2.NORMALIZATION_BOUNDARY_EPSILON,
        "sensitivity_grid": list(SENSITIVITY_GRID),
    }


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Jev normalization sensitivity diagnostic (offline)")
    parser.add_argument("--capability-journal", type=Path, default=DEFAULT_CAPABILITY_JOURNAL)
    parser.add_argument("--pilot-journal", type=Path, default=DEFAULT_PILOT_JOURNAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_DIAGNOSTICS_OUTPUT)
    args = parser.parse_args(argv)
    document = build_diagnostics_document(capability_journal=args.capability_journal,
                                          pilot_journal=args.pilot_journal)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "sensitivity_version": document["sensitivity_version"],
        "capability_vectors": document["capability_journal"]["vectors"],
        "pilot_vectors": document["pilot_journal"]["vectors"],
        "capability_unstable": document["capability_journal"]["report"]["unstable"],
        "output": str(args.output),
    }, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SENSITIVITY_VERSION", "SENSITIVITY_GRID", "DEFAULT_DIAGNOSTICS_OUTPUT",
    "acceptance_at", "classification_at", "default_conclusion", "normalization_sensitivity",
    "journal_vectors", "build_diagnostics_document", "normalization_policy_fingerprint", "main",
]
