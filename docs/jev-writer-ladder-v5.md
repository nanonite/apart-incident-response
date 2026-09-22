# J5d (repaired) — writer observability and planning-low ladder v5 (#187)

Status: offline implementation and registration lock for review. **No live
calls, no v3 rerun, no family sweep, no #159 execution, no push/merge.** The
locked v5 registration carries `live_collection_authorized: false`. This
supersedes the unreleased v4 (preserved byte-for-byte); v1–v3 remain immutable.

## 1. Repairs over v4

1. **Writer-invalid outcomes no longer call Jev or count as valid.** For
   `empty_output`, `truncated_output`, `unparsed_output`, `invalid_answer`,
   `writer_error` (and `non_owned_claim`) the runner journals the writer failure,
   marks the receiver branch **unattempted**, and applies the registered stop
   rule before any Jev call. A case can no longer be both valid and invalid;
   `writer_valid`, `receiver_valid` and `joint_valid` are separate.
2. **`L4` renamed** to the *full-context standalone writer (approximate original
   schema)*. Exact original reproduction moved to a new **`L4X` exact original
   COMM bridge**: two agents (A, B) across the two registered turns, the original
   `treatment_prompt` JSON schema and `ANSWER:`/optional-`MESSAGE:` grammar, the
   deterministic `provider_seed`, 1024 max tokens, and evolving visible-message
   state. Implemented in
   `src/apart_incident_response/jev_writer_exact_bridge_v5.py`.
3. **Original-grammar answers are validated** against the public candidate
   labels; an unknown or malformed answer is classified `invalid_answer`
   separately from deliberate silence.
4. **L5 positive-control gate enforced**: every L5 call must produce an
   exact-owned message (`fraction >= 1.0`); otherwise status becomes
   `inconclusive` (`l5_gate_failed`) and no voluntary-rung interpretation is
   emitted.
5. **Reporting denominators separated**: `planned_cases`,
   `planned_provider_calls`, `attempted_cases`, `writer_valid`, `writer_invalid`,
   `receiver_valid`, `receiver_invalid`, `receiver_unattempted`, `joint_valid`,
   writer outcomes by arm, exact-owned accepted writes, rejected claims, verified
   read exposures, `authoritative_i_m` (count) and `i_m_bits`, distinct forms,
   provider requests, Jev/Ling tokens, cost and missingness — per rung and arm.
   COMM and COMM_CONTROL writer outcomes are not pooled.

## 2. Writer observability (v5)

`src/apart_incident_response/jev_ling_writer_v5.py` (outcomes
`ling-writer-outcomes-v5`, parser `ling-writer-parser-v5`): mutually exclusive
outcomes `deliberate_silence`, `message_candidate`, `empty_output`,
`truncated_output`, `unparsed_output`, `non_owned_claim`, `invalid_answer`,
`writer_error`. Sanitized `finish_reason`, `answer`, tokens, content length,
parser classification, `max_tokens`, `seed_sent` and physical-attempt provenance
are persisted; empty/truncated output is never silence; `raw_response_retained`
false; no credentials, headers, bodies or envelopes. The writer accepts an
optional per-call `seed` and `max_tokens` (used by the exact bridge) while the
standalone rungs send no seed and use 64 tokens. v3 pacing/retry/cap/redaction
are inherited unchanged.

## 3. Ladder and decision rules (v5)

Rungs: L0 private clues; L1 +instruction; L2 +candidates; L3 +condition/turn/role;
L4 full-context standalone (approximate); L5 required exact-owned-claim INDUCED
control (excluded from voluntary inference); L4X exact original COMM bridge.
Frozen rules unchanged in intent: L4/L5 writes while L0 silent → prompt/role
dependent emission; all voluntary rungs silent → demote planning-low; any
empty/truncated/unparsed/invalid-answer → repair instrumentation/budget first
(and now stops the run); L5 failure → transport/parser unvalidated; no post-hoc
rung selection; emission ≠ exposure ≠ correlation ≠ causal uptake; three gates
required.

## 4. Successor registration v5

- Version `stage2-jev-writer-ladder-v5`, status `locked_for_jev_writer_ladder_v5`,
  `live_collection_authorized: false`
- Hash `26944aafa98ebb7e1e06a509cbe3294e2b8dd428e6243c2547b6901c6ce8dc54`
- Paths: `runs/epic-126/jev-writer-ladder-preregistration-v5.json`,
  `jev-writer-ladder-v5.jsonl`, `jev-writer-ladder-report-v5.json`,
  `jev-writer-exact-bridge-v5.jsonl`, `jev-writer-exact-bridge-report-v5.json`
- Caps: planned **493** (ladder 408 + bridge 85); combined **550**; Jev **250**,
  Ling **300**; cost cap **$1** (worst case `$0.1892352`); bridge sub-caps 180 /
  60 / 120 / $0.5
- Jev protocol unchanged `jev-choice-wire-v2|75190e25…`
- Verifier rejects v1 protocol keys, old v1/v2/v3/v4 output paths, and ladder,
  timing, retry, model, endpoint, manifest, cap or hash drift.

## 5. Preflight and tests

Offline preflights: ladder **ok 29/29**, exact bridge preflight ok; zero provider
calls. Focused v5 suites 63 passed; full offline suite 770 passed, 4 skipped, 74
subtests, with only the known environment-only bubblewrap failures.

## 6. Future live commands (NOT RUN; each requires separate authorization)

```
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src \
  python -m apart_incident_response.jev_writer_ladder_pilot_v5 --live --approval "<ref>"

UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src \
  python -m apart_incident_response.jev_writer_exact_bridge_v5 --live --approval "<ref>"
```

#159 remains blocked until a ladder/bridge run yields verified eligible exposure
and a reviewer explicitly approves replay.
