# Launch Proof

Date: 2026-09-13

## Automated Tests

The containerized test target completed successfully:

```text
just test
Ran 109 tests
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
the launch path, but is not usable experimental evidence.

## OpenCode Go Validation

The pinned Pi checkout reports version 0.85.1 and contains native opencode-go
plus x-opencode-session support. Deterministic tests verify the controller's
model selection, opencode.ai:443-only relay, per-agent session identity,
transient key staging, child-environment exclusion, cleanup, and redacted
evidence.

The managed outer command sandbox initially rejected Bubblewrap's private
network namespace with `bwrap: loopback: Failed RTM_NEWADDR: Operation not
permitted`. The configured rootful Docker runtime has `SYS_ADMIN` and
`NET_ADMIN`, and its corrected Bubblewrap `--unshare-net` probe passed without
removing the child namespace or widening egress.

A real OpenCode Go C0 request ran in that Docker/Bubblewrap environment on
2026-09-13 with `opencode-go/kimi-k2.6`: it completed in 9.43664 seconds,
used 728 provider tokens, and submitted zero tools. The matched Task 1 C0/C1/C2
triplet also reached the provider and wrote metrics, but all nine agents
exceeded the existing 16,000-token per-agent envelope. C0 used 50,498 tokens
and 43 tool calls, C1 used 50,072 tokens and 53 tool calls, and C2 used
52,056 tokens and 55 tool calls. The triplet therefore failed its acceptance
gate; the five-seed matrix was not run. The current run remains a launch and
telemetry validation, not usable task-success evidence.

Only the sanitized summary and triplet metrics were retained at
`runs/opencode-go/`; all raw provider workspaces and temporary auth copies
were deleted.

## Containerized Matrix Launch

The reproducible outer launch path is intentionally separate from the managed
Codex command sandbox. Start a dedicated trusted session with explicit full
access, then verify Docker and the nested boundary before any provider run:

```bash
codex --sandbox danger-full-access --ask-for-approval never --cd "$PWD"
just docker-check
just container-isolation
just container-harness
```

This is an opt-in launch path for the host that provides the trusted outer
session, not a repository-wide default. Other machines can continue using the
normal runtime validation, build, and test commands without full host access.

`container-isolation` records the container marker, the absence of a Docker
socket, and a distinct Bubblewrap network namespace. `container-harness`
records the same controller artifacts under `/app/runs`, mapped to the host
`runs/` directory, and labels the fake-provider result
`experimental_data=false`. The matrix service has no Docker socket mount;
Docker access is limited to the outer session and the controller process.

The current managed session cannot provide Docker API access, so these
container commands have not been executed here. No successful containerized
or real-model evidence is claimed by this section until the commands complete
in the dedicated outer context. The existing host-run live summaries above
remain historical launch diagnostics and do not satisfy the real anchor gate.

## Workspace Layout

Run data belongs under `runs/<experiment>/`. The captured deterministic results
are available at `runs/t1/harness-seed-0001/matrix.json` and
`runs/t1/live-configured-seed-0001/matrix.json`. The OpenCode live ledger is
`runs/opencode-go/live-summary.json` with the retained triplet metrics under
`runs/opencode-go/triplet-s0001/`. For new Task 1 anchor runs, use `runs/t1/`;
it contains one `matrix.json` index, one `sNNNN.json` triplet summary per seed,
and one `sNNNN-C{0,1,2}/` condition directory per condition. Each condition
directory contains its manifest, budget, results, board database when
applicable, agent artifacts, and derived telemetry files. Run directories are
generated data and are excluded from source commits.
