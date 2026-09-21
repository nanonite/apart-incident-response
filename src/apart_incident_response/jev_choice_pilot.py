"""#158 — optional-board Ling-writer / Jev-receiver pilot runner (offline build).

Fail-closed: the preflight pins the locked #185 registration hash and refuses to
run without explicit ``--live`` plus a recorded approval reference. The runner
executes the registered per-condition turn schedule, never manufactures a real
board write, preserves optional silence, enforces the registered per-provider
physical-request partitions and cost cap at the transport boundary, journals
replay-ready provenance durably, and reports whether each of the six prompt forms
has eligible verified exposure. It does not start #159 replay.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Protocol, Sequence

from . import behavioral_discovery as bd
from . import jev_choice as jc
from . import jev_replay_preregistration as pr
from .communication_events import CommunicationEventLog
from .communication_protocol import DependenceRegime, ReasoningComplexity
from .jev_choice import JevChoiceAdapter, JevChoiceClient, load_jev_credentials
from .jev_choice_smoke import estimate_cost_usd
from . import task_families as tf


PILOT_VERSION = "jev-choice-pilot-v1"
ARMS = ("ISO", "FULL", "COMM", "COMM_CONTROL")
RECEIVER_AGENT = "A"
WRITER_AGENT = "B"
DEFAULT_REPORT = Path("runs/epic-126/jev-choice-pilot-report.json")
DEFAULT_JOURNAL = Path("runs/epic-126/jev-choice-pilot.jsonl")


class WriterClient(Protocol):
    provider: str
    max_physical_requests: int | None

    def write(self, context: Mapping[str, Any]) -> Mapping[str, Any]:
        ...


@dataclass(frozen=True)
class PilotCase:
    instance_id: str
    seed: int
    arm: str
    condition: str
    turns: int
    prompt_form_id: str
    request_hash: str
    writer_required: bool

    def to_dict(self) -> dict[str, Any]:
        return {"instance_id": self.instance_id, "seed": self.seed, "arm": self.arm,
                "condition": self.condition, "turns": self.turns,
                "prompt_form_id": self.prompt_form_id, "writer_required": self.writer_required}


@dataclass(frozen=True)
class PilotPlan:
    cases: tuple[PilotCase, ...]
    planned_requests: int
    request_cap: int
    jev_request_cap: int
    ling_request_cap: int
    cost_cap_usd: float
    input_token_ceiling: int
    worst_case_call_cost_usd: float
    registration_hash: str
    protocol_key: str
    model: str
    endpoint: str
    ling_model: str
    ling_endpoint: str
    ling_prompt_template: str
    ling_max_tokens: int
    ling_temperature: float

    def to_dict(self) -> dict[str, Any]:
        return {"planned_requests": self.planned_requests, "request_cap": self.request_cap,
                "jev_request_cap": self.jev_request_cap, "ling_request_cap": self.ling_request_cap,
                "cost_cap_usd": self.cost_cap_usd, "registration_hash": self.registration_hash,
                "protocol_key": self.protocol_key, "model": self.model, "endpoint": self.endpoint,
                "ling_model": self.ling_model, "ling_endpoint": self.ling_endpoint,
                "cases": [case.to_dict() for case in self.cases]}


def pilot_instances(*, seed_base: int = pr.JEV_REPLAY_SEED_BASE,
                    per_block: int = pr.JEV_REPLAY_PER_BLOCK) -> list[tf.FamilyInstance]:
    return [tf.generate_instance("planning", seed_base + replicate, DependenceRegime.N,
                                 ReasoningComplexity.LOW) for replicate in range(per_block)]


def build_pilot_plan(instances: Sequence[tf.FamilyInstance], registration: Mapping[str, Any],
                     receiver: JevChoiceAdapter) -> PilotPlan:
    cases: list[PilotCase] = []
    for instance in instances:
        pre_form = receiver.build_state(instance, RECEIVER_AGENT, "ISO")
        for arm in ARMS:
            condition = {"ISO": "ISO", "FULL": "FULL", "COMM": "COMM", "COMM_CONTROL": "COMM"}[arm]
            turns = pr.JEV_REPLAY_TURNS[condition]
            form_state = receiver.build_state(instance, RECEIVER_AGENT, condition)
            cases.append(PilotCase(instance.instance_id, instance.seed, arm, condition, turns,
                                   pre_form.request_hash,
                                   form_state.request_hash if arm in ("ISO", "FULL") else "",
                                   arm in ("COMM", "COMM_CONTROL")))
    caps = registration.get("caps", {})
    partition = caps.get("provider_partition") or {}
    ling = registration.get("ling_contract") or {}
    planned = sum(case.turns for case in cases)
    return PilotPlan(cases=tuple(cases), planned_requests=planned,
                     request_cap=int(caps.get("physical_requests", 0)),
                     jev_request_cap=int(partition.get("jev", pr.JEV_REPLAY_JEV_REQUEST_CAP)),
                     ling_request_cap=int(partition.get("ling", pr.JEV_REPLAY_LING_REQUEST_CAP)),
                     cost_cap_usd=float(caps.get("cost_cap_usd", 0.0)),
                     input_token_ceiling=int(caps.get("input_token_ceiling", 0)),
                     worst_case_call_cost_usd=estimate_cost_usd(int(caps.get("input_token_ceiling", 0))),
                     registration_hash=str(registration.get("preregistration_hash", "")),
                     protocol_key=str((registration.get("model_and_protocol") or {}).get("protocol_key", "")),
                     model=str((registration.get("model_and_protocol") or {}).get("model", "")),
                     endpoint=str((registration.get("model_and_protocol") or {}).get("endpoint", "")),
                     ling_model=str(ling.get("model", "")), ling_endpoint=str(ling.get("endpoint", "")),
                     ling_prompt_template=str(ling.get("prompt_template", "")),
                     ling_max_tokens=int(ling.get("max_tokens", 0)),
                     ling_temperature=float(ling.get("temperature", 0.0)))


def verify_pilot_preflight(plan: PilotPlan, registration: Mapping[str, Any], receiver: JevChoiceAdapter,
                           *, repo_root: Path, pinned_hash: str | None = None,
                           ling_key_present: bool | None = None, writer: Any | None = None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    provider = registration.get("model_and_protocol", {})
    registration_result = pr.verify_against_jev_replay_preregistration(
        registration, instance_ids=list((registration.get("frozen_forms") or {}).get("instance_ids", [])),
        model=plan.model, endpoint=plan.endpoint, protocol_key=plan.protocol_key,
        planned_requests=plan.planned_requests, repo_root=repo_root)
    check("registration_verifies", registration_result["ok"], registration_result["errors"])
    if pinned_hash is not None:
        check("pinned_hash_matches", plan.registration_hash == pinned_hash,
              {"plan": plan.registration_hash, "pinned": pinned_hash})
    check("protocol_key_is_jev", jc.is_jev_protocol_key(plan.protocol_key), plan.protocol_key)
    check("models_match", receiver.model == provider.get("model") and plan.model == provider.get("model"),
          plan.model)
    check("endpoint_matches", plan.endpoint == provider.get("endpoint"), plan.endpoint)
    check("planned_within_cap", plan.planned_requests <= plan.request_cap,
          {"planned": plan.planned_requests, "cap": plan.request_cap})
    check("partition_sums_to_cap", plan.jev_request_cap + plan.ling_request_cap == plan.request_cap,
          {"jev": plan.jev_request_cap, "ling": plan.ling_request_cap, "total": plan.request_cap})
    planned_jev = sum(1 for case in plan.cases)
    planned_ling = sum(1 for case in plan.cases if case.writer_required)
    check("planned_jev_within_partition", planned_jev <= plan.jev_request_cap,
          {"planned": planned_jev, "partition": plan.jev_request_cap})
    check("planned_ling_within_partition", planned_ling <= plan.ling_request_cap,
          {"planned": planned_ling, "partition": plan.ling_request_cap})
    check("cost_ceiling_within_cap",
          estimate_cost_usd(plan.input_token_ceiling * max(1, plan.request_cap)) <= plan.cost_cap_usd,
          plan.cost_cap_usd)
    check("forms_are_six", len({case.prompt_form_id for case in plan.cases}) == 6,
          len({case.prompt_form_id for case in plan.cases}))
    credentials = load_jev_credentials()
    check("jev_credentials_present", bool(credentials.present and credentials.shape_ok),
          credentials.redacted())
    ling_ok = bd._api_key() is not None if ling_key_present is None else bool(ling_key_present)
    check("ling_credentials_present", ling_ok, None)
    ling = registration.get("ling_contract") or {}
    check("ling_model_frozen", plan.ling_model and plan.ling_model == ling.get("model") == pr.LING_MODEL,
          plan.ling_model)
    check("ling_endpoint_frozen",
          plan.ling_endpoint and plan.ling_endpoint == ling.get("endpoint") == pr.LING_ENDPOINT,
          plan.ling_endpoint)
    check("ling_prompt_frozen", plan.ling_prompt_template == ling.get("prompt_template") == pr.LING_PROMPT_TEMPLATE,
          None)
    check("ling_decoding_frozen",
          plan.ling_max_tokens == ling.get("max_tokens") and plan.ling_temperature == ling.get("temperature"),
          {"max_tokens": plan.ling_max_tokens, "temperature": plan.ling_temperature})
    if writer is not None:
        check("writer_model_matches", getattr(writer, "model", None) == plan.ling_model,
              getattr(writer, "model", None))
        check("writer_endpoint_matches", getattr(writer, "endpoint", None) == plan.ling_endpoint,
              getattr(writer, "endpoint", None))
        check("writer_partition_enforced",
              getattr(writer, "max_physical_requests", None) == plan.ling_request_cap,
              getattr(writer, "max_physical_requests", None))
    return {"ok": all(item["ok"] for item in checks), "checks": checks,
            "failed": [item["check"] for item in checks if not item["ok"]],
            "registration_verification": registration_result}


def _blocked(plan: PilotPlan, reason: str, approval: str | None) -> dict[str, Any]:
    return {"mode": "jev-choice-pilot", "status": "blocked", "stop_reason": reason, "approval": approval,
            "planned_requests": plan.planned_requests, "attempted_requests": 0, "physical_attempts": 0,
            "max_physical_requests": plan.request_cap, "cases": [], "replay_started": False,
            "raw_response_retained": False, "credentials_retained": False}


def _instance_evidence(instance: tf.FamilyInstance, writer: str, candidate: Any,
                       message_id: str, exposure_id: str) -> tuple[str | None, list[dict[str, Any]],
                                                                    float | None, str]:
    if not candidate or not instance.holds_claim(writer, str(candidate)):
        return None, [], None, "rejected" if candidate else "silent"
    message = str(candidate)
    info = instance.information(RECEIVER_AGENT, message, message_id)
    log = CommunicationEventLog(f"pilot-{instance.instance_id}")
    log.board_write(writer, info, message_tokens=len(message.split()), receiver_id=RECEIVER_AGENT)
    log.peer_read(RECEIVER_AGENT, info, exposure_id=exposure_id)
    return message, [event.to_dict() for event in log.events], float(info.delta_i_bits), "real"


def execute_pilot(plan: PilotPlan, receiver: JevChoiceAdapter, writer: WriterClient,
                  verification: Mapping[str, Any], instances: Sequence[tf.FamilyInstance], *,
                  approval: str | None, pinned_hash: str | None = None,
                  journal_path: Path | None = None, sleep_fn: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Run the registered schedule. Fails closed without approval, preflight, or
    per-provider partitions enforced by both transports."""

    if not approval:
        return _blocked(plan, "missing_approval", approval)
    if not verification.get("ok"):
        return _blocked(plan, "preflight_failed", approval)
    if pinned_hash is not None and plan.registration_hash != pinned_hash:
        return _blocked(plan, "registration_hash_mismatch", approval)
    if plan.jev_request_cap + plan.ling_request_cap != plan.request_cap:
        return _blocked(plan, "partition_mismatch", approval)
    if getattr(receiver.client, "max_physical_requests", None) != plan.jev_request_cap:
        return _blocked(plan, "receiver_partition_not_enforced", approval)
    if getattr(writer, "max_physical_requests", None) != plan.ling_request_cap:
        return _blocked(plan, "writer_partition_not_enforced", approval)
    if journal_path is not None and journal_path.exists():
        return _blocked(plan, "output_exists", approval)

    by_id = {instance.instance_id: instance for instance in instances}
    report: dict[str, Any] = {
        "mode": "jev-choice-pilot", "status": "completed", "stop_reason": None, "approval": approval,
        "registration_hash": plan.registration_hash, "pinned_registration_hash": pinned_hash,
        "protocol_key": plan.protocol_key, "planned_requests": plan.planned_requests,
        "attempted_requests": 0, "physical_attempts": 0, "max_physical_requests": plan.request_cap,
        "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0, "cost_cap_usd": plan.cost_cap_usd,
        "by_arm": {arm: {"attempted": 0, "valid": 0, "invalid": 0, "real_writes": 0, "reads": 0}
                   for arm in ARMS},
        "by_form": {}, "resolved_models": [], "replay_started": False,
        "note": "does not start #159 replay; missing form exposure makes the pilot inconclusive",
        "cases": [], "raw_response_retained": False, "credentials_retained": False,
    }
    by_form: dict[str, dict[str, Any]] = {}

    handle = None
    if journal_path is not None:
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        handle = journal_path.open("x", encoding="utf-8")
    issued = 0

    def journal(row: dict[str, Any]) -> None:
        report["cases"].append(row)
        if handle is not None:
            handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    try:
        for case in plan.cases:
            attempts_so_far = int(getattr(receiver.client, "physical_attempts", 0) or 0) \
                + int(getattr(writer, "physical_attempts", 0) or 0)
            if (attempts_so_far + case.turns) * plan.worst_case_call_cost_usd > plan.cost_cap_usd:
                report["status"], report["stop_reason"] = "stopped", "cost_cap"
                break
            if issued > 0:
                sleep_fn(0.25)
            instance = by_id[case.instance_id]
            pre_state = receiver.build_state(instance, RECEIVER_AGENT, "ISO")
            message: str | None = None
            board_log: list[dict[str, Any]] = []
            i_m_bits: float | None = None
            write_status: str | None = None
            exposure_id: str | None = None
            turns_executed = 0
            writer_error: str | None = None
            if case.writer_required:
                turns_executed += 1
                try:
                    outcome = writer.write({"instance_id": instance.instance_id, "agent_id": WRITER_AGENT,
                                            "private_clues": list(instance.private_clues.get(WRITER_AGENT, ()))})
                    if case.arm == "COMM":
                        exposure_id = f"x-{instance.instance_id}"
                        message, board_log, i_m_bits, write_status = _instance_evidence(
                            instance, WRITER_AGENT, outcome.get("message"),
                            f"m-{instance.instance_id}", exposure_id)
                    else:
                        write_status = "control_no_write"
                except WriterError as exc:  # bounded sanitized writer failure
                    writer_error = exc.error_class
                    write_status = "writer_error"
                except Exception as exc:
                    writer_error = f"writer_{type(exc).__name__}"
                    write_status = "writer_error"
            visible = [{"text": jc_message(message)}] if message else []
            condition = case.condition
            state = receiver.build_state(instance, RECEIVER_AGENT, condition, visible_messages=visible)
            if case.arm in ("ISO", "FULL") and state.request_hash != case.request_hash:
                report["status"], report["stop_reason"] = "stopped", "request_hash_drift"
                break
            if writer_error is not None:
                journal({"instance_id": case.instance_id, "arm": case.arm, "condition": condition,
                         "status": "invalid", "error_class": writer_error,
                         "write_status": write_status, "turns_executed": turns_executed,
                         "prompt_form_id": case.prompt_form_id})
                report["status"], report["stop_reason"] = "stopped", writer_error
                break
            try:
                response, _ = receiver.complete_with_raw(state)
            except Exception as exc:  # defensive: durable invalid row, partial report
                error_class = f"jev_{type(exc).__name__}"
                journal({"instance_id": case.instance_id, "arm": case.arm, "condition": condition,
                         "status": "invalid", "error_class": error_class,
                         "write_status": write_status, "turns_executed": turns_executed,
                         "prompt_form_id": case.prompt_form_id})
                report["status"], report["stop_reason"] = "stopped", error_class
                break
            turns_executed += 1
            issued += 1
            report["attempted_requests"] += 1
            report["by_arm"][case.arm]["attempted"] += 1
            usage = dict(response.usage)
            report["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
            report["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
            report["estimated_cost_usd"] = estimate_cost_usd(report["input_tokens"])
            if response.model:
                report["resolved_models"] = sorted(set(report["resolved_models"]) | {response.model})
            valid = response.status == "complete"
            report["by_arm"][case.arm]["valid" if valid else "invalid"] += 1
            if write_status == "real":
                report["by_arm"][case.arm]["real_writes"] += 1
                report["by_arm"][case.arm]["reads"] += 1
            row = {
                "instance_id": case.instance_id, "arm": case.arm, "condition": condition,
                "turns_registered": case.turns, "turns_executed": turns_executed,
                "prompt_form_id": case.prompt_form_id, "request_hash": state.request_hash,
                "task": {"family": instance.family, "seed": instance.seed,
                         "regime": instance.assignment.regime.value,
                         "complexity": instance.complexity.value, "agent": RECEIVER_AGENT},
                "pre_read_state": dict(pre_state.state), "option_ids": sorted(instance.solutions),
                "target_id": instance.target,
                "feasible_set": sorted(instance.private_solutions[RECEIVER_AGENT]),
                "protocol_key": plan.protocol_key, "resolved_model": response.model,
                "status": response.status, "error_class": response.error_class,
                "selected_option_id": response.selected_option_id, "confidence": response.confidence,
                "probabilities": dict(response.probabilities), "usage": usage,
                "write_status": write_status, "claim": message,
                "message_id": f"m-{instance.instance_id}" if message else None,
                "exposure_id": exposure_id, "i_m_bits": i_m_bits, "board_log": board_log,
                "eligible_exposure": bool(write_status == "real"),
            }
            journal(row)
            form = by_form.setdefault(case.prompt_form_id,
                                      {"real_writes": 0, "reads": 0, "valid": 0, "eligible_exposure": False})
            form["valid"] += int(valid)
            if write_status == "real":
                form["real_writes"] += 1
                form["reads"] += 1
                form["eligible_exposure"] = True
            if not valid:
                report["status"], report["stop_reason"] = "stopped", response.error_class
                break
    finally:
        if handle is not None:
            handle.close()

    report["physical_attempts"] = int(getattr(receiver.client, "physical_attempts", 0) or 0) \
        + int(getattr(writer, "physical_attempts", 0) or 0)
    report["provider_attempts"] = {
        "jev": int(getattr(receiver.client, "physical_attempts", 0) or 0),
        "ling": int(getattr(writer, "physical_attempts", 0) or 0),
        "combined": int(getattr(receiver.client, "physical_attempts", 0) or 0)
        + int(getattr(writer, "physical_attempts", 0) or 0),
        "jev_partition": plan.jev_request_cap, "ling_partition": plan.ling_request_cap}
    report["by_form"] = dict(sorted(by_form.items()))
    missing = [form for form in {case.prompt_form_id for case in plan.cases}
               if not by_form.get(form, {}).get("eligible_exposure")]
    report["forms_with_eligible_exposure"] = sum(1 for form in by_form.values() if form["eligible_exposure"])
    report["forms_missing_exposure"] = sorted(missing)
    if report["status"] == "completed" and missing:
        report["status"] = "inconclusive"
        report["stop_reason"] = "missing_verified_exposure"
    report["replay_ready"] = not missing and report["status"] == "completed"
    return report


def jc_message(message: str | None) -> str:
    from . import jev_replay as jr
    return jr.serialize_message(message or "")


LING_RETRYABLE = jc.JEV_RETRYABLE_STATUSES


class WriterError(Exception):
    """Sanitized writer failure carrying only a bounded error class (no bodies)."""

    def __init__(self, error_class: str) -> None:
        self.error_class = str(error_class)
        super().__init__(self.error_class)


class LingWriterClient:
    """OpenRouter chat writer with the registered contract and retry policy; live only."""

    provider = "openrouter"

    def __init__(self, *, model: str = pr.LING_MODEL, endpoint: str = pr.LING_ENDPOINT,
                 api_key: str | None = None, timeout: float = 120.0,
                 max_retries: int = pr.LING_MAX_RETRIES, max_physical_requests: int | None = None,
                 sleep_fn: Callable[[float], None] = time.sleep) -> None:
        self.model = model
        self.endpoint = endpoint
        self.api_key = api_key if api_key is not None else bd._api_key()
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_physical_requests = max_physical_requests
        self.physical_attempts = 0
        self._sleep = sleep_fn

    def _backoff(self, attempt: int) -> float:
        return min(pr.LING_BACKOFF_INITIAL * (2 ** attempt), pr.LING_BACKOFF_MAX)

    def write(self, context: Mapping[str, Any]) -> Mapping[str, Any]:  # pragma: no cover - live only
        import urllib.error
        import urllib.request
        if not self.api_key:
            raise WriterError("writer_missing_credentials")
        clues = list(context.get("private_clues", ()))
        prompt = pr.LING_PROMPT_TEMPLATE.format(clues=clues)
        body = json.dumps({"model": self.model, "messages": [{"role": "user", "content": prompt}],
                           "max_tokens": pr.LING_MAX_TOKENS,
                           "temperature": pr.LING_TEMPERATURE}).encode()
        attempt = 0
        while True:
            if self.max_physical_requests is not None and self.physical_attempts >= self.max_physical_requests:
                raise WriterError("writer_physical_request_cap_exhausted")
            self.physical_attempts += 1
            request = urllib.request.Request(self.endpoint, data=body, method="POST",
                                             headers={"Authorization": f"Bearer {self.api_key}",
                                                      "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                status = int(exc.code)
                if status in LING_RETRYABLE and attempt < self.max_retries:
                    self._sleep(self._backoff(attempt))
                    attempt += 1
                    continue
                raise WriterError(f"writer_http_{status}_{bd.classify_http_status(status)}") from exc
            except OSError as exc:
                if attempt < self.max_retries:
                    self._sleep(self._backoff(attempt))
                    attempt += 1
                    continue
                raise WriterError(f"writer_network_{type(exc).__name__}") from exc
        text = str(payload["choices"][0]["message"]["content"])
        if "MESSAGE:" in text:
            return {"message": text.split("MESSAGE:", 1)[1].strip()}
        return {"message": None}


class _PreflightWriter:
    provider = "openrouter"
    max_physical_requests: int | None = None

    def write(self, context: Mapping[str, Any]) -> Mapping[str, Any]:  # pragma: no cover
        raise RuntimeError("preflight writer must never issue a request")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="#158 optional-board Ling-writer/Jev-receiver pilot")
    parser.add_argument("--registration", type=Path, default=pr.DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    parser.add_argument("--live", action="store_true", help="run live (requires --approval)")
    parser.add_argument("--approval", help="recorded reviewer approval reference; required for --live")
    args = parser.parse_args(argv)
    registration = json.loads(args.registration.read_text(encoding="utf-8"))
    instances = pilot_instances()
    receiver = JevChoiceAdapter(_PreflightWriter(), model=pr.JEV_REPLAY_MODEL)
    plan = build_pilot_plan(instances, registration, receiver)
    writer = LingWriterClient(max_physical_requests=plan.ling_request_cap)
    verification = verify_pilot_preflight(plan, registration, receiver,
                                          repo_root=Path(__file__).resolve().parents[2],
                                          pinned_hash=registration.get("preregistration_hash"),
                                          writer=writer)
    print(json.dumps({"mode": "jev-choice-pilot-preflight", "ok": verification["ok"],
                      "failed": verification["failed"], "plan": plan.to_dict(),
                      "checks": verification["checks"]}, indent=2, sort_keys=True, allow_nan=False))
    if not verification["ok"]:
        return 2
    if not args.live:
        return 0
    if not args.approval:
        print(json.dumps({"mode": "jev-choice-pilot", "status": "blocked",
                          "stop_reason": "missing_approval"}, indent=2, sort_keys=True))
        return 2
    live_receiver = JevChoiceAdapter(
        JevChoiceClient(model=pr.JEV_REPLAY_MODEL, max_physical_requests=plan.jev_request_cap),
        model=pr.JEV_REPLAY_MODEL)
    report = execute_pilot(plan, live_receiver, writer, verification, instances, approval=args.approval,
                           pinned_hash=registration.get("preregistration_hash"),
                           journal_path=args.journal)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PILOT_VERSION", "ARMS", "PilotCase", "PilotPlan", "pilot_instances", "build_pilot_plan",
    "verify_pilot_preflight", "execute_pilot", "LingWriterClient", "main",
]
