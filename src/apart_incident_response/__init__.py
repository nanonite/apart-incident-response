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
_EXPERIMENT_EXPORTS = {
    "CAPABILITY_PROFILES",
    "CapabilityProfile",
    "ExperimentController",
    "ExperimentProtocol",
    "FACTOR_LEVELS",
    "PROTOCOL_VERSION",
    "SwarmRun",
    "compute_metrics",
    "classify_uptake_outcomes",
    "detect_uptake",
    "replay_trace",
    "write_derived_artifacts",
}


def __getattr__(name: str) -> Any:
    if name not in _TOOL_EXPORTS:
        if name not in _EXPERIMENT_EXPORTS:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        if name in {"CAPABILITY_PROFILES", "CapabilityProfile"}:
            from . import capabilities

            value = getattr(capabilities, name)
        elif name in {"classify_uptake_outcomes", "compute_metrics", "detect_uptake", "replay_trace", "write_derived_artifacts"}:
            from . import telemetry

            value = getattr(telemetry, name)
        else:
            from . import controller

            value = getattr(controller, name)
        globals()[name] = value
        return value
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
    "CAPABILITY_PROFILES",
    "CapabilityProfile",
    "ExperimentController",
    "ExperimentProtocol",
    "FACTOR_LEVELS",
    "PROTOCOL_VERSION",
    "SwarmRun",
    "compute_metrics",
    "classify_uptake_outcomes",
    "detect_uptake",
    "replay_trace",
    "write_derived_artifacts",
]
