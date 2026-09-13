"""Optional dependency loader for the isolated Qwen3-8B runtime."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.metadata
from pathlib import Path
from typing import Any, Mapping


class Qwen3RuntimeError(RuntimeError):
    """Raised when the pinned local-model runtime cannot be used."""


@dataclass(frozen=True)
class Qwen3RuntimeConfig:
    model_id: str
    revision: str
    tokenizer_revision: str
    max_seq_length: int = 4096
    device: str = "auto"
    load_in_4bit: bool = True
    local_files_only: bool = False

    def __post_init__(self) -> None:
        if not self.model_id or not self.revision or not self.tokenizer_revision:
            raise Qwen3RuntimeError("model and tokenizer revisions are required")
        if self.max_seq_length < 1:
            raise Qwen3RuntimeError("max_seq_length must be positive")
        if self.device not in {"auto", "cuda", "cpu"}:
            raise Qwen3RuntimeError("device must be auto, cuda, or cpu")
        if self.device == "cpu" and self.load_in_4bit:
            raise Qwen3RuntimeError("4-bit bitsandbytes loading is CUDA-only; choose --device cpu explicitly")


@dataclass(frozen=True)
class Qwen3ModelBundle:
    model: Any
    tokenizer: Any
    device: Any
    runtime: Mapping[str, Any]


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def dependency_versions() -> dict[str, str]:
    """Return installed versions without importing CUDA-heavy modules."""

    return {
        name: _package_version(name)
        for name in ("torch", "transformers", "unsloth", "safetensors", "accelerate", "bitsandbytes", "peft")
    }


def cuda_status() -> dict[str, Any]:
    """Describe CUDA availability and give a precise missing-dependency reason."""

    try:
        import torch
    except ImportError:
        return {"available": False, "reason": "torch is not installed", "torch_cuda": None}
    available = bool(torch.cuda.is_available())
    details: dict[str, Any] = {
        "available": available,
        "torch_cuda": torch.version.cuda,
        "device_count": int(torch.cuda.device_count()) if available else 0,
    }
    if available:
        details["device_name"] = torch.cuda.get_device_name(0)
    else:
        details["reason"] = "CUDA is unavailable to PyTorch"
    return details


def resolve_device(requested: str) -> str:
    """Resolve auto/cuda/cpu without silently changing an experiment path."""

    status = cuda_status()
    if requested == "cpu":
        return "cpu"
    if not status.get("available"):
        reason = status.get("reason", "CUDA is unavailable")
        raise Qwen3RuntimeError(f"CUDA is required for device={requested}: {reason}; choose --device cpu explicitly")
    return "cuda"


def _model_device(model: Any, requested: str) -> Any:
    if requested == "cpu":
        import torch

        return torch.device("cpu")
    try:
        return next(model.parameters()).device
    except (AttributeError, StopIteration) as exc:
        raise Qwen3RuntimeError("loaded Qwen3 model has no parameter device") from exc


def load_qwen3(config: Qwen3RuntimeConfig, *, cache_dir: Path | str | None = None) -> Qwen3ModelBundle:
    """Load the pinned checkpoint through Unsloth's Transformers-compatible API."""

    resolved_device = resolve_device(config.device)
    try:
        import torch
        from unsloth import FastLanguageModel
    except ImportError as exc:
        raise Qwen3RuntimeError(
            "the Qwen3 runtime needs the pinned torch and unsloth packages; build Dockerfile.qwen3 first"
        ) from exc
    kwargs: dict[str, Any] = {
        "model_name": config.model_id,
        "revision": config.revision,
        "tokenizer_name": config.model_id,
        "max_seq_length": config.max_seq_length,
        "load_in_4bit": config.load_in_4bit and resolved_device == "cuda",
        "dtype": torch.bfloat16 if resolved_device == "cuda" else torch.float32,
        "device_map": "auto" if resolved_device == "cuda" else {"": "cpu"},
        "trust_remote_code": False,
        "local_files_only": config.local_files_only,
    }
    if cache_dir is not None:
        cache_path = Path(cache_dir).expanduser().resolve()
        kwargs["cache_dir"] = str(cache_path)
    try:
        model, tokenizer = FastLanguageModel.from_pretrained(**kwargs)
        model = FastLanguageModel.for_inference(model)
    except RuntimeError as exc:
        mode = "CUDA" if resolved_device == "cuda" else "CPU"
        raise Qwen3RuntimeError(f"Qwen3 {mode} model loading failed: {exc}") from exc
    runtime = {
        "resolved_device": resolved_device,
        "cuda": cuda_status(),
        "dependencies": dependency_versions(),
        "model_id": config.model_id,
        "revision": config.revision,
        "tokenizer_revision": config.tokenizer_revision,
        "quantization": "4bit-bnb" if kwargs["load_in_4bit"] else "none",
    }
    return Qwen3ModelBundle(model, tokenizer, _model_device(model, resolved_device), runtime)


__all__ = [
    "Qwen3ModelBundle",
    "Qwen3RuntimeConfig",
    "Qwen3RuntimeError",
    "cuda_status",
    "dependency_versions",
    "load_qwen3",
    "resolve_device",
]
