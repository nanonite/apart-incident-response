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

## Guards (separate from the entropy effect)

A reduction in entropy alone is **not** evidence of useful, target-directed
information. Every useful-information claim additionally requires both guards,
evaluated per event before it enters `d_f`:

1. **Target-probability guard**: `p_target(real) ≥ p_target(placebo)` — the real
   message must not lower the true-target probability. A stricter practical
   margin `δ` may be required.
2. **Feasible-set-mass guard**: `mass_F(real) ≥ mass_F(placebo) − ε`, where
   **`F` is the pre-read clue-consistent set `S(C)`** (the receiver's own feasible
   set before any message), which is fixed by `C` and **independent of the real
   message content**. This avoids the tautology of scoring the real claim against
   a set the real claim defines. Mass on `F` must not fall; reduced entropy that
   concentrates mass outside `F` is not useful information.

Objective claim `I_m` (controller-side log-cardinality reduction of the feasible
set, in bits) is kept **distinct** from model entropy `H(Choice p)`. `I_m` is a
property of the message, not of the model's distribution.

## Eligibility, identity, missingness

- **Eligible real message**: exact owner claim (`holds_claim`), delivered via the
  board, and exposed to the receiver (writer/reader/exposure provenance present).
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

## Claim scope

- J3 ISO−FULL data is a **method regression**, not causal replay evidence.
- No causal, calibration, or held-out claim from this design until a fresh,
  form-level evaluation is separately registered and authorized.

## Judgments needing reviewer approval (not chosen silently)

1. **`ε`** (feasible-set-mass slack) and **`δ`** (target-probability margin); a
   default of `ε=δ=0` is proposed but the practical margins are a judgment.
2. **Minimum complete pairs per form** before `d_f` is computed.
3. **Placebo construction rule** (e.g. writer-owned but already-implied claim vs
   a format-matched non-claim) — must satisfy `I_m = 0` and not reduce `F`.
4. **Decision rule**: one-sided directional (`Δ<0`) vs two-sided inference with a
   directional claim only if the sign holds.
5. **k**: conditional on the **six known forms**, or a **generator redesign** for
   new forms (see #185). Wilson/interval claims must not read repeated queries as
   independent.
