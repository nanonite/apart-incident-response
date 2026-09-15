"""One-command privacy-safe report over fixture or live battery rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .communication_analysis import PairedOutcome, analyze_runs
from .task_families import FamilyInstance


def report_from_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    outcomes = [PairedOutcome(
        pair_id=str(row["pair_id"]), family=str(row["family"]), model=str(row.get("model", "unknown")),
        condition=str(row["condition"]), success=row.get("success"), valid=bool(row.get("valid", True)),
        query_cost=str(row.get("query_cost", "unspecified")), urgency=str(row.get("urgency", "unspecified")),
        reward_pressure=float(row.get("reward_pressure", 0.0)),
        transmitted_bits=float(row.get("transmitted_bits", 0.0)),
        post_read_correlated_bits=float(row.get("post_read_correlated_bits", 0.0)),
        communication_tokens=int(row.get("communication_tokens", 0)), latency_seconds=row.get("latency_seconds"),
    ) for row in rows]
    report = analyze_runs(outcomes)
    report["falsification_checks"] = falsification_checks(rows)
    report["privacy"] = {"raw_messages_included": False, "answer_keys_included": False}
    return report


def falsification_checks(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Declare alternative-explanation checks without overclaiming from small pilots."""

    records = list(rows)
    return {
        "raw_message_volume_as_phi": {"status": "not_used", "message_volume_is_predictor": False},
        "output_length": {"status": "recorded_if_available", "field": "response_chars"},
        "action_type": {"status": "recorded_if_available", "field": "action_type"},
        "read_frequency": {"status": "recorded_if_available", "field": "read_count"},
        "incomplete_logprob_mass": {"status": "retained_invalid", "field": "logprob_coverage"},
        "input_rows": len(records),
    }


def report_from_battery(instances: Iterable[FamilyInstance], results: Iterable[Any]) -> dict[str, Any]:
    """Build the pooled/per-family report from controller-owned run objects."""

    instance_list = list(instances)
    rows = [{
        "pair_id": result.pair_id,
        "family": result.family,
        "model": result.model_id,
        "condition": result.condition.value,
        "success": result.task_success,
        "valid": result.status == "completed",
        "transmitted_bits": result.event_summary.get("transmitted_bits", 0.0),
        "post_read_correlated_bits": result.event_summary.get("post_read_correlated_bits", 0.0),
        "communication_tokens": result.event_summary.get("communication_tokens", 0),
        "latency_seconds": result.event_summary.get("first_post_read_success_latency_seconds"),
    } for result in results]
    report = report_from_rows(rows)
    report["structural_coverage"] = {
        "instance_count": len(instance_list),
        "families": sorted({instance.family for instance in instance_list}),
        "assignments": [instance.assignment.to_dict() for instance in instance_list],
        "cell_count": len(instance_list),
    }
    report["invalid_run_denominators"] = {
        "total_rows": len(rows),
        "invalid_rows": sum(not row["valid"] for row in rows),
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    rows = json.loads(args.input.read_text(encoding="utf-8"))
    report = report_from_rows(rows)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["falsification_checks", "main", "report_from_battery", "report_from_rows"]
