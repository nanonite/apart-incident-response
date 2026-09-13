"""Controller router for the constrained task and board tool contract."""

from __future__ import annotations

from pathlib import Path
import os
from typing import Any, Callable, Mapping

from .board_tools import BoardToolService
from .runtime import AgentIdentity, Condition
from .task_tools import TaskCatalog, TaskDefinition, TaskToolService
from .tool_audit import ToolAuditLog, _utc_now
from .tool_contract import (
    BOARD_TOOL_NAMES,
    CORE_TOOL_NAMES,
    MAX_MESSAGE_BYTES,
    MAX_QUERY_RESULTS,
    MAX_READ_BYTES,
    MAX_READ_MESSAGES,
    MAX_TASK_FILE_BYTES,
    MAX_TOOL_REQUEST_BYTES,
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
    ) -> None:
        self.credentials = credentials or ControllerCredentialAuthority()
        self._task_service = task_service
        self._board_service = board_service
        self._audit = (
            ToolAuditLog(artifact_root, clock) if artifact_root is not None else None
        )

    def issue_credential(self, identity: AgentIdentity) -> str:
        return self.credentials.issue(identity)

    def available_tools(self, identity: AgentIdentity) -> tuple[str, ...]:
        if identity.condition is Condition.C0 or self._board_service is None:
            return CORE_TOOL_NAMES
        return CORE_TOOL_NAMES + BOARD_TOOL_NAMES

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
            result = self._dispatch(verified.identity, operation_name, input_object)
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
        return response

    def _check_operation(self, identity: AgentIdentity, operation: str) -> None:
        if operation in self.available_tools(identity):
            return
        if operation in BOARD_TOOL_NAMES and identity.condition is Condition.C0:
            raise ToolUnavailableError("board tools are unavailable in C0")
        raise ToolValidationError("unsupported tool")

    def _dispatch(
        self, identity: AgentIdentity, operation: str, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        if operation == "task_read":
            return self._task_service.read(identity, arguments)
        if operation == "task_query":
            return self._task_service.query(identity, arguments)
        if operation == "task_submit":
            return self._task_service.submit(identity, arguments)
        if self._board_service is None:
            raise ToolUnavailableError("board service is not mounted")
        if operation == "board_read":
            return self._board_service.read(identity, arguments)
        if operation == "board_append":
            return self._board_service.append(identity, arguments)
        raise ToolValidationError("unsupported tool")

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
    "MAX_QUERY_RESULTS",
    "MAX_READ_BYTES",
    "MAX_READ_MESSAGES",
    "MAX_TASK_FILE_BYTES",
    "MAX_TOOL_REQUEST_BYTES",
    "TaskCatalog",
    "TaskDefinition",
    "TaskToolService",
    "ToolServiceError",
    "ToolServiceSocketServer",
    "ToolUnavailableError",
    "ToolValidationError",
]
