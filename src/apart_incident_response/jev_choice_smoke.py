"""J3c — offline preflight and guarded tiny Jev Choice wire smoke (#178).

Offline by default: this module builds and verifies a reproducible preflight for
two frozen, leak-checked planning-low instances x {ISO, FULL} against
``jev-1.13.0`` under a 6-physical-request and $1 cap. No Jev API request is made
unless ``--live`` is passed together with an explicit ``--approval`` record, and
even then the preflight must pass and the transport must enforce the cap.

Live execution (only after separate reviewer approval) saves one curated,
credential-free golden request/response fixture and reports physical attempts,
estimated cost, invalidity and a continue/stop decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .jev_choice import (
    JEV_CHOICE_CODEC_VERSION,
    JEV_DEFAULT_MODEL,
    JEV_SYSTEMONE_ENDPOINT,
    ChoiceState,
    JevChoiceAdapter,
    JevChoiceClient,
    jev_choice_protocol_key,
    load_jev_credentials,
)
from .jev_protocol import audit_instance, planning_low_instances


JEV_SMOKE_MODEL = JEV_DEFAULT_MODEL
JEV_SMOKE_INSTANCE_COUNT = 2
JEV_SMOKE_CONDITIONS = ("ISO", "FULL")
JEV_SMOKE_MAX_PHYSICAL_REQUESTS = 6
JEV_SMOKE_MAX_RETRIES = 2
JEV_SMOKE_COST_CAP_USD = 1.0
#: Documented conservative per-request input-token ceiling used only to bound the
#: pre-live cost estimate ($42 / Btok = $0.042 / Mtok input; output is free).
JEV_SMOKE_INPUT_TOKEN_CEILING = 8192
JEV_INPUT_USD_PER_MTOK = 0.042

DEFAULT_MANIFEST = Path("runs/epic-126/jev-planning-low-manifest.json")
DEFAULT_OUTPUT = Path("runs/epic-126/jev-choice-wire-smoke.jsonl")
DEFAULT_REPORT = Path("runs/epic-126/jev-choice-wire-smoke-report.json")
DEFAULT_GOLDEN = Path("runs/epic-126/jev-choice-wire-smoke-golden.json")


def estimate_cost_usd(input_tokens: int) -> float:
    return round(max(0, int(input_tokens)) * JEV_INPUT_USD_PER_MTOK / 1_000_000, 9)


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SmokeCase:
    instance_id: str
    seed: int
    condition: str
    question_id: str
    option_ids: tuple[str, ...]
    request_hash: str
    state_hash: str
    clue_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "seed": self.seed,
            "condition": self.condition,
            "question_id": self.question_id,
            "option_count": len(self.option_ids),
            "request_hash": self.request_hash,
            "state_hash": self.state_hash,
            "clue_count": self.clue_count,
        }


@dataclass(frozen=True)
class SmokePlan:
    model: str
    endpoint: str
    protocol_key: str
    cases: tuple[SmokeCase, ...]
    manifest_hash: str | None
    manifest_instance_ids: tuple[str, ...]
    planned_physical_requests: int
    max_physical_requests: int
    max_retries: int
    cost_cap_usd: float
    input_token_ceiling: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "endpoint": self.endpoint,
            "protocol_key": self.protocol_key,
            "manifest_hash": self.manifest_hash,
            "planned_physical_requests": self.planned_physical_requests,
            "max_physical_requests": self.max_physical_requests,
            "max_retries": self.max_retries,
            "retry_reserve": max(0, self.max_physical_requests - self.planned_physical_requests),
            "cost_cap_usd": self.cost_cap_usd,
            "input_token_ceiling": self.input_token_ceiling,
            "estimated_cost_planned_usd": estimate_cost_usd(
                self.input_token_ceiling * max(1, self.planned_physical_requests)),
            "estimated_cost_ceiling_usd": estimate_cost_usd(
                self.input_token_ceiling * max(1, self.max_physical_requests)),
            "cases": [case.to_dict() for case in self.cases],
        }


def build_smoke_plan(instances: Sequence[Any], manifest: Mapping[str, Any], adapter: JevChoiceAdapter, *,
                     max_physical_requests: int = JEV_SMOKE_MAX_PHYSICAL_REQUESTS,
                     max_retries: int = JEV_SMOKE_MAX_RETRIES,
                     cost_cap_usd: float = JEV_SMOKE_COST_CAP_USD,
                     input_token_ceiling: int = JEV_SMOKE_INPUT_TOKEN_CEILING) -> SmokePlan:
    manifest_ids = tuple(str(instance_id) for instance_id in manifest.get("instance_ids", []))
    cases: list[SmokeCase] = []
    for instance in instances:
        for condition in JEV_SMOKE_CONDITIONS:
            state = adapter.build_state(instance, "A", condition)
            cases.append(SmokeCase(
                instance_id=instance.instance_id,
                seed=instance.seed,
                condition=condition,
                question_id=state.question_id,
                option_ids=tuple(option.option_id for option in state.options),
                request_hash=state.request_hash,
                state_hash=_canonical_hash(dict(state.state)),
                clue_count=len(state.state.get("clues", [])),
            ))
    endpoint = getattr(adapter.client, "endpoint", JEV_SYSTEMONE_ENDPOINT)
    key = jev_choice_protocol_key(model=adapter.model, endpoint=endpoint,
                                  max_retries=getattr(adapter.client, "max_retries", max_retries),
                                  instructions=adapter.instructions, question_id=adapter.question_id)
    return SmokePlan(model=adapter.model, endpoint=endpoint, protocol_key=key, cases=tuple(cases),
                     manifest_hash=manifest.get("manifest_hash"), manifest_instance_ids=manifest_ids,
                     planned_physical_requests=len(cases), max_physical_requests=max_physical_requests,
                     max_retries=max_retries, cost_cap_usd=cost_cap_usd,
                     input_token_ceiling=input_token_ceiling)


def verify_smoke_plan(plan: SmokePlan, adapter: JevChoiceAdapter, credentials: Any,
                      instances: Sequence[Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    by_id = {instance.instance_id: instance for instance in instances}
    check("model_pinned", plan.model == JEV_SMOKE_MODEL, plan.model)
    check("endpoint_pinned", plan.endpoint == JEV_SYSTEMONE_ENDPOINT, plan.endpoint)
    check("instance_count", len(by_id) == JEV_SMOKE_INSTANCE_COUNT, len(by_id))
    check("case_count", len(plan.cases) == JEV_SMOKE_INSTANCE_COUNT * len(JEV_SMOKE_CONDITIONS),
          len(plan.cases))
    check("conditions", {case.condition for case in plan.cases} == set(JEV_SMOKE_CONDITIONS),
          sorted({case.condition for case in plan.cases}))
    check("caps_positive", plan.max_physical_requests >= 1 and plan.cost_cap_usd > 0, None)
    check("planned_within_cap", plan.planned_physical_requests <= plan.max_physical_requests,
          {"planned": plan.planned_physical_requests, "cap": plan.max_physical_requests})
    estimate = estimate_cost_usd(plan.input_token_ceiling * max(1, plan.planned_physical_requests))
    check("cost_ceiling_within_cap", estimate <= plan.cost_cap_usd,
          {"estimate": estimate, "cap": plan.cost_cap_usd})

    for case in plan.cases:
        instance = by_id.get(case.instance_id)
        if instance is None:
            check(f"instance_present:{case.instance_id}", False)
            continue
        check(f"instance_in_manifest:{case.instance_id}",
              case.instance_id in plan.manifest_instance_ids, None)
        audit = audit_instance(instance)
        check(f"leak_checked:{case.instance_id}", audit["all_pass"],
              audit["checks"] if not audit["all_pass"] else None)
        state = adapter.build_state(instance, "A", case.condition)
        check(f"request_hash:{case.instance_id}:{case.condition}",
              state.request_hash == case.request_hash, None)
        check(f"option_ids:{case.instance_id}:{case.condition}",
              tuple(option.option_id for option in state.options) == case.option_ids, None)
        check(f"no_target:{case.instance_id}:{case.condition}",
              instance.target not in json.dumps(dict(state.state)), None)

    check("credentials_present", bool(getattr(credentials, "present", False)),
          getattr(credentials, "redacted", lambda: {})())
    check("credentials_shape_ok", bool(getattr(credentials, "shape_ok", False)), None)

    return {"ok": all(item["ok"] for item in checks), "checks": checks,
            "failed": [item["check"] for item in checks if not item["ok"]],
            "credentials": getattr(credentials, "redacted", lambda: {})()}


def _blocked(plan: SmokePlan, reason: str, approval: str | None) -> dict[str, Any]:
    return {"mode": "jev-choice-wire-smoke", "status": "blocked", "stop_reason": reason,
            "decision": "stop", "approval": approval, "planned_cases": len(plan.cases),
            "attempted_cases": 0, "valid_cases": 0, "physical_attempts": 0,
            "max_physical_requests": plan.max_physical_requests, "estimated_cost_usd": 0.0,
            "cost_ceiling_usd": estimate_cost_usd(
                plan.input_token_ceiling * max(1, plan.max_physical_requests)),
            "cost_cap_usd": plan.cost_cap_usd, "cases": [],
            "raw_response_retained": False, "credentials_retained": False}


def curate_golden_fixture(*, request_body: Mapping[str, Any], response_body: Mapping[str, Any],
                          plan: SmokePlan, probe: str) -> dict[str, Any]:
    """Return a credential-free golden fixture in the jev-dsl fixture shape."""

    def strip(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {key: strip(item) for key, item in value.items()
                    if str(key).lower() not in {"authorization", "api_key", "api-key", "x-api-key"}}
        if isinstance(value, (list, tuple)):
            return [strip(item) for item in value]
        return value

    return {
        "_source": {
            "probe": probe,
            "codec_version": JEV_CHOICE_CODEC_VERSION,
            "model": plan.model,
            "endpoint": plan.endpoint,
            "protocol_key": plan.protocol_key,
            "note": ("Curated credential-free capture from the #178 wire smoke; no credential "
                     "header or key is retained."),
        },
        "probe": probe,
        "status": 200,
        "request": strip(dict(request_body)),
        "response": strip(dict(response_body)),
    }


def execute_smoke(plan: SmokePlan, adapter: JevChoiceAdapter, verification: Mapping[str, Any],
                  instances: Sequence[Any], *, approval: str | None, golden_path: Path | None = None,
                  probe: str = "jev-choice-wire-smoke") -> dict[str, Any]:
    """Run the frozen smoke. Fails closed: no call is made unless preflight and caps pass."""

    if not approval:
        return _blocked(plan, "missing_approval", approval)
    if not verification.get("ok"):
        return _blocked(plan, "preflight_failed", approval)
    if plan.planned_physical_requests > plan.max_physical_requests:
        return _blocked(plan, "planned_requests_exceed_cap", approval)
    if getattr(adapter.client, "max_physical_requests", None) != plan.max_physical_requests:
        return _blocked(plan, "transport_cap_not_enforced", approval)

    by_id = {instance.instance_id: instance for instance in instances}
    report: dict[str, Any] = {
        "mode": "jev-choice-wire-smoke", "status": "completed", "stop_reason": None,
        "decision": "continue", "approval": approval, "model": plan.model, "endpoint": plan.endpoint,
        "protocol_key": plan.protocol_key, "planned_cases": len(plan.cases), "attempted_cases": 0,
        "valid_cases": 0, "physical_attempts": 0, "max_physical_requests": plan.max_physical_requests,
        "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0,
        "cost_ceiling_usd": estimate_cost_usd(plan.input_token_ceiling * max(1, plan.max_physical_requests)),
        "cost_cap_usd": plan.cost_cap_usd, "resolved_models": [], "invalid_classes": {},
        "cases": [], "golden_fixture": None, "raw_response_retained": False,
        "credentials_retained": False,
    }
    golden: dict[str, Any] | None = None
    for case in plan.cases:
        if report["estimated_cost_usd"] >= plan.cost_cap_usd:
            report["status"] = "stopped"
            report["stop_reason"] = "cost_cap"
            break
        instance = by_id[case.instance_id]
        state = adapter.build_state(instance, "A", case.condition)
        if state.request_hash != case.request_hash:
            report["status"] = "stopped"
            report["stop_reason"] = "request_hash_drift"
            break
        response, raw = adapter.complete_with_raw(state)
        report["attempted_cases"] += 1
        usage = dict(response.usage)
        report["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
        report["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
        report["estimated_cost_usd"] = estimate_cost_usd(report["input_tokens"])
        if response.model:
            report["resolved_models"] = sorted(set(report["resolved_models"]) | {response.model})
        report["cases"].append({
            "instance_id": case.instance_id, "condition": case.condition,
            "request_hash": case.request_hash, "status": response.status,
            "error_class": response.error_class, "selected_option_id": response.selected_option_id,
            "confidence": response.confidence,
        })
        if response.status != "complete":
            report["invalid_classes"][response.error_class] = \
                report["invalid_classes"].get(response.error_class, 0) + 1
            report["status"] = "stopped"
            report["stop_reason"] = response.error_class
            break
        report["valid_cases"] += 1
        if golden is None and raw is not None:
            golden = curate_golden_fixture(request_body=adapter.build_request(state), response_body=raw,
                                           plan=plan, probe=f"{probe}-{case.instance_id}-{case.condition}")

    report["physical_attempts"] = int(getattr(adapter.client, "physical_attempts", 0) or 0)
    if report["status"] == "stopped":
        report["decision"] = "stop"
    if golden is not None and golden_path is not None:
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(json.dumps(golden, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                               encoding="utf-8")
        report["golden_fixture"] = str(golden_path)
    return report


class _PreflightClient:
    """No-network placeholder so the offline preflight can share adapter settings."""

    provider = "jev"

    def __init__(self, *, endpoint: str = JEV_SYSTEMONE_ENDPOINT, max_retries: int = JEV_SMOKE_MAX_RETRIES,
                 max_physical_requests: int | None = None) -> None:
        self.endpoint = endpoint
        self.max_retries = max_retries
        self.max_physical_requests = max_physical_requests
        self.physical_attempts = 0

    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:  # pragma: no cover - never called
        raise RuntimeError("preflight client must never issue a request")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="J3c offline preflight and guarded Jev Choice wire smoke")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--live", action="store_true", help="issue the live smoke (requires --approval)")
    parser.add_argument("--approval", help="recorded reviewer approval reference; required for --live")
    args = parser.parse_args(argv)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    credentials = load_jev_credentials()
    instances = planning_low_instances(JEV_SMOKE_INSTANCE_COUNT)

    preflight_client = _PreflightClient(max_physical_requests=JEV_SMOKE_MAX_PHYSICAL_REQUESTS)
    adapter = JevChoiceAdapter(preflight_client, model=JEV_SMOKE_MODEL)
    plan = build_smoke_plan(instances, manifest, adapter)
    verification = verify_smoke_plan(plan, adapter, credentials, instances)
    summary = {"mode": "jev-choice-wire-smoke-preflight", "ok": verification["ok"],
               "failed": verification["failed"], "plan": plan.to_dict(),
               "credentials": verification["credentials"], "checks": verification["checks"]}
    print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))
    if not verification["ok"]:
        return 2
    if not args.live:
        return 0

    if not args.approval:
        print(json.dumps({"mode": "jev-choice-wire-smoke", "status": "blocked",
                          "stop_reason": "missing_approval"}, indent=2, sort_keys=True))
        return 2
    client = JevChoiceClient(model=JEV_SMOKE_MODEL, max_physical_requests=JEV_SMOKE_MAX_PHYSICAL_REQUESTS,
                             max_retries=JEV_SMOKE_MAX_RETRIES)
    live_adapter = JevChoiceAdapter(client, model=JEV_SMOKE_MODEL)
    report = execute_smoke(plan, live_adapter, verification, instances, approval=args.approval,
                           golden_path=args.golden)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                           encoding="utf-8")
    if report.get("golden_fixture"):
        print(f"golden fixture: {report['golden_fixture']}")
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "JEV_SMOKE_MODEL", "JEV_SMOKE_INSTANCE_COUNT", "JEV_SMOKE_CONDITIONS",
    "JEV_SMOKE_MAX_PHYSICAL_REQUESTS", "JEV_SMOKE_MAX_RETRIES", "JEV_SMOKE_COST_CAP_USD",
    "JEV_SMOKE_INPUT_TOKEN_CEILING", "JEV_INPUT_USD_PER_MTOK", "DEFAULT_MANIFEST", "DEFAULT_OUTPUT",
    "DEFAULT_REPORT", "DEFAULT_GOLDEN", "estimate_cost_usd", "SmokeCase", "SmokePlan",
    "build_smoke_plan", "verify_smoke_plan", "curate_golden_fixture", "execute_smoke", "main",
]
