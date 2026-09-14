"""Sanitized indexes and navigable timelines for experiment runs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .probability_artifacts import (
    ProbabilityArtifactError,
    build_probability_artifact,
    is_complete_probability_artifact,
    replay_partial_entropy,
    unavailable_probability_artifact,
)


_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "authorization",
    "cookie",
    "password",
    "secret",
    "credential",
    "credential_file",
)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            records.append(dict(value))
    return records


def sanitize_artifact(value: Any, secrets: Sequence[str] = (), *, key: str = "") -> Any:
    """Redact credential-shaped fields and known secret values recursively."""

    normalized_key = key.casefold().replace("-", "_")
    if normalized_key != "credential_id" and any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
        return "<redacted-secret>"
    if isinstance(value, Mapping):
        return {
            str(item_key): sanitize_artifact(item, secrets, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_artifact(item, secrets, key=key) for item in value]
    if isinstance(value, tuple):
        return [sanitize_artifact(item, secrets, key=key) for item in value]
    if isinstance(value, str):
        redacted = value
        for secret in sorted({item for item in secrets if item}, key=len, reverse=True):
            redacted = redacted.replace(secret, "<redacted-secret>")
        return redacted
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _safe_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _event_usage(event: Mapping[str, Any]) -> Mapping[str, Any] | None:
    usage = event.get("usage")
    if isinstance(usage, Mapping):
        return dict(usage)
    message = event.get("message")
    if isinstance(message, Mapping) and isinstance(message.get("usage"), Mapping):
        return dict(message["usage"])
    return None


def _content_text(content: Any) -> str | None:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, Mapping) and isinstance(part.get("text"), str):
            parts.append(part["text"])
    return "".join(parts) or None


def _assistant_messages(event: Mapping[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    message = event.get("message")
    if isinstance(message, Mapping) and message.get("role") == "assistant":
        record: dict[str, Any] = {
            "role": "assistant",
            "content": message.get("content"),
        }
        for field in ("model", "provider", "stopReason", "stop_reason"):
            if field in message:
                record[field] = message[field]
        usage = _event_usage(message)
        if usage is not None:
            record["usage"] = usage
        messages.append(record)
    event_type = str(event.get("type", ""))
    if not messages and event_type in {"assistant_message", "message_end", "message_update"}:
        text = event.get("text")
        if text is None:
            text = _content_text(event.get("content"))
        if isinstance(text, str):
            messages.append({"role": "assistant", "content": text})
    return messages


def _probability_capture(event: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Find the provider capture attached to an assistant event."""

    candidates: list[Any] = [event]
    message = event.get("message")
    if isinstance(message, Mapping):
        candidates.append(message)
    for candidate in candidates:
        for field in ("probabilityCapture", "probability_capture"):
            capture = candidate.get(field)
            if isinstance(capture, Mapping):
                return capture
    return None


def _probability_turn_kind(event: Mapping[str, Any]) -> str:
    message = event.get("message")
    content = message.get("content") if isinstance(message, Mapping) else event.get("content")
    if isinstance(content, str):
        return "text"
    if isinstance(event.get("text"), str) and not isinstance(content, list):
        return "text"
    types = {
        item.get("type")
        for item in content
        if isinstance(item, Mapping) and isinstance(item.get("type"), str)
    } if isinstance(content, list) else set()
    if "toolCall" in types or "tool_call" in types:
        return "tool_call"
    if "thinking" in types:
        return "reasoning"
    if "text" in types:
        return "text"
    return "unsupported"


def _probability_provenance(capture: Mapping[str, Any]) -> dict[str, Any]:
    provider = capture.get("provider")
    model = capture.get("model")
    parameters = capture.get("parameters")
    return {
        "provider": provider if isinstance(provider, str) and provider else "unknown",
        "model": model if isinstance(model, str) and model else "unknown",
        "parameters": dict(parameters) if isinstance(parameters, Mapping) else {},
    }


def _build_probability_artifacts(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Normalize provider captures once per assistant turn and make them replayable."""

    turns: list[dict[str, Any]] = []
    for source_sequence, event in enumerate(events, start=1):
        event_type = event.get("type")
        message = event.get("message")
        is_assistant = (
            isinstance(message, Mapping) and message.get("role") == "assistant"
        ) or (event_type == "assistant_message")
        if not is_assistant or event_type not in {"message_end", "assistant_message"}:
            continue
        capture = _probability_capture(event)
        if capture is None:
            provenance = {
                "provider": message.get("provider", "unknown")
                if isinstance(message, Mapping) else "unknown",
                "model": message.get("model", "unknown")
                if isinstance(message, Mapping) else "unknown",
                "parameters": {},
            }
            records = None
            declared_status = "unavailable"
            reason = "provider did not expose probability capture for this assistant turn"
            capture = {}
        else:
            provenance = _probability_provenance(capture)
            records = capture.get("token_records")
            declared_status = capture.get("status")
            reason = capture.get("missing_data_reason")
        if not isinstance(reason, str) or not reason.strip():
            reason = None
        if not isinstance(records, list) or not records:
            probability = unavailable_probability_artifact(
                provenance,
                reason=reason or "provider omitted probability records for this assistant turn",
            )
            capture_status = "unavailable"
        else:
            try:
                probability = build_probability_artifact(records, provenance=provenance)
                capture_status = declared_status if declared_status in {"complete", "partial"} else "complete"
                if capture_status == "partial" and reason:
                    probability["capture_status"] = "partial"
                    probability["capture_missing_data_reason"] = reason
            except (ProbabilityArtifactError, TypeError, ValueError) as exc:
                reason = f"provider probability records were unusable ({type(exc).__name__})"
                probability = unavailable_probability_artifact(provenance, reason=reason)
                capture_status = "unavailable"
        try:
            replay = replay_partial_entropy(probability)
        except ProbabilityArtifactError as exc:
            replay = {"status": "failed", "error": f"replay failed ({type(exc).__name__})"}
        request_id = capture.get("request_id")
        if not isinstance(request_id, str) and isinstance(message, Mapping):
            request_id = message.get("responseId")
        turns.append({
            "source_sequence": source_sequence,
            "event_type": event.get("type", "unknown"),
            "kind": _probability_turn_kind(event),
            "status": capture_status,
            "provider": provenance["provider"],
            "model": provenance["model"],
            "request_id": request_id if isinstance(request_id, str) else None,
            "session_id": capture.get("session_id") if isinstance(capture.get("session_id"), str) else None,
            "probability_artifact": probability,
            "replay": replay,
        })

    kinds = ("text", "tool_call", "reasoning", "unsupported")
    by_kind: dict[str, dict[str, int]] = {}
    for kind in kinds:
        matching = [turn for turn in turns if turn["kind"] == kind]
        by_kind[kind] = {
            "turns": len(matching),
            "complete": sum(turn["status"] == "complete" for turn in matching),
            "partial": sum(turn["status"] == "partial" for turn in matching),
            "unavailable": sum(turn["status"] == "unavailable" for turn in matching),
            "tokens": sum(
                turn["probability_artifact"].get("coverage", {}).get("token_count", 0)
                for turn in matching
            ),
        }
    return {
        "schema_version": 1,
        "artifact_schema": "agent-turn-probability-v1",
        "turns": turns,
        "coverage": {
            "turns": len(turns),
            "complete": sum(turn["status"] == "complete" for turn in turns),
            "partial": sum(turn["status"] == "partial" for turn in turns),
            "unavailable": sum(turn["status"] == "unavailable" for turn in turns),
            "tokens": sum(
                turn["probability_artifact"].get("coverage", {}).get("token_count", 0)
                for turn in turns
            ),
            "by_kind": by_kind,
        },
    }


def _artifact_links(root: Path, agent_dir: Path) -> dict[str, dict[str, Any]]:
    artifact_dir = agent_dir / "artifacts"
    names = (
        "metadata.json",
        "events.json",
        "stdout.jsonl",
        "stderr.log",
        "response.json",
        "final_response.txt",
        "agent_telemetry.json",
        "result.json",
        "tool_calls.jsonl",
        "task_submission.json",
        "timeline.json",
        "probability_artifacts.json",
    )
    return {
        name: {"path": _relative(root, artifact_dir / name), "present": (artifact_dir / name).is_file()}
        for name in names
    }


def build_agent_timeline(
    run_root: Path | str,
    agent_id: str,
    *,
    secrets: Sequence[str] = (),
    persist: bool = False,
) -> dict[str, Any]:
    """Build one agent’s ordered, sanitized timeline from retained artifacts."""

    root = Path(run_root).expanduser().resolve()
    if not isinstance(agent_id, str) or not agent_id or Path(agent_id).name != agent_id:
        raise ValueError("agent_id must be a single path component")
    agent_dir = root / "agents" / agent_id
    artifact_dir = agent_dir / "artifacts"
    metadata = _load_json(artifact_dir / "metadata.json")
    result = _load_json(artifact_dir / "result.json")
    telemetry = _load_json(artifact_dir / "agent_telemetry.json")
    events = _load_json(artifact_dir / "events.json")
    if not isinstance(events, list):
        events = []
    audits = _load_jsonl(artifact_dir / "tool_calls.jsonl")
    identity = None
    if isinstance(result, Mapping) and isinstance(result.get("identity"), Mapping):
        identity = result["identity"]
    elif isinstance(metadata, Mapping) and isinstance(metadata.get("identity"), Mapping):
        identity = metadata["identity"]

    prompt = metadata.get("prompt") if isinstance(metadata, Mapping) else None
    entries: list[dict[str, Any]] = []
    if isinstance(prompt, str):
        entries.append({
            "sequence": 0,
            "source": "controller",
            "kind": "prompt",
            "timestamp": metadata.get("started_at") if isinstance(metadata, Mapping) else None,
            "text": prompt,
        })
    for source_sequence, event in enumerate((item for item in events if isinstance(item, Mapping)), start=1):
        entry: dict[str, Any] = {
            "sequence": len(entries),
            "source": "pi",
            "source_sequence": source_sequence,
            "kind": "assistant_message" if _assistant_messages(event) else "pi_event",
            "event_type": event.get("type", "unknown"),
            "timestamp": event.get("timestamp") or event.get("observed_at"),
            "event": event,
        }
        usage = _event_usage(event)
        if usage is not None:
            entry["usage"] = usage
        assistant_messages = _assistant_messages(event)
        if assistant_messages:
            entry["assistant_messages"] = assistant_messages
        entries.append(entry)
    for source_sequence, audit in enumerate(audits, start=1):
        entries.append({
            "sequence": len(entries),
            "source": "tool_audit",
            "source_sequence": source_sequence,
            "kind": "tool_call",
            "timestamp": audit.get("timestamp"),
            "operation": audit.get("operation"),
            "tool_call": {
                "validated_input": audit.get("validated_input"),
                "response": audit.get("response"),
            },
        })
    if len(entries) > 1 and all(_safe_timestamp(entry.get("timestamp")) is not None for entry in entries[1:]):
        prompt_entry = entries[:1] if entries and entries[0].get("kind") == "prompt" else []
        event_entries = entries[1:] if prompt_entry else entries
        event_entries.sort(key=lambda entry: _safe_timestamp(entry.get("timestamp")))
        entries = prompt_entry + event_entries
    for sequence, entry in enumerate(entries):
        entry["sequence"] = sequence

    probability_artifacts = _build_probability_artifacts(
        [item for item in events if isinstance(item, Mapping)]
    )

    usage_reports = [
        {
            "source_sequence": index,
            "event_type": event.get("type", "unknown"),
            "timestamp": event.get("timestamp") or event.get("observed_at"),
            "usage": _event_usage(event),
        }
        for index, event in enumerate((item for item in events if isinstance(item, Mapping)), start=1)
        if _event_usage(event) is not None
    ]
    by_operation: dict[str, dict[str, int]] = {}
    for audit in audits:
        operation = str(audit.get("operation", "unknown"))
        counts = by_operation.setdefault(operation, {"calls": 0, "succeeded": 0, "failed": 0})
        counts["calls"] += 1
        response = audit.get("response")
        if isinstance(response, Mapping) and response.get("ok") is True:
            counts["succeeded"] += 1
        else:
            counts["failed"] += 1
    safe_entries = sanitize_artifact(entries, secrets)
    safe_result = sanitize_artifact(result, secrets) if isinstance(result, Mapping) else {}
    safe_telemetry = sanitize_artifact(telemetry, secrets) if isinstance(telemetry, Mapping) else {}
    status = safe_result.get("status") or safe_telemetry.get("status") or "missing"
    failure_reasons = [
        value
        for value in (
            safe_result.get("failure_reason"),
            safe_result.get("persistence_failure"),
            safe_telemetry.get("failure_reason"),
        )
        if isinstance(value, str) and value
    ]
    timeline = {
        "schema_version": 1,
        "identity": sanitize_artifact(identity or {"agent_id": agent_id}, secrets),
        "status": status,
        "prompt": sanitize_artifact(prompt, secrets),
        "failure_reasons": list(dict.fromkeys(failure_reasons)),
        "reported_usage": sanitize_artifact(usage_reports, secrets),
        "tool_summary": sanitize_artifact({
            "total_calls": len(audits),
            "by_operation": by_operation,
        }, secrets),
        "usage": {
            "provider_tokens": safe_result.get("tokens_used", safe_telemetry.get("provider_tokens")),
            "tool_calls": safe_result.get("tool_calls_used", safe_telemetry.get("tool_call_count")),
            "turns": safe_telemetry.get("turn_count"),
        },
        "artifacts": _artifact_links(root, agent_dir),
        "probability_artifacts": {
            "path": _relative(root, artifact_dir / "probability_artifacts.json"),
            "present": (artifact_dir / "probability_artifacts.json").is_file(),
            "coverage": probability_artifacts["coverage"],
        },
        "entries": safe_entries,
        "event_order": {
            "pi_events": "events.json order, preserved by source_sequence",
            "tool_audits": "tool_calls.jsonl order, preserved by source_sequence",
            "global_sequence": "timestamp order from observed Pi events and tool audits; source order is stable when timestamps are absent",
        },
    }
    if persist and agent_dir.is_dir():
        _write_json(artifact_dir / "probability_artifacts.json", sanitize_artifact(probability_artifacts, secrets))
        timeline["probability_artifacts"]["present"] = True
        timeline["artifacts"]["probability_artifacts.json"]["present"] = True
        _write_json(artifact_dir / "timeline.json", timeline)
    return timeline


def entropy_eligibility(
    run_root: Path | str,
    *,
    expected_agent_count: int = 2,
) -> dict[str, Any]:
    """Check the strict gate for using token entropy from one condition run."""

    root = Path(run_root).expanduser().resolve()
    manifest = _load_json(root / "manifest.json")
    assignments = manifest.get("assignment") if isinstance(manifest, Mapping) else None
    agent_ids = [
        item.get("agent_id")
        for item in assignments
        if isinstance(item, Mapping) and isinstance(item.get("agent_id"), str)
    ] if isinstance(assignments, list) else []
    reasons: list[str] = []
    if len(agent_ids) != expected_agent_count or len(set(agent_ids)) != expected_agent_count:
        reasons.append(f"expected exactly {expected_agent_count} assigned agents")
    agents: dict[str, dict[str, Any]] = {}
    for agent_id in agent_ids:
        path = root / "agents" / agent_id / "artifacts" / "probability_artifacts.json"
        try:
            artifact = _load_json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            artifact = None
        eligible = is_complete_probability_artifact(artifact)
        agents[agent_id] = {"path": _relative(root, path), "eligible": eligible}
        if not eligible:
            reasons.append(f"{agent_id}: probability_artifacts.json is incomplete or unavailable")
    return {
        "eligible": not reasons,
        "expected_agent_count": expected_agent_count,
        "agents": agents,
        "reasons": list(dict.fromkeys(reasons)),
    }


def write_condition_index(
    run_root: Path | str,
    *,
    secrets: Sequence[str] = (),
    controller_failure: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write an index for one condition, including links for every agent."""

    root = Path(run_root).expanduser().resolve()
    manifest = _load_json(root / "manifest.json")
    if not isinstance(manifest, Mapping):
        manifest = {}
    results_document = _load_json(root / "results.json")
    results = results_document.get("results", []) if isinstance(results_document, Mapping) else []
    if not isinstance(results, list):
        results = []
    result_by_agent = {
        item.get("identity", {}).get("agent_id"): item
        for item in results
        if isinstance(item, Mapping)
        and isinstance(item.get("identity"), Mapping)
        and isinstance(item.get("identity", {}).get("agent_id"), str)
    }
    assigned_ids = [
        item.get("agent_id")
        for item in manifest.get("assignment", [])
        if isinstance(item, Mapping) and isinstance(item.get("agent_id"), str)
    ]
    present_ids = [
        path.name
        for path in (root / "agents").iterdir()
        if (root / "agents").is_dir() and path.is_dir()
    ] if (root / "agents").is_dir() else []
    agent_ids = sorted(set(assigned_ids) | set(present_ids) | set(result_by_agent))
    agents: dict[str, Any] = {}
    failure_reasons: list[dict[str, Any]] = []
    for agent_id in agent_ids:
        timeline = build_agent_timeline(root, agent_id, secrets=secrets, persist=True)
        if agent_id not in present_ids:
            timeline = {
                "schema_version": 1,
                "identity": {"agent_id": agent_id},
                "status": "missing",
                "failure_reasons": ["agent artifact directory is missing"],
                "usage": {},
                "artifacts": {},
                "probability_artifacts": {
                    "path": _relative(root, root / "agents" / agent_id / "artifacts" / "probability_artifacts.json"),
                    "present": False,
                    "coverage": {
                        "turns": 0,
                        "complete": 0,
                        "partial": 0,
                        "unavailable": 0,
                        "tokens": 0,
                        "by_kind": {},
                    },
                },
                "entries": [],
                "event_order": {},
            }
        status = timeline.get("status", "missing")
        reasons = timeline.get("failure_reasons", [])
        if status != "completed" or reasons:
            for reason in reasons or [f"agent status: {status}"]:
                failure_reasons.append({"agent_id": agent_id, "reason": reason})
        agents[agent_id] = {
            "identity": timeline.get("identity", {"agent_id": agent_id}),
            "status": status,
            "failure_reasons": reasons,
            "timeline": {
                "path": _relative(root, root / "agents" / agent_id / "artifacts" / "timeline.json"),
                "present": (root / "agents" / agent_id / "artifacts" / "timeline.json").is_file(),
            },
            "artifacts": timeline.get("artifacts", {}),
            "probability_artifacts": timeline.get("probability_artifacts", {}),
            "usage": timeline.get("usage", {}),
        }
    controller_errors = results_document.get("controller_errors", []) if isinstance(results_document, Mapping) else []
    if isinstance(controller_errors, list):
        failure_reasons.extend(
            {"source": "controller", "reason": sanitize_artifact(error, secrets)}
            for error in controller_errors
            if isinstance(error, Mapping)
        )
    if controller_failure is not None:
        failure_reasons.append({"source": "controller", "reason": sanitize_artifact(controller_failure, secrets)})
    status = "failed" if failure_reasons else "completed"
    index = {
        "schema_version": 1,
        "run": sanitize_artifact({
            "run_id": manifest.get("run_id", root.name),
            "run_uuid": manifest.get("run_uuid"),
            "provider": manifest.get("provider"),
            "model": manifest.get("model") or (
                manifest.get("factor_assignment", {}).get("model")
                if isinstance(manifest.get("factor_assignment"), Mapping)
                else None
            ),
            "triplet_id": manifest.get("triplet_id"),
            "condition": manifest.get("condition"),
            "seed": manifest.get("seed"),
            "run_class": manifest.get("run_class"),
        }, secrets),
        "status": status,
        "prompt": sanitize_artifact(manifest.get("prompt"), secrets),
        "agents": agents,
        "probability_coverage": {
            agent_id: details.get("probability_artifacts", {}).get("coverage", {})
            for agent_id, details in agents.items()
            if isinstance(details, Mapping)
        },
        "failure_reasons": failure_reasons,
        "artifacts": {
            "manifest": {"path": "manifest.json", "present": (root / "manifest.json").is_file()},
            "budget": {"path": "budget.json", "present": (root / "budget.json").is_file()},
            "results": {"path": "results.json", "present": (root / "results.json").is_file()},
            "metrics": {"path": "artifacts/metrics.json", "present": (root / "artifacts/metrics.json").is_file()},
            "replay": {"path": "artifacts/replay.json", "present": (root / "artifacts/replay.json").is_file()},
        },
    }
    _write_json(root / "index.json", index)
    return index


def artifact_links_for_run(run_root: Path | str, matrix_root: Path | str) -> dict[str, Any]:
    """Return relative matrix links to a condition index and each agent timeline."""

    root = Path(run_root).expanduser().resolve()
    matrix = Path(matrix_root).expanduser().resolve()
    index = _load_json(root / "index.json")
    agents = index.get("agents", {}) if isinstance(index, Mapping) else {}
    relative_root = _relative(matrix, root)
    agent_links = {
        agent_id: f"{relative_root}/{details['timeline']['path']}"
        for agent_id, details in agents.items()
        if isinstance(details, Mapping)
        and isinstance(details.get("timeline"), Mapping)
        and isinstance(details["timeline"].get("path"), str)
    }
    probability_links = {
        agent_id: f"{relative_root}/{details['probability_artifacts']['path']}"
        for agent_id, details in agents.items()
        if isinstance(details, Mapping)
        and isinstance(details.get("probability_artifacts"), Mapping)
        and isinstance(details["probability_artifacts"].get("path"), str)
    }
    return {
        "index": f"{relative_root}/index.json",
        "agents": agent_links,
        "probability_artifacts": probability_links,
    }


def triplet_artifact_links(runs: Iterable[Any], matrix_root: Path | str) -> dict[str, Any]:
    """Build links for all conditions in a triplet."""

    matrix = Path(matrix_root).expanduser().resolve()
    run_list = tuple(runs)
    return {
        "triplet": f"{run_list[0].triplet_id}.json" if run_list else None,
        "conditions": {
            run.condition.value: {
                "run_id": run.run_id,
                **artifact_links_for_run(run.artifact_root, matrix),
            }
            for run in run_list
        },
    }


__all__ = [
    "artifact_links_for_run",
    "build_agent_timeline",
    "sanitize_artifact",
    "triplet_artifact_links",
    "write_condition_index",
]
