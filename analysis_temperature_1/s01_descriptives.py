"""Step 1: descriptives (Table 1), action distributions per turn, survival curves."""
import json

import numpy as np
import pandas as pd

from common import (ACTION_CLASSES, COLOR, CONDS, INK, K_STAR, MODELS, Tee, fig_path, load_calls,
                    load_runs, mark_kstar, mpl_setup, run_dir, save_table)

Tee("s01_descriptives")
runs = load_runs()
calls = load_calls()
DIRS = ["A1->A2", "A2->A1"]


def med_iqr(x):
    x = pd.Series(x).dropna()
    if x.empty:
        return "—"
    return f"{x.median():g} [{x.quantile(.25):g}–{x.quantile(.75):g}] (n={len(x)})"


# placebo contamination / hallucinations from check.json
contam = []
for r in runs.itertuples():
    chk = json.load(open(run_dir(r.model, r.condition, r.seed) / "check.json"))
    subs = chk.get("submissions", {})
    contam.append(dict(model=r.model, condition=r.condition, seed=r.seed,
                       n_submissions=len(subs),
                       contaminated=any(bool(s.get("placebo_contamination")) for s in subs.values()),
                       invented_tables=any(bool(s.get("invented_tables")) for s in subs.values()),
                       invented_hex=any(bool(s.get("invented_hex")) for s in subs.values())))
contam = pd.DataFrame(contam)
save_table(contam, "t1_submission_contamination_by_run", md=False)

rows = []
for (m, c), g in runs.groupby(["model", "condition"], sort=False):
    cl = calls[(calls.model == m) & (calls.condition == c)]
    ct = contam[(contam.model == m) & (contam.condition == c)]
    dec = cl[cl.action == "decrypt"]
    row = dict(model=m, condition=c, runs=len(g), invalid=int((~g.valid.astype(bool)).sum()),
               task_success=g.task_success.mean(), both_complete=(g.n_complete == 2).mean(),
               comm_verified=g.communication_verified.mean(),
               complete_via_channel=g.complete_via_verified_channel.mean(),
               turns_mean=g.turns_executed.mean(), turns_median=g.turns_executed.median(),
               parse_fail_mean=g.parse_fail_rate.mean(), api_errors=int(g.api_errors.sum()),
               cost_usd=g.cost_usd.sum(),
               decrypt_calls=len(dec), pw_other_rate=(dec.password_source == "other").mean(),
               pw_peer=int((dec.password_source == "peer").sum()),
               runs_with_submission=int((ct.n_submissions > 0).sum()),
               placebo_contaminated_runs=int(ct.contaminated.sum()),
               invented_tables_runs=int(ct.invented_tables.sum()), invented_hex_runs=int(ct.invented_hex.sum()),
               placebo_decrypt_attempts=int(g.placebo_decrypt_attempts.sum()))
    for d in DIRS:
        vc = g[f"{d}_verdict"].value_counts()
        row[f"{d} W/R/V"] = f"{vc.get('WRITTEN_NOT_READ',0)}/{vc.get('READ_NOT_USED',0)}/{vc.get('VERIFIED',0)}"
        for k in ("tau_write", "tau_read", "tau_use"):
            row[f"{d} {k}"] = med_iqr(g[f"{d}_{k}"])
    row["tau_first_foreign_read"] = med_iqr(g.tau_first_foreign_read)
    rows.append(row)
t1 = pd.DataFrame(rows)
t1["condition"] = pd.Categorical(t1.condition, CONDS)
t1 = t1.sort_values(["model", "condition"])
save_table(t1, "table1_descriptives")
print(t1.T.to_string())

# ---- per-turn action distribution (realised actions) and survival
calls["cls"] = calls.action_class.fillna("API_ERR")
dist = (calls.groupby(["model", "condition", "turn", "agent"]).cls.value_counts(normalize=False)
        .unstack(fill_value=0).reset_index())
save_table(dist, "t1_action_counts_by_turn", md=False)
surv = []
for (m, c), g in runs.groupby(["model", "condition"]):
    for t in range(1, 31):
        cl = calls[(calls.model == m) & (calls.condition == c) & (calls.turn == t)]
        surv.append(dict(model=m, condition=c, turn=t, runs_present=int((g.turns_executed >= t).sum()),
                         agents_acting=int(((cl.action != "done")).sum())))
surv = pd.DataFrame(surv)
save_table(surv, "t1_survival", md=False)

plt = mpl_setup()
ACOL = {"READ": "#eda100", "WRITE": "#e87ba4", "DECRYPT": "#008300", "SUBMIT": "#4a3aa7",
        "OTHER": "#e34948", "DONE": "#c9c8c2", "API_ERR": "#52514e"}
order = ["READ", "DECRYPT", "WRITE", "SUBMIT", "OTHER", "API_ERR", "DONE"]
for m in MODELS:
    fig, axes = plt.subplots(2, 3, figsize=(11, 5.4), sharex=True, sharey=True)
    for j, c in enumerate(CONDS):
        for i, a in enumerate(["A1", "A2"]):
            ax = axes[i, j]
            d = dist[(dist.model == m) & (dist.condition == c) & (dist.agent == a)].set_index("turn")
            d = d.reindex(columns=order, fill_value=0).reindex(range(1, 31), fill_value=0)
            bottom = np.zeros(30)
            for k in order:
                ax.bar(d.index, d[k], bottom=bottom, color=ACOL[k], width=0.86, label=k, linewidth=0)
                bottom += d[k].to_numpy()
            mark_kstar(ax, K_STAR - 0.5)
            ax.set_title(f"{c} · {a} ({'BRAND_KIT' if a=='A1' else 'SCHEMA'})", color=INK["primary"])
            ax.grid(axis="x", visible=False)
    for ax in axes[:, 0]:
        ax.set_ylabel("runs (count)")
    for ax in axes[1]:
        ax.set_xlabel("turn")
    h, l = axes[0, 0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=len(order), bbox_to_anchor=(0.5, 1.0))
    fig.suptitle(f"{m}: realised action per turn (bars shrink when runs stop)", y=1.05, color=INK["primary"])
    fig.tight_layout()
    fig.savefig(fig_path(m, "f1_actions_by_turn"), bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(5.5, 3.2))
    for c in CONDS:
        s = surv[(surv.model == m) & (surv.condition == c)]
        ax.step(s.turn, s.runs_present, where="post", color=COLOR[c], label=f"{c}: runs active")
        ax.step(s.turn, s.agents_acting / 2, where="post", color=COLOR[c], ls=":", lw=1.5)
        ax.text(30.3, s.runs_present.iloc[-1], c, color=INK["secondary"], va="center", fontsize=8)
    mark_kstar(ax)
    ax.set(xlabel="turn", ylabel="runs (of 20)", ylim=(0, 21), xlim=(1, 32),
           title=f"{m}: survival (solid = run active, dotted = acting agents / 2)")
    ax.legend(loc="lower left")
    fig.tight_layout()
    fig.savefig(fig_path(m, "f1_survival"))
    plt.close(fig)
print("figures written")
