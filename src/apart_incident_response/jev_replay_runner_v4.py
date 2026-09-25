"""#195 — source-bound matched Jev replay-v4 runner (offline; live gated).

Executes the frozen real/placebo/null replay from the locked v4
registration: event-major over the #192 decision order, the counterbalanced
branch schedule, one durable fsync'd journal row per logical
``(event_id, branch)``, the registered stop/retry/suspect/provider-failure
rules, and the registered equal-form analysis. Every request and state hash
is recomputed and verified against the registration before any Jev call.

Offline by construction: no provider call happens before every preflight
check passes and an explicit runtime approval is supplied;
``live_collection_authorized`` on the registration stays false, and binding
this runner does not authorize execution. No Ling call exists in the design.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import jev_choice as jc
from . import jev_choice_v2 as jc2
from . import jev_replay as jr
from . import jev_replay_inference as ji
from . import jev_replay_preregistration as pr
from . import jev_replay_preregistration_v2 as prv2
from . import jev_replay_preregistration_v4 as prv4
from .communication_protocol import DependenceRegime, ReasoningComplexity


REPLAY_RUNNER_VERSION = "jev-choice-replay-runner-v4"
RUNNER_SOURCE_REL = "src/apart_incident_response/jev_replay_runner_v4.py"
RECEIVER_AGENT = "A"

PROVIDER_FAILURE_CLASSES = frozenset({"transport_error", "provider_rejected",
                                      "missing_credentials"})
SUSPECT_NONTERMINAL_CLASSES = frozenset({"not_normalized_suspect"})
#: Everything else in the v2 invalid-class set stops the run immediately.
TERMINAL_INVALID_CLASSES = frozenset(jc2.JEV_V2_INVALID_CLASSES) \
    - PROVIDER_FAILURE_CLASSES - SUSPECT_NONTERMINAL_CLASSES


class BranchJournalError(RuntimeError):
    """Raised on duplicate branch keys or journal write failures (fail closed)."""


class BranchJournal:
    """Append-only branch-attempt journal: one durable row per (event_id, branch)."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.handle = path.open("x", encoding="utf-8")
        self.keys: set[tuple[str, str]] = set()
        self.rows = 0
        self.fsync_count = 0

    def write(self, row: Mapping[str, Any]) -> None:
        key = (str(row.get("event_id")), str(row.get("branch")))
        if key in self.keys:
            self.close()
            raise BranchJournalError(f"duplicate branch journal key: {key}")
        self.handle.write(json.dumps(dict(row), sort_keys=True, allow_nan=False) + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.fsync_count += 1
        self.rows += 1
        self.keys.add(key)

    def close(self) -> None:
        if not self.handle.closed:
            self.handle.close()

    def read_rows(self) -> list[dict[str, Any]]:
        text = self.path.read_text(encoding="utf-8") if self.path.is_file() else ""
        return [json.loads(line) for line in text.splitlines() if line.strip()]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_locked_registration(*, repo_root: Path | None = None,
                             pinned_hash: str | None = None) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    path = root / prv4.DEFAULT_OUTPUT_V4
    if not path.is_file():
        raise ValueError("v4 replay registration missing")
    registration = json.loads(path.read_text(encoding="utf-8"))
    if registration.get("preregistration_version") != prv4.JEV_REPLAY_V4_PREREG_VERSION:
        raise ValueError("wrong registration version")
    if registration.get("status") != prv4.JEV_REPLAY_V4_LOCKED_STATUS:
        raise ValueError("registration is not locked")
    if registration.get("live_collection_authorized") is not False:
        raise ValueError("live_collection_authorized must be false")
    if pinned_hash is not None and registration.get("preregistration_hash") != pinned_hash:
        raise ValueError("registration hash drift")
    return registration


def build_replay_plan(registration: Mapping[str, Any]
                      ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate the frozen event manifest, feasible sets and branch schedule."""

    events = list(registration.get("events") or [])
    if len(events) != prv4.EXPECTED_EVENT_COUNT:
        raise ValueError("registration must bind exactly 17 events")
    event_ids = [str(event["event_id"]) for event in events]
    if len(set(event_ids)) != len(event_ids):
        raise ValueError("registration event ids are not unique")
    counts: dict[str, int] = {}
    for event in events:
        form = str(event.get("prompt_form_id"))
        if form not in prv4.FROZEN_FORM_IDS:
            raise ValueError(f"event references a non-frozen form: {form}")
        counts[form] = counts.get(form, 0) + 1
        instance = prv4._regenerate_instance(str(event["instance_id"]))
        pre_read = event.get("pre_read") or {}
        authoritative = sorted(str(value) for value in instance.private_solutions["A"])
        if pre_read.get("feasible_set") != authoritative:
            raise ValueError(f"feasible set drift: {event['event_id']}")
        if pre_read.get("feasible_set_hash") != jr.canonical_hash(authoritative):
            raise ValueError(f"feasible set hash drift: {event['event_id']}")
        if pre_read.get("target_id") != str(instance.target):
            raise ValueError(f"target id drift: {event['event_id']}")
    distribution = tuple(counts.get(form, 0) for form in prv4.FROZEN_FORM_IDS)
    if distribution != prv4.EXPECTED_FORM_DISTRIBUTION:
        raise ValueError(f"form distribution {distribution} != 1/4/4/1/4/3")
    schedule = prv4.build_branch_schedule(events)
    if registration.get("branch_schedule") != schedule:
        raise ValueError("branch schedule drift from the frozen construction")
    return events, schedule


def pre_read_state(instance: Any, model: str) -> tuple[Any, dict[str, Any], Any]:
    """Rebuild the frozen receiver-A pre-read state C and its ISO ChoiceState."""

    body, iso_state = prv4.pre_read_body(instance, model)
    state_dict = dict(iso_state.state)
    return iso_state, state_dict, body


def branch_choice_state(adapter: Any, instance: Any, body: Mapping[str, Any],
                        state_dict: Mapping[str, Any], branch: str,
                        message_text: str | None) -> Any:
    """Build the branch ChoiceState so its hash equals the registered hash."""

    branch_body = jr.branch_request_body(body, message_text)
    request_hash = jr.prompt_form_id(branch_body)
    options = tuple(jc.ChoiceOption(option_id=str(label), label=str(label))
                    for label in sorted(instance.solutions))
    branch_state = dict(branch_body["state"])
    if branch not in prv4.BRANCHES:
        raise ValueError(f"unknown branch: {branch}")
    return jc.ChoiceState(instance.instance_id, RECEIVER_AGENT, "COMM",
                          adapter.question_id, options, branch_state,
                          adapter.instructions, request_hash), request_hash


def message_text_for(registration_event: Mapping[str, Any], branch: str) -> str | None:
    real = registration_event.get("real") or {}
    placebo = registration_event.get("placebo") or {}
    if branch == "real":
        return jr.serialize_message(str(real.get("claim")))
    if branch == "placebo":
        return jr.serialize_placebo_message(str(placebo.get("claim")))
    if branch == "null":
        return None
    raise ValueError(f"unknown branch: {branch}")


def branch_metrics(probabilities: Mapping[str, float], *, target_id: str,
                   feasible_set: Sequence[str]) -> dict[str, Any]:
    """Metrics from the accepted normalized vector only."""

    vector = {str(key): float(value) for key, value in probabilities.items()}
    return {"entropy_bits": jr.entropy_bits(vector),
            "p_target": float(vector.get(str(target_id), 0.0)),
            "feasible_mass": sum(float(vector.get(str(value), 0.0))
                                 for value in feasible_set)}


def analyze_replay(event_records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Registered analysis over grouped event records (pure; frozen plan).

    ``event_records`` are report-level records
    ``{event_id, prompt_form_id, branches: {real|placebo|null: {...}}}``.
    Only normalized accepted branch vectors carry metrics. Guards are
    evaluated per event and reported separately — never used to filter the
    primary entropy estimate. The unit is the prompt form.
    """

    forms = sorted({str(record.get("prompt_form_id")) for record in event_records})
    d_by_form: dict[str, list[float]] = defaultdict(list)
    guard_counts = {form: {"complete_pairs": 0, "target_ok": 0, "mass_ok": 0,
                           "useful_uptake": 0,
                           "delta_p_target_sum": 0.0,
                           "delta_feasible_mass_sum": 0.0}
                    for form in forms}
    per_event: list[dict[str, Any]] = []
    null_contrasts: list[dict[str, Any]] = []
    incomplete_branches = 0

    for record in event_records:
        branches = record.get("branches") or {}
        real = branches.get("real") or {}
        placebo = branches.get("placebo") or {}
        null = branches.get("null") or {}
        for branch in (real, placebo, null):
            if not branch.get("valid"):
                incomplete_branches += 1
        complete = bool(real.get("valid") and placebo.get("valid"))
        d_i = None
        guard = None
        if complete:
            d_i = float(real["entropy_bits"]) - float(placebo["entropy_bits"])
            form = str(record["prompt_form_id"])
            d_by_form[form].append(d_i)
            delta_target = float(real["p_target"]) - float(placebo["p_target"])
            delta_mass = float(real["feasible_mass"]) - float(placebo["feasible_mass"])
            target_ok = delta_target >= prv4.GUARDS["target_probability_delta"]
            mass_ok = delta_mass >= -prv4.GUARDS["feasible_set_mass_epsilon"]
            useful = bool((d_i < 0) and target_ok and mass_ok)
            counts = guard_counts[form]
            counts["complete_pairs"] += 1
            counts["target_ok"] += int(target_ok)
            counts["mass_ok"] += int(mass_ok)
            counts["useful_uptake"] += int(useful)
            counts["delta_p_target_sum"] += delta_target
            counts["delta_feasible_mass_sum"] += delta_mass
            guard = {"delta_p_target_i": delta_target,
                     "delta_feasible_mass_i": delta_mass,
                     "target_ok_i": target_ok, "mass_ok_i": mass_ok,
                     "useful_uptake_i": useful}
        null_contrast = None
        if real.get("valid") and null.get("valid"):
            null_contrast = {"real_minus_null": float(real["entropy_bits"])
                             - float(null["entropy_bits"])}
            null_contrasts.append({"event_id": record.get("event_id"),
                                   **null_contrast})
        if real.get("valid") and placebo.get("valid") and null.get("valid"):
            null_contrast = {**(null_contrast or {}),
                             "placebo_minus_null": float(placebo["entropy_bits"])
                             - float(null["entropy_bits"])}
        per_event.append({"event_id": record.get("event_id"),
                          "prompt_form_id": record.get("prompt_form_id"),
                          "complete_pair": complete,
                          "d_i": d_i, "guards": guard,
                          "null_contrast": null_contrast})

    form_means = {form: sum(values) / len(values) for form, values in d_by_form.items()
                  if values}
    ordered_means = [form_means[form] for form in forms if form in form_means]
    k = len(ordered_means)
    interval = None
    sign_flip = None
    if k >= 2:
        mean = sum(ordered_means) / k
        variance = sum((value - mean) ** 2 for value in ordered_means) / (k - 1)
        half_width = ji.t_critical_975(k - 1) * math.sqrt(variance) / math.sqrt(k)
        interval = {"k": k, "df": k - 1, "mean": mean,
                    "t_interval_975": [mean - half_width, mean + half_width]}
    else:
        mean = None

    if k >= 6:
        sign_flip = ji.sign_flip_two_sided(ordered_means)
        inference = {
            "result": "six_form_primary_inference",
            "k": k,
            "form_means": form_means,
            "primary_delta": mean,
            "direction_requirement": "observed equal-form mean must be negative",
            "direction_met": bool(mean is not None and mean < 0),
            "interval": interval,
            "sign_flip": sign_flip,
            "min_two_sided_p": 2 / 64,
            "statement": ("primary registered inference: exhaustive two-sided cluster "
                          "sign-flip over the six form means plus the form-mean t interval "
                          "(df=5), both reported with a negative direction required"),
        }
    elif k == 5:
        inference = {
            "result": "five_form_interval_only",
            "k": k,
            "form_means": form_means,
            "primary_delta": mean,
            "interval": interval,
            "sign_flip": {"reported": False,
                          "forbidden_two_sided_below_0_05": True},
            "causal_gate_released": False,
            "statement": ("only five forms have a complete real/placebo pair: interval-only "
                          "descriptive reporting; a two-sided sign-flip p below 0.05 is "
                          "forbidden and no causal gate is released"),
        }
    else:
        inference = {
            "result": "replay_coverage_failure",
            "k": k,
            "form_means": form_means,
            "primary_delta": mean,
            "interval": interval,
            "sign_flip": {"reported": False},
            "causal_gate_released": False,
            "statement": ("fewer than five forms have a complete real/placebo pair: "
                          "replay-coverage failure"),
        }

    guards_summary = {}
    for form in forms:
        counts = guard_counts[form]
        completed = counts["complete_pairs"]
        guards_summary[form] = {
            "complete_pairs": completed,
            "target_ok": counts["target_ok"],
            "mass_ok": counts["mass_ok"],
            "useful_uptake": counts["useful_uptake"],
            "mean_delta_p_target": (counts["delta_p_target_sum"] / completed
                                    if completed else None),
            "mean_delta_feasible_mass": (counts["delta_feasible_mass_sum"] / completed
                                         if completed else None),
        }
    return {
        "unit": "prompt form",
        "events": len(event_records),
        "complete_pairs": sum(len(values) for values in d_by_form.values()),
        "incomplete_branches": incomplete_branches,
        "per_event": per_event,
        "form_means_d_i": form_means,
        "inference": inference,
        "guards": {
            "delta": prv4.GUARDS["target_probability_delta"],
            "epsilon": prv4.GUARDS["feasible_set_mass_epsilon"],
            "formulas": dict(prv4.GUARD_FORMULAS),
            "per_form": guards_summary,
            "filtered_primary_estimate": False,
            "statement": ("guards are evaluated and reported per event and within form; they "
                          "never remove a valid real/placebo pair from the primary entropy "
                          "estimate, and entropy reduction alone is never useful uptake when "
                          "either guard fails"),
        },
        "null_manipulation_checks": {
            "scope": "retained for real-minus-null and placebo-minus-null; null excluded "
                     "from the primary real-versus-placebo contrast",
            "events_with_real_minus_null": len(null_contrasts),
            "mean_real_minus_null": (sum(item["real_minus_null"] for item in null_contrasts)
                                     / len(null_contrasts)) if null_contrasts else None,
        },
        "missingness": {
            "complete_pairs_by_form": {form: len(d_by_form.get(form, [])) for form in forms},
            "planned_pairs": len(event_records),
            "imputation": "none",
        },
        "claim_limits": [
            "no instance-level t-test or Wilcoxon; the17 events are replicates within six "
            "forms, never independent states",
            "five-form fallback is interval-only descriptive with sub-0.05 sign-flip "
            "forbidden; below five forms is replay-coverage failure",
            "inference is conditional on the six frozen forms and the paid Ling route that "
            "generated the messages",
        ],
    }


def verify_replay_runner_preflight(registration: Mapping[str, Any], receiver: Any, *,
                                   repo_root: Path, approval: str | None,
                                   check_credentials: bool = True,
                                   require_approval: bool = True,
                                   pinned_hash: str | None = None,
                                   journal_exists: bool | None = None,
                                   report_exists: bool | None = None) -> dict[str, Any]:
    """Named-check, fail-closed preflight; never issues a provider request."""

    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    check("approval_present", bool(approval) or not require_approval, None)
    verification = prv4.verify_against_jev_replay_preregistration_v4(
        registration, repo_root=repo_root, require_approval=require_approval,
        journal_exists=journal_exists, report_exists=report_exists)
    check("registration_verifies", verification["ok"], verification["errors"])
    check("registration_hash_matches",
          registration.get("preregistration_hash") == pinned_hash
          if pinned_hash is not None else True, registration.get("preregistration_hash"))
    check("status_locked", registration.get("status") == prv4.JEV_REPLAY_V4_LOCKED_STATUS,
          registration.get("status"))
    check("live_collection_not_authorized",
          registration.get("live_collection_authorized") is False
          and registration.get("approval", {}).get("live_collection_authorized") is False
          and registration.get("lock_is_not_live_authorization") is True, None)

    runner_policy = registration.get("runner_policy", {})
    source_files = list(registration.get("source_files") or [])
    check("runner_policy_satisfied",
          runner_policy.get("runner_implemented") is True
          and runner_policy.get("runner_source_files") == [RUNNER_SOURCE_REL]
          and runner_policy.get("runner_source_bound") is True
          and RUNNER_SOURCE_REL in source_files, runner_policy.get("runner_source_files"))
    check("runner_not_live_authorization",
          runner_policy.get("adding_runner_authorizes_collection") is False
          and "does not authorize execution" in str(runner_policy.get("policy", ""))
          and "separate explicit authorization" in str(
              runner_policy.get("live_execution_rule", "")), None)

    check("source_treatment_hashes_wellformed",
          all(isinstance(registration.get(key), str) and len(registration.get(key)) == 64
              for key in ("source_files_hash", "treatment_hash", "message_wording_hash")), None)

    try:
        events, schedule = build_replay_plan(registration)
        check("event_manifest_and_schedule_verified", True,
              {"events": len(events),
               "distribution": list(prv4.EXPECTED_FORM_DISTRIBUTION)})
        event_ids = [str(event["event_id"]) for event in events]
        check("event_ids_exact_unique_ordered",
              len(set(event_ids)) == 17
              and schedule.get("event_order") == event_ids, None)
        check("branch_schedule_event_major",
              schedule.get("event_major") is True
              and schedule.get("allowed_branches") == list(prv4.BRANCHES)
              and schedule.get("position_balance", {}).get("max_position_difference") <= 1
              and schedule.get("position_balance", {}).get("per_branch_totals")
              == {"null": 17, "placebo": 17, "real": 17}, None)
        check("feasible_set_hashes_verified", True,
              "all 17 events match the regenerated authoritative feasible sets")
    except ValueError as exc:
        check("event_manifest_and_schedule_verified", False, str(exc))

    protocol = registration.get("model_and_protocol") or {}
    client = receiver.client
    check("jev_model_matches", protocol.get("model") == pr.JEV_REPLAY_MODEL
          == getattr(receiver, "model", None), protocol.get("model"))
    check("jev_endpoint_matches", protocol.get("endpoint") == pr.JEV_REPLAY_ENDPOINT
          == getattr(client, "endpoint", None), protocol.get("endpoint"))
    check("jev_retry_policy",
          protocol.get("max_retries") == pr.JEV_REPLAY_MAX_RETRIES
          and getattr(client, "max_retries", None) == pr.JEV_REPLAY_MAX_RETRIES
          and protocol.get("retryable_statuses") == sorted(jc.JEV_RETRYABLE_STATUSES), None)
    key = str(protocol.get("protocol_key") or "")
    check("jev_protocol_key", bool(key) and not jc.is_jev_protocol_key(key)
          and jc2.is_jev_v2_protocol_key(key) and key == prv4.prv6_protocol_key(), key)
    check("codec_version", protocol.get("codec_version") == jc2.JEV_CHOICE_V2_CODEC_VERSION,
          protocol.get("codec_version"))
    check("normalization_policy",
          protocol.get("normalization_policy_hash") == prv2.normalization_policy_hash()
          and protocol.get("normalization_policy") == prv2.normalization_policy(), None)

    check("request_state_option_treatment_hashes", verification["ok"],
          "per-event hashes are recomputed inside registration_verifies")

    outputs = registration.get("outputs") or {}
    journal_path = repo_root / str(outputs.get("journal", prv4.DEFAULT_JOURNAL_V4))
    report_path = repo_root / str(outputs.get("report", prv4.DEFAULT_REPORT_V4))
    journal_bad = journal_exists if journal_exists is not None else journal_path.exists()
    report_bad = report_exists if report_exists is not None else report_path.exists()
    check("journal_path_fresh", not journal_bad, str(journal_path))
    check("report_path_fresh", not report_bad, str(report_path))

    if check_credentials:
        credentials = jc.load_jev_credentials()
        check("jev_credentials_present", bool(credentials.present and credentials.shape_ok),
              credentials.redacted())

    caps = registration.get("caps") or {}
    planned = caps.get("planned_calls") or {}
    partition = caps.get("provider_partition") or {}
    check("jev_physical_cap_enforced",
          getattr(client, "max_physical_requests", None) == 153
          and caps.get("physical_requests") == 153 and partition.get("jev") == 153,
          getattr(client, "max_physical_requests", None))
    check("planned_calls_51_0",
          (planned.get("jev"), planned.get("ling"), planned.get("combined")) == (51, 0, 51),
          planned)
    check("cost_caps_and_reserve",
          caps.get("cost_cap_usd") == prv4.COST_CAP_USD
          and caps.get("worst_case_cost_usd") == prv4.WORST_CASE_COST_USD
          and caps.get("worst_case_next_call_cost_usd") == prv4.NEXT_CALL_RESERVE_USD
          and float(caps.get("worst_case_cost_usd", 1e9)) <= float(caps.get("cost_cap_usd", 0.0)),
          {"cost_cap_usd": caps.get("cost_cap_usd"),
           "worst_case_cost_usd": caps.get("worst_case_cost_usd"),
           "next_call_reserve": caps.get("worst_case_next_call_cost_usd")})
    check("upstream_192_hashes_verified", verification["ok"],
          "decision artifact and upstream pins are recomputed inside registration_verifies")

    return {"ok": all(item["ok"] for item in checks), "checks": checks,
            "failed": [item["check"] for item in checks if not item["ok"]],
            "registration_verification": verification}


def _blocked(reason: str, approval: str | None,
             registration: Mapping[str, Any]) -> dict[str, Any]:
    return {"mode": REPLAY_RUNNER_VERSION, "status": "blocked", "stop_reason": reason,
            "approval": approval,
            "registration_hash": registration.get("preregistration_hash"),
            "planned_events": prv4.EXPECTED_EVENT_COUNT,
            "provider_calls": 0,
            "raw_response_retained": False, "credentials_retained": False}


def execute_replay_runner(registration: Mapping[str, Any], receiver: Any, *,
                          verification: Mapping[str, Any],
                          approval: str | None,
                          pinned_hash: str | None = None,
                          journal_path: Path | None = None,
                          report_path: Path | None = None,
                          sleep_fn: Callable[[float], None] = time.sleep,
                          ) -> dict[str, Any]:
    """Run the frozen replay schedule with the registered journal and stops."""

    outputs = registration.get("outputs", {})
    journal_path = journal_path if journal_path is not None else Path(
        str(outputs.get("journal", prv4.DEFAULT_JOURNAL_V4)))
    report_path = report_path if report_path is not None else Path(
        str(outputs.get("report", prv4.DEFAULT_REPORT_V4)))
    if not approval:
        return _blocked("missing_approval", approval, registration)
    if not verification.get("ok"):
        return _blocked("preflight_failed", approval, registration)
    if pinned_hash is not None and registration.get("preregistration_hash") != pinned_hash:
        return _blocked("registration_hash_mismatch", approval, registration)
    if getattr(receiver.client, "max_physical_requests", None) != 153:
        return _blocked("partition_not_enforced", approval, registration)
    if journal_path.exists():
        return _blocked("output_exists", approval, registration)
    if report_path.exists():
        return _blocked("report_exists", approval, registration)
    try:
        events, schedule = build_replay_plan(registration)
    except ValueError as exc:
        return _blocked(f"plan_drift: {exc}", approval, registration)
    by_event_id = {str(event["event_id"]): event for event in events}
    instance_cache: dict[str, Any] = {}
    protocol_key = registration["model_and_protocol"]["protocol_key"]
    cost_cap = float(registration["caps"]["cost_cap_usd"])
    adapter = receiver
    report: dict[str, Any] = {
        "mode": REPLAY_RUNNER_VERSION, "status": "completed", "stop_reason": None,
        "approval": approval,
        "registration_hash": registration.get("preregistration_hash"),
        "protocol_key": protocol_key, "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
        "model": pr.JEV_REPLAY_MODEL,
        "planned": {"events": prv4.EXPECTED_EVENT_COUNT, "branches": 51,
                    "by_branch": {"real": 17, "placebo": 17, "null": 17}},
        "attempted_branches": 0, "valid_branches": 0, "invalid_branches": 0,
        "unattempted_branches": 51,
        "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0,
        "cost_cap_usd": cost_cap,
        "physical_attempts": {"jev": 0, "cap": 153},
        "events": [], "raw_response_retained": False, "credentials_retained": False,
    }
    journal: BranchJournal | None = None
    stop_reason: str | None = None
    consecutive_provider_failures = 0
    rows: list[dict[str, Any]] = []

    def stop(reason: str) -> None:
        nonlocal stop_reason
        if stop_reason is None:
            stop_reason = reason
            report["status"] = "stopped"
            report["stop_reason"] = reason

    try:
        journal = BranchJournal(journal_path)
        for event_index, event_id in enumerate(schedule["event_order"]):
            if stop_reason is not None:
                break
            registration_event = by_event_id[event_id]
            instance_id = str(registration_event["instance_id"])
            instance = instance_cache.get(instance_id)
            if instance is None:
                instance = prv4._regenerate_instance(instance_id)
                instance_cache[instance_id] = instance
            pre_read = registration_event.get("pre_read") or {}
            _, state_dict, body = pre_read_state(instance, pr.JEV_REPLAY_MODEL)
            if jr.canonical_hash(state_dict) != pre_read.get("state_hash") \
                    or jr.prompt_form_id(body) != pre_read.get("request_body_hash"):
                stop("pre_read_hash_mismatch")
                break
            form_id = str(registration_event["prompt_form_id"])
            for branch_position, branch in enumerate(schedule["schedule"][event_id],
                                                     start=1):
                if stop_reason is not None:
                    break
                extra_physical = 1 + pr.JEV_REPLAY_MAX_RETRIES
                jev_attempts = int(getattr(receiver.client, "physical_attempts", 0) or 0)
                if jev_attempts + extra_physical > 153:
                    stop("request_cap")
                    break
                if report["estimated_cost_usd"] + prv4.NEXT_CALL_RESERVE_USD > cost_cap:
                    stop("cost_cap")
                    break
                text = message_text_for(registration_event, branch)
                try:
                    choice_state, request_hash = branch_choice_state(
                        adapter, instance, body, state_dict, branch, text)
                except ValueError as exc:
                    stop(f"branch_state_error: {exc}")
                    break
                registered_hash = (pre_read.get("branch_request_hashes") or {}).get(branch)
                if request_hash != registered_hash:
                    stop("branch_request_hash_mismatch")
                    break
                attempts_before = int(getattr(receiver.client, "physical_attempts", 0) or 0)
                response, _ = receiver.complete_with_raw(choice_state)
                attempts_after = int(getattr(receiver.client, "physical_attempts", 0) or 0)
                report["physical_attempts"]["jev"] = attempts_after
                report["attempted_branches"] += 1

                valid = False
                error_class = None
                metrics = {"entropy_bits": None, "p_target": None, "feasible_mass": None}
                probabilities: dict[str, float] = {}
                diagnostics = None
                usage = dict(getattr(response, "usage", {}) or {})
                if response.status == "complete":
                    if response.request_hash != choice_state.request_hash:
                        error_class = "request_hash_drift"
                    else:
                        valid = True
                        probabilities = dict(response.probabilities)
                        diagnostics = (response.diagnostics.to_dict()
                                       if response.diagnostics is not None else None)
                        metrics = branch_metrics(
                            probabilities, target_id=str(pre_read.get("target_id")),
                            feasible_set=list(pre_read.get("feasible_set") or []))
                        consecutive_provider_failures = 0
                else:
                    error_class = response.error_class
                    diagnostics = (response.diagnostics.to_dict()
                                   if getattr(response, "diagnostics", None) is not None
                                   else None)
                    probabilities = dict(getattr(response, "raw_probabilities", None) or {})

                report["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
                report["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
                report["estimated_cost_usd"] = round(
                    report["input_tokens"] * 0.042 / 1_000_000, 9)

                row = {
                    "event_id": event_id, "branch": branch,
                    "planned_branch_position": branch_position,
                    "actual_branch_position": branch_position,
                    "instance_id": instance_id, "prompt_form_id": form_id,
                    "request_hash": response.request_hash,
                    "state_hash": jr.canonical_hash(dict(choice_state.state)),
                    "protocol_key": protocol_key,
                    "resolved_model": getattr(response, "model", None),
                    "physical_attempts": {"branch": attempts_after - attempts_before,
                                          "jev_cumulative": attempts_after, "cap": 153},
                    "probabilities": probabilities,
                    "probability_diagnostics": diagnostics,
                    "selected_option_id": getattr(response, "selected_option_id", None),
                    "entropy_bits": metrics["entropy_bits"],
                    "p_target": metrics["p_target"],
                    "feasible_mass": metrics["feasible_mass"],
                    "valid": valid, "status": response.status,
                    "error_class": error_class, "usage": usage,
                    "cap_counters": {"jev_used": attempts_after, "jev_cap": 153,
                                     "estimated_cost_usd": report["estimated_cost_usd"],
                                     "cost_cap_usd": cost_cap},
                    "raw_response_retained": False, "credentials_retained": False,
                }
                journal.write(row)
                rows.append(row)
                report["unattempted_branches"] = 51 - report["attempted_branches"]
                if valid:
                    report["valid_branches"] += 1
                    consecutive_provider_failures = 0
                else:
                    report["invalid_branches"] += 1
                    if error_class in SUSPECT_NONTERMINAL_CLASSES:
                        continue  # journaled invalid; siblings still run
                    if error_class in PROVIDER_FAILURE_CLASSES:
                        consecutive_provider_failures += 1
                        if consecutive_provider_failures >= 2:
                            stop("provider_failure_limit")
                            break
                        continue
                    stop(str(error_class) or "terminal_invalid_branch")
                    break
    except BranchJournalError as exc:
        stop(f"duplicate_branch_key: {exc}")
    finally:
        if journal is not None:
            journal.close()
            rows = journal.read_rows()

    report["provider_calls"] = report["physical_attempts"]["jev"]
    report["physical_attempts"]["combined"] = report["physical_attempts"]["jev"]
    report["rows"] = len(rows)

    # group branch rows into event-level real/placebo/null records
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        record = grouped.setdefault(str(row["event_id"]), {
            "event_id": row["event_id"], "instance_id": row["instance_id"],
            "prompt_form_id": row["prompt_form_id"], "branches": {}})
        record["branches"][str(row["branch"])] = row
    event_records = []
    for event_id in schedule["event_order"]:
        source = by_event_id[event_id]
        record = grouped.get(event_id, {"event_id": event_id,
                                        "instance_id": source["instance_id"],
                                        "prompt_form_id": source["prompt_form_id"],
                                        "branches": {}})
        event_records.append({
            "event_id": event_id,
            "instance_id": record["instance_id"],
            "prompt_form_id": record["prompt_form_id"],
            "branches": record["branches"],
            "branch_order_planned": schedule["schedule"][event_id],
            "branch_order_actual": [row["branch"] for row in sorted(
                record["branches"].values(),
                key=lambda row: row.get("actual_branch_position") or 0)],
        })
    report["events"] = event_records
    report["schedule_adherence"] = {
        "planned_equals_actual": all(
            event["branch_order_actual"] == event["branch_order_planned"]
            for event in event_records),
        "rows": len(rows),
    }

    # missingness by branch, event and form
    branch_counts = {branch: {"planned": 17, "attempted": 0, "valid": 0, "invalid": 0,
                              "unattempted": 17} for branch in prv4.BRANCHES}
    event_counts: dict[str, Any] = {}
    form_counts: dict[str, Any] = {}
    for event in event_records:
        form = str(event["prompt_form_id"])
        form_entry = form_counts.setdefault(form, {
            "planned_events": 0, "planned_branches": 0, "attempted": 0, "valid": 0,
            "invalid": 0, "unattempted": 0, "complete_pairs": 0})
        form_entry["planned_events"] += 1
        form_entry["planned_branches"] += 3
        attempted = valid = invalid = 0
        for branch in prv4.BRANCHES:
            row = event["branches"].get(branch)
            if row is None:
                continue
            attempted += 1
            branch_counts[branch]["attempted"] += 1
            form_entry["attempted"] += 1
            if row.get("valid"):
                valid += 1
                branch_counts[branch]["valid"] += 1
                form_entry["valid"] += 1
            else:
                invalid += 1
                branch_counts[branch]["invalid"] += 1
                form_entry["invalid"] += 1
        unattempted = 3 - attempted
        form_entry["unattempted"] += unattempted
        complete_pair = bool(event["branches"].get("real", {}).get("valid")
                             and event["branches"].get("placebo", {}).get("valid"))
        form_entry["complete_pairs"] += int(complete_pair)
        event_counts[event["event_id"]] = {"planned": 3, "attempted": attempted,
                                           "valid": valid, "invalid": invalid,
                                           "unattempted": unattempted,
                                           "partial_triplet": 0 < attempted < 3,
                                           "complete_pair": complete_pair}
    for branch in prv4.BRANCHES:
        branch_counts[branch]["unattempted"] = 17 - branch_counts[branch]["attempted"]
    report["missingness"] = {"by_branch": branch_counts, "by_event": event_counts,
                             "by_form": form_counts}

    report["analysis"] = analyze_replay(event_records)
    report["partial_report_note"] = (
        "stopping preserves this report with planned/attempted/valid/invalid/unattempted "
        "counts by branch, event and form; partial triplets remain observable")
    report["raw_response_retained"] = False
    report["credentials_retained"] = False
    if report["status"] == "completed" and report["attempted_branches"] < 51:
        report["status"], report["stop_reason"] = "stopped", "incomplete_schedule"
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="#195 replay-v4 runner (offline; live gated)")
    parser.add_argument("--live", action="store_true",
                        help="execute the replay (requires --approval; never run offline)")
    parser.add_argument("--approval", help="reviewer runtime authorization reference")
    parser.add_argument("--repo-root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = Path(args.repo_root) if args.repo_root is not None else _repo_root()
    try:
        registration = load_locked_registration(repo_root=root)
    except ValueError as exc:
        print(json.dumps({"mode": REPLAY_RUNNER_VERSION, "status": "blocked",
                          "stop_reason": f"registration_load_failed: {exc}",
                          "provider_calls": 0}, indent=2, sort_keys=True))
        return 2
    receiver = jc2.JevChoiceAdapterV2(
        jc.JevChoiceClient(model=pr.JEV_REPLAY_MODEL, max_physical_requests=153),
        model=pr.JEV_REPLAY_MODEL)
    verification = verify_replay_runner_preflight(
        registration, receiver, repo_root=root, approval=args.approval,
        check_credentials=bool(args.live), require_approval=bool(args.live),
        pinned_hash=registration.get("preregistration_hash"))
    print(json.dumps({"mode": f"{REPLAY_RUNNER_VERSION}-preflight",
                      "ok": verification["ok"], "failed": verification["failed"],
                      "checks": verification["checks"]},
                     indent=2, sort_keys=True, allow_nan=False))
    if not verification["ok"]:
        return 2
    if not args.live:
        print(json.dumps({"mode": REPLAY_RUNNER_VERSION, "status": "offline",
                          "note": "preflight only; no provider call made",
                          "live_collection_authorized": False, "provider_calls": 0},
                         indent=2, sort_keys=True))
        return 0
    report = execute_replay_runner(
        registration, receiver, verification=verification, approval=args.approval,
        pinned_hash=registration.get("preregistration_hash"))
    if report.get("status") != "blocked":
        target = root / str(registration["outputs"]["report"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                          encoding="utf-8")
    print(json.dumps({key: report.get(key) for key in
                      ("mode", "status", "stop_reason", "attempted_branches",
                       "valid_branches", "invalid_branches")},
                     indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["status"] == "completed" else (2 if report["status"] == "blocked" else 1)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "REPLAY_RUNNER_VERSION", "RUNNER_SOURCE_REL", "RECEIVER_AGENT",
    "PROVIDER_FAILURE_CLASSES", "SUSPECT_NONTERMINAL_CLASSES", "TERMINAL_INVALID_CLASSES",
    "BranchJournalError", "BranchJournal", "load_locked_registration", "build_replay_plan",
    "pre_read_state", "branch_choice_state", "message_text_for", "branch_metrics",
    "analyze_replay", "verify_replay_runner_preflight", "execute_replay_runner", "main",
]
