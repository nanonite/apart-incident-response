"""E2 — matched real/placebo/null replay schema and form identity (#183).

Offline. One replay event freezes a single pre-read Jev Choice state C and stores
nested real, inert-placebo, and null branch results: full probability vectors,
entropy, target probability, feasible-set mass, validity, model, usage,
request/state hashes, prompt_form_id, target, objective I_m, and writer/reader/
exposure provenance. Validation fails closed on unmatched states, mixed
protocols, duplicates, malformed vectors, and answer-key leakage.

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
INVALID_REPLAY_PROBLEMS = frozenset({
    "missing_branch",
    "unknown_branch",
    "unmatched_state",
    "mixed_protocol",
    "duplicate_event",
    "malformed_vector",
    "non_finite_probability",
    "negative_probability",
    "not_normalized",
    "option_identity_mismatch",
    "answer_key_leakage",
    "target_not_in_options",
    "feasible_set_not_in_options",
    "missing_provenance",
    "non_jev_protocol_key",
    "stored_metric_mismatch",
    "form_hash_mismatch",
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


def entropy_bits(probabilities: Mapping[str, float]) -> float:
    return -sum(float(value) * math.log2(float(value)) for value in probabilities.values()
                if float(value) > 0)


def _vector_problems(probabilities: Any, option_ids: Sequence[str]) -> list[str]:
    problems: list[str] = []
    if not isinstance(probabilities, Mapping) or not probabilities:
        return ["malformed_vector"]
    if set(probabilities) != set(option_ids):
        problems.append("option_identity_mismatch")
    values = list(probabilities.values())
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
           for value in values):
        problems.append("non_finite_probability")
    if any(float(value) < 0 for value in values):
        problems.append("negative_probability")
    elif abs(sum(float(value) for value in values) - 1.0) > NORMALIZATION_TOLERANCE:
        problems.append("not_normalized")
    return problems


def make_branch(branch: str, *, status: str, probabilities: Mapping[str, float] | None = None,
                option_ids: Sequence[str], target_id: str, feasible_set: Sequence[str],
                state_hash: str, protocol_key: str | None = None, resolved_model: str | None = None,
                usage: Mapping[str, Any] | None = None, request_hash: str | None = None,
                error_class: str | None = None) -> dict[str, Any]:
    """Build one branch record. Derived guards are computed from the vector."""

    probabilities = dict(probabilities or {})
    feasible_mass = sum(float(probabilities.get(option, 0.0)) for option in feasible_set) \
        if status == "complete" else None
    return {
        "branch": branch,
        "status": status,
        "error_class": error_class,
        "probabilities": probabilities,
        "entropy_bits": entropy_bits(probabilities) if status == "complete" else None,
        "p_target": float(probabilities.get(target_id, 0.0)) if status == "complete" else None,
        "feasible_mass": feasible_mass,
        "resolved_model": resolved_model,
        "usage": dict(usage or {}),
        "request_hash": request_hash,
        "protocol_key": protocol_key,
        "state_hash": state_hash,
    }


def build_event(*, event_id: str, instance_id: str, condition: str, prompt_form_id_value: str,
                pre_read_state: Mapping[str, Any], option_ids: Sequence[str], target_id: str,
                feasible_set: Sequence[str], i_m_bits: float, message: Mapping[str, Any],
                branches: Mapping[str, Mapping[str, Any]],
                request_body: Mapping[str, Any] | None = None) -> dict[str, Any]:
    event = {
        "schema_version": JEV_REPLAY_VERSION,
        "event_id": event_id,
        "instance_id": instance_id,
        "condition": condition,
        "prompt_form_id": prompt_form_id_value,
        "pre_read_state": dict(pre_read_state),
        "option_ids": list(option_ids),
        "target_id": target_id,
        "feasible_set": list(feasible_set),
        "i_m_bits": float(i_m_bits),
        "message": dict(message),
        "branches": {branch: dict(record) for branch, record in branches.items()},
    }
    if request_body is not None:
        event["request_body"] = dict(request_body)
    return event


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


def validate_event(event: Mapping[str, Any]) -> list[str]:
    """Return all validation problems (empty = a valid event).

    Recomputes entropy, target probability and feasible-set mass from each
    complete branch's probability vector and verifies the prompt-form and state
    hashes against the recorded pre-read request, so stored metrics cannot be
    trusted without matching vectors.
    """

    problems: list[str] = []
    branches = event.get("branches")
    option_ids = list(event.get("option_ids", []))
    target = str(event.get("target_id", ""))
    feasible_set = list(event.get("feasible_set", []))
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

    expected_state_hash = canonical_hash(event.get("pre_read_state", {}))
    state_hashes = {record.get("state_hash") for record in branches.values()}
    if len(state_hashes) != 1 or None in state_hashes or expected_state_hash not in state_hashes:
        problems.append("unmatched_state")
    request_body = event.get("request_body")
    if isinstance(request_body, Mapping) and event.get("prompt_form_id") != prompt_form_id(request_body):
        problems.append("form_hash_mismatch")
    if not isinstance(event.get("prompt_form_id"), str) or not event.get("prompt_form_id"):
        problems.append("unmatched_state")

    protocol_keys = {record.get("protocol_key") for record in branches.values()
                     if record.get("status") == "complete"}
    if len(protocol_keys) > 1:
        problems.append("mixed_protocol")
    for key in protocol_keys:
        if not jc.is_jev_protocol_key(key):
            problems.append("non_jev_protocol_key")
            break

    for branch, record in branches.items():
        if record.get("status") != "complete":
            continue
        probabilities = record.get("probabilities")
        for problem in _vector_problems(probabilities, option_ids):
            if problem not in problems:
                problems.append(problem)
        if isinstance(probabilities, Mapping) and probabilities and set(probabilities) == set(option_ids):
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
    message = event.get("message") or {}
    if not message.get("writer_id") or not message.get("reader_id") or not message.get("exposure_id"):
        problems.append("missing_provenance")
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
        branches = event.get("branches") or {}
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
        real = branches.get("real", {})
        placebo = branches.get("placebo", {})
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
            if record.get("status") == "complete"}
    if not keys:
        raise ValueError("mixed_protocol: no complete branches")
    if len(keys) != 1:
        raise ValueError(f"mixed_protocol: {sorted(str(key) for key in keys)}")
    key = next(iter(keys))
    if not jc.is_jev_protocol_key(key):
        raise ValueError(f"non_jev_protocol_key: {key}")
    return str(key)


__all__ = [
    "JEV_REPLAY_VERSION", "BRANCHES", "INVALID_REPLAY_PROBLEMS", "canonical_hash",
    "pre_read_request_body", "prompt_form_id", "entropy_bits", "make_branch", "build_event",
    "validate_event", "summarize_events", "assert_no_duplicate_events", "assert_single_protocol",
]
