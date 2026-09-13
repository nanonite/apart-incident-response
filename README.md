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

The real matrix must be launched from a dedicated trusted outer Codex session
with explicit full host access. This is an opt-in launch choice for this
repository; it does not change the global Codex default:

```bash
cd /path/to/apart-incident-response
codex --sandbox danger-full-access --ask-for-approval never --cd "$PWD"
```

In that outer session, `just docker-check` verifies Docker access before any
controller starts. Docker control belongs only to this outer session and the
container controller; the Pi process never receives the Docker socket.
This is a host-specific opt-in path for machines that provide a trusted
full-access outer session. It is not required by, or enabled by default for,
other machines using this repository.

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
does so. Run-local auth.json, auth.json.lock (including directory-shaped
proper-lockfile locks), and models.json are deleted on every exit path.
Credentials are never placed in command arguments, logs, artifacts, or child
environment variables. If a rotated-token write fails, the run is marked
failed (or retains its original failure status) with a non-secret persistence
diagnostic in result.json; cleanup, relay shutdown, and lock release still
run.

OpenCode Go uses Pi 0.85.1's built-in opencode-go provider. The controller
checks the pinned checkout for that provider and its session-header support
before launch; it refuses a custom fallback when those sources are absent.
The two Pi provider paths and their execution boundaries are compared in
[`docs/pi-provider-paths.md`](docs/pi-provider-paths.md).
The default Codex model and OAuth egress stay unchanged. Select OpenCode Go
for a real run with a model override and a private key file outside the
repository:

```bash
export APART_PI_ROOT="$PWD/pi"
export APART_OPENCODE_API_KEY_FILE="$HOME/.local/share/opencode/auth.json"
PYTHONPATH=src python scripts/run_experiment.py \
  --real-anchor --model opencode-go/kimi-k2.6 --seeds 1 \
  --output runs/opencode-go
```

APART_OPENCODE_API_KEY_FILE may point to the standard OpenCode auth JSON or a
one-line key file. The controller extracts the key, stages it only in the
run-local Pi auth file, and removes that file on every exit path. A direct
OPENCODE_API_KEY value is accepted only by the controller as a fallback and
is never forwarded to Pi. OpenCode selection derives an HTTPS-only opencode.ai
allowlist and removes the Codex OAuth host. Each agent gets a stable
x-opencode-session value derived from its run and agent identity and a
distinct User-Agent; the existing per-agent and aggregate token/tool-call
limits remain in force.

OpenRouter uses Pi's built-in `openrouter` provider. Select a model with its
full provider/model slug, such as `openrouter/openai/gpt-4o-mini`:

```bash
export APART_PI_ROOT="$PWD/pi"
export APART_OPENROUTER_API_KEY_FILE="$HOME/.config/openrouter/api-key"
PYTHONPATH=src python scripts/run_experiment.py \
  --real-anchor --model openrouter/openai/gpt-4o-mini --seeds 1 \
  --output runs/openrouter
```

The controller reads the private key file, stages it only in the run-local Pi
auth file, and removes it after the run. A controller-only `OPENROUTER_API_KEY`
environment value is also supported. OpenRouter selection allows only
`openrouter.ai:443` through the model relay and removes the Codex OAuth and
OpenCode hosts. See [`docs/pi-provider-paths.md`](docs/pi-provider-paths.md)
for the container command and the verified logprob request contract. For a
prompt-only OpenRouter probability capture, use the shared one-shot dispatcher
with the dedicated controller environment variable:

```bash
export OPENROUTER_API_KEY='provided-outside-the-repository'
PYTHONPATH=src python scripts/qwen3_goal.py --mode openrouter \
  --model openrouter/openai/gpt-4o-mini \
  --prompt-file prompts/task-1.txt --seed 1 --temperature 0 \
  --top-logprobs 5 --max-tokens 512 \
  --output runs/openrouter/logprobs/seed-1
```

The adapter sends one non-streaming chat-completions request, requires the
provider to preserve logprob parameters, validates the returned token array,
and writes a sanitized response plus a `partial-token-probability-v1`
artifact. Missing or malformed probabilities produce `failure.json`.

The `run` command writes metadata, raw JSONL, stderr, parsed events, the final
response, budget usage, and exit status under the agent artifact directory.
Experiment output under `runs/` is intentionally versioned for sharing between
workers; event, message, tool, and usage data is retained exactly, with only
credential-shaped fields and known secret values redacted.

## Controlled n-agent experiment controller

The controller in [controller.py](src/apart_incident_response/controller.py)
implements the versioned protocol in
[docs/experiment-protocol.md](docs/experiment-protocol.md). It starts one
threaded, isolated `AgentRun` per agent, gives every condition triplet the same
prompt/fixture/model/n/timeout/aggregate budget, and owns one board database
per non-C0 swarm. The aggregate budget is reserved atomically before provider
launch; for n variations the per-agent envelope is the integer division of the
same aggregate ceiling.

Run a real Task 1 pilot only after configuring the Pi root and controller-owned
OAuth store described above:

```bash
PYTHONPATH=src python scripts/run_experiment.py \
  --real-anchor --seeds 1 2 3 4 5 \
  --output runs/t1
```

The command writes a condition directory and a paired triplet summary for each
seed. It preserves credential-redacted Pi JSONL/stderr, parsed events,
response/tokenizer artifacts, tool audits, board state/events, submissions,
budget/failure data, and derived provenance/replay metrics. `index.json` links
the matrix through each condition to every agent `timeline.json`; inspect one agent with `PYTHONPATH=src python scripts/inspect_run.py --run-root <condition> --agent-id agent-1`. `U` requires a prior cross-agent board read followed by
later recipient use of a seeded token; token overlap and task success are not
substitutes for that trace. Five-seed output is descriptive pilot evidence
only.

The fake-provider commands are harness checks, never model data:

```bash
PYTHONPATH=src python scripts/run_experiment.py --harness-check
PYTHONPATH=src python scripts/run_experiment.py --harness-factors
```

The second command exercises the predeclared agent-count, capability,
difficulty, transformation-window, and model-factor paths while recording
`run_class=harness_check` and `experimental_data=false`.

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

Before Task 2 work begins, regenerate the credential-free single-agent Task 1
calibration with:

```bash
PYTHONPATH=src:. python scripts/task_one_calibration.py \
  --output docs/task-one-calibration.json
```

It runs one deterministic fake agent per evidence bundle in C0, where only
`task_read`, `task_query`, and `task_submit` are available. The records capture
the prompt, bundle, tool and token counts, response, and validator result. The
checked-in trace shows all three runs complete while no individual bundle passes
the complete diagnosis validator. Calibration is diagnostic evidence and is not
a fourth experimental condition.

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

The default `runtime` service only validates configuration. The dedicated
`matrix` service runs the controller inside the image built from the pinned
`pi` checkout. Run these commands from the trusted outer session above:
The matrix service and its Just targets are opt-in; normal repository Docker
commands do not start it or require full host access.

```bash
just docker-check
just container-isolation
just container-harness
```

`container-harness` writes deterministic, fake-provider checks under
`runs/container-harness/`; it is harness evidence, never model data.
`container-isolation` writes sanitized container and Bubblewrap namespace
evidence to `runs/container-isolation.json`. Both commands fail if a Docker
socket is visible inside the matrix container.

For a real, explicitly authorized calibration or anchor, provide credentials
from outside the repository. The Codex path mounts the source auth read-only;
the controller-owned OAuth refresh state is kept in the named Docker volume
`apart-incident-response-controller-auth-state`:

```bash
export APART_PI_AUTH_FILE="$HOME/.codex/auth.json"
just container-anchor output=t1-container seeds="1"
```

The OpenCode Go path uses a private key file instead and stages it only for the
controller. The entrypoint copies the read-only input to a controller-owned
0600 path, and the runtime removes run-local staged credentials on exit:

```bash
export APART_OPENCODE_API_KEY_FILE="$HOME/.local/share/opencode/auth.json"
just container-anchor output=opencode-go-container \
  model=opencode-go/kimi-k2.6 seeds="1"
```

The `container-anchor` target never puts credential contents in arguments.
Its `/app/runs` mount maps to the repository's `runs/` directory, so manifests,
raw events, failures, usage, and derived telemetry remain available on the
host. Use the existing host command only when intentionally running the
controller outside Docker:

```bash
PYTHONPATH=src python scripts/run_experiment.py \
  --real-anchor --seeds 1 --output runs/t1-host
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
