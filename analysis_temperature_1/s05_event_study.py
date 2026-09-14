"""Step 5: event study aligned on real communication events.

switch: per direction (author -> receiver) align on τ_read and on τ_use (runs.csv); curves for receiver and author.
placebo: per agent, align on the first turn that agent received donor entries (n_placebo_returned > 0);
         the other agent of the run is the non-exposed comparison.
Timing: the call at τ_read is the READ_LOG itself; its output text was generated BEFORE the entries were returned.
The returned entries first appear in the receiver's prompt at τ_read+1 ("RESULT OF THAT ACTION"), so rel=+1 is the
first exposed call. At τ_use the used content is already in the prompt (the use is the call's output).
Window t-τ in [-5, +5]. One value per run x agent x relative turn (each agent has one call per turn).
Metrics: mean_H_renorm_bits (raw and action/length-adjusted from s03.prepare) and mean_surprisal_bits.
Summary per run: mean(+1..+3) - mean(-3..-1), bootstrap CI over runs; receiver minus author.
Also reproduces tables_full/aligned_tau_read.csv to document its alignment definition.
"""
import numpy as np
import pandas as pd

from common import COLOR, INK, MODELS, Tee, boot_ci, fig_path, load_calls, load_runs, mpl_setup, save_table
from s03_endpoints import prepare

WIN = 5


def events(calls, runs):
    ev = []
    sw = runs[runs.condition == "switch"]
    for _, r in sw.iterrows():
        for d in ("A1->A2", "A2->A1"):
            author, receiver = d.split("->")
            for kind in ("tau_read", "tau_use"):
                tau = r[f"{d}_{kind}"]
                if pd.notna(tau):
                    ev.append(dict(model=r.model, condition="switch", seed=r.seed, align=kind, direction=d,
                                   receiver=receiver, author=author, tau=int(tau)))
    pl = calls[(calls.condition == "placebo") & (calls.n_placebo_returned.fillna(0) > 0)]
    first = pl.groupby(["model", "seed", "agent"]).turn.min().reset_index()
    for r in first.itertuples(index=False):
        other = "A2" if r.agent == "A1" else "A1"
        ev.append(dict(model=r.model, condition="placebo", seed=r.seed, align="tau_placebo_read",
                       direction=f"donor->{r.agent}", receiver=r.agent, author=other, tau=int(r.turn)))
    return pd.DataFrame(ev)


def aligned_values(ev, d, ycols):
    rows = []
    key = d.set_index(["model", "condition", "seed", "agent", "turn"])
    for e in ev.itertuples(index=False):
        for role, ag in (("receiver", e.receiver), ("author", e.author)):
            for rel in range(-WIN, WIN + 1):
                k = (e.model, e.condition, e.seed, ag, e.tau + rel)
                if k in key.index:
                    v = key.loc[k]
                    v = v.iloc[0] if isinstance(v, pd.DataFrame) else v
                    rows.append(dict(model=e.model, condition=e.condition, seed=e.seed, align=e.align,
                                     direction=e.direction, role=role, agent=ag, rel=rel, action=v["action"],
                                     **{c: v[c] for c in ycols}))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    Tee("s05_event_study")
    calls, runs = load_calls(), load_runs()
    d = prepare(calls, runs)  # rows with tokens, valid runs; y_raw, y_adj
    ycols = ["y_raw", "y_adj", "mean_surprisal_bits"]
    ev = events(calls, runs)
    print(ev.groupby(["model", "align"]).size().to_string())
    av = aligned_values(ev, d, ycols)
    save_table(av, "t5_event_aligned_values", md=False)

    # curves
    curve = []
    for (m, al, role, rel), g in av.groupby(["model", "align", "role", "rel"]):
        for c in ycols:
            mu, lo, hi = boot_ci(g[c].to_numpy(), n_boot=2000, offset=rel + 10)
            curve.append(dict(model=m, align=al, role=role, rel=rel, metric=c, n=len(g), mean=mu, ci_low=lo, ci_high=hi,
                              frac_read_log=(g.action == "read_log").mean()))
    curve = pd.DataFrame(curve)
    save_table(curve, "t5_event_curves", md=False)

    # per-event summary: post(+1..+3) - pre(-3..-1)
    summ = []
    for (m, al, role), g in av.groupby(["model", "align", "role"]):
        for c in ycols:
            per = []
            for (s, dr), gg in g.groupby(["seed", "direction"]):
                pre = gg[(gg.rel >= -3) & (gg.rel <= -1)][c].mean()
                post = gg[(gg.rel >= 1) & (gg.rel <= 3)][c].mean()
                per.append(dict(seed=s, direction=dr, diff=post - pre))
            per = pd.DataFrame(per).dropna()
            mu, lo, hi = boot_ci(per["diff"].to_numpy(), offset=3)
            summ.append(dict(model=m, align=al, role=role, metric=c, n_events=len(per), post_minus_pre=mu,
                             ci_low=lo, ci_high=hi, n_pos=int((per["diff"] > 0).sum())))
    summ = pd.DataFrame(summ)
    # receiver - author, paired by event
    rva = []
    for (m, al), g in av.groupby(["model", "align"]):
        for c in ycols:
            per = []
            for (s, dr), gg in g.groupby(["seed", "direction"]):
                vals = {}
                for role in ("receiver", "author"):
                    x = gg[gg.role == role]
                    vals[role] = x[(x.rel >= 1) & (x.rel <= 3)][c].mean() - x[(x.rel >= -3) & (x.rel <= -1)][c].mean()
                per.append(vals["receiver"] - vals["author"])
            per = np.array(per, float)
            per = per[~np.isnan(per)]
            mu, lo, hi = boot_ci(per, offset=4)
            rva.append(dict(model=m, align=al, role="receiver-author", metric=c, n_events=len(per),
                            post_minus_pre=mu, ci_low=lo, ci_high=hi, n_pos=int((per > 0).sum())))
    table5a = pd.concat([summ, pd.DataFrame(rva)], ignore_index=True)
    save_table(table5a, "t5_event_study_summary")
    pd.set_option("display.width", 220)
    print(table5a[table5a.metric != "y_raw"].to_string(index=False))

    # reproduce aligned_tau_read.csv
    ref = pd.read_csv("../tables_full/aligned_tau_read.csv")
    sw = calls[(calls.condition == "switch") & calls.has_tokens]
    cands = {}
    r_sw = runs[runs.condition == "switch"].set_index(["model", "seed"])
    for name in ("tau_first_foreign_read", "receiver_tau_read"):
        x = sw.copy()
        if name == "tau_first_foreign_read":
            x["tau"] = [r_sw.loc[(m, s), "tau_first_foreign_read"] for m, s in zip(x.model, x.seed)]
        else:  # agent's own tau_read as receiver
            x["tau"] = [r_sw.loc[(m, s), ("A2->A1_tau_read" if a == "A1" else "A1->A2_tau_read")]
                        for m, s, a in zip(x.model, x.seed, x.agent)]
        x = x[x.tau.notna()]
        x["turn_minus_tau_read"] = (x.turn - x.tau).astype(int)
        g = x.groupby(["model", "agent", "turn_minus_tau_read"]).mean_H_renorm_bits.agg(["size", "mean"]).reset_index()
        j = ref.merge(g, on=["model", "agent", "turn_minus_tau_read"], how="outer")
        cands[name] = dict(rows_ref=len(ref), rows_match=int(j[["n", "size"]].notna().all(axis=1).sum()),
                           max_abs_diff_mean=float((j.tokH_mean - j["mean"]).abs().max()),
                           n_mismatch=int((j.n != j["size"]).sum()))
    print("aligned_tau_read.csv reproduction:", cands)
    save_table(pd.DataFrame(cands).T.reset_index(names="alignment"), "t5_aligned_tau_read_reproduction")

    # figures
    plt = mpl_setup()
    for m in MODELS:
        fig, axes = plt.subplots(2, 3, figsize=(11, 5.6), sharex=True)
        for j, (al, cond) in enumerate((("tau_read", "switch"), ("tau_use", "switch"), ("tau_placebo_read", "placebo"))):
            for i, (metric, lab) in enumerate((("y_adj", "H̄ adjusted (bits/token)"), ("mean_surprisal_bits", "surprisal (bits/token)"))):
                ax = axes[i, j]
                for role, ls in (("receiver", "-"), ("author", ":")):
                    cc = curve[(curve.model == m) & (curve["align"] == al) & (curve.role == role) & (curve.metric == metric)]
                    if cc.empty:
                        continue
                    ax.fill_between(cc.rel, cc.ci_low, cc.ci_high, color=COLOR[cond], alpha=.12 if role == "receiver" else .06, lw=0)
                    ax.plot(cc.rel, cc["mean"], color=COLOR[cond], ls=ls, marker="o", ms=4, label=role if role == "receiver" else "other agent")
                    ax.text(WIN + .2, cc["mean"].iloc[-1], "receiver" if role == "receiver" else "other", fontsize=8,
                            color=INK["secondary"], va="center")
                ax.axvline(0, color=INK["muted"], lw=1, ls="--")
                if i == 0:
                    n_ev = int(curve[(curve.model == m) & (curve["align"] == al) & (curve.role == "receiver") & (curve.rel == 0) & (curve.metric == metric)].n.sum())
                    ax.set_title(f"{cond} · {al} (n={n_ev})")
                if j == 0:
                    ax.set_ylabel(lab)
                if i == 1:
                    ax.set_xlabel("turn − τ")
                ax.set_xlim(-WIN - .5, WIN + 1.8)
        axes[0, 0].legend(loc="upper left")
        fig.suptitle(f"{m}: event study around real (switch) and donor (placebo) exposure; 95% bootstrap CI over events", color=INK["primary"])
        fig.tight_layout()
        fig.savefig(fig_path(m, "f5_event_study"))
        plt.close(fig)
    print("figures written")
