# Isolated Qwen3-8B runtime

The local full-vocabulary path is deliberately separate from the lightweight
remote-agent image. `Dockerfile.qwen3` pins Python ML dependencies in
`requirements-qwen3.txt`, and `compose.qwen3.yaml` mounts model weights from a
host cache rather than baking them into the image. The checkpoint and library
versions are recorded in [`config/qwen3-8b.json`](../config/qwen3-8b.json).

## GPU runtime

The supported path is an NVIDIA CUDA host with the NVIDIA Container Toolkit:

```console
docker compose -f compose.qwen3.yaml build qwen3
docker compose -f compose.qwen3.yaml run --rm qwen3 \
    --mode full-logits \
    --prompt "The capital of France is" \
    --seed 1 \
    --output runs/qwen3-8b/full-logits/seed-1
```

The first run downloads the pinned checkpoint into `./qwen3-cache` (or the
directory selected by `QWEN3_CACHE_DIR`). The cache is not part of the image or
the repository. The full-logits mode uses Unsloth's `FastLanguageModel` loader
with 4-bit bitsandbytes weights on CUDA, then delegates generation to the
Transformers-compatible model with KV caching and unprocessed logits output.

## CPU behavior

The script checks CUDA before model loading. `--device auto` fails clearly when
CUDA is unavailable, because silently loading an 8B model on CPU would make a
timing or resource comparison invalid. An explicit `--device cpu` selects
non-quantized Transformers/Unsloth loading for functional CPU validation; it
requires substantial RAM and can be impractically slow. If the pinned packages,
checkpoint, or CPU memory are unavailable, the run writes a structured
`failure.json` when an output directory is available and exits non-zero.

The compose service is GPU-only by design. Use the Python entrypoint directly
inside a compatible environment for the explicit CPU path.
