"""Controller router for the constrained task and board tool contract."""

from __future__ import annotations

from pathlib import Path
import os
import threading
from typing import Any, Callable, Mapping

from .board_tools import BoardToolService
from .capabilities import get_capability_profile
from .runtime import AgentIdentity, Condition
from .task_tools import TaskCatalog, TaskDefinition, TaskToolService, TrustedRuntimeUsage
from .tool_audit import ToolAuditLog, _redact, _utc_now
from .tool_contract import (
    BOARD_TOOL_NAMES,
    CORE_TOOL_NAMES,
    MAX_DIAGNOSIS_BYTES,
    MAX_EVIDENCE_EXCERPT_BYTES,
    MAX_EVIDENCE_REFERENCES,
    MAX_MESSAGE_BYTES,
    MAX_QUERY_RESULTS,
    MAX_READ_BYTES,
    MAX_READ_MESSAGES,
    MAX_TASK_FILE_BYTES,
    MAX_TOOL_REQUEST_BYTES,
    MAX_SUBMISSION_BYTES,
    CredentialError,
    ToolServiceError,
    ToolUnavailableError,
    ToolValidationError,
    exact_keys,
    optional_positive_int,
    validate_object,
)
from .tool_credentials import ControllerCredentialAuthority
from .tool_transport import ToolServiceSocketServer


class ConstrainedToolService:
    """Route exactly five validated operations to task and board services."""

    def __init__(
        self,
        task_service: TaskToolService,
        board_service: BoardToolService | None = None,
        *,
        credentials: ControllerCredentialAuthority | None = None,
        artifact_root: Path | str | os.PathLike[str] | None = None,
        clock: Callable[[], str] = _utc_now,
        telemetry: Callable[[Mapping[str, Any]], None] | None = None,
        board_read_interval: int = 1,
    ) -> None:
        if isinstance(board_read_interval, bool) or not isinstance(board_read_interval, int) or board_read_interval < 1:
            raise ToolValidationError("board_read_interval must be a positive integer")
        self.credentials = credentials or ControllerCredentialAuthority()
        self._task_service = task_service
        self._board_service = board_service
        self._clock = clock
        self._telemetry = telemetry
        self._runtime_usage: dict[tuple[str, str], TrustedRuntimeUsage] = {}
        self._runtime_lock = threading.Lock()
        self._board_read_interval = board_read_interval
        self._board_read_attempts: dict[tuple[str, str], int] = {}
        self._board_read_lock = threading.Lock()
        self._board_append_attempts: dict[tuple[str, str], int] = {}
        self._board_append_lock = threading.Lock()
        self._redaction_secrets: set[str] = set()
        if artifact_root is not None:
            self._task_service.configure_submission_artifacts(artifact_root, clock)
        self._audit = (
            ToolAuditLog(artifact_root, clock) if artifact_root is not None else None
        )

    def add_redaction_secret(self, secret: str) -> None:
        if not isinstance(secret, str) or not secret:
            return
        with self._runtime_lock:
            self._redaction_secrets.add(secret)
        self._task_service.add_redaction_secret(secret)
        if self._audit is not None:
            self._audit.add_redaction_secret(secret)

    def update_runtime_usage(
        self, identity: AgentIdentity, total_tokens: int, tool_calls: int
    ) -> None:
        """Record controller-observed usage for the next task submission."""

        if not isinstance(identity, AgentIdentity):
            raise ToolValidationError("runtime identity is invalid")
        usage = TrustedRuntimeUsage(total_tokens, tool_calls)
        key = (identity.run_id, identity.agent_id)
        with self._runtime_lock:
            previous = self._runtime_usage.get(key)
            if previous is not None and (
                usage.total_tokens < previous.total_tokens
                or usage.tool_calls < previous.tool_calls
            ):
                raise ToolValidationError("runtime usage cannot decrease")
            self._runtime_usage[key] = usage

    def finalize_runtime_usage(self, identity: AgentIdentity) -> None:
        """Finalize a submitted artifact using the controller's drained counters."""

        usage = self._runtime_usage_for(identity)
        if usage is not None:
            self._task_service.finalize_submission_usage(identity, usage)

    def issue_credential(self, identity: AgentIdentity) -> str:
        return self.credentials.issue(identity)

    def available_tools(self, identity: AgentIdentity) -> tuple[str, ...]:
        profile = get_capability_profile(identity.capability_profile)
        task_tools = tuple(name for name in CORE_TOOL_NAMES if name in profile.task_tools)
        if identity.condition is Condition.C0 or self._board_service is None:
            return task_tools
        return task_tools + BOARD_TOOL_NAMES

    def invoke(self, credential: str, operation: Any, arguments: Any) -> dict[str, Any]:
        try:
            verified = self.credentials.verify(credential)
        except ToolServiceError as exc:
            return self._error_response(exc)
        operation_name = operation if isinstance(operation, str) else "<invalid>"
        validated_input: Any = arguments
        try:
            self._check_operation(verified.identity, operation_name)
            input_object = validate_object(arguments)
            validated_input = input_object
            result = self._dispatch(
                verified.identity,
                operation_name,
                input_object,
                credential=verified.token,
                runtime_usage=self._runtime_usage_for(verified.identity),
            )
            response: dict[str, Any] = {"ok": True, "result": result}
        except ToolServiceError as exc:
            response = self._error_response(exc)
        except Exception:
            response = {
                "ok": False,
                "error": {"code": "internal_error", "message": "tool service failed"},
            }
        if self._audit is not None:
            self._audit.record(verified, operation_name, validated_input, response)
        if self._telemetry is not None and operation_name in BOARD_TOOL_NAMES:
            self._record_board_telemetry(
                verified.identity, operation_name, validated_input, response
            )
        return response

    def _record_board_telemetry(
        self,
        identity: AgentIdentity,
        operation: str,
        arguments: Any,
        response: Mapping[str, Any],
    ) -> None:
        result = response.get("result") if response.get("ok") else None
        messages = result.get("messages", []) if isinstance(result, Mapping) else []
        if not isinstance(messages, list):
            messages = []
        serialized_messages = [
            {
                "sequence_id": message.get("sequence_id"),
                "source_agent": message.get("agent_id"),
                "message_size": message.get("message_size"),
                "message_body": message.get("message_body"),
            }
            for message in messages
            if isinstance(message, Mapping)
        ]
        append_result = result if operation == "board_append" and isinstance(result, Mapping) else {}
        cadence = result.get("cadence") if operation == "board_read" and isinstance(result, Mapping) else None
        event: dict[str, Any] = {
            "schema_version": 1,
            "timestamp": self._clock(),
            "run_id": identity.run_id,
            "agent_id": identity.agent_id,
            "condition": identity.condition.value,
            "operation": operation,
            "cursor_before": arguments.get("after_sequence_id", 0) if isinstance(arguments, Mapping) else None,
            "requested_limit": arguments.get("limit") if isinstance(arguments, Mapping) else None,
            "message_ids": [message.get("sequence_id") for message in serialized_messages],
            "messages": serialized_messages,
            "bytes_read": sum(int(message.get("message_size") or 0) for message in serialized_messages),
            "bytes_written": int(append_result.get("message_size") or 0),
            "message_id": append_result.get("sequence_id"),
            "message": arguments.get("message") if operation == "board_append" and isinstance(arguments, Mapping) else None,
            "cadence": dict(cadence) if isinstance(cadence, Mapping) else None,
            "ok": bool(response.get("ok")),
        }
        if not response.get("ok"):
            error = response.get("error")
            event["error"] = dict(error) if isinstance(error, Mapping) else {"code": "unknown"}
        with self._runtime_lock:
            secrets = tuple(self._redaction_secrets)
        event = _redact(event, None, secrets)
        try:
            self._telemetry(event)
        except Exception:
            # Telemetry must not alter an authenticated tool result. A missing
            # event remains diagnosable from the raw audit and manifest files.
            return

    def _check_operation(self, identity: AgentIdentity, operation: str) -> None:
        if operation in self.available_tools(identity):
            return
        if operation in BOARD_TOOL_NAMES and identity.condition is Condition.C0:
            raise ToolUnavailableError("board tools are unavailable in C0")
        if operation in CORE_TOOL_NAMES:
            raise ToolUnavailableError(
                f"{operation} is not exposed by capability profile "
                f"{identity.capability_profile}"
            )
        raise ToolValidationError("unsupported tool")

    def _dispatch(
        self,
        identity: AgentIdentity,
        operation: str,
        arguments: Mapping[str, Any],
        *,
        credential: str,
        runtime_usage: TrustedRuntimeUsage | None,
    ) -> dict[str, Any]:
        if operation == "task_read":
            return self._task_service.read(identity, arguments)
        if operation == "task_query":
            return self._task_service.query(identity, arguments)
        if operation == "task_submit":
            self._require_board_engagement(identity)
            return self._task_service.submit(
                identity,
                arguments,
                runtime_usage=runtime_usage,
                credential=credential,
            )
        if self._board_service is None:
            raise ToolUnavailableError("board service is not mounted")
        if operation == "board_read":
            return self._board_read(identity, arguments)
        if operation == "board_append":
            key = (identity.run_id, identity.agent_id)
            with self._board_append_lock:
                self._board_append_attempts[key] = self._board_append_attempts.get(key, 0) + 1
            return self._board_service.append(identity, arguments)
        raise ToolValidationError("unsupported tool")

    def _require_board_engagement(self, identity: AgentIdentity) -> None:
        """Gate task_submit on genuine board engagement where a board exists.

        Tool-description and system-prompt nudges (advisory only) measurably
        failed to raise board usage above near-zero across many live runs.
        This is a hard, code-enforced floor instead: an agent in a condition
        with a board must have called both board_read and board_append at
        least once before it may submit. C0 (no board at all) is unaffected.
        """

        if self._board_service is None or identity.condition is Condition.C0:
            return
        key = (identity.run_id, identity.agent_id)
        with self._board_read_lock:
            has_read = self._board_read_attempts.get(key, 0) > 0
        with self._board_append_lock:
            has_appended = self._board_append_attempts.get(key, 0) > 0
        if has_read and has_appended:
            return
        missing = [
            name for name, done in (("board_read", has_read), ("board_append", has_appended)) if not done
        ]
        raise ToolUnavailableError(
            "task_submit requires calling " + " and ".join(missing) + " at least once first"
        )

    def _board_read(
        self, identity: AgentIdentity, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Expose board messages only on scheduled controller-owned read slots."""

        if self._board_service is None:
            raise ToolUnavailableError("board service is not mounted")
        exact_keys(arguments, {"after_sequence_id", "limit"})
        cursor = arguments.get("after_sequence_id", 0)
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise ToolValidationError("after_sequence_id must be a non-negative integer")
        optional_positive_int(arguments, "limit", 20, MAX_READ_MESSAGES)
        key = (identity.run_id, identity.agent_id)
        with self._board_read_lock:
            attempt = self._board_read_attempts.get(key, 0) + 1
            self._board_read_attempts[key] = attempt
        scheduled = (attempt - 1) % self._board_read_interval == 0
        cadence = {
            "interval": self._board_read_interval,
            "attempt": attempt,
            "scheduled_opportunity": scheduled,
        }
        if not scheduled:
            return {
                "messages": [],
                "next_cursor": cursor,
                "has_more": True,
                "cadence": {**cadence, "messages_delivered": 0},
            }
        result = self._board_service.read(identity, arguments)
        result["cadence"] = {
            **cadence,
            "messages_delivered": len(result.get("messages", [])),
        }
        return result

    def _runtime_usage_for(self, identity: AgentIdentity) -> TrustedRuntimeUsage | None:
        with self._runtime_lock:
            return self._runtime_usage.get((identity.run_id, identity.agent_id))

    @staticmethod
    def _error_response(error: ToolServiceError) -> dict[str, Any]:
        return {"ok": False, "error": {"code": error.code, "message": str(error)}}


__all__ = [
    "BOARD_TOOL_NAMES",
    "CORE_TOOL_NAMES",
    "BoardToolService",
    "ConstrainedToolService",
    "ControllerCredentialAuthority",
    "CredentialError",
    "MAX_MESSAGE_BYTES",
    "MAX_DIAGNOSIS_BYTES",
    "MAX_EVIDENCE_EXCERPT_BYTES",
    "MAX_EVIDENCE_REFERENCES",
    "MAX_QUERY_RESULTS",
    "MAX_READ_BYTES",
    "MAX_READ_MESSAGES",
    "MAX_TASK_FILE_BYTES",
    "MAX_TOOL_REQUEST_BYTES",
    "MAX_SUBMISSION_BYTES",
    "TaskCatalog",
    "TaskDefinition",
    "TaskToolService",
    "TrustedRuntimeUsage",
    "ToolServiceError",
    "ToolServiceSocketServer",
    "ToolUnavailableError",
    "ToolValidationError",
]
