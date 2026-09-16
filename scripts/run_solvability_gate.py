"""FULL-only solvability gate — pre-registered run script.

Pre-registration (recorded before any live calls):
  Models: lfm25, ling (3 seeds/stratum), nemotron (2 seeds/stratum)
  Families: hypothesis, reference
  Complexities: LOW, HIGH
  Regime: N (necessary information — hardest, maximally discriminating for the battery)
  Max runs: 90 total
  Max cost: $0.00 (all free models)
  Rate limit: 3.5s delay between calls within each model (20 RPM cap)
  Stop conditions:
    - Total runs >= 90 → stop
    - Any non-zero estimated cost → abort (should not happen with free models)

Solvability heuristic: ~0.6 FULL success per stratum.
  viable    >= 0.6 success rate with at least 2 valid runs
  floor     == 0.0 with >= 2 valid runs
  uncertain otherwise

Artifacts saved to: runs/discovery-145/solvability_gate/
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "src"))

from apart_incident_response.communication_protocol import DependenceRegime, ReasoningComplexity
from apart_incident_response.model_registry import (
    REGISTRY, SOLVABILITY_HEURISTIC, SpendCap, rate_limit_delay,
)
from apart_incident_response.openrouter_battery import OpenRouterBatteryProvider
from apart_incident_response.solvability_gate import (
    MIN_VALID_RUNS_FOR_VIABLE, SolvabilityGate, StratumResult,
)

FAMILIES = ["hypothesis", "reference"]
COMPLEXITIES = [ReasoningComplexity.LOW, ReasoningComplexity.HIGH]
REGIME = DependenceRegime.N

# nemotron is slow (~70s/call); mini gate with 2 seeds is sufficient given smoke-test pass
MODEL_SEEDS: dict[str, tuple[int, ...]] = {
    "lfm25":    (1, 2, 3),
    "ling":     (1, 2, 3),
    "nemotron": (1, 2),
}

CAP = SpendCap(max_total_usd=0.0, max_runs_per_model=30, max_total_runs=90)
ARTIFACT_DIR = _repo_root / "runs" / "discovery-145" / "solvability_gate"


def provider_factory(model_key: str) -> OpenRouterBatteryProvider:
    spec = REGISTRY[model_key]
    return OpenRouterBatteryProvider(
        spec.slug,
        max_output_tokens=512,
        temperature=0.0,
        rate_limit_delay=rate_limit_delay(model_key),
    )


def run() -> dict:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    print("FULL-only solvability gate — pre-registered parameters")
    print(f"  models:       {list(MODEL_SEEDS.keys())}")
    print(f"  families:     {FAMILIES}")
    print(f"  complexities: {[c.value for c in COMPLEXITIES]}")
    print(f"  regime:       {REGIME.value}")
    print(f"  cap:          max_total_runs={CAP.max_total_runs} max_cost_usd={CAP.max_total_usd}")
    print()

    all_stratum_results: list[StratumResult] = []

    for model_key, seeds in MODEL_SEEDS.items():
        spec = REGISTRY[model_key]
        print(f"=== {model_key}  ({spec.slug})  seeds={seeds} ===")

        gate = SolvabilityGate(
            lambda mk=model_key: provider_factory(mk),
            cap=CAP,
        )

        for family in FAMILIES:
            for complexity in COMPLEXITIES:
                t0 = time.monotonic()
                stratum = gate.screen_stratum(family, complexity, model_key, seeds)
                elapsed = time.monotonic() - t0

                flag = "✓" if stratum.verdict == "viable" else (
                    "✗" if stratum.verdict == "floor" else "?"
                )
                rate_str = f"{stratum.success_rate:.2f}" if stratum.success_rate is not None else "n/a"
                print(f"  {flag} {family}/{complexity.value:6s}  "
                      f"{stratum.n_success}/{stratum.n_valid}  rate={rate_str}  "
                      f"verdict={stratum.verdict}  ({elapsed:.0f}s)")
                all_stratum_results.append(stratum)

        print(f"  runs this model: {gate._total_runs}")
        print()

    # overall verdict
    summary_gate = SolvabilityGate(provider_factory, cap=CAP)
    verdict = summary_gate.gate_verdict(all_stratum_results)

    report = {
        "schema": "solvability-gate-v2",
        "status": "valid_candidate",
        "analysis_eligible": True,
        "minimum_valid_runs_for_viable": MIN_VALID_RUNS_FOR_VIABLE,
        "pre_registration": {
            "models": {k: {"slug": REGISTRY[k].slug, "seeds": list(v)}
                       for k, v in MODEL_SEEDS.items()},
            "families": FAMILIES,
            "complexities": [c.value for c in COMPLEXITIES],
            "regime": REGIME.value,
            "solvability_heuristic": SOLVABILITY_HEURISTIC,
            "cap": {"max_total_usd": CAP.max_total_usd,
                    "max_runs_per_model": CAP.max_runs_per_model,
                    "max_total_runs": CAP.max_total_runs},
        },
        "stratum_results": [
            {
                "family": r.family,
                "complexity": r.complexity.value,
                "model": r.model,
                "verdict": r.verdict,
                "n_run": r.n_run,
                "n_success": r.n_success,
                "n_valid": r.n_valid,
                "success_rate": r.success_rate,
                "ci_lower": r.ci_lower,
                "ci_upper": r.ci_upper,
            }
            for r in all_stratum_results
        ],
        "gate_verdict": verdict,
    }

    report_path = ARTIFACT_DIR / "gate_report.json"
    report_path.write_text(json.dumps(report, indent=2))

    print("═" * 60)
    print(f"Recommendation : {verdict['recommendation']}")
    print(f"Viable strata  : {verdict['viable_count']}")
    print(f"Floor strata   : {verdict['floor_count']}")
    print(f"Uncertain      : {verdict['uncertain_count']}")
    print(f"Report saved   : {report_path}")

    return report


if __name__ == "__main__":
    run()
