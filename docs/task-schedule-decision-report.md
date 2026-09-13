# Decision report — task schedule, evals, measurement, and local inference

Status: working agreement, 2026-09-13. Active protocol: `response_dynamics_v1` (two agents, C0/C1/C2,
append-only researcher log). This report captures what we do to tasks, how we evaluate and test them,
why "forced output every minute" does not currently hold, how we plan to measure and enforce task
upload time, and how Ollama / `gemma2:2b` plugs in.

## 1. What we do to the task (question → data, end to end)

1. `tasks.py` defines 6 **synthetic, offline** tasks, difficulty 1–5, including the asymmetric database review, each with:
   - `question` displayed to both agents,
   - `choices` (option keys), `correct` key, per-agent private `evidence` (`A`, `B`),
   - `design` note explaining why it is a good control/intervention task.
2. The runner (`experiment.py`) builds a **per-agent observation** each checkpoint: private evidence only (+
   peer responses when communication is visible under C1/C2), a context hash, and a byte preflight.
3. Each agent returns a **TaskUpdate** with exactly `response_text` + `answer_class` (JSON schema enforced
   for Ollama via `format`).
4. The controller immediately appends an `evaluator_result`: `score = 1 if answer_class == correct`
   (exact option match, `evaluator_version='exact-option-v1'`), plus the expected class and scoring scope.
5. Everything lands in the append-only, hash-chained `events` SQLite store. Analysis never imports runtime.

Verified 2026-09-13: fixture protocol, analysis, and panel tests exercise the runner automatically.
The full suite passed 156 tests with two optional skips. HTTP smoke checks covered live generation
status, C0 isolation, C2 projections, ZIP/JSONL downloads, export auditing, and hash-chain integrity.

## 2. How we test the evals

- **Exact-option evaluator** is the only task metric today (`analysis.score` averages it per
  task/condition/step/agent). It measures selected-answer correctness, not explanation quality.
- **Answer-class entropy proxy** (bits) is the only distribution metric today; it is a frequency proxy,
  explicitly NOT semantic entropy (`semantic_entropy_status='not_computed'`).
- **Fixture adapter** (`adapters.py`) is deterministic, non-LLM plumbing. It is the correct tool to test
  protocol/eval/event flow in CI without paying for inference. The protocol suite now covers fixture shape,
  C2 visibility, minute violations, complete grids, and difficulty propagation.
- **OllamaAdapter** is the real-inference path and raises if the model is not installed at the endpoint.
- Imported records get no evaluator by design (`importing.py`); external provenance is unverified.

## 3. Why "force output what agents have already thought each minute" doesn't work today

The controller records submissions, but checkpoints are not paced to wall-clock minutes. Concretely:

1. **Step ≠ minute.** Config defaults to five logical checkpoints (CLI currently defaults to three).
   Nothing waits for a 60-second boundary; C2 step 3 means checkpoint 4, not necessarily elapsed 3:01.
2. **Request and run budgets exist.** Each controller wait is limited by the smaller of
   `timeout_seconds` and `minute_seconds` (defaults 180 and 60). The 300-second run budget is checked
   at checkpoint boundaries; an in-flight request can carry execution past that boundary. This is
   not a strict five-minute wall-clock cutoff or guaranteed cancellation of model computation.
3. **The old path had missing updates on failure.** The minute protocol now records a `minute_violation`
   and a degenerate `task_update` (`stalled_no_generation`) when the controller deadline is missed, so
   researchers can distinguish a failed submission from an absent record.
4. **Serially generated.** Agent A then Agent B are executed sequentially per step; their real wall-clock
   times differ, so both agents are not guaranteed to land in the same minute bucket.
5. **Stopped runs can remain incomplete.** Stop requests, run-budget exits, and resource errors can
   leave unattempted checkpoints. Reports must distinguish these from attempted, stalled submissions.

Effect: current timestamps support request-duration auditing, not an enforced minute cadence. Missing
and stalled observations require explicit accounting when comparing answer distributions.

## 4. How we plan to measure and enforce task upload time (≤ 5 min)

Current additive configuration and recorded fields:

- `schedule='minute_checkpoints'`, `minute_seconds=60`, `deadline_seconds=300` (budgets, not fixed pacing).
- `steps` default **5**; C2 unlock at **step 3 = checkpoint 4**; compare checkpoints before/after unlock.
- **Enforcement:** request timeout around each generation; when exceeded, append a
  `minute_violation` event **and** a degenerate `task_update` (`termination_state='stalled_no_generation'`)
  with `response_text` empty + `submitted=True`, recording attempted failures without inventing responses.
- **Measurement recorded per run:** `minute` (=`step+1`) in payload, per-run `elapsed_seconds`, per-minute
  `minute_elapsed_ms`, submission timestamps, `upload_within_deadline` bool. Existing update
  `elapsed_seconds` is batch-relative; the dashboard derives run elapsed time from stored run timestamps.
- **Provenance:** `difficulty` added to observation and `task_update` payloads so analysis and the panel can
  slice by difficulty without importing the runtime.

The live panel shows A/B queued, generating, validating, submitted, or stalled status, completed
responses, exact supplied contexts, permitted peer history, and recent events. Terminal batches expose
ZIP and response-JSONL download links. These researcher views never become agent inputs.

## 5. How we measure the agent task (and how we inform the team)

- **Metric registry** — every plotted number must trace to its definition, source events, and versions
  (task, model, prompt, config, evaluator). Current registry entries: `exact-option-v1` (accuracy),
  `frequency-bits-v1` (answer-class entropy proxy). Next: semantic entropy (Farquhar-style), `ΔH` around the
  unlock, difficulty-stratified accuracy/entropy, and `D(A,B)` trajectory distance as proxies.
- **Single source of truth:** the append-only event log → `analysis.analyze()` → `metrics.jsonl` → dashboard
  and the research bundle. Analysis stays artifact-only.
- We are deciding the **definition** of semantic state and the repeat-run grouping explicitly
  (cross-run vs fixed-checkpoint) before implementing, per `semantic-entropy-live-plan.md`.

## 6. Scenario tracking and simulation

- **Scenario = task × difficulty × condition (C0/C1/C2) × repeats**, counterbalanced across repeats,
  recorded in `batch_started.config` + per-task `task_version` digest.
- **Simulation order:** run the FixtureAdapter first (CI-valid, deterministic), then local
  `gemma2:2b` via Ollama, before any remote transport. This validates the protocol cheaply and separates
  plumbing bugs from model effects.

## 7. Ollama integration (local inference)

- `APART_OLLAMA_URL` (default `http://127.0.0.1:11434`); optional bearer token via `APART_MODEL_TOKEN`.
- Endpoint must be a plain HTTP(S) origin; no credentials/query embedded.
- Default model: `gemma2:2b`. `metadata()` confirms the model is installed (`/api/tags`) and records
  `.digest` + `/api/version`.
- Generation: `/api/chat` with JSON `format` schema, `temperature=0.6`, per-call `seed`,
  `num_predict=max_output_tokens`, `num_ctx=8192`, `keep_alive=10m`, HTTP timeout 180 s.
- `source` flag distinguishes `local_model` (loopback) vs `remote_model`; this drives dashboard badges and
  analysis strata, and must never be conflated with the fixture.

## 8. Open items agreed this session

- Difficulty into event schema (in §4 provenance).
- Enforce minute cadence + ≤5 min audit (§4).
- Add protocol/eval automated tests (fixture-first).
- Dashboard: additive views (two-agent live, shared vs isolated layer, minute time bar with per-minute
  submission triggers, task-pool editor, difficulty filter, researcher report). Do not rebuild existing
  compare/inspect/export views.
- Keep network/OAuth bridge from the online branch out of controlled runs (treat as future C3 channel whose
  traffic is logged, never injected into agent context).
