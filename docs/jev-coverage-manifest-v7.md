# v7 coverage registration — paid-Ling routing repair (#191 review)

Status: offline repair implemented under Chainlink task **#194**
("Repair and lock paid-route v7 six-form coverage collection", open for
reviewer assessment); v7 registration **locked**
(`live_collection_authorized: false`). The capped transport probe ran in the
previous turn (the one network step; no rerun here); **no experimental
collection ran and none is authorized**. v1–v6 registrations and all live
artifacts — including the frozen v6 journal/report from commit `935bdbf` —
are preserved byte-identical. #192/#193/#159 were not touched.

## Root cause and probe (review repair items 2, 4, 5)

- The authorized v6 run stopped at case 1 with
  `writer_http_404_endpoint_or_model_unavailable`. The OpenRouter **routable
  catalog (460 models) does not contain `inclusionai/ling-3.0-flash-vl:free`**
  while the public model page still advertises it — page/catalog inconsistency
  that explains the 404.
- **Capped nonexperimental transport probe** ran once under
  `reviewer-repair-191-transport-probe-2026-09-24`:
  `src/apart_incident_response/jev_coverage_probe_v7.py` (caps: 1 physical
  request, 16 output tokens, $0.01 ceiling, catalog fetch first, refusal on
  missing approval/existing output/gated catalog/missing credentials).
  Result artifact `runs/epic-126/jev-ling-transport-probe-v7.json`
  (sha256 `06d22e87…`, **immutable historical evidence — never modified**):
  HTTP **200**, 1/1 attempt, model `inclusionai/ling-3.0-flash-vl`, 26 in /
  16 out tokens, estimated cost **$0.00000444** ≤ $0.01,
  `finish_reason=length`, `empty_output`, no usable answer, no raw response
  or credential retained.
- **Corrected interpretation (registration-side, hash-bound to the artifact)**:
  the binding records `routing_success: true` / `transport_success: true`
  (routing, credentials, HTTP success, usage/pricing) and
  `writer_output_validated: false` — the probe proves **routing/transport
  only, never behavioral writer capability**. `probe_scope` states
  "routing, credentials, HTTP success, and usage/pricing only; not behavioral
  or writer-output capability"; the experimental writer still uses the
  separately registered 1,024-token budget.
- **Approval basis, recorded accurately**: the probe reference
  (`reviewer-repair-191-transport-probe-2026-09-24`) was derived from a
  reviewer recommendation rather than a separately supplied formal approval
  string; it is accepted only as nonexperimental route evidence, is not
  retrospective experimental authorization, and does not authorize v7
  collection.
- **Catalog/availability gate** (`jev_openrouter_catalog.py`, read-only, no
  credentials): the target paid SKU must be present with positive pricing
  before any experimental collection; free-SKU presence is diagnostic only.
  Enforced by the probe, recorded in the registration, re-fetched by the v7
  live preflight. The gate is hardened to fail closed: every malformed
  catalog payload returns named failed checks (`catalog_reachable`,
  `target_sku_present`, `target_pricing_present`) and can never escape as a
  `ValueError`/`TypeError`; the runner makes zero provider calls when the
  gate fails (adversarially tested).

## Pricing freeze (review repair item 4)

Catalog snapshot pricing for the paid SKU: **prompt $0.06/Mtok,
completion $0.18/Mtok** (context 262144). The free-route assumption of v1–v6
is explicitly not reused. Frozen cost model (registration `caps.cost_model`):

| Component | Arithmetic | Worst case |
|---|---|---|
| Ling (conservative **8192** input ceiling — the runner does not enforce a prompt-size bound, so the retired 4096 assumption is not reused) | (8192×$0.06 + 1024×$0.18)/Mtok = $0.00067584/call × 432 | **$0.29196288** |
| Jev (unchanged: $0.042/Mtok input, output free) | 8192×$0.042/Mtok = $0.000344064/call × 108 | **$0.037158912** |
| Total | Ling + Jev | **$0.329121792 ≤ $1.00 ceiling** |

Next-call reserves (retry-inclusive `worst_call × (1 + max_retries)`,
reserved **exactly once per logical call** while the provider partitions
still reserve `1 + max_retries` **physical** attempts): Ling **$0.00202752**
(0.00067584×3), Jev $0.001032192. Planned calls and partitions are
unchanged: **144 Ling + 36 Jev = 180 logical; 432/108/540 physical**. Any
recorded bound above $0.329121792 or above the $1.00 ceiling fails the
verifier; a 4096-token legacy cost model fails as `cost model drift`.

## v7 registration (review repair items 3, 8, 9)

`runs/epic-126/jev-coverage-manifest-preregistration-v7.json` — version
`stage2-jev-coverage-manifest-v7`, status
`locked_for_jev_coverage_manifest_v7`, hash
`f7f7d5742ea3e6a710ed102e6c2a454992abede5c4f51591a9cc447781797565`.
Builder/verifier: `jev_coverage_manifest_preregistration_v7.py` (27-file
source binding incl. the catalog, probe and runner modules).

- **Fresh paths**: registration `…-preregistration-v7.json`, journal
  `jev-coverage-manifest-v7.jsonl`, report `jev-coverage-manifest-report-v7.json`.
  The v6 paths are never reused, deleted from, or appended to; they are
  sha256-pinned `preserved_inputs` (v6 registration `63be1ccb…` /
  lock `628de647…`, journal `f5a7a0d8…`, report `a6f5253c…`) alongside the
  v1–v5 pins, the #189 audit and the frozen bridge pair.
- **Same base model identifier, new SKU**: `model_and_protocol.ling_model` =
  `inclusionai/ling-3.0-flash-vl` (previous `…:free` recorded). Prompt
  treatment, seed algorithm, grammar, pacing, retry policy, token budget,
  manifest and caps are unchanged. Cautious drift language bound into
  `model_routing_repair.treatment_drift`: *same base OpenRouter model
  identifier and unchanged prompt protocol; provider routing or serving
  configuration may differ. v7 findings are conditional on the paid route and
  must not automatically be pooled with free-route behavioral rates.*
  Model-family switches were rejected as larger drift.
- **Manifest reused unchanged (item 9)**: identical 36 IDs/order/membership,
  manifest hash `c4221e7d…`, with explicit justification — *v6 produced no
  model output and no task outcome (stopped at writer HTTP 404 before any
  message, exposure, or Jev call), so reusing the identical manifest
  introduces no outcome-based selection.*
- **Bound requirements**: `transport_probe` (sha256 + `routing_success` +
  `writer_output_validated=false` + `probe_scope` + `approval_basis` +
  single-attempt cap + pricing, each cross-checked against the derived
  interpretation of the immutable artifact), `catalog_gate` (required before
  live, live re-fetch),
  `runner_policy` (v7 runner source-bound, probe required, catalog gate
  required, `adding_runner_authorizes_collection: false`, live execution
  forbidden until a **new review grants explicit live authorization**
  referencing this lock).
- The verifier fails closed on: hash/content/source/treatment/geometry drift,
  wrong (free) Ling model, pricing or worst-case drift (including legacy
  4096-token cost models and any combined worst case above $0.329121792 or
  the $1.00 ceiling), old v1–v6 output paths, wrong
  manifest/justification, probe tampering or a missing probe, probe-scope /
  approval-basis / routing-vs-writer-output misinterpretation,
  preserved-input drift, missing runner policy/probe/catalog requirements,
  freshness collisions, catalog pricing drift at live preflight, missing
  credentials at live preflight, and any live-authorization flip. The
  catalog gate itself fails closed on every malformed payload (bad
  `model_count`, missing/non-string/non-numeric/non-finite/non-positive
  pricing, malformed `entries`) as named failed checks — never as an
  exception — so the live preflight blocks before any completion call.

## v7 runner (review repair items 3, 6)

`src/apart_incident_response/jev_coverage_bridge_v7.py`
(`exact-original-comm-bridge-v7`) reuses the reviewed v6 execution semantics
(original `AgentContext → treatment_prompt` builder, L4X grammar/provider
seed/1024 tokens, peer-only visibility, ownership, #189 eligibility selector,
fixed N=36, fsync journal, registered terminal stops) with:

- Ling writer constructed with the **paid SKU explicitly** from the
  registration (no reliance on module defaults);
- **paid-route cost accounting**: per-provider token counters
  (ling/jev × input/output) and `estimate_run_cost_usd` using the frozen
  rates; guards reserve the registered next-call reserves exactly once;
- **`material_correction` always present** on journal rows (explicit `false`
  until a receiver response exists — the v6 stopped-row defect, repair item 6);
- fresh v7 outputs only; no path overrides on the CLI.

## Lifecycle test isolation (review repair item 7)

`tests/v6_lifecycle_sandbox.py` builds a lock-time sandbox (src symlink +
symlinks to exactly the recorded prior-scan sources + the registration file;
own outputs absent). Both v6 suites run against it via `setUpModule`, and the
v7 suites use the explicit `journal_exists`/`report_exists` verifier/preflight
parameters — so committed collection outputs never cause ordinary post-run
test failures.

## Tests

- `tests/test_jev_openrouter_catalog.py`, `tests/test_jev_coverage_probe_v7.py`,
  `tests/test_jev_coverage_manifest_preregistration_v7.py`,
  `tests/test_jev_coverage_bridge_v7.py` (fresh suites, no network: catalog
  gate synthetic tests; probe refusal paths + committed-artifact contract;
  registration/verifier rejections; runner plan/preflight/blocking/fixed-N/
  cost-accounting/material_correction/CLI tests).
- Both v6 suites (78 tests) green with the committed v6 outputs present.
- Adversarial catalog suite (17 tests): every malformed `model_count`,
  pricing and `entries` case fails closed without raising; probe interpretation
  and approval-basis tests; conservative cost-bound tests (8192 ceiling,
  $0.00067584 / $0.00202752 / $0.29196288 / $0.329121792, legacy-4096 and
  above-bound/above-ceiling rejection); zero-call proof on a failed live
  catalog gate.

## Not run — future live command (requires NEW review + live authorization)

```
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src \
  python -m apart_incident_response.jev_coverage_bridge_v7 \
  --live --approval "<new reviewer reference for lock f7f7d574…>"
```

The successful probe does **not** authorize collection. #192 stays idle (no
coverage block exists); #159 remains blocked.
