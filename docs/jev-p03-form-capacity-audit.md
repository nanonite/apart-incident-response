# P03 — Audit form capacity and independence

Task: Chainlink **#204** under **#201** under **#159**. Offline audit only —
no provider call, no collection, no registration lock, no live run.
Protocol: [hypotheses and sequential discovery/confirmation plan](jev-discovery-confirmation-plan.md).
Family: `hypothesis:low` (the next-family pilot frozen in P02). This task
closes with evidence only; nothing here authorizes collection, registration
locking, or any successor execution.

Machine-readable census:
[`runs/next-phase/jev-form-census-v1.json`](runs/next-phase/jev-form-census-v1.json)
with self-recorded `content_hash`
**`ee0ba3a1714828b3e39834280a0a2eb7850f1cc0526463eb59d3bc4b7026fe14`**.
The record lives outside `runs/epic-126/` so the frozen #200 audit's
byte-reproducibility (which scans `runs/epic-126/**`) is preserved.

Frozen input pins (recomputed from disk at build time; fail closed on drift):
#200 audit `audit_content_hash`
**`5242e9cfa35e3a77c54045475428dd617cf93cb16d464b55ad679adc35f80a83`**,
#200 draft registration `preregistration_hash`
**`ff186a066e6af093ecc383e668d948bdca7c1ef8f84b5752b88db47960a6ec6d`**,
P02 scope freeze `content_hash`
**`4cf5556c8e9c0811653e4b4d726a7b437d43bd63134cad0f80b84eb9148ec59b`**.

## 1. Versioned census and design consequence

The census re-scans the three frozen 512-seed windows (primary 85000–85511,
closure probe 86000–86511, confirmation 87000–87511) with the frozen #200
generator code path. Every window yields exactly **4 distinct prompt forms**,
saturated by 32 seeds and unchanged at the 64/128/256/512 growth checkpoints:

```text
[32, 4], [64, 4], [128, 4], [256, 4], [512, 4]
```

The four frozen form ids (matching the #200 audit `form_set_hash`
`010c5812c17723ee617dac4039b021fb363c2ab61932f46092cb30ec02dc6480`):

```text
57ee9880f18bff4971516f9db820fd96dfb9eb86dab29e166025625e88a7b0c9
a0e4ffd0c0b442207bf171422592a1f0b8f58556e2d44d8845d74ec23853f03d
a95806c84d3a722d0ae240c637277373526956b57051cf006e5430706bf6e94c
fc05e96360fa58fd2398727a886654d27d87fe561b2160002bcc01511f322562
```

**Design consequence (frozen):** `k = 4` for the `hypothesis` family. The
attainable exact two-sided sign-flip floor is 2/2⁴ = **0.125 > 0.05**, so no
dichotomous rejection at α = 0.05 is attainable at any effect size on this
family. The pilot is an **estimation and descriptive study**; no
significance-style claim is made, including for its fresh-seed replication
block. H0: Delta = 0; H1: Delta < 0; Delta is the equal-weight form mean of
real-minus-placebo entropy. Guards never filter the estimate; all forms and
missingness are reported without imputation. No planning-low effect-size prior
is used anywhere. Distinct seed ids are not independent forms; the
experimental unit is the prompt form.

## 2. Closure evidence

**Status: closed — proven by exhaustive enumeration of the finite generator
state space**, not merely observed saturation. This upgrades the #200 audit's
observed-saturation closure to a proven closure for this generator
configuration.

**Generator-level argument.** The prompt form id is the sha256 of the
model-visible ISO pre-read request body (model + state +
question/instructions/criteria). For the hypothesis family at LOW complexity
and regime N, the body is a deterministic function of `(bit0, bit2)` of the
target: the state carries only A's private clues `bit0`/`bit2` (B's clue
`bit1` is not in the pre-read body), and the model, question, instructions
and the eight options are fixed. `(bit0, bit2)` has exactly four values, so
at most four distinct forms can ever be produced.

**Exhaustive enumeration.** The census enumerates all eight target numbers
0–7 (which cover all four `(bit0, bit2)` pairs) through the real generator
code path:

| target | bit0 | bit1 | bit2 | form id | first seed |
|---|---|---|---|---|---|
| candidate-0 | 0 | 0 | 0 | `fc05e963…` | 85001 |
| candidate-1 | 1 | 0 | 0 | `a0e4ffd0…` | 85004 |
| candidate-2 | 0 | 1 | 0 | `fc05e963…` | 85000 |
| candidate-3 | 1 | 1 | 0 | `a0e4ffd0…` | 85010 |
| candidate-4 | 0 | 0 | 1 | `57ee9880…` | 85041 |
| candidate-5 | 1 | 0 | 1 | `a95806c8…` | 85002 |
| candidate-6 | 0 | 1 | 1 | `57ee9880…` | 85003 |
| candidate-7 | 1 | 1 | 1 | `a95806c8…` | 85012 |

The eight targets realize exactly **4 distinct forms**, grouped by
`(bit0, bit2)`: `(0,0)←{0,2}`, `(1,0)←{1,3}`, `(0,1)←{4,6}`,
`(1,1)←{5,7}`. The form is a function of `(bit0, bit2)` (computationally
verified: each pair maps to exactly one form), all four pairs are realized,
and the upper bound is four. The form space is therefore exactly these four
forms — closed.

**Observed saturation (corroborating).** The disjoint closure probe
(86000–86511) finds 0 new forms; all three windows yield the same 4 forms.

**Residual unknowns (stated, not hidden):**

- The closure proof covers only this generator configuration (hypothesis
  family, LOW complexity, regime N, Jev ISO pre-read); it does not extend to
  other families, complexities, regimes or receiver conditions.
- Closure of the form space does not establish statistical independence of
  the four forms; they share one template and differ only in `state.clues`
  (see §4).
- The census is a deterministic offline artifact; it contains no live
  outcome and authorizes no collection.

## 3. Pre-read hashes

For each form, the census records the full pre-read hash record for one
representative instance (the first seed in the primary window realizing the
form), computed via the frozen code path
`jev_replay.prompt_form_id(jev_replay_preregistration_v4.pre_read_body(...))`
and `jev_replication_preregistration.branch_hashes`:

| form id | representative instance | seed | pre-read state hash | real claim | placebo claim |
|---|---|---|---|---|---|
| `57ee9880…` | `hypothesis-00014c0b` | 85003 | `e451bfac…` | `bit1=1` | `bit0=0` |
| `a0e4ffd0…` | `hypothesis-00014c0c` | 85004 | `0cc37efd…` | `bit1=0` | `bit0=1` |
| `a95806c8…` | `hypothesis-00014c0a` | 85002 | `53245aff…` | `bit1=0` | `bit0=1` |
| `fc05e963…` | `hypothesis-00014c08` | 85000 | `c52d49e8…` | `bit1=1` | `bit0=0` |

Each record also carries the `pre_read_request_body_hash` (equal to the form
id), the `pre_read_state_hash`, and the real/placebo/null
`branch_request_hashes` and `branch_state_hashes`. The test suite recomputes
every hash from the generator and fails closed on drift.

## 4. Shared-template/dependence assessment

The four pre-read bodies are **identical except for `state.clues`**: they
share the model (`jev-1.13.0`), the question id, the instructions, the eight
options (`candidate-0`…`candidate-7`) and the state structure
(`family`/`complexity`/`agent_id`). The common template hashes to
`951f7efa7b38b33c8fe6c6d90bf071e968ec4d86bfa2cb4f404a20aaa62a237a`. The only
varying field is `state.clues = (bit0, bit2)`:

| form id | bit0 | bit2 | clues |
|---|---|---|---|
| `fc05e963…` | 0 | 0 | `["bit0=0", "bit2=0"]` |
| `57ee9880…` | 0 | 1 | `["bit0=0", "bit2=1"]` |
| `a0e4ffd0…` | 1 | 0 | `["bit0=1", "bit2=0"]` |
| `a95806c8…` | 1 | 1 | `["bit0=1", "bit2=1"]` |

The four forms are therefore a **complete 2×2 factorial over `(bit0, bit2)`**
— the entire finite form space, not a sample from a larger prompt population.
They are **hash-distinct but not independent prompts**: a template-level
effect would shift all four forms together. Form-level sign flips are
**assumption-dependent**: the exact two-sided sign-flip p is reported as a
descriptive statistic with the exchangeability assumption labeled, never as
assumption-free inference. With `k = 4` the attainable floor 0.125 > 0.05
makes the test non-confirmatory regardless, so the pilot and its fresh-seed
replication remain descriptive/estimation only.

## 5. Per-form capacity

Seeds per form across the three frozen windows (each window 512 seeds):

| form id | primary | closure probe | confirmation | total |
|---|---|---|---|---|
| `57ee9880…` | 118 | 138 | 140 | 396 |
| `a0e4ffd0…` | 129 | 117 | 117 | 363 |
| `a95806c8…` | 133 | 123 | 143 | 399 |
| `fc05e963…` | 132 | 134 | 112 | 378 |

Every form has ample capacity in every window (≥112 seeds), so the frozen
selection rule (first `INSTANCES_PER_FORM = 4` seeds per form, ascending)
is comfortably satisfiable in all three windows. The primary-window counts
match the #200 audit `per_form_seed_counts` exactly.

## 6. Seed/ID overlap report and current manifest coverage

**Overlap report.** The 32 selected ids (16 primary + 16 confirmation, seeds
85000–85025 and 87000–87032) are disjoint from the prior-instance-id set and
from each other:

- `selected_ids_overlapping_prior`: **[]** (empty)
- `primary_vs_confirmation_overlap`: **[]** (empty)
- `documented_seed_range_overlaps`: **[]** (empty)
- `disjoint_from_all_prior_artifacts`: **true**

**Current manifest coverage (rechecked).** The prior-instance-id set
reproduces the #200 pin exactly from current disk: **8945** ids, sha256
**`429e8c54720d1a472d9e191fedc0510ade291680514f2dae4dff8c2a747607f9`**,
the same **119** scan sources as the #200 audit. **No new manifest** with
instance ids appears under the #200 scan patterns since the #200 audit, and
no recorded manifest is missing. The P01/P02 artifacts
(`runs/next-phase/jev-p02-scope-freeze.json`, `docs/jev-p01-evidence-index.md`,
`docs/jev-p02-scope-freeze.md`) live outside the #200 scan scope and are
recorded here, never treated as empty sets. The inaccessible
`runs/container-isolation.json` is recorded as inaccessible, never as an
empty set.

## 7. Checks (all offline, zero provider calls)

- Recomputed the census `content_hash` from the artifact; it matches
  `ee0ba3a1…` (fail closed on drift).
- Rebuilt the census from the frozen generator and current disk state:
  **byte-for-byte** identical to the artifact (deterministic rebuild).
- Recomputed every input-evidence hash (#200 audit, #200 registration, P02
  scope freeze) from disk; all match the pins recorded in the census.
- Verified the #200 audit still rebuilds byte-for-byte from current disk
  (its `audit_content_hash` `5242e9cf…` is unchanged).
- Verified the closure enumeration: 8 targets → 4 `(bit0, bit2)` pairs →
  exactly 4 distinct forms, matching the #200 audit form set.
- Verified the pre-read hashes recompute from the generator for all four
  forms.
- Verified the dependence assessment: the four bodies share one template and
  differ only in `state.clues`.
- Verified no seed/ID overlap with the prior-instance-id set, no
  primary/confirmation overlap, and no documented seed-range overlap.
- Verified current manifest coverage is unchanged since the #200 audit.
- Ran the census CLI verification: **30/30** named checks pass,
  `provider_calls: 0`.
- Ran the #200 offline preflight verification: **49/49** named checks pass,
  `provider_calls: 0`, registration status `draft_pending_review`,
  `live_collection_authorized: false`.
- Ran the task-relevant test suites: `tests/test_jev_p03_form_census.py`,
  `tests/test_jev_p02_scope_freeze.py`, and
  `tests/test_jev_replication_preregistration.py`; every suite asserts the
  frozen inputs byte-for-byte unchanged after running.
- No live output path exists or was created; the #200 live paths remain
  absent.

## 8. Handoff

P03 is complete with evidence paths, hashes, checks and this handoff. The next
concrete offline step is **P04 (#205)** — classify design and plan discovery:
k and attainable p floor; pilot versus potentially confirmatory
classification; discovery registration with fixed N, treatment/route,
budgets, stops, paths, and coverage rules; `hypothesis` remains descriptive.
#205 is blocked by this task until the plugin records its closure. A
predecessor closed as failed does not authorize successor execution; this
task closes with evidence, and nothing in it authorizes collection, any
provider call, or any registration lock.
