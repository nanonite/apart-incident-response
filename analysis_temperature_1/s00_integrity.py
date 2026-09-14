"""Step 0: load and integrity checks. Fails loudly on any violated invariant."""
import json

import numpy as np
import pandas as pd

from common import (CONDS, K_STAR, MODELS, Tee, load_calls, load_runs, rng, read_jsonl,
                    run_dir, save_table)

Tee("s00_integrity")
runs = load_runs()
calls = load_calls()
problems = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        problems.append(msg)


print("== runs.csv")
check(len(runs) == 180, f"180 runs (got {len(runs)})")
cell = runs.groupby(["model", "condition"]).seed.agg(["count", "min", "max", "nunique"])
check((cell["count"] == 20).all() and (cell["nunique"] == 20).all(), "20 distinct seeds per model x condition")
check(set(runs.seed) == set(range(1, 21)), "seeds are 1..20")
invalid = runs[~runs["valid"].astype(bool)]
print(f"  invalid runs (kept, flagged): {invalid[['model','condition','seed','flags']].to_dict('records')}")

print("== calls.csv")
per_run = calls.groupby(["model", "condition", "seed"]).size().rename("rows").reset_index()
per_run = per_run.merge(runs[["model", "condition", "seed", "turns_executed"]])
check((per_run.rows == 2 * per_run.turns_executed).all(), "rows per run == 2 x turns_executed")
agents_per_turn = calls.groupby(["model", "condition", "seed", "turn"]).agent.apply(lambda s: tuple(sorted(s)))
check((agents_per_turn == ("A1", "A2")).all(), "each executed turn has exactly A1 and A2")

is_switch_post = (calls.condition == "switch") & (calls.turn >= K_STAR)
check(((calls.read_policy == "all") == is_switch_post).all(), "read_policy=all <=> switch & t>=8")
real = calls.n_real_foreign_returned.fillna(0) > 0
plac = calls.n_placebo_returned.fillna(0) > 0
check(not (real & ~is_switch_post).any(), "n_real_foreign_returned>0 only in switch & t>=8")
check(not (plac & ~((calls.condition == "placebo") & (calls.turn >= K_STAR))).any(),
      "n_placebo_returned>0 only in placebo & t>=8")
check(not (real & (calls.action != "read_log")).any(), "real foreign entries are only returned by read_log")

err = calls[calls.api_error.notna()]
print(f"  API error rows (kept): {len(err)}; by cell:")
print(err.groupby(["model", "condition"]).size().to_string())
check(err.api_error.str.contains("429").all(), "all API errors are HTTP 429")
check((err.action.isna()).all(), "API error rows have no action")
check(not calls.loc[calls.action == "done", "n_tokens"].notna().any(), "done rows carry no tokens")

print("== ordering and roles")
order_rows, role_rows = [], []
for m in MODELS:
    for c in CONDS:
        for s in range(1, 21):
            meta = json.load(open(run_dir(m, c, s) / "meta.json"))
            turns = read_jsonl(run_dir(m, c, s) / "turns.jsonl")
            own = {t["agent"]: t["asset"] for t in turns if t.get("password_source") == "own" and t.get("asset")}
            order_rows.append(dict(model=m, condition=c, seed=s, first=meta["order_within_turn"][0]))
            role_rows.append(dict(model=m, condition=c, seed=s, A1=own.get("A1"), A2=own.get("A2")))
order = pd.DataFrame(order_rows)
roles = pd.DataFrame(role_rows)
check(order.groupby(["model", "seed"])["first"].nunique().eq(1).all(), "within-turn order identical across conditions for a (model, seed)")
check(order.groupby("seed")["first"].nunique().eq(1).all(), "within-turn order depends only on the seed (same across models)")
by_seed = order.drop_duplicates("seed").set_index("seed")["first"]
print(f"  seeds where A1 moves first: {sorted(by_seed[by_seed=='A1'].index.tolist())}")
print(f"  seeds where A2 moves first: {sorted(by_seed[by_seed=='A2'].index.tolist())}")
pos_meta = calls.merge(order, on=["model", "condition", "seed"])
check(((pos_meta.position_in_turn == 0) == (pos_meta.agent == pos_meta["first"])).all(),
      "position_in_turn agrees with meta.order_within_turn")
roles_ok = ((roles.A1.fillna("BRAND_KIT") == "BRAND_KIT") & (roles.A2.fillna("SCHEMA") == "SCHEMA")).all()
check(roles_ok, "asset roles fixed: A1 owns BRAND_KIT, A2 owns SCHEMA (all runs)")
save_table(order.drop_duplicates("seed")[["seed", "first"]].sort_values("seed"), "t0_turn_order_by_seed", md=False)

print("== reconciliation calls.csv vs turns.jsonl / check.json (random sample)")
g = rng(0)
sample = [(m, c, int(s)) for m in MODELS for c in CONDS for s in g.choice(np.arange(1, 21), 2, replace=False)]
mism = []
for m, c, s in sample:
    turns = {(t["turn"], t["agent"]): t for t in read_jsonl(run_dir(m, c, s) / "turns.jsonl")}
    sub = calls[(calls.model == m) & (calls.condition == c) & (calls.seed == s) & (calls.action != "done")
                & calls.action.notna()]
    for r in sub.itertuples():
        t = turns.get((r.turn, r.agent))
        if t is None:
            mism.append((m, c, s, r.turn, r.agent, "missing in turns.jsonl"))
            continue
        e = t.get("entropy") or {}
        if t["action"] != r.action:
            mism.append((m, c, s, r.turn, r.agent, f"action {t['action']} vs {r.action}"))
        if e and not np.isclose(e.get("mean_H_renorm_bits", np.nan), r.mean_H_renorm_bits, rtol=1e-9, atol=1e-12, equal_nan=True):
            mism.append((m, c, s, r.turn, r.agent, "mean_H_renorm"))
        if e and e.get("n_tokens") != r.n_tokens:
            mism.append((m, c, s, r.turn, r.agent, "n_tokens"))
        q = t.get("q_action") or {}
        for k, v in q.items():
            if not np.isclose(v, getattr(r, f"q_{k}"), atol=1e-12):
                mism.append((m, c, s, r.turn, r.agent, f"q_{k}"))
        if r.action == "decrypt" and bool(t.get("decrypt_ok")) != (str(r.decrypt_ok) == "True"):
            mism.append((m, c, s, r.turn, r.agent, "decrypt_ok"))
    chk = json.load(open(run_dir(m, c, s) / "check.json"))
    row = runs[(runs.model == m) & (runs.condition == c) & (runs.seed == s)].iloc[0]
    for d in ("A1->A2", "A2->A1"):
        cd = chk["communication"][d]
        if cd["verdict"] != row[f"{d}_verdict"]:
            mism.append((m, c, s, None, d, "verdict"))
        for k in ("tau_write", "tau_read", "tau_use"):
            a, b = cd[k], row[f"{d}_{k}"]
            if not ((a is None and pd.isna(b)) or (a is not None and a == b)):
                mism.append((m, c, s, None, d, k))
check(not mism, f"{len(sample)} sampled runs reconcile ({len(mism)} mismatches)")
for x in mism[:20]:
    print("    ", x)

print("== exposure")
expo = calls.assign(real=real, plac=plac).groupby(["model", "condition", "agent"]).agg(
    real_reads=("real", "sum"), placebo_reads=("plac", "sum"),
    runs_with_placebo_read=("plac", lambda s: calls.loc[s.index][s].seed.nunique())).reset_index()
print(expo[(expo.real_reads > 0) | (expo.placebo_reads > 0)].to_string(index=False))
save_table(expo, "t0_exposure_by_agent", md=False)

print(f"\n{len(problems)} integrity problem(s)")
if problems:
    raise SystemExit("integrity checks failed: " + "; ".join(problems))
