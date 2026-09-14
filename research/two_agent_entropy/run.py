#!/usr/bin/env python3
"""Experiment runner: gate -> donor -> full, then analyze.

    cd research/two_agent_entropy
    python3 run.py init   --exp artifacts/two-agent-entropy/exp1
    python3 run.py gate   --exp ... --runs 10              # switch condition, pass = >=50% runs COMPLETE
    python3 run.py donor  --exp ...                        # one donor log per model (placebo source)
    python3 run.py full   --exp ... --runs 20              # base / switch / placebo x models
    python3 run.py analyze --exp ...                       # tables + report.html

Extensions (see harness.RunConfig): ``init`` accepts --switch-range LO,HI (randomised switch turn per seed),
--close-offset K (switch closes again at switch_eff + K), --n-agents 3 (observer A3, E8) and --max-turns;
``full`` accepts the condition ``placebo_inert`` (fact-free foreign entries; uses the donor schedule when a
donor log exists) and --seed-start to place a new matrix in its own seed range.

Runs are resumable: a run directory that already has check.json is skipped.
All phases share one budget ledger (``budget.json``, cap ``--budget``).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

import harness as H
import scenario as S

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXP = REPO_ROOT / "artifacts" / "two-agent-entropy" / "exp1"
_print_lock = threading.Lock()


def say(message: str) -> None:
    with _print_lock:
        print(message, flush=True)


def load_scenarios(exp: Path) -> tuple[S.Scenario, S.Scenario]:
    main, donor = exp / "scenario.json", exp / "donor_scenario.json"
    if not main.exists():
        raise SystemExit(f"no scenario in {exp}; run `run.py init --exp {exp}` first")
    return S.Scenario.load(main), S.Scenario.load(donor)


def cmd_init(args) -> None:
    exp = args.exp
    if (exp / "scenario.json").exists() and not args.force:
        say(f"scenario already exists in {exp} (use --force to regenerate)")
        return
    exp.mkdir(parents=True, exist_ok=True)
    if args.scenario_from:
        # reuse an earlier experiment's scenario (same assets, identifiers and passwords) for comparability
        for name in ("scenario.json", "donor_scenario.json"):
            shutil.copy2(args.scenario_from / name, exp / name)
    else:
        S.generate("schema-brand-v1").save(exp / "scenario.json")
        S.generate("schema-brand-donor-v1").save(exp / "donor_scenario.json")
    (exp / "experiment.json").write_text(json.dumps({
        "config": asdict(H.RunConfig(
            temperature=args.temperature, max_turns=args.max_turns, early_stop_turn=min(args.early_stop_turn, args.max_turns),
            switch_turn=args.switch_turn,
            switch_turn_range=tuple(int(v) for v in args.switch_range.split(",")) if args.switch_range else None,
            close_turn_offset=args.close_offset, n_agents=args.n_agents)),
        "scenario_from": str(args.scenario_from) if args.scenario_from else None,
        "models": {k: m.to_dict() for k, m in H.MODELS.items()},
        "conditions": list(H.CONDITIONS), "prompt_version": H.PROMPT_VERSION,
        "system_prompt": H.SYSTEM_PROMPT, "statement": S.STATEMENT,
    }, indent=1))
    say(f"initialised {exp}")


def run_config(exp: Path) -> H.RunConfig:
    """The RunConfig frozen at init (older experiments without a file fall back to defaults)."""
    path = exp / "experiment.json"
    if not path.exists():
        return H.RunConfig()
    stored = json.loads(path.read_text()).get("config", {})
    return H.RunConfig(**{k: v for k, v in stored.items() if k in H.RunConfig.__dataclass_fields__})


def _models(args) -> list[H.ModelSpec]:
    names = list(H.MODELS) if args.models == "all" else args.models.split(",")
    return [H.MODELS[n] for n in names]


def _execute(jobs: list[dict], args, budget: H.Budget) -> list[dict]:
    api_key = H.load_api_key()
    cfg = run_config(args.exp)
    say(f"  run config: temperature={cfg.temperature} max_turns={cfg.max_turns} switch_turn={cfg.switch_turn} "
        f"switch_turn_range={cfg.switch_turn_range} close_turn_offset={cfg.close_turn_offset} n_agents={cfg.n_agents}")
    results: list[dict] = []
    stop = threading.Event()

    def work(job: dict) -> dict | None:
        out: Path = job["out_dir"]
        if (out / "check.json").exists():
            return {"skipped": True, "check": json.loads((out / "check.json").read_text()),
                    "meta": json.loads((out / "meta.json").read_text()), **job}
        if stop.is_set():
            return None
        if out.exists():
            shutil.rmtree(out)
        try:
            result = H.run_one(api_key=api_key, budget=budget, cfg=cfg, **{k: v for k, v in job.items() if k != "label"})
        except H.BudgetExceeded as exc:
            stop.set()
            say(f"  BUDGET STOP: {exc}")
            return None
        except Exception as exc:  # one broken run must not kill the batch
            say(f"  FAILED {job['label']}: {type(exc).__name__}: {exc}")
            (out / "run_error.txt").write_text(traceback.format_exc())
            return None
        c, m = result["check"], result["meta"]
        say(f"  {job['label']:<42} turns={m['turns_executed']:>2} stop={m['stop_reason']:<26} "
            f"grades={c['completion']} comm={c['verified_directions'] or '-'} "
            f"flags={[f['flag'] for f in c['flags']] or '-'} ${m['cost_usd']:.4f}  (total ${budget.spent:.3f})")
        return {**result, **job}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(work, job) for job in jobs]):
            value = future.result()
            if value:
                results.append(value)
    return results


def _summary(results: list[dict], group_keys=("model", "condition")) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for r in results:
        key = tuple(r["meta"][k] if k != "model" else r["meta"]["model"]["label"] for k in group_keys)
        groups.setdefault(key, []).append(r)
    rows = []
    for key, items in sorted(groups.items()):
        n = len(items)
        rows.append({
            **dict(zip(group_keys, key)), "runs": n,
            "task_success": sum(r["check"]["task_success"] for r in items) / n,
            "communication_verified": sum(r["check"]["communication_verified"] for r in items) / n,
            "complete_via_channel": sum(r["check"]["complete_via_verified_channel"] for r in items) / n,
            "both_complete": sum(r["check"]["n_complete"] >= 2 for r in items) / n,
            "entropy_valid": sum(bool((r["check"].get("logprob_integrity") or {}).get("entropy_valid")) for r in items) / n,
            "invalid": sum(not r["check"]["valid"] for r in items),
            "mean_parse_fail": sum(r["check"]["parse_fail_rate"] for r in items) / n,
            "mean_turns": sum(r["meta"]["turns_executed"] for r in items) / n,
            "cost_usd": round(sum(r["meta"]["cost_usd"] for r in items), 4),
        })
    return rows


def _print_summary(rows: list[dict]) -> None:
    for row in rows:
        say("  " + "  ".join(f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}" for k, v in row.items()))


def cmd_gate(args) -> None:
    sc, _ = load_scenarios(args.exp)
    budget = H.Budget(args.exp / "budget.json", args.budget)
    root = args.exp / "gate" / H.PROMPT_VERSION
    jobs = [{"label": f"gate {m.label} switch s{seed}", "sc": sc, "model": m, "condition": "switch",
             "seed": seed, "phase": f"gate-{H.PROMPT_VERSION}",
             "out_dir": root / m.label / "switch" / f"s{seed:03d}"}
            for m in _models(args) for seed in range(101, 101 + args.runs)]
    say(f"GATE prompt={H.PROMPT_VERSION}: {len(jobs)} runs, budget spent so far ${budget.spent:.3f}")
    rows = _summary(_execute(jobs, args, budget))
    _print_summary(rows)
    verdict = {r["model"]: {"task_success": r["task_success"], "runs": r["runs"],
                            "pass": r["runs"] >= args.runs and r["task_success"] >= 0.5} for r in rows}
    (root / "gate_summary.json").write_text(json.dumps({"rows": rows, "verdict": verdict}, indent=1))
    say(f"GATE verdict: {verdict}")


def cmd_donor(args) -> None:
    _, donor_sc = load_scenarios(args.exp)
    budget = H.Budget(args.exp / "budget.json", args.budget)
    for m in _models(args):
        target = args.exp / "donor" / m.label / "donor_log.json"
        if target.exists():
            say(f"donor for {m.label} exists")
            continue
        for seed in range(901, 904):
            out = args.exp / "donor" / m.label / f"s{seed:03d}"
            result = _execute([{"label": f"donor {m.label} s{seed}", "sc": donor_sc, "model": m,
                                "condition": "switch", "seed": seed, "phase": "donor", "out_dir": out}], args, budget)
            if not result:
                continue
            entries = result[0]["meta"]["log_final"]
            per_agent = {a: sum(1 for e in entries if e["author"] == a) for a in S.AGENTS}
            if all(v >= 2 for v in per_agent.values()):
                target.write_text(json.dumps({"seed": seed, "per_agent": per_agent, "entries": entries}, indent=1))
                say(f"donor for {m.label}: seed {seed}, entries {per_agent}")
                break
            say(f"donor seed {seed} for {m.label} too sparse ({per_agent}); trying next")
        else:
            say(f"WARNING: no usable donor log for {m.label}")


def cmd_full(args) -> None:
    sc, donor_sc = load_scenarios(args.exp)
    budget = H.Budget(args.exp / "budget.json", args.budget)
    jobs = []
    for m in _models(args):
        donor_file = args.exp / "donor" / m.label / "donor_log.json"
        donor_entries = json.loads(donor_file.read_text())["entries"] if donor_file.exists() else None
        for condition in args.conditions.split(","):
            if condition not in H.CONDITIONS:
                raise SystemExit(f"unknown condition {condition!r}; choose from {H.CONDITIONS}")
            if condition == "placebo" and not donor_entries:
                say(f"skip placebo for {m.label}: no donor log (run `donor` first)")
                continue
            if condition == "placebo_inert" and not donor_entries:
                say(f"note: placebo_inert for {m.label} without donor log -> default schedule (one entry per agent every 2 turns)")
            uses_donor = condition in ("placebo", "placebo_inert")
            for seed in range(args.seed_start, args.seed_start + args.runs):
                jobs.append({"label": f"full {m.label} {condition} s{seed}", "sc": sc, "model": m,
                             "condition": condition, "seed": seed, "phase": "full",
                             "donor": donor_sc if uses_donor else None,
                             "donor_entries": donor_entries if uses_donor else None,
                             "out_dir": args.exp / "full" / m.label / condition / f"s{seed:03d}"})
    say(f"FULL: {len(jobs)} runs, budget spent so far ${budget.spent:.3f}")
    rows = _summary(_execute(jobs, args, budget))
    _print_summary(rows)
    (args.exp / "full" / "full_summary.json").write_text(json.dumps(rows, indent=1))


def cmd_analyze(args) -> None:
    import analyze
    analyze.main(args.exp, phase=args.phase)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "gate", "donor", "full", "analyze"):
        p = sub.add_parser(name)
        p.add_argument("--exp", type=Path, default=DEFAULT_EXP)
        p.add_argument("--models", default="all")
        p.add_argument("--runs", type=int, default=10 if name == "gate" else 20)
        p.add_argument("--conditions", default="base,switch,placebo")
        p.add_argument("--workers", type=int, default=8)
        p.add_argument("--budget", type=float, default=10.0)
        p.add_argument("--force", action="store_true")
        p.add_argument("--phase", default="full")
        p.add_argument("--temperature", type=float, default=1.0, help="init only: sampling temperature for every call")
        p.add_argument("--scenario-from", type=Path, default=None, help="init only: copy scenario files from this experiment")
        p.add_argument("--max-turns", type=int, default=30, help="init only")
        p.add_argument("--early-stop-turn", type=int, default=20, help="init only")
        p.add_argument("--switch-turn", type=int, default=8, help="init only: fixed switch turn (ignored if --switch-range)")
        p.add_argument("--switch-range", default=None, help="init only: LO,HI -> switch turn drawn per seed (deterministic)")
        p.add_argument("--close-offset", type=int, default=None, help="init only: read policy closes at switch_eff + K")
        p.add_argument("--n-agents", type=int, default=2, choices=(2, 3), help="init only: 3 adds observer A3 (E8)")
        p.add_argument("--seed-start", type=int, default=1, help="full only: first seed of the matrix")
    args = parser.parse_args()
    args.exp = args.exp.resolve()
    {"init": cmd_init, "gate": cmd_gate, "donor": cmd_donor, "full": cmd_full, "analyze": cmd_analyze}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
