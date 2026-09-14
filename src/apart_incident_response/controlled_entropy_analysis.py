"""NumPy analysis for UUID-based two-agent C0/C1/C2 matrices.

The analysis branch that motivated this module used flat CSV tables and a
different ``base/switch/placebo`` protocol.  Current runs retain the same
useful ideas, but their source of truth is the UUID matrix and its condition
artifacts.  This module deliberately keeps loading, validation, estimators,
and inference in plain Python/NumPy so a Marimo notebook can call it without
Pandas or a model runtime.

The probability values are the bounded partial distributions recorded by the
provider.  They are suitable for within-matrix comparisons, but are not
full-vocabulary entropy.  Matrix validation is strict: an incomplete or
three-agent triplet cannot be silently included in a two-agent analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .probability_artifacts import (
    is_complete_probability_artifact,
    replay_partial_entropy,
)
from .run_paths import RunPathError, validate_uuid4


CONDITIONS = ("C0", "C1", "C2")
CONTRASTS = {
    "C1-C0": ("C1", "C0"),
    "C2-C0": ("C2", "C0"),
    "C1-C2": ("C1", "C2"),
}
DEFAULT_BOOTSTRAP_DRAWS = 10_000
DEFAULT_RANDOM_SEED = 20260913


class AnalysisValidationError(ValueError):
    """Raised when an artifact matrix cannot support the requested analysis."""

    def __init__(self, message: str, *, report: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.report = dict(report or {})


@dataclass(frozen=True)
class AgentArtifact:
    agent_id: str
    path: Path
    document: Mapping[str, Any]


@dataclass(frozen=True)
class ConditionRecord:
    root: Path
    condition: str
    seed: int
    run_uuid: str
    model: str
    task_id: str
    agent_ids: tuple[str, ...]
    agents: tuple[AgentArtifact, ...]
    manifest: Mapping[str, Any]
    metrics: Mapping[str, Any]


@dataclass(frozen=True)
class TripletRecord:
    seed: int
    model: str
    run_uuid: str
    conditions: Mapping[str, ConditionRecord]
    matrix_index: int


@dataclass(frozen=True)
class MatrixDataset:
    """A validated, analysis-ready matrix and any rejected diagnostics."""

    matrix_path: Path
    document: Mapping[str, Any]
    model: str
    run_uuid: str
    triplets: tuple[TripletRecord, ...]
    rejected: tuple[Mapping[str, Any], ...] = ()

    @property
    def seeds(self) -> tuple[int, ...]:
        return tuple(triplet.seed for triplet in self.triplets)

    @property
    def condition_count(self) -> int:
        return len(self.triplets) * len(CONDITIONS)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AnalysisValidationError(f"cannot read JSON artifact: {path}") from exc


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _resolve_link(root: Path, value: Any, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise AnalysisValidationError(f"{label} is missing or is not a relative path")
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise AnalysisValidationError(f"{label} escapes the matrix root") from exc
    return candidate


def _condition_root(matrix_root: Path, condition_entry: Mapping[str, Any], condition: str) -> Path:
    index_path = condition_entry.get("index")
    if not isinstance(index_path, str):
        raise AnalysisValidationError(f"{condition}: artifact link has no condition index")
    index = _resolve_link(matrix_root, index_path, label=f"{condition}.index")
    if not index.is_file():
        raise AnalysisValidationError(f"{condition}: condition index is missing: {index}")
    return index.parent


def _agent_probability_path(
    matrix_root: Path,
    condition_root: Path,
    condition_entry: Mapping[str, Any],
    agent_id: str,
) -> Path:
    links = condition_entry.get("probability_artifacts")
    linked = links.get(agent_id) if isinstance(links, Mapping) else None
    if linked is None:
        return condition_root / "agents" / agent_id / "artifacts" / "probability_artifacts.json"
    return _resolve_link(matrix_root, linked, label=f"{agent_id}.probability_artifacts")


def _load_condition(
    matrix_root: Path,
    condition: str,
    condition_entry: Mapping[str, Any],
    *,
    expected_agent_count: int,
) -> ConditionRecord:
    root = _condition_root(matrix_root, condition_entry, condition)
    manifest_value = _read_json(root / "manifest.json")
    if not isinstance(manifest_value, Mapping):
        raise AnalysisValidationError(f"{condition}: manifest is not an object")
    manifest = dict(manifest_value)

    if manifest.get("condition") != condition:
        raise AnalysisValidationError(
            f"{condition}: manifest condition is {manifest.get('condition')!r}"
        )
    seed = manifest.get("seed")
    if not _is_int(seed):
        raise AnalysisValidationError(f"{condition}: manifest seed is missing or invalid")
    run_uuid = manifest.get("run_uuid")
    if not isinstance(run_uuid, str) or not run_uuid:
        raise AnalysisValidationError(f"{condition}: manifest run_uuid is missing")
    model = manifest.get("model")
    factor_assignment = manifest.get("factor_assignment")
    if isinstance(factor_assignment, Mapping):
        model = factor_assignment.get("model", model)
        assigned_count = factor_assignment.get("agent_count")
    else:
        assigned_count = None
    if not isinstance(model, str) or not model:
        raise AnalysisValidationError(f"{condition}: model identity is missing")
    if assigned_count != expected_agent_count:
        raise AnalysisValidationError(
            f"{condition}: expected exactly {expected_agent_count} assigned agents, "
            f"found {assigned_count!r}"
        )

    assignments = manifest.get("assignment")
    assigned_ids = [
        item.get("agent_id")
        for item in assignments
        if isinstance(item, Mapping) and isinstance(item.get("agent_id"), str)
    ] if isinstance(assignments, list) else []
    if len(assigned_ids) != expected_agent_count or len(set(assigned_ids)) != expected_agent_count:
        raise AnalysisValidationError(
            f"{condition}: manifest assignment is not exactly {expected_agent_count} agents"
        )

    agents_root = root / "agents"
    present_ids = sorted(
        path.name for path in agents_root.iterdir()
        if agents_root.is_dir() and path.is_dir()
    ) if agents_root.is_dir() else []
    if tuple(present_ids) != tuple(sorted(assigned_ids)):
        raise AnalysisValidationError(
            f"{condition}: agent artifact directories {present_ids!r} do not match "
            f"the assigned two-agent set {sorted(assigned_ids)!r}"
        )

    results_document = _read_json(root / "results.json")
    results = results_document.get("results") if isinstance(results_document, Mapping) else None
    if not isinstance(results, list):
        raise AnalysisValidationError(f"{condition}: results.json has no results array")
    if len(results) != expected_agent_count:
        raise AnalysisValidationError(
            f"{condition}: results.json contains {len(results)} results, expected "
            f"exactly {expected_agent_count}"
        )
    result_by_agent = {
        item.get("identity", {}).get("agent_id"): item
        for item in results
        if isinstance(item, Mapping) and isinstance(item.get("identity"), Mapping)
    }
    for agent_id in assigned_ids:
        result = result_by_agent.get(agent_id)
        if not isinstance(result, Mapping):
            raise AnalysisValidationError(f"{condition}: result missing for {agent_id}")
        if result.get("status") != "completed":
            raise AnalysisValidationError(
                f"{condition}: {agent_id} result status is {result.get('status')!r}"
            )

    agents: list[AgentArtifact] = []
    for agent_id in sorted(assigned_ids):
        artifact_path = _agent_probability_path(
            matrix_root, root, condition_entry, agent_id
        )
        if not artifact_path.is_file():
            raise AnalysisValidationError(
                f"{condition}: probability artifact missing for {agent_id}"
            )
        artifact = _read_json(artifact_path)
        if not is_complete_probability_artifact(artifact):
            raise AnalysisValidationError(
                f"{condition}: probability artifact for {agent_id} is incomplete or unavailable"
            )
        agents.append(AgentArtifact(agent_id, artifact_path, artifact))

    metrics_value = _read_json(root / "artifacts" / "metrics.json")
    metrics = dict(metrics_value) if isinstance(metrics_value, Mapping) else {}
    task = manifest.get("task")
    task_id = task.get("task_id") if isinstance(task, Mapping) else "unknown"
    if not isinstance(task_id, str):
        task_id = "unknown"
    return ConditionRecord(
        root=root,
        condition=condition,
        seed=seed,
        run_uuid=run_uuid,
        model=model,
        task_id=task_id,
        agent_ids=tuple(sorted(assigned_ids)),
        agents=tuple(agents),
        manifest=manifest,
        metrics=metrics,
    )


def _load_triplet(
    matrix_root: Path,
    entry: Any,
    index: int,
    *,
    expected_agent_count: int,
) -> TripletRecord:
    if not isinstance(entry, Mapping):
        raise AnalysisValidationError(f"triplet {index}: entry is not an object")
    declared_conditions = entry.get("conditions")
    if declared_conditions is not None and (
        not isinstance(declared_conditions, (list, tuple))
        or tuple(declared_conditions) != CONDITIONS
    ):
        raise AnalysisValidationError(
            f"triplet {index}: declared conditions must be ordered C0, C1, C2"
        )
    artifacts = entry.get("artifacts")
    condition_entries = artifacts.get("conditions") if isinstance(artifacts, Mapping) else None
    if not isinstance(condition_entries, Mapping) or set(condition_entries) != set(CONDITIONS):
        raise AnalysisValidationError(
            f"triplet {index}: must contain exactly C0, C1, and C2 artifact links"
        )
    conditions: dict[str, ConditionRecord] = {}
    for condition in CONDITIONS:
        condition_entry = condition_entries[condition]
        if not isinstance(condition_entry, Mapping):
            raise AnalysisValidationError(f"triplet {index} {condition}: link is not an object")
        conditions[condition] = _load_condition(
            matrix_root,
            condition,
            condition_entry,
            expected_agent_count=expected_agent_count,
        )

    first = conditions[CONDITIONS[0]]
    for condition in CONDITIONS[1:]:
        current = conditions[condition]
        if current.seed != first.seed:
            raise AnalysisValidationError(
                f"triplet {index}: condition seeds do not match ({first.seed} vs {current.seed})"
            )
        if current.run_uuid != first.run_uuid:
            raise AnalysisValidationError(f"triplet {index}: condition UUIDs do not match")
        if current.model != first.model:
            raise AnalysisValidationError(f"triplet {index}: condition model identities do not match")
        if current.task_id != first.task_id:
            raise AnalysisValidationError(f"triplet {index}: condition task identities do not match")
        if current.agent_ids != first.agent_ids:
            raise AnalysisValidationError(f"triplet {index}: condition agent assignments do not match")
    return TripletRecord(first.seed, first.model, first.run_uuid, conditions, index)


def load_matrix(
    matrix_path: Path | str,
    *,
    expected_agent_count: int = 2,
    require_experimental: bool = True,
    require_complete: bool = True,
) -> MatrixDataset:
    """Load and validate a UUID matrix for a two-agent entropy analysis.

    ``require_complete=True`` is the default because accepting the valid
    subset of a partially executed matrix changes the declared seed design.
    Set it to ``False`` only to inspect the valid triplets while developing a
    run; the rejected entries remain available in ``dataset.rejected``.
    """

    path = Path(matrix_path).expanduser().resolve()
    if path.is_dir():
        path = path / "matrix.json"
    document_value = _read_json(path)
    if not isinstance(document_value, Mapping):
        raise AnalysisValidationError(f"matrix is not a JSON object: {path}")
    document = dict(document_value)
    if document.get("run_class") != "experimental":
        raise AnalysisValidationError("analysis input must have run_class=experimental")
    if require_experimental and document.get("experimental_data") is not True:
        raise AnalysisValidationError(
            "analysis input is not marked experimental_data=true; retain it as diagnostics"
        )
    if not _is_int(expected_agent_count) or expected_agent_count < 2:
        raise AnalysisValidationError("expected_agent_count must be an integer >= 2")

    matrix_root = path.parent
    matrix_uuid = document.get("run_uuid")
    run_metadata = _read_json(matrix_root / "run.json") if (matrix_root / "run.json").is_file() else {}
    if not isinstance(matrix_uuid, str):
        matrix_uuid = run_metadata.get("run_uuid") if isinstance(run_metadata, Mapping) else None
    if not isinstance(matrix_uuid, str) or not matrix_uuid:
        raise AnalysisValidationError("matrix invocation UUID is missing")
    try:
        matrix_uuid = validate_uuid4(matrix_uuid)
    except RunPathError as exc:
        raise AnalysisValidationError("matrix invocation UUID is not a UUID v4") from exc
    model = document.get("model")
    if not isinstance(model, str) or not model:
        model = run_metadata.get("model") if isinstance(run_metadata, Mapping) else None
    if not isinstance(model, str) or not model:
        model = None

    entries = document.get("triplets")
    if not isinstance(entries, list) or not entries:
        raise AnalysisValidationError("matrix has no triplets")
    triplets: list[TripletRecord] = []
    rejected: list[Mapping[str, Any]] = []
    for index, entry in enumerate(entries):
        try:
            triplet = _load_triplet(
                matrix_root,
                entry,
                index,
                expected_agent_count=expected_agent_count,
            )
        except AnalysisValidationError as exc:
            rejected.append({"triplet_index": index, "reason": str(exc)})
            continue
        if triplet.run_uuid != matrix_uuid:
            rejected.append({"triplet_index": index, "reason": "triplet UUID does not match matrix UUID"})
            continue
        if model is not None and triplet.model != model:
            rejected.append({"triplet_index": index, "reason": "triplet model does not match matrix model"})
            continue
        model = model or triplet.model
        triplets.append(triplet)

    seen_seeds: set[int] = set()
    unique_triplets: list[TripletRecord] = []
    for triplet in triplets:
        if triplet.seed in seen_seeds:
            rejected.append({
                "triplet_index": triplet.matrix_index,
                "reason": f"duplicate matched seed {triplet.seed}",
            })
            continue
        seen_seeds.add(triplet.seed)
        unique_triplets.append(triplet)
    triplets = unique_triplets

    if not triplets:
        detail = f"; first rejection: {rejected[0]['reason']}" if rejected else ""
        raise AnalysisValidationError(
            "matrix has no complete two-agent C0/C1/C2 triplets" + detail,
            report={"rejected": rejected},
        )
    if rejected and require_complete:
        raise AnalysisValidationError(
            f"matrix contains {len(rejected)} rejected triplet(s); complete matrices are required",
            report={"rejected": rejected, "accepted_seeds": [item.seed for item in triplets]},
        )
    assert model is not None
    return MatrixDataset(path, document, model, matrix_uuid, tuple(triplets), tuple(rejected))


def discover_matrices(runs_root: Path | str) -> tuple[Path, ...]:
    """Return candidate matrix indexes without interpreting their contents."""

    root = Path(runs_root).expanduser().resolve()
    return tuple(sorted(path for path in root.glob("**/matrix.json") if path.is_file()))


def _token_entropy(token: Mapping[str, Any], field: str) -> float:
    entropy = token.get("entropy")
    value = entropy.get(field) if isinstance(entropy, Mapping) else None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        return float("nan")
    return float(value)


def _token_covered_mass(token: Mapping[str, Any]) -> float:
    values = [token.get("sampled_probability")]
    alternatives = token.get("top_alternatives", [])
    if not isinstance(alternatives, list):
        return float("nan")
    values.extend(
        alternative.get("probability")
        for alternative in alternatives
        if isinstance(alternative, Mapping)
    )
    if not values or any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        for value in values
    ):
        return float("nan")
    return float(np.sum(np.asarray(values, dtype=float)))


def _mean(values: Iterable[float]) -> float:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    return float(np.mean(finite)) if finite else float("nan")


def token_rows(dataset: MatrixDataset) -> list[dict[str, Any]]:
    """Flatten stored token probabilities into analysis rows."""

    rows: list[dict[str, Any]] = []
    for triplet in dataset.triplets:
        for condition, run in triplet.conditions.items():
            for agent in run.agents:
                turns = agent.document.get("turns", [])
                for turn_number, turn in enumerate(turns, start=1):
                    probability = turn.get("probability_artifact") if isinstance(turn, Mapping) else None
                    tokens = probability.get("tokens", []) if isinstance(probability, Mapping) else []
                    for position, token in enumerate(tokens):
                        if not isinstance(token, Mapping):
                            continue
                        rows.append({
                            "model": run.model,
                            "run_uuid": run.run_uuid,
                            "seed": run.seed,
                            "condition": condition,
                            "agent": agent.agent_id,
                            "turn": turn_number,
                            "source_sequence": turn.get("source_sequence"),
                            "kind": turn.get("kind", "unknown"),
                            "position": position,
                            "sampled_token": token.get("sampled_token"),
                            "sampled_surprise_bits": _token_entropy(token, "sampled_surprise_bits"),
                            "partial_entropy_bits": _token_entropy(token, "partial_entropy_bits"),
                            "top_k_entropy_bits": _token_entropy(token, "top_k_entropy_bits"),
                            "residual_bucket_entropy_bits": _token_entropy(token, "residual_bucket_entropy_bits"),
                            "covered_mass": float(token.get("covered_mass", float("nan"))),
                        })
    return rows


def call_rows(dataset: MatrixDataset) -> list[dict[str, Any]]:
    """Summarize one probability artifact turn as one statistical observation."""

    rows: list[dict[str, Any]] = []
    for triplet in dataset.triplets:
        for condition, run in triplet.conditions.items():
            for agent in run.agents:
                turns = agent.document.get("turns", [])
                for turn_number, turn in enumerate(turns, start=1):
                    probability = turn.get("probability_artifact") if isinstance(turn, Mapping) else None
                    tokens = probability.get("tokens", []) if isinstance(probability, Mapping) else []
                    if not isinstance(tokens, list) or not tokens:
                        continue
                    rows.append({
                        "model": run.model,
                        "run_uuid": run.run_uuid,
                        "seed": run.seed,
                        "condition": condition,
                        "agent": agent.agent_id,
                        "turn": turn_number,
                        "source_sequence": turn.get("source_sequence"),
                        "kind": turn.get("kind", "unknown"),
                        "token_count": len(tokens),
                        "mean_entropy_bits": _mean(_token_entropy(t, "partial_entropy_bits") for t in tokens if isinstance(t, Mapping)),
                        "mean_surprise_bits": _mean(_token_entropy(t, "sampled_surprise_bits") for t in tokens if isinstance(t, Mapping)),
                        "mean_coverage": _mean(
                            float(t.get("covered_mass", float("nan")))
                            for t in tokens if isinstance(t, Mapping)
                        ),
                    })
    return rows


def replay_validation(dataset: MatrixDataset, *, tolerance: float = 1e-9) -> list[dict[str, Any]]:
    """Compare every stored token entropy with a fresh replay of its artifact."""

    rows: list[dict[str, Any]] = []
    for triplet in dataset.triplets:
        for condition, run in triplet.conditions.items():
            for agent in run.agents:
                artifact = agent.document
                try:
                    replay = []
                    for turn in artifact.get("turns", []):
                        replayed = replay_partial_entropy(turn["probability_artifact"])
                        replay.append(replayed)
                    entropy_errors: list[float] = []
                    coverage_errors: list[float] = []
                    compared = 0
                    for turn, replayed in zip(artifact.get("turns", []), replay):
                        stored_tokens = turn["probability_artifact"].get("tokens", [])
                        replayed_tokens = replayed.get("tokens", [])
                        for stored, computed in zip(stored_tokens, replayed_tokens):
                            stored_entropy = _token_entropy(stored, "partial_entropy_bits")
                            computed_entropy = computed.get("partial_entropy_bits", float("nan"))
                            if math.isfinite(stored_entropy) and math.isfinite(float(computed_entropy)):
                                compared += 1
                                entropy_errors.append(abs(stored_entropy - float(computed_entropy)))
                            stored_coverage = stored.get("covered_mass")
                            computed_coverage = _token_covered_mass(stored)
                            if (
                                isinstance(stored_coverage, (int, float))
                                and not isinstance(stored_coverage, bool)
                                and math.isfinite(float(stored_coverage))
                                and math.isfinite(computed_coverage)
                            ):
                                coverage_errors.append(abs(float(stored_coverage) - computed_coverage))
                    max_error = max(entropy_errors) if entropy_errors else float("nan")
                    max_coverage_error = max(coverage_errors) if coverage_errors else float("nan")
                    rows.append({
                        "model": run.model,
                        "seed": run.seed,
                        "condition": condition,
                        "agent": agent.agent_id,
                        "tokens_compared": compared,
                        "max_abs_error_bits": max_error,
                        "max_abs_coverage_error": max_coverage_error,
                        "valid": bool(entropy_errors) and bool(coverage_errors)
                        and max_error <= tolerance
                        and max_coverage_error <= tolerance,
                    })
                except (KeyError, TypeError, ValueError) as exc:
                    rows.append({
                        "model": run.model,
                        "seed": run.seed,
                        "condition": condition,
                        "agent": agent.agent_id,
                        "tokens_compared": 0,
                        "max_abs_error_bits": float("nan"),
                        "max_abs_coverage_error": float("nan"),
                        "valid": False,
                        "error": str(exc),
                    })
    return rows


def entropy_bits(probabilities: Sequence[float]) -> float:
    """Shannon entropy in bits for a finite normalized vector."""

    values = np.asarray(probabilities, dtype=float)
    if values.ndim != 1 or values.size == 0 or not np.isfinite(values).all():
        raise ValueError("entropy requires a non-empty finite vector")
    if (values < 0).any() or not math.isclose(float(values.sum()), 1.0, abs_tol=1e-8):
        raise ValueError("entropy requires a normalized probability vector")
    positive = values[values > 0]
    return float(-np.sum(positive * np.log2(positive)))


def bootstrap_ci(
    values: Sequence[float],
    *,
    draws: int = DEFAULT_BOOTSTRAP_DRAWS,
    seed: int = DEFAULT_RANDOM_SEED,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """Percentile bootstrap over independent matched seeds."""

    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return float("nan"), float("nan"), float("nan")
    if not _is_int(draws) or draws < 1:
        raise ValueError("draws must be a positive integer")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between zero and one")
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, x.size, size=(draws, x.size))
    estimates = x[indices].mean(axis=1)
    return (
        float(x.mean()),
        float(np.quantile(estimates, alpha / 2)),
        float(np.quantile(estimates, 1 - alpha / 2)),
    )


def sign_test_pvalue(values: Sequence[float]) -> float:
    """Two-sided exact sign-test p-value, ignoring zero differences."""

    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x) & (x != 0)]
    n = int(x.size)
    if n == 0:
        return float("nan")
    positives = int((x > 0).sum())
    lower = sum(math.comb(n, k) for k in range(positives + 1)) / (2**n)
    upper = sum(math.comb(n, k) for k in range(positives, n + 1)) / (2**n)
    return float(min(1.0, 2 * min(lower, upper)))


def _average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    sorted_values = values[order]
    ranks = np.empty(values.size, dtype=float)
    start = 0
    while start < values.size:
        end = start + 1
        while end < values.size and sorted_values[end] == sorted_values[start]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2
        start = end
    return ranks


def wilcoxon_signed_rank_pvalue(values: Sequence[float]) -> float:
    """Two-sided paired signed-rank p-value without a SciPy dependency."""

    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x) & (x != 0)]
    n = int(x.size)
    if n == 0:
        return float("nan")
    ranks = _average_ranks(np.abs(x))
    observed = float(ranks[x > 0].sum())
    total = float(ranks.sum())
    if n <= 20:
        counts = 0
        extreme = abs(2 * observed - total) - 1e-12
        for mask in range(1 << n):
            signed = sum(ranks[i] for i in range(n) if mask & (1 << i))
            if abs(2 * signed - total) >= extreme:
                counts += 1
        return float(counts / (1 << n))
    tie_counts = [int((np.abs(x) == value).sum()) for value in np.unique(np.abs(x))]
    variance = n * (n + 1) * (2 * n + 1) / 24
    variance -= sum(count**3 - count for count in tie_counts) / 48
    if variance <= 0:
        return 1.0
    z = (abs(observed - total / 2) - 0.5) / math.sqrt(variance)
    return float(math.erfc(max(0.0, z) / math.sqrt(2)))


def benjamini_hochberg(pvalues: Sequence[float]) -> np.ndarray:
    """Adjust a p-value family while preserving NaN positions."""

    p = np.asarray(pvalues, dtype=float)
    result = np.full(p.shape, np.nan, dtype=float)
    valid = np.isfinite(p)
    if not valid.any():
        return result
    values = p[valid]
    order = np.argsort(values)
    adjusted_sorted = values[order] * values.size / np.arange(1, values.size + 1)
    adjusted_sorted = np.minimum.accumulate(adjusted_sorted[::-1])[::-1]
    adjusted = np.empty(values.size, dtype=float)
    adjusted[order] = np.clip(adjusted_sorted, 0, 1)
    result[valid] = adjusted
    return result


def _seed_condition_means(
    rows: Sequence[Mapping[str, Any]],
    *,
    metric: str,
    turn_start: int | None,
    turn_stop: int | None,
) -> dict[tuple[int, str], float]:
    by_agent: dict[tuple[int, str, str], list[float]] = {}
    for row in rows:
        turn = row.get("turn")
        if not _is_int(turn) or (turn_start is not None and turn < turn_start) or (turn_stop is not None and turn > turn_stop):
            continue
        value = row.get(metric)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
            continue
        key = (int(row["seed"]), str(row["condition"]), str(row["agent"]))
        by_agent.setdefault(key, []).append(float(value))
    by_condition: dict[tuple[int, str], list[float]] = {}
    for (seed, condition, _agent), values in by_agent.items():
        by_condition.setdefault((seed, condition), []).append(float(np.mean(values)))
    return {key: float(np.mean(values)) for key, values in by_condition.items() if values}


def paired_condition_contrasts(
    dataset: MatrixDataset,
    *,
    metric: str = "mean_entropy_bits",
    turn_start: int | None = None,
    turn_stop: int | None = None,
    draws: int = DEFAULT_BOOTSTRAP_DRAWS,
    seed: int = DEFAULT_RANDOM_SEED,
) -> list[dict[str, Any]]:
    """Estimate matched C0/C1/C2 contrasts with seeds as the unit."""

    rows = call_rows(dataset)
    values = _seed_condition_means(
        rows, metric=metric, turn_start=turn_start, turn_stop=turn_stop
    )
    output: list[dict[str, Any]] = []
    for offset, (name, (right, left)) in enumerate(CONTRASTS.items()):
        differences = [
            values[(triplet.seed, right)] - values[(triplet.seed, left)]
            for triplet in dataset.triplets
            if (triplet.seed, right) in values and (triplet.seed, left) in values
        ]
        estimate, low, high = bootstrap_ci(differences, draws=draws, seed=seed + offset)
        finite = np.asarray(differences, dtype=float)
        output.append({
            "model": dataset.model,
            "metric": metric,
            "contrast": name,
            "turn_start": turn_start,
            "turn_stop": turn_stop,
            "n_seeds": int(finite.size),
            "seeds": [triplet.seed for triplet in dataset.triplets if (triplet.seed, right) in values and (triplet.seed, left) in values],
            "estimate": estimate,
            "ci_low": low,
            "ci_high": high,
            "median": float(np.median(finite)) if finite.size else float("nan"),
            "sd": float(np.std(finite, ddof=1)) if finite.size > 1 else float("nan"),
            "n_positive": int((finite > 0).sum()),
            "p_sign": sign_test_pvalue(finite),
            "p_wilcoxon": wilcoxon_signed_rank_pvalue(finite),
        })
    pvalues = benjamini_hochberg([row["p_wilcoxon"] for row in output])
    for row, adjusted in zip(output, pvalues):
        row["p_wilcoxon_bh"] = float(adjusted)
    return output


def turn_profile(
    dataset: MatrixDataset,
    *,
    metric: str = "mean_entropy_bits",
) -> list[dict[str, Any]]:
    """Return per-turn condition means and seed-bootstrap intervals."""

    rows = call_rows(dataset)
    result: list[dict[str, Any]] = []
    for condition in CONDITIONS:
        turns = sorted({int(row["turn"]) for row in rows if row["condition"] == condition})
        for turn in turns:
            values = _seed_condition_means(
                [row for row in rows if row["condition"] == condition and row["turn"] == turn],
                metric=metric,
                turn_start=turn,
                turn_stop=turn,
            )
            per_seed = [values[(triplet.seed, condition)] for triplet in dataset.triplets if (triplet.seed, condition) in values]
            mean, low, high = bootstrap_ci(per_seed, seed=DEFAULT_RANDOM_SEED + turn)
            result.append({
                "model": dataset.model,
                "condition": condition,
                "turn": turn,
                "n_seeds": len(per_seed),
                "mean": mean,
                "ci_low": low,
                "ci_high": high,
            })
    return result


def outcome_summary(dataset: MatrixDataset) -> list[dict[str, Any]]:
    """Summarize controller metrics without conflating task success and uptake."""

    keys = (
        "task_success_rate", "task_success", "communication_verified", "U", "message_read_ratio_M",
        "cross_agent_messages_X", "board_reads_R", "board_writes_W",
        "total_tokens", "total_turns", "success_per_1000_tokens",
        "completed_agents", "submitted_agents",
    )
    output = []
    for condition in CONDITIONS:
        values = [triplet.conditions[condition].metrics for triplet in dataset.triplets]
        row: dict[str, Any] = {"model": dataset.model, "condition": condition, "n_seeds": len(values)}
        for key in keys:
            numeric = [
                1.0 if item[key] else 0.0
                for item in values
                if key in {"task_success", "communication_verified"}
                and isinstance(item.get(key), bool)
            ]
            numeric.extend(
                item[key]
                for item in values
                if key not in {"task_success", "communication_verified"}
                and isinstance(item.get(key), (int, float))
                and not isinstance(item.get(key), bool)
            )
            row[key] = float(np.mean(numeric)) if numeric else float("nan")
        output.append(row)
    return output


def independence_baseline(dataset: MatrixDataset) -> list[dict[str, Any]]:
    """Return H(agent 1)+H(agent 2), explicitly without a joint estimate."""

    rows = call_rows(dataset)
    output: list[dict[str, Any]] = []
    for triplet in dataset.triplets:
        for condition in CONDITIONS:
            for turn in sorted({row["turn"] for row in rows if row["seed"] == triplet.seed and row["condition"] == condition}):
                values = [
                    row["mean_entropy_bits"]
                    for row in rows
                    if row["seed"] == triplet.seed and row["condition"] == condition and row["turn"] == turn
                ]
                if len(values) == 2 and all(math.isfinite(float(value)) for value in values):
                    output.append({
                        "model": dataset.model,
                        "seed": triplet.seed,
                        "condition": condition,
                        "turn": turn,
                        "agent_entropy_sum_bits": float(np.sum(values)),
                        "agent_count": 2,
                        "joint_entropy_available": False,
                    })
    return output


__all__ = [
    "AnalysisValidationError",
    "CONDITIONS",
    "MatrixDataset",
    "TripletRecord",
    "AgentArtifact",
    "ConditionRecord",
    "bootstrap_ci",
    "benjamini_hochberg",
    "call_rows",
    "discover_matrices",
    "entropy_bits",
    "independence_baseline",
    "load_matrix",
    "outcome_summary",
    "paired_condition_contrasts",
    "replay_validation",
    "sign_test_pvalue",
    "token_rows",
    "turn_profile",
    "wilcoxon_signed_rank_pvalue",
]
