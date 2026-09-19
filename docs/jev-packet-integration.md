# Jev packet-readout integration plan (successor to the current Jev collection)

Status: design / **post-current-collection**. Offline only. No live calls, no
registration change, no protocol-key change to the frozen v1 planning-low
manifest. This plan fixes the record of an earlier draft that contained several
measurement errors (see "Corrections" below).

Scope: extend the Jev receiver from a single finite-decision Choice to a
compound **packet** of labelled questions, and add the readouts the current
Ling-only screen cannot produce. Build the schema-agnostic parts now; gate the
wire codec and every live run behind explicit approval and a real Jev
endpoint/model.

## 1. Why

The current Jev track already implements the offline Choice adapter (#155) and
credential handling (#156). What it cannot do:

- measure whether the receiver **believes its own evidence is sufficient**;
- retrieve a **receiver-derived feasible set** to compare against the
  controller's clue-consistent set;
- measure **communication pressure** as a calibrated decision.

The packet layer adds these in Jev's native output shape without changing the
frozen v1 artifacts. It runs **after** the current Jev data collection completes;
it does not modify #156–#159 as registered.

## 2. What we take from the Jev DSL (and what we do not)

Reference: `github.com/inanna-malick/jev-dsl`, an agent-first Haskell DSL over
TypeSafe's Jev judgment model.

| Take | Leave |
|---|---|
| Contract vocabulary: `state` + labelled question map; kinds **Noul / Choice / Score**; Choice 1–255, Score 1–10 | The Haskell library / nix build as a dependency |
| Compound packets; nested cells flatten to dotted keys | Score as a primary instrument ("rarely the right shape") |
| Answers under the same labels; no free-text parsing | The uncalibrated `lenient/careful/strict` floors as truth |

**Contract status: unverified.** No Noul/Score/packet token exists anywhere in
this repo; the only implemented shape is the invented `{model, options, prompt}`
in `jev_choice.py`. Record the exact jev-dsl revision mirrored, or treat the
vocabulary as unverified until a golden capture exists (see §7).

## 3. Corrections to the earlier draft

- **Constant-label Noul.** `#sufficient` has one class per condition
  (ISO `|S_A|=3` → "not one"; FULL `|S_joint|=1` → "exactly one"), so
  reliability bins / calibration curves are undefined. It is a **descriptive
  belief / self-knowledge probe**, not a calibration target. The design fact
  (`|S_A|`, `|S_joint|`) is already known from the manifest.
- **No ISO→FULL confound.** ISO and FULL are both board-free, one turn
  (`DEFAULT_CONDITION_TURNS = {"ISO":1,"FULL":1,"COMM":2}`). The extra turn is
  COMM-only and contaminates COMM contrasts and `C_need_comm`, not `C_need`.
  Do not state an ISO→FULL confound in the v5 rationale.
- **Condition-dependent feasibility target.** The feasibility battery must not
  be scored against `pooled_values` (= `S_joint`) in every condition.

## 4. Packet design

### 4.1 Identical packet in every condition

To keep conditions comparable, the paired-surface packet is identical across
ISO/FULL/COMM:

1. candidate **Choice** over the public option set (existing v1 behaviour);
2. **feasibility Noul battery** — one Noul per public candidate;
3. **need Noul** — self-knowledge probe (descriptive).

No `Score` in the paired surface (its referent is undefined without a message).
Keep `Score` in the IR but unused.

### 4.2 COMM-only pressure readout (separate, labelled call)

`channel_choice` over `["answer_now", "request_peer_message"]`;
`φ = P(request_peer_message)`. Compare with `C_need` and message `I_m`. This is
stated preference, not revealed use — pair it with observed board use. Collect
it as a **separate labelled call** so it never changes the identical
cross-condition packet.

### 4.3 Feasibility targets and fit block

| Condition | Truth set |
|---|---|
| ISO | `S_A` |
| FULL | `S_joint` |
| COMM pre-read | `S_A` |
| COMM post-read | `clue_consistent(S_A ∪ read messages)` |

Define `τ`, an **empty thresholded set** counted as its own outcome (never
silently mapped to argmax), and fit `τ` on a discovery seed block **disjoint**
from selection and evaluation, then freeze it. COMM post-read (3 → 1 when the
decisive claim is emitted) is the board-necessity readout.

## 5. Analysis rules

- **Unit of analysis** is `instance × condition`. One complete packet per cell;
  a valid Choice with invalid Nouls does not enter the primary contrast.
  Per-kind denominators are descriptive, not per-kind n (kinds sampled in one
  call are correlated by construction).
- **Calibration lives on the feasibility battery** (mixed classes in every
  condition), never on the constant-label need Noul.
- Never equate `H(Choice p)`, the need probability, and `log|feasible set|`;
  report association with paired uncertainty (`I_m` distinct from `H(Choice p)`).
- Post-read correlation stays correlation; causal uptake requires matched
  real/placebo/null replay.

## 6. Artifacts and schema

- One row per `(instance_id, condition, adapter_version)` with question kinds
  **nested** — otherwise `paired_contrast`'s duplicate-valid-row guard
  (`behavioral_discovery.py`) raises.
- Carry `protocol_key` and `adapter_version` on every row.

## 7. Wire and versioning

- Build the internal packet IR, invariants and **leak tests** now,
  schema-agnostic.
- Keep one thin codec; mark fixtures `ASSUMED_SCHEMA`.
- At J3 capture one redacted request/response pair as a **golden fixture**,
  regenerate codec tests from it, and only then freeze the codec.
- Key grammar: introduce `packet_protocol_key` (**key-v2**, extra adapter
  dimension) rather than mutating v1; keep v1 consumers equality-only; add a
  **mixed-key refusal** in the analysis loader; update the six-field assertion
  (`tests/test_behavioral_discovery.py`) in the same commit that adds v2.
- v1 hygiene: `PACKET_INVALID_RESPONSE_CLASSES = INVALID_RESPONSE_CLASSES | {...}`
  in the new module (never mutate `jev_choice` constants); write a new manifest
  file; keep v1 manifest hash + key regression.

## 8. Inducement arm

planning-low COMM has produced near-zero verified use; new readouts do not
create communication. Add a **separately labelled required-claim / silence-penalty
arm** (permitted by the J5 scope) to the packet registration, so the packet
readouts are not flat again. It is labelled and never pooled with voluntary-use
estimates.

## 9. Sequencing

- **Current track unchanged:** #156 (Choice-only J3 gate), #157, #158, #159.
- **Successor:** the packet-readout subepic under #153, blocked by completion of
  the current Jev collection. It carries its own `v5` registration
  (`stage2-planning-low-packet-v1`).
- Per-kind gate coverage is a child issue (the current #156 acceptance text is
  Choice-only).

## 10. Build order

1. Packet IR + invariants + ISO/FULL/COMM leak tests (schema-agnostic).
2. `packet_protocol_key` v2 + mixed-key refusal + updated six-field test.
3. v5 preregistration draft: identical packet, per-condition targets, `τ` fit
   block, per-kind denominators, required-claim arm, caps.
4. Gate-report scaffold with placeholder endpoint/model.
5. At J3 approval: pin endpoint/model, capture the golden wire pair, freeze the
   codec, run the bounded probe.
