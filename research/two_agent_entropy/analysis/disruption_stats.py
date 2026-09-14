#!/usr/bin/env python3
"""Disruption detection: pooled switch + placebo runs against base runs, per experiment, model and measure.

Both switch and placebo put foreign log entries into an agent's context from turn 8, so together they are the
"disrupted" class. Uses the run-level deltas (turns 8-20 minus 1-7) in
<artifacts>/two-agent-entropy/<exp>/analysis/stats/D_run_level_deltas.csv with the same tests as
entropy_analysis.py (10,000 permutations, 4,000 bootstrap resamples, AUC, Holm within experiment and measure).

Writes research/two_agent_entropy/results/disruption_vs_base.csv.

Usage: python3 disruption_stats.py [artifacts_root] [output_csv]
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from entropy_analysis import auc, hedges_g, perm_test  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
ARTIFACTS = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "artifacts" / "two-agent-entropy"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO / "research" / "two_agent_entropy" / "results" / "disruption_vs_base.csv"
EXPERIMENTS = [("exp1", 1.0), ("exp3", 0.5), ("exp2", 0.0)]
METRICS = ["H_adj", "H_decision"]
RNG = np.random.default_rng(20260914)


def holm(ps: np.ndarray) -> np.ndarray:
    order = np.argsort(ps)
    adj = np.empty_like(ps)
    running = 0.0
    for rank, j in enumerate(order):
        running = max(running, min(1.0, ps[j] * (len(ps) - rank)))
        adj[j] = running
    return adj


def main() -> None:
    rows = []
    for exp, temperature in EXPERIMENTS:
        runs = pd.read_csv(ARTIFACTS / exp / "analysis" / "stats" / "D_run_level_deltas.csv")
        for model in sorted(runs.model.unique()):
            sub = runs[runs.model == model]
            for metric in METRICS:
                col = f"{metric}_delta"
                disrupted = sub[sub.condition.isin(["switch", "placebo"])][col].dropna().values
                base = sub[sub.condition == "base"][col].dropna().values
                diff, p = perm_test(disrupted, base)
                boots = RNG.choice(disrupted, (4000, len(disrupted))).mean(1) - RNG.choice(base, (4000, len(base))).mean(1)
                lo, hi = np.percentile(boots, [2.5, 97.5])
                rows.append({"experiment": exp, "temperature": temperature, "model": model, "metric": metric,
                             "contrast": "disrupted - base", "diff_bits": diff, "ci_low": lo, "ci_high": hi,
                             "hedges_g": hedges_g(disrupted, base), "auc": auc(disrupted, base), "p_perm": p,
                             "n_disrupted": len(disrupted), "n_base": len(base)})
    df = pd.DataFrame(rows)
    df["p_holm"] = np.nan
    for _, idx in df.groupby(["experiment", "metric"]).groups.items():
        df.loc[idx, "p_holm"] = holm(df.loc[idx, "p_perm"].values)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(df.to_string(index=False, float_format=lambda v: f"{v:.4f}"))


if __name__ == "__main__":
    main()
