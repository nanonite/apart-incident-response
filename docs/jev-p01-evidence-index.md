# P01 — Baseline/research-contract reconciliation: evidence index

Task: Chainlink **#202** under **#201** under **#159**. Offline reconciliation
only — no provider call, no artifact modification, no rerun, nothing reopened.
Protocol: [hypotheses and sequential discovery/confirmation plan](jev-discovery-confirmation-plan.md).
Family: `hypothesis:low` (the next-family pilot identified in §4). This task
closes with evidence only; nothing here authorizes collection, registration
locking beyond the existing #200 draft, or any successor execution.

## 1. Evidence index (recomputed, fail closed on drift)

Every hash below was recomputed from the file on disk for this task. The
frozen artifacts are preserved byte-for-byte: nothing listed here was edited,
re-run or reopened, and the #199 memo and #200 draft remain the historical
records of their own tasks.

| Input | Role in this task | sha256 |
|---|---|---|
| `runs/epic-126/replay-v5/jev-choice-replay-inference-v5.json` | #198 offline inference; planning-low primary result and guards | `b892a8d514623aca17b83f17a59e9e699d773b48f059b7b954b6239ff7d6f2ce` |
| `runs/epic-126/replay-v5/jev-choice-replay-v5.jsonl` | replay-v5 journal (51 rows) | `5e9f7322bdb29baf16b18f9b4f4181e9a88ad454e0394ea379e4cdea29b1fede` |
| `runs/epic-126/replay-v5/jev-choice-replay-report-v5.json` | replay-v5 run report | `0ec84446d697bca91c25e155b3cd61f43b4e7706e6df185ea08c3685a8f88310` |
| `runs/epic-126/replay-v5/jev-choice-replay-preregistration-v5.json` | frozen replay-v5 registration | `3c02f8bb44c11d6edd050daf32950e3cf8365f79638e92d46181df764945ddd7` |
| `docs/jev-planning-low-replay-decision-memo.md` | #199 conditional decision memo (closed) | `93215d4cafc20114d7ece32d0e3b1d9c6d28a8ced4236c577fe24ac90775c018` |
| `runs/epic-126/jev-board-necessity-selection.json` | planning-low discovery screen (selection evidence only) | `78dba91926c0134c772c85020ab1a503c8785ddbb34031528a0231297641627a` |
| `runs/epic-126/replication/jev-replication-form-audit-v1.json` | #200 frozen form-capacity audit | `cb529cd61e0e662bfa19fc4998e89fa59a0bf0d63e14f77498035466d6bce89d` |
| `runs/epic-126/replication/jev-replication-preregistration-v1.json` | #200 frozen draft registration | `bddf46ed5fd87ec4da99532d645580a65e250d64639de80477002ff73d278f3c` |
| `docs/jev-replication-preregistration.md` | #200 draft design record | `fec0831bbec1cbb32dd7599a7cb1ac6bf19dacee02effbc319a0e608bc41169d` |
| `src/apart_incident_response/jev_replication_preregistration.py` | #200 offline module (audit + draft registration + preflight) | `d91c0e3ad13fc3049240ab76f13214997872681485ef24b60627763f7ec06133` |
| `tests/test_jev_replication_preregistration.py` | #200 test suite (50 tests) | `ce9363676d87c891d7dab8edd020f32a6c3203940f48753c557212f946a3b9ca` |
| `docs/jev-discovery-confirmation-plan.md` | protocol for #201–#215 | `501e21b6dea760371b0bf368046d8bacd203f6b92f0af754a7955d1f738677f7` |

Content pins recorded inside the frozen artifacts and recomputed for this task:

| Pin | Value |
|---|---|
| replay-v5 registration content hash (in #198 inputs, #199 memo, v5 registration) | `0a81e400f598d16742301d7c07cbaf5398fa861b4fa1701c15405391ab4f6d15` |
| #200 `audit_content_hash` (self-recorded in the audit; bound in the registration `audit_binding`) | `5242e9cfa35e3a77c54045475428dd617cf93cb16d464b55ad679adc35f80a83` |
| #200 `preregistration_hash` (content hash of the draft registration) | `ff186a066e6af093ecc383e668d948bdca7c1ef8f84b5752b88db47960a6ec6d` |

Drift check: every recomputed hash above matches the pin recorded inside the
frozen artifact that cites it (#198/#199 for the replay-v5 inputs and the v5
registration content hash; the #200 draft for `audit_content_hash` and
`preregistration_hash`, whose `audit_binding` also matches the audit on disk).
Any mismatch fails the task closed.

## 2. Planning-low conditional result (preserved)

Reproduced verbatim from the frozen #198 inference artifact and the #199 memo;
the test suite pins every number below against the inference artifact so this
index cannot drift from the record.

- Equal-weight six-form mean of `H_real - H_placebo` = **-0.7775085127397289
  bits**; all six form means are negative.
- Exact two-sided cluster sign-flip **p = 0.03125** (64 sign patterns, the
  k = 6 floor 2/64).
- Form-mean t interval, df = 5: **[-1.1722041593435226, -0.38281286613593507]**,
  which excludes zero.
- **17/17** complete real/placebo pairs over the **six frozen forms**
  (1/4/4/1/4/3); the preregistered negative direction is met and the registered
  primary inference criterion is met.
- Sensitivity over the registered normalization thresholds 1e-6 / 0.01 / 0.03 /
  0.05 leaves the registered decision unchanged at every threshold.
- Null manipulation checks: mean real-minus-null -0.615288 bits (17/17 below
  null); mean placebo-minus-null +0.082010 bits (6/17 below null); null is
  excluded from the primary real-versus-placebo contrast.

Guard summary, reported separately and filtering nothing
(`filtered_primary_estimate: false`, `excluded_from_primary: 0`): target ok
**17/17**, mass ok **15/17**, useful uptake **15/17**.

Guard failures preserved — both events are in form
`55968fe191b18f37d1951d71f777115f753e0b9a6da526015f3db5251a1383eb`, both with
`target_ok: true`, `mass_ok: false`, `useful_uptake: false` (registered guard
configuration: target-probability delta 0.0, feasible-mass epsilon 0.01):

| event | Δ feasible mass | mass_ok | useful_uptake |
|---|---|---|---|
| `planning-000124f9:message-B-0` | -0.01 | false | false |
| `planning-00012511:message-B-0` | -0.02 | false | false |

Scope, unchanged: conditional on the six frozen planning-low prompt forms and
the paid Ling route that generated the messages; the experimental unit is the
prompt form with k = 6. This result is historical evidence outside any new
confirmation set. It is not used as a prior, power assumption or effect-size
guarantee for `hypothesis:low` or for any other family, and no claim below
relies on it.

## 3. Research-contract reconciliation

The existing #200 draft was checked line by line against the plan contract.
Every row must hold for the pilot to proceed as registered:

| Contract rule (plan) | #200 draft record | |
|---|---|---|
| H0: Delta = 0; H1: Delta < 0 | `directional_prediction: "Delta < 0"`; operational test stays two-sided exact sign-flip plus the negative-direction requirement | match |
| Equal-weight form mean of real-minus-placebo entropy | `estimand.primary` = equal-weight mean of the within-form means of `H_real - H_placebo` | match |
| Guards never filter the estimate | `guards.reporting` = never used to filter; guards reported by form and event | match |
| Report all forms/missingness; no imputation | `imputation: never impute missing pairs`; complete-case scope frozen | match |
| Distinct seed IDs are not independent forms | `events_are_independent_units: false`; no instance-level primary inference | match |
| No planning-low effect-size prior | `anti_prior_statement`; `mde.not_a_prior` | match |
| k = 4 ⇒ descriptive only, even for a fresh-seed replication | floor 2/2⁴ = 0.125 > 0.05 recorded; estimation and descriptive study | match |

No contract gap was found. The two wording defects that do exist are logged
for a new version in §5; they do not change the registered estimand or the
descriptive-only consequence.

## 4. Next `hypothesis:low` pilot identified

The existing #200 draft registration and its frozen audit are the next pilot:

- **Family**: `hypothesis`, complexity `low` — chosen by the declared
  outcome-blind rule (alphabetically first non-planning family passing the
  structural preconditions; rule order `hypothesis, legal, lexicon, poetry,
  reference`). The rule cannot encode a preference; no prior live outcome was
  consulted.
- **Form space**: closed at **k = 4** distinct prompt forms — saturated by 32
  seeds and unchanged at 64/128/256/512; the disjoint closure probe finds 0 new
  forms. The four frozen form ids:

  ```text
  57ee9880f18bff4971516f9db820fd96dfb9eb86dab29e166025625e88a7b0c9
  a0e4ffd0c0b442207bf171422592a1f0b8f58556e2d44d8845d74ec23853f03d
  a95806c84d3a722d0ae240c637277373526956b57051cf006e5430706bf6e94c
  fc05e96360fa58fd2398727a886654d27d87fe561b2160002bcc01511f322562
  ```

- **Design**: two fixed blocks of 16 instances (4 seeds per form, ascending,
  no outcome-based stopping) — `primary` window 85000–85511 and fresh-seed
  `confirmation` window 87000–87511, disjoint from every documented prior range
  and from each other. The confirmation block is confirmatory only and may
  never be pooled with the primary block for the primary estimate.
- **Status**: the attainable exact two-sided sign-flip floor is 2/2⁴ = 0.125
  > 0.05, so no dichotomous rejection at α = 0.05 is attainable at any effect
  size on this family. The pilot is preregistered as an **estimation and
  descriptive study**; no significance-style claim is made, including for its
  fresh-seed replication block.
- **Gate state**: `draft_pending_review`; `live_collection_authorized: false`;
  `lock_does_not_imply_approval: true`. Locking is not execution approval, and
  this task authorizes no live run.
- **Artifacts** (frozen, preserved byte-for-byte): audit
  `runs/epic-126/replication/jev-replication-form-audit-v1.json` and draft
  registration
  `runs/epic-126/replication/jev-replication-preregistration-v1.json`, with the
  hashes recorded in §1.

## 5. Log for a new registration version

Logged here per the plan. The frozen #200 JSON is **not** edited; P09 resolves
both items in a new version, not by modifying the frozen draft.

1. **Old five-form wording.** The frozen #200 draft registers
   `minimum_forms_for_confirmatory: 5` with a `five_form_fallback` ("with
   exactly five forms the result is interval-only descriptive — a two-sided
   sign-flip p below 0.05 is forbidden and no causal gate is released") and
   `below_five_forms: replay-coverage failure`. The plan's unadjusted recipe
   requires **six** forms for a potentially confirmatory test (k = 6 floor
   0.03125 ≤ 0.05); k = 4 and k = 5 are descriptive/estimation only, and six
   forms are necessary, not sufficient. A new version must replace the
   five-form wording with the six-form confirmatory minimum.
2. **Interval half-width / MDE mismatch.** The frozen #200 draft labels
   `t(0.975, k−1) × SD_between / √k` — illustrative ≈ **0.30754 bits** at
   k = 4 with SD_between = 0.1933 bits recorded in #185/#189 — as an "MDE".
   The plan defines that quantity as an illustrative **interval half-width**,
   not a power-based MDE. A new version must label it correctly in new
   reports, and any actual MDE must come from a prospective power analysis for
   the actual sign-flip and multiplicity rule, with a stated target power
   (default 80%), a scenario grid, and the smallest negative effect reaching
   that power (or "unattainable" when the discrete test cannot reject).

## 6. Checks (all offline, zero provider calls)

- Recomputed every sha256 in §1 from disk; all match the pins recorded inside
  the frozen #198/#199/#200 artifacts (fail closed on drift).
- Recomputed the #200 registration content hash from the frozen draft; it
  matches `preregistration_hash` `ff186a066e6af093ecc383e668d948bdca7c1ef8f84b5752b88db47960a6ec6d`.
- Ran the #200 offline preflight verification: **49/49** named checks pass,
  `provider_calls: 0`, registration status `draft_pending_review`,
  `live_collection_authorized: false`.
- Ran the task-relevant test suites: `tests/test_jev_replication_preregistration.py`
  (50 tests) and `tests/test_jev_replay_decision_memo.py` (17 tests) pass, as
  does the new `tests/test_jev_p01_evidence_index.py` that pins this document
  against the frozen artifacts; every suite asserts the frozen inputs
  byte-for-byte unchanged after running.
- Ran the repository suite (`python -m unittest discover -s tests`): all tests
  pass except 4 pre-existing environment errors on this host — numpy cannot
  load `libstdc++.so.6` and `bubblewrap` is not on PATH — which are unrelated
  to this task and predate it.

## 7. Handoff

P01 is complete with evidence paths, hashes, checks and this handoff. The next
concrete offline step is **P02 (#203)** — freeze next-family scope and
artifact inventory: candidate order and structural rule, prior-manifest
inventory with hashes, proposed discovery and held-out seed windows, explicit
stage labels; no live outcome used to choose forms or seeds. #203 is blocked
by this task until the plugin records its closure. A predecessor closed as
failed does not authorize successor execution; this task closes with
evidence, and nothing in it authorizes collection or any provider call.
