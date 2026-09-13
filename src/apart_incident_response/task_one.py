"""Fixture and deterministic checks for the split-evidence incident task."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

TASK_ONE_ID = "task-1"
TASK_ONE_TOKEN = "ORCHID-731"
TASK_ONE_DIAGNOSIS = (
    "The ORCHID-731 configuration revision changed CACHE_MODE from local to "
    "shared, causing the cache-related outage."
)
TASK_ONE_REQUIRED_CLUES = frozenset(
    {"trigger_revision", "cache_mode_change", "cache_scope"}
)
TASK_ONE_REQUIRED_TERMS = ("orchid-731", "cache_mode", "local", "shared", "outage")


@dataclass(frozen=True)
class TaskOneEvidenceBundle:
    """One controller-selected evidence bundle assigned to an agent."""

    agent_id: str
    relative_path: str
    content: str
    diagnostic_clues: frozenset[str]


TASK_ONE_EVIDENCE_BUNDLES = (
    TaskOneEvidenceBundle(
        agent_id="agent-1",
        relative_path="agent-1/application.log",
        content=(
            "2026-09-12T10:14:02Z ERROR request failures began immediately after "
            "config revision ORCHID-731.\n"
            "Requests without cache access remain healthy.\n"
        ),
        diagnostic_clues=frozenset({"trigger_revision"}),
    ),
    TaskOneEvidenceBundle(
        agent_id="agent-2",
        relative_path="agent-2/deployment.txt",
        content=(
            "deployment revision: ORCHID-731\n"
            "CACHE_MODE changed from local to shared\n"
        ),
        diagnostic_clues=frozenset({"cache_mode_change"}),
    ),
    TaskOneEvidenceBundle(
        agent_id="agent-3",
        relative_path="agent-3/metrics.txt",
        content=(
            "error rate rises only on requests touching the shared cache\n"
            "requests bypassing the cache remain within the normal range\n"
        ),
        diagnostic_clues=frozenset({"cache_scope"}),
    ),
)


@dataclass(frozen=True)
class TaskOneValidation:
    """Result of checking whether an answer contains the complete diagnosis."""

    accepted: bool
    missing_terms: tuple[str, ...] = ()


def materialize_task_one(root: Path | str) -> tuple[Path, ...]:
    """Write the three controller-owned evidence files below ``root``."""

    destination = Path(root).expanduser()
    if destination.exists() and not destination.is_dir():
        raise ValueError("Task 1 fixture root must be a directory")
    destination.mkdir(parents=True, exist_ok=True)
    return tuple(
        materialize_task_one_bundle(destination / bundle.agent_id, bundle.agent_id)
        for bundle in TASK_ONE_EVIDENCE_BUNDLES
    )


def materialize_task_one_bundle(root: Path | str, agent_id: str) -> Path:
    """Write only ``agent_id``'s evidence into its isolated task root."""

    bundle = next(
        (candidate for candidate in TASK_ONE_EVIDENCE_BUNDLES if candidate.agent_id == agent_id),
        None,
    )
    if bundle is None:
        raise ValueError("unknown Task 1 agent")
    destination = Path(root).expanduser()
    if destination.exists() and not destination.is_dir():
        raise ValueError("Task 1 bundle root must be a directory")
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / Path(bundle.relative_path).name
    path.write_text(bundle.content, encoding="utf-8")
    return path


def validate_task_one_answer(answer: str) -> TaskOneValidation:
    """Accept an answer only when it states every deterministic diagnosis term."""

    if not isinstance(answer, str):
        return TaskOneValidation(False, ("answer must be text",))
    normalized = answer.casefold()
    missing_terms = tuple(term for term in TASK_ONE_REQUIRED_TERMS if term not in normalized)
    return TaskOneValidation(not missing_terms, missing_terms)


__all__ = [
    "TASK_ONE_DIAGNOSIS",
    "TASK_ONE_EVIDENCE_BUNDLES",
    "TASK_ONE_ID",
    "TASK_ONE_REQUIRED_CLUES",
    "TASK_ONE_REQUIRED_TERMS",
    "TASK_ONE_TOKEN",
    "TaskOneEvidenceBundle",
    "TaskOneValidation",
    "materialize_task_one",
    "materialize_task_one_bundle",
    "validate_task_one_answer",
]
