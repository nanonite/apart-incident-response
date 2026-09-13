# Launch Proof

Date: 2026-09-13

## Automated Tests

The containerized test target completed successfully:

```text
just test
Ran 79 tests
OK
```

The production configuration now allows 16,000 tokens per agent and 48,000
tokens per swarm. The sandbox mounts Pi's read-only `node_modules` tree at
`/experiment/node_modules` so the mounted extension can resolve `typebox`.

## Harness Launch

Command:

```text
PYTHONPATH=src python scripts/run_experiment.py \
  --harness-check --output runs/t1/harness-seed-0001
```

The deterministic C0/C1/C2 triplet completed all three agents in every
condition with no failures and 100 percent task success. It recorded the
expected coordination behavior: C0 uptake `0.0`, C1 uptake `0.6667`, and C2
uptake `0.0`. This is harness evidence, not model data.

## Live Launch

A one-seed containerized triplet reached the Pi 0.85.1 process, bubblewrap,
the constrained extension, tool service, and live provider. The run used the
configured `openai-codex/gpt-5.6-luna` model and produced artifacts under the
workspace path `runs/t1/live-configured-seed-0001`.

The live agents did not complete the task: C0, C1, and C2 each had zero
completed submissions. Agents exhausted token or tool-call envelopes while
retrying task reads, queries, and validator-rejected submissions. This proves
the launch path, but is not usable experimental evidence. OpenCode model
access and model/task calibration are deferred.

## Workspace Layout

Run data belongs under `runs/<experiment>/`. The captured results are
available at `runs/t1/harness-seed-0001/matrix.json` and
`runs/t1/live-configured-seed-0001/matrix.json`. For new Task 1 anchor runs,
use `runs/t1/`; it contains one `matrix.json` index, one `sNNNN.json` triplet
summary per seed, and one `sNNNN-C{0,1,2}/` condition directory per condition.
Each condition directory contains its manifest, budget, results, board
database when applicable, agent artifacts, and derived telemetry files. Run
directories are generated data and are excluded from source commits.
