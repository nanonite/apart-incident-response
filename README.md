# Apart incident response runtime

Builds, tests, and smoke checks run in reproducible Docker stages. From the
repository root:

```bash
just setup
just test
just build
docker compose run --rm runtime
```

The report build is also containerized:

```bash
just report
```

The runtime contract is in `config/runtime.json`. It pins the Pi CLI version,
the `openai-codex/gpt-5.6-luna` model identifier at `xhigh` thinking level, per-agent and aggregate budgets,
timeout, and the fixed C0/C1/C2 condition set. The containerized launcher uses
the pinned Pi checkout at `/opt/pi`. Each run receives a controller-issued identity and a private
`artifacts/<run-id>/agents/<agent-id>/` directory.

Task prompts are configured under the top-level `prompts` object by task ID.
When a run omits `--prompt` and `--prompt-file`, the controller selects the
configured prompt from the task ID and seed; condition is not part of that
selection. The selected prompt is recorded in `metadata.json`, which makes the
same task and seed byte identical across C0, C1, and C2. See
[`docs/neutral-agent-prompts.md`](docs/neutral-agent-prompts.md).

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

Configure authentication outside the repository and point the container at a
Pi-format `auth.json` or the local Codex CLI auth file. Set a separate,
controller-owned state path outside the repository for rotated credentials:

```bash
export APART_PI_AUTH_FILE="$HOME/.codex/auth.json"
export APART_PI_AUTH_STORE="$HOME/.local/state/apart-incident-response/codex-auth.json"
# Optional stable controller secret for identity verification across processes.
# If omitted, each controller process uses a private random signing key.
export APART_IDENTITY_KEY="choose-a-secret-outside-the-repository"
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
database. The board service builds on this store with bounded cursor reads,
credential-derived identity, run containment, and C0/C1/C2 visibility.

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

## Constrained task and board tools

`apart_incident_response.tool_service.ConstrainedToolService` is the only
controller boundary used by the mounted extension. It exposes
`task_read`, `task_query`, and `task_submit`, plus `board_read` and
`board_append` in C1/C2. C0 registers only the three task tools. Task identity,
run identity, agent identity, and condition are resolved from an opaque
controller-issued credential; those fields are never accepted in tool input.

The service reads task fixtures from a controller-selected `TaskCatalog` and
the board service is the only code that holds `BoardStore`. Task paths are
relative and bounded, queries are literal and bounded, and submissions are
structured as a diagnosis plus fixture-backed evidence references and are
idempotent per run/agent. Each accepted submission is persisted as
`task_submission.json` beside the invocation audit, including the
controller-derived run/agent/task identity, timestamp, trusted runtime token
and tool-call counters, and a stable content hash. Every accepted or rejected
authenticated invocation is written to that agent's `tool_calls.jsonl` artifact
with validated input,
result or error, timestamp, run ID, and agent ID. Credential values are
redacted and are never written to the log. The submission-time usage record is
marked `provisional`; `AgentRun` replaces it with `final` totals after the
child output has been drained.

The extension is [incident-tools.ts](pi-extension/incident-tools.ts). Pass it
explicitly to `AgentRun.run()` together with a configured service:

```python
from apart_incident_response import (
    BoardToolService,
    BoardStore,
    ConstrainedToolService,
    TaskCatalog,
    TaskDefinition,
    TaskToolService,
)

board = BoardStore.initialize("/var/lib/apart-incident-response/board.sqlite3")
tasks = TaskCatalog({"task-1": TaskDefinition("task-1", "/srv/tasks/task-1")})
service = ConstrainedToolService(
    TaskToolService(tasks), BoardToolService(board), artifact_root="/srv/apart/runs"
)
```

The runnable CLI wires the same service whenever `runtime run` receives
`--extension`. Use `--task-root` to select the controller-owned task fixture
and `--board-database` to select a private shared board database; without the
latter, C1/C2 use a private database under the run directory. C0 does not
open a board database. A `task-1` run without `--task-root` materializes only
the authenticated agent's Task 1 evidence bundle and attaches the deterministic
Task 1 diagnosis validator before accepting `task_submit`.

The production service endpoint is a private Unix socket mounted only at the
extension endpoint. The managed test environment denies Unix pathname socket
creation, so credential-free fixture runs use a private controller-created
FIFO pair with the same JSON service contract; this transport is selected only
for the explicit `sandbox="none"` test policy. Neither transport exposes the
SQLite path or a general filesystem, shell, subprocess, MCP, or network tool.
The credential-free two-agent board trace is recorded in
[docs/board-smoke-trace.json](docs/board-smoke-trace.json), and can be
regenerated by the container-backed smoke target.

The real Pi extension acceptance smoke is [scripts/pi_extension_smoke.py](scripts/pi_extension_smoke.py).
It launches the installed Pi 0.85.1 CLI directly with the production
[incident-tools.ts](pi-extension/incident-tools.ts) extension, disables built-in
tools and extension discovery, and uses a deterministic in-process model fixture
only to make Pi emit constrained tool calls. Those calls cross the controller's
fixture FIFO and produce the audit evidence in
[docs/pi-extension-smoke-trace.json](docs/pi-extension-smoke-trace.json). Run it
with `just pi-smoke`.

## Docker

The image build includes the pinned Pi submodule. After cloning without
`--recurse-submodules`, initialize it before building:

```bash
git submodule update --init --recursive
```

Build the runtime image and validate its pinned configuration:

```bash
docker compose build
docker compose run --rm runtime
```

Docker also verifies the repository's build responsibilities directly:

```bash
# Python runtime contract and constrained-tool tests.
docker build --target test --output type=cacheonly .

# Direct Pi 0.85.1 extension smoke test.
docker build --target pi-smoke --output type=cacheonly .

# Rebuild report/main.pdf with the TeX and Biber toolchain.
docker build --target report --output type=cacheonly .
```

The test stage runs the unit test suite. The runtime image
contains Python 3.12, Bun, bubblewrap, CA certificates, `tini`, and a
Linux-prepared copy of the pinned `pi` submodule at `/opt/pi`. Its dependencies
are installed from `package-lock.json` without lifecycle scripts, and its
required model catalog is generated for direct execution with Bun. The image
does not contain credentials, experiment artifacts, or the research documents
under `docs/`.

To run an agent, mount only its authentication file read-only:

```bash
docker compose run --rm \
  --volume "${APART_PI_AUTH_FILE}:/run/secrets/pi-auth.json:ro" \
  runtime run config/runtime.json \
  --run-id run-001 --agent-id agent-1 --condition C0 \
  --task-id task-1 --seed 1 --prompt "Run the assigned task." \
  --workspace-root artifacts/runs
```

The `SYS_ADMIN` and `NET_ADMIN` capabilities and relaxed outer
seccomp/AppArmor profiles are required so the controller can create
bubblewrap's nested namespaces and initialize their loopback interface. They
apply to the container only; the Pi child process is still launched inside the
restricted filesystem and private network namespace defined by
`config/runtime.json`.
