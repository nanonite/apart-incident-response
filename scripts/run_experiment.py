#!/usr/bin/env python3
"""Run the controlled Task 1 harness or an explicitly requested real matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT / "src"))

from apart_incident_response.controller import ExperimentController  # noqa: E402
from apart_incident_response.runtime import IsolationPolicy, RuntimeConfig  # noqa: E402


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def run_harness_check(output: Path) -> dict[str, object]:
    """Run only deterministic infrastructure checks with a fake provider."""

    fake = SOURCE_ROOT / "tests" / "fixtures" / "controlled_fake_agent.py"
    config = RuntimeConfig(
        pi_version="fixture",
        model="fixture/controlled-agent",
        launch_command=(sys.executable, str(fake)),
        agent_count=3,
        per_agent_token_budget=40,
        per_agent_tool_call_budget=10,
        aggregate_token_budget=120,
        aggregate_tool_call_budget=30,
        timeout_seconds=10,
        isolation=IsolationPolicy(sandbox="none", allow_unsafe_for_tests=True),
    )
    controller = ExperimentController(
        config,
        output,
        extension=SOURCE_ROOT / "pi-extension" / "incident-tools.ts",
        run_class="harness_check",
    )
    triplets = controller.run_anchor_matrix((1,))
    result = {
        "schema_version": 1,
        "run_class": "harness_check",
        "experimental_data": False,
        "reason": "deterministic fake provider used for lifecycle, access, telemetry, and pairing checks",
        "triplets": [
            {
                "conditions": [run.condition.value for run in triplet],
                "run_ids": [run.run_id for run in triplet],
                "metrics": {run.condition.value: run.metrics for run in triplet},
            }
            for triplet in triplets
        ],
    }
    _write(output / "matrix.json", result)
    return result


def run_real_anchor(output: Path, seeds: tuple[int, ...]) -> dict[str, object]:
    config = RuntimeConfig.from_json(SOURCE_ROOT / "config" / "runtime.json")
    controller = ExperimentController(
        config,
        output,
        extension=SOURCE_ROOT / "pi-extension" / "incident-tools.ts",
        run_class="experimental",
    )
    triplets = controller.run_anchor_matrix(seeds)
    result = {
        "schema_version": 1,
        "run_class": "experimental",
        "experimental_data": True,
        "claim_scope": "descriptive pilot evidence only",
        "triplets": [
            {
                "conditions": [run.condition.value for run in triplet],
                "run_ids": [run.run_id for run in triplet],
                "metrics": {run.condition.value: run.metrics for run in triplet},
            }
            for triplet in triplets
        ],
    }
    _write(output / "matrix.json", result)
    return result


def run_harness_factor_checks(output: Path) -> dict[str, object]:
    """Exercise every predeclared factor path with the fake provider only."""

    fake = SOURCE_ROOT / "tests" / "fixtures" / "controlled_fake_agent.py"
    config = RuntimeConfig(
        pi_version="fixture",
        model="fixture/controlled-agent-tier-1",
        launch_command=(sys.executable, str(fake)),
        agent_count=3,
        per_agent_token_budget=40,
        per_agent_tool_call_budget=10,
        aggregate_token_budget=120,
        aggregate_tool_call_budget=30,
        timeout_seconds=10,
        isolation=IsolationPolicy(sandbox="none", allow_unsafe_for_tests=True),
    )
    controller = ExperimentController(config, output, extension=SOURCE_ROOT / "pi-extension" / "incident-tools.ts", run_class="harness_check")
    factors = {
        "agent_count": (2, 3, 4),
        "capability_profile": ("task-diagnostic-v1", "task-read-submit-v1"),
        "difficulty": ("easy", "anchor", "hard"),
        "transformation_cadence": ("per_turn", "every_2_turns", "every_4_turns"),
        "model": ("configured", "fixture/controlled-agent-tier-2"),
    }
    records = []
    for factor, levels in factors.items():
        triplets = controller.run_factor_pilot(factor, levels, seeds=(1,))
        records.append({
            "factor": factor,
            "levels": list(levels),
            "triplet_count": len(triplets),
            "run_ids": [[run.run_id for run in triplet] for triplet in triplets],
        })
    result = {
        "schema_version": 1,
        "run_class": "harness_check",
        "experimental_data": False,
        "reason": "fake provider exercises all predeclared #66-#71 controller paths; real-model access is a separate gate",
        "factors": records,
    }
    _write(output / "factor-checks.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--harness-check", action="store_true")
    mode.add_argument("--harness-factors", action="store_true")
    mode.add_argument("--real-anchor", action="store_true")
    parser.add_argument("--output", type=Path, default=SOURCE_ROOT / "runs" / "t1")
    parser.add_argument("--seeds", type=int, nargs="+", default=[1])
    args = parser.parse_args()
    if args.harness_check:
        result = run_harness_check(args.output.expanduser().resolve())
    elif args.harness_factors:
        result = run_harness_factor_checks(args.output.expanduser().resolve())
    else:
        result = run_real_anchor(args.output.expanduser().resolve(), tuple(args.seeds))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
