# Token-level logprobs: extraction, storage, and centralization

## What we recorded
Full pilot run on real inference (Ollama `gemma2:2b`, `logprobs=True`, `top_logprobs=5`):

| Condition | Batch | Generation calls | Events |
|---|---|---|---|
| C0 isolated | `batch-687582293688` | 50 | 309 |
| C1 shared | `batch-93d60807d1de` | 50 | 329 |
| C2 unlock@3 | `batch-19cbd342555c` | 50 | 319 |
| **Total** | | **150** | **929** |

All 150 generations returned usable token-level logprobs (`logprobs_available=True`, 7,402
logprob entries). No retry-fallback path was hit on this endpoint.

## Extraction rate (what/how often per unit of time)
- One inference call produces one `generation_result` event carrying one `logprobs` array
  (one entry per output token: `token`, `logprob`, plus `top[5]` alternate tokens with their
  logprobs).
- Wall time per condition batch (50 calls): about 13 minutes, i.e. roughly **3.8 generation
  calls per minute** and ~200 ms of inference per logprobs-annotated output token as served.
- Output token counts are the logprobs dimension: mean **50.3 output tokens** per call, 440
  input tokens per call, 7,552 total output tokens across the run.

## What is stored and at what cost
- Logprobs live in `generation_result` payloads inside the append-only, hash-chained SQLite
  store (`event_id`, batch, SHA-256 chain, UPDATE/DELETE blocked by triggers).
- The `task_update` payload carries a compact pointer (`logprobs_available`,
  `logprob_token_count`) for the per-minute observation grid; the full array stays on the
  generation event so dashboard/analysis can join by `attempt_event_id`.
- Size: with top-5 logprobs a `generation_result` payload averages ~16.3 KB vs ~0.3 KB for
  the fixture runs; a full 5-task update averages 3.4 KB. The whole 929-event dataset is
  **3.84 MB** on disk before ZIP; the ZIP bundles are ~275 KB per condition batch.

## Centralization on GitHub
- `artifacts/` is gitignored, so the pushable artifact is the export bundle built by
  `panel.bundle()`: `events.jsonl`, `responses.jsonl`, `metrics.jsonl`, `manifest.json`,
  `README.md`. Per-condition bundles are in `exports/apart-research-bundle/`.
- The static dashboard snapshot `dashboard/dist/demo.json` (2.3 MB, real C2 data with
  logprobs) renders the full event grid, minute bar, audit trail, and 3-pane shared log
  without any server; it is committed so GitHub Pages/hosting serves the web display.
- Never push the artifact DB, `.openai/`, or `APART_MODEL_TOKEN*` (gitignored).

## Caveats (unchanged from protocol)
- `metrics.jsonl` contains per-agent answer-class entropy proxies in bits, not semantic
  entailment entropy; fewer than two classified samples yields `null`, not zero.
- Private evidence, evaluator truth, and current-step output never enter shared history;
  projections are the only visibility mechanism.