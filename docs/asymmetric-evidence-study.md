# Asymmetric evidence study

Date: 2026-09-13. This is a five-checkpoint, two-agent, offline study with a 300-second task-run budget. Checkpoints are not yet paced at wall-clock minutes: each agent request has a wait limit, and quick requests advance sooner. The default UI preset runs three tasks (`database-insider`, `cache-incident`, and `campus-security`) twice under the selected communication conditions. The database task contains only a fictional `TEST_ONLY_KEY` marker in a local fixture; it is not a credential and is never used against a real service.

The control question is: when Agent A receives a useful defensive finding and Agent B does not, does B use the permitted peer update? `neutral` gives the normal restricted prompt. `peer_review` asks an agent to inspect visible peer evidence. `required_peer_check` asks it to state whether it agrees or disagrees. C0 measures isolation, C1 measures sharing from the start, and C2 unlocks earlier peer history at checkpoint 4. Agents submit updates at each checkpoint.

## Run from the panel

1. Start the local panel:

   ```bash
   UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src python -m apart_incident_response.panel --db artifacts/observatory.sqlite --port 8765
   ```

2. Open `http://127.0.0.1:8765`.
3. Choose **Asymmetric study · 3 tasks**, **5 checkpoints**, **2 repeats**, and `C0,C1,C2`.
4. Run once with **Ask agent to review peer update**, then run again with **Require agree/disagree check**. Use the same model and seed settings between runs.
5. The **Live run** pane follows the active task and condition. It shows A/B queued or generating states, submitted responses, exact contexts, elapsed request/run time, the most recent event, and only the peer responses delivered by the visibility policy. Responses appear when Ollama completes a request, without token streaming. **Download batch logs · ZIP** and **Responses · JSONL** appear after completion, stop, or failure. A portable snapshot offers JSON and JSONL downloads.
6. Use **Shared log** to select a run and minute. The three panes are researcher truth, Agent A visibility, and Agent B visibility. Use **Run inspector** for raw event JSON and **Research handoff** for exports.

## What to audit

For each condition and repeat, compare `communication_available`, `visible_message_ids`, `communication_used`, and `peer_reference_detected` in `task_update`. `communication_used` means a peer event was delivered; `peer_reference_detected` is only a textual proxy. It is not a causal claim. Compare task score and answer-class/semantic analyses separately.

Events are stored append-only in the SQLite database passed to `--db`. The panel report is derived from those events. Exported bundles contain `events.jsonl`, `responses.jsonl`, `metrics.jsonl`, provenance, and audit actions. Do not treat the synthetic database task as a live security test.
