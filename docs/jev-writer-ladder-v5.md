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
- Hash `7e8debef89015736aeaf7276998cf67bafa67f75b8e0b465e20d1259c3330333`
- Paths: `runs/epic-126/jev-writer-ladder-preregistration-v5.json`,
  `jev-writer-ladder-v5.jsonl`, `jev-writer-ladder-report-v5.json`,
  `jev-writer-exact-bridge-v5.jsonl`, `jev-writer-exact-bridge-report-v5.json`
- Caps: planned **493** (ladder 408 + bridge 85); combined **550**; Jev **250**,
  Ling **300**; cost cap **$1** (worst case `$0.1892352`). Non-overlapping
  sub-partitions (retries included): **ladder Jev 216 / Ling 220 (total 436,
  $0.5)** and **bridge Jev 34 / Ling 80 (total 114, $0.5)**; ladder+bridge sums
  equal 250 / 300, so the two commands cannot jointly exceed the combined cap.
- Jev protocol unchanged `jev-choice-wire-v2|75190e25…`
- Verifier rejects v1 protocol keys, old v1/v2/v3/v4 output paths, and ladder,
  timing, retry, model, endpoint, manifest, cap or hash drift.

## 5. Exact bridge (repaired)

`src/apart_incident_response/jev_writer_exact_bridge_v5.py`:

- **Real preflight** (`verify_bridge_preflight`, 38 named checks): canonical
  registration content/hash, locked v5 status, `live_collection_authorized`
  false, source/treatment hashes, the 17-instance/six-form manifest, model,
  endpoint, codec, v2 protocol key, writer model/endpoint/pacing/retries/parser
  version/seed algorithm/1024-token budget, actual Jev and Ling partitions,
  bridge caps, non-overlapping combined partitions, fresh journal/report paths,
  redacted credential presence and prior v1-v4 artifact presence. It returns
  `ok`, named `checks` and `failed`; a failed preflight or missing approval
  yields zero provider calls and no output creation.
- **Original prompt path**: `agent_context_and_prompt` builds the same
  `AgentContext` as the original runner and serializes
  `json.dumps(behavioral_discovery.treatment_prompt(context), sort_keys=True)`
  (no second hand-built schema). Regression tests compare every generated prompt
  byte-for-byte with the original path.
- **Visibility**: each Ling agent sees only peer-authored board rows in the
  original row schema (`message_id, author, receiver, text, status,
  delta_i_bits, message_tokens`); the Jev receiver A sees only accepted
  B-authored claims; rejected writes never become visible.
- **Caps and guards**: the CLI constructs the transports from the registered
  bridge partitions (Jev 34 / Ling 80) and `execute_bridge` independently
  re-verifies them and applies request and worst-case-next-call cost guards
  before every writer and receiver operation (retries counted), preserving a
  durable partial journal on a registered stop.
- **Jev evidence**: each case persists receiver attempted/valid/invalid, request
  and state hashes, protocol key, resolved model, option/target IDs, selected
  option, normalized and raw vectors, diagnostics and tier, confidence, usage,
  per-agent/turn writer outcomes, board log and verified exposure provenance,
  provider attempt counters, and `raw_response_retained=false` /
  `credentials_retained=false`. Invalid vectors, model drift, protocol mismatch,
  malformed usage, request/state drift and hard normalization failures stop the
  run; `completed` requires a valid receiver result for every planned instance.
- **Finalizer exposure**: before the Jev call, A's exposure to every accepted
  B-authored claim passed into `visible_messages` is recorded as a
  `peer_read_exposure` event with the frozen `jev-finalizer` exposure id, so the
  final-turn B message has matching read provenance for the replay validator.
- **Accounting**: per-case `provider_attempts` is captured after the receiver
  call (cumulative through that case); a receiver cost-guard stop is
  `receiver_attempted=false` / `receiver_unattempted_cases++` with error class
  `cost_cap`, while a transport/provider exception after attempting is
  `receiver_attempted=true`, `receiver_valid=false` /
  `receiver_invalid_cases++` with the sanitized error class.

## 6. Preflight and tests

Offline preflights: ladder **ok 29/29**, exact bridge **ok 38/38**; zero provider
calls. Focused v5 suites **81 passed**; full offline suite **788 passed**, 4
skipped, 74 subtests, with only the known environment-only bubblewrap failures.

## 7. Future live commands (NOT RUN; each requires separate authorization)

```
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src \
  python -m apart_incident_response.jev_writer_ladder_pilot_v5 --live --approval "<ref>"

UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src \
  python -m apart_incident_response.jev_writer_exact_bridge_v5 --live --approval "<ref>"
```

#159 remains blocked until a ladder/bridge run yields verified eligible exposure
and a reviewer explicitly approves replay.
