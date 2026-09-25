# Jev Choice replay — v5 (successor registration after the stopped v4 run)

Task: Chainlink **#197** under **#159**. Offline preparation only.
Status: registration locked; `live_collection_authorized: false`; **no live call made**.

## Why v5 exists

The authorized replay-v4 attempt (`reviewer-approved-2026-09-25-jev-replay-v4-97217b47`)
stopped with `stop_reason: provider_failure_limit` after 2 of 51 branches (real and
null of `planning-000124f8:message-B-1`), each exhausting its 3 registered physical
attempts as sanitized `transport_error` — 0 valid branches, 6 physical Jev attempts,
0 tokens, $0.00 cost. Its registered outputs are therefore occupied, and v4 policy
forbids resume, append, overwrite, pooling or reinterpretation.

#196 then ran two separately authorized availability probes and found both registered
routes reachable on the first attempt (Jev `jev-1.13.0` → `valid_response`, 420 input
tokens; OpenRouter `inclusionai/ling-3.0-flash-vl` → HTTP 200). Neither credential nor
route is currently failing. Those probes are availability evidence only and never
authorize replay.

A fresh registration with fresh output paths is required before any new live call.

## Registration

| | |
|---|---|
| Registration | `runs/epic-126/replay-v5/jev-choice-replay-preregistration-v5.json` |
| Version / status | `stage2-jev-choice-replay-v5` / `locked_for_jev_choice_replay_v5` |
| Hash | `0a81e400f598d16742301d7c07cbaf5398fa861b4fa1701c15405391ab4f6d15` |
| Journal (fresh) | `runs/epic-126/replay-v5/jev-choice-replay-v5.jsonl` |
| Report (fresh) | `runs/epic-126/replay-v5/jev-choice-replay-report-v5.json` |
| Runner | `src/apart_incident_response/jev_replay_runner_v5.py` |
| Schedule executor | `src/apart_incident_response/jev_replay_runner_v4.py` (reused, source-bound) |
| Source files | 15 bound files, `source_files_hash` recomputed |
| `live_collection_authorized` | `false` |

The registration is derived from the reviewed v4 builder and then differs **only** in
an enumerated key set (`V5_OVERRIDE_KEYS` plus two new keys). Everything else —
`events`, `branch_schedule`, `branch_design`, `forms`, `estimand`, `guards`,
`missingness`, `inference`, `sensitivity`, `limitations`, `caps`, `claim_scope`,
`execution_policy`, `provenance`, `message_wording_hash`, authorization flags — is
asserted byte-identical to v4.

## Immutable historical inputs

Pinned and re-hashed on every build and verification:

| Artifact | sha256 |
|---|---|
| `runs/epic-126/replay-v4/jev-choice-replay-preregistration-v4.json` | `5ea64f8218ed1ddabb2cab5a081dea666e686683a2a67ea9a186a9409ea40ee2` |
| `runs/epic-126/replay-v4/jev-choice-replay-v4.jsonl` (2 rows) | `5a870d5f643f3716c70b8350ab19ff256834f9079e6364931661630587b24b62` |
| `runs/epic-126/replay-v4/jev-choice-replay-report-v4.json` | `71a7f2c401bb67d5db5d0758188531361ae42cd6aedd4de92d3100c727f3a8a2` |
| v4 registration content hash | `97217b478ee84797c642944732211d563666e11f3c1bd809593da848a1946eb4` |

Build and verification fail closed if any of these drift. v5 never opens them.

## What is preserved

- **Experimental unit**: the model-visible pre-read prompt form, `k = 6`.
- **Estimand**: `Delta` = equal-weight mean over the six frozen forms of the
  within-form mean of `H_real - H_placebo`; `d_i = H_real,i - H_placebo,i`;
  `events_are_independent_units: false`.
- **Inference**: exhaustive two-sided cluster sign-flip over the six form means
  (floor `2/64 = 0.03125`) **and** the form-mean t interval with `df = 5`; both
  reported, negative direction required. Instance-level t-test / Wilcoxon prohibited.
- **Missingness**: never impute; ≥1 complete real/placebo pair per frozen form;
  five-form fallback is interval-only descriptive with sub-0.05 sign-flip forbidden
  and no causal gate; below five forms is replay-coverage failure.
- **Guards**: `delta = 0`, `epsilon = 0.01`, reported separately, never filtering
  the primary estimate.
- **Design**: 17 events × 3 branches (B→A real, controller placebo, null), frozen
  counterbalanced event-major branch schedule, distribution `1/4/4/1/4/3`.
- **Protocol**: `jev-1.13.0`, `https://api.typesafe.ai/v1/systemone`,
  `jev-choice-wire-v2`, protocol key `jev-choice-wire-v2|75190e25…`,
  normalization policy `292ac217…`, `max_retries 2`, retryable
  `408/429/500/502/503/504/529`.
- **Caps**: 51 logical Jev / 0 Ling, 153 physical (`51 × 3`), reserve 102,
  $1.00 ceiling, worst case `$0.052641792`, next-call reservation `$0.001032192`.

## Operational decisions (`operational_policy`)

| Decision | Choice | Rationale |
|---|---|---|
| Retry policy | **preserve** (`max_retries 2`, 3 physical per logical call) | the stop was a transport availability event, not evidence the retry budget was wrong; more retries would raise the physical ceiling without cause |
| Terminal-failure rule | **preserve** (stop after 2 consecutive terminal provider/transport failures) | fail-closed; weakening it trades safety for availability |
| Jev token budget | **preserve** (8192 ceiling, $0.042/Mtok) | the stopped run returned zero usage; the #196 probe used 420 input tokens |
| Bounded pacing | **change, bounded** (`model_and_protocol.backoff`: initial 0.5 s → **2.0 s**, max 5.0 s → **10.0 s**, jitter unchanged) | the v4 schedule allowed at most `0.5 + 1.0 = 1.5 s` of backoff per logical call, so the terminal rule can fire after ~3 s of registered backoff on the first event; `2.0 + 4.0 = 6.0 s` widens the window while changing no count, status, cap or fail-closed rule. Applies to retries only — no sleep on the happy path |
| Timeout | **preserve** (30 s) | the #196 probe returned promptly; no timeout evidence |
| Output lifecycle | **fresh paths, no resume/append/overwrite/path overrides** | v4 outputs are occupied by a stopped run |
| Physical + cost caps | **preserve** | design and retry-inclusive arithmetic unchanged |

Because `model_and_protocol.backoff` moved, `treatment_hash` differs from v4 — but
**only** through the runner binding fields (`runner_source_file`,
`runner_version`, and the added `runner_source_delegate`); every treatment-defining
field is identical. This is asserted in the tests.

## Runner split

`jev_replay_runner_v5.py` owns registration loading, fail-closed preflight, the
registered bounded pacing, rooted output paths and report provenance. The reviewed
`jev_replay_runner_v4.py` owns schedule execution: frozen event-major order,
counterbalanced branch schedule, the durable append-only `BranchJournal`
(append + flush + fsync per `(event_id, branch)`, duplicate keys fail closed,
opened with `"x"` so resume/append/overwrite are impossible), request/state hash
re-verification before every Jev call, and the registered stop/retry/suspect/
provider-failure rules and equal-form analysis. Both modules are source-bound by
the registration, and `adding_runner_authorizes_collection` is `false`.

Reports produced by the shared executor are stamped with
`mode: jev-choice-replay-runner-v5`, `registration_version`, and a `runner` block
recording the entrypoint and delegate.

## Fail-closed verification

`verify_against_jev_replay_preregistration_v5` (62 named checks through the runner
preflight) covers: fresh output paths; exact manifest and event order; branch
request/state hashes recomputed from the decision artifact and regenerated
instances; model/endpoint/codec/protocol/normalization pins; caps with
retry-inclusive cost reservation; source and treatment hashes; superseded-v4 pins;
no mixed protocol keys; no stale registration hash; byte-reproducible rebuild;
operational-policy completeness; and (when requested) credential presence, reported
as `present / shape_ok / source / fingerprint` — never printed.

v4 output freshness is deliberately evaluated as of v4 lock time during the frozen
content re-check, because v4 is superseded historical state whose outputs are pinned
instead; v5 carries its own freshness checks.

## Tests

`tests/test_jev_replay_preregistration_v5.py` (28) and
`tests/test_jev_replay_runner_v5.py` (20):

- superseded v4 artifacts byte-identical before and after every test;
- v5 journal/report absent until an authorized run;
- occupied new paths fail preflight and block execution;
- failed preflight and missing approval make zero provider calls;
- partial failures journaled durably (fsync per row, reread matches);
- no resume / append / overwrite possible (`open("x")`, `output_exists`);
- registration hash and content reproduce byte-for-byte;
- v4 scientific blocks byte-identical, estimand/inference/guards/missingness
  unchanged, treatment hash differs only by runner binding.

## Not run

```
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src \
  python -m apart_incident_response.jev_replay_runner_v5 \
  --live \
  --approval "<reviewer authorization reference citing 0a81e400...>"
```

Locking this registration and binding the runner are **not** execution
authorization. Live replay of v5 requires a separately supplied reviewer
authorization reference; #159 stays open until then.
