#!/usr/bin/env python3
"""Entropy analysis of exp1 (two-agent shared log, base / switch / placebo).

Inputs : <exp>/tables_full/{calls.csv, runs.csv}  (produced by ../analyze.py)
Outputs: <exp>/analysis/{figures/*.png, stats/*.csv, stats/summary.json}

Requirements (analysis only; see requirements.txt): numpy, scipy, pandas, matplotlib,
statsmodels, ruptures.

Analyses (all run-level inference; runs are the independent unit)
  A  ground truth       task success, verified communication, tau_read / tau_use
  B  token entropy      trajectories per model x condition, 95% bootstrap CIs
  C  confound check     action mix per turn; entropy by action type
  D  DiD                per-run Delta = mean(post: turns 8-20) - mean(pre: 1-7), raw and
                        adjusted for action type + log length; permutation tests vs base
  E  mixed model        H ~ condition*post + C(action) + log1p(n_tokens) + (1 | run)
  F  decision entropy   entropy of the first-token action distribution q(a)
  G  system entropy     H(X1,X2) = H(X1) + H(X2) - I(X1;X2) over the action variable across
                        runs; pairing-permutation null for I; all-states and active-only
  H  aligned            token entropy aligned on the first cross-agent read (tau_read)
  I  post-read spike    entropy of the call right after a READ_LOG, by what the read returned
  J  detection          run-level ROC (switch vs base / placebo); CUSUM calibrated to 5%
                        false alarms on base runs; detection delay vs tau_read; PELT
"""

from __future__ import annotations

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

MODELS = ["gpt-4o-mini", "llama-3.3-70b", "qwen3-235b"]
CONDITIONS = ["base", "switch", "placebo"]
THEMES = {
    "light": {"colours": {"base": "#64748b", "switch": "#0b6e8a", "placebo": "#c2410c"},
              "bg": "#ffffff", "ink": "#13212b", "muted": "#8a99a3", "accent2": "#7c3aed", "fig_dir": "figures"},
    "dark": {"colours": {"base": "#94a3b8", "switch": "#56b6d1", "placebo": "#efa35c"},
             "bg": "#152027", "ink": "#e3ebed", "muted": "#6f8089", "accent2": "#a78bfa", "fig_dir": "figures_dark"},
}
THEME = "light"
COLOURS = dict(THEMES[THEME]["colours"])
INK, MUTED = THEMES[THEME]["ink"], THEMES[THEME]["muted"]
ACTIONS = ["read_log", "write_log", "decrypt", "submit"]
SWITCH, WINDOW_END = 8, 20
RNG = np.random.default_rng(20260913)
Q_COLS = [f"q_{a}" for a in E.ACTIONS]

def apply_theme(name: str) -> None:
    """Switch colours and matplotlib styling for light or dark page backgrounds."""
    global THEME, INK, MUTED
    THEME = name
    t = THEMES[name]
    COLOURS.clear()
    COLOURS.update(t["colours"])
    INK, MUTED = t["ink"], t["muted"]
    plt.rcParams.update({"figure.facecolor": t["bg"], "axes.facecolor": t["bg"], "savefig.facecolor": t["bg"],
                         "text.color": t["ink"], "axes.labelcolor": t["ink"], "axes.edgecolor": t["muted"],
                         "xtick.color": t["ink"], "ytick.color": t["ink"], "grid.color": t["muted"],
                         "legend.labelcolor": t["ink"]})


plt.rcParams.update({"figure.dpi": 150, "savefig.dpi": 150, "font.size": 9, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.titleweight": "bold", "axes.titlesize": 10,
                     "legend.frameon": False})


# --------------------------------------------------------------------------- helpers

def boot_ci(values, n=2000, fn=np.mean):
    values = np.asarray([v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))])
    if len(values) == 0:
        return (np.nan, np.nan, np.nan)
    if len(values) == 1:
        return (float(fn(values)), np.nan, np.nan)
    idx = RNG.integers(0, len(values), size=(n, len(values)))
    boots = fn(values[idx], axis=1)
    return (float(fn(values)), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)))


def perm_test(a, b, n=10000):
    """Two-sided permutation test on the difference of means (run-level)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    observed = a.mean() - b.mean()
    pooled = np.concatenate([a, b])
    count = 0
    for _ in range(n):
        RNG.shuffle(pooled)
        if abs(pooled[:len(a)].mean() - pooled[len(a):].mean()) >= abs(observed) - 1e-12:
            count += 1
    return float(observed), (count + 1) / (n + 1)


def hedges_g(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    na, nb = len(a), len(b)
    sp = math.sqrt(((na - 1) * a.var(ddof=1) + (nb - 1) * b.var(ddof=1)) / (na + nb - 2))
    d = (a.mean() - b.mean()) / sp if sp > 0 else np.nan
    return d * (1 - 3 / (4 * (na + nb) - 9))


def auc(pos, neg):
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    pos, neg = pos[~np.isnan(pos)], neg[~np.isnan(neg)]
    if not len(pos) or not len(neg):
        return np.nan
    u = stats.mannwhitneyu(pos, neg, alternative="two-sided").statistic
    return float(u / (len(pos) * len(neg)))


def q_entropy(row):
    q = [row[c] for c in Q_COLS]
    if any(pd.isna(v) for v in q):
        return np.nan
    return -sum(v * math.log2(v) for v in q if v > 0)


def savefig(fig, path):
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


# --------------------------------------------------------------------------- load

def load(exp: Path):
    calls = pd.read_csv(exp / "tables_full" / "calls.csv", low_memory=False)
    runs = pd.read_csv(exp / "tables_full" / "runs.csv")
    runs = runs[runs["valid"]].copy()
    calls = calls.merge(runs[["model", "condition", "seed"]], on=["model", "condition", "seed"])
    calls["run"] = calls["model"] + "|" + calls["condition"] + "|" + calls["seed"].astype(str)
    active = calls[calls["action"].isin(ACTIONS)].copy()
    active["H"] = active["mean_H_renorm_bits"]
    active["log_tokens"] = np.log1p(active["n_tokens"])
    active["post"] = (active["turn"] >= SWITCH).astype(int)
    active["H_decision"] = active.apply(q_entropy, axis=1)
    return calls, active, runs


def adjust(active):
    """Residual entropy after action type + log length, fitted per model on all conditions."""
    out = []
    for model, df in active.groupby("model"):
        df = df.dropna(subset=["H"]).copy()
        fit = smf.ols("H ~ C(action) + log_tokens", data=df).fit()
        df["H_adj"] = df["H"] - fit.fittedvalues + df["H"].mean()
        out.append(df)
    return pd.concat(out)


# --------------------------------------------------------------------------- A ground truth

def ground_truth(runs, fig_dir, stats_dir):
    rows = []
    for (m, c), df in runs.groupby(["model", "condition"]):
        rows.append({"model": m, "condition": c, "runs": len(df),
                     "task_success": df.task_success.mean(), "communication_verified": df.communication_verified.mean(),
                     "complete_via_channel": df.complete_via_verified_channel.mean(),
                     "both_complete": (df.n_complete == 2).mean(),
                     "tau_read_median": df.tau_first_foreign_read.median(),
                     "mean_turns": df.turns_executed.mean()})
    gt = pd.DataFrame(rows)
    gt.to_csv(stats_dir / "A_ground_truth.csv", index=False)
    use = []
    for _, r in runs[runs.condition == "switch"].iterrows():
        for d in ("A1->A2", "A2->A1"):
            if r[f"{d}_verdict"] == "VERIFIED":
                use.append({"model": r.model, "direction": d, "tau_write": r[f"{d}_tau_write"],
                            "tau_read": r[f"{d}_tau_read"], "tau_use": r[f"{d}_tau_use"]})
    use = pd.DataFrame(use)
    use.to_csv(stats_dir / "A_channel_timing.csv", index=False)

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.4))
    x = np.arange(len(MODELS))
    width = 0.26
    for i, c in enumerate(CONDITIONS):
        vals = [gt[(gt.model == m) & (gt.condition == c)].task_success.item() for m in MODELS]
        comm = [gt[(gt.model == m) & (gt.condition == c)].communication_verified.item() for m in MODELS]
        axes[0].bar(x + (i - 1) * width, vals, width, color=COLOURS[c], label=f"{c}: task success")
        axes[0].scatter(x + (i - 1) * width, comm, color=INK, marker="_", s=120, zorder=3,
                        label="verified communication" if i == 0 else None)
    axes[0].set_xticks(x, MODELS)
    axes[0].set_ylim(0, 1.05)
    axes[0].set_ylabel("share of runs")
    axes[0].set_title("A. Ground truth: task success and verified communication")
    axes[0].legend(fontsize=7, ncol=2, loc="upper left")
    for i, m in enumerate(MODELS):
        df = use[use.model == m]
        axes[1].scatter(df.tau_read + RNG.uniform(-0.15, 0.15, len(df)), np.full(len(df), i + 0.12), s=12,
                        color=COLOURS["switch"], label="τ_read" if i == 0 else None)
        axes[1].scatter(df.tau_use + RNG.uniform(-0.15, 0.15, len(df)), np.full(len(df), i - 0.12), s=12,
                        color=THEMES[THEME]["accent2"], label="τ_use" if i == 0 else None)
    axes[1].axvline(SWITCH, color=INK, ls="--", lw=0.8)
    axes[1].set_yticks(range(len(MODELS)), MODELS)
    axes[1].set_xlabel("turn")
    axes[1].set_title("Switch runs: first cross-agent read and first use")
    axes[1].legend(fontsize=7)
    savefig(fig, fig_dir / "fig01_ground_truth.png")
    return gt, use


# --------------------------------------------------------------------------- B/C trajectories and confounds

def trajectories(active, fig_dir, stats_dir, column="H", name="fig02_token_entropy_trajectories.png",
                 title="B. Token entropy per call (top-20 renormalised, bits/token)"):
    rows = []
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.4), sharey=True)
    for ax, m in zip(axes, MODELS):
        for c in CONDITIONS:
            df = active[(active.model == m) & (active.condition == c)]
            # average agents within a run-turn first, then across runs
            per_run = df.groupby(["seed", "turn"])[column].mean().reset_index()
            pts = []
            for t in range(1, 31):
                v = per_run[per_run.turn == t][column].values
                if len(v) >= 5:
                    mean, lo, hi = boot_ci(v)
                    pts.append((t, mean, lo, hi, len(v)))
                    rows.append({"model": m, "condition": c, "turn": t, "metric": column, "mean": mean,
                                 "ci_low": lo, "ci_high": hi, "n_runs": len(v)})
            if pts:
                t, mean, lo, hi, _ = zip(*pts)
                ax.plot(t, mean, color=COLOURS[c], lw=1.6, label=c)
                ax.fill_between(t, lo, hi, color=COLOURS[c], alpha=0.15, lw=0)
        ax.axvline(SWITCH, color=INK, ls="--", lw=0.8)
        ax.axvline(WINDOW_END, color=MUTED, ls=":", lw=0.8)
        ax.set_title(m)
        ax.set_xlabel("turn")
    axes[0].set_ylabel("bits/token")
    axes[0].legend()
    fig.suptitle(title, x=0.01, ha="left", fontweight="bold")
    savefig(fig, fig_dir / name)
    return pd.DataFrame(rows)


def action_mix(calls, active, fig_dir, stats_dir):
    by_action = active.groupby(["model", "action"]).agg(n=("H", "size"), H=("H", "mean"), tokens=("n_tokens", "mean")).reset_index()
    by_action.to_csv(stats_dir / "C_entropy_by_action.csv", index=False)
    palette = {"read_log": "#94a3b8", "write_log": "#0b6e8a", "decrypt": "#eab308", "submit": "#16a34a", "done": "#e5e7eb"}
    fig, axes = plt.subplots(3, 3, figsize=(12, 7), sharex=True, sharey=True)
    for i, m in enumerate(MODELS):
        for j, c in enumerate(CONDITIONS):
            df = calls[(calls.model == m) & (calls.condition == c) & calls.action.isin(ACTIONS + ["done"])]
            share = df.groupby(["turn", "action"]).size().unstack(fill_value=0)
            share = share.div(share.sum(axis=1), axis=0)
            bottom = np.zeros(len(share))
            for a in ACTIONS + ["done"]:
                if a in share:
                    axes[i, j].bar(share.index, share[a], bottom=bottom, color=palette[a], width=0.9, label=a)
                    bottom += share[a].values
            axes[i, j].axvline(SWITCH - 0.5, color=INK, ls="--", lw=0.8)
            if i == 0:
                axes[i, j].set_title(c)
            if j == 0:
                axes[i, j].set_ylabel(f"{m}\nshare of agent-turns")
    axes[0, 0].legend(fontsize=7, ncol=5, loc="upper left", bbox_to_anchor=(0, 1.35))
    for ax in axes[-1]:
        ax.set_xlabel("turn")
    fig.suptitle("C. Action mix per turn (the main confound of per-call entropy)", x=0.01, ha="left", fontweight="bold")
    savefig(fig, fig_dir / "fig03_action_mix.png")
    return by_action


# --------------------------------------------------------------------------- D/E difference in differences

def did(active, fig_dir, stats_dir):
    metrics = {"H": "raw token entropy", "H_adj": "action+length adjusted", "H_decision": "decision entropy H(q)"}
    run_rows = []
    for (m, c, s), df in active.groupby(["model", "condition", "seed"]):
        df = df[df.turn <= WINDOW_END]
        row = {"model": m, "condition": c, "seed": s}
        for k in metrics:
            pre, post = df[df.turn < SWITCH][k].mean(), df[df.turn >= SWITCH][k].mean()
            row[f"{k}_pre"], row[f"{k}_post"], row[f"{k}_delta"] = pre, post, post - pre
        w = df[df.action == "write_log"]
        row["H_write_delta"] = w[w.turn >= SWITCH].H.mean() - w[w.turn < SWITCH].H.mean()
        run_rows.append(row)
    runlevel = pd.DataFrame(run_rows)
    runlevel.to_csv(stats_dir / "D_run_level_deltas.csv", index=False)
    metrics["H_write"] = "WRITE_LOG content only"

    tests = []
    for m in MODELS:
        for k in metrics:
            col = f"{k}_delta"
            groups = {c: runlevel[(runlevel.model == m) & (runlevel.condition == c)][col].values for c in CONDITIONS}
            for a, b in (("switch", "base"), ("placebo", "base"), ("switch", "placebo")):
                diff, p = perm_test(groups[a], groups[b])
                tests.append({"model": m, "metric": k, "contrast": f"{a} - {b}", "did_bits": diff,
                              "ci_low": boot_ci(groups[a])[0] - boot_ci(groups[b])[0] if False else np.nan,
                              "hedges_g": hedges_g(groups[a], groups[b]), "p_perm": p, "auc": auc(groups[a], groups[b]),
                              "n_a": int(np.sum(~np.isnan(groups[a]))), "n_b": int(np.sum(~np.isnan(groups[b])))})
    tests = pd.DataFrame(tests)
    # bootstrap CI for the difference of means
    for i, row in tests.iterrows():
        a_name, b_name = row.contrast.split(" - ")
        col = f"{row.metric}_delta"
        a = runlevel[(runlevel.model == row.model) & (runlevel.condition == a_name)][col].dropna().values
        b = runlevel[(runlevel.model == row.model) & (runlevel.condition == b_name)][col].dropna().values
        diffs = RNG.choice(a, (4000, len(a))).mean(1) - RNG.choice(b, (4000, len(b))).mean(1)
        tests.loc[i, ["ci_low", "ci_high"]] = np.percentile(diffs, [2.5, 97.5])
    # Holm correction within each metric family (3 models x 3 contrasts)
    tests["p_holm"] = np.nan
    for k, idx in tests.groupby("metric").groups.items():
        ps = tests.loc[idx, "p_perm"].values
        order = np.argsort(ps)
        adj = np.empty_like(ps)
        running = 0.0
        for rank, j in enumerate(order):
            running = max(running, min(1.0, ps[j] * (len(ps) - rank)))
            adj[j] = running
        tests.loc[idx, "p_holm"] = adj
    tests.to_csv(stats_dir / "D_did_tests.csv", index=False)

    fig, axes = plt.subplots(len(metrics), 3, figsize=(12, 9), sharey="row")
    for i, (k, label) in enumerate(metrics.items()):
        for j, m in enumerate(MODELS):
            ax = axes[i, j]
            for x, c in enumerate(CONDITIONS):
                v = runlevel[(runlevel.model == m) & (runlevel.condition == c)][f"{k}_delta"].dropna().values
                ax.scatter(np.full(len(v), x) + RNG.uniform(-0.12, 0.12, len(v)), v, s=10, color=COLOURS[c], alpha=0.7)
                mean, lo, hi = boot_ci(v)
                ax.errorbar(x + 0.28, mean, yerr=[[mean - lo], [hi - mean]], fmt="o", color=INK, ms=4, capsize=2)
            ax.axhline(0, color=MUTED, lw=0.6)
            ax.set_xticks(range(3), CONDITIONS)
            sw = tests[(tests.model == m) & (tests.metric == k) & (tests.contrast == "switch - base")].iloc[0]
            pl = tests[(tests.model == m) & (tests.metric == k) & (tests.contrast == "switch - placebo")].iloc[0]
            ax.set_title(f"{m}\nsw−base {sw.did_bits:+.3f} (p={sw.p_perm:.3f}) · sw−pl {pl.did_bits:+.3f} (p={pl.p_perm:.3f})", fontsize=8)
            if j == 0:
                ax.set_ylabel(f"Δ post−pre\n{label}")
    fig.suptitle("D. Run-level difference-in-differences (post turns 8–20 minus pre turns 1–7)", x=0.01, ha="left", fontweight="bold")
    savefig(fig, fig_dir / "fig04_did_run_level.png")

    mixed = []
    for m in MODELS:
        df = active[(active.model == m) & (active.turn <= WINDOW_END)].dropna(subset=["H"]).copy()
        df["condition"] = pd.Categorical(df.condition, categories=CONDITIONS)
        try:
            fit = smf.mixedlm("H ~ C(condition) * post + C(action) + log_tokens", df, groups=df["run"]).fit(method="lbfgs")
            for term in fit.params.index:
                if "post" in term or "condition" in term:
                    ci = fit.conf_int().loc[term]
                    mixed.append({"model": m, "term": term, "coef": fit.params[term], "ci_low": ci[0], "ci_high": ci[1],
                                  "p": fit.pvalues[term], "n_calls": len(df), "n_runs": df.run.nunique()})
        except Exception as exc:  # report rather than hide
            mixed.append({"model": m, "term": "FAILED", "coef": np.nan, "p": np.nan, "error": str(exc)})
        # robustness: OLS with run-clustered standard errors (no random-effect variance to estimate)
        ols = smf.ols("H ~ C(condition) * post + C(action) + log_tokens", df).fit(
            cov_type="cluster", cov_kwds={"groups": pd.factorize(df["run"])[0]})
        for term in ols.params.index:
            if ":post" in term:
                ci = ols.conf_int().loc[term]
                mixed.append({"model": m, "term": term + " [OLS cluster-robust]", "coef": ols.params[term],
                              "ci_low": ci[0], "ci_high": ci[1], "p": ols.pvalues[term], "n_calls": len(df),
                              "n_runs": df.run.nunique()})
    mixed = pd.DataFrame(mixed)
    mixed.to_csv(stats_dir / "E_mixed_model.csv", index=False)
    return runlevel, tests, mixed


# --------------------------------------------------------------------------- G system entropy

def system_entropy(calls, fig_dir, stats_dir, n_perm=1000):
    rows = []
    for m in MODELS:
        for c in CONDITIONS:
            df = calls[(calls.model == m) & (calls.condition == c)]
            for t in range(1, 31):
                at = df[df.turn == t]
                pairs_all, pairs_active = [], []
                for seed, g in at.groupby("seed"):
                    if set(g.agent) != {"A1", "A2"}:
                        continue
                    qs = []
                    for agent in ("A1", "A2"):
                        r = g[g.agent == agent].iloc[0]
                        if r.action == "done":
                            qs.append({E.DONE: 1.0})
                        elif not pd.isna(r[Q_COLS[0]]):
                            qs.append({a: float(r[f"q_{a}"]) for a in E.ACTIONS})
                        else:
                            qs.append(None)
                    if None in qs:
                        continue
                    pairs_all.append(tuple(qs))
                    if all(E.DONE not in q for q in qs):
                        pairs_active.append(tuple(qs))
                for variant, pairs in (("all_states", pairs_all), ("active_only", pairs_active)):
                    if len(pairs) < 5:
                        continue
                    q1, q2 = [p[0] for p in pairs], [p[1] for p in pairs]
                    obs = E.mixture_mi(q1, q2)
                    null = []
                    for _ in range(n_perm):
                        perm = RNG.permutation(len(q2))
                        null.append(E.mixture_mi(q1, [q2[k] for k in perm])["I_bits"])
                    null = np.asarray(null)
                    rows.append({"model": m, "condition": c, "turn": t, "variant": variant, "n_pairs": len(pairs),
                                 "H1": obs["H1_bits"], "H2": obs["H2_bits"], "sum_H": obs["sum_H_bits"], "I": obs["I_bits"],
                                 "H_system": obs["H_system_bits"], "I_null_mean": null.mean(),
                                 "I_null_95": np.percentile(null, 95), "I_excess": obs["I_bits"] - null.mean(),
                                 "p_perm": (np.sum(null >= obs["I_bits"] - 1e-12) + 1) / (n_perm + 1)})
    sysdf = pd.DataFrame(rows)
    sysdf.to_csv(stats_dir / "G_system_entropy.csv", index=False)

    for variant in ("all_states", "active_only"):
        fig, axes = plt.subplots(3, 3, figsize=(12, 8), sharex=True)
        for j, m in enumerate(MODELS):
            for c in CONDITIONS:
                d = sysdf[(sysdf.model == m) & (sysdf.condition == c) & (sysdf.variant == variant)]
                axes[0, j].plot(d.turn, d.sum_H, color=COLOURS[c], lw=1, ls=":", alpha=0.8)
                axes[0, j].plot(d.turn, d.H_system, color=COLOURS[c], lw=1.6, label=c)
                axes[1, j].plot(d.turn, d.I, color=COLOURS[c], lw=1.6, label=c)
                axes[1, j].plot(d.turn, d.I_null_95, color=COLOURS[c], lw=0.8, ls="--", alpha=0.7)
                sig = d[d.p_perm < 0.05]
                axes[1, j].scatter(sig.turn, sig.I, color=COLOURS[c], s=14, zorder=3)
                axes[2, j].plot(d.turn, d.I_excess, color=COLOURS[c], lw=1.6)
            for row in range(3):
                axes[row, j].axvline(SWITCH, color=INK, ls="--", lw=0.8)
            axes[0, j].set_title(m)
            axes[2, j].set_xlabel("turn")
            axes[2, j].axhline(0, color=MUTED, lw=0.6)
        axes[0, 0].set_ylabel("H(X1,X2) bits\n(dotted: H1+H2)")
        axes[1, 0].set_ylabel("I(X1;X2) bits\n(dashed: null 95th pct;\ndots: p<0.05)")
        axes[2, 0].set_ylabel("I − null mean")
        axes[0, 0].legend()
        fig.suptitle(f"G. System entropy over the action variable across runs ({variant.replace('_', ' ')})",
                     x=0.01, ha="left", fontweight="bold")
        savefig(fig, fig_dir / f"fig05_system_entropy_{variant}.png")

    window = sysdf[(sysdf.turn >= SWITCH) & (sysdf.turn <= WINDOW_END)]
    pre = sysdf[sysdf.turn < SWITCH]
    summary = (window.groupby(["model", "condition", "variant"])
               .agg(post_H_system=("H_system", "mean"), post_I=("I", "mean"), post_I_excess=("I_excess", "mean"),
                    post_turns_sig=("p_perm", lambda p: int((p < 0.05).sum())), post_turns=("p_perm", "size"))
               .reset_index())
    pre_sum = pre.groupby(["model", "condition", "variant"]).agg(pre_H_system=("H_system", "mean"), pre_I=("I", "mean")).reset_index()
    summary = summary.merge(pre_sum, on=["model", "condition", "variant"])
    summary.to_csv(stats_dir / "G_system_entropy_window_summary.csv", index=False)
    return sysdf, summary


# --------------------------------------------------------------------------- H aligned, I post-read spike

def aligned(active, runs, fig_dir, stats_dir):
    first_read = runs.set_index(["model", "condition", "seed"])["tau_first_foreign_read"]
    placebo_first = (active[(active.condition == "placebo") & (active.n_placebo_returned > 0)]
                     .groupby(["model", "seed"]).turn.min())
    rows = []
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.4), sharey=True)
    for ax, m in zip(axes, MODELS):
        for c, anchor in (("switch", lambda s: first_read.get((m, "switch", s))), ("placebo", lambda s: placebo_first.get((m, s)))):
            df = active[(active.model == m) & (active.condition == c)].copy()
            df["tau"] = df.seed.map(anchor)
            df = df.dropna(subset=["tau"])
            df["rel"] = df.turn - df.tau
            per = df.groupby(["seed", "rel"]).H_adj.mean().reset_index()
            pts = []
            for rel in range(-7, 11):
                v = per[per.rel == rel].H_adj.values
                if len(v) >= 5:
                    mean, lo, hi = boot_ci(v)
                    pts.append((rel, mean, lo, hi))
                    rows.append({"model": m, "condition": c, "rel_turn": rel, "mean": mean, "ci_low": lo, "ci_high": hi, "n": len(v)})
            if pts:
                r, mean, lo, hi = zip(*pts)
                ax.plot(r, mean, color=COLOURS[c], lw=1.6, label=f"{c} (anchor: first {'peer' if c == 'switch' else 'placebo'} read)")
                ax.fill_between(r, lo, hi, color=COLOURS[c], alpha=0.15, lw=0)
        ax.axvline(0, color=INK, ls="--", lw=0.8)
        ax.set_title(m)
        ax.set_xlabel("turn − first foreign read")
    axes[0].set_ylabel("adjusted bits/token")
    axes[0].legend(fontsize=7)
    fig.suptitle("H. Adjusted token entropy aligned on the first read that returned foreign entries", x=0.01, ha="left", fontweight="bold")
    savefig(fig, fig_dir / "fig06_aligned_first_foreign_read.png")
    pd.DataFrame(rows).to_csv(stats_dir / "H_aligned.csv", index=False)

    # I: call after a READ_LOG, by read content
    act = active.sort_values(["run", "agent", "turn"]).copy()
    act["prev_action"] = act.groupby(["run", "agent"]).action.shift()
    act["prev_foreign"] = act.groupby(["run", "agent"]).n_real_foreign_returned.shift()
    act["prev_placebo"] = act.groupby(["run", "agent"]).n_placebo_returned.shift()
    after = act[act.prev_action == "read_log"].copy()
    after["read_returned"] = np.select([after.prev_foreign > 0, after.prev_placebo > 0], ["peer entries", "placebo entries"], "own entries only")
    spike = (after[after.turn >= SWITCH].groupby(["model", "read_returned"])
             .agg(n=("H", "size"), H=("H", "mean"), H_adj=("H_adj", "mean"), H_decision=("H_decision", "mean")).reset_index())
    spike.to_csv(stats_dir / "I_post_read_spike.csv", index=False)
    fig, ax = plt.subplots(figsize=(7, 3.2))
    kinds = ["own entries only", "peer entries", "placebo entries"]
    kcol = {"own entries only": COLOURS["base"], "peer entries": COLOURS["switch"], "placebo entries": COLOURS["placebo"]}
    for i, m in enumerate(MODELS):
        for j, k in enumerate(kinds):
            v = after[(after.model == m) & (after.read_returned == k) & (after.turn >= SWITCH)].H_adj.values
            if len(v) >= 5:
                mean, lo, hi = boot_ci(v)
                ax.errorbar(i + (j - 1) * 0.25, mean, yerr=[[mean - lo], [hi - mean]], fmt="o", color=kcol[k],
                            capsize=2, label=k if i == 0 else None)
                ax.text(i + (j - 1) * 0.25, hi, f"n={len(v)}", ha="center", va="bottom", fontsize=6)
    ax.set_xticks(range(3), MODELS)
    ax.set_ylabel("adjusted bits/token")
    ax.legend(fontsize=7)
    ax.set_title("I. Entropy of the call right after a READ_LOG (turns ≥ 8), by what the read returned")
    savefig(fig, fig_dir / "fig07_post_read_spike.png")
    return spike


# --------------------------------------------------------------------------- J detection

def detection(active, runs, runlevel, fig_dir, stats_dir):
    out, roc_rows = [], []
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.6))
    for ax, m in zip(axes, MODELS):
        rl = runlevel[runlevel.model == m]
        for other, style in (("base", "-"), ("placebo", "--")):
            pos = rl[rl.condition == "switch"].H_adj_delta.dropna().values
            neg = rl[rl.condition == other].H_adj_delta.dropna().values
            thresholds = np.unique(np.concatenate([pos, neg, [np.inf, -np.inf]]))
            tpr = [np.mean(pos >= th) for th in thresholds]
            fpr = [np.mean(neg >= th) for th in thresholds]
            a = auc(pos, neg)
            ax.plot(fpr, tpr, ls=style, color=COLOURS["switch"], label=f"switch vs {other}: AUC {a:.2f}")
            roc_rows.append({"model": m, "contrast": f"switch vs {other}", "statistic": "H_adj_delta", "auc": a})
            posd = rl[rl.condition == "switch"].H_decision_delta.dropna().values
            negd = rl[rl.condition == other].H_decision_delta.dropna().values
            roc_rows.append({"model": m, "contrast": f"switch vs {other}", "statistic": "H_decision_delta", "auc": auc(posd, negd)})
        ax.plot([0, 1], [0, 1], color=MUTED, lw=0.6)
        ax.set_title(m)
        ax.set_xlabel("false positive rate")
        ax.legend(fontsize=7, loc="lower right")
    axes[0].set_ylabel("true positive rate")
    fig.suptitle("J1. Run-level ROC: does the adjusted entropy change separate switch runs?", x=0.01, ha="left", fontweight="bold")
    savefig(fig, fig_dir / "fig08_run_level_roc.png")

    # CUSUM on the per-run series of adjusted system token entropy (mean over active agents)
    tau = runs.set_index(["model", "condition", "seed"]).tau_first_foreign_read
    cusum_rows = []
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.4), sharey=True)
    for ax, m in zip(axes, MODELS):
        df = active[(active.model == m) & (active.turn <= WINDOW_END)]
        series = {k: g.groupby("turn").H_adj.mean().reindex(range(1, WINDOW_END + 1)) for k, g in df.groupby(["condition", "seed"])}
        base_pre = np.concatenate([s.loc[1:SWITCH - 1].dropna().values for (c, _), s in series.items() if c == "base"])
        mu, sd = base_pre.mean(), base_pre.std(ddof=1) or 1.0

        def stat(s, k=0.5):
            z = ((s - mu) / sd).fillna(0.0)
            up = lo = 0.0
            track = []
            for t, v in z.items():
                up, lo = max(0.0, up + v - k), max(0.0, lo - v - k)
                track.append((t, max(up, lo)))
            return track

        # threshold: 95th percentile of the max CUSUM over the post window in base runs
        base_max = [max(v for t, v in stat(s) if t >= SWITCH) for (c, _), s in series.items() if c == "base"]
        h = float(np.percentile(base_max, 95))
        for (c, seed), s in series.items():
            track = stat(s)
            alarm = next((t for t, v in track if t >= SWITCH and v > h), None)
            pelt = rpt.Pelt(model="l2", min_size=3).fit(s.fillna(s.mean()).values.reshape(-1, 1)).predict(pen=3 * sd ** 2)
            cusum_rows.append({"model": m, "condition": c, "seed": seed, "threshold_h": h, "alarm_turn": alarm,
                               "tau_read": tau.get((m, c, seed)), "delay": (alarm - tau.get((m, c, seed))) if alarm and not pd.isna(tau.get((m, c, seed))) else np.nan,
                               "pelt_breakpoints": "|".join(str(b + 1) for b in pelt[:-1])})
        cr = pd.DataFrame([r for r in cusum_rows if r["model"] == m])
        rates = cr.groupby("condition").alarm_turn.apply(lambda a: a.notna().mean())
        ax.bar(range(3), [rates.get(c, 0) for c in CONDITIONS], color=[COLOURS[c] for c in CONDITIONS])
        ax.set_xticks(range(3), CONDITIONS)
        delays = cr[cr.condition == "switch"].delay.dropna()
        ax.set_title(f"{m}\nalarm rate (h={h:.1f}); switch median delay {delays.median() if len(delays) else float('nan'):+.0f} turns")
        ax.axhline(0.05, color=MUTED, ls=":", lw=0.8)
    axes[0].set_ylabel("share of runs with an alarm in turns 8–20")
    fig.suptitle("J2. CUSUM on adjusted entropy, calibrated to 5% false alarms on base runs", x=0.01, ha="left", fontweight="bold")
    savefig(fig, fig_dir / "fig09_cusum_detection.png")
    cusum = pd.DataFrame(cusum_rows)
    cusum.to_csv(stats_dir / "J_cusum_runs.csv", index=False)
    pd.DataFrame(roc_rows).to_csv(stats_dir / "J_roc.csv", index=False)
    det = (cusum.groupby(["model", "condition"])
           .agg(alarm_rate=("alarm_turn", lambda a: a.notna().mean()), median_delay=("delay", "median"),
                threshold_h=("threshold_h", "first")).reset_index())
    det.to_csv(stats_dir / "J_cusum_summary.csv", index=False)
    return det, pd.DataFrame(roc_rows)


# --------------------------------------------------------------------------- main

def main(exp: Path, theme: str = "light") -> None:
    apply_theme(theme)
    out = exp / "analysis"
    fig_dir, stats_dir = out / THEMES[theme]["fig_dir"], out / "stats"
    fig_dir.mkdir(parents=True, exist_ok=True)
    stats_dir.mkdir(parents=True, exist_ok=True)
    calls, active, runs = load(exp)
    active = adjust(active)
    gt, timing = ground_truth(runs, fig_dir, stats_dir)
    traj = trajectories(active, fig_dir, stats_dir)
    traj_adj = trajectories(active, fig_dir, stats_dir, column="H_adj", name="fig02b_adjusted_entropy_trajectories.png",
                            title="B'. Token entropy adjusted for action type and length (bits/token)")
    traj_dec = trajectories(active, fig_dir, stats_dir, column="H_decision", name="fig02c_decision_entropy_trajectories.png",
                            title="F. Decision entropy H(q): uncertainty over the next action (bits)")
    pd.concat([traj, traj_adj, traj_dec]).to_csv(stats_dir / "B_trajectories.csv", index=False)
    by_action = action_mix(calls, active, fig_dir, stats_dir)
    runlevel, tests, mixed = did(active, fig_dir, stats_dir)
    sysdf, sys_summary = system_entropy(calls, fig_dir, stats_dir)
    spike = aligned(active, runs, fig_dir, stats_dir)
    det, roc = detection(active, runs, runlevel, fig_dir, stats_dir)
    summary = {
        "data": {"runs_valid": int(len(runs)), "agent_turn_calls": int(len(active)),
                 "models": MODELS, "conditions": CONDITIONS, "switch_turn": SWITCH, "window_end": WINDOW_END},
        "ground_truth": gt.to_dict("records"),
        "entropy_by_action": by_action.to_dict("records"),
        "did_tests": tests.to_dict("records"),
        "mixed_model": mixed.to_dict("records"),
        "system_entropy_window": sys_summary.to_dict("records"),
        "post_read_spike": spike.to_dict("records"),
        "cusum": det.to_dict("records"),
        "roc": roc.to_dict("records"),
    }
    (stats_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=float))
    print(json.dumps({"figures": sorted(p.name for p in fig_dir.iterdir()), "stats": sorted(p.name for p in stats_dir.iterdir())}, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve(), sys.argv[2] if len(sys.argv) > 2 else "light")
