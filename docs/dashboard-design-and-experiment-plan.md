# Dashboard design: users, feature toggles, shared log, and the two-agent test experiments

Date: 2026-09-13. This plan is additive to the response-dynamics protocol and the current local panel.

Navigation/export fix (2026-09-13): sidebar actions update the workspace title,
select and focus the corresponding content, and hide unrelated live widgets.
Compare shows responses/charts; Run inspector shows raw events; Research handoff
shows imports/downloads; Shared log shows Global/A/B projections with repeat labels.
The header Export traces action downloads directly. Active-run ZIPs are partial
snapshots with explicit cutoff/provenance; completed ZIPs also include `report.md`.
Live response JSONL and Markdown downloads use the local API and display failures.

Experiment 1 update: the new preset separates B's database-unlock goal from A's
feedback-only role. Shared-context selection compares full history with an additional
agent-authored key-insight projection. Live run shows source IDs and verified unlocks;
context/source disclosures retain open state across polling. See [Experiment 1](../Experiments/Experiment-1/README.md).

Implemented live observability: a dedicated top-level Live run pane follows the active run from stored events, showing A/B request states, exact supplied contexts, response transcripts, permitted peer history, request/run elapsed time, and activity events. Completed or stopped batches expose ZIP and JSONL downloads. The adapter returns complete responses, not streaming tokens. Checkpoint labels and actual elapsed time are displayed separately; the current runner has time budgets but no fixed one-minute pacing.

Companion to `docs/task-schedule-decision-report.md` and `docs/codex-prompt-task-schedule-dashboard.md`.
Scope: design of the explanatory panel (web), the "single shared log" picture, a visual of what each
agent internally receives, and a list of small experiments to run the two-agent system. All dashboard
work is **additive**: the existing compare/inspect/export views stay intact.

## 1. Key UI users (personas)

| Role | Who | Needs in the panel |
|---|---|---|
| Experiment controller | runs batches, sets conditions | Condition config, run start/stop, live progress, per-minute submission log, compute/cost guardrails |
| Entropy / physics analyst | owns `p → H` math | Per-condition entropy per minute, ΔH around unlock, difficulty strata, raw answers + embeddings, metric provenance |
| Input & representation researcher | owns tasks/prompts/embeddings | Task pool view/edit, prompt & config versions, answer/embedding mapping, import of external outputs |
| Research auditor | trusts the record | Full append-only shared log, tamper/hash status, export bundle, provenance for any plotted point |
| Safety observer | containment must hold | Network/isolation status visible at a glance, evidence that global log never reaches agents, stall/violation alerts |

The panel must let each role see only what they own + enough global truth to audit it.

## 2. Two kinds of toggles (keep them separate)

- **View toggles** (frontend-only, saved in `localStorage`) change what the *researcher* sees. They never
  change what the agents receive — observation ≠ visibility is preserved.
- **Run-config toggles** change the *next* batch (`/api/run`): conditions, unlock minute, steps, per-minute
  budget, difficulty range, model/adapter. They are read-only while a batch is live.

### Feature list — "important features with on/off switches"

| Toggle | Kind | What it does | Backed by | Default |
|---|---|---|---|---|
| Show communication availability (C0/C1/C2) | view | Colors agent cards by whether a peer channel exists this minute | `communication_available` on updates | on |
| Show messages received per agent | view | Lists `visible_message_ids` / `communication_delivery` events an agent received each minute | payload IDs | off |
| Peek: exact agent context vs global | view | Side-by-side "what A saw / what B saw / global truth" at a minute | `agent_observation.messages` | off |
| Split isolated vs shared layers | view | Two-layer diagram: C0 (no channel) vs C1 (channel with delivered dots) + C2 unlock marker at minute 4 | conditions + update ids | on |
| Evidence visibility (private A / private B / shared) | view | Color-coded tiles of the exact evidence slices an agent could use | observation payload | off |
| Show evaluator scores | view | Overlay ✓/✕ on answers (score is researcher annotation, never agent input) | `evaluator_result` | on |
| Minute grid / wall-clock | view | Swap axes: minute 1..5 vs real timestamps | payload `minute`/timestamps | minute |
| Difficulty filter | view | Restrict all views to a difficulty band | payload `difficulty` | all |
| Communication enabled (per new run) | run-config | Choose C0 / C1 / C2 / unlock minute for next batch | `/api/run` config | C0,C1 |
| Enforce ≤5 min audit | run-config | Turn on `minute_seconds`/`deadline_seconds` enforcement for next batch | new experiment config | on |
| Stall policy | run-config | Emit degenerate `stalled_no_generation` updates to keep the grid complete | new experiment config | on |

"**How to enable them**" = the run-config ones map to `/api/run` `conditions`, `unlock_step`, `steps`,
`minute_seconds`, `deadline_seconds`; the view ones are pure UI state and require no backend change.

## 3. "Single shared log" UI (the whole picture)

Reuse the existing global researcher log (inspect view) and deepen it into a dedicated view:

- Full-stream, append-only, hash-aware: show `seq`, `kind`, `run_id`, `minute`, agent, and hash chain tip.
- **Three-pane mode** at a selected minute: global truth | Agent A's projection | Agent B's projection.
  Each projection shows exactly the events that agent could see (`visible_event_ids`); the global pane
  shows everything including private evidence and evaluator truth. This directly demonstrates
  observation ≠ visibility.
- Filters: batch, run, condition, agent, kind, minute, communication on/off.
- Live tail while a batch runs; per-minute markers and violation/stall badges.
- One click per event → JSON detail (already exists in inspect view; reuse it).

## 4. Visual of the agents' internal communication (what they actually receive)

- Per minute `t` and agent, render a "mailbox": the exact messages delivered (`agent_observation.messages`
  + `visible_message_ids`). Late minutes show delivered peer responses under C1/C2 and nothing under C0.
- Communication layer diagram: two agent nodes; a shared channel line appears only when
  `communication_available==True`; dots on the line = delivered messages (id + step + author).
- C2 shows a lock that opens at minute 4 (3:01) and a "everything visible to this point" marker, matching
  the retrospective-history policy.

## 5. Little experiments to run the two agents (fixture-first, then gemma2:2b)

All cheap and isolated; each controls one factor. `C0/C1/C2`, `steps=5`, `unlock=3`.

| # | Experiment | Setup | What it tests | Cost |
|---|---|---|---|---|
| E1 | Plumbing grid | Fixture, C0 only, task `inventory`, 1 repeat | minute grid complete, degenerate policy, eval emits, no holes | trivial |
| E2 | Baseline C0 | Fixture, C0, all 5 difficulties, 3 repeats | difficulty→accuracy/entropy baseline, stable ordering | trivial |
| E3 | Shared vs isolated | Fixture, C0 vs C1, all difficulties, 3 repeats | does communication move entropy/accuracy (±), not assumed increase | trivial |
| E4 | Scheduled unlock ΔH | Fixture, C2 unlock=3, all difficulties | ΔH around minute 4, sign/magnitude/persistence per difficulty | trivial |
| E5 | Difficulty gradient | One condition, C1, difficulties 1..5, 3 repeats | does harder task raise communication-seeking proxy (peer mentions, answers that diverge after seeing peer) | small |
| E6 | Belief stability | C0, any task, 5 minutes | how often agents resubmit identical answer vs change across minutes | small |
| E7 | Minute-violation stress | C1, `minute_seconds=60`, gemma2:2b | how often generation exceeds a minute; stall policy keeps grid | real model min |
| E8 | Order bias probe | C1 one repeat: A-then-B, one repeat: B-then-A | sequential order effect on later agent's answer | small |
| E9 | Context growth check | C1, steps=5 | byte preflight does not silently truncate at minute 5 | small |
| E10 | Metric cross-check | Any batch above | answer-class bits vs semantic-entropy bits on same stored data | offline |

Run E1–E4 in CI (fixture). E5–E9 are the local `gemma2:2b` set. E10 is offline analysis only.

## 6. Development roadmap (ordered, additive)

1. Backend: `difficulty` in event schema + `minute`/deadline enforcement (experiment.py) + analysis
   slicing. Tests.
2. Backend: task-pool overlay + panel `report`/`tasks` endpoints (with tests).
3. Dashboard: toggle framework (view vs run-config), three-pane shared-log view, mailbox/layer diagram.
4. Dashboard: minute time bar with per-minute submission triggers + violation/stall badges live.
5. Dashboard: task-pool view, difficulty filter, researcher report download.
6. Docs: update this file with decisions as they land.

## 7. Decisions to confirm

1. Lock the minute defaults: `steps=5`, `unlock_step=3` (=3:01), `minute_seconds=60`, `deadline_seconds=300`.
2. Degenerate stalls: empty `response_text` + `submitted=true` (grid complete) vs omitting updates (today).
3. Shared-log default view: single stream (today) or three-pane on/off toggle (recommended default off).
4. Task-pool editing: read-only now with documented endpoint stub, or fully editable now.
