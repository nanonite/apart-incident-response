"""Step 3: paired endpoint contrasts per (model, seed).

Post window: turns 8 .. 8+w-1 (w in {5, 10}, fixed a priori), truncated at the end of the run.
Pre window: turns 1..7. H̄ of a run = mean over agent-calls with tokens in the window (both agents pooled).
Adjustment for action type and response length: per model, OLS
    H ~ C(action) + log(n_tokens) + C(arm):C(period)
(the arm x period cells absorb any treatment effect, so covariate coefficients are estimated within cells);
the covariate part (centred) is subtracted from H. 'raw' uses H unchanged.
Contrasts: comm = S - (B+P)/2, S-P, P-B; 'level' (post) and 'prepost' (post - pre).
Inference over seeds: bootstrap 10 000 (percentile), exact sign test, Wilcoxon signed-rank; BH within family.
"""
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

from common import (COLOR, CONDS, INK, K_STAR, MODELS, Tee, bh, boot_ci, fig_path, load_calls, load_runs,
                    mark_kstar, mpl_setup, save_table)

WINDOWS = (5, 10)
CONTRASTS = {"comm": {"switch": 1, "base": -.5, "placebo": -.5},
             "S-P": {"switch": 1, "placebo": -1},
             "P-B": {"placebo": 1, "base": -1}}


def prepare(calls: pd.DataFrame, runs: pd.DataFrame, metric: str = "mean_H_renorm_bits",
            exclude_invalid: bool = True, extra_cov: bool = False) -> pd.DataFrame:
    d = calls[calls.has_tokens].copy()
    if exclude_invalid:
        bad = runs.loc[~runs.valid.astype(bool), ["model", "condition", "seed"]]
        d = d.merge(bad.assign(_bad=1), how="left", on=["model", "condition", "seed"])
        d = d[d._bad.isna()].drop(columns="_bad")
    d["y_raw"] = d[metric]
    d["log_ntok"] = np.log(d.n_tokens)
    d["log_ptok"] = np.log(d.prompt_tokens)
    d["period"] = np.where(d.turn >= K_STAR, "post", "pre")
    d["y_adj"] = np.nan
    cov = "C(action) + log_ntok" + (" + log_ptok" if extra_cov else "")
    for m, g in d.groupby("model"):
        fit = smf.ols(f"y_raw ~ {cov} + C(condition):C(period)", data=g).fit()
        X = fit.model.exog
        names = fit.model.exog_names
        keep = [i for i, n in enumerate(names) if n.startswith("C(action)") or n.startswith("log_")]
        part = X[:, keep] @ fit.params.to_numpy()[keep]
        d.loc[g.index, "y_adj"] = g.y_raw - (part - part.mean())
    return d


def run_endpoints(d: pd.DataFrame, runs: pd.DataFrame, w: int, ycol: str) -> pd.DataFrame:
    end = runs.set_index(["model", "condition", "seed"]).turns_executed
    post = d[(d.turn >= K_STAR) & (d.turn < K_STAR + w)]
    pre = d[d.turn < K_STAR]
    e_post = post.groupby(["model", "condition", "seed"])[ycol].mean().rename("post")
    e_pre = pre.groupby(["model", "condition", "seed"])[ycol].mean().rename("pre")
    e = pd.concat([e_pre, e_post], axis=1).reset_index()
    e["prepost"] = e.post - e.pre
    e["level"] = e.post
    e["end_turn"] = [end.get((m, c, s), np.nan) for m, c, s in zip(e.model, e.condition, e.seed)]
    return e


def contrast_rows(e: pd.DataFrame, label: dict, offset: int = 0) -> list[dict]:
    rows = []
    for m, g in e.groupby("model"):
        for kind in ("level", "prepost"):
            wide = g.pivot(index="seed", columns="condition", values=kind)
            for cname, wts in CONTRASTS.items():
                cols = list(wts)
                sub = wide.reindex(columns=cols).dropna()
                x = sum(sub[c] * v for c, v in wts.items()).to_numpy()
                n = len(x)
                if n == 0:
                    continue
                est, lo, hi = boot_ci(x, offset=offset)
                npos = int((x > 0).sum())
                nz = int((x != 0).sum())
                p_sign = stats.binomtest(npos, nz, 0.5).pvalue if nz else np.nan
                p_wil = stats.wilcoxon(x).pvalue if nz > 0 else np.nan
                rows.append(dict(**label, model=m, kind=kind, contrast=cname, n_seeds=n,
                                 missing_seeds=",".join(map(str, sorted(set(range(1, 21)) - set(sub.index)))),
                                 mean=est, ci_low=lo, ci_high=hi, median=float(np.median(x)),
                                 sd=float(np.std(x, ddof=1)) if n > 1 else np.nan,
                                 n_pos=npos, p_sign=p_sign, p_wilcoxon=p_wil))
    return rows


def endpoint_table(calls, runs, metric="mean_H_renorm_bits", tag="main", read_only=False,
                   drop_long=False, extra_cov=False) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = prepare(calls, runs, metric=metric, extra_cov=extra_cov)
    if read_only:
        d = d[d.action == "read_log"]
    if drop_long:
        d = d[~d.action.isin(["write_log", "submit"])]
    rows, per_seed = [], []
    for w in WINDOWS:
        for adj in ("raw", "adj"):
            ycol = "y_adj" if adj == "adj" and not read_only else "y_raw"
            if read_only and adj == "adj":
                continue
            e = run_endpoints(d, runs, w, ycol)
            label = dict(spec=tag, metric=metric, window=w, adjust=adj if not read_only else "read_only")
            rows += contrast_rows(e, label, offset=w)
            per_seed.append(e.assign(**label))
    t = pd.DataFrame(rows)
    t["p_wilcoxon_bh"] = bh(t.p_wilcoxon)
    return t, pd.concat(per_seed)


if __name__ == "__main__":
    Tee("s03_endpoints")
    calls, runs = load_calls(), load_runs()
    t_main, seeds_main = endpoint_table(calls, runs)
    t_read, seeds_read = endpoint_table(calls, runs, tag="read_only", read_only=True)
    t_ptok, _ = endpoint_table(calls, runs, tag="adj+log_prompt_tokens", extra_cov=True)
    t_ptok = t_ptok[t_ptok.adjust == "adj"]
    table2 = pd.concat([t_main, t_read, t_ptok], ignore_index=True)
    table2["p_wilcoxon_bh_family"] = bh(table2.p_wilcoxon)
    save_table(table2, "table2_endpoints")
    save_table(pd.concat([seeds_main, seeds_read]), "t3_endpoint_values_by_run", md=False)
    show = table2[(table2.contrast == "comm")]
    cols = ["spec", "model", "window", "adjust", "kind", "n_seeds", "mean", "ci_low", "ci_high", "n_pos",
            "p_sign", "p_wilcoxon", "p_wilcoxon_bh_family"]
    print(show[cols].to_string(index=False))
    print()
    print(table2[table2.contrast != "comm"][cols + ["contrast"]].to_string(index=False))

    # ---- H̄ per turn per condition (run-level turn means, bootstrap CI over runs)
    plt = mpl_setup()
    d = prepare(calls, runs)
    for m in MODELS:
        fig, axes = plt.subplots(1, 2, figsize=(10, 3.4), sharex=True)
        for ax, ycol, ttl in ((axes[0], "y_raw", "raw mean H_renorm"), (axes[1], "y_adj", "adjusted for action & length")):
            for c in CONDS:
                g = d[(d.model == m) & (d.condition == c)]
                rt = g.groupby(["turn", "seed"])[ycol].mean().reset_index()
                pts = []
                for t, gg in rt.groupby("turn"):
                    if len(gg) < 5:
                        continue
                    mu, lo, hi = boot_ci(gg[ycol].to_numpy(), n_boot=2000, offset=int(t))
                    pts.append((t, mu, lo, hi))
                if not pts:
                    continue
                p = np.array(pts)
                ax.fill_between(p[:, 0], p[:, 2], p[:, 3], color=COLOR[c], alpha=.15, lw=0)
                ax.plot(p[:, 0], p[:, 1], color=COLOR[c], label=c)
                ax.text(p[-1, 0] + .3, p[-1, 1], c, color=INK["secondary"], fontsize=8, va="center")
            mark_kstar(ax)
            ax.set(title=ttl, xlabel="turn", xlim=(1, 32))
        axes[0].set_ylabel("H̄ per call (bits/token)")
        axes[0].legend(loc="upper left")
        fig.suptitle(f"{m}: per-call mean token entropy by turn (turns with ≥5 runs; 95% bootstrap CI over runs)",
                     color=INK["primary"])
        fig.tight_layout()
        fig.savefig(fig_path(m, "f3_Hbar_by_turn"))
        plt.close(fig)
    print("figures written")
