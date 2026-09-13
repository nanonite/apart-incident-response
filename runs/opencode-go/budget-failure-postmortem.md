# Budget-failure postmortem — `opencode-go/kimi-k2.6`, seed 1

Date: 2026-09-13. Tracked in Chainlink #74. Source summaries are
`live-summary.json`, `triplet-s0001/s0001.json`, and
`triplet-s0001/matrix.json`. The structured extraction is
`budget-failure-analysis.json`.

## Conclusion

The evidence supports an agent loop or task-validator problem rather than a
too-small cumulative budget. The existing 16,000-token per-agent and
48,000-token aggregate limits remain unchanged. The smallest fix is to return
the validator's missing terms from `task_submit`, so a retry can correct its
diagnosis instead of receiving a generic rejection.

The historical raw per-agent Pi events and tool audits were deleted before the
#73 retention work. The saved summaries preserve exact per-agent token totals
through each failure overage and exact condition totals, but they do not
preserve exact per-agent tool-call counts, per-turn usage, or individual
`task_submit` rejection records. Those fields are explicitly `null` in the
structured analysis; they are not reconstructed from aggregates.

## Recovered per-agent token usage

The runtime reports `token overage` after a 16,000-token claim. Therefore the
per-agent totals below are the exact claim plus the recorded overage.

| Condition | Agent | Tokens | Overage | Status |
| --- | --- | ---: | ---: | --- |
| C0 | agent-1 | 16,086 | 86 | budget_exhausted |
| C0 | agent-2 | 18,089 | 2,089 | budget_exhausted |
| C0 | agent-3 | 16,323 | 323 | budget_exhausted |
| C1 | agent-1 | 17,386 | 1,386 | budget_exhausted |
| C1 | agent-2 | 16,677 | 677 | budget_exhausted |
| C1 | agent-3 | 16,009 | 9 | budget_exhausted |
| C2 | agent-1 | 18,791 | 2,791 | budget_exhausted |
| C2 | agent-2 | 16,719 | 719 | budget_exhausted |
| C2 | agent-3 | 16,546 | 546 | budget_exhausted |

Condition totals were C0 `50,498` tokens / `43` tool calls / `30` turns, C1
`50,072` / `53` / `26`, and C2 `52,056` / `55` / `31`. Board telemetry
recorded C0 `0/0`, C1 `0/0`, and C2 `1/0` board reads/writes.

## Tools and failure behavior

The configured `task-diagnostic-v1` profile exposes `task_read`, `task_query`,
and `task_submit` in every condition. C1 and C2 additionally expose
`board_read` and `board_append`. The retained condition summaries show the
board totals above, but the deleted audit files prevent an exact operation
sequence or per-agent repetition count.

The summaries record zero accepted submissions. They contain no retained
`validator_outcomes`, so the historical files cannot independently prove the
number or text of rejected `task_submit` attempts. The prior narrative
reported a repeated `task_read` → `task_query` → `task_submit` loop with the
generic validator error. The deterministic test now reproduces the important
failure mode and verifies that the rejection names each missing term.

The validator requires the seeded token, literal `cache_mode`, `local`,
`shared`, and `outage`, plus the expected causal relationship. `outage` is not
present in the assigned evidence or the neutral prompt. Evidence is split
across agents, and a generic rejection did not tell an agent what to repair.
That makes a non-converging retry loop a better explanation than a budget that
was merely too small.

## Output limit versus cumulative budget

`runtime.py` stages `models.json` with `maxTokens=16,000` as a per-request
provider override when supported. That setting is not a cumulative experiment
budget. The runtime separately counts observed provider usage and terminates
an agent when `agent_tokens_used > per_agent_token_budget`; the saved failure
reasons identify that cumulative hard stop and the resulting overage. No
retained evidence shows a provider-side response truncation. The bounded
follow-up should retain request events so this distinction is directly
inspectable.

## Fix and validation

`TaskToolService.submit` now returns `diagnosis rejected by the task validator
(missing or incorrect: ...)`, using the validator's deterministic
`missing_terms`. No budget, isolation, prompt, or validator acceptance rule
was widened.

Before: a rejected diagnosis returned only the generic validator error.
After: the deterministic submission test receives all missing terms, allowing
the next attempt to add the missing `outage` term and satisfy the existing
acceptance rule.

`PYTHONPATH=src:. python3 -m unittest discover -s tests` passes 129 tests with
2 expected skips. A bounded real triplet was not run because no OpenCode API
key file, `OPENCODE_API_KEY`, or Pi auth file is available in this environment.
When credentials are mounted, run exactly:

```bash
PYTHONPATH=src python scripts/run_experiment.py \
  --real-anchor --seeds 1 \
  --model opencode-go/kimi-k2.6 \
  --output runs/opencode-go/live-fix-seed-0001
```

Do not run the five-seed matrix until that triplet produces retained per-agent
traces and passes its bounded validation gate.
