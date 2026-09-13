#!/usr/bin/env python3
"""One-shot ``/goal`` inference against a local Ollama model, with logprobs.

This is the entropy data path for the accidental-coordination experiment. It
sends a single prompt to an Ollama-backed model (no user-to-agent follow-up, no
tool loop), requests token-level ``logprobs`` with a ``top_logprobs`` view, and
writes one self-contained JSON artifact per response. The artifact is the raw
source for the response-state entropy metrics described in
``entropy-metrics-mvp.md``.

Only the Python standard library is used, so the harness runs anywhere a
reachable Ollama server exists (host or the ``ollama`` compose service).

Typical usage::

    python scripts/ollama_goal_inference.py \
        --prompt-file prompts/task-1.txt \
        --top-logprobs 5 \
        --output artifacts/goal/qwen3-8b/seed-1

The harness is intentionally prompt-only and never exposes tool, network, or
filesystem capabilities to the model. It is a deterministic single completion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:8b"
DEFAULT_CHECKPOINT_ID = "Qwen/Qwen3-8B"
DEFAULT_CHECKPOINT_REVISION = "47719a242beab8f9aecc40ce3928b034dd5dd559"


def _read_prompt(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if "\x00" in text:
        raise ValueError(f"prompt file contains a NUL byte: {path}")
    return text


def _write_failure(output: Path, *, run_id: str, error: Exception) -> None:
    try:
        output.mkdir(parents=True, exist_ok=True)
        path = output / "failure.json"
        path.write_text(json.dumps({
            "schema_version": 1,
            "run_class": "goal_inference",
            "status": "failed",
            "run_id": run_id,
            "mode": "logprobs",
            "error_type": type(error).__name__,
            "error": str(error),
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
    except OSError:
        return


def _post_generate(
    host: str,
    model: str,
    prompt: str,
    *,
    top_logprobs: int,
    num_predict: int,
    temperature: float,
    think: bool,
    seed: int | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "logprobs": True,
        "top_logprobs": top_logprobs,
        "think": think,
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
        },
    }
    if seed is not None:
        payload["options"]["seed"] = seed

    request = urllib.request.Request(
        f"{host.rstrip('/')}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=1800) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _per_token_entropy(logprob: float, top_logprobs: list[dict[str, object]]) -> dict[str, float]:
    """Compute a top-K entropy lower bound plus the sampled-token surprise.

    Ollama reports log probabilities, not raw logits, and only exposes the top
    ``top_logprobs`` alternatives. True vocabulary entropy is unavailable from
    this surface, so we report the top-K entropy (a lower bound) alongside the
    log probability of the token that was actually sampled.
    """
    tokens = [{"logprob": logprob}] + [
        {"logprob": float(item["logprob"])} for item in top_logprobs
    ]
    max_logprob = max(t["logprob"] for t in tokens)
    probs = [math.exp(t["logprob"] - max_logprob) for t in tokens]
    total = sum(probs)
    normalized = [p / total for p in probs]
    entropy = -sum(p * math.log2(p) for p in normalized if p > 0)
    return {
        "sampled_logprob": float(logprob),
        "sampled_prob": math.exp(float(logprob)),
        "top_k_entropy_bits": round(entropy, 6),
    }


def _summarize(logprobs: list[dict[str, object]]) -> dict[str, float]:
    if not logprobs:
        return {"token_count": 0}
    surprise_bits = 0.0
    top_k_entropy_bits = 0.0
    for entry in logprobs:
        lp = float(entry["logprob"])
        surprise_bits += -lp / math.log(2)
        top_k_entropy_bits += float(entry["_entropy"]["top_k_entropy_bits"])
    return {
        "token_count": len(logprobs),
        "total_surprise_bits": round(surprise_bits, 6),
        "mean_surprise_bits": round(surprise_bits / len(logprobs), 6),
        "total_top_k_entropy_bits": round(top_k_entropy_bits, 6),
        "mean_top_k_entropy_bits": round(top_k_entropy_bits / len(logprobs), 6),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST, help="Ollama base URL")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model name")
    parser.add_argument("--checkpoint-id", default=DEFAULT_CHECKPOINT_ID, help="Pinned logical checkpoint ID")
    parser.add_argument("--checkpoint-revision", default=DEFAULT_CHECKPOINT_REVISION, help="Pinned checkpoint revision")
    parser.add_argument(
        "--prompt",
        help="Inline prompt text (mutually exclusive with --prompt-file)",
    )
    parser.add_argument("--prompt-file", type=Path, help="Path to a UTF-8 prompt file")
    parser.add_argument("--top-logprobs", type=int, default=5, help="Top-K alternatives per token")
    parser.add_argument("--num-predict", type=int, default=512, help="Max generated tokens")
    parser.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature")
    parser.add_argument("--think", action="store_true", help="Allow Qwen thinking mode")
    parser.add_argument("--seed", type=int, default=None, help="Deterministic sampling seed")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/goal/qwen3-8b"),
        help="Directory to write the JSON artifact into",
    )
    parser.add_argument("--run-id", default=None, help="Stable run identifier")
    args = parser.parse_args(argv)

    if args.prompt and args.prompt_file:
        parser.error("--prompt and --prompt-file are mutually exclusive")
    if not args.prompt and not args.prompt_file:
        parser.error("one of --prompt or --prompt-file is required")

    output = args.output.expanduser().resolve()
    run_id = args.run_id or datetime.now(timezone.utc).isoformat()
    try:
        if args.top_logprobs < 0 or args.num_predict < 1:
            raise ValueError("top-logprobs must be non-negative and num-predict must be positive")
        prompt = args.prompt if args.prompt is not None else _read_prompt(args.prompt_file)
        response = _post_generate(
            args.host,
            args.model,
            prompt,
            top_logprobs=args.top_logprobs,
            num_predict=args.num_predict,
            temperature=args.temperature,
            think=args.think,
            seed=args.seed,
        )

        raw_logprobs = response.get("logprobs") or []
        enriched: list[dict[str, object]] = []
        for entry in raw_logprobs:
            item = dict(entry)
            item["_entropy"] = _per_token_entropy(
                float(item["logprob"]), item.get("top_logprobs") or []
            )
            enriched.append(item)

        artifact = {
            "schema_version": 1,
            "run_class": "goal_inference",
            "experimental_data": True,
            "run_id": run_id,
            "checkpoint": {
                "model_id": args.checkpoint_id,
                "revision": args.checkpoint_revision,
                "ollama_model": args.model,
            },
            "model": args.model,
            "prompt": {"text": prompt, "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()},
            "parameters": {
                "top_logprobs": args.top_logprobs,
                "num_predict": args.num_predict,
                "temperature": args.temperature,
                "think": args.think,
                "seed": args.seed,
            },
            "response": response.get("response", ""),
            "thinking": response.get("thinking", ""),
            "done_reason": response.get("done_reason"),
            "prompt_eval_count": response.get("prompt_eval_count"),
            "eval_count": response.get("eval_count"),
            "total_duration": response.get("total_duration"),
            "logprobs": enriched,
            "summary": _summarize(enriched),
        }

        output.mkdir(parents=True, exist_ok=True)
        out_path = output / "goal_inference.json"
        out_path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        out_path.chmod(0o600)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, urllib.error.URLError) as exc:
        _write_failure(output, run_id=run_id, error=exc)
        print(json.dumps({"status": "failed", "run_id": run_id, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps({"artifact": str(out_path), "summary": artifact["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
