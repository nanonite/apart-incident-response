# L03 — Legal design classification and outcome-blind discovery design

Task: Chainlink **#221** under **#218** under **#159**. Family `legal:low`,
milestone **L03**, predecessor **#220** (L02, the completed form census),
successor **#222** (L04), with the offline cross-family audit **#227** sitting
between them (`#221 → #227 → #222`). Protocol:
[hypotheses and sequential discovery/confirmation plan](jev-discovery-confirmation-plan.md);
family chain: [legal sequential research chain](jev-legal-task-sequence.md);
program direction: [cross-family entropy program v1 amendment](jev-cross-family-entropy-program-v1.md).

Offline design decision only — **no provider call**, no probe, no live
journal, no registration lock and no authorization inference; a process-wide
audit hook observed **zero network events** while the artifact was assembled.
This task classifies the legal design and fixes an outcome-blind discovery
screen; it is not a registration, and nothing here authorizes collection, a
route, a budget or any successor execution.

Machine-readable artifact:
[`runs/next-phase/legal/jev-legal-p03-design-v1.json`](../runs/next-phase/legal/jev-legal-p03-design-v1.json)
with self-recorded `content_hash`
**`adf52cb7b7d62e532acc0b8f26c000582e4a291767f737558f016fdf9eafed06`**, rebuilt byte-for-byte by
`python -m apart_incident_response.jev_legal_p03_design --repo-root .`
(fail closed on drift).

## 1. Input evidence (recomputed from disk on every build)

Every digest below was recomputed from the bytes on disk; the pins carried
from earlier verified records are checked by prefix and fail closed on drift.

| Input | Role | sha256 (recomputed) |
| --- | --- | --- |
| `docs/jev-discovery-confirmation-plan.md` | research protocol (pin `501e21b6`) | `501e21b6dea760371b0bf368046d8bacd203f6b92f0af754a7955d1f738677f7` |
| `runs/epic-126/replication/jev-replication-form-audit-v1.json` | #200 frozen form-capacity audit (pin `cb529cd6`) | `cb529cd61e0e662bfa19fc4998e89fa59a0bf0d63e14f77498035466d6bce89d` |
| `runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection.jsonl` | #207 terminal P06 journal (pin `4e8de096`) | `4e8de096f2c30a6a36a94a0f79e5f450c2e196123e3eafe1c310a92c4f334c83` |
| `runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection-report.json` | #207 terminal P06 report (pin `3086ceac`) | `3086ceac558ff922bd083db3795f5f1aa5c7127813daba8bfd71ae1fbef09d3c` |
| `docs/jev-hypothesis-low-terminal-decision.md` | #215 terminal family report (pin `89ef2aaf`) | `89ef2aafb5e28f12d0db707499c583d89cdcc490d105c23c3c56b39e11818d0b` |
| `runs/next-phase/legal/jev-legal-p01-evidence-v1.json` | L01 evidence index (pin `b2d07266`) | `b2d0726619f5a18ce1ed5a54c5197d51709b1e0473b58ee129c74592b7b707e3` |
| `docs/jev-legal-p01-baseline.md` | L01 baseline narrative (pin `8926f48d`) | `8926f48d85338163fae0f9434f63c62b380f6402580bb57cd1d35b25d0471870` |
| `docs/jev-legal-task-sequence.md` | legal family task sequence (pin `884b0ed4`) | `884b0ed4329cc47888e797478f8f00b57f7f5c9d679998d154f5a789397d0394` |
| `docs/jev-cross-family-entropy-program-v1.md` | program amendment (2026-09-29) | `d9acace24a0cdbfc9a41e331b1fd422f07f22e3fc01480e6408af78d9de4be05` |
| `runs/next-phase/legal/jev-legal-p02-form-census-v1.json` | L02 census (#220), predecessor handoff | `4bffa5cda2433a81efb41025f42fdd82c585c41798ff2c55e9d853aa45681d24` |
| `docs/jev-legal-p02-capacity.md` | L02 capacity narrative (#220) | `25fac868d502b05ede479fa7e68161f8f4fd4db33267a0f01d710f2d0adec2fa` |

Generator and hashing sources are pinned the same way: `task_families.py`
`b399bb15…`, `jev_replication_preregistration.py` `d91c0e3a…`,
`jev_replay.py` `5c1c2dfd…`, `jev_replay_preregistration_v4.py` `18213126…`,
`jev_choice.py` `9ce9920e…`, `jev_form_census.py` `a1a5839a…`,
`jev_legal_form_census.py` `216eecde…`.

The L02 census's own self-recorded `content_hash`
`b01aa7de17cb21d18b7dd83a12764da7ff265a18b7089f2c2be7eaaf6b72b775`
recomputes from its bytes; its 35 checks all still pass, its recorded network
audit is zero, and the L02 handoff names this task (L03, issue 221). The L01
artifact's hashes also still recompute, so the terminal #200/#207/#215 files
are byte-identical across L01, L02 and L03.

## 2. k, the exact sign-flip floor, and declared multiplicity

L02 observed **k = 4** independent prompt forms, saturated by 32 seeds in
both fresh windows and *proven* closed by generator-level exhaustive
enumeration (the form is a function of `(bit0, bit2)` of the target, which has
four values). This task rebuilds that k from the generator over the pinned
discovery window and obtains the same four form ids; k is a recorded finding,
not a re-decision.

The exact two-sided sign-flip floor is derived from k alone:

```text
2/2^k = 2/2^4 = 2/16 = 1/8 = 0.125
```

`0.125 > 0.05`, so **no dichotomous rejection at α = 0.05 is attainable at any
effect size on this generator version**, before any multiplicity adjustment.
Ties and zero effects can only make the attainable p larger. Attainable floor
by k: 4 → 0.125, 5 → 0.0625, 6 → 0.03125, 7 → 0.015625, 8 → 0.0078125,
9 → 0.00390625.

Declared multiplicity only demands *more* forms. For a Holm family of m
hypotheses the first ordered p must be at most `.05/m`; the smallest k whose
best-case floor reaches that threshold:

| Registered family count m | Holm first-step threshold | smallest k with attainable floor |
| --- | --- | --- |
| 1 (single registration) | 1/20 = 0.05 | 6 |
| 2 | 1/40 = 0.025 | 7 |
| 7 (breadth target) | 1/140 ≈ 0.00714286 | 9 |
| 8 (breadth target) | 1/160 = 0.00625 | 9 |

Legal:low's floor 0.125 sits above every threshold in this grid, so **no
declared multiplicity rule can make this version confirmatory**. Distinct
seeds never add form units, and pooling legal with other families to obtain a
smaller p-value is forbidden; a cross-family claim would need its own
registered estimand and error contract. Planning-low and hypothesis-low
outcomes — and the motivating paper — supply **no legal-family effect-size
prior**; nothing here is a power claim.

## 3. Classification: descriptive discovery (not no-go, not confirmatory)

The decision rule is deterministic and ordered; it is evaluated in the
artifact with a full trace:

1. structural gate fails → **no_go** (write a no-go design decision; never
   fabricate a runnable registration);
2. capacity gate fails → **no_go**;
3. floor `2/2^k` > 0.05 (k < 6) → **descriptive_discovery**;
4. k ≥ 6 → potentially confirmatory design, still subject to every other gate,
   declared multiplicity, coverage and a separate L07 authorization.

**Structural gate — pass.** L02 proves closure of the finite form space;
`finalizer_needs_peer`, `eligible` and the closed finite solution set hold for
all 512 instances in each window; every instance carries an authoritative
B-owned claim worth 1.0 bit (`ExactInformationEvaluator`, A's feasible set
2 → 1); the placebo claim is A-owned and inert (`I_m = 0.0`); the receiver
option set (the eight `disposition-0..7` labels) is fixed and identical
across forms.

**Capacity gate — pass.** Per-form discovery-window capacity is
129 / 126 / 121 / 136 seeds (scarcest cell across both windows: 105), every
form clears the selection quantum `INSTANCES_PER_FORM = 4`, the recorded
discovery window is 88000–88511, the closure-probe window 89000–89511 stays
unselectable, and L02 fixed no held-out window.

**Decision: `descriptive_discovery`.** The family is runnable as a descriptive
pilot — it is *not* a no-go, because both gates pass, and it is *not*
potentially confirmatory, because the attainable floor 0.125 exceeds α = 0.05
at any effect size. A potentially confirmatory design needs k ≥ 6 before
declared multiplicity, fresh data, defensible exchangeability, a registered
error criterion and a separate authorization. The classification binds this
four-form generator version; a redesigned generator would be a new protocol
boundary with its own audit, and this task performs no redesign.

The **registered legal estimand is preserved unchanged**: H0 `Delta = 0`,
H1 `Delta < 0`, `Delta` the equal-weight form mean of real-minus-placebo
entropy on the fixed eight-option set, tested by the exhaustive two-sided
exact cluster sign-flip plus a negative-direction requirement (never a silent
one-sided switch), with the companion form-mean t interval labeled as an
interval half-width and not a power-based MDE. Guards never filter the
estimate.

## 4. Exchangeability limits (stated, not hidden)

The four forms are hash-distinct but **template-identical** (template hash
`35b03db195dd6aed416005b5fa3f985e08572c66d058fed6572d9bff975ef6f6`): they
share model, question, instructions, the `disposition-0..7` options and the
state structure, differing only in `state.clues` — a complete 2×2 factorial
over `(bit0, bit2)` and the *entire* finite form space, not a sample from a
larger prompt population. A template-level effect would shift all four forms
together, so form-level sign flips are **assumption-dependent**: the exact
two-sided p is reported as a descriptive statistic with the exchangeability
assumption labeled, never as assumption-free inference. Hash-distinctness
does not establish statistical independence, and more seeds within a form
change neither k nor exchangeability. The closed form space also forbids the
population reading: `E_f` is a uniform average over the registered finite
forms.

## 5. Outcome-blind fixed-N discovery screen

Selection is a pure function of recorded capacity and the pinned windows —
no outcome, emission, guard or entropy value is ever consulted
(`consulted_outcomes: []`).

- **Window:** L02 discovery window **88000–88511** (512 seeds). The
  closure-probe window 89000–89511 is never selectable; the hypothesis
  85000–87511 span and every documented prior range stay untouched.
- **Rule:** the first `s*` seeds per form in ascending seed order, fixed N,
  no outcome-based stopping, where `s*` is derived in §6.
- **Screen size:** `s* = 4` per form, **fixed N = 16** (4 forms × 4 seeds).
- **Manifest** (rebuilt from the generator; 16 unique ids, all inside the
  window and disjoint from every prior seed/ID):

| form id | seeds | instance ids |
| --- | --- | --- |
| `309706db…` | 88008, 88020, 88026, 88031 | `legal-000157c8`, `legal-000157d4`, `legal-000157da`, `legal-000157df` |
| `3ca02230…` | 88006, 88009, 88011, 88017 | `legal-000157c6`, `legal-000157c9`, `legal-000157cb`, `legal-000157d1` |
| `935f8414…` | 88004, 88005, 88010, 88013 | `legal-000157c4`, `legal-000157c5`, `legal-000157ca`, `legal-000157cd` |
| `bb6fcd3f…` | 88000, 88001, 88002, 88003 | `legal-000157c0`, `legal-000157c1`, `legal-000157c2`, `legal-000157c3` |

Spare capacity (121−4 … 136−4 seeds per form) is headroom for coverage
reporting only; it never licenses seed replacement, replenishment or extra
forms. No held-out/confirmation window is chosen here; a later window must
use the L02 inventory-first rule before its own outcomes exist.

## 6. Request/cost scenarios and stop conditions (planning arithmetic only)

Every count is retry-inclusive (×3 physical per logical call, `max_retries`
2) under the original L4X shape: 4 writer calls + 1 receiver call per
instance; the optional exploratory replay is ≤ N events × 3 branches. The
rate card (`0.00067584`/writer call, `0.000344064`/receiver call) is carried
from the #200/#205 registration as arithmetic precedent — **the legal family
has no registered or authorized route**, and the stopped hypothesis Ling route
carries nothing forward.

| Scenario (s per form) | N | Collection worst case | Replay worst case | Program worst case | Feasible? |
| --- | --- | --- | --- | --- | --- |
| s = 2 | 8 | $0.073138176 | $0.024772608 | $0.097910784 | no — below the `INSTANCES_PER_FORM = 4` quantum |
| **s = 4** | **16** | **$0.146276352** | **$0.049545216** | **$0.195821568** | **yes — selected** |
| s = 8 | 32 | $0.292552704 | $0.099090432 | $0.391643136 | no — exceeds the $0.20 collection and $0.30 program ceilings |

Selection rule: `s*` is the smallest size that is at least the selection
quantum, at most the scarcest per-form capacity, and whose worst-case
collection, replay and program costs fit the planning ceilings ($0.20 /
$0.10 / $0.30). The rule is a pure function of capacity and the rate card.
L04 must register the legal route, model, token budget, cost rates,
retry-inclusive request and dollar caps and stop rule as new registration
fields; only L07 may authorize any request.

**Stop conditions:** request or cost cap before the next call; all fixed-N
instances attempted (fixed schedule; completion ends the block); model or
endpoint drift; protocol-key, normalization-policy or option-set identity
drift; registration/source/treatment/geometry hash drift; malformed,
non-finite, negative or option-mismatched vectors; hard normalization
deviation above the registered ceiling or argmax shift after normalization;
writer terminal errors (including `truncated_output`, the L01-diagnosed
output-cap classification); two consecutive terminal provider failures; output
collision; any audit exception that breaks provenance or treatment integrity.
A stop keeps the whole fixed manifest as an immutable journal — including
failure and not-attempted rows — and routes to a terminal report; resuming
requires a new registration and fresh paths.

## 7. Prospective coverage rule (frozen from capacity before collection)

- Permissible within-form missingness: up to 3 of 4 seeds per form missing;
  **at least 1 complete instance per form**.
- Complete-case scope: planned instances with all required fields
  (structural need, emission or recorded silence, verified B ownership,
  accepted board write followed by A read exposure, information), reported by
  stage, form and branch with reasons.
- Discovery screen requirements: every registered form must have at least one
  instance with structural need, at least one with voluntary emission or
  recorded silence, and at least one with verified B ownership plus write/read
  exposure.
- A missing entire form blocks the registered full-form estimand; label any
  available-form estimate descriptive. No imputation, no seed replacement, no
  form removal after outcomes, no replenishment from spare capacity.
- Selection risk: if within-form missingness is not random, the complete-case
  estimate may be biased; the rule freezes the missingness before collection
  and reports the resulting scope.

Proposed live paths (currently absent, created by nothing here):
`runs/next-phase/legal/jev-discovery-v1/jev-discovery-collection.jsonl`,
`…/jev-discovery-collection-report.json`,
`…/jev-exploratory-replay.jsonl`, `…/jev-exploratory-replay-report.json`.
Fresh paths only: no resume, no append, no overwrite, no path overrides.

## 8. Constraints and non-claims

The artifact records fourteen constraints with their basis and consequence,
including: no provider call of any kind until the separate L07 gate; a failed
or stopped predecessor never authorizes its successor; frozen #200 and
terminal #207/#215 files preserved byte-identically; the registered estimand
and two-sided test preserved; seeds never counted as forms; no effect-size
prior from planning-low or hypothesis-low; no silent generator redesign; no
re-ordering of the frozen historical queue (`hypothesis → legal → lexicon →
poetry → reference`); the motivating paper is not Jev entropy evidence;
#227's audit precedes #222 and grants no authorization; k = 4 cannot become
confirmatory by adding seeds or pooling families; L04 registers route, model,
budget, caps and stops as new fields; selection stays outcome-blind; no
held-out window is chosen here.

Non-claims include: no confirmatory or significance-style claim; no
population generalization; no effect-size prior; seeds are not forms; no
cross-family pooling; no route, model or budget approval; capacity headroom is
not permission to replace missing seeds.

## 9. Checks (all offline, zero provider calls)

- **40/40** named checks pass in the artifact, `provider_calls: 0`, and
  `network_audit` records **0 events** under
  `sys.addaudithook(socket., urllib., http.client., ftplib.)`.
- Deterministic rebuild: the artifact rebuilds **byte-for-byte** from the
  frozen inputs, the L02 census and the generator; verification fails closed
  on drift of any input pin, k, floor, gate, manifest or classification.
- k is independently rebuilt from the generator over the pinned window and
  must equal L02's form set; the floor is recomputed from k as 2/16 = 0.125;
  the multiplicity grid is recomputed from exact fractions.
- Every manifest entry is re-derived from the generator (form assignment and
  instance id), sits inside 88000–88511, and is checked against the documented
  prior seed ranges and the reserved hypothesis span.
- Scenario costs recompute from the rate card; only s = 4 is feasible, and
  the selection rule must return it.
- Frozen #200/#207/#215 inputs, the L01 evidence index, the L02 census and
  the L01/L02 narratives are byte-identical before and after the build.
- Focused validation: `tests/test_jev_legal_p03_design.py` recomputes the
  floor, the manifest, the scenario arithmetic and the decision trace
  independently of the module, patches `urllib.request.urlopen` with a raising
  stub for the whole build, and fails if any network event fires, any frozen
  input changes byte-for-byte, or any proposed live path exists.

## 10. Handoff to L04 (#222) and #227

L03 closes with evidence paths, hashes, checks, limitations and this
handoff. L04 receives: the `descriptive_discovery` classification with its
decision trace, k = 4 and the 0.125 floor, the two verified gates, the
fixed-N = 16 outcome-blind screen and manifest, the scenario comparison and
stop conditions, and the prospective coverage rule.

- **#222 follows #227**, not this task: the offline cross-family capacity and
  expansion audit (`#227`) must complete first (`#221 → #227 → #222`). Its
  scope — auditing every remaining family across predeclared cells and
  specifying additional families as prospective full task designs with
  authentic peer-owned information, matched inert placebos and measurable
  receiver uncertainty, never microbenchmarks — is recorded in the artifact
  and is **not performed here**. Its outcome can demand a new program version
  but cannot mutate this decision, the L02 census or an eventual L04 lock, and
  it grants no authorization.
- L04 must produce a fresh legal discovery registration **or an explicit
  no-go**; this design decision is input, never a registration. It registers
  route, model, token budget, cost rates, retry-inclusive request and dollar
  caps, stop rules and fresh paths as new registration fields.
- No provider call is authorized by this artifact; **L07** supplies the
  separate, scope-bound user authorization (exact stage, route, request and
  dollar caps) and the loop stops there.
- #221 stays blocked until the plugin records it closed after reviewer
  approval; issue creation, this document and any credential imply no
  authority. A failed or stopped predecessor never authorizes its successor,
  and the frozen hypothesis artifacts stay untouched.
