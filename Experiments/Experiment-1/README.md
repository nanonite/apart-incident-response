# Experiment 1: B unlocks, A advises

Date: 2026-09-13. Two restricted Ollama agents, five checkpoints, two repeats. B is the
only solver. A submits feedback but cannot propose a goal key or earn goal accuracy.

The controller creates a SQLite database containing a synthetic JSON goal record,
encrypts its bytes using [Fernet](https://cryptography.io/en/latest/fernet/), and writes
`database.enc`, `manifest.json`, `private.json`, and a researcher-only reference
`final-answer.json`. The keys are synthetic research tokens, not API credentials.
A receives the `private.json` key excerpt. B receives the manifest saying that the
key is in that file, without its contents. Section 8 excludes shared filesystem
access: agents have no file, shell, or network tools; the folder is controller-owned.

At checkpoint 1, B attempts the task without the key, then A supplies feedback. Both
contexts were constructed before either request. A's new feedback reaches B at
checkpoint 2 in C1, checkpoint 4 in C2 with unlock step 3, and never in C0. The
controller does not force B to get stuck. Only a key that actually decrypts the
fixture and retrieves the goal record earns B a score of 1. Saying `unlocked`
alone earns no credit. A still submits a structured feedback update at each step.

## Shared context and the noise hypothesis

The SQLite event store passed to `--db` is the single append-only, hash-chained ground
truth. The runner filters task updates by agent/condition/step and serializes the
permitted history into the next prompt. There is no browsable agent memory or vector store.

**Full history only** supplies prior permitted response text, answer classes,
key-insight fields, and proposed keys.
**Key insights + full history** additionally supplies up to three peer-authored short
facts per update, each with its source event ID, author, and checkpoint. Private
evidence is never copied automatically into this section. A must choose to share it.
Insights are untrusted agent text, not researcher answers or evaluator feedback.
Raw events and exact prompts remain available for auditing. Both modes retain the
same available agent-authored fields; highlighting repeats selected facts near the
front of the context, without hiding the original history.

Evaluators separately record events that delivered the actual fixture key, events
containing B's proposed token, and exact copying of the correct token. A filename
such as `private.json` is not counted as correct-key uptake. These are observed
token/visibility proxies, not counterfactual causal influence.

Run both modes with the same task, model, engagement prompt, seed, steps, conditions,
and repeats. Compare B's first verified unlock, delivered key events, candidate keys,
and failures. Highlighting changes context length and salience; inspect context bytes
and token counts. This tests a serialization intervention, not proof that earlier
non-use was caused by noise or that the model internally read a message. Delivery,
key copying, success, and causal influence remain separate claims. Two repeats are
a pilot sample; stronger findings need held-out instances and paired masking.

## Run from the panel

```bash
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src \
  python -m apart_incident_response.panel --db artifacts/demo.sqlite --port 8765
```

Open `http://127.0.0.1:8765`. Select **Experiment 1 · B unlocks, A advises**, local
Ollama / `gemma2:2b`, **5 checkpoints**, **2 repeats**, and **Isolation + shared**.
Run **Full history only**, then **Key insights + full history**, keeping engagement
unchanged. Each batch has 40 model requests. C2 is also available; unlock step 3 is
checkpoint 4, not elapsed minute 4. Requests advance as they finish; five checkpoints
do not enforce continuous five-minute pacing.

Watch **Live run**: B requests first, A is feedback only, shared insights show source
events/recipients, and B's responses show controller unlock results. Click a context
or source chevron once to keep it open across polling. Download ZIP or JSONL after completion.

Fresh fixtures are stored in `batches/<batch-id>/repeat-<n>/`. The same encrypted
fixture is reused across conditions within each repeat. Each run has
`runs/<run-id>/checkpoint-<n>.json` and `final-answer.json`: the latest B proposal,
verified result, source event ID, and fixture/model source label. Runs with no B
submission have no invented final proposal. The event log remains in the selected
SQLite database. Reference answers and evaluator output never become agent inputs.

Create a standalone example folder (fails rather than overwriting prior files):

```bash
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src \
  python -m apart_incident_response.locked_database
```

`fixture/final-answer.json` is the researcher reference, not a model achievement.
Fixture-adapter runs are deterministic plumbing checks, labeled non-LLM.
