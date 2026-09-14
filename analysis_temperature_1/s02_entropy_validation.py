"""Step 2: validate entropy measures.

(a) recompute per-token H_lower / H_renorm / coverage from topk.csv.gz and compare with tokens.csv.gz;
(b) reproduce system_entropy.csv from calls.csv with sysent.py;
(c) H_lower vs H_renorm agreement and coverage distribution per model.
"""
import numpy as np
import pandas as pd
from scipy import stats

from common import (COLOR, CONDS, INK, MODELS, TABLES, Tee, fig_path, load_calls, load_system,
                    load_tokens, mpl_setup, save_table)
from sysent import system_table

Tee("s02_entropy_validation")
KEY = ["model", "condition", "seed", "turn", "agent", "pos"]

# ---------------------------------------------------------------- (a) token level
print("== (a) recompute token entropies from top-20 logprobs")
aggs = []
dt = {"model": "category", "condition": "category", "agent": "category", "seed": "int16",
      "turn": "int8", "pos": "int16", "rank": "int8", "alt_logprob_ln": "float64"}
for chunk in pd.read_csv(TABLES / "topk.csv.gz", usecols=list(dt), dtype=dt, chunksize=3_000_000):
    p = np.exp(chunk["alt_logprob_ln"].to_numpy())
    with np.errstate(divide="ignore", invalid="ignore"):
        plogp = np.where(p > 0, p * np.log2(p), 0.0)
    chunk = chunk.assign(S1=p, S2=plogp, k=1)
    aggs.append(chunk.groupby(KEY, observed=True)[["S1", "S2", "k"]].sum().reset_index())
agg = pd.concat(aggs).groupby(KEY, observed=True)[["S1", "S2", "k"]].sum().reset_index()
c = agg.S1.clip(upper=1.0)
rest = (1.0 - c).clip(lower=0.0)
with np.errstate(divide="ignore", invalid="ignore"):
    # Verified definition: truncated sum over the top-k only (no term for the residual mass).
    # The "block" variant (-S2 - rest*log2(rest)) is also reported to document that it does NOT match.
    agg["H_lower_re"] = -agg.S2
    agg["H_block_re"] = -agg.S2 - np.where(rest > 0, rest * np.log2(rest), 0.0)
    agg["H_renorm_re"] = -agg.S2 / agg.S1 + np.log2(agg.S1)
agg["coverage_re"] = agg.S1

tok = load_tokens()
for col in ("model", "condition", "agent"):
    tok[col] = tok[col].astype(str)
    agg[col] = agg[col].astype(str)
mrg = tok.merge(agg, on=KEY, how="left", indicator=True)
res_a = []
for m, g in mrg.groupby("model"):
    real = g[~g.placeholder.astype(bool)]
    row = dict(model=m, tokens=len(g), placeholders=int(g.placeholder.astype(bool).sum()),
               tokens_without_topk=int((real["_merge"] == "left_only").sum()),
               k_not_20=int((real.k.fillna(0) != 20).sum()))
    for a, b in (("H_lower_bits", "H_lower_re"), ("H_renorm_bits", "H_renorm_re"), ("coverage", "coverage_re")):
        row[f"maxabs_{a}"] = float(np.nanmax(np.abs(real[a] - real[b])))
    res_a.append(row)
res_a = pd.DataFrame(res_a)
print(res_a.to_string(index=False))
mrg["err_renorm"] = (mrg.H_renorm_bits - mrg.H_renorm_re).abs()
mrg["err_block"] = (mrg.H_lower_bits - mrg.H_block_re).abs()
print("  worst H_renorm rows:")
print(mrg.nlargest(8, "err_renorm")[KEY + ["H_renorm_bits", "H_renorm_re", "coverage", "coverage_re", "k"]].to_string(index=False))
bad = mrg[mrg.err_renorm > 1e-6]
print(f"  rows with renorm error > 1e-6: {len(bad)} (by model: {bad.model.value_counts().to_dict()}; k counts: {bad.k.value_counts().to_dict()})")
print(f"  max abs error of the 'block' H_lower variant: {mrg.err_block.max():.4f} (does not match)")
save_table(bad[KEY + ["H_lower_bits", "H_lower_re", "H_renorm_bits", "H_renorm_re", "coverage", "coverage_re", "k"]],
           "t2a_token_recompute_mismatches", md=False)
save_table(res_a, "t2a_token_entropy_recompute")
tol_ok = (res_a[[c for c in res_a if c.startswith("maxabs")]] < 1e-6).all().all()
print(f"  all max abs errors < 1e-6: {tol_ok}")

# ---------------------------------------------------------------- (c) agreement and coverage
print("\n== (c) H_lower vs H_renorm, coverage")
real = tok[~tok.placeholder.astype(bool)]
rows = []
for m, g in real.groupby("model"):
    rows.append(dict(model=m, tokens=len(g),
                     pearson_token=stats.pearsonr(g.H_lower_bits, g.H_renorm_bits)[0],
                     spearman_token=stats.spearmanr(g.H_lower_bits, g.H_renorm_bits)[0],
                     mean_H_lower=g.H_lower_bits.mean(), mean_H_renorm=g.H_renorm_bits.mean(),
                     mean_abs_diff=(g.H_lower_bits - g.H_renorm_bits).abs().mean(),
                     coverage_mean=g.coverage.mean(), coverage_p01=g.coverage.quantile(.01),
                     coverage_p05=g.coverage.quantile(.05), coverage_median=g.coverage.median(),
                     frac_cov_lt_0_99=(g.coverage < .99).mean(), frac_cov_lt_0_9=(g.coverage < .9).mean(),
                     frac_sampled_outside_topk=(~g.get("chosen_in_topk", pd.Series(True, index=g.index)).astype(bool)).mean()
                     if "chosen_in_topk" in g else np.nan))
calls = load_calls()
for r in rows:
    g = calls[(calls.model == r["model"]) & calls.has_tokens]
    r["pearson_call_mean"] = stats.pearsonr(g.mean_H_lower_bits, g.mean_H_renorm_bits)[0]
    r["spearman_call_mean"] = stats.spearmanr(g.mean_H_lower_bits, g.mean_H_renorm_bits)[0]
cov_tab = pd.DataFrame(rows)
print(cov_tab.T.to_string())
save_table(cov_tab, "t2c_lower_vs_renorm_coverage")

by_cond = (real.groupby(["model", "condition"]).agg(coverage_mean=("coverage", "mean"),
                                                     frac_cov_lt_0_99=("coverage", lambda s: (s < .99).mean()))
           .reset_index())
save_table(by_cond, "t2c_coverage_by_condition")
print(by_cond.to_string(index=False))

plt = mpl_setup()
for m in MODELS:
    fig, ax = plt.subplots(figsize=(5.5, 3.2))
    for cnd in CONDS:
        v = np.sort(real[(real.model == m) & (real.condition == cnd)].coverage.to_numpy())
        y = np.arange(1, len(v) + 1) / len(v)
        ax.plot(v, y, color=COLOR[cnd], label=cnd)
    ax.set_xscale("function", functions=(lambda x: -np.log10(np.clip(1 - x, 1e-9, 1)),
                                         lambda y: 1 - 10 ** (-y)))
    ax.set_xticks([0.5, 0.9, 0.99, 0.999, 0.9999, 0.99999])
    ax.set_xticklabels(["0.5", "0.9", "0.99", "0.999", "0.9999", "0.99999"])
    ax.set_xlim(0.5, 0.999999)
    ax.set(xlabel="top-20 coverage Σp (log-odds-like scale)", ylabel="fraction of tokens ≤ x",
           title=f"{m}: top-20 probability mass per generated token")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(fig_path(m, "f2_coverage_ecdf"))
    plt.close(fig)

# ---------------------------------------------------------------- (b) system_entropy.csv
print("\n== (b) reproduce system_entropy.csv")
mine = system_table(calls)
ref = load_system()
j = ref.merge(mine, on=["model", "condition", "turn"], how="outer", suffixes=("_ref", "_re"), indicator=True)
print(f"  rows ref={len(ref)} recomputed={len(mine)}; merge: {j['_merge'].value_counts().to_dict()}")
cmp_rows = []
for col in [c for c in mine.columns if c not in ("model", "condition", "turn")]:
    if f"{col}_ref" not in j:
        continue
    a, b = j[f"{col}_ref"].astype(float), j[f"{col}_re"].astype(float)
    both_nan = a.isna() & b.isna()
    d = (a - b).abs()[~both_nan]
    cmp_rows.append(dict(column=col, max_abs_diff=float(d.max()) if d.notna().any() else np.nan,
                         n_nan_mismatch=int((a.isna() != b.isna()).sum())))
cmp = pd.DataFrame(cmp_rows)
print(cmp.to_string(index=False))
save_table(cmp, "t2b_system_entropy_reproduction")
save_table(mine, "system_entropy_recomputed", md=False)
