#!/usr/bin/env python3
"""Entropy analysis of the two-agent shared-log experiments (generalised, v2).

Inputs
------
An experiment directory holding ``tables_<phase>/{calls.csv, runs.csv}`` (the
tables written by ``../analyze.py``), or explicit ``--calls`` / ``--runs`` paths
so that any flattener with recognised column names can be analysed (see
``ALIASES``; ``exp_*_calls.csv.gz`` / ``exp_*_runs.csv`` are supported).

Outputs (unchanged from v1)
---------------------------
``<out>/figures/*.png`` and ``<out>/stats/{*.csv, summary.json}``.

Analyses (all run-level inference; runs are the independent unit)
  A  ground truth       task success, verified communication, tau_read / tau_use,
                        observer (A3) completion when present
  B  token entropy      trajectories per model x condition, 95% bootstrap CIs
  C  confound check     action mix per turn; entropy by action type
  D  DiD                per-run Delta = mean(post) - mean(pre) with pre/post cut at
                        each run's own switch turn; raw and adjusted for action type
                        and log length; permutation tests over every condition pair
  E  mixed model        H ~ condition*post + C(action) + log1p(n_tokens) + (1 | run)
  F  decision entropy   entropy of the first-token action distribution q(a)
  G  system entropy     H(Xi,Xj) = H(Xi) + H(Xj) - I(Xi;Xj) over the action variable
                        across runs, for every agent pair; pairing-permutation null
  H  aligned            token entropy aligned on the first foreign read of each run
  I  post-read spike    entropy of the call right after a READ_LOG, by what it returned
  J  detection          run-level ROC; CUSUM calibrated to 5% false alarms on the
                        control condition; detection delay vs tau_read; PELT

What is generalised with respect to the exp1 version
----------------------------------------------------
1. Arbitrary sets of models and conditions, discovered from the tables
   (``placebo_inert`` and any future arm included). Missing model x condition
   cells are tolerated everywhere: a cell with no runs is skipped, never
   ``.item()``-ed, and the corresponding contrast is reported with NaN.
2. The pre/post cut uses each run's own ``switch_turn_effective`` (randomised
   switch, E5a/E5b) instead of the global constant, with the post window
   measured in turns from that event; ``switch_closed_turn`` is carried through
   and marked in the figures. Event alignment (H) uses the per-run anchor.
3. A third agent (observer ``A3``) is handled: trajectories and the DiD average
   over whatever agents are present, the system decomposition runs over every
   agent pair, and the ground-truth table reports the observer's grade and
   provenance when those columns exist.
4. Every Monte-Carlo estimate draws from a label-seeded generator, so a p-value
   or a bootstrap interval does not depend on how many other cells exist in the
   table (in v1 a single missing cell shifted the whole random stream).

Requirements (analysis only; see requirements.txt): numpy, scipy, pandas,
matplotlib, statsmodels, ruptures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import ruptures as rpt
import statsmodels.formula.api as smf
from scipy import stats

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import entropy as E  # noqa: E402

# ----------------------------------------------------------------------------- configuration

SWITCH_DEFAULT = 8          # used only when the tables carry no switch_turn_effective
POST_LEN_DEFAULT = 13       # turns in the post window, counted from the switch turn
N_PERM_DEFAULT = 10_000
N_PERM_SYSTEM = 1_000
BASE_SEED = 20260913

ACTIONS = ["read_log", "write_log", "decrypt", "submit"]
ACTION_PALETTE = {"read_log": "#94a3b8", "write_log": "#0b6e8a", "decrypt": "#eab308",
                  "submit": "#16a34a", "done": "#e5e7eb"}

# Conditions are ordered, and contrasted, by how much of a control they are:
# base (nothing happens) < inert placebo (foreign text, no task shape) <
# decoy placebo (foreign text with task shape, false) < switch (real channel).
CONTROL_RANK = {"base": 0, "placebo_inert": 1, "placebo": 2, "switch": 3}
CONDITION_COLOURS = {"base": "#64748b", "switch": "#0b6e8a", "placebo": "#c2410c",
                     "placebo_inert": "#a16207"}
EXTRA_COLOURS = ["#7c3aed", "#0f766e", "#be123c", "#4d7c0f", "#9333ea"]

# Column aliases: target name -> candidate names, first hit wins.
ALIASES = {
    "H": ["mean_H_renorm_bits", "H", "mean_H_renorm", "H_renorm_bits"],
    "H_lower": ["mean_H_lower_bits", "H_lower"],
    "surprisal": ["mean_surprisal_bits", "surp"],
    "n_tokens": ["n_tokens", "completion_tokens"],
    "n_foreign": ["n_real_foreign_returned", "n_foreign"],
    "n_placebo": ["n_placebo_returned", "n_placebo"],
    "n_inert": ["n_inert_returned", "n_inert"],
    "switch_turn": ["switch_turn_effective"],
    "switch_closed": ["switch_closed_turn"],
    "tau_read": ["tau_first_foreign_read"],
    "valid": ["valid", "run_valid"],
    "entropy_valid": ["entropy_valid", "run_entropy_valid"],
    "task_success": ["task_success", "run_task_success"],
}

plt.rcParams.update({"figure.dpi": 150, "savefig.dpi": 150, "font.size": 9, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.titleweight": "bold", "axes.titlesize": 10,
                     "legend.frameon": False})


# ----------------------------------------------------------------------------- small helpers

def _rng(label) -> np.random.Generator:
    """A generator seeded from a label, so results do not depend on call order."""
    digest = hashlib.blake2b(repr(label).encode(), digest_size=8).digest()
    return np.random.default_rng(BASE_SEED + int.from_bytes(digest, "big"))


def _clean(values) -> np.ndarray:
    a = np.asarray(list(values), dtype=float)
    return a[~np.isnan(a)]


def resolve(df: pd.DataFrame, target: str) -> str | None:
    """First column of ``df`` that matches the alias list for ``target``."""
    for name in ALIASES.get(target, [target]):
        if name in df.columns:
            return name
    return None


def column(df: pd.DataFrame, target: str, default=np.nan) -> pd.Series:
    name = resolve(df, target)
    if name is None:
        return pd.Series(default, index=df.index, name=target)
    return df[name]


def as_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "1.0", "yes", "t"})


def order_conditions(conditions) -> list[str]:
    known = sorted(c for c in conditions if c in CONTROL_RANK)
    unknown = sorted(c for c in conditions if c not in CONTROL_RANK)
    return sorted(known, key=lambda c: CONTROL_RANK[c]) + unknown


def condition_colours(conditions) -> dict[str, str]:
    out, spare = {}, list(EXTRA_COLOURS)
    for c in conditions:
        out[c] = CONDITION_COLOURS.get(c) or (spare.pop(0) if spare else "#334155")
    return out


def contrast_pairs(conditions) -> list[tuple[str, str]]:
    """Every unordered pair, written as (treatment, control) by control rank."""
    ranked = [(CONTROL_RANK.get(c, 10 + i), c) for i, c in enumerate(conditions)]
    ranked.sort()
    pairs = []
    for i, (_, control) in enumerate(ranked):
        for _, treat in ranked[i + 1:]:
            pairs.append((treat, control))
    return pairs


def cell(df: pd.DataFrame, **filters):
    """Subset of ``df`` matching the filters; empty frame instead of an error."""
    mask = pd.Series(True, index=df.index)
    for k, v in filters.items():
        mask &= df[k] == v
    return df[mask]


def scalar(df: pd.DataFrame, column_name: str, **filters) -> float:
    """One value from a (possibly absent) cell; NaN when the cell has no rows."""
    sub = cell(df, **filters)
    if len(sub) == 0 or column_name not in sub.columns:
        return float("nan")
    values = _clean(sub[column_name])
    return float(values[0]) if len(values) else float("nan")


def boot_ci(values, n=2000, fn=np.mean, label=None):
    values = _clean(values)
    if len(values) == 0:
        return (np.nan, np.nan, np.nan)
    if len(values) == 1:
        return (float(fn(values)), np.nan, np.nan)
    rng = _rng(("boot", label, len(values), round(float(values.sum()), 9)) if label is None
               else ("boot", label))
    idx = rng.integers(0, len(values), size=(n, len(values)))
    boots = fn(values[idx], axis=1)
    return (float(fn(values)), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)))


def perm_test(a, b, n=N_PERM_DEFAULT, label=None):
    """Two-sided permutation test on the difference of means (run-level)."""
    a, b = _clean(a), _clean(b)
    if len(a) == 0 or len(b) == 0:
        return (np.nan, np.nan)
    observed = a.mean() - b.mean()
    pooled = np.concatenate([a, b])
    rng = _rng(("perm", label, len(a), len(b), round(float(pooled.sum()), 9)))
    count = 0
    for _ in range(n):
        rng.shuffle(pooled)
        if abs(pooled[:len(a)].mean() - pooled[len(a):].mean()) >= abs(observed) - 1e-12:
            count += 1
    return float(observed), (count + 1) / (n + 1)


def hedges_g(a, b):
    a, b = _clean(a), _clean(b)
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return np.nan
    sp = math.sqrt(((na - 1) * a.var(ddof=1) + (nb - 1) * b.var(ddof=1)) / (na + nb - 2))
    d = (a.mean() - b.mean()) / sp if sp > 0 else np.nan
    return d * (1 - 3 / (4 * (na + nb) - 9))


def auc(pos, neg):
    pos, neg = _clean(pos), _clean(neg)
    if not len(pos) or not len(neg):
        return np.nan
    u = stats.mannwhitneyu(pos, neg, alternative="two-sided").statistic
    return float(u / (len(pos) * len(neg)))


def holm(p_values: np.ndarray) -> np.ndarray:
    """Holm step-down adjustment; NaN p-values stay NaN and do not count."""
    out = np.full(len(p_values), np.nan)
    finite = np.where(~np.isnan(p_values))[0]
    ps = p_values[finite]
    order = np.argsort(ps)
    running = 0.0
    for rank, j in enumerate(order):
        running = max(running, min(1.0, ps[j] * (len(ps) - rank)))
        out[finite[j]] = running
    return out


def savefig(fig, path):
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def grid(n: int, width_per: float = 4.0, height: float = 3.4, **kwargs):
    """A 1 x n row of axes that always returns a flat list of axes."""
    fig, axes = plt.subplots(1, max(n, 1), figsize=(width_per * max(n, 1), height), **kwargs)
    return fig, list(np.atleast_1d(axes))


def switch_marks(ax, switch_turns, closed_turns=(), colour="black"):
    """Mark the switch turn: a line when it is unique, a band when it was drawn."""
    values = sorted({float(t) for t in _clean(switch_turns)})
    if not values:
        return
    if len(values) == 1:
        ax.axvline(values[0], color=colour, ls="--", lw=0.8)
    else:
        ax.axvspan(values[0], values[-1], color=colour, alpha=0.07, lw=0)
    closed = sorted({float(t) for t in _clean(closed_turns)})
    if closed:
        if len(closed) == 1:
            ax.axvline(closed[0], color="#b45309", ls="-.", lw=0.8)
        else:
            ax.axvspan(closed[0], closed[-1], color="#b45309", alpha=0.07, lw=0)


# ----------------------------------------------------------------------------- load

def q_columns(df: pd.DataFrame) -> list[str]:
    cols = [f"q_{a}" for a in E.ACTIONS if f"q_{a}" in df.columns]
    if cols:
        return cols
    return [f"q_{a.lower()}" for a in E.ACTIONS if f"q_{a.lower()}" in df.columns]


def q_entropy(row, q_cols):
    q = [row[c] for c in q_cols]
    if any(pd.isna(v) for v in q):
        return np.nan
    total = sum(q)
    if total <= 0:
        return np.nan
    return -sum((v / total) * math.log2(v / total) for v in q if v > 0)


def load(calls_path: Path, runs_path: Path, *, switch_turn_default=SWITCH_DEFAULT,
         post_len=POST_LEN_DEFAULT, entropy_valid_only=False):
    calls = pd.read_csv(calls_path, low_memory=False)
    runs = pd.read_csv(runs_path, low_memory=False)

    valid_col = resolve(runs, "valid")
    n_runs_raw = len(runs)
    if valid_col:
        runs = runs[as_bool(runs[valid_col])].copy()
    n_dropped_entropy = 0
    ev_col = resolve(runs, "entropy_valid")
    if entropy_valid_only and ev_col:
        keep = as_bool(runs[ev_col])
        n_dropped_entropy = int((~keep).sum())
        runs = runs[keep].copy()

    sw_col = resolve(runs, "switch_turn")
    runs["switch_turn_eff"] = (pd.to_numeric(runs[sw_col], errors="coerce")
                               if sw_col else pd.Series(np.nan, index=runs.index))
    runs["switch_turn_eff"] = runs["switch_turn_eff"].fillna(switch_turn_default).astype(int)
    cl_col = resolve(runs, "switch_closed")
    runs["switch_closed_eff"] = (pd.to_numeric(runs[cl_col], errors="coerce")
                                 if cl_col else pd.Series(np.nan, index=runs.index))
    runs["tau_read_eff"] = pd.to_numeric(column(runs, "tau_read"), errors="coerce")
    runs["run"] = runs.model + "|" + runs.condition + "|" + runs.seed.astype(str)

    keys = ["model", "condition", "seed"]
    calls = calls.merge(runs[keys + ["switch_turn_eff", "switch_closed_eff", "tau_read_eff"]],
                        on=keys, suffixes=("", "_run"))
    calls["run"] = calls.model + "|" + calls.condition + "|" + calls.seed.astype(str)
    for target in ("n_foreign", "n_placebo", "n_inert"):
        calls[target] = pd.to_numeric(column(calls, target), errors="coerce").fillna(0.0)

    active = calls[calls.action.isin(ACTIONS)].copy()
    active["H"] = pd.to_numeric(column(active, "H"), errors="coerce")
    active["n_tokens"] = pd.to_numeric(column(active, "n_tokens"), errors="coerce")
    active["log_tokens"] = np.log1p(active["n_tokens"])
    active["post"] = (active.turn >= active.switch_turn_eff).astype(int)
    active["rel_turn"] = active.turn - active.switch_turn_eff
    active["in_window"] = active.rel_turn < post_len
    q_cols = q_columns(active)
    active["H_decision"] = (active.apply(lambda r: q_entropy(r, q_cols), axis=1)
                            if q_cols else np.nan)

    models = sorted(set(runs.model) | set(active.model))
    conditions = order_conditions(set(runs.condition) | set(active.condition))
    agents = sorted(set(active.agent))
    meta = {
        "calls_table": str(calls_path), "runs_table": str(runs_path),
        "runs_in_table": n_runs_raw, "runs_valid": int(len(runs)),
        "runs_dropped_entropy_gate": n_dropped_entropy,
        "agent_turn_calls": int(len(active)), "models": models, "conditions": conditions,
        "agents": agents, "q_columns": q_cols,
        "switch_turns": sorted(int(t) for t in runs.switch_turn_eff.unique()),
        "switch_turn_randomised": bool(runs.switch_turn_eff.nunique() > 1),
        "switch_closed_turns": sorted(int(t) for t in _clean(runs.switch_closed_eff.unique())),
        "switch_turn_default_used": sw_col is None, "post_window_turns": post_len,
        "max_turn": int(active.turn.max()) if len(active) else 0,
        "cells": {f"{m}|{c}": int(len(cell(runs, model=m, condition=c))) for m in models for c in conditions},
    }
    return calls, active, runs, meta


def adjust(active: pd.DataFrame) -> pd.DataFrame:
    """Residual entropy after action type + log length, fitted per model on all conditions."""
    out = []
    for model, df in active.groupby("model"):
        df = df.dropna(subset=["H"]).copy()
        if df.empty:
            continue
        formula = "H ~ C(action) + log_tokens" if df.action.nunique() > 1 else "H ~ log_tokens"
        try:
            fit = smf.ols(formula, data=df).fit()
            df["H_adj"] = df["H"] - fit.fittedvalues + df["H"].mean()
        except Exception:
            df["H_adj"] = df["H"]
        out.append(df)
    return pd.concat(out) if out else active.assign(H_adj=np.nan)


# ----------------------------------------------------------------------------- A ground truth

def ground_truth(runs, ctx):
    models, conditions, colours = ctx["models"], ctx["conditions"], ctx["colours"]
    rows = []
    for (m, c), df in runs.groupby(["model", "condition"]):
        row = {"model": m, "condition": c, "runs": len(df)}
        for key, target in (("task_success", "task_success"), ("communication_verified", "communication_verified"),
                            ("complete_via_channel", "complete_via_verified_channel")):
            row[key] = float(as_bool(df[target]).mean()) if target in df.columns else np.nan
        row["both_complete"] = float((pd.to_numeric(df.n_complete, errors="coerce") >= 2).mean()) \
            if "n_complete" in df.columns else np.nan
        row["tau_read_median"] = float(df.tau_read_eff.median())
        row["mean_turns"] = float(pd.to_numeric(column(df, "turns_executed"), errors="coerce").mean())
        row["switch_turn_mean"] = float(df.switch_turn_eff.mean())
        if "grade_A3" in df.columns:
            row["observer_complete"] = float((df.grade_A3.astype(str) == "COMPLETE").mean())
            row["observer_provenance_ok"] = float(as_bool(df.A3_provenance_ok).mean()) \
                if "A3_provenance_ok" in df.columns else np.nan
        ev = resolve(df, "entropy_valid")
        row["entropy_valid"] = float(as_bool(df[ev]).mean()) if ev else np.nan
        rows.append(row)
    gt = pd.DataFrame(rows)
    gt.to_csv(ctx["stats"] / "A_ground_truth.csv", index=False)

    directions = sorted(c[:-len("_verdict")] for c in runs.columns if c.endswith("_verdict"))
    use = []
    for _, r in runs.iterrows():
        for d in directions:
            if str(r.get(f"{d}_verdict")) == "VERIFIED":
                use.append({"model": r.model, "condition": r.condition, "seed": r.seed, "direction": d,
                            "tau_write": r.get(f"{d}_tau_write"), "tau_read": r.get(f"{d}_tau_read"),
                            "tau_use": r.get(f"{d}_tau_use"), "switch_turn": r.switch_turn_eff})
    use = pd.DataFrame(use)
    use.to_csv(ctx["stats"] / "A_channel_timing.csv", index=False)

    fig, axes = grid(2, width_per=5.0)
    x = np.arange(len(models))
    width = 0.8 / max(len(conditions), 1)
    for i, c in enumerate(conditions):
        offset = (i - (len(conditions) - 1) / 2) * width
        succ = [scalar(gt, "task_success", model=m, condition=c) for m in models]
        comm = [scalar(gt, "communication_verified", model=m, condition=c) for m in models]
        axes[0].bar(x + offset, np.nan_to_num(succ), width, color=colours[c], label=f"{c}: task success")
        axes[0].scatter(x + offset, comm, color="black", marker="_", s=90, zorder=3,
                        label="verified communication" if i == 0 else None)
    axes[0].set_xticks(x, models, rotation=15, ha="right")
    axes[0].set_ylim(0, 1.34)
    axes[0].set_yticks(np.arange(0, 1.01, 0.25))
    axes[0].set_ylabel("share of runs")
    axes[0].set_title("A. Ground truth: task success and verified communication")
    axes[0].legend(fontsize=6.5, ncol=2, loc="upper left", handlelength=1.2, columnspacing=1.0)
    rng = _rng("gt_jitter")
    for i, m in enumerate(models):
        df = use[use.model == m] if len(use) else use
        if len(df):
            for col, colour, label, dy in (("tau_read", colours.get("switch", "#0b6e8a"), "τ_read", 0.12),
                                           ("tau_use", "#7c3aed", "τ_use", -0.12)):
                v = pd.to_numeric(df[col], errors="coerce").values
                axes[1].scatter(v + rng.uniform(-0.15, 0.15, len(v)), np.full(len(v), i + dy), s=12,
                                color=colour, label=label if i == 0 else None)
    switch_marks(axes[1], runs.switch_turn_eff, runs.switch_closed_eff)
    axes[1].set_yticks(range(len(models)), models)
    axes[1].set_xlabel("turn")
    axes[1].set_title("Verified directions: first cross-agent read and first use")
    if len(use):
        axes[1].legend(fontsize=7)
    savefig(fig, ctx["figures"] / "fig01_ground_truth.png")
    return gt, use


# ----------------------------------------------------------------------------- B/C trajectories, confounds

def trajectories(active, ctx, column_name="H", name="fig02_token_entropy_trajectories.png",
                 title="B. Token entropy per call (top-20 renormalised, bits/token)", min_runs=5):
    models, conditions, colours = ctx["models"], ctx["conditions"], ctx["colours"]
    if active[column_name].notna().sum() == 0:
        return pd.DataFrame()
    rows = []
    fig, axes = grid(len(models), sharey=True)
    turns = range(1, ctx["max_turn"] + 1)
    for ax, m in zip(axes, models):
        for c in conditions:
            df = cell(active, model=m, condition=c)
            if df.empty:
                continue
            per_run = df.groupby(["seed", "turn"])[column_name].mean().reset_index()
            pts = []
            for t in turns:
                v = _clean(per_run[per_run.turn == t][column_name])
                if len(v) >= min_runs:
                    mean, lo, hi = boot_ci(v, label=(m, c, t, column_name))
                    pts.append((t, mean, lo, hi))
                    rows.append({"model": m, "condition": c, "turn": t, "metric": column_name,
                                 "mean": mean, "ci_low": lo, "ci_high": hi, "n_runs": len(v)})
            if pts:
                t, mean, lo, hi = zip(*pts)
                ax.plot(t, mean, color=colours[c], lw=1.6, label=c)
                ax.fill_between(t, lo, hi, color=colours[c], alpha=0.15, lw=0)
        sub = cell(active, model=m)
        switch_marks(ax, sub.switch_turn_eff.unique(), sub.switch_closed_eff.unique())
        ax.set_title(m)
        ax.set_xlabel("turn")
    axes[0].set_ylabel("bits/token")
    axes[0].legend()
    fig.suptitle(title, x=0.01, ha="left", fontweight="bold")
    savefig(fig, ctx["figures"] / name)
    return pd.DataFrame(rows)


def aligned_trajectories(active, ctx, column_name="H_adj",
                         name="fig02d_event_aligned_trajectories.png"):
    """Same trajectories, but the x axis is turns since each run's switch turn."""
    models, conditions, colours = ctx["models"], ctx["conditions"], ctx["colours"]
    rows = []
    fig, axes = grid(len(models), sharey=True)
    rel_range = range(-7, ctx["post_window"] + 1)
    for ax, m in zip(axes, models):
        for c in conditions:
            df = cell(active, model=m, condition=c)
            if df.empty:
                continue
            per_run = df.groupby(["seed", "rel_turn"])[column_name].mean().reset_index()
            pts = []
            for rel in rel_range:
                v = _clean(per_run[per_run.rel_turn == rel][column_name])
                if len(v) >= 5:
                    mean, lo, hi = boot_ci(v, label=(m, c, rel, "rel"))
                    pts.append((rel, mean, lo, hi))
                    rows.append({"model": m, "condition": c, "rel_turn": rel, "metric": column_name,
                                 "mean": mean, "ci_low": lo, "ci_high": hi, "n_runs": len(v)})
            if pts:
                rel, mean, lo, hi = zip(*pts)
                ax.plot(rel, mean, color=colours[c], lw=1.6, label=c)
                ax.fill_between(rel, lo, hi, color=colours[c], alpha=0.15, lw=0)
        ax.axvline(0, color="black", ls="--", lw=0.8)
        ax.set_title(m)
        ax.set_xlabel("turn − switch turn of the run")
    axes[0].set_ylabel("adjusted bits/token")
    axes[0].legend()
    fig.suptitle("B''. Adjusted token entropy aligned on each run's switch turn",
                 x=0.01, ha="left", fontweight="bold")
    savefig(fig, ctx["figures"] / name)
    return pd.DataFrame(rows)


def action_mix(calls, active, ctx):
    models, conditions = ctx["models"], ctx["conditions"]
    by_action = (active.groupby(["model", "action"])
                 .agg(n=("H", "size"), H=("H", "mean"), tokens=("n_tokens", "mean")).reset_index())
    by_action.to_csv(ctx["stats"] / "C_entropy_by_action.csv", index=False)

    fig, axes = plt.subplots(len(models), len(conditions),
                             figsize=(4 * len(conditions), 2.4 * len(models)), sharex=True, sharey=True,
                             squeeze=False)
    for i, m in enumerate(models):
        for j, c in enumerate(conditions):
            ax = axes[i][j]
            df = calls[(calls.model == m) & (calls.condition == c) & calls.action.isin(ACTIONS + ["done"])]
            if len(df):
                share = df.groupby(["turn", "action"]).size().unstack(fill_value=0)
                share = share.div(share.sum(axis=1), axis=0)
                bottom = np.zeros(len(share))
                for a in ACTIONS + ["done"]:
                    if a in share:
                        ax.bar(share.index, share[a], bottom=bottom, color=ACTION_PALETTE[a], width=0.9, label=a)
                        bottom += share[a].values
                switch_marks(ax, df.switch_turn_eff.unique() - 0.5, [])
            else:
                ax.text(0.5, 0.5, "no runs", transform=ax.transAxes, ha="center", va="center",
                        fontsize=8, color="#94a3b8")
            if i == 0:
                ax.set_title(c)
            if j == 0:
                ax.set_ylabel(f"{m}\nshare of agent-turns")
    axes[0][0].legend(fontsize=7, ncol=5, loc="upper left", bbox_to_anchor=(0, 1.35))
    for ax in axes[-1]:
        ax.set_xlabel("turn")
    fig.suptitle("C. Action mix per turn (the main confound of per-call entropy)",
                 x=0.01, ha="left", fontweight="bold")
    savefig(fig, ctx["figures"] / "fig03_action_mix.png")
    return by_action


# ----------------------------------------------------------------------------- D/E difference in differences

def run_level_deltas(active, ctx) -> pd.DataFrame:
    """Per-run pre/post deltas, with the cut at each run's own switch turn."""
    metrics = ["H", "H_adj", "H_decision"]
    rows = []
    for (m, c, s), df in active.groupby(["model", "condition", "seed"]):
        df = df[df.in_window | (df.rel_turn < 0)]
        row = {"model": m, "condition": c, "seed": s, "switch_turn": int(df.switch_turn_eff.iloc[0]),
               "n_pre": int((df.rel_turn < 0).sum()), "n_post": int((df.rel_turn >= 0).sum())}
        for k in metrics:
            pre, post = df[df.rel_turn < 0][k].mean(), df[df.rel_turn >= 0][k].mean()
            row[f"{k}_pre"], row[f"{k}_post"], row[f"{k}_delta"] = pre, post, post - pre
        w = df[df.action == "write_log"]
        row["H_write_delta"] = w[w.rel_turn >= 0].H.mean() - w[w.rel_turn < 0].H.mean()
        rows.append(row)
    return pd.DataFrame(rows)


def did(active, ctx, n_perm=N_PERM_DEFAULT):
    models, conditions, colours = ctx["models"], ctx["conditions"], ctx["colours"]
    metrics = {"H": "raw token entropy", "H_adj": "action+length adjusted",
               "H_decision": "decision entropy H(q)", "H_write": "WRITE_LOG content only"}
    runlevel = run_level_deltas(active, ctx)
    runlevel.to_csv(ctx["stats"] / "D_run_level_deltas.csv", index=False)

    tests = []
    for m in models:
        for k in metrics:
            col = f"{k}_delta"
            groups = {c: _clean(cell(runlevel, model=m, condition=c).get(col, pd.Series(dtype=float)))
                      for c in conditions}
            for a, b in contrast_pairs(conditions):
                if len(groups[a]) == 0 or len(groups[b]) == 0:
                    tests.append({"model": m, "metric": k, "contrast": f"{a} - {b}", "did_bits": np.nan,
                                  "ci_low": np.nan, "ci_high": np.nan, "hedges_g": np.nan, "p_perm": np.nan,
                                  "auc": np.nan, "n_a": len(groups[a]), "n_b": len(groups[b])})
                    continue
                diff, p = perm_test(groups[a], groups[b], n=n_perm, label=(m, k, a, b))
                rng = _rng(("ci", m, k, a, b))
                boots = (rng.choice(groups[a], (4000, len(groups[a]))).mean(1)
                         - rng.choice(groups[b], (4000, len(groups[b]))).mean(1))
                lo, hi = np.percentile(boots, [2.5, 97.5])
                tests.append({"model": m, "metric": k, "contrast": f"{a} - {b}", "did_bits": diff,
                              "ci_low": float(lo), "ci_high": float(hi),
                              "hedges_g": hedges_g(groups[a], groups[b]), "p_perm": p,
                              "auc": auc(groups[a], groups[b]),
                              "n_a": len(groups[a]), "n_b": len(groups[b])})
    tests = pd.DataFrame(tests, columns=["model", "metric", "contrast", "did_bits", "ci_low",
                                         "ci_high", "hedges_g", "p_perm", "auc", "n_a", "n_b"])
    tests["p_holm"] = np.nan
    if len(tests):
        for _, idx in tests.groupby("metric").groups.items():
            tests.loc[idx, "p_holm"] = holm(tests.loc[idx, "p_perm"].values)
    tests.to_csv(ctx["stats"] / "D_did_tests.csv", index=False)

    fig, axes = plt.subplots(len(metrics), len(models), figsize=(4 * len(models), 2.6 * len(metrics)),
                             sharey="row", squeeze=False)
    rng = _rng("did_jitter")
    for i, (k, label) in enumerate(metrics.items()):
        for j, m in enumerate(models):
            ax = axes[i][j]
            for x, c in enumerate(conditions):
                v = _clean(cell(runlevel, model=m, condition=c).get(f"{k}_delta", pd.Series(dtype=float)))
                if not len(v):
                    continue
                ax.scatter(np.full(len(v), x) + rng.uniform(-0.12, 0.12, len(v)), v, s=10,
                           color=colours[c], alpha=0.7)
                mean, lo, hi = boot_ci(v, label=(m, c, k, "did"))
                ax.errorbar(x + 0.28, mean, yerr=[[mean - lo], [hi - mean]], fmt="o", color="black",
                            ms=4, capsize=2)
            ax.axhline(0, color="grey", lw=0.6)
            ax.set_xticks(range(len(conditions)), conditions, rotation=20, ha="right", fontsize=7)
            shown = [t for _, t in cell(tests, model=m, metric=k).iterrows() if not pd.isna(t.p_perm)]
            focal = conditions[-1]
            head = ([t for t in shown if t.contrast.startswith(f"{focal} - ")] or shown)[:2]
            ax.set_title(m, fontsize=8)
            if head:
                ax.text(0.02, 0.97, "\n".join(f"{t.contrast}: {t.did_bits:+.3f} (p={t.p_perm:.3f})"
                                              for t in head),
                        transform=ax.transAxes, va="top", ha="left", fontsize=6)
            if j == 0:
                ax.set_ylabel(f"Δ post−pre\n{label}")
    fig.suptitle("D. Run-level difference-in-differences (post minus pre, cut at each run's switch turn)",
                 x=0.01, ha="left", fontweight="bold")
    savefig(fig, ctx["figures"] / "fig04_did_run_level.png")

    mixed = []
    for m in models:
        df = cell(active, model=m)
        df = df[df.in_window | (df.rel_turn < 0)].dropna(subset=["H"]).copy()
        if df.empty or df.condition.nunique() < 2:
            continue
        present = [c for c in conditions if c in set(df.condition)]
        df["condition"] = pd.Categorical(df.condition, categories=present)
        formula = "H ~ C(condition) * post + C(action) + log_tokens"
        try:
            fit = smf.mixedlm(formula, df, groups=df["run"]).fit(method="lbfgs")
            for term in fit.params.index:
                if "post" in term or "condition" in term:
                    ci = fit.conf_int().loc[term]
                    mixed.append({"model": m, "term": term, "coef": fit.params[term], "ci_low": ci[0],
                                  "ci_high": ci[1], "p": fit.pvalues[term], "n_calls": len(df),
                                  "n_runs": df.run.nunique()})
        except Exception as exc:  # report rather than hide
            mixed.append({"model": m, "term": "FAILED", "coef": np.nan, "p": np.nan, "error": str(exc)})
        try:
            ols = smf.ols(formula, df).fit(cov_type="cluster",
                                           cov_kwds={"groups": pd.factorize(df["run"])[0]})
            for term in ols.params.index:
                if ":post" in term:
                    ci = ols.conf_int().loc[term]
                    mixed.append({"model": m, "term": term + " [OLS cluster-robust]",
                                  "coef": ols.params[term], "ci_low": ci[0], "ci_high": ci[1],
                                  "p": ols.pvalues[term], "n_calls": len(df), "n_runs": df.run.nunique()})
        except Exception as exc:
            mixed.append({"model": m, "term": "OLS FAILED", "coef": np.nan, "p": np.nan, "error": str(exc)})
    mixed = pd.DataFrame(mixed, columns=["model", "term", "coef", "ci_low", "ci_high", "p",
                                         "n_calls", "n_runs", "error"])
    mixed.to_csv(ctx["stats"] / "E_mixed_model.csv", index=False)
    return runlevel, tests, mixed


# ----------------------------------------------------------------------------- G system entropy

def system_entropy(calls, ctx, n_perm=N_PERM_SYSTEM, min_pairs=5):
    models, conditions, colours = ctx["models"], ctx["conditions"], ctx["colours"]
    agents = ctx["agents"]
    q_cols = ctx["q_columns"]
    if not q_cols:
        return pd.DataFrame(), pd.DataFrame()
    pairs_of_agents = [(agents[i], agents[j]) for i in range(len(agents)) for j in range(i + 1, len(agents))]
    rows = []
    for m in models:
        for c in conditions:
            df = cell(calls, model=m, condition=c)
            if df.empty:
                continue
            for a1, a2 in pairs_of_agents:
                for t in range(1, ctx["max_turn"] + 1):
                    at = df[df.turn == t]
                    pairs_all, pairs_active = [], []
                    for _, g in at.groupby("seed"):
                        if not {a1, a2} <= set(g.agent):
                            continue
                        qs = []
                        for agent in (a1, a2):
                            r = g[g.agent == agent].iloc[0]
                            if r.action == "done":
                                qs.append({E.DONE: 1.0})
                            elif not pd.isna(r[q_cols[0]]):
                                qs.append({a: float(r[f"q_{a}"]) for a in E.ACTIONS if f"q_{a}" in g.columns})
                            else:
                                qs.append(None)
                        if None in qs:
                            continue
                        pairs_all.append(tuple(qs))
                        if all(E.DONE not in q for q in qs):
                            pairs_active.append(tuple(qs))
                    for variant, pairs in (("all_states", pairs_all), ("active_only", pairs_active)):
                        if len(pairs) < min_pairs:
                            continue
                        q1, q2 = [p[0] for p in pairs], [p[1] for p in pairs]
                        obs = E.mixture_mi(q1, q2)
                        rng = _rng(("sysmi", m, c, a1, a2, t, variant))
                        null = np.asarray([E.mixture_mi(q1, [q2[k] for k in rng.permutation(len(q2))])["I_bits"]
                                           for _ in range(n_perm)])
                        rows.append({"model": m, "condition": c, "pair": f"{a1}|{a2}", "turn": t,
                                     "variant": variant, "n_pairs": len(pairs), "H1": obs["H1_bits"],
                                     "H2": obs["H2_bits"], "sum_H": obs["sum_H_bits"], "I": obs["I_bits"],
                                     "H_system": obs["H_system_bits"], "I_null_mean": null.mean(),
                                     "I_null_95": np.percentile(null, 95),
                                     "I_excess": obs["I_bits"] - null.mean(),
                                     "p_perm": (np.sum(null >= obs["I_bits"] - 1e-12) + 1) / (n_perm + 1)})
    sysdf = pd.DataFrame(rows)
    sysdf.to_csv(ctx["stats"] / "G_system_entropy.csv", index=False)
    if sysdf.empty:
        return sysdf, pd.DataFrame()

    main_pair = sysdf.pair.iloc[0] if len(pairs_of_agents) == 1 else f"{agents[0]}|{agents[1]}"
    for variant in ("all_states", "active_only"):
        fig, axes = plt.subplots(3, len(models), figsize=(4 * len(models), 2.6 * 3), sharex=True,
                                 squeeze=False)
        for j, m in enumerate(models):
            for c in conditions:
                d = sysdf[(sysdf.model == m) & (sysdf.condition == c) & (sysdf.variant == variant)
                          & (sysdf.pair == main_pair)]
                if d.empty:
                    continue
                axes[0][j].plot(d.turn, d.sum_H, color=colours[c], lw=1, ls=":", alpha=0.8)
                axes[0][j].plot(d.turn, d.H_system, color=colours[c], lw=1.6, label=c)
                axes[1][j].plot(d.turn, d.I, color=colours[c], lw=1.6, label=c)
                axes[1][j].plot(d.turn, d.I_null_95, color=colours[c], lw=0.8, ls="--", alpha=0.7)
                sig = d[d.p_perm < 0.05]
                axes[1][j].scatter(sig.turn, sig.I, color=colours[c], s=14, zorder=3)
                axes[2][j].plot(d.turn, d.I_excess, color=colours[c], lw=1.6)
            sub = cell(calls, model=m)
            for row in range(3):
                switch_marks(axes[row][j], sub.switch_turn_eff.unique(), sub.switch_closed_eff.unique())
            axes[0][j].set_title(m)
            axes[2][j].set_xlabel("turn")
            axes[2][j].axhline(0, color="grey", lw=0.6)
        axes[0][0].set_ylabel("H(X1,X2) bits\n(dotted: H1+H2)")
        axes[1][0].set_ylabel("I(X1;X2) bits\n(dashed: null 95th pct;\ndots: p<0.05)")
        axes[2][0].set_ylabel("I − null mean")
        axes[0][0].legend()
        fig.suptitle(f"G. System entropy over the action variable across runs "
                     f"({variant.replace('_', ' ')}, pair {main_pair})", x=0.01, ha="left", fontweight="bold")
        savefig(fig, ctx["figures"] / f"fig05_system_entropy_{variant}.png")

    post = sysdf[sysdf.turn >= sysdf.model.map(lambda m: min(ctx["switch_by_model"].get(m, SWITCH_DEFAULT)))]
    summary = (post.groupby(["model", "condition", "pair", "variant"])
               .agg(post_H_system=("H_system", "mean"), post_I=("I", "mean"),
                    post_I_excess=("I_excess", "mean"),
                    post_turns_sig=("p_perm", lambda p: int((p < 0.05).sum())),
                    post_turns=("p_perm", "size")).reset_index())
    pre = sysdf[sysdf.turn < sysdf.model.map(lambda m: min(ctx["switch_by_model"].get(m, SWITCH_DEFAULT)))]
    pre_sum = (pre.groupby(["model", "condition", "pair", "variant"])
               .agg(pre_H_system=("H_system", "mean"), pre_I=("I", "mean")).reset_index())
    summary = summary.merge(pre_sum, on=["model", "condition", "pair", "variant"], how="left")
    summary.to_csv(ctx["stats"] / "G_system_entropy_window_summary.csv", index=False)
    return sysdf, summary


# ----------------------------------------------------------------------------- H aligned, I post-read spike

def first_foreign_turn(active: pd.DataFrame) -> pd.Series:
    """Per run: first turn whose READ_LOG returned anything written by another agent."""
    got = active[(active.n_foreign > 0) | (active.n_placebo > 0) | (active.n_inert > 0)]
    return got.groupby("run").turn.min()


def aligned(active, runs, ctx):
    models, conditions, colours = ctx["models"], ctx["conditions"], ctx["colours"]
    anchor = first_foreign_turn(active)
    tau_read = runs.set_index("run").tau_read_eff.dropna()
    anchor = tau_read.combine_first(anchor)
    rows = []
    fig, axes = grid(len(models), sharey=True)
    for ax, m in zip(axes, models):
        for c in conditions:
            if c == "base":
                continue
            df = cell(active, model=m, condition=c).copy()
            if df.empty:
                continue
            df["tau"] = df.run.map(anchor)
            df = df.dropna(subset=["tau"])
            if df.empty:
                continue
            df["rel"] = df.turn - df.tau
            per = df.groupby(["seed", "rel"]).H_adj.mean().reset_index()
            pts = []
            for rel in range(-7, 11):
                v = _clean(per[per.rel == rel].H_adj)
                if len(v) >= 5:
                    mean, lo, hi = boot_ci(v, label=(m, c, rel, "aligned"))
                    pts.append((rel, mean, lo, hi))
                    rows.append({"model": m, "condition": c, "rel_turn": rel, "mean": mean,
                                 "ci_low": lo, "ci_high": hi, "n": len(v)})
            if pts:
                r, mean, lo, hi = zip(*pts)
                ax.plot(r, mean, color=colours[c], lw=1.6, label=c)
                ax.fill_between(r, lo, hi, color=colours[c], alpha=0.15, lw=0)
        ax.axvline(0, color="black", ls="--", lw=0.8)
        ax.set_title(m)
        ax.set_xlabel("turn − first foreign read")
    axes[0].set_ylabel("adjusted bits/token")
    axes[0].legend(fontsize=7)
    fig.suptitle("H. Adjusted token entropy aligned on the first read that returned foreign entries",
                 x=0.01, ha="left", fontweight="bold")
    savefig(fig, ctx["figures"] / "fig06_aligned_first_foreign_read.png")
    pd.DataFrame(rows, columns=["model", "condition", "rel_turn", "mean", "ci_low", "ci_high", "n"]
                 ).to_csv(ctx["stats"] / "H_aligned.csv", index=False)

    act = active.sort_values(["run", "agent", "turn"]).copy()
    act["prev_action"] = act.groupby(["run", "agent"]).action.shift()
    for src in ("n_foreign", "n_placebo", "n_inert"):
        act[f"prev_{src}"] = act.groupby(["run", "agent"])[src].shift()
    after = act[act.prev_action == "read_log"].copy()
    after["read_returned"] = np.select(
        [after.prev_n_foreign > 0, after.prev_n_placebo > 0, after.prev_n_inert > 0],
        ["peer entries", "decoy entries", "inert entries"], "own entries only")
    post = after[after.rel_turn >= 0]
    spike = (post.groupby(["model", "read_returned"])
             .agg(n=("H", "size"), H=("H", "mean"), H_adj=("H_adj", "mean"),
                  H_decision=("H_decision", "mean")).reset_index())
    spike.to_csv(ctx["stats"] / "I_post_read_spike.csv", index=False)

    kinds = ["own entries only", "peer entries", "decoy entries", "inert entries"]
    kcol = {"own entries only": CONDITION_COLOURS["base"], "peer entries": CONDITION_COLOURS["switch"],
            "decoy entries": CONDITION_COLOURS["placebo"], "inert entries": CONDITION_COLOURS["placebo_inert"]}
    fig, ax = plt.subplots(figsize=(2.6 * max(len(models), 2), 3.2))
    for i, m in enumerate(models):
        for j, k in enumerate(kinds):
            v = _clean(post[(post.model == m) & (post.read_returned == k)].H_adj)
            if len(v) >= 5:
                mean, lo, hi = boot_ci(v, label=(m, k, "spike"))
                ax.errorbar(i + (j - 1.5) * 0.2, mean, yerr=[[mean - lo], [hi - mean]], fmt="o",
                            color=kcol[k], capsize=2, label=k if i == 0 else None)
                ax.text(i + (j - 1.5) * 0.2, hi, f"n={len(v)}", ha="center", va="bottom", fontsize=6)
    ax.set_xticks(range(len(models)), models, rotation=15, ha="right")
    ax.set_ylabel("adjusted bits/token")
    ax.legend(fontsize=7)
    ax.set_title("I. Entropy of the call right after a READ_LOG (post window), by what the read returned")
    savefig(fig, ctx["figures"] / "fig07_post_read_spike.png")
    return spike


# ----------------------------------------------------------------------------- J detection

def detection(active, runs, runlevel, ctx):
    models, conditions, colours = ctx["models"], ctx["conditions"], ctx["colours"]
    positive = "switch" if "switch" in conditions else conditions[-1]
    control = "base" if "base" in conditions else conditions[0]
    others = [c for c in conditions if c != positive]
    roc_rows = []
    fig, axes = grid(len(models), height=3.6)
    for ax, m in zip(axes, models):
        rl = cell(runlevel, model=m)
        drawn = False
        for other, style in zip(others, ["-", "--", ":", "-."] * 3):
            pos = _clean(cell(rl, condition=positive).get("H_adj_delta", pd.Series(dtype=float)))
            neg = _clean(cell(rl, condition=other).get("H_adj_delta", pd.Series(dtype=float)))
            if not len(pos) or not len(neg):
                continue
            thresholds = np.unique(np.concatenate([pos, neg, [np.inf, -np.inf]]))
            tpr = [np.mean(pos >= th) for th in thresholds]
            fpr = [np.mean(neg >= th) for th in thresholds]
            a = auc(pos, neg)
            ax.plot(fpr, tpr, ls=style, color=colours.get(other, "#334155"),
                    label=f"{positive} vs {other}: AUC {a:.2f}")
            drawn = True
            roc_rows.append({"model": m, "contrast": f"{positive} vs {other}",
                             "statistic": "H_adj_delta", "auc": a, "n_pos": len(pos), "n_neg": len(neg)})
            posd = _clean(cell(rl, condition=positive).get("H_decision_delta", pd.Series(dtype=float)))
            negd = _clean(cell(rl, condition=other).get("H_decision_delta", pd.Series(dtype=float)))
            roc_rows.append({"model": m, "contrast": f"{positive} vs {other}",
                             "statistic": "H_decision_delta", "auc": auc(posd, negd),
                             "n_pos": len(posd), "n_neg": len(negd)})
        ax.plot([0, 1], [0, 1], color="grey", lw=0.6)
        ax.set_title(m)
        ax.set_xlabel("false positive rate")
        if drawn:
            ax.legend(fontsize=7, loc="lower right")
    axes[0].set_ylabel("true positive rate")
    fig.suptitle(f"J1. Run-level ROC: does the adjusted entropy change separate {positive} runs?",
                 x=0.01, ha="left", fontweight="bold")
    savefig(fig, ctx["figures"] / "fig08_run_level_roc.png")

    cusum_rows = []
    fig, axes = grid(len(models), sharey=True)
    for ax, m in zip(axes, models):
        df = cell(active, model=m)
        df = df[df.in_window | (df.rel_turn < 0)]
        if df.empty:
            continue
        series, switches = {}, {}
        for (c, seed), g in df.groupby(["condition", "seed"]):
            sw = int(g.switch_turn_eff.iloc[0])
            end = sw + ctx["post_window"] - 1
            series[(c, seed)] = g.groupby("turn").H_adj.mean().reindex(range(1, end + 1))
            switches[(c, seed)] = sw
        control_pre = [s.loc[1:switches[k] - 1].dropna().values for k, s in series.items() if k[0] == control]
        if not control_pre or not len(np.concatenate(control_pre)):
            continue
        base_pre = np.concatenate(control_pre)
        mu, sd = base_pre.mean(), base_pre.std(ddof=1) or 1.0

        def track(s, k=0.5):
            z = ((s - mu) / sd).fillna(0.0)
            up = lo = 0.0
            out = []
            for t, v in z.items():
                up, lo = max(0.0, up + v - k), max(0.0, lo - v - k)
                out.append((t, max(up, lo)))
            return out

        base_max = [max((v for t, v in track(s) if t >= switches[k]), default=0.0)
                    for k, s in series.items() if k[0] == control]
        h = float(np.percentile(base_max, 95))
        for (c, seed), s in series.items():
            sw = switches[(c, seed)]
            alarm = next((t for t, v in track(s) if t >= sw and v > h), None)
            values = s.fillna(s.mean()).values.reshape(-1, 1)
            try:
                pelt = rpt.Pelt(model="l2", min_size=3).fit(values).predict(pen=3 * sd ** 2)
            except Exception:
                pelt = []
            tau = runs.set_index(["model", "condition", "seed"]).tau_read_eff.get((m, c, seed), np.nan)
            cusum_rows.append({"model": m, "condition": c, "seed": seed, "switch_turn": sw,
                               "threshold_h": h, "alarm_turn": alarm, "tau_read": tau,
                               "delay_vs_switch": (alarm - sw) if alarm else np.nan,
                               "delay": (alarm - tau) if (alarm and not pd.isna(tau)) else np.nan,
                               "pelt_breakpoints": "|".join(str(b + 1) for b in pelt[:-1])})
        cr = pd.DataFrame([r for r in cusum_rows if r["model"] == m])
        rates = cr.groupby("condition").alarm_turn.apply(lambda a: a.notna().mean())
        ax.bar(range(len(conditions)), [rates.get(c, 0) for c in conditions],
               color=[colours[c] for c in conditions])
        ax.set_xticks(range(len(conditions)), conditions, rotation=20, ha="right", fontsize=7)
        delays = _clean(cr[cr.condition == positive].delay)
        med = np.median(delays) if len(delays) else float("nan")
        ax.set_title(f"{m}\nalarm rate (h={h:.1f}); {positive} median delay {med:+.0f} turns", fontsize=8)
        ax.axhline(0.05, color="grey", ls=":", lw=0.8)
    axes[0].set_ylabel("share of runs with an alarm in the post window")
    fig.suptitle(f"J2. CUSUM on adjusted entropy, calibrated to 5% false alarms on {control} runs",
                 x=0.01, ha="left", fontweight="bold")
    savefig(fig, ctx["figures"] / "fig09_cusum_detection.png")

    cusum = pd.DataFrame(cusum_rows)
    cusum.to_csv(ctx["stats"] / "J_cusum_runs.csv", index=False)
    roc = pd.DataFrame(roc_rows, columns=["model", "contrast", "statistic", "auc", "n_pos", "n_neg"])
    roc.to_csv(ctx["stats"] / "J_roc.csv", index=False)
    det = pd.DataFrame()
    if len(cusum):
        det = (cusum.groupby(["model", "condition"])
               .agg(alarm_rate=("alarm_turn", lambda a: a.notna().mean()),
                    median_delay=("delay", "median"),
                    median_delay_vs_switch=("delay_vs_switch", "median"),
                    threshold_h=("threshold_h", "first")).reset_index())
        det.to_csv(ctx["stats"] / "J_cusum_summary.csv", index=False)
    return det, roc


# ----------------------------------------------------------------------------- main

def run_analysis(calls_path: Path, runs_path: Path, out: Path, *, switch_turn=SWITCH_DEFAULT,
                 post_len=POST_LEN_DEFAULT, n_perm=N_PERM_DEFAULT, n_perm_system=N_PERM_SYSTEM,
                 skip_system=False, entropy_valid_only=False) -> dict:
    fig_dir, stats_dir = out / "figures", out / "stats"
    fig_dir.mkdir(parents=True, exist_ok=True)
    stats_dir.mkdir(parents=True, exist_ok=True)
    calls, active, runs, meta = load(calls_path, runs_path, switch_turn_default=switch_turn,
                                     post_len=post_len, entropy_valid_only=entropy_valid_only)
    active = adjust(active)
    ctx = {"figures": fig_dir, "stats": stats_dir, "models": meta["models"],
           "conditions": meta["conditions"], "agents": meta["agents"],
           "colours": condition_colours(meta["conditions"]), "max_turn": meta["max_turn"],
           "post_window": post_len, "q_columns": meta["q_columns"],
           "switch_by_model": {m: sorted(set(cell(runs, model=m).switch_turn_eff)) or [switch_turn]
                               for m in meta["models"]}}

    gt, timing = ground_truth(runs, ctx)
    traj = trajectories(active, ctx)
    traj_adj = trajectories(active, ctx, column_name="H_adj",
                            name="fig02b_adjusted_entropy_trajectories.png",
                            title="B'. Token entropy adjusted for action type and length (bits/token)")
    traj_dec = trajectories(active, ctx, column_name="H_decision",
                            name="fig02c_decision_entropy_trajectories.png",
                            title="F. Decision entropy H(q): uncertainty over the next action (bits)")
    traj_rel = aligned_trajectories(active, ctx) if meta["switch_turn_randomised"] else pd.DataFrame()
    pd.concat([t for t in (traj, traj_adj, traj_dec) if len(t)]).to_csv(
        stats_dir / "B_trajectories.csv", index=False)
    if len(traj_rel):
        traj_rel.to_csv(stats_dir / "B_trajectories_event_aligned.csv", index=False)
    by_action = action_mix(calls, active, ctx)
    runlevel, tests, mixed = did(active, ctx, n_perm=n_perm)
    if skip_system:
        sysdf, sys_summary = pd.DataFrame(), pd.DataFrame()
    else:
        sysdf, sys_summary = system_entropy(calls, ctx, n_perm=n_perm_system)
    spike = aligned(active, runs, ctx)
    det, roc = detection(active, runs, runlevel, ctx)

    summary = {
        "data": meta,
        "ground_truth": gt.to_dict("records"),
        "entropy_by_action": by_action.to_dict("records"),
        "did_tests": tests.to_dict("records"),
        "mixed_model": mixed.to_dict("records"),
        "system_entropy_window": sys_summary.to_dict("records") if len(sys_summary) else [],
        "post_read_spike": spike.to_dict("records"),
        "cusum": det.to_dict("records") if len(det) else [],
        "roc": roc.to_dict("records") if len(roc) else [],
    }
    (stats_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=float))
    return {"figures": sorted(p.name for p in fig_dir.iterdir()),
            "stats": sorted(p.name for p in stats_dir.iterdir()),
            "cells": meta["cells"], "switch_turns": meta["switch_turns"]}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("exp", nargs="?", type=Path, help="experiment directory holding tables_<phase>/")
    ap.add_argument("--phase", default="full")
    ap.add_argument("--calls", type=Path, help="explicit calls table (csv or csv.gz)")
    ap.add_argument("--runs", type=Path, help="explicit runs table")
    ap.add_argument("--out", type=Path, help="output directory (default <exp>/analysis)")
    ap.add_argument("--switch-turn", type=int, default=SWITCH_DEFAULT,
                    help="fallback switch turn when the tables carry no switch_turn_effective")
    ap.add_argument("--post-len", type=int, default=POST_LEN_DEFAULT,
                    help="length of the post window in turns, counted from the switch turn")
    ap.add_argument("--n-perm", type=int, default=N_PERM_DEFAULT)
    ap.add_argument("--n-perm-system", type=int, default=N_PERM_SYSTEM)
    ap.add_argument("--skip-system", action="store_true", help="skip analysis G (the slow one)")
    ap.add_argument("--entropy-valid-only", action="store_true",
                    help="drop runs failing the logprob integrity gate (entropy_valid=False)")
    args = ap.parse_args(argv)

    if args.calls and args.runs:
        calls_path, runs_path = args.calls, args.runs
        out = args.out or (args.exp / "analysis" if args.exp else calls_path.parent / "analysis")
    elif args.exp:
        tables = args.exp / f"tables_{args.phase}"
        calls_path, runs_path = tables / "calls.csv", tables / "runs.csv"
        out = args.out or args.exp / "analysis"
    else:
        ap.error("give an experiment directory or both --calls and --runs")
    print(json.dumps(run_analysis(calls_path, runs_path, out, switch_turn=args.switch_turn,
                                  post_len=args.post_len, n_perm=args.n_perm,
                                  n_perm_system=args.n_perm_system, skip_system=args.skip_system,
                                  entropy_valid_only=args.entropy_valid_only), indent=1))


if __name__ == "__main__":
    main()
