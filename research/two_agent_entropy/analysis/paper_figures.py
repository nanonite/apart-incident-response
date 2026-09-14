#!/usr/bin/env python3
"""Paper figures comparing the three temperatures (exp1 T=1, exp3 T=0.5, exp2 T=0).

Reads <artifacts>/two-agent-entropy/<exp>/analysis/stats/{D_did_tests,I_post_read_spike}.csv and writes
vector PDFs (plus 300 dpi PNGs) on a white background, sized for the report's two-column text width:

    report/figures/temperature_switch_minus_placebo.pdf
    report/figures/temperature_post_read_entropy.pdf

Usage: python3 paper_figures.py [artifacts_root] [output_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
ARTIFACTS = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "artifacts" / "two-agent-entropy"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO / "report" / "figures"

MODELS = ["gpt-4o-mini", "llama-3.3-70b", "qwen3-235b"]
# Validated categorical slots (light mode): blue, orange, aqua; one marker shape per temperature.
TEMPS = [("exp1", "T = 1", "#2a78d6", "o"), ("exp3", "T = 0.5", "#eb6834", "s"), ("exp2", "T = 0", "#1baf7a", "D")]
INK, MUTED, GRID = "#13212b", "#56666f", "#e3e9eb"
TEXT_WIDTH_IN = 497.92 / 72.27

plt.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans"], "font.size": 7.5,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK, "text.color": INK,
    "axes.spines.top": False, "axes.spines.right": False, "figure.facecolor": "white", "axes.facecolor": "white",
    "savefig.facecolor": "white", "pdf.fonttype": 42, "legend.frameon": False,
})


def load(name: str) -> pd.DataFrame:
    frames = []
    for exp, label, _, _ in TEMPS:
        df = pd.read_csv(ARTIFACTS / exp / "analysis" / "stats" / name)
        df["temp"] = label
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def legend_handles(filled=True):
    return [Line2D([0], [0], marker=m, color=c, markerfacecolor=c, markeredgecolor=c, lw=0, markersize=5, label=l)
            for _, l, c, m in TEMPS]


def switch_minus_placebo() -> None:
    did = load("D_did_tests.csv")
    did = did[did.contrast == "switch - placebo"]
    measures = [("H_adj", "Adjusted token entropy (bits/token)"), ("H_decision", "Decision entropy (bits)")]
    fig, axes = plt.subplots(1, 2, figsize=(TEXT_WIDTH_IN, 2.55), sharey=True)
    offsets = {"T = 1": -0.24, "T = 0.5": 0.0, "T = 0": 0.24}
    for ax, (metric, title) in zip(axes, measures):
        sub = did[did.metric == metric]
        for mi, model in enumerate(MODELS):
            base_y = len(MODELS) - 1 - mi
            if mi:
                ax.axhline(base_y + 0.5, color=GRID, lw=0.8, zorder=0)
            for _, label, colour, marker in TEMPS:
                row = sub[(sub.model == model) & (sub.temp == label)].iloc[0]
                y = base_y - offsets[label]
                sig = row.p_holm < 0.05
                ax.plot([row.ci_low, row.ci_high], [y, y], color=colour, lw=1.4, solid_capstyle="round", zorder=2)
                ax.plot(row.did_bits, y, marker=marker, markersize=4.6, color=colour, markeredgecolor=colour,
                        markerfacecolor=colour if sig else "white", markeredgewidth=1.1, zorder=3)
                if sig:
                    ax.text(row.ci_high, y, f"  {row.did_bits:+.3f}", va="center", ha="left", fontsize=7, color=INK)
        ax.axvline(0, color=MUTED, lw=0.9, zorder=1)
        ax.grid(axis="x", color=GRID, lw=0.6, zorder=0)
        ax.set_axisbelow(True)
        ax.set_title(title, loc="left", fontsize=8, fontweight="bold", pad=6)
        ax.set_xlabel("switch − placebo  (← placebo higher · switch higher →)", fontsize=7, color=MUTED)
        ax.tick_params(axis="y", length=0)
        lo, hi = sub.ci_low.min(), sub.ci_high.max()
        pad = (hi - lo) * 0.12
        ax.set_xlim(min(lo - pad, -0.02), hi + pad * 2.2)
    axes[0].set_yticks(range(len(MODELS)))
    axes[0].set_yticklabels(list(reversed(MODELS)))
    axes[0].set_ylim(-0.6, len(MODELS) - 0.4)
    fig.legend(handles=legend_handles(), loc="upper right", ncol=3, fontsize=7.5, bbox_to_anchor=(0.995, 1.0),
               handletextpad=0.3, columnspacing=1.2)
    fig.tight_layout(rect=(0, 0, 1, 0.95), w_pad=2.2)
    save(fig, "temperature_switch_minus_placebo")


def post_read_entropy() -> None:
    spike = load("I_post_read_spike.csv")
    reads = [("own entries only", "own"), ("peer entries", "peer"), ("placebo entries", "placebo")]
    fig, axes = plt.subplots(1, 3, figsize=(TEXT_WIDTH_IN, 2.1), sharey=True)
    ymax = max(0.6, round(spike.H_adj.max() + 0.05, 1))
    for ax, model in zip(axes, MODELS):
        for ri, (key, label) in enumerate(reads):
            for ti, (_, temp, colour, marker) in enumerate(TEMPS):
                row = spike[(spike.model == model) & (spike.read_returned == key) & (spike.temp == temp)]
                if row.empty:
                    continue
                x, y = ri + (ti - 1) * 0.22, row.iloc[0].H_adj
                ax.plot([x, x], [0, y], color=colour, lw=1.2, alpha=0.35, zorder=1)
                ax.plot(x, y, marker=marker, markersize=4.4, color=colour, zorder=2)
        ax.set_xticks(range(len(reads)))
        ax.set_xticklabels([label for _, label in reads])
        ax.set_xlim(-0.6, len(reads) - 0.4)
        ax.set_ylim(0, ymax)
        ax.grid(axis="y", color=GRID, lw=0.6)
        ax.set_axisbelow(True)
        ax.tick_params(axis="x", length=0)
        ax.set_title(model, loc="left", fontsize=8, fontweight="bold", pad=6)
    axes[0].set_ylabel("adjusted entropy (bits/token)")
    fig.legend(handles=legend_handles(), loc="upper right", ncol=3, fontsize=7.5, bbox_to_anchor=(0.995, 1.0),
               handletextpad=0.3, columnspacing=1.2)
    fig.tight_layout(rect=(0, 0, 1, 0.93), w_pad=1.5)
    save(fig, "temperature_post_read_entropy")


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight", pad_inches=0.02)
    fig.savefig(OUT / f"{name}.png", dpi=300, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    print(OUT / f"{name}.pdf")


if __name__ == "__main__":
    switch_minus_placebo()
    post_read_entropy()
