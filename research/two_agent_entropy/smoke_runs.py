#!/usr/bin/env python3
"""Live smoke test of the extended harness: one gpt-4o-mini run per condition, max_turns=12, budget-capped.

    OPENROUTER_API_KEY=... python3 smoke_runs.py --exp <dir> [--budget 0.20] [--donor-log path/to/donor_log.json]

Runs (all gpt-4o-mini): base | switch (fixed 8) | placebo (donor log) | placebo_inert | switch randomised
(range 4-7) with close offset 3 | three agents (switch fixed 6). Afterwards ``analyze.main`` is executed on the
directory to prove the version-1 tables still build. Prints one line per run and an integrity summary.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import analyze
import harness as H
import scenario as S


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", type=Path, required=True)
    ap.add_argument("--budget", type=float, default=0.20)
    ap.add_argument("--donor-log", type=Path, default=None, help="donor_log.json from run.py donor (placebo source)")
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--max-turns", type=int, default=12)
    args = ap.parse_args()
    exp = args.exp
    exp.mkdir(parents=True, exist_ok=True)
    if not (exp / "scenario.json").exists():
        S.generate("smoke-main").save(exp / "scenario.json")
        S.generate("smoke-donor").save(exp / "donor_scenario.json")
    sc, donor_sc = S.Scenario.load(exp / "scenario.json"), S.Scenario.load(exp / "donor_scenario.json")
    donor_entries = json.loads(args.donor_log.read_text())["entries"] if args.donor_log else None
    model = H.MODELS[args.model]
    api_key = H.load_api_key()
    budget = H.Budget(exp / "budget.json", args.budget)
    T = args.max_turns
    base = dict(max_turns=T, early_stop_turn=T - 2, switch_turn=8)
    jobs = [
        ("base", H.RunConfig(**base), 1),
        ("switch", H.RunConfig(**base), 1),
        ("placebo", H.RunConfig(**base), 1),
        ("placebo_inert", H.RunConfig(**base), 1),
        ("switch", H.RunConfig(**{**base, "switch_turn_range": (4, 7), "close_turn_offset": 3}), 2),
        ("switch", H.RunConfig(**{**base, "switch_turn": 6, "n_agents": 3}), 3),
    ]
    (exp / "experiment.json").write_text(json.dumps({"smoke": True, "jobs": [
        {"condition": c, "seed": s, "config": asdict(cfg)} for c, cfg, s in jobs], "model": model.to_dict()}, indent=1))

    def work(job):
        condition, cfg, seed = job
        out = exp / "full" / model.label / condition / f"s{seed:03d}"
        if (out / "check.json").exists():
            return condition, seed, json.loads((out / "check.json").read_text()), json.loads((out / "meta.json").read_text())
        uses_donor = condition in ("placebo", "placebo_inert")
        if condition == "placebo" and not donor_entries:
            return condition, seed, None, {"error": "no donor log"}
        try:
            r = H.run_one(sc=sc, model=model, condition=condition, seed=seed, cfg=cfg, out_dir=out, phase="full",
                          api_key=api_key, budget=budget, donor=donor_sc if uses_donor else None,
                          donor_entries=donor_entries if uses_donor else None)
        except Exception:  # noqa: BLE001
            (out / "run_error.txt").write_text(traceback.format_exc())
            return condition, seed, None, {"error": traceback.format_exc()[-300:]}
        return condition, seed, r["check"], r["meta"]

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        results = list(pool.map(work, jobs))
    ok = True
    for condition, seed, check, meta in results:
        if check is None:
            ok = False
            print(f"  FAILED {condition} s{seed}: {meta['error']}")
            continue
        gate = check["logprob_integrity"]
        print(f"  {condition:<14} s{seed} n_agents={meta['n_agents']} turns={meta['turns_executed']:>2} calls={meta['calls']:>2} "
              f"api_errors={meta['api_errors']} switch_eff={meta['switch_turn_effective']} closed={meta['switch_closed_turn']} "
              f"grades={check['completion']} comm={check['verified_directions'] or '-'} flags={[f['flag'] for f in check['flags']] or '-'} "
              f"gate: frac_flagged={gate['frac_flagged']} sim={gate['mean_similarity']} entropy_valid={gate['entropy_valid']} "
              f"${meta['cost_usd']:.4f}")
    print(f"budget spent ${budget.spent:.4f} of ${args.budget:.2f}")
    print("analyze:", analyze.main(exp, phase="full"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
