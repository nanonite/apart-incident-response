# Jev communication pressure: hypotheses and sequential research plan

Status: planning only, 2026-09-26. This document authorizes no provider calls,
registration lock, or collection. It supplies a task decomposition for Chainlink
#159 and its existing next-family task #200. The structure is now instantiated
as epic **#201**, with P01–P14 mapped to **#202–#215** respectively. Task creation
does not authorize execution of live stages.

## Research purpose and starting evidence

Identify task families in which a real peer message causes a useful reduction
in receiver uncertainty. Discovery estimates, communication failures, guard
violations, and descriptive pilots are research results in their own right.
Confirmation is an evidentiary gate: it tests whether an apparent entropy
effect survives independent-form aggregation, fresh data, and a registered
error criterion. It does not replace discovery or prove the hypothesis true.

The initial confirmed family-level case is **planning-low, conditional on its
six frozen forms and the paid Ling route that generated its messages**. The
[completed decision memo](jev-planning-low-replay-decision-memo.md) reports
17 complete pairs, an equal-form effect of -0.7775085 bits, exact two-sided
sign-flip p = 0.03125, and a 95% form-mean t interval [-1.1722, -0.3828]. All
six form means are negative. Target guards pass 17/17; feasible-mass and useful
uptake guards pass 15/17. Thus entropy support does not imply every event had
useful uptake. Preserve its artifacts and scope; do not use its estimate or
p-value as a prior, power assumption, or guarantee for another family.

The [#200 draft](jev-replication-preregistration.md) already selects
`hypothesis:low` by an offline structural rule and reports four forms. Its two
16-instance blocks remain unrun and the registration remains draft. Continue
with this family as a descriptive pilot; calling a block “confirmation” cannot
make four forms confirmatory. Later families proceed one at a time in the
recorded candidate order (`legal`, `lexicon`, `poetry`, `reference`), subject to
the gates below. No outcome-based reordering or search for a winning family.

## Hypotheses and estimand

For an eligible event e in prompt form f, freeze receiver pre-read state C_fe.
Let H^R_fe be receiver Choice entropy after the real peer claim, and H^P_fe
entropy after the matched inert placebo. Entropy is in bits on the identical
registered option set:

```text
H(p) = -sum_j p_j log2(p_j), with 0 log2(0) = 0
d_fe = H(real message | C_fe) - H(matched placebo | C_fe)
d_f  = mean_e(d_fe) within form f
Delta = E_f[d_f], estimated as (1/k) sum_f d_f

H0: Delta = 0    real communication does not change mean entropy versus placebo
H1: Delta < 0    real communication lowers mean entropy versus placebo
```

Forms receive equal weight regardless of their event counts. For a closed form
space, E_f denotes a uniform average over the registered finite forms, not an
unspecified population of prompts. A null mean permits heterogeneous positive
and negative form effects; H0 does not assert every event is unchanged.

The scientific alternative is directional, but the operational test remains
the original **two-sided exact cluster sign-flip test plus a negative-direction
requirement**. Do not silently switch to a one-sided p-value. A future one-sided
design would require its own registration and composite null Delta >= 0.

For observed form means, enumerate all 2^k sign assignments and compute
`T_s = mean_f(s_f * d_f)`. The primary raw p-value is the proportion with
`abs(T_s) >= abs(mean_f(d_f))`, using a frozen numerical tie tolerance. Report
the companion 95% t interval `mean(d_f) +/- t(.975,k-1)*sd(d_f)/sqrt(k)`.
The interval is unadjusted unless a simultaneous interval was registered.

Exact enumeration does not make this an assumption-free test of the weak
mean-zero null. Independent cluster sign exchangeability under the null must
be defensible (for example, appropriate symmetric form-difference errors).
Hash-distinct prompts alone do not establish statistical independence. Audit
shared templates and dependence, and state why form-level sign flips are
appropriate; otherwise retain descriptive estimates and label the inference
assumption-dependent. The companion t interval also requires distributional
assumptions, especially with small k. See the primary
[SciPy paired permutation documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html)
for paired exchangeability and exhaustive sign enumeration.

## What makes entropy reduction useful

Keep three quantities separate: objective information delivered (`I_m` from
the authoritative clue evaluator), change in receiver entropy (`d_fe`), and
causal uptake under the matched real/placebo contrast. Exposure proves delivery
to context, not uptake; entropy reduction does not prove calibration.

Before receiver outcomes, establish authoritative B-to-A ownership, an accepted
board write followed by A's verified read, nonempty exposure identity, positive
real `I_m`, absence of receiver-known claims, and one deduplicated informative
claim per state. Record every failed eligibility check and silence in the
collection denominator. These are design/provenance checks, not outcome guards.

Hold pre-read state, model, options, instructions, target, and replay timing
policy fixed across real/placebo/null; only `visible_messages` differs. Use the
original L4X writer treatment. Match the real/placebo envelope; verify placebo
`I_m = 0` and unchanged feasible set. Keep null for manipulation checks only.

For every valid complete pair, retain target probability and probability mass
on the **pre-read** feasible set F = S(C), fixed independently of the message.
Register target margin delta and mass tolerance epsilon; carry forward delta
= 0 and epsilon = 0.01 only when explicitly pinned in the new registration.
Report `target_ok`, `feasible_mass_ok` (legacy `mass_ok`), and `useful_uptake`,
including the exact inequalities and strict target-improvement rule used by the
existing implementation. Report continuous differences as well as pass rates,
by event and by form. Any tolerated mass decrease must remain visible.

**Guards never filter the primary entropy estimate.** An entropy-supported
family with guard failures gets a qualified interpretation and failure counts,
not an unqualified useful-uptake claim. A future family-wide binary usefulness
criterion requires a prespecified aggregation rule; event pass rates alone do
not establish a separate confirmatory usefulness result.

## How additional data help, and where they cannot help

More seeds within a form improve estimates of event variability, message
emission, coverage, missingness, and guard rates. They do not increase k.
Fresh seeds can test reproducibility on the same forms but do not establish
generalization to new forms. Do not split duplicates, pool different families,
or redefine forms after outcomes to obtain a smaller p-value.

| Independent forms k | Smallest two-sided sign-flip p | Design at unadjusted alpha = .05 |
|---|---|---|
| 4 | 0.125 | Descriptive/estimation only |
| 5 | 0.0625 | Descriptive/estimation only |
| 6 | 0.03125 | Potentially confirmatory, subject to all other gates |
| 7 | 0.015625 | Potentially confirmatory, subject to all other gates |

These are best-case floors; ties and zero effects can make them worse. Six
forms are necessary for this unadjusted recipe, not sufficient for adequate
power or multiplicity-adjusted rejection. With two hypotheses in a Holm family,
the smallest p must pass .025; two six-form tests cannot pass the first step.
The design audit must compute attainable adjusted decisions before collection.

Use discovery data to estimate within- and between-form variability, coverage,
and plausible effect ranges. Then freeze a prospective power analysis for the
actual sign-flip and multiplicity rule, including missingness and a stated
target power (default planning target: 80%). Report a scenario grid and the
smallest negative effect reaching that power, or “unattainable” when the
discrete test cannot reject. Do not promise power from planning-low's result.

The older documents' `t-critical * SD / sqrt(k)` quantity is an illustrative
**interval half-width**, not a power-based MDE. Preserve historical artifacts,
but label it correctly in new reports. Do not assert that a nonsignificant
result rules out effects based on that number. If a larger form space requires
generator changes, treat that as a new design/version with a new audit.

## Discovery, registration, and multiplicity policy

Audit capacity offline before any new-family provider calls. A fixed-window
census and independent closure probe show observed saturation; a mathematical
claim that the space is closed additionally needs exhaustive enumeration or a
generator-level argument. If unavailable, record closure as unproven. Compute
form IDs from canonical model-visible pre-read requests, select ascending seeds
deterministically within form, and prove seed and instance-ID disjointness from
all prior manifests. Record inaccessible or unaccounted manifests as audit
failures, never as empty sets. Never select seeds using emission or entropy.

Run a separately registered discovery screen when new emission/exposure data
are needed. Structural need, voluntary emission, ownership, and verified
exposure are selection evidence. Optional exploratory replay estimates are
labeled exploratory. All such outcomes precede and remain separate from a
fresh-seed confirmation block. No form replenishment based on live behavior.

For confirmation, freeze the exact hypothesis/family set before its new
outcomes, defaulting to Holm family-wise control at .05. FDR is an alternative
only if selected in advance with its different error interpretation. Retain
unsuccessful or unavailable registered families in the multiplicity accounting;
report missing tests and use conservative p = 1 for adjustment bookkeeping,
not as an imputed scientific result. Do not shrink the denominator.

A single-family registration is legitimate, but repeated singleton tests do
not provide .05 error control across the research program. If claiming control
across a planned sequence, freeze the full set and correction before its
confirmatory outcomes and process families sequentially within that set.
Otherwise explicitly limit error claims to each registration; future batches
are separate and cannot be pooled into a post-hoc program-wide success claim.
Planning-low remains historical evidence outside any new confirmation set.

## Sequential Chainlink decomposition

Next-phase epic **#201** is a child of #159. Reference
#198/#199 as completed evidence and #200 as the existing offline design; avoid
duplicating or reopening that completed work. Instantiate the following tasks
for one family at a time. Each row supplies a title, dependency, output, and
completion gate suitable for its issue description. Issue completion never
stands in for live authorization.

| Key / proposed task | Depends on | Deliverable and acceptance gate |
|---|---|---|
| P01 — Reconcile baseline and research contract | Existing #198/#199/#200 | Evidence index with input hashes; planning-low conditional result and guard failures preserved; next `hypothesis:low` pilot identified; old five-form wording and interval-half-width/MDE mismatch logged for a new version. Zero calls. |
| P02 — Freeze next-family scope and artifact inventory | P01; prior family's P14 if repeating | Candidate order and structural rule; prior-manifest inventory with hashes; proposed discovery and held-out seed windows; explicit stage labels. No live outcome used to choose forms/seeds. |
| P03 — Audit form capacity and independence | P02 | Versioned census, closure evidence, pre-read hashes, shared-template/dependence assessment, per-form capacity, seed/ID overlap report. Deterministic rebuild; no overlap; unknown closure stated. Reuse #200 audit as evidence, rechecking current manifest coverage. |
| P04 — Classify design and plan discovery | P03 | k and attainable p floor; pilot versus potentially confirmatory classification; discovery registration with fixed N, treatment/route, budgets, stops, paths, and coverage rules. `hypothesis` remains descriptive. |
| P05 — Lock discovery design and record live authorization | P04 | Offline preflight, reviewed lock hash, then separate explicit authorization reference with stage/route/cost scope. Pending authorization blocks P06; this plan is not that authorization. |
| P06 — Collect discovery communication data | P05 | Immutable journal for every planned seed: structural need, emission/silence, ownership, writes/reads, information, rejection/failure reasons, costs. Fixed schedule; no replacement or outcome-based stopping. |
| P07 — Estimate discovery results and prospective feasibility | P06 | Selection report plus any registered exploratory replay; coverage/guard/missingness estimates; variance and effect scenarios; power-based MDE and interval-width table; no causal claim from emission. Any replay here must be separately covered by P05 authorization. |
| P08 — Draft fresh replay registration and multiplicity contract | P07 | New held-out manifests, source/treatment/geometry/protocol hashes, complete hypothesis set, correction, sign-flip assumptions, negative direction, t interval, guard definitions, normalization grid, fixed counts, branch schedule, costs/stops and fresh paths. Check adjusted attainability. For k < 6, label fresh block descriptive replication. |
| P09 — Implement and verify replay preflight offline | P08 | Reuse existing replay/inference modules where valid; fixtures verify branch identity, ownership/exposure, deduplication, hashes, form aggregation, missingness, sensitivity and correction. Failed preflight/missing approval cause zero calls; no artifact overwrite. Resolve old #200 design wording in a new version, not by editing its frozen JSON. |
| P10 — Lock replay registration and record separate live authorization | P09 | Reviewed locked registration and explicit stage-specific live authorization reference. No substitution, fallback route, or inference of approval from a lock. Otherwise leave P11 blocked. |
| P11 — Collect held-out messages and matched replay | P10 | Fixed fresh-seed collection and real/placebo/null requests, full provenance and raw vectors, model/route metadata and costs. No resume, append to an old run, overwrite, seed substitution, paid fallback, or coverage-driven extension. |
| P12 — Validate and compute offline primary inference | P11 | Integrity report, complete-pair and missingness tables for every frozen form, per-form means, equal-form estimate, exact sign-flip p when eligible, companion interval, and registered multiplicity adjustment. No guard filtering or imputation. |
| P13 — Report guards, sensitivity, and information accounting | P12 | Target/mass changes, event/form guard rates, useful uptake, exact versus renormalized vectors, frozen sensitivity grid (default 1e-6/.01/.03/.05), null checks, unique versus gross delivered information, power/MDE limits and decision changes. |
| P14 — Publish family decision and next-family handoff | P13, or terminal stop evidence | Five evidence levels and classification below; full denominator/failure accounting, scope and hashes. Publish negative/descriptive results too. Close with evidence; advance the recorded family order only after this handoff. |

Current execution map: #202 is the first offline task. Discovery authorization
gate #206 blocks collection #207; replay authorization gate #211 blocks held-out
collection/replay #212. Final decision/handoff is #215. #200 remains open as the
existing offline design record, related to #201 together with completed #198
and #199; these evidence links do not require reopening completed work.

Use Chainlink blocking relationships `P02 blocked-by P01`, and so on, as well
as parent/child organization. Copy relevant protocol rules into each live task.
An unmet statistical-capacity gate routes to descriptive work; an unmet
authorization gate blocks live work; an integrity failure stops that run and
routes directly to a terminal P14 report. Do not execute successors merely
because the predecessor was closed with a failure resolution.

Reserve fresh versioned paths such as
`runs/epic-126/next-phase/<family>/<registration-id>/` for audit, manifests,
registration, discovery journal/report, held-out collection journal/report,
replay journal/report, inference, sensitivity, and decision artifacts. These
are proposed paths, not files created by this plan. Preserve raw responses,
normalization metadata, branch request/state hashes, registration/source/
treatment/geometry/protocol hashes, and authorization references. A stopped run
requires a new registration and fresh paths before any later attempt.

## Missingness and decision outputs

Report planned, attempted, emitted, eligible, replayed, valid, complete, and
missing counts by stage, form, and branch, with reasons. Average valid complete
pairs within their frozen forms, regardless of guards. A missing entire form
blocks confirmation of the registered full-form estimand; label any available-
form estimate descriptive. Freeze permissible within-form missingness before
collection and report the resulting complete-case scope and selection risk.
Do not impute, replace seeds, or remove a difficult form after outcomes.

For each family publish structural need, voluntary emission, verified exposure,
entropy reduction, and matched-contrast causal uptake as five separate levels.
Assign one primary decision, with integrity and missingness taking precedence:

- **Invalid due to provenance or treatment-integrity failure:** the intended
  contrast cannot be established; no supported causal claim.
- **Inconclusive due to missingness or insufficient forms:** a planned
  confirmatory design cannot meet its frozen coverage or inference conditions.
- **Descriptive/estimation-only evidence:** the study was deliberately a pilot,
  including the four-form `hypothesis` design; show estimates without promotion
  to confirmation, including for its fresh-seed replication block.
- **Confirmatory support:** a fresh, valid, adequately covered registered
  confirmation meets the adjusted test, negative direction, and registered
  interval criterion. State conditional scope and separately qualify usefulness
  using all guard results; never describe this as proof of H1.
- **No supported entropy reduction:** a valid completed confirmatory design
  does not meet its criterion. Report its interval, power limits, and possible
  positive effects; failure to reject does not establish H0 or equivalence.

The next concrete offline action is P01–P04 for the existing `hypothesis` draft.
Data generation follows only after the relevant registration and separate live
authorization gates. Discovery can inform a future test; it cannot retrospectively
become that test's held-out evidence.
