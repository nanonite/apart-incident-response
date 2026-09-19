# Epic 126 T4 Go/No-Go Memo

Decision date: 2026-09-14

## Observed Inputs

- T1 retained-pilot audit: 18/18 behavioral runs invalid; zero submitted
  agents and zero validator outcomes.
- T1 corrected smoke: 24 independent instances, 12 design cells, 72
  ISO/FULL/COMM condition-runs, 144 agent requests, 48 valid and 24 invalid
  condition-runs, zero verified useful-use events.
- T2 capability probe: 3 requests against
  `inclusionai/ling-3.0-flash-vl:free` through
  `https://openrouter.ai/api/v1/chat/completions`.
- Ordinary text returned records but visible-span alignment was not exact.
- Tool-call arguments returned zero logprob records.
- Reasoning-bearing output returned zero logprob records and terminated at the
  token limit.
- Full-vocabulary logits: unavailable.
- Observed live cost: `$0.00`.

## Decision

**NO-GO for T3 and all scaling.** No entropy pilot, six-family battery,
second-model comparison, or 6480-run/model expansion is authorized.

The implementation supports observed-token/top-k partial entropy when records
and top-k mass are present, but this T2 probe did not establish aligned target
coverage for the planned output kinds. Top-k mass is not a substitute for
visible-token alignment or full-vocabulary logits.

## Required Next Gate

1. Obtain a pinned provider/output-kind combination with reproducible visible
   span alignment for ordinary text and the exact output kind needed by T3.
2. Re-run the three-kind capability matrix with the same request cap and retain
   missing/tool/reasoning failures.
3. Obtain explicit approval for a preregistered real/placebo/null pilot only
   after T1 selects a nonzero verified-use cell and T2 passes.
4. Keep the full battery blocked until a separate power/cost decision.
