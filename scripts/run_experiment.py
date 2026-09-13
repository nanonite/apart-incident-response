#!/usr/bin/env python3
"""Run the controlled Task 1 harness or an explicitly requested real matrix."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
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


def _matrix_validity(triplets: list[tuple[object, ...]]) -> dict[str, object]:
    """Assess execution integrity separately from task success.

    A run is usable as experimental execution data when every expected agent
    produced a completed result and the controller did not report an error.
    Whether those agents diagnosed, submitted, or passed validation is a
    separate task-outcome metric and must not invalidate the execution trace.
    """

    expected_conditions = ("C0", "C1", "C2")
    assessments: list[dict[str, object]] = []
    for index, triplet in enumerate(triplets):
        conditions = [getattr(run, "condition").value for run in triplet]
        reasons: list[str] = []
        if tuple(conditions) != expected_conditions:
            reasons.append("triplet does not contain exactly one C0, C1, and C2 run")
        for run in triplet:
            condition = getattr(getattr(run, "condition", None), "value", "unknown")
            metrics = getattr(run, "metrics", {})
            artifact_root = getattr(run, "artifact_root", None)
            if not isinstance(artifact_root, Path):
                reasons.append(f"{condition}: missing artifact root")
                continue
            try:
                manifest = json.loads((artifact_root / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                manifest = None
            if not isinstance(manifest, Mapping):
                reasons.append(f"{condition}: run manifest is missing or invalid")
                continue

            factor_assignment = manifest.get("factor_assignment")
            expected_count = factor_assignment.get("agent_count") if isinstance(factor_assignment, Mapping) else None
            if isinstance(expected_count, bool) or not isinstance(expected_count, int) or expected_count < 1:
                reasons.append(f"{condition}: manifest is missing a valid expected agent count")
                continue
            assignments = manifest.get("assignment")
            assigned_ids = [
                item.get("agent_id")
                for item in assignments
                if isinstance(item, Mapping) and isinstance(item.get("agent_id"), str)
            ] if isinstance(assignments, list) else []
            if len(assigned_ids) != expected_count or len(set(assigned_ids)) != expected_count:
                reasons.append(f"{condition}: manifest assignment count does not match expected agent count")

            metrics_count = metrics.get("agent_count") if isinstance(metrics, Mapping) else None
            if metrics_count != expected_count:
                reasons.append(f"{condition}: metrics agent count does not match manifest")

            results = list(getattr(run, "results", ()))
            result_ids = [
                result.get("identity", {}).get("agent_id")
                for result in results
                if isinstance(result, Mapping) and isinstance(result.get("identity"), Mapping)
            ]
            if len(results) != expected_count:
                reasons.append(f"{condition}: {len(results)}/{expected_count} agent results present")
            if len(result_ids) != len(results) or set(result_ids) != set(assigned_ids):
                reasons.append(f"{condition}: agent result identities are missing or unexpected")
            if any(result.get("status") != "completed" for result in results if isinstance(result, Mapping)):
                reasons.append(f"{condition}: raw agent results contain execution failures")

            try:
                results_document = json.loads((artifact_root / "results.json").read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                results_document = None
            if not isinstance(results_document, Mapping):
                reasons.append(f"{condition}: raw results document is missing or invalid")
            else:
                controller_errors = results_document.get("controller_errors")
                if not isinstance(controller_errors, list) or controller_errors:
                    reasons.append(f"{condition}: controller errors are present")
                raw_results = results_document.get("results")
                if not isinstance(raw_results, list) or len(raw_results) != expected_count:
                    reasons.append(f"{condition}: results artifact is missing expected agent results")
            manifest_errors = manifest.get("controller_errors")
            if not isinstance(manifest_errors, list) or manifest_errors:
                reasons.append(f"{condition}: manifest controller errors are present")
        unique_reasons = list(dict.fromkeys(reasons))
        assessments.append({
            "triplet_index": index,
            "conditions": conditions,
            "valid": not unique_reasons,
            "reasons": unique_reasons,
        })
    valid = bool(assessments) and all(bool(item["valid"]) for item in assessments)
    return {
        "valid": valid,
        "experimental_data": valid,
        "data_status": "valid_descriptive_pilot" if valid else "invalid_non_experimental",
        "triplets": assessments,
        "reason": (
            "all expected agent executions completed without controller errors in every condition triplet; task success remains separate"
            if valid
            else "one or more condition triplets have incomplete execution integrity; retain failures but exclude matrix from experimental data"
        ),
    }


def run_real_anchor(output: Path, seeds: tuple[int, ...]) -> dict[str, object]:
    config = RuntimeConfig.from_json(SOURCE_ROOT / "config" / "runtime.json")
    controller = ExperimentController(
        config,
        output,
        extension=SOURCE_ROOT / "pi-extension" / "incident-tools.ts",
        run_class="experimental",
    )
    triplets = controller.run_anchor_matrix(seeds)
    validity = _matrix_validity(triplets)
    result = {
        "schema_version": 1,
        "run_class": "experimental",
        "experimental_data": validity["experimental_data"],
        "data_status": validity["data_status"],
        "claim_scope": (
            "descriptive pilot evidence only"
            if validity["valid"]
            else "non-experimental diagnostic; incomplete agent execution or controller evidence"
        ),
        "validity": validity,
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
    return 0 if not args.real_anchor or result["experimental_data"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
