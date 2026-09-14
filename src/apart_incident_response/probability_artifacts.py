"""Shared artifacts for token probabilities reported by model providers.

Provider logprob APIs expose a sampled token and a bounded set of alternatives,
not the model's complete vocabulary logits. This module keeps that partial
measurement explicit and replayable.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


ARTIFACT_SCHEMA = "partial-token-probability-v1"
ARTIFACT_SCHEMA_VERSION = 1
PROBABILITY_CLASS = "partial_top_k"
_MASS_TOLERANCE = 1e-6


class ProbabilityArtifactError(ValueError):
    """Raised when a provider probability record cannot be normalized safely."""


def _finite_logprob(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProbabilityArtifactError(f"{field_name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ProbabilityArtifactError(f"{field_name} must be a finite number")
    if number > 0:
        raise ProbabilityArtifactError(f"{field_name} must be non-positive")
    return number


def _token(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ProbabilityArtifactError(f"{field_name} must be a string")
    return value


def _probability(logprob: float) -> float:
    return math.exp(logprob)


def _entropy_bits(probabilities: Sequence[float]) -> float:
    return -sum(probability * math.log2(probability) for probability in probabilities if probability > 0)


def _mass(values: Mapping[str, float]) -> tuple[float, float]:
    covered = sum(values.values())
    if covered > 1.0 + _MASS_TOLERANCE:
        raise ProbabilityArtifactError(
            f"reported probability mass exceeds one: {covered:.9f}"
        )
    covered = min(covered, 1.0)
    if covered <= 0:
        raise ProbabilityArtifactError("reported probability mass is empty")
    return covered, max(0.0, 1.0 - covered)


def normalize_token_probability(record: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize one Ollama/OpenRouter-style token probability record.

    The sampled token is authoritative and is counted once even when the
    provider repeats it inside ``top_logprobs``. Alternatives with the same
    token are also deduplicated while preserving the first provider order.
    """

    if not isinstance(record, Mapping):
        raise ProbabilityArtifactError("token probability record must be an object")
    sampled_token = _token(record.get("token"), "token")
    sampled_logprob = _finite_logprob(record.get("logprob"), "logprob")
    alternatives = record.get("top_logprobs")
    if alternatives is None:
        alternatives = []
    if not isinstance(alternatives, list):
        raise ProbabilityArtifactError("top_logprobs must be an array")

    by_token: dict[str, float] = {sampled_token: sampled_logprob}
    ordered_alternatives: list[dict[str, Any]] = []
    for index, candidate in enumerate(alternatives):
        if not isinstance(candidate, Mapping):
            raise ProbabilityArtifactError(f"top_logprobs[{index}] must be an object")
        candidate_token = _token(candidate.get("token"), f"top_logprobs[{index}].token")
        candidate_logprob = _finite_logprob(
            candidate.get("logprob"), f"top_logprobs[{index}].logprob"
        )
        if candidate_token in by_token:
            continue
        by_token[candidate_token] = candidate_logprob
        alternative: dict[str, Any] = {
            "token": candidate_token,
            "logprob": candidate_logprob,
            "probability": _probability(candidate_logprob),
        }
        if isinstance(candidate.get("bytes"), list):
            alternative["bytes"] = list(candidate["bytes"])
        ordered_alternatives.append(alternative)

    probabilities_by_token = {
        token: _probability(logprob) for token, logprob in by_token.items()
    }
    covered_mass, residual_mass = _mass(probabilities_by_token)
    probabilities = [_probability(sampled_logprob)] + [
        float(item["probability"]) for item in ordered_alternatives
    ]
    normalized = [probability / covered_mass for probability in probabilities]
    sampled_probability = probabilities[0]
    partial_entropy = _entropy_bits(normalized)
    residual_bucket_entropy = _entropy_bits([*probabilities, residual_mass])
    return {
        "sampled_token": sampled_token,
        "sampled_logprob": sampled_logprob,
        "sampled_probability": sampled_probability,
        "top_alternatives": ordered_alternatives,
        "covered_mass": covered_mass,
        "residual_mass": residual_mass,
        "entropy": {
            "sampled_logprob": sampled_logprob,
            "sampled_prob": sampled_probability,
            "sampled_surprise_bits": -sampled_logprob / math.log(2),
            "partial_entropy_bits": partial_entropy,
            "top_k_entropy_bits": partial_entropy,
            "residual_bucket_entropy_bits": residual_bucket_entropy,
        },
    }


def _provenance(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProbabilityArtifactError("provenance must be an object")
    provider = value.get("provider")
    model = value.get("model")
    if not isinstance(provider, str) or not provider:
        raise ProbabilityArtifactError("provenance.provider must be a non-empty string")
    if not isinstance(model, str) or not model:
        raise ProbabilityArtifactError("provenance.model must be a non-empty string")
    parameters = value.get("parameters", {})
    if not isinstance(parameters, Mapping):
        raise ProbabilityArtifactError("provenance.parameters must be an object")
    return {
        "provider": provider,
        "model": model,
        "parameters": dict(parameters),
    }


def unavailable_probability_artifact(
    provenance: Mapping[str, Any], reason: str
) -> dict[str, Any]:
    """Create an explicit artifact for a response with no usable probabilities."""

    if not isinstance(reason, str) or not reason.strip():
        raise ProbabilityArtifactError("missing-data reason must be a non-empty string")
    return {
        "artifact_schema": ARTIFACT_SCHEMA,
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "probability_class": PROBABILITY_CLASS,
        "full_vocabulary_compatible": False,
        "status": "unavailable",
        "missing_data_reason": reason,
        "provenance": _provenance(provenance),
        "tokens": [],
        "coverage": {
            "token_count": 0,
            "tokens_with_alternatives": 0,
            "alternative_count": 0,
        },
    }


def build_probability_artifact(
    records: Sequence[Mapping[str, Any]] | None,
    *,
    provenance: Mapping[str, Any],
    missing_data_reason: str | None = None,
) -> dict[str, Any]:
    """Build a versioned partial-probability artifact from provider records."""

    normalized_provenance = _provenance(provenance)
    if records is None or missing_data_reason is not None:
        if records:
            raise ProbabilityArtifactError(
                "missing-data reason cannot accompany probability records"
            )
        return unavailable_probability_artifact(
            normalized_provenance,
            missing_data_reason or "provider omitted probability data",
        )
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        raise ProbabilityArtifactError("probability records must be an array")
    tokens = [normalize_token_probability(record) for record in records]
    if not tokens:
        return unavailable_probability_artifact(
            normalized_provenance, "provider returned an empty probability array"
        )
    alternatives = sum(len(token["top_alternatives"]) for token in tokens)
    tokens_with_alternatives = sum(
        bool(token["top_alternatives"]) for token in tokens
    )
    return {
        "artifact_schema": ARTIFACT_SCHEMA,
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "probability_class": PROBABILITY_CLASS,
        "full_vocabulary_compatible": False,
        "status": "complete",
        "missing_data_reason": None,
        "provenance": normalized_provenance,
        "entropy_definition": {
            "sampled_surprise_bits": "-log2(p(sampled token))",
            "partial_entropy_bits": (
                "Shannon entropy after normalizing probability mass covered by "
                "the sampled token and deduplicated reported alternatives"
            ),
            "residual_bucket_entropy_bits": (
                "Shannon entropy of reported token probabilities plus one bucket "
                "for all unobserved vocabulary mass"
            ),
            "full_vocabulary_entropy": "unavailable from top-K logprobs",
        },
        "tokens": tokens,
        "coverage": {
            "token_count": len(tokens),
            "tokens_with_alternatives": tokens_with_alternatives,
            "alternative_count": alternatives,
            "mean_covered_mass": sum(token["covered_mass"] for token in tokens) / len(tokens),
            "mean_residual_mass": sum(token["residual_mass"] for token in tokens) / len(tokens),
        },
    }


def replay_partial_entropy(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute per-token partial entropy from a stored artifact."""

    if not isinstance(artifact, Mapping):
        raise ProbabilityArtifactError("probability artifact must be an object")
    if artifact.get("artifact_schema") != ARTIFACT_SCHEMA:
        raise ProbabilityArtifactError("unexpected probability artifact schema")
    tokens = artifact.get("tokens")
    if not isinstance(tokens, list):
        raise ProbabilityArtifactError("probability artifact tokens must be an array")
    if artifact.get("status") == "unavailable":
        return {"status": "unavailable", "token_count": 0}
    replayed: list[dict[str, float]] = []
    for index, token in enumerate(tokens):
        if not isinstance(token, Mapping):
            raise ProbabilityArtifactError(f"tokens[{index}] must be an object")
        sampled_logprob = _finite_logprob(token.get("sampled_logprob"), f"tokens[{index}].sampled_logprob")
        alternatives = token.get("top_alternatives")
        if not isinstance(alternatives, list):
            raise ProbabilityArtifactError(f"tokens[{index}].top_alternatives must be an array")
        values = {"sampled": _probability(sampled_logprob)}
        for alt_index, alternative in enumerate(alternatives):
            if not isinstance(alternative, Mapping):
                raise ProbabilityArtifactError(
                    f"tokens[{index}].top_alternatives[{alt_index}] must be an object"
                )
            token_name = _token(alternative.get("token"), "alternative.token")
            if token_name == token.get("sampled_token") or token_name in values:
                continue
            values[token_name] = _finite_logprob(
                alternative.get("logprob"), "alternative.logprob"
            )
            values[token_name] = _probability(values[token_name])
        covered_mass, residual_mass = _mass(values)
        probabilities = [value / covered_mass for value in values.values()]
        replayed.append({
            "partial_entropy_bits": _entropy_bits(probabilities),
            "residual_bucket_entropy_bits": _entropy_bits([*values.values(), residual_mass]),
        })
    return {"status": "complete", "token_count": len(replayed), "tokens": replayed}
