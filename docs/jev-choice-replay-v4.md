# Matched Jev replay preregistration v4 (#193 amending #159)

Status: offline **locked** registration for reviewer assessment —
`live_collection_authorized: false`. Locking is not authorization: **#159
execution is not authorized, the replay was not run, and no provider call was
made.** #159 remains blocked pending this review plus a separate live
authorization.

- Module: `src/apart_incident_response/jev_replay_preregistration_v4.py`
- Artifact: `runs/epic-126/jev-choice-replay-preregistration-v4.json`
  (version `stage2-jev-choice-replay-v4`, status
  `locked_for_jev_choice_replay_v4`, content hash
  `97217b478ee84797c642944732211d563666e11f3c1bd809593da848a1946eb4`
  (amendment chain: `fe156254…` → `ffb46af2…` → runner-bound
  `97217b47…`; earlier locks are recorded/superseded in git and
  `runner_policy.superseded_offline_lock`), byte-reproducible)
- Fresh outputs (refused if occupied) live under `runs/epic-126/replay-v4/`
  — a subdirectory because the earlier registrations' prior-ID scan globs are
  non-recursive, so the v4 trio never perturbs their rebuild evidence:
  journal `runs/epic-126/replay-v4/jev-choice-replay-v4.jsonl`, report
  `runs/epic-126/replay-v4/jev-choice-replay-report-v4.json`
- Tests: `tests/test_jev_replay_preregistration_v4.py`

## Consumed event set (#192 authoritative input)

Pinned fail-closed: `runs/epic-126/decisions/jev-v7-coverage-decision.json`
(sha256 `3f45b8bf…`, baseline commit `cad2c80`) plus every upstream hash it
records (v7 journal/report/registration `f7f7d574…`, #189 audit, selector and
generator sources) — recomputed at verification.

- **Exactly 17 events**, unique IDs (`instance:message`), consumed in the
  decision artifact's order.
- **Form distribution exactly 1/4/4/1/4/3** over the six frozen prompt forms
  (sorted-form order); form manifest hash `fb061b7a…` (identical to the #190
  six-form hash); **k = 6**.
- Every event re-verified against the regenerated instance: receiver-valid,
  B→A, authoritative `I_m = log2(3)`, B ownership, nonempty exposure IDs,
  request/state hashes present.
- The incomplete **32/36 v7 collection is not a completed fixed-N sample**;
  this registration consumes its frozen event set as-is.

## Frozen matched branch construction

Per event, one identical pre-read state `C` (receiver-A pre-read state:
family/complexity/agent_id/clues + registered model/question/instructions/
criteria; `prompt_form_id` equals the frozen form id) with three branches
differing **only** in `state.visible_messages`:

- **real**: `C` + `peer_clue: <exact accepted B-owned claim from #192>`;
- **placebo**: `C` + the same envelope around a receiver-already-known clue
  of A with authoritative `I_m = 0` and no feasible-set reduction (synthetic
  origin `controller`, controller-side only);
- **null**: `C` with no message.

The envelope (`peer_clue: {claim}`, wording hash `268425b3…`) is identical
and source-neutral for real and placebo; sender identity and synthetic origin
are never model-visible. State hashes, pre-read request hashes and all three
branch request hashes are frozen per event and recomputed by the verifier
(fail closed on branch-state mismatch, target/answer-key leakage, option
drift). Jev `jev-1.13.0`, Choice codec v2, protocol
`jev-choice-wire-v2|75190e25…`, retries 2, normalization policy hash
`292ac217…` (normalize-all-accepted-vectors). **No Ling call** exists in the
replay design — real messages come from the frozen event set.

## Counterbalanced branch execution order (frozen)

Jev is stochastic with no supported seed/temperature control, so branch
order is frozen in the registration (`branch_schedule`), not left to the
future runner:

- **Event-major**: events execute in the exact #192 decision order; the three
  branches of one event run adjacently before the next event.
- **Per-event permutation** = `BRANCH_PERMUTATIONS[(lexicographic form index
  + within-form event index) % 6]` — lexicographic, hash-free, depending
  only on frozen form/event identity, never on outcomes. The full
  `event_id → [branch1, branch2, branch3]` table is stored explicitly.
- Allowed branches are exactly `real`, `placebo`, `null`, each once per event.
- All **six permutations** occur; branch-position counts across the 51 calls:

  | Position | real | placebo | null | max diff |
  |---|---|---|---|---|
  | 1 | 6 | 5 | 6 | 1 |
  | 2 | 5 | 6 | 6 | 1 |
  | 3 | 6 | 6 | 5 | 1 |

  per-branch totals 17/17/17. Within multi-event forms the schedule rotates
  through distinct consecutive permutations, so branch position is not
  needlessly confounded with treatment.
- The future journal persists **planned and actual** branch position per
  row/event; a runner must **fail closed** if execution order differs from
  the frozen schedule.

## Guard estimands and authoritative feasible set (frozen)

Every event stores the sorted authoritative receiver-A pre-read
`feasible_set` (verified equal to the regenerated instance's
`private_solutions["A"]` and the clue-consistent pre-read set), a
`feasible_set_hash` (`canonical_hash`), and controller-side `target_id`.
Frozen per-event formulas (computed only from the accepted normalized
vector):

```
delta_p_target_i     = p_target(real_i) - p_target(placebo_i)
delta_feasible_mass_i = mass_SA(real_i) - mass_SA(placebo_i)
mass_SA(branch_i)     = sum of normalized Choice probabilities over the frozen
                        authoritative pre-read feasible_set for receiver A
target_ok_i  := delta_p_target_i >= 0.0
mass_ok_i    := delta_feasible_mass_i >= -0.01
useful_uptake_i := (H_real_i - H_placebo_i < 0) and target_ok_i and mass_ok_i
```

Guard values are reported per event and aggregated within form; guards never
remove an otherwise valid real/placebo pair from the primary entropy
estimate; entropy reduction alone is never useful uptake when either guard
fails; null stays excluded from these real-versus-placebo guards. Feasible-set,
formula, comparison-direction and threshold drift all fail the verifier.

## Estimand and inference (frozen)

- Unit: **prompt form**; `d_i = H_real,i − H_placebo,i`; within-form mean;
  **Δ = equal-weight mean over the six forms**; directional prediction
  **Δ < 0**. The 17 events are replicates, never independent units.
- Primary inference: **exhaustive two-sided cluster sign-flip over the six
  form means** plus the **form-mean t interval (df = 5)**, both reported, with
  a negative observed mean required. Minimum two-sided p: k=6 → 2/64 =
  0.03125; k=5 → 2/32 = 0.0625. Instance-level t/Wilcoxon tests prohibited
  as primary.
- **Null branch** retained only for `H_real−H_null` / `H_placebo−H_null`
  manipulation checks; excluded from the primary contrast.
- **Guards** (reported separately, never filter the primary estimate):
  target-probability margin **δ = 0**, feasible-set-mass **ε = 0.01**;
  entropy reduction is never "useful uptake" if the target guard fails.
- **Missingness**: a pair is complete iff real and placebo are both valid;
  report planned/attempted/valid/invalid/complete by branch and form; primary
  inference needs ≥1 complete pair in **every** frozen form; target retain all
  17; **no imputation**; five forms → interval-only descriptive, two-sided
  sign-flip p < 0.05 forbidden, **no causal gate**; fewer than five →
  replay-coverage failure.
- **Sensitivity**: normalization thresholds 1e-6 / 0.01 / 0.03 / 0.05; report
  exact vs materially-renormalized rows, maximum probability adjustment,
  maximum induced entropy change, argmax changes. Secondary only (never
  overrides primary): form-cluster bootstrap, sign test on form means,
  instance-weighted mean; hierarchical and Wilcoxon-on-form-means are not
  implemented and are not registered.

## Operational execution and missingness rules (frozen)

`execution_policy` freezes everything the future #191-style runner must not
silently choose:

- **Preflight**: exact reviewed registration hash with repository-backed
  verification; exact event and branch-order manifests; model/endpoint/codec/
  protocol/retry/normalization settings; request/state/option/treatment
  hashes; credentials present but never printed or retained; registered
  journal/report paths absent; enforced request and cost caps; **no provider
  call before every check passes**.
- **Output lifecycle**: no overwrite, no automatic resume, no append to any
  prior replay artifact; a fresh execution after a partial/stopped run
  requires a new review and explicit authorization; raw envelopes and
  credentials never retained.
- **Durability/journal**: append-only branch-attempt journal — one durable
  row per logical `(event_id, branch)`; append + flush + fsync after every
  logical branch outcome; unique key `(event_id, branch)` with
  **duplicate-key → fail closed**; rows persist planned/actual branch
  position, request/state hashes, protocol/model, physical attempts,
  vector/normalization diagnostics, validity, usage, error class and cap
  counters; the final report groups branch rows into event-level
  real/placebo/null records for the registered replay validator and
  inference; partial triplets stay observable.
- **Per-branch**: retries only for registered retryable transport statuses,
  maximum two; physical attempts include retries; reserve the registered
  retry-inclusive next-call cost **$0.001032192** (= 0.000344064 × 3) before
  each logical branch; a nonterminal invalid branch is journaled without
  skipping the event's remaining branches; primary complete pair = real AND
  placebo valid; null validity reported separately and not required; no
  imputation.
- **Immediate terminal stops**: request/cost cap before the next call; model
  drift; protocol-key drift; request/state/option identity drift; malformed
  or non-finite/negative/option-mismatched vectors; hard normalization
  deviation above 0.05; argmax shift after normalization; output collision;
  registration or source/treatment hash drift.
- **Nonterminal invalidity**: an accepted response outside the primary
  normalization band but within the registered suspect sensitivity band is
  recorded invalid with safe raw diagnostics retained, never reinterpreted as
  valid, and the run continues unless a terminal rule applies.
- **Provider failures**: sanitized invalid branch row after retry exhaustion;
  stop after **two consecutive** terminal provider/HTTP failures; the counter
  resets after a successful valid response; no bodies or credentials ever
  retained.
- **Stopping** preserves a partial report with
  planned/attempted/valid/invalid/unattempted counts **by branch, event and
  form**.
- **Runner policy**: no runner exists yet; a future runner must be added to
  this registration's source binding and the registration re-locked with a
  new hash **before any live authorization** (`adding_runner_authorizes_
  collection: false`).

## Cap arithmetic

| Item | Arithmetic | Value |
|---|---|---|
| Planned Jev calls | 17 events × 3 branches | **51** |
| Planned Ling calls | no Ling call in the replay design | **0** (justified in `caps.ling_budget`) |
| Physical ceiling | 51 × (1 + max_retries 2) | **153** (reserve 102) |
| Worst-case cost | 153 × 8192 × $0.042/Mtok | **$0.052641792 ≤ $1.00 ceiling** |

## Limitations (registered)

k is capped at **six** by the generator's closed form space (fresh IDs never
increase k); the planning-context approximate detectable-effect/CI limit is
**≈ 0.203 bits**; a null result cannot exclude smaller effects; all inference
is conditional on the six frozen planning-low forms and on the **paid Ling
route** that generated the messages (never pooled with free-route behavioral
rates).

## Verifier (fail closed)

Rejects: draft/authorization statuses; registration hash/content/source/
treatment drift; decision-artifact pin or upstream hash drift; missing, extra,
duplicated or reordered event IDs; wrong form set/counts/membership or
distribution; non-B→A events; non-informative real claims; non-inert placebo
claims; branch-state/request/state/option mismatches; target or answer-key
leakage; estimand/weighting/independence tampering; altered inference, guard,
missingness, sensitivity or limitation rules; v1 protocol keys, wrong
Jev model/endpoint/codec, normalization-policy drift, mixed protocol keys;
cap or cost drift (including any Ling budget); old or occupied output paths;
and any attempt to treat the 17 events as 17 independent experimental units.

## Runner (#195) — source-bound, offline-validated

`src/apart_incident_response/jev_replay_runner_v4.py`
(`jev-choice-replay-runner-v4`) is registered in `runner_policy`
(`runner_implemented: true`, `runner_source_files` lists exactly it,
included in `REPLAY_V4_SOURCE_FILES` → new `source_files_hash` and
`treatment_hash` embedding the runner source). **Adding the runner does not
authorize execution**; `live_collection_authorized` stays false.

- **Preflight (25 named checks, fail-closed)**: locked registration + content
  hash, all #192 event/upstream hashes, exact event IDs, six-form
  distribution 1/4/4/1/4/3, feasible-set hashes, branch schedule and
  event-major order, `jev-1.13.0`/endpoint/codec v2/protocol key/retry/
  normalization, source/treatment hashes, fresh `replay-v4/` outputs,
  Jev credentials present (never printed), physical cap 153 / planned 51/0,
  cost reserve `$0.001032192`. Failed preflight or missing approval ⇒ zero
  calls and zero output files; no provider construction happens before the
  preflight passes.
- **Execution**: frozen schedule (event-major, three adjacent branches per
  event, planned order from `branch_schedule`); real = exact accepted B→A
  claim, placebo = source-neutral envelope around the frozen receiver-known
  A clue, null = no message; only `state.visible_messages` differs; every
  request hash and the pre-read state hash are recomputed and must equal the
  registered values before any Jev call; no Ling call.
- **Journal**: append-only `BranchJournal` — one durable row per
  `(event_id, branch)`, append+flush+fsync per row, duplicate keys fail
  closed, overwrite refused (`open "x"`), no automatic resume; rows carry
  planned/actual positions, request/state hashes, protocol/model, physical
  attempts and cap counters, safe vector diagnostics, normalized metrics
  (entropy, p_target, feasible mass), validity, usage and error class; the
  report groups rows into event-level real/placebo/null records with
  planned/attempted/valid/invalid/unattempted counts by branch, event and
  form; partial triplets stay observable.
- **Stops**: retries only for registered statuses (max 2); reserve
  `$0.001032192` before every logical branch; malformed/non-finite/negative/
  option-mismatched vectors, model/protocol/identity drift, hard
  normalization (>0.05), argmax shift, hash drift, caps and output
  collisions stop immediately; suspect-band vectors are journaled invalid
  with diagnostics and never become valid; nonterminal invalid branches do
  not skip siblings; sanitized provider-failure rows with a stop after two
  consecutive terminal provider failures (counter resets on success).
- **Registered analysis in the report**: `d_i = H_real − H_placebo` over
  complete pairs, equal-weight within-form means across the six forms,
  exhaustive two-sided cluster sign-flip + form-mean t interval (df=5),
  negative-direction requirement, δ/ε guards computed per event and within
  form but never filtering the entropy estimate, separate null manipulation
  checks, five-form interval-only fallback (sub-0.05 sign-flip forbidden, no
  causal gate), below-five = replay-coverage failure, no instance-level
  inference; only accepted normalized vectors feed any metric.

## Not run — future live command (requires separate review + live authorization)

Task **#195** ("Implement the source-bound Jev replay-v4 runner offline")
is open for reviewer assessment. The live command (**NOT RUN**):

```
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src \
  python -m apart_incident_response.jev_replay_runner_v4 \
  --live --approval "<reviewer reference for lock 97217b47…>"
```

Offline usage (`python -m apart_incident_response.jev_replay_runner_v4`
without `--live`) runs the named preflight only and makes zero provider
calls. **#159 stays blocked** pending #195 review, reconciliation of open
blockers #158/#187, and a separate explicit live authorization.
