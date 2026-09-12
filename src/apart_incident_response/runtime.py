"""Reproducible, capability-restricted single-agent runtime.

The runtime deliberately owns the experiment contract rather than allowing an
agent process to choose its identity, workspace, model, or resource budget.
The Pi process is launched with an argv list (never through a shell), and all
run state is persisted under one agent-specific artifact directory.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import select
import selectors
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import Event, Lock, Thread
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
_MODEL_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,253}[a-z0-9])?$")
_IDENTITY_SIGNING_KEY = secrets.token_bytes(32)


def _identity_signing_key() -> bytes:
    """Return the controller-only key used for identity bindings.

    A deployment may provide a stable key through ``APART_IDENTITY_KEY`` so
    separate controller processes can verify records.  The fallback is a
    process-local random key; it is still secret from the child and prevents
    an agent from recomputing bindings from the public identity fields.
    """

    configured = os.environ.get("APART_IDENTITY_KEY")
    if configured:
        return configured.encode("utf-8")
    return _IDENTITY_SIGNING_KEY


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
        """Controller-keyed binding used by tool servers to identify the agent."""

        material = f"{self.run_id}\0{self.agent_id}\0{self.condition.value}\0{self.task_id}\0{self.seed}"
        return hmac.new(
            _identity_signing_key(), material.encode("utf-8"), hashlib.sha256
        ).hexdigest()

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
        if not isinstance(supplied_credential, str):
            raise RuntimeConfigError("agent identity requires a controller credential_id")
        if not hmac.compare_digest(supplied_credential, identity.credential_id):
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
    # Pi itself must reach the configured model provider. Agent-side network
    # access remains denied by the tool policy and by the absence of network
    # capable tools. Provider traffic is sent through the controller-owned
    # allowlisted relay, never through the host network namespace directly.
    model_network: bool = False
    model_hosts: tuple[str, ...] = ("chatgpt.com",)
    oauth_hosts: tuple[str, ...] = ("auth.openai.com",)
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
        if not self.model_hosts:
            raise RuntimeConfigError("model_hosts must contain at least one provider hostname")
        if not self.oauth_hosts:
            raise RuntimeConfigError("oauth_hosts must contain at least one authentication hostname")
        for host in (*self.model_hosts, *self.oauth_hosts):
            if not isinstance(host, str) or not _MODEL_HOST.fullmatch(host.lower()):
                raise RuntimeConfigError(f"invalid model provider hostname: {host!r}")


@dataclass(frozen=True)
class RuntimeConfig:
    """Pinned controller settings shared by C0, C1, and C2."""

    pi_version: str
    model: str
    launch_command: tuple[str, ...] = ("pi",)
    pi_root_env: str | None = None
    pi_auth_file_env: str | None = None
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
        if self.pi_auth_file_env is not None and not _ENV_NAME.fullmatch(self.pi_auth_file_env):
            raise RuntimeConfigError("pi_auth_file_env must be a valid uppercase environment variable name")
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
        model_hosts = isolation.get("model_hosts", ["chatgpt.com"])
        oauth_hosts = isolation.get("oauth_hosts", ["auth.openai.com"])
        if not isinstance(model_hosts, list):
            raise RuntimeConfigError("isolation.model_hosts must be a JSON array")
        if not isinstance(oauth_hosts, list):
            raise RuntimeConfigError("isolation.oauth_hosts must be a JSON array")
        if any(not isinstance(host, str) for host in (*model_hosts, *oauth_hosts)):
            raise RuntimeConfigError("isolation host allowlists must contain strings")
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
            pi_auth_file_env=(
                str(pi.get("auth_file_env")) if pi.get("auth_file_env") is not None else None
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
                model_network=_strict_bool(
                    isolation.get("model_network", False), "isolation.model_network"
                ),
                model_hosts=tuple(host.lower() for host in model_hosts),
                oauth_hosts=tuple(host.lower() for host in oauth_hosts),
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
                allow_unsafe_for_tests=_strict_bool(
                    isolation.get("allow_unsafe_for_tests", False),
                    "isolation.allow_unsafe_for_tests",
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
                "auth_file_env": self.pi_auth_file_env,
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


@dataclass(frozen=True)
class BudgetClaim:
    """An unforgeable controller-owned reservation for one agent envelope."""

    claim_id: int
    token_limit: int
    tool_call_limit: int


@dataclass(frozen=True)
class BudgetSettlement:
    """The bounded accounting result for one completed or failed claim."""

    within_claim: bool
    accepted_tokens: int
    accepted_tool_calls: int
    token_overage: int
    tool_call_overage: int

    def __bool__(self) -> bool:
        return self.within_claim


class SystemBudget:
    """Thread-safe whole-system budget shared by every agent in a run."""

    def __init__(self, token_limit: int, tool_call_limit: int) -> None:
        self.token_limit = _positive_int(token_limit, "token_limit")
        self.tool_call_limit = _positive_int(tool_call_limit, "tool_call_limit")
        self._tokens = 0
        self._tool_calls = 0
        self._reserved_tokens = 0
        self._reserved_tool_calls = 0
        self._overage_tokens = 0
        self._overage_tool_calls = 0
        self._next_claim_id = 1
        self._claims: dict[int, BudgetClaim] = {}
        self._lock = Lock()

    def _assert_invariants_locked(self) -> None:
        if self._tokens < 0 or self._reserved_tokens < 0:
            raise RuntimeConfigError("negative token budget accounting")
        if self._tool_calls < 0 or self._reserved_tool_calls < 0:
            raise RuntimeConfigError("negative tool-call budget accounting")
        if self._tokens + self._reserved_tokens > self.token_limit:
            raise RuntimeConfigError("token aggregate ceiling exceeded")
        if self._tool_calls + self._reserved_tool_calls > self.tool_call_limit:
            raise RuntimeConfigError("tool-call aggregate ceiling exceeded")

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
            if self._tokens + self._reserved_tokens + tokens > self.token_limit:
                return False
            if self._tool_calls + self._reserved_tool_calls + tool_calls > self.tool_call_limit:
                return False
            self._tokens += tokens
            self._tool_calls += tool_calls
            self._assert_invariants_locked()
            return True

    def claim(self, tokens: int, tool_calls: int) -> BudgetClaim | None:
        """Claim a complete agent envelope before starting a provider request."""

        if tokens <= 0 or tool_calls <= 0:
            raise RuntimeConfigError("budget claims must be positive")
        with self._lock:
            if self._tokens + self._reserved_tokens + tokens > self.token_limit:
                return None
            if self._tool_calls + self._reserved_tool_calls + tool_calls > self.tool_call_limit:
                return None
            claim = BudgetClaim(self._next_claim_id, tokens, tool_calls)
            self._next_claim_id += 1
            self._reserved_tokens += tokens
            self._reserved_tool_calls += tool_calls
            self._claims[claim.claim_id] = claim
            self._assert_invariants_locked()
            return claim

    def settle(self, claim: BudgetClaim, tokens: int, tool_calls: int) -> BudgetSettlement:
        """Release a claim and account for the provider usage it incurred."""

        if not isinstance(claim, BudgetClaim):
            raise RuntimeConfigError("invalid budget claim")
        if min(claim.token_limit, claim.tool_call_limit, tokens, tool_calls) < 0:
            raise RuntimeConfigError("budget values cannot be negative")
        with self._lock:
            stored = self._claims.pop(claim.claim_id, None)
            if stored is not claim:
                raise RuntimeConfigError("budget claim was settled more than once or was forged")
            self._reserved_tokens -= claim.token_limit
            self._reserved_tool_calls -= claim.tool_call_limit
            available_tokens = self.token_limit - self._tokens - self._reserved_tokens
            available_tools = self.tool_call_limit - self._tool_calls - self._reserved_tool_calls
            accepted_tokens = min(tokens, claim.token_limit, max(available_tokens, 0))
            accepted_tools = min(tool_calls, claim.tool_call_limit, max(available_tools, 0))
            token_overage = tokens - accepted_tokens
            tool_overage = tool_calls - accepted_tools
            self._tokens += accepted_tokens
            self._tool_calls += accepted_tools
            self._overage_tokens += token_overage
            self._overage_tool_calls += tool_overage
            self._assert_invariants_locked()
            return BudgetSettlement(
                within_claim=(tokens <= claim.token_limit and tool_calls <= claim.tool_call_limit),
                accepted_tokens=accepted_tokens,
                accepted_tool_calls=accepted_tools,
                token_overage=token_overage,
                tool_call_overage=tool_overage,
            )

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "tokens_used": self._tokens,
                "tokens_reserved": self._reserved_tokens,
                "token_limit": self.token_limit,
                "tool_calls_used": self._tool_calls,
                "tool_calls_reserved": self._reserved_tool_calls,
                "tool_call_limit": self.tool_call_limit,
                "tokens_over_budget": self._overage_tokens,
                "tool_calls_over_budget": self._overage_tool_calls,
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
    agent_dir = workspace.root / "home" / ".pi" / "agent"
    return {
        "PATH": path,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "HOME": str(workspace.root / "home"),
        "PI_CODING_AGENT_DIR": str(agent_dir),
        "APART_RUN_ID": identity.run_id,
        "APART_AGENT_ID": identity.agent_id,
        "APART_CONDITION": identity.condition.value,
        "APART_TASK_ID": identity.task_id,
        "APART_SEED": str(identity.seed),
        "APART_PI_VERSION": config.pi_version,
        "APART_MODEL": config.model,
        "APART_BUILTIN_TOOLS": "disabled",
        "APART_NETWORK": "model-only" if config.isolation.model_network else "disabled",
        "APART_SHARED_FILESYSTEM": "disabled",
    }


def _resolve_auth_file(config: RuntimeConfig) -> Path | None:
    """Resolve an optional host-side Pi auth file without placing secrets in env."""

    if config.pi_auth_file_env is None:
        return None
    raw_path = os.environ.get(config.pi_auth_file_env)
    if not raw_path:
        return None
    auth_file = Path(raw_path).expanduser().resolve()
    if not auth_file.is_file():
        raise RuntimeConfigError(f"Pi auth file does not exist: {auth_file}")
    return auth_file


def _codex_token_expiry(access_token: str) -> int:
    """Read a JWT expiry in milliseconds without exposing token contents."""

    try:
        encoded_payload = access_token.split(".")[1]
        padding = "=" * (-len(encoded_payload) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded_payload + padding))
        expiry = payload.get("exp")
        if isinstance(expiry, (int, float)) and not isinstance(expiry, bool):
            return int(expiry * 1000)
    except (IndexError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        pass
    return int((time.time() + 3600) * 1000)


def _prepare_auth_file(source: Path | None, workspace: IsolatedWorkspace) -> Path | None:
    """Make Pi auth.json from either Pi auth storage or Codex CLI auth storage."""

    if source is None:
        return None
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeConfigError(f"cannot read Pi auth file: {source}") from exc
    if not isinstance(raw, Mapping):
        raise RuntimeConfigError("Pi auth file must contain a JSON object")
    target = workspace.root / "home" / ".pi" / "agent" / "auth.json"
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload: Mapping[str, Any] = raw
    if "openai-codex" not in raw:
        tokens = raw.get("tokens")
        if isinstance(tokens, Mapping):
            access = tokens.get("access_token")
            refresh = tokens.get("refresh_token")
            if isinstance(access, str) and isinstance(refresh, str) and access and refresh:
                payload = {
                    "openai-codex": {
                        "type": "oauth",
                        "access": access,
                        "refresh": refresh,
                        "expires": _codex_token_expiry(access),
                    }
                }
    target.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    target.chmod(0o600)
    return target


def _prepare_model_limits(workspace: IsolatedWorkspace, config: RuntimeConfig) -> Path | None:
    """Stage Pi's provider max-output override when its provider supports it.

    Pi's generic provider APIs honor ``models.json`` ``maxTokens``. The
    OpenAI Codex Responses adapter in Pi 0.85.1 currently does not forward
    that field; the runtime therefore still treats observed overage as a
    failed run and records it explicitly rather than pretending the provider
    request was capped.
    """

    provider, separator, model_id = config.model.partition("/")
    if not separator or not provider or not model_id:
        return None
    model_id = model_id.split(":", 1)[0]
    if not model_id:
        return None
    target = workspace.root / "home" / ".pi" / "agent" / "models.json"
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = {
        "providers": {
            provider: {
                "modelOverrides": {
                    model_id: {"maxTokens": config.per_agent_token_budget}
                }
            }
        }
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    target.chmod(0o600)
    return target


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


class _ModelEgressProxy:
    """Host-side allowlisted CONNECT relay for the isolated model process."""

    def __init__(self, socket_path: Path, allowed_hosts: Iterable[str]) -> None:
        self.socket_path = socket_path
        self.allowed_hosts = frozenset(host.lower() for host in allowed_hosts)
        self._listener: socket.socket | None = None
        self._stopping = Event()
        self._thread: Thread | None = None
        self._clients: set[Thread] = set()
        self._clients_lock = Lock()

    def start(self) -> None:
        self.socket_path.unlink(missing_ok=True)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(self.socket_path))
            self.socket_path.chmod(0o600)
            listener.listen(16)
            listener.settimeout(0.2)
        except BaseException:
            listener.close()
            self.socket_path.unlink(missing_ok=True)
            raise
        self._listener = listener
        self._thread = Thread(target=self._serve, name="apart-model-egress", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        listener = self._listener
        self._listener = None
        if listener is not None:
            listener.close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        with self._clients_lock:
            clients = tuple(self._clients)
        for client in clients:
            client.join(timeout=1)
        try:
            self.socket_path.unlink(missing_ok=True)
        except OSError:
            # Shutdown is best-effort and must not mask the agent result.
            pass

    def _serve(self) -> None:
        listener = self._listener
        if listener is None:
            return
        while not self._stopping.is_set():
            try:
                client, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            client_thread = Thread(
                target=self._handle_client,
                args=(client,),
                name="apart-model-egress-client",
                daemon=True,
            )
            with self._clients_lock:
                self._clients.add(client_thread)
            client_thread.start()

    def _handle_client(self, client: socket.socket) -> None:
        try:
            client.settimeout(30)
            request = self._read_headers(client)
            if request is None:
                return
            header_bytes, _remainder = request
            first_line = header_bytes.split(b"\r\n", 1)[0].decode("latin-1", "replace")
            parts = first_line.split(" ", 2)
            if len(parts) != 3 or parts[2] not in {"HTTP/1.0", "HTTP/1.1"}:
                self._deny(client)
                return
            method, target, _ = parts
            if method.upper() != "CONNECT":
                self._deny(client)
                return
            parsed_target = self._parse_connect_target(target)
            if parsed_target is None:
                self._deny(client)
                return
            host, port = parsed_target
            upstream = socket.create_connection((host, port), timeout=30)
            try:
                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                self._relay(client, upstream)
            finally:
                upstream.close()
        except (OSError, ValueError):
            return
        finally:
            client.close()

    @staticmethod
    def _read_headers(client: socket.socket) -> tuple[bytes, bytes] | None:
        data = bytearray()
        while b"\r\n\r\n" not in data and len(data) <= 64 * 1024:
            chunk = client.recv(8192)
            if not chunk:
                return None
            data.extend(chunk)
        marker = data.find(b"\r\n\r\n")
        if marker < 0:
            return None
        end = marker + 4
        return bytes(data[:end]), bytes(data[end:])

    def _allowed(self, host: str, port: int) -> bool:
        return host.lower().rstrip(".") in self.allowed_hosts and port == 443

    def _parse_connect_target(self, target: str) -> tuple[str, int] | None:
        """Validate an explicit HTTPS CONNECT target and its allowlist entry."""

        if target.count(":") != 1:
            return None
        host, port_text = target.rsplit(":", 1)
        if not host or port_text != "443" or not _MODEL_HOST.fullmatch(host.lower()):
            return None
        host = host.lower().rstrip(".")
        if not self._allowed(host, 443):
            return None
        return host, 443

    @staticmethod
    def _deny(client: socket.socket) -> None:
        try:
            client.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
        except OSError:
            pass

    @staticmethod
    def _relay(left: socket.socket, right: socket.socket) -> None:
        left.settimeout(None)
        right.settimeout(None)
        open_sockets = [left, right]
        while open_sockets:
            readable, _, _ = select.select(open_sockets, [], [], 30)
            if not readable:
                return
            for source in readable:
                payload = source.recv(64 * 1024)
                destination = right if source is left else left
                if not payload:
                    try:
                        destination.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                    open_sockets.remove(source)
                    continue
                destination.sendall(payload)


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
    auth_file = _resolve_auth_file(config)
    resolved_extension: Path | None = None
    if extension is not None:
        resolved_extension = extension.expanduser().resolve()
        if not resolved_extension.is_file():
            raise RuntimeConfigError(f"Pi extension does not exist: {resolved_extension}")
    command.extend(
        [
            "--no-tools" if resolved_extension is None else "--no-builtin-tools",
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
    if resolved_extension is not None:
        command.extend(["--extension", str(resolved_extension)])
    if config.isolation.sandbox == "none":
        if auth_file is not None:
            auth_file = _prepare_auth_file(auth_file, workspace)
        return command
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise RuntimeConfigError("bubblewrap is required but was not found on PATH")
    home = workspace.root / "home"
    home.mkdir(mode=0o700, exist_ok=True)
    (home / ".pi" / "agent").mkdir(mode=0o700, parents=True, exist_ok=True)
    auth_file = _prepare_auth_file(auth_file, workspace)
    safe_env = _safe_env(identity, workspace, config)
    safe_env["HOME"] = "/home/agent"
    safe_env["PI_CODING_AGENT_DIR"] = "/home/agent/.pi/agent"
    # The child always gets a private network namespace. When model_network is
    # enabled, the bridge process exposes only the controller's allowlisted
    # model relay on loopback inside that namespace.
    safe_env["HTTP_PROXY"] = "http://127.0.0.1:18080" if config.isolation.model_network else ""
    safe_env["HTTPS_PROXY"] = safe_env["HTTP_PROXY"]
    safe_env["http_proxy"] = safe_env["HTTP_PROXY"]
    safe_env["https_proxy"] = safe_env["HTTP_PROXY"]
    safe_env["NO_PROXY"] = ""
    safe_env["no_proxy"] = ""
    sandbox_command = [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--unshare-ipc",
        "--unshare-pid",
        "--unshare-uts",
        "--unshare-net",
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
        "--bind",
        str(home),
        "/home/agent",
        "--chdir",
        "/workspace/task",
    ]
    if config.isolation.model_network:
        source_root = Path(__file__).resolve().parent.parent
        if not source_root.is_dir():
            raise RuntimeConfigError(f"runtime source directory does not exist: {source_root}")
        insert_at = sandbox_command.index("--chdir")
        sandbox_command[insert_at:insert_at] = [
            "--dir",
            "/runtime",
            "--ro-bind",
            str(source_root),
            "/runtime/src",
            "--dir",
            "/etc",
        ]
        for path in (Path("/etc/resolv.conf"), Path("/etc/hosts"), Path("/etc/nsswitch.conf")):
            if path.exists():
                sandbox_command[insert_at:insert_at] = ["--ro-bind", str(path), str(path)]
        cert_dir = Path("/etc/ssl/certs")
        if cert_dir.is_dir():
            sandbox_command[insert_at:insert_at] = [
                "--dir",
                "/etc/ssl",
                "--ro-bind",
                str(cert_dir),
                "/etc/ssl/certs",
            ]
    if config.isolation.model_network:
        safe_env["PYTHONPATH"] = "/runtime/src"
    for name, value in safe_env.items():
        sandbox_command.extend(["--setenv", name, value])
    if auth_file is not None:
        if auth_file != workspace.root / "home" / ".pi" / "agent" / "auth.json":
            raise RuntimeConfigError("auth file staging escaped the isolated home")
    sandbox_command.append("--")
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
    if resolved_extension is not None:
        extension_mount = "/experiment/extensions"
        insert_at = sandbox_command.index("--chdir")
        sandbox_command[insert_at:insert_at] = [
            "--dir",
            "/experiment",
            "--dir",
            extension_mount,
            "--ro-bind",
            str(resolved_extension.parent),
            extension_mount,
        ]
        command = [
            part.replace(str(resolved_extension), f"{extension_mount}/{resolved_extension.name}")
            for part in command
        ]
    for runtime_path in ("/nix/store", "/run/current-system"):
        path = Path(runtime_path)
        if path.exists():
            insert_at = sandbox_command.index("--chdir")
            sandbox_command[insert_at:insert_at] = ["--ro-bind", runtime_path, runtime_path]
    if config.isolation.model_network:
        bridge_python = (
            "/run/current-system/sw/bin/python3"
            if Path("/run/current-system/sw/bin/python3").exists()
            else sys.executable
        )
        command = [
            bridge_python,
            "-m",
            "apart_incident_response.network_bridge",
            "--socket",
            "/workspace/.apart-model-proxy.sock",
            "--port",
            "18080",
            "--",
            *command,
        ]
    return sandbox_command + command


def _usage_total(usage: Any) -> int:
    if not isinstance(usage, Mapping):
        return 0
    for key in ("totalTokens", "total_tokens", "tokens", "token_count", "tokenCount"):
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return max(value, 0)
    components = [usage.get(key, 0) for key in ("input", "output", "cacheRead", "cacheWrite")]
    if all(isinstance(value, int) and not isinstance(value, bool) for value in components):
        return max(sum(components), 0)
    return 0


def _message_key(message: Mapping[str, Any]) -> str:
    timestamp = message.get("timestamp")
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
        return f"timestamp:{timestamp}"
    response_id = message.get("responseId") or message.get("response_id")
    if isinstance(response_id, str) and response_id:
        return f"response:{response_id}"
    return "assistant:stream"


def _event_usage_increment(
    event: Mapping[str, Any],
    current_message_key: str | None,
    usage_seen: dict[str, int],
) -> tuple[int, str | None]:
    """Return newly observed Pi tokens, de-duplicating streaming snapshots."""

    event_type = str(event.get("type", "")).lower()
    if event_type == "message_start":
        message = event.get("message")
        if isinstance(message, Mapping) and message.get("role") == "assistant":
            current_message_key = _message_key(message)
        return 0, current_message_key

    if event_type == "message_update":
        total = _usage_total(event.get("usage"))
        key = current_message_key or "assistant:stream"
    elif event_type == "message_end":
        message = event.get("message")
        if isinstance(message, Mapping):
            if message.get("role") != "assistant":
                return 0, current_message_key
            key = _message_key(message)
            total = _usage_total(message.get("usage"))
        else:
            usage = event.get("usage")
            key = "legacy"
            total = _usage_total(usage if isinstance(usage, Mapping) else event)
    else:
        usage = event.get("usage")
        if not isinstance(usage, Mapping):
            usage = event
        total = _usage_total(usage)
        key = "legacy"

    previous = usage_seen.get(key, 0)
    usage_seen[key] = max(previous, total)
    return max(total - previous, 0), current_message_key


def _event_tool_call_ids(event: Mapping[str, Any]) -> set[str]:
    """Return logical tool-call IDs, ignoring execution-end duplicates."""

    event_type = str(event.get("type", "")).lower()
    identifiers: set[str] = set()
    if event_type in {"tool_execution_start", "tool_call"}:
        raw_id = event.get("toolCallId") or event.get("tool_call_id") or event.get("id")
        if isinstance(raw_id, str) and raw_id:
            identifiers.add(raw_id)
        else:
            name = event.get("toolName") or event.get("name") or "unknown"
            identifiers.add(f"anonymous-tool:{name}")
    if event_type in {"message_start", "message_end"}:
        message = event.get("message")
        if isinstance(message, Mapping) and message.get("role") == "assistant":
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, Mapping) and block.get("type") == "toolCall":
                        raw_id = block.get("id")
                        if isinstance(raw_id, str) and raw_id:
                            identifiers.add(raw_id)
                        else:
                            identifiers.add(f"anonymous-tool:{block.get('name', 'unknown')}")
    return identifiers


def _assistant_text(event: Mapping[str, Any]) -> str | None:
    """Extract the authoritative text from a Pi assistant message_end event."""

    event_type = str(event.get("type", "")).lower()
    message = event.get("message")
    if event_type == "message_end" and isinstance(message, Mapping) and message.get("role") == "assistant":
        content = message.get("content")
        if isinstance(content, list):
            text = "".join(
                block.get("text", "")
                for block in content
                if isinstance(block, Mapping) and block.get("type") == "text" and isinstance(block.get("text"), str)
            )
            return text or None
        if isinstance(content, str):
            return content or None
    for key in ("text", "response", "final"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    return None


def _event_failure_reason(event: Mapping[str, Any]) -> str | None:
    """Return a provider/agent error carried by Pi's JSON event stream."""

    message = event.get("message")
    if isinstance(message, Mapping) and message.get("role") == "assistant":
        if message.get("stopReason") == "error":
            error = message.get("errorMessage")
            return f"Pi provider error: {error}" if isinstance(error, str) and error else "Pi provider error"
    messages = event.get("messages")
    if isinstance(messages, list):
        for candidate in reversed(messages):
            if isinstance(candidate, Mapping) and candidate.get("role") == "assistant" and candidate.get("stopReason") == "error":
                error = candidate.get("errorMessage")
                return f"Pi provider error: {error}" if isinstance(error, str) and error else "Pi provider error"
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
        artifact_dir = self.workspace.artifact_dir
        started_at = _utc_now()
        started_clock = time.monotonic()
        command: list[str] = []
        events: list[dict[str, Any]] = []
        final_response: str | None = None
        failure_reason: str | None = None
        status = ExitStatus.FAILED
        exit_code: int | None = None
        agent_tokens_used = 0
        agent_tool_calls_used = 0
        stdout_path = artifact_dir / "stdout.jsonl"
        stderr_path = artifact_dir / "stderr.log"
        claim: BudgetClaim | None = None
        proxy: _ModelEgressProxy | None = None
        settlement: BudgetSettlement | None = None

        def settle_claim() -> None:
            nonlocal claim, settlement, status, failure_reason
            if claim is None:
                return
            settlement = self.system_budget.settle(
                claim, agent_tokens_used, agent_tool_calls_used
            )
            claim = None
            if not settlement.within_claim:
                status = ExitStatus.BUDGET_EXHAUSTED
                detail = (
                    "provider usage exceeded its claimed envelope"
                    f" (token overage={settlement.token_overage},"
                    f" tool-call overage={settlement.tool_call_overage})"
                )
                failure_reason = f"{failure_reason}; {detail}" if failure_reason else detail

        try:
            if self.config.isolation.model_network and self.config.isolation.sandbox == "bubblewrap":
                proxy = _ModelEgressProxy(
                    self.workspace.root / ".apart-model-proxy.sock",
                    (*self.config.isolation.model_hosts, *self.config.isolation.oauth_hosts),
                )
                proxy.start()
            command = build_pi_command(self.config, self.identity, self.workspace, extension)
            _prepare_model_limits(self.workspace, self.config)
            self._write_json(artifact_dir / "metadata.json", {
                "identity": self.identity.to_dict(),
                "runtime": self.config.to_dict(),
                "command": command,
                "started_at": started_at,
            })
            stdout_path.write_text("", encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")

            # Reserve the complete envelope before Popen. A provider request
            # must never start merely because current accounting happens to
            # have spare capacity; concurrent agents claim their ceilings
            # atomically before they can incur usage.
            claim = self.system_budget.claim(
                self.config.per_agent_token_budget,
                self.config.per_agent_tool_call_budget,
            )
            if claim is None:
                failure_reason = "system compute ceiling exhausted before provider launch"
                status = ExitStatus.BUDGET_EXHAUSTED
                return self._finish(
                    status, exit_code, started_at, _utc_now(), started_clock,
                    final_response, failure_reason, command, events,
                    agent_tokens_used, agent_tool_calls_used,
                )

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
                settle_claim()
                return self._finish(
                    status, exit_code, started_at, _utc_now(), started_clock,
                    final_response, failure_reason, command, events,
                    agent_tokens_used, agent_tool_calls_used,
                )

            assert process.stdin is not None
            assert process.stdout is not None
            assert process.stderr is not None
            selector: selectors.BaseSelector | None = None
            current_message_key: str | None = None
            usage_seen: dict[str, int] = {}
            seen_tool_calls: set[str] = set()
            stdout_lines: list[str] = []
            stderr_lines: list[str] = []
            deadline = started_clock + self.config.timeout_seconds
            try:
                # Prompt delivery is inside the protected lifecycle. A child
                # that exits early can raise BrokenPipeError here, and the
                # outer finally below still removes staged credentials.
                process.stdin.write(prompt)
                process.stdin.write("\n")
                process.stdin.close()
                selector = selectors.DefaultSelector()
                selector.register(process.stdout, selectors.EVENT_READ, "stdout")
                selector.register(process.stderr, selectors.EVENT_READ, "stderr")
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
                                event_failure = _event_failure_reason(event)
                                if event_failure is not None and failure_reason is None:
                                    failure_reason = event_failure
                                token_delta, current_message_key = _event_usage_increment(
                                    event, current_message_key, usage_seen
                                )
                                new_tool_calls = _event_tool_call_ids(event) - seen_tool_calls
                                seen_tool_calls.update(new_tool_calls)
                                tool_delta = len(new_tool_calls)
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
                                candidate = _assistant_text(event)
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
                if selector is not None:
                    selector.close()
                process.stdin.close()
                process.stdout.close()
                process.stderr.close()
            if status not in {ExitStatus.TIMED_OUT, ExitStatus.BUDGET_EXHAUSTED, ExitStatus.LAUNCH_ERROR}:
                if failure_reason is not None:
                    status = ExitStatus.FAILED
                elif exit_code == 0:
                    status = ExitStatus.COMPLETED
                else:
                    status = ExitStatus.FAILED
                    if failure_reason is None:
                        failure_reason = f"agent exited with status {exit_code}"
            settle_claim()
            result = self._finish(
                status, exit_code, started_at, _utc_now(), started_clock,
                final_response, failure_reason, command, events,
                agent_tokens_used, agent_tool_calls_used,
            )
            (artifact_dir / "stdout.jsonl").write_text("".join(stdout_lines), encoding="utf-8")
            (artifact_dir / "stderr.log").write_text("".join(stderr_lines), encoding="utf-8")
            return result
        finally:
            try:
                settle_claim()
            except Exception:
                # An existing run exception/result must not be masked by a
                # defensive accounting or cleanup path.
                pass
            try:
                self._cleanup_staged_auth()
            except Exception:
                pass
            if proxy is not None:
                try:
                    proxy.stop()
                except Exception:
                    pass

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

    def _cleanup_staged_auth(self) -> None:
        """Remove any transient Codex-to-Pi credential conversion after launch."""

        run_root = self.workspace.root.resolve()
        agent_home = run_root / "home" / ".pi" / "agent"
        if agent_home.parent.parent.parent != run_root:
            return
        for staged in (
            agent_home / "auth.json",
            agent_home / "auth.json.lock",
            agent_home / "models.json",
        ):
            try:
                if staged.is_symlink() or not staged.is_dir():
                    staged.unlink(missing_ok=True)
                else:
                    shutil.rmtree(staged)
            except OSError:
                # Cleanup is best-effort. The caller's finally block always
                # continues to proxy shutdown, and the run result/exception
                # remains authoritative.
                continue

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


def _run_agent_command(args: argparse.Namespace) -> int:
    config = RuntimeConfig.from_json(args.config)
    if args.prompt is not None:
        prompt = args.prompt
    else:
        prompt = args.prompt_file.read_text(encoding="utf-8")
    identity = AgentIdentity(
        run_id=args.run_id,
        agent_id=args.agent_id,
        condition=Condition(args.condition),
        task_id=args.task_id,
        seed=args.seed,
    )
    workspace = create_isolated_workspace(args.workspace_root, identity)
    result = AgentRun(
        config,
        identity,
        workspace,
        SystemBudget(config.aggregate_token_budget, config.aggregate_tool_call_budget),
    ).run(prompt, args.extension)
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0 if result.status is ExitStatus.COMPLETED else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-config")
    validate.add_argument("path", type=Path)
    run = subparsers.add_parser("run", help="Run one isolated Pi agent")
    run.add_argument("config", type=Path)
    run.add_argument("--run-id", required=True)
    run.add_argument("--agent-id", required=True)
    run.add_argument("--condition", choices=[condition.value for condition in Condition], required=True)
    run.add_argument("--task-id", required=True)
    run.add_argument("--seed", type=int, required=True)
    run.add_argument("--workspace-root", type=Path, default=Path("artifacts/runs"))
    run.add_argument("--extension", type=Path)
    prompt = run.add_mutually_exclusive_group(required=True)
    prompt.add_argument("--prompt")
    prompt.add_argument("--prompt-file", type=Path)
    args = parser.parse_args(argv)
    if args.command == "validate-config":
        try:
            return _validate_config_command(args.path)
        except (OSError, json.JSONDecodeError, RuntimeConfigError) as exc:
            parser.error(str(exc))
    if args.command == "run":
        try:
            return _run_agent_command(args)
        except (OSError, json.JSONDecodeError, RuntimeConfigError, ValueError) as exc:
            parser.error(str(exc))
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
