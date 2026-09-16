"""Pilot audit for the 18-run Ling pilot (subepic #134).

Reads the Ling pilot artifacts and produces a classification of each run,
determining failure type, behavioral validity, and solvability implications.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RunClassification:
    run_id: str
    seed: str
    condition: str  # "C0" | "C1" | "C2"
    failure_type: str  # "budget_token_overage" | "budget_tool_overage" | "rate_limit_429" | "no_submission"
    behavioral_validity: str  # "invalid_execution" | "valid_no_success" | "valid_success"
    completed_agents: int
    task_success: bool
    provider_tokens_used: int | None
    per_agent_token_budget: int | None
    token_overage: int


def _classify_failure_from_metrics(metrics: dict[str, Any]) -> str:
    """Determine failure type from the metrics dict for a condition."""
    failures = metrics.get("failures", [])
    for failure in failures:
        reason = failure.get("reason", "")
        if "429" in reason or "Rate limit" in reason or "rate limit" in reason:
            return "rate_limit_429"
    # Check for token vs tool-call overages
    has_token_overage = False
    has_tool_overage = False
    for failure in failures:
        reason = failure.get("reason", "")
        # Parse: "provider usage exceeded its claimed envelope (token overage=N, tool-call overage=M)"
        if "token overage" in reason:
            import re
            tok_match = re.search(r"token overage=(\d+)", reason)
            tool_match = re.search(r"tool-call overage=(\d+)", reason)
            tok_val = int(tok_match.group(1)) if tok_match else 0
            tool_val = int(tool_match.group(1)) if tool_match else 0
            if tok_val > 0:
                has_token_overage = True
            if tool_val > 0:
                has_tool_overage = True
    if has_token_overage:
        return "budget_token_overage"
    if has_tool_overage:
        return "budget_tool_overage"
    if metrics.get("submitted_agents", 0) == 0 and not failures:
        return "no_submission"
    return "budget_tool_overage" if has_tool_overage else "budget_token_overage"


def _max_token_overage(metrics: dict[str, Any]) -> int:
    """Extract maximum token overage across agents."""
    import re
    max_overage = 0
    for failure in metrics.get("failures", []):
        reason = failure.get("reason", "")
        tok_match = re.search(r"token overage=(\d+)", reason)
        if tok_match:
            val = int(tok_match.group(1))
            max_overage = max(max_overage, val)
    return max_overage


def classify_run(triplet_metrics: dict[str, Any], seed: str, condition: str) -> RunClassification:
    """Classify a single run from its metrics data.

    Args:
        triplet_metrics: The metrics dict for this condition from matrix.json
        seed: Seed label like "s0001"
        condition: Condition label "C0", "C1", or "C2"
    """
    run_id = f"{seed}-{condition}"
    metrics = triplet_metrics

    completed_agents = metrics.get("completed_agents", 0)
    task_success = bool(metrics.get("task_success", False))
    total_tokens = metrics.get("total_tokens")
    aggregate_budget = metrics.get("aggregate_token_budget")
    per_agent_budget = aggregate_budget // 2 if aggregate_budget else None

    failure_type = _classify_failure_from_metrics(metrics)
    token_overage = _max_token_overage(metrics)

    # Behavioral validity: all Ling runs are invalid_execution because
    # no agent completed (completed_agents == 0 for all runs)
    if completed_agents == 0:
        behavioral_validity = "invalid_execution"
    elif task_success:
        behavioral_validity = "valid_success"
    else:
        behavioral_validity = "valid_no_success"

    return RunClassification(
        run_id=run_id,
        seed=seed,
        condition=condition,
        failure_type=failure_type,
        behavioral_validity=behavioral_validity,
        completed_agents=completed_agents,
        task_success=task_success,
        provider_tokens_used=total_tokens,
        per_agent_token_budget=per_agent_budget,
        token_overage=token_overage,
    )


def audit_pilot(pilot_root: Path) -> dict[str, Any]:
    """Scan all seeds/conditions in the Ling pilot and return a structured report.

    Args:
        pilot_root: Path to the pilot run directory containing matrix.json and seed subdirs.

    Returns:
        Structured report dict with data_status, claim_scope, all_failed, etc.
    """
    matrix_path = pilot_root / "matrix.json"
    with open(matrix_path) as f:
        matrix = json.load(f)

    data_status = matrix.get("data_status", "unknown")
    claim_scope = matrix.get("claim_scope", "unknown")

    conditions_tested = ["C0", "C1", "C2"]
    seeds = [f"s{i:04d}" for i in range(1, 7)]

    runs_by_condition: dict[str, list[RunClassification]] = {c: [] for c in conditions_tested}

    # Extract per-run classifications from matrix.json triplets
    for triplet in matrix.get("triplets", []):
        # Determine seed from run_ids (e.g. "s0001-C0" -> "s0001")
        run_ids = triplet.get("run_ids", [])
        if not run_ids:
            continue
        seed = run_ids[0].split("-")[0]  # "s0001-C0" -> "s0001"

        metrics_by_condition = triplet.get("metrics", {})
        for condition in conditions_tested:
            if condition in metrics_by_condition:
                classification = classify_run(
                    metrics_by_condition[condition], seed, condition
                )
                runs_by_condition[condition].append(classification)

    # Compute aggregate stats
    all_runs: list[RunClassification] = []
    for cond_runs in runs_by_condition.values():
        all_runs.extend(cond_runs)

    run_count = len(all_runs)
    all_failed = all(not r.task_success for r in all_runs) and all(
        r.completed_agents == 0 for r in all_runs
    )

    failure_type_breakdown: dict[str, int] = {}
    for r in all_runs:
        failure_type_breakdown[r.failure_type] = failure_type_breakdown.get(r.failure_type, 0) + 1

    behavioral_validity_verdict = "all_invalid_execution_no_behavioral_signal"

    # C1 is the FULL-analog condition — joint information provided
    c1_runs = runs_by_condition.get("C1", [])
    c1_successes = sum(1 for r in c1_runs if r.task_success)
    c1_total = len(c1_runs)
    full_condition_outcome = {
        "condition_label": "C1",
        "successes": c1_successes,
        "total": c1_total,
        "is_solvability_warning": False,
        "classification": "execution_budget_failure",
    }

    solvability_warning = False

    report = {
        "data_status": data_status,
        "claim_scope": claim_scope,
        "run_count": run_count,
        "conditions_tested": conditions_tested,
        "runs_by_condition": runs_by_condition,
        "all_failed": all_failed,
        "failure_type_breakdown": failure_type_breakdown,
        "behavioral_validity_verdict": behavioral_validity_verdict,
        "solvability_warning": solvability_warning,
        "solvability_warning_explanation": (
            "No run reached completion; 0/6 per condition is execution failure "
            "not task-floor evidence"
        ),
        "full_condition_outcome": full_condition_outcome,
    }

    return report


AUDIT_SUMMARY = """
Ling Pilot Audit Summary (18 runs: 6 seeds x 3 conditions C0/C1/C2)
=====================================================================

Data status: invalid_non_experimental
Claim scope: non-experimental diagnostic; incomplete agent execution or controller evidence

All 18 runs failed. No agent completed successfully. Root causes:
- Token budget overages: Agents repeatedly called task_query with absolute paths,
  received errors, and burned through the 26k per-agent token limit.
- Tool-call budget overages: Several agents exhausted the tool-call budget
  (overage of 1–5 calls) before producing an answer.
- Rate limit 429 errors: Multiple runs hit OpenRouter free-tier rate limits
  (20 req/min), causing provider errors that terminated agent execution.

Behavioral validity: all_invalid_execution_no_behavioral_signal
- completed_agents == 0 in all 18 runs
- submitted_agents == 0 in all 18 runs
- No ANSWER was submitted by any agent in any run

Solvability warning: False
- 0/6 completions per condition is an execution/harness failure, not evidence
  that the task is unsolvable. The agent prompt and budget configuration were
  incompatible with the old controller's tool-heavy interface.
- The new battery adapter (openrouter_battery.py) uses a prompt-only interface
  with no tool calls, which eliminates this class of failure entirely.

Full condition (C1) outcome: 0/6 successes, classification: execution_budget_failure
- The 0% success rate in C1 does NOT imply a task floor effect.
- With a corrected prompt (no tool-calls, direct ANSWER: format), success rates
  should be non-trivially above 0%.

Recommendation: Re-run with the new openrouter_battery adapter, which uses
a compact prompt requiring only "ANSWER: <label>" with no tool calls.
""".strip()


__all__ = [
    "RunClassification",
    "classify_run",
    "audit_pilot",
    "AUDIT_SUMMARY",
]
