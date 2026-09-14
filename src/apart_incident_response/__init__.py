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
    "artifact_links_for_run",
    "build_agent_timeline",
    "sanitize_artifact",
    "triplet_artifact_links",
    "write_condition_index",
    "RunDirectory",
    "RunPathError",
    "create_run_directory",
    "decode_model_slug",
    "encode_model_slug",
    "find_run_by_uuid",
    "select_canonical_run_documents",
    "split_model_id",
    "validate_uuid4",
    "Qwen3ArtifactError",
    "LoadedLogitsArtifact",
    "derive_entropy_from_tensor",
    "entropy_from_rows",
    "load_full_logits_artifact",
    "replay_entropy",
    "validate_metadata",
    "write_full_logits_artifact",
    "Qwen3ModelBundle",
    "Qwen3RuntimeConfig",
    "Qwen3RuntimeError",
    "cuda_status",
    "dependency_versions",
    "load_qwen3",
    "resolve_device",
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
        elif name in {"artifact_links_for_run", "build_agent_timeline", "sanitize_artifact", "triplet_artifact_links", "write_condition_index"}:
            from . import run_artifacts

            value = getattr(run_artifacts, name)
        elif name in {
            "RunDirectory", "RunPathError", "create_run_directory", "decode_model_slug",
            "encode_model_slug", "find_run_by_uuid", "select_canonical_run_documents", "split_model_id", "validate_uuid4",
        }:
            from . import run_paths

            value = getattr(run_paths, name)
        elif name in {
            "Qwen3ArtifactError", "LoadedLogitsArtifact", "derive_entropy_from_tensor",
            "entropy_from_rows", "load_full_logits_artifact", "replay_entropy",
            "validate_metadata", "write_full_logits_artifact",
        }:
            from . import qwen3_artifacts

            value = getattr(qwen3_artifacts, name)
        elif name in {
            "Qwen3ModelBundle", "Qwen3RuntimeConfig", "Qwen3RuntimeError", "cuda_status",
            "dependency_versions", "load_qwen3", "resolve_device",
        }:
            from . import qwen3_runtime

            value = getattr(qwen3_runtime, name)
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
    "artifact_links_for_run",
    "build_agent_timeline",
    "sanitize_artifact",
    "triplet_artifact_links",
    "write_condition_index",
    "RunDirectory",
    "RunPathError",
    "create_run_directory",
    "decode_model_slug",
    "encode_model_slug",
    "find_run_by_uuid",
    "select_canonical_run_documents",
    "split_model_id",
    "validate_uuid4",
    "Qwen3ArtifactError",
    "LoadedLogitsArtifact",
    "derive_entropy_from_tensor",
    "entropy_from_rows",
    "load_full_logits_artifact",
    "replay_entropy",
    "validate_metadata",
    "write_full_logits_artifact",
    "Qwen3ModelBundle",
    "Qwen3RuntimeConfig",
    "Qwen3RuntimeError",
    "cuda_status",
    "dependency_versions",
    "load_qwen3",
    "resolve_device",
]
