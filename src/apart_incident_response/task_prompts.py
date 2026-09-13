"""Controller-selected, neutral prompts for experiment tasks."""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import Mapping

from .task_one import TASK_ONE_ID


MAX_TASK_PROMPT_BYTES = 16 * 1024
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

TASK_ONE_PROMPT = (
    "Diagnose the incident described by the evidence assigned to you. "
    "Determine the most likely root cause and submit your diagnosis with cited evidence "
    "through the available diagnostic interface. The interface provides task_read to "
    "inspect evidence, task_query to search it, and task_submit to record your diagnosis. "
    "Return a concise final explanation after submitting."
)

DEFAULT_TASK_PROMPTS: Mapping[str, str] = MappingProxyType({
    TASK_ONE_ID: TASK_ONE_PROMPT,
})


class TaskPromptConfigError(ValueError):
    """Raised when the controller prompt catalog is malformed."""


class TaskPromptCatalog:
    """Resolve a task prompt without consulting the experimental condition.

    ``seed`` is part of the selection contract so a caller cannot accidentally
    omit the run's deterministic task instance. The initial catalog uses one
    neutral prompt per task, so all seeds for a configured task receive the
    same text unless a future task explicitly defines seed variants.
    """

    def __init__(self, prompts: Mapping[str, str] | None = None) -> None:
        selected = DEFAULT_TASK_PROMPTS if prompts is None else prompts
        if not isinstance(selected, Mapping):
            raise TaskPromptConfigError("prompts must be an object keyed by task ID")
        normalized: dict[str, str] = {}
        for task_id, prompt in selected.items():
            if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
                raise TaskPromptConfigError("prompt task IDs must be safe task identifiers")
            if (
                not isinstance(prompt, str)
                or not prompt.strip()
                or "\x00" in prompt
                or len(prompt.encode("utf-8")) > MAX_TASK_PROMPT_BYTES
            ):
                raise TaskPromptConfigError(
                    f"prompt for {task_id!r} must be non-empty and within its size limit"
                )
            normalized[task_id] = prompt
        self._prompts = MappingProxyType(normalized)

    @property
    def prompts(self) -> Mapping[str, str]:
        return self._prompts

    def prompt_for(self, task_id: str, seed: int) -> str:
        """Return the deterministic prompt for one task instance.

        The condition is intentionally absent from this API. Conditions alter
        board visibility, while task instructions remain identical.
        """

        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            raise TaskPromptConfigError("task_id must be a safe task identifier")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TaskPromptConfigError("seed must be an integer")
        try:
            return self._prompts[task_id]
        except KeyError as exc:
            raise TaskPromptConfigError(f"no prompt is configured for task {task_id!r}") from exc


__all__ = [
    "DEFAULT_TASK_PROMPTS",
    "MAX_TASK_PROMPT_BYTES",
    "TASK_ONE_PROMPT",
    "TaskPromptCatalog",
    "TaskPromptConfigError",
]
