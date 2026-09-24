"""#191 — fresh six-form L4X coverage runner v6 (offline implementation; live gated).

Executes the original-treatment L4X bridge over the locked 36-instance,
form-balanced v6 manifest: two Ling agents x two turns through the original
``AgentContext -> treatment_prompt`` path, peer-only board, ownership-checked
writes, and the Jev Choice wire v2 final read by agent A. Execution semantics
are reused from the reviewed ``jev_writer_exact_bridge_v5`` (same prompt
builder, writer outcomes, ladder constants and provenance log); this module
adds the v6 manifest/plan, registered caps, per-case prompt-form evidence, the
#189 authoritative eligibility selector and the coverage report.

Fixed N=36: every planned instance runs; deliberate silence and rejected
non-owned claims continue; only the registered terminal stop rules stop the
run. ``live_collection_authorized`` remains false — the CLI requires both
``--live`` and ``--approval`` and the preflight must pass before any provider
call. No provider call is ever made by offline use of this module.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import behavioral_discovery as bd
from . import jev_choice as jc
from . import jev_choice_v2 as jc2
from . import jev_ling_writer_v3 as writer_v3
from . import jev_ling_writer_v5 as writer_v5
from . import jev_replay as jr
from . import jev_replay_preregistration as pr
from . import jev_six_form_coverage_audit as audit
from . import jev_coverage_manifest_preregistration_v6 as prv6
from . import jev_writer_exact_bridge_v5 as bridge
from . import jev_writer_ladder_v5 as ladder
from .communication_events import CommunicationEventLog
from .jev_choice import JevChoiceClient
from .jev_choice_smoke import estimate_cost_usd


COVERAGE_BRIDGE_VERSION = "exact-original-comm-bridge-v6"
RECEIVER_AGENT = bridge.RECEIVER_AGENT
CASE_PACE_SECONDS = 0.25

#: Frozen v1-v5 / #189 inputs; preflight fails closed if any drift.
FROZEN_INPUT_SHA256 = {
    "runs/epic-126/jev-choice-replay-preregistration.json":
        "241591d24acc38ada2b236270adac6dba91fc9c3b190cc7afecd9436fc08675d",
    "runs/epic-126/jev-choice-replay-preregistration-v2.json":
        "f4e68dadcd570789e30b46f41282201f7b5a0377c941f9d717a0699ca8fa5ee0",
    "runs/epic-126/jev-choice-replay-preregistration-v3.json":
        "fbb4eecc7c5765974bdbaaa4de46cc1006d456aafc70263899cd8c00114567c9",
    "runs/epic-126/jev-writer-ladder-preregistration-v4.json":
        "a3dd6e2c8e60e64132c76668f4f5b79881e32936a816353d667a1f4250db4255",
    "runs/epic-126/jev-writer-ladder-preregistration-v5.json":
        "42ab5784ec0f536159aedf8f8e83763197425633117d9b0fc0a2d08ecf9b3993",
    "runs/epic-126/jev-six-form-coverage-audit-v1.json":
        "73751bed24776e851f76e63dec427dafc1b458624bc56efdf96612fcfc568dcb",
    "runs/epic-126/jev-writer-exact-bridge-v5.jsonl":
        "4ea9f91decba5c504bb2726e178f36ed6cd845bba635876c822aa72d53c9a5de",
    "runs/epic-126/jev-writer-exact-bridge-report-v5.json":
        "325206d9c51a56c10195265e7f699e78b57b762b9d243160d52cdd63c58aef2d",
}


@dataclass(frozen=True)
class CoveragePlan:
    """Runtime plan regenerated from the locked registration."""

    instance_ids: tuple[str, ...]
    prompt_form_ids: Mapping[str, str]
    form_membership: Mapping[str, tuple[str, ...]]
    planned_cases: int
    planned_ling: int
    planned_jev: int
    planned_requests: int
    ling_request_cap: int
    jev_request_cap: int
    request_cap: int
    cost_cap_usd: float
    worst_case_call_cost_usd: float
    worst_case_next_call_cost_usd: float
    registration_hash: str
    protocol_key: str
    model: str
    endpoint: str
    ling_model: str
    ling_endpoint: str
    token_budget: int
    seed_algorithm: str

    def to_dict(self) -> dict[str, Any]:
        return {"instance_ids": list(self.instance_ids),
                "planned_cases": self.planned_cases,
                "planned_calls": {"ling": self.planned_ling, "jev": self.planned_jev,
                                  "combined": self.planned_requests},
                "ling_request_cap": self.ling_request_cap,
                "jev_request_cap": self.jev_request_cap,
                "request_cap": self.request_cap,
                "cost_cap_usd": self.cost_cap_usd,
                "worst_case_call_cost_usd": self.worst_case_call_cost_usd,
                "worst_case_next_call_cost_usd": self.worst_case_next_call_cost_usd,
                "registration_hash": self.registration_hash,
                "protocol_key": self.protocol_key,
                "model": self.model, "endpoint": self.endpoint,
                "ling_model": self.ling_model, "ling_endpoint": self.ling_endpoint,
                "token_budget": self.token_budget, "seed_algorithm": self.seed_algorithm}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_locked_registration(*, repo_root: Path | None = None,
                             pinned_hash: str | None = None) -> dict[str, Any]:
    """Load only the locked v6 registration; fail closed on status/hash drift."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    path = root / prv6.DEFAULT_OUTPUT_V6
    if not path.is_file():
        raise ValueError("v6 registration missing")
    registration = json.loads(path.read_text(encoding="utf-8"))
    if registration.get("preregistration_version") != prv6.COVERAGE_PREREG_VERSION:
        raise ValueError("wrong registration version")
    if registration.get("status") != prv6.COVERAGE_LOCKED_STATUS:
        raise ValueError("registration is not locked")
    if registration.get("live_collection_authorized") is not False:
        raise ValueError("live_collection_authorized must be false")
    if registration.get("approval", {}).get("live_collection_authorized") is not False:
        raise ValueError("registration approval must not authorize live collection")
    if pinned_hash is not None and registration.get("preregistration_hash") != pinned_hash:
        raise ValueError("registration hash drift")
    return registration


def build_coverage_plan(registration: Mapping[str, Any]
                        ) -> tuple[CoveragePlan, list[Any]]:
    """Regenerate the exact registered manifest and verify order/form membership."""

    selection, instances = prv6.select_form_balanced_manifest()
    manifest = registration.get("manifest", {})
    registered_ids = [str(item) for item in manifest.get("instance_ids", [])]
    if selection["instance_ids"] != registered_ids:
        raise ValueError("regenerated manifest differs from the registered instance order")
    if len(registered_ids) != prv6.BLOCK_N or len(set(registered_ids)) != prv6.BLOCK_N:
        raise ValueError("registered manifest must be 36 unique instance ids")
    regenerated_membership = {form: tuple(ids)
                              for form, ids in selection["form_membership"].items()}
    registered_membership = {form: tuple(ids) for form, ids in
                             (manifest.get("form_membership") or {}).items()}
    if regenerated_membership != registered_membership:
        raise ValueError("regenerated form membership differs from the registration")
    if any(len(ids) != prv6.INSTANCES_PER_FORM for ids in registered_membership.values()) \
            or set(registered_membership) != set(prv6.FROZEN_FORM_IDS):
        raise ValueError("registration must hold exactly six instances per frozen form")
    prompt_form_ids = audit.pre_read_form_ids(instances)
    if set(prompt_form_ids.values()) != set(prv6.FROZEN_FORM_IDS):
        raise ValueError("regenerated prompt forms differ from the frozen six-form set")

    caps = registration.get("caps", {})
    planned = caps.get("planned_calls", {})
    partition = caps.get("provider_partition", {})
    protocol = registration.get("model_and_protocol", {})
    treatment = registration.get("treatment", {})
    per_call = float(caps.get("worst_case_call_cost_usd", 0.0))
    plan = CoveragePlan(
        instance_ids=tuple(registered_ids),
        prompt_form_ids={instance_id: prompt_form_ids[instance_id]
                         for instance_id in registered_ids},
        form_membership={form: tuple(ids) for form, ids in registered_membership.items()},
        planned_cases=prv6.BLOCK_N,
        planned_ling=int(planned.get("ling", -1)),
        planned_jev=int(planned.get("jev", -1)),
        planned_requests=int(planned.get("combined", -1)),
        ling_request_cap=int(partition.get("ling", -1)),
        jev_request_cap=int(partition.get("jev", -1)),
        request_cap=int(caps.get("physical_requests", -1)),
        cost_cap_usd=float(caps.get("cost_cap_usd", 0.0)),
        worst_case_call_cost_usd=per_call,
        worst_case_next_call_cost_usd=round(
            per_call * (1 + max(pr.LING_MAX_RETRIES, pr.JEV_REPLAY_MAX_RETRIES)), 12),
        registration_hash=str(registration.get("preregistration_hash", "")),
        protocol_key=str(protocol.get("protocol_key", "")),
        model=str(protocol.get("model", "")),
        endpoint=str(protocol.get("endpoint", "")),
        ling_model=str(protocol.get("ling_model", "")),
        ling_endpoint=str(protocol.get("ling_endpoint", "")),
        token_budget=int(treatment.get("token_budget", -1)),
        seed_algorithm=str(treatment.get("seed_algorithm", "")),
    )
    if (plan.planned_ling, plan.planned_jev, plan.planned_requests) != (144, 36, 180):
        raise ValueError("registered planned calls must be 144/36/180")
    if (plan.ling_request_cap, plan.jev_request_cap, plan.request_cap) != (432, 108, 540):
        raise ValueError("registered physical partitions must be 432/108/540")
    if plan.ling_request_cap + plan.jev_request_cap != plan.request_cap:
        raise ValueError("provider partitions must sum to the combined cap")
    return plan, instances


def construct_coverage_runtime(registration: Mapping[str, Any], *,
                               clock: Callable[[], float] | None = None,
                               sleep_fn: Callable[[float], None] | None = None
                               ) -> tuple[Any, Any, CoveragePlan, list[Any]]:
    """Build the transports with exactly the registered physical partitions."""

    plan, instances = build_coverage_plan(registration)
    receiver = jc2.JevChoiceAdapterV2(
        JevChoiceClient(model=plan.model, max_physical_requests=plan.jev_request_cap),
        model=plan.model)
    writer_kwargs: dict[str, Any] = {"max_physical_requests": plan.ling_request_cap}
    if clock is not None:
        writer_kwargs["clock"] = clock
    if sleep_fn is not None:
        writer_kwargs["sleep_fn"] = sleep_fn
    writer = writer_v5.LingWriterClientV5(**writer_kwargs)
    return receiver, writer, plan, instances


def verify_coverage_bridge_preflight(plan: CoveragePlan,
                                     registration: Mapping[str, Any],
                                     receiver: Any, writer: Any, *,
                                     repo_root: Path,
                                     approval: str | None,
                                     ling_key_present: bool | None = None,
                                     check_credentials: bool = True,
                                     require_approval: bool = True,
                                     pinned_hash: str | None = None
                                     ) -> dict[str, Any]:
    """Named-check, fail-closed preflight. Never issues a provider request."""

    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    check("approval_present", bool(approval) or not require_approval, None)
    verification = prv6.verify_against_coverage_manifest_preregistration_v6(
        registration, repo_root=repo_root)
    check("registration_verifies", verification["ok"], verification["errors"])
    check("registration_hash_matches",
          registration.get("preregistration_hash") == plan.registration_hash,
          plan.registration_hash)
    if pinned_hash is not None:
        check("pinned_hash_matches", plan.registration_hash == pinned_hash, plan.registration_hash)
    check("status_locked", registration.get("status") == prv6.COVERAGE_LOCKED_STATUS,
          registration.get("status"))
    check("live_collection_not_authorized",
          registration.get("live_collection_authorized") is False
          and registration.get("approval", {}).get("live_collection_authorized") is False
          and registration.get("lock_is_not_live_authorization") is True, None)

    runner_policy = registration.get("runner_policy", {})
    source_files = list((registration.get("generator", {}) or {}).get("source_files", []))
    check("runner_policy_satisfied",
          runner_policy.get("runner_implemented") is True
          and runner_policy.get("runner_source_files") == [prv6.RUNNER_SOURCE_REL]
          and prv6.RUNNER_SOURCE_REL in source_files
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
          and all(form_counts.get(form) == 6 for form in prv6.FROZEN_FORM_IDS)
          and set(manifest.get("iso_form_ids", [])) == set(prv6.FROZEN_FORM_IDS), None)
    disjointness = manifest.get("disjointness", {})
    check("manifest_disjointness", disjointness.get("ok") is True
          and not disjointness.get("overlap"), None)
    design = registration.get("coverage_design", {})
    check("fixed_n_and_no_replacement",
          design.get("fixed_n") is True
          and design.get("n") == 36
          and bool(design.get("no_stopping_after_first_message"))
          and bool(design.get("no_stopping_after_form_exposure"))
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
          and protocol.get("max_retries") == pr.JEV_REPLAY_MAX_RETRIES
          and protocol.get("retryable_statuses") == sorted(jc.JEV_RETRYABLE_STATUSES), None)
    check("jev_protocol_key",
          plan.protocol_key == protocol.get("protocol_key")
          and jc2.is_jev_v2_protocol_key(plan.protocol_key)
          and not jc.is_jev_protocol_key(plan.protocol_key)
          and plan.protocol_key == prv6.protocol_key_v6(), plan.protocol_key)
    check("jev_partition_matches",
          getattr(client, "max_physical_requests", None) == plan.jev_request_cap == 108,
          getattr(client, "max_physical_requests", None))

    treatment = registration.get("treatment", {})
    check("ling_model_matches", writer.model == plan.ling_model == protocol.get("ling_model")
          == pr.LING_MODEL, writer.model)
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
          and treatment.get("seed_algorithm") == ladder.EXACT_BRIDGE_SEED_ALGORITHM, None)
    check("token_budget_matches", plan.token_budget == 1024
          == ladder.EXACT_BRIDGE_TOKEN_BUDGET
          == treatment.get("token_budget"), plan.token_budget)
    check("grammar_and_prompt_path",
          treatment.get("writer_prompt", {}).get("prompt_schema_version")
          == bd.PROMPT_SCHEMA_VERSION
          and "treatment_prompt" in str(treatment.get("writer_prompt", {}).get("path", "")),
          None)
    check("two_agents_two_turns",
          treatment.get("turns") == ladder.EXACT_BRIDGE_TURNS
          and list(treatment.get("agents", [])) == list(ladder.EXACT_BRIDGE_AGENTS), None)
    check("ling_partition_matches",
          getattr(writer, "max_physical_requests", None) == plan.ling_request_cap == 432,
          getattr(writer, "max_physical_requests", None))

    caps = registration.get("caps", {})
    check("combined_cap_and_partitions",
          plan.jev_request_cap + plan.ling_request_cap == plan.request_cap == 540
          and caps.get("physical_requests") == 540, plan.request_cap)
    check("planned_within_caps",
          plan.planned_ling <= plan.ling_request_cap
          and plan.planned_jev <= plan.jev_request_cap
          and plan.planned_requests <= plan.request_cap
          and (plan.planned_ling, plan.planned_jev, plan.planned_requests) == (144, 36, 180),
          {"ling": plan.planned_ling, "jev": plan.planned_jev,
           "combined": plan.planned_requests})
    check("cost_cap_and_guard",
          plan.cost_cap_usd == 1.0
          and float(caps.get("worst_case_cost_usd", 1e9)) <= plan.cost_cap_usd
          and plan.worst_case_next_call_cost_usd >= plan.worst_case_call_cost_usd,
          {"cost_cap_usd": plan.cost_cap_usd,
           "worst_case_cost_usd": caps.get("worst_case_cost_usd"),
           "worst_case_next_call_cost_usd": plan.worst_case_next_call_cost_usd})

    outputs = registration.get("outputs", {})
    journal_path = repo_root / str(outputs.get("journal", prv6.DEFAULT_JOURNAL_V6))
    report_path = repo_root / str(outputs.get("report", prv6.DEFAULT_REPORT_V6))
    check("journal_path_fresh", not journal_path.exists(), str(journal_path))
    check("report_path_fresh", not report_path.exists(), str(report_path))

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
    check("frozen_v1_v5_and_189_inputs_unchanged",
          all(item["ok"] for item in frozen),
          [item["path"] for item in frozen if not item["ok"]])

    return {"ok": all(item["ok"] for item in checks), "checks": checks,
            "failed": [item["check"] for item in checks if not item["ok"]],
            "registration_verification": verification,
            "frozen_inputs": frozen}


def _blocked(reason: str, approval: str | None, plan: CoveragePlan | None) -> dict[str, Any]:
    return {"mode": COVERAGE_BRIDGE_VERSION, "status": "blocked", "stop_reason": reason,
            "approval": approval,
            "registration_hash": plan.registration_hash if plan else None,
            "planned_cases": plan.planned_cases if plan else None,
            "provider_calls": 0,
            "raw_response_retained": False, "credentials_retained": False}


def summarize_coverage(cases: Sequence[Mapping[str, Any]], *,
                       counted_exposures: int) -> dict[str, Any]:
    """Aggregate the coverage report; the formal decision belongs to #192."""

    by_form: dict[str, dict[str, Any]] = {
        form: {"planned_cases": prv6.INSTANCES_PER_FORM, "attempted_cases": 0,
               "receiver_valid_cases": 0, "b_writer_opportunities": 0,
               "accepted_b_messages": 0, "eligible_b_to_a_events": 0,
               "deliberate_silence_outcomes": 0, "rejected_write_attempts": 0}
        for form in sorted(prv6.FROZEN_FORM_IDS)}
    writer_totals: dict[str, int] = {}
    writer_by_agent_turn: dict[str, int] = {}
    tiers: dict[str, int] = {}
    renormalized = 0
    writes_by_author: dict[str, int] = {"A": 0, "B": 0}
    authoritative = 0
    gross_bits = 0.0
    rejected_writes = 0
    exposures_recounted = 0
    eligible_events = 0
    eligible_claims = 0
    for case in cases:
        form = str(case.get("prompt_form_id"))
        block = by_form.get(form)
        if block is None:
            continue
        block["attempted_cases"] += 1
        if case.get("receiver_valid"):
            block["receiver_valid_cases"] += 1
        for outcome in case.get("writer_outcomes") or ():
            agent = str(outcome.get("agent"))
            key = f"{agent}|{outcome.get('turn')}|{outcome.get('outcome')}"
            writer_by_agent_turn[key] = writer_by_agent_turn.get(key, 0) + 1
            name = str(outcome.get("outcome"))
            writer_totals[name] = writer_totals.get(name, 0) + 1
            if agent == "B":
                block["b_writer_opportunities"] += 1
            if name == "deliberate_silence":
                block["deliberate_silence_outcomes"] += 1
            if name == "non_owned_claim":
                block["rejected_write_attempts"] += 1
        block["rejected_write_attempts"] += len(case.get("rejected") or ())
        for row in case.get("board") or ():
            if row.get("status") == "accepted":
                writes_by_author[str(row.get("author"))] = writes_by_author.get(
                    str(row.get("author")), 0) + 1
                if str(row.get("author")) == "B":
                    block["accepted_b_messages"] += 1
                if row.get("delta_i_bits") is not None:
                    authoritative += 1
                    gross_bits += float(row["delta_i_bits"])
        for event in case.get("board_log") or ():
            if event.get("kind") == "peer_read_exposure":
                exposures_recounted += 1
        tier = str(case.get("normalization_tier") or "missing")
        tiers[tier] = tiers.get(tier, 0) + 1
        if case.get("renormalized"):
            renormalized += 1
        if case.get("replay_eligible"):
            eligible_events += 1
            eligible_claims += len((case.get("replay_selection") or {}).get("selected") or ())
            block["eligible_b_to_a_events"] += 1

    covered = sorted(form for form, block in by_form.items()
                     if block["eligible_b_to_a_events"] > 0)
    missing = sorted(set(prv6.FROZEN_FORM_IDS) - set(covered))

    return {
        "per_form": by_form,
        "forms_with_eligible_exposure": len(covered),
        "forms_with_eligible_exposure_ids": covered,
        "missing_forms": missing,
        "writer_outcome_totals": dict(sorted(writer_totals.items())),
        "writer_outcomes_by_agent_turn": dict(sorted(writer_by_agent_turn.items())),
        "writer_invalid_cases": sum(
            1 for case in cases
            if any(str(outcome.get("outcome")) in bridge.STOP_WRITER_OUTCOMES
                   for outcome in case.get("writer_outcomes") or ())),
        "normalization": {"tiers": dict(sorted(tiers.items())),
                          "renormalized_cases": renormalized},
        "messages_by_direction": {"b_to_a": writes_by_author.get("B", 0),
                                  "a_to_b": writes_by_author.get("A", 0)},
        "writes_by_agent": dict(sorted(writes_by_author.items())),
        "authoritative_i_m": authoritative,
        "i_m_bits": round(gross_bits, 9),
        "i_m_bits_label": ("gross transmitted bits over all accepted messages (both directions, "
                           "with within-event repeats); not unique information delivered to A"),
        "verified_read_exposures": exposures_recounted,
        "verified_read_exposures_counted": counted_exposures,
        "replay_eligible_events": eligible_events,
        "replay_eligible_claims": eligible_claims,
        "one_deduplicated_claim_per_pre_read_state": eligible_claims == eligible_events,
        "replay_eligibility_source": ("apart_incident_response.jev_six_form_coverage_audit."
                                      "select_replay_claims (#189 authoritative selector)"),
        "coverage_decision_pending_192": True,
        "replay_started": False,
        "coverage_note": ("collection only: observed coverage is reported; the formal coverage "
                          "decision belongs to #192 and this run does not start #159"),
        "seeds_replaced": 0,
    }


def execute_coverage_bridge(plan: CoveragePlan, receiver: Any, writer: Any,
                            verification: Mapping[str, Any],
                            instances: Sequence[Any], *,
                            approval: str | None,
                            registration: Mapping[str, Any],
                            pinned_hash: str | None = None,
                            journal_path: Path | None = None,
                            report_path: Path | None = None,
                            sleep_fn: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Run fixed N=36 over the registered manifest with durable per-case rows."""

    outputs = registration.get("outputs", {})
    journal_path = journal_path if journal_path is not None else Path(
        str(outputs.get("journal", prv6.DEFAULT_JOURNAL_V6)))
    report_path = report_path if report_path is not None else Path(
        str(outputs.get("report", prv6.DEFAULT_REPORT_V6)))

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
        "instance_ids": list(plan.instance_ids),
        "prompt_forms": sorted(set(plan.prompt_form_ids.values())),
        "planned_cases": plan.planned_cases,
        "planned_requests": plan.planned_requests,
        "planned_calls": {"ling": plan.planned_ling, "jev": plan.planned_jev,
                          "combined": plan.planned_requests},
        "partitions": {"ling": plan.ling_request_cap, "jev": plan.jev_request_cap,
                       "combined": plan.request_cap},
        "attempted_cases": 0, "receiver_valid_cases": 0, "receiver_invalid_cases": 0,
        "receiver_unattempted_cases": 0,
        "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0,
        "cost_cap_usd": plan.cost_cap_usd,
        "worst_case_next_call_cost_usd": plan.worst_case_next_call_cost_usd,
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

    def guards_ok(extra_calls: int, *, ling: bool) -> bool:
        ling_attempts = int(getattr(writer, "physical_attempts", 0) or 0)
        jev_attempts = int(getattr(receiver.client, "physical_attempts", 0) or 0)
        combined = ling_attempts + jev_attempts
        if ling and ling_attempts + extra_calls > plan.ling_request_cap:
            return False
        if not ling and jev_attempts + extra_calls > plan.jev_request_cap:
            return False
        if combined + extra_calls > plan.request_cap:
            return False
        return (report["estimated_cost_usd"]
                + plan.worst_case_next_call_cost_usd * extra_calls <= plan.cost_cap_usd)

    counted_exposures = 0
    try:
        for instance_id in plan.instance_ids:
            instance = by_id[instance_id]
            if report["attempted_cases"] > 0:
                sleep_fn(CASE_PACE_SECONDS)
            report["attempted_cases"] += 1
            run_id = f"coverage-{instance_id}"
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
                    report["input_tokens"] += int(outcome.get("input_tokens") or 0)
                    report["output_tokens"] += int(outcome.get("output_tokens") or 0)
                    report["estimated_cost_usd"] = estimate_cost_usd(report["input_tokens"])
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
                "renormalized": None, "request_hash": None, "state_hash": None,
                "protocol_key": plan.protocol_key, "resolved_model": None,
                "option_ids": sorted(instance.solutions), "target_id": instance.target,
                "selected_option_id": None, "confidence": None,
                "probabilities": {}, "raw_probabilities": {},
                "probability_diagnostics": None, "usage": {},
                "i_m_bits": None, "eligible_exposure": False,
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
                        report["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
                        report["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
                        report["estimated_cost_usd"] = estimate_cost_usd(report["input_tokens"])
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
                    receiver_row["eligible_exposure"] = bool(b_accepted)
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
            selection = audit.select_replay_claims(receiver_row, instance)
            receiver_row["replay_selection"] = selection
            receiver_row["replay_eligible"] = bool(selection["eligible"] and receiver_valid)
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
    summary = summarize_coverage(report["cases"], counted_exposures=counted_exposures)
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
    parser = argparse.ArgumentParser(description="#191 fresh six-form L4X coverage runner v6")
    parser.add_argument("--live", action="store_true",
                        help="execute collection (requires --approval; never run offline)")
    parser.add_argument("--approval", help="reviewer authorization reference for live collection")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--journal", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
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
        require_approval=bool(args.live))
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
    journal_path = args.journal if args.journal is not None else root / str(
        registration["outputs"]["journal"])
    report_target = args.report if args.report is not None else root / str(
        registration["outputs"]["report"])
    report = execute_coverage_bridge(
        plan, receiver, writer, verification, instances, approval=args.approval,
        registration=registration, pinned_hash=registration_hash,
        journal_path=journal_path, report_path=report_target)
    if report.get("status") != "blocked":
        target = report_target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                          encoding="utf-8")
    print(json.dumps({key: report.get(key) for key in
                      ("mode", "status", "stop_reason", "attempted_cases",
                       "receiver_valid_cases", "forms_with_eligible_exposure",
                       "coverage_decision_pending_192", "replay_started")},
                     indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "COVERAGE_BRIDGE_VERSION", "RECEIVER_AGENT", "CASE_PACE_SECONDS",
    "FROZEN_INPUT_SHA256", "CoveragePlan", "load_locked_registration",
    "build_coverage_plan", "construct_coverage_runtime",
    "verify_coverage_bridge_preflight", "summarize_coverage",
    "execute_coverage_bridge", "main",
]
