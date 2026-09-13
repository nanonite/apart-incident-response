# Apart incident response runtime

This repository uses a workspace-local, reproducible Python environment managed by
[`uv`](https://docs.astral.sh/uv/). From the repository root:

```bash
UV_CACHE_DIR=.uv-cache uv sync
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src python -m unittest discover -s tests -v
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src python -m apart_incident_response.runtime validate-config config/runtime.json
```

The report's `just` build and its LaTeX dependencies are reproducible through
the workspace flake:

```bash
nix develop --command just --justfile report/justfile --working-directory report build
```

The runtime contract is in `config/runtime.json`. It pins the Pi CLI version,
the `openai-codex/gpt-5.6-luna` model identifier at `xhigh` thinking level, per-agent and aggregate budgets,
timeout, and the fixed C0/C1/C2 condition set. Set `APART_PI_ROOT` to a local checkout such as
`$HOME/GitRepos/pi`; the launcher invokes that checkout directly with Bun rather
than depending on a globally installed Pi binary. Each run receives a controller-issued identity and a private
`artifacts/<run-id>/agents/<agent-id>/` directory.

Pi is launched as an argv list with all tools, skills, extensions, prompt
templates, themes, context-file discovery, and session persistence disabled.
Bubblewrap always gives the process a private network namespace. When
`model_network` is enabled, only the allowlisted `model_hosts` endpoint is
reachable through the controller relay. The pinned OpenAI Codex OAuth refresh
host is separately allowlisted as `oauth_hosts` (`auth.openai.com`), also only
on HTTPS port 443. The relay accepts only valid HTTP CONNECT requests and
denies unrelated hosts, ports, and malformed requests; its TLS tunnel cannot
inspect the encrypted OAuth path, so Pi 0.85.1 remains responsible for using
the documented `/oauth/token` flow. The Pi/extension process never gets the
host network namespace. Agent shell, subprocess, MCP, subagent, and
shared-filesystem channels remain denied.
If an explicit experiment extension is supplied, its directory is mounted
read-only into the sandbox and only built-in tools are disabled so that the
extension can expose the intended tools.

Bubblewrap namespace creation is a host capability, not a model-network
fallback. The launcher always retains `--unshare-net` and fails closed when
the command environment denies it. On this host, the reproducible approved
smoke uses the host execution context and the read-only system binds that the
launcher itself uses:

```bash
bwrap --die-with-parent --new-session --unshare-net \
  --ro-bind /nix/store /nix/store \
  --ro-bind /run/current-system /run/current-system \
  -- /run/current-system/sw/bin/true
```

Run the same `runtime run` command below from that approved host context for
an end-to-end Bubblewrap/relay/Pi check. The ordinary managed command sandbox
may reject network namespace creation with `Operation not permitted`; do not
remove `--unshare-net` or run the agent on the host network to work around it.

Configure authentication outside the repository and point the launcher at a
Pi-format `auth.json` or the local Codex CLI auth file. Set a separate,
controller-owned state path outside the repository for rotated credentials:

```bash
export APART_PI_ROOT="$HOME/GitRepos/pi"
export APART_PI_AUTH_FILE="$HOME/.codex/auth.json"
export APART_PI_AUTH_STORE="$HOME/.local/state/apart-incident-response/codex-auth.json"
# Optional stable controller secret for identity verification across processes.
# If omitted, each controller process uses a private random signing key.
export APART_IDENTITY_KEY="choose-a-secret-outside-the-repository"
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src python -m apart_incident_response.runtime run \
  config/runtime.json --run-id run-001 --agent-id agent-1 --condition C0 \
  --task-id task-1 --seed 1 --prompt "Run the assigned task." \
  --workspace-root artifacts/runs
```

On first use, the controller imports the source auth into the store; later
runs use the store so a Pi OAuth refresh is available to the next run. The
resolved store path must be outside this repository and all run
workspaces, including through symlinks. Its dedicated parent must be owned by
the controller and already have mode `0700`; an existing parent is never
chmodded. A missing dedicated parent is created with mode `0700`. The store
and its advisory lock are mode `0600`, and updates are lock-protected and
atomic. The credential lock spans
staging, Pi execution, and persistence, so concurrent authenticated runs are
serialized rather than racing a rotating refresh token. The source Codex/Pi
auth file is never modified unless a separate, explicit controller workflow
does so. Run-local `auth.json`, `auth.json.lock` (including directory-shaped
proper-lockfile locks), and `models.json` are deleted on every exit path.
Credentials are never placed in command arguments, logs, artifacts, or child
environment variables. If a rotated-token write fails, the run is marked
failed (or retains its original failure status) with a non-secret persistence
diagnostic in `result.json`; cleanup, relay shutdown, and lock release still
run.

The `run` command writes metadata, raw JSONL, stderr, parsed events, the final
response, budget usage, and exit status under the agent artifact directory.

## Board storage foundation

Epic 3 issue #16 provides the controller-owned storage primitive in
`apart_incident_response.board_storage.BoardStore`. Initialize it from the
board service with a path in a dedicated service-owned directory and the
current agent workspace roots:

```python
from apart_incident_response.board_storage import BoardStore

with BoardStore.initialize(
    "/var/lib/apart-incident-response/board.sqlite3",
    agent_workspace_roots=["/srv/apart/runs/run-001/agents/agent-1"],
) as board:
    record = board.append_message("run-001", "agent-1", "diagnostic note")
```

The store creates `messages` with an `AUTOINCREMENT` sequence ID, controller
timestamp, run/agent identity, message body, and UTF-8 byte size. SQLite
triggers reject `UPDATE` and `DELETE`, including direct SQL against the service
database. `iter_messages()` is only a deterministic storage primitive for the
future `board_read` API; cursor handling, C0/C1/C2 visibility, identity
derivation, and Pi tools are intentionally not part of #16.

The database is service-owned and must remain outside agent task directories,
including symlinked paths. It is never mounted into Bubblewrap, included in a
Pi command, or exposed as a path/connection to an agent. The board service is
the only component that should hold a `BoardStore` instance.

Each agent claims its complete configured compute envelope before Pi starts.
Pi's generic providers receive a run-local `models.json` `maxTokens` override;
the Pi 0.85.1 OpenAI Codex Responses adapter does not currently forward that
field, so an observed provider overage is terminated/reported as
`budget_exhausted` and recorded separately rather than silently counted beyond
the aggregate ceiling. The controller's accepted accounting always remains
within the aggregate ceiling.

The pinned Pi version and model are intentionally configuration values so every
co-worker can review or change them in one file before running a matrix.
