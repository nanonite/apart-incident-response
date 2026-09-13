# Local Qwen3-8B logprobs data path

The experiment's remote model (`openai-codex/gpt-5.6-luna`) does not expose
token probabilities, so it cannot feed the response-state entropy metrics in
[`entropy-metrics-mvp.md`](entropy-metrics-mvp.md). This document records the
one-shot `/goal` data path that substitutes a locally served Qwen3-8B (4-bit)
whose token-level `logprobs` are captured per response.

## Model and server

- **Model:** `qwen3:8b` (Qwen3-8B instruct, GGUF `Q4_K_M` 4-bit, 40k context).
- **Server:** Ollama `0.34.0`, which exposes `logprobs` and `top_logprobs` on
  `/api/generate` (the native endpoint; the OpenAI-compatible
  `/v1/chat/completions` layer is not required for this path).
- **Compose:** the `ollama` service in `compose.yaml` runs the server with GPU
  access and a bind-mounted model store at `./ollama-models` (git-ignored).

```console
just ollama-up      # start the Ollama server (GPU if available)
just ollama-pull    # pull qwen3:8b (one-time, ~5.2 GB)
```

The server listens on `http://localhost:11434`.

## One-shot `/goal` inference

The `scripts/ollama_goal_inference.py` harness sends a single prompt (no
user-to-agent follow-up, no tool loop), requests token logprobs with a
`top_logprobs` view, and writes one JSON artifact per response:

```console
just goal           # quick smoke: "The capital of France is"
```

For experiment prompts, pass an explicit prompt file:

```console
python3 scripts/ollama_goal_inference.py \
    --model qwen3:8b \
    --prompt-file prompts/task-1.txt \
    --top-logprobs 5 \
    --temperature 0 \
    --num-predict 512 \
    --output artifacts/goal/qwen3-8b/seed-1
```

`--think` is off by default so the model emits the answer directly rather than
consuming the budget on `<think>` reasoning tokens. Set `--seed` for
deterministic sampling.

## Artifact shape

Each `goal_inference.json` contains the prompt, the full response string, and a
per-token `logprobs` array. Every entry carries:

```jsonc
{
  "token": " capital",
  "logprob": -0.0012,
  "bytes": [32, 99, ...],
  "top_logprobs": [ /* top-K alternatives with their logprobs */ ],
  "_entropy": {
    "sampled_logprob": -0.0012,
    "sampled_prob": 0.9988,
    "top_k_entropy_bits": 0.031
  }
}
```

The `summary` block aggregates token count, total/mean surprise
(`-log2 p(sampled)`) and total/mean top-K entropy. Ollama reports log
probabilities, not raw logits, and only the top-K alternatives, so the
`top_k_entropy_bits` is a lower bound on true vocabulary entropy. Record it as
such; do not compare it against a full-vocabulary entropy from another source.

## Replication notes

- Hosts without an NVIDIA GPU drop `deploy.resources.reservations.devices` from
  the `ollama` service; Ollama falls back to CPU.
- The model store is bound to `./ollama-models`, so the 5.2 GB download persists
  across `compose down` and is not part of the Docker image.
- The harness uses only the Python standard library, so it runs on the host
  without torch/transformers/vllm.
