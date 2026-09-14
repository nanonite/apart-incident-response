"""Step 7: functional form of H̄(t) (damped oscillation of Zhu et al.) against null models.

Zhu:   H(t) = A exp(-λ t) sin(ω t + φ) + β ln(1+t) + H0          (6 parameters)
Nulls: constant (1), linear (2), logarithmic a + b ln(1+t) (2), cubic B-spline df=4 with intercept (5).
Data: call-level H̄ (mean_H_renorm_bits) with tokens, valid runs; targets 'raw' and 'adj' (action/length adjusted, s03).
Segments: full series (t = 1..30) per model x condition, and post-switch segment t >= 8 for every arm.
Criteria: Gaussian AIC/BIC from RSS; leave-one-seed-out (LOSO) mean squared prediction error;
Zhu retained only if (i) LOSO MSE below every null, (ii) n/k > 50, (iii) raw predictions on t in [1,30] within [0, log2 20].
Form change: seed-bootstrap (200) of Zhu parameters on the post segment; |switch - placebo| compared with the
bootstrap spread sqrt(sd_S^2 + sd_P^2) (ratio > 2 flagged). Sinusoidal parameters are weakly identified; see log.
"""
import warnings

import numpy as np
import pandas as pd
from patsy import dmatrix
from scipy.optimize import curve_fit

from common import COLOR, CONDS, INK, K_STAR, MODELS, Tee, fig_path, load_calls, load_runs, mark_kstar, mpl_setup, rng, save_table
from s03_endpoints import prepare

warnings.filterwarnings("ignore", category=RuntimeWarning)
LOG2_20 = np.log2(20)
N_STARTS = 12
N_BOOT = 200
P_NAMES = ["A", "lam", "omega", "phi", "beta", "H0"]
LB = [-5, 0, 0.05, -np.pi, -3, -3]
UB = [5, 3, np.pi, np.pi, 3, 5]


def zhu(t, A, lam, omega, phi, beta, H0):
    return A * np.exp(-lam * t) * np.sin(omega * t + phi) + beta * np.log1p(t) + H0


def fit_zhu(t, y, g, p0_extra=None):
    best = (np.inf, None)
    starts = [] if p0_extra is None else [p0_extra]
    for _ in range(N_STARTS):
        starts.append([g.uniform(-1, 1), g.uniform(0, 1), g.uniform(0.2, 2.5), g.uniform(-np.pi, np.pi),
                       g.uniform(-.2, .2), float(np.mean(y))])
    for p0 in starts:
        p0 = np.clip(p0, np.array(LB) + 1e-6, np.array(UB) - 1e-6)
        try:
            p, _ = curve_fit(zhu, t, y, p0=p0, bounds=(LB, UB), maxfev=4000)
        except Exception:
            continue
        rss = float(np.sum((y - zhu(t, *p)) ** 2))
        if rss < best[0]:
            best = (rss, p)
    return best[1]


def spline_basis(t, knots_from):
    return np.asarray(dmatrix("bs(t, df=4, degree=3, include_intercept=True, lower_bound=lo, upper_bound=hi) - 1",
                              {"t": t, "lo": knots_from[0], "hi": knots_from[1]}))


def fit_predict(name, t_tr, y_tr, t_te, g, p0=None):
    if name == "constant":
        return np.full(len(t_te), y_tr.mean()), 1, None
    if name in ("linear", "log"):
        f = (lambda x: x) if name == "linear" else np.log1p
        X = np.c_[np.ones(len(t_tr)), f(t_tr)]
        b = np.linalg.lstsq(X, y_tr, rcond=None)[0]
        return b[0] + b[1] * f(t_te), 2, b
    if name == "spline":
        lo, hi = min(t_tr.min(), t_te.min()), max(t_tr.max(), t_te.max())
        Xtr = spline_basis(t_tr, (lo, hi))
        Xte = spline_basis(t_te, (lo, hi))
        b = np.linalg.lstsq(Xtr, y_tr, rcond=None)[0]
        return Xte @ b, Xtr.shape[1], b
    if name == "zhu":
        p = fit_zhu(t_tr, y_tr, g, p0)
        if p is None:
            return np.full(len(t_te), np.nan), 6, None
        return zhu(t_te, *p), 6, p
    raise ValueError(name)


MODELS_FF = ["constant", "linear", "log", "spline", "zhu"]

if __name__ == "__main__":
    Tee("s07_functional_form")
    calls, runs = load_calls(), load_runs()
    d = prepare(calls, runs)
    g = rng(7)
    rows, params, curves = [], [], []
    for m in MODELS:
        for c in CONDS:
            for seg in ("full", "post"):
                for target in ("y_raw", "y_adj"):
                    sub = d[(d.model == m) & (d.condition == c)]
                    if seg == "post":
                        sub = sub[sub.turn >= K_STAR]
                    t = sub.turn.to_numpy(float)
                    y = sub[target].to_numpy(float)
                    s = sub.seed.to_numpy()
                    n = len(y)
                    full_fit = {}
                    for name in MODELS_FF:
                        pred, k, par = fit_predict(name, t, y, t, g)
                        rss = float(np.sum((y - pred) ** 2))
                        full_fit[name] = par
                        grid = np.arange(t.min(), 31, dtype=float)
                        gpred = fit_predict(name, t, y, grid, g, p0=par if name == "zhu" else None)[0] if name == "spline" else (
                            zhu(grid, *par) if name == "zhu" and par is not None else
                            (np.full(len(grid), y.mean()) if name == "constant" else
                             (par[0] + par[1] * (grid if name == "linear" else np.log1p(grid)) if par is not None else np.nan)))
                        in_range = bool(np.all((gpred >= 0) & (gpred <= LOG2_20))) if target == "y_raw" else np.nan
                        # LOSO
                        se_sum, cnt = 0.0, 0
                        for held in np.unique(s):
                            tr, te = s != held, s == held
                            p_te = fit_predict(name, t[tr], y[tr], t[te], g, p0=par if name == "zhu" else None)[0]
                            se_sum += float(np.nansum((y[te] - p_te) ** 2))
                            cnt += int(np.sum(~np.isnan(p_te)))
                        rows.append(dict(model=m, condition=c, segment=seg, target=target, candidate=name, k=k, n=n,
                                         rss=rss, aic=n * np.log(rss / n) + 2 * k, bic=n * np.log(rss / n) + k * np.log(n),
                                         loso_mse=se_sum / cnt, range_ok=in_range))
                        if target == "y_raw" and seg == "full":
                            curves.append(dict(model=m, condition=c, candidate=name, t=grid, pred=gpred))
                    if full_fit["zhu"] is not None:
                        params.append(dict(model=m, condition=c, segment=seg, target=target,
                                           **dict(zip(P_NAMES, full_fit["zhu"]))))
    t4 = pd.DataFrame(rows)
    best_null = (t4[t4.candidate != "zhu"].groupby(["model", "condition", "segment", "target"])
                 .agg(best_null_loso=("loso_mse", "min"), best_null_bic=("bic", "min")).reset_index())
    z = t4[t4.candidate == "zhu"].merge(best_null, on=["model", "condition", "segment", "target"])
    z["zhu_beats_nulls_oos"] = z.loso_mse < z.best_null_loso
    z["zhu_beats_nulls_bic"] = z.bic < z.best_null_bic
    z["n_over_k_gt_50"] = z.n / z.k > 50
    z["retain_zhu"] = z.zhu_beats_nulls_oos & z.n_over_k_gt_50 & (z.range_ok.fillna(True).astype(bool))
    winner = t4.loc[t4.groupby(["model", "condition", "segment", "target"]).loso_mse.idxmin(),
                    ["model", "condition", "segment", "target", "candidate"]].rename(columns={"candidate": "loso_winner"})
    z = z.merge(winner, on=["model", "condition", "segment", "target"])
    save_table(t4, "table4_functional_form_all")
    save_table(z[["model", "condition", "segment", "target", "n", "loso_mse", "best_null_loso", "bic", "best_null_bic",
                  "range_ok", "zhu_beats_nulls_oos", "zhu_beats_nulls_bic", "n_over_k_gt_50", "retain_zhu", "loso_winner"]],
               "table4_functional_form_summary")
    pd.set_option("display.width", 250)
    print(z[["model", "condition", "segment", "target", "n", "loso_mse", "best_null_loso", "bic", "best_null_bic",
             "range_ok", "retain_zhu", "loso_winner"]].to_string(index=False))
    pr = pd.DataFrame(params)
    save_table(pr, "t7_zhu_params_point")

    # ---- parameter bootstrap over seeds, post segment, raw & adj: switch vs placebo (and vs base)
    brows = []
    for m in MODELS:
        for target in ("y_raw", "y_adj"):
            boot = {}
            for c in CONDS:
                sub = d[(d.model == m) & (d.condition == c) & (d.turn >= K_STAR)]
                p0 = pr[(pr.model == m) & (pr.condition == c) & (pr.segment == "post") & (pr.target == target)][P_NAMES]
                p0 = p0.iloc[0].to_numpy() if len(p0) else None
                seeds = sub.seed.unique()
                by_seed = {s_: sub[sub.seed == s_] for s_ in seeds}
                reps = []
                for b in range(N_BOOT):
                    pick = g.choice(seeds, len(seeds), replace=True)
                    bb = pd.concat([by_seed[x] for x in pick])
                    p = fit_zhu(bb.turn.to_numpy(float), bb[target].to_numpy(float), g, p0)
                    if p is not None:
                        reps.append(p)
                boot[c] = np.array(reps)
            for a_, b_ in (("switch", "placebo"), ("switch", "base"), ("placebo", "base")):
                pa = pr[(pr.model == m) & (pr.condition == a_) & (pr.segment == "post") & (pr.target == target)][P_NAMES].iloc[0]
                pb = pr[(pr.model == m) & (pr.condition == b_) & (pr.segment == "post") & (pr.target == target)][P_NAMES].iloc[0]
                for i, pn in enumerate(P_NAMES):
                    sa, sb = boot[a_][:, i].std(ddof=1), boot[b_][:, i].std(ddof=1)
                    spread = np.sqrt(sa ** 2 + sb ** 2)
                    diff = pa[pn] - pb[pn]
                    brows.append(dict(model=m, target=target, contrast=f"{a_}-{b_}", param=pn, diff=diff,
                                      boot_sd_a=sa, boot_sd_b=sb, ratio=abs(diff) / spread if spread > 0 else np.nan,
                                      flagged=bool(abs(diff) > 2 * spread)))
    t4b = pd.DataFrame(brows)
    save_table(t4b, "table4b_zhu_param_differences")
    print(t4b[t4b.contrast == "switch-placebo"].to_string(index=False))

    # ---- figure: turn means + Zhu and best null fits (raw, full series)
    plt = mpl_setup()
    for m in MODELS:
        fig, axes = plt.subplots(1, 3, figsize=(12, 3.4), sharey=True)
        for ax, c in zip(axes, CONDS):
            sub = d[(d.model == m) & (d.condition == c)]
            tm = sub.groupby("turn").y_raw.agg(["mean", "size"]).reset_index()
            ax.scatter(tm.turn, tm["mean"], s=np.clip(tm["size"], 8, 60), color=COLOR[c], alpha=.55, lw=0, label="turn mean (size ∝ calls)")
            zrow = z[(z.model == m) & (z.condition == c) & (z.segment == "full") & (z.target == "y_raw")].iloc[0]
            for cv in curves:
                if cv["model"] == m and cv["condition"] == c and cv["candidate"] in ("zhu", zrow.loso_winner if zrow.loso_winner != "zhu" else "spline"):
                    isz = cv["candidate"] == "zhu"
                    ax.plot(cv["t"], cv["pred"], color=COLOR[c] if isz else INK["secondary"], ls="-" if isz else "--",
                            lw=2 if isz else 1.5, label="Zhu damped oscillation" if isz else f"best null ({cv['candidate']})")
            mark_kstar(ax)
            ax.set(title=f"{c}: LOSO winner = {zrow.loso_winner}", xlabel="turn", xlim=(1, 30.5))
            ax.legend(loc="upper right", fontsize=7)
        axes[0].set_ylabel("H̄ per call (bits/token)")
        fig.suptitle(f"{m}: functional form of H̄(t), full series (points = turn means of calls)", color=INK["primary"])
        fig.tight_layout()
        fig.savefig(fig_path(m, "f7_functional_form"))
        plt.close(fig)
    print("figures written")
