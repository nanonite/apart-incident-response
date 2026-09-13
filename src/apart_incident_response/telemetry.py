"""Raw-event telemetry, provenance-backed uptake, and replayable metrics."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
from typing import Any, Callable, Iterable, Mapping


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class JsonlEventLog:
    """Append immutable JSON events to a controller-owned artifact."""

    def __init__(self, path: Path | str, clock: Callable[[], str] = utc_now) -> None:
        self.path = Path(path).expanduser().resolve()
        self.clock = clock
        self._lock = threading.Lock()

    def record(self, event: Mapping[str, Any]) -> dict[str, Any]:
        normalized = dict(event)
        normalized.setdefault("timestamp", self.clock())
        encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True) + "\n"
        with self._lock:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.path.parent.chmod(0o700)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(encoded)
            self.path.chmod(0o600)
        return normalized


def _load_json(path: Path) -> Mapping[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            events.append(dict(value))
    return events


def _private_token_owners(
    run_root: Path, tokens: Iterable[str]
) -> tuple[dict[str, frozenset[str]], str | None]:
    """Resolve private seeded-token ownership from the immutable run manifest."""

    requested = tuple(tokens)
    if not requested:
        return {}, None
    manifest = _load_json(run_root / "manifest.json")
    task = manifest.get("task") if manifest is not None else None
    provenance = task.get("token_provenance") if isinstance(task, Mapping) else None
    owners_by_token = provenance.get("private_token_owners") if isinstance(provenance, Mapping) else None
    owner_agent_ids_by_token = provenance.get("private_token_owner_agent_ids") if isinstance(provenance, Mapping) else None
    assignments = manifest.get("assignment") if manifest is not None else None
    if not isinstance(owners_by_token, Mapping) or not isinstance(assignments, list):
        return {}, "manifest lacks private seeded-token provenance"
    resolved: dict[str, frozenset[str]] = {}
    role_to_agents: dict[str, set[str]] = {}
    assigned_agents: set[str] = set()
    for item in assignments:
        if not isinstance(item, Mapping):
            continue
        role = item.get("evidence_role")
        agent = item.get("agent_id")
        if isinstance(role, str) and isinstance(agent, str):
            role_to_agents.setdefault(role, set()).add(agent)
            assigned_agents.add(agent)
    if not role_to_agents:
        return {}, "manifest has no resolvable evidence assignments"
    owner_roles_by_token = provenance.get("private_token_owner_roles") if isinstance(provenance, Mapping) else None
    for token in requested:
        direct_agents = owner_agent_ids_by_token.get(token) if isinstance(owner_agent_ids_by_token, Mapping) else None
        if isinstance(direct_agents, list):
            if not direct_agents or not all(isinstance(agent, str) and agent in assigned_agents for agent in direct_agents):
                return {}, f"manifest has invalid private owner agent provenance for {token}"
            resolved[token] = frozenset(direct_agents)
            continue
        roles = owner_roles_by_token.get(token) if isinstance(owner_roles_by_token, Mapping) else owners_by_token.get(token)
        if not isinstance(roles, list) or not roles or not all(isinstance(role, str) for role in roles):
            return {}, f"manifest has invalid private owner provenance for {token}"
        agents = frozenset(
            agent
            for role in roles
            for agent in role_to_agents.get(role, set())
        )
        if not agents:
            return {}, f"manifest cannot resolve private owners for {token}"
        resolved[token] = agents
    return resolved, None


def _contains_token(value: Any, token: str) -> bool:
    if isinstance(value, str):
        return token.casefold() in value.casefold()
    if isinstance(value, Mapping):
        return any(_contains_token(key, token) or _contains_token(item, token) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_token(item, token) for item in value)
    return False


def _event_payload(event: Mapping[str, Any]) -> Any:
    return event.get("validated_input", event.get("response", {}))


def _read_messages(event: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    response = event.get("response")
    result = response.get("result") if isinstance(response, Mapping) else None
    messages = result.get("messages") if isinstance(result, Mapping) else None
    if not isinstance(messages, list):
        return []
    return [message for message in messages if isinstance(message, Mapping)]


def _seconds_between(first: Any, second: Any) -> float | None:
    if not isinstance(first, str) or not isinstance(second, str):
        return None
    try:
        left = datetime.fromisoformat(first.replace("Z", "+00:00"))
        right = datetime.fromisoformat(second.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max((right - left).total_seconds(), 0.0)


def _agent_artifacts(run_root: Path) -> Iterable[tuple[str, Path, list[dict[str, Any]]]]:
    agents_root = run_root / "agents"
    if not agents_root.is_dir():
        return
    for agent_dir in sorted(path for path in agents_root.iterdir() if path.is_dir()):
        artifact_dir = agent_dir / "artifacts"
        yield agent_dir.name, artifact_dir, _load_jsonl(artifact_dir / "tool_calls.jsonl")


def detect_uptake(run_root: Path | str, seeded_tokens: Iterable[str]) -> list[dict[str, Any]]:
    """Find later recipient use after a provenance-backed cross-agent read.

    A token match in a final answer alone is not uptake. The recipient must
    first be shown a board message carrying the token, and the later matching
    event is linked to that board sequence ID and source agent.
    """

    root = Path(run_root).expanduser().resolve()
    tokens = tuple(dict.fromkeys(token for token in seeded_tokens if isinstance(token, str) and token))
    private_owners, provenance_error = _private_token_owners(root, tokens)
    if provenance_error is not None:
        return []
    uptake: list[dict[str, Any]] = []
    for recipient, artifact_dir, events in _agent_artifacts(root):
        for read_index, event in enumerate(events):
            if event.get("operation") != "board_read":
                continue
            response = event.get("response")
            result = response.get("result") if isinstance(response, Mapping) else None
            messages = result.get("messages") if isinstance(result, Mapping) else None
            if not isinstance(messages, list):
                continue
            for message in messages:
                if not isinstance(message, Mapping):
                    continue
                source = message.get("agent_id")
                sequence_id = message.get("sequence_id")
                body = message.get("message_body")
                if not isinstance(source, str) or source == recipient or not isinstance(body, str):
                    continue
                matching_tokens = [token for token in tokens if _contains_token(body, token)]
                if not matching_tokens:
                    continue
                for token in matching_tokens:
                    owners = private_owners.get(token, frozenset())
                    if source not in owners or recipient in owners:
                        continue
                    key = (recipient, source, sequence_id, token)
                    later = events[read_index + 1 :]
                    chosen: tuple[str, Mapping[str, Any]] | None = None
                    for candidate in later:
                        if _contains_token(_event_payload(candidate), token):
                            chosen = (str(candidate.get("operation", "tool_event")), candidate)
                            break
                    if chosen is None:
                        response_path = artifact_dir / "response.json"
                        response_record = _load_json(response_path)
                        final_response = response_record.get("final_response") if response_record else None
                        if _contains_token(final_response, token):
                            chosen = ("final_response", response_record or {})
                    if chosen is None:
                        continue
                    stage, candidate = chosen
                    uptake.append({
                        "source_agent": source,
                        "recipient_agent": recipient,
                        "message_id": sequence_id,
                        "seeded_token": token,
                        "board_read_timestamp": event.get("timestamp"),
                        "uptake_timestamp": candidate.get("timestamp", event.get("timestamp")),
                        "uptake_stage": stage,
                        "message_body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                        "private_token_owner": source,
                        "recipient_private_token_known": False,
                        "provenance": "private-owner-board-sequence-to-later-recipient-event",
                    })
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in uptake:
        key = (
            record["recipient_agent"],
            record["source_agent"],
            record["message_id"],
            record["seeded_token"],
        )
        unique.setdefault(key, record)
    return sorted(unique.values(), key=lambda record: str(record.get("uptake_timestamp", "")))


def classify_uptake_outcomes(
    run_root: Path | str, uptake: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Separate channel use from trace-supported utility or misleading use."""

    root = Path(run_root).expanduser().resolve()
    by_agent: dict[str, tuple[Path, list[dict[str, Any]], Mapping[str, Any] | None]] = {}
    for agent_id, artifact_dir, events in _agent_artifacts(root):
        by_agent[agent_id] = (artifact_dir, events, _load_json(artifact_dir / "result.json"))
    outcomes: list[dict[str, Any]] = []
    for original in uptake:
        record = dict(original)
        recipient = str(record.get("recipient_agent", ""))
        artifact_dir, events, result = by_agent.get(recipient, (Path(), [], None))
        submission = _load_json(artifact_dir / "task_submission.json") if artifact_dir != Path() else None
        token = str(record.get("seeded_token", ""))
        diagnosis = submission.get("diagnosis") if submission else None
        cited = bool(
            submission
            and _contains_token(submission.get("evidence"), token)
        )
        if submission and _contains_token(diagnosis, token):
            utility_class = "useful_or_correct"
        elif submission:
            utility_class = "redundant"
        elif result and result.get("status") != "completed":
            utility_class = "misleading_or_failed"
        else:
            utility_class = "redundant"
        read_index = next(
            (index for index, event in enumerate(events)
             if event.get("operation") == "board_read"
             and any(message.get("sequence_id") == record.get("message_id") for message in _read_messages(event))),
            None,
        )
        later_events = events[read_index + 1 :] if read_index is not None else []
        record.update({
            "utility_class": utility_class,
            "cited_in_submission_evidence": cited,
            "diagnosis_contains_seeded_token": _contains_token(diagnosis, token),
            "preceded_submission": any(event.get("operation") == "task_submit" for event in later_events),
            "preceded_tool_choice": bool(later_events),
            "preceded_final_response": bool(result and result.get("final_response")),
            "behavior_change_observation": "later_recipient_event_present",
        })
        outcomes.append(record)
    return outcomes


def _board_events(run_root: Path) -> list[dict[str, Any]]:
    return _load_jsonl(run_root / "artifacts" / "board_events.jsonl")


def _result_records(run_root: Path) -> list[Mapping[str, Any]]:
    records: list[Mapping[str, Any]] = []
    for _agent_id, artifact_dir, _events in _agent_artifacts(run_root):
        result = _load_json(artifact_dir / "result.json")
        if result is not None:
            records.append(result)
    return records


def compute_metrics(
    run_root: Path | str,
    seeded_tokens: Iterable[str],
    *,
    observation_window_turns: int = 1,
    baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute auditable condition metrics from raw artifacts only."""

    root = Path(run_root).expanduser().resolve()
    tokens = tuple(dict.fromkeys(token for token in seeded_tokens if isinstance(token, str) and token))
    private_owners, provenance_error = _private_token_owners(root, tokens)
    board_events = _board_events(root)
    uptake = detect_uptake(root, tokens)
    uptake_outcomes = classify_uptake_outcomes(root, uptake)
    results = _result_records(root)
    board_reads = [event for event in board_events if event.get("operation") == "board_read"]
    board_writes = [event for event in board_events if event.get("operation") == "board_append"]
    cross_agent_messages = 0
    total_read_messages = 0
    cadence_attempts = 0
    scheduled_read_opportunities = 0
    for event in board_reads:
        cadence_attempts += 1
        cadence = event.get("cadence")
        scheduled = not isinstance(cadence, Mapping) or bool(cadence.get("scheduled_opportunity", True))
        if scheduled:
            scheduled_read_opportunities += 1
        messages = event.get("message_ids", [])
        if isinstance(messages, list):
            total_read_messages += len(messages)
            cross_agent_messages += sum(
                1 for message in event.get("messages", [])
                if isinstance(message, Mapping) and message.get("source_agent") != event.get("agent_id")
            )
    successful_agents = sum(1 for result in results if result.get("status") == "completed")
    submitted_agents = 0
    validator_outcomes: list[dict[str, Any]] = []
    for _agent, artifact_dir, _events in _agent_artifacts(root):
        submission = _load_json(artifact_dir / "task_submission.json")
        if submission is not None:
            submitted_agents += 1
            validator = submission.get("validator")
            validator_outcomes.append({
                "agent_id": submission.get("agent_id"),
                "validator": validator,
                "accepted": bool(validator.get("accepted")) if isinstance(validator, Mapping) else True,
            })
    total_tokens = sum(int(result.get("tokens_used", 0) or 0) for result in results)
    total_tool_calls = sum(int(result.get("tool_calls_used", 0) or 0) for result in results)
    duration_seconds = max((float(result.get("duration_seconds", 0) or 0) for result in results), default=0.0)
    total_turns = 0
    for _agent, artifact_dir, _events in _agent_artifacts(root):
        telemetry = _load_json(artifact_dir / "agent_telemetry.json")
        if telemetry is not None:
            total_turns += int(telemetry.get("turn_count", 0) or 0)
    token_budget = _load_json(root / "manifest.json") or {}
    limits = token_budget.get("budget", {}) if isinstance(token_budget, Mapping) else {}
    aggregate_limit = limits.get("aggregate_token_budget") if isinstance(limits, Mapping) else None
    recipients = {record["recipient_agent"] for record in uptake}
    eligible = len({
        (event.get("agent_id"), message.get("sequence_id"), token)
        for event in board_reads
        for message in event.get("messages", []) if isinstance(message, Mapping)
        for token in tokens
        if message.get("agent_id") != event.get("agent_id")
        and _contains_token(message.get("message_body"), token)
        and event.get("agent_id") not in private_owners.get(token, frozenset())
        and message.get("source_agent") in private_owners.get(token, frozenset())
    })
    transformations = []
    for event in board_writes:
        body = event.get("message", "")
        source = event.get("agent_id")
        kind = (
            "verbatim_seeded_token"
            if any(_contains_token(body, token) and source in private_owners.get(token, frozenset()) for token in tokens)
            else "unattributed_seeded_token"
            if any(_contains_token(body, token) for token in tokens)
            else "message_without_seeded_token"
        )
        transformations.append({
            "source_agent": event.get("agent_id"),
            "timestamp": event.get("timestamp"),
            "message_id": event.get("message_id"),
            "stage": "private_evidence_to_board_message",
            "transformation_type": kind,
        })
    for record in uptake_outcomes:
        transformations.append({
            "source_agent": record.get("source_agent"),
            "recipient_agent": record.get("recipient_agent"),
            "timestamp": record.get("uptake_timestamp"),
            "message_id": record.get("message_id"),
            "stage": "board_message_to_later_recipient_event",
            "transformation_type": (
                "verbatim_seeded_token"
                if record.get("diagnosis_contains_seeded_token")
                else "synthesis_or_paraphrase"
            ),
        })
    latencies = [
        latency
        for record in uptake
        for latency in [_seconds_between(record.get("board_read_timestamp"), record.get("uptake_timestamp"))]
        if latency is not None
    ]
    board_bytes_read = sum(int(event.get("bytes_read", 0) or 0) for event in board_reads)
    board_bytes_written = sum(int(event.get("bytes_written", 0) or 0) for event in board_writes)
    message_to_answer_opportunities = sum(
        1
        for event in board_reads
        if not isinstance(event.get("cadence"), Mapping)
        or bool(event["cadence"].get("scheduled_opportunity", True))
        for message in event.get("messages", [])
        if isinstance(message, Mapping)
        and message.get("source_agent") != event.get("agent_id")
    )
    transformation_opportunities = len(board_writes) + message_to_answer_opportunities
    metrics: dict[str, Any] = {
        "schema_version": 1,
        "uptake_definition": "recipient use after a prior board read of a seeded-token message from a declared private owner; every recipient with private exposure is excluded",
        "U": (len(uptake) / eligible) if eligible else 0.0,
        "uptake_defined": bool(eligible) and provenance_error is None,
        "uptake_provenance_valid": provenance_error is None,
        "uptake_provenance_error": provenance_error,
        "private_token_owners": {token: sorted(owners) for token, owners in private_owners.items()},
        "uptake_events": len(uptake),
        "uptake_recipients": len(recipients),
        "uptake_opportunities": eligible,
        "uptake": uptake,
        "uptake_outcomes": uptake_outcomes,
        "board_reads_R": len(board_reads),
        "board_writes_W": len(board_writes),
        "cadence_read_attempts": cadence_attempts,
        "scheduled_board_read_opportunities": scheduled_read_opportunities,
        "board_bytes_read": board_bytes_read,
        "board_bytes_written": board_bytes_written,
        "cross_agent_messages_X": cross_agent_messages,
        "message_read_ratio_M": (cross_agent_messages / total_read_messages) if total_read_messages else 0.0,
        "uptake_latency_seconds": latencies,
        "mean_uptake_latency_seconds": (sum(latencies) / len(latencies)) if latencies else None,
        "transformation_events": transformations,
        "evidence_to_message_opportunities": len(board_writes),
        "message_to_answer_opportunities": message_to_answer_opportunities,
        "transformation_opportunities": transformation_opportunities,
        "transformation_rate": (len(transformations) / transformation_opportunities) if transformation_opportunities else 0.0,
        "agent_count": len(results),
        "completed_agents": successful_agents,
        "submitted_agents": submitted_agents,
        "validator_outcomes": validator_outcomes,
        "task_success": bool(submitted_agents > 0),
        "task_success_rate": (submitted_agents / len(results)) if results else 0.0,
        "total_tokens": total_tokens,
        "total_tool_calls": total_tool_calls,
        "total_turns": total_turns,
        "wall_clock_seconds": duration_seconds,
        "success_per_1000_tokens": (1000 * int(submitted_agents > 0) / total_tokens) if total_tokens else None,
        "aggregate_token_budget": aggregate_limit,
        "failures": [
            {"agent_id": result.get("identity", {}).get("agent_id"), "status": result.get("status"), "reason": result.get("failure_reason")}
            for result in results if result.get("status") != "completed"
        ],
        "pilot_claim_scope": "descriptive; no causal or inferential claim from this metric alone",
    }
    if baseline is not None:
        metrics["coordination_overhead"] = {
            "extra_tokens_vs_baseline": total_tokens - int(baseline.get("total_tokens", 0) or 0),
            "extra_tool_calls_vs_baseline": total_tool_calls - int(baseline.get("total_tool_calls", 0) or 0),
            "extra_board_reads_vs_baseline": len(board_reads) - int(baseline.get("board_reads_R", 0) or 0),
            "extra_board_writes_vs_baseline": len(board_writes) - int(baseline.get("board_writes_W", 0) or 0),
        }
    return metrics


def replay_trace(run_root: Path | str) -> list[dict[str, Any]]:
    """Return a single timestamp-ordered trace from the preserved raw events."""

    root = Path(run_root).expanduser().resolve()
    trace: list[dict[str, Any]] = []
    for event in _board_events(root):
        trace.append({"source": "board", **event})
    for agent_id, artifact_dir, events in _agent_artifacts(root):
        for event in events:
            trace.append({"source": "agent_tool", "agent_id": agent_id, **event})
        result = _load_json(artifact_dir / "result.json")
        if result is not None:
            trace.append({
                "source": "agent_result",
                "agent_id": agent_id,
                "timestamp": result.get("ended_at"),
                "status": result.get("status"),
                "final_response": result.get("final_response"),
            })
    return sorted(trace, key=lambda event: str(event.get("timestamp", "")))


def write_derived_artifacts(
    run_root: Path | str,
    seeded_tokens: Iterable[str],
    *,
    observation_window_turns: int = 1,
    baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist derived metrics while retaining all raw inputs unchanged."""

    root = Path(run_root).expanduser().resolve()
    metrics = compute_metrics(root, seeded_tokens, observation_window_turns=observation_window_turns, baseline=baseline)
    uptake = metrics["uptake"]
    (root / "artifacts").mkdir(mode=0o700, parents=True, exist_ok=True)
    for filename, value in (("metrics.json", metrics), ("uptake.json", {"schema_version": 1, "records": uptake, "outcomes": metrics["uptake_outcomes"]}), ("replay.json", {"schema_version": 1, "events": replay_trace(root)})):
        path = root / "artifacts" / filename
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
    return metrics


__all__ = [
    "JsonlEventLog",
    "compute_metrics",
    "classify_uptake_outcomes",
    "detect_uptake",
    "replay_trace",
    "utc_now",
    "write_derived_artifacts",
]
