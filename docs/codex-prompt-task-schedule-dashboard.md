# Codex prompt — task schedule into the event schema + dashboard showcase

Date: 2026-09-13.

Use this verbatim (or lightly trimmed) as the master prompt for a Codex agent. It starts with
repository inspection so Codex does not rebuild what exists.

---

You are working in the `apart-incident-response` experiment repo. This is an AI-safety research
prototype: two restricted LLM agents solve the same synthetic task under different communication
conditions (C0 isolation, C1 shared from start, C2 scheduled unlock), while an append-only event log
records everything. The scientific goal is to measure entropy / coordination dynamics of evolving
agent responses — we are not building a general multi-agent framework.

Do NOT start coding immediately. First produce a short "what is already built" report by reading the
repo, covering: `src/apart_incident_response/{tasks,experiment,events,analysis,adapters,panel,runtime}.py`,
`tests/`, and `dashboard/dist/` (HTML/JS/CSS, demo.json). Identify what each module owns, the event
kinds it emits, and which dashboard views already exist (compare conditions, run inspector, export,
task tabs, timeline, score chart, distribution panel). Then return that report as section 0 of your
reply.

## Context you can rely on

- Protocol: `response_dynamics_v1`, two agents A/B, one researcher-visible append-only event store
  (`events.py`, hash-chained SQLite). Observation ≠ visibility: agents get filtered projections; the
  controller logs everything.
- Tasks: 5 synthetic offline tasks in `tasks.py`, difficulty 1–5, each with `choices`, `correct`,
  private `evidence` per agent, and `design`. No task touches a real website or network.
- Eval: exact-option evaluator (`answer_class == correct`), plus an answer-class entropy proxy in
  `analysis.py`. Semantic entropy is decided but NOT implemented.
- Local inference: `OllamaAdapter` (`adapters.py`) with `gemma2:2b` at `http://127.0.0.1:11434`
  (env `APART_OLLAMA_URL`, optional `APART_MODEL_TOKEN`); JSON `format` schema, temperature 0.6,
  per-call seed, `num_ctx=8192`. `FixtureAdapter` is deterministic non-LLM plumbing for CI.
- The tweaks below are **additive** and must not break existing runs (append-only log, same event
  kinds, same `RuntimeConfig` isolation contract in `runtime.py`). Keep observation ≠ visibility.
  Do not touch the bubblewrap network/shell isolation policy for C0/C1/C2.

## Task 1 — difficulty into the event schema

1. Add `difficulty` to each agent `observation` and `task_update` payload in `experiment.py`
   (from the task definition), and propagate it through `analysis.py` rows so every metric is
   independently sliceable by difficulty.
2. Add it to the import pipeline (`importing.py`) as an optional field so external records can carry
   it without becoming trusted; record `difficulty` in analysis rows when `task_update` includes it.
3. Panel: surface difficulty-stratified accuracy and answer-class entropy in the existing dashboard
   (a difficulty selector that filters task tabs does not count; add explicit per-difficulty views).

## Task 2 — enforce task upload time (minute cadence, ≤ 5 min audited task)

Current problem (document this in your report): the "submit every minute" rule is only a prompt line;
steps are not wall-clock minutes, a single generation can run 180 s, and failed/timeout/anomaly outputs
emit NO `task_update` (`run_error` only), leaving ragged minutes that skew entropy.

1. Add to `experiment.py` config (`validate_config`, with defaults that keep old runs valid):
   `schedule='minute_checkpoints'`, `minute_seconds=60`, `deadline_seconds=300`,
   and set defaults `steps=5`, `unlock_step=3` for the minute protocol (C2 unlocks at the start of
   minute 4, i.e. 3:01; minutes 4–5 are measured post-unlock).
2. Enforce per-minute deadlines around each generation. On timeouts/violations, instead of leaving a
   hole, append BOTH a `minute_violation` event and a **degenerate** `task_update` with
   `termination_state='stalled_no_generation'`, empty `response_text`, `submitted=true`, and
   `done_reason` of the failure, so the grid "agent × minute" is always complete.
3. Record `minute` (=`step+1`), per-run `elapsed_seconds`, per-minute `minute_elapsed_ms`, exact
   submission timestamps, and `upload_within_deadline` on each update. Add a per-run deadline check that
   can stop a run at 5 min with a `run_finished` status `over_deadline` without inventing data.
4. Keep the old wall-clock config names working (timeout_seconds, batch_timeout_seconds) — the new
   fields are an overlay, not a replacement.

## Task 3 — scenario tracking and simulation

1. Keep the scenario space explicit: **task × difficulty × condition × repeats**, counterbalanced,
   recorded in `batch_started.config` and per-task `task_version` digest (already present — make sure
   difficulty is covered by the task digest).
2. Provide a scripted example demonstrating a **simulated scenario**: `experiment.py --adapter fixture`
   for a clean plumbing pass, then `--adapter ollama --model gemma2:2b` for a real local run, and a
   `--tasks`/`--conditions`/`--steps`/`--unlock-step` invocation for the 5-minute C2 scenario. Add it to
   `examples/` with the exact commands.
3. Add a `docs/` note (1 paragraph max) describing how scenarios differ from experimental groups and how
   results remain comparable (same log contract; visibility is a policy, logging is constant).

## Task 4 — dashboard showcase (additive views, do not rebuild)

Identify the existing views first (compare, inspect, export) and then add these as NEW sections/views in
`dashboard/dist` (vanilla JS/CSS, same `/api` server in `panel.py` — extend it only if truly needed):

1. **Two-agent live view.** Side-by-side cards for A and B showing per-minute proposals
   (minute 1..5), answer class, score, communication availability, and whether the submission landed
   within the deadline.
2. **Communication layers.** A visual split of the isolated layer (C0) vs the shared channel (C1), with
   a scheduled-unlock marker for C2 at minute 4: which messages were visible to whom (use
   `visible_message_ids` / `communication_delivery`) and when the unlock fires.
3. **Minute time bar.** A progressing 1..5 minute bar while a batch runs, with a **visual trigger** that
   lights up as each agent submits each minute (poll `/api/state`); when a run is live, show the running
   batch's minute in real time and a countdown of the current minute.
4. **Task pool (management).** Read-only-first view of the task pool with difficulty labels; provide a
   wiring point (endpoint stub documented, not necessarily implemented) so researchers can later
   add/edit/disable questions.
5. **Researcher output redirect.** A "report" action that produces a markdown summary per batch: per
   condition accuracy, answer-class entropy per minute around the unlock, per difficulty, plus warnings
   for `minute_violation`/stalled submissions — downloadable from the dashboard, and it must never feed
   back into running agents.

Keep the existing compare/inspect/export views working (they are used for auditing). Add a titled
"previously built" block in the dashboard footer or README listing what existed before this change.

## Task 5 — tests (regression net)

Extend `tests/` with automated tests for the pieces you touch, fixture-first:

- `test_tasks.py`: pool validation, difficulty bounds 1–5, digest stability/`task_by_id`.
- `test_experiment_protocol.py`: minute schedule config defaults; per-minute deadline produces
  degenerate updates + `minute_violation`, grid stays complete; C2 unlock at step 3 changes visibility
  exactly at minute 4; difficulty lands in `task_update`.
- `test_analysis.py`: entropy correctness (normalized distribution, null for n<2), difficulty slicing.
- `test_adapters.py`: fixture generate shape; OllamaAdapter endpoint validation.
- Keep `tests/test_runtime.py` green (do not modify the isolation contract).

## Constraints

- Observation ≠ visibility; never send the global log to an agent.
- Do not implement C3 (emergent sandboxed channel) now; do not wire the online branch's network/OAuth
  bridge into controlled runs.
- Analysis remains artifact-only (no runtime imports).
- Do not put entropy math into the agent harness; expose structured data instead.

## Deliverables

1. "What is already built" report (section 0).
2. Implementation of Tasks 1–5 with tests green (`UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src
   python -m unittest discover -s tests -v`).
3. A short changelog note at the end listing exactly which files you changed and which you deliberately
   left untouched.

## Files changed in the verified implementation

Live-observability update (2026-09-13): changed `panel.py`, `tests/test_panel.py`, `dashboard/dist/{index.html,app.js,styles.css,demo.json}` and added `dashboard/dist/activity.js`. Updated this note, `task-schedule-decision-report.md`, the dashboard design note, and asymmetric study instructions. The portable snapshot was regenerated from verified stored Ollama data; its previous copy is backed up under `artifacts/panel-live-backup`. No harness, runtime, visibility, or model-adapter behavior changed. The UI distinguishes discrete checkpoints from actual elapsed time and provides terminal-batch log downloads. Validation: 156 tests passed with two optional skips; live HTTP and download smoke checks passed.

Integration update (2026-09-13): merged upstream runtime development, added panel API identification and a stale-server launch guard, and verified the combined suite (153 tests, 2 optional Qwen3 tests skipped) plus HTTP launch/audit/C2 projections. Integration edits: `panel.py`, `app.js`, `tests/test_panel.py`, `README.md`, `.gitignore`, `chainlink-breakdown-plan.md`, and this note. `runtime.py` and `tests/test_runtime.py` match upstream unchanged. Recorded SQLite logs passed hash-chain verification and were not rewritten.

Changed: `src/apart_incident_response/tasks.py`, `experiment.py`, `analysis.py`, `importing.py`, `panel.py`,
`tests/test_tasks.py`, `tests/test_experiment_protocol.py`, `tests/test_analysis.py`, `tests/test_adapters.py`,
`dashboard/dist/index.html`, `dashboard/dist/app.js`, `dashboard/dist/styles.css`, and the three research notes.
Deliberately untouched: `src/apart_incident_response/runtime.py`, `tests/test_runtime.py`, bubblewrap policy,
network/OAuth integrations, and any real website.
