# Non-planning-family Jev replay replication — draft preregistration (#200)

**Status: `draft_pending_review`, offline. No provider call is made by any code
path in this module. Locking will not be execution approval.**

Next-phase planning: [hypotheses and sequential discovery/confirmation plan](jev-discovery-confirmation-plan.md).
That plan clarifies the six-form confirmatory minimum, descriptive status of
this four-form study, and the distinction between interval half-width and a
power-based MDE. This document and its frozen draft artifacts remain a historical
record; implementing those clarifications requires a new registration version.

| | |
|---|---|
| Task | Chainlink **#200** under **#159** |
| Module | `src/apart_incident_response/jev_replication_preregistration.py` |
| Form audit | `runs/epic-126/replication/jev-replication-form-audit-v1.json` |
| Registration (draft) | `runs/epic-126/replication/jev-replication-preregistration-v1.json` |
| `audit_content_hash` | `5242e9cfa35e3a77c54045475428dd617cf93cb16d464b55ad679adc35f80a83` |
| `preregistration_hash` | `ff186a066e6af093ecc383e668d948bdca7c1ef8f84b5752b88db47960a6ec6d` |
| Offline preflight | 49/49 named checks, `provider_calls: 0` |

## 1. Family selection (outcome blind)

**Rule (declared before any live outcome):** among the non-planning families,
take the alphabetically first (bytewise ascending) family identifier that
passes three offline structural preconditions — closed finite solution set,
A-finalizer structurally needs the peer clue, and at least one B-owned claim
that is informative for A.

Result: **`hypothesis`** (rule order `hypothesis, legal, lexicon, poetry,
reference`; `planning` excluded by requirement).

The rule cannot encode a preference, so the choice carries no information about
favourability. **No prior live result** (L4X bridge, v6/v7 coverage, pilots,
normalization probe, the selection screen, the planning-low replay) was
consulted, and the **planning-low estimate and p-value are not used as a prior,
an expectation or an effect-size guarantee anywhere** in this registration.

## 2. Form-capacity audit (deterministic, offline)

Prompt-form identity is derived **only** from generator/task structure: the
sha256 of the model-visible ISO pre-read request body
(`jev_replay.prompt_form_id(pre_read_body(...))`). No outcome enters the hash.

| Window | Seeds | Role |
|---|---|---|
| primary | 85000–85511 (512) | form census + manifest selection |
| closure probe | 86000–86511 (512) | closure test only — **no seed may be selected from it** |
| confirmation | 87000–87511 (512) | fresh-seed confirmation block manifest |

All three windows are disjoint from every documented prior seed range
(16000–17104, 39000–39001, 41000–41001, 70000–70016, 71000–71016,
72000–72016, 73000–73016, 74000–74016, 75000–75255, 80000–80016).

**Finding:** `hypothesis` has **4 distinct prompt forms**, saturating by 32
seeds and unchanged at 64/128/256/512. The disjoint closure probe finds **0 new
forms**, so the space is **closed**.

| form | seeds in primary window |
|---|---|
| `57ee9880f18bff49…` | 118 |
| `a0e4ffd0c0b44220…` | 129 |
| `a95806c84d3a722d…` | 133 |
| `fc05e96360fa58fd…` | 132 |

Structure (uniform across the window): 8 candidates, A's pre-read feasible set
size 2, B holds exactly 1 private clue, that clue is accepted and informative
for A with `delta_i_bits = 1.0`, `finalizer_needs_peer` holds.

**Selection rule:** first `INSTANCES_PER_FORM = 4` seeds per form in ascending
order → **N = 16 per block**, fixed, **no outcome-based stopping**. Two blocks
(`primary` 85000…, `confirmation` 87000…) → 32 instances total.

**Disjointness proof:** 8 945 prior instance ids across all recorded artifacts
plus documented seed ranges (`prior_instance_ids_sha256` recorded); selected
ids overlapping prior = `[]`; primary ∩ confirmation = `[]`; window overlaps
with documented ranges = none.

## 3. Frozen replication design

- **Original L4X communication treatment**: family `hypothesis`, complexity
  `low`, regime `N`, agents A/B, 2 turns, `AgentContext → treatment_prompt →
  json.dumps(sort_keys=True)`, schema `treatment-prompt-v2`
  (`prompt_hash 80072617…`, identical to the v6/v7 registered spec), grammar
  `ANSWER: <label> + optional MESSAGE: <claim>` (answer-only = silence),
  `provider_seed` algorithm `sha256-truncated-signed31-v1`, temperature 0.0,
  token budget 1024, Ling writer transport v3 with 3.25 s pacing.
- **Jev receiver**: `jev-1.13.0`, `https://api.typesafe.ai/v1/systemone`,
  codec `jev-choice-wire-v2`, protocol key `jev-choice-wire-v2|75190e25…`,
  normalization policy `292ac217…` (normalize every accepted vector).
- **Branches**: `real` (the exact accepted B-owned claim — bound per instance as
  B's single owned private clue), `placebo` (controller-injected source-neutral
  re-presentation of a receiver-known A clue, `I_m = 0`, no feasible-set
  reduction, same envelope), `null` (no message). Only
  `state.visible_messages` differs.
- **Authoritative checks**: `holds_claim('B', …)` ownership; board-log
  `board_write` then A `peer_read_exposure` with sequencing and a nonempty
  exposure id; authoritative `ExactInformationEvaluator` accepted with
  `delta_i_bits > 0`; real claim absent from A's private clues; at most one
  deduplicated claim per pre-read state; A→B writes excluded.
- **Estimand**: experimental unit is the prompt form; `d_i = H_real −
  H_placebo`; primary is the equal-weight mean of the within-form means;
  `events_are_independent_units: false`; **no instance-level primary
  inference**; **no imputation**.

All three branch request hashes and branch state hashes are precomputed and
bound per instance in the registration, and re-verified on every build.

## 4. Multiplicity and confirmation (preregistered)

- **Family-level control:** Holm step-down over the *registered* family set,
  frozen before outcomes = `["hypothesis"]`. With exactly one registered family
  the Holm-adjusted p equals the raw p, and **no cross-family claim** follows.
  Any extra family requires its own preregistration and its own confirmation
  block.
- **Forbidden:** sweeping families and selecting a winner post hoc; adding or
  removing a registered family after outcomes are visible.
- **Fresh-seed confirmation required before any claim:** the `confirmation`
  block (16 instances, window 87000–87511, same deterministic selection rule,
  disjoint from the primary block) is confirmatory only and may never be pooled
  with the primary block for the primary estimate.
- **Minimum-form rule:** a dichotomous confirmatory claim needs **≥ 5 distinct
  prompt forms**; fewer than five is replay-coverage failure.
- **Five-form fallback:** with exactly five forms the result is interval-only
  descriptive — a two-sided sign-flip p below 0.05 is forbidden and no causal
  gate is released.

### The decisive audit consequence

`k_max = 4` for this family, so the attainable exact two-sided sign-flip floor
is `2/2⁴ = 0.125 > 0.05`. **No dichotomous rejection at α = 0.05 is attainable
at any effect size on this family.** Unless a reviewer approves a different
form unit in a separate registration, this replication is preregistered as an
**estimation and descriptive study**: the equal-form estimate and its t
interval are reported and no significance-style claim is made.

**MDE:** `t(0.975, k−1) × SD_between / √k`, illustrative with
`SD_between = 0.1933` bits (recorded in #185/#189 from the J3 ISO-minus-FULL
method demonstration, sensitivity only) → **≈ 0.30754 bits at k = 4**. This
family's own between-form SD is unknown until data exist; the planning-low
estimate and p-value are never used as a prior or a guarantee. A null result
cannot exclude effects below that figure.

## 5. Operational settings (frozen)

| | |
|---|---|
| Jev | `jev-1.13.0`, systemone endpoint, `max_retries 2`, retryable `408/429/500/502/503/504/529`, timeout 30 s, backoff 0.5/5.0/jitter 0.25 |
| Ling | paid `inclusionai/ling-3.0-flash-vl` on `pr.LING_ENDPOINT`, key loader `behavioral_discovery._api_key`, temperature 0.0, pacing `ling-writer-openrouter-pacing-v3` (3.25 s), `max_retries 2` |
| Partitions | collection: Ling 384 / Jev 96 physical; replay: Jev 288 / Ling 0 physical |
| Caps | collection planned 160 (Ling 128 + Jev 32) / physical 480 / ≤ $0.40 (worst $0.292552704); replay planned 96 Jev / physical 288 / ≤ $0.15 (worst $0.099090432); **program** planned 256 / physical 768 / ≤ **$1.00** (worst **$0.391643136**) |
| Cost model | Ling `(8192×0.06 + 1024×0.18)/1e6 = 0.00067584`/call; Jev `8192×0.042/1e6 = 0.000344064`/call; next-call reserve = 3 × worst call |
| Terminal stops | cost/request cap, model drift, protocol-key drift, request/state/option identity drift, malformed/negative/option-mismatched vector, hard normalization > 0.05, argmax shift, output collision, registration/source/treatment/geometry hash drift, writer terminal errors, two consecutive terminal provider failures |
| Output lifecycle | fresh paths, **no resume, no append, no overwrite, no path overrides**; a stopped run needs a new registration and a new review |
| Authorization | `separate_live_authorization_required_after_locking: true`, `locking_is_not_authorization: true`, `approval_may_not_be_inferred_from_locking: true` |

Reserved (all currently absent):

- `runs/epic-126/replication/jev-replication-collection.jsonl`
- `runs/epic-126/replication/jev-replication-collection-report.json`
- `runs/epic-126/replication/jev-replay-replication.jsonl`
- `runs/epic-126/replication/jev-replay-replication-report.json`

## 6. Fail-closed verification (49 named checks)

Version and **draft** status; **approval not inferred from locking**
(`approval_required`, `approval.approved = false`,
`lock_does_not_imply_approval`, `live_collection_authorized = false`,
`lock_is_not_live_authorization`, `approval_may_not_be_inferred_from_locking`);
audit rebuilds and is byte-reproducible on disk; audit content and form-set
hashes match; family matches the selection rule and is outcome-blind; form
capacity matches the audit and is recorded closed; the k=4 floor is recorded;
fixed-N membership of 4 per form per block; **branch request/state hashes
recompute** for every manifest instance; prior-artifact and seed-window
disjointness; manifest hashes match; estimand, sign-flip + t interval,
no-instance-level, no-imputation, minimum-form rule, five-form fallback and
guard non-filtering; Holm rule, frozen family set, no post-hoc winner,
fresh-seed confirmation; Jev/Ling/normalization/retry/terminal-stop/cap pins and
arithmetic; fresh outputs disjoint from v4 and v5; source binding; byte-identical
rebuild with a matching content hash; no mixed protocol keys; optional
credential presence reported redacted.

## 7. Running

```
# offline verification (default, zero calls)
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src \
  python -m apart_incident_response.jev_replication_preregistration

# write the audit + DRAFT registration once (never overwrites)
... --lock
```

`--live` is always refused while the registration is a draft: missing approval
→ `blocked/missing_approval`; supplied approval → `blocked/
draft_registration_requires_reviewer_lock_and_a_separate_live_authorization_reference`.
Both paths make **zero provider calls**.

## 8. Tests

`tests/test_jev_replication_preregistration.py` — 50 tests covering
reproducible form selection, seed/id disjointness, closed/open form-space
behaviour, manifest hash stability and byte-reproducibility, multiplicity-rule
encoding, design/operational freezes, draft-and-not-authorizing status,
registration tamper rejection (lock flip, approval flip, status flip, stale
hash, family swap, cap tamper, manifest/audit tamper, mixed protocol, minimum
form rule), and zero provider calls on offline verification, missing approval,
draft refusal and failed preflight.

Frozen inputs (both artifacts and the four reserved output paths) are
snapshotted and asserted unchanged after every test.
