# Jev cell-selection decision memo (epic-126)

Scope: offline analysis of the committed `runs/epic-126/confirmatory-v3.*`
artifacts. No live model calls, no new collection, no push or merge. Source
artifact: `runs/epic-126/jev-cell-selection-v1.json`.

## Data
- Confirmatory screen: 85 instances (5 representative cells x 17), 255 runs,
  510/600 physical requests, `$0.00`, no provider failures.
- Validity: 211 valid / 44 invalid (`invalid_output_empty` 43,
  `invalid_output_unparsed` 1).

## Per-cell audit (preregistered Holm over five cell-specific C_need claims)

| cell | valid ISO/FULL/COMM | ISO->FULL diff | Newcombe 95% | McNemar p | Holm p | FWER |
|---|---|---|---|---|---|---|
| planning:low | 17/17/17 | 0.588 | — | 0.00195 | **0.00977** | **yes** |
| hypothesis:medium | 14/12/14 | 0.583 | — | 0.0156 | 0.0625 | no |
| planning:high | 7/17/5 | 0.714 | — | 0.0625 | 0.1875 | no (validity) |
| hypothesis:low | 14/17/11 | 0.357 | — | 0.227 | 0.453 | no |
| reference:low | 17/15/17 | 0.133 | — | 0.500 | 0.500 | no |

Overall matched ISO->FULL: n=65 complete pairs, difference 0.446, Newcombe
[0.291, 0.569], McNemar exact p=4.18e-07.

## Decision
- **Advance: `planning:low`.** Fully valid in all three conditions (17/17/17),
  holm-significant C_need (0.0098). Voluntary board use 14/17 with 20 messages,
  31.7 transmitted bits, 0 rejected writes — but only **2/17 post-read
  correlation** events. The COMM>ISO difference is therefore **not** established
  as causal communication, and it also confounds board use with the extra
  finalizer turn (COMM 2 turns vs ISO 1). Treat these results as **selection
  data, not fresh confirmation**.
- **Hold: `planning:high`.** 22 invalid runs (ISO 10/10 at the token cap, COMM
  12/17), no provider failures. Provider and parsing paths are clean; ISO
  invalid runs consume exactly `max_tokens=1024`, i.e. length truncation with
  empty content. COMM per-agent truncation cannot be proven from the retained
  totals because per-output `finish_reason` and per-agent output tokens are not
  recorded. A focused validity-fix task blocks further planning-high
  collection; no live rerun without a new registration.
- Others do not advance: `hypothesis:medium` is not Holm-significant; `hypothesis:low`
  and `reference:low` show little joint-information benefit.

## Measurable now vs only after Jev capability/calibration
- **Now (Ling-only):** ISO/FULL/COMM success, C_need with complete-pair
  inference, voluntary board use, transmitted bits, post-read **correlation**,
  rejected writes, validity/missingness. This is selection evidence only.
- **After Jev capability/calibration (#155/#156) and replay (#159):**
  receiver-side finite-decision p-vectors and H(Choice p), calibration checks,
  and matched real/placebo/null receiver replay for **causal uptake** and the
  entropy effect. p<0.05 is **not** an entropy gate and post-read correlation is
  **not** causal use.

## Approval required before a live Jev pilot
A new versioned registration (v4 or amendment) that freezes: planning-low fresh
seeds, Ling writer / Jev receiver roles, optional board, ISO/FULL controls,
matched real/placebo/null receiver replay, validity and calibration gates,
message-exposure and causal-uptake definitions, discordant-pair sample size,
and request/cost stop caps. No live pilot starts without explicit approval.
