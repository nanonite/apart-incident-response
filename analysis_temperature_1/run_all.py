#!/usr/bin/env python3
"""Recreate the analysis-report-01 analysis from one current matrix."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pipeline import write_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", required=True, type=Path, help="current UUID matrix.json")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("analysis_temperature_1/out/analysis.json"),
        help="JSON report destination",
    )
    args = parser.parse_args()
    report = write_report(args.matrix, args.output)
    print(f"analysis_status={report['analysis_status']}")
    print(f"matrix={args.matrix}")
    if report["analysis_status"] == "blocked":
        print(f"blocking_error={report.get('blocking_error', 'unknown')}")
        return 2
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
