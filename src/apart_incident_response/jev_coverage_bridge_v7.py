"""#191 repair — v7 six-form coverage runner (paid Ling SKU; live gated).

Successor to ``jev_coverage_bridge_v6`` for the v7 registration. Execution
semantics are reused from the reviewed v6 runner (original
``AgentContext -> treatment_prompt`` bridge, L4X grammar/seed/token budget,
peer-only visibility, ownership checks, #189 eligibility selector, fixed
N=36, fsync journaling, registered terminal stop rules). v7 differences:

- loads only the locked **v7** registration (fresh paths; v6 untouched);
- constructs the Ling writer with the registered **paid** SKU explicitly;
- prices paid Ling prompt/completion tokens per provider (the v1-v6
  free-route estimate is not reused) with registered next-call reserves;
- journal rows always carry ``material_correction`` (false until a receiver
  response exists);
- the live preflight additionally enforces the OpenRouter catalog gate and
  the successful capped transport-probe binding before any collection.

``live_collection_authorized`` remains false; the CLI requires ``--live``
and ``--approval`` and a new review must grant that approval. Offline use
makes zero provider calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import behavioral_discovery as bd
from . import jev_choice as jc
from . import jev_choice_v2 as jc2
from . import jev_coverage_bridge_v6 as run6
from . import jev_coverage_manifest_preregistration_v6 as prv6
from . import jev_coverage_manifest_preregistration_v7 as prv7
from . import jev_ling_writer_v3 as writer_v3
from . import jev_ling_writer_v5 as writer_v5
from . import jev_coverage_probe_v7 as probe
from . import jev_openrouter_catalog as catalog
from . import jev_replay as jr
from . import jev_replay_preregistration as pr
from . import jev_six_form_coverage_audit as audit
from . import jev_writer_exact_bridge_v5 as bridge
from . import jev_writer_ladder_v5 as ladder
from .communication_events import CommunicationEventLog
from .jev_choice import JevChoiceClient


COVERAGE_BRIDGE_VERSION = "exact-original-comm-bridge-v7"
RECEIVER_AGENT = bridge.RECEIVER_AGENT
CASE_PACE_SECONDS = run6.CASE_PACE_SECONDS

#: Frozen inputs: v1-v5 + #189 + bridge pair (v6 runner pins) plus the v6
#: trio, the successful probe, and everything recorded by the v7 registration.
FROZEN_INPUT_SHA256 = {
    **run6.FROZEN_INPUT_SHA256,
    **prv7.PRESERVED_INPUT_SHA256,
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_locked_registration(*, repo_root: Path | None = None,
                             pinned_hash: str | None = None) -> dict[str, Any]:
    """Load only the locked v7 registration; fail closed on status/hash drift."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    path = root / prv7.DEFAULT_OUTPUT_V7
    if not path.is_file():
        raise ValueError("v7 registration missing")
    registration = json.loads(path.read_text(encoding="utf-8"))
    if registration.get("preregistration_version") != prv7.COVERAGE_PREREG_VERSION:
        raise ValueError("wrong registration version")
    if registration.get("status") != prv7.COVERAGE_LOCKED_STATUS:
        raise ValueError("registration is not locked")
    if registration.get("live_collection_authorized") is not False:
        raise ValueError("live_collection_authorized must be false")
    if registration.get("approval", {}).get("live_collection_authorized") is not False:
        raise ValueError("registration approval must not authorize live collection")
    if pinned_hash is not None and registration.get("preregistration_hash") != pinned_hash:
        raise ValueError("registration hash drift")
    return registration


def build_coverage_plan(registration: Mapping[str, Any]
                        ) -> tuple[Any, list[Any]]:
    """Reuse the reviewed plan builder; the v7 document satisfies its checks."""

    return run6.build_coverage_plan(registration)


def construct_coverage_runtime(registration: Mapping[str, Any], *,
                               clock: Callable[[], float] | None = None,
                               sleep_fn: Callable[[float], None] | None = None
                               ) -> tuple[Any, Any, Any, list[Any]]:
    """Build the transports with the registered caps and the paid Ling SKU."""

    plan, instances = build_coverage_plan(registration)
    if plan.ling_model != prv7.PAID_LING_MODEL:
        raise ValueError("plan ling model must be the paid SKU")
    receiver = jc2.JevChoiceAdapterV2(
        JevChoiceClient(model=plan.model, max_physical_requests=plan.jev_request_cap),
        model=plan.model)
    writer_kwargs: dict[str, Any] = {"model": plan.ling_model,
                                     "endpoint": plan.ling_endpoint,
                                     "max_physical_requests": plan.ling_request_cap}
    if clock is not None:
        writer_kwargs["clock"] = clock
    if sleep_fn is not None:
        writer_kwargs["sleep_fn"] = sleep_fn
    writer = writer_v5.LingWriterClientV5(**writer_kwargs)
    return receiver, writer, plan, instances


def estimate_run_cost_usd(tokens: Mapping[str, int],
                          cost_model: Mapping[str, Any]) -> float:
    """Paid-route cost: Ling prompt+completion plus Jev input (output free)."""

    ling = (int(tokens.get("ling_input_tokens", 0)) * float(
        cost_model["ling_prompt_usd_per_mtok"])
        + int(tokens.get("ling_output_tokens", 0)) * float(
            cost_model["ling_completion_usd_per_mtok"])) / 1_000_000
    jev = (int(tokens.get("jev_input_tokens", 0)) * float(
        cost_model["jev_input_usd_per_mtok"])) / 1_000_000
    return round(ling + jev, 12)


def verify_coverage_bridge_preflight(plan: Any,
                                     registration: Mapping[str, Any],
                                     receiver: Any, writer: Any, *,
                                     repo_root: Path,
                                     approval: str | None,
                                     ling_key_present: bool | None = None,
                                     check_credentials: bool = True,
                                     check_catalog: bool = False,
                                     catalog_document: Mapping[str, Any] | None = None,
                                     require_approval: bool = True,
                                     pinned_hash: str | None = None,
                                     journal_exists: bool | None = None,
                                     report_exists: bool | None = None
                                     ) -> dict[str, Any]:
    """Named-check, fail-closed v7 preflight. Never issues a request itself."""

    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    check("approval_present", bool(approval) or not require_approval, None)
    verification = prv7.verify_against_coverage_manifest_preregistration_v7(
        registration, repo_root=repo_root, check_credentials=False,
        check_catalog=False, journal_exists=journal_exists,
        report_exists=report_exists, require_approval=require_approval)
    check("registration_verifies", verification["ok"], verification["errors"])
    check("registration_hash_matches",
          registration.get("preregistration_hash") == plan.registration_hash,
          plan.registration_hash)
    if pinned_hash is not None:
        check("pinned_hash_matches", plan.registration_hash == pinned_hash,
              plan.registration_hash)
    check("status_locked", registration.get("status") == prv7.COVERAGE_LOCKED_STATUS,
          registration.get("status"))
    check("live_collection_not_authorized",
          registration.get("live_collection_authorized") is False
          and registration.get("approval", {}).get("live_collection_authorized") is False
          and registration.get("lock_is_not_live_authorization") is True, None)

    runner_policy = registration.get("runner_policy", {})
    source_files = list((registration.get("generator", {}) or {}).get("source_files", []))
    check("runner_policy_satisfied",
          runner_policy.get("runner_implemented") is True
          and runner_policy.get("runner_source_files") == [prv7.RUNNER_SOURCE_REL]
          and prv7.RUNNER_SOURCE_REL in source_files
          and runner_policy.get("runner_source_bound") is True,
          runner_policy.get("runner_source_files"))
    check("runner_not_live_authorization",
          runner_policy.get("adding_runner_authorizes_collection") is False
          and "live execution is forbidden" in str(runner_policy.get("live_execution_rule", "")),
          None)
    generator = registration.get("generator", {})
    check("source_treatment_geometry_prompt_hashes_wellformed",
          all(isinstance(generator.get(key), str) and len(generator.get(key)) == 64
              for key in ("source_files_hash", "manifest_treatment_hash",
                          "information_geometry_hash", "treatment_hash"))
          and isinstance(registration.get("treatment", {}).get("writer_prompt", {}).get(
              "prompt_hash"), str), None)

    manifest = registration.get("manifest", {})
    check("manifest_36_exact_order",
          list(plan.instance_ids) == [str(item) for item in manifest.get("instance_ids", [])]
          and len(plan.instance_ids) == 36, len(plan.instance_ids))
    form_counts = manifest.get("form_counts", {})
    check("forms_six_per_exact_form",
          set(form_counts) == set(prv6.FROZEN_FORM_IDS)
          and all(form_counts.get(form) == 6 for form in prv6.FROZEN_FORM_IDS), None)
    disjointness = manifest.get("disjointness", {})
    check("manifest_disjointness", disjointness.get("ok") is True
          and not disjointness.get("overlap"), None)
    check("manifest_reuse_justified",
          "no outcome-based selection" in str(manifest.get("manifest_reuse_justification", "")),
          None)
    design = registration.get("coverage_design", {})
    check("fixed_n_and_no_replacement",
          design.get("fixed_n") is True and design.get("n") == 36
          and bool(design.get("no_stopping_after_first_message"))
          and "no seed replacement" in str(design.get("no_seed_replacement", "")), None)
    check("resume_not_permitted", registration.get("resume_permitted", False) is False, None)

    protocol = registration.get("model_and_protocol", {})
    client = receiver.client
    check("jev_model_matches", receiver.model == plan.model == protocol.get("model")
          == pr.JEV_REPLAY_MODEL, plan.model)
    check("jev_endpoint_matches", getattr(client, "endpoint", None) == plan.endpoint
          == protocol.get("endpoint") == pr.JEV_REPLAY_ENDPOINT, plan.endpoint)
    check("jev_retry_policy",
          getattr(client, "max_retries", None) == pr.JEV_REPLAY_MAX_RETRIES
          and protocol.get("max_retries") == pr.JEV_REPLAY_MAX_RETRIES, None)
    check("jev_protocol_key",
          plan.protocol_key == protocol.get("protocol_key")
          and jc2.is_jev_v2_protocol_key(plan.protocol_key)
          and not jc.is_jev_protocol_key(plan.protocol_key)
          and plan.protocol_key == prv6.protocol_key_v6(), plan.protocol_key)
    check("jev_partition_matches",
          getattr(client, "max_physical_requests", None) == plan.jev_request_cap == 108,
          getattr(client, "max_physical_requests", None))

    treatment = registration.get("treatment", {})
    check("ling_model_is_paid_sku",
          writer.model == plan.ling_model == protocol.get("ling_model")
          == prv7.PAID_LING_MODEL, writer.model)
    check("ling_endpoint_matches", writer.endpoint == plan.ling_endpoint
          == protocol.get("ling_endpoint") == pr.LING_ENDPOINT, writer.endpoint)
    check("ling_parser_and_schema",
          writer.writer_parser_version == writer_v5.WRITER_PARSER_VERSION
          and writer.writer_outcomes_version == writer_v5.WRITER_OUTCOMES_VERSION
          and treatment.get("writer_observability") == writer_v5.writer_schema(), None)
    check("ling_pacing",
          writer.min_attempt_interval_seconds == writer_v3.LING_MIN_ATTEMPT_INTERVAL_SECONDS
          and writer.pacing_algorithm == writer_v3.LING_PACING_ALGORITHM
          and writer.clock_name == writer_v3.LING_MONOTONIC_CLOCK_NAME, None)
    check("ling_retry_policy",
          writer.max_retries == pr.LING_MAX_RETRIES
          and writer.transport_version == writer_v5.LingWriterClientV5.transport_version, None)
    check("ling_seed_behavior",
          treatment.get("writer_prompt", {}).get("seed_behavior", {}).get("algorithm")
          == bd.PROVIDER_SEED_ALGORITHM
          and treatment.get("seed_algorithm") == ladder.EXACT_BRIDGE_SEED_ALGORITHM
          and plan.seed_algorithm == ladder.EXACT_BRIDGE_SEED_ALGORITHM, None)
    check("token_budget_matches", plan.token_budget == 1024
          == ladder.EXACT_BRIDGE_TOKEN_BUDGET == treatment.get("token_budget"),
          plan.token_budget)
    check("grammar_and_prompt_path",
          "treatment_prompt" in str(treatment.get("writer_prompt", {}).get("path", "")), None)
    check("two_agents_two_turns",
          treatment.get("turns") == ladder.EXACT_BRIDGE_TURNS
          and list(treatment.get("agents", [])) == list(ladder.EXACT_BRIDGE_AGENTS), None)
    check("ling_partition_matches",
          getattr(writer, "max_physical_requests", None) == plan.ling_request_cap == 432,
          getattr(writer, "max_physical_requests", None))

    caps = registration.get("caps", {})
    cost_model = caps.get("cost_model", {})
    check("cost_model_frozen_paid_route",
          cost_model == prv7.cost_model(),
          {"ling_prompt": cost_model.get("ling_prompt_usd_per_mtok"),
           "ling_completion": cost_model.get("ling_completion_usd_per_mtok")})
    check("cost_model_recomputes_within_ceiling",
          caps.get("worst_case_cost_usd") == prv7.WORST_CASE_TOTAL_USD
          and float(caps.get("worst_case_cost_usd", 1e9)) <= float(
              caps.get("cost_cap_usd", 0.0)) == prv7.COST_CAP_USD,
          {"worst_case_cost_usd": caps.get("worst_case_cost_usd"),
           "cost_cap_usd": caps.get("cost_cap_usd")})
    check("combined_cap_and_partitions",
          plan.jev_request_cap + plan.ling_request_cap == plan.request_cap == 540
          and caps.get("physical_requests") == 540, plan.request_cap)
    check("planned_within_caps",
          (plan.planned_ling, plan.planned_jev, plan.planned_requests) == (144, 36, 180)
          and plan.planned_ling <= plan.ling_request_cap
          and plan.planned_jev <= plan.jev_request_cap, None)

    probe_path = repo_root / prv7.PROBE_PATH
    probe_ok = probe_path.is_file() and hashlib.sha256(
        probe_path.read_bytes()).hexdigest() == prv7.EXPECTED_PROBE_SHA256
    probe_doc = json.loads(probe_path.read_text(encoding="utf-8")) if probe_ok else {}
    interpretation = probe.interpret_probe_artifact(probe_doc)
    check("transport_probe_routing_succeeded_and_capped",
          probe_ok and interpretation["routing_success"] is True
          and probe_doc.get("model") == prv7.PAID_LING_MODEL
          and (probe_doc.get("attempts") or {}).get("physical") == 1
          and (probe_doc.get("attempts") or {}).get("cap") == 1,
          {"sha256_ok": probe_ok, "routing_success": interpretation["routing_success"],
           "writer_output_validated": interpretation["writer_output_validated"]})
    # Probe scope/approval semantics are enforced on the registration binding
    # (the immutable artifact predates those fields); here we only prove the
    # artifact itself never supports a validated-writer-output claim.
    check("probe_writer_output_not_claimed",
          not probe_ok or interpretation["writer_output_validated"] is False,
          interpretation["outcome"])
    gate_record = registration.get("catalog_gate", {})
    check("catalog_gate_recorded",
          gate_record.get("required_before_live") is True
          and (gate_record.get("recorded_from_probe") or {}).get("target_present") is True,
          gate_record.get("recorded_from_probe"))
    if check_catalog:
        try:
            fetched = catalog_document if catalog_document is not None \
                else catalog.fetch_model_catalog()
        except Exception as exc:
            check("live_catalog_gate", False, f"{type(exc).__name__}: {exc}")
            fetched = None
        if fetched is not None:
            # The hardened gate never raises on malformed payloads; pricing is
            # parsed with positive_rate so no exception can escape here either.
            gate = catalog.catalog_availability_gate(prv7.PAID_LING_MODEL, catalog=fetched)
            entry = gate["diagnostics"].get("target_entry") or {}
            prompt_tok = catalog.positive_rate(entry.get("prompt_usd_per_tok"))
            completion_tok = catalog.positive_rate(entry.get("completion_usd_per_tok"))
            prompt_rate = prompt_tok * 1_000_000 if prompt_tok is not None else None
            completion_rate = completion_tok * 1_000_000 if completion_tok is not None else None
            check("live_catalog_gate", gate["ok"], gate["failed"])
            check("live_catalog_pricing_matches_frozen",
                  prompt_rate == prv7.LING_PROMPT_USD_PER_MTOK
                  and completion_rate == prv7.LING_COMPLETION_USD_PER_MTOK,
                  {"prompt_usd_per_mtok": prompt_rate,
                   "completion_usd_per_mtok": completion_rate})

    outputs = registration.get("outputs", {})
    journal_path = repo_root / str(outputs.get("journal", prv7.DEFAULT_JOURNAL_V7))
    report_path = repo_root / str(outputs.get("report", prv7.DEFAULT_REPORT_V7))
    journal_bad = journal_exists if journal_exists is not None else journal_path.exists()
    report_bad = report_exists if report_exists is not None else report_path.exists()
    check("journal_path_fresh", not journal_bad, str(journal_path))
    check("report_path_fresh", not report_bad, str(report_path))

    if check_credentials:
        credentials = jc.load_jev_credentials()
        check("jev_credentials_present", bool(credentials.present and credentials.shape_ok),
              credentials.redacted())
        ling_ok = bd._api_key() is not None if ling_key_present is None else bool(ling_key_present)
        check("ling_credentials_present", ling_ok, None)

    frozen = []
    for relative, expected in FROZEN_INPUT_SHA256.items():
        path = repo_root / relative
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        frozen.append({"path": relative, "expected_sha256": expected, "actual_sha256": actual,
                       "ok": actual == expected})
    check("frozen_v1_v7_inputs_unchanged", all(item["ok"] for item in frozen),
          [item["path"] for item in frozen if not item["ok"]])

    return {"ok": all(item["ok"] for item in checks), "checks": checks,
            "failed": [item["check"] for item in checks if not item["ok"]],
            "registration_verification": verification, "frozen_inputs": frozen}


def _blocked(reason: str, approval: str | None, plan: Any) -> dict[str, Any]:
    return {"mode": COVERAGE_BRIDGE_VERSION, "status": "blocked", "stop_reason": reason,
            "approval": approval,
            "registration_hash": plan.registration_hash if plan else None,
            "planned_cases": plan.planned_cases if plan else None,
            "provider_calls": 0,
            "raw_response_retained": False, "credentials_retained": False}


def execute_coverage_bridge(plan: Any, receiver: Any, writer: Any,
                            verification: Mapping[str, Any],
                            instances: Sequence[Any], *,
                            approval: str | None,
                            registration: Mapping[str, Any],
                            pinned_hash: str | None = None,
                            journal_path: Path | None = None,
                            report_path: Path | None = None,
                            sleep_fn: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Run fixed N=36 under the v7 registration with paid-route accounting."""

    outputs = registration.get("outputs", {})
    journal_path = journal_path if journal_path is not None else Path(
        str(outputs.get("journal", prv7.DEFAULT_JOURNAL_V7)))
    report_path = report_path if report_path is not None else Path(
        str(outputs.get("report", prv7.DEFAULT_REPORT_V7)))
    cost_model = dict((registration.get("caps", {}) or {}).get("cost_model", {}))
    if cost_model != prv7.cost_model():
        return _blocked("cost_model_drift", approval, plan)
    ling_reserve = prv7.LING_NEXT_CALL_RESERVE_USD
    jev_reserve = prv7.JEV_NEXT_CALL_RESERVE_USD

    if not approval:
        return _blocked("missing_approval", approval, plan)
    if not verification.get("ok"):
        return _blocked("preflight_failed", approval, plan)
    if pinned_hash is not None and plan.registration_hash != pinned_hash:
        return _blocked("registration_hash_mismatch", approval, plan)
    if plan.jev_request_cap + plan.ling_request_cap != plan.request_cap:
        return _blocked("bridge_partition_mismatch", approval, plan)
    if getattr(receiver.client, "max_physical_requests", None) != plan.jev_request_cap:
        return _blocked("receiver_partition_not_enforced", approval, plan)
    if getattr(writer, "max_physical_requests", None) != plan.ling_request_cap:
        return _blocked("writer_partition_not_enforced", approval, plan)
    if journal_path.exists():
        return _blocked("output_exists", approval, plan)
    if report_path.exists():
        return _blocked("report_exists", approval, plan)

    by_id = {instance.instance_id: instance for instance in instances}
    report: dict[str, Any] = {
        "mode": COVERAGE_BRIDGE_VERSION, "status": "completed", "stop_reason": None,
        "approval": approval, "registration_hash": plan.registration_hash,
        "protocol_key": plan.protocol_key, "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
        "token_budget": plan.token_budget, "turns": ladder.EXACT_BRIDGE_TURNS,
        "agents": list(ladder.EXACT_BRIDGE_AGENTS), "seed_algorithm": plan.seed_algorithm,
        "ling_model": plan.ling_model,
        "instance_ids": list(plan.instance_ids),
        "planned_cases": plan.planned_cases,
        "planned_calls": {"ling": plan.planned_ling, "jev": plan.planned_jev,
                          "combined": plan.planned_requests},
        "partitions": {"ling": plan.ling_request_cap, "jev": plan.jev_request_cap,
                       "combined": plan.request_cap},
        "cost_model": cost_model,
        "attempted_cases": 0, "receiver_valid_cases": 0, "receiver_invalid_cases": 0,
        "receiver_unattempted_cases": 0,
        "input_tokens": 0, "output_tokens": 0,
        "tokens_by_provider": {"ling_input_tokens": 0, "ling_output_tokens": 0,
                               "jev_input_tokens": 0, "jev_output_tokens": 0},
        "estimated_cost_usd": 0.0, "cost_cap_usd": prv7.COST_CAP_USD,
        "resolved_models": [], "cases": [],
        "raw_response_retained": False, "credentials_retained": False,
    }
    handle = None
    if journal_path is not None:
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        handle = journal_path.open("x", encoding="utf-8")

    def journal(row: dict[str, Any]) -> None:
        report["cases"].append(row)
        if handle is not None:
            handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def guards_ok(extra_physical: int, *, ling: bool) -> bool:
        ling_attempts = int(getattr(writer, "physical_attempts", 0) or 0)
        jev_attempts = int(getattr(receiver.client, "physical_attempts", 0) or 0)
        combined = ling_attempts + jev_attempts
        if ling and ling_attempts + extra_physical > plan.ling_request_cap:
            return False
        if not ling and jev_attempts + extra_physical > plan.jev_request_cap:
            return False
        if combined + extra_physical > plan.request_cap:
            return False
        reserve = ling_reserve if ling else jev_reserve
        return report["estimated_cost_usd"] + reserve <= report["cost_cap_usd"]

    counted_exposures = 0
    try:
        for instance_id in plan.instance_ids:
            instance = by_id[instance_id]
            if report["attempted_cases"] > 0:
                sleep_fn(CASE_PACE_SECONDS)
            report["attempted_cases"] += 1
            run_id = f"coverage-v7-{instance_id}"
            log = CommunicationEventLog(run_id)
            board: list[dict[str, Any]] = []
            board_info: dict[str, Any] = {}
            rejected: list[dict[str, Any]] = []
            writer_outcomes: list[dict[str, Any]] = []
            invalid: str | None = None
            for turn in range(ladder.EXACT_BRIDGE_TURNS):
                for agent in ladder.EXACT_BRIDGE_AGENTS:
                    for row in [r for r in board if r["author"] != agent]:
                        read = log.peer_read(agent, board_info[row["message_id"]],
                                             exposure_id=f"turn-{turn}")
                        if read is not None:
                            counted_exposures += 1
                    if not guards_ok(1 + pr.LING_MAX_RETRIES, ling=True):
                        report["status"], report["stop_reason"] = "stopped", "cost_cap"
                        invalid = "cost_cap"
                        break
                    _, prompt = bridge.agent_context_and_prompt(instance, agent, turn, board,
                                                                 run_id)
                    outcome = writer.write_outcome({
                        "prompt": prompt, "grammar": ladder.RUNG_INDEX["L4X"].grammar,
                        "private_clues": list(instance.private_clues.get(agent, ())),
                        "candidate_labels": sorted(instance.solutions),
                        "seed": bd.provider_seed(instance.instance_id, "COMM", turn, agent),
                        "max_tokens": plan.token_budget})
                    ling_in = int(outcome.get("input_tokens") or 0)
                    ling_out = int(outcome.get("output_tokens") or 0)
                    report["tokens_by_provider"]["ling_input_tokens"] += ling_in
                    report["tokens_by_provider"]["ling_output_tokens"] += ling_out
                    report["input_tokens"] += ling_in
                    report["output_tokens"] += ling_out
                    report["estimated_cost_usd"] = estimate_run_cost_usd(
                        report["tokens_by_provider"], cost_model)
                    kind = outcome["outcome"]
                    writer_outcomes.append({
                        "agent": agent, "turn": turn, "outcome": kind,
                        "finish_reason": outcome.get("finish_reason"),
                        "content_length": outcome.get("content_length"),
                        "answer": outcome.get("answer"),
                        "claim": outcome.get("claim"),
                        "input_tokens": outcome.get("input_tokens"),
                        "output_tokens": outcome.get("output_tokens"),
                        "completion_tokens": outcome.get("completion_tokens"),
                        "parser_classification": outcome.get("parser_classification"),
                        "seed_sent": outcome.get("seed_sent"),
                        "max_tokens": outcome.get("max_tokens"),
                        "error_class": outcome.get("error_class"),
                        "physical_attempts": outcome.get("physical_attempts")})
                    if kind == writer_v5.OUTCOME_MESSAGE_CANDIDATE \
                            and instance.holds_claim(agent, str(outcome["claim"])):
                        receiver_agent = "B" if agent == "A" else "A"
                        message_id = f"message-{agent}-{turn}"
                        text = str(outcome["claim"])
                        info = instance.information(receiver_agent, text, message_id)
                        row = {"message_id": message_id, "author": agent,
                               "receiver": receiver_agent, "text": text,
                               "status": info.status, "delta_i_bits": info.delta_i_bits,
                               "message_tokens": len(text.split())}
                        board.append(row)
                        board_info[message_id] = info
                        log.board_write(agent, info, message_tokens=row["message_tokens"],
                                        receiver_id=receiver_agent)
                    elif kind == writer_v5.OUTCOME_NON_OWNED_CLAIM:
                        rejected.append({"agent": agent, "turn": turn,
                                         "claim": outcome.get("claim")})
                        log.record("board_write_rejected", agent, status="rejected",
                                   payload={"reason": "claim_not_owned_by_writer",
                                            "raw_text": outcome.get("claim")})
                    elif kind == writer_v5.OUTCOME_DELIBERATE_SILENCE:
                        pass
                    else:
                        invalid = str(outcome.get("error_class") or kind)
                        report["status"], report["stop_reason"] = "stopped", invalid
                        break
                if invalid is not None:
                    break

            receiver_attempted = False
            receiver_valid = False
            receiver_error_class: str | None = None
            receiver_row: dict[str, Any] = {
                "instance_id": instance.instance_id, "instance_seed": instance.seed,
                "prompt_form_id": plan.prompt_form_ids[instance_id],
                "registered_form_membership": True,
                "turns": ladder.EXACT_BRIDGE_TURNS,
                "agents": list(ladder.EXACT_BRIDGE_AGENTS),
                "board": list(board), "rejected": rejected, "board_log": [],
                "writer_outcomes": writer_outcomes,
                "receiver_attempted": False, "receiver_unattempted": True,
                "receiver_invalid": False,
                "receiver_valid": False, "receiver_status": None,
                "receiver_error_class": None, "normalization_tier": None,
                "renormalized": None, "material_correction": False,
                "request_hash": None, "state_hash": None,
                "protocol_key": plan.protocol_key, "resolved_model": None,
                "option_ids": sorted(instance.solutions), "target_id": instance.target,
                "selected_option_id": None, "confidence": None,
                "probabilities": {}, "raw_probabilities": {},
                "probability_diagnostics": None, "usage": {},
                "i_m_bits": None, "eligible_exposure": False,
                "accepted_b_message_present": False,
                "replay_selection": None, "replay_eligible": False,
                "provider_attempts": {},
                "raw_response_retained": False, "credentials_retained": False,
            }
            if invalid is None:
                b_rows = [row for row in board
                          if row["author"] == "B" and row["status"] == "accepted"]
                visible = [{"text": jr.serialize_message(str(row["text"]))} for row in b_rows]
                state = receiver.build_state(instance, RECEIVER_AGENT, "COMM",
                                             visible_messages=visible)
                receiver_row["request_hash"] = state.request_hash
                receiver_row["state_hash"] = jr.canonical_hash(state.state)
                if not guards_ok(1 + pr.JEV_REPLAY_MAX_RETRIES, ling=False):
                    receiver_error_class = "cost_cap"
                    report["status"], report["stop_reason"] = "stopped", "cost_cap"
                else:
                    receiver_attempted = True
                    for row in b_rows:
                        read = log.peer_read(RECEIVER_AGENT, board_info[row["message_id"]],
                                             exposure_id=bridge.JEV_FINALIZER_EXPOSURE_ID)
                        if read is not None:
                            counted_exposures += 1
                    try:
                        response, _ = receiver.complete_with_raw(state)
                    except Exception as exc:
                        receiver_error_class = f"jev_{type(exc).__name__}"
                        report["status"], report["stop_reason"] = "stopped", receiver_error_class
                        response = None
                    if response is not None:
                        usage = dict(response.usage)
                        jev_in = int(usage.get("input_tokens", 0) or 0)
                        jev_out = int(usage.get("output_tokens", 0) or 0)
                        report["tokens_by_provider"]["jev_input_tokens"] += jev_in
                        report["tokens_by_provider"]["jev_output_tokens"] += jev_out
                        report["input_tokens"] += jev_in
                        report["output_tokens"] += jev_out
                        report["estimated_cost_usd"] = estimate_run_cost_usd(
                            report["tokens_by_provider"], cost_model)
                        if response.model:
                            report["resolved_models"] = sorted(
                                set(report["resolved_models"]) | {response.model})
                        receiver_valid = response.status == "complete"
                        receiver_row.update({
                            "receiver_status": response.status,
                            "receiver_error_class": response.error_class,
                            "receiver_valid": receiver_valid,
                            "normalization_tier": response.normalization_tier,
                            "renormalized": response.renormalized,
                            "material_correction": run6.material_correction(response),
                            "resolved_model": response.model,
                            "selected_option_id": response.selected_option_id,
                            "confidence": response.confidence,
                            "probabilities": dict(response.probabilities),
                            "raw_probabilities": dict(response.raw_probabilities),
                            "probability_diagnostics": (
                                response.diagnostics.to_dict()
                                if response.diagnostics is not None else None),
                            "usage": usage,
                        })
                        if receiver_valid and response.request_hash != state.request_hash:
                            receiver_valid = False
                            receiver_error_class = "request_hash_drift"
                            report["status"], report["stop_reason"] = "stopped", "request_hash_drift"
                        if not receiver_valid:
                            receiver_error_class = receiver_error_class or response.error_class
                            if report["status"] == "completed":
                                report["status"], report["stop_reason"] = "stopped", \
                                    receiver_error_class
            if receiver_attempted:
                if receiver_valid:
                    report["receiver_valid_cases"] += 1
                    b_accepted = [row for row in board
                                  if row["author"] == "B" and row["status"] == "accepted"]
                    if b_accepted:
                        receiver_row["i_m_bits"] = sum(
                            float(row["delta_i_bits"] or 0.0) for row in b_accepted)
                else:
                    report["receiver_invalid_cases"] += 1
            else:
                report["receiver_unattempted_cases"] += 1
            receiver_row["receiver_attempted"] = receiver_attempted
            receiver_row["receiver_unattempted"] = not receiver_attempted
            receiver_row["receiver_invalid"] = bool(receiver_attempted and not receiver_valid)
            receiver_row["receiver_valid"] = receiver_valid
            receiver_row["receiver_error_class"] = receiver_error_class
            receiver_row["provider_attempts"] = {
                "jev": int(getattr(receiver.client, "physical_attempts", 0) or 0),
                "ling": int(getattr(writer, "physical_attempts", 0) or 0),
                "combined": int(getattr(receiver.client, "physical_attempts", 0) or 0)
                + int(getattr(writer, "physical_attempts", 0) or 0)}
            receiver_row["board_log"] = [event.to_dict() for event in log.events]
            receiver_row["accepted_b_message_present"] = any(
                row.get("author") == "B" and row.get("status") == "accepted"
                for row in board)
            selection = audit.select_replay_claims(receiver_row, instance)
            receiver_row["replay_selection"] = selection
            receiver_row["replay_eligible"] = bool(selection["eligible"] and receiver_valid)
            receiver_row["eligible_exposure"] = receiver_row["replay_eligible"]
            journal(receiver_row)
            if report["status"] == "stopped":
                break
    finally:
        if handle is not None:
            handle.close()

    jev_attempts = int(getattr(receiver.client, "physical_attempts", 0) or 0)
    ling_attempts = int(getattr(writer, "physical_attempts", 0) or 0)
    report["physical_attempts"] = jev_attempts + ling_attempts
    report["provider_attempts"] = {"jev": jev_attempts, "ling": ling_attempts,
                                   "combined": jev_attempts + ling_attempts,
                                   "jev_partition": plan.jev_request_cap,
                                   "ling_partition": plan.ling_request_cap}
    summary = run6.summarize_coverage(report["cases"], counted_exposures=counted_exposures)
    report.update(summary)
    report["distinct_forms"] = len({str(case.get("prompt_form_id"))
                                    for case in report["cases"]})
    if report["status"] == "completed" and \
            report["receiver_valid_cases"] != plan.planned_cases:
        report["status"], report["stop_reason"] = "incomplete", "missing_valid_receiver"
    report["raw_response_retained"] = False
    report["credentials_retained"] = False
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="#191 repair: v7 coverage runner")
    parser.add_argument("--live", action="store_true",
                        help="execute collection (requires --approval; never run offline)")
    parser.add_argument("--approval", help="reviewer authorization reference for live collection")
    parser.add_argument("--repo-root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = Path(args.repo_root) if args.repo_root is not None else _repo_root()
    try:
        registration = load_locked_registration(repo_root=root)
    except ValueError as exc:
        print(json.dumps({"mode": COVERAGE_BRIDGE_VERSION, "status": "blocked",
                          "stop_reason": f"registration_load_failed: {exc}",
                          "provider_calls": 0}, indent=2, sort_keys=True))
        return 2
    registration_hash = str(registration.get("preregistration_hash", ""))
    try:
        receiver, writer, plan, instances = construct_coverage_runtime(registration)
    except ValueError as exc:
        print(json.dumps({"mode": COVERAGE_BRIDGE_VERSION, "status": "blocked",
                          "stop_reason": f"plan_failed: {exc}", "provider_calls": 0},
                         indent=2, sort_keys=True))
        return 2
    verification = verify_coverage_bridge_preflight(
        plan, registration, receiver, writer, repo_root=root, approval=args.approval,
        pinned_hash=registration_hash, check_credentials=bool(args.live),
        check_catalog=bool(args.live), require_approval=bool(args.live))
    print(json.dumps({"mode": f"{COVERAGE_BRIDGE_VERSION}-preflight",
                      "ok": verification["ok"], "failed": verification["failed"],
                      "checks": verification["checks"], "plan": plan.to_dict()},
                     indent=2, sort_keys=True, allow_nan=False))
    if not verification["ok"]:
        return 2
    if not args.live:
        print(json.dumps({"mode": COVERAGE_BRIDGE_VERSION, "status": "offline",
                          "note": "preflight only; no provider call made",
                          "live_collection_authorized": False, "provider_calls": 0},
                         indent=2, sort_keys=True))
        return 0
    if not args.approval:
        print(json.dumps(_blocked("missing_approval", args.approval, plan), indent=2,
                         sort_keys=True))
        return 2
    journal_path = root / str(registration["outputs"]["journal"])
    report_target = root / str(registration["outputs"]["report"])
    report = execute_coverage_bridge(
        plan, receiver, writer, verification, instances, approval=args.approval,
        registration=registration, pinned_hash=registration_hash,
        journal_path=journal_path, report_path=report_target)
    if report.get("status") != "blocked":
        report_target.parent.mkdir(parents=True, exist_ok=True)
        report_target.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8")
    print(json.dumps({key: report.get(key) for key in
                      ("mode", "status", "stop_reason", "attempted_cases",
                       "receiver_valid_cases", "forms_with_eligible_exposure",
                       "estimated_cost_usd", "coverage_decision_pending_192",
                       "replay_started")}, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "COVERAGE_BRIDGE_VERSION", "RECEIVER_AGENT", "CASE_PACE_SECONDS",
    "FROZEN_INPUT_SHA256", "load_locked_registration", "build_coverage_plan",
    "construct_coverage_runtime", "estimate_run_cost_usd",
    "verify_coverage_bridge_preflight", "execute_coverage_bridge", "main",
]
