"""ISO/FULL/COMM anchor screen — pre-registered run script (#136).

Pre-registration (recorded before any live calls):
  Anchor model: ling (inclusionai/ling-3.0-flash-vl:free)
  Families: hypothesis, reference
  Regimes: R (redundant), H (helpful), N (necessary)
  Complexities: LOW, HIGH
  Conditions: ISO, FULL, COMM (matched triplets on same instances)
  Seeds: 101, 102 per cell (independent from solvability-gate seeds 1-3)
  Rate limit: 3.5s between calls (20 RPM cap)
  Turns: 2 (finalizing_agent=A; A reads B's turn-0 message before turn-1 answer)
  Max runs: 288 API calls  (24 instances × 3 conditions × 2 agents × 2 turns)
  Max cost: $0.00 (free model)
  Stop conditions: 3 consecutive HTTP errors → abort

Estimands reported:
  C_need = P(success|FULL) - P(success|ISO)  [unclipped]
  eta_comm = (P(COMM)-P(ISO)) / C_need        [undefined when C_need≈0]
  D_idx (measured feasible-set reduction)
  sum_m DeltaI_m (post-read correlated bits)
  raw R/H/N regime counts

Artifacts: runs/discovery-145/anchor_screen/ (turn-1 files are retained as
protocol-debugging artifacts; the turn-2 rerun uses separate files)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "src"))

from apart_incident_response.communication_protocol import (
    BatteryCondition, DependenceRegime, ReasoningComplexity, c_need, eta_comm,
)
from apart_incident_response.communication_runner import TwoAgentBatteryRunner, BatteryRunResult
from apart_incident_response.model_registry import REGISTRY, rate_limit_delay
from apart_incident_response.openrouter_battery import (
    OpenRouterBatteryProvider, ResumableArtifact, UsageAccumulator,
)
from apart_incident_response.task_families import generate_instance

ANCHOR_MODEL = "ling"
FAMILIES = ["hypothesis", "reference"]
REGIMES = [DependenceRegime.R, DependenceRegime.H, DependenceRegime.N]
COMPLEXITIES = [ReasoningComplexity.LOW, ReasoningComplexity.HIGH]
SEEDS = [101, 102]
ARTIFACT_DIR = _repo_root / "runs" / "discovery-145" / "anchor_screen"
RUNS_PATH = ARTIFACT_DIR / "runs.turns2.jsonl"
ROWS_PATH = ARTIFACT_DIR / "rows.turns2.json"
ANALYSIS_PATH = ARTIFACT_DIR / "analysis.turns2.json"


def run() -> dict:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    spec = REGISTRY[ANCHOR_MODEL]
    artifact = ResumableArtifact(RUNS_PATH)
    usage = UsageAccumulator(cost_per_mtok=spec.cost_per_mtok_input)
    delay = rate_limit_delay(ANCHOR_MODEL)
    runner = TwoAgentBatteryRunner(token_budget=512, turns=2)

    print("ISO/FULL/COMM anchor screen — pre-registered parameters")
    print(f"  model:        {ANCHOR_MODEL} ({spec.slug})")
    print(f"  families:     {FAMILIES}")
    print(f"  regimes:      {[r.value for r in REGIMES]}")
    print(f"  complexities: {[c.value for c in COMPLEXITIES]}")
    print(f"  seeds:        {SEEDS}")
    print(f"  rate_delay:   {delay}s")
    print()

    all_rows: list[dict] = []
    consecutive_errors = 0

    for family in FAMILIES:
        for regime in REGIMES:
            for complexity in COMPLEXITIES:
                for seed in SEEDS:
                    inst = generate_instance(family, seed, regime, complexity)
                    pair_id = f"pair-{inst.instance_id}-{regime.value}-{complexity.value}"

                    # Skip if already done (resumability)
                    already = [c for c in ("ISO", "FULL", "COMM")
                                if artifact.already_done(pair_id, c)]
                    if len(already) == 3:
                        print(f"  [skip] {family}/{regime.value}/{complexity.value}/s{seed} already complete")
                        continue

                    t_cell = time.monotonic()
                    cell_results: list[BatteryRunResult] = []

                    for condition in BatteryCondition:
                        if artifact.already_done(pair_id, condition.value):
                            continue
                        provider = OpenRouterBatteryProvider(
                            spec.slug, max_output_tokens=512, temperature=0.0,
                            rate_limit_delay=delay,
                        )
                        try:
                            result = runner.run_condition(
                                inst, condition, provider, pair_id=pair_id
                            )
                            consecutive_errors = 0
                        except Exception as exc:
                            consecutive_errors += 1
                            print(f"  ERROR {family}/{regime.value}/{complexity.value}/s{seed}/{condition.value}: {exc}")
                            if consecutive_errors >= 3:
                                print("  3 consecutive errors — aborting")
                                raise SystemExit(1)
                            continue

                        artifact.append(result)
                        cell_results.append(result)
                        # track usage
                        u = provider.usage_summary()
                        usage.record(u["prompt_tokens"], u["completion_tokens"])

                    # build row for this instance
                    for r in cell_results:
                        ev = r.event_summary or {}
                        post_read_correlated_bits = float(ev.get("post_read_correlated_bits") or 0.0)
                        row = {
                            "pair_id": r.pair_id,
                            "instance_id": r.instance_id,
                            "family": r.family,
                            "seed": r.seed,
                            "regime_hint": regime.value,
                            "complexity": complexity.value,
                            "model": ANCHOR_MODEL,
                            "condition": r.condition.value,
                            "task_success": r.task_success,
                            "valid": r.status == "completed",
                            "d_idx": inst.assignment.d_idx,
                            "regime_measured": inst.assignment.regime.value if inst.assignment.regime else None,
                            "post_read_correlated_bits": post_read_correlated_bits,
                            "communication_tokens": ev.get("communication_tokens", 0),
                            "invalid_agents": list(r.invalid_agents),
                        }
                        all_rows.append(row)

                    elapsed = time.monotonic() - t_cell
                    successes = {r.condition.value: r.task_success for r in cell_results}
                    print(f"  {family}/{regime.value}/{complexity.value}/s{seed}  "
                          f"ISO={successes.get('ISO','?')} FULL={successes.get('FULL','?')} "
                          f"COMM={successes.get('COMM','?')}  ({elapsed:.0f}s)")

    # save full rows
    rows_path = ROWS_PATH
    rows_path.write_text(json.dumps(all_rows, indent=2))

    # compute analysis
    analysis = _analyze(all_rows)
    analysis_path = ANALYSIS_PATH
    analysis_path.write_text(json.dumps(analysis, indent=2))

    print()
    print("═" * 60)
    u = usage.summary()
    print(f"Total calls:      {u['calls']}")
    print(f"Prompt tokens:    {u['prompt_tokens']}")
    print(f"Completion tokens:{u['completion_tokens']}")
    print(f"Estimated cost:   ${u['estimated_cost_usd']:.4f}")
    print(f"Rows saved:       {len(all_rows)} → {rows_path}")
    print(f"Analysis saved:   {analysis_path}")

    return {"rows": all_rows, "analysis": analysis, "usage": u}


def _analyze(rows: list[dict]) -> dict:
    """Compute per-cell C_need, eta_comm, regime distribution, and correlation bits."""
    from collections import defaultdict
    from apart_incident_response.communication_analysis import wilson_interval

    # group by (family, regime_hint, complexity, seed) → condition → row
    by_cell: dict = defaultdict(dict)
    for row in rows:
        if not row["valid"]:
            continue
        key = (row["family"], row["regime_hint"], row["complexity"], row["seed"])
        by_cell[key][row["condition"]] = row

    cell_metrics = []
    for (family, regime, complexity, seed), conds in sorted(by_cell.items()):
        iso = conds.get("ISO")
        full = conds.get("FULL")
        comm = conds.get("COMM")

        p_iso  = float(iso["task_success"])  if iso  else None
        p_full = float(full["task_success"]) if full else None
        p_comm = float(comm["task_success"]) if comm else None

        cn     = c_need(p_full, p_iso) if p_full is not None and p_iso is not None else None
        ec     = eta_comm(p_comm, p_iso, p_full) if (p_comm is not None and cn is not None) else None
        d      = full["d_idx"] if full else None

        cell_metrics.append({
            "family": family,
            "regime_hint": regime,
            "complexity": complexity,
            "seed": seed,
            "p_iso": p_iso,
            "p_full": p_full,
            "p_comm": p_comm,
            "c_need": cn,
            "eta_comm": ec,
            "d_idx": d,
            "regime_measured": (full or iso or comm or {}).get("regime_measured"),
            "post_read_correlated_bits": (comm or {}).get("post_read_correlated_bits", 0.0),
        })

    # aggregate by (family, regime_hint, complexity)
    agg: dict = defaultdict(lambda: {"iso":[], "full":[], "comm":[], "c_need":[], "post_read_correlated_bits":[]})
    for m in cell_metrics:
        k = (m["family"], m["regime_hint"], m["complexity"])
        if m["p_iso"]  is not None: agg[k]["iso"].append(m["p_iso"])
        if m["p_full"] is not None: agg[k]["full"].append(m["p_full"])
        if m["p_comm"] is not None: agg[k]["comm"].append(m["p_comm"])
        if m["c_need"] is not None: agg[k]["c_need"].append(m["c_need"])
        agg[k]["post_read_correlated_bits"].append(m.get("post_read_correlated_bits", 0.0))

    aggregate_rows = []
    for (family, regime, complexity), vals in sorted(agg.items()):
        n = len(vals["full"])
        p_iso_mean  = sum(vals["iso"])  / len(vals["iso"])  if vals["iso"]  else None
        p_full_mean = sum(vals["full"]) / len(vals["full"]) if vals["full"] else None
        p_comm_mean = sum(vals["comm"]) / len(vals["comm"]) if vals["comm"] else None
        cn_mean = sum(vals["c_need"]) / len(vals["c_need"]) if vals["c_need"] else None
        ec_mean = eta_comm(p_comm_mean, p_iso_mean, p_full_mean) if (
            p_comm_mean is not None and p_iso_mean is not None and p_full_mean is not None
        ) else None
        total_bits = sum(vals["post_read_correlated_bits"])
        aggregate_rows.append({
            "family": family, "regime_hint": regime, "complexity": complexity,
            "n": n,
            "p_iso_mean": p_iso_mean, "p_full_mean": p_full_mean, "p_comm_mean": p_comm_mean,
            "c_need_mean": cn_mean, "eta_comm_mean": ec_mean,
            "total_post_read_correlated_bits": total_bits,
            "ci_iso": wilson_interval(round(sum(vals["iso"])), len(vals["iso"])) if vals["iso"] else None,
            "ci_full": wilson_interval(round(sum(vals["full"])), len(vals["full"])) if vals["full"] else None,
            "ci_comm": wilson_interval(round(sum(vals["comm"])), len(vals["comm"])) if vals["comm"] else None,
        })

    # regime distribution
    regime_counts = defaultdict(int)
    for row in rows:
        r = row.get("regime_measured")
        if r:
            regime_counts[r] += 1

    return {
        "model": ANCHOR_MODEL,
        "analysis_status": "corrected_two_turn_candidate",
        "analysis_eligible": True,
        "turns": 2,
        "cell_metrics": cell_metrics,
        "aggregate_rows": aggregate_rows,
        "regime_counts": dict(regime_counts),
        "total_valid_rows": sum(1 for r in rows if r["valid"]),
        "total_invalid_rows": sum(1 for r in rows if not r["valid"]),
    }


if __name__ == "__main__":
    run()
