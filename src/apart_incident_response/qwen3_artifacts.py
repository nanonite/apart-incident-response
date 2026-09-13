"""Binary Qwen3 logits artifacts and replayable entropy derivations."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


ARTIFACT_SCHEMA = "qwen3-full-logits-v1"
ARTIFACT_SCHEMA_VERSION = 1
LOGITS_FILENAME = "logits.safetensors"
METADATA_FILENAME = "metadata.json"
GENERATED_FILENAME = "generated.json"
ENTROPY_FILENAME = "entropy.json"


class Qwen3ArtifactError(ValueError):
    """Raised when a logits artifact is incomplete, corrupt, or inconsistent."""


@dataclass(frozen=True)
class LoadedLogitsArtifact:
    metadata: Mapping[str, Any]
    logits: Any
    generated_token_ids: Any


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Qwen3ArtifactError(f"{name} must be an object")
    return value


def _require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise Qwen3ArtifactError(f"{name} must be a non-empty string")
    return value


def _require_sha256(value: Any, name: str) -> str:
    text = _require_text(value, name)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise Qwen3ArtifactError(f"{name} must be a lowercase SHA-256 digest")
    return text


def validate_metadata(metadata: Mapping[str, Any]) -> None:
    """Validate the structural contract independently of optional ML packages."""

    if metadata.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise Qwen3ArtifactError("unsupported logits artifact schema version")
    if metadata.get("artifact_schema") != ARTIFACT_SCHEMA:
        raise Qwen3ArtifactError("unexpected logits artifact schema")
    _require_text(metadata.get("run_id"), "run_id")
    model = _require_mapping(metadata.get("model"), "model")
    _require_text(model.get("id"), "model.id")
    _require_text(model.get("revision"), "model.revision")
    tokenizer = _require_mapping(metadata.get("tokenizer"), "tokenizer")
    _require_text(tokenizer.get("id"), "tokenizer.id")
    _require_text(tokenizer.get("revision"), "tokenizer.revision")
    prompt = _require_mapping(metadata.get("prompt"), "prompt")
    _require_sha256(prompt.get("sha256"), "prompt.sha256")
    generation = _require_mapping(metadata.get("generation"), "generation")
    for key in ("seed", "max_new_tokens", "temperature", "think", "use_cache"):
        if key not in generation:
            raise Qwen3ArtifactError(f"generation.{key} is required")
    tensor = _require_mapping(metadata.get("tensor"), "tensor")
    if tensor.get("name") != "logits" or tensor.get("layout") != "step_vocab_row_major":
        raise Qwen3ArtifactError("tensor metadata does not describe step-major logits")
    if tensor.get("pre_sampling") is not True:
        raise Qwen3ArtifactError("logits must be marked as pre-sampling")
    shape = tensor.get("shape")
    if not isinstance(shape, list) or len(shape) != 2 or any(not isinstance(item, int) or item <= 0 for item in shape):
        raise Qwen3ArtifactError("tensor.shape must contain two positive integers")
    generated_count = generation.get("generated_token_count")
    if generated_count is not None and generated_count != shape[0]:
        raise Qwen3ArtifactError("generation.generated_token_count does not match tensor.shape")
    paths = _require_mapping(metadata.get("paths"), "paths")
    for key in ("logits", "metadata", "generated", "entropy"):
        _require_text(paths.get(key), f"paths.{key}")
    checksums = _require_mapping(metadata.get("checksums"), "checksums")
    _require_sha256(checksums.get("logits_artifact_sha256"), "checksums.logits_artifact_sha256")
    _require_sha256(checksums.get("generated_token_ids_sha256"), "checksums.generated_token_ids_sha256")
    provenance = _require_mapping(metadata.get("provenance"), "provenance")
    if provenance.get("logits_source") != "transformers_generate_output_logits":
        raise Qwen3ArtifactError("logits provenance does not identify the raw generation output")


def entropy_from_rows(
    rows: Sequence[Sequence[float]], generated_token_ids: Sequence[int]
) -> dict[str, Any]:
    """Compute exact full-vocabulary entropy from small numeric rows in tests."""

    if len(rows) != len(generated_token_ids):
        raise Qwen3ArtifactError("logit rows and generated token IDs have different lengths")
    entropy_bits: list[float] = []
    sampled_logprobs: list[float] = []
    vocabulary_size = len(rows[0]) if rows else 0
    for row, token_id in zip(rows, generated_token_ids):
        if not row:
            raise Qwen3ArtifactError("a logit row cannot be empty")
        if len(row) != vocabulary_size:
            raise Qwen3ArtifactError("logit rows have different vocabulary widths")
        if not isinstance(token_id, int) or isinstance(token_id, bool) or not 0 <= token_id < len(row):
            raise Qwen3ArtifactError("generated token ID is outside the vocabulary row")
        if any(not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in row):
            raise Qwen3ArtifactError("logits contain NaN, infinity, or a non-numeric value")
        maximum = max(float(value) for value in row)
        normalizer = maximum + math.log(sum(math.exp(float(value) - maximum) for value in row))
        log_probs = [float(value) - normalizer for value in row]
        entropy = -sum(math.exp(log_prob) * log_prob for log_prob in log_probs) / math.log(2)
        entropy_bits.append(entropy)
        sampled_logprobs.append(log_probs[token_id])
    return _entropy_payload(entropy_bits, sampled_logprobs, vocabulary_size)


def _entropy_payload(entropy_bits: Sequence[float], sampled_logprobs: Sequence[float], vocabulary_size: int) -> dict[str, Any]:
    values = [float(value) for value in entropy_bits]
    logprobs = [float(value) for value in sampled_logprobs]
    return {
        "schema_version": 1,
        "entropy_definition": "full-vocabulary Shannon entropy of raw pre-sampling logits, in bits",
        "sampled_token_logprob_definition": "log_softmax(raw logits) at the generated token ID",
        "vocabulary_size": vocabulary_size,
        "token_count": len(values),
        "entropy_bits": values,
        "sampled_token_logprobs": logprobs,
        "mean_entropy_bits": (sum(values) / len(values)) if values else None,
        "mean_sampled_token_logprob": (sum(logprobs) / len(logprobs)) if logprobs else None,
    }


def derive_entropy_from_tensor(logits: Any, generated_token_ids: Any) -> dict[str, Any]:
    """Derive entropy and sampled-token logprobs from a torch tensor."""

    try:
        import torch
    except ImportError as exc:
        raise Qwen3ArtifactError("torch is required to replay a binary logits artifact") from exc
    if not isinstance(logits, torch.Tensor) or logits.ndim != 2:
        raise Qwen3ArtifactError("logits must be a two-dimensional torch tensor")
    if not isinstance(generated_token_ids, torch.Tensor) or generated_token_ids.ndim != 1:
        raise Qwen3ArtifactError("generated token IDs must be a one-dimensional torch tensor")
    if logits.shape[0] != generated_token_ids.shape[0]:
        raise Qwen3ArtifactError("logit rows and generated token IDs have different lengths")
    if not logits.is_floating_point() or not torch.isfinite(logits).all().item():
        raise Qwen3ArtifactError("logits must be finite floating-point values")
    token_ids = generated_token_ids.to(device=logits.device, dtype=torch.long)
    if token_ids.numel() and ((token_ids < 0).any().item() or (token_ids >= logits.shape[1]).any().item()):
        raise Qwen3ArtifactError("generated token ID is outside the vocabulary")
    log_probs = torch.log_softmax(logits.float(), dim=-1)
    probabilities = log_probs.exp()
    entropy_bits = -(probabilities * log_probs).sum(dim=-1) / math.log(2)
    selected = log_probs.gather(1, token_ids.reshape(-1, 1)).reshape(-1)
    return _entropy_payload(
        entropy_bits.detach().cpu().tolist(),
        selected.detach().cpu().tolist(),
        int(logits.shape[1]),
    )


def write_full_logits_artifact(
    output_root: Path | str,
    logits: Any,
    generated_token_ids: Any,
    metadata: Mapping[str, Any],
    *,
    generated_record: Mapping[str, Any],
) -> dict[str, Any]:
    """Write safetensors, metadata, generated text, and derived entropy."""

    try:
        import torch
        from safetensors.torch import save_file
    except ImportError as exc:
        raise Qwen3ArtifactError("torch and safetensors are required to write logits") from exc
    if not isinstance(logits, torch.Tensor) or not isinstance(generated_token_ids, torch.Tensor):
        raise Qwen3ArtifactError("logits and generated token IDs must be torch tensors")
    if logits.ndim != 2 or generated_token_ids.ndim != 1:
        raise Qwen3ArtifactError("logits must be [generated_tokens, vocabulary] and IDs must be [generated_tokens]")
    if logits.shape[0] < 1 or logits.shape[1] < 1:
        raise Qwen3ArtifactError("logits must contain at least one generated row and one vocabulary column")
    if logits.shape[0] != generated_token_ids.shape[0]:
        raise Qwen3ArtifactError("logit rows and generated token IDs have different lengths")
    if not logits.is_floating_point() or not torch.isfinite(logits).all().item():
        raise Qwen3ArtifactError("logits must be finite floating-point values")
    root = Path(output_root).expanduser().resolve()
    binary_dir = root / "full-logits"
    binary_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    logits_cpu = logits.detach().to(device="cpu").contiguous()
    token_ids_cpu = generated_token_ids.detach().to(device="cpu", dtype=torch.int64).contiguous()
    binary_path = binary_dir / LOGITS_FILENAME
    save_file(
        {"logits": logits_cpu, "generated_token_ids": token_ids_cpu},
        str(binary_path),
        metadata={"artifact_schema": ARTIFACT_SCHEMA, "schema_version": str(ARTIFACT_SCHEMA_VERSION)},
    )
    entropy = derive_entropy_from_tensor(logits_cpu, token_ids_cpu)
    normalized = dict(metadata)
    normalized.update({
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "artifact_schema": ARTIFACT_SCHEMA,
        "tensor": {
            **_require_mapping(normalized.get("tensor"), "tensor"),
            "name": "logits",
            "dtype": str(logits_cpu.dtype).removeprefix("torch."),
            "shape": [int(logits_cpu.shape[0]), int(logits_cpu.shape[1])],
            "layout": "step_vocab_row_major",
            "pre_sampling": True,
        },
        "paths": {
            "logits": "full-logits/logits.safetensors",
            "metadata": "full-logits/metadata.json",
            "generated": "full-logits/generated.json",
            "entropy": "full-logits/entropy.json",
        },
        "checksums": {
            "logits_artifact_sha256": _sha256_file(binary_path),
            "generated_token_ids_sha256": hashlib.sha256(token_ids_cpu.numpy().tobytes()).hexdigest(),
        },
        "derived_entropy": entropy,
    })
    validate_metadata(normalized)
    _write_json(binary_dir / GENERATED_FILENAME, dict(generated_record))
    _write_json(binary_dir / ENTROPY_FILENAME, entropy)
    _write_json(binary_dir / METADATA_FILENAME, normalized)
    return normalized


def load_full_logits_artifact(output_root: Path | str) -> LoadedLogitsArtifact:
    """Load and integrity-check a binary artifact for replay."""

    try:
        from safetensors.torch import load_file
    except ImportError as exc:
        raise Qwen3ArtifactError("safetensors is required to load logits") from exc
    root = Path(output_root).expanduser().resolve()
    binary_dir = root / "full-logits"
    metadata = json.loads((binary_dir / METADATA_FILENAME).read_text(encoding="utf-8"))
    validate_metadata(metadata)
    binary_path = binary_dir / LOGITS_FILENAME
    expected = metadata["checksums"]["logits_artifact_sha256"]
    actual = _sha256_file(binary_path)
    if actual != expected:
        raise Qwen3ArtifactError("logits artifact checksum does not match metadata")
    tensors = load_file(str(binary_path), device="cpu")
    if set(tensors) != {"logits", "generated_token_ids"}:
        raise Qwen3ArtifactError("logits artifact has an unexpected tensor set")
    logits = tensors["logits"]
    token_ids = tensors["generated_token_ids"]
    expected_shape = tuple(metadata["tensor"]["shape"])
    if tuple(logits.shape) != expected_shape or tuple(token_ids.shape) != (expected_shape[0],):
        raise Qwen3ArtifactError("binary tensor shape does not match metadata")
    expected_ids = metadata["checksums"]["generated_token_ids_sha256"]
    if hashlib.sha256(token_ids.numpy().tobytes()).hexdigest() != expected_ids:
        raise Qwen3ArtifactError("generated token ID checksum does not match metadata")
    return LoadedLogitsArtifact(metadata, logits, token_ids)


def replay_entropy(output_root: Path | str) -> dict[str, Any]:
    """Recompute entropy from raw tensors and compare it with the saved result."""

    artifact = load_full_logits_artifact(output_root)
    derived = derive_entropy_from_tensor(artifact.logits, artifact.generated_token_ids)
    stored = _require_mapping(artifact.metadata.get("derived_entropy"), "derived_entropy")
    if stored.get("token_count") != derived.get("token_count"):
        raise Qwen3ArtifactError("stored entropy token count does not replay")
    for key in ("entropy_bits", "sampled_token_logprobs"):
        stored_values = stored.get(key)
        derived_values = derived.get(key)
        if not isinstance(stored_values, list) or not isinstance(derived_values, list) or len(stored_values) != len(derived_values):
            raise Qwen3ArtifactError(f"stored entropy field {key} does not replay")
        if any(not math.isclose(float(left), float(right), rel_tol=1e-6, abs_tol=1e-6) for left, right in zip(stored_values, derived_values)):
            raise Qwen3ArtifactError(f"stored entropy field {key} does not replay")
    return derived


__all__ = [
    "ARTIFACT_SCHEMA",
    "ARTIFACT_SCHEMA_VERSION",
    "ENTROPY_FILENAME",
    "GENERATED_FILENAME",
    "LOGITS_FILENAME",
    "METADATA_FILENAME",
    "LoadedLogitsArtifact",
    "Qwen3ArtifactError",
    "derive_entropy_from_tensor",
    "entropy_from_rows",
    "load_full_logits_artifact",
    "replay_entropy",
    "validate_metadata",
    "write_full_logits_artifact",
]
