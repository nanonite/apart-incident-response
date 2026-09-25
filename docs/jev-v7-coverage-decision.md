# V7 coverage decision memo (#192)

Status: offline decision complete; artifact
`runs/epic-126/decisions/jev-v7-coverage-decision.json` (version
`jev-v7-coverage-decision-v1`, byte-reproducible, hash-bound to the
committed v7 journal/report/registration, the #189 audit + selector source,
and the generator source). The artifact lives in the `decisions/`
subdirectory because the registrations' prior-ID scan globs over
`runs/epic-126/*.json` are non-recursive — keeping it out of the top level
preserves the committed registrations' rebuild evidence. **Zero provider calls; no replay, rerun, or
resume of v7; no #193/#159 work; no frozen artifact modified.** Source:
`src/apart_incident_response/jev_v7_coverage_decision.py`; tests:
`tests/test_jev_v7_coverage_decision.py`.

## Verified inputs (fail-closed)

Live-result commit `1782324`; clean tracked worktree; registration content
hash `f7f7d574…` (file sha `289d83fe…`); v7 journal 32 rows (sha
`23ab961c…`); report status `stopped`, stop_reason `empty_output`,
planned/attempted `36/32`, receiver valid/invalid/unattempted `31/0/1`
(sha `45651555…`); #189 audit (`73751bed…`), selector source
(`d97918ce…`), generator (`b399bb15…`); all historical v1–v6 pins and the
routing probe (`06d22e87…`) byte-identical. Any mismatch aborts the analysis.

## Writer validity ≠ correctness

Writer-valid means a **protocol-classifiable** outcome: `deliberate_silence`,
an accepted owned `message_candidate`, or a `non_owned_claim` explicitly
rejected and recorded. Writer-invalid: `empty_output`, `truncated_output`,
`unparsed_output`, `invalid_answer`, `writer_error`.

Denominators: **125 writer calls = 124 valid + 1 invalid**. The invalid call
(case `planning-0001251d`, A turn 0) is **writer-invalid missing data caused
by output-budget exhaustion** — empty visible content, `finish_reason=length`,
`output_tokens=1024`, no error class, receiver unattempted. It is **not**
deliberate silence, not lack of communication, not an API-key failure, and
not an OpenRouter transport failure, and it is never counted as silence
(silence = 100 separate calls).

## Denominators

| Quantity | Count |
|---|---|
| Planned instances | 36 |
| Attempted instances | 32 |
| Unattempted instances | 4 (`1251e`, `12522`, `12524`, `12530`) |
| Receiver valid / invalid / unattempted | 31 / 0 / 1 |
| Writer-valid / writer-invalid calls | 124 / 1 |
| Eligible replay events / claims | 17 / 17 |
| Distinct covered forms | 6 |
| Rows with accepted B message but no eligible event | 0 |

Missingness by form (planned 6 each): `0a3349…` 6 attempted / 6 valid /
1 event · `1c1d9f…` 6/6/4 · `2954f5…` 6 attempted, 5 valid, 1 receiver-
unattempted (the writer-invalid case) / 4 events · `3196a8…` 4 attempted
(2 never attempted), 4 valid / 1 event · `55968f…` 6/6/4 · `ce847a…`
4 attempted (2 never attempted), 4 valid / 3 events.

## The two decisions

1. **Collection completeness: FAILED.** Fixed N=36 was not completed
   (stopped at case 32 under a registered terminal rule). The v7 block is a
   **registered partial run** and cannot be described as a completed
   fixed-N sample.
2. **Coverage / replay readiness: SIX-FORM COVERAGE OBSERVED; conditional
   replay gate RELEASED.** All six frozen prompt forms have ≥1 valid,
   authoritative B→A replay event after #189-selector recomputation over
   every row (17 events, per-form 1/4/4/1/4/3). Frozen statement:
   *"Six-form replay coverage passed within a registered partial run;
   fixed-N collection completeness failed."* The release is on the coverage
   dimension only (#193 may amend/lock the #159 plan); it does not erase the
   incomplete-collection gate, and no replay inference has been run.

## Information accounting (never "unique delivered")

| View | Records | Bits |
|---|---|---|
| Gross transmitted, all accepted messages | 24 | 38.0391000173 |
| Gross B→A | 19 | 30.1142875137 |
| Gross A→B | 5 | 7.9248125036 |
| Replay-eligible event-claims (deduplicated) | 17 | 26.9443625123 |
| Distinct form/claim treatments | 6 | 9.5097750043 |

The primary replay set is verified **B→A only**. Gross totals include A→B
messages and within-event repeats and are never unique information
delivered to Jev A.

## Experimental unit and claim limits

Unit = **prompt form**; **k = 6** (covered forms, not events); the 17
events are replicates of one model-visible pre-read state + claim treatment
per form, not 17 independent states. Prohibited and **not performed**:
instance-level t-test, Wilcoxon, any independence-assuming analysis,
real/placebo/null replay inference, and any causal-uptake effect. Paid-route
findings remain conditional on the paid Ling SKU (not poolable with
free-route behavioral rates).

## Next

Gate release unblocks **#193** (amend and lock the #159 matched replay
plan). **#159 remains blocked** pending #193; replay collection and analysis
are out of scope here.
