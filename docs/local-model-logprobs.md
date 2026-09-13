# Local Qwen3-8B logprobs data path

The experiment's remote model (`openai-codex/gpt-5.6-luna`) does not expose
token probabilities, so it cannot feed the response-state entropy metrics in
[`entropy-metrics-mvp.md`](entropy-metrics-mvp.md). This document records the
one-shot `/goal` data path that substitutes a locally served Qwen3-8B (4-bit)
whose token-level `logprobs` are captured per response.

The provider-neutral normalization and replay contract lives in
[`src/apart_incident_response/probability_artifacts.py`](../src/apart_incident_response/probability_artifacts.py).
Ollama and OpenRouter records use the `partial-token-probability-v1` artifact:
the sampled token is counted once, repeated top alternatives are removed,
covered and residual probability mass are retained, and partial entropy is
kept distinct from the full-vocabulary Qwen logits artifact.

The companion Transformers/Unsloth path in
[`qwen3_full_logits.py`](../scripts/qwen3_full_logits.py) uses the same pinned
Qwen3-8B checkpoint metadata and prompt contract to capture the complete
pre-sampling vocabulary distribution. It is isolated in
[`Dockerfile.qwen3`](../Dockerfile.qwen3); it does not add ML dependencies to
the remote-agent image.

OpenRouter uses the same one-shot dispatcher and shared artifact schema. Set
`OPENROUTER_API_KEY` in the controller environment and select the full
provider/model slug:

```console
PYTHONPATH=src python3 scripts/qwen3_goal.py --mode openrouter \
    --model openrouter/openai/gpt-4o-mini \
    --prompt-file prompts/task-1.txt --seed 1 --temperature 0 \
    --top-logprobs 5 --max-tokens 512 \
    --output runs/openrouter/logprobs/seed-1
```

The request is non-streaming and sets `logprobs: true`, `top_logprobs`, and
`provider.require_parameters: true` with fallbacks disabled. The adapter keeps
the response ID, usage, selected route, and sanitized raw response beside the
normalized probability artifact. An omitted or malformed token array writes an
explicit `failure.json` instead of fabricating probabilities.

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

For experiment prompts, pass an explicit prompt file through the shared mode
dispatcher:

```console
python3 scripts/qwen3_goal.py --mode logprobs \
    --model qwen3:8b \
    --prompt-file prompts/task-1.txt \
    --top-logprobs 5 \
    --temperature 0 \
    --num-predict 512 \
    --output runs/qwen3-8b/logprobs/seed-1
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
    "top_k_entropy_bits": 0.031,
    "partial_entropy_bits": 0.031,
    "residual_bucket_entropy_bits": 0.032,
    "covered_mass": 0.999,
    "residual_mass": 0.001
  }
}
```

The `summary` block aggregates token count, total/mean surprise
(`-log2 p(sampled)`) and total/mean partial entropy. Ollama reports log
probabilities, not raw logits, and only the top-K alternatives. The
`residual_bucket_entropy_bits` value groups all unobserved vocabulary mass into
one bucket and is a lower bound on true vocabulary entropy. The
`partial_entropy_bits` value is the entropy of the observed mass after
normalization; neither value is a full-vocabulary entropy and neither should be
compared directly with the Qwen full-logits metric.

## Full-vocabulary logits mode

The full-logits mode is the authoritative source for vocabulary entropy. It
calls `FastLanguageModel.from_pretrained` with the revision in
`config/qwen3-8b.json`, uses KV-cached Transformers generation with
`output_logits=True`, and stores one raw pre-sampling row for every generated
token:

```console
docker compose -f compose.qwen3.yaml run --rm qwen3 \
    --mode full-logits \
    --prompt "The capital of France is" \
    --seed 1 \
    --output runs/qwen3-8b/full-logits/seed-1
```

Each run contains:

- `full-logits/logits.safetensors`, with `logits[generated_token, vocabulary]`
  and `generated_token_ids` tensors;
- `full-logits/metadata.json`, with model/tokenizer revisions, dtype, shape,
  prompt hashes, decoding parameters, resource data, paths, checksums, and
  raw-logit provenance;
- `full-logits/generated.json`, with decoded IDs, thinking text, response text,
  and the rendered prompt; and
- `full-logits/entropy.json`, derived by applying full-vocabulary `log_softmax`
  to the binary tensor and gathering the generated-token logprobs.

Replay requires the same isolated runtime:

```console
python3 -c 'from apart_incident_response.qwen3_artifacts import replay_entropy; print(replay_entropy("runs/qwen3-8b/full-logits/seed-1"))'
```

The binary artifact's full-vocabulary entropy is not interchangeable with the
Ollama top-K entropy lower bound above. Both artifacts retain the sampled-token
logprob so parity can be checked without treating truncated top-K entropy as a
full distribution.

## Replication notes

- Hosts without an NVIDIA GPU drop `deploy.resources.reservations.devices` from
  the `ollama` service; Ollama falls back to CPU.
- The model store is bound to `./ollama-models`, so the 5.2 GB download persists
  across `compose down` and is not part of the Docker image.
- The harness uses only the Python standard library, so it runs on the host
  without torch/transformers/vllm.
- The Unsloth/Transformers image uses `./qwen3-cache` for weights and requires
  the NVIDIA Container Toolkit for its compose GPU service. `--device auto`
  fails explicitly without CUDA; use the Python entrypoint with
  `--device cpu` only for an intentional, non-performance CPU validation.
