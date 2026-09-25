# Planning-low Jev replay — final decision memo (conditional)

Task: Chainlink **#199** under **#159**. Offline reconciliation only — no provider
call, no artifact modification, no rerun, nothing reopened.

## 1. Input integrity (recomputed, fail closed on drift)

| Input | sha256 |
|---|---|
| `runs/epic-126/replay-v5/jev-choice-replay-inference-v5.json` (#198) | `b892a8d514623aca17b83f17a59e9e699d773b48f059b7b954b6239ff7d6f2ce` |
| `runs/epic-126/replay-v5/jev-choice-replay-v5.jsonl` (51 rows) | `5e9f7322bdb29baf16b18f9b4f4181e9a88ad454e0394ea379e4cdea29b1fede` |
| `runs/epic-126/replay-v5/jev-choice-replay-report-v5.json` | `0ec84446d697bca91c25e155b3cd61f43b4e7706e6df185ea08c3685a8f88310` |
| `runs/epic-126/replay-v5/jev-choice-replay-preregistration-v5.json` (file) | `3c02f8bb44c11d6edd050daf32950e3cf8365f79638e92d46181df764945ddd7` |
| registration content hash | `0a81e400f598d16742301d7c07cbaf5398fa861b4fa1701c15405391ab4f6d15` |
| run commit | `3e678ac` · analysis commit `87e8b71` |

The inference artifact records the same three input hashes and the same
registration hash; all four files were re-hashed for this memo and match.

Registered result reproduced from the artifact: equal-weight six-form mean of
`H_real - H_placebo` = **-0.7775085127397289 bits**; exact two-sided cluster
sign-flip **p = 0.03125** (64 sign patterns, the k=6 floor 2/64); form-mean
t interval **df = 5: [-1.1722041593435226, -0.38281286613593507]**; **17/17**
complete real/placebo pairs over the **six frozen forms** (1/4/4/1/4/3);
registered criterion met.

## 2. The five levels, kept separate

These are five different claims with five different evidence bases. Nothing in
one row licenses the row below it.

### Level 1 — Structural communication need

**Status: supported as selection evidence, not as fresh confirmation.**

The offline board-necessity selection recorded `finalizer_needs_peer` 17/17 on
the discovery instances and a Ling C_need for planning:low of +0.588 with
Holm-adjusted p = 0.0098, with voluntary board use 14/17 (20 messages,
31.70 bits) and post-read correlation 2/17. This is selection data from the
discovery screen (`runs/epic-126/jev-board-necessity-selection.json`), not a
fresh confirmation, and post-read correlation is never treated as uptake.

### Level 2 — Message emission

**Status: supported under the exact original treatment; treatment-dependent.**

The exact original-treatment L4X bridge produced 14 accepted owner-exact
messages (A 2, B 12) with 14 verified read exposures and 9/17 eligible B→A
exposures, whereas the standalone private-clues-only writer treatment produced
17/17 silence. The fresh paid-route coverage block then produced 24 owned
message candidates against 100 deliberate silences. Emission is therefore a
property of the writer prompt/role/treatment, not of the Jev receiver, and
emission alone says nothing about the receiver.

### Level 3 — Verified exposure

**Status: supported with full provenance.**

The #192 selector verified 17 replay-eligible one-way B→A events, each with an
accepted B-owned claim, authoritative `I_m = log2(3) > 0`, a matching board
write, an after-write A read with a nonempty exposure id, no rejection
evidence, and at most one deduplicated claim per pre-read state; A→B writes and
receiver-known zero-information claims are excluded. Coverage spans all six
frozen forms with distribution 1/4/4/1/4/3. Exposure is proven delivery to the
receiver's context — still not an effect on the receiver.

### Level 4 — Entropy reduction

**Status: supported within the registered estimand.**

On the frozen 17-event set, the equal-weight mean of the six within-form means
of `H_real - H_placebo` is -0.7775085127397289 bits, all six form means are
negative, the exact two-sided cluster sign-flip p-value is 0.03125 and the
form-mean t interval with df = 5 is [-1.1722041593435226, -0.38281286613593507],
which excludes zero. Sensitivity over the registered normalization thresholds
1e-6 / 0.01 / 0.03 / 0.05 leaves the registered decision unchanged at every
threshold. Guards were reported separately and filtered nothing
(`filtered_primary_estimate: false`, `excluded_from_primary: 0`): 17/17 target
ok, 15/17 mass ok, 15/17 useful uptake.

### Level 5 — Causal uptake under the registered real/placebo contrast

**Status: supported inside the registered conditional scope only.**

The matched real/placebo/null replay holds receiver model, options, wording,
target, timing and pre-read state fixed and varies only the message. Under that
registered contrast the preregistered negative direction is met, the exact
sign-flip p-value is 0.03125 and the interval excludes zero, so the registered
criterion is met. The scope is exactly the six frozen planning-low prompt forms
and the paid Ling route that generated the messages. This is form-level
evidence for those six forms on that route; it is not a broader causal claim.

## 3. What is supported

1. A structural communication need existed for planning:low in the discovery
   screen (selection evidence, Holm p = 0.0098), with voluntary board use
   recorded but no causal reading of it.
2. Messages are emitted under the exact original writer treatment and their
   emission depends on the writer prompt/role, not on the Jev receiver.
3. Seventeen one-way B→A events with verified write-then-read provenance were
   delivered across all six frozen forms.
4. Within the registered matched contrast, real messages reduced receiver
   Choice entropy relative to an inert placebo: equal-weight six-form mean
   -0.7775085127397289 bits, exact two-sided sign-flip p = 0.03125,
   form-mean t interval df = 5 [-1.1722041593435226, -0.38281286613593507],
   17/17 complete pairs, preregistered direction met, conclusion stable across
   the registered sensitivity grid.
5. The registered causal-uptake criterion for planning:low is met on the paid
   Ling route, conditional on the six frozen prompt forms.

## 4. What is NOT supported

- **No population-level claim.** k = 6 is capped by the generator's closed form
  space; six forms are not a sample of a population of prompts.
- **No cross-family claim.** Nothing here speaks to hypothesis, reference,
  poetry, legal or lexicon, or to any family not registered for this run.
- **No calibration claim.** Entropy change is not evidence that Jev Choice
  probabilities are calibrated; no calibration quantity was estimated.
- **No instance-level claim.** The 17 events are replicates within six forms,
  never 17 independent units; no instance-level t-test, Wilcoxon test or
  instance-weighted estimate is primary or reported as a result.
- **No unique-information claim.** Gross replay-eligible `I_m` is
  26.9443625123 bits over 17 events (it counts within-form repeats), while the
  distinct form/claim treatments total 9.5097750043 bits over 6 treatments;
  gross totals are never described as unique delivered information, and
  `H_real - H_placebo` is a change in the receiver's distribution, not bits
  delivered.
- **No route invariance.** Findings are conditional on the paid Ling route that
  generated the messages and are not automatically poolable with free-route
  behavioral rates.
- **No family sweep, no post-hoc winner.** No other family was screened here,
  and no family, form, rung or seed may be selected post hoc for a confirmatory
  claim.
- **No generalization beyond these six frozen forms** and no claim about
  effects smaller than the approximate 0.203-bit MDE.

## 5. Sensitivity and guard summary

| Check | Result |
|---|---|
| Normalization tiers | exact 50, complete_renormalized 1, other 0 |
| Sensitivity 1e-6 | 16 pairs, k = 6, estimate -0.773556, p = 0.03125, decision unchanged |
| Sensitivity 0.01 / 0.03 / 0.05 | 17 pairs, identical to the primary result |
| `conclusion_changed` | false at every threshold |
| Guards | target ok 17/17, mass ok 15/17, useful uptake 15/17; 0 filtered, 0 excluded |
| Null checks | mean real-null -0.615288 bits (17/17 below null); mean placebo-null +0.082010 bits (6/17 below null) |

## 6. Claim scope

Scope: conditional on the six frozen planning-low prompt forms and the paid Ling route
that generated the messages; experimental unit is the prompt form with k = 6;
approximate MDE / CI limitation 0.203 bits, so a null result could not exclude
smaller effects. No population-level, cross-family, calibration, instance-level
or unique-information claim is made or implied.

## 7. Recommended next scientific phase

Replicate the same preregistered recipe on another family, and only after a new
form-capacity audit:

1. **Form-capacity audit first (offline).** Establish that the candidate family
   yields genuinely distinct pre-read prompt forms and report the achievable k.
   Seed disjointness alone is never sufficient — the 70000-74000 blocks are
   ID-disjoint yet repeat the J3 forms.
2. **Fresh seeds**, selected offline by deterministic prompt form only, disjoint
   from every prior manifest, with fixed N and no outcome-dependent stopping.
3. **Family-level multiplicity control**, decided and preregistered before any
   collection (Holm or FDR across exactly the families registered), plus a
   fresh-seed confirmation rule.
4. **A new registration** with fresh output paths, own source/treatment hashes,
   own caps and stop rules, locked and separately reviewed before any live run.
   The replay-v5 hash `0a81e400…` does not cover any replication.
5. **Do not sweep families and select a winner post hoc.** The registered family
   set may not change after outcomes are visible.

## 8. Chainlink reconciliation

- #198 (offline inference) — closed by review; artifact published.
- #197 (fresh replay-v5 registration) — completed: registration locked and the
  authorized run executed and analysed; closed with an evidence-backed
  resolution in this reconciliation.
- #188 (six-form coverage and causal replay epic) — all six children closed
  with resolutions, coverage gate released, replay executed and analysed;
  closed with an evidence-backed resolution in this reconciliation.
- #159 — remains **open** for reviewer assessment of this conditional
  conclusion; nothing here authorizes further collection.
- #181, #182, #183, #184 — left **open** for reviewer assessment; their
  offline deliverables exist and are exercised by the suite, and they are not
  reopened, rerun or modified by this task.
- #195, #196, #198 — already closed; **not reopened**.
- #199 — this task; #200 — replication task, left **draft/offline** with a new
  registration required before any live run.
