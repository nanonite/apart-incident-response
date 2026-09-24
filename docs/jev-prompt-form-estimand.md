# E1 — Equal-prompt-form replay estimand and guards (#182)

Status: offline design contract for review; extended by the #189 freeze below
(recomputed L4X v5 coverage, information accounting, inference limits, and the
#190 sizing handoff). Freezes the estimand, form identity,
eligibility, missingness, and useful-information guards for the Jev Choice
causal-replay method. **No live calls, no caps, no causal claim.** This Choice
work is separate from packet tasks #173/#175.

## Experimental unit and pre-read state

- The unit is the **model-visible pre-read prompt form**, not the instance ID.
  Two requests with the same pre-read body are one form (a repeated query), not
  independent replicates. J3 has k=6 forms across 17 IDs.
- One pre-read receiver state `C` is frozen per event and shared by every branch.
  `C` is the Jev `state` (family, complexity, agent_id, clues) with the same
  `model`, question id, instruction wording, and `criteria` option set. No target,
  joint answer set, or unreceived peer clue is in `C`.
- **prompt_form_id** = `sha256` of the canonical JSON of the pre-read request
  body `{model, state, questions:{<qid>:{type,instructions,criteria}}}` with no
  message attached. It binds model, state, wording, and option set.

## Branches

For each event the same `C` is replayed in three branches; everything except the
message content is held fixed (receiver model, options, wording, target, timing):

- **real** — an eligible writer message that is owner-exact and exposed to the
  receiver (provenance recorded).
- **inert placebo** — a format-matched message with **no task information**:
  controller-side `I_m = 0` and no reduction of the receiver's feasible set. It
  controls for receiving a message of that shape.
- **null** — no message.

## Estimand

- Event difference `d_event = H_real − H_placebo` (bits), same `C`, same form.
- Per-form `d_f` = mean of `d_event` over complete real/placebo pairs in form `f`.
- **Primary estimand** `Δ = (1/k) Σ_f d_f`, the equal-weight mean across distinct
  forms. Forms are weighted equally; instances and duplicates are not.
- **Directional prediction**: `Δ < 0` (a real message reduces decision entropy
  more than an inert placebo).
- **Null cancels from the primary contrast** but is retained as a separate
  **manipulation check**: report real−null and placebo−null. Null is not the
  primary comparator because a null branch cannot separate "no message" from
  timing/exposure effects that the placebo controls.

## Guards (evaluated separately from the entropy estimate)

A reduction in entropy alone is **not** evidence of useful, target-directed
information. **Every pre-eligible, valid real/placebo pair enters the primary
entropy estimate regardless of the guards**; selecting events by their outcomes
would bias the contrast. The guards are evaluated and reported **alongside** the
primary estimate, never used to filter it.

For each event the useful-information claim additionally requires both guards:

1. **Target-probability guard**: `p_target(real) ≥ p_target(placebo) + δ` — the
   real message must not lower the true-target probability. Provisional `δ = 0`.
2. **Feasible-set-mass guard**: `mass_F(real) ≥ mass_F(placebo) − ε`, where
   **`F` is the pre-read clue-consistent set `S(C)`** (the receiver's own feasible
   set before any message), which is fixed by `C` and **independent of the real
   message content**. This avoids the tautology of scoring the real claim against
   a set the real claim defines. Mass on `F` must not fall; reduced entropy that
   concentrates mass outside `F` is not useful information. Provisional `ε = 0.01`.

Report form-level guard differences and event-level violations. An entropy drop
with no target-probability improvement must **not** be called useful uptake.

Objective claim `I_m` (controller-side log-cardinality reduction of the feasible
set, in bits) is kept **distinct** from model entropy `H(Choice p)`. `I_m` is a
property of the message, not of the model's distribution.

## Eligibility, identity, missingness

- **Instrument (frozen, source-neutral)**: one message envelope `peer_clue: {claim}` for
  both the real and placebo arms, so sender identity is **not** a model-visible
  difference in the primary contrast; the real writer id and the synthetic placebo origin
  are retained only controller-side. Each branch request is deterministically
  reconstructed as the frozen pre-read body with `state.visible_messages` set to `[]`
  (null) or one `peer_clue` message; each branch `request_hash` is **recomputed** and must
  match the stored value, so arbitrary hashes are rejected.
- **Eligible real message (authoritative)**: resolved from the generated instance — the
  writer provably owns the exact claim (`holds_claim`) and the reader is the receiver.
  Delivery/exposure is proven only from the retained `CommunicationEventLog`: an accepted
  `board_write` by the writer whose `normalized_claim`/`raw_text` equal the claim and
  whose `receiver_id` is the reader, followed by a `peer_read_exposure` by the reader with
  the recorded `exposure_id`. A `board_write_rejected`, a missing read, or a mismatched
  exposure fails closed (`unverified_real_evidence`); a flattened self-reported board
  record is not accepted. Objective information `I_m` is recomputed from the instance,
  never self-reported.
- **Eligible placebo (authoritative)**: the claim is one of the receiver's own pre-read
  clues, its authoritative `I_m` against the receiver's pre-read feasible set is 0, and
  the feasible set is unchanged; synthetic provenance stays controller-side.
- **Identity**: all branches of an event must share the identical `C` and option
  set (same `prompt_form_id`). A branch whose state or options differ is rejected.
- **Validity**: a branch must return a complete, normalized, exact-option-key
  Choice vector with a valid confidence/usage and resolved model; otherwise the
  branch is invalid.
- **Complete pair**: real and placebo both valid and identity-matched. Incomplete
  pairs are **reported, not silently dropped**; a form with no complete pair
  contributes no `d_f` but counts in the missingness table.
- **Mixed protocols, duplicates, answer-key leakage** fail closed: one Jev
  protocol key per analysis; no duplicate `(prompt_form_id, event_id, branch)`;
  no target value or answer key in any model-visible state.
- **No exceptions on malformed input**: invalid records return problem codes.

## Claim scope

- J3 ISO−FULL data is a **method regression**, not causal replay evidence.
- No causal, calibration, or held-out claim from this design until a fresh,
  form-level evaluation is separately registered and authorized.

## Judgments needing reviewer approval (not chosen silently)

1. **`ε`** (feasible-set-mass slack) and **`δ`** (target-probability margin).
   Provisional recommendation: **`δ = 0`, `ε = 0.01`**, reported form-level and
   event-level, never used to filter the primary estimate.
2. **Minimum complete pairs per form**: require at least one valid pair in each of
   the six forms for the six-form primary analysis; aim for two or more planned
   opportunities per form. If a form is lost, call the result incomplete — at five
   forms the smallest two-sided sign-flip p is 0.0625.
3. **Placebo construction rule**: a preregistered, controller-injected typed claim
   **already known to the receiver**, verified `I_m = 0` and no feasible-set
   reduction, with its synthetic origin recorded outside the model-visible
   message. The current audited instances have no B-owned zero-information claim,
   so a naturally B-owned placebo is not feasible without a generator change.
4. **Decision rule**: keep the **two-sided exact sign-flip** and additionally
   require a negative effect; report the form-mean t interval alongside it. Do not
   switch to one-sided testing after seeing data. Null remains a separate check.
5. **k**: run as a pilot **conditional on the six known forms**; new seed IDs do
   not create new forms. Treat the t interval and sign-flip result as
   assumption-dependent summaries of these forms, not generalization; redesign the
   generator before a broader claim (see #185).
6. **Caps**: ≤300 physical requests and ≤$1 Jev cost are ceilings only; freeze
   them after the registration spells out planned Ling and Jev calls, retries, and
   what happens when optional board use leaves a form without a real message.

## #189 freeze — coverage facts, accounting, inference limits, #190 handoff

Status: frozen by the offline audit `#189`. Reproducible module
`src/apart_incident_response/jev_six_form_coverage_audit.py`, focused tests
`tests/test_jev_six_form_coverage_audit.py`, versioned artifact
`runs/epic-126/jev-six-form-coverage-audit-v1.json` (audit version
`jev-six-form-coverage-audit-v1`). Every number below is recomputed from the
hash-pinned immutable L4X v5 inputs
(`runs/epic-126/jev-writer-exact-bridge-v5.jsonl`,
`runs/epic-126/jev-writer-exact-bridge-report-v5.json`) and the task
generator — not copied from issue prose. The audit makes zero provider calls
and never writes to the frozen inputs; a hash mismatch fails closed.

### Recomputed L4X v5 coverage (17-instance block)

- **17/17 valid** Jev receiver cases (0 invalid, 0 unattempted; all
  normalization tier `exact`, model `jev-1.13.0`).
- **14 accepted messages: A=2, B=12**; **14 authoritative-information
  records** (`delta_i_bits` present) and **14 verified read exposures**
  (`peer_read_exposure` events, all 12 accepted B messages read by A).
- **9/17 cases with eligible B→A Jev exposure** (rate `9/17 ≈ 0.529`);
  eligibility = valid receiver + ≥1 replay-selected B→A claim under the frozen
  provenance rules.
- **Six distinct pre-read prompt forms**; **exactly five of six** have ≥1
  eligible B→A exposure.
- **Uncovered form** `55968fe191b18f37d1951d71f777115f753e0b9a6da526015f3db5251a1383eb`
  (B-owned clue `precedes=inspect>stage`; instances
  `planning-00011949/0001194a/0001194e`; 6 B writer opportunities, 0 accepted
  B messages, 0 eligible exposures).
- **Zero** empty, truncated, unparsed, invalid-answer, or writer-error
  outputs; the only writer outcomes present are `deliberate_silence` (53),
  owned `message_candidate` (14), and classified `non_owned_claim` (1). No
  invalid writer output affected the result.

Per-form coverage table (recomputed):

| prompt_form_id (prefix) | B-owned clue | instances | B writer opps | accepted B | accepted A | eligible B→A |
|---|---|---|---|---|---|---|
| `0a3349e16c96…` | `precedes=inspect>deploy` | 4 | 8 | 4 | 0 | 3 |
| `1c1d9f6b5c92…` | `precedes=stage>deploy` | 3 | 6 | 2 | 0 | 2 |
| `2954f5684bcd…` | `precedes=stage>inspect` | 1 | 2 | 2 | 0 | 1 |
| `3196a8d69f84…` | `precedes=deploy>stage` | 3 | 6 | 1 | 1 | 1 |
| `55968fe191b1…` | `precedes=inspect>stage` | 3 | 6 | 0 | 1 | 0 |
| `ce847ac53b6e…` | `precedes=deploy>inspect` | 3 | 6 | 3 | 0 | 2 |
| **total** | 6 distinct clues | 17 | 34 | 12 | 2 | 9 |

### Prompt-form / information-geometry audit

- Prompt form ↔ B-owned clue is **bijective**: 6 forms, 6 distinct B clues;
  the pre-read form fixes A's private clues and claims are partitioned, so the
  form determines B's single owned clue and vice versa.
- Every B clue carries **exactly `log2(3) ≈ 1.584963` bits** to A: A's
  pre-read feasible set shrinks 3 → 1 under the authoritative evaluator, status
  `accepted`, for all six forms.
- The uncovered form has the **same information geometry** as the covered
  forms, so its gap is classified a **writer/seed coverage event**, not an
  information-geometry difference. This does **not** prove the form will emit
  under new seeds (nor that it cannot): emission under fresh seeds is an
  empirical question owned by #190.

### Information accounting (frozen)

Primary replay direction is **one-way B→A**. Frozen rules:

1. Exclude A→B writes from the primary replay.
2. Exclude receiver-known or authoritative `I_m = 0` claims.
3. Use at most one accepted, B-owned, informative claim per pre-read state.
4. Require verified board-write and A-read provenance
   (`CommunicationEventLog`, never the flattened board row alone).
5. Deduplicate repeated identical B claims within an event.
6. Report gross transmitted bits separately from replay-eligible information.
7. Do not claim symmetry across agents.

Accounting result (recomputed):

- **Gross reported** `i_m_bits = 22.18947501` over 14 authoritative records —
  this is **not** unique information delivered to Jev A: it includes 2 A→B
  messages (`2 × log2(3) ≈ 3.169925`) and 3 within-event repeated identical B
  claims (`3 × log2(3) ≈ 4.754888`).
- **Gross B→A**: 12 messages, `12 × log2(3) ≈ 19.019550`.
- **Replay-eligible**: 9 events × 1 claim = `9 × log2(3) ≈ 14.264663` bits,
  spanning **5 distinct (form, claim) treatments** = `5 × log2(3) ≈ 7.924813`
  bits of distinct model-visible claim content (instances within a form repeat
  the same pre-read state and B clue).

### Experimental unit and primary estimand (frozen)

- Experimental unit: the **distinct model-visible pre-read prompt form**
  (`prompt_form_id`), not the instance ID.
- For replay event `i` in form `f`: `H_real = H(Y | C, M_real)`,
  `H_placebo = H(Y | C, M_placebo)`, `H_null = H(Y | C)`,
  `d_i = H_real − H_placebo`, `d_f` = mean `d_i` within form `f`.
- **Primary estimand** = equal-weight mean of `d_f` across the six forms.
- The **null branch remains necessary** for real-minus-null,
  placebo-minus-null, and manipulation checks even though it cancels from the
  primary real-minus-placebo contrast.
- Guard metrics (`p_target`, feasible-set mass) are reported **separately**
  and must **not** filter observations from the primary entropy estimate.

### Inference and claim limits (frozen)

- Primary: **exact two-sided cluster sign-flip test on form means**; interval:
  **form-mean t interval with df = k − 1**.
- Minimum attainable two-sided sign-flip p: **k=6 → 2/64 = 0.03125**;
  **k=5 → 2/32 = 0.0625**. Therefore a **five-form result is interval-only and
  descriptive**; it cannot satisfy a two-sided α=0.05 sign-flip gate.
- Instance-weighted analyses are **secondary only**; no instance-level t-test
  or Wilcoxon as primary; missing real/placebo pairs are **not imputed**;
  branch missingness and complete pairs are reported by form.
- Sensitivity reproduction with the illustrative between-form SD ≈ 0.1933
  bits (recomputed from the J3 ISO-FULL method demonstration as 0.193318…):
  `t(0.975,5) × 0.1933 / sqrt(6) = 2.571 × 0.1933 / 2.449490 ≈ 0.202889 ≈ 0.203`
  bits. This is **planning/sensitivity context, not a guaranteed powered
  effect threshold**: a null result cannot rule out effects smaller than
  roughly 0.2 bits. The known form space contains only six forms, so adding
  duplicate instance IDs **cannot increase k**.

### #190 handoff (documented only — not implemented by #189)

- Observed eligible-instance rate `9/17 ≈ 0.529`; target: six fresh
  offline-selected instances per each of six forms, **N = 36**.
- Under the simplifying independent-rate assumption:
  `1 − (1 − 9/17)^6 ≈ 0.989` (one form gets ≥1 eligible exposure) and
  `[1 − (1 − 9/17)^6]^6 ≈ 0.937` (all six do).
- This is an **assumption-based sizing heuristic, not evidence of
  independence**. The next block must use a **new registration and manifest**
  and must **not append** to the frozen 17-instance artifact. Seed-to-form
  selection may happen offline because form identity is deterministic. The
  future collection must use **fixed N with no stopping after the first
  message**.
