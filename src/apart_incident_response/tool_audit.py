"""Credential-free, per-agent audit artifacts for tool invocations."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
from typing import Any, Callable, Mapping

from .tool_credentials import VerifiedCredentials


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _redact(value: Any, credential: str) -> Any:
    if isinstance(value, Mapping):
        secret_keys = {
            "access", "access_token", "authorization", "credential", "credential_id",
            "refresh", "refresh_token", "token",
        }
        return {
            str(key): "<redacted-secret>"
            if str(key).casefold() in secret_keys
            else _redact(item, credential)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, credential) for item in value]
    if isinstance(value, str):
        return value.replace(credential, "<redacted-credential>")
    return value


class ToolAuditLog:
    """Append sanitized, per-agent tool records to the run artifact."""

    def __init__(self, artifact_root: Path | str | os.PathLike[str], clock: Callable[[], str] = _utc_now) -> None:
        self._artifact_root = Path(artifact_root).expanduser().resolve()
        self._clock = clock
        self._lock = threading.Lock()

    def record(
        self,
        credentials: VerifiedCredentials,
        operation: str,
        validated_input: Mapping[str, Any] | None,
        response: Mapping[str, Any],
    ) -> None:
        identity = credentials.identity
        path = self._artifact_root / identity.run_id / "agents" / identity.agent_id / "artifacts" / "tool_calls.jsonl"
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        event = {
            "timestamp": self._clock(),
            "run_id": identity.run_id,
            "agent_id": identity.agent_id,
            "condition": identity.condition.value,
            "task_id": identity.task_id,
            "operation": operation,
            "validated_input": _redact(validated_input, credentials.token),
            "response": _redact(response, credentials.token),
        }
        encoded = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
        with self._lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(encoded)
            path.chmod(0o600)
