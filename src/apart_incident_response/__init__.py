"""Controlled execution primitives for the accidental-coordination experiment."""

from typing import Any

from .board_storage import BoardMessage, BoardStorageError, BoardStore

_TOOL_EXPORTS = {
    "BOARD_TOOL_NAMES",
    "CORE_TOOL_NAMES",
    "BoardToolService",
    "ConstrainedToolService",
    "ControllerCredentialAuthority",
    "CredentialError",
    "TaskCatalog",
    "TaskDefinition",
    "TaskToolService",
    "TrustedRuntimeUsage",
    "ToolServiceError",
    "ToolServiceSocketServer",
    "ToolUnavailableError",
    "ToolValidationError",
}


def __getattr__(name: str) -> Any:
    if name not in _TOOL_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from . import tool_service

    value = getattr(tool_service, name)
    globals()[name] = value
    return value


__all__ = [
    "BOARD_TOOL_NAMES",
    "CORE_TOOL_NAMES",
    "BoardMessage",
    "BoardStorageError",
    "BoardStore",
    "BoardToolService",
    "ConstrainedToolService",
    "ControllerCredentialAuthority",
    "CredentialError",
    "TaskCatalog",
    "TaskDefinition",
    "TaskToolService",
    "TrustedRuntimeUsage",
    "ToolServiceError",
    "ToolServiceSocketServer",
    "ToolUnavailableError",
    "ToolValidationError",
]
