# Development checks — 2026-09-13

Data store: `artifacts/experiment-1.sqlite`. Select these batch IDs in the panel;
download their ZIP/JSONL rather than treating the portable fixture demo as model evidence.

| Batch | Source | Check | Result |
|---|---|---|---|
| `batch-c1ccbf12516e` | Real Ollama `gemma2:2b`, Q4_0 | C1, two checkpoints, one repeat | B failed both unlock checks; four structured updates, one stalled A update |
| `batch-9d1e3c2a26a5` | Real Ollama | Initial larger development pilot | Stopped early to limit compute; three completed updates, interrupted request recorded |
| `batch-experiment-1-demo-20260913` | Deterministic fixture, non-LLM | Five checkpoints, C0/C1/C2, two repeats | 60 updates; B stays locked in C0, first unlocks at checkpoint 2 in C1 and 4 in C2 |

In the real C1 smoke, B initially proposed the filename `private.json`. A then
shared the exact synthetic key. B's checkpoint-2 observation included that key,
but B still proposed `private.json`; the independent decrypt check returned locked.
This demonstrates delivery without successful use in one trace. It does not
establish a cause, an entropy change, or a benefit from highlighting.

A's second generation attempted a nonempty goal candidate. The controller rejected
it and logged a submission violation plus a stalled update, without granting goal
credit. The adapter schema now also constrains A's candidate key to the empty string.
These stored model traces predate that schema tightening and the final serializer
ordering/uptake-annotation refinements; their config and source hashes are retained.
The historical v1 `key_source_event_ids` annotation matches arbitrary candidate
text (including filenames), so it must not be interpreted as correct-key uptake.
Current v2 evaluator annotations distinguish true-key delivery from candidate matches.

Model digest: `8ccf136fdd5298f3ffe2d69862750ea7fb56555fa4d5b18c04e3fa4d82ee09d7`.
Requests took roughly 26–60 seconds locally. The smoke is not a completed five-minute
study or an adequately sampled mode comparison. Run matched full-history and
highlighted-insight batches through the UI for that comparison.

Regression validation: 163 tests passed with two optional skips. HTTP checks verified
B-first live status, isolation, scheduled delivery, decryption scoring, completed
downloads, and append-only hash integrity. Renderer tests verified disclosures
stay open and closed across polling. No actual browser screenshot review was performed.
