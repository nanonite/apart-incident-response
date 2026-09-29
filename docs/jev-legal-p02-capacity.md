# L02 — Legal form capacity, independence and fresh-window audit

Task: Chainlink **#220** under **#218** under **#159**. Family `legal:low`,
milestone **L02**, predecessor **#219** (L01, closed with the pinned baseline),
successor **#221** (L03). Protocol:
[hypotheses and sequential discovery/confirmation plan](jev-discovery-confirmation-plan.md);
family chain: [legal sequential research chain](jev-legal-task-sequence.md).
Offline audit only — **no provider call**, no probe, no live journal, no
registration lock and no authorization inference; a process-wide audit hook
observed **zero network events** while the census was assembled. This task
closes with evidence only; nothing here authorizes collection, a route, a
budget, a lock or any successor execution.

Machine-readable census:
[`runs/next-phase/legal/jev-legal-p02-form-census-v1.json`](../runs/next-phase/legal/jev-legal-p02-form-census-v1.json)
with self-recorded `content_hash`
**`5fee9d0173dbdcc8ea3f5783f5ee578f1a0cf697742f8de7c4d71d0bcccfb6f2`**, rebuilt byte-for-byte by
`python -m apart_incident_response.jev_legal_form_census --repo-root .`
(fail closed on drift).

Frozen input pins (recomputed from disk on every build; the expected prefixes
come from the #219/#215 task text and are pins, never hashes):

| Input | Role | sha256 (recomputed) |
| --- | --- | --- |
| `docs/jev-discovery-confirmation-plan.md` | research protocol (pin `501e21b6`) | `501e21b6dea760371b0bf368046d8bacd203f6b92f0af754a7955d1f738677f7` |
| `runs/epic-126/replication/jev-replication-form-audit-v1.json` | #200 frozen form-capacity audit (pin `cb529cd6`) | `cb529cd61e0e662bfa19fc4998e89fa59a0bf0d63e14f77498035466d6bce89d` |
| `runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection.jsonl` | #207 terminal P06 journal (pin `4e8de096`) | `4e8de096f2c30a6a36a94a0f79e5f450c2e196123e3eafe1c310a92c4f334c83` |
| `runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection-report.json` | #207 terminal P06 report (pin `3086ceac`) | `3086ceac558ff922bd083db3795f5f1aa5c7127813daba8bfd71ae1fbef09d3c` |
| `docs/jev-hypothesis-low-terminal-decision.md` | #215 terminal family report (pin `89ef2aaf`) | `89ef2aafb5e28f12d0db707499c583d89cdcc490d105c23c3c56b39e11818d0b` |
| `runs/next-phase/legal/jev-legal-p01-evidence-v1.json` | L01 predecessor evidence index (#219) | `b2d0726619f5a18ce1ed5a54c5197d51709b1e0473b58ee129c74592b7b707e3` |
| `docs/jev-legal-p01-baseline.md` | L01 baseline narrative (#219) | `8926f48d85338163fae0f9434f63c62b380f6402580bb57cd1d35b25d0471870` |
| `docs/jev-legal-task-sequence.md` | legal family task sequence (#218) | `884b0ed4329cc47888e797478f8f00b57f7f5c9d679998d154f5a789397d0394` |

The L01 artifact's own 19 checks all still pass, its recorded network audit is
zero, and every input hash L01 pinned recomputes from the bytes on disk, so the
terminal #200/#207/#215 files are byte-identical across L01 and L02.

## 1. Prior-manifest inventory (performed first, before any window)

The inventory is the first step of the build, by construction: the windows in
§2 are a pure function of it, so no outcome and no manual choice can enter
them.

- **Scan scope:** every `runs/**/*.json` and `runs/**/*.jsonl` artifact
  outside this chain's own namespace, discovered by an explicit directory walk
  so that unlistable directories and unreadable files surface as exceptions
  instead of silently disappearing.
- **Coverage:** 1074 manifests discovered, **1069 read**, 5 unreadable, and
  `runs/next-phase/legal/**` (this chain's outputs, including the L01 evidence
  index) skipped at walk time.
- **Instance ids found:** **535** (hypothesis 149, planning 153, reference 98,
  legal 45, lexicon 45, poetry 45), sha256
  **`aafdd077730bd057df6746978acbd05dafdc683aebcdf43b5f516fbffb0baf14`**.
- **Prior legal instance ids:** **45** — `legal-00000065`/`legal-00000066`
  (seeds 101, 102, discovery-145 extended screen) plus seeds 16800–16819,
  16900–16919 and 17000–17002 (epic-126 channel audit, four-family need screen
  and preregistered manifest). All 45 are outside both fresh windows.
- **Seeds found in accessible manifests:** **1965**, min 1, max **87511**,
  sha256 **`1952e7113d4f065c39157f4ab811aa20fde9a4a78bed6ee39ca3bac54cda3d6d`**,
  stored as exact run-length ranges in the census.
- **Documented prior seed ranges** (from the frozen generator constants):
  16000–17104, 39000–39001, 41000–41001, 70000–70016, 71000–71016,
  72000–72016, 73000–73016, 74000–74016, 75000–75255, 80000–80016.
- **Reserved hypothesis windows, never reusable here:** 85000–85511,
  86000–86511, 87000–87511 (span 85000–87511).
- **Prior seed union** (accessible manifests ∪ documented ranges ∪ reserved
  windows): **3152** seeds, max **87511**, sha256
  **`c4c55096579e341add56ba75df56739c458d2e5e46aece1104334ec0e549f2d3`**.

**Exceptions — audit exceptions, never empty sets.** 20 locations could not be
read; their contents are *unknown*, are recorded in the census and are never
treated as an empty set or as "no overlap":

- Unreadable files (5): `runs/container-isolation.json`,
  `runs/t1-container/matrix.json`, `runs/t1-container/s0001.json`,
  `runs/t1-container-retry/matrix.json`, `runs/t1-container-retry/s0001.json`.
- Unlistable directories (15): `runs/container-harness/`,
  `runs/codex-c0/codex-c0-C0/`, `runs/opencode-go-container/`,
  `runs/opencode-go-container-retry/`, `runs/opencode-qwen-container/`,
  `runs/openrouter/pilot-container/`, `runs/openrouter/pilot-container-2/`,
  `runs/openrouter/pilot-container-3/`, `runs/openrouter/pilot-container-4/`,
  `runs/t1-container/s0001-C0/`, `runs/t1-container/s0001-C1/`,
  `runs/t1-container/s0001-C2/`, `runs/t1-container-retry/s0001-C0/`,
  `runs/t1-container-retry/s0001-C1/`, `runs/t1-container-retry/s0001-C2/`.

**Stated exclusions (scope decisions, recorded not silent).**
`runs/next-phase/legal/**` (this chain's own outputs, so that later legal-chain
artifacts recording these windows cannot perturb the rebuild; the only prior
file there, the L01 evidence index, is hash-pinned above and contains
hypothesis-window seeds covered by the reserved ranges);
`.chainlink/issues.db` (mutable task-tracker state rewritten by the plugin on
every issue event, not a run manifest);
`docs/**`, `src/**`, `tests/**` and root markdown (narrative and source files,
not run manifests — they reference ids that live in the scanned manifests).

## 2. Fresh windows, chosen offline after the inventory

Rule (fixed in advance, applied to the completed inventory): start at the first
1000-multiple strictly above the largest prior seed — 87511 → floor **88000** —
then take the first 512-seed candidate per role sharing no seed with the
inventory, stepping by 1000 so consecutive windows are disjoint by
construction. Zero candidates had to be skipped.

| Role | Window | Seeds | Notes |
| --- | --- | --- | --- |
| discovery | **88000–88511** | 512 | the only window a later registered block may select from |
| closure probe | **89000–89511** | 512 | independent; offline closure evidence only; **no seed may ever be selected from it** |

Both windows are disjoint from the prior seed union (0 overlapping seeds),
disjoint from each other, and **never touch the hypothesis 85000–87511 span**;
no hypothesis instance id or output path is reused (`jev-form-census-v1.json`,
the #200 audit/registration, the #207 journal/report and the P02/P04/P05
next-phase files all stay untouched, and this census writes only to
`runs/next-phase/legal/jev-legal-p02-form-census-v1.json`). The rebuilt ids are
`legal-000157c0`…`legal-000159bf` (discovery) and
`legal-00015ba8`…`legal-00015da7` (closure probe): **1024 unique ids**.

L02 fixes only these two windows. **No held-out/confirmation window is chosen
here**; any later held-out window must be chosen by this same inventory-first
rule before its own outcomes exist, and no seed may be drawn from either window
before a registered gate allows it.

## 3. Census: form count and per-form capacity (findings, not assumptions)

Both fresh windows were rebuilt from the generator
(`generate_instance("legal", seed, N, LOW)`). Every window yields exactly
**k = 4 distinct prompt forms**, saturated by 32 seeds and unchanged at the
64/128/256/512 growth checkpoints in **both** windows:

```text
[32, 4], [64, 4], [128, 4], [256, 4], [512, 4]
```

The four legal form ids (form set hash
`ad2f6bee676229527b067912c4259f8fb7f9e4e0e989685d5afa8613f48e5633`):

```text
309706db278f790720bf76f19b248ff43e5eaf178d250cd60f9defccfb7b00c9
3ca0223020c4113d4a8147d3b611c414248eb64369497f9a5f6a4a7f78a0df9f
935f84146a383fa027fb55446dd011c55d81f32151477d56ca85d7e155b8c809
bb6fcd3ffb95e480cd779f380549bfca873e86b8c313825d97d14c6ea7b6ca07
```

**Per-form capacity** (seeds per form per window):

| form id | discovery 88000–88511 | closure probe 89000–89511 | total |
|---|---|---|---|
| `309706db…` | 129 | 123 | 252 |
| `3ca02230…` | 126 | 143 | 269 |
| `935f8414…` | 121 | 141 | 262 |
| `bb6fcd3f…` | 136 | 105 | 241 |
| **all forms** | **512** | **512** | **1024** |

The scarcest cell still holds 105 seeds, far above the existing selection
quantum (`INSTANCES_PER_FORM = 4`), so a fixed-N block is comfortably
satisfiable in either window. Capacity counts are seeds, not independent units:
**distinct seeds never add form units**, and the experimental unit remains the
prompt form.

## 4. Closure evidence: proven, not merely observed

**Status: closed — proven by generator-level exhaustive enumeration of the
finite form space**, with the disjoint closure-probe window as corroboration
(observed saturation alone would not have established closure).

**Argument.** The form id is the sha256 of the model-visible ISO pre-read
request body. For `legal` at LOW complexity and regime N that body is a
deterministic function of `(bit0, bit2)` of the target: the state carries only
A's private clues `fictional_fact_0`/`fictional_fact_2` (B's
`fictional_fact_1` never appears in the pre-read body) while model, question,
instructions and the eight `disposition-0..7` options are fixed. `(bit0, bit2)`
has exactly four values, so at most four forms can ever be produced.

**Exhaustive enumeration** through the real generator code path (all eight
`disposition-0..7` targets, all four pairs realized):

| target | bit0 | bit1 | bit2 | form id | first discovery seed |
|---|---|---|---|---|---|
| disposition-0 | 0 | 0 | 0 | `309706db…` | 88041 |
| disposition-1 | 1 | 0 | 0 | `bb6fcd3f…` | 88001 |
| disposition-2 | 0 | 1 | 0 | `309706db…` | 88008 |
| disposition-3 | 1 | 1 | 0 | `bb6fcd3f…` | 88000 |
| disposition-4 | 0 | 0 | 1 | `935f8414…` | 88013 |
| disposition-5 | 1 | 0 | 1 | `3ca02230…` | 88006 |
| disposition-6 | 0 | 1 | 1 | `935f8414…` | 88004 |
| disposition-7 | 1 | 1 | 1 | `3ca02230…` | 88009 |

The eight targets realize exactly **4 distinct forms**, grouped by
`(bit0, bit2)`: `(0,0)←{0,2}`, `(1,0)←{1,3}`, `(0,1)←{4,6}`,
`(1,1)←{5,7}`. The form is a function of `(bit0, bit2)` (computationally
verified: each pair maps to exactly one form), the enumeration matches the form
set observed in both windows, and the upper bound is four — closed.

**Observed saturation (corroborating).** The independent closure-probe window
89000–89511 adds **0** new forms; both windows yield the same four forms.

**Residual unknowns (stated, not hidden):**

- The proof covers only this generator configuration (legal family, LOW
  complexity, regime N, Jev ISO pre-read); it does not extend to other
  families, complexities, regimes or receiver conditions.
- Closure of the form space does not establish statistical independence of the
  four forms; they share one template and differ only in `state.clues` (§7).
- The census is a deterministic offline artifact; it contains no live outcome
  and authorizes no collection.

## 5. Pre-read, option and state hashes

Form identity is `jev_replay.prompt_form_id(jev_replay_preregistration_v4.pre_read_body(...))`
(the `pre_read_request_body_hash` equals the form id); state and option-set
hashes come from `jev_replay.canonical_hash`; branch hashes come from
`jev_replication_preregistration.branch_hashes`. One representative instance
per form (first discovery-window seed):

| form id | representative | seed | `pre_read_state_hash` | `option_set_hash` | real / placebo claim |
|---|---|---|---|---|---|
| `309706db…` | `legal-000157c8` | 88008 | `b050087e3479be5da0fac7aa6fe5bebe1f3efca82cb81e608bdddcecfa70cb5d` | `04740042a5ee268940966b919c1fed29eb8a42503de2973bbc39178ae7b9bcb6` | `fictional_fact_1=1` / `fictional_fact_0=0` |
| `3ca02230…` | `legal-000157c6` | 88006 | `9e7244cafb4f9596824d9f551a7b80a985d5b0638d63efbd9d9184dd0413601b` | `04740042a5ee268940966b919c1fed29eb8a42503de2973bbc39178ae7b9bcb6` | `fictional_fact_1=0` / `fictional_fact_0=1` |
| `935f8414…` | `legal-000157c4` | 88004 | `b159155ca5daee27b4a8c153563076eb1cf97a656b1585f289c792e69f58deb6` | `04740042a5ee268940966b919c1fed29eb8a42503de2973bbc39178ae7b9bcb6` | `fictional_fact_1=1` / `fictional_fact_0=0` |
| `bb6fcd3f…` | `legal-000157c0` | 88000 | `5b26e40d9c80c6a5b311d265ddd2642e65e276eb33cafb1fa598c236a904e4f0` | `04740042a5ee268940966b919c1fed29eb8a42503de2973bbc39178ae7b9bcb6` | `fictional_fact_1=1` / `fictional_fact_0=1` |

The option set is the same eight `disposition-0..7` labels for every form, so
`option_set_hash` is identical across forms while `pre_read_state_hash`
separates them. Each record also carries the real/placebo/null
`branch_request_hashes` and `branch_state_hashes`; for `bb6fcd3f…`:

```text
branch_request_hashes  real d59eedda…  placebo cd065e10…  null 986f6c0d…
branch_state_hashes    real 0d6ee0e8…  placebo 8fe87e9c…  null 59b905c3…
```

(the artifact stores the full 64-character values, plus the four records above;
the test suite recomputes every hash from the generator and fails closed on
drift).

## 6. A-finalizer peer need and the authoritative B-owned informative claim

Structural preconditions recomputed over each fresh window (generator
structure, never an outcome):

| quantity | discovery | closure probe |
|---|---|---|
| closed finite solution set | true | true |
| `finalizer_needs_peer` (all 512 instances) | true | true |
| `informative_b_owned_claims` | 512 | 512 |
| B→A information per claim | `[1.0]` bit | `[1.0]` bit |
| A clues / B clues per instance | 2 / 1 | 2 / 1 |
| structural `eligible` | true | true |

For every form the A-finalizer's own clue-consistent set holds **2** candidates
while the joint set holds **1**, so `len(clue_consistent_a) > len(joint)`
(`finalizer_needs_peer`) and the channel is complete
(`pooled == joint`, `both_agents_needed`): A cannot close the task without the
peer's clue.

The informative claim is **authoritative** in the required sense — ownership is
read from the family oracle (`instance.claim_owner` returns `B`, A does not
hold the claim before the message) and the information value from
`ExactInformationEvaluator`, never from a writer assertion:

- real claim `fictional_fact_1` = B's bit, status `accepted`, **I_m = 1.0 bit**
  (A's feasible set 2 → 1);
- placebo claim `fictional_fact_0`/`fictional_fact_2` = A's own clue, owner
  `A`, **I_m = 0.0 bit** — inert, feasible set unchanged.

## 7. Shared-template dependence assessment

The four pre-read bodies are **identical except for `state.clues`**: they share
the model (`jev-1.13.0`), question id (`candidate`), the instructions, the eight
options (`disposition-0`…`disposition-7`) and the state structure
(`family`/`complexity`/`agent_id`). The common template hashes to
`35b03db195dd6aed416005b5fa3f985e08572c66d058fed6572d9bff975ef6f6`. The only
varying field is `state.clues = (bit0, bit2)` of the target:

| form id | bit0 | bit2 | clues |
|---|---|---|---|
| `309706db…` | 0 | 0 | `["fictional_fact_0=0", "fictional_fact_2=0"]` |
| `935f8414…` | 0 | 1 | `["fictional_fact_0=0", "fictional_fact_2=1"]` |
| `bb6fcd3f…` | 1 | 0 | `["fictional_fact_0=1", "fictional_fact_2=0"]` |
| `3ca02230…` | 1 | 1 | `["fictional_fact_0=1", "fictional_fact_2=1"]` |

The four forms are a **complete 2×2 factorial over `(bit0, bit2)`** — the
entire finite form space, not a sample from a larger prompt population. They are
**hash-distinct but not independent prompts**: a template-level effect would
shift all four forms together, so form-level sign flips are
**assumption-dependent** — the exact two-sided sign-flip p is reported as a
descriptive statistic with the exchangeability assumption labeled, never as
assumption-free inference. The legal form ids are also disjoint from the four
hypothesis form ids, so no frozen #200 form is reused.

## 8. Seed/ID overlap report

- `selected`: 1024 instance ids, **1024 unique**, seeds sha256
  `3fd851f847af5be1b67aaee5e381c764133c20a7c772b97332ad22089c51379f`,
  per-window id/seed digests recorded in the artifact.
- `selected_ids_overlapping_prior`: **[]** ·
  `selected_seeds_overlapping_prior`: **[]** ·
  `selected_legal_instance_ids_overlapping_prior_legal_ids`: **[]** ·
  `discovery_vs_closure_probe_*_overlap`: **[]** ·
  `reserved_hypothesis_window_overlaps`: **[]** ·
  `documented_seed_range_overlaps`: **[]**
- `disjoint_from_all_accessible_prior_artifacts`: **true**, qualified by
  `inaccessible_locations_remaining: 20` — the 20 exceptions of §1 stay open
  audit exceptions and are never counted as empty sets.
- Output path is fresh: `runs/next-phase/legal/jev-legal-p02-form-census-v1.json`
  is not any hypothesis output path and never overwrites an existing file
  (exclusive create).

## 9. Capacity consequence (classification belongs to L03)

With **k = 4** the attainable exact two-sided sign-flip floor is 2/2⁴ =
**0.125 > 0.05**, so no dichotomous rejection at α = 0.05 is attainable at any
effect size on this family, and adjusted multiplicity can only demand more
forms (`k < 6`). H0: Delta = 0; H1: Delta < 0; Delta is the equal-weight form
mean of real-minus-placebo entropy. The formal pilot-versus-confirmatory
classification, attainability grid and outcome-blind discovery design are
**L03 (#221)**'s deliverable; guards never filter an estimate; planning-low and
hypothesis-low outcomes supply **no legal-family effect-size prior**; and no
outcome, emission or entropy value entered any selection here.

## 10. Checks (all offline, zero provider calls)

- **35/35** named checks pass in the census artifact, `provider_calls: 0`, and
  `network_audit` records **0 events** under
  `sys.addaudithook(socket., urllib., http.client., ftplib.)`.
- Deterministic rebuild: the census rebuilds **byte-for-byte** from the
  generator and the current disk state, and verification **fails closed on
  drift** of any input pin, source hash, window choice or form set.
- Frozen #200 and terminal #207/#215 inputs, the L01 evidence index and the
  L01 baseline are byte-identical before and after this build.
- Inventory checks: prior-manifest inventory completed before window choice,
  20 inaccessible locations recorded as audit exceptions, stated exclusions
  recorded rather than silently dropped.
- Window checks: derived after inventory, disjoint from the prior seed union,
  discovery/probe disjoint, hypothesis 85000–87511 never reused, output path
  fresh.
- Content checks: unique ids, no seed/ID overlap, form counts agree across
  windows and enumeration, closure proven with all eight targets enumerated,
  per-form capacity sums to 512/512/1024, pre-read/option/state/branch hashes
  present for every form, `finalizer_needs_peer` true everywhere,
  B-owned claim informative and placebo inert, shared template identical except
  `state.clues`.
- Focused validation: `tests/test_jev_legal_p02_form_census.py` recomputes the
  census, the overlap sets and every form hash independently of the module,
  patches `urllib.request.urlopen` with a raising stub for the whole build, and
  fails if any network event fires or any frozen input changes byte-for-byte.

## 11. Handoff to L03 (#221)

L02 closes with evidence paths, hashes, checks, exceptions and this handoff.
L03 receives: the completed prior-manifest inventory and its 20 exceptions, the
two fresh windows 88000–88511 and 89000–89511 with their per-form capacity,
the **k = 4** form set with the generator-level closure proof, the shared-
template/dependence assessment and the 0.125 attainable floor. #221 stays
blocked until the plugin records #220 closed after reviewer approval; issue
creation, this document and any credential imply no authority. A predecessor
closed as failed does not authorize successor execution, no provider call is
authorized until the separate L07 gate, and nothing here authorizes collection,
a registration lock or a live run.
