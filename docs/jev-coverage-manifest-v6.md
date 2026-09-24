# Fresh form-balanced L4X coverage manifest (v6 registration) (#190)

Status: offline registration **locked** for review — `live_collection_authorized:
false`. Locking a registration is not live authorization; #191 must obtain a
separate live authorization and pass a runner preflight before any provider
call. **Zero provider calls** were made by the builder, verifier, CLI or
tests. The v1–v5 registrations and all live artifacts are immutable and
untouched; the frozen 17-instance L4X v5 journal/report are never appended to
or reinterpreted.

- Module: `src/apart_incident_response/jev_coverage_manifest_preregistration_v6.py`
- Artifact: `runs/epic-126/jev-coverage-manifest-preregistration-v6.json`
  (version `stage2-jev-coverage-manifest-v6`, status
  `locked_for_jev_coverage_manifest_v6`, registration hash `0961f404…`)
- Tests: `tests/test_jev_coverage_manifest_preregistration_v6.py` (36 tests)
- Fresh outputs reserved for #191: `runs/epic-126/jev-coverage-manifest-v6.jsonl`
  (journal), `runs/epic-126/jev-coverage-manifest-report-v6.json` (report);
  the verifier fails if either exists.

## 1. Deterministic offline seed selection

- Fixed scan window: seeds **75000–75255** (base 75000, window 256). The
  window is fixed at registration time and never tuned after any outcome.
- Form identity: each instance's pre-read **A** prompt form is computed with
  the exact #189 canonical serializer (`jev_six_form_coverage_audit.
  pre_read_form_ids` → `prompt_form_id` of the ISO pre-read body), and must
  equal the six-form set frozen by #189 (cross-checked against
  `pr.frozen_forms()` and the committed #189 audit artifact).
- Selection order: **ascending seed; first six instances per frozen form**
  within the window. All 256 seeds are scored; selection consults **form
  identity only** — no model outcomes, writer behavior, or live artifacts.
  Completion seed 75056 (rarest form filled at the 57th seed).
- Result: exactly **36 unique instance IDs** (seeds 75000–75056 minus skipped
  duplicates), **exactly six per form**, all `planning-*`.

| prompt_form_id | selected instance IDs (seed order) |
|---|---|
| `0a3349e16c9633b4d559dfbb808d1e50d0446d8f92160a0feddd1e37299796ee` | 124ff, 12506, 12507, 12508, 1250a, 1250b |
| `1c1d9f6b5c9271ad8e74de180c3e397e1369d326564c9a08ba0840eff0b148fc` | 124f8, 124fb, 124fd, 124fe, 12502, 1250c |
| `2954f5684bcd198ed8eea0956cf573f93cde628d6dfa7472fc57f556bd089b2c` | 12501, 12504, 12509, 1250d, 1250e, 1251d |
| `3196a8d69f844702db012816def7d7866e7416e9fadc9f28eaa7f12ac16a8569` | 124fa, 12515, 12519, 1251c, 12522, 12524 |
| `55968fe191b18f37d1951d71f777115f753e0b9a6da526015f3db5251a1383eb` | 124f9, 124fc, 12500, 12503, 12505, 12511 |
| `ce847ac53b6e344103bc775aede5212b2be6fbd568dc1d85fd24cbde8f585222` | 1250f, 12514, 12517, 1251b, 1251e, 12530 |

(IDs shown as `planning-000<suffix>`; full IDs are embedded in the
registration.)

- Manifest hash `c4221e7db05fbdcba7b441099cb59d84147fa00d25569000ae2f416ca7233ad1`;
  form-manifest hash `fb061b7a956ff953f15851e89d79aa6da149a78300164ffa7e493505fc8c96ea`.
- **Disjointness**: overlap with the prior-instance set is empty (recorded as
  `manifest.disjointness`). The prior set = every `instance_id` found in 101
  epic-126 JSON/JSONL artifacts (wire smoke, capability, planning-low
  manifest, pilots, ladders, bridge, audits) **plus** the documented prior
  seed ranges 16400–16419, 16500–16519, 16600–16602, 39000–39001,
  41000–41001, 70000–70016, 71000–71016, 72000–72016, 73000–73016,
  74000–74016, 80000–80016 → 489 prior IDs, evidence hash
  `442572b537dbfaa8172ebc55cef17a3655aacaeb90a3e049929e424779101f2b`.
  The v6 registration itself is excluded from the scan so the evidence is
  stable before and after it is written.

Fresh IDs are **replicates within the existing six forms**; they do not
increase k beyond six.

## 2. Frozen treatment (original-treatment L4X bridge)

Bound in `treatment`: mode `exact-original-comm-bridge-v5`;
family=planning, complexity=low, regime=N; original Ling COMM interaction for
**two agents × two turns** via
`AgentContext → behavioral_discovery.treatment_prompt → json.dumps(sort_keys=True)`
(prompt schema `treatment-prompt-v2`, original `ANSWER:`/optional `MESSAGE:`
grammar, prompt hash `80072617…`); deterministic `provider_seed`
(`sha256-truncated-signed31-v1`); Ling model/endpoint on OpenRouter,
temperature 0.0, **1024-token** writer budget; v3 pacing/retry transport
(`ling-writer-openrouter-pacing-v3`, min interval 3.25 s start-to-start,
numeric-only Retry-After, max_retries 2, backoff 0.5→5.0 s); peer-only board
visibility; `holds_claim` ownership on accepted writes; **one-way B→A**
primary direction; final Jev receiver **A** with Choice wire v2
(`jev-choice-wire-v2|75190e25…`, model `jev-1.13.0`, state schema
`jev-choice-state-v1`, normalization policy hash bound); finalizer exposure id
`jev-finalizer`; durable per-case journal; `raw_response_retained=false`,
`credentials_retained=false`.

Bindings recorded and verified: `source_files_hash d9f8bfc4…` (21 files),
`manifest_treatment_hash b4d047b1…` (36-instance model-visible treatment),
`information_geometry_hash d29c9e6f…` (per-instance B-claim records — all six
forms retain the #189 log2(3)-bit geometry, 3→1), composite
`treatment_hash b352e4e5…`, writer schema/transport/codec versions. Any
semantic drift requires a new registration.

## 3. Fixed-N coverage design and sizing

Six forms × six instances = **N=36**, fixed. Every planned instance runs
regardless of earlier messages; no stopping after a form obtains an exposure;
no seed replacement after any outcome; no pooling with the frozen 17-instance
block for the primary coverage decision (prior data is historical sizing
context only). Experimental unit for later replay remains the prompt form,
**k=6**.

Sizing rationale (assumption-based heuristic, recorded as such): historical
eligible rate 9/17 ≈ 0.529; under a simplifying constant-rate/independence
assumption, P(one form ≥1 with six instances) = 1 − (1 − 9/17)^6 ≈ 0.989 and
P(all six) = [1 − (1 − 9/17)^6]^6 ≈ 0.937. This is **not** evidence that
eligibility is independent or constant across forms.

## 4. Evidence, eligibility and coverage outcomes (for #192)

Every case retains: writer outcomes by agent/turn; accepted/rejected board
writes; exact claim and ownership; authoritative I_m from A's perspective;
write/read event sequence and exposure ID; B→A direction; receiver
attempted/valid/invalid; normalized+raw probability vectors with diagnostics;
request/state hashes and protocol key; model/version and usage; provider
physical-attempt counters; `prompt_form_id`; `raw_response_retained=false`;
`credentials_retained=false`.

Future eligibility rule (frozen): receiver valid; accepted B-owned claim
delivered to A; authoritative I_m>0; claim not already known to A; verified
write payload identity; verified A read after the write with nonempty exposure
ID; no rejection evidence; at most one deduplicated claim per pre-read state;
A→B messages excluded from primary replay eligibility.

Coverage outcomes (frozen; the decision belongs to **#192**): six forms
covered → release the coverage gate for #192/#193 review; five forms →
interval-only descriptive fallback, no α=0.05 two-sided sign-flip claim;
fewer than five or failed validity/provenance gates → stop and report
inducement/coverage failure. Collection itself must not start #159.

## 5. Planned calls and caps

- Planned logical calls (N=36): Ling = 36 × 4 (2 agents × 2 turns) = **144**;
  Jev = 36 × 1 = **36**; combined = **180**.
- Retry-inclusive physical partitions (registered max_retries = 2, so
  per-call max physical = 3): Ling = 144 × 3 = **432**; Jev = 36 × 3 =
  **108**; combined = **540** (= partition sum, non-overlapping by provider).
  No-retry execution needs only 180 ≤ 540 (144 ≤ 432, 36 ≤ 108) — the cap
  cannot starve the planned run under ordinary operation.
- Cost: ceiling $1.00 (established). Worst case = 540 × 8192 tokens ×
  $0.042/Mtok = **$0.18579456** ≤ $1.00, with per-call worst-case guard
  $0.000344064.
- Stop rules: request/cost caps, repeated HTTP failure, contract mismatch,
  model drift, missing checker evidence, writer error/rate-limit terminal,
  empty/truncated/unparsed/invalid-answer output, hard normalization failure,
  argmax shift on renormalization, output/report exists.

## 6. Verifier and #191 handoff

`verify_against_coverage_manifest_preregistration_v6` fails closed on: draft
or wrong status; registration hash/content drift (full rebuild from repo);
source/treatment/geometry hash drift; wrong form set; any form count ≠ 6;
manifest duplication or overlap with the 489 prior IDs; wrong model, endpoint,
codec, state schema, writer transport, pacing, turns, token budget, seed
algorithm or prompt path; cap inconsistency or insufficient cap; old v1–v5
output paths; an existing future journal/report; non-Jev, v1 or mixed
protocol keys; missing credentials **only** when
`check_credentials=True` (proposed live preflight; local env/file reads,
no request); and any attempt to treat the lock as live authorization.
Default verification is offline and credential-free.

Handoff to **#191**: build a fresh runner against this registration (fresh
journal/report paths above), require a passing preflight plus separate live
authorization, execute fixed N=36 with no outcome-dependent stopping, and
persist the frozen evidence fields. #191 must not append to
`jev-writer-exact-bridge-v5.jsonl`, must not modify v1–v5 artifacts, and must
not start #159. #192 owns the coverage decision.
