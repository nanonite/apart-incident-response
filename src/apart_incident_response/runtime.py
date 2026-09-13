"""Reproducible, capability-restricted single-agent runtime.

The runtime deliberately owns the experiment contract rather than allowing an
agent process to choose its identity, workspace, model, or resource budget.
The Pi process is launched with an argv list (never through a shell), and all
run state is persisted under one agent-specific artifact directory.
"""

from __future__ import annotations

import argparse
import base64
from collections import defaultdict
import fcntl
import hashlib
import hmac
import json
import math
import os
import re
import select
import selectors
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Callable, IO, Iterable, Iterator, Mapping, Sequence

from .task_prompts import DEFAULT_TASK_PROMPTS, TaskPromptCatalog, TaskPromptConfigError


# Keep CLI execution and package imports on one module identity. This matters
# when the CLI constructs the service layer dynamically with ``python -m``.
if __name__ == "__main__":
    sys.modules.setdefault("apart_incident_response.runtime", sys.modules[__name__])


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
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_OPENCODE_PROVIDER = "opencode-go"
_OPENCODE_HOST = "opencode.ai"
_CODEX_PROVIDER = "openai-codex"
_OLLAMA_PROVIDER = "ollama"
_OLLAMA_DEFAULT_HOST = "127.0.0.1"
_OLLAMA_DEFAULT_PORT = 11434
_OLLAMA_PROXY_HOST = "127.0.0.1"
_OLLAMA_PROXY_PORT = 11434
_OLLAMA_PROXY_PATH = "/v1/chat/completions"
_OLLAMA_DUMMY_API_KEY = "ollama-local"
_OLLAMA_LOGPROBS_TOP_K = 5
_DEFAULT_PROVIDER_USER_AGENT = "apart-incident-response/1"


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


def _pinned_ollama_config() -> dict[str, str]:
    """Load the repository pin used for controller-owned Ollama runs."""

    path = _REPOSITORY_ROOT / "config" / "qwen3-8b.json"
    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeConfigError(f"cannot load pinned Ollama config: {path}") from exc
    if not isinstance(payload, Mapping):
        raise RuntimeConfigError(f"pinned Ollama config is not an object: {path}")
    model = payload.get("ollama_model")
    model_id = payload.get("model_id")
    revision = payload.get("revision")
    if not all(isinstance(value, str) and value.strip() for value in (model, model_id, revision)):
        raise RuntimeConfigError(f"pinned Ollama config is missing model metadata: {path}")
    return {
        "path": str(path),
        "ollama_model": model,
        "model_id": model_id,
        "revision": revision,
    }


@dataclass(frozen=True)
class AgentIdentity:
    """Controller-issued identity passed to one agent process."""

    run_id: str
    agent_id: str
    condition: Condition
    task_id: str
    seed: int
    capability_profile: str = "task-diagnostic-v1"

    def __post_init__(self) -> None:
        _validate_id(self.run_id, "run_id")
        _validate_id(self.agent_id, "agent_id")
        _validate_id(self.task_id, "task_id")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise RuntimeConfigError("seed must be an integer")
        _validate_id(self.capability_profile, "capability_profile")
        object.__setattr__(self, "condition", Condition(self.condition))

    @property
    def credential_id(self) -> str:
        """Controller-keyed binding used by tool servers to identify the agent."""

        material = (
            f"{self.run_id}\0{self.agent_id}\0{self.condition.value}\0{self.task_id}"
            f"\0{self.seed}\0{self.capability_profile}"
        )
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
            "capability_profile": self.capability_profile,
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
                capability_profile=raw.get("capability_profile", "task-diagnostic-v1"),
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
    pi_auth_store_env: str | None = None
    api_key_file_env: str | None = "APART_OPENCODE_API_KEY_FILE"
    api_key_env: str | None = "OPENCODE_API_KEY"
    provider_user_agent: str = _DEFAULT_PROVIDER_USER_AGENT
    thinking_level: str = "medium"
    agent_count: int = 3
    per_agent_token_budget: int = 4_000
    per_agent_tool_call_budget: int = 32
    aggregate_token_budget: int = 12_000
    aggregate_tool_call_budget: int = 96
    timeout_seconds: float = 300.0
    isolation: IsolationPolicy = field(default_factory=IsolationPolicy)
    conditions: tuple[Condition, ...] = (Condition.C0, Condition.C1, Condition.C2)
    task_prompts: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_TASK_PROMPTS))

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
        if self.pi_auth_store_env is not None and not _ENV_NAME.fullmatch(self.pi_auth_store_env):
            raise RuntimeConfigError("pi_auth_store_env must be a valid uppercase environment variable name")
        if self.api_key_file_env is not None and not _ENV_NAME.fullmatch(self.api_key_file_env):
            raise RuntimeConfigError("api_key_file_env must be a valid uppercase environment variable name")
        if self.api_key_env is not None and not _ENV_NAME.fullmatch(self.api_key_env):
            raise RuntimeConfigError("api_key_env must be a valid uppercase environment variable name")
        if (
            not isinstance(self.provider_user_agent, str)
            or not self.provider_user_agent
            or len(self.provider_user_agent) > 256
            or any(character in self.provider_user_agent for character in "\r\n")
        ):
            raise RuntimeConfigError(
                "provider_user_agent must be a non-empty one-line value of at most 256 characters"
            )
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
        provider, separator, _model_id = self.model.partition("/")
        if separator and provider == _OPENCODE_PROVIDER:
            if self.isolation.model_hosts != (_OPENCODE_HOST,):
                raise RuntimeConfigError(
                    "OpenCode Go requires the model egress allowlist to contain only opencode.ai"
                )
            if self.isolation.oauth_hosts:
                raise RuntimeConfigError("OpenCode Go must not allow unrelated OAuth egress hosts")
        if separator and provider == _OLLAMA_PROVIDER:
            pinned = _pinned_ollama_config()
            if _model_id != pinned["ollama_model"]:
                raise RuntimeConfigError(
                    f"Ollama model is not pinned in {pinned['path']}: {_model_id!r}"
                )
            if self.isolation.model_hosts != (_OLLAMA_PROXY_HOST,):
                raise RuntimeConfigError(
                    "Ollama requires the isolated loopback model endpoint in the egress contract"
                )
            if self.isolation.oauth_hosts:
                raise RuntimeConfigError("Ollama must not allow OAuth egress hosts")
        try:
            catalog = TaskPromptCatalog(self.task_prompts)
        except TaskPromptConfigError as exc:
            raise RuntimeConfigError(str(exc)) from exc
        object.__setattr__(self, "task_prompts", dict(catalog.prompts))

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RuntimeConfig":
        pi = raw.get("pi")
        limits = raw.get("limits")
        isolation = raw.get("isolation", {})
        conditions = raw.get("conditions", ["C0", "C1", "C2"])
        task_prompts = raw.get("prompts", DEFAULT_TASK_PROMPTS)
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
        if not isinstance(task_prompts, Mapping):
            raise RuntimeConfigError("prompts must be a JSON object")
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
            pi_auth_store_env=(
                str(pi.get("auth_store_env"))
                if pi.get("auth_store_env") is not None
                else None
            ),
            api_key_file_env=(
                str(pi.get("api_key_file_env"))
                if pi.get("api_key_file_env") is not None
                else "APART_OPENCODE_API_KEY_FILE"
            ),
            api_key_env=(
                str(pi.get("api_key_env"))
                if pi.get("api_key_env") is not None
                else "OPENCODE_API_KEY"
            ),
            provider_user_agent=str(pi.get("provider_user_agent", _DEFAULT_PROVIDER_USER_AGENT)),
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
            task_prompts=dict(task_prompts),
        )

    def for_model(self, model: str) -> "RuntimeConfig":
        """Select a model and derive its provider-specific egress contract."""

        if not isinstance(model, str) or "/" not in model:
            raise RuntimeConfigError("model must use the provider/model-id form")
        provider, _separator, model_id = model.partition("/")
        isolation = self.isolation
        current_provider = self.model.partition("/")[0]
        if provider == _OPENCODE_PROVIDER:
            isolation = replace(isolation, model_hosts=(_OPENCODE_HOST,), oauth_hosts=())
        elif provider == _OLLAMA_PROVIDER:
            pinned = _pinned_ollama_config()
            if model_id != pinned["ollama_model"]:
                raise RuntimeConfigError(
                    f"unknown Ollama model {model_id!r}; only {pinned['ollama_model']!r} is pinned"
                )
            isolation = replace(
                isolation,
                model_hosts=(_OLLAMA_PROXY_HOST,),
                oauth_hosts=(),
            )
            # Pi's generic --thinking flag is not Ollama's native `think` field.
            # Local runs are explicitly non-thinking unless the caller overrides it.
            return replace(self, model=model, thinking_level="off", isolation=isolation)
        elif provider == _CODEX_PROVIDER or current_provider in {_OPENCODE_PROVIDER, _OLLAMA_PROVIDER}:
            isolation = replace(
                isolation,
                model_hosts=("chatgpt.com",),
                oauth_hosts=("auth.openai.com",),
            )
        return replace(self, model=model, isolation=isolation)

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
                "auth_store_env": self.pi_auth_store_env,
                "api_key_file_env": self.api_key_file_env,
                "api_key_env": self.api_key_env,
                "provider_user_agent": self.provider_user_agent,
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
            "prompts": dict(self.task_prompts),
        }

    def prompt_for(self, task_id: str, seed: int) -> str:
        """Select a task prompt using task and seed, independent of condition."""

        try:
            return TaskPromptCatalog(self.task_prompts).prompt_for(task_id, seed)
        except TaskPromptConfigError as exc:
            raise RuntimeConfigError(str(exc)) from exc


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
    workspace_root: Path
    run_root: Path
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
    return IsolatedWorkspace(
        workspace_root=root,
        run_root=run_root,
        root=agent_root,
        task_dir=task_dir,
        session_dir=session_dir,
        artifact_dir=artifact_dir,
    )


def _safe_env(
    identity: AgentIdentity,
    workspace: IsolatedWorkspace,
    config: RuntimeConfig,
    extra_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a deliberately small child environment with no inherited secrets."""

    path = os.environ.get("PATH", os.defpath)
    agent_dir = workspace.root / "home" / ".pi" / "agent"
    environment = {
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
        "APART_CAPABILITY_PROFILE": identity.capability_profile,
        "APART_PI_VERSION": config.pi_version,
        "APART_MODEL": config.model,
        "APART_BUILTIN_TOOLS": "disabled",
        "APART_NETWORK": "model-only" if config.isolation.model_network else "disabled",
        "APART_SHARED_FILESYSTEM": "disabled",
    }
    if _model_provider(config.model) == _OPENCODE_PROVIDER:
        environment["APART_OPENCODE_SESSION"] = _opencode_session_id(identity)
        environment["APART_OPENCODE_USER_AGENT"] = config.provider_user_agent
    for name, value in (extra_env or {}).items():
        if name not in {
            "APART_CONTROLLER_CREDENTIAL_FILE",
            "APART_TOOL_SOCKET",
            "APART_TOOL_REQUEST_FIFO",
            "APART_TOOL_RESPONSE_FIFO",
        }:
            raise RuntimeConfigError(f"unsupported controller environment variable: {name}")
        if not isinstance(value, str) or not value:
            raise RuntimeConfigError(f"{name} must be a non-empty string")
        environment[name] = value
    return environment


def _stage_controller_credential(path: Path, credential: str) -> None:
    """Write an opaque service credential outside the agent-visible mount."""

    if path.exists() or path.is_symlink():
        raise RuntimeConfigError("controller credential staging path already exists")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(credential)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _create_bind_mount_placeholder(path: Path) -> None:
    """Create a private file target for a Bubblewrap socket bind mount."""

    if path.exists() or path.is_symlink():
        raise RuntimeConfigError(f"Bubblewrap bind target already exists: {path}")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    os.close(descriptor)


def _resolve_auth_file(config: RuntimeConfig) -> Path | None:
    """Resolve an optional host-side Pi auth file without placing secrets in env."""

    if _model_provider(config.model) in {_OPENCODE_PROVIDER, _OLLAMA_PROVIDER}:
        return None
    if config.pi_auth_file_env is None:
        return None
    raw_path = os.environ.get(config.pi_auth_file_env)
    if not raw_path:
        return None
    auth_file = Path(raw_path).expanduser().resolve()
    if not auth_file.is_file():
        raise RuntimeConfigError(f"Pi auth file does not exist: {auth_file}")
    return auth_file


@dataclass
class _AuthStage:
    """A run-local auth copy and its optional controller-owned persistence lease."""

    target: Path
    store: Path | None
    baseline_revision: int
    transient_provider: str | None = None
    lock_handle: IO[str] | None = None

    def release(self) -> None:
        if self.lock_handle is None:
            return
        try:
            fcntl.flock(self.lock_handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.lock_handle.close()
            self.lock_handle = None


@dataclass(frozen=True)
class _AuthStoreSnapshot:
    auth: Mapping[str, Any]
    revision: int


def _path_is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _model_provider(model: str) -> str:
    return model.partition("/")[0]


def _resolve_ollama_target() -> tuple[str, int, str, str]:
    """Resolve the controller-only Ollama target without accepting a URL path."""

    configured = os.environ.get("OLLAMA_HOST", "").strip()
    raw = configured or f"http://{_OLLAMA_DEFAULT_HOST}:{_OLLAMA_DEFAULT_PORT}"
    candidate = raw if "://" in raw else f"http://{raw}"
    try:
        parsed = urllib.parse.urlsplit(candidate)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise RuntimeConfigError("OLLAMA_HOST is not a valid HTTP host and port") from exc
    if (
        parsed.scheme != "http"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or host is None
        or ":" in host
        or not _MODEL_HOST.fullmatch(host.lower())
        or port is None
        or not 1 <= port <= 65535
    ):
        raise RuntimeConfigError(
            "OLLAMA_HOST must be an http://host:port endpoint without credentials or a URL path"
        )
    normalized_host = host.lower().rstrip(".")
    endpoint = f"http://{normalized_host}:{port}"
    return normalized_host, port, endpoint, raw


def probe_ollama(config: RuntimeConfig) -> dict[str, Any] | None:
    """Verify the pinned local model before any isolated agent is launched."""

    if _model_provider(config.model) != _OLLAMA_PROVIDER:
        return None
    pinned = _pinned_ollama_config()
    model_id = config.model.partition("/")[2]
    if model_id != pinned["ollama_model"]:
        raise RuntimeConfigError(
            f"unknown Ollama model {model_id!r}; only {pinned['ollama_model']!r} is pinned"
        )
    _host, _port, endpoint, raw_host = _resolve_ollama_target()
    request = urllib.request.Request(
        f"{endpoint}/api/tags",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError, urllib.error.URLError) as exc:
        raise RuntimeConfigError(
            f"Ollama preflight failed for {endpoint} ({type(exc).__name__})"
        ) from exc
    models = payload.get("models") if isinstance(payload, Mapping) else None
    if not isinstance(models, list):
        raise RuntimeConfigError("Ollama preflight returned no model list")
    selected = next(
        (
            item
            for item in models
            if isinstance(item, Mapping)
            and (item.get("name") == model_id or item.get("model") == model_id)
        ),
        None,
    )
    digest = selected.get("digest") if isinstance(selected, Mapping) else None
    if not isinstance(digest, str) or not digest:
        raise RuntimeConfigError(f"Ollama model tag is missing: {model_id}")
    return {
        "status": "ok",
        "ollama_host": endpoint,
        "ollama_host_env": raw_host,
        "ollama_model": model_id,
        "digest": digest,
        "checkpoint": {
            "model_id": pinned["model_id"],
            "revision": pinned["revision"],
        },
    }


def _model_request_metadata(config: RuntimeConfig) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "provider": _model_provider(config.model),
        "model": config.model,
        "thinking_level": config.thinking_level,
    }
    if _model_provider(config.model) == _OLLAMA_PROVIDER:
        _host, _port, endpoint, raw_host = _resolve_ollama_target()
        metadata.update({
            "ollama_host": endpoint,
            "ollama_host_env": raw_host,
            "ollama_model": config.model.partition("/")[2],
            "ollama_think": config.thinking_level != "off",
        })
    return metadata


def _opencode_session_id(identity: AgentIdentity) -> str:
    """Return one stable, non-secret routing ID for an agent run."""

    material = f"{identity.run_id}\0{identity.agent_id}".encode("utf-8")
    return f"apart-{hashlib.sha256(material).hexdigest()[:32]}"


def _read_private_api_key(path: Path) -> str:
    """Read a controller-owned key file without putting its value in env or argv."""

    if path.is_symlink() or not path.is_file():
        raise RuntimeConfigError("OpenCode API key file is not a regular file")
    info = path.stat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise RuntimeConfigError("OpenCode API key file must be controller-owned and mode 0600")
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeConfigError("cannot read OpenCode API key file") from exc
    if not value:
        raise RuntimeConfigError("OpenCode API key file is empty")
    if value.startswith("{"):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise RuntimeConfigError("OpenCode API key file is not valid JSON") from exc
        provider_payload = payload.get(_OPENCODE_PROVIDER) if isinstance(payload, Mapping) else None
        candidate = provider_payload.get("key") if isinstance(provider_payload, Mapping) else None
        if not isinstance(candidate, str) or not candidate.strip():
            raise RuntimeConfigError("OpenCode API key JSON is missing its provider key")
        value = candidate.strip()
    return value


def _resolve_provider_api_key(config: RuntimeConfig) -> str | None:
    """Resolve provider credentials only in the controller before private staging."""

    provider = _model_provider(config.model)
    if provider == _OLLAMA_PROVIDER:
        return _OLLAMA_DUMMY_API_KEY
    if provider != _OPENCODE_PROVIDER:
        return None
    if config.api_key_file_env:
        raw_path = os.environ.get(config.api_key_file_env)
        if raw_path:
            return _read_private_api_key(Path(raw_path).expanduser().resolve())
    if config.api_key_env:
        value = os.environ.get(config.api_key_env)
        if value:
            value = value.strip()
            if value:
                return value
    raise RuntimeConfigError(
        "OpenCode Go API key is unavailable; provide a private key file through "
        f"{config.api_key_file_env} or the controller-only {config.api_key_env} variable"
    )


def _redact_text(value: str | None, secrets: Sequence[str]) -> str | None:
    """Remove controller-only secret values before returning or persisting data."""

    if value is None:
        return None
    redacted = value
    for secret in sorted({secret for secret in secrets if secret}, key=len, reverse=True):
        redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def _redact_value(value: Any, secrets: Sequence[str]) -> Any:
    if isinstance(value, str):
        return _redact_text(value, secrets)
    if isinstance(value, Mapping):
        return {key: _redact_value(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item, secrets) for item in value)
    return value


def _resolve_auth_store(
    config: RuntimeConfig,
    source: Path | None,
    workspace: IsolatedWorkspace,
) -> Path | None:
    """Resolve the controller-owned OAuth store, never the user's source file."""

    if config.pi_auth_store_env is None or _model_provider(config.model) in {
        _OPENCODE_PROVIDER,
        _OLLAMA_PROVIDER,
    }:
        # OpenCode and Ollama credentials are staged only in the run-local Pi auth file.
        # Keep the configured Codex store intact so switching back to Codex
        # preserves its existing credential lifecycle.
        return None
    raw_path = os.environ.get(config.pi_auth_store_env)
    if not raw_path:
        if source is not None:
            raise RuntimeConfigError(
                f"{config.pi_auth_store_env} must point to a controller-owned OAuth store"
            )
        return None
    raw_store = Path(raw_path).expanduser()
    if raw_store.is_symlink():
        raise RuntimeConfigError("OAuth store path must not be a symlink")
    store = raw_store.resolve()
    if source is not None and store == source.resolve():
        raise RuntimeConfigError("OAuth store must not overwrite the source Pi/Codex auth file")
    forbidden = (
        _REPOSITORY_ROOT,
        workspace.workspace_root.resolve(),
        workspace.run_root.resolve(),
        workspace.root.resolve(),
    )
    if any(_path_is_within(store, directory) for directory in forbidden):
        raise RuntimeConfigError(
            "APART_PI_AUTH_STORE must resolve outside the repository and run workspaces"
        )
    return store


def _load_json_mapping(path: Path, label: str) -> Mapping[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeConfigError(f"cannot read {label}: {path}") from exc
    if not isinstance(raw, Mapping):
        raise RuntimeConfigError(f"{label} must contain a JSON object")
    return raw


def _normalize_auth_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Convert Codex CLI token storage to the Pi auth.json shape."""

    if "openai-codex" in raw:
        return json.loads(json.dumps(raw))
    tokens = raw.get("tokens")
    if isinstance(tokens, Mapping):
        access = tokens.get("access_token")
        refresh = tokens.get("refresh_token")
        if isinstance(access, str) and isinstance(refresh, str) and access and refresh:
            return {
                "openai-codex": {
                    "type": "oauth",
                    "access": access,
                    "refresh": refresh,
                    "expires": _codex_token_expiry(access),
                }
            }
    return json.loads(json.dumps(raw))


def _codex_credentials(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    entry = payload.get("openai-codex")
    if not isinstance(entry, Mapping):
        return None
    access = entry.get("access")
    refresh = entry.get("refresh")
    if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
        return None
    return entry


def _validate_private_directory(path: Path, label: str) -> None:
    try:
        info = path.stat()
    except OSError as exc:
        raise RuntimeConfigError(f"cannot inspect {label}: {path}") from exc
    mode = stat.S_IMODE(info.st_mode)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or mode & 0o077
        or mode & 0o700 != 0o700
    ):
        raise RuntimeConfigError(
            f"{label} must be a dedicated private directory owned by the controller "
            f"with mode 0700; create one and point APART_PI_AUTH_STORE at it: {path}"
        )


def _validate_private_file(path: Path, label: str) -> None:
    try:
        info = path.stat()
    except OSError as exc:
        raise RuntimeConfigError(f"cannot inspect {label}: {path}") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise RuntimeConfigError(f"{label} must be owned by the controller with mode 0600: {path}")


def _ensure_private_parent(path: Path, *, validate_existing: bool = True) -> None:
    parent = path.parent
    if parent.exists():
        if validate_existing:
            _validate_private_directory(parent, "OAuth store parent")
        return
    try:
        parent.mkdir(mode=0o700, parents=True, exist_ok=False)
    except FileExistsError:
        # Another controller may have created the shared store parent after
        # the existence check above. Validate it below before using it.
        pass
    if validate_existing:
        _validate_private_directory(parent, "new OAuth store parent")


def _atomic_write_json(
    path: Path,
    value: Mapping[str, Any],
    *,
    validate_parent: bool = True,
) -> None:
    """Atomically write a controller or run-local JSON file with mode 0600."""

    _ensure_private_parent(path, validate_existing=validate_parent)
    descriptor = -1
    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        except OSError:
            directory_fd = -1
        if directory_fd >= 0:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def _auth_store_document(auth: Mapping[str, Any], revision: int) -> dict[str, Any]:
    return {"format": 1, "revision": revision, "auth": auth}


def _read_auth_store(path: Path) -> _AuthStoreSnapshot | None:
    if path.is_symlink():
        raise RuntimeConfigError(f"OAuth store must not be a symlink: {path}")
    if not path.exists():
        return None
    _validate_private_file(path, "OAuth store")
    raw = _load_json_mapping(path, "OAuth store")
    auth = raw.get("auth")
    revision = raw.get("revision")
    if not isinstance(auth, Mapping) or isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise RuntimeConfigError(f"OAuth store has an invalid format: {path}")
    return _AuthStoreSnapshot(auth=json.loads(json.dumps(auth)), revision=revision)


def _write_auth_store(path: Path, auth: Mapping[str, Any], revision: int) -> None:
    _atomic_write_json(path, _auth_store_document(auth, revision))


def _acquire_auth_store_lock(path: Path) -> IO[str]:
    """Acquire an advisory lock that spans staging, Pi refresh, and persistence."""

    _ensure_private_parent(path)
    lock_path = Path(f"{path}.lock")
    if lock_path.is_symlink():
        raise RuntimeConfigError(f"OAuth store lock must not be a symlink: {lock_path}")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise RuntimeConfigError(f"cannot open OAuth store lock: {lock_path}") from exc
    handle = os.fdopen(descriptor, "r+")
    try:
        _validate_private_file(lock_path, "OAuth store lock")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except BaseException:
        handle.close()
        raise
    return handle


@contextmanager
def _locked_auth_store(path: Path) -> Iterator[None]:
    handle = _acquire_auth_store_lock(path)
    try:
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


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


def _prepare_auth_file(
    source: Path | None,
    workspace: IsolatedWorkspace,
    config: RuntimeConfig,
    *,
    api_key: str | None = None,
    hold_lock: bool = False,
) -> _AuthStage | None:
    """Stage credentials and optionally hold the controller refresh lease."""

    transient_provider = _model_provider(config.model) if api_key is not None else None
    if api_key is not None and transient_provider not in {_OPENCODE_PROVIDER, _OLLAMA_PROVIDER}:
        raise RuntimeConfigError("a transient API key can only be staged for OpenCode Go or Ollama")
    store = _resolve_auth_store(config, source, workspace)
    lock_handle: IO[str] | None = None
    baseline_revision = 0
    try:
        if store is None:
            if source is None:
                if api_key is None:
                    return None
                payload = {}
            else:
                payload = _normalize_auth_payload(_load_json_mapping(source, "Pi auth file"))
        elif hold_lock:
            lock_handle = _acquire_auth_store_lock(store)
            snapshot = _read_auth_store(store)
            if snapshot is None:
                if source is None and api_key is None:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
                    lock_handle.close()
                    lock_handle = None
                    return None
                payload = (
                    _normalize_auth_payload(_load_json_mapping(source, "Pi auth file"))
                    if source is not None
                    else {}
                )
                baseline_revision = 1
                _write_auth_store(store, payload, baseline_revision)
            else:
                payload = dict(snapshot.auth)
                baseline_revision = snapshot.revision
        else:
            with _locked_auth_store(store):
                snapshot = _read_auth_store(store)
                if snapshot is None:
                    if source is None and api_key is None:
                        return None
                    payload = (
                        _normalize_auth_payload(_load_json_mapping(source, "Pi auth file"))
                        if source is not None
                        else {}
                    )
                    baseline_revision = 1
                    _write_auth_store(store, payload, baseline_revision)
                else:
                    payload = dict(snapshot.auth)
                    baseline_revision = snapshot.revision

        if api_key is not None:
            payload = dict(payload)
            payload[transient_provider] = {"type": "api_key", "key": api_key}
        target = workspace.root / "home" / ".pi" / "agent" / "auth.json"
        _atomic_write_json(target, payload, validate_parent=False)
        return _AuthStage(target, store, baseline_revision, transient_provider, lock_handle)
    except BaseException:
        if lock_handle is not None:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            finally:
                lock_handle.close()
        raise


def _persist_auth_stage(stage: _AuthStage | None) -> None:
    """Persist Pi's rotated OAuth token without changing the source auth file."""

    if stage is None or stage.store is None or not stage.target.is_file():
        return
    candidate = _normalize_auth_payload(_load_json_mapping(stage.target, "staged Pi auth file"))
    if stage.transient_provider is not None:
        candidate = dict(candidate)
        candidate.pop(stage.transient_provider, None)
    if _codex_credentials(candidate) is None:
        return

    lock_handle: IO[str] | None = stage.lock_handle
    acquired_here = False
    if lock_handle is None:
        lock_handle = _acquire_auth_store_lock(stage.store)
        acquired_here = True
    try:
        current = _read_auth_store(stage.store)
        if current is not None and current.revision != stage.baseline_revision:
            # A controller holding the same lease cannot reach this branch,
            # but refusing a stale write also protects against non-cooperating
            # writers instead of replacing a newer refresh token.
            return
        next_revision = (current.revision if current is not None else stage.baseline_revision) + 1
        if current is not None and candidate == current.auth:
            return
        _write_auth_store(stage.store, candidate, next_revision)
    finally:
        if acquired_here and lock_handle is not None:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            finally:
                lock_handle.close()


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
    if not model_id:
        return None
    target = workspace.root / "home" / ".pi" / "agent" / "models.json"
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if provider == _OLLAMA_PROVIDER:
        if model_id != _pinned_ollama_config()["ollama_model"]:
            raise RuntimeConfigError(f"unknown Ollama model {model_id!r}")
        payload = {
            "providers": {
                _OLLAMA_PROVIDER: {
                    "baseUrl": f"http://{_OLLAMA_PROXY_HOST}:{_OLLAMA_PROXY_PORT}/v1",
                    "api": "openai-completions",
                    "models": [{
                        "id": model_id,
                        "name": "Qwen3 8B 4-bit",
                    }],
                    "modelOverrides": {
                        model_id: {
                            "maxTokens": config.per_agent_token_budget,
                            "samplingParams": {
                                "think": config.thinking_level != "off",
                                "logprobs": True,
                                "top_logprobs": _OLLAMA_LOGPROBS_TOP_K,
                            },
                        }
                    },
                }
            }
        }
    else:
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
    if _model_provider(config.model) == _OPENCODE_PROVIDER:
        provider_path = pi_root / "packages" / "ai" / "src" / "providers" / "opencode-go.ts"
        header_path = pi_root / "packages" / "ai" / "src" / "providers" / "opencode-headers.ts"
        if not provider_path.is_file() or not header_path.is_file():
            raise RuntimeConfigError(
                "pinned Pi does not provide built-in OpenCode Go support; refusing a custom fallback"
            )
        provider_source = provider_path.read_text(encoding="utf-8")
        header_source = header_path.read_text(encoding="utf-8")
        if "opencodeGoProvider" not in provider_source or "OPENCODE_API_KEY" not in provider_source:
            raise RuntimeConfigError("pinned Pi OpenCode Go provider is incomplete")
        if "x-opencode-session" not in header_source:
            raise RuntimeConfigError("pinned Pi OpenCode session-header support is incomplete")
    if not any("{pi_root}" in part for part in command):
        raise RuntimeConfigError("launch_command must reference {pi_root} for a local Pi checkout")
    return [part.replace("{pi_root}", str(pi_root)) for part in command], pi_root


class _SseLogprobCapture:
    """Extract per-token logprobs from a relayed OpenAI-style SSE response.

    Reads the same bytes the proxy is already forwarding to the agent
    unmodified; a parsing failure here must never affect the relayed stream,
    so every entry point swallows malformed input instead of raising.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._tokens: list[dict[str, Any]] = []

    def feed(self, chunk: bytes) -> None:
        self._buffer.extend(chunk)
        while b"\n" in self._buffer:
            line, _, rest = self._buffer.partition(b"\n")
            self._buffer = bytearray(rest)
            self._consume_line(line)

    def _consume_line(self, line: bytes) -> None:
        text = line.strip()
        if not text.startswith(b"data:"):
            return
        payload = text[len(b"data:"):].strip()
        if not payload or payload == b"[DONE]":
            return
        try:
            event = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        try:
            choices = event["choices"]
            choice = choices[0]
        except (KeyError, IndexError, TypeError):
            return
        delta = choice.get("delta") if isinstance(choice, Mapping) else None
        channel = "content"
        if isinstance(delta, Mapping) and delta.get("reasoning"):
            channel = "reasoning"
        logprobs = choice.get("logprobs") if isinstance(choice, Mapping) else None
        entries = logprobs.get("content") if isinstance(logprobs, Mapping) else None
        if not isinstance(entries, list):
            return
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            token = entry.get("token")
            logprob = entry.get("logprob")
            if not isinstance(token, str) or not isinstance(logprob, (int, float)):
                continue
            alternatives = [
                {"token": item.get("token"), "logprob": item.get("logprob")}
                for item in entry.get("top_logprobs") or []
                if isinstance(item, Mapping)
                and isinstance(item.get("token"), str)
                and isinstance(item.get("logprob"), (int, float))
            ]
            self._tokens.append({
                "token": token,
                "logprob": float(logprob),
                "channel": channel,
                "top_logprobs": alternatives,
            })

    def finalize(self) -> dict[str, Any] | None:
        if not self._tokens:
            return None
        return {"token_count": len(self._tokens), "tokens": self._tokens}


def _top_k_entropy_bits(logprob: float, top_logprobs: list[Mapping[str, Any]]) -> float:
    """Top-K entropy lower bound over the sampled token plus its alternatives.

    Mirrors ``scripts/ollama_goal_inference.py``'s ``_per_token_entropy``: true
    vocabulary entropy is unavailable from Ollama's logprobs surface, so this
    renormalizes the sampled token and its reported alternatives into a
    pseudo-distribution and reports Shannon entropy over that top-K pool.
    """

    logprobs = [logprob] + [
        float(item["logprob"]) for item in top_logprobs if isinstance(item.get("logprob"), (int, float))
    ]
    max_logprob = max(logprobs)
    probabilities = [math.exp(value - max_logprob) for value in logprobs]
    total = sum(probabilities)
    normalized = [probability / total for probability in probabilities]
    return -sum(probability * math.log2(probability) for probability in normalized if probability > 0)


def _summarize_agent_logits(logits_path: Path) -> dict[str, Any] | None:
    """Fold a per-agent logits.jsonl capture into surprise/entropy summary stats."""

    if not logits_path.is_file():
        return None
    turn_count = 0
    token_count = 0
    surprise_bits = 0.0
    top_k_entropy_bits = 0.0
    channel_counts: dict[str, int] = defaultdict(int)
    try:
        with logits_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                tokens = record.get("tokens") if isinstance(record, Mapping) else None
                if not isinstance(tokens, list) or not tokens:
                    continue
                turn_count += 1
                for entry in tokens:
                    if not isinstance(entry, Mapping):
                        continue
                    logprob = entry.get("logprob")
                    if not isinstance(logprob, (int, float)):
                        continue
                    token_count += 1
                    surprise_bits += -float(logprob) / math.log(2)
                    top_k_entropy_bits += _top_k_entropy_bits(float(logprob), entry.get("top_logprobs") or [])
                    channel_counts[str(entry.get("channel", "content"))] += 1
    except OSError:
        return None
    if token_count == 0:
        return None
    return {
        "turn_count": turn_count,
        "token_count": token_count,
        "channel_counts": dict(sorted(channel_counts.items())),
        "mean_surprise_bits": round(surprise_bits / token_count, 6),
        "mean_top_k_entropy_bits": round(top_k_entropy_bits / token_count, 6),
    }


class _ModelEgressProxy:
    """Host-side allowlisted relay for the isolated model process."""

    def __init__(
        self,
        socket_path: Path,
        allowed_hosts: Iterable[str],
        *,
        local_target: tuple[str, int] | None = None,
        logits_sink: Path | None = None,
    ) -> None:
        self.socket_path = socket_path
        self.allowed_hosts = frozenset(host.lower() for host in allowed_hosts)
        if local_target is not None:
            host, port = local_target
            if ":" in host or not _MODEL_HOST.fullmatch(host.lower()) or not 1 <= port <= 65535:
                raise RuntimeConfigError("local model target must be a valid host and port")
            self.local_target = (host.lower().rstrip("."), port)
        else:
            self.local_target = None
        self.logits_sink = logits_sink
        self._logits_lock = Lock()
        self._logits_sequence = 0
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
            header_bytes, remainder = request
            if self.local_target is not None:
                normalized_request = self._parse_local_request(header_bytes)
                if normalized_request is None:
                    self._deny(client)
                    return
                upstream = socket.create_connection(self.local_target, timeout=30)
                try:
                    upstream.sendall(normalized_request + remainder)
                    capture = _SseLogprobCapture() if self.logits_sink is not None else None
                    self._relay(client, upstream, on_right_chunk=capture.feed if capture else None)
                    if capture is not None:
                        self._write_logits_record(capture.finalize())
                finally:
                    upstream.close()
                return
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
        if self.local_target is not None:
            return (host.lower().rstrip("."), port) == self.local_target
        return host.lower().rstrip(".") in self.allowed_hosts and port == 443

    def _parse_connect_target(self, target: str) -> tuple[str, int] | None:
        """Validate an explicit HTTPS CONNECT target and its allowlist entry."""

        if self.local_target is not None:
            return None
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
    def _parse_local_request(header_bytes: bytes) -> bytes | None:
        """Accept only Ollama's OpenAI-compatible chat completion request."""

        try:
            header_text = header_bytes.decode("latin-1")
        except UnicodeDecodeError:
            return None
        lines = header_text.rstrip("\r\n").split("\r\n")
        if not lines:
            return None
        parts = lines[0].split(" ", 2)
        if len(parts) != 3 or parts[0] != "POST" or parts[2] not in {"HTTP/1.0", "HTTP/1.1"}:
            return None
        request_target = parts[1]
        if request_target == _OLLAMA_PROXY_PATH:
            normalized_target = request_target
        else:
            try:
                parsed_target = urllib.parse.urlsplit(request_target)
                target_port = parsed_target.port
            except ValueError:
                return None
            if (
                parsed_target.scheme != "http"
                or parsed_target.username is not None
                or parsed_target.password is not None
                or parsed_target.hostname != _OLLAMA_PROXY_HOST
                or target_port != _OLLAMA_PROXY_PORT
                or parsed_target.path != _OLLAMA_PROXY_PATH
                or parsed_target.query
                or parsed_target.fragment
            ):
                return None
            normalized_target = parsed_target.path
        host_values = [
            line.partition(":")[2].strip()
            for line in lines[1:]
            if line.partition(":")[0].lower() == "host"
        ]
        if len(host_values) != 1 or host_values[0] != f"{_OLLAMA_PROXY_HOST}:{_OLLAMA_PROXY_PORT}":
            return None
        if not all(":" in line for line in lines[1:] if line):
            return None
        if normalized_target == request_target:
            return header_bytes
        lines[0] = f"POST {normalized_target} {parts[2]}"
        return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")

    @staticmethod
    def _deny(client: socket.socket) -> None:
        try:
            client.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
        except OSError:
            pass

    @staticmethod
    def _relay(
        left: socket.socket,
        right: socket.socket,
        *,
        on_right_chunk: Callable[[bytes], None] | None = None,
    ) -> None:
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
                if source is right and on_right_chunk is not None:
                    try:
                        on_right_chunk(payload)
                    except Exception:
                        # Best-effort telemetry capture must never interrupt
                        # the relay the sandboxed agent depends on.
                        on_right_chunk = None
                destination.sendall(payload)

    def _write_logits_record(self, record: dict[str, Any] | None) -> None:
        if record is None or self.logits_sink is None:
            return
        try:
            with self._logits_lock:
                self._logits_sequence += 1
                record = {"sequence": self._logits_sequence, "captured_at": _utc_now(), **record}
                self.logits_sink.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with self.logits_sink.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                self.logits_sink.chmod(0o600)
        except OSError:
            # Logits capture is best-effort telemetry, never a run-blocking path.
            pass


def build_pi_command(
    config: RuntimeConfig,
    identity: AgentIdentity,
    workspace: IsolatedWorkspace,
    extension: Path | None = None,
    auth_stage: _AuthStage | None = None,
    tool_socket: Path | None = None,
    model_proxy_socket: Path | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> list[str]:
    """Build the exact Pi argv used for one agent.

    The caller supplies an extension only when the constrained experiment
    tools exist. Explicit ``--no-*`` flags prevent project-local discovery from
    adding tools or instructions through the shared checkout.
    """

    config.isolation.validate()
    command, pi_root = _resolve_launch_command(config)
    source_auth_file = _resolve_auth_file(config)
    if auth_stage is None:
        auth_stage = _prepare_auth_file(source_auth_file, workspace, config)
    auth_file = auth_stage.target if auth_stage is not None else None
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
    resolved_tool_socket: Path | None = None
    if tool_socket is not None:
        resolved_tool_socket = tool_socket.expanduser().resolve()
        if resolved_tool_socket.name != ".apart-tool-service.sock":
            raise RuntimeConfigError("tool service socket must use the controller socket name")
        try:
            resolved_tool_socket.relative_to(workspace.root.resolve())
        except ValueError as exc:
            transient_root = Path(tempfile.gettempdir()).resolve()
            transient_parent = resolved_tool_socket.parent
            try:
                transient_parent.relative_to(transient_root)
            except ValueError:
                raise RuntimeConfigError("tool service socket must be inside the agent workspace or a private transient IPC directory") from exc
            try:
                transient_mode = stat.S_IMODE(transient_parent.stat().st_mode)
            except OSError as stat_error:
                raise RuntimeConfigError("tool service socket must use a private transient IPC directory") from stat_error
            if (
                transient_parent.parent != transient_root
                or not transient_parent.name.startswith("apart-tool-")
                or transient_mode != 0o700
            ):
                raise RuntimeConfigError("tool service socket must use a private transient IPC directory") from exc
    resolved_model_proxy_socket: Path | None = None
    if model_proxy_socket is not None:
        resolved_model_proxy_socket = model_proxy_socket.expanduser().resolve()
        if resolved_model_proxy_socket.name != ".apart-model-proxy.sock":
            raise RuntimeConfigError("model proxy socket must use the controller socket name")
        try:
            resolved_model_proxy_socket.relative_to(workspace.root.resolve())
        except ValueError as exc:
            transient_root = Path(tempfile.gettempdir()).resolve()
            transient_parent = resolved_model_proxy_socket.parent
            try:
                transient_parent.relative_to(transient_root)
            except ValueError:
                raise RuntimeConfigError("model proxy socket must use a private transient IPC directory") from exc
            try:
                transient_mode = stat.S_IMODE(transient_parent.stat().st_mode)
            except OSError as stat_error:
                raise RuntimeConfigError("model proxy socket must use a private transient IPC directory") from stat_error
            if (
                transient_parent.parent != transient_root
                or not transient_parent.name.startswith("apart-model-")
                or transient_mode != 0o700
            ):
                raise RuntimeConfigError("model proxy socket must use a private transient IPC directory") from exc
    if config.isolation.sandbox == "none":
        return command
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise RuntimeConfigError("bubblewrap is required but was not found on PATH")
    home = workspace.root / "home"
    home.mkdir(mode=0o700, exist_ok=True)
    (home / ".pi" / "agent").mkdir(mode=0o700, parents=True, exist_ok=True)
    safe_env = _safe_env(identity, workspace, config, extra_env)
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
    if resolved_tool_socket is not None:
        safe_env["APART_TOOL_SOCKET"] = (
            "/workspace/.apart-tool-service.sock"
            if config.isolation.sandbox == "bubblewrap"
            else str(resolved_tool_socket)
        )
    credential_file = (extra_env or {}).get("APART_CONTROLLER_CREDENTIAL_FILE")
    resolved_credential_file: Path | None = None
    if credential_file is not None:
        resolved_credential_file = Path(credential_file).expanduser().resolve()
        if resolved_credential_file.is_symlink() or not resolved_credential_file.is_file():
            raise RuntimeConfigError("controller credential file is not a regular file")
        try:
            resolved_credential_file.relative_to(workspace.root.resolve())
        except ValueError:
            pass
        else:
            raise RuntimeConfigError("controller credential file must be outside the agent mount")
        safe_env["APART_CONTROLLER_CREDENTIAL_FILE"] = "/controller/credential"
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
    if resolved_tool_socket is not None:
        insert_at = sandbox_command.index("--chdir")
        sandbox_command[insert_at:insert_at] = [
            "--bind",
            str(resolved_tool_socket),
            "/workspace/.apart-tool-service.sock",
        ]
    if resolved_model_proxy_socket is not None:
        insert_at = sandbox_command.index("--chdir")
        sandbox_command[insert_at:insert_at] = [
            "--bind",
            str(resolved_model_proxy_socket),
            "/workspace/.apart-model-proxy.sock",
        ]
    if resolved_credential_file is not None:
        insert_at = sandbox_command.index("--chdir")
        sandbox_command[insert_at:insert_at] = [
            "--dir",
            "/controller",
            "--ro-bind",
            str(resolved_credential_file),
            "/controller/credential",
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
        extension_mounts = [
            "--dir",
            "/experiment",
            "--dir",
            extension_mount,
            "--ro-bind",
            str(resolved_extension.parent),
            extension_mount,
        ]
        if pi_root is not None and (pi_root / "node_modules").is_dir():
            extension_mounts.extend([
                "--ro-bind",
                str(pi_root / "node_modules"),
                "/experiment/node_modules",
            ])
        sandbox_command[insert_at:insert_at] = extension_mounts
        command = [
            part.replace(str(resolved_extension), f"{extension_mount}/{resolved_extension.name}")
            for part in command
        ]
    # Bubblewrap starts from an empty tmpfs root. Expose only the immutable
    # host runtime trees required to execute Bun/Python. The Nix paths cover
    # NixOS, while /usr and the library trees cover Debian-based containers
    # and conventional Linux hosts.
    for runtime_path in (
        "/usr",
        "/lib",
        "/lib64",
        "/nix/store",
        "/run/current-system",
    ):
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
        wrapped_command = [
            bridge_python,
            "-m",
            "apart_incident_response.network_bridge",
            "--socket",
            "/workspace/.apart-model-proxy.sock",
            "--port",
            "18080",
        ]
        if _model_provider(config.model) == _OLLAMA_PROVIDER:
            wrapped_command.extend(["--local-port", str(_OLLAMA_PROXY_PORT)])
        command = [*wrapped_command, "--", *command]
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


def _bubblewrap_failure_reason(stderr_lines: Iterable[str]) -> str | None:
    """Turn namespace setup failures into an explicit launch status."""

    for line in stderr_lines:
        stripped = line.strip()
        if stripped.startswith("bwrap:") and (
            "NETLINK_ROUTE" in stripped
            or "RTM_NEWADDR" in stripped
            or "network namespace" in stripped.lower()
        ):
            return f"Bubblewrap isolation failed: {stripped}"
    return None


def _persistence_failure_diagnostic(error: BaseException) -> str:
    """Describe persistence failure without copying exception details or secrets."""

    return f"OAuth credential persistence failed ({type(error).__name__})"


def _submission_finalization_failure_diagnostic(error: BaseException) -> str:
    """Describe submission finalization failure without copying artifact data."""

    return f"Task submission finalization failed ({type(error).__name__})"


def _merge_persistence_diagnostics(
    first: str | None, second: str | None
) -> str | None:
    if first is None:
        return second
    if second is None:
        return first
    return f"{first}; {second}"


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
    persistence_failure: str | None = None
    provider_started_at: str | None = None

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
        tool_service: "ConstrainedToolService | None" = None,
    ) -> None:
        self.config = config
        self.identity = identity
        self.workspace = workspace
        self.system_budget = system_budget
        self.tool_service = tool_service

    def run(self, prompt: str | None = None, extension: Path | None = None) -> RunResult:
        if prompt is None:
            prompt = self.config.prompt_for(self.identity.task_id, self.identity.seed)
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
        model_ipc_dir: Path | None = None
        tool_server: "ToolServiceSocketServer | None" = None
        tool_ipc_dir: Path | None = None
        bind_mount_placeholders: list[Path] = []
        tool_environment: dict[str, str] = {}
        credential_file: Path | None = None
        auth_stage: _AuthStage | None = None
        settlement: BudgetSettlement | None = None
        result: RunResult | None = None
        persistence_failure: str | None = None
        provider_api_key: str | None = None
        secret_values: tuple[str, ...] = ()

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
            if self.tool_service is not None:
                from .tool_service import ToolServiceSocketServer

                # The controller owns the counters that a task submission may
                # record; initialize them before the child can call a tool.
                self.tool_service.update_runtime_usage(self.identity, 0, 0)
                tool_ipc_dir = Path(tempfile.mkdtemp(prefix="apart-tool-", dir=tempfile.gettempdir()))
                tool_ipc_dir.chmod(0o700)
                tool_server = ToolServiceSocketServer(
                    self.tool_service,
                    tool_ipc_dir / ".apart-tool-service.sock",
                    use_fifo=self.config.isolation.sandbox == "none",
                )
                try:
                    tool_server.start()
                    credential = self.tool_service.issue_credential(self.identity)
                    secret_values = (credential,)
                    add_redaction_secret = getattr(self.tool_service, "add_redaction_secret", None)
                    if callable(add_redaction_secret):
                        add_redaction_secret(credential)
                    credential_file = (
                        self.workspace.run_root
                        / f".apart-controller-credential-{self.identity.agent_id}"
                    )
                    _stage_controller_credential(credential_file, credential)
                    tool_environment = {
                        "APART_CONTROLLER_CREDENTIAL_FILE": str(credential_file)
                    }
                    if tool_server.uses_fifo:
                        tool_environment["APART_TOOL_REQUEST_FIFO"] = str(tool_server.request_fifo)
                        tool_environment["APART_TOOL_RESPONSE_FIFO"] = str(tool_server.response_fifo)
                    else:
                        tool_environment["APART_TOOL_SOCKET"] = str(tool_server.socket_path)
                except (OSError, RuntimeConfigError, ValueError) as exc:
                    failure_reason = f"tool service setup failed ({type(exc).__name__})"
                    status = ExitStatus.LAUNCH_ERROR
                    result = self._finish(
                        status, exit_code, started_at, _utc_now(), started_clock,
                        final_response, failure_reason, command, events,
                        agent_tokens_used, agent_tool_calls_used,
                    )
                    return result
            if self.config.isolation.model_network and self.config.isolation.sandbox == "bubblewrap":
                model_ipc_dir = Path(tempfile.mkdtemp(prefix="apart-model-", dir=tempfile.gettempdir()))
                model_ipc_dir.chmod(0o700)
                model_socket = model_ipc_dir / ".apart-model-proxy.sock"
                if _model_provider(self.config.model) == _OLLAMA_PROVIDER:
                    ollama_host, ollama_port, _endpoint, _raw_host = _resolve_ollama_target()
                    proxy = _ModelEgressProxy(
                        model_socket,
                        (),
                        local_target=(ollama_host, ollama_port),
                        logits_sink=self.workspace.artifact_dir / "logits.jsonl",
                    )
                else:
                    proxy = _ModelEgressProxy(
                        model_socket,
                        (*self.config.isolation.model_hosts, *self.config.isolation.oauth_hosts),
                    )
                proxy.start()
            provider_api_key = _resolve_provider_api_key(self.config)
            if provider_api_key is not None:
                secret_values = (*secret_values, provider_api_key)
                if self.tool_service is not None:
                    self.tool_service.add_redaction_secret(provider_api_key)
            auth_stage = _prepare_auth_file(
                _resolve_auth_file(self.config),
                self.workspace,
                self.config,
                api_key=provider_api_key,
                hold_lock=False,
            )
            if self.config.isolation.sandbox == "bubblewrap":
                if tool_server is not None and not tool_server.uses_fifo:
                    placeholder = self.workspace.root / ".apart-tool-service.sock"
                    _create_bind_mount_placeholder(placeholder)
                    bind_mount_placeholders.append(placeholder)
                if model_ipc_dir is not None:
                    placeholder = self.workspace.root / ".apart-model-proxy.sock"
                    _create_bind_mount_placeholder(placeholder)
                    bind_mount_placeholders.append(placeholder)
            command = build_pi_command(
                self.config,
                self.identity,
                self.workspace,
                extension,
                auth_stage=auth_stage,
                tool_socket=(
                    tool_server.socket_path
                    if (
                        tool_server is not None
                        and not tool_server.uses_fifo
                    )
                    else None
                  ),
                  model_proxy_socket=(
                      model_ipc_dir / ".apart-model-proxy.sock"
                      if model_ipc_dir is not None
                      else None
                  ),
                  extra_env=tool_environment,
            )
            _prepare_model_limits(self.workspace, self.config)
            self._write_json(artifact_dir / "metadata.json", {
                "identity": self.identity.to_dict(),
                "runtime": self.config.to_dict(),
                "model_request": _model_request_metadata(self.config),
                "prompt": prompt,
                "command": command,
                "started_at": started_at,
            })
            stdout_path.write_text("", encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            stdout_path.chmod(0o600)
            stderr_path.chmod(0o600)

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
                result = self._finish(
                    status, exit_code, started_at, _utc_now(), started_clock,
                    final_response, failure_reason, command, events,
                    agent_tokens_used, agent_tool_calls_used,
                )
                return result

            try:
                provider_started_at = _utc_now()
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=self.workspace.task_dir,
                    env=_safe_env(
                        self.identity, self.workspace, self.config, tool_environment
                    ),
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
                result = self._finish(
                    status, exit_code, started_at, _utc_now(), started_clock,
                    final_response, failure_reason, command, events,
                    agent_tokens_used, agent_tool_calls_used,
                )
                return result

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
                                safe_line = _redact_text(line, secret_values) or ""
                                stdout_file.write(safe_line)
                                stdout_file.flush()
                                stdout_lines.append(safe_line)
                                event = self._parse_event(line)
                                if event is None:
                                    continue
                                event.setdefault("observed_at", _utc_now())
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
                                if self.tool_service is not None:
                                    self.tool_service.update_runtime_usage(
                                        self.identity,
                                        agent_tokens_used,
                                        agent_tool_calls_used,
                                    )
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
                                safe_line = _redact_text(line, secret_values) or ""
                                stderr_file.write(safe_line)
                                stderr_file.flush()
                                stderr_lines.append(safe_line)
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
                    bubblewrap_failure = _bubblewrap_failure_reason(stderr_lines)
                    if bubblewrap_failure is not None:
                        status = ExitStatus.LAUNCH_ERROR
                        failure_reason = bubblewrap_failure
                    else:
                        status = ExitStatus.FAILED
                        if failure_reason is None:
                            failure_reason = f"agent exited with status {exit_code}"
            settle_claim()
            if self.tool_service is not None:
                # The submission may have raced the stdout event that reports
                # its tool call. Finalize after the child and selector have
                # fully drained so the artifact carries complete usage.
                try:
                    self.tool_service.finalize_runtime_usage(self.identity)
                except Exception as exc:
                    # A malformed or unavailable submission artifact must not
                    # erase the run's exit status or prevent result.json from
                    # being written. Keep the diagnostic type-only because
                    # the exception may contain paths or sensitive data.
                    persistence_failure = _submission_finalization_failure_diagnostic(exc)
            result = self._finish(
                status, exit_code, started_at, _utc_now(), started_clock,
                final_response, failure_reason, command, events,
                agent_tokens_used, agent_tool_calls_used,
                persistence_failure=persistence_failure,
                provider_started_at=provider_started_at,
                secret_values=secret_values,
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
            auth_persistence_failure: str | None = None
            try:
                _persist_auth_stage(auth_stage)
            except Exception as exc:
                # Keep the diagnostic deliberately class-only: exception
                # messages can contain paths or provider data and must never
                # expose a credential in the artifact.
                auth_persistence_failure = _persistence_failure_diagnostic(exc)
            try:
                self._cleanup_staged_auth()
            except Exception:
                pass
            if proxy is not None:
                try:
                    proxy.stop()
                except Exception:
                    pass
            if model_ipc_dir is not None:
                try:
                    shutil.rmtree(model_ipc_dir)
                except OSError:
                    pass
            for placeholder in bind_mount_placeholders:
                try:
                    placeholder.unlink(missing_ok=True)
                except OSError:
                    pass
            if tool_server is not None:
                try:
                    tool_server.stop()
                except Exception:
                    pass
            if tool_ipc_dir is not None:
                try:
                    shutil.rmtree(tool_ipc_dir)
                except OSError:
                    pass
            if credential_file is not None:
                try:
                    credential_file.unlink(missing_ok=True)
                except OSError:
                    pass
            if auth_stage is not None:
                try:
                    auth_stage.release()
                except Exception:
                    pass
            if auth_persistence_failure is not None and result is not None:
                result.persistence_failure = _merge_persistence_diagnostics(
                    result.persistence_failure, auth_persistence_failure
                )
                if result.status is ExitStatus.COMPLETED:
                    result.status = ExitStatus.FAILED
                result.failure_reason = (
                    f"{result.failure_reason}; {result.persistence_failure}"
                    if result.failure_reason
                    else result.persistence_failure
                )
                try:
                    self._write_json(
                        self.workspace.artifact_dir / "result.json", result.to_dict()
                    )
                except Exception:
                    # Preserve the original run result if artifact rewriting
                    # itself is unavailable; never mask it from the caller.
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
        path.chmod(0o600)

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
        persistence_failure: str | None = None,
        provider_started_at: str | None = None,
        secret_values: Sequence[str] = (),
    ) -> RunResult:
        safe_final_response = _redact_text(final_response, secret_values)
        safe_failure_reason = _redact_text(failure_reason, secret_values)
        safe_persistence_failure = _redact_text(persistence_failure, secret_values)
        safe_events = [
            _redact_value(event, secret_values)
            for event in events
        ]
        result = RunResult(
            identity=self.identity,
            status=status,
            exit_code=exit_code,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=round(time.monotonic() - started_clock, 6),
            tokens_used=tokens_used,
            tool_calls_used=tool_calls_used,
            final_response=safe_final_response,
            failure_reason=safe_failure_reason,
            command=command,
            workspace=str(self.workspace.root),
            artifact_dir=str(self.workspace.artifact_dir),
            events=safe_events,
            persistence_failure=safe_persistence_failure,
            provider_started_at=provider_started_at,
        )
        response_text = safe_final_response or ""
        response_bytes = response_text.encode("utf-8")
        tokenizer_config = {
            "name": "utf8-byte-v1",
            "version": "1",
            "normalization": "none",
            "encoding": "utf-8",
        }
        tokenizer_config_hash = hashlib.sha256(
            json.dumps(tokenizer_config, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        (self.workspace.artifact_dir / "final_response.txt").write_bytes(response_bytes)
        (self.workspace.artifact_dir / "final_response.txt").chmod(0o600)
        self._write_json(self.workspace.artifact_dir / "response.json", {
            "schema_version": 1,
            "identity": self.identity.to_dict(),
            "final_response": safe_final_response,
            "response_sha256": hashlib.sha256(response_bytes).hexdigest(),
            "provider_token_count": tokens_used,
            "tokenizer": tokenizer_config,
            "tokenizer_config_sha256": tokenizer_config_hash,
            "token_ids": list(response_bytes),
            "token_count": len(response_bytes),
            "token_count_definition": "derived UTF-8 byte token count; provider_token_count is authoritative usage",
        })
        event_counts: dict[str, int] = defaultdict(int)
        for event in safe_events:
            event_counts[str(event.get("type", "unknown"))] += 1
        logits_summary = _summarize_agent_logits(self.workspace.artifact_dir / "logits.jsonl")
        self._write_json(self.workspace.artifact_dir / "agent_telemetry.json", {
            "schema_version": 1,
            "identity": self.identity.to_dict(),
            "started_at": started_at,
            "provider_started_at": provider_started_at,
            "ended_at": ended_at,
            "status": status.value,
            "event_counts": dict(sorted(event_counts.items())),
            "turn_count": event_counts.get("turn_end", event_counts.get("message_end", 0)),
            "tool_call_count": tool_calls_used,
            "provider_tokens": tokens_used,
            "wall_clock_seconds": round(time.monotonic() - started_clock, 6),
            "failure_reason": safe_failure_reason,
            "logits": logits_summary,
        })
        (self.workspace.artifact_dir / "events.json").write_text(
            json.dumps(safe_events, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (self.workspace.artifact_dir / "events.json").chmod(0o600)
        self._write_json(self.workspace.artifact_dir / "result.json", result.to_dict())
        return result


def load_identity(raw: Mapping[str, Any]) -> AgentIdentity:
    """Parse identity data at a controller boundary."""

    return AgentIdentity.from_dict(raw)


def _validate_config_command(path: Path) -> int:
    config = RuntimeConfig.from_json(path)
    print(json.dumps(config.to_dict(), indent=2, sort_keys=True))
    return 0


def _build_cli_tool_service(
    args: argparse.Namespace,
    identity: AgentIdentity,
    workspace: IsolatedWorkspace,
) -> tuple[Any, Any]:
    """Build the controller tool boundary for an explicitly mounted extension."""

    from .board_storage import BoardStore
    from .tool_service import (
        BoardToolService,
        ConstrainedToolService,
        TaskCatalog,
        TaskDefinition,
        TaskToolService,
    )

    from .task_one import TASK_ONE_ID

    if identity.task_id == TASK_ONE_ID:
        from .task_one import TASK_ONE_EVIDENCE_BUNDLES, materialize_task_one_bundle

        bundle = next(
            (candidate for candidate in TASK_ONE_EVIDENCE_BUNDLES if candidate.agent_id == identity.agent_id),
            None,
        )
        if bundle is None:
            raise RuntimeConfigError("Task 1 has no evidence bundle for the authenticated agent")
        bundle_name = Path(bundle.relative_path).name
        if args.task_root is None:
            task_root = workspace.task_dir
            materialize_task_one_bundle(task_root, identity.agent_id)
        else:
            supplied_root = Path(args.task_root).expanduser().resolve()
            candidate_root = supplied_root / identity.agent_id
            task_root = candidate_root if candidate_root.is_dir() else supplied_root
        task_definition = TaskDefinition(
            identity.task_id,
            task_root,
            allowed_paths=(bundle_name,),
        )
    else:
        task_root = args.task_root or workspace.task_dir
        task_definition = TaskDefinition(identity.task_id, task_root)
    catalog = TaskCatalog({identity.task_id: task_definition})
    board_store = None
    board_service = None
    if identity.condition is not Condition.C0:
        database_path = args.board_database or workspace.run_root / ".apart-board.sqlite3"
        board_store = BoardStore.initialize(
            database_path,
            agent_workspace_roots=(workspace.root,),
        )
        board_service = BoardToolService(board_store)
    service = ConstrainedToolService(
        TaskToolService(catalog),
        board_service,
        artifact_root=workspace.workspace_root,
    )
    return service, board_store


def _run_agent_command(args: argparse.Namespace) -> int:
    config = RuntimeConfig.from_json(args.config)
    identity = AgentIdentity(
        run_id=args.run_id,
        agent_id=args.agent_id,
        condition=Condition(args.condition),
        task_id=args.task_id,
        seed=args.seed,
    )
    if args.prompt is not None:
        prompt = args.prompt
    elif args.prompt_file is not None:
        prompt = args.prompt_file.read_text(encoding="utf-8")
    else:
        prompt = None
    workspace = create_isolated_workspace(args.workspace_root, identity)
    tool_service = None
    board_store = None
    if args.extension is not None:
        tool_service, board_store = _build_cli_tool_service(args, identity, workspace)
    try:
        result = AgentRun(
            config,
            identity,
            workspace,
            SystemBudget(config.aggregate_token_budget, config.aggregate_tool_call_budget),
            tool_service,
        ).run(prompt, args.extension)
    finally:
        if board_store is not None:
            board_store.close()
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
    run.add_argument("--task-root", type=Path)
    run.add_argument("--board-database", type=Path)
    prompt = run.add_mutually_exclusive_group(required=False)
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
