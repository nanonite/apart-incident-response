"""Safe, model-scoped paths for new experiment invocations.

The directory name is an invocation UUID, while the provider and encoded model
segments make a run easy to find without putting an untrusted model identifier
directly into a filesystem path.  Existing callers can continue to pass a
historical flat artifact root to their readers; this module only governs new
writers.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PureWindowsPath
import re
from typing import Any, Iterable, Mapping
from urllib.parse import quote, unquote
import uuid


SAFE_LABEL = re.compile(r"^[A-Za-z0-9._-]+$")
SAFE_MODEL_SLUG = re.compile(r"^(?:[A-Za-z0-9._~-]|%[0-9A-Fa-f]{2})+$")
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


class RunPathError(ValueError):
    """Raised when a run identity cannot be represented safely."""


def _safe_label(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or not SAFE_LABEL.fullmatch(value):
        raise RunPathError(f"{name} must be a non-empty safe path component")
    if value in {".", ".."}:
        raise RunPathError(f"{name} cannot be a traversal component")
    return value


def _model_text(model: str) -> str:
    if not isinstance(model, str) or not model or "\x00" in model:
        raise RunPathError("model must be a non-empty string without NUL bytes")
    if (
        model.startswith(("/", "\\"))
        or Path(model).is_absolute()
        or PureWindowsPath(model).is_absolute()
    ):
        raise RunPathError("model cannot be an absolute path")
    components = model.replace("\\", "/").split("/")
    if any(component in {"", ".", ".."} for component in components):
        raise RunPathError("model cannot contain empty or traversal components")
    return model


def encode_model_slug(model: str) -> str:
    """Encode the complete model identifier into one reversible path component."""

    model = _model_text(model)
    return quote(model, safe="-_.~")


def decode_model_slug(slug: str) -> str:
    """Reverse :func:`encode_model_slug` after validating the path component."""

    if not isinstance(slug, str) or not slug or not SAFE_MODEL_SLUG.fullmatch(slug):
        raise RunPathError("model slug must be one safe encoded path component")
    decoded = unquote(slug)
    _model_text(decoded)
    return decoded


def split_model_id(model: str, *, provider: str | None = None) -> tuple[str, str, str]:
    """Return provider, full model ID, and its encoded model path slug."""

    full_model = _model_text(model)
    if provider is None:
        if "/" in full_model:
            selected_provider = full_model.split("/", 1)[0]
            selected_provider = _safe_label(selected_provider, "provider")
        else:
            selected_provider = "unknown"
    else:
        selected_provider = _safe_label(provider, "provider")
    slug = encode_model_slug(full_model)
    if not SAFE_MODEL_SLUG.fullmatch(slug):
        raise RunPathError("model slug must be one safe encoded path component")
    return selected_provider, full_model, slug


def select_canonical_run_documents(
    paths: Iterable[Path | str],
) -> list[tuple[Path, Mapping[str, Any]]]:
    """Select one document per UUID, preferring the canonical UUID directory.

    Older one-shot writers may have left a compatibility copy at the output
    base beside the canonical artifact.  The copy has the same ``run_uuid``;
    a sibling ``run.json`` identifies the canonical document.  Documents
    without a UUID remain independent historical artifacts.
    """

    documents = []
    for raw_path in paths:
        path = Path(raw_path)
        document = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(document, Mapping):
            documents.append((path, document))

    canonical_by_uuid: dict[str, Path] = {}
    for path, document in documents:
        run_uuid = document.get("run_uuid")
        if isinstance(run_uuid, str) and (path.parent / "run.json").is_file():
            canonical_by_uuid.setdefault(run_uuid, path)

    selected: list[tuple[Path, Mapping[str, Any]]] = []
    selected_uuids: set[str] = set()
    for path, document in documents:
        run_uuid = document.get("run_uuid")
        if isinstance(run_uuid, str):
            canonical_path = canonical_by_uuid.get(run_uuid)
            if canonical_path is not None:
                if path != canonical_path:
                    continue
            elif run_uuid in selected_uuids:
                continue
            selected_uuids.add(run_uuid)
        selected.append((path, document))
    return selected


def validate_uuid4(value: str | uuid.UUID) -> str:
    """Validate and normalize an RFC 4122 version 4 UUID."""

    try:
        parsed = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (AttributeError, ValueError, TypeError) as exc:
        raise RunPathError("run_uuid must be a valid UUID v4") from exc
    if parsed.version != 4 or parsed.variant != uuid.RFC_4122 or not UUID_RE.fullmatch(str(parsed)):
        raise RunPathError("run_uuid must be a valid UUID v4")
    return str(parsed)


@dataclass(frozen=True)
class RunDirectory:
    """The resolved path and identity for one model invocation."""

    base_dir: Path
    path: Path
    provider: str
    model: str
    model_slug: str
    run_uuid: str
    run_id: str

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "artifact_schema": "model-run-v1",
            "run_uuid": self.run_uuid,
            "run_id": self.run_id,
            "provider": self.provider,
            "model": self.model,
            "model_slug": self.model_slug,
            "path": str(self.path),
        }

    def write_metadata(self, extra: Mapping[str, Any] | None = None) -> Path:
        """Write non-secret invocation metadata before provider work begins."""

        payload = {**self.metadata, **dict(extra or {})}
        path = self.path / "run.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        return path


def create_run_directory(
    output_base: Path | str,
    model: str,
    *,
    provider: str | None = None,
    run_id: str | None = None,
    run_uuid: str | uuid.UUID | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> RunDirectory:
    """Create one new model-scoped UUID directory with exclusive semantics.

    ``output_base`` is a directory containing provider directories.  The final
    UUID directory is created with ``exist_ok=False`` so a retry cannot reuse
    or overwrite an invocation.  ``run_id`` is a stable caller label and is
    deliberately separate from the generated UUID.
    """

    selected_provider, full_model, model_slug = split_model_id(model, provider=provider)
    base = Path(output_base).expanduser().resolve()
    selected_uuid = validate_uuid4(uuid.uuid4() if run_uuid is None else run_uuid)
    selected_run_id = _safe_label(run_id, "run_id") if run_id is not None else selected_uuid
    path = base / selected_provider / model_slug / selected_uuid
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise RunPathError(f"run UUID already exists: {path}") from exc
    path.chmod(0o700)
    run = RunDirectory(base, path, selected_provider, full_model, model_slug, selected_uuid, selected_run_id)
    run.write_metadata(metadata)
    return run


def find_run_by_uuid(root: Path | str, run_uuid: str | uuid.UUID) -> RunDirectory:
    """Find a new invocation by UUID for CLI/index tooling."""

    selected_uuid = validate_uuid4(run_uuid)
    base = Path(root).expanduser().resolve()
    matches = [candidate for candidate in base.rglob(selected_uuid) if candidate.is_dir() and candidate.name == selected_uuid]
    if len(matches) != 1:
        if not matches:
            raise RunPathError(f"run UUID not found below {base}: {selected_uuid}")
        raise RunPathError(f"run UUID is ambiguous below {base}: {selected_uuid}")
    path = matches[0]
    metadata_path = path / "run.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunPathError(f"run metadata is missing or invalid: {metadata_path}") from exc
    if not isinstance(metadata, Mapping):
        raise RunPathError(f"run metadata is not an object: {metadata_path}")
    provider = metadata.get("provider")
    model = metadata.get("model")
    model_slug = metadata.get("model_slug")
    run_id = metadata.get("run_id", selected_uuid)
    if not all(isinstance(value, str) and value for value in (provider, model, model_slug, run_id)):
        raise RunPathError(f"run metadata lacks identity fields: {metadata_path}")
    return RunDirectory(base, path, provider, model, model_slug, selected_uuid, run_id)


__all__ = [
    "RunDirectory",
    "RunPathError",
    "create_run_directory",
    "decode_model_slug",
    "encode_model_slug",
    "find_run_by_uuid",
    "select_canonical_run_documents",
    "split_model_id",
    "validate_uuid4",
]
