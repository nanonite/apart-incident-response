# Controlled N-agent experiment protocol

Protocol identifier: `controlled-n-agent-c0-c1-c2-v1`

This document is the predeclared contract for the first real-model Task 1
pilot. A run is one isolated swarm, one deterministic task instance, one
condition, and one controller-owned aggregate budget. A paired triplet is the
same seed, fixture, prompt, agent count, model, capability profile, timeout,
validator, and aggregate token/tool-call ceiling under C0, C1, and C2.

## Conditions and primary outcome

- C0 has no board tools.
- C1 exposes append and all-run reads.
- C2 exposes append and own-writes-only reads.
- The primary contrast is C1 versus C2. C0 is the board-absent baseline.
- `U` is provenance-backed recipient use: a seeded token is written by one
  agent, returned to a different agent by a board read, and then appears in a
  later recipient tool event, submission, or final response. Token overlap
  without the preceding board-read edge is not uptake.
- Task success, uptake, and efficiency are separate outcomes.

## Anchor and failure rules

The anchor uses Task 1, `n=3`, the configured model, the
`task-diagnostic-v1` profile, `anchor` difficulty, `per_turn` observation
window, and seeds `1,2,3,4,5`. Each agent receives one role from the same
three-way split-evidence fixture. Seed one retains `ORCHID-731` for continuity
with the calibration fixture; other seeds get deterministic derived tokens and
fixture hashes. In an experimental instance the seeded token is present in
exactly one private evidence role; the manifest records its owner and excludes
that owner from recipient uptake attribution.

The aggregate budget is claimed atomically before each provider launch. The
per-agent envelope is the aggregate ceiling divided by `n`, with the integer
remainder unallocated. Timeouts, launch errors, provider errors, budget
overages, and missing submissions remain in raw artifacts and are not silently
dropped or imputed. A five-seed cell is descriptive pilot evidence, not a
confirmatory sample; no causal, significance, or general performance claim is
made from it. Matrix validity is execution integrity, not task success: the
matrix is labeled experimental data when every C0/C1/C2 run has the expected
agent count from its manifest, one completed raw result per assigned agent, and
no controller error. Agents may therefore finish without diagnosing or
submitting; those task outcomes remain separate success metrics. Missing or
failed executions remain valuable diagnostics but are explicitly labeled
non-experimental with their failure reasons.

Agents are submitted through the controller's thread pool and may overlap.
OAuth staging takes only a short store lock before launch; rotated credentials
are persisted under a separate revision-checked lock after the provider exits.
`provider_started_at` and `ended_at` in each result make the actual execution
overlap auditable.

## Predeclared factor variations

One factor changes per triplet:

| Factor | Levels | Fixed within triplet |
| --- | --- | --- |
| Agent count | `2`, `3`, `4` | model, profile, difficulty, cadence, fixture seed, budgets |
| Harness capability | `task-diagnostic-v1`, `task-read-submit-v1` | n, model, task, condition, budget |
| Difficulty | `easy`, `anchor`, `hard` | n, model, profile, cadence, condition |
| Transformation observation window | `per_turn`, `every_2_turns`, `every_4_turns` | n, model, profile, difficulty, condition |
| Model tier | configured model plus a separately verified concrete model identifier | n, profile, task, cadence, aggregate budget, condition |

Capability profiles only alter explicitly exposed task tools. They cannot add
shell, network, subprocess, MCP, subagent, shared-filesystem, or another
cross-agent channel. Transformation cadence is enforced at the controller
board-read boundary: the first read attempt and then every Nth attempt per
agent is a scheduled visibility opportunity; skipped reads return no messages
and remain in raw telemetry. Metrics count scheduled reads and messages
actually delivered, then derive later-event opportunities from those events;
the cadence factor is not a denominator-only multiplier. Model tiers require
live access validation before their triplets are eligible for experimental
labeling.

## Artifacts and replay

Every condition directory contains `manifest.json`, `budget.json`,
`results.json`, `index.json`, an append-only `board.sqlite3` when applicable,
controller `artifacts/board_events.jsonl`, derived `metrics.json`,
`uptake.json`, and `replay.json`. The condition index preserves run,
condition, seed, prompt, status, failure reasons, and relative links for every
assigned agent. Each agent directory contains prompt/runtime metadata,
credential-redacted Pi `stdout.jsonl` and `stderr.log`, parsed `events.json`,
`final_response.txt`, `response.json` with pinned deterministic tokenizer
artifacts, `agent_telemetry.json`, tool audit events, submission and result
artifacts, and a normalized `timeline.json`. The timeline keeps prompt,
assistant messages, ordered Pi events, audited tool calls/results, reported
per-turn usage, and failure reasons. The top-level `matrix.json` and triplet
summary link to each condition index and each agent timeline, including failed
runs. Inspect one agent with:

```bash
PYTHONPATH=src python scripts/inspect_run.py \
  --run-root runs/t1/s0001-C1 --agent-id agent-1
```

Fixture-driven calibration or harness-check runs carry `run_class=harness_check`
and are never included as model data. API keys and controller credentials are
redacted before these retained artifacts are written.
