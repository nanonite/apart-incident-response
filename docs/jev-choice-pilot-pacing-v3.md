# Jev optional-board pilot v3 — Ling/OpenRouter pacing repair (#186)

Status: offline implementation and registration lock for review. **No live
calls, no rerun, no #159 start, no push/merge.** The locked v3 registration
carries `live_collection_authorized: false`. A future live successor requires
explicit reviewer approval.

## 1. What happened

The stopped v2 optional-board pilot (`runs/epic-126/jev-choice-pilot-report-v2.json`,
commit `c555597`) ended on `writer_http_429_rate_limited`. That 429 came from the
**Ling/OpenRouter writer path, not Jev**: Jev completed 50 receiver calls
without error, while Ling/OpenRouter made 29 physical attempts for 25 logical
writer turns before the terminal 429. The previous pacing was only 0.25 seconds
between cases and writer retries waited 0.5 s and 1.0 s; OpenRouter documents a
20 requests-per-minute ceiling for free-model traffic.

The stopped v2 result remains **immutable**. The observed 12/12 completed COMM
turns as silence, zero real writes, and zero verified exposures remain valid
**partial-run observations**, not a reinterpreted or superseded result. The
pacing repair enables a successor run to complete; it does not reinterpret that
silence and does not unblock #159.

## 2. Ling-only pacing

`src/apart_incident_response/jev_ling_writer_v3.py` adds a monotonic rate limiter
to the Ling writer transport, version `ling-writer-openrouter-pacing-v3`:

- minimum interval of **3.25 seconds** between the **start of every physical
  OpenRouter attempt**, applied across separate logical writer calls and retry
  attempts;
- Jev is never subject to this interval;
- the monotonic clock and sleep function are injected, so tests never wait;
- the remaining wait is computed from the previous physical-attempt start time,
  so request time already spent is not slept again.

The 3.25 s interval targets OpenRouter's documented 20 RPM free-model ceiling.
**Pacing cannot guarantee relief from a daily quota or an upstream-provider
capacity limit**; it addresses only the per-minute ceiling.

## 3. Retry delay policy

For the registered retryable statuses (`408, 429, 500, 502, 503, 504, 529`):

- numeric `Retry-After` seconds and numeric `retry-after-ms` are read safely;
- HTTP-date parsing is explicitly not implemented;
- malformed, negative, non-finite, or above-cap values are ignored;
- the maximum accepted server-requested delay is **10.0 seconds**;
- the delay before the next physical attempt is
  `max(remaining 3.25 s interval, registered exponential backoff, valid server delay)`;
- the registered maximum retry count (2) and retryable statuses are unchanged;
- a terminal 429 remains a durable invalid writer row and stops the pilot.

Provider response bodies are never parsed or retained. On error, only the HTTP
status and bounded numeric header values are inspected.

## 4. Sanitized provenance

Per physical attempt the writer persists a bounded record with: HTTP status,
logical writer-call identifier, physical-attempt number, retry ordinal, applied
delay seconds, delay source and contributing sources, whether `Retry-After` was
present and valid, and whether `retry-after-ms` was present and valid. Records are
`allow_nan=False` serializable. Authorization headers, credentials, complete
response headers, raw response bodies and raw provider envelopes are never
retained.

## 5. Successor registration

`src/apart_incident_response/jev_replay_preregistration_v3.py` builds and
verifies the successor registration `stage2-jev-choice-replay-v3`. It never
modifies, resumes, pools with, or reinterprets the v1 or v2 artifacts. The Jev
codec (`jev-choice-wire-v2`) and normalization policy are unchanged.

- registration: `runs/epic-126/jev-choice-replay-preregistration-v3.json`
- v3 journal: `runs/epic-126/jev-choice-pilot-v3.jsonl`
- v3 report: `runs/epic-126/jev-choice-pilot-report-v3.json`

Frozen and hashed: writer transport version, minimum Ling attempt interval,
monotonic pacing algorithm, retryable statuses and retry count, exponential
backoff, supported retry headers and parsing rules, maximum accepted server
delay, sanitized provenance schema, Ling model/endpoint/prompt/decoding, Jev
model/protocol, source and treatment hashes, request/cost caps, stop rules, the
exact manifest and prompt forms, and the fresh v3 paths. The verifier rejects old
v1/v2 protocol keys and output paths and any source, timing, retry-policy, model,
endpoint, manifest, cap or hash drift, and requires
`live_collection_authorized: false`.

## 6. Fail-closed preflight

The v3 pilot preflight (32 checks) inspects the actual instantiated writer and
verifies model, endpoint, the 3.25 s minimum interval, the monotonic clock and
pacing-algorithm version, the Retry-After policy, retry count and backoff, the
physical-request partition, registration and source hashes, the protocol key,
caps, fresh output paths, and redacted credential presence. A failed preflight or
a missing live approval results in **zero provider calls**.

## 7. Scope preserved

Ling model, endpoint, prompt, temperature and token limit; optional silence;
exact-owner typed-claim requirements; board-write/read provenance;
COMM_CONTROL behavior; the Jev codec and normalization policy; provider
partitions and the combined cost guard; invalidity and stop semantics; and the
#159 gate are all unchanged. No model substitution, paid fallback, automatic
fallback model, or induced-write arm.

## 8. Future live command (NOT RUN; requires separate authorization)

```
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src \
  python -m apart_incident_response.jev_choice_pilot_v3 \
  --live --approval "<ref>"
```

#159 remains blocked until verified real-message exposure exists.
