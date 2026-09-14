"""Step 6: system coupling I(X1;X2).

(a) per turn: soft I - I_shuffled and hard I (Miller-Madow) with a permutation null (500 random re-pairings of
    A2 rows across seeds within the turn): 95th percentile band and permutation p-value;
(b) pre (t<8) vs post (t>=8) means over turns with runs_paired >= 10, seed-bootstrap CIs (1000 resamples of seeds);
(c) per-seed jackknife pseudo-values of the post-window mean of (I - I_shuffled), giving a per-seed ΔI_comm that can
    be compared in sign with ΔH_comm from s03 (criterion 1);
(d) per-run signals: Jensen-Shannon divergence between q_A1 and q_A2 in the same turn, and the rolling (5-turn)
    correlation of the two agents' H̄ trajectories.
"""
import numpy as np
import pandas as pd

from common import COLOR, CONDS, INK, K_STAR, MODELS, Q_COLS, Tee, boot_ci, fig_path, load_calls, load_runs, load_system, mark_kstar, mpl_setup, rng, save_table
from sysent import hard_I, paired_arrays, soft_I

N_PERM = 500
N_BOOT = 1000
RP_MIN = 10
POST_W = 10  # post window for the per-seed jackknife: turns 8..17 (same as s03 w=10)


def js_bits(p, q):
    p = np.asarray(p, float)
    q = np.asarray(q, float)
    m = (p + q) / 2

    def kl(a, b):
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(a > 0, a * np.log2(a / b), 0.0).sum(-1)
    return 0.5 * kl(p, m) + 0.5 * kl(q, m)


def turn_arrays(calls):
    out = {}
    for (m, c, t), g in calls.groupby(["model", "condition", "turn"]):
        seeds, q1, q2, a1, a2 = paired_arrays(g)
        if len(seeds):
            out[(m, c, t)] = (seeds, q1, q2, a1, a2)
    return out


def stat_pair(q1, q2, a1, a2):
    _, _, I, _, Ish = soft_I(q1, q2)
    _, _, _, mm, _ = hard_I(a1, a2)
    return I - Ish, mm


if __name__ == "__main__":
    Tee("s06_coupling")
    calls, runs = load_calls(), load_runs()
    ref = load_system()
    arrs = turn_arrays(calls)
    g = rng(6)

    # ---- (a) per-turn permutation null
    rows = []
    for (m, c, t), (seeds, q1, q2, a1, a2) in arrs.items():
        n = len(seeds)
        obs_soft, obs_hard = stat_pair(q1, q2, a1, a2)
        null_s, null_h = np.full(N_PERM, np.nan), np.full(N_PERM, np.nan)
        if n >= 3:
            for b in range(N_PERM):
                p = g.permutation(n)
                null_s[b], null_h[b] = stat_pair(q1, q2[p], a1, a2[p])
        rows.append(dict(model=m, condition=c, turn=t, runs_paired=n, I_minus_shuffled=obs_soft, hard_I_MM=obs_hard,
                         null95_soft=np.nanquantile(null_s, .95) if n >= 3 else np.nan,
                         null95_hard=np.nanquantile(null_h, .95) if n >= 3 else np.nan,
                         p_perm_soft=(1 + np.sum(null_s >= obs_soft - 1e-12)) / (N_PERM + 1) if n >= 3 else np.nan,
                         p_perm_hard=(1 + np.sum(null_h >= obs_hard - 1e-12)) / (N_PERM + 1) if n >= 3 else np.nan))
    per_turn = pd.DataFrame(rows).sort_values(["model", "condition", "turn"])
    per_turn = per_turn.merge(ref[["model", "condition", "turn", "H_system_bits", "H_system_ci_low", "H_system_ci_high", "sum_H_bits"]],
                              on=["model", "condition", "turn"], how="left")
    save_table(per_turn, "t6_coupling_per_turn", md=False)
    sig = per_turn[per_turn.runs_paired >= RP_MIN]
    print("turns (runs_paired>=10) whose observed statistic exceeds the permutation 95th percentile:")
    print(sig.assign(exc_soft=sig.I_minus_shuffled > sig.null95_soft, exc_hard=sig.hard_I_MM > sig.null95_hard,
                     post=sig.turn >= K_STAR)
          .groupby(["model", "condition", "post"])[["exc_soft", "exc_hard"]].agg(["sum", "size"]).to_string())

    # ---- (b) pre/post with seed bootstrap
    def prepost_stats(sub_arrs, idx_map=None):
        res = {}
        for (t, (seeds, q1, q2, a1, a2)) in sub_arrs:
            if idx_map is not None:
                sel = [np.where(seeds == s)[0][0] for s in idx_map if s in seeds]
                if len(sel) < 3:
                    continue
                sel = np.array(sel)
                q1_, q2_, a1_, a2_ = q1[sel], q2[sel], a1[sel], a2[sel]
            else:
                q1_, q2_, a1_, a2_ = q1, q2, a1, a2
            res[t] = stat_pair(q1_, q2_, a1_, a2_)
        return res

    pp_rows = []
    for m in MODELS:
        for c in CONDS:
            sub = [(t, v) for (mm, cc, t), v in arrs.items() if mm == m and cc == c and len(v[0]) >= RP_MIN]
            obs = prepost_stats(sub)
            pre = [v for t, v in obs.items() if t < K_STAR]
            post = [v for t, v in obs.items() if t >= K_STAR]
            if not pre or not post:
                continue
            # Delete-one-seed jackknife. (A with-replacement seed bootstrap is invalid here: duplicated seeds make
            # the mixture look more heterogeneous and bias I upwards, so percentile intervals missed the estimate.)
            est = np.array([np.mean([v[0] for v in pre]), np.mean([v[0] for v in post]),
                            np.mean([v[1] for v in pre]), np.mean([v[1] for v in post])])
            est = np.r_[est, est[1] - est[0], est[3] - est[2]]
            all_seeds = sorted(set().union(*[set(v[0]) for _, v in sub]))
            loo = []
            for s_out in all_seeds:
                bs = {}
                for t, (seeds, q1, q2, a1, a2) in sub:
                    keep = seeds != s_out
                    bs[t] = stat_pair(q1[keep], q2[keep], a1[keep], a2[keep])
                v = [np.mean([x[0] for t, x in bs.items() if t < K_STAR]), np.mean([x[0] for t, x in bs.items() if t >= K_STAR]),
                     np.mean([x[1] for t, x in bs.items() if t < K_STAR]), np.mean([x[1] for t, x in bs.items() if t >= K_STAR])]
                loo.append(v + [v[1] - v[0], v[3] - v[2]])
            loo = np.array(loo)
            n_s = len(all_seeds)
            se = np.sqrt((n_s - 1) / n_s * ((loo - loo.mean(0)) ** 2).sum(0))
            labs = ["soft I-Ish pre", "soft I-Ish post", "hard I_MM pre", "hard I_MM post", "soft I-Ish post-pre", "hard I_MM post-pre"]
            for i, lab in enumerate(labs):
                pp_rows.append(dict(model=m, condition=c, quantity=lab, est=est[i], jk_se=se[i],
                                    ci_low=est[i] - 1.96 * se[i], ci_high=est[i] + 1.96 * se[i],
                                    n_turns=len(pre) if lab.endswith(" pre") else (len(post) if lab.endswith("post") else np.nan),
                                    n_seeds=n_s))
    # post-pre differences between arms (switch - placebo etc.) with the same paired jackknife would need joint
    # leave-one-seed-out across arms; reported below from the per-seed pseudo-values instead.
    pp = pd.DataFrame(pp_rows)
    save_table(pp, "table6_coupling_prepost")
    print(pp.to_string(index=False))

    # ---- (c) per-seed jackknife pseudo-values of post-window mean (I - Ish)
    jk_rows = []
    for m in MODELS:
        for c in CONDS:
            sub = [(t, v) for (mm, cc, t), v in arrs.items()
                   if mm == m and cc == c and K_STAR <= t < K_STAR + POST_W and len(v[0]) >= 3]
            if not sub:
                continue
            all_seeds = sorted(set().union(*[set(v[0]) for _, v in sub]))
            full = np.mean([stat_pair(v[1], v[2], v[3], v[4])[0] for _, v in sub])
            n = len(all_seeds)
            for s in all_seeds:
                vals = []
                for _, (seeds, q1, q2, a1, a2) in sub:
                    keep = seeds != s
                    if keep.sum() >= 2:
                        vals.append(stat_pair(q1[keep], q2[keep], a1[keep], a2[keep])[0])
                loo = np.mean(vals)
                jk_rows.append(dict(model=m, condition=c, seed=s, pseudo=n * full - (n - 1) * loo))
    jk = pd.DataFrame(jk_rows)
    wide = jk.pivot_table(index=["model", "seed"], columns="condition", values="pseudo").reset_index()
    wide["dI_comm"] = wide["switch"] - 0.5 * (wide["base"] + wide["placebo"])
    ep = pd.read_csv("out/tables/t3_endpoint_values_by_run.csv")
    ep = ep[(ep.spec == "main") & (ep.window == POST_W) & (ep.adjust == "adj")]
    ew = ep.pivot_table(index=["model", "seed"], columns="condition", values="level").reset_index()
    ew["dH_comm"] = ew["switch"] - 0.5 * (ew["base"] + ew["placebo"])
    crit = wide[["model", "seed", "dI_comm"]].merge(ew[["model", "seed", "dH_comm"]], on=["model", "seed"])
    crit = crit.dropna()
    crit["same_sign"] = np.sign(crit.dI_comm) == np.sign(crit.dH_comm)
    save_table(crit, "t6_criterion1_per_seed", md=False)
    c1 = crit.groupby("model").agg(n=("same_sign", "size"), same_sign=("same_sign", "sum"),
                                   dI_pos=("dI_comm", lambda x: int((x > 0).sum())),
                                   dH_pos=("dH_comm", lambda x: int((x > 0).sum()))).reset_index()
    c1.loc[len(c1)] = ["all", c1.n.sum(), c1.same_sign.sum(), c1.dI_pos.sum(), c1.dH_pos.sum()]
    c1["frac_same_sign"] = c1.same_sign / c1.n
    dI = [dict(model=m, **dict(zip(["dI_comm_mean", "ci_low", "ci_high"], boot_ci(gr.dI_comm.to_numpy(), offset=61))))
          for m, gr in wide.dropna(subset=["dI_comm"]).groupby("model")]
    save_table(c1.merge(pd.DataFrame(dI), on="model", how="left"), "t6_criterion1_summary")
    print(c1.merge(pd.DataFrame(dI), on="model", how="left").to_string(index=False))

    # ---- (d) per-run JS divergence and rolling correlation
    ok = calls[calls.action.notna()].copy()
    ok[Q_COLS] = ok[Q_COLS].fillna(0.0)
    w = ok.pivot_table(index=["model", "condition", "seed", "turn"], columns="agent", values=Q_COLS)
    w = w.dropna()
    q1 = np.stack([w[(qc, "A1")].to_numpy() for qc in Q_COLS], 1)
    q2 = np.stack([w[(qc, "A2")].to_numpy() for qc in Q_COLS], 1)
    js = w.index.to_frame(index=False)
    js["JS_bits"] = js_bits(q1, q2)
    hb = calls[calls.has_tokens].pivot_table(index=["model", "condition", "seed", "turn"], columns="agent",
                                             values="mean_H_renorm_bits").reset_index()
    hb["roll_corr5"] = np.nan
    for key, gg in hb.groupby(["model", "condition", "seed"]):
        gg = gg.sort_values("turn")
        hb.loc[gg.index, "roll_corr5"] = gg["A1"].rolling(5, min_periods=4).corr(gg["A2"])
    runsig = js.merge(hb[["model", "condition", "seed", "turn", "roll_corr5"]], how="left",
                      on=["model", "condition", "seed", "turn"])
    save_table(runsig, "t6_run_signals_js_corr", md=False)
    js_rows = []
    for (m, c), gg in runsig.groupby(["model", "condition"]):
        per_seed = gg.assign(post=gg.turn >= K_STAR).groupby(["seed", "post"]).JS_bits.mean().unstack()
        diff = (per_seed.get(True) - per_seed.get(False)).dropna().to_numpy()
        mu, lo, hi = boot_ci(diff, offset=62)
        js_rows.append(dict(model=m, condition=c, JS_post_minus_pre=mu, ci_low=lo, ci_high=hi, n_seeds=len(diff),
                            JS_pre=np.nanmean(per_seed.get(False)), JS_post=np.nanmean(per_seed.get(True))))
    jst = pd.DataFrame(js_rows)
    save_table(jst, "t6_js_prepost")
    print(jst.to_string(index=False))

    # ---- figures
    plt = mpl_setup()
    for m in MODELS:
        fig, axes = plt.subplots(1, 3, figsize=(12, 3.5), sharex=True)
        for c in CONDS:
            pt = per_turn[(per_turn.model == m) & (per_turn.condition == c) & (per_turn.runs_paired >= 5)]
            if pt.empty:
                continue
            ax = axes[0]
            ax.fill_between(pt.turn, pt.H_system_ci_low, pt.H_system_ci_high, color=COLOR[c], alpha=.12, lw=0)
            ax.plot(pt.turn, pt.H_system_bits, color=COLOR[c], label=c)
            ax.text(pt.turn.iloc[-1] + .3, pt.H_system_bits.iloc[-1], c, fontsize=8, color=INK["secondary"], va="center")
            for ax, col, nul in ((axes[1], "I_minus_shuffled", "null95_soft"), (axes[2], "hard_I_MM", "null95_hard")):
                ax.plot(pt.turn, pt[col], color=COLOR[c], label=c)
                ax.plot(pt.turn, pt[nul], color=COLOR[c], lw=1, ls=":")
                ax.text(pt.turn.iloc[-1] + .3, pt[col].iloc[-1], c, fontsize=8, color=INK["secondary"], va="center")
        axes[0].set(title="H(X1,X2), soft action distribution", ylabel="bits")
        axes[1].set(title="I − I_shuffled (dotted: permutation 95th pct)")
        axes[2].set(title="hard I, Miller–Madow (dotted: permutation 95th pct)")
        for ax in axes:
            mark_kstar(ax)
            ax.set_xlabel("turn")
            ax.set_xlim(1, 32)
        axes[0].legend(loc="upper right")
        fig.suptitle(f"{m}: system entropy and coupling across runs (turns with ≥5 paired runs)", color=INK["primary"])
        fig.tight_layout()
        fig.savefig(fig_path(m, "f6_system_coupling"))
        plt.close(fig)
    print("figures written")
