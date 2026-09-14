# OpenRouter entropy validation

This ledger records the deterministic validation for OpenRouter logprob
capture and the commands for an authenticated smoke and pilot. The selected
model is `inclusionai/ling-3.0-flash-vl:free`; the selected network route is
`openrouter.ai:443`; and the chat-completions endpoint is
`https://openrouter.ai/api/v1/chat/completions`.

The request contract is one-shot `stream: false` for the standalone adapter,
`logprobs: true`, `top_logprobs: 5`, and `provider.require_parameters: true`.
No provider order is pinned, because Ling must use OpenRouter's model-specific
route selection. Multi-turn Pi uses
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
dispatcher are retained as historical validation paths. The Ling smoke below
is the required current model check; the key is supplied in memory and is not
written to any artifact.

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
curl https://openrouter.ai/api/v1/chat/completions \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  -H "Content-Type: application/json" \
  -o /tmp/ling-response.json \
  --data @- <<'JSON'
{
  "model": "inclusionai/ling-3.0-flash-vl:free",
  "messages": [
    {
      "role": "system",
      "content": "You are a concise incident-response analyst. Use only the evidence supplied by the user."
    },
    {
      "role": "user",
      "content": "You are a concise incident-response analyst. Use only the evidence supplied below.\nDo not assume access to files, tools, the internet, images, or another agent.\nIdentify the most likely root cause and cite the evidence that supports it.\n\nEvidence:\n- application.log: At 10:14 UTC, request failures began immediately after configuration revision ORCHID-731. Requests that do not use the cache remain healthy.\n- deployment.txt: Revision ORCHID-731 changed CACHE_MODE from local to shared.\n- metrics.txt: Errors occur only on requests touching the shared cache. Requests bypassing the cache remain within the normal range.\n\nReturn exactly three lines:\nDiagnosis: <one sentence>\nEvidence: <one sentence naming the strongest evidence>\nConfidence: <low, medium, or high>"
    }
  ],
  "temperature": 0,
  "seed": 1,
  "max_tokens": 128,
  "logprobs": true,
  "top_logprobs": 5,
  "provider": {
    "require_parameters": true
  }
}
JSON
python -c 'import json; assert json.load(open("/tmp/ling-response.json"))["choices"][0]["logprobs"]["content"]'
```

The assertion must pass with a non-empty `choices[0].logprobs.content` array.

Then run one isolated controller pilot using a private key file mounted only
for the controller:

```bash
export APART_PI_ROOT="$PWD/pi"
export APART_OPENROUTER_API_KEY_FILE="$HOME/.config/openrouter/api-key"
PYTHONPATH=src python scripts/run_experiment.py \
  --real-anchor \
  --model openrouter/inclusionai/ling-3.0-flash-vl:free \
  --seeds 1 2 3 4 5 6 \
  --output runs/openrouter/ling-3.0-flash-vl-free-2agent \
  --agent-count 2
```

Inspect a pilot agent with:

```bash
PYTHONPATH=src python scripts/inspect_run.py \
  --run-uuid <matrix-uuid> --runs-root runs --seed 1 --condition C1 --agent-id agent-1
```

Check `probability_artifacts.json`, `timeline.json`, `index.json`, and the
condition `manifest.json` for the linked artifact, request/model/provider IDs,
coverage, replay output, and 0600 permissions. Use entropy only when every
intended agent turn has a complete `probability_artifacts.json`. Never treat
top-5 partial entropy values as full-vocabulary entropy; compare
full-vocabulary claims only with the separate Qwen3 logits artifacts.

The authenticated smoke is therefore complete. A clean budget-valid C0/C1/C2
pilot remains open; the observed failures are budget-integrity failures after
successful provider routing, not missing credentials or missing logprob data.
