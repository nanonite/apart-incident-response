# Apart incident response runtime

This repository uses a workspace-local, reproducible Python environment managed by
[`uv`](https://docs.astral.sh/uv/). From the repository root:

```bash
UV_CACHE_DIR=.uv-cache uv sync
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src python -m unittest discover -s tests -v
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src python -m apart_incident_response.runtime validate-config config/runtime.json
```

The runtime contract is in `config/runtime.json`. It pins the Pi CLI version,
model identifier, per-agent and aggregate budgets, timeout, and the fixed C0/C1/C2
condition set. Set `APART_PI_ROOT` to a local checkout such as
`$HOME/GitRepos/pi`; the launcher invokes that checkout directly with Bun rather
than depending on a globally installed Pi binary. Each run receives a controller-issued identity and a private
`artifacts/<run-id>/agents/<agent-id>/` directory.

Pi is launched as an argv list with built-in tools, skills, extensions, prompt
templates, themes, context-file discovery, and session persistence disabled.
Bubblewrap is required for a normal run so the child has no network, IPC, PID,
UTS, or shared writable filesystem channel. Custom experiment tools can later be
loaded through the explicit extension argument without enabling Pi discovery.

The pinned Pi version and model are intentionally configuration values so every
co-worker can review or change them in one file before running a matrix. No API
credentials are copied into the child environment; authentication must be
configured by the host setup.
