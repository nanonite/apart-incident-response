# Jev Choice replay — v5 offline inference (#198)

Offline analysis of the completed replay-v5 run. **No provider call, no replay
rerun**; the journal and report are read-only inputs.

| | |
|---|---|
| Task | Chainlink **#198** under **#159** |
| Module | `src/apart_incident_response/jev_replay_inference_v5.py` |
| Analysis version | `jev-replay-inference-v5-v1` |
| Artifact | `runs/epic-126/replay-v5/jev-choice-replay-inference-v5.json` |
| Artifact sha256 | `b892a8d514623aca17b83f17a59e9e699d773b48f059b7b954b6239ff7d6f2ce` |

## Inputs (pinned, re-verified before any analysis)

| Input | sha256 |
|---|---|
| `runs/epic-126/replay-v5/jev-choice-replay-v5.jsonl` (51 rows) | `5e9f7322bdb29baf16b18f9b4f4181e9a88ad454e0394ea379e4cdea29b1fede` |
| `runs/epic-126/replay-v5/jev-choice-replay-report-v5.json` | `0ec84446d697bca91c25e155b3cd61f43b4e7706e6df185ea08c3685a8f88310` |
| `runs/epic-126/replay-v5/jev-choice-replay-preregistration-v5.json` (file) | `3c02f8bb44c11d6edd050daf32950e3cf8365f79638e92d46181df764945ddd7` |
| registration content hash | `0a81e400f598d16742301d7c07cbaf5398fa861b4fa1701c15405391ab4f6d15` |
| run commit | `3e678ac` |

## Fail-closed verification (27 hash/structure checks)

Hash layer: journal, report, registration file and registration content hash
against the pins.

Structure layer: report `status == completed`; report registration hash matches;
journal row count == 51 == report rows; no duplicate `(event_id, branch)` keys;
no duplicate report events; all three branches present for all 17 events and no
unknown branch; every row `valid`, `status == "complete"` and `error_class` null;
**one** protocol key in the journal equal to the registration and report key;
**one** resolved model equal to the registration; branch `request_hash` and
`state_hash` **recomputed** from the regenerated instance, the frozen pre-read
body and the branch message and matched against both the journal row and the
registration's `pre_read.branch_request_hashes`; exactly the six frozen forms in
the required `1/4/4/1/4/3` event distribution; well-formed vectors (finite,
non-negative, summing to 1 within 1e-6, `shape_valid`/`all_finite`/
`all_nonnegative`/`argmax_preserved`, normalization deviation ≤ 0.05); finite
`entropy_bits`/`p_target`/`feasible_mass` everywhere (so nothing needs
imputing); guard thresholds `delta = 0`, `epsilon = 0.01`; registered inference
rules present; report schedule adherence.

Any failure raises `AnalysisError` and nothing is written.

## Primary estimand and inference

- `d_i = H_real,i − H_placebo,i` per event; averaged **within** prompt form;
  primary estimate = **equal-weight mean of the six form means**;
- preregistered prediction: `Delta < 0`;
- **exact two-sided cluster sign-flip** over the six form means (64 sign
  patterns, floor `2/64 = 0.03125`);
- **form-mean t interval, df = 5** (`t(0.975, 5) = 2.571`);
- the observed estimate must have the preregistered negative direction;
- instance-level t-tests, Wilcoxon tests and instance-weighted means are never
  primary (the instance-weighted mean is computed only to demonstrate that the
  primary is *not* it).

### Result

| | |
|---|---|
| k | 6 forms, 17 complete pairs |
| **Primary estimate** | **−0.7775085127397289 bits** |
| **Exact sign-flip p** | **0.03125** (= 2/64, the k=6 floor; 64 permutations) |
| **95 % form-mean t interval (df = 5)** | **[−1.1722041593435226, −0.38281286613593507]** |
| Direction (negative) | met |
| Interval excludes zero | yes |
| Registered criterion | **met** |

Form means: `0a3349e1…` −1.036555 · `1c1d9f6b…` −0.864235 ·
`2954f568…` −0.643650 · `3196a8d6…` −0.840406 · `55968fe1…` −0.104951 ·
`ce847ac5…` −1.175254 (all six negative).

## Secondary reporting

- per-form `n_pairs`, mean, SD, min/max, negative count and a forest table with
  per-form t intervals (`n = 1` forms report no interval);
- complete-pair counts by form (1/4/4/1/4/3) and by branch (17/17/17 valid,
  0 invalid, 0 unattempted);
- per-event `H_real`, `H_placebo`, `H_null`, `d_i`, `p_target` values and
  differences, `feasible_mass` values and differences;
- guards: `target_ok` 17/17, `mass_ok` 15/17, `useful_uptake` 15/17, 0 target
  violations, 2 mass violations — reported with `filtered_primary_estimate:
  false` and `excluded_from_primary: 0`;
- null manipulation checks: `real − null` mean −0.615288 bits with 17/17 events
  below null, `placebo − null` mean +0.082010 bits with 6/17 below null; null
  stays excluded from the primary contrast;
- normalization tiers: **exact 50**, **complete_renormalized 1**, others 0;
- sensitivity grid over `1e-6, 0.01, 0.03, 0.05`:
  - `1e-6` → 16 accepted pairs, 1 excluded event, k = 6, estimate −0.773556,
    p = 0.03125 → **criterion unchanged, point estimate moved**;
  - `0.01`, `0.03`, `0.05` → 17 accepted pairs, **identical to the primary
    result**;
  - `conclusion_changed` is false at every threshold (definition recorded in
    the artifact; `estimate_changed` / `k_changed` reported separately).

## Claim limits

- approximate **0.203-bit MDE / CI limitation** (`t(0.975,5) × 0.1933 / √6`); a
  null result could not exclude effects below ~0.2 bits;
- conditional scope: **six frozen planning-low prompt forms** and the **paid
  Ling route** that generated the messages; `k` is capped at six by the closed
  form space;
- explicit non-claims: no calibration claim, no population-level or
  cross-family causal claim, no generalization beyond the six forms, no
  instance-level inference;
- **gross vs unique delivered information**: gross replay-eligible
  `i_m_bits` = 26.9443625123 over 17 events (counts within-form repeats) versus
  9.5097750043 over the 6 distinct form/claim treatments; placebo inert at 0.0
  bits. `H_real − H_placebo` is a change in the receiver's output distribution,
  **not** information delivered, and is always kept distinct from objective
  `I_m`.

`registered_causal_uptake.criterion_met: true`, scoped to
"registered conditional scope only (six frozen forms, paid Ling route)".

## Artifact lifecycle

- deterministic: no timestamp, no randomness, no network; identical inputs
  produce a byte-identical file (tested);
- written once with open mode `"x"` — never overwritten, never appended;
- lives outside the live journal/report paths.

## Running

```
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src \
  python -m apart_incident_response.jev_replay_inference_v5
```

Exit 0 writes the artifact and prints the primary result and decision; exit 2
means a gate failed and nothing was written.
