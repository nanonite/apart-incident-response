# J3c — Jev Choice wire smoke: preflight and live procedure (#178)

Status: **offline preparation complete; no live Jev request has been made.** Live
execution requires a separately recorded reviewer approval (issue creation and
this document are not approval). Do not run `--live` without it.

## Frozen scope

- Two frozen, leak-checked planning-low instances from
  `runs/epic-126/jev-planning-low-manifest.json`:
  `planning-00011170`, `planning-00011171`.
- Conditions: `ISO`, `FULL` (four cases; one Choice question each).
- Model `jev-1.13.0`, endpoint `https://api.typesafe.ai/v1/systemone`.
- Measured protocol key: `jev-choice-wire-v1|856a2636a322ae9834277f48bd30a6f2412962af129db33c92a1c328e5f41385`.

## Commands

Offline preflight (issues no request; exits non-zero if any check fails):

    UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src \
      python -m apart_incident_response.jev_choice_smoke

Live smoke (only after explicit approval is recorded):

    UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src \
      python -m apart_incident_response.jev_choice_smoke \
      --live --approval "<recorded approval reference>"

## Caps

- **At most 6 physical requests including retries** (4 planned cases + 2 retry
  slots). The transport is constructed with `max_physical_requests=6` and counts
  every attempt; the runner refuses to run if the client cap is not enforced.
- **At most $1** estimated input cost.
- Retries: at most 2 per call, only network errors and
  `{408, 429, 500, 502, 503, 504, 529}`; `retry-after`/`retry-after-ms` honored.

## Preflight checks (all must pass)

- model and endpoint pinned;
- exactly 2 instances and 4 cases, conditions `{ISO, FULL}`;
- planned requests within cap, and the documented cost ceiling within the $1 cap;
- every selected instance id is in the frozen manifest;
- every instance passes the leak/invariant audit (`audit_instance`), and the
  target is absent from the model-visible state;
- re-derived request hashes and option ids match the frozen plan;
- credential present and well-shaped, reported only as a redacted fingerprint.

Any failure exits non-zero and **no call is made**; `execute_smoke` fails closed
on a failed preflight, a missing approval, an unenforced transport cap, or a
request-hash drift.

## Stop rules (live)

Stop on the first: contract mismatch (missing/extra answer or option, wrong kind,
non-normalized or non-finite vector, choice outside the exact argmax, invalid
confidence/usage, unresolved or drifted model), provider rejection, transport
retry exhaustion, the physical-request cap, or the cost cap. A malformed HTTP-200
body is a `malformed_response` and is not retried.

## Cost accounting

Jev charges per input token only ($42 / Btok = **$0.042 / Mtok**); output tokens
are free.

    estimated_cost_usd = input_tokens * 0.042 / 1_000_000

The preflight bounds cost with a documented 8192 input-token ceiling per
request: the **planned** four calls estimate `4 x 8192 x 0.042 / 1e6 = $0.00138`,
and the **retry-inclusive ceiling** at six attempts is
`6 x 8192 x 0.042 / 1e6 = $0.00206`. The live report replaces the estimate with
the actual `usage.input_tokens` returned by the provider and also reports the
retry-inclusive bound (`cost_ceiling_usd`). $0.00138 covers the four planned
calls only, not the six-attempt ceiling.

## Golden-fixture procedure

On the first valid live case, the runner writes one curated fixture to
`runs/epic-126/jev-choice-wire-smoke-golden.json`:

- shape `{_source, probe, status, request, response}`;
- `request` is the wire body the adapter built (`model`, `state`, `questions`);
- credential-named keys (`authorization`, `api_key`, `api-key`, `x-api-key`) are
  dropped, not redacted, and no key value is retained;
- `_source` records codec version, model, endpoint, protocol key, and probe.

After capture: compare the golden response against the offline codec
(`tests/fixtures/jev_choice_wire_choice_one.json` is `ASSUMED_SCHEMA`), confirm
the exact answer/option keys, and only then freeze the codec. On any mismatch,
repair and re-version the codec before proceeding to #179; do not interpret data.

## Artifacts

- Preflight/plan JSON: printed to stdout.
- Live run: `runs/epic-126/jev-choice-wire-smoke-report.json` (+ `.jsonl` reserved)
  and the golden fixture above.
- The report records planned/attempted/valid cases, physical attempts, tokens,
  estimated cost, resolved models, invalid classes, stop reason, and the
  continue/stop decision. `raw_response_retained` and `credentials_retained` are
  false.

## Not in scope

No Ling writer, COMM, Noul/Score packet, #180 calibration, or expanded sample.
`#179` locks the capability/calibration registration after a clean smoke.
