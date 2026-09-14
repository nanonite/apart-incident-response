"""Credential-safe behavioral discovery adapter and pilot audit.

This path intentionally does not request logprobs.  Behavioral validity and
entropy eligibility are independent fields, and the artifact store retains
only controller-side summaries and hashes.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Iterable, Mapping, Sequence

from .communication_analysis import PairedOutcome, paired_metrics
from .communication_protocol import BatteryCondition
from .communication_report import report_from_battery
from .communication_runner import AgentContext, AgentResponse, BatteryRunResult, TwoAgentBatteryRunner
from .reasoning_baseline import DEFAULT_FREE_MODEL, PROJECT_ENV_FILE, OPENROUTER_ENV_FILE
from .task_families import FamilyInstance


ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
BEHAVIORAL_VERSION = "behavioral-discovery-v1"


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
    max_requests: int = 144
    max_cost_usd: float = 20.0
    min_interval_seconds: float = 0.25
    retries: int = 1
    max_tokens: int = 96

    def __post_init__(self) -> None:
        if not self.model.endswith(":free"):
            raise ValueError("T1 adapter requires a :free model")
        if self.max_requests <= 0 or self.max_cost_usd < 0 or self.min_interval_seconds < 0:
            raise ValueError("invalid behavioral provider cap")


@dataclass(frozen=True)
class BehavioralResponse:
    text: str
    model: str
    usage: Mapping[str, Any]
    cost_usd: float
    status: str
    error_type: str | None = None


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

    def complete(self, prompt: str, *, seed: int) -> BehavioralResponse:
        self._reserve()
        if not self.api_key:
            return BehavioralResponse("", self.model, {}, 0.0, "unavailable", "missing_credentials")
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "max_tokens": self.config.max_tokens,
            "temperature": 0.0,
            "seed": seed,
            "provider": {"require_parameters": True},
        }
        request = urllib.request.Request(
            self.config.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        last_error: Exception | None = None
        for attempt in range(self.config.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    body = json.loads(response.read().decode("utf-8"))
                choice = (body.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                usage = body.get("usage") if isinstance(body.get("usage"), Mapping) else {}
                raw_cost = usage.get("cost")
                cost = float(raw_cost) if isinstance(raw_cost, (int, float)) else 0.0
                self.cost_usd += cost
                if self.cost_usd > self.config.max_cost_usd:
                    return BehavioralResponse("", self.model, usage, cost, "invalid", "cost_cap_exceeded")
                return BehavioralResponse(str(message.get("content") or ""), str(body.get("model") or self.model),
                                          usage, cost, "complete")
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in {408, 429, 500, 502, 503, 504} or attempt >= self.config.retries:
                    break
                time.sleep(2 ** attempt)
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= self.config.retries:
                    break
                time.sleep(2 ** attempt)
        return BehavioralResponse("", self.model, {}, 0.0, "unavailable", type(last_error).__name__ if last_error else "request_failed")

    def respond(self, context: AgentContext) -> AgentResponse:
        prompt = json.dumps({
            "instruction": context.task_view.get("task_instruction"),
            "family": context.task_view.get("family"),
            "condition": context.condition.value,
            "candidate_labels": context.task_view.get("candidate_labels", []),
            "joint_candidate_labels": context.task_view.get("joint_candidate_labels"),
            "private_clues": context.task_view.get("private_clues", []),
            "visible_messages": list(context.visible_messages),
        }, sort_keys=True)
        result = self.complete(prompt, seed=context.turn)
        match = re.search(r"answer\s*:\s*([^\n.]+)", result.text, flags=re.IGNORECASE)
        message_match = re.search(r"message\s*:\s*([^\n]+)", result.text, flags=re.IGNORECASE)
        return AgentResponse(
            answer=match.group(1).strip() if match else None,
            message=message_match.group(1).strip() if message_match else None,
            output_text=result.text,
            logprob_status="not_requested",
            failure_reason=None if result.status == "complete" else result.error_type,
        )


class BehavioralArtifactStore:
    """Append-only sanitized run summaries for resume and audit."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)

    def append(self, result: BatteryRunResult) -> None:
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
            "status": result.status,
            "task_success": result.task_success,
            "invalid_agents": list(result.invalid_agents),
            "event_summary": dict(result.event_summary),
            "artifact_hash": hashlib.sha256(json.dumps(result.artifact, sort_keys=True).encode()).hexdigest(),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
        self.path.chmod(0o600)


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
    runner = TwoAgentBatteryRunner(turns=1, token_budget=provider.config.max_tokens)
    results: list[BatteryRunResult] = []
    for instance in instances:
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
        "cost_usd": provider.cost_usd,
        "report": report_from_battery(instances, results),
    }


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
            valid=record.get("status") == "completed", useful_bits=float(summary.get("verified_useful_bits", 0.0)),
            communication_tokens=int(summary.get("communication_tokens", 0)),
            latency_seconds=summary.get("first_verified_use_latency_seconds"),
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
            "verified_use_count": sum(row.useful_bits > 0 for row in cell_rows if row.valid),
            "transmitted_bits": sum(row.useful_bits for row in cell_rows if row.valid),
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
    "BEHAVIORAL_VERSION", "BehavioralArtifactStore", "BehavioralProviderConfig",
    "BehavioralResponse", "OpenRouterBehavioralProvider", "audit_retained_pilot",
    "pressure_catalog", "run_behavioral_screen",
]
