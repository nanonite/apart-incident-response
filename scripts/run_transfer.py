"""Transfer selected ISO/FULL/COMM cells to Nemotron (#149).

Pre-registration:
  Transfer model: nemotron (nvidia/nemotron-3-ultra-550b-a55b:free)
  Source: corrected two-turn anchor rows (runs/discovery-145/anchor_screen/rows.turns2.json)
  Selection: all N-regime (necessary information) instances from anchor screen
             — these have the highest C_need and are most informative
  Conditions: ISO, FULL, COMM (matched triplets, same instance IDs as anchor)
  Max runs: up to 96 API calls (8 instances × 3 conditions × 2 agents × 2 turns)
  Max cost: $0.00 (free model)
  Stop conditions: 3 consecutive HTTP errors → abort

Artifacts: runs/discovery-145/transfer/ (turn-1 files are retained as
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
    BatteryCondition, DependenceRegime, ReasoningComplexity,
)
from apart_incident_response.communication_runner import TwoAgentBatteryRunner
from apart_incident_response.model_registry import REGISTRY, rate_limit_delay
from apart_incident_response.openrouter_battery import (
    OpenRouterBatteryProvider, ResumableArtifact, UsageAccumulator,
)
from apart_incident_response.task_families import generate_instance

TRANSFER_MODEL = "nemotron"
ARTIFACT_DIR = _repo_root / "runs" / "discovery-145" / "transfer"
ANCHOR_ROWS_PATH = _repo_root / "runs" / "discovery-145" / "anchor_screen" / "rows.turns2.json"
RUNS_PATH = ARTIFACT_DIR / "runs.turns2.jsonl"
ROWS_PATH = ARTIFACT_DIR / "rows.turns2.json"


def select_transfer_instances(anchor_rows: list[dict]) -> list[dict]:
    """Select N-regime instances from anchor screen for transfer."""
    seen = set()
    selected = []
    for row in anchor_rows:
        if row.get("regime_hint") == "N" and row.get("valid"):
            key = (row["instance_id"], row.get("regime_hint"), row.get("complexity"))
            if key not in seen:
                seen.add(key)
                selected.append({
                    "instance_id": row["instance_id"],
                    "family": row["family"],
                    "seed": row["seed"],
                    "regime_hint": row["regime_hint"],
                    "complexity": row["complexity"],
                })
    return selected


def run() -> dict:
    if not ANCHOR_ROWS_PATH.exists():
        print(f"ERROR: anchor screen rows not found at {ANCHOR_ROWS_PATH}")
        print("Run run_anchor_screen.py first.")
        return {}

    anchor_rows = json.loads(ANCHOR_ROWS_PATH.read_text())
    transfer_instances = select_transfer_instances(anchor_rows)
    print(f"Transfer instances (N-regime from anchor): {len(transfer_instances)}")
    for inst in transfer_instances:
        print(f"  {inst['family']}/{inst['regime_hint']}/{inst['complexity']}/s{inst['seed']}")
    print()

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    spec = REGISTRY[TRANSFER_MODEL]
    artifact = ResumableArtifact(RUNS_PATH)
    usage = UsageAccumulator(cost_per_mtok=spec.cost_per_mtok_input)
    runner = TwoAgentBatteryRunner(token_budget=512, turns=2)

    print(f"Transfer model: {TRANSFER_MODEL} ({spec.slug})")
    print(f"Rate delay: 0.0s (Nemotron is slow; no separate rate limit needed)")
    print()

    all_rows = []
    consecutive_errors = 0

    for inst_spec in transfer_instances:
        regime = DependenceRegime(inst_spec["regime_hint"])
        complexity = ReasoningComplexity(inst_spec["complexity"])
        inst = generate_instance(inst_spec["family"], inst_spec["seed"], regime, complexity)
        pair_id = f"pair-{inst.instance_id}-{regime.value}-{complexity.value}"

        already = [c for c in ("ISO", "FULL", "COMM")
                   if artifact.already_done(pair_id, c)]
        if len(already) == 3:
            print(f"  [skip] {inst_spec['family']}/s{inst_spec['seed']} already done")
            continue

        t_cell = time.monotonic()
        cell_results = []

        for condition in BatteryCondition:
            if artifact.already_done(pair_id, condition.value):
                continue
            provider = OpenRouterBatteryProvider(
                spec.slug, max_output_tokens=512, temperature=0.0,
                rate_limit_delay=0.0,  # nemotron is slow; no artificial delay
            )
            try:
                result = runner.run_condition(inst, condition, provider, pair_id=pair_id)
                consecutive_errors = 0
            except Exception as exc:
                consecutive_errors += 1
                print(f"  ERROR {inst_spec['family']}/s{inst_spec['seed']}/{condition.value}: {exc}")
                if consecutive_errors >= 3:
                    print("  3 consecutive errors — aborting")
                    raise SystemExit(1)
                continue

            artifact.append(result)
            cell_results.append(result)
            u = provider.usage_summary()
            usage.record(u["prompt_tokens"], u["completion_tokens"])

        for r in cell_results:
            ev = r.event_summary or {}
            row = {
                "pair_id": r.pair_id,
                "instance_id": r.instance_id,
                "family": r.family,
                "seed": r.seed,
                "regime_hint": inst_spec["regime_hint"],
                "complexity": inst_spec["complexity"],
                "model": TRANSFER_MODEL,
                "condition": r.condition.value,
                "task_success": r.task_success,
                "valid": r.status == "completed",
                "d_idx": inst.assignment.d_idx,
                "regime_measured": inst.assignment.regime.value if inst.assignment.regime else None,
                "post_read_correlated_bits": float(ev.get("post_read_correlated_bits") or 0.0),
                "communication_tokens": ev.get("communication_tokens", 0),
                "invalid_agents": list(r.invalid_agents),
            }
            all_rows.append(row)

        elapsed = time.monotonic() - t_cell
        successes = {r.condition.value: r.task_success for r in cell_results}
        print(f"  {inst_spec['family']}/{inst_spec['complexity']}/s{inst_spec['seed']}  "
              f"ISO={successes.get('ISO','?')} FULL={successes.get('FULL','?')} "
              f"COMM={successes.get('COMM','?')}  ({elapsed:.0f}s)")

    rows_path = ROWS_PATH
    rows_path.write_text(json.dumps(all_rows, indent=2))

    print()
    u = usage.summary()
    print(f"Calls: {u['calls']}  cost: ${u['estimated_cost_usd']:.4f}")
    print(f"Rows: {len(all_rows)} → {rows_path}")

    return {"rows": all_rows, "usage": u}


if __name__ == "__main__":
    run()
