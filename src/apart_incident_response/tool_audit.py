"""Credential-free, per-agent audit artifacts for tool invocations."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
from typing import Any, Callable, Mapping, Sequence

from .tool_credentials import VerifiedCredentials


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _redact(
    value: Any,
    credential: str | None,
    secrets: Sequence[str] = (),
) -> Any:
    if isinstance(value, Mapping):
        secret_keys = {
            "access", "access_token", "authorization", "credential", "credential_id",
            "refresh", "refresh_token", "token",
        }
        return {
            str(key): "<redacted-secret>"
            if str(key).casefold() in secret_keys
            else _redact(item, credential, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, credential, secrets) for item in value]
    if isinstance(value, str):
        redacted = value.replace(credential, "<redacted-credential>") if credential else value
        for secret in sorted({secret for secret in secrets if secret}, key=len, reverse=True):
            redacted = redacted.replace(secret, "<redacted-provider-secret>")
        return redacted
    return value


class ToolAuditLog:
    """Append sanitized, per-agent tool records to the run artifact."""

    def __init__(self, artifact_root: Path | str | os.PathLike[str], clock: Callable[[], str] = _utc_now) -> None:
        self._artifact_root = Path(artifact_root).expanduser().resolve()
        self._clock = clock
        self._lock = threading.Lock()
        self._secrets: set[str] = set()

    def add_redaction_secret(self, secret: str) -> None:
        if not isinstance(secret, str) or not secret:
            return
        with self._lock:
            self._secrets.add(secret)

    def record(
        self,
        credentials: VerifiedCredentials,
        operation: str,
        validated_input: Mapping[str, Any] | None,
        response: Mapping[str, Any],
    ) -> None:
        identity = credentials.identity
        run_root = self._artifact_root
        if not (run_root / "agents").is_dir():
            run_root = run_root / identity.run_id
        path = run_root / "agents" / identity.agent_id / "artifacts" / "tool_calls.jsonl"
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        with self._lock:
            secrets = tuple(self._secrets)
        event = {
            "timestamp": self._clock(),
            "run_id": identity.run_id,
            "agent_id": identity.agent_id,
            "condition": identity.condition.value,
            "task_id": identity.task_id,
            "operation": operation,
            "validated_input": _redact(validated_input, credentials.token, secrets),
            "response": _redact(response, credentials.token, secrets),
        }
        encoded = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
        with self._lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(encoded)
            path.chmod(0o600)
