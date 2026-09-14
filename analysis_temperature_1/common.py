"""Shared paths, loaders, palette and statistics helpers for the exp1 analysis."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
EXP = ROOT.parent
TABLES = EXP / "tables_full"
TABLES_GATE = EXP / "tables_gate"
OUT = ROOT / "out"
OUT_T = OUT / "tables"
OUT_F = OUT / "figs"
OUT_L = OUT / "logs"
for _d in (OUT_T, OUT_F, OUT_L):
    _d.mkdir(parents=True, exist_ok=True)

SEED = 20260913
MODELS = ["gpt-4o-mini", "llama-3.3-70b", "qwen3-235b"]
CONDS = ["base", "placebo", "switch"]
K_STAR = 8
ACTION_CLASSES = ["READ", "WRITE", "DECRYPT", "SUBMIT", "OTHER", "DONE"]
Q_COLS = [f"q_{a}" for a in ACTION_CLASSES]
ACTION_TO_CLASS = {"read_log": "READ", "write_log": "WRITE", "decrypt": "DECRYPT",
                   "submit": "SUBMIT", "unparsed": "OTHER", "done": "DONE"}

# Categorical slots 1-3 of the dataviz reference palette (validated all-pairs, light mode).
# Condition -> colour is fixed across every figure.
COLOR = {"base": "#2a78d6", "switch": "#eb6834", "placebo": "#1baf7a"}
INK = {"primary": "#0b0b0b", "secondary": "#52514e", "muted": "#8a8984", "grid": "#e4e3df"}
SURFACE = "#fcfcfb"


def rng(offset: int = 0) -> np.random.Generator:
    return np.random.default_rng(SEED + offset)


def load_runs(gate: bool = False) -> pd.DataFrame:
    return pd.read_csv((TABLES_GATE if gate else TABLES) / "runs.csv")


def load_calls(gate: bool = False, text: bool = False) -> pd.DataFrame:
    path = (TABLES_GATE if gate else TABLES) / "calls.csv"
    df = pd.read_csv(path)
    if not text:
        df = df.drop(columns=["completion_text"])
    df["action_class"] = df["action"].map(ACTION_TO_CLASS)
    df["has_tokens"] = df["n_tokens"].fillna(0) > 0
    return df


def load_system(gate: bool = False) -> pd.DataFrame:
    return pd.read_csv((TABLES_GATE if gate else TABLES) / "system_entropy.csv")


TOKEN_COLS = ["model", "condition", "seed", "turn", "agent", "pos", "surprisal_bits",
              "H_lower_bits", "H_renorm_bits", "coverage", "placeholder"]


def load_tokens(model: str | None = None, cols=TOKEN_COLS) -> pd.DataFrame:
    dtypes = {"model": "category", "condition": "category", "agent": "category",
              "seed": "int16", "turn": "int8", "pos": "int16"}
    parts = []
    for chunk in pd.read_csv(TABLES / "tokens.csv.gz", usecols=cols,
                             dtype={k: v for k, v in dtypes.items() if k in cols},
                             chunksize=500_000):
        if model is not None:
            chunk = chunk[chunk["model"] == model]
        parts.append(chunk)
    return pd.concat(parts, ignore_index=True)


def run_dir(model: str, condition: str, seed: int) -> Path:
    return EXP / "full" / model / condition / f"s{seed:03d}"


def read_jsonl(path: Path) -> list[dict]:
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


# ---------------------------------------------------------------- statistics
def entropy_bits(p: np.ndarray, axis=-1) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(p > 0, -p * np.log2(p), 0.0)
    return t.sum(axis=axis)


def boot_ci(x, n_boot: int = 10_000, stat=np.mean, alpha: float = 0.05, offset: int = 0):
    """Percentile bootstrap CI over the units in x (units = seeds)."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) == 0:
        return np.nan, np.nan, np.nan
    g = rng(offset)
    idx = g.integers(0, len(x), size=(n_boot, len(x)))
    reps = np.apply_along_axis(stat, 1, x[idx]) if stat is not np.mean else x[idx].mean(axis=1)
    return float(stat(x)), float(np.quantile(reps, alpha / 2)), float(np.quantile(reps, 1 - alpha / 2))


def bh(pvals) -> np.ndarray:
    """Benjamini-Hochberg adjusted p-values (NaN preserved)."""
    p = np.asarray(pvals, dtype=float)
    out = np.full_like(p, np.nan)
    ok = ~np.isnan(p)
    q = p[ok]
    n = len(q)
    if n == 0:
        return out
    order = np.argsort(q)
    ranked = q[order] * n / np.arange(1, n + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    adj = np.empty(n)
    adj[order] = np.clip(ranked, 0, 1)
    out[ok] = adj
    return out


class Tee:
    """Mirror stdout into out/logs/<name>.txt."""

    def __init__(self, name: str):
        self.fh = open(OUT_L / f"{name}.txt", "w")
        self.stdout = sys.stdout
        sys.stdout = self

    def write(self, s):
        self.stdout.write(s)
        self.fh.write(s)

    def flush(self):
        self.stdout.flush()
        self.fh.flush()


def save_table(df: pd.DataFrame, name: str, md: bool = True, floatfmt: str = ".4g") -> None:
    df.to_csv(OUT_T / f"{name}.csv", index=False)
    if md:
        (OUT_T / f"{name}.md").write_text(to_markdown(df, floatfmt))


def to_markdown(df: pd.DataFrame, floatfmt: str = ".4g") -> str:
    def fmt(v):
        if isinstance(v, (float, np.floating)):
            return "" if np.isnan(v) else format(v, floatfmt)
        return str(v)
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join(fmt(v) for v in row) + " |")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- plotting
def mpl_setup():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": INK["muted"], "axes.labelcolor": INK["secondary"],
        "xtick.color": INK["secondary"], "ytick.color": INK["secondary"],
        "text.color": INK["primary"], "axes.grid": True, "grid.color": INK["grid"],
        "grid.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False,
        "lines.linewidth": 2, "font.size": 9, "axes.titlesize": 10, "legend.frameon": False,
        "figure.dpi": 130,
    })
    return plt


def mark_kstar(ax, x=K_STAR):
    ax.axvline(x, color=INK["muted"], lw=1, ls="--", zorder=0)
    ax.text(x, 1.0, " k*=8", transform=ax.get_xaxis_transform(), va="top", ha="left",
            color=INK["secondary"], fontsize=8)


def fig_path(model: str, name: str) -> Path:
    d = OUT_F / model
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{name}.png"
