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
from .tool_audit import ToolAuditLog, _utc_now
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
    ) -> None:
        self.credentials = credentials or ControllerCredentialAuthority()
        self._task_service = task_service
        self._board_service = board_service
        self._clock = clock
        self._telemetry = telemetry
        self._runtime_usage: dict[tuple[str, str], TrustedRuntimeUsage] = {}
        self._runtime_lock = threading.Lock()
        if artifact_root is not None:
            self._task_service.configure_submission_artifacts(artifact_root, clock)
        self._audit = (
            ToolAuditLog(artifact_root, clock) if artifact_root is not None else None
        )

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
            "ok": bool(response.get("ok")),
        }
        if not response.get("ok"):
            error = response.get("error")
            event["error"] = dict(error) if isinstance(error, Mapping) else {"code": "unknown"}
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
            return self._task_service.submit(
                identity,
                arguments,
                runtime_usage=runtime_usage,
                credential=credential,
            )
        if self._board_service is None:
            raise ToolUnavailableError("board service is not mounted")
        if operation == "board_read":
            return self._board_service.read(identity, arguments)
        if operation == "board_append":
            return self._board_service.append(identity, arguments)
        raise ToolValidationError("unsupported tool")

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
