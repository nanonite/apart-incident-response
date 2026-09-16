# Epic 126 Validation Handoff

Base: local `811aad4` in worktree `epic-126-validation`.

## T0

T0/#127/#133 were already closed at the base commit. The worktree preserves
the reconciled `.chainlink/issues.db` and unrelated artifacts.

## T1 Gate

The retained Ling artifact tree was identified as the legacy Task 1 C0/C1/C2
experiment, not the six-family ISO/FULL/COMM pilot. The six-family pilot was
not located in retained artifacts and is therefore behaviorally **unknown**.
The separately labeled legacy audit found 18/18 execution-invalid runs:
all run indexes were failed, submitted agents were zero, validator outcomes
were empty, and agent statuses were predominantly `budget_exhausted`.
The raw evidence was not rewritten. Salvage decision: no salvage.

A new logprob-free adapter was implemented and a corrected smoke screen ran on
hypothesis elimination and reference games:

- 24 independent matched instances
- 12 measured design cells
- 72 ISO/FULL/COMM condition-runs
- 144 maximum agent requests
- model `inclusionai/ling-3.0-flash-vl:free`
- endpoint `https://openrouter.ai/api/v1/chat/completions`
- minimum interval 0.25 seconds
- hard cost cap `$20`; observed cost `$0.00`
- 48 valid and 24 invalid condition-runs
- 0 verified useful-communication events

The screen is mechanics/discovery evidence only. No cell was selected for
entropy; no rigid R/H/N monotonicity claim was made.

Artifacts:

- `runs/epic-126/t1-retained-pilot-audit.json`
- `runs/epic-126/t1-screen-retry.jsonl`
- `runs/epic-126/t1-screen-retry-report.json`
- `runs/epic-126/t1-pressure-catalog.json`

## T2 Gate

Three pinned requests were made against the same free Ling model, one per
output kind. The capability report separates record presence, visible-span
alignment, top-K mass, and full-logit availability:

- Ordinary text: records present, top-K mass approximately 1, visible alignment mismatch, no full logits
- Tool-call arguments: zero logprob records, tool call present
- Reasoning-bearing text: zero logprob records, provider stopped at length

No output kind passed aligned entropy eligibility. Top-K mass was not used as a
coverage substitute. T3 is therefore blocked.

Artifact: `runs/epic-126/t2-capability-report.json`.

## T1a FULL-only execution gate (#147)

The FULL-only gate was repaired to classify provider HTTP failures, retry only
on 408/429/5xx, keep credentials out of payloads and artifacts, disable
logprobs, and record per-run request/rate/token/usage/cost/model/provider
provenance plus an invalid-output versus valid-wrong-answer distinction.

Gate command (bounded to 8 FULL runs / 16 agent requests, 0.25 s rate floor,
`$20` cost ceiling, stop on repeated HTTP failure, request/cost cap, or missing
checker evidence):

    UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src \
      python -m apart_incident_response.behavioral_discovery --live --max-runs 8

Artifacts:

- `runs/epic-126/full-gate-repair.jsonl`
- `runs/epic-126/full-gate-repair-report.json`
- `runs/epic-126/full-gate-repair-diagnostic.json`
- `runs/epic-126/full-gate-repair-preflight.json`

Observed result (2026-09-15): the preflight probe returned HTTP 401
"API key expired." for all five payload variants (with and without provider
routing parameters, seed, and temperature), so the pinned endpoint and model
never reached model execution. The gate attempted 2 of 8 frozen runs
(4 requests, `$0.00`) against the frozen instance set and stopped on
`repeated_http_failure`; 0 valid model outputs, 0 checker-valid outputs, 0
successes, valid denominator 0. The blocker is the expired provider credential
configured in the project `.env`, not a task/scorer/model floor. No paired
ISO/FULL/COMM screen was launched and no solvability conclusion is permitted
until a valid credential is restored and the gate produces valid outputs with
independent checker evidence.

## T3/T4

T3 was not run because T1 selected no useful cells and T2 found no aligned
entropy-eligible output kind. No full six-family battery or substantial spend
was launched. The next gate requires a provider/output-kind combination with
aligned target-token coverage, followed by explicit preregistration and budget
approval.
