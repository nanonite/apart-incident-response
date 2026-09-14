"""Step 4: interrupted time series, switch vs placebo (and base), per model and pooled.

H̄ = arm intercepts + Σ_arm [β1 t + β2 D + β3 (t - k) D]_arm + γ1 log n_tokens + γ2 log prompt_tokens
     + δ[action] + agent + position  (+ random seed intercept and run:agent variance component in MixedLM).
Arm-specific columns (no interaction coding) so an arm without an interruption simply has no D column.
Primary inference: OLS with cluster-robust SE by seed (t with G-1 df). MixedLM reported for the main spec per model.
Estimands: DiD level = β2_S - β2_P, DiD slope = β3_S - β3_P (also S-B and P-B).
Specs: main (D = t>=8); exposure (D = t >= τ+1, τ = first READ_LOG that returned foreign/donor entries to this
       agent; the READ_LOG result is only shown in the prompt of the next call);
       rp10 (turns with runs_present >= 10 in that arm); readdec (READ_LOG/DECRYPT calls only).
"""
import warnings

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from common import CONDS, K_STAR, MODELS, Tee, bh, load_calls, load_runs, save_table

ARM_ABBR = {"base": "b", "placebo": "p", "switch": "s"}
MOD_ABBR = {"gpt-4o-mini": "gpt", "llama-3.3-70b": "llama", "qwen3-235b": "qwen"}


def build(calls, runs, metric="mean_H_renorm_bits", spec="main", drop_long=False):
    bad = runs.loc[~runs.valid.astype(bool), ["model", "condition", "seed"]].assign(_bad=1)
    d = calls.merge(bad, how="left", on=["model", "condition", "seed"])
    d = d[d._bad.isna() & d.has_tokens].copy()
    d["y"] = d[metric]
    d["log_ntok"] = np.log(d.n_tokens)
    d["log_ptok"] = np.log(d.prompt_tokens)
    d["pos"] = d.position_in_turn
    d["run_agent"] = d.condition + "_" + d.seed.astype(str) + "_" + d.agent
    if spec == "exposure":
        ex = calls[(calls.n_real_foreign_returned.fillna(0) > 0) | (calls.n_placebo_returned.fillna(0) > 0)]
        tau = ex.groupby(["model", "condition", "seed", "agent"]).turn.min().rename("tau_exp").reset_index()
        d = d.merge(tau, how="left", on=["model", "condition", "seed", "agent"])
        # READ_LOG output is shown in the prompt of the agent's NEXT call, so the first exposed call is tau+1.
        onset = d.tau_exp + 1
        d["D"] = (d.turn >= onset).astype(float)
        d["tD"] = np.where(d.D > 0, d.turn - onset, 0.0)
    else:
        d["D"] = (d.turn >= K_STAR).astype(float)
        d["tD"] = (d.turn - K_STAR) * d.D
    if spec == "rp10":
        rp = pd.DataFrame([(m, c, t, int((g.turns_executed >= t).sum()))
                           for (m, c), g in runs.groupby(["model", "condition"]) for t in range(1, 31)],
                          columns=["model", "condition", "turn", "rp"])
        d = d.merge(rp, on=["model", "condition", "turn"])
        d = d[d.rp >= 10]
    if spec == "readdec":
        d = d[d.action.isin(["read_log", "decrypt"])]
    if drop_long:
        d = d[~d.action.isin(["write_log", "submit"])]
    return d.reset_index(drop=True)


def arm_columns(d, prefix=""):
    cols = []
    for c, a in ARM_ABBR.items():
        ind = (d.condition == c).astype(float)
        for base, v in (("I", ind), ("t", ind * d.turn), ("D", ind * d.D), ("tD", ind * d.tD)):
            name = f"{base}_{prefix}{a}"
            d[name] = v
            if base == "I" and c == "placebo":
                continue  # reference arm absorbed by the intercept
            if d[name].abs().sum() > 0:
                cols.append(name)
    return cols


def contrasts(res, cols, prefix=""):
    out = []
    have = set(cols)
    for par in ("D", "tD"):
        lab = "level" if par == "D" else "slope"
        for arm in ("s", "p", "b"):
            n = f"{par}_{prefix}{arm}"
            if n in have:
                out.append((f"{lab} {arm.upper()}", n))
        for x, y in (("s", "p"), ("s", "b"), ("p", "b")):
            a, b = f"{par}_{prefix}{x}", f"{par}_{prefix}{y}"
            if a in have and b in have:
                out.append((f"{lab} DiD {x.upper()}-{y.upper()}", f"{a} - {b}"))
    rows = []
    is_mixed = hasattr(res, "fe_params")
    b = res.fe_params if is_mixed else res.params
    names = list(b.index)
    V = res.cov_params().loc[names, names].to_numpy()
    for lab, expr in out:
        # contrast computed by hand from fixed effects (t_test fails on MixedLM results)
        L = np.zeros(len(names))
        for sign, nm in zip([1, -1], [s.strip() for s in expr.split(" - ")]):
            L[names.index(nm)] = sign
        est = float(L @ b.to_numpy())
        se = float(np.sqrt(L @ V @ L))
        if is_mixed:  # Wald z
            from scipy import stats
            crit, p = stats.norm.ppf(.975), 2 * stats.norm.sf(abs(est / se))
        else:  # cluster-robust t with G-1 df
            from scipy import stats
            dfree = res.df_resid_inference if getattr(res, "df_resid_inference", None) else res.df_resid
            crit, p = stats.t.ppf(.975, dfree), 2 * stats.t.sf(abs(est / se), dfree)
        rows.append(dict(term=lab, est=est, se=se, ci_low=est - crit * se, ci_high=est + crit * se, p=p))
    return rows


def fit_model(d, model_name, spec, metric, mixed=False):
    d = d.copy()
    cols = arm_columns(d)
    covs = "log_ntok + log_ptok + C(action) + C(agent) + C(pos)"
    f = "y ~ 1 + " + " + ".join(cols) + " + " + covs
    rows = []
    res = smf.ols(f, data=d).fit(cov_type="cluster", cov_kwds={"groups": d.seed}, use_t=True)
    for r in contrasts(res, cols):
        rows.append(dict(model=model_name, spec=spec, metric=metric, estimator="OLS-CR(seed)", n_obs=int(res.nobs), **r))
    if mixed:
        with warnings.catch_warnings(record=True) as wlist:
            warnings.simplefilter("always")
            try:
                mres = smf.mixedlm(f, data=d, groups=d.seed, re_formula="1",
                                   vc_formula={"run_agent": "0 + C(run_agent)"}).fit(reml=True, method="lbfgs")
                conv = bool(mres.converged)
                for r in contrasts(mres, cols):
                    rows.append(dict(model=model_name, spec=spec, metric=metric, estimator="MixedLM",
                                     n_obs=int(mres.nobs), converged=conv, **r))
            except Exception as exc:  # reported, not hidden
                rows.append(dict(model=model_name, spec=spec, metric=metric, estimator="MixedLM",
                                 term="FAILED", note=str(exc)[:200]))
        msgs = sorted({str(w.message)[:80] for w in wlist})
        if msgs:
            print(f"  MixedLM warnings {model_name}/{spec}: {msgs}")
    return rows


def fit_pooled(d, spec, metric):
    d = d.copy()
    cols = []
    for m, ab in MOD_ABBR.items():
        sub = d.model == m
        tmp = d.loc[sub].copy()
        c_m = arm_columns(tmp, prefix=f"{ab}_")
        for c in c_m:
            d[c] = 0.0
            d.loc[sub, c] = tmp[c]
        cols += c_m
        d[f"M_{ab}"] = sub.astype(float)
        d[f"Ip_{ab}"] = ((d.condition == "placebo") & sub).astype(float)
    mcols = [f"M_{ab}" for ab in list(MOD_ABBR.values())[1:]]
    covs = "C(model):(log_ntok + log_ptok) + C(model):C(action) + C(model):C(agent) + C(pos)"
    f = "y ~ 1 + " + " + ".join(mcols + cols) + " + " + covs
    res = smf.ols(f, data=d).fit(cov_type="cluster", cov_kwds={"groups": d.seed}, use_t=True)
    rows = []
    have = set(res.model.exog_names)
    for par, lab in (("D", "level"), ("tD", "slope")):
        for x, y in (("s", "p"), ("s", "b"), ("p", "b")):
            terms = [(f"{par}_{ab}_{x}", f"{par}_{ab}_{y}") for ab in MOD_ABBR.values()
                     if f"{par}_{ab}_{x}" in have and f"{par}_{ab}_{y}" in have]
            if not terms:
                continue
            w = 1 / len(terms)
            expr = " + ".join(f"{w}*{a} - {w}*{b}" for a, b in terms)
            tt = res.t_test(f"{expr} = 0")
            ci = np.asarray(tt.conf_int()).ravel()
            rows.append(dict(model="pooled (mean of models)", spec=spec, metric=metric, estimator="OLS-CR(seed)",
                             n_obs=int(res.nobs), term=f"{lab} DiD {x.upper()}-{y.upper()}",
                             est=float(np.ravel(tt.effect)[0]), se=float(np.ravel(tt.sd)[0]),
                             ci_low=ci[0], ci_high=ci[1], p=float(np.ravel(tt.pvalue)[0])))
    return rows


def its_table(calls, runs, metric="mean_H_renorm_bits", specs=("main", "exposure", "rp10", "readdec"),
              mixed=True, drop_long=False, tag=None):
    rows = []
    for spec in specs:
        d = build(calls, runs, metric=metric, spec=spec, drop_long=drop_long)
        for m in MODELS:
            rows += fit_model(d[d.model == m], m, tag or spec, metric, mixed=mixed and spec == "main")
        rows += fit_pooled(d, tag or spec, metric)
    t = pd.DataFrame(rows)
    return t


if __name__ == "__main__":
    Tee("s04_its")
    calls, runs = load_calls(), load_runs()
    t = its_table(calls, runs)
    did = t.term.str.contains("DiD S-P", na=False) & (t.estimator == "OLS-CR(seed)")
    t["p_bh_DiD_SP_OLS"] = np.nan
    t.loc[did, "p_bh_DiD_SP_OLS"] = bh(t.loc[did, "p"])
    save_table(t, "table3_its_did")
    pd.set_option("display.width", 250)
    print(t[t.term.str.contains("DiD", na=False)].to_string(index=False))
    print()
    print(t[~t.term.str.contains("DiD", na=True)].to_string(index=False))
