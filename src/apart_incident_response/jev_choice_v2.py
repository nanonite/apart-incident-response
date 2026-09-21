"""Jev Choice wire codec v2 — capture-then-judge normalization (offline).

Successor to the strict ``jev-choice-wire-v1`` codec in
:mod:`apart_incident_response.jev_choice`. v1 is preserved byte-for-byte and is
used for reproduction of every locked v1 artifact and the stopped optional-board
pilot (commit ``ff2fbc7``).

v2 changes exactly one thing: the probability vector is **captured and diagnosed
before** it is classified. The reviewer-approved primary policy accepts a valid
vector whose absolute normalization deviation ``abs(sum(p_raw) - 1)`` is at most
``1e-2`` (inclusive with only a machine-epsilon allowance at the boundary); such
a vector is flagged ``complete_renormalized`` and divided by its raw sum before
any metric is computed. Strict option identity and finite, nonnegative values
remain mandatory, and no vector is ever repaired.

The transport is inherited from v1 (Authorization-header-only, retries and
physical-request accounting unchanged). No credentials, authorization headers or
raw provider envelopes are retained.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import jev_choice as jc
from .jev_choice import (
    JEV_CHOICE_INSTRUCTIONS,
    JEV_DEFAULT_MODEL,
    JEV_MAX_RETRIES,
    JEV_QUESTION_ID,
    JEV_RETRYABLE_STATUSES,
    JEV_SYSTEMONE_ENDPOINT,
    MAX_CHOICE_OPTIONS,
    JevChoiceAdapter,
    JevChoiceClient,  # re-exported for callers
)


#: Codec/protocol version for capture-then-judge normalization.
JEV_CHOICE_V2_CODEC_VERSION = "jev-choice-wire-v2"
JEV_V2_PROTOCOL_KEY_PREFIX = "jev-choice-wire-v2|"

#: Reviewer-approved tier thresholds (absolute normalization deviation).
EXACT_DEVIATION_TOLERANCE = 1e-6
PRIMARY_ACCEPTANCE_BOUND = 1e-2
#: 0.03 is a sensitivity/diagnostic quantization bound only, never an acceptance
#: bound. 0.05 is the hard ceiling that triggers the registered hard stop.
QUANTIZATION_BOUND = 0.03
HARD_DEVIATION_CEILING = 0.05

#: Registered sensitivity grid (classification tolerances).
SENSITIVITY_GRID = (1e-6, 0.01, 0.03, 0.05)

#: Allowance applied only at the inclusive 1e-2 boundary so an exact decimal
#: deviation is not rejected by binary floating-point representation.
NORMALIZATION_BOUNDARY_EPSILON = 8 * sys.float_info.epsilon

NORMALIZATION_TIERS = (
    "exact",
    "complete_renormalized",
    "not_normalized_suspect",
    "not_normalized_hard",
    "malformed",
)

JEV_V2_INVALID_CLASSES = frozenset(
    set(jc.INVALID_RESPONSE_CLASSES)
    | {"not_normalized_suspect", "not_normalized_hard", "argmax_shifted_on_renormalization"}
)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def json_safe(value: Any) -> Any:
    """Encode a captured value so ``allow_nan=False`` serialization never fails."""

    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return value
    return value


def _safe_vector(probabilities: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): json_safe(value) for key, value in probabilities.items()}


def classify_normalization(absolute_deviation: float) -> str:
    """Map an absolute normalization deviation to its registered tier."""

    if absolute_deviation <= EXACT_DEVIATION_TOLERANCE:
        return "exact"
    if absolute_deviation <= PRIMARY_ACCEPTANCE_BOUND + NORMALIZATION_BOUNDARY_EPSILON:
        return "complete_renormalized"
    if absolute_deviation <= HARD_DEVIATION_CEILING:
        return "not_normalized_suspect"
    return "not_normalized_hard"


@dataclass(frozen=True)
class ChoiceVectorDiagnostics:
    """Credential-free capture of one Choice probability vector before judging."""

    option_count: int
    raw_probability_sum: float | None
    signed_normalization_deviation: float | None
    absolute_normalization_deviation: float | None
    minimum_probability: float | None
    maximum_probability: float | None
    zero_count: int | None
    all_finite: bool
    all_nonnegative: bool
    shape_valid: bool
    invalid_classes: tuple[str, ...]
    raw_argmax_set: tuple[str, ...]
    normalization_tier: str
    renormalized: bool
    argmax_preserved: bool | None
    normalization_adjustment: float | None
    entropy_raw_bits: float | None
    entropy_normalized_bits: float | None

    @property
    def accepted(self) -> bool:
        return self.shape_valid and self.normalization_tier in {"exact", "complete_renormalized"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "option_count": self.option_count,
            "raw_probability_sum": self.raw_probability_sum,
            "signed_normalization_deviation": self.signed_normalization_deviation,
            "absolute_normalization_deviation": self.absolute_normalization_deviation,
            "minimum_probability": self.minimum_probability,
            "maximum_probability": self.maximum_probability,
            "zero_count": self.zero_count,
            "all_finite": self.all_finite,
            "all_nonnegative": self.all_nonnegative,
            "shape_valid": self.shape_valid,
            "invalid_classes": list(self.invalid_classes),
            "raw_argmax_set": list(self.raw_argmax_set),
            "normalization_tier": self.normalization_tier,
            "renormalized": self.renormalized,
            "argmax_preserved": self.argmax_preserved,
            "normalization_adjustment": self.normalization_adjustment,
            "entropy_raw_bits": self.entropy_raw_bits,
            "entropy_normalized_bits": self.entropy_normalized_bits,
        }


def _argmax_preserved(raw_argmax_set: Sequence[str], normalized: Mapping[str, float]) -> bool:
    """Whether renormalization leaves the argmax set unchanged (fail closed)."""

    peak = max(normalized.values())
    normalized_argmax = {option_id for option_id, value in normalized.items() if value == peak}
    return normalized_argmax == set(raw_argmax_set)


def _malformed_diagnostics(option_count: int, invalid_class: str, *,
                           all_finite: bool = False, all_nonnegative: bool = False,
                           raw_vector: Mapping[str, Any] | None = None) -> ChoiceVectorDiagnostics:
    raw_vector = raw_vector or {}
    finite_values = [float(value) for value in raw_vector.values()
                     if _is_number(value) and math.isfinite(float(value))]
    total = sum(finite_values) if all_finite and finite_values else None
    deviation = (total - 1.0) if total is not None else None
    return ChoiceVectorDiagnostics(
        option_count=option_count,
        raw_probability_sum=total,
        signed_normalization_deviation=deviation,
        absolute_normalization_deviation=abs(deviation) if deviation is not None else None,
        minimum_probability=min(finite_values) if all_finite and finite_values else None,
        maximum_probability=max(finite_values) if all_finite and finite_values else None,
        zero_count=(sum(1 for value in finite_values if value == 0.0)
                    if all_finite and finite_values else None),
        all_finite=all_finite,
        all_nonnegative=all_nonnegative,
        shape_valid=False,
        invalid_classes=(invalid_class,),
        raw_argmax_set=(),
        normalization_tier="malformed",
        renormalized=False,
        argmax_preserved=None,
        normalization_adjustment=None,
        entropy_raw_bits=None,
        entropy_normalized_bits=None,
    )


def diagnose_probability_vector(probabilities: Any, option_ids: Sequence[str]
                                ) -> tuple[dict[str, Any], ChoiceVectorDiagnostics, list[str]]:
    """Capture a raw vector and its diagnostics, then return invalid classes.

    Never raises and never repairs. Returns ``(safe_raw_vector, diagnostics,
    problems)`` where ``problems`` is empty for a valid-shaped vector and holds
    the registered invalid class otherwise. A malformed or absent vector still
    yields diagnostics describing exactly what was seen.
    """

    if not isinstance(probabilities, Mapping) or not probabilities:
        return {}, _malformed_diagnostics(0, "missing_probabilities"), ["missing_probabilities"]

    raw = _safe_vector(probabilities)
    option_count = len(probabilities)
    identity_ok = set(probabilities) == set(option_ids)

    numeric = all(_is_number(value) for value in probabilities.values())
    finite = numeric and all(math.isfinite(float(value)) for value in probabilities.values())
    nonnegative = numeric and all(float(value) >= 0 for value in probabilities.values())

    if not finite:
        return raw, _malformed_diagnostics(option_count, "non_finite_probability", all_finite=False,
                                           all_nonnegative=nonnegative, raw_vector=raw), \
            ["non_finite_probability"]

    values = {str(key): float(value) for key, value in probabilities.items()}
    total = sum(values.values())
    deviation = total - 1.0
    absolute = abs(deviation)
    peak = max(values.values())
    raw_argmax = tuple(sorted(option_id for option_id, value in values.items() if value == peak))

    problems: list[str] = []
    if not identity_ok:
        problems.append("mismatched_option_set")
    if not nonnegative:
        problems.append("negative_probability")
    elif total <= 0:
        problems.append("empty_distribution")
    shape_valid = not problems
    tier = classify_normalization(absolute) if shape_valid else "malformed"
    if shape_valid and tier == "not_normalized_suspect":
        problems.append("not_normalized_suspect")
    elif shape_valid and tier == "not_normalized_hard":
        problems.append("not_normalized_hard")

    normalized: dict[str, float] | None = None
    adjustment: float | None = None
    entropy_raw: float | None = None
    entropy_normalized: float | None = None
    argmax_preserved: bool | None = None
    if total > 0:
        normalized = {option_id: value / total for option_id, value in values.items()}
        argmax_preserved = _argmax_preserved(raw_argmax, normalized)
        adjustment = max(abs(normalized[option_id] - values[option_id]) for option_id in values)
        entropy_raw = entropy_bits(values)
        entropy_normalized = entropy_bits(normalized)

    if shape_valid and tier == "complete_renormalized" and argmax_preserved is False:
        problems.append("argmax_shifted_on_renormalization")
        shape_valid = False
        tier = "malformed"
    # Every accepted vector is rescaled by its raw sum before any metric, so the
    # flag is true for both accepted tiers and false for suspect/hard/malformed.
    renormalized = shape_valid and tier in {"exact", "complete_renormalized"}

    diagnostics = ChoiceVectorDiagnostics(
        option_count=option_count,
        raw_probability_sum=total,
        signed_normalization_deviation=deviation,
        absolute_normalization_deviation=absolute,
        minimum_probability=min(values.values()),
        maximum_probability=peak,
        zero_count=sum(1 for value in values.values() if value == 0.0),
        all_finite=True,
        all_nonnegative=nonnegative,
        shape_valid=shape_valid,
        invalid_classes=tuple(problems),
        raw_argmax_set=raw_argmax,
        normalization_tier=tier,
        renormalized=renormalized,
        argmax_preserved=argmax_preserved,
        normalization_adjustment=adjustment,
        entropy_raw_bits=entropy_raw,
        entropy_normalized_bits=entropy_normalized,
    )
    return raw, diagnostics, problems


def normalized_metric_vector(probabilities: Mapping[str, Any],
                             diagnostics: ChoiceVectorDiagnostics,
                             problems: Sequence[str]) -> dict[str, float]:
    """Return the single metric vector for an accepted response.

    Every accepted vector -- ``exact`` as well as ``complete_renormalized`` -- is
    divided by its raw sum, so the downstream invariant is unambiguous: all
    metrics are computed from ``p_raw / sum(p_raw)``. Invalid vectors return an
    empty mapping.
    """

    if not diagnostics.shape_valid or problems:
        return {}
    total = diagnostics.raw_probability_sum
    if total is None or total <= 0:
        return {}
    return {str(key): float(value) / total for key, value in probabilities.items()}


def entropy_bits(probabilities: Mapping[str, float]) -> float:
    return -sum(float(value) * math.log2(float(value)) for value in probabilities.values()
                if _is_number(value) and float(value) > 0)


def brier_score(probabilities: Mapping[str, float], target_id: str) -> float:
    """Multi-class Brier score against the one-hot target, over the option set."""

    return sum((float(value) - (1.0 if option_id == target_id else 0.0)) ** 2
               for option_id, value in probabilities.items())


def log_loss(probabilities: Mapping[str, float], target_id: str) -> float | None:
    probability = float(probabilities.get(target_id, 0.0))
    if probability <= 0:
        return None
    return -math.log(probability)


def distribution_metrics(probabilities: Mapping[str, float], *, target_id: str,
                         feasible_set: Sequence[str]) -> dict[str, Any]:
    """Metrics computed from the single vector permitted by the v2 policy."""

    if not probabilities:
        return {"entropy_bits": None, "p_target": None, "feasible_mass": None,
                "brier_score": None, "log_loss": None}
    return {
        "entropy_bits": entropy_bits(probabilities),
        "p_target": float(probabilities.get(target_id, 0.0)),
        "feasible_mass": sum(float(probabilities.get(option, 0.0)) for option in feasible_set),
        "brier_score": brier_score(probabilities, target_id),
        "log_loss": log_loss(probabilities, target_id),
    }


@dataclass(frozen=True)
class ChoiceResponseV2:
    status: str
    probabilities: Mapping[str, float]
    raw_probabilities: Mapping[str, Any]
    selected_option_id: str | None
    confidence: float | None
    model: str
    version: str
    usage: Mapping[str, Any]
    request_hash: str
    error_class: str | None = None
    normalization_tier: str = "malformed"
    renormalized: bool = False
    diagnostics: ChoiceVectorDiagnostics | None = None


def jev_choice_protocol_key_v2(*, model: str = JEV_DEFAULT_MODEL,
                               endpoint: str = JEV_SYSTEMONE_ENDPOINT,
                               max_retries: int = JEV_MAX_RETRIES,
                               instructions: str = JEV_CHOICE_INSTRUCTIONS,
                               question_id: str = JEV_QUESTION_ID) -> str:
    """Additive v2 Jev protocol key. v1 keys can never collide with it."""

    components = {
        "codec_version": JEV_CHOICE_V2_CODEC_VERSION,
        "endpoint": endpoint,
        "requested_model": model,
        "resolved_model_policy": jc.JEV_CHOICE_RESOLVED_MODEL_POLICY,
        "state_schema": jc.JEV_CHOICE_STATE_SCHEMA,
        "instructions": instructions,
        "criteria_policy": jc.JEV_CHOICE_CRITERIA_POLICY,
        "question_id": question_id,
        "option_id_policy": jc.JEV_CHOICE_OPTION_ID_POLICY,
        "normalization_policy": {
            "capture_then_judge": True,
            "exact_deviation_tolerance": EXACT_DEVIATION_TOLERANCE,
            "primary_acceptance_bound": PRIMARY_ACCEPTANCE_BOUND,
            "quantization_bound": QUANTIZATION_BOUND,
            "hard_deviation_ceiling": HARD_DEVIATION_CEILING,
            "boundary_epsilon": NORMALIZATION_BOUNDARY_EPSILON,
            "renormalize_near_normalized": True,
            "normalize_all_accepted_vectors": True,
            "metric_vector": "p_raw / sum(p_raw)",
            "argmax_preservation_required": True,
        },
        "max_retries": max_retries,
        "retryable_statuses": sorted(JEV_RETRYABLE_STATUSES),
    }
    digest = hashlib.sha256(json.dumps(components, sort_keys=True).encode("utf-8")).hexdigest()
    return JEV_V2_PROTOCOL_KEY_PREFIX + digest


def is_jev_v2_protocol_key(key: Any) -> bool:
    return isinstance(key, str) and key.startswith(JEV_V2_PROTOCOL_KEY_PREFIX)


def is_any_jev_protocol_key(key: Any) -> bool:
    return is_jev_v2_protocol_key(key) or jc.is_jev_protocol_key(key)


def assert_single_jev_v2_protocol_key(records: Sequence[Mapping[str, Any]]) -> str:
    """Refuse mixed or v1 keys so v2 artifacts cannot be pooled with v1."""

    keys = [record.get("protocol_key") for record in records]
    if not keys:
        raise ValueError("no records supplied")
    if any(key is None for key in keys):
        raise ValueError("record missing protocol_key")
    unique = sorted({str(key) for key in keys})
    if len(unique) != 1:
        raise ValueError(f"multiple protocol keys present: {unique}")
    key = unique[0]
    if not is_jev_v2_protocol_key(key):
        raise ValueError(f"refusing non-v2 protocol key: {key}")
    return key


def _invalid_v2(model: str, request_hash: str, error_class: str,
                *, diagnostics: ChoiceVectorDiagnostics | None = None,
                raw_probabilities: Mapping[str, Any] | None = None) -> ChoiceResponseV2:
    if error_class not in JEV_V2_INVALID_CLASSES:
        raise ValueError(f"unknown v2 invalid-response class: {error_class}")
    tier = "malformed"
    if diagnostics is not None:
        tier = diagnostics.normalization_tier
    return ChoiceResponseV2(
        "invalid", {}, dict(raw_probabilities or {}), None, None, model,
        JEV_CHOICE_V2_CODEC_VERSION, {}, request_hash, error_class, tier,
        bool(diagnostics.renormalized) if diagnostics is not None else False, diagnostics)


class JevChoiceAdapterV2(JevChoiceAdapter):
    """v2 adapter: capture-then-judge, with v1 transport and state building intact."""

    provider = "jev"
    version = JEV_CHOICE_V2_CODEC_VERSION

    def complete_with_raw(self, state: jc.ChoiceState) -> tuple[ChoiceResponseV2, Mapping[str, Any] | None]:
        if len(state.options) > self.max_options:
            return _invalid_v2(self.model, state.request_hash, "oversized_option_set"), None
        ids = [option.option_id for option in state.options]
        if len(set(ids)) != len(ids):
            return _invalid_v2(self.model, state.request_hash, "duplicate_option_ids"), None
        if not ids:
            return _invalid_v2(self.model, state.request_hash, "empty_distribution"), None
        try:
            raw = self.client.complete(self.build_request(state))
        except jc.JevCredentialError:
            return _invalid_v2(self.model, state.request_hash, "missing_credentials"), None
        except jc.JevProviderRejection:
            return _invalid_v2(self.model, state.request_hash, "provider_rejected"), None
        except jc.JevResponseError:
            return _invalid_v2(self.model, state.request_hash, "malformed_response"), None
        except jc.JevTransportError:
            return _invalid_v2(self.model, state.request_hash, "transport_error"), None
        except Exception:
            return _invalid_v2(self.model, state.request_hash, "transport_error"), None
        return self.parse(state, raw), raw

    def complete(self, state: jc.ChoiceState) -> ChoiceResponseV2:
        response, _ = self.complete_with_raw(state)
        return response

    def parse(self, state: jc.ChoiceState, raw: Mapping[str, Any]) -> ChoiceResponseV2:
        if not isinstance(raw, Mapping):
            return _invalid_v2(self.model, state.request_hash, "malformed_response")
        if "answers" not in raw:
            if "detail" in raw or "error_type" in raw:
                return _invalid_v2(self.model, state.request_hash, "provider_rejected")
            return _invalid_v2(self.model, state.request_hash, "response_not_evaluated")
        answers = raw.get("answers")
        if not isinstance(answers, Mapping):
            return _invalid_v2(self.model, state.request_hash, "malformed_response")
        if state.question_id not in answers:
            return _invalid_v2(self.model, state.request_hash, "missing_answer")
        if set(answers) != {state.question_id}:
            return _invalid_v2(self.model, state.request_hash, "extra_answer")
        answer = answers[state.question_id]
        if not isinstance(answer, Mapping):
            return _invalid_v2(self.model, state.request_hash, "malformed_response")
        if answer.get("type") != "choice":
            return _invalid_v2(self.model, state.request_hash, "wrong_answer_kind")

        expected = [option.option_id for option in state.options]
        raw_vector, diagnostics, problems = diagnose_probability_vector(
            answer.get("probabilities"), expected)
        if problems:
            return _invalid_v2(self.model, state.request_hash, problems[0],
                               diagnostics=diagnostics, raw_probabilities=raw_vector)
        used = normalized_metric_vector(answer["probabilities"], diagnostics, problems)
        if not used:
            return _invalid_v2(self.model, state.request_hash, "malformed_response",
                               diagnostics=diagnostics, raw_probabilities=raw_vector)

        # Selection is validated against the normalized metric vector that every
        # downstream metric uses, then separately confirmed to agree with the raw
        # argmax so the two views cannot diverge silently.
        used_peak = max(used.values())
        used_argmax = {option_id for option_id, value in used.items() if value == used_peak}
        if used_argmax != set(diagnostics.raw_argmax_set):
            return _invalid_v2(self.model, state.request_hash, "argmax_shifted_on_renormalization",
                               diagnostics=diagnostics, raw_probabilities=raw_vector)
        selected = answer.get("choice")
        if not isinstance(selected, str) or selected not in set(expected) or selected not in used_argmax:
            return _invalid_v2(self.model, state.request_hash, "unknown_selection",
                               diagnostics=diagnostics, raw_probabilities=raw_vector)
        confidence = answer.get("confidence")
        if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                or not math.isfinite(confidence) or confidence < 0 or confidence > 1):
            return _invalid_v2(self.model, state.request_hash, "invalid_confidence",
                               diagnostics=diagnostics, raw_probabilities=raw_vector)
        usage = raw.get("usage")
        if not isinstance(usage, Mapping) or not all(
                isinstance(usage.get(name), int) and not isinstance(usage.get(name), bool)
                for name in ("input_tokens", "output_tokens")):
            return _invalid_v2(self.model, state.request_hash, "malformed_usage",
                               diagnostics=diagnostics, raw_probabilities=raw_vector)
        resolved_model = raw.get("model")
        if not isinstance(resolved_model, str) or resolved_model != self.model:
            return _invalid_v2(self.model, state.request_hash, "model_drift",
                               diagnostics=diagnostics, raw_probabilities=raw_vector)
        return ChoiceResponseV2(
            "complete", used, raw_vector, selected, float(confidence), resolved_model,
            self.version, dict(usage), state.request_hash, None, diagnostics.normalization_tier,
            diagnostics.renormalized, diagnostics)

    def map_submission(self, response: ChoiceResponseV2) -> str | None:
        return response.selected_option_id if response.status == "complete" else None

    def record(self, state: jc.ChoiceState, response: ChoiceResponseV2) -> dict[str, Any]:
        protocol_key = jev_choice_protocol_key_v2(
            model=self.model,
            endpoint=getattr(self.client, "endpoint", JEV_SYSTEMONE_ENDPOINT),
            max_retries=getattr(self.client, "max_retries", JEV_MAX_RETRIES),
            instructions=self.instructions,
            question_id=self.question_id,
        )
        diagnostics = response.diagnostics.to_dict() if response.diagnostics is not None else None
        return {
            "codec_version": self.version,
            "protocol_key": protocol_key,
            "instance_id": state.instance_id,
            "agent_id": state.agent_id,
            "condition": state.condition,
            "question_id": state.question_id,
            "option_count": len(state.options),
            "request_hash": state.request_hash,
            "status": response.status,
            "error_class": response.error_class,
            "normalization_tier": response.normalization_tier,
            "renormalized": response.renormalized,
            "resolved_model": response.model,
            "selected_option_id": response.selected_option_id,
            "probabilities": dict(response.probabilities),
            "raw_probabilities": dict(response.raw_probabilities),
            "probability_sum": round(sum(response.probabilities.values()), 9),
            "raw_probability_sum": (diagnostics or {}).get("raw_probability_sum"),
            "probability_diagnostics": diagnostics,
            "confidence": response.confidence,
            "usage": dict(response.usage),
            "physical_attempts": getattr(self.client, "physical_attempts", None),
            "endpoint": getattr(self.client, "endpoint", None),
            "raw_response_retained": False,
        }


__all__ = [
    "JEV_CHOICE_V2_CODEC_VERSION", "JEV_V2_PROTOCOL_KEY_PREFIX", "EXACT_DEVIATION_TOLERANCE",
    "PRIMARY_ACCEPTANCE_BOUND", "QUANTIZATION_BOUND", "HARD_DEVIATION_CEILING",
    "SENSITIVITY_GRID", "NORMALIZATION_BOUNDARY_EPSILON", "NORMALIZATION_TIERS",
    "JEV_V2_INVALID_CLASSES", "ChoiceVectorDiagnostics", "ChoiceResponseV2",
    "JevChoiceAdapterV2", "JevChoiceClient", "assert_single_jev_v2_protocol_key",
    "brier_score", "classify_normalization", "diagnose_probability_vector",
    "distribution_metrics", "entropy_bits", "is_any_jev_protocol_key", "is_jev_v2_protocol_key",
    "jev_choice_protocol_key_v2", "json_safe", "log_loss", "normalized_metric_vector",
]
