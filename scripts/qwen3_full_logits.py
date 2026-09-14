#!/usr/bin/env python3
"""Run one Qwen3-8B completion and preserve raw full-vocabulary logits."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import sys
import time
from typing import Any, Mapping


SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT / "src"))

from apart_incident_response.qwen3_artifacts import (  # noqa: E402
    Qwen3ArtifactError,
    write_full_logits_artifact,
)
from apart_incident_response.qwen3_runtime import (  # noqa: E402
    Qwen3RuntimeConfig,
    Qwen3RuntimeError,
    dependency_versions,
    load_qwen3,
)
from apart_incident_response.run_paths import copy_file_if_absent, create_run_directory  # noqa: E402


DEFAULT_CONFIG = SOURCE_ROOT / "config" / "qwen3-8b.json"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _mirror_tree(source: Path, legacy_root: Path) -> None:
    """Keep the old direct artifact root usable while new callers use UUID paths."""

    destination = legacy_root / source.name
    if destination == source:
        return
    try:
        destination.mkdir(mode=0o700, parents=True, exist_ok=True)
        for path in source.rglob("*"):
            target = destination / path.relative_to(source)
            if path.is_dir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
            elif path.is_file():
                copy_file_if_absent(path, target)
    except OSError:
        return


def _mirror_file(path: Path, legacy_root: Path) -> None:
    try:
        copy_file_if_absent(path, legacy_root / path.name)
    except OSError:
        return


def _write_failure(
    output: Path,
    *,
    run_id: str,
    run_uuid: str,
    model: str,
    stage: str,
    error: Exception,
    legacy_root: Path | None = None,
) -> None:
    try:
        output.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "run_class": "goal_inference",
            "status": "failed",
            "run_id": run_id,
            "run_uuid": run_uuid,
            "provider": "qwen3",
            "model_id": model,
            "stage": stage,
            "error_type": type(error).__name__,
            "error": str(error),
            "dependencies": dependency_versions(),
        }
        path = output / "failure.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        if legacy_root is not None:
            _mirror_file(path, legacy_root)
    except OSError:
        return


def _load_config(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Qwen3RuntimeError(f"Qwen3 config could not be read: {path}") from exc
    if not isinstance(value, Mapping):
        raise Qwen3RuntimeError("Qwen3 config must be an object")
    for key in ("model_id", "revision", "tokenizer_revision"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise Qwen3RuntimeError(f"Qwen3 config requires {key}")
    return value


def _read_prompt(inline: str | None, path: Path | None) -> str:
    if inline is not None and path is not None:
        raise Qwen3RuntimeError("--prompt and --prompt-file are mutually exclusive")
    if inline is None and path is None:
        raise Qwen3RuntimeError("one of --prompt or --prompt-file is required")
    prompt = inline if inline is not None else path.read_text(encoding="utf-8")
    if "\x00" in prompt:
        raise Qwen3RuntimeError("prompt contains a NUL byte")
    return prompt


def _seed_torch(seed: int) -> Any:
    try:
        import torch
    except ImportError as exc:
        raise Qwen3RuntimeError("torch is required for full-logits inference") from exc
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    return torch


def _render_prompt(tokenizer: Any, prompt: str, think: bool) -> str:
    if not think or not hasattr(tokenizer, "apply_chat_template"):
        return prompt
    messages = [{"role": "user", "content": prompt}]
    try:
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=True,
        )
    except TypeError as exc:
        raise Qwen3RuntimeError("the pinned Qwen3 tokenizer lacks enable_thinking chat-template support") from exc


def _synchronize(torch: Any, device: Any) -> None:
    if getattr(device, "type", None) == "cuda":
        torch.cuda.synchronize(device)


def _memory_snapshot(torch: Any, device: Any) -> dict[str, int] | None:
    if getattr(device, "type", None) != "cuda":
        return None
    return {
        "allocated_bytes": int(torch.cuda.memory_allocated(device)),
        "reserved_bytes": int(torch.cuda.memory_reserved(device)),
        "max_allocated_bytes": int(torch.cuda.max_memory_allocated(device)),
    }


def _generation_parameters(args: argparse.Namespace, tokenizer: Any) -> dict[str, Any]:
    if args.max_new_tokens < 1:
        raise Qwen3RuntimeError("--max-new-tokens must be positive")
    if args.temperature < 0:
        raise Qwen3RuntimeError("--temperature cannot be negative")
    if not 0 < args.top_p <= 1:
        raise Qwen3RuntimeError("--top-p must be in (0, 1]")
    if args.top_k < 0:
        raise Qwen3RuntimeError("--top-k cannot be negative")
    eos = getattr(tokenizer, "eos_token_id", None)
    pad = getattr(tokenizer, "pad_token_id", None)
    return {
        "seed": args.seed,
        "max_new_tokens": args.max_new_tokens,
        "temperature": args.temperature,
        "top_p": args.top_p,
        "top_k": args.top_k,
        "do_sample": args.temperature > 0,
        "think": args.think,
        "use_cache": True,
        "eos_token_id": eos,
        "pad_token_id": pad,
    }


def _run_generation(args: argparse.Namespace, config: Mapping[str, Any], prompt: str) -> dict[str, Any]:
    torch = _seed_torch(args.seed)
    model_config = Qwen3RuntimeConfig(
        model_id=args.model or str(config["model_id"]),
        revision=args.revision or str(config["revision"]),
        tokenizer_revision=str(config["tokenizer_revision"]),
        max_seq_length=args.max_seq_length,
        device=args.device,
        load_in_4bit=args.device != "cpu",
        local_files_only=args.local_files_only,
    )
    bundle = load_qwen3(model_config, cache_dir=args.cache_dir)
    rendered_prompt = _render_prompt(bundle.tokenizer, prompt, args.think)
    inputs = bundle.tokenizer(rendered_prompt, return_tensors="pt")
    inputs = {key: value.to(bundle.device) for key, value in inputs.items()}
    parameters = _generation_parameters(args, bundle.tokenizer)
    generation_kwargs: dict[str, Any] = {
        **inputs,
        "max_new_tokens": args.max_new_tokens,
        "do_sample": parameters["do_sample"],
        "use_cache": True,
        "return_dict_in_generate": True,
        "output_logits": True,
        "output_scores": False,
    }
    if parameters["eos_token_id"] is not None:
        generation_kwargs["eos_token_id"] = parameters["eos_token_id"]
    if parameters["pad_token_id"] is not None:
        generation_kwargs["pad_token_id"] = parameters["pad_token_id"]
    if parameters["do_sample"]:
        generation_kwargs.update({"temperature": args.temperature, "top_p": args.top_p, "top_k": args.top_k})
    _synchronize(torch, bundle.device)
    started = time.monotonic()
    memory_before = _memory_snapshot(torch, bundle.device)
    with torch.inference_mode():
        generated = bundle.model.generate(**generation_kwargs)
    _synchronize(torch, bundle.device)
    duration_seconds = round(time.monotonic() - started, 6)
    memory_after = _memory_snapshot(torch, bundle.device)
    raw_logits = getattr(generated, "logits", None)
    if not raw_logits:
        raise Qwen3ArtifactError("Transformers did not return unprocessed logits; output_logits is unavailable")
    sequence = generated.sequences[0]
    input_length = int(inputs["input_ids"].shape[-1])
    generated_ids = sequence[input_length:input_length + len(raw_logits)].to(dtype=torch.int64)
    logits = torch.stack([step[0] if step.ndim == 2 else step for step in raw_logits], dim=0)
    if logits.shape[0] != generated_ids.shape[0]:
        raise Qwen3ArtifactError("generated token IDs are not aligned with returned logits")
    completion_text = bundle.tokenizer.decode(generated_ids.tolist(), skip_special_tokens=False)
    thinking = ""
    response = completion_text
    if "</think>" in completion_text:
        thinking, response = completion_text.split("</think>", 1)
        thinking = thinking.removeprefix("<think>").strip()
        response = response.strip()
    generation = {
        **parameters,
        "input_token_count": input_length,
        "generated_token_count": int(generated_ids.shape[0]),
        "duration_seconds": duration_seconds,
    }
    metadata = {
        "run_id": args.run_id,
        "run_uuid": args.run_uuid,
        "provider": "qwen3",
        "model_id": model_config.model_id,
        "artifact_root": str(args.output),
        "model": {
            "id": model_config.model_id,
            "revision": model_config.revision,
            "quantization": bundle.runtime["quantization"],
        },
        "tokenizer": {
            "id": model_config.model_id,
            "revision": model_config.tokenizer_revision,
            "vocab_size": int(getattr(bundle.tokenizer, "vocab_size", logits.shape[-1])),
            "eos_token_id": parameters["eos_token_id"],
            "pad_token_id": parameters["pad_token_id"],
        },
        "prompt": {
            "text": prompt,
            "sha256": _sha256_text(prompt),
            "rendered_text_sha256": _sha256_text(rendered_prompt),
            "input_token_ids_sha256": hashlib.sha256(inputs["input_ids"].detach().cpu().numpy().tobytes()).hexdigest(),
        },
        "generation": generation,
        "tensor": {
            "device": str(bundle.device),
            "source_dtype": str(logits.dtype).removeprefix("torch."),
        },
        "runtime": bundle.runtime,
        "resources": {"memory_before": memory_before, "memory_after": memory_after},
        "provenance": {
            "logits_source": "transformers_generate_output_logits",
            "pre_sampling": True,
            "sampling_processors": "raw logits are captured before generation processors; output_scores is disabled",
            "kv_cache": True,
        },
    }
    generated_record = {
        "schema_version": 1,
        "run_id": args.run_id,
        "run_uuid": args.run_uuid,
        "prompt": prompt,
        "rendered_prompt": rendered_prompt,
        "generated_token_ids": generated_ids.detach().cpu().tolist(),
        "completion_text": completion_text,
        "thinking": thinking,
        "response": response,
        "generation": generation,
    }
    normalized = write_full_logits_artifact(
        args.output,
        logits,
        generated_ids,
        metadata,
        generated_record=generated_record,
    )
    return {
        "schema_version": 1,
        "run_class": "goal_inference",
        "status": "completed",
        "run_id": args.run_id,
        "run_uuid": args.run_uuid,
        "provider": "qwen3",
        "model_id": model_config.model_id,
        "response": response,
        "thinking": thinking,
        "generated_token_count": int(generated_ids.shape[0]),
        "logits_shape": normalized["tensor"]["shape"],
        "artifact_root": str(args.output),
        "entropy": normalized["derived_entropy"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--revision")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output", type=Path, default=Path("runs/qwen3-8b/full-logits"))
    parser.add_argument("--run-id", default="seed-1")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--max-new-tokens", type=int, default=128)
    parser.add_argument("--max-seq-length", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=0.8)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--think", action="store_true")
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--local-files-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    requested_output = args.output.expanduser().resolve()
    args.config = args.config.expanduser().resolve()
    args.cache_dir = args.cache_dir.expanduser().resolve() if args.cache_dir else None
    run_id = args.run_id
    path_model = args.model or "Qwen/Qwen3-8B"
    try:
        preview_config = _load_config(args.config)
        path_model = args.model or str(preview_config["model_id"])
    except (Qwen3RuntimeError, OSError, ValueError):
        # Preserve a failure artifact even when the configuration itself is
        # unreadable; the default model keeps the path contract deterministic.
        pass
    invocation = create_run_directory(
        requested_output,
        path_model,
        provider="qwen3",
        run_id=run_id,
        metadata={"mode": "full-logits", "run_class": "goal_inference"},
    )
    args.output = invocation.path
    args.run_uuid = invocation.run_uuid
    try:
        prompt = _read_prompt(args.prompt, args.prompt_file)
        config = _load_config(args.config)
        result = _run_generation(args, config, prompt)
    except (Qwen3ArtifactError, Qwen3RuntimeError, OSError, ValueError, RuntimeError, ImportError, MemoryError) as exc:
        _write_failure(
            args.output,
            run_id=run_id,
            run_uuid=invocation.run_uuid,
            model=path_model,
            stage="full_logits_inference",
            error=exc,
            legacy_root=requested_output,
        )
        print(json.dumps({"status": "failed", "run_id": run_id, "run_uuid": invocation.run_uuid, "artifact_root": str(args.output), "error": str(exc)}, indent=2))
        return 2
    _mirror_tree(args.output / "full-logits", requested_output)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
