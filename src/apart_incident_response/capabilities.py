"""Versioned, explicit diagnostic capability profiles.

Profiles only change task-diagnostic tools. Board visibility is always derived
from the experimental condition, so a profile can never create a second
cross-agent channel or silently change C0/C1/C2 semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping


@dataclass(frozen=True)
class CapabilityProfile:
    name: str
    version: str
    task_tools: tuple[str, ...]
    permissions: tuple[str, ...]

    @property
    def profile_id(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def sha256(self) -> str:
        payload = json.dumps(self._base_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _base_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "task_tools": list(self.task_tools),
            "permissions": list(self.permissions),
            "profile_id": self.profile_id,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._base_dict(), "sha256": self.sha256}


CAPABILITY_PROFILES: Mapping[str, CapabilityProfile] = {
    "task-diagnostic-v1": CapabilityProfile(
        name="task-diagnostic",
        version="1",
        task_tools=("task_read", "task_query", "task_submit"),
        permissions=("read-assigned-task", "query-assigned-task", "submit-diagnosis"),
    ),
    "task-read-submit-v1": CapabilityProfile(
        name="task-read-submit",
        version="1",
        task_tools=("task_read", "task_submit"),
        permissions=("read-assigned-task", "submit-diagnosis"),
    ),
}


def get_capability_profile(name: str) -> CapabilityProfile:
    """Resolve a controller-selected profile and fail closed for unknown names."""

    if not isinstance(name, str) or name not in CAPABILITY_PROFILES:
        raise ValueError(f"unknown capability profile: {name!r}")
    return CAPABILITY_PROFILES[name]


__all__ = ["CAPABILITY_PROFILES", "CapabilityProfile", "get_capability_profile"]
