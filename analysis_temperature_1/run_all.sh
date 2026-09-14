#!/usr/bin/env bash
# Re-runs the whole exp1 analysis in order. Outputs: out/tables, out/figs, out/logs.
set -euo pipefail
cd "$(dirname "$0")"
for s in s00_integrity s01_descriptives s02_entropy_validation s03_endpoints s04_its s05_event_study \
         s06_coupling s07_functional_form s08_detector s09_robustness; do
  echo "== $s"
  uv run python "$s.py" > "out/logs/${s}_stdout.txt" 2>&1
done
echo "all steps finished"
