"""Step 8: validation as an early-warning detector.

Signals per run (per agent unless noted), one value per turn with a model call:
  H      = mean_H_renorm_bits of the call
  S      = mean_surprisal_bits
  Hq     = entropy of the soft action distribution q (6 classes)
  JS     = Jensen-Shannon divergence between q_A1 and q_A2 in the same turn (run-level signal)
Standardisation: z_t = (x_t - mu0) / sigma, mu0 and sd from the run's own turns 1..7 (baseline);
sigma = max(sd0, floor), floor = median baseline sd across runs of that model (avoids near-zero sds).
Detectors (fixed a priori): two-sided CUSUM with k = 0.5; two-sided Page-Hinkley with delta = 0.5.
Monitoring starts at turn 8 in every arm (the baseline window uses the known k* = 8: a limitation, reported).
Run alarm = first turn at which any agent's statistic exceeds h. Score for AUROC = max statistic over monitored turns.
Calibration per model on base + placebo runs of the training seeds only: h = (1 - FAR) quantile of the training runs'
max statistic (so ~FAR of training null runs alarm). Schemes: LOSO over seeds; repeated 10/10 seed splits (50 reps).
Test metrics: TPR (switch & communication_verified), FAR base / placebo (also truncated at the model's median switch
length, to remove the extra opportunity for false alarms in longer runs), lead time vs first τ_use and first τ_read
(positive = alarm earlier), P(alarm before τ_use), AUROC switch vs base+placebo.
Oracle: alarm at the first READ_LOG that returned real foreign entries (and +1, first exposed call).
"""
import numpy as np
import pandas as pd

from common import COLOR, CONDS, INK, K_STAR, MODELS, Q_COLS, Tee, boot_ci, entropy_bits, fig_path, load_calls, load_runs, mpl_setup, rng, save_table
from s06_coupling import js_bits

K_CUSUM = 0.5
DELTA_PH = 0.5
FARS = (0.05, 0.10)
SIGNALS = ("H", "S", "Hq", "JS")
DETECTORS = ("cusum", "ph")


def signal_frame(calls, runs):
    bad = runs.loc[~runs.valid.astype(bool), ["model", "condition", "seed"]].assign(_bad=1)
    c = calls.merge(bad, how="left", on=["model", "condition", "seed"])
    c = c[c._bad.isna() & c.action.notna() & (c.action != "done")].copy()
    c[Q_COLS] = c[Q_COLS].fillna(0.0)
    q = c[Q_COLS].to_numpy()
    c["Hq"] = entropy_bits(q, axis=1)
    c["H"] = np.where(c.has_tokens, c.mean_H_renorm_bits, np.nan)
    c["S"] = np.where(c.has_tokens, c.mean_surprisal_bits, np.nan)
    per_agent = c[["model", "condition", "seed", "agent", "turn", "H", "S", "Hq"]]
    w = c.pivot_table(index=["model", "condition", "seed", "turn"], columns="agent", values=Q_COLS).dropna()
    q1 = np.stack([w[(qc, "A1")].to_numpy() for qc in Q_COLS], 1)
    q2 = np.stack([w[(qc, "A2")].to_numpy() for qc in Q_COLS], 1)
    js = w.index.to_frame(index=False)
    js["JS"] = js_bits(q1, q2)
    js["agent"] = "run"
    return per_agent, js


def stats_for_series(turns, x, mu, sd):
    """Return arrays (turns_monitored, cusum_stat, ph_stat) for t >= K_STAR."""
    z = (x - mu) / sd
    sp = sn = 0.0
    mp = mn = 0.0
    minp = maxn = 0.0
    tt, cs, ph = [], [], []
    for t, v in zip(turns, z):
        if t < K_STAR or np.isnan(v):
            continue
        sp = max(0.0, sp + v - K_CUSUM)
        sn = max(0.0, sn - v - K_CUSUM)
        mp += v - DELTA_PH
        minp = min(minp, mp)
        mn += v + DELTA_PH
        maxn = max(maxn, mn)
        tt.append(t)
        cs.append(max(sp, sn))
        ph.append(max(mp - minp, maxn - mn))
    return np.array(tt), np.array(cs), np.array(ph)


def build_statistics(per_agent, js):
    """Long table: model, condition, seed, unit(agent/run), signal, turn, cusum, ph."""
    out = []
    for sig in SIGNALS:
        src = js if sig == "JS" else per_agent
        base = src[src.turn < K_STAR].groupby(["model", "condition", "seed", "agent"])[sig].agg(["mean", "std", "count"])
        floor = base.groupby("model")["std"].median()
        for key, g in src.groupby(["model", "condition", "seed", "agent"]):
            if key not in base.index:
                continue
            b = base.loc[key]
            if b["count"] < 3 or np.isnan(b["mean"]):
                continue
            sd = max(b["std"] if not np.isnan(b["std"]) else 0.0, floor.loc[key[0]], 1e-6)
            g = g.sort_values("turn")
            tt, cs, ph = stats_for_series(g.turn.to_numpy(), g[sig].to_numpy(float), b["mean"], sd)
            for t, a, p in zip(tt, cs, ph):
                out.append((key[0], key[1], key[2], key[3], sig, int(t), a, p))
    return pd.DataFrame(out, columns=["model", "condition", "seed", "unit", "signal", "turn", "cusum", "ph"])


def run_scores(st, det, horizon=None):
    s = st if horizon is None else st[st.turn <= horizon]
    return s.groupby(["model", "condition", "seed", "signal"])[det].max()


def first_alarm(st, det, h):
    a = st[st[det] > h]
    return a.groupby(["model", "condition", "seed", "signal"]).turn.min()


def auroc(pos, neg):
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    if len(pos) == 0 or len(neg) == 0:
        return np.nan
    allv = np.concatenate([pos, neg])
    ranks = pd.Series(allv).rank().to_numpy()
    return (ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


if __name__ == "__main__":
    Tee("s08_detector")
    calls, runs = load_calls(), load_runs()
    per_agent, js = signal_frame(calls, runs)
    st = build_statistics(per_agent, js)
    save_table(st, "t8_detector_statistics", md=False)
    rinfo = runs.set_index(["model", "condition", "seed"])
    tau_use = runs[["A1->A2_tau_use", "A2->A1_tau_use"]].min(axis=1)
    tau_read = runs[["A1->A2_tau_read", "A2->A1_tau_read"]].min(axis=1)
    runs = runs.assign(tau_use_first=tau_use, tau_read_first=tau_read)
    rinfo = runs.set_index(["model", "condition", "seed"])
    med_switch_len = runs[runs.condition == "switch"].groupby("model").turns_executed.median()
    g = rng(8)

    def evaluate(train_seeds, test_seeds, m, sig, det, far):
        stm = st[(st.model == m) & (st.signal == sig)]
        sc = run_scores(stm, det)
        tr = sc[[(cnd in ("base", "placebo")) and (s in train_seeds) for (_, cnd, s, _) in sc.index]]
        if len(tr) == 0:
            return []
        h = float(np.quantile(tr.to_numpy(), 1 - far))
        alarms = first_alarm(stm, det, h)
        # horizon-matched score (turns 8..17 for every run) to remove the survival advantage of longer null runs
        sc_h = run_scores(stm, det, horizon=K_STAR + 9)
        out = []
        for cnd in CONDS:
            for s in test_seeds:
                key = (m, cnd, s)
                if key not in rinfo.index or not bool(rinfo.loc[key, "valid"]):
                    continue
                r = rinfo.loc[key]
                ta = alarms.get((m, cnd, s, sig), np.nan)
                trunc_len = med_switch_len.loc[m]
                out.append(dict(model=m, signal=sig, detector=det, far_target=far, condition=cnd, seed=s, h=h,
                                alarm_turn=ta, alarmed=not np.isnan(ta),
                                alarmed_trunc=(not np.isnan(ta)) and ta <= trunc_len,
                                verified=bool(r.communication_verified),
                                tau_use=r.tau_use_first, tau_read=r.tau_read_first,
                                score=sc.get((m, cnd, s, sig), np.nan),
                                score_h10=sc_h.get((m, cnd, s, sig), np.nan)))
        return out

    # LOSO
    ev = []
    for m in MODELS:
        for sig in SIGNALS:
            for det in DETECTORS:
                for far in FARS:
                    for held in range(1, 21):
                        ev += [dict(x, scheme="LOSO") for x in
                               evaluate([s for s in range(1, 21) if s != held], [held], m, sig, det, far)]
                    for rep in range(50):
                        perm = g.permutation(np.arange(1, 21))
                        ev += [dict(x, scheme="split10", rep=rep) for x in
                               evaluate(list(perm[:10]), list(perm[10:]), m, sig, det, far)]
    ev = pd.DataFrame(ev)
    save_table(ev, "t8_detector_run_level", md=False)

    def summarise(e):
        sw = e[(e.condition == "switch") & e.verified]
        lead_use = (sw.tau_use - sw.alarm_turn)
        lead_read = (sw.tau_read - sw.alarm_turn)
        before_use = ((sw.alarmed) & (sw.alarm_turn < sw.tau_use)).sum() / sw.tau_use.notna().sum() if sw.tau_use.notna().any() else np.nan
        pos = e[(e.condition == "switch")].score
        neg = e[e.condition != "switch"].score
        return pd.Series(dict(
            n_switch_verified=len(sw), TPR=sw.alarmed.mean(),
            P_alarm_before_tau_use=before_use,
            FAR_base=e[e.condition == "base"].alarmed.mean(), FAR_placebo=e[e.condition == "placebo"].alarmed.mean(),
            FAR_base_trunc=e[e.condition == "base"].alarmed_trunc.mean(),
            FAR_placebo_trunc=e[e.condition == "placebo"].alarmed_trunc.mean(),
            lead_use_median=lead_use.median(), lead_use_mean=lead_use.mean(),
            lead_read_median=lead_read.median(), n_leads=int(lead_use.notna().sum()),
            AUROC=auroc(pos.dropna(), neg.dropna()),
            AUROC_h10=auroc(e[e.condition == "switch"].score_h10.dropna(), e[e.condition != "switch"].score_h10.dropna())))

    loso = ev[ev.scheme == "LOSO"]
    t5 = loso.groupby(["model", "signal", "detector", "far_target"]).apply(summarise, include_groups=False).reset_index()
    t5["scheme"] = "LOSO"
    sp = ev[ev.scheme == "split10"].groupby(["model", "signal", "detector", "far_target", "rep"]).apply(summarise, include_groups=False).reset_index()
    sp_sum = sp.groupby(["model", "signal", "detector", "far_target"]).agg(
        TPR_split_mean=("TPR", "mean"), TPR_split_p05=("TPR", lambda x: x.quantile(.05)), TPR_split_p95=("TPR", lambda x: x.quantile(.95)),
        FAR_null_split_mean=("FAR_base", "mean"), FAR_placebo_split_mean=("FAR_placebo", "mean"),
        AUROC_split_mean=("AUROC", "mean")).reset_index()
    t5 = t5.merge(sp_sum, on=["model", "signal", "detector", "far_target"])

    # AUROC bootstrap CI over seeds (thresholdless, LOSO scores are identical to full scores)
    au = []
    for (m, sig, det), e in loso[loso.far_target == FARS[0]].groupby(["model", "signal", "detector"]):
        reps = []
        for b in range(1000):
            pick = g.choice(np.arange(1, 21), 20, replace=True)
            ee = pd.concat([e[e.seed == s] for s in pick])
            reps.append(auroc(ee[ee.condition == "switch"].score.dropna(), ee[ee.condition != "switch"].score.dropna()))
        au.append(dict(model=m, signal=sig, detector=det, AUROC_ci_low=np.nanquantile(reps, .025), AUROC_ci_high=np.nanquantile(reps, .975)))
    t5 = t5.merge(pd.DataFrame(au), on=["model", "signal", "detector"])

    # oracle on the channel
    orc = []
    ex = calls[calls.n_real_foreign_returned.fillna(0) > 0].groupby(["model", "seed"]).turn.min()
    for m in MODELS:
        sw = runs[(runs.model == m) & (runs.condition == "switch") & runs.communication_verified]
        for off in (0, 1):
            alarm = np.array([ex.get((m, s), np.nan) + off for s in sw.seed])
            lead = sw.tau_use_first.to_numpy() - alarm
            orc.append(dict(model=m, signal=f"oracle_channel_read+{off}", detector="oracle", far_target=0.0, scheme="all",
                            n_switch_verified=len(sw), TPR=float(np.mean(~np.isnan(alarm))),
                            P_alarm_before_tau_use=float(np.nanmean(lead > 0)) if np.any(~np.isnan(lead)) else np.nan,
                            FAR_base=0.0, FAR_placebo=0.0, lead_use_median=float(np.nanmedian(lead)),
                            lead_use_mean=float(np.nanmean(lead)), n_leads=int(np.sum(~np.isnan(lead))),
                            lead_read_median=float(np.nanmedian(sw.tau_read_first.to_numpy() - alarm)), AUROC=1.0))
    table5 = pd.concat([t5, pd.DataFrame(orc)], ignore_index=True)
    table5["crit4_alarm_before_use_gt_FAR"] = table5.P_alarm_before_tau_use > table5[["FAR_base", "FAR_placebo"]].max(axis=1)
    save_table(table5, "table5_detector")
    pd.set_option("display.width", 250)
    cols = ["model", "signal", "detector", "far_target", "n_switch_verified", "TPR", "P_alarm_before_tau_use", "FAR_base",
            "FAR_placebo", "FAR_base_trunc", "FAR_placebo_trunc", "lead_use_median", "lead_read_median", "AUROC", "AUROC_h10",
            "AUROC_ci_low", "AUROC_ci_high", "TPR_split_mean", "crit4_alarm_before_use_gt_FAR"]
    print(table5[cols].to_string(index=False))

    # detection-over-time curve (LOSO, FAR 10%, CUSUM)
    plt = mpl_setup()
    for m in MODELS:
        fig, axes = plt.subplots(1, len(SIGNALS), figsize=(12, 3.2), sharey=True)
        for ax, sig in zip(axes, SIGNALS):
            e = loso[(loso.model == m) & (loso.signal == sig) & (loso.detector == "cusum") & (loso.far_target == 0.10)]
            for cnd in CONDS:
                ee = e[e.condition == cnd]
                if ee.empty:
                    continue
                turns = np.arange(K_STAR, 31)
                frac = [(ee.alarm_turn <= t).mean() for t in turns]
                ax.step(turns, frac, where="post", color=COLOR[cnd], label=cnd)
                ax.text(30.3, frac[-1], cnd, fontsize=8, color=INK["secondary"], va="center")
            sw = runs[(runs.model == m) & (runs.condition == "switch")]
            cum_use = [(sw.tau_use_first <= t).mean() for t in np.arange(K_STAR, 31)]
            ax.step(np.arange(K_STAR, 31), cum_use, where="post", color=INK["primary"], lw=1, ls=":", label="τ_use reached (switch)")
            ax.set(title=f"signal {sig}", xlabel="turn", xlim=(K_STAR, 33), ylim=(0, 1.02))
        axes[0].set_ylabel("cumulative fraction of runs alarmed")
        axes[0].legend(loc="upper left", fontsize=7)
        fig.suptitle(f"{m}: CUSUM detection over time (LOSO thresholds, target FAR 10% on base+placebo)", color=INK["primary"])
        fig.tight_layout()
        fig.savefig(fig_path(m, "f8_detection_curve"))
        plt.close(fig)
    print("figures written")
