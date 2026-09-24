"""#189 — six-form coverage estimand and information accounting audit (offline).

Recomputes every frozen coverage fact directly from the immutable L4X v5
journal/report and the task generator (never from issue prose), audits the six
pre-read prompt forms and their B-owned clue geometry, applies the frozen
one-way B->A replay-eligibility rules, and freezes the equal-form estimand,
inference limits, sensitivity calculation and the #190 fresh-coverage sizing
handoff.

No provider calls. The L4X v5 artifacts are read-only, hash-pinned inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import jev_choice as jc
from . import jev_replay as jr
from . import jev_replay_inference as ji
from . import jev_replay_preregistration as pr
from . import task_families as tf
from .jev_choice_pilot import RECEIVER_AGENT, pilot_instances


AUDIT_VERSION = "jev-six-form-coverage-audit-v1"
ISSUE_ID = "#189"

MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parents[1]

DEFAULT_JOURNAL_REL = "runs/epic-126/jev-writer-exact-bridge-v5.jsonl"
DEFAULT_REPORT_REL = "runs/epic-126/jev-writer-exact-bridge-report-v5.json"
DEFAULT_OUTPUT_REL = "runs/epic-126/jev-six-form-coverage-audit-v1.json"
ILLUSTRATIVE_SD_JOURNAL_REL = "runs/epic-126/jev-choice-capability.jsonl"

#: Hash-pinned immutable L4X v5 inputs; the audit fails closed on drift.
EXPECTED_JOURNAL_SHA256 = "4ea9f91decba5c504bb2726e178f36ed6cd845bba635876c822aa72d53c9a5de"
EXPECTED_REPORT_SHA256 = "325206d9c51a56c10195265e7f699e78b57b762b9d243160d52cdd63c58aef2d"

#: Writer outcomes that would invalidate coverage if present.
FORBIDDEN_WRITER_OUTCOMES = frozenset({
    "empty_output", "truncated_output", "unparsed_output", "invalid_answer", "writer_error",
})

LOG2_3 = math.log2(3)

#: Illustrative between-form SD in bits (J3 ISO-FULL method demonstration).
ILLUSTRATIVE_BETWEEN_FORM_SD_BITS = 0.1933

# Frozen one-way B->A replay-eligibility rejection reasons, in evaluation order.
REJECTIONS = (
    "direction_not_b_to_a",
    "write_not_accepted",
    "missing_verified_board_write",
    "missing_verified_read_exposure",
    "receiver_known_claim",
    "zero_or_uninformative_claim",
    "claim_not_owned_by_writer",
    "duplicate_claim_within_event",
    "second_claim_same_pre_read_state",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_journal(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_pinned_inputs(repo_root: Path | None = None) -> dict[str, Any]:
    """Fail closed unless the immutable L4X v5 artifacts match their pinned hashes."""

    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    journal_path = root / DEFAULT_JOURNAL_REL
    report_path = root / DEFAULT_REPORT_REL
    rows = []
    ok = True
    for label, path, expected in (
        ("journal", journal_path, EXPECTED_JOURNAL_SHA256),
        ("report", report_path, EXPECTED_REPORT_SHA256),
    ):
        actual = sha256_file(path)
        matched = actual == expected
        ok = ok and matched
        rows.append({"input": label, "path": str(Path(DEFAULT_JOURNAL_REL if label == "journal"
                                                       else DEFAULT_REPORT_REL)),
                     "expected_sha256": expected, "actual_sha256": actual, "ok": matched})
    if not ok:
        failed = [row["input"] for row in rows if not row["ok"]]
        raise ValueError(f"pinned_input_hash_mismatch: {failed}")
    return {"ok": ok, "inputs": rows, "inputs_modified_by_audit": False}


def pre_read_form_ids(instances: Sequence[Any], *,
                      receiver_agent: str = RECEIVER_AGENT) -> dict[str, str]:
    """Map every instance to its model-visible pre-read prompt form id.

    The form id is the replay ``prompt_form_id`` of the ISO pre-read request
    body and must equal the adapter ``request_hash`` the bridge counted as a
    distinct form.
    """

    adapter = jc.JevChoiceAdapter(object(), model=pr.JEV_REPLAY_MODEL)
    forms: dict[str, str] = {}
    for instance in instances:
        state = adapter.build_state(instance, receiver_agent, "ISO")
        body = jr.pre_read_request_body(
            state=dict(state.state), question_id=state.question_id,
            instructions=state.instructions,
            option_ids=[option.option_id for option in state.options],
            model=adapter.model)
        form_id = jr.prompt_form_id(body)
        if form_id != state.request_hash:
            raise ValueError(f"form_identity_mismatch: {instance.instance_id}")
        forms[instance.instance_id] = form_id
    return forms


def writer_outcome_census(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_agent_turn: Counter[tuple[str, int, str]] = Counter()
    totals: Counter[str] = Counter()
    for case in cases:
        for outcome in case.get("writer_outcomes") or ():
            key = (str(outcome.get("agent")), int(outcome.get("turn")), str(outcome.get("outcome")))
            by_agent_turn[key] += 1
            totals[key[2]] += 1
    forbidden = sorted(name for name in totals if name in FORBIDDEN_WRITER_OUTCOMES)
    return {
        "by_agent_turn_outcome": {f"{agent}|{turn}|{outcome}": count
                                  for (agent, turn, outcome), count in sorted(by_agent_turn.items())},
        "totals_by_outcome": dict(sorted(totals.items())),
        "total_writer_attempts": sum(totals.values()),
        "forbidden_outcomes_present": forbidden,
        "forbidden_outcome_count": sum(totals[name] for name in forbidden),
        "forbidden_writer_output_affected_result": bool(forbidden),
        "interpretation": (
            "empty/truncated/unparsed/invalid-answer/writer-error outcomes never reached the "
            "receiver and never contributed to coverage; deliberate_silence, owned "
            "message_candidate and classified non_owned_claim are the only outcomes present"),
    }


def select_replay_claims(case: Mapping[str, Any], instance: Any, *,
                         receiver_agent: str = RECEIVER_AGENT) -> dict[str, Any]:
    """Apply the frozen one-way B->A replay-eligibility rules to one pre-read state.

    Rules, in order: direction (peer B->A only, never A->B), accepted board
    write, verified write-to-read provenance from the CommunicationEventLog,
    receiver-known rejection, authoritative recomputed I_m > 0 (never trusted
    from the flattened row), writer ownership, deduplication of repeated
    identical claims within the event, and at most one selected claim per
    pre-read state.
    """

    board = list(case.get("board") or ())
    log_rows = list(case.get("board_log") or ())
    writes: dict[str, Mapping[str, Any]] = {}
    reads: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for event in log_rows:
        kind = event.get("kind")
        message_id = event.get("message_id")
        if not message_id:
            continue
        if kind == "board_write" and event.get("status") == "accepted":
            writes.setdefault(str(message_id), event)
        elif kind == "peer_read_exposure":
            reads[str(message_id)].append(event)

    receiver_clues = {str(clue).strip().casefold()
                      for clue in (instance.private_clues.get(receiver_agent) or ())}
    accepted: list[tuple[Mapping[str, Any], Any, Mapping[str, Any]]] = []
    rejected: list[dict[str, str]] = []

    def reject(message_id: Any, claim: Any, reason: str) -> None:
        rejected.append({"message_id": str(message_id), "claim": str(claim), "reason": reason})

    for row in board:
        message_id = str(row.get("message_id"))
        text = str(row.get("text"))
        author = str(row.get("author"))
        row_receiver = str(row.get("receiver"))
        if author == receiver_agent or row_receiver != receiver_agent:
            reject(message_id, text, "direction_not_b_to_a")
            continue
        if row.get("status") != "accepted":
            reject(message_id, text, "write_not_accepted")
            continue
        write_event = writes.get(message_id)
        payload = dict((write_event or {}).get("payload") or {})
        if (write_event is None or str(write_event.get("agent_id")) != author
                or str(payload.get("receiver_id")) != receiver_agent):
            reject(message_id, text, "missing_verified_board_write")
            continue
        if not any(str(event.get("agent_id")) == receiver_agent
                   for event in reads.get(message_id, ())):
            reject(message_id, text, "missing_verified_read_exposure")
            continue
        if text.strip().casefold() in receiver_clues:
            reject(message_id, text, "receiver_known_claim")
            continue
        info = instance.information(receiver_agent, text, message_id)
        if (info.status != "accepted" or info.delta_i_bits is None
                or not float(info.delta_i_bits) > 0.0):
            reject(message_id, text, "zero_or_uninformative_claim")
            continue
        if not instance.holds_claim(author, text):
            reject(message_id, text, "claim_not_owned_by_writer")
            continue
        accepted.append((row, info, write_event))

    selected: list[dict[str, Any]] = []
    seen_claims: set[str] = set()
    for row, info, write_event in accepted:
        message_id = str(row.get("message_id"))
        text = str(row.get("text"))
        claim_key = text.strip().casefold()
        if claim_key in seen_claims:
            reject(message_id, text, "duplicate_claim_within_event")
            continue
        seen_claims.add(claim_key)
        if selected:
            reject(message_id, text, "second_claim_same_pre_read_state")
            continue
        exposure_ids = sorted({str((dict(event.get("payload") or {})).get("exposure_id"))
                               for event in reads.get(message_id, ())
                               if str(event.get("agent_id")) == receiver_agent
                               and (event.get("payload") or {}).get("exposure_id")})
        selected.append({
            "message_id": message_id,
            "claim": text,
            "writer_id": str(row.get("author")),
            "reader_id": receiver_agent,
            "i_m_bits": float(info.delta_i_bits),
            "write_sequence": write_event.get("sequence"),
            "exposure_ids": exposure_ids,
        })

    return {
        "instance_id": case.get("instance_id"),
        "receiver_agent": receiver_agent,
        "selected": selected,
        "rejected": rejected,
        "eligible": bool(selected),
    }


def _case_is_eligible(case: Mapping[str, Any], selection: Mapping[str, Any]) -> bool:
    """Eligible B->A Jev exposure: valid receiver plus >=1 selected claim."""

    return bool(selection.get("eligible")) and bool(case.get("receiver_valid"))


def form_audit_table(cases: Sequence[Mapping[str, Any]], instances: Sequence[Any],
                     form_ids: Mapping[str, str],
                     selections: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_instance = {instance.instance_id: instance for instance in instances}
    members: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for case in cases:
        members[form_ids[str(case["instance_id"])]].append(case)

    rows: list[dict[str, Any]] = []
    for form_id in sorted(members):
        form_cases = members[form_id]
        instance_ids = sorted(str(case["instance_id"]) for case in form_cases)
        b_clues: set[str] = set()
        for instance_id in instance_ids:
            b_clues.update(str(clue) for clue in
                           (by_instance[instance_id].private_clues.get("B") or ()))
        representative = by_instance[instance_ids[0]]
        b_clue = sorted(b_clues)[0] if len(b_clues) == 1 else None
        info = (representative.information(RECEIVER_AGENT, b_clue, "m-six-form-audit")
                if b_clue is not None else None)
        b_opportunities = sum(1 for case in form_cases
                              for outcome in case.get("writer_outcomes") or ()
                              if str(outcome.get("agent")) == "B")
        accepted_b = sum(1 for case in form_cases
                         for row in case.get("board") or ()
                         if str(row.get("author")) == "B" and row.get("status") == "accepted")
        accepted_a = sum(1 for case in form_cases
                         for row in case.get("board") or ()
                         if str(row.get("author")) == "A" and row.get("status") == "accepted")
        eligible = sum(1 for case in form_cases
                       if _case_is_eligible(case, selections[str(case["instance_id"])]))
        rows.append({
            "prompt_form_id": form_id,
            "b_owned_clues": sorted(b_clues),
            "single_b_owned_clue": len(b_clues) == 1,
            "b_owned_clue": b_clue,
            "authoritative_information": None if info is None else {
                "claim": b_clue,
                "delivered_to": RECEIVER_AGENT,
                "status": info.status,
                "i_m_bits": float(info.delta_i_bits) if info.delta_i_bits is not None else None,
                "receiver_feasible_before": info.before_count,
                "receiver_feasible_after": info.after_count,
            },
            "instance_ids": instance_ids,
            "instance_count": len(instance_ids),
            "b_writer_opportunities": b_opportunities,
            "accepted_b_messages": accepted_b,
            "accepted_a_messages": accepted_a,
            "eligible_b_to_a_exposures": eligible,
            "replay_selected_claims": sum(
                1 for case in form_cases
                if _case_is_eligible(case, selections[str(case["instance_id"])])),
            "covered": eligible > 0,
        })
    return rows


def form_geometry(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    clues = [row["b_owned_clue"] for row in rows]
    forms = [row["prompt_form_id"] for row in rows]
    clue_forms: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row["b_owned_clue"] is not None:
            clue_forms[row["b_owned_clue"]].add(row["prompt_form_id"])
    bijective = (
        len(rows) == len(set(forms))
        and all(row["single_b_owned_clue"] for row in rows)
        and len(set(clues)) == len(clues)
        and all(len(form_set) == 1 for form_set in clue_forms.values())
        and len(clue_forms) == len(rows)
    )
    geometries = sorted({
        (row["authoritative_information"]["status"],
         row["authoritative_information"]["receiver_feasible_before"],
         row["authoritative_information"]["receiver_feasible_after"],
         round(float(row["authoritative_information"]["i_m_bits"]), 12))
        for row in rows if row["authoritative_information"] is not None
    })
    bits_ok = all(row["authoritative_information"] is not None
                  and row["authoritative_information"]["i_m_bits"] is not None
                  and math.isclose(float(row["authoritative_information"]["i_m_bits"]), LOG2_3,
                                   rel_tol=0.0, abs_tol=1e-12)
                  for row in rows)
    return {
        "distinct_forms": len(set(forms)),
        "distinct_b_clues": len(set(clues)),
        "form_to_b_clue_bijective": bijective,
        "each_b_clue_carries_log2_3_bits": bits_ok,
        "expected_bits": LOG2_3,
        "geometries": [{"status": status, "receiver_feasible_before": before,
                        "receiver_feasible_after": after, "i_m_bits": bits}
                       for status, before, after, bits in geometries],
        "geometry_equivalent_across_forms": len(geometries) == 1 and bits_ok,
        "note": ("the pre-read form fixes A's private clues, and claims are partitioned, so the "
                 "form determines B's single owned clue and vice versa"),
    }


def uncovered_form_record(rows: Sequence[Mapping[str, Any]],
                          geometry: Mapping[str, Any]) -> dict[str, Any] | None:
    missing = [row for row in rows if not row["covered"]]
    if len(missing) != 1:
        return None
    row = missing[0]
    return {
        "prompt_form_id": row["prompt_form_id"],
        "b_owned_clue": row["b_owned_clue"],
        "instance_ids": row["instance_ids"],
        "instance_count": row["instance_count"],
        "b_writer_opportunities": row["b_writer_opportunities"],
        "accepted_b_messages": row["accepted_b_messages"],
        "eligible_b_to_a_exposures": row["eligible_b_to_a_exposures"],
        "authoritative_information": row["authoritative_information"],
        "classification": (
            "writer/seed coverage event: the uncovered form's information geometry is "
            "equivalent to the covered forms (same log2(3)-bit B clue to A), so the gap is an "
            "observed writer/seed emission outcome, not an information-geometry difference"),
        "not_proven": (
            "this does not prove the form will emit under new seeds, nor that it cannot; "
            "emission under fresh seeds is an empirical question for #190"),
        "geometry_equivalent_to_covered_forms": bool(geometry["geometry_equivalent_across_forms"]),
    }


def coverage_facts(cases: Sequence[Mapping[str, Any]], report: Mapping[str, Any],
                   rows: Sequence[Mapping[str, Any]],
                   selections: Mapping[str, Mapping[str, Any]],
                   census: Mapping[str, Any]) -> dict[str, Any]:
    valid = sum(1 for case in cases if case.get("receiver_valid"))
    invalid = sum(1 for case in cases
                  if case.get("receiver_attempted") and not case.get("receiver_valid"))
    unattempted = sum(1 for case in cases if not case.get("receiver_attempted"))
    accepted_by_author: Counter[str] = Counter()
    authoritative_records = 0
    gross_bits = 0.0
    for case in cases:
        for row in case.get("board") or ():
            if row.get("status") != "accepted":
                continue
            accepted_by_author[str(row.get("author"))] += 1
            delta = row.get("delta_i_bits")
            if delta is not None:
                authoritative_records += 1
                gross_bits += float(delta)
    exposures = sum(1 for case in cases
                    for event in case.get("board_log") or ()
                    if event.get("kind") == "peer_read_exposure")
    eligible = sum(1 for case in cases
                   if _case_is_eligible(case, selections[str(case["instance_id"])]))
    covered = sum(1 for row in rows if row["covered"])
    uncovered = [row for row in rows if not row["covered"]]
    tiers = sorted({str(case.get("normalization_tier")) for case in cases
                    if case.get("normalization_tier")})
    return {
        "cases_total": len(cases),
        "receiver_valid_cases": valid,
        "receiver_invalid_cases": invalid,
        "receiver_unattempted_cases": unattempted,
        "all_receiver_cases_valid": valid == len(cases),
        "accepted_messages": {
            "total": sum(accepted_by_author.values()),
            "by_author": dict(sorted(accepted_by_author.items())),
        },
        "authoritative_information_records": authoritative_records,
        "verified_read_exposures": exposures,
        "eligible_b_to_a_cases": eligible,
        "eligible_b_to_a_rate": eligible / len(cases) if cases else None,
        "distinct_pre_read_prompt_forms": len({row["prompt_form_id"] for row in rows}),
        "forms_with_eligible_exposure": covered,
        "forms_total": len(rows),
        "exactly_five_of_six_forms_covered": covered == 5 and len(rows) == 6,
        "uncovered_form_id": uncovered[0]["prompt_form_id"] if len(uncovered) == 1 else None,
        "gross_i_m_bits_from_board": gross_bits,
        "normalization_tiers": tiers,
        "resolved_models": sorted({str(case.get("resolved_model")) for case in cases
                                   if case.get("resolved_model")}),
        "forbidden_writer_outcomes": list(census["forbidden_outcomes_present"]),
        "invalid_writer_output_affected_result": bool(census["forbidden_outcomes_present"]),
        "status_reported": report.get("status"),
        "stop_reason_reported": report.get("stop_reason"),
        "eligible_definition": (
            "receiver_valid case with >=1 replay-selected B->A claim (accepted B-owned board "
            "write, verified A read provenance, recomputed I_m > 0, deduplicated)"),
    }


def information_accounting(cases: Sequence[Mapping[str, Any]],
                           selections: Mapping[str, Mapping[str, Any]],
                           rows: Sequence[Mapping[str, Any]],
                           report: Mapping[str, Any]) -> dict[str, Any]:
    by_direction = {"b_to_a": {"messages": 0, "bits": 0.0},
                    "a_to_b": {"messages": 0, "bits": 0.0}}
    for case in cases:
        for row in case.get("board") or ():
            if row.get("status") != "accepted" or row.get("delta_i_bits") is None:
                continue
            direction = "b_to_a" if str(row.get("author")) == "B" else "a_to_b"
            by_direction[direction]["messages"] += 1
            by_direction[direction]["bits"] += float(row["delta_i_bits"])

    eligible_selections = [selections[str(case["instance_id"])] for case in cases
                           if _case_is_eligible(case, selections[str(case["instance_id"])])]
    duplicates_removed = sum(1 for selection in selections.values()
                             for rejection in selection["rejected"]
                             if rejection["reason"] == "duplicate_claim_within_event")
    distinct_form_claims: set[tuple[str, str]] = set()
    for case in cases:
        selection = selections[str(case["instance_id"])]
        if not _case_is_eligible(case, selection):
            continue
        form_id = _form_of(rows, str(case["instance_id"]))
        distinct_form_claims.add((form_id, selection["selected"][0]["claim"]))
    eligible_bits = sum(selection["selected"][0]["i_m_bits"]
                        for selection in eligible_selections)

    rules = [
        "the primary replay direction is one-way B->A; A->B writes are excluded",
        "receiver-known claims and authoritative I_m = 0 claims are excluded",
        "at most one accepted, B-owned, informative claim per pre-read state",
        "verified board-write and A-read provenance are required (CommunicationEventLog)",
        "repeated identical B claims within an event are deduplicated to one claim",
        "gross transmitted bits are reported separately from replay-eligible information",
        "no symmetry across agents is claimed; A->B accounting is directional, not mirrored",
    ]
    return {
        "primary_replay_direction": "one-way B->A",
        "rules": rules,
        "gross_reported": {
            "source": "immutable report field i_m_bits (gross, both directions, with repeats)",
            "authoritative_records": report.get("authoritative_i_m"),
            "i_m_bits": report.get("i_m_bits"),
            "warning": ("the gross report total is NOT unique information delivered to Jev A: "
                        "it includes A->B messages and repeated identical B claims"),
        },
        "recomputed_gross": {
            "authoritative_records": by_direction["b_to_a"]["messages"]
            + by_direction["a_to_b"]["messages"],
            "i_m_bits": by_direction["b_to_a"]["bits"] + by_direction["a_to_b"]["bits"],
        },
        "by_direction": {
            "b_to_a": {"messages": by_direction["b_to_a"]["messages"],
                       "i_m_bits": by_direction["b_to_a"]["bits"]},
            "a_to_b_excluded": {"messages": by_direction["a_to_b"]["messages"],
                                "i_m_bits": by_direction["a_to_b"]["bits"]},
        },
        "b_to_a_duplicates_removed": {
            "messages": duplicates_removed,
            "i_m_bits": duplicates_removed * LOG2_3,
        },
        "replay_eligible": {
            "events": len(eligible_selections),
            "claims": len(eligible_selections),
            "i_m_bits": eligible_bits,
            "distinct_form_claims": len(distinct_form_claims),
            "distinct_form_claim_i_m_bits": len(distinct_form_claims) * LOG2_3,
            "distinct_form_claim_list": [{"prompt_form_id": form_id, "claim": claim}
                                         for form_id, claim in sorted(distinct_form_claims)],
            "note": ("each eligible event carries at most one claim; distinct model-visible "
                     "(form, claim) content is counted separately because instances within a "
                     "form repeat the same pre-read state and B clue"),
        },
        "no_agent_symmetry_claim": (
            "A->B writes are recorded as gross transmission only; nothing here mirrors the "
            "B->A estimand, guards, or eligibility onto agent A"),
    }


def _form_of(rows: Sequence[Mapping[str, Any]], instance_id: str) -> str:
    for row in rows:
        if instance_id in row["instance_ids"]:
            return str(row["prompt_form_id"])
    raise KeyError(f"instance not in any audited form: {instance_id}")


def frozen_estimand() -> dict[str, Any]:
    return {
        "experimental_unit": ("the distinct model-visible pre-read prompt form "
                              "(prompt_form_id), not the instance ID"),
        "primary_direction": "one-way B->A",
        "branches": {
            "H_real": "H(Y | C, M_real)",
            "H_placebo": "H(Y | C, M_placebo)",
            "H_null": "H(Y | C)",
        },
        "event_contrast": "d_i = H_real - H_placebo for replay event i in form f",
        "form_contrast": "d_f = mean(d_i) within form f over complete real/placebo pairs",
        "primary_estimand": "equal-weight mean of d_f across the six forms",
        "null_branch": ("retained and necessary for real-minus-null, placebo-minus-null and "
                        "manipulation checks even though it cancels from the primary "
                        "real-minus-placebo contrast"),
        "guards": ("p_target and feasible-set mass are guard metrics reported separately and "
                   "must not filter observations from the primary entropy estimate"),
        "missingness": ("missing real/placebo pairs are not imputed; branch missingness and "
                        "complete pairs are reported by form"),
        "claim_limits": [
            "instance-weighted analyses are secondary only",
            "no instance-level t-test or Wilcoxon as primary",
            "emission and exposure are not causal uptake",
        ],
    }


def inference_limits() -> dict[str, Any]:
    floor_k6 = ji.sign_flip_two_sided([-1.0] * 6)
    floor_k5 = ji.sign_flip_two_sided([-1.0] * 5)
    return {
        "primary_test": "exact two-sided cluster sign-flip test on form means",
        "interval": "form-mean t interval with df = k - 1",
        "sign_flip_floor": {
            "k_6": {"permutations": floor_k6["permutations"],
                    "expression": "2/64",
                    "min_two_sided_p": floor_k6["min_p_value"],
                    "exact_min_p": 2 / 64},
            "k_5": {"permutations": floor_k5["permutations"],
                    "expression": "2/32",
                    "min_two_sided_p": floor_k5["min_p_value"],
                    "exact_min_p": 2 / 32},
            "five_form_rule": ("a five-form result is interval-only and descriptive; it cannot "
                               "satisfy a two-sided alpha = 0.05 sign-flip gate because "
                               "2/32 = 0.0625"),
        },
        "secondary_only": ["instance-weighted analyses"],
        "not_primary": ["instance-level t-test", "instance-level Wilcoxon"],
        "missingness_rule": ("missing real/placebo pairs are not imputed; report branch "
                             "missingness and complete pairs by form"),
        "guards_rule": ("p_target and feasible-set mass are reported separately and never "
                        "filter the primary entropy estimate"),
        "form_space_limit": ("the known form space contains only six forms, so adding duplicate "
                             "instance IDs cannot increase k"),
    }


def sensitivity_scale(journal_path: Path | None = None) -> dict[str, Any]:
    """Reproduce the illustrative six-form 95% t-interval half-width scale."""

    k = 6
    df = k - 1
    t_critical = ji.t_critical_975(df)
    half_width = t_critical * ILLUSTRATIVE_BETWEEN_FORM_SD_BITS / math.sqrt(k)
    recomputed_sd = None
    sd_source_path = None
    sd_source_sha256 = None
    path = Path(journal_path) if journal_path is not None else REPO_ROOT / ILLUSTRATIVE_SD_JOURNAL_REL
    if path.exists():
        sd_source_path = str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)
        sd_source_sha256 = sha256_file(path)
        rows = load_journal(path)
        recomputed_sd = pr.between_form_sd(rows)
    recomputed_half = (t_critical * recomputed_sd / math.sqrt(k)) if recomputed_sd else None
    return {
        "illustrative_between_form_sd_bits": ILLUSTRATIVE_BETWEEN_FORM_SD_BITS,
        "illustrative_sd_source": (
            "between-form SD of the J3 ISO-FULL form-mean entropy differences (method "
            "demonstration only; not a real-placebo effect or power estimate)"),
        "illustrative_sd_source_path": sd_source_path,
        "illustrative_sd_source_sha256": sd_source_sha256,
        "illustrative_sd_recomputed_bits": recomputed_sd,
        "k": k,
        "df": df,
        "t_critical_975": t_critical,
        "expression": "t(0.975,5) * 0.1933 / sqrt(6)",
        "half_width_bits": half_width,
        "half_width_rounded_bits": round(half_width, 3),
        "half_width_recomputed_sd_bits": recomputed_half,
        "interpretation": (
            "planning/sensitivity context, not a guaranteed powered effect threshold: a null "
            "result cannot rule out effects smaller than roughly 0.2 bits"),
        "form_space_note": ("the known form space contains only six forms; duplicate instance "
                            "IDs cannot increase k"),
    }


def fresh_coverage_sizing(*, eligible_numerator: int | None = None,
                          eligible_denominator: int | None = None,
                          n_per_form: int = 6, forms: int = 6) -> dict[str, Any]:
    """Assumption-based N=36 sizing heuristic documented for the #190 handoff."""

    numerator = 9 if eligible_numerator is None else eligible_numerator
    denominator = 17 if eligible_denominator is None else eligible_denominator
    rate = numerator / denominator
    per_form = 1.0 - (1.0 - rate) ** n_per_form
    all_forms = per_form ** forms
    return {
        "handoff_to": "#190",
        "status": "documented only; #189 does not implement #190",
        "observed_eligible_instance_rate": {
            "numerator": numerator,
            "denominator": denominator,
            "value": rate,
            "rounded": round(rate, 3),
            "expression": f"{numerator}/{denominator}",
        },
        "target": {
            "fresh_instances_per_form": n_per_form,
            "forms": forms,
            "N": n_per_form * forms,
        },
        "assumption": ("simplifying independent-rate assumption; this calculation is a sizing "
                       "heuristic, not evidence that instance eligibility is independent"),
        "probability_one_form_has_at_least_one": {
            "expression": f"1 - (1 - {numerator}/{denominator})^{n_per_form}",
            "value": per_form,
            "rounded": round(per_form, 3),
        },
        "probability_all_forms_have_at_least_one": {
            "expression": f"[1 - (1 - {numerator}/{denominator})^{n_per_form}]^{forms}",
            "value": all_forms,
            "rounded": round(all_forms, 3),
        },
        "requirements": [
            "a new registration and manifest; do not append to the frozen 17-instance artifact",
            "seed-to-form selection may happen offline because form identity is deterministic",
            "the future collection uses fixed N with no stopping after the first message",
        ],
    }


def report_crosscheck(cases: Sequence[Mapping[str, Any]], report: Mapping[str, Any],
                      rows: Sequence[Mapping[str, Any]],
                      selections: Mapping[str, Mapping[str, Any]],
                      census: Mapping[str, Any],
                      facts: Mapping[str, Any]) -> dict[str, Any]:
    recomputed_writes = Counter()
    recomputed_gross_bits = 0.0
    authoritative = 0
    exposures = 0
    for case in cases:
        for row in case.get("board") or ():
            if row.get("status") == "accepted":
                recomputed_writes[str(row.get("author"))] += 1
                if row.get("delta_i_bits") is not None:
                    authoritative += 1
                    recomputed_gross_bits += float(row["delta_i_bits"])
        exposures += sum(1 for event in case.get("board_log") or ()
                         if event.get("kind") == "peer_read_exposure")
    rejected_events = sum(1 for case in cases
                          for event in case.get("board_log") or ()
                          if event.get("kind") == "board_write_rejected")
    journal_eligible = sum(1 for case in cases if case.get("eligible_exposure"))
    recomputed_eligible = facts["eligible_b_to_a_cases"]
    checks = [
        {"check": "status_completed", "recomputed": "completed", "reported": report.get("status"),
         "ok": report.get("status") == "completed"},
        {"check": "stop_reason_none", "recomputed": None, "reported": report.get("stop_reason"),
         "ok": report.get("stop_reason") is None},
        {"check": "receiver_valid_cases",
         "recomputed": facts["receiver_valid_cases"], "reported": report.get("receiver_valid_cases"),
         "ok": facts["receiver_valid_cases"] == report.get("receiver_valid_cases")},
        {"check": "receiver_invalid_cases",
         "recomputed": facts["receiver_invalid_cases"], "reported": report.get("receiver_invalid_cases"),
         "ok": facts["receiver_invalid_cases"] == report.get("receiver_invalid_cases")},
        {"check": "receiver_unattempted_cases",
         "recomputed": facts["receiver_unattempted_cases"],
         "reported": report.get("receiver_unattempted_cases"),
         "ok": facts["receiver_unattempted_cases"] == report.get("receiver_unattempted_cases")},
        {"check": "writes_by_agent",
         "recomputed": dict(sorted(recomputed_writes.items())),
         "reported": dict(sorted((report.get("writes_by_agent") or {}).items())),
         "ok": dict(recomputed_writes) == dict(report.get("writes_by_agent") or {})},
        {"check": "board_messages",
         "recomputed": sum(recomputed_writes.values()), "reported": report.get("board_messages"),
         "ok": sum(recomputed_writes.values()) == report.get("board_messages")},
        {"check": "authoritative_i_m",
         "recomputed": authoritative, "reported": report.get("authoritative_i_m"),
         "ok": authoritative == report.get("authoritative_i_m")},
        {"check": "i_m_bits",
         "recomputed": round(recomputed_gross_bits, 9), "reported": report.get("i_m_bits"),
         "ok": math.isclose(round(recomputed_gross_bits, 9), float(report.get("i_m_bits") or 0.0),
                            rel_tol=0.0, abs_tol=1e-12)},
        {"check": "verified_read_exposures",
         "recomputed": exposures, "reported": report.get("verified_read_exposures"),
         "ok": exposures == report.get("verified_read_exposures")},
        {"check": "distinct_forms",
         "recomputed": facts["distinct_pre_read_prompt_forms"],
         "reported": report.get("distinct_forms"),
         "ok": facts["distinct_pre_read_prompt_forms"] == report.get("distinct_forms")},
        {"check": "eligible_cases_match_journal_flag",
         "recomputed": recomputed_eligible, "reported": journal_eligible,
         "ok": recomputed_eligible == journal_eligible},
        {"check": "rejected_writes",
         "recomputed": rejected_events, "reported": report.get("rejected_writes"),
         "ok": rejected_events == report.get("rejected_writes")},
        {"check": "forbidden_writer_outcomes_absent",
         "recomputed": list(census["forbidden_outcomes_present"]), "reported": [],
         "ok": not census["forbidden_outcomes_present"]},
        {"check": "planned_cases_equal_journal_rows",
         "recomputed": len(cases), "reported": report.get("planned_cases"),
         "ok": len(cases) == report.get("planned_cases")},
    ]
    return {"ok": all(check["ok"] for check in checks), "checks": checks,
            "failed": [check["check"] for check in checks if not check["ok"]]}


def build_audit(repo_root: Path | None = None) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    inputs = verify_pinned_inputs(root)
    journal_path = root / DEFAULT_JOURNAL_REL
    report_path = root / DEFAULT_REPORT_REL
    cases = load_journal(journal_path)
    report = load_report(report_path)
    instances = pilot_instances()
    if {str(case["instance_id"]) for case in cases} != {instance.instance_id for instance in instances}:
        raise ValueError("journal_instance_set_mismatch")

    form_ids = pre_read_form_ids(instances)
    registered_forms = set(pr.frozen_forms()["iso_form_ids"])
    if set(form_ids.values()) != registered_forms:
        raise ValueError("prompt_form_set_mismatch_vs_registered_manifest")

    by_id = {instance.instance_id: instance for instance in instances}
    selections = {str(case["instance_id"]): select_replay_claims(case, by_id[str(case["instance_id"])])
                  for case in cases}
    census = writer_outcome_census(cases)
    rows = form_audit_table(cases, instances, form_ids, selections)
    geometry = form_geometry(rows)
    facts = coverage_facts(cases, report, rows, selections, census)
    accounting = information_accounting(cases, selections, rows, report)
    crosscheck = report_crosscheck(cases, report, rows, selections, census, facts)
    if not crosscheck["ok"]:
        raise ValueError(f"report_crosscheck_failed: {crosscheck['failed']}")
    uncovered = uncovered_form_record(rows, geometry)
    if uncovered is None or facts["uncovered_form_id"] != uncovered["prompt_form_id"]:
        raise ValueError("uncovered_form_cardinality_mismatch")

    inputs_block = {
        "journal": {"path": DEFAULT_JOURNAL_REL, "sha256": EXPECTED_JOURNAL_SHA256,
                    "immutable": True, "write_attempts_by_audit": 0},
        "report": {"path": DEFAULT_REPORT_REL, "sha256": EXPECTED_REPORT_SHA256,
                   "immutable": True, "write_attempts_by_audit": 0},
        "verification": inputs,
        "task_generator": {
            "module": "apart_incident_response.task_families",
            "generator_version": tf.GENERATOR_VERSION,
            "checker_version": tf.CHECKER_VERSION,
            "family": "planning",
            "regime": "N",
            "complexity": "low",
            "seed_base": pr.JEV_REPLAY_SEED_BASE,
            "per_block": pr.JEV_REPLAY_PER_BLOCK,
            "instance_count": len(instances),
        },
        "registered_manifest": {
            "source": "jev_replay_preregistration.frozen_forms",
            "paired_forms": len(registered_forms),
        },
    }

    audit = {
        "audit_version": AUDIT_VERSION,
        "issue": ISSUE_ID,
        "generated_by": "src/apart_incident_response/jev_six_form_coverage_audit.py",
        "mode": "offline-analysis-only",
        "provider_calls": 0,
        "inputs": inputs_block,
        "coverage_facts": facts,
        "writer_outcome_census": census,
        "forms": rows,
        "information_geometry": geometry,
        "uncovered_form": uncovered,
        "information_accounting": accounting,
        "estimand": frozen_estimand(),
        "inference_limits": inference_limits(),
        "sensitivity": sensitivity_scale(root / ILLUSTRATIVE_SD_JOURNAL_REL),
        "fresh_coverage_handoff": fresh_coverage_sizing(
            eligible_numerator=facts["eligible_b_to_a_cases"],
            eligible_denominator=facts["cases_total"]),
        "report_crosscheck": crosscheck,
        "prior_artifacts_modified": [],
        "claim_scope": (
            "coverage and accounting audit of the frozen 17-instance L4X v5 block, "
            "conditional on the six known prompt forms; no causal, calibration, or "
            "held-out claim"),
    }
    return audit


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{ISSUE_ID} six-form coverage audit")
    parser.add_argument("--output", type=Path, default=None,
                        help="audit artifact path (default: %(default)s)")
    parser.add_argument("--repo-root", type=Path, default=None,
                        help="repository root containing runs/epic-126 (default: source tree)")
    args = parser.parse_args(argv)
    root = Path(args.repo_root) if args.repo_root is not None else REPO_ROOT
    audit = build_audit(root)
    output = Path(args.output) if args.output is not None else root / DEFAULT_OUTPUT_REL
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit, indent=2, sort_keys=True, allow_nan=False) + "\n",
                      encoding="utf-8")
    summary = {
        "audit_version": audit["audit_version"],
        "output": str(output),
        "report_crosscheck_ok": audit["report_crosscheck"]["ok"],
        "coverage": {
            "valid_cases": audit["coverage_facts"]["receiver_valid_cases"],
            "eligible_b_to_a_cases": audit["coverage_facts"]["eligible_b_to_a_cases"],
            "forms_covered": audit["coverage_facts"]["forms_with_eligible_exposure"],
            "forms_total": audit["coverage_facts"]["forms_total"],
            "uncovered_form_id": audit["coverage_facts"]["uncovered_form_id"],
        },
        "replay_eligible_bits": audit["information_accounting"]["replay_eligible"]["i_m_bits"],
        "provider_calls": 0,
    }
    print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AUDIT_VERSION", "ISSUE_ID", "DEFAULT_JOURNAL_REL", "DEFAULT_REPORT_REL",
    "DEFAULT_OUTPUT_REL", "EXPECTED_JOURNAL_SHA256", "EXPECTED_REPORT_SHA256",
    "FORBIDDEN_WRITER_OUTCOMES", "ILLUSTRATIVE_BETWEEN_FORM_SD_BITS", "LOG2_3", "REJECTIONS",
    "sha256_file", "load_journal", "load_report", "verify_pinned_inputs",
    "pre_read_form_ids", "writer_outcome_census", "select_replay_claims",
    "form_audit_table", "form_geometry", "uncovered_form_record", "coverage_facts",
    "information_accounting", "frozen_estimand", "inference_limits", "sensitivity_scale",
    "fresh_coverage_sizing", "report_crosscheck", "build_audit", "main",
]
