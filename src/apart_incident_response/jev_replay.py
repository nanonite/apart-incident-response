"""E2 — matched real/placebo/null replay schema and form identity (#183).

Offline. One replay event freezes a single pre-read Jev Choice state C and stores
nested real, inert-placebo, and null branch results: full probability vectors,
entropy, target probability, feasible-set mass, validity, model, usage,
request/state hashes, prompt_form_id, target, objective I_m, and writer/reader/
exposure provenance. Validation fails closed on unmatched states, mixed
protocols, duplicates, malformed vectors, answer-key leakage, and any missing or
inconsistent metric, model, usage, request body, or placebo descriptor. It never
raises on malformed input; it returns problem codes.

No API calls; J3 artifacts are only read as a method regression elsewhere.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from typing import Any, Mapping, Sequence

from . import jev_choice as jc


JEV_REPLAY_VERSION = "jev-replay-v1"
BRANCHES = ("real", "placebo", "null")
NORMALIZATION_TOLERANCE = jc.NORMALIZATION_TOLERANCE
REQUIRED_BRANCH_METRICS = ("entropy_bits", "p_target", "feasible_mass")
REQUIRED_USAGE = ("input_tokens", "output_tokens")

#: Frozen placebo construction and model-visible wording. The placebo re-presents
#: one of the receiver's own pre-read clues as a peer claim, so it is already
#: known and carries no task information (I_m = 0). The synthetic origin is
#: recorded outside the model-visible message.
PLACEBO_CONSTRUCTION = "re-present one of the receiver's own pre-read private clues as a peer claim"
PLACEBO_WORDING_TEMPLATE = "peer_clue: {claim}"
PLACEBO_SYNTHETIC = True

INVALID_REPLAY_PROBLEMS = frozenset({
    "missing_branch", "unknown_branch", "malformed_branch", "unmatched_state", "mixed_protocol",
    "duplicate_event", "malformed_vector", "non_finite_probability", "negative_probability",
    "not_normalized", "option_identity_mismatch", "answer_key_leakage", "target_not_in_options",
    "feasible_set_not_in_options", "missing_provenance", "non_jev_protocol_key",
    "stored_metric_mismatch", "form_hash_mismatch", "missing_request_body",
    "request_body_state_mismatch", "request_body_options_mismatch", "request_body_model_mismatch",
    "missing_model", "branch_model_mismatch", "missing_branch_metric", "missing_usage",
    "missing_branch_request_hash", "ineligible_real_message", "placebo_not_inert",
    "placebo_wording_mismatch",
})


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def pre_read_request_body(*, state: Mapping[str, Any], question_id: str, instructions: str,
                          option_ids: Sequence[str], model: str) -> dict[str, Any]:
    """The model-visible pre-read request body, with no message attached."""

    return {"model": model, "state": dict(state),
            "questions": {question_id: {"type": "choice", "instructions": instructions,
                                        "criteria": {option_id: None for option_id in option_ids}}}}


def prompt_form_id(request_body: Mapping[str, Any]) -> str:
    """Hash the model-visible pre-read body; ties replicate the same form."""

    return canonical_hash(request_body)


def serialize_placebo_message(claim: str) -> str:
    """Frozen model-visible placebo wording for an already-known receiver clue."""

    return PLACEBO_WORDING_TEMPLATE.format(claim=claim)


def placebo_wording_hash() -> str:
    return canonical_hash({"construction": PLACEBO_CONSTRUCTION, "wording": PLACEBO_WORDING_TEMPLATE})


def entropy_bits(probabilities: Mapping[str, float]) -> float:
    return -sum(float(value) * math.log2(float(value)) for value in probabilities.values()
                if _is_number(value) and float(value) > 0)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _vector_problems(probabilities: Any, option_ids: Sequence[str]) -> list[str]:
    if not isinstance(probabilities, Mapping) or not probabilities:
        return ["malformed_vector"]
    problems: list[str] = []
    if set(probabilities) != set(option_ids):
        problems.append("option_identity_mismatch")
    if not all(_is_number(value) for value in probabilities.values()):
        problems.append("non_finite_probability")
        return problems
    values = [float(value) for value in probabilities.values()]
    if any(not math.isfinite(value) for value in values):
        problems.append("non_finite_probability")
    if any(value < 0 for value in values):
        problems.append("negative_probability")
    elif abs(sum(values) - 1.0) > NORMALIZATION_TOLERANCE:
        problems.append("not_normalized")
    return problems


def make_branch(branch: str, *, status: str, probabilities: Mapping[str, float] | None = None,
                option_ids: Sequence[str], target_id: str, feasible_set: Sequence[str],
                state_hash: str, protocol_key: str | None = None, resolved_model: str | None = None,
                usage: Mapping[str, Any] | None = None, request_hash: str | None = None,
                error_class: str | None = None) -> dict[str, Any]:
    """Build one branch record. Derived guards are computed from the vector, and no
    exception is raised on a malformed vector (metrics become None)."""

    probabilities = dict(probabilities or {})
    metrics_ok = (status == "complete" and not _vector_problems(probabilities, option_ids))
    return {
        "branch": branch,
        "status": status,
        "error_class": error_class,
        "probabilities": probabilities,
        "entropy_bits": entropy_bits(probabilities) if metrics_ok else None,
        "p_target": float(probabilities.get(target_id, 0.0)) if metrics_ok else None,
        "feasible_mass": sum(float(probabilities.get(option, 0.0)) for option in feasible_set)
        if metrics_ok else None,
        "resolved_model": resolved_model,
        "usage": dict(usage or {}),
        "request_hash": request_hash,
        "protocol_key": protocol_key,
        "state_hash": state_hash,
    }


def build_event(*, event_id: str, instance_id: str, condition: str, model: str,
                prompt_form_id_value: str, pre_read_state: Mapping[str, Any], option_ids: Sequence[str],
                target_id: str, feasible_set: Sequence[str], i_m_bits: float, message: Mapping[str, Any],
                placebo: Mapping[str, Any], branches: Mapping[str, Mapping[str, Any]],
                request_body: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": JEV_REPLAY_VERSION,
        "event_id": event_id,
        "instance_id": instance_id,
        "condition": condition,
        "model": model,
        "prompt_form_id": prompt_form_id_value,
        "pre_read_state": dict(pre_read_state),
        "request_body": dict(request_body),
        "option_ids": list(option_ids),
        "target_id": target_id,
        "feasible_set": list(feasible_set),
        "i_m_bits": float(i_m_bits),
        "message": dict(message),
        "placebo": dict(placebo),
        "branches": {branch: dict(record) for branch, record in branches.items()},
    }


def _leakage_problems(event: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    state_json = json.dumps(event.get("pre_read_state", {}), sort_keys=True)
    target = str(event.get("target_id"))
    if target and target in state_json:
        problems.append("answer_key_leakage")
    for marker in ("joint_solutions", "joint_candidate", "joint_solution"):
        if marker in state_json:
            problems.append("answer_key_leakage")
            break
    return problems


def _request_body_problems(event: Mapping[str, Any], option_ids: Sequence[str]) -> list[str]:
    problems: list[str] = []
    body = event.get("request_body")
    if not isinstance(body, Mapping):
        return ["missing_request_body"]
    if body.get("model") != event.get("model"):
        problems.append("request_body_model_mismatch")
    if canonical_hash(body.get("state", {})) != canonical_hash(event.get("pre_read_state", {})):
        problems.append("request_body_state_mismatch")
    questions = body.get("questions")
    if not isinstance(questions, Mapping) or len(questions) != 1:
        problems.append("request_body_options_mismatch")
    else:
        criteria = next(iter(questions.values())).get("criteria") if isinstance(
            next(iter(questions.values())), Mapping) else None
        if not isinstance(criteria, Mapping) or set(criteria) != set(option_ids):
            problems.append("request_body_options_mismatch")
    return problems


def _message_problems(event: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    message = event.get("message") or {}
    if not message.get("writer_id") or not message.get("reader_id") or not message.get("exposure_id"):
        problems.append("missing_provenance")
    if not isinstance(message.get("owner_exact"), bool) or message.get("owner_exact") is not True:
        problems.append("ineligible_real_message")
    if not _is_number(message.get("i_m_bits")) or float(message.get("i_m_bits")) < 0:
        problems.append("missing_provenance")
    placebo = event.get("placebo") or {}
    if placebo.get("synthetic") is not PLACEBO_SYNTHETIC or placebo.get("i_m_bits") != 0:
        problems.append("placebo_not_inert")
    if placebo.get("construction") != PLACEBO_CONSTRUCTION \
            or placebo.get("wording") != PLACEBO_WORDING_TEMPLATE:
        problems.append("placebo_wording_mismatch")
    return problems


def validate_event(event: Mapping[str, Any]) -> list[str]:
    """Return all validation problems (empty = a valid event); never raises.

    Recomputes entropy, target probability and feasible-set mass from each
    complete branch vector, cross-checks the mandatory request body against the
    frozen pre-read state/options/model, and requires branch metrics, resolved
    model, usage, request hash and provenance.
    """

    if not isinstance(event, Mapping):
        return ["malformed_event"]
    problems: list[str] = []
    branches = event.get("branches")
    option_ids = list(event.get("option_ids", []))
    target = str(event.get("target_id", ""))
    feasible_set = list(event.get("feasible_set", []))
    if not isinstance(event.get("model"), str) or not event.get("model"):
        problems.append("missing_model")
    if not isinstance(branches, Mapping):
        return ["missing_branch"]
    for branch in BRANCHES:
        if branch not in branches:
            problems.append("missing_branch")
    for branch in branches:
        if branch not in BRANCHES:
            problems.append("unknown_branch")
    if target and target not in option_ids:
        problems.append("target_not_in_options")
    if not set(feasible_set) <= set(option_ids) or not feasible_set:
        problems.append("feasible_set_not_in_options")
    problems.extend(_leakage_problems(event))
    problems.extend(_request_body_problems(event, option_ids))
    problems.extend(_message_problems(event))

    expected_state_hash = canonical_hash(event.get("pre_read_state", {}))
    state_hashes = {record.get("state_hash") for record in branches.values()
                    if isinstance(record, Mapping)}
    if len(state_hashes) != 1 or None in state_hashes or expected_state_hash not in state_hashes:
        problems.append("unmatched_state")
    body = event.get("request_body")
    if isinstance(body, Mapping) and event.get("prompt_form_id") != prompt_form_id(body):
        problems.append("form_hash_mismatch")
    if not isinstance(event.get("prompt_form_id"), str) or not event.get("prompt_form_id"):
        problems.append("unmatched_state")

    protocol_keys = {record.get("protocol_key") for record in branches.values()
                     if isinstance(record, Mapping) and record.get("status") == "complete"}
    if len(protocol_keys) > 1:
        problems.append("mixed_protocol")
    for key in protocol_keys:
        if not jc.is_jev_protocol_key(key):
            problems.append("non_jev_protocol_key")
            break

    for branch, record in branches.items():
        if not isinstance(record, Mapping):
            problems.append("malformed_branch")
            continue
        if record.get("status") != "complete":
            continue
        probabilities = record.get("probabilities")
        for problem in _vector_problems(probabilities, option_ids):
            if problem not in problems:
                problems.append(problem)
        for name in REQUIRED_BRANCH_METRICS:
            if record.get(name) is None or not _is_number(record.get(name)):
                problems.append("missing_branch_metric")
                break
        if record.get("resolved_model") != event.get("model"):
            problems.append("branch_model_mismatch")
        usage = record.get("usage")
        if not isinstance(usage, Mapping) or not all(
                isinstance(usage.get(name), int) and not isinstance(usage.get(name), bool)
                for name in REQUIRED_USAGE):
            problems.append("missing_usage")
        if not isinstance(record.get("request_hash"), str) or not record.get("request_hash"):
            problems.append("missing_branch_request_hash")
        if not _vector_problems(probabilities, option_ids):
            expected_metrics = {
                "entropy_bits": entropy_bits(probabilities),
                "p_target": float(probabilities.get(target, 0.0)),
                "feasible_mass": sum(float(probabilities.get(option, 0.0)) for option in feasible_set),
            }
            for name, expected in expected_metrics.items():
                stored = record.get(name)
                if stored is not None and abs(float(stored) - expected) > 1e-9:
                    if "stored_metric_mismatch" not in problems:
                        problems.append("stored_metric_mismatch")
    return problems


def summarize_events(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_form: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"planned": 0, "attempted": 0, "valid": 0, "complete_pairs": 0, "incomplete_pairs": 0,
                 "branches": {branch: {"attempted": 0, "valid": 0, "failed": 0, "unattempted": 0}
                              for branch in BRANCHES}})
    invalid = []
    for event in events:
        form = str(event.get("prompt_form_id"))
        row = by_form[form]
        row["planned"] += 1
        branches = event.get("branches") if isinstance(event.get("branches"), Mapping) else {}
        any_attempted = False
        for branch in BRANCHES:
            record = branches.get(branch)
            status = record.get("status") if isinstance(record, Mapping) else None
            counts = row["branches"][branch]
            if record is None or status in (None, "unattempted"):
                counts["unattempted"] += 1
            elif status == "complete":
                counts["attempted"] += 1
                counts["valid"] += 1
                any_attempted = True
            else:
                counts["attempted"] += 1
                counts["failed"] += 1
                any_attempted = True
        if any_attempted:
            row["attempted"] += 1
        problems = validate_event(event)
        if not problems:
            row["valid"] += 1
        else:
            invalid.append({"event_id": event.get("event_id"), "problems": sorted(set(problems))})
        real = branches.get("real") or {}
        placebo = branches.get("placebo") or {}
        if not problems and real.get("status") == "complete" and placebo.get("status") == "complete" \
                and real.get("state_hash") == placebo.get("state_hash"):
            row["complete_pairs"] += 1
        elif not problems:
            row["incomplete_pairs"] += 1
    return {
        "schema_version": JEV_REPLAY_VERSION,
        "events": len(events),
        "forms": len(by_form),
        "by_form": dict(sorted(by_form.items())),
        "invalid": invalid,
    }


def assert_no_duplicate_events(events: Sequence[Mapping[str, Any]]) -> None:
    seen_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    for event in events:
        event_id = str(event.get("event_id"))
        if event_id in seen_ids:
            raise ValueError(f"duplicate_event: {event_id}")
        seen_ids.add(event_id)
        key = (str(event.get("prompt_form_id")), event_id)
        if key in seen_pairs:
            raise ValueError(f"duplicate_event: {key}")
        seen_pairs.add(key)


def assert_single_protocol(events: Sequence[Mapping[str, Any]]) -> str:
    keys = {record.get("protocol_key") for event in events
            for record in (event.get("branches") or {}).values()
            if isinstance(record, Mapping) and record.get("status") == "complete"}
    if not keys:
        raise ValueError("mixed_protocol: no complete branches")
    if len(keys) != 1:
        raise ValueError(f"mixed_protocol: {sorted(str(key) for key in keys)}")
    key = next(iter(keys))
    if not jc.is_jev_protocol_key(key):
        raise ValueError(f"non_jev_protocol_key: {key}")
    return str(key)


__all__ = [
    "JEV_REPLAY_VERSION", "BRANCHES", "REQUIRED_BRANCH_METRICS", "INVALID_REPLAY_PROBLEMS",
    "PLACEBO_CONSTRUCTION", "PLACEBO_WORDING_TEMPLATE", "canonical_hash", "pre_read_request_body",
    "prompt_form_id", "serialize_placebo_message", "placebo_wording_hash", "entropy_bits",
    "make_branch", "build_event", "validate_event", "summarize_events", "assert_no_duplicate_events",
    "assert_single_protocol",
]
