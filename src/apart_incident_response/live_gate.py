"""Explicit budget, capability, and power gates for live validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


PILOT_MODEL = "deepseek/deepseek-v4.1-flash"
PILOT_BUDGET_USD = 20.0


@dataclass(frozen=True)
class LiveGate:
    max_runs: int
    max_cost: float
    require_power_decision: bool = True
    allow_api: bool = False

    def authorize(self, *, estimated_runs: int, estimated_cost: float, power_decision: str | None,
                  provider_capability: bool, stage: str) -> dict[str, Any]:
        reasons: list[str] = []
        if estimated_runs > self.max_runs:
            reasons.append("estimated runs exceed cap")
        if estimated_cost > self.max_cost:
            reasons.append("estimated cost exceeds cap")
        if self.require_power_decision and power_decision not in {"go", "no-go"}:
            reasons.append("explicit budget/power decision is required")
        if power_decision == "no-go":
            reasons.append("power decision is no-go")
        if not provider_capability:
            reasons.append("provider capability smoke test failed")
        if stage == "full_battery" and not self.allow_api:
            reasons.append("full battery API spend is disabled by default")
        return {"authorized": not reasons, "stage": stage, "estimated_runs": estimated_runs,
                "estimated_cost": estimated_cost, "reasons": reasons,
                "next_gate": "explicit_budget_power_approval" if reasons else "bounded_execution"}


def evaluate_capability_smoke(report: Mapping[str, Any], *, require_logprobs: bool = True) -> dict[str, Any]:
    """Convert a smoke report into a gate input without claiming scientific success."""

    rows = list(report.get("rows", ()))
    valid = [row for row in rows if row.get("status") == "valid"]
    logprob_rows = [row for row in valid if row.get("logprob_token_count", 0) > 0]
    complete_rows = [row for row in logprob_rows if row.get("logprob_status") == "complete"]
    if require_logprobs:
        capability = bool(valid) and len(logprob_rows) == len(valid)
    else:
        capability = bool(valid)
    return {
        "provider": report.get("provider"),
        "model": report.get("model"),
        "requests": len(rows),
        "valid": len(valid),
        "logprob_rows": len(logprob_rows),
        "complete_logprob_rows": len(complete_rows),
        "capability_pass": capability,
        "entropy_coverage_pass": bool(valid) and len(complete_rows) == len(valid),
        "scientific_battery_evidence": False,
        "status": "capability_pass" if capability else "capability_incomplete",
    }


def staged_plan() -> list[dict[str, Any]]:
    return [
        {"stage": "offline", "runs": 0, "api_cost": 0, "requirement": "all generators, validators, and fake-provider tests pass"},
        {"stage": "capability_smoke", "runs": 3, "api_cost": 0, "requirement": "provider returns outputs and preserves provenance"},
        {"stage": "bounded_pilot", "runs": 54, "model": PILOT_MODEL, "api_cost_usd": PILOT_BUDGET_USD, "requirement": "one independent instance per family x selected cells, only after smoke gate"},
        {"stage": "full_battery", "runs": 6480, "api_cost": "budget and power gate", "requirement": "explicit go decision; never implicit"},
    ]


__all__ = ["LiveGate", "PILOT_BUDGET_USD", "PILOT_MODEL", "evaluate_capability_smoke", "staged_plan"]
