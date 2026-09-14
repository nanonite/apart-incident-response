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
                        "mean_top_k_entropy_bits": _mean(_token_entropy(t, "top_k_entropy_bits") for t in tokens if isinstance(t, Mapping)),
                        "mean_residual_entropy_bits": _mean(_token_entropy(t, "residual_bucket_entropy_bits") for t in tokens if isinstance(t, Mapping)),
                        "mean_surprise_bits": _mean(_token_entropy(t, "sampled_surprise_bits") for t in tokens if isinstance(t, Mapping)),
                        "mean_coverage": _mean(
                            float(t.get("covered_mass", float("nan")))
                            for t in tokens if isinstance(t, Mapping)
                        ),
                    })
    return rows


def require_replay_valid(
    dataset: MatrixDataset,
    *,
    tolerance: float = 1e-9,
) -> list[dict[str, Any]]:
    """Return the replay audit or refuse to produce an entropy estimate.

    Replay is part of the analysis inclusion rule.  Callers that only need an
    execution audit can still use :func:`replay_validation` directly.
    """

    rows = replay_validation(dataset, tolerance=tolerance)
    invalid = [row for row in rows if not row.get("valid", False)]
    if invalid:
        sample = invalid[0]
        detail = (
            f"{sample.get('condition', '?')}/{sample.get('agent', '?')} "
            f"seed {sample.get('seed', '?')}: "
            f"{sample.get('error', 'stored probability values do not replay') }"
        )
        raise AnalysisValidationError(
            f"entropy estimate blocked by replay validation ({len(invalid)} invalid artifacts; {detail})",
            report={"invalid": invalid, "checked": rows},
        )
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
    """Average only balanced seed-condition cells.

    A cell is usable when every agent has one finite observation for every
    requested response ordinal.  This keeps short runs from contributing a
    different number of responses to different conditions.
    """

    turns = {
        int(row["turn"])
        for row in rows
        if _is_int(row.get("turn"))
        and (turn_start is None or row["turn"] >= turn_start)
        and (turn_stop is None or row["turn"] <= turn_stop)
    }
    if turn_start is not None and turn_stop is not None:
        turns = set(range(turn_start, turn_stop + 1))
    if not turns:
        return {}

    by_agent: dict[tuple[int, str, str], dict[int, list[float]]] = {}
    for row in rows:
        turn = row.get("turn")
        if not _is_int(turn) or (turn_start is not None and turn < turn_start) or (turn_stop is not None and turn > turn_stop):
            continue
        value = row.get(metric)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
            continue
        key = (int(row["seed"]), str(row["condition"]), str(row["agent"]))
        by_agent.setdefault(key, {}).setdefault(int(turn), []).append(float(value))

    by_condition: dict[tuple[int, str], list[float]] = {}
    for (seed, condition, agent), values_by_turn in by_agent.items():
        if set(values_by_turn) != turns or any(len(values) != 1 for values in values_by_turn.values()):
            continue
        by_condition.setdefault((seed, condition), []).append(
            float(np.mean([values_by_turn[turn][0] for turn in sorted(turns)]))
        )
    return {
        key: float(np.mean(values))
        for key, values in by_condition.items()
        if len(values) >= 2
    }


def _resolved_window(
    rows: Sequence[Mapping[str, Any]],
    *,
    metric: str,
    turn_start: int | None,
    turn_stop: int | None,
) -> tuple[int, int]:
    start = 1 if turn_start is None else int(turn_start)
    if start < 1:
        raise ValueError("turn_start must be at least one")
    if turn_stop is None:
        maxima: dict[tuple[int, str, str], int] = {}
        for row in rows:
            turn = row.get("turn")
            value = row.get(metric)
            if _is_int(turn) and isinstance(value, (int, float)) and math.isfinite(float(value)):
                key = (int(row["seed"]), str(row["condition"]), str(row["agent"]))
                maxima[key] = max(maxima.get(key, 0), int(turn))
        if not maxima:
            raise AnalysisValidationError("no finite call observations are available")
        stop = min(maxima.values())
    else:
        stop = int(turn_stop)
    if stop < start:
        raise ValueError("turn_stop must be at least turn_start")
    return start, stop


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
    require_replay_valid(dataset)
    resolved_start, resolved_stop = _resolved_window(
        rows, metric=metric, turn_start=turn_start, turn_stop=turn_stop
    )
    values = _seed_condition_means(
        rows, metric=metric, turn_start=resolved_start, turn_stop=resolved_stop
    )
    output: list[dict[str, Any]] = []
    for offset, (name, (right, left)) in enumerate(CONTRASTS.items()):
        differences = [
            values[(triplet.seed, right)] - values[(triplet.seed, left)]
            for triplet in dataset.triplets
            if all((triplet.seed, condition) in values for condition in CONDITIONS)
        ]
        included_seeds = [
            triplet.seed for triplet in dataset.triplets
            if all((triplet.seed, condition) in values for condition in CONDITIONS)
        ]
        estimate, low, high = bootstrap_ci(differences, draws=draws, seed=seed + offset)
        finite = np.asarray(differences, dtype=float)
        output.append({
            "model": dataset.model,
            "metric": metric,
            "contrast": name,
            "turn_start": turn_start,
            "turn_stop": turn_stop,
            "turn_start_resolved": resolved_start,
            "turn_stop_resolved": resolved_stop,
            "balance_rule": "both agents and all requested response ordinals are present in every included condition",
            "n_seeds": int(finite.size),
            "seeds": included_seeds,
            "excluded_seeds": [seed for seed in dataset.seeds if seed not in included_seeds],
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
    require_replay_valid(dataset)
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
                "balanced_agents": len(per_seed) > 0,
                "mean": mean,
                "ci_low": low,
                "ci_high": high,
            })
    return result


def _contrast_statistics(
    dataset: MatrixDataset,
    values: Mapping[tuple[int, str], float],
    *,
    metric: str,
    label: str,
    turn_start: int,
    turn_stop: int,
    draws: int,
    seed: int,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for offset, (name, (right, left)) in enumerate(CONTRASTS.items()):
        included = [
            triplet.seed for triplet in dataset.triplets
            if all((triplet.seed, condition) in values for condition in CONDITIONS)
        ]
        differences = [
            values[(matched_seed, right)] - values[(matched_seed, left)]
            for matched_seed in included
        ]
        finite = np.asarray(differences, dtype=float)
        estimate, low, high = bootstrap_ci(differences, draws=draws, seed=seed + offset)
        output.append({
            "model": dataset.model,
            "metric": metric,
            "analysis": label,
            "contrast": name,
            "turn_start": turn_start,
            "turn_stop": turn_stop,
            "balance_rule": "both agents and all requested response ordinals are present in every included condition",
            "n_seeds": int(finite.size),
            "seeds": included,
            "excluded_seeds": [item.seed for item in dataset.triplets if item.seed not in included],
            "estimate": estimate,
            "ci_low": low,
            "ci_high": high,
            "median": float(np.median(finite)) if finite.size else float("nan"),
            "sd": float(np.std(finite, ddof=1)) if finite.size > 1 else float("nan"),
            "n_positive": int((finite > 0).sum()),
            "p_sign": sign_test_pvalue(finite),
            "p_wilcoxon": wilcoxon_signed_rank_pvalue(finite),
        })
    adjusted = benjamini_hochberg([row["p_wilcoxon"] for row in output])
    for row, value in zip(output, adjusted):
        row["p_wilcoxon_bh"] = float(value)
    return output


def _window_values(
    rows: Sequence[Mapping[str, Any]],
    *,
    metric: str,
    turn_start: int,
    turn_stop: int,
) -> dict[tuple[int, str], float]:
    return _seed_condition_means(
        rows,
        metric=metric,
        turn_start=turn_start,
        turn_stop=turn_stop,
    )


def endpoint_analysis(
    dataset: MatrixDataset,
    *,
    metric: str = "mean_entropy_bits",
    intervention_turn: int = 8,
    post_windows: Sequence[int] = (5, 10),
    draws: int = DEFAULT_BOOTSTRAP_DRAWS,
    seed: int = DEFAULT_RANDOM_SEED,
) -> list[dict[str, Any]]:
    """Recreate the old endpoint table for the current three-condition schema.

    The current artifacts do not expose the old action and prompt-length
    covariates, so these are raw balanced endpoints.  Each row is still a
    matched seed contrast and the pre/post variant uses the same requested
    response ordinals in every included cell.
    """

    if intervention_turn < 2:
        raise ValueError("intervention_turn must be at least two")
    rows = call_rows(dataset)
    require_replay_valid(dataset)
    output: list[dict[str, Any]] = []
    for offset, width in enumerate(post_windows):
        if not _is_int(width) or width < 1:
            raise ValueError("post_windows must contain positive integers")
        post_start = intervention_turn
        post_stop = intervention_turn + int(width) - 1
        post = _window_values(rows, metric=metric, turn_start=post_start, turn_stop=post_stop)
        post_rows = _contrast_statistics(
            dataset, post, metric=metric, label=f"post_{width}",
            turn_start=post_start, turn_stop=post_stop,
            draws=draws, seed=seed + offset * 3,
        )
        for row in post_rows:
            row["window"] = int(width)
            row["endpoint"] = "post"
        output.extend(post_rows)

        pre = _window_values(rows, metric=metric, turn_start=1, turn_stop=intervention_turn - 1)
        changes = {
            key: post[key] - pre[key]
            for key in post
            if key in pre
        }
        change_rows = _contrast_statistics(
            dataset, changes, metric=metric, label=f"prepost_{width}",
            turn_start=1, turn_stop=post_stop,
            draws=draws, seed=seed + offset * 3 + 1,
        )
        for row in change_rows:
            row["window"] = int(width)
            row["endpoint"] = "post_minus_pre"
        output.extend(change_rows)
    return output


def _ols_coefficients(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float, float]:
    if x.ndim != 2 or y.ndim != 1 or len(y) != len(x) or len(y) == 0:
        return np.asarray([], dtype=float), float("nan"), float("nan")
    try:
        coefficients, _residuals, _rank, _singular = np.linalg.lstsq(x, y, rcond=None)
    except np.linalg.LinAlgError:
        return np.asarray([], dtype=float), float("nan"), float("nan")
    residual = y - x @ coefficients
    sse = float(np.sum(residual * residual))
    n = len(y)
    k = x.shape[1]
    if n == 0 or sse <= 0:
        bic = float("-inf") if sse == 0 else float("nan")
    else:
        bic = float(n * math.log(sse / n) + k * math.log(n))
    return coefficients, sse, bic


def interrupted_series(
    dataset: MatrixDataset,
    *,
    metric: str = "mean_entropy_bits",
    intervention_turn: int = 8,
) -> list[dict[str, Any]]:
    """Fit a descriptive interrupted series at a declared turn boundary.

    C0/C1/C2 runs have no treatment onset recorded in the artifact.  This
    function therefore reports piecewise slopes and level changes only; it
    does not label the boundary as a causal intervention or emit ITS p-values.
    """

    if intervention_turn < 2:
        raise ValueError("intervention_turn must be at least two")
    profile = turn_profile(dataset, metric=metric)
    output: list[dict[str, Any]] = []
    for condition in CONDITIONS:
        values = [
            row for row in profile
            if row["condition"] == condition and math.isfinite(float(row["mean"]))
        ]
        if not values:
            continue
        turns = np.asarray([row["turn"] for row in values], dtype=float)
        y = np.asarray([row["mean"] for row in values], dtype=float)
        post = (turns >= intervention_turn).astype(float)
        centered = turns - intervention_turn
        x = np.column_stack((np.ones(len(turns)), centered, post, centered * post))
        coefficients, sse, bic = _ols_coefficients(x, y)
        if len(coefficients) == 4:
            output.append({
                "model": dataset.model,
                "condition": condition,
                "metric": metric,
                "intervention_turn": intervention_turn,
                "event_source": "declared analysis boundary; no observed uptake onset",
                "n_turns": len(values),
                "min_seed_count": min(int(row["n_seeds"]) for row in values),
                "level_at_boundary": float(coefficients[0]),
                "pre_slope": float(coefficients[1]),
                "level_change": float(coefficients[2]),
                "slope_change": float(coefficients[3]),
                "post_slope": float(coefficients[1] + coefficients[3]),
                "sse": sse,
                "bic": bic,
            })
    return output


def event_aligned_profile(
    dataset: MatrixDataset,
    *,
    metric: str = "mean_entropy_bits",
    event_turn: int = 8,
    radius: int = 3,
) -> list[dict[str, Any]]:
    """Return an event-study profile around a declared turn.

    This is the portable part of the former event study.  The old endogenous
    ``tau_read``/``tau_use`` fields are not available in the UUID probability
    artifacts, so ``event_turn`` must be supplied and is reported as such.
    """

    if radius < 0:
        raise ValueError("radius must be non-negative")
    rows = call_rows(dataset)
    require_replay_valid(dataset)
    grouped: dict[tuple[str, int, int], list[float]] = {}
    for row in rows:
        value = row.get(metric)
        turn = row.get("turn")
        if row.get("condition") not in CONDITIONS or not _is_int(turn):
            continue
        relative = int(turn) - event_turn
        if abs(relative) > radius or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            continue
        grouped.setdefault((str(row["condition"]), relative, int(row["seed"])), []).append(float(value))
    output: list[dict[str, Any]] = []
    for condition in CONDITIONS:
        for relative in range(-radius, radius + 1):
            per_seed = [
                float(np.mean(values))
                for (item_condition, item_relative, _seed), values in grouped.items()
                if item_condition == condition and item_relative == relative and len(values) == 2
            ]
            mean, low, high = bootstrap_ci(per_seed, seed=DEFAULT_RANDOM_SEED + relative + radius)
            output.append({
                "model": dataset.model,
                "condition": condition,
                "relative_turn": relative,
                "event_turn": event_turn,
                "event_source": "declared analysis boundary; no observed uptake onset",
                "metric": metric,
                "n_seeds": len(per_seed),
                "mean": mean,
                "ci_low": low,
                "ci_high": high,
            })
    return output


def _pearson(x: Sequence[float], y: Sequence[float]) -> float:
    left = np.asarray(x, dtype=float)
    right = np.asarray(y, dtype=float)
    if left.size < 2 or left.size != right.size:
        return float("nan")
    left = left - left.mean()
    right = right - right.mean()
    denominator = math.sqrt(float(np.sum(left * left) * np.sum(right * right)))
    return float(np.sum(left * right) / denominator) if denominator > 0 else float("nan")


def coupling_proxy(
    dataset: MatrixDataset,
    *,
    metric: str = "mean_entropy_bits",
) -> list[dict[str, Any]]:
    """Measure aligned agent trajectory coupling available in current traces.

    The old soft action-class joint distribution cannot be reconstructed from
    these artifacts.  This proxy uses paired per-response entropy trajectories
    and is labelled separately from mutual information.
    """

    rows = call_rows(dataset)
    require_replay_valid(dataset)
    by_key: dict[tuple[int, str, int], dict[str, float]] = {}
    for row in rows:
        value = row.get(metric)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            by_key.setdefault((int(row["seed"]), str(row["condition"]), int(row["turn"])), {})[str(row["agent"])] = float(value)
    output: list[dict[str, Any]] = []
    for condition in CONDITIONS:
        pairs = [values for (seed, item_condition, turn), values in by_key.items()
                 if item_condition == condition and len(values) == 2]
        left = [values[sorted(values)[0]] for values in pairs]
        right = [values[sorted(values)[1]] for values in pairs]
        delta = np.asarray(left, dtype=float) - np.asarray(right, dtype=float)
        mean_delta, low, high = bootstrap_ci(delta, seed=DEFAULT_RANDOM_SEED + len(output))
        output.append({
            "model": dataset.model,
            "condition": condition,
            "metric": metric,
            "coupling_measure": "paired entropy trajectory proxy",
            "n_pairs": int(delta.size),
            "n_seeds": len({key[0] for key, values in by_key.items() if key[1] == condition and len(values) == 2}),
            "agent_correlation": _pearson(left, right),
            "mean_agent_delta_bits": mean_delta,
            "ci_low": low,
            "ci_high": high,
            "joint_entropy_available": False,
        })
    return output


def functional_form_comparison(
    dataset: MatrixDataset,
    *,
    metric: str = "mean_entropy_bits",
) -> list[dict[str, Any]]:
    """Compare small NumPy-only time-series forms by BIC and RMSE."""

    profile = turn_profile(dataset, metric=metric)
    forms = {
        "constant": lambda x: np.column_stack((np.ones(len(x)),)),
        "linear": lambda x: np.column_stack((np.ones(len(x)), x)),
        "logarithmic": lambda x: np.column_stack((np.ones(len(x)), np.log1p(x))),
        "cubic": lambda x: np.column_stack((np.ones(len(x)), x, x**2, x**3)),
    }
    output: list[dict[str, Any]] = []
    for condition in CONDITIONS:
        values = [row for row in profile if row["condition"] == condition and math.isfinite(float(row["mean"]))]
        x = np.asarray([row["turn"] for row in values], dtype=float)
        y = np.asarray([row["mean"] for row in values], dtype=float)
        for name, design in forms.items():
            matrix = design(x)
            if len(y) < matrix.shape[1]:
                continue
            coefficients, sse, bic = _ols_coefficients(matrix, y)
            output.append({
                "model": dataset.model,
                "condition": condition,
                "metric": metric,
                "form": name,
                "n_turns": len(y),
                "rmse": float(math.sqrt(sse / len(y))) if math.isfinite(sse) else float("nan"),
                "bic": bic,
                "selected_by_bic": False,
            })
    for condition in CONDITIONS:
        candidates = [row for row in output if row["condition"] == condition and math.isfinite(float(row["bic"]))]
        if candidates:
            winner = min(candidates, key=lambda row: row["bic"])["form"]
            for row in candidates:
                row["selected_by_bic"] = row["form"] == winner
    return output


def early_warning_detector(
    dataset: MatrixDataset,
    *,
    metric: str = "mean_entropy_bits",
    baseline_stop: int = 7,
    monitor_start: int = 8,
    quantile: float = 0.95,
) -> list[dict[str, Any]]:
    """Apply a transparent z-score detector using C0 as the null calibration.

    It is a diagnostic detector.  The fixed monitoring boundary is known in
    advance, and current traces do not record an observed uptake event against
    which alarm lead time can be scored.
    """

    if not 0 < quantile < 1 or baseline_stop >= monitor_start:
        raise ValueError("quantile must be in (0, 1) and baseline_stop before monitor_start")
    rows = call_rows(dataset)
    require_replay_valid(dataset)
    by_series: dict[tuple[int, str, str], list[tuple[int, float]]] = {}
    for row in rows:
        value = row.get(metric)
        turn = row.get("turn")
        if _is_int(turn) and isinstance(value, (int, float)) and math.isfinite(float(value)):
            by_series.setdefault((int(row["seed"]), str(row["condition"]), str(row["agent"])), []).append((int(turn), float(value)))
    scores: dict[tuple[int, str, str], tuple[float, int | None, int]] = {}
    for key, series in by_series.items():
        baseline = np.asarray([value for turn, value in series if turn <= baseline_stop], dtype=float)
        monitored = [(turn, value) for turn, value in series if turn >= monitor_start]
        if baseline.size < 2 or not monitored:
            continue
        mean = float(baseline.mean())
        sd = float(baseline.std(ddof=1))
        scale = sd if sd > 1e-12 else 1.0
        z = [(turn, abs((value - mean) / scale)) for turn, value in monitored]
        scores[key] = (max(value for _turn, value in z), next((turn for turn, value in z if value >= 0), None), int(baseline.size))
    null_scores = [value[0] for key, value in scores.items() if key[1] == "C0"]
    threshold = float(np.quantile(null_scores, quantile)) if null_scores else float("nan")
    output: list[dict[str, Any]] = []
    for (seed, condition, agent), (score, _unused_alarm, baseline_n) in scores.items():
        series = by_series[(seed, condition, agent)]
        baseline = np.asarray([value for turn, value in series if turn <= baseline_stop], dtype=float)
        scale = float(baseline.std(ddof=1)) if baseline.size > 1 else 1.0
        scale = scale if scale > 1e-12 else 1.0
        mean = float(baseline.mean())
        alarm = next((turn for turn, value in series if turn >= monitor_start and abs((value - mean) / scale) >= threshold), None)
        output.append({
            "model": dataset.model,
            "seed": seed,
            "condition": condition,
            "agent": agent,
            "metric": metric,
            "baseline_turns": baseline_n,
            "monitor_start": monitor_start,
            "threshold": threshold,
            "max_abs_z": score,
            "alarm_turn": alarm,
            "alarm_before_observed_uptake": None,
            "interpretation": "fixed-boundary diagnostic; no uptake timestamp in current artifact",
        })
    return output


def robustness_summary(dataset: MatrixDataset) -> list[dict[str, Any]]:
    """Summarize partial, top-K, residual and coverage token measures."""

    rows = token_rows(dataset)
    output: list[dict[str, Any]] = []
    for condition in CONDITIONS:
        values = [row for row in rows if row["condition"] == condition]
        def finite(field: str) -> list[float]:
            return [float(row[field]) for row in values if isinstance(row.get(field), (int, float)) and math.isfinite(float(row[field]))]
        coverage = finite("covered_mass")
        partial = finite("partial_entropy_bits")
        output.append({
            "model": dataset.model,
            "condition": condition,
            "token_rows": len(values),
            "partial_entropy_mean_bits": float(np.mean(partial)) if partial else float("nan"),
            "top_k_entropy_mean_bits": float(np.mean(finite("top_k_entropy_bits"))) if finite("top_k_entropy_bits") else float("nan"),
            "residual_bucket_entropy_mean_bits": float(np.mean(finite("residual_bucket_entropy_bits"))) if finite("residual_bucket_entropy_bits") else float("nan"),
            "coverage_mean": float(np.mean(coverage)) if coverage else float("nan"),
            "coverage_below_0_99": float(np.mean(np.asarray(coverage) < 0.99)) if coverage else float("nan"),
        })
    return output


def audit_matrix(matrix_path: Path | str) -> dict[str, Any]:
    """Audit a matrix, including rejected runs, without creating an estimate."""

    path = Path(matrix_path).expanduser().resolve()
    if path.is_dir():
        path = path / "matrix.json"
    document = _read_json(path)
    if not isinstance(document, Mapping):
        raise AnalysisValidationError(f"matrix is not a JSON object: {path}")
    triplets = document.get("triplets")
    if not isinstance(triplets, list):
        triplets = []
    condition_rows: list[dict[str, Any]] = []
    reasons: list[str] = []
    for index, triplet in enumerate(triplets):
        entries = triplet.get("artifacts", {}).get("conditions", {}) if isinstance(triplet, Mapping) else {}
        for condition in CONDITIONS:
            entry = entries.get(condition) if isinstance(entries, Mapping) else None
            row: dict[str, Any] = {"triplet_index": index, "condition": condition}
            try:
                if not isinstance(entry, Mapping):
                    raise AnalysisValidationError("missing condition link")
                root = _condition_root(path.parent, entry, condition)
                manifest = _read_json(root / "manifest.json")
                results = _read_json(root / "results.json")
                result_rows = results.get("results", []) if isinstance(results, Mapping) else []
                statuses = [
                    item.get("status") for item in result_rows
                    if isinstance(item, Mapping)
                ]
                probability_rows = []
                for artifact in entry.get("probability_artifacts", {}).values() if isinstance(entry.get("probability_artifacts"), Mapping) else []:
                    artifact_path = _resolve_link(path.parent, artifact, label="probability artifact")
                    probability = _read_json(artifact_path)
                    coverage = probability.get("coverage", {}) if isinstance(probability, Mapping) else {}
                    probability_rows.append({
                        "complete": coverage.get("complete"),
                        "partial": coverage.get("partial"),
                        "unavailable": coverage.get("unavailable"),
                        "turns": coverage.get("turns"),
                        "tokens": coverage.get("tokens"),
                    })
                row.update({
                    "seed": manifest.get("seed") if isinstance(manifest, Mapping) else None,
                    "agent_count": len((manifest.get("assignment", []) if isinstance(manifest, Mapping) else [])),
                    "result_statuses": statuses,
                    "probability_artifacts": probability_rows,
                    "entropy_ready": bool(statuses) and all(status == "completed" for status in statuses)
                    and bool(probability_rows) and all(
                        item.get("complete", 0) > 0 and item.get("unavailable", 0) == 0
                        for item in probability_rows
                    ),
                })
            except (AnalysisValidationError, OSError, TypeError, ValueError) as exc:
                row["error"] = str(exc)
                row["entropy_ready"] = False
            if not row.get("entropy_ready"):
                reasons.append(
                    f"triplet {index} {condition}: "
                    f"{row.get('error') or row.get('result_statuses') or 'probability artifact unavailable'}"
                )
            condition_rows.append(row)
    ready = bool(condition_rows) and all(row.get("entropy_ready") for row in condition_rows)
    return {
        "matrix": str(path),
        "run_uuid": document.get("run_uuid"),
        "model": document.get("model"),
        "run_class": document.get("run_class"),
        "experimental_data": document.get("experimental_data"),
        "triplets": len(triplets),
        "conditions_checked": len(condition_rows),
        "entropy_ready": ready,
        "conditions": condition_rows,
        "reasons": reasons,
    }


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
    require_replay_valid(dataset)
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
    "audit_matrix",
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
    "endpoint_analysis",
    "event_aligned_profile",
    "early_warning_detector",
    "functional_form_comparison",
    "interrupted_series",
    "independence_baseline",
    "load_matrix",
    "outcome_summary",
    "paired_condition_contrasts",
    "replay_validation",
    "require_replay_valid",
    "robustness_summary",
    "coupling_proxy",
    "sign_test_pvalue",
    "token_rows",
    "turn_profile",
    "wilcoxon_signed_rank_pvalue",
]
