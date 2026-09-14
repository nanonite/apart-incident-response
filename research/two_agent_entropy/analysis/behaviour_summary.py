#!/usr/bin/env python3
"""Descriptive summary of what agents do after the switch turn (turns 8-20), per experiment, model and condition.

Reads <artifacts>/two-agent-entropy/<exp>/tables_full/calls.csv (derived tables; raw run logs are not touched) and
writes research/two_agent_entropy/results/behaviour_post_switch.csv with the share of calls per action and the share
of calls that repeat the agent's previous action. These are descriptive counts with no statistical test.

Usage: python3 behaviour_summary.py [artifacts_root] [output_csv]
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
ARTIFACTS = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "artifacts" / "two-agent-entropy"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO / "research" / "two_agent_entropy" / "results" / "behaviour_post_switch.csv"
EXPERIMENTS = [("exp1", 1.0), ("exp3", 0.5), ("exp2", 0.0)]
ACTIONS = ["read_log", "write_log", "decrypt", "submit", "done"]


def main() -> None:
    rows = []
    for exp, temperature in EXPERIMENTS:
        calls = pd.read_csv(ARTIFACTS / exp / "tables_full" / "calls.csv", usecols=lambda c: c != "completion_text")
        window = calls[(calls.turn >= 8) & (calls.turn <= 20) & calls.action.notna()]
        for (model, condition), group in window.groupby(["model", "condition"]):
            ordered = group.sort_values(["seed", "agent", "turn"])
            repeat = (ordered.groupby(["seed", "agent"]).action.shift() == ordered.action).mean()
            shares = group.action.value_counts(normalize=True)
            row = {"experiment": exp, "temperature": temperature, "model": model, "condition": condition,
                   "n_calls": len(group), "repeat_share": repeat}
            row.update({f"share_{a}": float(shares.get(a, 0.0)) for a in ACTIONS})
            rows.append(row)
    df = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(df.to_string(index=False, float_format=lambda v: f"{v:.2f}"))


if __name__ == "__main__":
    main()
