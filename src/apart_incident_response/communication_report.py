"""One-command privacy-safe report over fixture or live battery rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .communication_analysis import PairedOutcome, analyze_runs


def report_from_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    outcomes = [PairedOutcome(
        pair_id=str(row["pair_id"]), family=str(row["family"]), model=str(row.get("model", "unknown")),
        condition=str(row["condition"]), success=row.get("success"), valid=bool(row.get("valid", True)),
        query_cost=str(row.get("query_cost", "unspecified")), urgency=str(row.get("urgency", "unspecified")),
        reward_pressure=float(row.get("reward_pressure", 0.0)), useful_bits=float(row.get("useful_bits", 0.0)),
        communication_tokens=int(row.get("communication_tokens", 0)), latency_seconds=row.get("latency_seconds"),
    ) for row in rows]
    report = analyze_runs(outcomes)
    report["privacy"] = {"raw_messages_included": False, "answer_keys_included": False}
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


__all__ = ["main", "report_from_rows"]
