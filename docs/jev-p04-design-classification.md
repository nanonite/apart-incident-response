# P04 — Classify design and plan discovery

Task: Chainlink **#205** under **#201** under **#159**. Offline planning
only — no provider call, no collection, no registration lock, no live run.
Protocol: [hypotheses and sequential discovery/confirmation plan](jev-discovery-confirmation-plan.md).
Family: `hypothesis:low` (the next-family pilot frozen in P02, audited in
P03). This task closes with evidence only; nothing here authorizes
collection, registration locking, or any successor execution.

Machine-readable registration:
[`runs/next-phase/jev-p04-discovery-registration-v1.json`](runs/next-phase/jev-p04-discovery-registration-v1.json)
with self-recorded `registration_hash`
**`6fa6149770b620cd3a026a6415f8e4d97e800e8af5237794de7b29fca6dacfac`**.
The record lives outside `runs/epic-126/` so the frozen #200 audit's
byte-reproducibility (which scans `runs/epic-126/**`) is preserved.

Frozen input pins (recomputed from disk at build time; fail closed on drift):
#200 audit `audit_content_hash`
**`5242e9cfa35e3a77c54045475428dd617cf93cb16d464b55ad679adc35f80a83`**,
#200 draft registration `preregistration_hash`
**`ff186a066e6af093ecc383e668d948bdca7c1ef8f84b5752b88db47960a6ec6d`**,
P02 scope freeze `content_hash`
**`4cf5556c8e9c0811653e4b4d726a7b437d43bd63134cad0f80b84eb9148ec59b`**,
P03 census `content_hash`
**`ee0ba3a1714828b3e39834280a0a2eb7850f1cc0526463eb59d3bc4b7026fe14`**.

## 1. k and attainable p floor

The P03 census closed the `hypothesis` prompt-form space at **k = 4**
distinct forms (proven by exhaustive enumeration of the finite generator
state space: the form is a function of `(bit0, bit2)` of the target, which
has four values, all realized). The attainable exact two-sided sign-flip
floor is `2/2^k = 2/2⁴ = ` **0.125 > 0.05**, so **no dichotomous rejection
at α = 0.05 is attainable at any effect size on this family**. Ties and zero
effects can only make the floor worse.

## 2. Pilot versus potentially confirmatory classification

The design is classified as a **pilot** (descriptive/estimation only), not
potentially confirmatory:

| k | Attainable two-sided sign-flip floor | Classification at unadjusted α = .05 |
|---|---|---|
| 4 | 0.125 | **Pilot** (descriptive/estimation only) |
| 5 | 0.0625 | Descriptive/estimation only |
| 6 | 0.03125 | Potentially confirmatory, subject to all other gates |
| 7 | 0.015625 | Potentially confirmatory, subject to all other gates |

A potentially confirmatory design needs **k ≥ 6** (floor ≤ 0.05); six forms
are necessary, not sufficient for adequate power or multiplicity-adjusted
rejection. With k = 4 the floor 0.125 > 0.05 makes the test non-confirmatory
regardless. **`hypothesis` remains descriptive, including for its fresh-seed
replication block** — a fresh-seed replication cannot become confirmatory on
this family.

The scientific contract is unchanged: H0: Delta = 0; H1: Delta < 0; Delta is
the equal-weight form mean of real-minus-placebo entropy. The operational
test remains the original two-sided exact cluster sign-flip plus a
negative-direction requirement. Guards never filter the estimate; all forms
and missingness are reported without imputation. No planning-low effect-size
prior is used anywhere. Distinct seed ids are not independent forms; the
experimental unit is the prompt form.

## 3. Discovery registration (draft, offline)

The discovery registration freezes the discovery-stage design (P05–P07) for
the `hypothesis` family. It is a **draft** (`draft_pending_review`);
locking is not execution approval, and a separate explicit live authorization
reference is required before any provider call. The registration resolves
the two #200 wording defects logged in P01 §5: the **six-form** confirmatory
minimum (not five) and the **interval half-width** labeling (not a
power-based MDE).

### 3.1 Fixed N

- **Window**: discovery 85000–85511 (512 seeds) — the #200 `primary` block,
  relabeled `discovery` in the P02 scope freeze.
- **Selection rule**: first `INSTANCES_PER_FORM = 4` seeds per form in
  ascending seed order within the window; **fixed N = 16** (4 per form × 4
  forms); **no outcome-based stopping**.
- The manifest is rebuilt from the generator and matches the #200 audit
  `primary` block exactly (same window, same selection rule). The 16
  instance ids are disjoint from the prior-instance-id set (8945 ids, sha256
  `429e8c54…`) and from the held-out window.

### 3.2 Treatment and route

- **Treatment**: original L4X communication treatment — family `hypothesis`,
  complexity `low`, regime `N`, agents A/B, 2 turns, one-way B→A, final
  receiver A via Jev Choice wire v2, exposure id `jev-finalizer`. The writer
  prompt is the frozen v6/v7 registered spec (`treatment-prompt-v2`); the
  grammar is `ANSWER: <label> + optional MESSAGE: <claim>` (answer-only =
  silence).
- **Writer transport**: Ling writer transport v3
  (`ling-writer-openrouter-pacing-v3`), model `inclusionai/ling-3.0-flash-vl`
  on the paid OpenRouter SKU, temperature 0.0, token budget 1024, pacing
  3.25 s, max_retries 2.
- **Jev receiver**: `jev-1.13.0`, systemone endpoint, codec
  `jev-choice-wire-v2`, protocol key `jev-choice-wire-v2|75190e25…`,
  normalization policy `292ac217…` (normalize every accepted vector), hard
  normalization ceiling 0.05.

### 3.3 Budgets

One discovery block (16 instances): discovery collection then optional
exploratory replay. Every bound is retry inclusive (×3 physical per logical
call). Cost model: Ling `(8192×0.06 + 1024×0.18)/1e6 = 0.00067584`/call;
Jev `8192×0.042/1e6 = 0.000344064`/call; next-call reserve = 3 × worst call.

| Stage | Planned | Physical | Cost ceiling | Worst case |
|---|---|---|---|---|
| Discovery collection | 64 Ling + 16 Jev | 192 Ling + 48 Jev | ≤ $0.20 | $0.146276352 |
| Exploratory replay | ≤ 48 Jev (≤16 events × 3 branches) | 144 Jev | ≤ $0.10 | $0.049545216 |
| **Program** | 64 Ling + 64 Jev | 192 Ling + 192 Jev | ≤ **$0.30** | **$0.195821568** |

### 3.4 Terminal stops

Request or cost cap before the next call; model drift; protocol-key drift;
request/state/option identity drift; malformed, non-finite, negative or
option-mismatched vector; hard normalization deviation above 0.05; argmax
shift after normalization; output collision; registration, source, treatment
or geometry hash drift; writer terminal errors; two consecutive terminal
provider failures.

### 3.5 Paths

Reserved live output paths (proposed, currently absent):

- `runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection.jsonl`
- `runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection-report.json`
- `runs/next-phase/hypothesis/jev-discovery-v1/jev-exploratory-replay.jsonl`
- `runs/next-phase/hypothesis/jev-discovery-v1/jev-exploratory-replay-report.json`

Output lifecycle: fresh paths, **no resume, no append, no overwrite, no path
overrides**; a stopped run requires a new registration and a new review. The
reserved paths live under `runs/next-phase/`, not `runs/epic-126/next-phase/`,
because the frozen #200 scan (`runs/epic-126/**/*.json[l]`) picks up instance
ids from any file under `runs/epic-126/` and would break the frozen
prior-instance-id pin once a live journal exists; this matches the P02/P03
precedent.

### 3.6 Coverage rules

- **Permissible within-form missingness**: up to 3 of 4 seeds per form may be
  missing; at least 1 complete instance per form is required.
- **Complete-case scope**: the set of planned instances with all required
  fields (structural need, emission/silence, ownership, board write/read
  exposure, information), reported by stage, form, and branch with reasons.
- **Missing entire form**: blocks confirmation of the registered full-form
  estimand; label any available-form estimate descriptive.
- **No imputation, no seed replacement, no form removal after outcomes.**
- **Selection risk**: if within-form missingness is not random, the
  complete-case estimate may be biased; the registration freezes the
  permissible missingness before collection and reports the resulting
  complete-case scope and selection risk.
- **Discovery screen requirements**: every registered form must have at least
  one instance with structural need, voluntary emission or recorded silence,
  verified B ownership, and an accepted board write followed by A read
  exposure.
- **Exploratory replay requirements**: every registered form must have at
  least one complete real/placebo pair; a missing entire form blocks the
  full-form estimand.

### 3.7 Exploratory replay (optional)

The registration covers an optional exploratory replay on the discovery
block, **separately covered by P05 authorization**. It is labeled
**exploratory; never confirmatory**: k = 4 floor 0.125 > 0.05, so no
significance-style claim is made. Branches are real/placebo/null with only
`state.visible_messages` differing. The exploratory replay may never be
pooled with the held-out block (P08–P13).

## 4. Checks (all offline, zero provider calls)

- Recomputed the registration `registration_hash` from the artifact; it
  matches `6fa61497…` (fail closed on drift).
- Rebuilt the registration from the frozen generator and current disk state:
  **byte-for-byte** identical to the artifact (deterministic rebuild).
- Recomputed every input-evidence hash (#200 audit, #200 registration, P02
  scope freeze, P03 census) from disk; all match the pins recorded in the
  registration.
- Verified the design classification: k = 4, floor 0.125, pilot (not
  potentially confirmatory), fresh-seed replication descriptive.
- Verified the fixed-N manifest: 16 instances, 4 per form, matches the #200
  audit `primary` block.
- Verified the budget arithmetic: planned/physical counts, cost model, and
  worst-case costs within ceilings.
- Verified the terminal stops, fresh paths (outside `runs/epic-126/`), and
  coverage rules are registered.
- Verified the six-form confirmatory minimum and the interval half-width
  labeling (not a power-based MDE) resolve the P01 §5 log.
- Ran the registration CLI verification: **41/41** named checks pass,
  `provider_calls: 0`.
- Ran the task-relevant test suites: `tests/test_jev_p04_design_classification.py`,
  `tests/test_jev_p03_form_census.py`, `tests/test_jev_p02_scope_freeze.py`,
  and `tests/test_jev_replication_preregistration.py`; every suite asserts the
  frozen inputs byte-for-byte unchanged after running.
- No live output path exists or was created; the #200 live paths remain
  absent.

## 5. Handoff

P04 is complete with evidence paths, hashes, checks and this handoff. The next
concrete offline step is **P05 (#206)** — lock discovery design and record
live authorization: offline preflight, reviewed lock hash, then separate
explicit authorization reference with stage/route/cost scope. Pending
authorization blocks P06; this plan is not that authorization. #206 is
blocked by this task until the plugin records its closure. A predecessor
closed as failed does not authorize successor execution; this task closes
with evidence, and nothing in it authorizes collection, any provider call,
or any registration lock.
