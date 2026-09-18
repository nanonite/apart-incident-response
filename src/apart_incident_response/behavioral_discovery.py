"""Credential-safe behavioral discovery adapter and pilot audit.

This path intentionally does not request logprobs.  Behavioral validity and
entropy eligibility are independent fields, and the artifact store retains
only controller-side summaries and hashes.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import argparse
import hashlib
import json
import math
import os
from enum import Enum
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Iterable, Mapping, Sequence

from .communication_analysis import PairedOutcome, paired_metrics
from .communication_protocol import BatteryCondition, DependenceRegime, ReasoningComplexity
from .communication_report import report_from_battery
from .communication_runner import AgentContext, AgentResponse, BatteryRunResult, TwoAgentBatteryRunner
from .reasoning_baseline import DEFAULT_FREE_MODEL, PROJECT_ENV_FILE, OPENROUTER_ENV_FILE
from .task_families import (
    GENERATOR_VERSION,
    FamilyInstance,
    audit_channel_invariants,
    generate_instance,
    preregistered_manifest,
)


ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
BEHAVIORAL_VERSION = "behavioral-discovery-v1"
FULL_GATE_VERSION = "t1a-full-only-gate-v1"
PROMPT_SCHEMA_VERSION = "treatment-prompt-v2"
ORACLE_SCHEMA_VERSION = "behavioral-oracle-v1"
ORACLE_CONDITION = "ORACLE"
# One-way finalizer policy, preregistered: A is always the scored finalizer and B
# is the peer. No A/B counterbalancing is attempted in this subepic.
FINALIZER_POLICY = "one_way_A_finalizer"
FINALIZER_AGENT = "A"
BOARD_FREE_CONDITIONS = ("ISO", "FULL", ORACLE_CONDITION)
# Frozen per-condition turn schedule: board-free conditions are single-shot, COMM
# needs two turns so the finalizer can read a peer message. Bound into the
# protocol key so mixed schedules cannot be pooled.
DEFAULT_CONDITION_TURNS: dict[str, int] = {"ISO": 1, "FULL": 1, "COMM": 2}
# Proposed floor below which eta_comm is reported as undefined.
MINIMUM_EFFECTIVE_C_NEED = 0.10
TREATMENT_PROMPT_FIELDS = (
    "instruction", "family", "complexity", "condition", "turn", "is_finalizer",
    "finalizing_agent", "candidate_labels", "joint_clues", "private_clues", "visible_messages",
)


class DiagnosticCondition(str, Enum):
    """Manipulation-check conditions kept outside the primary ISO/FULL/COMM battery."""

    ORACLE = ORACLE_CONDITION
    # Required-claim / silence-penalty inducement. Distinct condition identity so
    # it is never pooled with voluntary COMM.
    INDUCED = "INDUCED"


INDUCED_SCHEMA_VERSION = "behavioral-induced-v1"


def provider_seed(instance_id: str, condition: str, turn: int, agent_id: str) -> int:
    """Reproducible provider seed derived from instance, condition, turn and agent."""

    payload = f"{instance_id}|{condition}|{turn}|{agent_id}"
    return int(hashlib.sha256(payload.encode()).hexdigest()[:8], 16)


def treatment_prompt(context: AgentContext) -> dict[str, Any]:
    """Exact model-visible prompt schema; never contains a joint candidate answer key."""

    return {
        "instruction": context.task_view.get("task_instruction"),
        "family": context.task_view.get("family"),
        "complexity": context.task_view.get("complexity"),
        "condition": context.condition.value,
        "turn": context.turn,
        "is_finalizer": context.task_view.get("is_finalizer", False),
        "finalizing_agent": context.task_view.get("finalizing_agent"),
        "candidate_labels": context.task_view.get("candidate_labels", []),
        "joint_clues": context.task_view.get("joint_clues", []),
        "private_clues": context.task_view.get("private_clues", []),
        "visible_messages": list(context.visible_messages),
    }


def treatment_prompt_hash(context: AgentContext) -> str:
    return hashlib.sha256(json.dumps(treatment_prompt(context), sort_keys=True).encode()).hexdigest()


PROTOCOL_OUTPUT_STEM = GENERATOR_VERSION


def _treatment_schema_hash() -> str:
    return hashlib.sha256(json.dumps(treatment_schema(), sort_keys=True).encode()).hexdigest()[:16]


def run_settings_hash(*, turns: int | Mapping[str, int] | None, max_tokens: int | None,
                      finalizing_agent: str = FINALIZER_AGENT) -> str:
    """Hash of the frozen run settings that must match across a protocol boundary."""

    settings = {
        "turns": dict(turns) if isinstance(turns, Mapping) else turns,
        "max_tokens": max_tokens,
        "finalizing_agent": finalizing_agent,
        "finalizer_policy": FINALIZER_POLICY,
        "prompt_schema_version": PROMPT_SCHEMA_VERSION,
        "temperature": 0.0,
        "stream": False,
        "require_parameters": True,
    }
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:16]


def current_protocol_key(model_id: str, provider_version: str, *,
                         turns: int | Mapping[str, int] | None = None,
                         max_tokens: int | None = None,
                         finalizing_agent: str = FINALIZER_AGENT) -> str:
    """Boundary that prevents mixing runs from different protocols, models or settings."""

    return "|".join([
        GENERATOR_VERSION,
        PROMPT_SCHEMA_VERSION,
        _treatment_schema_hash(),
        run_settings_hash(turns=turns, max_tokens=max_tokens, finalizing_agent=finalizing_agent),
        str(model_id),
        str(provider_version),
    ])


def _protocol_extra(provider: Any, *, turns: int | Mapping[str, int], max_tokens: int,
                    finalizing_agent: str = FINALIZER_AGENT) -> dict[str, Any]:
    return {
        "generator_version": GENERATOR_VERSION,
        "prompt_schema_version": PROMPT_SCHEMA_VERSION,
        "protocol_key": current_protocol_key(getattr(provider, "model", "unknown"),
                                             getattr(provider, "version", "unknown"),
                                             turns=turns, max_tokens=max_tokens,
                                             finalizing_agent=finalizing_agent),
    }


def resolve_condition_turns(conditions: Sequence[BatteryCondition], *,
                            turns: int | None = None,
                            condition_turns: Mapping[str, int] | None = None) -> dict[str, int]:
    """Resolve the per-condition turn schedule (explicit > uniform > frozen default)."""

    names = [condition.value for condition in conditions]
    if condition_turns is not None:
        schedule = {name: int(condition_turns[name]) for name in names if name in condition_turns}
        missing = [name for name in names if name not in schedule]
        for name in missing:
            schedule[name] = int(turns) if turns is not None else DEFAULT_CONDITION_TURNS.get(name, 2)
    elif turns is not None:
        schedule = {name: int(turns) for name in names}
    else:
        schedule = {name: DEFAULT_CONDITION_TURNS.get(name, 2) for name in names}
    if any(value <= 0 for value in schedule.values()):
        raise ValueError("condition turns must be positive")
    return schedule


def request_budget(condition: str, turns: int, *, finalizer_only_board_free: bool = True) -> int:
    """Frozen per-instance agent-request budget for a condition."""

    if turns <= 0:
        raise ValueError("turns must be positive")
    agents = 1 if finalizer_only_board_free and condition in BOARD_FREE_CONDITIONS else 2
    return turns * agents


def treatment_schema() -> dict[str, Any]:
    """Locked treatment schema for the primary battery and the ORACLE check."""

    return {
        "prompt_schema_version": PROMPT_SCHEMA_VERSION,
        "prompt_fields": list(TREATMENT_PROMPT_FIELDS),
        "primary_conditions": [condition.value for condition in BatteryCondition],
        "diagnostic_conditions": [condition.value for condition in DiagnosticCondition],
        "board_free_conditions": list(BOARD_FREE_CONDITIONS),
        "forbidden_model_visible_fields": ["joint_candidate_labels"],
        "finalizer_policy": FINALIZER_POLICY,
        "finalizing_agent": FINALIZER_AGENT,
        "provider_seed_basis": "sha256(instance_id|condition|turn|agent_id)[:8]",
        "condition_turns": {**DEFAULT_CONDITION_TURNS, ORACLE_CONDITION: 1},
        "minimum_effective_c_need": MINIMUM_EFFECTIVE_C_NEED,
        "request_budget": {condition: request_budget(condition, DEFAULT_CONDITION_TURNS.get(condition, 1))
                           for condition in ("ISO", "FULL", ORACLE_CONDITION, "COMM")},
        "oracle_schema_version": ORACLE_SCHEMA_VERSION,
        "oracle_separate_from_primary": True,
        "comm_grammar": {
            "writer_may_submit": "only an exact claim from the writer's own private clues",
            "rejected_writes": "recorded as board_write_rejected with reason claim_not_owned_by_writer",
            "silence": "optional in the primary COMM arm; no penalty",
            "post_read_evidence": "correlation only (post_read_correlation); causal uptake requires matched replay",
            "inducement": "distinct INDUCED condition, never pooled with voluntary COMM",
        },
        "induced_schema_version": INDUCED_SCHEMA_VERSION,
        "cue_estimands": {"c_need": "p_FULL - p_ISO", "oracle_gap": "p_ORACLE - p_FULL"},
    }


# Only transient conditions may be retried.  Auth/payment/not-found errors are
# terminal so a bad credential or model slug cannot silently burn the request
# or cost budget on pointless retries.
RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
HTTP_ERROR_CLASSES = {
    400: "client_error",
    401: "auth_error",
    402: "payment_required",
    403: "auth_error",
    404: "endpoint_or_model_unavailable",
    405: "client_error",
    408: "request_timeout",
    409: "client_error",
    413: "client_error",
    418: "client_error",
    422: "client_error",
    429: "rate_limited",
}


def classify_http_status(status_code: int) -> str:
    """Map a provider HTTP status to a stable, sanitized error class."""

    if status_code in HTTP_ERROR_CLASSES:
        return HTTP_ERROR_CLASSES[status_code]
    if 500 <= status_code < 600:
        return "server_error"
    if 400 <= status_code < 500:
        return "client_error"
    return "http_error"


def is_retryable_status(status_code: int) -> bool:
    return status_code in RETRYABLE_STATUSES


def _retry_after_seconds(exc: urllib.error.HTTPError) -> float | None:
    raw = None
    for name, value in (exc.headers or {}).items():
        if str(name).lower() == "retry-after":
            raw = value
            break
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


def sanitize_provider_message(raw: str | None, api_key: str | None = None, *, limit: int = 300) -> str:
    """Redact credentials, account ids and token-like strings from a provider error message."""

    if not raw:
        return ""
    text = str(raw)
    if api_key:
        text = text.replace(api_key, "<redacted-key>")
    text = re.sub(r"\bsk-[A-Za-z0-9_\-]{6,}", "<redacted-key>", text)
    text = re.sub(r"\buser_[A-Za-z0-9]{6,}", "<redacted-user>", text)
    text = re.sub(r"[A-Za-z0-9_\-\.]{40,}", "<redacted-token>", text)
    return text[:limit]


def _secret_from_env_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        normalized = name.strip().removeprefix("export ").upper().replace("-", "_")
        if separator and normalized in {"OPENROUTER_API_KEY", "OPEN_ROUTER_API_KEY"} and value.strip():
            return value.strip().strip('"').strip("'")
    return None


def _api_key() -> str | None:
    for name in ("OPENROUTER_API_KEY", "OPEN_ROUTER_API_KEY"):
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
    configured = os.environ.get("APART_OPENROUTER_ENV_FILE", "").strip()
    for path in ([Path(configured)] if configured else []) + [PROJECT_ENV_FILE, OPENROUTER_ENV_FILE]:
        key = _secret_from_env_file(path)
        if key:
            return key
    return None


@dataclass(frozen=True)
class BehavioralProviderConfig:
    model: str = DEFAULT_FREE_MODEL
    endpoint: str = ENDPOINT
    max_requests: int = 288
    max_cost_usd: float = 20.0
    min_interval_seconds: float = 0.25
    retries: int = 1
    max_tokens: int = 96
    max_consecutive_failures: int = 2

    def __post_init__(self) -> None:
        if not self.model.endswith(":free"):
            raise ValueError("T1 adapter requires a :free model")
        if self.max_requests <= 0 or self.max_cost_usd < 0 or self.min_interval_seconds < 0:
            raise ValueError("invalid behavioral provider cap")
        if self.retries < 0 or self.max_tokens <= 0:
            raise ValueError("invalid behavioral retry or token cap")
        if self.max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be positive")


@dataclass(frozen=True)
class BehavioralResponse:
    text: str
    model: str
    usage: Mapping[str, Any]
    cost_usd: float
    status: str
    error_type: str | None = None
    status_code: int | None = None
    error_class: str | None = None
    retry_after_seconds: float | None = None
    request_id: str | None = None
    error_message: str | None = None


class OpenRouterBehavioralProvider:
    """OpenRouter chat provider with logprobs explicitly disabled."""

    provider = "openrouter"
    version = BEHAVIORAL_VERSION

    def __init__(self, config: BehavioralProviderConfig = BehavioralProviderConfig(), *, api_key: str | None = None) -> None:
        self.config = config
        self.model = config.model
        self.api_key = _api_key() if api_key is None else api_key
        self._lock = threading.Lock()
        self._last_request = 0.0
        self.request_count = 0
        self.cost_usd = 0.0
        self.input_tokens = 0
        self.output_tokens = 0
        self.consecutive_failures = 0
        self.last_model = config.model
        self.last_error_message: str | None = None
        self.failure_classes: Counter[str] = Counter()

    def _reserve(self) -> None:
        with self._lock:
            if self.request_count >= self.config.max_requests:
                raise RuntimeError("behavioral request cap exhausted")
            now = time.monotonic()
            delay = self.config.min_interval_seconds - (now - self._last_request)
            if delay > 0:
                time.sleep(delay)
            self._last_request = time.monotonic()
            self.request_count += 1

    def build_request(self, prompt: str, *, seed: int) -> urllib.request.Request:
        """Build a request that carries the key only in the Authorization header.

        The payload never contains the credential, logprob parameters, or any
        answer key beyond what the caller deliberately places in the prompt.
        """

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "max_tokens": self.config.max_tokens,
            "temperature": 0.0,
            "seed": seed,
            "provider": {"require_parameters": True},
        }
        return urllib.request.Request(
            self.config.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key or ''}", "Content-Type": "application/json"},
            method="POST",
        )

    def diagnostics(self) -> dict[str, Any]:
        """Sanitized provider provenance; never includes credentials or bodies."""

        return {
            "provider": self.provider,
            "provider_version": self.version,
            "endpoint": self.config.endpoint,
            "model": self.model,
            "last_served_model": self.last_model,
            "requests": self.request_count,
            "request_cap": self.config.max_requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
            "cost_cap_usd": self.config.max_cost_usd,
            "consecutive_failures": self.consecutive_failures,
            "failure_classes": dict(self.failure_classes),
            "last_error_message": self.last_error_message,
            "logprobs_requested": False,
        }

    def complete(self, prompt: str, *, seed: int) -> BehavioralResponse:
        if not self.api_key:
            return BehavioralResponse("", self.model, {}, 0.0, "unavailable", "missing_credentials",
                                      error_class="credentials_unavailable")
        request = self.build_request(prompt, seed=seed)
        last: BehavioralResponse | None = None
        for attempt in range(self.config.retries + 1):
            # Count each physical HTTP attempt, including retries, against the
            # request cap.  A logical completion can make more than one call.
            if attempt and self.request_count >= self.config.max_requests:
                return BehavioralResponse("", self.model, {}, 0.0, "unavailable", "request_cap_exhausted",
                                          error_class="request_cap")
            self._reserve()
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    body = json.loads(response.read().decode("utf-8"))
                choice = (body.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                usage = body.get("usage") if isinstance(body.get("usage"), Mapping) else {}
                raw_cost = usage.get("cost")
                cost = float(raw_cost) if isinstance(raw_cost, (int, float)) else 0.0
                self.cost_usd += cost
                self.input_tokens += int(usage.get("prompt_tokens") or 0)
                self.output_tokens += int(usage.get("completion_tokens") or 0)
                self.last_model = str(body.get("model") or self.model)
                self.consecutive_failures = 0
                request_id = str(body.get("id") or "") or None
                if self.cost_usd > self.config.max_cost_usd:
                    return BehavioralResponse("", self.last_model, usage, cost, "invalid", "cost_cap_exceeded",
                                              error_class="cost_cap", request_id=request_id)
                return BehavioralResponse(str(message.get("content") or ""), self.last_model, usage, cost,
                                          "complete", request_id=request_id)
            except urllib.error.HTTPError as exc:
                status_code = int(exc.code)
                error_class = classify_http_status(status_code)
                retry_after = _retry_after_seconds(exc)
                detail = ""
                try:
                    detail = sanitize_provider_message(exc.read().decode("utf-8", "replace"), self.api_key)
                except Exception:
                    detail = ""
                self.last_error_message = detail or None
                last = BehavioralResponse("", self.model, {}, 0.0, "unavailable",
                                          f"http_{status_code}_{error_class}", status_code=status_code,
                                          error_class=error_class, retry_after_seconds=retry_after,
                                          error_message=detail or None)
                self.failure_classes[error_class] += 1
                self.consecutive_failures += 1
                if not is_retryable_status(status_code) or attempt >= self.config.retries:
                    break
                time.sleep(min(retry_after if retry_after is not None else 2 ** attempt, 30.0))
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                self.last_error_message = type(exc).__name__
                last = BehavioralResponse("", self.model, {}, 0.0, "unavailable", type(exc).__name__,
                                          error_class="transport_error", error_message=type(exc).__name__)
                self.failure_classes["transport_error"] += 1
                self.consecutive_failures += 1
                if attempt >= self.config.retries:
                    break
                time.sleep(2 ** attempt)
        return last or BehavioralResponse("", self.model, {}, 0.0, "unavailable", "request_failed",
                                          error_class="transport_error")

    def respond(self, context: AgentContext) -> AgentResponse:
        prompt = json.dumps(treatment_prompt(context), sort_keys=True)
        result = self.complete(prompt, seed=provider_seed(
            context.instance_id, context.condition.value, context.turn, context.agent_id))
        match = re.search(r"answer\s*:\s*([^\n.]+)", result.text, flags=re.IGNORECASE)
        message_match = re.search(r"message\s*:\s*([^\n]+)", result.text, flags=re.IGNORECASE)
        return AgentResponse(
            answer=match.group(1).strip() if match else None,
            message=message_match.group(1).strip() if message_match else None,
            output_text=result.text,
            logprob_status="not_requested",
            failure_reason=None if result.status == "complete" else result.error_type,
            input_tokens=result.usage.get("prompt_tokens") if isinstance(result.usage, Mapping) else None,
            output_tokens=result.usage.get("completion_tokens") if isinstance(result.usage, Mapping) else None,
            cost_usd=result.cost_usd,
            prompt_hash=treatment_prompt_hash(context),
            prompt_schema_version=PROMPT_SCHEMA_VERSION,
        )


class BehavioralArtifactStore:
    """Append-only sanitized run summaries for resume and audit."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)

    def append(self, result: BatteryRunResult, *, extra: Mapping[str, Any] | None = None) -> None:
        record = {
            "schema_version": "behavioral-run-v1",
            "run_id": result.run_id,
            "pair_id": result.pair_id,
            "instance_id": result.instance_id,
            "family": result.family,
            "condition": result.condition.value,
            "seed": result.seed,
            "provider": result.provider,
            "provider_version": result.provider_version,
            "model_id": result.model_id,
            "status": result.status,
            "task_success": result.task_success,
            "invalid_agents": list(result.invalid_agents),
            "event_summary": dict(result.event_summary),
            "artifact_hash": hashlib.sha256(json.dumps(result.artifact, sort_keys=True).encode()).hexdigest(),
        }
        if extra:
            record.update(dict(extra))
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
        self.path.chmod(0o600)

    def records(self) -> list[dict[str, Any]]:
        """Replay sanitized records for resume and audit; skips malformed lines."""

        if not self.path.is_file():
            return []
        records: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                records.append(value)
        return records

    def completed_instance_ids(self, *, protocol_key: str | None = None,
                               condition: str | None = None) -> set[str]:
        """Instances with a resumable valid execution already on disk.

        When ``protocol_key`` or ``condition`` is given, records that do not
        match are ignored so old/new runs and different conditions are never
        mixed during resume.
        """

        return {str(record["instance_id"]) for record in self.records()
                if record.get("valid_execution") is True and record.get("instance_id")
                and (protocol_key is None or record.get("protocol_key") == protocol_key)
                and (condition is None or record.get("condition") == condition)}

    def append_oracle(self, record: Mapping[str, Any]) -> None:
        """Append a separately-schemed ORACLE manipulation-check record."""

        payload = {"schema_version": ORACLE_SCHEMA_VERSION, "condition": ORACLE_CONDITION, **dict(record)}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, allow_nan=False) + "\n")
        self.path.chmod(0o600)

    def oracle_completed_instance_ids(self, *, protocol_key: str | None = None) -> set[str]:
        """Instances with a resumable valid ORACLE record for the given protocol."""

        return {str(record["instance_id"]) for record in self.records()
                if record.get("schema_version") == ORACLE_SCHEMA_VERSION
                and record.get("valid_execution") is True and record.get("instance_id")
                and (protocol_key is None or record.get("protocol_key") == protocol_key)}


def audit_retained_pilot(root: Path | str) -> dict[str, Any]:
    """Audit retained C0/C1/C2 artifacts without rewriting raw evidence."""

    root = Path(root).expanduser().resolve()
    rows: list[dict[str, Any]] = []
    for seed_dir in sorted(root.glob("s[0-9][0-9][0-9][0-9]")):
        for condition_dir in sorted(seed_dir.glob("C[012]")):
            def load(name: str) -> Mapping[str, Any]:
                try:
                    value = json.loads((condition_dir / name).read_text(encoding="utf-8"))
                    return value if isinstance(value, Mapping) else {}
                except (OSError, ValueError, json.JSONDecodeError):
                    return {}
            index = load("index.json")
            metrics = load("artifacts/metrics.json")
            board_path = condition_dir / "artifacts/board_events.jsonl"
            if board_path.is_file():
                with board_path.open(encoding="utf-8") as handle:
                    board_events = sum(1 for _ in handle)
            else:
                board_events = 0
            agents = index.get("agents", {}) if isinstance(index.get("agents", {}), Mapping) else {}
            execution_valid = index.get("status") == "completed" and bool(agents) and all(
                isinstance(value, Mapping) and value.get("status") == "completed" for value in agents.values()
            )
            checker_valid = bool(metrics.get("submitted_agents")) and bool(metrics.get("validator_outcomes"))
            rows.append({
                "seed": seed_dir.name,
                "condition": condition_dir.name,
                "execution_valid": execution_valid,
                "checker_valid": checker_valid,
                "behavioral_valid": execution_valid and checker_valid,
                "entropy_valid": False,
                "run_status": index.get("status", "missing"),
                "agent_statuses": sorted({value.get("status") for value in agents.values() if isinstance(value, Mapping)}),
                "submitted_agents": metrics.get("submitted_agents", 0),
                "validator_count": len(metrics.get("validator_outcomes", [])) if isinstance(metrics.get("validator_outcomes", []), list) else 0,
                "board_event_count": board_events,
            })
    valid_behavior = sum(row["behavioral_valid"] for row in rows)
    return {
        "audit_version": "retained-pilot-behavioral-v1",
        "audited_scope": "legacy_task1_c0_c1_c2",
        "six_family_iso_full_comm_status": "unknown_not_located_in_retained_artifact_roots",
        "root": str(root),
        "run_count": len(rows),
        "behavioral_valid_count": valid_behavior,
        "entropy_valid_count": sum(row["entropy_valid"] for row in rows),
        "salvage_decision": "salvage" if valid_behavior else "no_salvage_behavioral_execution_invalid",
        "rows": rows,
        "raw_evidence_rewritten": False,
    }


def run_behavioral_screen(instances: Sequence[FamilyInstance], provider: OpenRouterBehavioralProvider,
                          artifact_store: BehavioralArtifactStore) -> dict[str, Any]:
    runner = TwoAgentBatteryRunner(turns=2, token_budget=provider.config.max_tokens, finalizing_agent="A")
    results: list[BatteryRunResult] = []
    attempted_instances = 0
    baseline_requests_per_instance = len(BatteryCondition) * runner.turns * 2
    for instance in instances:
        # Stop at a triplet boundary rather than recording an avoidably invalid
        # triplet when the remaining hard cap cannot fund its base requests.
        if provider.request_count + baseline_requests_per_instance > provider.config.max_requests:
            break
        attempted_instances += 1
        pair = f"behavioral-{instance.instance_id}"
        for condition in BatteryCondition:
            result = runner.run_condition(instance, condition, provider, pair_id=pair,
                                          run_id=f"{pair}-{condition.value}")
            artifact_store.append(result)
            results.append(result)
    return {
        "screen_version": BEHAVIORAL_VERSION,
        "run_count": len(results),
        "valid_run_count": sum(result.status == "completed" for result in results),
        "invalid_run_count": sum(result.status != "completed" for result in results),
        "provider_requests": provider.request_count,
        "planned_instances": len(instances),
        "attempted_instances": attempted_instances,
        "stopped_before_instance_for_request_cap": attempted_instances < len(instances),
        "cost_usd": provider.cost_usd,
        "report": report_from_battery(instances, results),
    }


FROZEN_FULL_GATE_MANIFEST: tuple[tuple[str, int, ReasoningComplexity], ...] = (
    ("hypothesis", 15000, ReasoningComplexity.LOW),
    ("hypothesis", 15001, ReasoningComplexity.LOW),
    ("hypothesis", 15002, ReasoningComplexity.MEDIUM),
    ("hypothesis", 15003, ReasoningComplexity.MEDIUM),
    ("reference", 15004, ReasoningComplexity.LOW),
    ("reference", 15005, ReasoningComplexity.LOW),
    ("reference", 15006, ReasoningComplexity.MEDIUM),
    ("reference", 15007, ReasoningComplexity.MEDIUM),
)


def frozen_full_gate_instances() -> list[FamilyInstance]:
    """Rebuild the eight frozen FULL-only gate instances from the seed manifest.

    The manifest is reconstructed from the committed full-gate instance IDs
    (hypothesis-00003a98..9b, reference-00003a9c..9f) and the #145 plan of
    hypothesis/reference x low/medium x 2 seeds under measured regime N.
    """

    return [generate_instance(family, seed, DependenceRegime.N, complexity)
            for family, seed, complexity in FROZEN_FULL_GATE_MANIFEST]


def select_frozen_instances(*, families: str | None = None,
                            complexities: str | None = None) -> list[FamilyInstance]:
    """Filter the frozen manifest by family and/or complexity for bounded cells."""

    instances = frozen_full_gate_instances()
    if families:
        wanted = {name.strip() for name in families.split(",") if name.strip()}
        instances = [instance for instance in instances if instance.family in wanted]
    if complexities:
        wanted = {name.strip() for name in complexities.split(",") if name.strip()}
        instances = [instance for instance in instances if instance.complexity.value in wanted]
    return instances


PAIRED_CELLS: tuple[tuple[str, ReasoningComplexity], ...] = (
    ("hypothesis", ReasoningComplexity.LOW),
    ("hypothesis", ReasoningComplexity.MEDIUM),
    ("reference", ReasoningComplexity.LOW),
    ("reference", ReasoningComplexity.MEDIUM),
)

FAMILY_ORDER: tuple[str, ...] = ("hypothesis", "reference", "planning", "poetry", "legal", "lexicon")
DEFAULT_PAIRED_FAMILIES: tuple[str, ...] = ("hypothesis", "reference")
PAIRED_COMPLEXITIES: tuple[ReasoningComplexity, ...] = (ReasoningComplexity.LOW, ReasoningComplexity.MEDIUM)
_FAMILY_SEED_BASE = {"hypothesis": 16000, "reference": 16200, "planning": 16400,
                     "poetry": 16600, "legal": 16800, "lexicon": 17000}
_COMPLEXITY_SEED_OFFSET = {ReasoningComplexity.LOW: 0, ReasoningComplexity.MEDIUM: 100}


def extended_paired_instances(seeds_per_cell: int = 5, *,
                              families: Sequence[str] | None = None) -> list[FamilyInstance]:
    """Build an equal-n paired screen over family x complexity cells.

    Seeds are independent of the eight frozen gate instances and unique per
    cell. The default families keep the previously frozen hypothesis/reference
    seeds unchanged; other families get distinct offsets.
    """

    if seeds_per_cell <= 0:
        raise ValueError("seeds_per_cell must be positive")
    selected = tuple(families) if families else DEFAULT_PAIRED_FAMILIES
    for family in selected:
        if family not in _FAMILY_SEED_BASE:
            raise ValueError(f"unknown task family: {family}")
    instances: list[FamilyInstance] = []
    for family in selected:
        base = _FAMILY_SEED_BASE[family]
        for complexity in PAIRED_COMPLEXITIES:
            offset = _COMPLEXITY_SEED_OFFSET[complexity]
            for replicate in range(seeds_per_cell):
                instances.append(generate_instance(family, base + offset + replicate,
                                                   DependenceRegime.N, complexity))
    return instances


AUDIT_COMPLEXITIES: tuple[ReasoningComplexity, ...] = tuple(ReasoningComplexity)


def channel_audit_manifest(seeds_per_cell: int = 3,
                           families: Sequence[str] | None = None) -> list[FamilyInstance]:
    """Offline audit manifest spanning every family x complexity at regime N."""

    if seeds_per_cell <= 0:
        raise ValueError("seeds_per_cell must be positive")
    selected = tuple(families) if families else FAMILY_ORDER
    for family in selected:
        if family not in _FAMILY_SEED_BASE:
            raise ValueError(f"unknown task family: {family}")
    instances: list[FamilyInstance] = []
    for family in selected:
        base = _FAMILY_SEED_BASE[family]
        for index, complexity in enumerate(AUDIT_COMPLEXITIES):
            for replicate in range(seeds_per_cell):
                instances.append(generate_instance(family, base + index * 100 + replicate,
                                                   DependenceRegime.N, complexity))
    return instances


def build_screen_instances(*, scheme: str | None = None, seeds_per_cell: int | None = None,
                           families: str | None = None, complexities: str | None = None,
                           ) -> list[FamilyInstance]:
    """Select live-screen instances; ``stage2`` consumes the frozen preregistration block."""

    if scheme == "stage2":
        from .preregistration import stage2_instances  # lazy import avoids a cycle
        instances = stage2_instances(seeds_per_cell or 2)
        if families:
            wanted = {name.strip() for name in families.split(",") if name.strip()}
            instances = [instance for instance in instances if instance.family in wanted]
        if complexities:
            wanted = {name.strip() for name in complexities.split(",") if name.strip()}
            instances = [instance for instance in instances if instance.complexity.value in wanted]
        return instances
    if scheme == "frozen" or (scheme is None and not seeds_per_cell):
        return select_frozen_instances(families=families, complexities=complexities)
    extended_families = (tuple(name.strip() for name in families.split(",") if name.strip())
                         if families else None)
    return extended_paired_instances(seeds_per_cell or 5, families=extended_families)


class _RecordingProvider:
    """Capture sanitized AgentResponses while delegating to the live provider."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.provider = getattr(inner, "provider", "unknown")
        self.version = getattr(inner, "version", "unknown")
        self.responses: dict[tuple[str, str, int], AgentResponse] = {}

    @property
    def model(self) -> str:
        return getattr(self.inner, "model", "unknown")

    def respond(self, context: AgentContext) -> AgentResponse:
        response = self.inner.respond(context)
        self.responses[(context.run_id, context.agent_id, context.turn)] = response
        return response


def _classify_run(*, status: str, output_present: bool, answer_parsed: bool,
                  checker_valid: bool, accepted: bool) -> str:
    if status != "completed":
        return "provider_execution_failure"
    if not output_present:
        return "invalid_output_empty"
    if not answer_parsed:
        return "invalid_output_unparsed"
    if not checker_valid:
        return "missing_checker_evidence"
    return "success" if accepted else "valid_wrong_answer"


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval for a binomial proportion."""

    if total <= 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = (z / denominator) * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return (max(0.0, center - half), min(1.0, center + half))


def mcnemar_exact_p(left_only: int, right_only: int) -> float:
    """Two-sided exact McNemar test on the discordant pairs."""

    discordant = left_only + right_only
    if discordant == 0:
        return 1.0
    k = min(left_only, right_only)
    tail = sum(math.comb(discordant, i) for i in range(k + 1)) / (2 ** discordant)
    return min(1.0, 2 * tail)


def mcnemar_midp(left_only: int, right_only: int) -> float:
    """Two-sided mid-p McNemar test; less conservative than the exact test."""

    discordant = left_only + right_only
    if discordant == 0:
        return 1.0
    k = min(left_only, right_only)
    lower = sum(math.comb(discordant, i) for i in range(k)) / (2 ** discordant)
    observed = math.comb(discordant, k) / (2 ** discordant)
    return min(1.0, 2 * (lower + 0.5 * observed))


def paired_difference_ci(both_success: int, left_only: int, right_only: int, both_fail: int,
                         z: float = 1.96) -> tuple[float, float] | None:
    """Newcombe method-10 interval for the difference of paired proportions.

    Built from the Wilson intervals of the two marginals plus the discordant-pair
    correction; robust for small matched samples where a Wald interval misbehaves.
    """

    n = both_success + left_only + right_only + both_fail
    if n <= 0:
        return None
    p_left = (both_success + left_only) / n
    p_right = (both_success + right_only) / n
    difference = p_right - p_left
    left_interval = wilson_interval(both_success + left_only, n, z)
    right_interval = wilson_interval(both_success + right_only, n, z)
    if left_interval is None or right_interval is None:
        return None
    l1, u1 = left_interval
    l2, u2 = right_interval
    denominator = math.sqrt((both_success + left_only) * (both_fail + right_only)
                            * (both_success + right_only) * (left_only + both_fail))
    phi = (both_success * both_fail - left_only * right_only) / denominator if denominator > 0 else 0.0
    lower = difference - math.sqrt(max(0.0, (p_right - l2) ** 2
                                       - 2 * phi * (p_right - l2) * (u1 - p_left)
                                       + (u1 - p_left) ** 2))
    upper = difference + math.sqrt(max(0.0, (u2 - p_right) ** 2
                                       - 2 * phi * (u2 - p_right) * (p_left - l1)
                                       + (p_left - l1) ** 2))
    return (max(-1.0, lower), min(1.0, upper))


def paired_contrast(records: Iterable[Mapping[str, Any]], left_condition: str,
                    right_condition: str) -> dict[str, Any] | None:
    """Matched-by-instance contrast of two conditions with Wilson/McNemar inference."""

    def succeeded(record: Mapping[str, Any]) -> bool:
        if "checker_accepted" in record:
            return bool(record["checker_accepted"])
        return bool(record.get("task_success"))

    outcomes: dict[str, dict[str, bool]] = {}
    duplicates: list[tuple[str, str]] = []
    for record in records:
        instance_id = record.get("instance_id")
        condition = record.get("condition")
        if instance_id is None or condition not in {left_condition, right_condition}:
            continue
        if record.get("valid_execution") is not True:
            continue
        bucket = outcomes.setdefault(str(instance_id), {})
        if str(condition) in bucket:
            duplicates.append((str(instance_id), str(condition)))
        bucket[str(condition)] = succeeded(record)
    if duplicates:
        raise ValueError(
            "ambiguous duplicate valid rows for "
            f"{sorted(set(duplicates))[:5]} ({len(duplicates)} total); "
            "reject mixed or repeated inputs instead of silently taking the last row")
    a = b = c = d = 0
    for pair in outcomes.values():
        if left_condition not in pair or right_condition not in pair:
            continue
        left, right = pair[left_condition], pair[right_condition]
        if left and right:
            a += 1
        elif left and not right:
            b += 1
        elif not left and right:
            c += 1
        else:
            d += 1
    n = a + b + c + d
    if n == 0:
        return None
    p_left = (a + b) / n
    p_right = (a + c) / n
    difference = p_right - p_left
    standard_error = math.sqrt(b + c - (b - c) ** 2 / n) / n
    return {
        "left_condition": left_condition,
        "right_condition": right_condition,
        "n_pairs": n,
        "both_success": a,
        "left_only": b,
        "right_only": c,
        "both_fail": d,
        "p_left": p_left,
        "p_right": p_right,
        "difference": difference,
        "wilson_left": wilson_interval(a + b, n),
        "wilson_right": wilson_interval(a + c, n),
        "paired_wald_ci": (difference - 1.96 * standard_error, difference + 1.96 * standard_error),
        "newcombe_ci": paired_difference_ci(a, b, c, d),
        "mcnemar_exact_p": mcnemar_exact_p(b, c),
        "mcnemar_midp_p": mcnemar_midp(b, c),
    }


def _pairwise_contrasts(rows: Sequence[Mapping[str, Any]],
                        conditions: Sequence[BatteryCondition]) -> dict[str, Any]:
    contrasts: dict[str, Any] = {}
    for index, left in enumerate(conditions):
        for right in conditions[index + 1:]:
            contrast = paired_contrast(rows, left.value, right.value)
            if contrast is not None:
                contrasts[f"{left.value}->{right.value}"] = contrast
    return contrasts


ANALYSIS_PAIRS: tuple[tuple[str, str], ...] = (
    ("ISO", "FULL"), ("ISO", "COMM"), ("FULL", "COMM"), ("FULL", ORACLE_CONDITION),
)


def pair_attempt_state(records: Iterable[Mapping[str, Any]], instances: Sequence[FamilyInstance],
                       conditions: Sequence[str] = ("ISO", "FULL", "COMM"), *,
                       condition_requests: Mapping[str, int] | None = None) -> dict[str, Any]:
    """Offline partial-attempt plan: which instance/condition pairs are still missing.

    A plain rerun would append duplicate valid rows, which paired analysis
    rejects; this planner lets a resume run only the missing conditions and
    count the remaining request budget.
    """

    valid = set()
    invalid_present = set()
    for record in records:
        instance_id = record.get("instance_id")
        condition = record.get("condition")
        if instance_id is None or condition is None:
            continue
        key = (str(instance_id), str(condition))
        if record.get("valid_execution") is True:
            valid.add(key)
        else:
            invalid_present.add(key)
    rows: list[dict[str, Any]] = []
    for instance in instances:
        for condition in conditions:
            key = (instance.instance_id, condition)
            status = "valid" if key in valid else ("invalid_present" if key in invalid_present else "missing")
            rows.append({"instance_id": instance.instance_id, "condition": condition, "status": status})
    complete_instances = sum(1 for instance in instances
                             if all((instance.instance_id, condition) in valid for condition in conditions))
    resume_pairs = [(row["instance_id"], row["condition"]) for row in rows if row["status"] != "valid"]
    resume_requests = None
    if condition_requests is not None:
        resume_requests = sum(int(condition_requests.get(condition, 0)) for _, condition in resume_pairs)
    return {
        "rows": rows,
        "planned_pairs": len(rows),
        "valid_pairs": sum(row["status"] == "valid" for row in rows),
        "invalid_pairs": sum(row["status"] == "invalid_present" for row in rows),
        "missing_pairs": sum(row["status"] == "missing" for row in rows),
        "complete_instances": complete_instances,
        "incomplete_instances": len(instances) - complete_instances,
        "resume_pairs": resume_pairs,
        "resume_requests": resume_requests,
    }


def paired_contrasts_by_protocol(records: Iterable[Mapping[str, Any]],
                                 pairs: Sequence[tuple[str, str]] = ANALYSIS_PAIRS) -> dict[str, Any]:
    """Segregate records by protocol boundary before computing paired contrasts.

    Records from a different generator, treatment schema or model configuration
    are never pooled together.
    """

    groups: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        key = str(record.get("protocol_key") or "legacy_unknown_protocol")
        groups.setdefault(key, []).append(record)
    report: dict[str, Any] = {}
    for key, group in sorted(groups.items()):
        contrasts: dict[str, Any] = {}
        for left, right in pairs:
            try:
                contrast = paired_contrast(group, left, right)
            except ValueError as exc:
                contrasts[f"{left}->{right}"] = {"ambiguous": True, "error": str(exc)}
                continue
            if contrast is not None:
                contrasts[f"{left}->{right}"] = contrast
        report[key] = {"record_count": len(group), "paired_contrasts": contrasts}
    return report


def run_oracle_probe(instances: Sequence[FamilyInstance], provider: Any,
                     artifact_store: BehavioralArtifactStore, *, max_runs: int = 8,
                     finalizing_agent: str = "A", resume: bool = True) -> dict[str, Any]:
    """Pooled-private oracle: the finalizer sees the union of both agents' clues.

    This bounds what the COMM channel could achieve in principle, separating
    information availability from the agents' actual message exchange.
    """

    if max_runs <= 0:
        raise ValueError("max_runs must be positive")
    selected = list(instances)[:max_runs]
    protocol_key = current_protocol_key(getattr(provider, "model", "unknown"),
                                        getattr(provider, "version", "unknown"),
                                        turns=1, max_tokens=provider.config.max_tokens,
                                        finalizing_agent=finalizing_agent)
    completed = artifact_store.oracle_completed_instance_ids(protocol_key=protocol_key) if resume else set()
    pending = [instance for instance in selected if instance.instance_id not in completed]
    rows: list[dict[str, Any]] = []
    stop_reason: str | None = None
    consecutive_http_failures = 0
    for instance in pending:
        if provider.request_count + request_budget(ORACLE_CONDITION, 1) > provider.config.max_requests:
            stop_reason = "request_cap"
            break
        if provider.cost_usd >= provider.config.max_cost_usd:
            stop_reason = "cost_cap"
            break
        # ORACLE matches the FULL treatment's information and prompt schema as
        # closely as possible, but carries its own condition identity.
        view = instance.agent_view(finalizing_agent, "FULL")
        view = {**view, "is_finalizer": True, "finalizing_agent": finalizing_agent}
        run_id = f"oracle-{instance.instance_id}"
        context = AgentContext(run_id, instance.instance_id, finalizing_agent, DiagnosticCondition.ORACLE,
                               0, view, (), PROMPT_SCHEMA_VERSION, provider.config.max_tokens)
        try:
            response = provider.respond(context)
        except Exception as exc:  # preserve invalid ORACLE runs for denominator reporting
            invalid_row = {
                "instance_id": instance.instance_id, "family": instance.family,
                "complexity": instance.complexity.value,
                "regime": instance.assignment.regime.value if instance.assignment.regime else None,
                "condition": ORACLE_CONDITION, "classification": "provider_execution_failure",
                "valid_execution": False, "checker_accepted": False,
                "failure_reason": type(exc).__name__,
                "generator_version": GENERATOR_VERSION,
                "prompt_schema_version": PROMPT_SCHEMA_VERSION,
                "protocol_key": protocol_key, "prompt_hash": None,
                "channel": instance.channel_analysis(),
            }
            artifact_store.append_oracle(invalid_row)
            rows.append(invalid_row)
            consecutive_http_failures += 1
            if consecutive_http_failures >= provider.config.max_consecutive_failures:
                stop_reason = "repeated_http_failure"
                break
            continue
        output_present = bool(response.output_text.strip())
        answer = response.answer
        answer_parsed = answer is not None and str(answer).strip() != ""
        checker_result = instance.validate(answer or "")
        checker_valid = answer_parsed and isinstance(checker_result, Mapping) and "accepted" in checker_result
        accepted = bool(checker_result.get("accepted", False))
        status = "completed" if not response.failure_reason else "invalid"
        classification = _classify_run(status=status, output_present=output_present,
                                       answer_parsed=answer_parsed, checker_valid=checker_valid,
                                       accepted=accepted)
        valid_execution = classification in {"success", "valid_wrong_answer"}
        if valid_execution:
            failure_reason = None
        elif response.failure_reason:
            failure_reason = response.failure_reason
        else:
            failure_reason = classification
        if response.failure_reason and response.failure_reason.startswith("http_"):
            consecutive_http_failures += 1
        else:
            consecutive_http_failures = 0
        row = {
            "instance_id": instance.instance_id, "family": instance.family,
            "complexity": instance.complexity.value,
            "regime": instance.assignment.regime.value if instance.assignment.regime else None,
            "condition": ORACLE_CONDITION, "classification": classification,
            "valid_execution": valid_execution, "checker_accepted": accepted,
            "failure_reason": failure_reason,
            "generator_version": GENERATOR_VERSION,
            "prompt_schema_version": response.prompt_schema_version or PROMPT_SCHEMA_VERSION,
            "protocol_key": protocol_key,
            "prompt_hash": response.prompt_hash,
            "channel": instance.channel_analysis(),
        }
        artifact_store.append_oracle(row)
        rows.append(row)
        if consecutive_http_failures >= provider.config.max_consecutive_failures:
            stop_reason = "repeated_http_failure"
            break

    valid_rows = [row for row in rows if row["valid_execution"]]
    successful = [row for row in valid_rows if row["checker_accepted"]]
    cells: list[dict[str, Any]] = []
    for key in sorted({(row["family"], row["complexity"]) for row in rows}):
        cell_rows = [row for row in rows if (row["family"], row["complexity"]) == key]
        cell_valid = [row for row in cell_rows if row["valid_execution"]]
        cells.append({
            "family": key[0], "complexity": key[1],
            "valid_denominator": len(cell_valid), "successes": sum(row["checker_accepted"] for row in cell_valid),
            "p_success": (sum(row["checker_accepted"] for row in cell_valid) / len(cell_valid)
                          if cell_valid else None),
        })
    if not rows:
        stop_reason = stop_reason or "no_instances_attempted"
    elif stop_reason is None:
        stop_reason = "completed_planned_runs"
    return {
        "probe_version": "pooled-private-oracle-v1",
        "oracle_schema_version": ORACLE_SCHEMA_VERSION,
        "condition": ORACLE_CONDITION,
        "separate_from_primary_conditions": True,
        "stage": "T1a-pooled-oracle",
        "endpoint": provider.config.endpoint,
        "model": provider.model,
        "finalizing_agent": finalizing_agent,
        "finalizer_policy": FINALIZER_POLICY,
        "planned_instances": len(selected),
        "attempted_instances": len(rows),
        "valid_runs": len(valid_rows),
        "invalid_runs": len(rows) - len(valid_rows),
        "successes": len(successful),
        "oracle_success_rate": len(successful) / len(valid_rows) if valid_rows else None,
        "cells": cells,
        "requests_made": provider.request_count,
        "requests_per_instance": request_budget(ORACLE_CONDITION, 1),
        "cost_usd": provider.cost_usd,
        "stop_reason": stop_reason,
        "provider_diagnostics": provider.diagnostics() if hasattr(provider, "diagnostics") else {},
        "p_oracle_minus_full_note": "report p_ORACLE - p_FULL from the paired analysis, not here",
        "raw_responses_retained": False,
        "credentials_retained": False,
    }


def _replay_finalizer_context(instance: FamilyInstance, provider: Any, *, visible_text: str | None,
                              finalizing_agent: str, turn: int, run_id: str) -> AgentContext:
    peer = "B" if finalizing_agent == "A" else "A"
    view = {**instance.agent_view(finalizing_agent, "ISO"),
            "is_finalizer": True, "finalizing_agent": finalizing_agent}
    visible = () if visible_text is None else (
        {"message_id": "m-replay", "author": peer, "text": visible_text},)
    return AgentContext(run_id, instance.instance_id, finalizing_agent, BatteryCondition.COMM,
                        turn, view, visible, PROMPT_SCHEMA_VERSION, provider.config.max_tokens)


def matched_replay_uptake(instance: FamilyInstance, provider: Any, *, real_message: str,
                          placebo_message: str | None = None, finalizing_agent: str = "A",
                          turn: int = 0) -> dict[str, Any]:
    """Counterfactual replay for causal uptake.

    Runs the finalizer with the real peer message and again with a matched
    placebo (or no message), and reports causal uptake only if the accepted
    answer depends on the real message. Correlation alone is not causal.
    """

    real_response = provider.respond(_replay_finalizer_context(
        instance, provider, visible_text=real_message, finalizing_agent=finalizing_agent,
        turn=turn, run_id=f"replay-real-{instance.instance_id}"))
    placebo_response = provider.respond(_replay_finalizer_context(
        instance, provider, visible_text=placebo_message, finalizing_agent=finalizing_agent,
        turn=turn, run_id=f"replay-placebo-{instance.instance_id}"))
    real_accepted = bool(instance.validate(real_response.answer or "").get("accepted", False))
    placebo_accepted = bool(instance.validate(placebo_response.answer or "").get("accepted", False))
    return {
        "instance_id": instance.instance_id,
        "real_message": real_message,
        "placebo_message": placebo_message,
        "real_answer": real_response.answer,
        "placebo_answer": placebo_response.answer,
        "real_accepted": real_accepted,
        "placebo_accepted": placebo_accepted,
        "answer_changed": real_response.answer != placebo_response.answer,
        "causal_uptake": bool(real_accepted and not placebo_accepted),
        "evidence_class": "matched_replay_counterfactual",
    }


def run_full_gate(instances: Sequence[FamilyInstance], provider: Any,
                  artifact_store: BehavioralArtifactStore, *, max_runs: int = 8,
                  finalizing_agent: str = "A", resume: bool = True) -> dict[str, Any]:
    """Run the bounded FULL-only execution gate with explicit stop rules."""

    if max_runs <= 0:
        raise ValueError("max_runs must be positive")
    runner = TwoAgentBatteryRunner(turns=1, token_budget=provider.config.max_tokens,
                                   finalizing_agent=finalizing_agent)
    selected = list(instances)[:max_runs]
    protocol_key = current_protocol_key(getattr(provider, "model", "unknown"),
                                        getattr(provider, "version", "unknown"),
                                        turns=runner.turns, max_tokens=provider.config.max_tokens,
                                        finalizing_agent=finalizing_agent)
    completed = artifact_store.completed_instance_ids(
        protocol_key=protocol_key, condition=BatteryCondition.FULL.value) if resume else set()
    pending = [instance for instance in selected if instance.instance_id not in completed]
    requests_per_run = request_budget(BatteryCondition.FULL.value, runner.turns)
    rows: list[dict[str, Any]] = []
    stop_reason: str | None = None
    consecutive_http_failures = 0

    for instance in pending:
        if provider.request_count + requests_per_run > provider.config.max_requests:
            stop_reason = "request_cap"
            break
        if provider.cost_usd >= provider.config.max_cost_usd:
            stop_reason = "cost_cap"
            break
        recorder = _RecordingProvider(provider)
        run_id = f"full-gate-{instance.instance_id}"
        result = runner.run_condition(instance, BatteryCondition.FULL, recorder,
                                      pair_id=run_id, run_id=run_id, finalizer_only=True)
        final_response = recorder.responses.get((run_id, finalizing_agent, 0))
        output_present = bool(final_response is not None and final_response.output_text.strip())
        answer = result.submitted_answers.get(finalizing_agent)
        answer_parsed = answer is not None and str(answer).strip() != ""
        checker_result = instance.validate(answer or "")
        checker_valid = answer_parsed and isinstance(checker_result, Mapping) and "accepted" in checker_result
        accepted = bool(checker_result.get("accepted", False))
        classification = _classify_run(status=result.status, output_present=output_present,
                                       answer_parsed=answer_parsed, checker_valid=checker_valid,
                                       accepted=accepted)
        valid_execution = classification in {"success", "valid_wrong_answer"}
        if valid_execution:
            failure_reason = None
        elif final_response is not None and final_response.failure_reason:
            failure_reason = final_response.failure_reason
        else:
            failure_reason = classification
        finalizer_failure = final_response.failure_reason if final_response else None
        if finalizer_failure and finalizer_failure.startswith("http_"):
            consecutive_http_failures += 1
        else:
            consecutive_http_failures = 0
        row = {
            "run_id": run_id,
            "instance_id": instance.instance_id,
            "family": instance.family,
            "seed": instance.seed,
            "complexity": instance.complexity.value,
            "regime": instance.assignment.regime.value if instance.assignment.regime else None,
            "condition": BatteryCondition.FULL.value,
            "status": result.status,
            "classification": classification,
            "valid_execution": valid_execution,
            "output_present": output_present,
            "answer_parsed": answer_parsed,
            "checker_valid": checker_valid,
            "checker_accepted": accepted,
            "failure_reason": failure_reason,
            "invalid_agents": list(result.invalid_agents),
            "provider": result.provider,
            "provider_version": result.provider_version,
            "model_id": result.model_id,
            "input_tokens": final_response.input_tokens if final_response else None,
            "output_tokens": final_response.output_tokens if final_response else None,
            "cost_usd": float(final_response.cost_usd) if final_response else 0.0,
            "artifact_hash": hashlib.sha256(json.dumps(result.artifact, sort_keys=True).encode()).hexdigest(),
        }
        artifact_store.append(result, extra={"classification": classification,
                                             "valid_execution": valid_execution,
                                             "failure_reason": failure_reason,
                                             **_protocol_extra(provider, turns=runner.turns,
                                                               max_tokens=provider.config.max_tokens,
                                                               finalizing_agent=finalizing_agent)})
        rows.append(row)
        if consecutive_http_failures >= provider.config.max_consecutive_failures:
            stop_reason = "repeated_http_failure"
            break
        if classification == "missing_checker_evidence":
            stop_reason = "missing_checker_evidence"
            break

    valid_rows = [row for row in rows if row["valid_execution"]]
    successful = [row for row in valid_rows if row["checker_accepted"]]
    checker_valid_runs = sum(row["checker_valid"] for row in rows)
    model_output_runs = sum(row["output_present"] for row in rows)
    failure_reasons = Counter(row["failure_reason"] for row in rows if row["failure_reason"])
    classifications = Counter(row["classification"] for row in rows)

    failure_classes = dict(provider.diagnostics().get("failure_classes", {})) if hasattr(provider, "diagnostics") else {}
    credential_blocked = any(name in {"auth_error", "credentials_unavailable", "payment_required"}
                             for name in failure_classes)
    if not rows:
        blocking_issue = "no_instances_attempted"
    elif credential_blocked:
        blocking_issue = "provider_credentials_unavailable"
    elif not valid_rows and model_output_runs == 0:
        blocking_issue = "provider_http_failure"
    elif not valid_rows:
        blocking_issue = "output_parse_or_checker_floor"
    else:
        blocking_issue = None

    cells: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["family"], row["complexity"])
        cell = cells.setdefault(key, {
            "family": row["family"], "complexity": row["complexity"], "regime": row["regime"],
            "planned": 0, "attempted": 0, "valid": 0, "successes": 0,
        })
        cell["attempted"] += 1
        cell["valid"] += int(row["valid_execution"])
        cell["successes"] += int(row["valid_execution"] and row["checker_accepted"])
    for instance in selected:
        key = (instance.family, instance.complexity.value)
        if key in cells:
            cells[key]["planned"] += 1

    if not rows:
        stop_reason = stop_reason or "no_instances_attempted"
    elif stop_reason is None:
        stop_reason = "completed_planned_runs"

    report = {
        "gate_version": FULL_GATE_VERSION,
        "stage": "T1a-full-only-gate",
        "condition": BatteryCondition.FULL.value,
        "endpoint": provider.config.endpoint,
        "model": provider.model,
        "provider": getattr(provider, "provider", "unknown"),
        "provider_version": getattr(provider, "version", "unknown"),
        "finalizing_agent": finalizing_agent,
        "finalizer_policy": FINALIZER_POLICY,
        "turns": runner.turns,
        "requests_per_run": requests_per_run,
        "request_cap": provider.config.max_requests,
        "rate_floor_seconds": provider.config.min_interval_seconds,
        "cost_cap_usd": provider.config.max_cost_usd,
        "planned_runs": len(selected),
        "resumed_runs": len(completed & {instance.instance_id for instance in selected}),
        "attempted_runs": len(rows),
        "valid_runs": len(valid_rows),
        "invalid_runs": len(rows) - len(valid_rows),
        "valid_denominator": len(valid_rows),
        "successes": len(successful),
        "valid_success_rate": len(successful) / len(valid_rows) if valid_rows else None,
        "valid_run_rate": len(valid_rows) / len(rows) if rows else None,
        "model_output_runs": model_output_runs,
        "checker_valid_runs": checker_valid_runs,
        "requests_made": provider.request_count,
        "input_tokens": sum(row["input_tokens"] or 0 for row in rows),
        "output_tokens": sum(row["output_tokens"] or 0 for row in rows),
        "cost_usd": sum(row["cost_usd"] for row in rows),
        "failure_reasons": dict(failure_reasons),
        "classification_counts": dict(classifications),
        "cells": [cells[key] for key in sorted(cells)],
        "stop_reason": stop_reason,
        "frozen_instance_ids": [instance.instance_id for instance in selected],
        "frozen_manifest_hash": hashlib.sha256(
            json.dumps([instance.instance_id for instance in selected], sort_keys=True).encode()).hexdigest(),
        "paired_screen_ready": bool(valid_rows) and checker_valid_runs > 0,
        "solvability_conclusion": "valid_denominator_present" if valid_rows else "not_available",
        "provider_credential_blocked": credential_blocked,
        "blocking_issue": blocking_issue,
        "provider_diagnostics": provider.diagnostics() if hasattr(provider, "diagnostics") else {},
        "raw_responses_retained": False,
        "credentials_retained": False,
        "next_decision": (next_decision_for(blocking_issue)),
    }
    return report


def run_paired_screen(instances: Sequence[FamilyInstance], provider: Any,
                      artifact_store: BehavioralArtifactStore, *, max_runs: int = 8,
                      finalizing_agent: str = "A", turns: int | None = None,
                      condition_turns: Mapping[str, int] | None = None,
                      conditions: Sequence[BatteryCondition] | None = None,
                      resume_records: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Run bounded paired ISO/FULL/COMM triplets with per-run validity classes.

    ``resume_records`` skips any (instance, condition) that already has a valid
    record, so a partial attempt can be completed without appending duplicates.
    """

    if max_runs <= 0:
        raise ValueError("max_runs must be positive")
    selected_conditions = tuple(conditions) if conditions else tuple(BatteryCondition)
    if not selected_conditions:
        raise ValueError("at least one condition is required")
    schedule = resolve_condition_turns(selected_conditions, turns=turns, condition_turns=condition_turns)
    runners = {condition.value: TwoAgentBatteryRunner(
        turns=schedule[condition.value], token_budget=provider.config.max_tokens,
        finalizing_agent=finalizing_agent) for condition in selected_conditions}
    selected = list(instances)[:max_runs]
    completed: set[tuple[str, str]] = {
        (str(record.get("instance_id")), str(record.get("condition")))
        for record in (resume_records or ()) if record.get("valid_execution") is True
    }
    requests_per_instance = sum(request_budget(condition.value, schedule[condition.value])
                                for condition in selected_conditions)
    rows: list[dict[str, Any]] = []
    resumed_runs = 0
    stop_reason: str | None = None
    consecutive_http_failures = 0
    stop = False
    for instance in selected:
        pending_conditions = [condition for condition in selected_conditions
                              if (instance.instance_id, condition.value) not in completed]
        resumed_runs += len(selected_conditions) - len(pending_conditions)
        if not pending_conditions:
            continue
        pending_requests = sum(request_budget(condition.value, schedule[condition.value])
                               for condition in pending_conditions)
        if provider.request_count + pending_requests > provider.config.max_requests:
            stop_reason = "request_cap"
            break
        if provider.cost_usd >= provider.config.max_cost_usd:
            stop_reason = "cost_cap"
            break
        pair = f"paired-{instance.instance_id}"
        for condition in pending_conditions:
            condition_turn_count = schedule[condition.value]
            runner = runners[condition.value]
            recorder = _RecordingProvider(provider)
            run_id = f"paired-{condition.value}-{instance.instance_id}"
            result = runner.run_condition(instance, condition, recorder, pair_id=pair, run_id=run_id,
                                          finalizer_only=condition.value in BOARD_FREE_CONDITIONS)
            final_response = recorder.responses.get((run_id, finalizing_agent, condition_turn_count - 1))
            output_present = bool(final_response is not None and final_response.output_text.strip())
            answer = result.submitted_answers.get(finalizing_agent)
            answer_parsed = answer is not None and str(answer).strip() != ""
            checker_result = instance.validate(answer or "")
            checker_valid = answer_parsed and isinstance(checker_result, Mapping) and "accepted" in checker_result
            accepted = bool(checker_result.get("accepted", False))
            classification = _classify_run(status=result.status, output_present=output_present,
                                           answer_parsed=answer_parsed, checker_valid=checker_valid,
                                           accepted=accepted)
            valid_execution = classification in {"success", "valid_wrong_answer"}
            if valid_execution:
                failure_reason = None
            elif final_response is not None and final_response.failure_reason:
                failure_reason = final_response.failure_reason
            else:
                failure_reason = classification
            summary = result.event_summary
            structural = instance.channel_analysis()
            finalizer_failure = final_response.failure_reason if final_response else None
            if finalizer_failure and finalizer_failure.startswith("http_"):
                consecutive_http_failures += 1
            else:
                consecutive_http_failures = 0
            row = {
                "run_id": run_id, "pair_id": pair, "instance_id": instance.instance_id,
                "family": instance.family, "seed": instance.seed,
                "complexity": instance.complexity.value,
                "regime": instance.assignment.regime.value if instance.assignment.regime else None,
                "condition": condition.value, "status": result.status,
                "classification": classification, "valid_execution": valid_execution,
                "output_present": output_present, "answer_parsed": answer_parsed,
                "checker_valid": checker_valid, "checker_accepted": accepted,
                "failure_reason": failure_reason,
                "message_count": int(summary.get("message_count", 0)),
                "transmitted_bits": float(summary.get("transmitted_bits", 0.0)),
                "communication_tokens": int(summary.get("communication_tokens", 0)),
                "post_read_correlation_count": int(summary.get("post_read_correlation_count", 0)),
                "post_read_correlated_bits": float(summary.get("post_read_correlated_bits", 0.0)),
                "rejected_write_count": int(summary.get("rejected_write_count", 0)),
                "voluntary_board_use": bool(summary.get("message_count", 0)),
                "finalizer_needs_peer": bool(structural["finalizer_needs_peer"]),
                "both_agents_needed": bool(structural["both_agents_needed"]),
                "channel_complete": bool(structural["channel_complete"]),
                "provider": result.provider, "provider_version": result.provider_version,
                "model_id": result.model_id,
                "input_tokens": final_response.input_tokens if final_response else None,
                "output_tokens": final_response.output_tokens if final_response else None,
                "cost_usd": float(final_response.cost_usd) if final_response else 0.0,
                "artifact_hash": hashlib.sha256(json.dumps(result.artifact, sort_keys=True).encode()).hexdigest(),
            }
            artifact_store.append(result, extra={"classification": classification,
                                                 "valid_execution": valid_execution,
                                                 "failure_reason": failure_reason,
                                                 **_protocol_extra(provider, turns=schedule,
                                                                   max_tokens=provider.config.max_tokens,
                                                                   finalizing_agent=finalizing_agent)})
            rows.append(row)
            if consecutive_http_failures >= provider.config.max_consecutive_failures:
                stop_reason = "repeated_http_failure"
                stop = True
                break
        if stop:
            break

    valid_rows = [row for row in rows if row["valid_execution"]]
    successful = [row for row in valid_rows if row["checker_accepted"]]
    by_condition: dict[str, Any] = {}
    for condition in selected_conditions:
        condition_rows = [row for row in rows if row["condition"] == condition.value]
        condition_valid = [row for row in condition_rows if row["valid_execution"]]
        condition_success = [row for row in condition_valid if row["checker_accepted"]]
        by_condition[condition.value] = {
            "attempted": len(condition_rows), "valid": len(condition_valid),
            "invalid": len(condition_rows) - len(condition_valid),
            "successes": len(condition_success),
            "valid_success_rate": len(condition_success) / len(condition_valid) if condition_valid else None,
            "messages": sum(row["message_count"] for row in condition_rows),
            "transmitted_bits": sum(row["transmitted_bits"] for row in condition_rows),
            "communication_tokens": sum(row["communication_tokens"] for row in condition_rows),
            "post_read_correlation_count": sum(row["post_read_correlation_count"] for row in condition_rows),
            "post_read_correlated_bits": sum(row["post_read_correlated_bits"] for row in condition_rows),
        }
    cell_keys = sorted({(row["family"], row["complexity"]) for row in rows})
    cells: list[dict[str, Any]] = []
    for family, complexity in cell_keys:
        cell_rows = [row for row in rows if row["family"] == family and row["complexity"] == complexity]
        probabilities: dict[str, float | None] = {}
        denominators: dict[str, int] = {}
        success_counts: dict[str, int] = {}
        for condition in selected_conditions:
            condition_valid = [row for row in cell_rows if row["condition"] == condition.value and row["valid_execution"]]
            probabilities[condition.value] = (sum(row["checker_accepted"] for row in condition_valid) / len(condition_valid)
                                              if condition_valid else None)
            denominators[condition.value] = len(condition_valid)
            success_counts[condition.value] = sum(row["checker_accepted"] for row in condition_valid)
        cells.append({
            "family": family, "complexity": complexity,
            "p_success": probabilities, "successes": success_counts,
            "valid_denominators": denominators,
            "c_need_unclipped": (probabilities.get("FULL", 0.0) - probabilities.get("ISO", 0.0)
                                 if probabilities.get("FULL") is not None and probabilities.get("ISO") is not None else None),
            "paired_contrasts": _pairwise_contrasts(cell_rows, selected_conditions),
        })

    failure_reasons = Counter(row["failure_reason"] for row in rows if row["failure_reason"])
    classifications = Counter(row["classification"] for row in rows)
    failure_classes = dict(provider.diagnostics().get("failure_classes", {})) if hasattr(provider, "diagnostics") else {}
    credential_blocked = any(name in {"auth_error", "credentials_unavailable", "payment_required"}
                             for name in failure_classes)
    all_denominators = all(by_condition[condition.value]["valid"] > 0 for condition in selected_conditions)
    if not rows:
        stop_reason = stop_reason or "no_instances_attempted"
    elif stop_reason is None:
        stop_reason = "completed_planned_runs"
    by_instance: dict[str, dict[str, Any]] = {}
    for row in rows:
        by_instance.setdefault(row["instance_id"], row)
    structural_necessity = {
        "definition": "A finalizer needs the peer when its own clue-consistent set is larger than the pooled/joint set",
        "instances": len(by_instance),
        "finalizer_needs_peer_count": sum(row["finalizer_needs_peer"] for row in by_instance.values()),
        "both_agents_needed_count": sum(row["both_agents_needed"] for row in by_instance.values()),
        "channel_complete_count": sum(row["channel_complete"] for row in by_instance.values()),
    }
    comm_rows = [row for row in rows if row["condition"] == BatteryCondition.COMM.value]
    voluntary_comm = {
        "condition": BatteryCondition.COMM.value,
        "attempted": len(comm_rows),
        "used_board_count": sum(row["voluntary_board_use"] for row in comm_rows),
        "rejected_write_count": sum(row["rejected_write_count"] for row in comm_rows),
        "post_read_correlation_count": sum(row["post_read_correlation_count"] for row in comm_rows),
        "causal_claim": "none: post-read accepted answers are correlation evidence only, not causal uptake",
    }
    p_iso = by_condition.get("ISO", {}).get("valid_success_rate")
    p_full = by_condition.get("FULL", {}).get("valid_success_rate")
    p_comm = by_condition.get("COMM", {}).get("valid_success_rate")
    c_need = (p_full - p_iso) if (p_full is not None and p_iso is not None) else None
    comm_recovery = (None if c_need is None or c_need < MINIMUM_EFFECTIVE_C_NEED or p_comm is None
                     else (p_comm - p_iso) / c_need)
    induced_arm = {
        "status": "not_run",
        "note": "required-claim or silence-penalty diagnostics must use a distinct INDUCED condition "
                "and are never pooled with voluntary COMM",
    }
    return {
        "screen_version": "paired-iso-full-comm-v1",
        "stage": "T1a-paired-screen",
        "endpoint": provider.config.endpoint,
        "model": provider.model,
        "provider": getattr(provider, "provider", "unknown"),
        "provider_version": getattr(provider, "version", "unknown"),
        "finalizing_agent": finalizing_agent, "turns": turns,
        "condition_turns": schedule,
        "minimum_effective_c_need": MINIMUM_EFFECTIVE_C_NEED,
        "finalizer_policy": FINALIZER_POLICY,
        "requests_per_instance": requests_per_instance,
        "request_cap": provider.config.max_requests,
        "rate_floor_seconds": provider.config.min_interval_seconds,
        "cost_cap_usd": provider.config.max_cost_usd,
        "planned_instances": len(selected),
        "attempted_instances": len({row["instance_id"] for row in rows}),
        "attempted_runs": len(rows),
        "resumed_runs": resumed_runs,
        "valid_runs": len(valid_rows),
        "invalid_runs": len(rows) - len(valid_rows),
        "successes": len(successful),
        "requests_made": provider.request_count,
        "input_tokens": sum(row["input_tokens"] or 0 for row in rows),
        "output_tokens": sum(row["output_tokens"] or 0 for row in rows),
        "cost_usd": sum(row["cost_usd"] for row in rows),
        "by_condition": by_condition,
        "cells": cells,
        "structural_necessity": structural_necessity,
        "voluntary_comm": voluntary_comm,
        "comm_recovery_eta": comm_recovery,
        "induced_arm": induced_arm,
        "paired_contrasts": _pairwise_contrasts(rows, selected_conditions),
        "failure_reasons": dict(failure_reasons),
        "classification_counts": dict(classifications),
        "stop_reason": stop_reason,
        "frozen_instance_ids": [instance.instance_id for instance in selected],
        "frozen_manifest_hash": hashlib.sha256(
            json.dumps([instance.instance_id for instance in selected], sort_keys=True).encode()).hexdigest(),
        "all_condition_denominators_present": all_denominators,
        "paired_screen_ready": bool(valid_rows) and all_denominators,
        "provider_credential_blocked": credential_blocked,
        "provider_diagnostics": provider.diagnostics() if hasattr(provider, "diagnostics") else {},
        "raw_responses_retained": False,
        "credentials_retained": False,
        "next_decision": ("review by_condition/cells before any T3 entropy work"
                          if all_denominators else "denominators incomplete; do not advance"),
    }


def next_decision_for(blocking_issue: str | None) -> str:
    if blocking_issue is None:
        return "review cells before paired ISO/FULL/COMM"
    if blocking_issue == "provider_credentials_unavailable":
        return "restore a valid provider credential, then re-run the FULL gate; no floor-effect inference"
    if blocking_issue == "provider_http_failure":
        return "diagnose provider HTTP routing before interpreting solvability"
    if blocking_issue == "output_parse_or_checker_floor":
        return "diagnose task/scorer/model floor effects before any paired spend"
    return "no valid denominator yet; do not launch paired screen"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T1a FULL-only gate and paired ISO/FULL/COMM screen")
    parser.add_argument("--mode", choices=["full-gate", "paired-screen", "oracle", "analyze", "audit-channels", "preregister", "treatment-schema", "attempt-state"], default="full-gate")
    parser.add_argument("--live", action="store_true", help="run the bounded live path (requires credentials)")
    parser.add_argument("--model", default=DEFAULT_FREE_MODEL)
    parser.add_argument("--endpoint", default=ENDPOINT)
    parser.add_argument("--max-runs", type=int)
    parser.add_argument("--max-tokens", type=int, default=96,
                        help="per-agent completion token budget; raise for reasoning models")
    parser.add_argument("--turns", type=int, help="uniform dialogue turns per agent for the paired screen")
    parser.add_argument("--condition-turns",
                        help="per-condition turns, e.g. 'ISO=1,FULL=1,COMM=2'; default is the frozen schedule")
    parser.add_argument("--conditions", help="comma-separated condition subset for the paired screen (default ISO,FULL,COMM)")
    parser.add_argument("--seeds-per-cell", type=int,
                        help="build an equal-n paired screen with this many seeds per family x complexity cell")
    parser.add_argument("--seed-scheme", choices=["frozen", "extended", "stage2"],
                        help="instance seed source; stage2 consumes the frozen preregistration manifest")
    parser.add_argument("--preregistration", type=Path,
                        help="locked preregistration to verify against before any live request")
    parser.add_argument("--resume-artifact", type=Path,
                        help="existing paired-screen artifact whose valid (instance, condition) pairs should be kept")
    parser.add_argument("--request-budget", type=int,
                        help="override the physical-request cap (e.g. remaining allowance on a resume)")
    parser.add_argument("--families", help="comma-separated family filter over the frozen manifest")
    parser.add_argument("--complexities", help="comma-separated complexity filter (low, medium, high)")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--diagnostic-output", type=Path)
    parser.add_argument("--inputs", help="comma-separated artifact jsonl files for --mode analyze")
    args = parser.parse_args(argv)
    if args.mode == "analyze":
        records: list[dict[str, Any]] = []
        for name in (args.inputs or "").split(","):
            path = Path(name.strip())
            if not path.is_file():
                parser.error(f"input not found: {path}")
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    records.append(json.loads(line))
        grouped = paired_contrasts_by_protocol(records)
        mixed = len(grouped) > 1
        single = next(iter(grouped.values()))["paired_contrasts"] if len(grouped) == 1 else {}
        report = {"mode": "analyze", "record_count": len(records),
                  "mixed_protocols": mixed, "protocol_groups": sorted(grouped),
                  "by_protocol": grouped, "paired_contrasts": single,
                  "raw_responses_retained": False, "credentials_retained": False}
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                                   encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
        return 0
    if args.mode == "attempt-state":
        attempt_records: list[dict[str, Any]] = []
        for name in (args.inputs or "").split(","):
            path = Path(name.strip())
            if not path.is_file():
                parser.error(f"input not found: {path}")
            attempt_records.extend(BehavioralArtifactStore(path).records())
        plan_instances = build_screen_instances(scheme=args.seed_scheme or "stage2",
                                                seeds_per_cell=args.seeds_per_cell)
        plan_schedule = resolve_condition_turns(tuple(BatteryCondition))
        condition_requests = {condition: request_budget(condition, plan_schedule[condition])
                              for condition in plan_schedule}
        state = pair_attempt_state(attempt_records, plan_instances, condition_requests=condition_requests)
        state["mode"] = "attempt-state"
        state["inputs"] = (args.inputs or "").split(",")
        state["condition_requests"] = condition_requests
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(state, indent=2, sort_keys=True, allow_nan=False) + "\n",
                                   encoding="utf-8")
        print(json.dumps({key: state[key] for key in (
            "mode", "planned_pairs", "valid_pairs", "invalid_pairs", "missing_pairs",
            "complete_instances", "incomplete_instances", "resume_requests")},
            indent=2, sort_keys=True, allow_nan=False))
        return 0
    if args.mode == "audit-channels":
        audit_families = (tuple(name.strip() for name in args.families.split(",") if name.strip())
                          if args.families else None)
        instances = channel_audit_manifest(args.seeds_per_cell or 3, families=audit_families)
        report = audit_channel_invariants(instances)
        report["mode"] = "audit-channels"
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                                   encoding="utf-8")
        print(json.dumps({key: report[key] for key in (
            "mode", "audit_version", "instance_count", "channel_complete_count",
            "channel_incomplete_ids", "both_agents_needed_count", "finalizer_needs_peer_count",
            "singleton_agent_ids", "unpartitioned_claims_ids", "declared_mismatch_count",
            "no_live_screen")},
            indent=2, sort_keys=True, allow_nan=False))
        return 0
    if args.mode == "preregister":
        prereg_families = (tuple(name.strip() for name in args.families.split(",") if name.strip())
                           if args.families else FAMILY_ORDER)
        instances = extended_paired_instances(args.seeds_per_cell or 20, families=prereg_families)
        report = preregistered_manifest(instances)
        report["mode"] = "preregister"
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                                   encoding="utf-8")
        print(json.dumps({key: report[key] for key in (
            "mode", "generator_version", "checker_version", "regime",
            "channel_complete_required", "instance_count", "manifest_hash", "no_live_screen")},
            indent=2, sort_keys=True, allow_nan=False))
        return 0
    if args.mode == "treatment-schema":
        report = treatment_schema()
        report["mode"] = "treatment-schema"
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                                   encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
        return 0
    instances = build_screen_instances(scheme=args.seed_scheme, seeds_per_cell=args.seeds_per_cell,
                                       families=args.families, complexities=args.complexities)
    max_runs = args.max_runs or len(instances)
    mode_stem = {"full-gate": "full-gate-repair", "paired-screen": "paired-screen",
                 "oracle": "oracle"}.get(args.mode, args.mode)
    base = f"{mode_stem}-{PROTOCOL_OUTPUT_STEM}"
    output = args.output or Path(f"runs/epic-126/{base}.jsonl")
    report_path = args.report or Path(f"runs/epic-126/{base}-report.json")
    diagnostic_path = args.diagnostic_output or Path(f"runs/epic-126/{base}-diagnostic.json")
    if not args.live:
        report = {
            "mode": args.mode, "status": "not_run", "model": args.model, "endpoint": args.endpoint,
            "planned_instances": len(instances),
            "frozen_instance_ids": [instance.instance_id for instance in instances],
            "cost_usd": 0.0, "raw_responses_retained": False, "credentials_retained": False,
            "next_step": "re-run with --live once a valid OPENROUTER_API_KEY is configured",
        }
    else:
        selected_conditions = tuple(BatteryCondition)
        if args.mode == "paired-screen" and args.conditions:
            try:
                selected_conditions = tuple(BatteryCondition[name.strip().upper()]
                                            for name in args.conditions.split(",") if name.strip())
            except KeyError:
                parser.error("--conditions must be a comma-separated subset of ISO,FULL,COMM")
            if not selected_conditions:
                parser.error("--conditions must not be empty")
        condition_turns = None
        if args.mode == "paired-screen" and args.condition_turns:
            try:
                condition_turns = {name.strip().upper(): int(value)
                                   for name, _, value in
                                   (item.partition("=") for item in args.condition_turns.split(","))
                                   if name.strip()}
            except ValueError:
                parser.error("--condition-turns must look like 'ISO=1,FULL=1,COMM=2'")
            if any(value <= 0 for value in condition_turns.values()):
                parser.error("--condition-turns values must be positive")
        schedule: dict[str, int] = {}
        if args.mode == "full-gate":
            max_requests = max_runs * 2
        elif args.mode == "oracle":
            max_requests = max_runs
        else:
            schedule = resolve_condition_turns(selected_conditions, turns=args.turns,
                                               condition_turns=condition_turns)
            max_requests = max_runs * sum(request_budget(condition.value, schedule[condition.value])
                                          for condition in selected_conditions)
        if args.request_budget:
            max_requests = args.request_budget
        config = BehavioralProviderConfig(model=args.model, endpoint=args.endpoint,
                                          max_requests=max_requests, max_cost_usd=20.0,
                                          min_interval_seconds=0.25, max_tokens=args.max_tokens)
        provider = OpenRouterBehavioralProvider(config)
        store = BehavioralArtifactStore(output)
        resume_records = None
        if args.resume_artifact:
            if not args.resume_artifact.is_file():
                parser.error(f"resume artifact not found: {args.resume_artifact}")
            resume_records = BehavioralArtifactStore(args.resume_artifact).records()
        if args.preregistration:
            from .preregistration import verify_against_preregistration
            document = json.loads(args.preregistration.read_text(encoding="utf-8"))
            verification = verify_against_preregistration(
                document,
                instance_ids=[instance.instance_id for instance in instances],
                model=provider.model, provider_version=getattr(provider, "version", "unknown"),
                condition_turns=schedule, max_tokens=provider.config.max_tokens,
                finalizing_agent=FINALIZER_AGENT)
            print(json.dumps({"mode": args.mode, "preregistration_verified": verification["ok"],
                              "expected_protocol_key": verification["expected_protocol_key"],
                              "actual_protocol_key": verification["actual_protocol_key"],
                              "errors": verification["errors"]}, indent=2, sort_keys=True))
            if not verification["ok"]:
                return 2
        if args.mode == "full-gate":
            report = run_full_gate(instances, provider, store, max_runs=max_runs)
        elif args.mode == "oracle":
            report = run_oracle_probe(instances, provider, store, max_runs=max_runs)
        else:
            report = run_paired_screen(instances, provider, store, max_runs=max_runs, turns=args.turns,
                                       condition_turns=condition_turns, conditions=selected_conditions,
                                       resume_records=resume_records)
        diagnostic = {
            "mode": args.mode, "stage": f"T1a-{args.mode}-diagnostic",
            "provider_diagnostics": report["provider_diagnostics"],
            "failure_reasons": report.get("failure_reasons", {}),
            "stop_reason": report["stop_reason"],
            "raw_responses_retained": False, "credentials_retained": False,
        }
        diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
        diagnostic_path.write_text(
            json.dumps(diagnostic, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    if not args.live:
        return 0
    return 0 if report["valid_runs"] else 1


def pressure_catalog(records: Iterable[Mapping[str, Any]], instances: Sequence[FamilyInstance]) -> dict[str, Any]:
    """Create a model-relative, uncertainty-aware catalog from sanitized runs."""

    by_id = {instance.instance_id: instance for instance in instances}
    outcomes: list[PairedOutcome] = []
    for record in records:
        instance = by_id.get(str(record.get("instance_id")))
        if instance is None:
            continue
        summary = record.get("event_summary", {}) if isinstance(record.get("event_summary", {}), Mapping) else {}
        outcomes.append(PairedOutcome(
            pair_id=str(record.get("pair_id")), family=instance.family, model=str(record.get("provider", "unknown")),
            condition=str(record.get("condition")), success=record.get("task_success"),
            valid=record.get("status") == "completed",
            transmitted_bits=float(summary.get("transmitted_bits", 0.0)),
            post_read_correlated_bits=float(summary.get("post_read_correlated_bits", 0.0)),
            communication_tokens=int(summary.get("communication_tokens", 0)),
            latency_seconds=summary.get("first_post_read_correlation_latency_seconds"),
        ))
    cells: dict[tuple[str, str, str], list[PairedOutcome]] = {}
    for item in instances:
        item_outcomes = [outcome for outcome in outcomes if outcome.pair_id == f"behavioral-{item.instance_id}"]
        cells.setdefault((item.family, item.assignment.regime.value if item.assignment.regime else "undefined", item.complexity.value), []).extend(item_outcomes)
    catalog_cells: list[dict[str, Any]] = []
    for (family, regime, complexity), cell_rows in sorted(cells.items()):
        probabilities: dict[str, float | None] = {}
        denominators: dict[str, int] = {}
        for condition in ("ISO", "FULL", "COMM"):
            valid = [row for row in cell_rows if row.condition == condition and row.valid and row.success is not None]
            probabilities[condition] = sum(bool(row.success) for row in valid) / len(valid) if valid else None
            denominators[condition] = len(valid)
        catalog_cells.append({
            "family": family, "regime": regime, "complexity": complexity,
            "d_idx_basis": "instance.assignment measured feasible-set reduction",
            "p_success": probabilities, "valid_denominators": denominators,
            "invalid_runs": {condition: sum(row.condition == condition and not row.valid for row in cell_rows) for condition in ("ISO", "FULL", "COMM")},
            "c_need_unclipped": probabilities["FULL"] - probabilities["ISO"] if probabilities["FULL"] is not None and probabilities["ISO"] is not None else None,
            "post_read_correlation_count": sum(row.post_read_correlated_bits > 0 for row in cell_rows if row.valid),
            "post_read_correlated_bits": sum(row.post_read_correlated_bits for row in cell_rows if row.valid),
            "transmitted_bits": sum(row.transmitted_bits for row in cell_rows if row.valid),
            "communication_tokens": sum(row.communication_tokens for row in cell_rows if row.valid),
            "status": "screening_only",
        })
    return {
        "catalog_version": "pressure-catalog-v1",
        "model_relative": True,
        "screening_only": True,
        "strict_r_h_n_monotonicity_required": False,
        "outcome_count": len(outcomes),
        "matched_metrics": paired_metrics(outcomes),
        "cells": catalog_cells,
        "next_decision": "review uncertainty and validity before expanding any cell",
    }


__all__ = [
    "BEHAVIORAL_VERSION", "FULL_GATE_VERSION", "FROZEN_FULL_GATE_MANIFEST",
    "PROMPT_SCHEMA_VERSION", "ORACLE_SCHEMA_VERSION", "ORACLE_CONDITION",
    "FINALIZER_POLICY", "FINALIZER_AGENT", "BOARD_FREE_CONDITIONS", "TREATMENT_PROMPT_FIELDS",
    "DiagnosticCondition", "provider_seed", "treatment_prompt", "treatment_prompt_hash",
    "request_budget", "treatment_schema", "current_protocol_key", "PROTOCOL_OUTPUT_STEM",
    "paired_contrasts_by_protocol", "ANALYSIS_PAIRS", "run_settings_hash",
    "matched_replay_uptake", "INDUCED_SCHEMA_VERSION", "pair_attempt_state",
    "sanitize_provider_message",
    "BehavioralArtifactStore", "BehavioralProviderConfig", "BehavioralResponse",
    "OpenRouterBehavioralProvider", "audit_retained_pilot", "classify_http_status",
    "frozen_full_gate_instances", "is_retryable_status", "main", "pressure_catalog",
    "run_behavioral_screen", "run_full_gate", "run_paired_screen", "select_frozen_instances",
    "PAIRED_CELLS", "extended_paired_instances", "wilson_interval", "mcnemar_exact_p",
    "mcnemar_midp", "paired_contrast", "paired_difference_ci", "run_oracle_probe",
    "build_screen_instances",
]


if __name__ == "__main__":
    raise SystemExit(main())
