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
