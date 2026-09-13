# Asymmetric evidence study

Date: 2026-09-13. This is a five-minute, two-agent, offline study. The default UI preset runs three tasks (`database-insider`, `cache-incident`, and `campus-security`) twice under the selected communication conditions. The database task contains only a fictional `TEST_ONLY_KEY` marker in a local fixture; it is not a credential and is never used against a real service.

The control question is: when Agent A receives a useful defensive finding and Agent B does not, does B use the permitted peer update? `neutral` gives the normal restricted prompt. `peer_review` asks an agent to inspect visible peer evidence. `required_peer_check` asks it to state whether it agrees or disagrees. C0 measures isolation, C1 measures sharing from the start, and C2 unlocks earlier peer history at minute 4. Every agent still submits one update per minute.

## Run from the panel

1. Start the local panel:

   ```bash
   UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src python -m apart_incident_response.panel --db artifacts/observatory.sqlite --port 8765
   ```

2. Open `http://127.0.0.1:8765`.
3. Choose **Asymmetric study · 3 tasks**, **5 minutes**, **2 repeats**, and `C0,C1,C2`.
4. Run once with **Ask agent to review peer update**, then run again with **Require agree/disagree check**. Use the same model and seed settings between runs.
5. During the run, the active banner shows the study and engagement mode. The minute bar shows elapsed time and the seconds remaining in the current minute. The live cards show A/B submissions, answer class, score, deadline status, and stalled updates.
6. Use **Shared log** to select a run and minute. The three panes are researcher truth, Agent A visibility, and Agent B visibility. Use **Run inspector** for raw event JSON and **Research handoff** for exports.

## What to audit

For each condition and repeat, compare `communication_available`, `visible_message_ids`, `communication_used`, and `peer_reference_detected` in `task_update`. `communication_used` means a peer event was delivered; `peer_reference_detected` is only a textual proxy. It is not a causal claim. Compare task score and answer-class/semantic analyses separately.

Events are stored append-only in the SQLite database passed to `--db`. The panel report is derived from those events. Exported bundles contain `events.jsonl`, `responses.jsonl`, `metrics.jsonl`, provenance, and audit actions. Do not treat the synthetic database task as a live security test.
