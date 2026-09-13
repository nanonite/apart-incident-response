"""Task-scoped implementations of the three core agent tools."""

from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .runtime import AgentIdentity
from .tool_contract import (
    MAX_QUERY_RESULTS,
    MAX_TASK_FILE_BYTES,
    ToolPermissionError,
    ToolValidationError,
    exact_keys,
    optional_positive_int,
    required_text,
    validate_relative_path,
)


@dataclass(frozen=True)
class TaskDefinition:
    """A controller-selected, read-only task fixture."""

    task_id: str
    root: Path | str | os.PathLike[str]
    allowed_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ToolValidationError("task_id must be a non-empty string")
        raw_root = Path(self.root).expanduser()
        if raw_root.is_symlink():
            raise ToolValidationError("task root must be a controller-owned directory")
        root = raw_root.resolve()
        if not root.is_dir():
            raise ToolValidationError("task root must be a controller-owned directory")
        object.__setattr__(self, "root", root)
        for path in self.allowed_paths:
            validate_relative_path(path, "allowed task path")


class TaskCatalog:
    """Resolve task fixtures without accepting task roots from agents."""

    def __init__(self, definitions: Mapping[str, TaskDefinition] | None = None) -> None:
        self._definitions = dict(definitions or {})
        if any(key != value.task_id for key, value in self._definitions.items()):
            raise ToolValidationError("task catalog keys must match task IDs")

    def get(self, task_id: str) -> TaskDefinition:
        definition = self._definitions.get(task_id)
        if definition is None:
            raise ToolPermissionError("the authenticated task is not registered")
        return definition


def _resolve_inside(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ToolPermissionError("task path escapes the authenticated task root") from exc
    return candidate


def _relative_to(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


class TaskToolService:
    """Implement task reads, literal queries, and idempotent submissions."""

    def __init__(self, catalog: TaskCatalog) -> None:
        self._catalog = catalog
        self._submissions: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def read(self, identity: AgentIdentity, arguments: Mapping[str, Any]) -> dict[str, Any]:
        exact_keys(arguments, {"path"})
        definition = self._catalog.get(identity.task_id)
        relative_path = validate_relative_path(arguments.get("path"))
        self._check_allowed(definition, relative_path)
        content = self._read_file(_resolve_inside(definition.root, relative_path))
        return {
            "task_id": identity.task_id,
            "path": relative_path,
            "content": content,
            "size": len(content.encode("utf-8")),
        }

    def query(self, identity: AgentIdentity, arguments: Mapping[str, Any]) -> dict[str, Any]:
        exact_keys(arguments, {"query", "path", "max_results"})
        definition = self._catalog.get(identity.task_id)
        query = required_text(arguments, "query", 256).casefold()
        max_results = optional_positive_int(arguments, "max_results", 20, MAX_QUERY_RESULTS)
        base = definition.root
        if "path" in arguments:
            relative_path = validate_relative_path(arguments["path"])
            self._check_allowed(definition, relative_path)
            base = _resolve_inside(definition.root, relative_path)
        return self._find_matches(definition, base, query, max_results)

    def submit(self, identity: AgentIdentity, arguments: Mapping[str, Any]) -> dict[str, Any]:
        exact_keys(arguments, {"answer"})
        answer = required_text(arguments, "answer", 16 * 1024)
        key = (identity.run_id, identity.agent_id)
        digest = hashlib.sha256(answer.encode("utf-8")).hexdigest()
        with self._lock:
            previous = self._submissions.get(key)
            if previous is not None and previous != digest:
                raise ToolValidationError("a different submission already exists for this agent")
            self._submissions[key] = digest
        return {"accepted": True, "task_id": identity.task_id, "submission_sha256": digest}

    @staticmethod
    def _check_allowed(definition: TaskDefinition, relative_path: str) -> None:
        if definition.allowed_paths and relative_path not in definition.allowed_paths:
            raise ToolPermissionError("path is outside the authenticated task permission set")

    @staticmethod
    def _read_file(path: Path) -> str:
        if not path.is_file():
            raise ToolPermissionError("task path is not a readable file")
        if path.stat().st_size > MAX_TASK_FILE_BYTES:
            raise ToolPermissionError("task file exceeds the read size limit")
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolPermissionError("task file is not UTF-8 text") from exc

    def _find_matches(
        self, definition: TaskDefinition, base: Path, query: str, max_results: int
    ) -> dict[str, Any]:
        matches: list[dict[str, Any]] = []
        for path in self._query_files(definition, base):
            for line_number, line in enumerate(self._read_file(path).splitlines(), 1):
                if query not in line.casefold():
                    continue
                matches.append({"path": _relative_to(definition.root, path), "line": line_number, "text": line[:4096]})
                if len(matches) >= max_results:
                    return {"task_id": definition.task_id, "matches": matches, "truncated": True}
        return {"task_id": definition.task_id, "matches": matches, "truncated": False}

    def _query_files(self, definition: TaskDefinition, base: Path) -> list[Path]:
        if not base.exists() or not base.is_dir():
            if base.is_file():
                return [base]
            raise ToolPermissionError("query path is not a task directory or file")
        candidates: list[Path] = []
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative_path = _relative_to(definition.root, path.resolve())
            try:
                self._check_allowed(definition, relative_path)
            except ToolPermissionError:
                continue
            if path.stat().st_size <= MAX_TASK_FILE_BYTES:
                candidates.append(path)
        return candidates
