"""Offline cell-selection audit for advancing toward a Jev entropy pilot.

No live calls. This module reads committed artifacts and reports per-cell
validity, matched ISO/FULL/COMM outcomes, preregistered Holm-adjusted
cell-specific C_need, and the planning-high empty-output trace. Post-read
correlation is treated as correlation, never as causal uptake.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import behavioral_discovery as bd
from . import preregistration as prer
from .communication_protocol import BatteryCondition
from .task_families import FamilyInstance


CELL_AUDIT_VERSION = "jev-cell-selection-v1"
CONDITIONS = ("ISO", "FULL", "COMM")


def cell_index(instances: Sequence[FamilyInstance]) -> dict[str, tuple[str, str]]:
    return {instance.instance_id: (instance.family, instance.complexity.value) for instance in instances}


def _valid(record: Mapping[str, Any]) -> bool:
    return record.get("valid_execution") is True


def _accepted(record: Mapping[str, Any]) -> bool:
    return record.get("task_success") is True


def _summary(record: Mapping[str, Any]) -> Mapping[str, Any]:
    summary = record.get("event_summary")
    return summary if isinstance(summary, Mapping) else {}


def audit_confirmatory(instances: Sequence[FamilyInstance], records: Sequence[Mapping[str, Any]],
                       *, max_tokens: int = 1024) -> dict[str, Any]:
    index = cell_index(instances)
    rows = [record for record in records if record.get("instance_id") in index]
    by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    duplicates: list[str] = []
    for record in rows:
        key = (str(record.get("instance_id")), str(record.get("condition")))
        if key in by_key:
            duplicates.append(f"{key[0]}:{key[1]}")
        by_key[key] = record

    pvalues: dict[str, float] = {}
    cells: list[dict[str, Any]] = []
    for family, complexity in sorted(set(index.values())):
        instance_ids = [iid for iid, cell in index.items() if cell == (family, complexity)]
        attempted = Counter()
        valid = Counter()
        for instance_id in instance_ids:
            for condition in CONDITIONS:
                record = by_key.get((instance_id, condition))
                if record is None:
                    continue
                attempted[condition] += 1
                if _valid(record):
                    valid[condition] += 1
        cell_rows = [row for row in rows if index.get(str(row.get("instance_id"))) == (family, complexity)]
        contrast = bd.paired_contrast(cell_rows, "ISO", "FULL")
        key = f"{family}:{complexity}"
        if contrast is not None:
            pvalues[key] = contrast["mcnemar_exact_p"]
        comm_rows = [by_key[(iid, "COMM")] for iid in instance_ids if (iid, "COMM") in by_key]
        comm = {
            "attempted": len(comm_rows),
            "valid": sum(1 for record in comm_rows if _valid(record)),
            "successes": sum(1 for record in comm_rows if _valid(record) and _accepted(record)),
            "used_board": sum(1 for record in comm_rows if int(_summary(record).get("message_count", 0)) > 0),
            "messages": sum(int(_summary(record).get("message_count", 0)) for record in comm_rows),
            "transmitted_bits": round(sum(float(_summary(record).get("transmitted_bits", 0.0)) for record in comm_rows), 4),
            "post_read_correlation_count": sum(int(_summary(record).get("post_read_correlation_count", 0)) for record in comm_rows),
            "rejected_write_count": sum(int(_summary(record).get("rejected_write_count", 0)) for record in comm_rows),
        }
        cells.append({
            "family": family, "complexity": complexity, "instances": len(instance_ids),
            "attempted_by_condition": dict(attempted), "valid_by_condition": dict(valid),
            "iso_to_full": contrast, "comm": comm,
            "mcnemar_exact_p": contrast["mcnemar_exact_p"] if contrast else None,
        })

    holm = prer.holm_adjust(pvalues) if pvalues else {}
    for cell in cells:
        key = f"{cell['family']}:{cell['complexity']}"
        cell["holm_adjusted_p"] = holm.get(key)
        cell["significant_fwer_0_05"] = holm.get(key) is not None and holm[key] < 0.05

    return {
        "audit_version": CELL_AUDIT_VERSION,
        "record_count": len(rows),
        "cell_count": len(cells),
        "cells": cells,
        "holm": holm,
        "holm_scope": "five cell-specific C_need claims",
        "primary_iso_to_full": bd.paired_contrast(rows, "ISO", "FULL"),
        "duplicate_pairs": duplicates,
        "notes": {
            "post_read_correlation_is_not_causal": True,
            "comm_confounds_board_use_with_extra_finalizer_turn": True,
            "planning_low_is_selection_data_not_fresh_confirmation": True,
            "p_value_is_not_an_entropy_gate": True,
        },
    }


def planning_high_invalid_trace(instances: Sequence[FamilyInstance],
                                records: Sequence[Mapping[str, Any]], *,
                                max_tokens: int = 1024) -> dict[str, Any]:
    index = cell_index(instances)
    rows = [record for record in records if index.get(str(record.get("instance_id"))) == ("planning", "high")]
    trace: list[dict[str, Any]] = []
    for record in sorted(rows, key=lambda item: (str(item.get("instance_id")), str(item.get("condition")))):
        summary = _summary(record)
        condition = str(record.get("condition"))
        output_tokens = int(summary.get("output_tokens", 0) or 0)
        trace.append({
            "instance_id": record.get("instance_id"),
            "condition": condition,
            "classification": record.get("classification"),
            "valid_execution": _valid(record),
            "input_tokens": summary.get("input_tokens"),
            "output_tokens": output_tokens,
            "output_at_token_cap": output_tokens == max_tokens,
            "provider_failure_types": summary.get("provider_failure_types", []),
            "event_count": summary.get("event_count"),
        })
    invalid = [row for row in trace if not row["valid_execution"]]
    iso_invalid = [row for row in invalid if row["condition"] == "ISO"]
    comm_invalid = [row for row in invalid if row["condition"] == "COMM"]
    provider_failures = sorted({name for row in trace for name in row["provider_failure_types"]})
    return {
        "max_tokens": max_tokens,
        "invalid_total": len(invalid),
        "invalid_by_condition": dict(Counter(row["condition"] for row in invalid)),
        "invalid_classification": dict(Counter(str(row["classification"]) for row in invalid)),
        "provider_failures_present": provider_failures,
        "iso_invalid_total": len(iso_invalid),
        "iso_invalid_at_cap": sum(1 for row in iso_invalid if row["output_at_token_cap"]),
        "comm_invalid_output_tokens": sorted(row["output_tokens"] for row in comm_invalid),
        "trace": trace,
        "interpretation": (
            "provider and parser paths are clean (no provider failures); ISO invalid runs consume "
            "exactly max_tokens, i.e. length truncation with empty content. COMM per-agent truncation "
            "cannot be proven from the retained totals because per-output finish_reason and per-agent "
            "output tokens are not recorded."
        ),
        "safe_next_diagnostics": [
            "record provider finish_reason and per-agent output tokens in the event log",
            "add an offline fixture asserting empty content with finish_reason=length yields invalid_output_empty",
            "run a bounded higher-token-budget evidence pass only under a new registration",
        ],
    }


def build_report(records: Sequence[Mapping[str, Any]], *, scheme: str = "stage2-confirmatory",
                 seeds_per_cell: int = 17) -> dict[str, Any]:
    instances = bd.build_screen_instances(scheme=scheme, seeds_per_cell=seeds_per_cell)
    return {
        "version": CELL_AUDIT_VERSION,
        "scheme": scheme,
        "seeds_per_cell": seeds_per_cell,
        "cell_audit": audit_confirmatory(instances, records),
        "planning_high_trace": planning_high_invalid_trace(instances, records),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Jev cell-selection audit")
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--scheme", default="stage2-confirmatory")
    parser.add_argument("--seeds-per-cell", type=int, default=17)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    records = [json.loads(line) for line in args.records.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = build_report(records, scheme=args.scheme, seeds_per_cell=args.seeds_per_cell)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    holm = report["cell_audit"]["holm"]
    print(json.dumps({
        "version": report["version"],
        "holm": holm,
        "advancing_cells": [f"{c['family']}:{c['complexity']}" for c in report["cell_audit"]["cells"]
                            if c["significant_fwer_0_05"]],
        "planning_high_invalid_total": report["planning_high_trace"]["invalid_total"],
    }, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CELL_AUDIT_VERSION", "audit_confirmatory", "build_report", "cell_index",
    "main", "planning_high_invalid_trace",
]
