# Apart incident response runtime

This repository uses a workspace-local, reproducible Python environment managed by
[`uv`](https://docs.astral.sh/uv/). From the repository root:

```bash
UV_CACHE_DIR=.uv-cache uv sync
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src python -m unittest discover -s tests -v
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src python -m apart_incident_response.runtime validate-config config/runtime.json
```

The runtime contract is in `config/runtime.json`. It pins the Pi CLI version,
the `openai-codex/gpt-5.6-luna` model identifier at `xhigh` thinking level, per-agent and aggregate budgets,
timeout, and the fixed C0/C1/C2 condition set. Set `APART_PI_ROOT` to a local checkout such as
`$HOME/GitRepos/pi`; the launcher invokes that checkout directly with Bun rather
than depending on a globally installed Pi binary. Each run receives a controller-issued identity and a private
`artifacts/<run-id>/agents/<agent-id>/` directory.

Pi is launched as an argv list with all tools, skills, extensions, prompt
templates, themes, context-file discovery, and session persistence disabled.
The provider network is available because Pi must call the pinned model; agent
shell, subprocess, MCP, subagent, and shared-filesystem channels remain denied.
If an explicit experiment extension is supplied, its directory is mounted
read-only into the sandbox and only built-in tools are disabled so that the
extension can expose the intended tools.

Configure authentication outside the repository and point the launcher at a
Pi-format `auth.json` or the local Codex CLI auth file. Codex credentials are
converted into a private run-local Pi auth file; secrets never enter the child
environment or repository:

```bash
export APART_PI_ROOT="$HOME/GitRepos/pi"
export APART_PI_AUTH_FILE="$HOME/.codex/auth.json"
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src python -m apart_incident_response.runtime run \
  config/runtime.json --run-id run-001 --agent-id agent-1 --condition C0 \
  --task-id task-1 --seed 1 --prompt "Run the assigned task." \
  --workspace-root artifacts/runs
```

The `run` command writes metadata, raw JSONL, stderr, parsed events, the final
response, budget usage, and exit status under the agent artifact directory.

The pinned Pi version and model are intentionally configuration values so every
co-worker can review or change them in one file before running a matrix.
