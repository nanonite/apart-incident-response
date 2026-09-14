# Codex handoff standard — minimum quality gate

Purpose: before any automation (Codex, a teammate, or you) starts changing this repo, meet this bar so
the incoming agent only sees *verified* state and does not trip on stale artifacts. Check everything in
order; a failure at any step blocks a code handoff (you may still do analysis-only handoffs).

## 1. Tests are green

```bash
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src python -m unittest discover -s tests -v
```

Expect:
- `test_runtime.py` — isolation contract projector (identity, budgets, bubblewrap, minimal Pi launch).
- `test_panel.py` — panel state serializable, audit trail, projections (global vs A vs B), C2 unlock,
  complete grid.

If `test_panel.py` fails, the dashboard/back-end handshake is broken; fix before passing to Codex.

## 2. Wire-level smoke test

Start the panel against the demo/prod DB:

```bash
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src python -m apart_incident_response.panel \
  --db artifacts/observatory.sqlite --port 8765
```

Open http://127.0.0.1:8765 and confirm (interaction guide below). Also hit read-only endpoints:

```bash
curl -s 'http://127.0.0.1:8765/api/state'            # JSON, no error
curl -s 'http://127.0.0.1:8765/api/audit'            # researcher action trail
curl -s 'http://127.0.0.1:8765/api/projections?batch=<id>&step=0&run=<run>'  # three panes
```

## 3. Dashboard snapshot is current

`dashboard/dist/demo.json` must match the current protocol (5-minute grid, C0/C1/C2). Regenerate only
from verified data, never by hand-editing JSON:

```bash
# 1) produce/use a fixture batch (CI-safe), e.g. steps=5, unlock_step=3
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src python - desktop/add_demo_batch.py # or your batch runner
# 2) write the portable snapshot
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src python -m apart_incident_response.panel \
  --db <demo-db> --snapshot dashboard/dist/demo.json
```

Check the snapshot carries: `events`, `metrics`, `audit`, and per-update `difficulty` when the event
schema has been extended. Do not ship a demo with a status of `running` unless that is intentional.

## 4. Artifacts and secrets

- `artifacts/` holds the append-only logs; never delete or rewrite rows (store has no-update/no-delete
  triggers by design).
- Never commit `APART_MODEL_TOKEN`, `.openai/`, `.chainlink/issues.db` content, or local model endpoint
  credentials. `.gitignore` must already exclude them.
- Report the state of `git status` and `git log --oneline -5` in the handoff so Codex knows the base and
  any wipe.

## 5. Docs are aligned (these three are the handoff bundle)

- `docs/task-schedule-decision-report.md` — what we do to tasks, why the minute force-out fails today,
  how we will measure/enforce ≤5 min, Ollama setup.
- `docs/dashboard-design-and-experiment-plan.md` — users, toggles (view vs run-config), shared-log
  three-pane design, E1–E10 experiments, roadmap.
- `docs/codex-prompt-task-schedule-dashboard.md` — the executable spec (difficulty→schema, minute
  enforcement, scenarios, dashboard add-ons, tests).

Each must record the date, and `files changed` section in the Codex prompt must be answered, not skipped.

## 6. How to interact with the UI and audit it

1. **Launch a run:** pick task suite, conditions, checkpoints, unlock step, adapter/model → "Run
   experiment". Alone "Stop after current request" stops at the next boundary.
2. **Watch live:** the minute bar (t1..t5) lights a chip when both agents submit that minute; the running
   minute pulses while the batch is live.
3. **Toggle researcher views** (view toggles bar): Communication availability, Scores, Messages
   received, Global vs A vs B. These change only what *you* see.
4. **Shared log** tab: pick a run and a minute → Global truth | Agent A | Agent B panes; badges show how
   many events each agent could see and whether the channel was open. The audit trail below it records
   every researcher action (launch, stop, import, export, snapshot).
5. **Audit evidence:** any plotted number → trace to `source_event_ids` → event JSON → the three-pane
   projection that generated it. The event store hashes the chain; `/api/audit` is the record of who did
   what.

## 7. Delivering model outputs (the researcher handoff)

- **Real model metadata** comes only from the adapter: `OllamaAdapter.metadata()` (model digest, runtime,
  transport `local_model`); every `task_update` carries `model`, `source`, `token_counts`, `latency_ms`,
  `model_metadata`. The dashboard badges and analysis strata use `source`, never the fixture.
- **Handoff artifacts** via the Export view: `apart-research-bundle.zip` (events.jsonl, responses.jsonl,
  metrics.jsonl, manifest.json, README) and `responses.jsonl`. Download them, don't copy DB rows.
- Semantic entropy and `ΔH` are analysis-side, tracked in metrics.jsonl — they never touch the agents.

## 8. When Codex arrives

- Give it this file plus the three docs in §5, and `git status` output.
- Codex must produce the "what is already built" report first (per the prompt), not start editing.
- Boundaries fixed for this round: don't modify `test_runtime.py`, don't implement C3, don't wire the
  online network/OAuth bridge into controlled runs, keep analysis artifact-only.