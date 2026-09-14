# OpenRouter entropy validation

This ledger records the deterministic validation for OpenRouter logprob
capture and the commands for an authenticated smoke and pilot. The selected
model is `openrouter/openai/gpt-4o-mini`; the selected network route is
`openrouter.ai:443`; and the chat-completions endpoint is
`https://openrouter.ai/api/v1/chat/completions`.

The request contract is one-shot `stream: false` for the standalone adapter,
`logprobs: true`, `top_logprobs: 5`, `provider.require_parameters: true`, an
explicit OpenAI provider order, and fallbacks disabled. Multi-turn Pi uses
streaming and captures `choice.logprobs.content` into the per-assistant-turn
`probabilityCapture` field. Tool-call turns preserve their normal Pi events and
are marked unavailable when no text token array is returned.

## Deterministic validation

Run from the repository root:

```console
PYTHONPATH=src python3 -m unittest discover -s tests
sh -n scripts/container_matrix_entrypoint.sh
git diff --check
```

On 2026-09-13, the Python suite completed with 167 tests and 2 environment
skips. The fixture tests cover the request fields, sampled and alternative
tokens, duplicate removal, empty and malformed data, response redaction,
per-turn text capture, tool-call compatibility, artifact replay, and C0/C1/C2
pairing. The Pi provider test was added against the pinned checkout but could
not run in this environment because its `typebox` dependency is not installed
and the frozen lockfile cannot migrate the checkout's `package-lock.json`.

The standalone smoke, failure, and artifact tests do not use a credential. A
successful test artifact records the response ID, response model, OpenRouter
route, usage, sanitized raw response, and the
`partial-token-probability-v1` artifact. Missing or malformed token arrays
write `failure.json` with an unavailable artifact and an explicit reason.

The authenticated standalone adapter and the documented `qwen3_goal.py`
dispatcher both ran successfully on 2026-09-13 with
`openrouter/openai/gpt-4o-mini` over `openrouter.ai:443`. Each response
captured 7 tokens. The resulting artifacts are under the printed model-scoped
UUID roots below `runs/openrouter/logprobs` and `runs/openrouter/smoke`; the key was supplied from
`.env` in memory and was not written to either artifact.

The containerized pilot also reached OpenRouter after the Pi compatibility fix
changed `max_completion_tokens` to `max_tokens` for this provider. Fresh
single-seed C0/C1/C2 attempts for seeds 1, 2, and 3 all produced provider
responses and per-agent probability artifact paths. The controller marked the
matrices `invalid_non_experimental` because seed 1 had a C0 budget overage,
seed 2 had a C2 overage, and seed 3 had two C2 overages. These are retained as
diagnostic runs; no invalid matrix is presented as experimental evidence.

## Authenticated runs

When a controller-only key is available, run the low-token standalone smoke:

```bash
export OPENROUTER_API_KEY='provided-outside-the-repository'
PYTHONPATH=src python scripts/qwen3_goal.py --mode openrouter \
  --model openrouter/openai/gpt-4o-mini --prompt 'The capital of France is' \
  --seed 1 --temperature 0 --top-logprobs 5 --max-tokens 16 \
  --output runs/openrouter/smoke
```

Then run one isolated controller pilot using a private key file mounted only
for the controller:

```bash
export APART_PI_ROOT="$PWD/pi"
export APART_OPENROUTER_API_KEY_FILE="$HOME/.config/openrouter/api-key"
PYTHONPATH=src python scripts/run_experiment.py \
  --real-anchor --model openrouter/openai/gpt-4o-mini --seeds 1 \
  --output runs/openrouter/pilot
```

Inspect a pilot agent with:

```bash
PYTHONPATH=src python scripts/inspect_run.py \
  --run-uuid <matrix-uuid> --runs-root runs --seed 1 --condition C1 --agent-id agent-1
```

Check `probability_artifacts.json`, `timeline.json`, `index.json`, and the
condition `manifest.json` for the linked artifact, request/model/provider IDs,
coverage, replay output, and 0600 permissions. Never treat the partial entropy
values as full-vocabulary entropy; compare full-vocabulary claims only with
the separate Qwen3 logits artifacts.

The authenticated smoke is therefore complete. A clean budget-valid C0/C1/C2
pilot remains open; the observed failures are budget-integrity failures after
successful provider routing, not missing credentials or missing logprob data.
