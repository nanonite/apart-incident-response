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

Follow-up (credential refreshed): the root-workspace `.env` key was rotated and
the gate re-ran on the same frozen set. The preflight probe then returned HTTP
200 for all five variants. The gate completed all 8 planned runs (16 requests,
16 physical attempts, `$0.00`, 1834 input / 701 output tokens):

- valid executions 2; successes 2; valid denominator 2; valid success rate 1.0
- model output runs 2; checker-valid runs 2
- failure reasons: `invalid_output_empty` 6
- cells: hypothesis low 0/2 valid, hypothesis medium 0/2, reference low 1/2, reference medium 1/2

Every invalid run consumed exactly `2 x max_tokens` (192 = 2 agents x 96)
completion tokens with empty content, consistent with the free reasoning model
exhausting the 96-token budget on hidden reasoning before emitting an `ANSWER:`
line. The two runs that finished below the cap both passed the checker. This is
a reasoning-budget/task-harness floor effect, not a provider failure, and the
valid denominator is too small to interpret FULL success. No paired ISO/FULL/COMM
screen or T3 entropy work was launched. Next bounded step: re-run the same
FULL gate with a larger per-agent token budget before any paired spend.

Budget follow-up (`--max-tokens 512`, separate artifacts): re-ran the same frozen
set to separate the budget floor from a model floor. Result: valid executions 6,
successes 6, valid denominator 6, valid success rate 1.0, checker-valid runs 6,
`invalid_output_empty` 2. The two remaining empties are both hypothesis medium
(seeds 15002/15003) and each consumed exactly `2 x 512 = 1024` completion tokens,
so that cell still truncates at 512. No provider failures, no HTTP 429, `$0.00`.
Raising the budget converted every previously-empty run except hypothesis medium.
Artifacts: `runs/epic-126/full-gate-budget512.jsonl`,
`full-gate-budget512-report.json`, `full-gate-budget512-diagnostic.json`. The gate
now has valid model outputs, independent checker results and a nonzero comparable
denominator, satisfying the mechanical prerequisite for a paired screen; the
paired ISO/FULL/COMM and T3 work remain unlaunched pending an explicit go.

Consolidated 1024 gate (all 8 frozen instances, one run, `--max-tokens 1024`):
valid executions 8, successes 8, valid denominator 8, valid run rate 1.0,
checker-valid runs 8, model output runs 8, failures 0, 16 requests, `$0.00`, no
HTTP 429. Artifacts: `runs/epic-126/full-gate-1024.jsonl`,
`full-gate-1024-report.json`, `full-gate-1024-diagnostic.json`.

Caveat: the FULL agent view currently includes `joint_candidate_labels`, which
for these measured regime-N instances is the single-element joint feasible set
containing the target (`joint_clues` are the constraints). A format-following
finalizer can therefore echo the joint set. The 8/8 result validates provider
execution, output parsing and the checker and bounds the FULL condition at
ceiling, but it is not by itself a discriminating reasoning signal. A paired
screen is only informative if ISO/COMM are measurably harder, or the FULL view
should expose `joint_clues` without `joint_candidate_labels` to make FULL a
genuine reasoning gate. Paired ISO/FULL/COMM and T3 remain unlaunched.

Paired ISO/FULL/COMM screen (8 frozen instances, `turns=2`, `--max-tokens 1024`,
96 requests, `$0.00`, no HTTP 429): 24 condition-runs, 22 valid, 2
`invalid_output_empty` (both hypothesis medium), 11 successes and 11
valid wrong answers.

- ISO: 8 valid, 2 successes (0.25)
- FULL: 7 valid, 7 successes (1.00), at ceiling
- COMM: 7 valid, 2 successes (0.286); 11 messages / 11 transmitted bits, 0
  post-read-success events

Per-cell `C_need` (FULL-ISO) with valid denominators: hypothesis low 1.0 (2/2/2),
hypothesis medium 0.5 (2/1/1), reference low 0.5 (2/2/2), reference medium 1.0
(2/2/2). Artifacts: `runs/epic-126/paired-screen.jsonl`,
`paired-screen-report.json`, `paired-screen-diagnostic.json`.

Interpretation caveats: FULL is at ceiling because its agent view passes
`joint_candidate_labels`, which for these regime-N instances is the
single-element joint set; COMM is statistically indistinguishable from ISO at
this n and produced no verified post-read use (`post_read_success_count` 0); the
2 invalid outputs are hypothesis medium at the 1024-token cap. This is a
small-n screening result, not a powered estimate. No T3 entropy work was
launched. Next: either drop `joint_candidate_labels` from the FULL view to make
FULL a genuine gate, or enlarge n per cell before interpreting `C_need`.

Extended paired screen, 5 seeds per cell (20 independent instances, same
protocol; artifacts `runs/epic-126/paired-screen-n5.*`): 60 condition-runs, 59
valid, 1 `invalid_output_empty`, 27 successes, 32 valid wrong answers, 240
requests, `$0.00`, no HTTP 429.

- ISO: 20 valid, 4 successes (0.20)
- FULL: 20 valid, 19 successes (0.95)
- COMM: 19 valid, 4 successes (0.211); 33 messages / 33 transmitted bits, 1
  post-read-success event

Per-cell `p_success` (ISO/FULL/COMM) with valid denominators and `C_need`:

- hypothesis low 0.40/1.00/0.25, `C_need` 0.60 (denominators 5/5/4)
- hypothesis medium 0.20/0.80/0.40, `C_need` 0.60 (5/5/5)
- reference low 0.20/1.00/0.20, `C_need` 0.80 (5/5/5)
- reference medium 0.00/1.00/0.00, `C_need` 1.00 (5/5/5)

At this n, COMM is statistically indistinguishable from ISO (0.211 vs 0.20) and
produced only 1 verified post-read success in 19 valid runs, so communication
did not recover FULL-level performance. FULL remains near ceiling (0.95) and
`C_need` is still inflated by `joint_candidate_labels` exposure. Next: run a
preregistered leak-free FULL view (`joint_clues` without the joint candidate
set) and compare.

Leak-free FULL comparison, 5 seeds per cell (`--full-view joint-clues`;
artifacts `runs/epic-126/paired-screen-n5-leakfree.*`): 60 condition-runs, 57
valid, 3 `invalid_output_empty`, 23 successes, 34 valid wrong answers, 240
requests, `$0.00`, no HTTP 429.

- ISO: 20 valid, 4 successes (0.200)
- FULL: 19 valid, 15 successes (0.789)
- COMM: 18 valid, 4 successes (0.222); 39 messages, 0 post-read-success events

Per-cell `p_success` (ISO/FULL/COMM) and `C_need`:

- hypothesis low 0.40/1.00/0.40, `C_need` 0.60 (denominators 5/5/5)
- hypothesis medium 0.20/1.00/0.333, `C_need` 0.80 (5/4/3)
- reference low 0.20/0.60/0.20, `C_need` 0.40 (5/5/5)
- reference medium 0.00/0.60/0.00, `C_need` 0.60 (5/5/5)

Removing the joint candidate set lowered FULL from 0.95 to 0.79 overall (the
reference family fell from 1.00 to 0.60), confirming the joint-set exposure
inflated `C_need`. COMM stayed at ISO level in both variants (0.222 vs 0.200
leak-free) with zero verified post-read use, so communication still did not
recover FULL performance. n=5 per cell remains a screening result, not a powered
estimate. No T3 entropy work was launched.

Leak-free default adopted: `BehavioralProviderConfig.include_joint_candidate_labels`
now defaults to `False` and `--full-view` defaults to `joint-clues`, so the
standard FULL treatment no longer exposes the joint candidate set. The leaky
`joint-set` view remains available via `--full-view joint-set` for comparison.

C_need scaling (n=9 per cell, leak-free ISO/FULL only, `turns=1`, 36 instances,
144 requests, `$0.00`, quota-limited; artifacts `runs/epic-126/cneed-n9.*`): 72
runs, 70 valid, 2 `invalid_output_empty`, 29 successes, 41 valid wrong answers.

- ISO: 36/36 valid, 7 successes (0.194)
- FULL: 34/36 valid, 22 successes (0.647)
- `C_need` per cell: hypothesis low 0.667 (denominators 9/9), hypothesis medium
  0.667 (9/7), reference low 0.111 (9/9), reference medium 0.444 (9/9)

This is the current best `C_need` estimate: FULL 0.647 overall, near the ~0.6
screening heuristic, with reference-low showing almost no joint-information
benefit over private clues (0.333 vs 0.222). The 2 invalid outputs are
hypothesis-medium FULL at the 1024-token cap. Free-model quota at end of run:
986/1000 used, 14 remaining; resets 00:00 UTC.

Test environment note: the numpy import error (the manylinux wheel needs
`libstdc++`/`libz`, absent from the NixOS loader path) is resolved by setting
`LD_LIBRARY_PATH=/run/current-system/sw/share/nix-ld/lib`. With it the suite
runs 291 tests with only the three bubblewrap tests erroring (`bwrap` is not
installed) and four skips.

C_need scaled to n=20 per cell (leak-free ISO/FULL, `turns=1`; artifacts
`runs/epic-126/cneed-n20.*`): 80 instances, 160 runs, 153 valid, 7
`invalid_output_empty` (all FULL at the 1024-token cap), 65 successes, 88 valid
wrong answers, 320 requests, `$0.00`, no HTTP 429.

- ISO: 80/80 valid, success 0.212
- FULL: 73/80 valid, success 0.658

Per-cell `C_need` (FULL-ISO) with 95% normal-approximation CI:

- hypothesis low 0.597 [0.365, 0.829] (denominators 20/19)
- hypothesis medium 0.650 [0.441, 0.859] (20/16)
- reference low 0.300 [0.032, 0.568] (20/20)
- reference medium 0.278 [0.071, 0.485] (20/18)
- overall `C_need` 0.445 [0.304, 0.586] (80/73)

The n=9 reference-low `C_need` (0.111) was noise; at n=20 it is 0.300. The two
hypothesis cells carry the largest joint-information need (~0.6), while the
reference cells are lower. The seven truncated FULL runs are all
hypothesis-medium, so its FULL denominator is 16/20. The COMM arm was not
re-run at n=20; the COMM ~= ISO null stands from the n=5 screen. No T3 entropy
work was launched.

COMM arm at n=20 (COMM-only, `turns=2`, same 80 instances as `cneed-n20`;
artifacts `runs/epic-126/comm-n20.*`): 80 runs, 78 valid, 2
`invalid_output_empty`, 28 successes, 320 requests, `$0.00`, no HTTP 429.

- COMM success 0.359 (vs ISO 0.212 and FULL 0.658 on the same instances)
- 129 messages / 129 transmitted bits; 8 verified post-read successes in 78
  valid runs (0.103)
- `COMM-ISO` difference 0.146, 95% CI [0.007, 0.286]
- `eta_comm = (p_COMM-p_ISO)/(p_FULL-p_ISO)`: hypothesis low 0.21, hypothesis
  medium 0.35, reference low 0.33, reference medium 0.54; **overall 0.33**

This supersedes the n=5 COMM ~= ISO null: at n=20 communication does recover
roughly one third of the FULL-ISO gap, though verified post-read use remains
low (8/78). Caveat: the COMM condition used `turns=2` while ISO/FULL used
`turns=1`, because the finalizer needs at least one turn to read a peer message.
No T3 entropy work was launched.

Paired inference (Wilson + McNemar) is now built in (`paired_contrasts`); the
n=20 analysis (`runs/epic-126/paired-analysis-n20.json`) gives:

- ISO -> FULL: n=73, 0 left-only / 34 right-only, `C_need` 0.466, Newcombe 95%
  CI [0.341, 0.566], McNemar exact p=1.2e-10
- ISO -> COMM: n=78, 2 left-only / 13 right-only, difference 0.141, Newcombe
  95% CI [0.048, 0.233], McNemar exact p=0.0074 (mid-p 0.0042)
- FULL -> COMM: n=71, difference -0.310, Newcombe 95% CI [-0.419, -0.183],
  McNemar exact p=1.1e-05

So communication recovers about a third of the FULL-ISO gap and remains
significantly below FULL.

Four-family C_need screen (planning, poetry, legal, lexicon; leak-free
ISO/FULL, `turns=1`, n=9/cell; artifacts
`runs/epic-126/cneed-fourfamilies-n9.*`): 72 instances, 144 runs, 143 valid, 1
`invalid_output_empty`, 51 successes, 288 requests, `$0.00`, no HTTP 429.

Per-cell ISO/FULL/`C_need` with Newcombe 95% CI and McNemar exact p:

- planning low 0.333/1.000/0.667 [0.234, 0.879] p=0.031
- planning medium 0.333/1.000/0.667 [0.234, 0.879] p=0.031
- lexicon medium 0.222/0.875/0.653 [0.196, 0.810] p=0.063
- poetry low 0.111/0.444/0.333 [0.010, 0.600] p=0.250
- lexicon low 0.333/0.556/0.222 [-0.266, 0.603] p=0.688
- legal medium 0.222/0.333/0.111 [-0.104, 0.330] p=1.000
- legal low 0.000/0.000/0.000 [-0.299, 0.299] p=1.000
- poetry medium 0.000/0.000/0.000 [-0.299, 0.299] p=1.000

Overall across the four new families: ISO 0.197, FULL 0.521, `C_need` 0.324,
Newcombe [0.196, 0.436], McNemar p=5.7e-06. The strongest new family is
**planning** (0.667 at both complexities, p=0.031); lexicon-medium is marginal
(0.653, p=0.063). legal and poetry show task/scorer **floor** effects (FULL 0.000
even with all constraints), so `C_need` is not measurable there. Combined with
hypothesis (n=20 `C_need` 0.60-0.65), the leading focus families for the
cross-model transfer stage (#152) are **planning and hypothesis**. No T3 entropy
work was launched.

Planning COMM arm (n=9/cell, `turns=2`, COMM-only, 72 requests, `$0.00`;
artifacts `runs/epic-126/comm-planning-n9.*`): 18 runs, 17 valid, 1
`invalid_output_empty`, 6 successes (0.353), 20 messages / 15 transmitted bits,
2/17 verified post-read. Combined with the planning ISO/FULL screen (18
instances): ISO 0.333, FULL 1.000, COMM 0.353.

- paired ISO -> COMM difference 0.000 (6 left-only / 6 right-only discordant),
  Newcombe [-0.215, 0.215], McNemar p=1.0
- paired FULL -> COMM difference -0.647 [-0.827, -0.349], McNemar p=9.8e-04
- `eta_comm` ~= 0.0 (planning), versus ~0.33 for hypothesis/reference

So planning has the **largest** `C_need` (0.667) but communication recovered
essentially none of it, unlike the two calibration families where COMM recovered
about a third. That is precisely the family difference the battery is meant to
detect. Caveat: n=17 for the paired ISO/COMM contrast, whose CI includes 0, so
this is a screening signal, not a confirmed family difference. Free-model quota
exhausted for the UTC day (995/1000). No T3 entropy work was launched.

Protocol repair (private-clue coverage and pooled oracle). The generated private
clues did not cover the joint clues: the decisive constraint was held by neither
agent, so COMM could not in principle reconstruct FULL, and `eta_comm` was
bounded by a generator artifact rather than by communication. Two generator bugs
were fixed in `task_families.py`:

- private clues now **partition** the claim list between A and B (even/odd
  indices), so the union of both agents' clues equals the joint clues for every
  family and complexity. Verified 0 coverage gaps across all six families x
  low/medium/high x multiple seeds; A and B both carry genuine complementary
  information (`channel_analysis().both_agents_needed` true).
- hypothesis medium/high no longer append a hard-coded `derived parity=0` /
  `chained checksum=0` claim that could contradict the target; the claim is now
  derived from the target value.

Added `FamilyInstance.channel_analysis()` (private sizes, pooled vs joint,
`covers_joint`, `both_agents_needed`) and a **pooled-private oracle** probe
(`--mode oracle`, `run_oracle_probe`) that gives the finalizer the union of both
agents' clues with no board, bounding the COMM channel and separating
information availability from message exchange. With complete coverage the
pooled oracle and leak-free FULL carry the same information; `eta_comm` stays
FULL-ISO based.

Consequence: all prior ISO/FULL/COMM artifacts were produced under the
under-covered protocol and are **superseded**. The cross-model transfer stage
(#152) must not use them. A re-run of the n=20 paired screen and the four-family
screen with the repaired generator is pending the free-model quota reset
(995/1000 used for the UTC day); next reset 00:00 UTC.

## T3/T4

T3 was not run because T1 selected no useful cells and T2 found no aligned
entropy-eligible output kind. No full six-family battery or substantial spend
was launched. The next gate requires a provider/output-kind combination with
aligned target-token coverage, followed by explicit preregistration and budget
approval.
