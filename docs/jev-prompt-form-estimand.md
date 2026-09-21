# E1 — Equal-prompt-form replay estimand and guards (#182)

Status: offline design contract for review. Freezes the estimand, form identity,
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
