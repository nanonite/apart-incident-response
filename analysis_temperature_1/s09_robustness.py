"""Step 9: confounders, robustness and multiplicity.

(1) Token-validity audit: for each call, share of tokens whose sampled token is not in the returned top-k
    (chosen_in_topk = False). For qwen3-235b the provider often returns a stale top-k list (identical to the previous
    token's) with the sampled token absent; those token entropies are not the entropy of the sampled position.
    'clean' metric = mean H_renorm over tokens with chosen_in_topk = True (calls with no valid token dropped).
(2) Re-run s03 endpoints and s04 ITS with: H_lower; clean H_renorm; excluding WRITE_LOG/SUBMIT calls.
(3) Placebo runs with vs without donor contamination in submissions (descriptive).
(4) Gate s101-s110 as a descriptive switch replication (never pooled with full).
(5) Benjamini-Hochberg within families: endpoints (Wilcoxon p), ITS (DiD S-P, OLS-CR), across all specs run.
"""
import numpy as np
import pandas as pd

from common import K_STAR, MODELS, TABLES, Tee, bh, boot_ci, load_calls, load_runs, save_table
from s03_endpoints import endpoint_table
from s04_its import its_table

Tee("s09_robustness")
calls, runs = load_calls(), load_runs()
KEYC = ["model", "condition", "seed", "turn", "agent"]

# ---------------------------------------------------------------- (1) token validity
tok = pd.read_csv(TABLES / "tokens.csv.gz", usecols=KEYC + ["pos", "H_renorm_bits", "H_lower_bits", "chosen_in_topk", "placeholder"])
tok = tok[~tok.placeholder.astype(bool)]
tok["valid"] = tok.chosen_in_topk.astype(bool)
per_call = tok.groupby(KEYC).agg(frac_invalid=("valid", lambda v: 1 - v.mean()),
                                 n_valid=("valid", "sum")).reset_index()
clean = tok[tok.valid].groupby(KEYC).agg(mean_H_renorm_clean=("H_renorm_bits", "mean"),
                                         mean_H_lower_clean=("H_lower_bits", "mean")).reset_index()
calls = calls.merge(per_call, on=KEYC, how="left").merge(clean, on=KEYC, how="left")
audit = (calls[calls.has_tokens].assign(post=lambda x: x.turn >= K_STAR)
         .groupby(["model", "condition", "post"])
         .agg(calls=("frac_invalid", "size"), mean_frac_invalid=("frac_invalid", "mean"),
              calls_any_invalid=("frac_invalid", lambda v: (v > 0).mean()),
              calls_all_invalid=("n_valid", lambda v: (v == 0).mean())).reset_index())
save_table(audit, "t9_token_validity_audit")
print(audit.to_string(index=False))

# ---------------------------------------------------------------- (2) sensitivity reruns
def with_metric(df, metric):
    d = df.copy()
    d["has_tokens"] = d.has_tokens & d[metric].notna()
    return d


ep_parts, its_parts = [], []
t2 = pd.read_csv("out/tables/table2_endpoints.csv")
ep_parts.append(t2.assign(sensitivity="primary (s03)"))
t3 = pd.read_csv("out/tables/table3_its_did.csv")
its_parts.append(t3.assign(sensitivity="primary (s04)"))
for label, metric, drop_long in (("H_lower", "mean_H_lower_bits", False),
                                 ("clean H_renorm (chosen_in_topk only)", "mean_H_renorm_clean", False),
                                 ("no WRITE/SUBMIT", "mean_H_renorm_bits", True),
                                 ("clean H_renorm, no WRITE/SUBMIT", "mean_H_renorm_clean", True)):
    c = with_metric(calls, metric)
    ep, _ = endpoint_table(c, runs, metric=metric, tag="main", drop_long=drop_long)
    ep_parts.append(ep.assign(sensitivity=label))
    it = its_table(c, runs, metric=metric, specs=("main", "exposure"), mixed=False, drop_long=drop_long)
    its_parts.append(it.assign(sensitivity=label))
    print(f"done: {label}")

ep_all = pd.concat(ep_parts, ignore_index=True)
its_all = pd.concat(its_parts, ignore_index=True)

# ---------------------------------------------------------------- (5) BH within families
ep_all["p_bh_family_endpoints"] = bh(ep_all.p_wilcoxon)
did = its_all.term.str.contains("DiD S-P", na=False) & (its_all.estimator == "OLS-CR(seed)")
its_all["p_bh_family_its_DiD_SP"] = np.nan
its_all.loc[did, "p_bh_family_its_DiD_SP"] = bh(its_all.loc[did, "p"])
save_table(ep_all, "table9a_endpoints_sensitivity")
save_table(its_all, "table9b_its_sensitivity")

pd.set_option("display.width", 250)
show = ep_all[(ep_all.contrast == "comm") & (ep_all.adjust.isin(["adj", "raw"])) & (ep_all.window == 10) & (ep_all.kind == "level")]
print(show[["sensitivity", "spec", "model", "adjust", "n_seeds", "mean", "ci_low", "ci_high", "n_pos", "p_wilcoxon", "p_bh_family_endpoints"]].to_string(index=False))
print(its_all[did][["sensitivity", "model", "spec", "term", "est", "ci_low", "ci_high", "p", "p_bh_family_its_DiD_SP"]].to_string(index=False))
fam = pd.DataFrame([
    dict(family="endpoints (all contrasts, specs, sensitivities)", n_tests=int(ep_all.p_wilcoxon.notna().sum()),
         n_raw_p_lt_05=int((ep_all.p_wilcoxon < .05).sum()), n_bh_q_lt_05=int((ep_all.p_bh_family_endpoints < .05).sum()),
         n_bh_q_lt_10=int((ep_all.p_bh_family_endpoints < .10).sum())),
    dict(family="ITS DiD switch-placebo (OLS-CR)", n_tests=int(did.sum()),
         n_raw_p_lt_05=int((its_all.loc[did, "p"] < .05).sum()), n_bh_q_lt_05=int((its_all.loc[did, "p_bh_family_its_DiD_SP"] < .05).sum()),
         n_bh_q_lt_10=int((its_all.loc[did, "p_bh_family_its_DiD_SP"] < .10).sum())),
])
save_table(fam, "table9c_multiplicity")
print(fam.to_string(index=False))
sig = ep_all[ep_all.p_bh_family_endpoints < .10]
print("endpoint rows with BH q < 0.10:")
print(sig[["sensitivity", "spec", "model", "window", "adjust", "kind", "contrast", "mean", "ci_low", "ci_high", "p_wilcoxon", "p_bh_family_endpoints"]].to_string(index=False))

# ---------------------------------------------------------------- (3) placebo contamination
ct = pd.read_csv("out/tables/t1_submission_contamination_by_run.csv")
ep_run = pd.read_csv("out/tables/t3_endpoint_values_by_run.csv")
ep_run = ep_run[(ep_run.spec == "main") & (ep_run.window == 10) & (ep_run.adjust == "adj") & (ep_run.condition == "placebo")]
pc = ep_run.merge(ct, on=["model", "condition", "seed"])
rows = []
for (m, cont), g in pc.groupby(["model", "contaminated"]):
    mu, lo, hi = boot_ci(g.prepost.dropna().to_numpy(), offset=91)
    rows.append(dict(model=m, contaminated=cont, n_runs=len(g), prepost_H_adj_mean=mu, ci_low=lo, ci_high=hi))
pct = pd.DataFrame(rows)
save_table(pct, "t9_placebo_contamination_split")
print(pct.to_string(index=False))

# ---------------------------------------------------------------- (4) gate replication (descriptive)
gr = load_runs(gate=True)
gc = load_calls(gate=True)
gate_rows = []
for m, g in gr.groupby("model"):
    cl = gc[(gc.model == m) & gc.has_tokens]
    pre = cl[cl.turn < K_STAR].groupby("seed").mean_H_renorm_bits.mean()
    post = cl[(cl.turn >= K_STAR) & (cl.turn < K_STAR + 10)].groupby("seed").mean_H_renorm_bits.mean()
    gate_rows.append(dict(model=m, runs=len(g), seeds=",".join(map(str, sorted(g.seed))), task_success=g.task_success.mean(),
                          comm_verified=g.communication_verified.mean(), turns_mean=g.turns_executed.mean(),
                          tau_first_foreign_read_median=g.tau_first_foreign_read.median(),
                          H_pre_mean=pre.mean(), H_post10_mean=post.mean(), H_post_minus_pre_mean=(post - pre).mean()))
gate = pd.DataFrame(gate_rows)
save_table(gate, "t9_gate_replication")
print(gate.to_string(index=False))
