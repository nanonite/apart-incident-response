# Communication Battery Deviation Log

Version: `two-agent-iso-full-comm-v1`

- Implementation is fixture/offline complete for the protocol, six families,
  runner, exact information calculations, provenance, calibration summary,
  and aggregate report.
- No live provider request has been made. Live cost is `$0.00`.
- DeepSeek V4.1 Flash is the nominated bounded-pilot model, with a hard `$20`
  ceiling. The provider smoke gate and explicit budget/power go decision are
  still pending.
- The proposed 54-cell/full battery and top-K entropy extension were not run.
- Entropy remains separately labeled and event-aligned to the first model
  output after peer-read exposure. Read-time entropy is not used.
- Full repository tests remain environment-incomplete because this worktree
  lacks `numpy`, `cryptography`, and `bubblewrap`; focused new-battery and
  legacy experiment tests pass.
- No credentials, answer keys, or raw sensitive artifacts were added.
- A separate bottom-of-reasoning smoke harness now supports the supplied
  OpenRouter `:free` models, capped at three requests. It has not made a live
  request; its default plan costs `$0.00`.
- A bounded Ling-3.0-Flash-VL smoke was run through the existing repository
  `.env` key without copying the file: 3/3 elementary reasoning cases were
  correct, 3/3 returned logprob records, and cost was `$0.00`. Returned
  logprob coverage was partial (approximately 0.093-0.148), so it is not an
  entropy-complete capability result.
- A six-family medium-complexity necessary-cell pilot attempted 18
  ISO/FULL/COMM runs. All runs were retained; provider outputs without usable
  logprob records were classified invalid. ISO: 0/6 valid, FULL: 0/6 valid,
  COMM: 0/6 valid in the final strict-logprob pass. Cost was `$0.00`.
- `uv sync --group dev` resolved Python dependencies. Full tests pass when run
  in a temporary Nix shell supplying `numpy`, `cryptography`, `zlib`, and
  `bubblewrap`; those host packages are not project dependencies.
