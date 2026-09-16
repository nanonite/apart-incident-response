"""FULL-only solvability gate for the T1a multi-model discovery (#147-148).

Runs instances under the FULL condition only (joint information provided,
no board needed) to screen for task/checker/budget floor effects before
spending on paired ISO/COMM runs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from .communication_protocol import BatteryCondition, ReasoningComplexity
from .communication_runner import BatteryProvider, BatteryRunResult, TwoAgentBatteryRunner
from .communication_analysis import wilson_interval
from .model_registry import SpendCap, DEFAULT_CAP
from .task_families import FamilyInstance

MIN_VALID_RUNS_FOR_VIABLE = 2


@dataclass
class FullOnlyResult:
    instance_id: str
    family: str
    seed: int
    model: str
    condition: str = "FULL"  # always FULL
    task_success: bool = False
    valid: bool = True
    parse_ok: bool = False
    answer_submitted: str | None = None
    failure_reason: str | None = None
    provider_tokens: int | None = None
    latency_seconds: float | None = None


@dataclass
class StratumResult:
    family: str
    complexity: ReasoningComplexity
    model: str
    n_run: int
    n_success: int
    n_valid: int
    success_rate: float | None
    ci_lower: float | None
    ci_upper: float | None
    verdict: str  # "viable" | "floor" | "uncertain" | "insufficient"


class SolvabilityGate:
    """FULL-only solvability gate for screening strata before full battery runs."""

    def __init__(
        self,
        provider_factory: Callable[[str], BatteryProvider],
        *,
        runner: TwoAgentBatteryRunner | None = None,
        cap: SpendCap | None = None,
    ) -> None:
        """Initialize the gate.

        Args:
            provider_factory: Callable that takes a model_key and returns a BatteryProvider.
            runner: Optional pre-configured runner; defaults to TwoAgentBatteryRunner().
            cap: Optional spend cap; defaults to DEFAULT_CAP.
        """
        self.provider_factory = provider_factory
        self.runner = runner or TwoAgentBatteryRunner(token_budget=512, turns=1)
        self.cap = cap or DEFAULT_CAP
        self._total_runs: int = 0

    def run_full_only(self, instance: FamilyInstance, model_key: str) -> FullOnlyResult:
        """Run FULL condition only via the runner, extract result."""
        start = time.monotonic()
        provider = self.provider_factory(model_key)
        try:
            result: BatteryRunResult = self.runner.run_condition(
                instance, BatteryCondition.FULL, provider
            )
        except Exception as exc:
            elapsed = time.monotonic() - start
            return FullOnlyResult(
                instance_id=instance.instance_id,
                family=instance.family,
                seed=instance.seed,
                model=model_key,
                condition="FULL",
                task_success=False,
                valid=False,
                parse_ok=False,
                answer_submitted=None,
                failure_reason=f"runner_error:{type(exc).__name__}",
                provider_tokens=None,
                latency_seconds=elapsed,
            )

        elapsed = time.monotonic() - start
        self._total_runs += 1

        # Extract submitted answers
        answers = result.submitted_answers
        # An answer is "submitted" if any agent provided one
        submitted_answer = next(
            (v for v in answers.values() if v is not None), None
        )
        parse_ok = submitted_answer is not None

        valid = result.status == "completed"
        failure_reason = None
        if result.status != "completed":
            failure_reason = f"status:{result.status}"

        # Estimate provider tokens from event summary
        provider_tokens = None
        event_summary = result.event_summary
        if isinstance(event_summary, dict):
            provider_tokens = event_summary.get("total_provider_tokens")

        return FullOnlyResult(
            instance_id=instance.instance_id,
            family=instance.family,
            seed=instance.seed,
            model=model_key,
            condition="FULL",
            task_success=result.task_success,
            valid=valid,
            parse_ok=parse_ok,
            answer_submitted=submitted_answer,
            failure_reason=failure_reason,
            provider_tokens=provider_tokens,
            latency_seconds=elapsed,
        )

    def screen_stratum(
        self,
        family: str,
        complexity: ReasoningComplexity,
        model_key: str,
        seeds: Sequence[int],
        *,
        extend_to: int = 5,
        instance_generator: Callable | None = None,
    ) -> StratumResult:
        """Run 2-3 seeds first, extend if uncertain.

        Args:
            family: Task family name.
            complexity: Reasoning complexity level.
            model_key: Model key from REGISTRY.
            seeds: Sequence of seed integers to use.
            extend_to: Maximum seeds to extend to if uncertain.
            instance_generator: Optional callable(family, seed, regime, complexity)
                                 -> FamilyInstance. Defaults to generate_instance.
        """
        from .task_families import generate_instance
        from .communication_protocol import DependenceRegime

        if instance_generator is None:
            instance_generator = lambda fam, seed: generate_instance(
                fam, seed, DependenceRegime.N, complexity
            )

        results: list[FullOnlyResult] = []
        initial_count = min(3, len(seeds))

        # Run initial 2-3 seeds
        for seed in seeds[:initial_count]:
            if self._total_runs >= self.cap.max_total_runs:
                break
            instance = instance_generator(family, seed)
            r = self.run_full_only(instance, model_key)
            results.append(r)

        # Check if uncertain and extend
        initial_verdict = self._compute_verdict(results)
        if initial_verdict == "uncertain" and len(seeds) > initial_count:
            for seed in seeds[initial_count:extend_to]:
                if self._total_runs >= self.cap.max_total_runs:
                    break
                instance = instance_generator(family, seed)
                r = self.run_full_only(instance, model_key)
                results.append(r)

        return self._build_stratum_result(family, complexity, model_key, results)

    def _compute_verdict(self, results: list[FullOnlyResult]) -> str:
        """Compute preliminary verdict from results so far."""
        n_valid = sum(1 for r in results if r.valid)
        if n_valid < MIN_VALID_RUNS_FOR_VIABLE:
            return "insufficient"
        n_success = sum(1 for r in results if r.valid and r.task_success)
        rate = n_success / n_valid
        if rate >= 0.6:
            return "viable"
        if rate == 0.0 and n_valid >= 2:
            return "floor"
        return "uncertain"

    def _build_stratum_result(
        self,
        family: str,
        complexity: ReasoningComplexity,
        model_key: str,
        results: list[FullOnlyResult],
    ) -> StratumResult:
        n_run = len(results)
        n_valid = sum(1 for r in results if r.valid)
        n_success = sum(1 for r in results if r.valid and r.task_success)

        if n_valid < MIN_VALID_RUNS_FOR_VIABLE:
            success_rate = None
            ci_lower = None
            ci_upper = None
            verdict = "insufficient"
        else:
            success_rate = n_success / n_valid
            interval = wilson_interval(n_success, n_valid)
            ci_lower = interval[0] if interval else None
            ci_upper = interval[1] if interval else None

            if success_rate >= 0.6:
                verdict = "viable"
            elif success_rate == 0.0 and n_valid >= 2:
                verdict = "floor"
            elif n_valid < 3:
                verdict = "uncertain"
            else:
                verdict = "uncertain"

        return StratumResult(
            family=family,
            complexity=complexity,
            model=model_key,
            n_run=n_run,
            n_success=n_success,
            n_valid=n_valid,
            success_rate=success_rate,
            ci_lower=ci_lower,
            ci_upper=ci_upper,
            verdict=verdict,
        )

    def diagnose_floor(self, results: list[FullOnlyResult]) -> dict[str, Any]:
        """Classify low success rate into specific failure modes.

        Categories:
        - "parse_failure": no ANSWER found in output
        - "wrong_candidates": answer not in candidates (hallucinated label)
        - "budget_exceeded": provider tokens > threshold
        - "task_floor": valid parse but always wrong answer
        """
        if not results:
            return {"diagnosis": "no_results", "details": {}}

        n_total = len(results)
        n_parse_failure = sum(1 for r in results if not r.parse_ok)
        n_budget_exceeded = sum(
            1 for r in results
            if r.provider_tokens is not None and r.provider_tokens > 26_000
        )
        n_valid_parse_wrong = sum(
            1 for r in results
            if r.parse_ok and not r.task_success and r.failure_reason is None
        )

        details = {
            "n_total": n_total,
            "n_parse_failure": n_parse_failure,
            "n_budget_exceeded": n_budget_exceeded,
            "n_valid_parse_wrong": n_valid_parse_wrong,
        }

        if n_parse_failure / n_total > 0.5:
            return {"diagnosis": "parse_failure", "details": details}
        if n_budget_exceeded / n_total > 0.5:
            return {"diagnosis": "budget_exceeded", "details": details}
        if n_valid_parse_wrong / n_total > 0.5:
            return {"diagnosis": "task_floor", "details": details}
        # Check for wrong candidates: parse_ok but answer hallucinated
        n_wrong_candidates = sum(
            1 for r in results
            if r.parse_ok and r.answer_submitted is not None
            and r.failure_reason and "no_parseable_answer" in r.failure_reason
        )
        if n_wrong_candidates / n_total > 0.3:
            return {"diagnosis": "wrong_candidates", "details": details}

        return {"diagnosis": "mixed", "details": details}

    def gate_verdict(self, stratum_results: list[StratumResult]) -> dict[str, Any]:
        """Compute overall gate verdict from stratum results.

        Returns:
            Dict with viable_count, floor_count, uncertain_count, insufficient_count,
            and recommendation.
        """
        viable = [r for r in stratum_results if r.verdict == "viable"]
        floor = [r for r in stratum_results if r.verdict == "floor"]
        uncertain = [r for r in stratum_results if r.verdict == "uncertain"]
        insufficient = [r for r in stratum_results if r.verdict == "insufficient"]

        total = len(stratum_results)
        viable_count = len(viable)
        floor_count = len(floor)
        uncertain_count = len(uncertain)

        if total == 0:
            recommendation = "no_data"
        elif insufficient:
            recommendation = "extend_pilot_insufficient_strata"
        elif floor_count == total:
            recommendation = "task_floor_suspected_do_not_proceed"
        elif viable_count > 0 and floor_count == 0:
            recommendation = "proceed_with_full_battery"
        elif viable_count > 0:
            recommendation = "proceed_with_caution_some_floor_strata"
        elif uncertain_count > 0:
            recommendation = "extend_pilot_uncertain_strata"
        else:
            recommendation = "insufficient_data"

        return {
            "viable_count": viable_count,
            "floor_count": floor_count,
            "uncertain_count": uncertain_count,
            "insufficient_count": len(insufficient),
            "total_strata": total,
            "recommendation": recommendation,
            "stratum_verdicts": [
                {
                    "family": r.family,
                    "complexity": r.complexity.value,
                    "model": r.model,
                    "verdict": r.verdict,
                    "success_rate": r.success_rate,
                    "n_run": r.n_run,
                    "n_success": r.n_success,
                }
                for r in stratum_results
            ],
        }


def run_solvability_gate(
    model_keys: Sequence[str],
    families: Sequence[str],
    complexities: Sequence[ReasoningComplexity],
    seeds: Sequence[int],
    provider_factory: Callable[[str], BatteryProvider],
    *,
    artifact_path: Path | None = None,
    cap: SpendCap | None = None,
) -> dict[str, Any]:
    """Top-level function: runs all strata, returns structured report.

    Args:
        model_keys: List of model keys from REGISTRY.
        families: List of task family names.
        complexities: List of ReasoningComplexity levels.
        seeds: Sequence of integer seeds.
        provider_factory: Callable(model_key) -> BatteryProvider.
        artifact_path: Optional path to save resumable JSONL artifact.
        cap: Optional spend cap.

    Returns:
        Structured report with all stratum results and gate verdict.
    """
    from .openrouter_battery import ResumableArtifact

    gate = SolvabilityGate(provider_factory, cap=cap)
    artifact: ResumableArtifact | None = None
    if artifact_path is not None:
        artifact = ResumableArtifact(artifact_path)

    all_stratum_results: list[StratumResult] = []
    all_full_results: list[FullOnlyResult] = []

    for model_key in model_keys:
        for family in families:
            for complexity in complexities:
                stratum = gate.screen_stratum(
                    family, complexity, model_key, seeds
                )
                all_stratum_results.append(stratum)

    verdict = gate.gate_verdict(all_stratum_results)

    return {
        "model_keys": list(model_keys),
        "families": list(families),
        "complexities": [c.value for c in complexities],
        "total_runs": gate._total_runs,
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


__all__ = [
    "FullOnlyResult",
    "MIN_VALID_RUNS_FOR_VIABLE",
    "StratumResult",
    "SolvabilityGate",
    "run_solvability_gate",
]
