# J3a — Jev Choice wire contract and Python transport decision

Status: design memo for review (#176, child of #156). **No live calls, no codec
code, no test changes.** Executable conformance tests belong to #177. This memo
records the contract, the current adapter's breaks, the transport and versioning
decisions, and the gate criteria for #178 and #180.

Current adapter under review: `src/apart_incident_response/jev_choice.py`
(offline scaffold, `JEV_ADAPTER_VERSION = "jev-choice-receiver-v1"`).

## 1. References and pins

| Reference | Pin |
|---|---|
| Local conformance checkout | `/home/framework/GitRepos/jev-dsl` @ `f16f1363b4d389d6e34f9d695fbd254ca0735f2e` |
| jev-dsl contract pin (README) | requests `jev-latest`; every success resolved to `jev-1.13.0` |
| Public OpenAPI at capture | `0.2.0`, SHA-256 `72452d6951dbaadd1030af76434917ef103e470bf0cd6ac035b02b111bfd4d24` |
| Captured Choice pair | `test/fixtures/choice-one.json` (status 200, `model` `jev-1.13.0`) |
| Captured rejections | `choice256` 400, `choice-zero` 400, `unknown`/malformed 400/422 |
| Official HTTP API | `https://docs.typesafe.ai/api` |
| Official models | `https://docs.typesafe.ai/models` |
| Official Python SDK | `https://docs.typesafe.ai/sdk/python` (+ retries/constants/clients) |

jev-dsl is used here as a **pinned offline conformance reference only**, never a
runtime checkout dependency (an allowlisted external input, not vendored).

## 2. Official Choice contract

### 2.1 Request

`POST https://api.typesafe.ai/v1/systemone`, header
`Authorization: Bearer <TYPESAFE_API_KEY>`, `Content-Type: application/json`.

```json
{
  "model": "jev-1.13.0",
  "state": { "...": "arbitrary JSON: string, object, or array" },
  "questions": {
    "<question id>": {
      "type": "choice",
      "instructions": "<string | object | array>",
      "criteria": { "<option id>": "<string | object | array | null>" }
    }
  }
}
```

- `questions` is a map chosen by the caller; the question id is **not sent to the
  model** and is not used in inference.
- `criteria` is the option set; each key is an option id, each value a description
  (`null` is allowed). **Maximum 255 options per Choice.**
- A request may mix Noul/Score/Choice questions; all run in parallel against one
  `state`. Out of scope here.

### 2.2 Response

```json
{
  "model": "jev-1.13.0",
  "answers": {
    "<question id>": {
      "type": "choice",
      "choice": "<option id>",
      "probabilities": { "<option id>": 0.0 },
      "confidence": 0.0
    }
  },
  "usage": { "input_tokens": 0, "output_tokens": 0 }
}
```

- One answer per question, under the same id.
- Choice answer carries `type`, `choice` (highest-probability option),
  `probabilities` (full distribution, sums to 1), `confidence` (0–1, derived from
  the distribution). Noul has no `confidence`.
- `model` is the **resolved versioned id**, not the requested alias.
- Errors: `401` bad key, `422` validation, `429` rate limit, `529` overloaded;
  observed `400` bodies also carry `detail` / `error_type` / validation arrays
  (see `core/Jev/Core/Contract.hs`, `parseEnvelope`/`Rejection`).

### 2.3 Decoder strictness to match (jev-dsl `Contract.hs`)

`parseChoice` requires `type`, `choice`, `probabilities`, `confidence`.
`distribution` requires probability keys to equal the submitted option set
exactly (no missing/extra/duplicate), every value and the confidence in [0,1].
Sum drift is a separate diagnostic (`driftOf`), not an acceptance gate. The
envelope distinguishes `answers` (evaluated) from rejection bodies
(`detail`, `error_type`, validation array).

## 3. Current adapter and contract breaks

Anchor lines in `jev_choice.py`:

| # | Current behaviour | Real contract | Consequence |
|---|---|---|---|
| B1 | `build_request` emits `{model, options, prompt, prompt_hash}` (line 233) | `{model, state, questions:{id:{type,instructions,criteria}}}` | Entire request rejected as malformed (422) |
| B2 | `parse` reads top-level `raw["probabilities"]` (line 260) | `raw["answers"][question_id]["probabilities"]` | Every live response classified `missing_probabilities` |
| B3 | Winner read from `selected_option_id` (line 278) | `choice` | Selection mapping absent |
| B4 | `confidence` ignored | Required Choice field | Calibration signal dropped |
| B5 | `usage` maps `cost` | `input_tokens` / `output_tokens`; no cost | Cost/usage accounting wrong |
| B6 | Requested model echoed; no drift check | Response `model` is resolved versioned id | Alias/version drift undetected |
| B7 | Rejection envelopes unrecognized | `detail` / `error_type` / validation | No provider-rejection taxonomy |
| B8 | Endpoint `https://example.invalid/jev/v1/choice`, model `jev-choice` | `https://api.typesafe.ai/v1/systemone`; versioned model | Placeholder, never callable |
| B9 | No retries; single `urllib.request.urlopen` | SDK retries 408/429/500–599; API says retry 429/529 | Transient failures become `transport_error` |

Sound and to preserve: `MAX_CHOICE_OPTIONS = 255` (line 26) matches the Choice
limit; `JevCredentials` redaction/fingerprint and Authorization-header-only
transport (lines 69–136); `sanitize_provider_message` reuse.

## 4. Target mapping

### 4.1 Question id and stable candidate IDs

- One Choice question id, fixed internal label `candidate` (never sent to the
  model, so it cannot bias answers).
- Criteria keys are the **exact candidate labels** from `instance.solutions`,
  sorted, `str()`-preserved, no trimming, no renumbering. These are the stable
  option ids across the manifest.
- `criteria` values default to `null` (see §7 risk); optional neutral descriptions
  may be added but must be frozen and hashed.

### 4.2 State as leak-free labelled state

Build the Jev `state` explicitly from the frozen instance view; do **not** dump
`agent_view` verbatim (its `task_instruction` is a natural-language answer-format
instruction for the Ling path and must not leak into the Jev state).

| Condition | State contents | Forbidden |
|---|---|---|
| ISO | `family`, `complexity`, `agent_id`, `private_clues` | `joint_clues`, peer claims, `joint_solutions`, target, joint candidate set/count |
| FULL | `family`, `complexity`, `agent_id`, **pooled clues once** (`joint_clues`) | re-prepending A's private clues, `joint_solutions`, target, joint candidate count/labels |
| COMM | `family`, `complexity`, `agent_id`, `private_clues`, received peer claims only (`visible_messages`) | joint clues not received, `joint_solutions`, target |

The **condition label is not part of the model-visible `state`**; it is recorded
in the artifact row only. Keeping condition out of `state`, and using the pooled
clues once in FULL, ensures the only ISO→FULL change is the information content,
not duplicated clues or a treatment cue.

`instance.solutions` (the 6 public options) is the criteria set in every
condition and is not a leak; the private feasible set (`private_solutions`) and
`joint_solutions` are never placed in state or criteria. Invariant tests remain
the ones already in `tests/test_jev_choice.py`
(`test_iso_state_excludes_joint_and_peer_clues`).

### 4.3 Instructions

Frozen wording bound into the protocol key, e.g.:

> Using the clues in `state`, assess how well each candidate in `criteria` fits
> those clues. Return a probability for every candidate in `criteria`.

The wording must be **condition-neutral and identical across ISO/FULL/COMM**, and
must not assert or reveal whether the visible clues determine a unique answer.
It is false in ISO (and potentially COMM before a useful message) that exactly
one candidate is consistent, so any "exactly one"/"unique" phrasing is
prohibited. Do not let the instruction encode the condition.

## 5. Transport decision

**Decision: Python-native `urllib` transport with a strict Jev Choice codec and
explicit physical-request accounting. Do not adopt the official SDK for this
gate.**

Rationale:

1. **Cap auditability.** #178/#180 cap *physical* requests. The SDK's
   `RetryPolicy` performs retries internally; attempt counts are not exposed
   through `system_one`. Counting requires injecting a custom `transport` /
   `http_client` anyway, so the SDK buys little.
2. **Dependency surface.** The project currently depends only on `cryptography`
   (`pyproject.toml`). The SDK adds `typesafe-sdk` (and its HTTP stack) into a
   hash-bound pipeline; the gate is small and does not need it.
3. **Existing, tested machinery.** `behavioral_discovery.py` already provides
   `classify_http_status`, `is_retryable_status`, `_retry_after_seconds`, and
   `sanitize_provider_message`, matching this repo's redaction conventions.
4. **SDK parity is achievable if needed.** The SDK can run with
   `RetryPolicy(max_retries=0)`; if we later want SDK parity we can call it
   through a counting transport. That remains an option, not the plan.

Consequences: we own retry/backoff semantics and must reproduce them exactly
(§6). A golden live pair (§8) is the check that our codec matches reality.

## 6. Retry and physical-request policy

- Retryable statuses (Jev-specific, superset of the current Ling set):
  **`{408, 429, 500, 502, 503, 504, 529}`**. Note `behavioral_discovery`'s
  `RETRYABLE_STATUSES` (line 233) omits `529`; define a separate Jev constant
  rather than changing Ling behaviour.
- Max 2 retries after the initial attempt (3 attempts total); exponential
  backoff base 0.5 s, cap 5.0 s, jitter 0.25; honor `retry-after` **and**
  `retry-after-ms`.
- Total retry budget cap per call (e.g. 30 s); stop and surface the last error.
- Count every physical attempt; the physical request counter is the cap unit.
- **Retry only network errors and the specified HTTP statuses.** A malformed
  JSON body on an HTTP success is a non-retryable invalid response
  (`malformed_response`), reported immediately without further requests.
- Credential only in the `Authorization` header; never in body, logs, or
  artifacts. Provider error bodies are sanitized (key redaction, length cap).

## 7. Design risk: `null` descriptions vs task solvability

`null` option descriptions are acceptable **only if** the frozen candidate ids
and clue wording give Jev enough information to solve the task. A valid
probability vector is not a usable receiver. Therefore:

- Freeze the **static, instance-independent** parts and bind those into the
  protocol key: the state serializer/schema, the instruction wording, the
  criteria policy (option ids are the exact candidate labels; values are
  `null`/neutral), the question id, and the codec/endpoint/model/retry versions.
  **Do not bind per-instance clue values** into the protocol key. Store a
  separate **per-call request/state hash** on each row so matched conditions
  (same codec/wording/policy, different instance) share one protocol key.
- Add an explicit **FULL task-validity check** to the probe: Jev must actually
  solve FULL instances (accuracy on the determined target), and ISO mass should
  concentrate on the clue-consistent set. FULL task validity is itself measured
  in #180, **after** #179 locks the protocol. A failed FULL result is therefore
  a **legitimate no-go outcome of the gate**, not a silent wording repair: any
  wording/registration change requires a new codec version and a new
  registration, not an edit under the locked protocol.

## 8. Endpoint, model, codec, and key versioning

- Endpoint constant: `https://api.typesafe.ai/v1/systemone`.
- Request **`jev-1.13.0` from the first smoke call**; require response
  `model == "jev-1.13.0"`. No `jev-latest` alias call in this smoke; an alias can
  move. Drift is an invalid result, not a warning.
- New codec version constant (e.g. `JEV_CHOICE_CODEC_VERSION = "jev-choice-wire-v1"`),
  separate from the offline scaffold `JEV_ADAPTER_VERSION`. v1 scaffold artifacts
  are preserved unmodified.
- New **additive Jev protocol key** (`jev_choice_protocol_key`), not the Ling
  six-field key. It binds only static, instance-independent inputs: codec version,
  endpoint, requested/resolved-model policy, the state serializer/schema version,
  instruction wording, criteria policy, question id, option-id policy,
  normalization tolerance, and retry policy. **Per-instance clue values are not
  key fields.** Each row carries a separate per-call request/state hash plus the
  instance and condition ids, so matched conditions with the same
  codec/wording/policy share one protocol key and different instances do not
  split the key. The recorded key is **derived from the settings actually used**
  (model, effective endpoint and retry policy from the client, instruction
  wording, question id), never from defaults; two adapters with different
  effective settings cannot record the same key. The analysis loader must
  **refuse mixed keys** so Jev artifacts cannot be pooled with Ling artifacts or
  with the offline scaffold.
- Sanitization / golden fixtures: store only `{probe, status, request, response}`
  with Authorization stripped and no credential echo (jev-dsl policy in
  `scripts/curate-fixtures.py`); `raw_response_retained: false`. Offline fixtures
  are `ASSUMED_SCHEMA` until the live golden pair exists; after capture,
  regenerate codec tests from the golden pair in #177 and freeze.
- Credential env: the loader already accepts `TYPESAFE` / `TYPESAFE_API_KEY` et
  al.; the SDK canonical name is `TYPESAFE_API_KEY`. The worktree `.env` uses
  `typesafe`. If the SDK is ever used, prefer `TYPESAFE_API_KEY` or pass
  `api_key=` explicitly.

## 9. Gate #178 — tiny wire smoke (design limits; not authorization)

Scope: 2 frozen leak-checked instances × {ISO, FULL}, one Choice question
(`candidate`). No Noul/Score, no Ling writer, no COMM, no entropy.

Caps: **at most 6 physical requests including retries**, **at most $1**.
Retries limited per §6. Stop on first contract mismatch.

Pass (for the single question id used, e.g. `candidate`):

1. HTTP 200.
2. `answers` contains **exactly that question id** — no missing, extra, or
   duplicate answer keys.
3. `answers["candidate"]["type"] == "choice"`.
4. `answers["candidate"]["probabilities"]` keys are **exactly the Choice
   `criteria` option ids** — no missing, extra, or duplicate.
5. Every probability is finite and in [0,1]; the distribution sums within
   tolerance (sum drift recorded separately).
6. `answers["candidate"]["confidence"]` is finite and in [0,1].
7. `answers["candidate"]["choice"]` is **in the argmax set** of the returned
   probabilities; ties are accepted as any argmax member (no tie-break required).
8. Resolved `model == "jev-1.13.0"`.
9. `usage.input_tokens` and `usage.output_tokens` are present integers.

Fail / stop: any of the above missing; unknown selection; wrong kind; missing or
extra answer/option; unresolved or drifted model; `401`/`422`; cap reached;
repeated retryable failure. On failure, stop and repair/re-version the codec —
do not interpret data. Capture one redacted golden pair and compare it to the
offline codec before proceeding.

## 10. Gate #180 — capability/calibration probe (numbers locked in #179)

Only after #179 is locked and live authorization is recorded. Held-out repaired
planning-low instances with manifest/seed separation from selection and later
J5 evaluation.

Report:

- Planned / attempted / valid denominators per condition; complete pairs.
- Capability: full-vector validity rate, option identity, normalization, and the
  **FULL task-validity** result (§7). ISO mass-on-consistent-set as the narrowing
  check.
- Calibration on FULL (target determined): p_correct, Brier/log loss, and
  reliability bins **with uncertainty, descriptive only** — a small probe
  cannot certify calibration. ISO reported as a partial-information floor.
- Resolved model, physical requests/usage/cost, failures, stop reason.
- Explicit continue/stop decision for #157.

Caps (sample size, request/cost ceilings) and go/no-go thresholds are set in
#179 before approval. This memo fixes only the design shape. A failed FULL
task-validity result is a **legitimate no-go** for #157; it is not repaired by
editing wording under the locked protocol. Any wording/registration revision
requires a new codec version and a new registration.

## 11. Unverified until a live call

- Actual response envelope beyond the documented example and `choice-one.json`.
- The confidence formula and its stability; probability sum drift.
- Actual retry / `Retry-After` / `retry-after-ms` behaviour and rate limits.
- Acceptance of the versioned `jev-1.13.0` id (vs aliases) for our account.
- Token accounting and `usage` presence under our request sizes.
- Exact `400` vs `422` rejection bodies.
- Whether frozen wording + `null` descriptions yield FULL task validity.
- All Noul/Score wire behaviour (deferred to #170/#174).

## 12. Out of scope

- Packet / Noul / Score codecs and per-kind golden captures (#170, #174).
- Ling writer / optional-board COMM pilot (#158).
- Real/placebo/null decision-entropy replay (#159).
- Any change to the frozen v1 manifest, the Ling six-field protocol key, or the
  offline scaffold artifacts.
