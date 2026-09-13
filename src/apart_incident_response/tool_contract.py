"""Shared limits and errors for the constrained controller tool contract."""

from __future__ import annotations

from typing import Any, Mapping

from .runtime import AgentIdentity


CORE_TOOL_NAMES = ("task_read", "task_query", "task_submit")
BOARD_TOOL_NAMES = ("board_read", "board_append")
MAX_MESSAGE_BYTES = 8 * 1024
MAX_READ_MESSAGES = 50
MAX_READ_BYTES = 64 * 1024
MAX_QUERY_RESULTS = 50
MAX_TASK_FILE_BYTES = 64 * 1024
MAX_TOOL_REQUEST_BYTES = 128 * 1024


class ToolServiceError(ValueError):
    """Base class for safe, agent-visible tool errors."""

    code = "tool_error"


class CredentialError(ToolServiceError):
    """Raised when a request does not carry a controller-issued credential."""

    code = "invalid_credential"


class ToolValidationError(ToolServiceError):
    """Raised for malformed or unsupported tool arguments."""

    code = "invalid_arguments"


class ToolPermissionError(ToolServiceError):
    """Raised when the authenticated caller lacks access to an operation."""

    code = "permission_denied"


class ToolUnavailableError(ToolServiceError):
    """Raised when a condition deliberately omits a capability."""

    code = "tool_unavailable"


def validate_object(arguments: Any) -> Mapping[str, Any]:
    if not isinstance(arguments, Mapping):
        raise ToolValidationError("tool arguments must be an object")
    return arguments


def exact_keys(arguments: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = set(arguments) - allowed
    if unknown:
        names = ", ".join(sorted(str(name) for name in unknown))
        raise ToolValidationError(f"unsupported argument(s): {names}")


def required_text(arguments: Mapping[str, Any], name: str, maximum: int) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > maximum:
        raise ToolValidationError(f"{name} must be a non-empty string within its size limit")
    return value


def optional_positive_int(
    arguments: Mapping[str, Any], name: str, default: int, maximum: int
) -> int:
    value = arguments.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ToolValidationError(f"{name} must be an integer from 1 through {maximum}")
    return value


def validate_relative_path(value: Any, field_name: str = "path") -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ToolValidationError(f"{field_name} must be a relative path")
    if "\x00" in value or "\\" in value or value.startswith("/"):
        raise ToolValidationError(f"{field_name} must be a relative POSIX path")
    parts = value.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise ToolValidationError(f"{field_name} contains an unsupported path component")
    return value
