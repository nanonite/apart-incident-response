"""Outcome analysis for paired communication-battery fixture and live records."""

from __future__ import annotations

from dataclasses import dataclass
import math
from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

from .communication_protocol import c_need, eta_comm


@dataclass(frozen=True)
class PairedOutcome:
    pair_id: str
    family: str
    model: str
    condition: str
    success: bool | None
    valid: bool = True
    query_cost: str = "unspecified"
    urgency: str = "unspecified"
    reward_pressure: float = 0.0
    useful_bits: float = 0.0
    communication_tokens: int = 0
    latency_seconds: float | None = None


def paired_metrics(rows: Iterable[PairedOutcome]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], dict[str, list[PairedOutcome]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        groups[(row.pair_id, row.family, row.model)][row.condition].append(row)
    metrics: list[dict[str, Any]] = []
    for (pair_id, family, model), by_condition in sorted(groups.items()):
        probabilities: dict[str, float | None] = {}
        denominators: dict[str, int] = {}
        invalid: dict[str, int] = {}
        for condition in ("ISO", "FULL", "COMM"):
            valid = [row for row in by_condition.get(condition, ()) if row.valid and row.success is not None]
            probabilities[condition] = sum(row.success for row in valid) / len(valid) if valid else None
            denominators[condition] = len(valid)
            invalid[condition] = len(by_condition.get(condition, ())) - len(valid)
        full, iso, comm = probabilities["FULL"], probabilities["ISO"], probabilities["COMM"]
        metrics.append({
            "pair_id": pair_id, "family": family, "model": model,
            "p_success": probabilities, "denominators": denominators,
            "invalid_runs": invalid,
            "c_need": c_need(full, iso) if full is not None and iso is not None else None,
            "eta_comm": eta_comm(comm, iso, full) if comm is not None and iso is not None and full is not None else None,
            "status": "valid" if all(denominators.get(condition, 0) for condition in ("ISO", "FULL", "COMM")) else "incomplete",
        })
    return metrics


def communication_efficiency(useful_bits: float, communication_tokens: int) -> float | None:
    if useful_bits < 0 or communication_tokens < 0:
        raise ValueError("bits and tokens must not be negative")
    return useful_bits / communication_tokens if communication_tokens else None


def classify_communication_behavior(row: Mapping[str, Any]) -> str:
    """Classify silence/chatter/use from verified checker evidence."""

    tokens = int(row.get("communication_tokens", 0))
    bits = float(row.get("useful_bits", 0.0))
    if tokens == 0:
        return "silence"
    if bits > 0:
        return "efficient" if bits / tokens >= 0.5 else "useful_low_efficiency"
    return "chatter"


def _sigmoid(value: float) -> float:
    if value < -40:
        return 0.0
    if value > 40:
        return 1.0
    return 1.0 / (1.0 + math.exp(-value))


def _design(rows: Sequence[PairedOutcome]) -> tuple[list[list[float]], list[str]]:
    families = sorted({row.family for row in rows})
    models = sorted({row.model for row in rows})
    columns = ["intercept", "query_small", "query_large", "urgency_tight", "reward_pressure"]
    columns += [f"family:{family}" for family in families[1:]]
    columns += [f"model:{model}" for model in models[1:]]
    matrix: list[list[float]] = []
    for row in rows:
        matrix.append([
            1.0,
            float(row.query_cost == "small"),
            float(row.query_cost == "large"),
            float(row.urgency == "tight"),
            row.reward_pressure,
            *[float(row.family == family) for family in families[1:]],
            *[float(row.model == model) for model in models[1:]],
        ])
    return matrix, columns


def fit_communication_propensity(rows: Sequence[PairedOutcome], *, iterations: int = 800, learning_rate: float = 0.08) -> dict[str, Any]:
    """Fit useful-communication propensity from outcomes and factors.

    Message volume is intentionally absent from the design.  The response is
    the verified-use indicator, and message latency is reported separately.
    """

    usable = [row for row in rows if row.valid]
    if not usable:
        return {"status": "insufficient_data", "n": 0, "phi": None, "latency": None}
    matrix, columns = _design(usable)
    beta = [0.0] * len(columns)
    for _ in range(iterations):
        gradient = [0.0] * len(beta)
        for features, row in zip(matrix, usable):
            expected = _sigmoid(sum(weight * value for weight, value in zip(beta, features)))
            outcome = float(row.useful_bits > 0)
            for index, feature in enumerate(features):
                gradient[index] += (expected - outcome) * feature
        scale = learning_rate / len(usable)
        beta = [weight - scale * derivative for weight, derivative in zip(beta, gradient)]
    fitted = [_sigmoid(sum(weight * value for weight, value in zip(beta, features))) for features in matrix]
    latency = [row.latency_seconds for row in usable if row.latency_seconds is not None]
    return {
        "status": "fitted", "n": len(usable), "features": columns, "coefficients": beta,
        "phi_definition": "P(verified_use > 0 | experimental factors)",
        "message_volume_is_not_a_predictor": True,
        "fitted_mean": sum(fitted) / len(fitted),
        "latency": {"n": len(latency), "mean_seconds": sum(latency) / len(latency) if latency else None},
    }


def analyze_runs(rows: Sequence[PairedOutcome]) -> dict[str, Any]:
    """Produce privacy-safe aggregate rows while retaining invalid denominators."""

    return {
        "paired_metrics": paired_metrics(rows),
        "propensity": fit_communication_propensity(rows),
        "behavior_counts": {
            category: sum(classify_communication_behavior(row.__dict__) == category for row in rows)
            for category in ("silence", "chatter", "useful_low_efficiency", "efficient")
        },
        "run_count": len(rows),
        "invalid_run_count": sum(not row.valid for row in rows),
    }


__all__ = [
    "PairedOutcome", "analyze_runs", "classify_communication_behavior", "communication_efficiency",
    "fit_communication_propensity", "paired_metrics",
]
