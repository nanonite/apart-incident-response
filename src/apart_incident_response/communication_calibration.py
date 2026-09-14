"""Offline calibration and bounded fixture-pilot summaries."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

from .communication_protocol import (
    DEPENDENCE_THRESHOLD_N,
    DEPENDENCE_THRESHOLD_R,
    DependenceRegime,
    ReasoningComplexity,
    assign_dependence,
)
from .task_families import FamilyInstance, generate_grid


def calibration_report(families: Sequence[str], *, seed: int = 1) -> dict[str, Any]:
    instances = [instance for family in families for instance in generate_grid(family, seed)]
    assignments = [instance.assignment for instance in instances]
    threshold_sensitivity = {}
    for low, high in ((0.05, 0.40), (0.10, 0.50), (0.15, 0.60)):
        threshold_sensitivity[f"{low:.2f}-{high:.2f}"] = dict(Counter(
            "undefined" if assignment.d_idx is None else
            "R" if assignment.d_idx <= low else "N" if assignment.d_idx >= high else "H"
            for assignment in assignments
        ))
    return {
        "status": "offline_calibration_complete",
        "families": list(families),
        "instance_count": len(instances),
        "cell_count": len(families) * 9,
        "assignments": [assignment.to_dict() for assignment in assignments],
        "realized_regime_counts": dict(Counter(assignment.regime.value if assignment.regime else "undefined" for assignment in assignments)),
        "threshold_sensitivity": threshold_sensitivity,
        "generator_hints_not_used_for_assignment": True,
        "live_pilot": {"status": "not_run", "model": "deepseek/deepseek-v4.1-flash", "budget_usd": 20.0},
        "recommendation": "run capability smoke and a small paired pilot before any replication-power expansion",
    }


def selected_fixture_instances(families: Sequence[str], *, seed: int = 1) -> list[FamilyInstance]:
    """Choose one independent instance per family and regime for bounded offline checks."""

    selected: list[FamilyInstance] = []
    for family_index, family in enumerate(families):
        grid = generate_grid(family, seed + family_index * 100)
        selected.extend(instance for instance in grid if instance.generator_hint in
                        {DependenceRegime.R, DependenceRegime.N} and instance.complexity is ReasoningComplexity.MEDIUM)
    return selected


__all__ = ["calibration_report", "selected_fixture_instances"]
