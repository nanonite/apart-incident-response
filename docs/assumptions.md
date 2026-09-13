# Assumptions: local Qwen3-8B logprobs data path

This document records the working assumptions behind the local-model data path
added under issues #72 and #75. It is the single place to revisit when any assumption is
violated or a downstream metric looks wrong. Where an assumption is a known
simplification, it is marked **[LIMITATION]** so the reader knows it is a
deliberate trade-off rather than an accident.

## 1. Why a local model at all

The experiment's configured remote model (`openai-codex/gpt-5.6-luna`) does not
expose token probabilities, so it cannot feed the response-state entropy metrics
in `entropy-metrics-mvp.md`. The local path substitutes a model whose token
`logprobs` are captured per response, so the entropy pipeline can be exercised
end-to-end while the remote-model experiment continues independently.

**Assumption A1.** The local model is a *data-producing substitute*, not a
replacement for the configured remote model in the C0/C1/C2 experiment. The
two are not compared as model tiers until a model tier passes live-access
validation (see `controller.py`).

## 2. Model and serving choice

- Model: `qwen3:8b` (Qwen3-8B instruct, GGUF `Q4_K_M`, 8.2B, 40960 context).
- Server: Ollama `0.34.0`, which exposes `logprobs`/`top_logprobs` on the
  native `/api/generate` endpoint.

**Assumption A2.** `Q4_K_M` (4-bit) is the correct quantization for the
12 GB RTX 4070 Ti. fp16 would be ~16 GB and does not fit. 4-bit leaves headroom
for context and avoids OOM.

**Assumption A3.** The native `/api/generate` endpoint is preferred over the
OpenAI-compatible `/v1/chat/completions` layer. The native endpoint documents
`logprobs`/`top_logprobs` directly; the compat layer's handling of those fields
has historically lagged and is not needed for a one-shot completion.

**Assumption A4.** `think` (Qwen's reasoning mode) is disabled by default so the
answer tokens are emitted directly and the logprob budget is not spent on
`<think>` tokens. Enabling it would change which tokens dominate the entropy
signal, so it is left off unless a specific hypothesis requires reasoning traces.

## 3. What "logits" means here

**Assumption A5. [LIMITATION]** Ollama reports **log probabilities, not raw
logits**, and only the **top-K** alternatives (via `top_logprobs`, up to 20).
The harness computes a **top-K entropy lower bound** and a **sampled-token
surprise** (`-log2 p(sampled)`), not a full-vocabulary entropy. These are
recorded as such and must not be compared against full-vocabulary entropies from
another source (e.g. a transformers or vLLM dump).

**Assumption A6.** The relevant probability surface for the entropy metrics is
the model's *output token distribution over a single response*, matching the
one-shot `/goal` definition in `mvp-plan.md` (no user-to-agent follow-up). This
is response-state entropy, not the evaluator-attributed source entropy (`H_src`)
which is computed benchmark-side and does not need model logprobs.

**Assumption A7.** Logprobs are interpreted as the model's internal belief
state. This is consistent with the `entropy-metrics-mvp.md` guidance that agents
should not be asked to expose calibrated belief distributions; the logprobs are
a passive byproduct of generation, not a prompted estimate.

## 4. Determinism and sampling

**Assumption A8.** `temperature=0` is the default so the sampled token is the
argmax and `sampled_prob` ≈ 1 for most positions. This makes the surprise signal
dominated by the model's actual top-1 confidence. To study the *distribution*
(spread, alternatives), a non-zero temperature and/or larger `top_logprobs` must
be set explicitly.

**Assumption A9.** `--seed` is passed through to Ollama only when set. Qwen's
`<think>` and other nondeterministic paths may still yield run-to-run variance
even with a seed, so seeds should be treated as best-effort reproducibility, not
a guarantee.

## 5. Environment and replication

**Assumption A10.** The model store lives in `./ollama-models` (git-ignored) as
a compose bind mount. This keeps the 5.2 GB download out of both the Docker
image and the git tree, and out of the root filesystem (which is near full).

**Assumption A11.** GPU access requires the NVIDIA Container Toolkit. On a
CPU-only host, dropping `deploy.resources.reservations.devices` makes Ollama
fall back to CPU; this is noted in `compose.yaml` but is not the tested path.

**Assumption A12.** The harness (`scripts/ollama_goal_inference.py`) is
stdlib-only so it runs on the host without torch/transformers/vllm. It therefore
cannot expose raw logits; that is acceptable under A5.

**Assumption A13.** The Transformers/Unsloth path uses the exact model and
tokenizer revisions in `config/qwen3-8b.json`. The safetensors artifact records
the revisions, quantization, runtime versions, prompt hashes, decoding settings,
tensor shape/dtype, and checksums needed to identify a replay.

**Assumption A14.** `output_logits=True` is the raw language-model-head output
before Transformers sampling processors. The artifact stores those rows rather
than the processed `scores` surface, and the generated token ID at each row is
stored in the same binary file for exact sampled-token logprob parity.

**Assumption A15. [LIMITATION]** Full-vocabulary entropy is measured on the
selected quantized Qwen3 checkpoint. It is comparable across replayed runs with
the same revision and runtime contract, but it is not automatically numerically
identical to Ollama's GGUF path or to a different quantization.

## 6. Known limitations to revisit

1. **Top-K only in Ollama.** The Ollama compatibility path remains limited to a
   top-K entropy lower bound. Full-vocabulary metrics must use the separate
   Transformers/Unsloth safetensors path; do not substitute `output_scores` for
   the raw `output_logits` artifact.
2. **No prompt logprobs.** Only generated-token logprobs are captured. Input-side
   probabilities (e.g. how likely the model found each evidence token) are not
   available from Ollama's `/api/generate`.
3. **Temperature scaling of logprobs.** Ollama reports logprobs from the raw
   logits; if sampling is later run at `temperature != 0`, the reported logprobs
   may not reflect the temperature-scaled distribution actually sampled. Keep
   temperature at 0 for the entropy path unless this is consciously revisited.
4. **One-shot only.** The harness does one completion. Multi-turn or staged
   `/goal` output (the "temporal spike" case in `mvp-plan.md` §13.1) is out of
   scope and would need a different harness.

## 7. Sign-off

Assumptions A1–A15 hold as of this commit. Any change to the model, quantization,
server, artifact schema, or logits interpretation should update this document
and re-examine the marked limitations.
