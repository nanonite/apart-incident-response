# Jev Choice normalization policy v2 and successor registration (#158)

Status: offline implementation and registration lock for review. **No live calls,
no pilot rerun, no #159 start, no push/merge.** The locked v2 registration
carries `live_collection_authorized: false`; the diagnostic probe carries
`execution_authorized: false` and requires a separate future approval.

This document records the reviewer-approved prospective normalization policy
implemented under a distinct codec/protocol version, `jev-choice-wire-v2`, and
the successor registration. Strict v1 semantics and every v1 artifact are
preserved byte-for-byte; the locked v1 registration and the stopped optional-board
pilot (commit `ff2fbc7`) are not modified, reinterpreted, appended to, pooled
with, or overwritten.

This is a **local analysis policy**, not behavior prescribed by TypeSafe. The
official Jev Choice contract describes `probabilities` as floats that sum to
one; it does not tell clients to renormalize a response. The pinned `jev-dsl`
reference likewise does not renormalize: it accepts the numeric distribution
and reports sum drift greater than `0.01` as a diagnostic. This repository's v1
codec instead rejected drift greater than `1e-6`. The capture-and-normalize
behavior below is therefore new, prospective v2 behavior and must not be
attributed to Jev itself or applied retroactively to v1 data.

## 1. Why v2

The stopped v1 pilot ended on the registered contract stop rule: the
`COMM_CONTROL` case returned a vector classified `not_normalized` under the
strict `1e-6` tolerance, while `COMM` used the **identical request hash**
`2ba516131bdb…` and summed to `1.00`. The v1 invalid path discarded the rejected
vector, so its exact deviation cannot be recovered and `ff2fbc7` must not be
retroactively reclassified.

Across the 34 retained prior vectors, 34/34 summed to `1.0` on a predominantly
`0.01` grid; the `1e-6` tolerance was mismatched to two-decimal quantization.
v2 changes **only** the probability-vector acceptance policy, never the prompt.

## 2. Capture-then-judge

`src/apart_incident_response/jev_choice_v2.py` parses and retains the
credential-free option probability vector **before** classifying it. Credentials,
authorization headers, and raw provider envelopes are never retained.

For every syntactically parseable vector it records:

`option_count`, `raw_probability_sum`, `signed_normalization_deviation`,
`absolute_normalization_deviation`, `minimum_probability`, `maximum_probability`,
`zero_count`, `all_finite`, `all_nonnegative`, `shape_valid`, `invalid_classes`,
`raw_argmax_set`, `normalization_tier`, `renormalized`, `argmax_preserved`,
`normalization_adjustment`, `entropy_raw_bits`, `entropy_normalized_bits`, and the
normalized probability vector when permitted.

Invalid responses retain the parsed public vector and diagnostics when safe.
Malformed envelopes (no `answers`, wrong kind, extra/missing answer) may lack a
vector. Non-finite values are encoded as `"nan"`/`"inf"`/`"-inf"` strings so
artifacts remain `allow_nan=False` serializable.

## 3. Frozen primary tiers

Option-key identity is exact. Empty, missing, nonnumeric, non-finite, negative,
and option-mismatched vectors remain invalid and are never repaired. Dividing a
finite, nonnegative, near-unit vector by its positive sum is the only permitted
transformation; it is recorded explicitly and is not described as provider
behavior.

| tier | absolute deviation `abs(sum(p)-1)` | valid | metric vector rescaled by raw sum |
|---|---|---|---|
| `exact` | `<= 1e-6` | yes | yes (within 1e-6; usually a numerical no-op) |
| `complete_renormalized` | `1e-6 < d <= 1e-2` (boundary inclusive with machine-epsilon allowance) | yes | yes (material correction) |
| `not_normalized_suspect` | `1e-2 < d <= 0.05` | no (sensitivity only) | no |
| `not_normalized_hard` | `d > 0.05` | no (hard stop) | no |

For **every accepted vector** (`exact` as well as `complete_renormalized`):

```
p_normalized[i] = p_raw[i] / sum(p_raw)
```

There is exactly one downstream invariant: all metrics are computed from the
rescaled vector. That vector is used for entropy, `p_target`, feasible-set mass,
Brier score, log loss, selection validation, and downstream replay inference.
The raw vector and raw sum are retained separately, and `normalization_tier`
records whether the rescale was a material correction (`complete_renormalized`)
or a numerical no-op within `1e-6` (`exact`). Selection is validated against the
argmax of the normalized metric vector actually used downstream, and is then
separately confirmed to agree with the raw argmax; positive scalar rescaling
preserves that argmax mathematically, and the implementation checks this as a
fail-closed invariant. A divergence is classified
`argmax_shifted_on_renormalization`.

The codec field `renormalized` is true for both accepted tiers, because both are
rescaled by the raw sum; `material_correction` (registration policy) distinguishes
the `complete_renormalized` band. The protocol fingerprint binds
`normalize_all_accepted_vectors: true` and `metric_vector: p_raw / sum(p_raw)`.

The primary automatic acceptance upper bound is exactly `1e-2`. The
quantization bound `0.03` and hard ceiling `0.05` are sensitivity/diagnostic
thresholds only. The quantization argument `n*q/2 = 0.03` for `n=6, q=0.01` and
the empirical entropy perturbation grid (`0.01 -> 0.0147` bits, `0.03 -> 0.0453`,
`0.05 -> 0.0779`, argmax observed stable through `0.05`) are recorded as
sensitivity context, not as authorization to expand the primary `1e-2` bound.

## 4. Sensitivity reporting

`src/apart_incident_response/jev_normalization_sensitivity.py` reports, at the
registered grid `1e-6, 0.01, 0.03, 0.05`, the accepted/rejected counts, the
maximum normalization adjustment, the maximum induced entropy difference,
whether the argmax changes, and whether any conclusion changes. A conclusion is
labelled **unstable** when it changes anywhere across the grid. The offline
diagnostic `runs/epic-126/jev-choice-normalization-diagnostics-v2.json` is
labelled a method/diagnostic and does **not** make a scientific conclusion (and
does not reclassify the stopped v1 run).

## 5. Successor registration

`src/apart_incident_response/jev_replay_preregistration_v2.py` builds and
verifies the successor v2 registration. The v1 registration object is untouched;
v2 lives at a fresh versioned path.

- registration: `runs/epic-126/jev-choice-replay-preregistration-v2.json`
- probability diagnostics: `runs/epic-126/jev-choice-normalization-diagnostics-v2.json`
- v2 journal: `runs/epic-126/jev-choice-pilot-v2.jsonl`
- v2 report: `runs/epic-126/jev-choice-pilot-report-v2.json`
- probe registration: `runs/epic-126/jev-choice-normalization-probe-v2.json`

Frozen: codec/protocol v2; tiers and thresholds; raw-versus-normalized metric
definitions; the sensitivity grid; invalidity and stop rules; changed
source/treatment hashes; the exact manifest, models, prompts, request partitions
and cost caps. The verifier rejects v1 protocol keys, old v1 output paths,
settings/hash drift, and tolerance drift, and requires
`live_collection_authorized: false`.

### Determinism

The official Choice request contract and the pinned local jev-dsl fixture expose
only `model`/`state`/`questions`; **no seed or temperature field is documented or
present**. Neither is sent. Jev is therefore recorded as **stochastic**, and
repeated samples per prompt form are required. Diagnostic repetitions are not
independent prompt forms.

## 6. Diagnostic probe (prepared, not executed)

A separately gated repeat diagnostic targets the identical `COMM_CONTROL` request
`2ba516131bdb…`:

- proposed and frozen `K = 16` (allowed range 12–20);
- every raw vector and deviation recorded;
- rejection rates reported at `1e-6`, `0.01`, `0.03`;
- stop immediately if any absolute deviation exceeds `0.05`;
- its own caps: `48` physical requests, `$0.25`;
- requires a separate future live approval;
- repetitions are not treated as independent prompt forms.

The probe preflight is repository-backed: it recomputes the canonical probe hash,
requires the loaded document to equal `build_probe_preregistration()`, and
validates the v2 protocol key and its reproducibility, the normalization-policy
hash, the model, the endpoint, the caps and the frozen request hash before any
call.

## 7. Tests

New tests cover: sums exactly `1.0`; sums at and just inside/outside `0.99` and
`1.01`; suspect deviations through `0.05`; hard deviations above `0.05`;
negative/non-finite/empty/mismatched vectors; raw-vector retention on invalid
normalization; normalized metrics and argmax preservation; v1 compatibility; v2
protocol-key separation; runner handling/reporting of `complete_renormalized`;
registration and output-path segregation; and zero provider calls during offline
preparation and gating.

## 8. Future live commands (NOT run; each needs separate approval)

v2 optional-board pilot:

```
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src \
  python -m apart_incident_response.jev_choice_pilot_v2 \
  --live --approval "<ref>"
```

v2 diagnostic probe:

```
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src \
  python -m apart_incident_response.jev_normalization_probe_v2 \
  --live --approval "<ref>"
```

## 9. Successor pilot pacing (v3, #186)

The stopped v2 optional-board pilot ended on `writer_http_429_rate_limited` from
the **Ling/OpenRouter** writer path, not Jev: Jev completed 50 receiver calls
while Ling/OpenRouter stopped after 29 physical attempts for 25 logical writer
turns. The v2 result is immutable and the observed 12/12 COMM silences and zero
exposures remain valid partial-run observations. A successor writer transport
(`ling-writer-openrouter-pacing-v3`, 3.25 s minimum interval between physical
OpenRouter attempts, bounded Retry-After handling, sanitized provenance) and a
fresh v3 registration are documented in
[`docs/jev-choice-pilot-pacing-v3.md`](jev-choice-pilot-pacing-v3.md). Pacing
addresses the documented 20 RPM free-model ceiling but cannot guarantee relief
from a daily quota or upstream-provider capacity limit. #159 remains blocked
until verified real-message exposure exists.
