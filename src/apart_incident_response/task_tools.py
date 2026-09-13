"""Task-scoped implementations of the three core agent tools."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .runtime import AgentIdentity
from .task_one import TASK_ONE_ID, validate_task_one_answer
from .tool_contract import (
    MAX_QUERY_RESULTS,
    MAX_DIAGNOSIS_BYTES,
    MAX_EVIDENCE_EXCERPT_BYTES,
    MAX_EVIDENCE_REFERENCES,
    MAX_SUBMISSION_BYTES,
    MAX_TASK_FILE_BYTES,
    ToolPermissionError,
    ToolValidationError,
    exact_keys,
    optional_positive_int,
    required_text,
    validate_object,
    validate_relative_path,
)


@dataclass(frozen=True)
class TaskDefinition:
    """A controller-selected, read-only task fixture."""

    task_id: str
    root: Path | str | os.PathLike[str]
    allowed_paths: tuple[str, ...] = ()
    answer_validator: Callable[[str], Any] | None = None

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
        if self.answer_validator is None and self.task_id == TASK_ONE_ID:
            object.__setattr__(self, "answer_validator", validate_task_one_answer)
        elif self.answer_validator is not None and not callable(self.answer_validator):
            raise ToolValidationError("answer_validator must be callable")


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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class TrustedRuntimeUsage:
    """Usage counters supplied by the controller runtime, never by the agent."""

    total_tokens: int
    tool_calls: int

    def __post_init__(self) -> None:
        for name, value in (("total_tokens", self.total_tokens), ("tool_calls", self.tool_calls)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ToolValidationError(f"{name} must be a non-negative integer")


class TaskToolService:
    """Implement task reads, literal queries, and idempotent submissions."""

    def __init__(
        self,
        catalog: TaskCatalog,
        *,
        artifact_root: Path | str | os.PathLike[str] | None = None,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self._catalog = catalog
        self._submissions: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()
        self._artifact_root = (
            Path(artifact_root).expanduser().resolve() if artifact_root is not None else None
        )
        self._clock = clock

    def configure_submission_artifacts(
        self, artifact_root: Path | str | os.PathLike[str], clock: Callable[[], str]
    ) -> None:
        root = Path(artifact_root).expanduser().resolve()
        with self._lock:
            if self._artifact_root is not None and self._artifact_root != root:
                raise ToolValidationError("submission artifact root cannot be changed")
            self._artifact_root = root
            self._clock = clock

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

    def submit(
        self,
        identity: AgentIdentity,
        arguments: Mapping[str, Any],
        *,
        runtime_usage: TrustedRuntimeUsage | None,
        credential: str,
    ) -> dict[str, Any]:
        exact_keys(arguments, {"diagnosis", "evidence"})
        definition = self._catalog.get(identity.task_id)
        if not isinstance(runtime_usage, TrustedRuntimeUsage):
            raise ToolValidationError("trusted runtime usage is unavailable")
        if not isinstance(credential, str) or not credential:
            raise ToolValidationError("controller credential is unavailable")
        if self._artifact_root is None:
            raise ToolValidationError("submission artifact storage is unavailable")
        diagnosis = required_text(arguments, "diagnosis", MAX_DIAGNOSIS_BYTES)
        if definition.answer_validator is not None:
            validation = definition.answer_validator(diagnosis)
            if not getattr(validation, "accepted", False):
                raise ToolValidationError("diagnosis failed the authenticated task validator")
        evidence = self._validate_evidence(definition, arguments.get("evidence"))
        safe_diagnosis = self._redact(diagnosis, credential)
        safe_evidence = self._redact(evidence, credential)
        digest = self._submission_hash(identity, safe_diagnosis, safe_evidence)
        payload = {
            "schema_version": 1,
            "submission_id": f"sha256:{digest}",
            "submission_sha256": digest,
            "run_id": identity.run_id,
            "agent_id": identity.agent_id,
            "task_id": identity.task_id,
            "condition": identity.condition.value,
            "seed": identity.seed,
            "timestamp": self._clock(),
            "diagnosis": safe_diagnosis,
            "evidence": safe_evidence,
            "token_usage": {
                "source": "controller_runtime_accounting",
                "status": "provisional",
                "total_tokens": runtime_usage.total_tokens,
                "tool_calls": runtime_usage.tool_calls,
            },
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if len(encoded.encode("utf-8")) > MAX_SUBMISSION_BYTES:
            raise ToolValidationError("submission exceeds the size limit")
        key = (identity.run_id, identity.agent_id)
        path = self._artifact_path(identity)
        with self._lock:
            if path.exists():
                existing = self._read_existing_submission(path, identity)
                if existing != digest:
                    raise ToolValidationError("a different submission already exists for this agent")
                self._submissions[key] = digest
                return self._submission_response(identity, digest)
            previous = self._submissions.get(key)
            if previous is not None and previous != digest:
                raise ToolValidationError("a different submission already exists for this agent")
            self._write_submission(path, encoded)
            self._submissions[key] = digest
        return self._submission_response(identity, digest)

    def finalize_submission_usage(
        self, identity: AgentIdentity, runtime_usage: TrustedRuntimeUsage
    ) -> None:
        """Replace the submission-time usage snapshot after the run drains."""

        if not isinstance(runtime_usage, TrustedRuntimeUsage):
            raise ToolValidationError("trusted runtime usage is unavailable")
        if self._artifact_root is None:
            return
        path = self._artifact_path(identity)
        with self._lock:
            if not path.exists():
                return
            self._read_existing_submission(path, identity)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ToolValidationError("existing submission artifact is invalid") from exc
            if not isinstance(payload, dict):
                raise ToolValidationError("existing submission artifact is invalid")
            payload["token_usage"] = {
                "source": "controller_runtime_accounting",
                "status": "final",
                "total_tokens": runtime_usage.total_tokens,
                "tool_calls": runtime_usage.tool_calls,
            }
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
            if len(encoded.encode("utf-8")) > MAX_SUBMISSION_BYTES:
                raise ToolValidationError("submission exceeds the size limit")
            self._write_submission(path, encoded)

    @staticmethod
    def _submission_response(identity: AgentIdentity, digest: str) -> dict[str, Any]:
        return {
            "accepted": True,
            "task_id": identity.task_id,
            "submission_id": f"sha256:{digest}",
            "submission_sha256": digest,
        }

    def _artifact_path(self, identity: AgentIdentity) -> Path:
        assert self._artifact_root is not None
        return (
            self._artifact_root
            / identity.run_id
            / "agents"
            / identity.agent_id
            / "artifacts"
            / "task_submission.json"
        )

    @staticmethod
    def _submission_hash(
        identity: AgentIdentity, diagnosis: str, evidence: list[dict[str, Any]]
    ) -> str:
        canonical = json.dumps(
            {
                "run_id": identity.run_id,
                "agent_id": identity.agent_id,
                "task_id": identity.task_id,
                "condition": identity.condition.value,
                "seed": identity.seed,
                "diagnosis": diagnosis,
                "evidence": evidence,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(canonical.encode("utf-8")) > MAX_SUBMISSION_BYTES:
            raise ToolValidationError("submission exceeds the size limit")
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _read_existing_submission(self, path: Path, identity: AgentIdentity) -> str:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ToolValidationError("existing submission artifact is invalid") from exc
        if not isinstance(existing, Mapping):
            raise ToolValidationError("existing submission artifact is invalid")
        if any(existing.get(field) != value for field, value in {
            "run_id": identity.run_id,
            "agent_id": identity.agent_id,
            "task_id": identity.task_id,
            "condition": identity.condition.value,
            "seed": identity.seed,
        }.items()):
            raise ToolValidationError("existing submission identity does not match")
        diagnosis = existing.get("diagnosis")
        evidence = existing.get("evidence")
        stored_digest = existing.get("submission_sha256")
        if not isinstance(diagnosis, str) or not isinstance(evidence, list) or not isinstance(stored_digest, str):
            raise ToolValidationError("existing submission artifact is invalid")
        digest = self._submission_hash(identity, diagnosis, evidence)
        if stored_digest != digest or existing.get("submission_id") != f"sha256:{digest}":
            raise ToolValidationError("existing submission artifact hash is invalid")
        return digest

    def _write_submission(self, path: Path, encoded: str) -> None:
        assert self._artifact_root is not None
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        current = path.parent
        while True:
            current.chmod(0o700)
            if current == self._artifact_root:
                break
            try:
                current.relative_to(self._artifact_root)
            except ValueError as exc:
                raise ToolValidationError("submission artifact path escaped its root") from exc
            if current.parent == current:
                break
            current = current.parent
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".task_submission.", suffix=".tmp", dir=path.parent
            )
            temporary_path = Path(temporary_name)
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
            path.chmod(0o600)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _validate_evidence(
        self, definition: TaskDefinition, raw_evidence: Any
    ) -> list[dict[str, Any]]:
        if not isinstance(raw_evidence, list) or not raw_evidence:
            raise ToolValidationError("evidence must be a non-empty list")
        if len(raw_evidence) > MAX_EVIDENCE_REFERENCES:
            raise ToolValidationError("too many evidence references")
        normalized: list[dict[str, Any]] = []
        for raw_reference in raw_evidence:
            reference = validate_object(raw_reference)
            exact_keys(reference, {"path", "excerpt", "line_start", "line_end"})
            relative_path = validate_relative_path(reference.get("path"), "evidence path")
            self._check_allowed(definition, relative_path)
            content = self._read_file(_resolve_inside(definition.root, relative_path))
            line_start = reference.get("line_start")
            line_end = reference.get("line_end")
            if ("line_start" in reference and line_start is None) or ("line_end" in reference and line_end is None):
                raise ToolValidationError("line references must be positive integers")
            if (line_start is None) != (line_end is None):
                raise ToolValidationError("line_start and line_end must be supplied together")
            selected = content
            normalized_reference: dict[str, Any] = {"path": relative_path}
            if line_start is not None:
                for name, value in (("line_start", line_start), ("line_end", line_end)):
                    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                        raise ToolValidationError(f"{name} must be a positive integer")
                lines = content.splitlines()
                if line_end < line_start or line_end > len(lines):
                    raise ToolValidationError("evidence line range is outside the task file")
                selected = "\n".join(lines[line_start - 1 : line_end])
                normalized_reference.update({"line_start": line_start, "line_end": line_end})
            excerpt = reference.get("excerpt")
            if "excerpt" in reference and excerpt is None:
                raise ToolValidationError("evidence excerpt is invalid")
            if excerpt is not None:
                if not isinstance(excerpt, str) or not excerpt.strip() or len(excerpt.encode("utf-8")) > MAX_EVIDENCE_EXCERPT_BYTES:
                    raise ToolValidationError("evidence excerpt is invalid or too large")
                if excerpt not in selected:
                    raise ToolValidationError("evidence excerpt does not match the referenced task content")
                normalized_reference["excerpt"] = excerpt
            if line_start is None and excerpt is None:
                raise ToolValidationError("evidence requires an excerpt or line range")
            normalized.append(normalized_reference)
        return normalized

    @staticmethod
    def _redact(value: Any, credential: str) -> Any:
        if isinstance(value, Mapping):
            return {str(key): TaskToolService._redact(item, credential) for key, item in value.items()}
        if isinstance(value, list):
            return [TaskToolService._redact(item, credential) for item in value]
        if isinstance(value, str):
            return value.replace(credential, "<redacted-credential>")
        return value

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
