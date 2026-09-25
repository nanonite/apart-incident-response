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
  `fe156254ab94088c2573061c6a62a9209afe4633ce95fd29a73ed516240695bf`,
  byte-reproducible)
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

## Not run — future live command (requires separate review + live authorization)

```
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src \
  python -m apart_incident_response.<v6/#191-style runner TBD for #159> \
  --live --approval "<reviewer reference for lock fe156254…>"
```

(No runner is registered or authorized by this task; #193 freezes the plan
only. #159 stays blocked.)
