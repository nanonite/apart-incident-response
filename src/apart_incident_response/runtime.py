"""Reproducible, capability-restricted single-agent runtime.

The runtime deliberately owns the experiment contract rather than allowing an
agent process to choose its identity, workspace, model, or resource budget.
The Pi process is launched with an argv list (never through a shell), and all
run state is persisted under one agent-specific artifact directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any, Iterable, Mapping, Sequence


class RuntimeConfigError(ValueError):
    """Raised when a runtime contract would violate experiment invariants."""


class Condition(str, Enum):
    """Board visibility condition used by the experiment."""

    C0 = "C0"
    C1 = "C1"
    C2 = "C2"


class ExitStatus(str, Enum):
    """Stable status values written to each run artifact."""

    COMPLETED = "completed"
    FAILED = "failed"
    LAUNCH_ERROR = "launch_error"
    TIMED_OUT = "timed_out"
    BUDGET_EXHAUSTED = "budget_exhausted"


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_THINKING_LEVELS = {"off", "minimal", "low", "medium", "high", "xhigh", "max"}


def _validate_id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise RuntimeConfigError(
            f"{field_name} must match {_SAFE_ID.pattern!r}; received {value!r}"
        )
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeConfigError(f"{field_name} must be a positive integer")
    return value


def _strict_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise RuntimeConfigError(f"{field_name} must be a JSON boolean")
    return value


@dataclass(frozen=True)
class AgentIdentity:
    """Controller-issued identity passed to one agent process."""

    run_id: str
    agent_id: str
    condition: Condition
    task_id: str
    seed: int

    def __post_init__(self) -> None:
        _validate_id(self.run_id, "run_id")
        _validate_id(self.agent_id, "agent_id")
        _validate_id(self.task_id, "task_id")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise RuntimeConfigError("seed must be an integer")
        object.__setattr__(self, "condition", Condition(self.condition))

    @property
    def credential_id(self) -> str:
        """Stable non-secret binding used by tool servers to identify the agent."""

        material = f"{self.run_id}\0{self.agent_id}\0{self.condition.value}\0{self.task_id}\0{self.seed}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "condition": self.condition.value,
            "task_id": self.task_id,
            "seed": self.seed,
            "credential_id": self.credential_id,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "AgentIdentity":
        """Parse and verify a controller-issued identity record."""

        if not isinstance(raw, Mapping):
            raise RuntimeConfigError("agent identity must be an object")
        try:
            identity = cls(
                run_id=raw["run_id"],
                agent_id=raw["agent_id"],
                condition=raw["condition"],
                task_id=raw["task_id"],
                seed=raw["seed"],
            )
        except KeyError as exc:
            raise RuntimeConfigError(f"agent identity is missing {exc.args[0]!r}") from exc
        supplied_credential = raw.get("credential_id")
        if supplied_credential is not None and supplied_credential != identity.credential_id:
            raise RuntimeConfigError("agent identity credential_id does not match its fields")
        return identity


@dataclass(frozen=True)
class IsolationPolicy:
    """Capabilities available to the child process.

    All side channels are denied by default. ``bubblewrap`` provides the OS
    boundary; the Pi flags provide the application-level tool boundary. The
    explicit test-only escape hatch is intentionally opt-in and never allowed
    by :meth:`validate` for a normal runtime configuration.
    """

    sandbox: str = "bubblewrap"
    network: bool = False
    shared_filesystem: bool = False
    shell: bool = False
    subprocess: bool = False
    mcp: bool = False
    subagents: bool = False
    allow_unsafe_for_tests: bool = False

    def validate(self) -> None:
        denied = {
            "network": self.network,
            "shared_filesystem": self.shared_filesystem,
            "shell": self.shell,
            "subprocess": self.subprocess,
            "mcp": self.mcp,
            "subagents": self.subagents,
        }
        enabled = [name for name, value in denied.items() if value]
        if enabled:
            raise RuntimeConfigError(
                "side-channel capabilities must remain disabled: " + ", ".join(enabled)
            )
        if self.sandbox not in {"bubblewrap", "none"}:
            raise RuntimeConfigError("sandbox must be 'bubblewrap' or 'none'")
        if self.sandbox == "none" and not self.allow_unsafe_for_tests:
            raise RuntimeConfigError("a production runtime requires bubblewrap isolation")


@dataclass(frozen=True)
class RuntimeConfig:
    """Pinned controller settings shared by C0, C1, and C2."""

    pi_version: str
    model: str
    launch_command: tuple[str, ...] = ("pi",)
    pi_root_env: str | None = None
    thinking_level: str = "medium"
    agent_count: int = 3
    per_agent_token_budget: int = 4_000
    per_agent_tool_call_budget: int = 32
    aggregate_token_budget: int = 12_000
    aggregate_tool_call_budget: int = 96
    timeout_seconds: float = 300.0
    isolation: IsolationPolicy = field(default_factory=IsolationPolicy)
    conditions: tuple[Condition, ...] = (Condition.C0, Condition.C1, Condition.C2)

    def __post_init__(self) -> None:
        if not isinstance(self.pi_version, str) or not self.pi_version.strip():
            raise RuntimeConfigError("pi_version must be an exact non-empty version")
        if not isinstance(self.model, str) or not self.model.strip():
            raise RuntimeConfigError("model must be an exact non-empty model identifier")
        if not self.launch_command or any(
            not isinstance(part, str) or not part for part in self.launch_command
        ):
            raise RuntimeConfigError("launch_command must be a non-empty argv tuple")
        if any(any(operator in part for operator in ("|", ";", "&&", "||", ">", "<")) for part in self.launch_command):
            raise RuntimeConfigError("launch_command must not contain shell operators")
        if self.pi_root_env is not None and not _ENV_NAME.fullmatch(self.pi_root_env):
            raise RuntimeConfigError("pi_root_env must be a valid uppercase environment variable name")
        if self.thinking_level not in _THINKING_LEVELS:
            raise RuntimeConfigError(
                f"thinking_level must be one of {sorted(_THINKING_LEVELS)}"
            )
        _positive_int(self.agent_count, "agent_count")
        _positive_int(self.per_agent_token_budget, "per_agent_token_budget")
        _positive_int(self.per_agent_tool_call_budget, "per_agent_tool_call_budget")
        _positive_int(self.aggregate_token_budget, "aggregate_token_budget")
        _positive_int(self.aggregate_tool_call_budget, "aggregate_tool_call_budget")
        if self.aggregate_token_budget < self.per_agent_token_budget:
            raise RuntimeConfigError("aggregate token budget must cover one agent")
        if self.aggregate_tool_call_budget < self.per_agent_tool_call_budget:
            raise RuntimeConfigError("aggregate tool-call budget must cover one agent")
        if not isinstance(self.timeout_seconds, (int, float)) or self.timeout_seconds <= 0:
            raise RuntimeConfigError("timeout_seconds must be positive")
        if tuple(self.conditions) != (Condition.C0, Condition.C1, Condition.C2):
            raise RuntimeConfigError("conditions must be the fixed ordered set C0, C1, C2")
        self.isolation.validate()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RuntimeConfig":
        pi = raw.get("pi")
        limits = raw.get("limits")
        isolation = raw.get("isolation", {})
        conditions = raw.get("conditions", ["C0", "C1", "C2"])
        if not isinstance(pi, Mapping) or not isinstance(limits, Mapping):
            raise RuntimeConfigError("config requires 'pi' and 'limits' objects")
        if not isinstance(isolation, Mapping):
            raise RuntimeConfigError("isolation must be an object")
        if not isinstance(conditions, list):
            raise RuntimeConfigError("conditions must be a JSON array")
        command = pi.get("launch_command", [pi.get("executable", "pi")])
        if not isinstance(command, list):
            raise RuntimeConfigError("pi.launch_command must be a JSON array")
        return cls(
            pi_version=str(pi.get("version", "")),
            model=str(pi.get("model", "")),
            launch_command=tuple(command),
            pi_root_env=(
                str(pi.get("root_env")) if pi.get("root_env") is not None else None
            ),
            thinking_level=str(pi.get("thinking_level", "medium")),
            agent_count=int(limits.get("agent_count", 3)),
            per_agent_token_budget=int(limits.get("per_agent_token_budget", 4_000)),
            per_agent_tool_call_budget=int(
                limits.get("per_agent_tool_call_budget", 32)
            ),
            aggregate_token_budget=int(limits.get("aggregate_token_budget", 12_000)),
            aggregate_tool_call_budget=int(
                limits.get("aggregate_tool_call_budget", 96)
            ),
            timeout_seconds=float(limits.get("timeout_seconds", 300.0)),
            isolation=IsolationPolicy(
                sandbox=str(isolation.get("sandbox", "bubblewrap")),
                network=_strict_bool(isolation.get("network", False), "isolation.network"),
                shared_filesystem=_strict_bool(
                    isolation.get("shared_filesystem", False), "isolation.shared_filesystem"
                ),
                shell=_strict_bool(isolation.get("shell", False), "isolation.shell"),
                subprocess=_strict_bool(
                    isolation.get("subprocess", False), "isolation.subprocess"
                ),
                mcp=_strict_bool(isolation.get("mcp", False), "isolation.mcp"),
                subagents=_strict_bool(
                    isolation.get("subagents", False), "isolation.subagents"
                ),
            ),
            conditions=tuple(Condition(str(condition)) for condition in conditions),
        )

    @classmethod
    def from_json(cls, path: Path) -> "RuntimeConfig":
        with path.open(encoding="utf-8") as handle:
            raw = json.load(handle)
        if not isinstance(raw, Mapping):
            raise RuntimeConfigError("runtime configuration must be a JSON object")
        return cls.from_dict(raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pi": {
                "version": self.pi_version,
                "model": self.model,
                "launch_command": list(self.launch_command),
                "root_env": self.pi_root_env,
                "thinking_level": self.thinking_level,
            },
            "limits": {
                "agent_count": self.agent_count,
                "per_agent_token_budget": self.per_agent_token_budget,
                "per_agent_tool_call_budget": self.per_agent_tool_call_budget,
                "aggregate_token_budget": self.aggregate_token_budget,
                "aggregate_tool_call_budget": self.aggregate_tool_call_budget,
                "timeout_seconds": self.timeout_seconds,
            },
            "isolation": asdict(self.isolation),
            "conditions": [condition.value for condition in self.conditions],
        }


class SystemBudget:
    """Thread-safe whole-system budget shared by every agent in a run."""

    def __init__(self, token_limit: int, tool_call_limit: int) -> None:
        self.token_limit = _positive_int(token_limit, "token_limit")
        self.tool_call_limit = _positive_int(tool_call_limit, "tool_call_limit")
        self._tokens = 0
        self._tool_calls = 0
        self._lock = Lock()

    @property
    def tokens_used(self) -> int:
        with self._lock:
            return self._tokens

    @property
    def tool_calls_used(self) -> int:
        with self._lock:
            return self._tool_calls

    def reserve(self, tokens: int = 0, tool_calls: int = 0) -> bool:
        if tokens < 0 or tool_calls < 0:
            raise RuntimeConfigError("budget increments cannot be negative")
        with self._lock:
            if self._tokens + tokens > self.token_limit:
                return False
            if self._tool_calls + tool_calls > self.tool_call_limit:
                return False
            self._tokens += tokens
            self._tool_calls += tool_calls
            return True

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "tokens_used": self._tokens,
                "token_limit": self.token_limit,
                "tool_calls_used": self._tool_calls,
                "tool_call_limit": self.tool_call_limit,
            }


@dataclass(frozen=True)
class IsolatedWorkspace:
    root: Path
    task_dir: Path
    session_dir: Path
    artifact_dir: Path


def create_isolated_workspace(root: Path, identity: AgentIdentity) -> IsolatedWorkspace:
    """Create an agent-only directory tree with restrictive permissions."""

    root = root.expanduser().resolve()
    run_root = root / identity.run_id
    agent_root = run_root / "agents" / identity.agent_id
    if agent_root.exists():
        raise RuntimeConfigError(f"agent workspace already exists: {agent_root}")
    for path in (run_root, run_root / "agents", agent_root):
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.chmod(0o700)
    task_dir = agent_root / "task"
    session_dir = agent_root / "session"
    artifact_dir = agent_root / "artifacts"
    for path in (task_dir, session_dir, artifact_dir):
        path.mkdir(mode=0o700)
        path.chmod(0o700)
    return IsolatedWorkspace(root=agent_root, task_dir=task_dir, session_dir=session_dir, artifact_dir=artifact_dir)


def _safe_env(identity: AgentIdentity, workspace: IsolatedWorkspace, config: RuntimeConfig) -> dict[str, str]:
    """Build a deliberately small child environment with no inherited secrets."""

    path = os.environ.get("PATH", os.defpath)
    return {
        "PATH": path,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "HOME": str(workspace.root / "home"),
        "APART_RUN_ID": identity.run_id,
        "APART_AGENT_ID": identity.agent_id,
        "APART_CONDITION": identity.condition.value,
        "APART_TASK_ID": identity.task_id,
        "APART_SEED": str(identity.seed),
        "APART_PI_VERSION": config.pi_version,
        "APART_MODEL": config.model,
        "APART_BUILTIN_TOOLS": "disabled",
        "APART_NETWORK": "disabled",
        "APART_SHARED_FILESYSTEM": "disabled",
    }


def _resolve_launch_command(config: RuntimeConfig) -> tuple[list[str], Path | None]:
    """Resolve the checked-out Pi root without invoking a shell."""

    command = list(config.launch_command)
    if config.pi_root_env is None:
        if any("{pi_root}" in part for part in command):
            raise RuntimeConfigError("launch_command references {pi_root} without pi_root_env")
        return command, None
    raw_root = os.environ.get(config.pi_root_env)
    if not raw_root:
        raise RuntimeConfigError(
            f"{config.pi_root_env} must point to the local Pi checkout before starting an agent"
        )
    pi_root = Path(raw_root).expanduser().resolve()
    if not pi_root.is_dir():
        raise RuntimeConfigError(f"Pi checkout does not exist: {pi_root}")
    package_path = pi_root / "packages" / "coding-agent" / "package.json"
    try:
        with package_path.open(encoding="utf-8") as handle:
            package = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeConfigError(f"cannot inspect local Pi package metadata: {package_path}") from exc
    if not isinstance(package, Mapping) or package.get("version") != config.pi_version:
        actual = package.get("version") if isinstance(package, Mapping) else None
        raise RuntimeConfigError(
            f"Pi version mismatch: config pins {config.pi_version}, checkout reports {actual}"
        )
    if not any("{pi_root}" in part for part in command):
        raise RuntimeConfigError("launch_command must reference {pi_root} for a local Pi checkout")
    return [part.replace("{pi_root}", str(pi_root)) for part in command], pi_root


def build_pi_command(
    config: RuntimeConfig,
    identity: AgentIdentity,
    workspace: IsolatedWorkspace,
    extension: Path | None = None,
) -> list[str]:
    """Build the exact Pi argv used for one agent.

    The caller supplies an extension only when the constrained experiment
    tools exist. Explicit ``--no-*`` flags prevent project-local discovery from
    adding tools or instructions through the shared checkout.
    """

    config.isolation.validate()
    command, pi_root = _resolve_launch_command(config)
    command.extend(
        [
            "--no-tools",
            "--no-skills",
            "--no-extensions",
            "--no-prompt-templates",
            "--no-themes",
            "--no-context-files",
            "--no-session",
            "--mode",
            "json",
            "--model",
            config.model,
            "--thinking",
            config.thinking_level,
        ]
    )
    if extension is not None:
        extension = extension.expanduser().resolve()
        command.extend(["--extension", str(extension)])
    if config.isolation.sandbox == "none":
        return command
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise RuntimeConfigError("bubblewrap is required but was not found on PATH")
    home = workspace.root / "home"
    home.mkdir(mode=0o700, exist_ok=True)
    sandbox_command = [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--unshare-net",
        "--unshare-ipc",
        "--unshare-pid",
        "--unshare-uts",
        "--clearenv",
        "--tmpfs",
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--dir",
        "/workspace",
        "--dir",
        "/home",
        "--ro-bind",
        str(workspace.root),
        "/workspace",
        "--bind",
        str(workspace.task_dir),
        "/workspace/task",
        "--ro-bind",
        str(home),
        "/home/agent",
        "--chdir",
        "/workspace/task",
        "--setenv",
        "PATH",
        os.environ.get("PATH", os.defpath),
        "--setenv",
        "HOME",
        "/home/agent",
        "--setenv",
        "LANG",
        "C.UTF-8",
        "--setenv",
        "LC_ALL",
        "C.UTF-8",
        "--",
    ]
    if pi_root is not None:
        insert_at = sandbox_command.index("--chdir")
        sandbox_command[insert_at:insert_at] = [
            "--dir",
            "/pi",
            "--ro-bind",
            str(pi_root),
            "/pi",
        ]
        command = [part.replace(str(pi_root), "/pi") for part in command]
    for runtime_path in ("/nix/store", "/run/current-system"):
        path = Path(runtime_path)
        if path.exists():
            insert_at = sandbox_command.index("--chdir")
            sandbox_command[insert_at:insert_at] = ["--ro-bind", runtime_path, runtime_path]
    return sandbox_command + command


def _extract_event_usage(event: Mapping[str, Any]) -> tuple[int, int]:
    usage = event.get("usage")
    if not isinstance(usage, Mapping):
        usage = event
    token_keys = ("total_tokens", "totalTokens", "tokens", "token_count", "tokenCount")
    tokens = next((usage.get(key) for key in token_keys if isinstance(usage.get(key), int)), 0)
    tool_keys = ("tool_calls", "toolCalls", "tool_call_count", "toolCallCount")
    tool_calls = next((usage.get(key) for key in tool_keys if isinstance(usage.get(key), int)), 0)
    return max(tokens, 0), max(tool_calls, 0)


def _event_tool_call_count(event: Mapping[str, Any]) -> int:
    event_type = str(event.get("type", "")).lower()
    return 1 if "tool" in event_type and "result" not in event_type else 0


def _event_text(event: Mapping[str, Any]) -> str | None:
    for key in ("text", "response", "final", "content"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    message = event.get("message")
    if isinstance(message, Mapping):
        content = message.get("content")
        if isinstance(content, str):
            return content
    return None


@dataclass
class RunResult:
    identity: AgentIdentity
    status: ExitStatus
    exit_code: int | None
    started_at: str
    ended_at: str
    duration_seconds: float
    tokens_used: int
    tool_calls_used: int
    final_response: str | None
    failure_reason: str | None
    command: list[str]
    workspace: str
    artifact_dir: str
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["identity"] = self.identity.to_dict()
        result["status"] = self.status.value
        return result


class AgentRun:
    """Run one Pi process and write a complete, inspectable artifact."""

    def __init__(
        self,
        config: RuntimeConfig,
        identity: AgentIdentity,
        workspace: IsolatedWorkspace,
        system_budget: SystemBudget,
    ) -> None:
        self.config = config
        self.identity = identity
        self.workspace = workspace
        self.system_budget = system_budget

    def run(self, prompt: str, extension: Path | None = None) -> RunResult:
        if not isinstance(prompt, str) or not prompt.strip():
            raise RuntimeConfigError("prompt must be a non-empty string")
        command = build_pi_command(self.config, self.identity, self.workspace, extension)
        artifact_dir = self.workspace.artifact_dir
        started_at = _utc_now()
        started_clock = time.monotonic()
        events: list[dict[str, Any]] = []
        final_response: str | None = None
        failure_reason: str | None = None
        status = ExitStatus.FAILED
        exit_code: int | None = None
        agent_tokens_used = 0
        agent_tool_calls_used = 0
        stdout_path = artifact_dir / "stdout.jsonl"
        stderr_path = artifact_dir / "stderr.log"
        self._write_json(artifact_dir / "metadata.json", {
            "identity": self.identity.to_dict(),
            "runtime": self.config.to_dict(),
            "command": command,
            "started_at": started_at,
        })
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.workspace.task_dir,
                env=_safe_env(self.identity, self.workspace, self.config),
                shell=False,
                close_fds=True,
                start_new_session=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except (OSError, ValueError) as exc:
            failure_reason = f"launcher failed: {exc}"
            status = ExitStatus.LAUNCH_ERROR
            ended_at = _utc_now()
            return self._finish(
                status, exit_code, started_at, ended_at, started_clock,
                final_response, failure_reason, command, events,
                agent_tokens_used, agent_tool_calls_used,
            )

        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        process.stdin.write(prompt)
        process.stdin.write("\n")
        process.stdin.close()
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        last_reported_tokens = 0
        last_reported_tools = 0
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        deadline = started_clock + self.config.timeout_seconds
        try:
            with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open(
                "w", encoding="utf-8"
            ) as stderr_file:
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        failure_reason = "agent exceeded runtime timeout"
                        status = ExitStatus.TIMED_OUT
                        self._terminate(process)
                        break
                    ready = selector.select(min(remaining, 0.25))
                    for key, _ in ready:
                        line = key.fileobj.readline()
                        if line == "":
                            selector.unregister(key.fileobj)
                            continue
                        if key.data == "stdout":
                            stdout_file.write(line)
                            stdout_file.flush()
                            stdout_lines.append(line)
                            event = self._parse_event(line)
                            if event is None:
                                continue
                            events.append(event)
                            event_tokens, event_tools = _extract_event_usage(event)
                            token_delta = max(event_tokens - last_reported_tokens, 0)
                            tool_delta = max(event_tools - last_reported_tools, 0)
                            if tool_delta == 0:
                                tool_delta += _event_tool_call_count(event)
                            last_reported_tokens = max(last_reported_tokens, event_tokens)
                            last_reported_tools = max(last_reported_tools, event_tools)
                            agent_tokens_used += token_delta
                            agent_tool_calls_used += tool_delta
                            if agent_tokens_used > self.config.per_agent_token_budget:
                                failure_reason = "agent exceeded per-agent token budget"
                                status = ExitStatus.BUDGET_EXHAUSTED
                                self._terminate(process)
                                break
                            if agent_tool_calls_used > self.config.per_agent_tool_call_budget:
                                failure_reason = "agent exceeded per-agent tool-call budget"
                                status = ExitStatus.BUDGET_EXHAUSTED
                                self._terminate(process)
                                break
                            if not self.system_budget.reserve(token_delta, tool_delta):
                                failure_reason = "system compute ceiling exhausted"
                                status = ExitStatus.BUDGET_EXHAUSTED
                                self._terminate(process)
                                break
                            candidate = _event_text(event)
                            if candidate is not None:
                                final_response = candidate
                        else:
                            stderr_file.write(line)
                            stderr_file.flush()
                            stderr_lines.append(line)
                    if status == ExitStatus.BUDGET_EXHAUSTED:
                        break
                    if process.poll() is not None and not selector.get_map():
                        break
                if process.poll() is None:
                    self._terminate(process)
                exit_code = process.wait(timeout=5)
        except (BrokenPipeError, OSError) as exc:
            failure_reason = f"agent I/O failed: {exc}"
            status = ExitStatus.FAILED
            self._terminate(process)
            exit_code = process.wait(timeout=5)
        finally:
            selector.close()
            process.stdout.close()
            process.stderr.close()
        if status not in {
            ExitStatus.TIMED_OUT,
            ExitStatus.BUDGET_EXHAUSTED,
            ExitStatus.LAUNCH_ERROR,
        }:
            if exit_code == 0:
                status = ExitStatus.COMPLETED
            else:
                status = ExitStatus.FAILED
                if failure_reason is None:
                    failure_reason = f"agent exited with status {exit_code}"
        ended_at = _utc_now()
        result = self._finish(
            status, exit_code, started_at, ended_at, started_clock,
            final_response, failure_reason, command, events,
            agent_tokens_used, agent_tool_calls_used,
        )
        (artifact_dir / "stdout.jsonl").write_text("".join(stdout_lines), encoding="utf-8")
        (artifact_dir / "stderr.log").write_text("".join(stderr_lines), encoding="utf-8")
        return result

    @staticmethod
    def _parse_event(line: str) -> dict[str, Any] | None:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            return None
        return dict(value) if isinstance(value, Mapping) else None

    @staticmethod
    def _terminate(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                process.kill()

    @staticmethod
    def _write_json(path: Path, value: Mapping[str, Any]) -> None:
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _finish(
        self,
        status: ExitStatus,
        exit_code: int | None,
        started_at: str,
        ended_at: str,
        started_clock: float,
        final_response: str | None,
        failure_reason: str | None,
        command: list[str],
        events: list[dict[str, Any]],
        tokens_used: int,
        tool_calls_used: int,
    ) -> RunResult:
        result = RunResult(
            identity=self.identity,
            status=status,
            exit_code=exit_code,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=round(time.monotonic() - started_clock, 6),
            tokens_used=tokens_used,
            tool_calls_used=tool_calls_used,
            final_response=final_response,
            failure_reason=failure_reason,
            command=command,
            workspace=str(self.workspace.root),
            artifact_dir=str(self.workspace.artifact_dir),
            events=events,
        )
        (self.workspace.artifact_dir / "events.json").write_text(
            json.dumps(events, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self._write_json(self.workspace.artifact_dir / "result.json", result.to_dict())
        return result


def load_identity(raw: Mapping[str, Any]) -> AgentIdentity:
    """Parse identity data at a controller boundary."""

    return AgentIdentity.from_dict(raw)


def _validate_config_command(path: Path) -> int:
    config = RuntimeConfig.from_json(path)
    print(json.dumps(config.to_dict(), indent=2, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-config")
    validate.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    if args.command == "validate-config":
        try:
            return _validate_config_command(args.path)
        except (OSError, json.JSONDecodeError, RuntimeConfigError) as exc:
            parser.error(str(exc))
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
