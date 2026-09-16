"""Pre-registered model shortlist for the T1a discovery gate (subepic #145).

Frozen before any live calls. Changes require a new commit.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelSpec:
    label: str
    slug: str  # OpenRouter model ID
    role: str  # "prior_baseline" | "small_floor" | "strong_free" | "intermediate"
    free: bool
    cost_per_mtok_input: float
    cost_per_mtok_output: float
    rate_limit_rpm: int | None
    notes: str


REGISTRY: dict[str, ModelSpec] = {
    "ling": ModelSpec(
        label="ling",
        slug="inclusionai/ling-3.0-flash-vl:free",
        role="prior_baseline",
        free=True,
        cost_per_mtok_input=0.0,
        cost_per_mtok_output=0.0,
        rate_limit_rpm=20,
        notes="Prior 18-run pilot; all runs were budget/execution failures under old containerised harness",
    ),
    "lfm25": ModelSpec(
        label="lfm25",
        slug="liquid/lfm-2.5-2.6b:free",
        role="small_floor",
        free=True,
        cost_per_mtok_input=0.0,
        cost_per_mtok_output=0.0,
        rate_limit_rpm=20,
        notes="Smallest free model (~2.6B params); solvability floor check",
    ),
    "nemotron": ModelSpec(
        label="nemotron",
        slug="nvidia/nemotron-3-ultra-550b-a55b:free",
        role="strong_free",
        free=True,
        cost_per_mtok_input=0.0,
        cost_per_mtok_output=0.0,
        rate_limit_rpm=20,
        notes="Nemotron 3 Ultra 550B MoE (55B active); capability ceiling reference. "
              "Confirmed available 2026-09-14. Original slug nvidia/llama-3.1-nemotron-ultra-253b-v1:free not found.",
    ),
    "nex": ModelSpec(
        label="nex",
        slug="nex-agi/nex-n2.5-pro:free",
        role="intermediate",
        free=True,
        cost_per_mtok_input=0.0,
        cost_per_mtok_output=0.0,
        rate_limit_rpm=20,
        notes="Nex-N2.5-Pro (free tier); intermediate capability. "
              "Replaces nexusflow/nexus-n2-pro which was not found on 2026-09-14.",
    ),
    "deepseek_flash": ModelSpec(
        label="deepseek_flash",
        slug="deepseek/deepseek-v4.1-flash",
        role="optional_paid",
        free=False,
        cost_per_mtok_input=0.3,
        cost_per_mtok_output=1.2,
        rate_limit_rpm=None,
        notes="DeepSeek V4.1 Flash; optional paid check. Requires separate spend approval.",
    ),
}

# Initial shortlist for the solvability gate (all free).
# nex is included as optional extension; deepseek_flash deferred until paid spend approved.
SELECTED_FOR_GATE: tuple[str, ...] = ("lfm25", "ling", "nemotron")


@dataclass
class SpendCap:
    max_total_usd: float = 0.0
    max_runs_per_model: int = 30
    max_total_runs: int = 90
    stop_on_budget_exhaust: bool = True


DEFAULT_CAP = SpendCap()

# Seeds to use: start with first 2-3 per stratum, extend to 5 max for uncertain strata
INSTANCE_SEEDS: tuple[int, ...] = (1, 2, 3, 4, 5)

# ~0.6 FULL success as screening threshold
SOLVABILITY_HEURISTIC: float = 0.6


def rate_limit_delay(model_key: str) -> float:
    """Return seconds to wait between requests for the given model.

    For models with rate_limit_rpm=20: 20/min = one per 3s, use 3.5 for safety.
    """
    spec = REGISTRY.get(model_key)
    if spec is None:
        return 3.5  # default conservative delay
    rpm = spec.rate_limit_rpm
    if rpm is None:
        return 1.0
    # Convert RPM to seconds per request with 16.7% safety margin
    return round(60.0 / rpm * 1.167, 1)


def estimated_cost(model_key: str, n_runs: int) -> float:
    """Return estimated cost in USD for running n_runs with the given model.

    For free models this is always 0.0. For paid models, estimate based on
    average ~512 prompt tokens and ~64 completion tokens per call, 2 agents.
    """
    spec = REGISTRY.get(model_key)
    if spec is None:
        return 0.0
    if spec.free:
        return 0.0
    # Rough estimate: 512 prompt tokens + 64 completion tokens per agent call, 2 agents
    prompt_tokens_per_run = 512 * 2
    completion_tokens_per_run = 64 * 2
    cost = (
        prompt_tokens_per_run / 1_000_000 * spec.cost_per_mtok_input
        + completion_tokens_per_run / 1_000_000 * spec.cost_per_mtok_output
    ) * n_runs
    return cost


__all__ = [
    "ModelSpec",
    "SpendCap",
    "REGISTRY",
    "SELECTED_FOR_GATE",
    "DEFAULT_CAP",
    "INSTANCE_SEEDS",
    "SOLVABILITY_HEURISTIC",
    "rate_limit_delay",
    "estimated_cost",
]
