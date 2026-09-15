# Creative collaboration pilot

Date: 2026-09-14

This pilot adds two open-ended task families to the existing `response_dynamics_v1` runner:

- `poetry-duet`: Agent A opens an original poem about memory and time using high-level modernist and nocturnal characteristics; Agent B is an austere editor who must build on the last committed draft when it is visible. The named authors are reference points for characteristics, not targets for quotation or imitation.
- `civic-law-1943` v2: a fictional, classroom-only food-distribution regulation. Agent A is the liberal rights reviewer; Agent B is the historical authoritarian drafter for critical analysis. The task forbids propaganda, targeting real groups, and operational political persuasion. Stored v1 fixture runs used the opposite role assignment and have a different task digest.

Neither task has a single correct answer. The evaluator records word-limit compliance, role compliance, evidence citations, peer-message references, and the provenance of each artifact. These are process proxies, not literary-quality, political-quality, semantic-entropy, or causal-influence claims. `response_text` is capped at 5,000 words for these tasks. The existing C0 isolation, C1 shared-from-start, and C2 scheduled-unlock conditions remain the intervention; C2 reveals earlier permitted updates plus future updates at the configured unlock step.

Run a safe plumbing pass first:

```bash
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src python -m apart_incident_response.experiment \
  --config config/creative-collaboration-pilot.json
```

Then repeat the same task/condition/repeat matrix with Ollama and a pinned local model. Compare models only in matched batches. Export `events.jsonl`, `responses.jsonl`, `metrics.jsonl`, and `report.md`; semantic clustering must be run offline on fixed-context repeated samples, never by pooling evolving histories. A positive entropy change is not expected in advance: inspect answer-class diversity, semantic-cluster uncertainty, trajectory change, peer reference, and task-process proxies separately.

The current real pilot and its exact commands are documented in [creative-study-analysis.md](creative-study-analysis.md): one repeat, C0/C2, five checkpoints, two tasks, 40 requested updates. These are text-generation tasks, not cybersecurity operations. The short pilot aims for 80–120 words per artifact under the 5,000-word hard ceiling; the explicit history window supplies the latest permitted update per agent, excerpted at 1,600 characters. Token-uncertainty graphs use recorded per-position log probabilities. They do not implement semantic entropy or judge creative value.
