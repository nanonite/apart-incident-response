# Real creative-track analysis

Date: 2026-09-14 (America/Bogota).

## Study and controls

Two restricted agents receive the same facts and one shared objective. The poetry track has A as an opening poet with modernist/nocturnal characteristics and B as a contrasting editor. The fictional 1943 food-regulation track has A as a liberal constitutional reviewer and B as a historical fascist/authoritarian drafter for critical analysis. Coercive historical provisions are objects of critique; this is not an endorsement or a real-world political campaign. These v2 tasks replace the earlier creative task definitions; stored v1 fixtures are retained and have different task digests.

The first real pilot uses Ollama `gemma2:2b`, temperature 0.6, seeded calls, no retries, five logical checkpoints, and one repeat in C0 and C2 for each task: 40 requested updates. Both contexts are frozen before either generation. C2 opens at checkpoint 4 (step 3); it can reveal earlier permitted peer records. Each creative task supplies the latest one update per agent, with an explicit 1,600-character artifact excerpt. The global event log preserves full original outputs. The declared history window means C2 does not supply the whole historical artifact corpus. Exact messages, selections, bytes and task versions are logged.

This is a creative text-generation study, not a cybersecurity experiment. The one-repeat pilot runs C0 before C2 for both tasks: physical order is not counterbalanced until additional repeats reverse it. Condition labels and random source IDs in history can also make pre-unlock prompts differ despite matched seeds. Neither matching seeds nor a signed entropy contrast alone establishes causality.

Each task/condition run has a 900-second budget. Requests have a 150-second limit in the main pilot, and the batch has a 3,600-second budget. Calibration used 120-second request waits. The complete calibration returned four valid updates, mean controller latency 81.847 seconds, and p95 116.346 seconds. Extrapolating ten requests from the mean is about 818 seconds; the p95 extrapolation is about 1,163 seconds. Neither is a guarantee that 900 seconds is sufficient. Hardware was CPU-only under heavy memory/swap pressure; runtime resource load is a potential confounder.

The 5,000-word cap is an upper boundary, not the requested artifact length. This pilot aims for 80–120 words and limits each full structured output to 512 tokens, including metadata. A longer wall-time budget cannot repair token-truncated JSON, missing evidence IDs, or invented references. Calibration was a poem run, so its valid-output rate does not establish law-task reliability.

## Existing analysis-report scripts

The supplied local `research/analysis_temperature_1/` scripts describe a different protocol: 30 READ/WRITE/DECRYPT/SUBMIT action turns, base/switch/placebo arms, 20 seeds, and API top-20 probabilities. They cannot be run unchanged on these artifact-updating C0/C2 five-checkpoint logs. Their folders were already untracked and remain untouched. An additional existing `research/two_agent_entropy/joint/analyze_panel.py` merges alternatives across token positions in its `logp_entropy` function; that does not compute mean predictive token entropy. It also replaces unscored outcomes with zero in one summary and divides by zero when there are no probability rows. This study uses a new artifact-only analysis module instead.

| Original stage | Creative-study replacement | Limit |
|---|---|---|
| s00 integrity | `validation.json`, hash-chain segment verification, `checkpoint-grid.csv` | Verify segment predecessor against full store for global continuity |
| s01 descriptives | `inventory.csv`, `responses.csv`, latency/length/source provenance | Checkpoints and agents are repeated measurements |
| s02 entropy validation | `tokens.csv.gz`, independent entropy recomputation, byte alignment | Top-5 support, not full vocabulary |
| s03 endpoints | Per-role, per-repeat C0/C2 pre/post contrasts | One repeat: descriptive only, no significance claim |
| s04 interrupted series | Raw step trajectories | Five points do not support credible model selection or ITS inference |
| s05 event study | C2 unlock and actual delivery/reference markers | Automatic delivery is not an agent READ action |
| s06 coupling | Lexical trajectory and peer-overlap proxies | No action-class MI or causal effect invented |
| s07 functional form | Plotted trajectories retained for inspection | No physics curve fitted to five points |
| s08 detector | Deferred | Requires independent calibration and validation runs |
| s09 robustness | Artifact-only vs whole-JSON entropy, coverage and probability validation | Logprob completeness and constrained decoding remain limitations |

## What entropy means here

For each captured token position, probabilities are deduplicated and validated; probability mass greater than one fails validation. Let C be the reported support mass. The report computes the truncated sum H_lower = −Σp log₂p; H_renorm = H_lower/C + log₂C on normalized support; and H_residual_bucket = H_lower − (1−C)log₂(1−C). It validates the latter two against the existing shared normalizer. It never mixes probability coordinates from different output positions. Bytes must reconstruct the raw JSON exactly before selecting tokens wholly inside `response_text`, so structural JSON tokens do not masquerade as artistic uncertainty. Missing probability data remains null.

Entropy contrasts are signed: C2 post−pre and the corresponding C0 change, then their difference. No direction is prescribed. Workflow-label frequencies (`draft`, `revision`, etc.) are a separate proxy and are null at one repeat. Creative value requires independent review. The exported shuffled `blind-review-sheet.csv` requests coherence, novelty, integration/contest of peer content, and role-relevant trade-offs. Without those scores, no entropy–quality correlation can be claimed.

Fixed-context semantic entropy is a separate next experiment. Define what counts as the same interpretation or policy proposition before clustering poems/laws. Do not pool evolving contexts and call it predictive semantic uncertainty. The original [Semantic Uncertainty paper](https://arxiv.org/abs/2302.09664) and [Nature work](https://www.nature.com/articles/s41586-024-07421-0) do not establish that artistic novelty, collaboration value, and semantic uncertainty coincide.

## Running and monitoring

On a machine with sufficient free disk:

```bash
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src python -m apart_incident_response.panel \
  --db artifacts/creative-study-real-v2.sqlite --port 8766
```

Then, from another terminal:

```bash
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src MPLCONFIGDIR=/tmp/apart-mpl-cache \
  python -u scripts/run_creative_tracks.py --panel http://127.0.0.1:8766 \
  --output research/creative_collaboration/pilot-v2 --repeats 1
```

The current machine had only about 16 MB free disk at launch. Its live panel uses `/dev/shm/apart-creative-study-real-v2.sqlite` instead. This is transient RAM-backed storage. The monitor writes an atomic durable `recovery-export.zip` to the project disk after each terminal task run. The final export and compressed database backup must be retained; RAM data alone is not durable. A monitor startup race was fixed without relaunching the already running batch. Resume monitoring using `--batch <batch-id>`; it makes no duplicate inference requests.

Open `http://127.0.0.1:8766`. The panel owns the worker, so its live cards can verify waiting/generating/submitted/terminal states. Port 8765 was left running with its original data. Export traces can be downloaded during execution as a partial snapshot. After completion, use `research/creative_collaboration/pilot-v2/report.html` and `creative-study-with-analysis.zip` for the graphs, tables and source logs. Analysis never feeds back into the agents.

To reproduce through the UI after the active batch ends: choose **Creative collaboration · 2 tasks**, **Isolation + scheduled unlock**, **5 checkpoints**, **1 repeat**, **unlock step 3**, **Ollama / gemma2:2b**, then change **Peer engagement** to **Neutral observation** (the creative selector initially applies peer review). Set **Task-run budget 15 minutes**, **Request wait 150 seconds**, **Whole-batch budget 60 minutes**, **Output limit 512**, **Peer-history byte limit 6000**, **Full history only**, **Task-defined roles**, and enable **Request token log-probabilities**. Leave delivery delay/cost zero and request-only delivery off. Click Run experiment once. The UI's study label differs from the script's label, so use its actual recorded batch/config hash when analyzing it. Four task/condition runs produce 40 requested updates; this is not a single five-minute run. Monitor cards/heartbeats are activity records, not a stream of hidden reasoning.

Recompute from a saved export without starting a model:

```bash
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src MPLCONFIGDIR=/tmp/apart-mpl-cache \
  python -m apart_incident_response.creative_analysis \
  --events research/creative_collaboration/pilot-v2/research-bundle.zip \
  --output research/creative_collaboration/reanalysis
```

For the physics handoff, start with `experiment-matrix.csv` (one row per task/condition/repeat) and `responses.csv` (one row per agent/checkpoint). `token-uncertainty-metrics.jsonl` supplies derived measurements and their source IDs; the original exported `metrics.jsonl` stays unchanged. Join `source_event_id` to `tokens.csv.gz` for position-level measurements, and join `observation_id` or `generation_event_id` to the ZIP's `events.jsonl` for exact supplied contexts or unaccepted raw generations. `task-catalog.json` holds the recorded tasks; `metric-catalog.csv` defines the quantities. No context states need to be reconstructed from the current code.

The isolated poem pilot exposed invalid peer references and malformed insights despite returning actual poem text. Preserve these as rejected submissions, with raw generations in the export and `generated_response_text`; do not retrospectively accept them or replace them with zero entropy. The existing harness labels both invalid and absent generations `stalled_no_generation`; analysis additionally distinguishes `rejected_generated_output` from genuinely absent generation without rewriting the log. Rejections also remove usable text from subsequent agent history, creating a further trajectory confound. Complete-run contrasts stay null when a run is incomplete or has errors. Separately labelled partial contrasts expose the surviving valid artifacts and pre/post sample counts, with an explicit selection-bias warning. Before the next controlled batch, consider a new versioned output schema that constrains references to delivered IDs (an empty list while isolated), and calibrate it for Gemma. Do not change that contract inside this batch.

Only Gemma is installed here. Future model comparisons should use identical task versions, conditions, checkpoints, role assignments, output budgets and analysis rules, with separately recorded model digests and enough repeated runs. No paid calls, model downloads, network tools, or agent side channels are introduced.
