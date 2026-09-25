"""#192 — replay-ready one-way event set and six-form coverage decision (offline).

Recomputes the authoritative #189 selection over the committed v7 partial run,
produces explicit denominators, and makes two separate preregistered
determinations: collection-completeness (fixed N) and coverage/replay
readiness (the frozen six-form rule). Everything is derived from the pinned
inputs; stored summary booleans are never trusted without authoritative
recomputation. No provider calls, no replay inference, no causal analysis.

The experimental unit is the prompt form: repeated instances inside a form
are replicates of one model-visible pre-read state and claim treatment, never
independent states.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import jev_six_form_coverage_audit as audit
from . import jev_coverage_manifest_preregistration_v6 as prv6
from . import jev_coverage_manifest_preregistration_v7 as prv7
from . import task_families as tf
from .communication_protocol import DependenceRegime, ReasoningComplexity


DECISION_VERSION = "jev-v7-coverage-decision-v1"
ISSUE_ID = "#192"

DEFAULT_JOURNAL = "runs/epic-126/jev-coverage-manifest-v7.jsonl"
DEFAULT_REPORT = "runs/epic-126/jev-coverage-manifest-report-v7.json"
DEFAULT_REGISTRATION = "runs/epic-126/jev-coverage-manifest-preregistration-v7.json"
DEFAULT_AUDIT_ARTIFACT = "runs/epic-126/jev-six-form-coverage-audit-v1.json"
DEFAULT_OUTPUT = "runs/epic-126/decisions/jev-v7-coverage-decision.json"

SELECTOR_MODULE = "src/apart_incident_response/jev_six_form_coverage_audit.py"
GENERATOR_MODULE = "src/apart_incident_response/task_families.py"

#: The decision artifact lives in runs/epic-126/decisions/ so it never enters
#: the registrations' top-level runs/epic-126/*.json prior-ID scan globs
#: (which are non-recursive); keeping it there preserves the committed
#: registrations' rebuild evidence.

#: sha256 pins for every analysis input (committed by 1782324 / earlier).
EXPECTED_SHA256 = {
    DEFAULT_JOURNAL: "23ab961c8f4327a98af821d5457b94f278c1f0993bc027953a86bbc36081ebc5",
    DEFAULT_REPORT: "456515559c65faf976ce1063107a2d4036c7f6d06f0e9bf7e9b1f87b89b1088f",
    DEFAULT_REGISTRATION: "289d83fee5c8fcdc3c1aaa29b104850d696a3d98c32cf291e300dbf89edd5e94",
    DEFAULT_AUDIT_ARTIFACT: "73751bed24776e851f76e63dec427dafc1b458624bc56efdf96612fcfc568dcb",
    SELECTOR_MODULE: "d97918ce1ebc6b2ab79e51ff29c1b85589ba662d5ebfeae543c8ee87a6e0b6d8",
    GENERATOR_MODULE: "b399bb15c96be98d2c4c7e00012448d9a3df9f1cd7deac0ff1375ecb3e1ea6c4",
}
EXPECTED_REGISTRATION_CONTENT_HASH = (
    "f7f7d5742ea3e6a710ed102e6c2a454992abede5c4f51591a9cc447781797565")

#: Historical frozen inputs (v1-v6 registrations/outputs, #189 audit, bridge,
#: routing probe) that must remain byte-identical during this analysis.
HISTORICAL_SHA256 = {
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
    "runs/epic-126/jev-writer-exact-bridge-v5.jsonl":
        "4ea9f91decba5c504bb2726e178f36ed6cd845bba635876c822aa72d53c9a5de",
    "runs/epic-126/jev-writer-exact-bridge-report-v5.json":
        "325206d9c51a56c10195265e7f699e78b57b762b9d243160d52cdd63c58aef2d",
    "runs/epic-126/jev-coverage-manifest-preregistration-v6.json":
        "63be1ccbff954cd4c55be303d3a9569e592b336a976c6fcc824fb2fbcda1c9f5",
    "runs/epic-126/jev-coverage-manifest-v6.jsonl":
        "f5a7a0d8c1f54a0e65864ca3e2ba9589d22be3989639fa50b98202aaa1d6c364",
    "runs/epic-126/jev-coverage-manifest-report-v6.json":
        "a6f5253cbef7aa4534df3520aaa88a7e3918bb97903a3f2ff264013edb6b195c",
    "runs/epic-126/jev-ling-transport-probe-v7.json":
        "06d22e8741ee490b93c7c6f78535c480f4f67a8f53f3ac1ca589f3d639abb534",
}

#: Frozen report facts for the committed partial run (fail closed on drift).
EXPECTED_REPORT_SUMMARY = {
    "status": "stopped",
    "stop_reason": "empty_output",
    "planned_cases": 36,
    "attempted_cases": 32,
    "receiver_valid_cases": 31,
    "receiver_invalid_cases": 0,
    "receiver_unattempted_cases": 1,
}

#: Writer-validity semantics: a protocol-classifiable outcome, NOT correctness.
VALID_WRITER_OUTCOMES = frozenset(
    {"deliberate_silence", "message_candidate", "non_owned_claim"})
INVALID_WRITER_OUTCOMES = frozenset(
    {"empty_output", "truncated_output", "unparsed_output", "invalid_answer", "writer_error"})

ELIGIBILITY_CONDITIONS = [
    "writer is B",
    "receiver is A",
    "board write was accepted",
    "B authoritatively owns the exact claim",
    "claim is informative to A before reading",
    "recomputed I_m > 0",
    "matching board_write exists",
    "matching A peer_read_exposure exists after the write",
    "nonempty exposure ID",
    "no board_write_rejected evidence for that message",
    "claim is not already known to A",
    "claim reduces A's feasible set",
    "at most one claim per pre-read state",
    "repeated identical B claims within an event are deduplicated",
    "A->B messages are excluded",
    "receiver must be valid",
    "request/state/protocol provenance must match",
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_report_summary(report: Mapping[str, Any]) -> list[str]:
    """Fail-closed comparison of the report against the frozen run facts."""

    errors = []
    for key, expected in EXPECTED_REPORT_SUMMARY.items():
        if report.get(key) != expected:
            errors.append(f"report field {key}: expected {expected!r}, "
                          f"found {report.get(key)!r}")
    return errors


def verify_registration(document: Mapping[str, Any]) -> list[str]:
    errors = []
    if document.get("preregistration_hash") != EXPECTED_REGISTRATION_CONTENT_HASH:
        errors.append("registration content hash mismatch")
    if document.get("status") != prv7.COVERAGE_LOCKED_STATUS:
        errors.append("registration is not the locked v7 registration")
    if document.get("live_collection_authorized") is not False:
        errors.append("registration must not authorize live collection")
    manifest = document.get("manifest", {})
    if manifest.get("manifest_hash") != \
            "c4221e7db05fbdcba7b441099cb59d84147fa00d25569000ae2f416ca7233ad1":
        errors.append("manifest hash mismatch")
    if manifest.get("n") != 36 or len(manifest.get("instance_ids") or []) != 36:
        errors.append("registration manifest must be 36 instances")
    if (document.get("caps", {}).get("planned_calls") or {}).get("combined") != 180:
        errors.append("registered planned calls mismatch")
    if document.get("model_and_protocol", {}).get("ling_model") != \
            "inclusionai/ling-3.0-flash-vl":
        errors.append("registration ling model mismatch")
    return errors


def verify_inputs(repo_root: Path | None = None) -> dict[str, Any]:
    """Verify every pinned input and the frozen report facts; fail closed."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    for relative, expected in EXPECTED_SHA256.items():
        path = root / relative
        actual = sha256_file(path) if path.is_file() else None
        check(f"pin:{relative}", actual == expected,
              {"expected": expected, "actual": actual})
    for relative, expected in HISTORICAL_SHA256.items():
        path = root / relative
        actual = sha256_file(path) if path.is_file() else None
        check(f"historical_pin:{relative}", actual == expected,
              {"expected": expected, "actual": actual})
    pinned_failed = [item["check"] for item in checks if not item["ok"]]
    if pinned_failed:
        raise ValueError(f"input verification failed: {pinned_failed}")

    report = json.loads((root / DEFAULT_REPORT).read_text(encoding="utf-8"))
    for error in verify_report_summary(report):
        check(f"report_summary:{error}", False, None)
    registration = json.loads((root / DEFAULT_REGISTRATION).read_text(encoding="utf-8"))
    for error in verify_registration(registration):
        check(f"registration:{error}", False, None)

    journal_rows = [json.loads(line) for line in
                    (root / DEFAULT_JOURNAL).read_text(encoding="utf-8").splitlines()
                    if line.strip()]
    check("journal_row_count", len(journal_rows) == 32, len(journal_rows))
    check("report_case_count", len(report.get("cases") or []) == 32,
          len(report.get("cases") or []))

    failed = [item["check"] for item in checks if not item["ok"]]
    if failed:
        raise ValueError(f"input verification failed: {failed}")
    return {"ok": True, "checks": checks, "failed": []}


def selection_policy() -> dict[str, Any]:
    return {
        "policy_version": "jev-six-form-coverage-audit-v1::select_replay_claims",
        "selector_module": SELECTOR_MODULE,
        "selector_source_sha256": EXPECTED_SHA256[SELECTOR_MODULE],
        "eligibility_conditions": list(ELIGIBILITY_CONDITIONS),
        "valid_writer_outcomes": sorted(VALID_WRITER_OUTCOMES),
        "invalid_writer_outcomes": sorted(INVALID_WRITER_OUTCOMES),
        "direction": "one-way B->A",
        "unit_filter_note": ("eligibility is evaluated per pre-read state; at most one "
                             "deduplicated claim per state"),
    }


def regenerate_instances(registration: Mapping[str, Any]) -> list[Any]:
    """Regenerate the registered 36 instances from their seeds (order preserved)."""

    instances = []
    for seed in registration["manifest"]["instance_seeds"]:
        instances.append(tf.generate_instance("planning", int(seed), DependenceRegime.N,
                                              ReasoningComplexity.LOW))
    expected_ids = list(registration["manifest"]["instance_ids"])
    actual_ids = [instance.instance_id for instance in instances]
    if actual_ids != expected_ids:
        raise ValueError("regenerated instance order differs from the registered manifest")
    return instances


def recompute_event_set(rows: Sequence[Mapping[str, Any]],
                        instances: Sequence[Any],
                        registration: Mapping[str, Any]) -> dict[str, Any]:
    """Authoritative recomputation over every row; fail closed on any drift."""

    by_id = {instance.instance_id: instance for instance in instances}
    forms = audit.pre_read_form_ids(list(instances))
    registered_protocol = registration["model_and_protocol"]["protocol_key"]
    membership = registration["manifest"]["form_membership"]

    events: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    provenance_failures: list[dict[str, Any]] = []
    present_without_event = 0
    recomputed_eligible_rows = 0

    for row in rows:
        instance_id = str(row.get("instance_id"))
        instance = by_id.get(instance_id)
        if instance is None:
            raise ValueError(f"journal row references unregistered instance: {instance_id}")
        form_id = str(row.get("prompt_form_id"))
        if forms.get(instance_id) != form_id:
            raise ValueError(f"prompt_form_id mismatch for {instance_id}: "
                             f"{row.get('prompt_form_id')} != {forms.get(instance_id)}")
        if instance_id not in membership.get(form_id, []):
            raise ValueError(f"instance {instance_id} not in registered membership of {form_id}")

        selection = audit.select_replay_claims(row, instance)
        stored_selection = row.get("replay_selection")
        stored_eligible = bool(row.get("replay_eligible"))
        stored_exposure = bool(row.get("eligible_exposure"))
        eligible = bool(selection["eligible"] and row.get("receiver_valid"))

        row_disagreements = []
        if selection != stored_selection:
            row_disagreements.append("stored replay_selection differs from recomputation")
        if eligible != stored_eligible:
            row_disagreements.append("stored replay_eligible disagrees with recomputation")
        if stored_exposure != stored_eligible:
            row_disagreements.append("eligible_exposure disagrees with replay_eligible")
        if row_disagreements:
            disagreements.append({"instance_id": instance_id, "problems": row_disagreements})
            continue

        if not eligible:
            if row.get("accepted_b_message_present"):
                present_without_event += 1
            continue
        recomputed_eligible_rows += 1
        selected = selection["selected"]
        problems = []
        if len(selected) != 1:
            problems.append(f"expected exactly one selected claim, found {len(selected)}")
        else:
            chosen = selected[0]
            if chosen.get("writer_id") != "B":
                problems.append("writer is not B")
            if chosen.get("reader_id") != "A":
                problems.append("receiver is not A")
            if not (isinstance(chosen.get("i_m_bits"), (int, float))
                    and float(chosen["i_m_bits"]) > 0.0):
                problems.append("I_m not positive")
            exposure_ids = chosen.get("exposure_ids") or []
            if not exposure_ids or any(not str(value).strip() for value in exposure_ids):
                problems.append("missing or empty exposure id")
            if row.get("protocol_key") != registered_protocol:
                problems.append("protocol key differs from the registration")
            for field in ("request_hash", "state_hash"):
                value = row.get(field)
                if not (isinstance(value, str) and len(value) == 64
                        and all(c in "0123456789abcdef" for c in value)):
                    problems.append(f"{field} missing or malformed")
            if row.get("resolved_model") is not None \
                    and row.get("resolved_model") != registration["model_and_protocol"]["model"]:
                problems.append("resolved model differs from the registration")
        if problems:
            provenance_failures.append({"instance_id": instance_id, "problems": problems})
            continue
        chosen = selected[0]
        events.append({
            "event_id": f"{instance_id}:{chosen['message_id']}",
            "instance_id": instance_id,
            "prompt_form_id": form_id,
            "message_id": chosen["message_id"],
            "claim": chosen["claim"],
            "i_m_bits": float(chosen["i_m_bits"]),
            "writer_id": chosen["writer_id"],
            "reader_id": chosen["reader_id"],
            "write_sequence": chosen.get("write_sequence"),
            "exposure_ids": list(chosen.get("exposure_ids") or []),
            "receiver_valid": bool(row.get("receiver_valid")),
            "request_hash": row.get("request_hash"),
            "state_hash": row.get("state_hash"),
            "protocol_key": row.get("protocol_key"),
            "resolved_model": row.get("resolved_model"),
            "selected_claims_in_pre_read_state": len(selected),
            "accepted_b_message_present": bool(row.get("accepted_b_message_present")),
        })

    if disagreements:
        raise ValueError(f"stored eligibility disagrees with recomputation: "
                         f"{disagreements[:3]}")
    if provenance_failures:
        raise ValueError(f"eligible event failed provenance checks: {provenance_failures[:3]}")
    return {"events": events, "recomputed_eligible_rows": recomputed_eligible_rows,
            "present_without_event": present_without_event}


def writer_validity_block(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    totals: dict[str, int] = {}
    by_agent_turn: dict[str, int] = {}
    valid_calls = invalid_calls = 0
    terminal = None
    for row in rows:
        for outcome in row.get("writer_outcomes") or ():
            name = str(outcome.get("outcome"))
            totals[name] = totals.get(name, 0) + 1
            key = f"{outcome.get('agent')}|{outcome.get('turn')}|{name}"
            by_agent_turn[key] = by_agent_turn.get(key, 0) + 1
            if name in VALID_WRITER_OUTCOMES:
                valid_calls += 1
            elif name in INVALID_WRITER_OUTCOMES:
                invalid_calls += 1
                if name == "empty_output":
                    terminal = {"instance_id": row.get("instance_id"),
                                "agent": outcome.get("agent"), "turn": outcome.get("turn"),
                                "outcome": name,
                                "visible_content": "empty" if outcome.get("content_length") == 0
                                else outcome.get("content_length"),
                                "finish_reason": outcome.get("finish_reason"),
                                "output_tokens": outcome.get("output_tokens"),
                                "error_class": outcome.get("error_class"),
                                "receiver_unattempted": bool(row.get("receiver_unattempted"))}
    total_calls = valid_calls + invalid_calls
    return {
        "definition": {
            "writer_valid": ("a Ling call produced a protocol-classifiable outcome: "
                             "deliberate_silence, an accepted owned message candidate, or a "
                             "non-owned claim that is explicitly rejected and recorded — "
                             "classifiability, NOT correctness"),
            "writer_invalid": ("empty_output, truncated_output, unparsed_output, invalid_answer, "
                               "writer_error"),
        },
        "writer_calls_total": total_calls,
        "writer_valid_calls": valid_calls,
        "writer_invalid_calls": invalid_calls,
        "outcome_totals": dict(sorted(totals.items())),
        "outcomes_by_agent_turn": dict(sorted(by_agent_turn.items())),
        "invalid_not_counted_as_silence": (
            totals.get("empty_output", 0) + totals.get("truncated_output", 0)
            + totals.get("unparsed_output", 0) + totals.get("invalid_answer", 0)
            + totals.get("writer_error", 0)) == invalid_calls,
        "terminal_failure": {
            **(terminal or {}),
            "classification": ("writer-invalid missing data caused by output-budget "
                               "exhaustion"),
            "explicitly_not": ["deliberate silence", "lack of communication",
                               "an API-key failure", "an OpenRouter transport failure"],
        },
    }


def missingness_by_form(rows: Sequence[Mapping[str, Any]],
                        instances: Sequence[Any],
                        registration: Mapping[str, Any],
                        events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    forms = audit.pre_read_form_ids(list(instances))
    membership = registration["manifest"]["form_membership"]
    attempted_ids = {str(row.get("instance_id")) for row in rows}
    valid_ids = {str(row.get("instance_id")) for row in rows if row.get("receiver_valid")}
    unattempted_receiver_ids = {str(row.get("instance_id")) for row in rows
                                if not row.get("receiver_attempted")}
    invalid_outcome_ids = {str(row.get("instance_id")) for row in rows
                           if any(str(o.get("outcome")) in INVALID_WRITER_OUTCOMES
                                  for o in row.get("writer_outcomes") or ())}
    eligible_by_form: dict[str, int] = {form: 0 for form in membership}
    for event in events:
        eligible_by_form[event["prompt_form_id"]] += 1

    missing: dict[str, Any] = {}
    for form in sorted(membership):
        planned_ids = list(membership[form])
        not_attempted = [iid for iid in planned_ids if iid not in attempted_ids]
        missing[form] = {
            "planned_instances": len(planned_ids),
            "attempted_instances": sum(1 for iid in planned_ids if iid in attempted_ids),
            "not_attempted_instances": not_attempted,
            "receiver_valid_instances": sum(1 for iid in planned_ids if iid in valid_ids),
            "receiver_unattempted_instances": sum(1 for iid in planned_ids
                                                  if iid in unattempted_receiver_ids),
            "writer_invalid_instances": sorted(iid for iid in planned_ids
                                               if iid in invalid_outcome_ids),
            "eligible_events": eligible_by_form[form],
        }
    return missing


def information_accounting(rows: Sequence[Mapping[str, Any]],
                           events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    gross_total = gross_b = gross_a = 0.0
    records_total = records_b = records_a = 0
    for row in rows:
        for board_row in row.get("board") or ():
            if board_row.get("status") != "accepted" or board_row.get("delta_i_bits") is None:
                continue
            delta = float(board_row["delta_i_bits"])
            gross_total += delta
            records_total += 1
            if str(board_row.get("author")) == "B":
                gross_b += delta
                records_b += 1
            else:
                gross_a += delta
                records_a += 1
    eligible_bits = sum(float(event["i_m_bits"]) for event in events)
    distinct_treatments = sorted({(event["prompt_form_id"], event["claim"])
                                  for event in events})
    distinct_bits = 0.0
    for form, claim in distinct_treatments:
        match = next(event for event in events
                     if event["prompt_form_id"] == form and event["claim"] == claim)
        distinct_bits += float(match["i_m_bits"])
    return {
        "label_rule": ("gross transmitted bits are gross transmission, never unique "
                       "information delivered to Jev A"),
        "gross_transmitted_all_messages": {"records": records_total,
                                           "i_m_bits": gross_total},
        "gross_b_to_a": {"records": records_b, "i_m_bits": gross_b},
        "gross_a_to_b": {"records": records_a, "i_m_bits": gross_a},
        "replay_eligible_event_claims": {"events": len(events), "claims": len(events),
                                         "i_m_bits": eligible_bits},
        "distinct_form_claim_treatments": {"count": len(distinct_treatments),
                                           "i_m_bits": distinct_bits,
                                           "pairs": [{"prompt_form_id": form, "claim": claim}
                                                     for form, claim in distinct_treatments]},
        "primary_replay_set_direction": "B->A only",
        "primary_replay_set_direction_verified": all(
            event["writer_id"] == "B" and event["reader_id"] == "A" for event in events),
        "gross_is_not_unique_note": ("the gross totals include A->B messages and repeated "
                                     "identical B claims within an event; they must never be "
                                     "described as unique information delivered"),
    }


def make_decisions(rows: Sequence[Mapping[str, Any]],
                   registration: Mapping[str, Any],
                   events: Sequence[Mapping[str, Any]],
                   missing: Mapping[str, Any]) -> dict[str, Any]:
    planned = 36
    attempted = len(rows)
    collection = {
        "gate": "fixed N=36",
        "planned": planned,
        "attempted": attempted,
        "result": "failed" if attempted < planned else "passed",
        "statement": (f"Fixed N={planned} was not completed: collection stopped at case "
                      f"{attempted} under a registered terminal rule. The v7 block is a "
                      "registered partial run and cannot be described as a completed "
                      "fixed-N sample."),
    }
    covered_forms = sorted({event["prompt_form_id"] for event in events})
    k = len(covered_forms)
    if k >= 6:
        coverage = {
            "rule_applied": ("#192 frozen coverage rule: every one of the six frozen prompt "
                             "forms has at least one valid, authoritative B->A replay event"),
            "result": "six_form_coverage_observed",
            "covered_forms": 6,
            "k": 6,
            "covered_form_ids": sorted(prv6.FROZEN_FORM_IDS),
            "conditional_replay_gate_released": True,
            "statement": ("Six-form replay coverage passed within a registered partial run; "
                          "fixed-N collection completeness failed."),
            "gate_scope": ("release is on the coverage dimension only: #193 may amend/lock the "
                           "#159 matched replay plan; the incomplete collection gate is not "
                           "erased and replay inference has not been run"),
        }
    elif k == 5:
        coverage = {
            "rule_applied": "#192 frozen coverage rule (five-form fallback)",
            "result": "five_form_coverage_interval_only",
            "covered_forms": 5,
            "k": 5,
            "covered_form_ids": covered_forms,
            "conditional_replay_gate_released": False,
            "statement": ("Only five frozen forms survived authoritative validation; only "
                          "interval-only descriptive work is allowed and a two-sided sign-flip "
                          "p-value below 0.05 is explicitly forbidden"),
        }
    else:
        coverage = {
            "rule_applied": "#192 frozen coverage rule (failure branch)",
            "result": "inducement_coverage_failure",
            "covered_forms": k,
            "k": k,
            "covered_form_ids": covered_forms,
            "conditional_replay_gate_released": False,
            "statement": ("Fewer than five frozen forms survived authoritative validation; "
                          "report inducement/coverage failure and stop"),
        }
    coverage["missing_forms"] = sorted(set(prv6.FROZEN_FORM_IDS) - set(covered_forms))
    coverage["form_event_counts"] = {
        form: sum(1 for event in events if event["prompt_form_id"] == form)
        for form in sorted(prv6.FROZEN_FORM_IDS)}
    return {"collection_completeness": collection, "coverage_replay_readiness": coverage}


def build_decision(repo_root: Path | None = None) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    input_verification = verify_inputs(root)
    registration = json.loads((root / DEFAULT_REGISTRATION).read_text(encoding="utf-8"))
    report = json.loads((root / DEFAULT_REPORT).read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in
            (root / DEFAULT_JOURNAL).read_text(encoding="utf-8").splitlines() if line.strip()]
    instances = regenerate_instances(registration)
    recomputation = recompute_event_set(rows, instances, registration)
    events = recomputation["events"]
    writer = writer_validity_block(rows)
    missing = missingness_by_form(rows, instances, registration, events)
    accounting = information_accounting(rows, events)
    decisions = make_decisions(rows, registration, events, missing)

    planned_ids = list(registration["manifest"]["instance_ids"])
    attempted_ids = [str(row.get("instance_id")) for row in rows]
    not_attempted = [iid for iid in planned_ids if iid not in set(attempted_ids)]

    document = {
        "artifact_version": DECISION_VERSION,
        "issue": ISSUE_ID,
        "generated_by": "src/apart_incident_response/jev_v7_coverage_decision.py",
        "mode": "offline-analysis-only",
        "provider_calls": 0,
        "inputs": {
            "sha256": dict(EXPECTED_SHA256),
            "historical_sha256": dict(HISTORICAL_SHA256),
            "registration_content_hash": EXPECTED_REGISTRATION_CONTENT_HASH,
            "input_verification": input_verification,
            "report_summary": {key: report.get(key) for key in EXPECTED_REPORT_SUMMARY},
        },
        "writer_validity": writer,
        "selection_policy": selection_policy(),
        "denominators": {
            "planned_instances": 36,
            "attempted_instances": len(rows),
            "unattempted_instances": 36 - len(rows),
            "unattempted_instance_ids": not_attempted,
            "receiver_valid": sum(1 for row in rows if row.get("receiver_valid")),
            "receiver_invalid": sum(1 for row in rows
                                    if row.get("receiver_attempted")
                                    and not row.get("receiver_valid")),
            "receiver_unattempted": sum(1 for row in rows
                                        if not row.get("receiver_attempted")),
            "writer_valid_calls": writer["writer_valid_calls"],
            "writer_invalid_calls": writer["writer_invalid_calls"],
            "eligible_replay_events": len(events),
            "eligible_claims": len(events),
            "distinct_covered_forms": len({event["prompt_form_id"] for event in events}),
            "rows_with_accepted_b_message_but_no_eligible_event":
                recomputation["present_without_event"],
            "recomputed_eligible_rows": recomputation["recomputed_eligible_rows"],
        },
        "missingness_by_form": missing,
        "events": events,
        "information_accounting": accounting,
        "decisions": decisions,
        "experimental_unit": {
            "unit": "prompt form",
            "k": len({event["prompt_form_id"] for event in events}),
            "events": len(events),
            "note": ("k is the number of covered frozen forms, not the number of events; "
                     "repeated instances within a form are replicates of one model-visible "
                     "pre-read state and claim treatment; the 17 events are not 17 "
                     "independent states"),
            "prohibited_and_not_performed": [
                "instance-level t-test", "instance-level Wilcoxon test",
                "other independence-assuming analyses",
                "real/placebo/null replay inference",
                "causal uptake effect",
            ],
        },
        "claim_scope": [
            "registered partial run: fixed-N completeness failed; never described as a "
            "completed fixed-N sample",
            "coverage pass is conditional on this partial run and does not erase the "
            "incomplete collection gate",
            "paid-route findings are conditional on the paid Ling SKU and must not be "
            "pooled with free-route behavioral rates",
            "gross transmitted I_m is never unique information delivered to Jev A",
            "no causal, behavioral-capability, or replay-inference claim is made here",
            "the formal coverage decision application of the frozen rule is recorded in "
            "decisions.coverage_replay_readiness; #193 owns the next step",
        ],
    }
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="#192 v7 coverage decision (offline)")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = Path(args.repo_root) if args.repo_root is not None else _repo_root()
    document = build_decision(root)
    output = args.output if args.output is not None else root / DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
                      encoding="utf-8")
    print(json.dumps({
        "artifact_version": document["artifact_version"],
        "output": str(output),
        "denominators": document["denominators"],
        "collection_completeness": document["decisions"]["collection_completeness"]["result"],
        "coverage_result": document["decisions"]["coverage_replay_readiness"]["result"],
        "gate_released": document["decisions"]["coverage_replay_readiness"][
            "conditional_replay_gate_released"],
        "provider_calls": 0,
    }, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DECISION_VERSION", "ISSUE_ID", "DEFAULT_JOURNAL", "DEFAULT_REPORT",
    "DEFAULT_REGISTRATION", "DEFAULT_AUDIT_ARTIFACT", "DEFAULT_OUTPUT",
    "EXPECTED_SHA256", "HISTORICAL_SHA256", "EXPECTED_REGISTRATION_CONTENT_HASH",
    "EXPECTED_REPORT_SUMMARY", "VALID_WRITER_OUTCOMES", "INVALID_WRITER_OUTCOMES",
    "ELIGIBILITY_CONDITIONS", "sha256_file", "verify_report_summary",
    "verify_registration", "verify_inputs", "selection_policy",
    "regenerate_instances", "recompute_event_set", "writer_validity_block",
    "missingness_by_form", "information_accounting", "make_decisions",
    "build_decision", "main",
]
