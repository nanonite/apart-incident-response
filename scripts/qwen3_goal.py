#!/usr/bin/env python3
"""Dispatch the compatible Ollama, OpenRouter, and full-logits goal modes."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT / "src"))
sys.path.insert(0, str(SOURCE_ROOT / "scripts"))

from ollama_goal_inference import main as ollama_main  # noqa: E402
from openrouter_goal_inference import main as openrouter_main  # noqa: E402
from qwen3_full_logits import main as full_logits_main  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("logprobs", "openrouter", "full-logits"), required=True)
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--host", default="http://localhost:11434")
    parser.add_argument("--endpoint", default="https://openrouter.ai/api/v1/chat/completions")
    parser.add_argument("--checkpoint-id", default="Qwen/Qwen3-8B")
    parser.add_argument("--checkpoint-revision", default="47719a242beab8f9aecc40ce3928b034dd5dd559")
    parser.add_argument("--revision")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--think", action="store_true")
    parser.add_argument("--top-logprobs", type=int, default=5)
    parser.add_argument("--num-predict", type=int, default=128)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--max-new-tokens", type=int, default=128)
    parser.add_argument("--max-seq-length", type=int, default=4096)
    parser.add_argument("--top-p", type=float, default=0.8)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--local-files-only", action="store_true")
    return parser


def _add(value: list[str], flag: str, item: object | None) -> None:
    if item is not None:
        value.extend((flag, str(item)))


def _forward_args(args: argparse.Namespace) -> list[str]:
    forwarded: list[str] = []
    _add(forwarded, "--prompt", args.prompt)
    _add(forwarded, "--prompt-file", args.prompt_file)
    _add(forwarded, "--model", args.model)
    _add(forwarded, "--output", args.output)
    _add(forwarded, "--run-id", args.run_id or f"seed-{args.seed}")
    forwarded.extend(("--seed", str(args.seed), "--temperature", str(args.temperature)))
    if args.think:
        forwarded.append("--think")
    if args.mode == "logprobs":
        forwarded.extend((
            "--host", args.host,
            "--checkpoint-id", args.checkpoint_id,
            "--checkpoint-revision", args.checkpoint_revision,
            "--top-logprobs", str(args.top_logprobs),
            "--num-predict", str(args.num_predict),
        ))
    elif args.mode == "openrouter":
        forwarded.extend((
            "--endpoint", args.endpoint,
            "--top-logprobs", str(args.top_logprobs),
            "--max-tokens", str(args.max_tokens),
        ))
    else:
        _add(forwarded, "--revision", args.revision)
        forwarded.extend(("--max-new-tokens", str(args.max_new_tokens), "--max-seq-length", str(args.max_seq_length)))
        forwarded.extend(("--top-p", str(args.top_p), "--top-k", str(args.top_k), "--device", args.device))
        _add(forwarded, "--cache-dir", args.cache_dir)
        if args.local_files_only:
            forwarded.append("--local-files-only")
    return forwarded


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.output is None:
        if args.mode == "openrouter":
            args.output = Path("runs/openrouter/logprobs")
        else:
            directory = "logprobs" if args.mode == "logprobs" else "full-logits"
            args.output = Path("runs/qwen3-8b") / directory
    forwarded = _forward_args(args)
    if args.mode == "logprobs":
        return ollama_main(forwarded)
    if args.mode == "openrouter":
        if args.think:
            parser.error("--think is only supported by the Ollama mode")
        return openrouter_main(forwarded)
    return full_logits_main(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
