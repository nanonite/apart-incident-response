"""E2 — matched real/placebo/null replay schema and form identity (#183).

Offline. One replay event freezes a single pre-read Jev Choice state C and stores
nested real, inert-placebo, and null branch results. Validation resolves the
generated instance from an authoritative task descriptor and checks ownership,
receiver perspective, board delivery/exposure, and objective information I_m
against it; it also reconstructs each branch's exact model-visible request and
recomputes its hash. Malformed records return problem codes and never raise.

No API calls; J3 artifacts are only read as a method regression elsewhere.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import defaultdict
from typing import Any, Mapping, Sequence

from . import jev_choice as jc
from .communication_protocol import DependenceRegime, ReasoningComplexity
from .task_families import generate_instance


JEV_REPLAY_VERSION = "jev-replay-v1"
BRANCHES = ("real", "placebo", "null")
NORMALIZATION_TOLERANCE = jc.NORMALIZATION_TOLERANCE
REQUIRED_BRANCH_METRICS = ("entropy_bits", "p_target", "feasible_mass")
REQUIRED_USAGE = ("input_tokens", "output_tokens")
I_M_TOLERANCE = 1e-9

#: One source-neutral message envelope for both the real and placebo arms; only
#: the claim content differs, so sender identity is not a model-visible contrast.
#: The real writer id and the synthetic placebo origin stay controller-side.
MESSAGE_ENVELOPE_TEMPLATE = "peer_clue: {claim}"
PLACEBO_CONSTRUCTION = ("controller-injected source-neutral re-presentation of a "
                        "receiver-already-known pre-read clue, using the same envelope as the real arm")
PLACEBO_SYNTHETIC = True
PLACEBO_ORIGIN = "controller"

INVALID_REPLAY_PROBLEMS = frozenset({
    "missing_branch", "unknown_branch", "malformed_branch", "malformed_event", "unmatched_state",
    "mixed_protocol", "malformed_vector", "non_finite_probability", "negative_probability",
    "not_normalized", "option_identity_mismatch", "answer_key_leakage", "target_not_in_options",
    "feasible_set_not_in_options", "missing_provenance", "non_jev_protocol_key",
    "stored_metric_mismatch", "form_hash_mismatch", "missing_request_body",
    "request_body_state_mismatch", "request_body_options_mismatch", "request_body_model_mismatch",
    "missing_model", "branch_model_mismatch", "missing_branch_metric", "missing_usage",
    "missing_branch_request_hash", "branch_request_mismatch", "ineligible_real_message",
    "placebo_not_inert", "placebo_wording_mismatch", "unverified_real_evidence",
    "instance_mismatch", "real_not_informative",
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
    return canonical_hash(request_body)


def serialize_message(claim: str) -> str:
    """Frozen source-neutral model-visible message envelope (real and placebo)."""

    return MESSAGE_ENVELOPE_TEMPLATE.format(claim=claim)


def serialize_placebo_message(claim: str) -> str:
    return serialize_message(claim)


def message_wording_hash() -> str:
    return canonical_hash({"envelope": MESSAGE_ENVELOPE_TEMPLATE, "placebo_origin": PLACEBO_ORIGIN})


def branch_request_body(pre_read_body: Mapping[str, Any], message_text: str | None) -> dict[str, Any]:
    """Deterministically reconstruct a branch request from the frozen pre-read body."""

    body = copy.deepcopy(dict(pre_read_body))
    state = body.setdefault("state", {})
    state["visible_messages"] = [] if message_text is None else [{"role": "peer", "text": message_text}]
    return body


def branch_message_text(event: Mapping[str, Any], branch: str) -> str | None:
    real = event.get("real_message") or {}
    placebo = event.get("placebo") or {}
    if branch == "real":
        return serialize_message(str(real.get("claim", "")))
    if branch == "placebo":
        return serialize_placebo_message(str(placebo.get("claim", "")))
    return None


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
    probabilities = dict(probabilities or {})
    metrics_ok = (status == "complete" and not _vector_problems(probabilities, option_ids))
    return {
        "branch": branch, "status": status, "error_class": error_class, "probabilities": probabilities,
        "entropy_bits": entropy_bits(probabilities) if metrics_ok else None,
        "p_target": float(probabilities.get(target_id, 0.0)) if metrics_ok else None,
        "feasible_mass": sum(float(probabilities.get(option, 0.0)) for option in feasible_set)
        if metrics_ok else None,
        "resolved_model": resolved_model, "usage": dict(usage or {}), "request_hash": request_hash,
        "protocol_key": protocol_key, "state_hash": state_hash,
    }


def build_event(*, event_id: str, instance_id: str, condition: str, model: str,
                task: Mapping[str, Any], prompt_form_id_value: str, pre_read_state: Mapping[str, Any],
                request_body: Mapping[str, Any], option_ids: Sequence[str], target_id: str,
                feasible_set: Sequence[str], i_m_bits: float, real_message: Mapping[str, Any],
                placebo: Mapping[str, Any], branches: Mapping[str, Mapping[str, Any]],
                board_log: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": JEV_REPLAY_VERSION, "event_id": event_id, "instance_id": instance_id,
        "condition": condition, "model": model, "task": dict(task),
        "prompt_form_id": prompt_form_id_value, "pre_read_state": dict(pre_read_state),
        "request_body": dict(request_body), "option_ids": list(option_ids), "target_id": target_id,
        "feasible_set": list(feasible_set), "i_m_bits": float(i_m_bits),
        "real_message": dict(real_message), "placebo": dict(placebo),
        "board_log": [dict(record) for record in board_log],
        "branches": {branch: dict(record) for branch, record in branches.items()},
    }


def resolve_instance(task: Mapping[str, Any]) -> Any:
    """Regenerate the authoritative instance from a task descriptor, or None."""

    try:
        return generate_instance(str(task["family"]), int(task["seed"]),
                                 DependenceRegime(str(task["regime"])),
                                 ReasoningComplexity(str(task["complexity"])))
    except (KeyError, TypeError, ValueError):
        return None


def _instance_problems(event: Mapping[str, Any]) -> tuple[list[str], Any]:
    task = event.get("task")
    if not isinstance(task, Mapping):
        return ["instance_mismatch"], None
    instance = resolve_instance(task)
    if instance is None:
        return ["instance_mismatch"], None
    problems: list[str] = []
    if instance.instance_id != event.get("instance_id"):
        problems.append("instance_mismatch")
    if list(event.get("option_ids", [])) != sorted(instance.solutions):
        problems.append("instance_mismatch")
    if str(event.get("target_id")) != instance.target:
        problems.append("instance_mismatch")
    agent = str(task.get("agent"))
    if agent not in {"A", "B"} or list(event.get("feasible_set", [])) != sorted(instance.private_solutions[agent]):
        problems.append("instance_mismatch")
    return problems, instance


def _real_message_problems(event: Mapping[str, Any], instance: Any) -> list[str]:
    real = event.get("real_message")
    if not isinstance(real, Mapping):
        return ["missing_provenance"]
    required = ("writer_id", "reader_id", "exposure_id", "message_id", "claim")
    if any(not real.get(name) for name in required):
        return ["missing_provenance"]
    agent = str((event.get("task") or {}).get("agent"))
    writer = str(real["writer_id"])
    reader = str(real["reader_id"])
    claim = str(real["claim"])
    message_id = str(real["message_id"])
    exposure_id = str(real["exposure_id"])
    problems: list[str] = []
    if not instance.holds_claim(writer, claim) or instance.claim_owner(claim) != writer:
        problems.append("ineligible_real_message")
    if reader != agent or reader == writer:
        problems.append("ineligible_real_message")

    log = event.get("board_log")
    if not isinstance(log, Sequence) or isinstance(log, (str, bytes)) or not log:
        problems.append("unverified_real_evidence")
        return problems
    rejected = [row for row in log if row.get("kind") == "board_write_rejected"
                and str(row.get("message_id")) == message_id]
    writes = [row for row in log if row.get("kind") == "board_write"
              and str(row.get("message_id")) == message_id and str(row.get("agent_id")) == writer]
    reads = [row for row in log if row.get("kind") == "peer_read_exposure"
             and str(row.get("message_id")) == message_id and str(row.get("agent_id")) == reader]
    if rejected or not writes or not reads:
        problems.append("unverified_real_evidence")
        return problems
    write = writes[0]
    write_payload = write.get("payload") or {}
    if write.get("status") != "accepted" or str(write_payload.get("normalized_claim")) != claim \
            or str(write_payload.get("raw_text")) != claim:
        problems.append("unverified_real_evidence")
    if write_payload.get("receiver_id") not in (None, reader):
        problems.append("unverified_real_evidence")
    read = min(reads, key=lambda row: row.get("sequence", 0))
    if not isinstance(write.get("sequence"), int) or not isinstance(read.get("sequence"), int) \
            or read["sequence"] <= write["sequence"]:
        problems.append("unverified_real_evidence")
    if str((read.get("payload") or {}).get("exposure_id")) != exposure_id:
        problems.append("unverified_real_evidence")

    info = instance.information(reader, claim, message_id)
    if info.status != "accepted" or info.delta_i_bits is None:
        problems.append("unverified_real_evidence")
        return problems
    if abs(float(info.delta_i_bits) - float(event.get("i_m_bits", -1.0))) > I_M_TOLERANCE:
        problems.append("unverified_real_evidence")
    if not info.useful:
        problems.append("real_not_informative")
    return problems


def _placebo_problems(event: Mapping[str, Any], instance: Any) -> list[str]:
    placebo = event.get("placebo")
    if not isinstance(placebo, Mapping) or not placebo.get("claim"):
        return ["missing_provenance"]
    agent = str((event.get("task") or {}).get("agent"))
    reader = str((event.get("real_message") or {}).get("reader_id", ""))
    claim = str(placebo["claim"])
    problems: list[str] = []
    if claim not in instance.private_clues.get(agent, ()):
        problems.append("placebo_not_inert")
    info = instance.information(reader or agent, claim, "placebo")
    if info.delta_i_bits is None or abs(float(info.delta_i_bits)) > I_M_TOLERANCE:
        problems.append("placebo_not_inert")
    extended = instance.clue_consistent(set(instance.private_clues.get(agent, ())) | {claim})
    if extended != instance.private_solutions[agent]:
        problems.append("placebo_not_inert")
    if placebo.get("synthetic") is not PLACEBO_SYNTHETIC \
            or placebo.get("construction") != PLACEBO_CONSTRUCTION \
            or placebo.get("envelope") != MESSAGE_ENVELOPE_TEMPLATE:
        problems.append("placebo_wording_mismatch")
    if placebo.get("i_m_bits") not in (0, 0.0):
        problems.append("placebo_not_inert")
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
        question = next(iter(questions.values()))
        criteria = question.get("criteria") if isinstance(question, Mapping) else None
        if not isinstance(criteria, Mapping) or set(criteria) != set(option_ids):
            problems.append("request_body_options_mismatch")
    return problems


def _branch_request_problems(event: Mapping[str, Any]) -> list[str]:
    body = event.get("request_body")
    if not isinstance(body, Mapping):
        return []
    problems: list[str] = []
    branches = event.get("branches")
    if not isinstance(branches, Mapping):
        return []
    for branch in BRANCHES:
        record = branches.get(branch)
        if not isinstance(record, Mapping) or record.get("status") != "complete":
            continue
        reconstructed = branch_request_body(body, branch_message_text(event, branch))
        if record.get("request_hash") != prompt_form_id(reconstructed):
            problems.append("branch_request_mismatch")
            break
    return problems


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
    """Return all validation problems (empty = valid); never raises.

    Resolves the authoritative instance and checks ownership, receiver
    perspective, board evidence and I_m against it; reconstructs each branch's
    exact model-visible request and recomputes its hash; recomputes metrics from
    vectors; and requires model/usage/protocol/provenance consistency.
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

    instance_problems, instance = _instance_problems(event)
    problems.extend(instance_problems)
    if instance is not None:
        problems.extend(_real_message_problems(event, instance))
        problems.extend(_placebo_problems(event, instance))

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
    problems.extend(_branch_request_problems(event))

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
    return {"schema_version": JEV_REPLAY_VERSION, "events": len(events), "forms": len(by_form),
            "by_form": dict(sorted(by_form.items())), "invalid": invalid}


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
    "MESSAGE_ENVELOPE_TEMPLATE", "PLACEBO_CONSTRUCTION", "PLACEBO_ORIGIN",
    "canonical_hash", "pre_read_request_body", "prompt_form_id", "serialize_message",
    "serialize_placebo_message", "message_wording_hash", "branch_request_body",
    "branch_message_text", "entropy_bits", "make_branch", "build_event", "resolve_instance",
    "validate_event", "summarize_events", "assert_no_duplicate_events", "assert_single_protocol",
]
