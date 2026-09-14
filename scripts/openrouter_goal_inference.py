#!/usr/bin/env python3
"""Run one prompt-only OpenRouter chat completion and save token probabilities.

The adapter deliberately makes one non-streaming request. It requires the
OpenRouter logprob fields and stores the provider response only after applying
credential redaction. ``OPENROUTER_API_KEY`` is read from the controller
environment and is never included in a request artifact or failure artifact.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
import sys
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT / "src"))

from apart_incident_response.probability_artifacts import (
    ProbabilityArtifactError,
    build_probability_artifact,
    normalize_token_probability,
    unavailable_probability_artifact,
)
from apart_incident_response.run_paths import copy_file_if_absent, create_run_directory


DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"
DEFAULT_TOP_LOGPROBS = 5
DEFAULT_MAX_TOKENS = 512
OPENROUTER_ROUTE = "openrouter.ai:443"


def _read_prompt(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if "\x00" in text:
        raise ValueError(f"prompt file contains a NUL byte: {path}")
    return text


def _api_model(model: str) -> str:
    if model.startswith("openrouter/"):
        model = model.removeprefix("openrouter/")
    if not model or model.count("/") != 1 or model.startswith("/") or model.endswith("/"):
        raise ValueError(
            "OpenRouter model must be an author/model slug, for example openai/gpt-4o-mini"
        )
    return model


def _provenance(model: str, *, top_logprobs: int, max_tokens: int, temperature: float, seed: int | None) -> dict[str, object]:
    return {
        "provider": "openrouter",
        "model": _api_model(model),
        "parameters": {
            "logprobs": True,
            "top_logprobs": top_logprobs,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "seed": seed,
            "stream": False,
            "route": OPENROUTER_ROUTE,
        },
    }


def _request_payload(
    model: str,
    prompt: str,
    *,
    top_logprobs: int,
    max_tokens: int,
    temperature: float,
    seed: int | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": _api_model(model),
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "logprobs": True,
        "top_logprobs": top_logprobs,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "provider": {
            "order": ["openai"],
            "allow_fallbacks": False,
            "require_parameters": True,
        },
    }
    if seed is not None:
        payload["seed"] = seed
    return payload


def _post_chat_completion(
    endpoint: str,
    api_key: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=1800) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"OpenRouter HTTP {exc.code}: {body}") from exc
    return _json_object(body, "OpenRouter response")


def _json_object(body: str, label: str) -> dict[str, object]:
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _redact(value: Any, secret: str) -> Any:
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]") if secret else value
    if isinstance(value, Mapping):
        return {str(key): _redact(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    return value


def _response_probability_records(response: Mapping[str, object]) -> tuple[list[dict[str, object]], Mapping[str, object]]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProbabilityArtifactError("OpenRouter response omitted choices")
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise ProbabilityArtifactError("OpenRouter response choice must be an object")
    logprobs = choice.get("logprobs")
    if not isinstance(logprobs, Mapping):
        raise ProbabilityArtifactError("OpenRouter response omitted choices[0].logprobs")
    content = logprobs.get("content")
    if not isinstance(content, list) or not content:
        raise ProbabilityArtifactError(
            "OpenRouter response omitted a non-empty choices[0].logprobs.content array"
        )
    records: list[dict[str, object]] = []
    for index, record in enumerate(content):
        if not isinstance(record, Mapping):
            raise ProbabilityArtifactError(f"OpenRouter token record {index} must be an object")
        # Normalize here to validate every field before retaining the provider
        # record. The shared builder consumes the provider-shaped record so it
        # can preserve the deduplicated alternatives in the artifact.
        normalize_token_probability(record)
        records.append(dict(record))
    return records, choice


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _mirror_file(path: Path, legacy_root: Path) -> None:
    """Keep a single requested output leaf readable for old callers."""

    destination = legacy_root / path.name
    if destination == path:
        return
    try:
        copy_file_if_absent(path, destination)
    except OSError:
        return


def _write_failure(
    output: Path,
    *,
    run_id: str,
    run_uuid: str,
    model: str,
    endpoint: str,
    parameters: Mapping[str, object],
    error: Exception,
    secret: str,
    legacy_root: Path | None = None,
) -> None:
    failure_model = model.removeprefix("openrouter/") or "unknown"
    provenance = {
        "provider": "openrouter",
        "model": failure_model,
        "parameters": dict(parameters),
    }
    artifact = {
        "schema_version": 1,
        "run_class": "goal_inference",
        "provider": "openrouter",
        "status": "failed",
        "run_id": run_id,
        "run_uuid": run_uuid,
        "model": model,
        "route": {
            "endpoint": endpoint,
            "host": urllib.parse.urlparse(endpoint).hostname,
            "openrouter_route": OPENROUTER_ROUTE,
        },
        "parameters": dict(parameters),
        "error_type": type(error).__name__,
        "error": _redact(str(error), secret),
        "probability_artifact": unavailable_probability_artifact(
            provenance,
            reason=_redact(str(error), secret),
        ),
    }
    try:
        _write_json(output / "failure.json", artifact)
        if legacy_root is not None:
            _mirror_file(output / "failure.json", legacy_root)
    except OSError:
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="OpenRouter chat-completions endpoint")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenRouter author/model slug")
    parser.add_argument("--prompt", help="Inline prompt text (mutually exclusive with --prompt-file)")
    parser.add_argument("--prompt-file", type=Path, help="Path to a UTF-8 prompt file")
    parser.add_argument("--top-logprobs", type=int, default=DEFAULT_TOP_LOGPROBS)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("runs/openrouter/logprobs"),
        help="Base directory; the resolved provider/model/UUID path is printed",
    )
    parser.add_argument("--run-id", default=None, help="Stable run identifier")
    args = parser.parse_args(argv)

    if args.prompt and args.prompt_file:
        parser.error("--prompt and --prompt-file are mutually exclusive")
    if not args.prompt and not args.prompt_file:
        parser.error("one of --prompt or --prompt-file is required")

    requested_output = args.output.expanduser().resolve()
    invocation = create_run_directory(
        requested_output,
        args.model,
        provider="openrouter",
        run_id=args.run_id,
        metadata={"mode": "logprobs", "run_class": "goal_inference"},
    )
    output = invocation.path
    run_id = invocation.run_id
    parameters = {
        "logprobs": True,
        "top_logprobs": args.top_logprobs,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "seed": args.seed,
        "stream": False,
        "provider": {
            "order": ["openai"],
            "allow_fallbacks": False,
            "require_parameters": True,
        },
    }
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    try:
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is required")
        if args.top_logprobs < 0 or args.top_logprobs > 20:
            raise ValueError("top-logprobs must be between 0 and 20")
        if args.max_tokens < 1:
            raise ValueError("max-tokens must be positive")
        if not math.isfinite(args.temperature) or args.temperature < 0:
            raise ValueError("temperature must be a finite non-negative number")
        prompt = args.prompt if args.prompt is not None else _read_prompt(args.prompt_file)
        payload = _request_payload(
            args.model,
            prompt,
            top_logprobs=args.top_logprobs,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            seed=args.seed,
        )
        response = _post_chat_completion(args.endpoint, api_key, payload)
        records, choice = _response_probability_records(response)
        probability_artifact = build_probability_artifact(
            records,
            provenance=_provenance(
                args.model,
                top_logprobs=args.top_logprobs,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                seed=args.seed,
            ),
        )
        message = choice.get("message")
        text = message.get("content", "") if isinstance(message, Mapping) else ""
        artifact = {
            "schema_version": 1,
            "run_class": "goal_inference",
            "experimental_data": True,
            "status": "complete",
            "run_id": run_id,
            "run_uuid": invocation.run_uuid,
            "provider": "openrouter",
            "model_id": args.model,
            "artifact_root": str(output),
            "model": args.model,
            "prompt": {
                "text": _redact(prompt, api_key),
                "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            },
            "parameters": parameters,
            "response": {
                "id": response.get("id"),
                "model": response.get("model"),
                "provider": response.get("provider"),
                "finish_reason": choice.get("finish_reason"),
                "text": _redact(text, api_key),
            },
            "usage": _redact(response.get("usage"), api_key),
            "route": {
                "endpoint": args.endpoint,
                "host": urllib.parse.urlparse(args.endpoint).hostname,
                "openrouter_route": OPENROUTER_ROUTE,
                "provider": response.get("provider", "openai"),
                "fallbacks_allowed": False,
                "parameters_required": True,
            },
            "raw_response": _redact(response, api_key),
            "probability_artifact": probability_artifact,
        }
        _write_json(output / "goal_inference.json", artifact)
        _mirror_file(output / "goal_inference.json", requested_output)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, urllib.error.URLError, ProbabilityArtifactError, RuntimeError) as exc:
        _write_failure(
            output,
            run_id=run_id,
            run_uuid=invocation.run_uuid,
            model=args.model,
            endpoint=args.endpoint,
            parameters=parameters,
            error=exc,
            secret=api_key,
            legacy_root=requested_output,
        )
        print(json.dumps({
            "status": "failed",
            "run_id": run_id,
            "run_uuid": invocation.run_uuid,
            "artifact_root": str(output),
            "error": _redact(str(exc), api_key),
        }, indent=2))
        return 2
    print(json.dumps({
        "artifact": str(output / "goal_inference.json"),
        "artifact_root": str(output),
        "run_id": run_id,
        "run_uuid": invocation.run_uuid,
        "response_id": response.get("id"),
        "model": response.get("model", args.model),
        "route": artifact["route"],
        "token_count": probability_artifact["coverage"]["token_count"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
