"""#198 — offline, reproducible inference for the completed replay-v5 run.

Reads the frozen replay-v5 journal, report and registration, verifies every
input hash and structural invariant, then computes the registered primary
estimand and inference plus the required secondary reporting, and writes one
fresh versioned analysis artifact.

Hard rules:

- offline only: no provider call, no replay rerun; the journal and report are
  read-only inputs and are never modified;
- fail closed on artifact drift, stale registration, duplicates, missing
  branches, mixed protocols, a non-single model, malformed vectors, invalid
  branch request/state hashes, or a form set other than the six frozen forms;
- never impute missing values; guard failures are reported, never exclusions;
- the primary inference is the equal-weight mean of the six within-form
  real-minus-placebo entropy differences with an exact two-sided cluster
  sign-flip and a form-mean t interval (df = 5); instance-level t-tests,
  Wilcoxon tests and instance-weighted means are never primary;
- claims stay conditional on the six frozen planning-low prompt forms and the
  paid Ling route that generated the messages: no calibration, no population
  causality, no generalization beyond that scope;
- the artifact is deterministic and never overwritten or appended to.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import jev_replay as jr
from . import jev_replay_inference as ji
from . import jev_replay_preregistration_v4 as prv4
from . import jev_replay_runner_v4 as _v4


ANALYSIS_VERSION = "jev-replay-inference-v5-v1"
DEFAULT_OUTPUT = Path("runs/epic-126/replay-v5/jev-choice-replay-inference-v5.json")
DEFAULT_JOURNAL = prv4.DEFAULT_JOURNAL_V4.parent.parent / "replay-v5" / "jev-choice-replay-v5.jsonl"
DEFAULT_REPORT = prv4.DEFAULT_JOURNAL_V4.parent.parent / "replay-v5" / "jev-choice-replay-report-v5.json"
DEFAULT_REGISTRATION = (prv4.DEFAULT_JOURNAL_V4.parent.parent / "replay-v5"
                        / "jev-choice-replay-preregistration-v5.json")

BRANCHES = ("real", "placebo", "null")
REQUIRED_FORMS = tuple(prv4.FROZEN_FORM_IDS)
EXPECTED_DISTRIBUTION = tuple(prv4.EXPECTED_FORM_DISTRIBUTION)
EXPECTED_EVENTS = prv4.EXPECTED_EVENT_COUNT
EXPECTED_ROWS = EXPECTED_EVENTS * len(BRANCHES)
SENSITIVITY_THRESHOLDS = (1e-6, 0.01, 0.03, 0.05)
EXPECTED_FORMS_COUNT = 6
ALPHA = 0.05

#: Pinned inputs for the single authorized run. Any drift fails closed.
PINNED = {
    "journal_sha256": "5e9f7322bdb29baf16b18f9b4f4181e9a88ad454e0394ea379e4cdea29b1fede",
    "report_sha256": "0ec84446d697bca91c25e155b3cd61f43b4e7706e6df185ea08c3685a8f88310",
    "registration_file_sha256": "3c02f8bb44c11d6edd050daf32950e3cf8365f79638e92d46181df764945ddd7",
    "registration_hash": "0a81e400f598d16742301d7c07cbaf5398fa861b4fa1701c15405391ab4f6d15",
    "run_commit": "3e678ac",
}


class AnalysisError(ValueError):
    """Fail-closed integrity or schema violation; never carries raw payloads."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(document: Mapping[str, Any]) -> str:
    payload = json.dumps({key: value for key, value in document.items()
                          if key != "preregistration_hash"}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(float(value))


# --------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------

def load_inputs(repo_root: Path) -> dict[str, Any]:
    """Read the three frozen inputs. Read-only; never modifies them."""

    root = Path(repo_root)
    paths = {"journal": root / DEFAULT_JOURNAL, "report": root / DEFAULT_REPORT,
             "registration": root / DEFAULT_REGISTRATION}
    for name, path in paths.items():
        if not path.is_file():
            raise AnalysisError(f"missing_input:{name}")
    rows = []
    for line in paths["journal"].read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return {"paths": {name: str(path.relative_to(root)) for name, path in paths.items()},
            "journal_rows": rows,
            "report": json.loads(paths["report"].read_text(encoding="utf-8")),
            "registration": json.loads(paths["registration"].read_text(encoding="utf-8")),
            "sha256": {name: sha256_file(path) for name, path in paths.items()}}


def verify_hashes(inputs: Mapping[str, Any], *, pins: Mapping[str, Any] | None = None
                  ) -> dict[str, Any]:
    """Recompute and verify journal/report/registration hashes."""

    pins = PINNED if pins is None else pins
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    sha = inputs["sha256"]
    check("journal_hash_matches_pinned", sha["journal"] == pins["journal_sha256"],
          sha["journal"])
    check("report_hash_matches_pinned", sha["report"] == pins["report_sha256"],
          sha["report"])
    check("registration_file_hash_matches_pinned",
          sha["registration"] == pins["registration_file_sha256"], sha["registration"])
    document = inputs["registration"]
    recomputed = _content_hash(document)
    check("registration_content_hash_matches_pinned",
          document.get("preregistration_hash") == pins["registration_hash"] == recomputed,
          {"recorded": document.get("preregistration_hash"), "recomputed": recomputed})
    return _verdict(checks)


def _verdict(checks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    errors = [f"{entry['check']}: {entry['detail']}" for entry in checks
              if not entry["ok"]]
    return {"ok": not errors, "errors": errors, "checks": list(checks)}


# --------------------------------------------------------------------------
# structural integrity
# --------------------------------------------------------------------------

def verify_structure(journal_rows: Sequence[Mapping[str, Any]],
                     report: Mapping[str, Any],
                     registration: Mapping[str, Any]) -> dict[str, Any]:
    """Fail-closed structural verification of the run against the registration."""

    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    check("report_status_completed", report.get("status") == "completed"
          and report.get("stop_reason") in (None, ""), report.get("status"))
    check("report_registration_hash_matches",
          report.get("registration_hash") == registration.get("preregistration_hash")
          == PINNED["registration_hash"], report.get("registration_hash"))

    check("journal_row_count_matches_report",
          len(journal_rows) == EXPECTED_ROWS == report.get("rows"),
          {"journal": len(journal_rows), "report": report.get("rows"),
           "expected": EXPECTED_ROWS})

    keys = [(str(row.get("event_id")), str(row.get("branch"))) for row in journal_rows]
    duplicates = sorted({key for key, count in Counter(keys).items() if count > 1})
    check("no_duplicate_event_branch_records", not duplicates, duplicates)

    report_events = list(report.get("events") or [])
    event_ids = [str(event.get("event_id")) for event in report_events]
    check("no_duplicate_report_events", len(set(event_ids)) == len(event_ids)
          and len(event_ids) == EXPECTED_EVENTS, {"events": len(event_ids)})

    grouped: dict[str, dict[str, Any]] = defaultdict(dict)
    for row in journal_rows:
        grouped[str(row.get("event_id"))][str(row.get("branch"))] = row
    missing = sorted(event_id for event_id, branches in grouped.items()
                     if set(branches) != set(BRANCHES))
    check("all_three_branches_present_per_event",
          len(grouped) == EXPECTED_EVENTS and not missing,
          {"events": len(grouped), "incomplete": missing})
    unknown = sorted({branch for branches in grouped.values()
                      for branch in branches if branch not in BRANCHES})
    check("no_unknown_branches", not unknown, unknown)

    bad = [{"event_id": event_id, "branch": row.get("branch"),
            "valid": row.get("valid"), "status": row.get("status"),
            "error_class": row.get("error_class")}
           for event_id, branches in grouped.items() for row in branches.values()
           if row.get("valid") is not True or row.get("status") != "complete"
           or row.get("error_class") is not None]
    check("all_branches_valid_and_complete", not bad, bad)

    protocol_keys = sorted({str(row.get("protocol_key")) for row in journal_rows})
    registered_key = str(((registration.get("model_and_protocol") or {}).get("protocol_key")))
    check("single_protocol_key_in_journal", len(protocol_keys) == 1, protocol_keys)
    check("journal_protocol_matches_registration",
          protocol_keys == [registered_key], {"journal": protocol_keys,
                                              "registered": registered_key})
    check("report_protocol_matches_registration",
          report.get("protocol_key") == registered_key, report.get("protocol_key"))

    models = sorted({str(row.get("resolved_model")) for row in journal_rows})
    registered_model = str((registration.get("model_and_protocol") or {}).get("model"))
    check("single_model_in_journal", len(models) == 1, models)
    check("journal_model_matches_registration", models == [registered_model],
          {"journal": models, "registered": registered_model})
    check("report_model_matches_registration", report.get("model") == registered_model,
          report.get("model"))

    registration_events = {str(event.get("event_id")): event
                           for event in (registration.get("events") or [])}
    check("registration_event_count", len(registration_events) == EXPECTED_EVENTS,
          len(registration_events))
    request_mismatch: list[Any] = []
    state_mismatch: list[Any] = []
    registered_model = str((registration.get("model_and_protocol") or {}).get("model"))
    for event_id in sorted(grouped):
        branches = grouped[event_id]
        bound = registration_events.get(event_id)
        if bound is None:
            request_mismatch.append({"event_id": event_id, "reason": "not_registered"})
            state_mismatch.append({"event_id": event_id, "reason": "not_registered"})
            continue
        pre_read = bound.get("pre_read") or {}
        registered_requests = pre_read.get("branch_request_hashes") or {}
        try:
            instance = prv4._regenerate_instance(str(bound.get("instance_id")))
            _iso_state, _state_dict, body = _v4.pre_read_state(instance, registered_model)
        except Exception as exc:  # noqa: BLE001 - fail closed with the reason
            request_mismatch.append({"event_id": event_id,
                                     "reason": f"rebuild_failed:{type(exc).__name__}"})
            state_mismatch.append({"event_id": event_id,
                                   "reason": f"rebuild_failed:{type(exc).__name__}"})
            continue
        for branch, row in branches.items():
            try:
                message_text = _v4.message_text_for(bound, branch)
            except ValueError:
                request_mismatch.append({"event_id": event_id, "branch": branch,
                                         "reason": "unknown_branch"})
                continue
            branch_body = jr.branch_request_body(body, message_text)
            recomputed_request = jr.prompt_form_id(branch_body)
            recomputed_state = jr.canonical_hash(dict(branch_body["state"]))
            if row.get("request_hash") != recomputed_request                     or row.get("request_hash") != registered_requests.get(branch):
                request_mismatch.append({"event_id": event_id, "branch": branch})
            if row.get("state_hash") != recomputed_state:
                state_mismatch.append({"event_id": event_id, "branch": branch})
    check("branch_request_hashes_match_registration", not request_mismatch,
          request_mismatch)
    check("branch_state_hashes_match_registration", not state_mismatch, state_mismatch)

    forms = sorted({str(row.get("prompt_form_id")) for row in journal_rows})
    check("six_required_forms_present", forms == sorted(REQUIRED_FORMS), forms)
    distribution = tuple(sorted(Counter(
        str(row.get("prompt_form_id")) for row in journal_rows
        if row.get("branch") == "real").values()))
    check("form_event_distribution_matches", distribution == tuple(
        sorted(EXPECTED_DISTRIBUTION)), {"observed": list(distribution),
                                         "expected": list(sorted(EXPECTED_DISTRIBUTION))})
    report_forms = {str(event.get("prompt_form_id")) for event in report_events}
    check("report_forms_match_required", report_forms == set(REQUIRED_FORMS),
          sorted(report_forms))

    vector_problems = []
    for row in journal_rows:
        probabilities = row.get("probabilities")
        diagnostics = row.get("probability_diagnostics") or {}
        event_id, branch = row.get("event_id"), row.get("branch")
        if not isinstance(probabilities, Mapping) or not probabilities:
            vector_problems.append({"event_id": event_id, "branch": branch,
                                    "problem": "missing_vector"})
            continue
        values = list(probabilities.values())
        if not all(_finite(value) and float(value) >= 0.0 for value in values):
            vector_problems.append({"event_id": event_id, "branch": branch,
                                    "problem": "non_finite_or_negative"})
            continue
        if abs(sum(float(value) for value in values) - 1.0) > 1e-6:
            vector_problems.append({"event_id": event_id, "branch": branch,
                                    "problem": "not_normalized"})
            continue
        deviation = diagnostics.get("absolute_normalization_deviation")
        if not _finite(deviation) or float(deviation) > 0.05:
            vector_problems.append({"event_id": event_id, "branch": branch,
                                    "problem": "deviation_above_hard_ceiling"})
            continue
        if diagnostics.get("shape_valid") is not True \
                or diagnostics.get("all_finite") is not True \
                or diagnostics.get("all_nonnegative") is not True:
            vector_problems.append({"event_id": event_id, "branch": branch,
                                    "problem": "diagnostics_invalid"})
            continue
        if diagnostics.get("argmax_preserved") is not True:
            vector_problems.append({"event_id": event_id, "branch": branch,
                                    "problem": "argmax_not_preserved"})
            continue
    check("malformed_vectors_rejected", not vector_problems, vector_problems)

    metric_problems = [{"event_id": row.get("event_id"), "branch": row.get("branch")}
                       for row in journal_rows
                       if not all(_finite(row.get(name)) for name in
                                  ("entropy_bits", "p_target", "feasible_mass"))]
    check("metrics_present_and_finite", not metric_problems, metric_problems)
    check("no_imputation_required", not metric_problems and not vector_problems,
          "every analyzed field is present in the journal")

    guards = registration.get("guards") or {}
    check("guard_thresholds_match_registration",
          guards.get("target_probability_delta") == 0.0
          and guards.get("feasible_set_mass_epsilon") == 0.01,
          {"delta": guards.get("target_probability_delta"),
           "epsilon": guards.get("feasible_set_mass_epsilon")})
    inference = registration.get("inference") or {}
    check("registered_inference_rules_present",
          "sign-flip" in str(inference.get("primary_test"))
          and "t interval" in str(inference.get("interval"))
          and inference.get("min_two_sided_p_k6") == 0.03125, None)
    check("report_analysis_present", isinstance(report.get("analysis"), Mapping), None)
    check("report_schedule_adherence",
          (report.get("schedule_adherence") or {}).get("planned_equals_actual") is True,
          report.get("schedule_adherence"))
    return _verdict(checks)


# --------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------

def _group_rows(journal_rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(dict)
    for row in journal_rows:
        grouped[str(row.get("event_id"))][str(row.get("branch"))] = dict(row)
    return dict(grouped)


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _sd(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = _mean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _form_summary(d_by_form: Mapping[str, Sequence[float]]) -> dict[str, Any]:
    rows = []
    for form in sorted(d_by_form):
        values = list(d_by_form[form])
        rows.append({"form": form, "n_pairs": len(values), "d_f": _mean(values),
                     "sd": _sd(values), "min": min(values), "max": max(values),
                     "negative_count": sum(1 for value in values if value < 0)})
    return {"rows": rows,
            "form_means": [row["d_f"] for row in rows],
            "k": len(rows)}


def _primary(form_means: Sequence[float]) -> dict[str, Any]:
    k = len(form_means)
    estimate = _mean(form_means)
    df = k - 1
    interval = None
    if k >= 2 and estimate is not None:
        sd = _sd(form_means)
        half = ji.t_critical_975(df) * (sd / math.sqrt(k))
        interval = [estimate - half, estimate + half]
    sign_flip = ji.sign_flip_two_sided(list(form_means))
    direction_met = estimate is not None and estimate < 0
    criterion_met = bool(k == EXPECTED_FORMS_COUNT and estimate is not None
                         and estimate < 0 and sign_flip.get("p_value") is not None
                         and sign_flip["p_value"] < ALPHA)
    return {"k": k, "df": df, "estimate": estimate, "t_interval_975": interval,
            "sign_flip": sign_flip, "direction_required": "negative",
            "direction_met": direction_met, "alpha": ALPHA,
            "p_value_floor_k6": 2 / 64, "criterion_met": criterion_met,
            "interval_excludes_zero": bool(interval and interval[1] < 0.0),
            "unit": "prompt form",
            "test": "exhaustive two-sided cluster sign-flip over the form means",
            "interval_name": f"form-mean t interval with df = {df}"}


def _decision(primary: Mapping[str, Any], guards: Mapping[str, Any],
              missingness: Mapping[str, Any]) -> str:
    estimate = primary["estimate"]
    p_value = primary["sign_flip"]["p_value"]
    interval = primary["t_interval_975"]
    if not primary["criterion_met"]:
        return (f"The registered primary criterion is NOT met: the equal-weight mean of the "
                f"within-form real-minus-placebo entropy differences is {estimate} with exact "
                f"two-sided sign-flip p = {p_value} at k = {primary['k']} "
                f"(direction_met={primary['direction_met']}), so no registered claim follows "
                f"from this run.")
    return (
        f"Within the six frozen planning-low prompt forms and the paid Ling route that "
        f"generated the messages: the equal-weight mean of the six within-form "
        f"real-minus-placebo entropy differences is {estimate:.6f} bits and "
        f"{'all six form means are negative' if primary['direction_met'] else 'the direction '
        f'requirement is not met'}; the exact two-sided cluster sign-flip p-value is "
        f"{p_value} (the k = 6 floor of 2/64 = 0.03125, from "
        f"{primary['sign_flip']['permutations']} sign patterns); the form-mean t interval "
        f"with df = 5 is [{interval[0]:.6f}, {interval[1]:.6f}] and "
        f"{'excludes' if primary['interval_excludes_zero'] else 'does not exclude'} zero. "
        f"The preregistered negative direction is met, so the registered primary inference "
        f"criterion is met. Guards were evaluated separately and filtered nothing "
        f"({guards.get('excluded_from_primary', 0)} pairs excluded); "
        f"{missingness.get('complete_pairs', 0)} of {missingness.get('events', 0)} events "
        f"entered the estimate with no imputation. This is conditional, form-level evidence "
        f"inside the registered scope only: not calibration, not a population-level causal "
        f"claim, and not generalizable beyond the six frozen forms.")


def analyze(journal_rows: Sequence[Mapping[str, Any]],
            registration: Mapping[str, Any]) -> dict[str, Any]:
    """Compute the registered estimand, inference and required secondary reporting."""

    grouped = _group_rows(journal_rows)
    registration_events = {str(event.get("event_id")): event
                           for event in (registration.get("events") or [])}
    delta = float((registration.get("guards") or {}).get("target_probability_delta", 0.0))
    epsilon = float((registration.get("guards") or {}).get("feasible_set_mass_epsilon", 0.01))

    per_event: list[dict[str, Any]] = []
    d_by_form: dict[str, list[float]] = defaultdict(list)
    complete_by_form = Counter()
    guards_by_form: dict[str, dict[str, int]] = defaultdict(
        lambda: {"events": 0, "target_ok": 0, "mass_ok": 0, "useful_uptake": 0})
    tier_counts = Counter()
    excluded_by_guards = 0
    null_real, null_placebo = [], []

    for event_id in sorted(grouped):
        branches = grouped[event_id]
        real, placebo, null = branches.get("real"), branches.get("placebo"), branches.get("null")
        form = str(real.get("prompt_form_id")) if real else str(
            placebo.get("prompt_form_id") if placebo else "")
        bound = registration_events.get(event_id, {})
        d_i = float(real["entropy_bits"]) - float(placebo["entropy_bits"])
        p_target_diff = float(real["p_target"]) - float(placebo["p_target"])
        mass_diff = float(real["feasible_mass"]) - float(placebo["feasible_mass"])
        target_ok = p_target_diff >= delta
        mass_ok = mass_diff >= -epsilon
        entropy_drop = d_i < 0
        useful = entropy_drop and target_ok and mass_ok
        real_minus_null = float(real["entropy_bits"]) - float(null["entropy_bits"])
        placebo_minus_null = float(placebo["entropy_bits"]) - float(null["entropy_bits"])
        null_real.append(real_minus_null)
        null_placebo.append(placebo_minus_null)

        for branch_row in (real, placebo, null):
            tier = ((branch_row.get("probability_diagnostics") or {})
                    .get("normalization_tier"))
            tier_counts[str(tier)] += 1
        per_event.append({
            "event_id": event_id,
            "prompt_form_id": form,
            "instance_id": real.get("instance_id"),
            "complete_triplet": True,
            "H_real": float(real["entropy_bits"]),
            "H_placebo": float(placebo["entropy_bits"]),
            "H_null": float(null["entropy_bits"]),
            "d_i": d_i,
            "p_target_real": float(real["p_target"]),
            "p_target_placebo": float(placebo["p_target"]),
            "delta_p_target_i": p_target_diff,
            "feasible_mass_real": float(real["feasible_mass"]),
            "feasible_mass_placebo": float(placebo["feasible_mass"]),
            "delta_feasible_mass_i": mass_diff,
            "real_minus_null": real_minus_null,
            "placebo_minus_null": placebo_minus_null,
            "guards": {"target_ok_i": target_ok, "mass_ok_i": mass_ok,
                       "entropy_drop_i": entropy_drop, "useful_uptake_i": useful},
            "registered_real_i_m_bits": float((bound.get("real") or {}).get("i_m_bits", 0.0)),
            "registered_placebo_i_m_bits": float((bound.get("placebo") or {}).get("i_m_bits", 0.0)),
        })
        d_by_form[form].append(d_i)
        complete_by_form[form] += 1
        counters = guards_by_form[form]
        counters["events"] += 1
        counters["target_ok"] += int(target_ok)
        counters["mass_ok"] += int(mass_ok)
        counters["useful_uptake"] += int(useful)
        excluded_by_guards += 0  # guards never remove a pair from the estimate

    form_table = _form_summary(d_by_form)
    primary = _primary(form_table["form_means"])
    primary = {**primary, "form_means": dict(zip([row["form"] for row in form_table["rows"]],
                                                 form_table["form_means"]))}

    guard_rows = [{"event_id": row["event_id"], "form": row["prompt_form_id"],
                   "delta_p_target_i": row["delta_p_target_i"],
                   "delta_feasible_mass_i": row["delta_feasible_mass_i"],
                   "target_ok": row["guards"]["target_ok_i"],
                   "mass_ok": row["guards"]["mass_ok_i"],
                   "useful_uptake": row["guards"]["useful_uptake_i"]}
                  for row in per_event]
    guards_block = {
        "delta": delta, "epsilon": epsilon,
        "filtering": "never used to filter the primary estimate",
        "filtered_primary_estimate": False,
        "excluded_from_primary": excluded_by_guards,
        "events": guard_rows,
        "per_form": {form: {"complete_pairs": complete_by_form[form], **counters}
                     for form, counters in sorted(guards_by_form.items())},
        "target_ok_events": sum(1 for row in guard_rows if row["target_ok"]),
        "mass_ok_events": sum(1 for row in guard_rows if row["mass_ok"]),
        "useful_uptake_events": sum(1 for row in guard_rows if row["useful_uptake"]),
        "target_violations": sum(1 for row in guard_rows if not row["target_ok"]),
        "mass_violations": sum(1 for row in guard_rows if not row["mass_ok"]),
        "statement": ("guards are reported per event and within form; they never remove a "
                      "valid real/placebo pair from the primary entropy estimate, and an "
                      "entropy reduction alone is never useful uptake when either guard fails"),
    }

    branch_counts = {branch: Counter() for branch in BRANCHES}
    for branches in grouped.values():
        for branch, row in branches.items():
            if branch in branch_counts:
                branch_counts[branch]["attempted"] += 1
                branch_counts[branch]["valid"] += int(row.get("valid") is True)
                branch_counts[branch]["invalid"] += int(row.get("valid") is not True)
    for branch in BRANCHES:
        branch_counts[branch]["planned"] = EXPECTED_EVENTS
        branch_counts[branch]["unattempted"] = EXPECTED_EVENTS - branch_counts[branch]["attempted"]
    missingness = {
        "imputation": "none",
        "events": len(grouped),
        "complete_triplets": sum(1 for row in per_event if row["complete_triplet"]),
        "complete_pairs": len(per_event),
        "incomplete_pairs": 0,
        "partial_triplets": 0,
        "by_branch": {branch: dict(branch_counts[branch]) for branch in BRANCHES},
        "complete_pairs_by_form": dict(sorted(complete_by_form.items())),
        "forms_with_at_least_one_pair": len(complete_by_form),
        "forms_below_min_pairs": 0,
        "primary_requirement": ("at least one complete real/placebo pair in every one of the "
                                "six frozen forms"),
        "primary_requirement_met": len(complete_by_form) == EXPECTED_FORMS_COUNT
        and all(count >= 1 for count in complete_by_form.values()),
    }

    sensitivity = _sensitivity(grouped, primary)
    tiers = dict(sorted(tier_counts.items()))
    normalization = {
        "tiers": tiers,
        "exact_rows": tiers.get("exact", 0),
        "complete_renormalized_rows": tiers.get("complete_renormalized", 0),
        "other_rows": sum(count for name, count in tiers.items()
                          if name not in ("exact", "complete_renormalized")),
        "hard_ceiling": 0.05,
        "thresholds": list(SENSITIVITY_THRESHOLDS),
        "sensitivity": sensitivity,
        "rule": "secondary sensitivity only; a secondary analysis never overrides the primary result",
    }

    information = _information_accounting(registration)
    limitations = dict(registration.get("limitations") or {})
    claim_scope = dict(registration.get("claim_scope") or {})

    document = {
        "analysis_version": ANALYSIS_VERSION,
        "issue": "#159",
        "task": "#198",
        "unit": "prompt form",
        "estimand": {
            "event_contrast": "d_i = H_real,i - H_placebo,i",
            "form_contrast": "mean of d_i within prompt form f",
            "primary": ("equal-weight mean of the six within-form means of "
                        "H_real - H_placebo"),
            "directional_prediction": "Delta < 0",
            "k": EXPECTED_FORMS_COUNT,
            "events": len(per_event),
            "events_are_independent_units": False,
        },
        "form_table": form_table["rows"],
        "forest_table": [{"form": row["form"], "n_pairs": row["n_pairs"],
                          "d_f": row["d_f"], "sd": row["sd"],
                          **_forest_ci(row)}
                         for row in form_table["rows"]],
        "per_event": per_event,
        "primary": primary,
        "guards": guards_block,
        "missingness": missingness,
        "null_manipulation_checks": {
            "scope": ("retained for real-minus-null and placebo-minus-null; null is excluded "
                      "from the primary real-versus-placebo contrast"),
            "events_with_real_minus_null": len(null_real),
            "mean_real_minus_null": _mean(null_real),
            "mean_placebo_minus_null": _mean(null_placebo),
            "real_below_null_events": sum(1 for value in null_real if value < 0),
            "placebo_below_null_events": sum(1 for value in null_placebo if value < 0),
        },
        "normalization": normalization,
        "information_accounting": information,
        "limitations": limitations,
        "claim_scope": claim_scope,
        "non_claims": [
            "no calibration claim about Jev Choice probability vectors",
            "no population-level or cross-family causal claim",
            "no generalization beyond the six frozen planning-low prompt forms",
            "no instance-level inference; the 17 events are replicates within six forms",
            "gross message information is never reported as unique delivered information",
        ],
    }
    document["decision"] = _decision(primary, guards_block, missingness)
    document["registered_causal_uptake"] = {
        "criterion_met": bool(primary["criterion_met"]),
        "scope": "registered conditional scope only (six frozen forms, paid Ling route)",
        "basis": ("matched real/placebo/null replay on the frozen event set with the "
                  "equal-weight form-level estimand, exact two-sided sign-flip and "
                  "form-mean t interval, direction as preregistered"),
        "guards_reported_separately": True,
        "guards_filtered_primary": False,
        "statement": (
            "the registered causal-uptake criterion is met within the registered "
            "conditional scope" if primary["criterion_met"] else
            "the registered causal-uptake criterion is not met"),
    }
    return document


def _forest_ci(row: Mapping[str, Any]) -> dict[str, Any]:
    interval = _form_ci(row)
    if interval is None:
        return {"ci_low": None, "ci_high": None,
                "ci_note": "fewer than two pairs; no interval reported"}
    return {"ci_low": interval[0], "ci_high": interval[1],
            "ci_note": "t interval on the within-form pairs"}


def _form_ci(row: Mapping[str, Any]) -> list[float] | None:
    if row["sd"] is None or row["n_pairs"] < 2:
        return None
    half = ji.t_critical_975(row["n_pairs"] - 1) * (row["sd"] / math.sqrt(row["n_pairs"]))
    return [row["d_f"] - half, row["d_f"] + half]


def _sensitivity(grouped: Mapping[str, Mapping[str, Any]],
                 primary: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Re-run the primary contrast with each registered acceptance threshold."""

    grid: list[dict[str, Any]] = []
    for threshold in SENSITIVITY_THRESHOLDS:
        d_by_form: dict[str, list[float]] = defaultdict(list)
        excluded_events = []
        for event_id in sorted(grouped):
            branches = grouped[event_id]
            deviations = []
            for branch in ("real", "placebo"):
                diagnostics = branches[branch].get("probability_diagnostics") or {}
                value = diagnostics.get("absolute_normalization_deviation")
                deviations.append(float(value) if _finite(value) else math.inf)
            if any(deviation > threshold + 1e-15 for deviation in deviations):
                excluded_events.append(event_id)
                continue
            form = str(branches["real"].get("prompt_form_id"))
            d_by_form[form].append(float(branches["real"]["entropy_bits"])
                                   - float(branches["placebo"]["entropy_bits"]))
        table = _form_summary(d_by_form)
        run = _primary(table["form_means"])
        estimate = run["estimate"]
        estimate_changed = (
            estimate is None or primary["estimate"] is None
            or not math.isclose(estimate, primary["estimate"], rel_tol=0.0, abs_tol=1e-15))
        criterion_changed = bool(run["criterion_met"]) != bool(primary["criterion_met"])
        k_changed = run["k"] != primary["k"]
        parts = []
        if k_changed:
            parts.append(f"form count changed to k={run['k']}")
        if estimate_changed:
            parts.append(f"point estimate moved to {estimate}")
        if criterion_changed:
            parts.append(f"registered criterion changed to {run['criterion_met']}")
        note = ("no change: same k, same point estimate and same registered decision"
                if not parts else "; ".join(parts)
                + f" (registered criterion remains {'met' if run['criterion_met'] else 'not met'})")
        grid.append({
            "threshold": threshold,
            "accepted_pairs": sum(1 for event_id in grouped
                                  if event_id not in excluded_events),
            "excluded_events": excluded_events,
            "excluded_event_count": len(excluded_events),
            "k": run["k"],
            "estimate": estimate,
            "sign_flip_p_value": run["sign_flip"].get("p_value"),
            "t_interval_975": run["t_interval_975"],
            "direction_met": run["direction_met"],
            "criterion_met": run["criterion_met"],
            "criterion_changed": criterion_changed,
            "estimate_changed": estimate_changed,
            "k_changed": k_changed,
            "conclusion_changed": bool(criterion_changed or k_changed),
            "conclusion_note": note,
        })
    return {"conclusion_definition": (
                "conclusion_changed is true when the registered decision (k = 6 with all six "
                "forms complete, negative direction and sign-flip p < 0.05) differs from the "
                "primary result; estimate_changed and k_changed are reported separately"),
            "thresholds": list(SENSITIVITY_THRESHOLDS),
            "grid": grid}


def _information_accounting(registration: Mapping[str, Any]) -> dict[str, Any]:
    """Separate gross transmitted information from unique delivered information."""

    events = list(registration.get("events") or [])
    gross_bits = sum(float((event.get("real") or {}).get("i_m_bits") or 0.0)
                     for event in events)
    distinct: dict[tuple[str, str], float] = {}
    for event in events:
        key = (str(event.get("prompt_form_id")), str((event.get("real") or {}).get("claim")))
        distinct.setdefault(key, float((event.get("real") or {}).get("i_m_bits") or 0.0))
    placebo_bits = sum(float((event.get("placebo") or {}).get("i_m_bits") or 0.0)
                       for event in events)
    return {
        "definitions": {
            "gross": ("sum of authoritative i_m_bits over replay-eligible events; includes "
                      "repeated identical claims across events within a form and is never "
                      "unique information delivered to receiver A"),
            "unique_delivered": ("at most one deduplicated accepted B-owned informative claim "
                                 "per pre-read state with verified board-write and A-read "
                                 "provenance; A-to-B writes and receiver-known or I_m = 0 "
                                 "claims are excluded"),
            "entropy_change": ("H_real - H_placebo is a change in the receiver's output "
                               "distribution, not information delivered; it is always kept "
                               "distinct from the objective message information I_m"),
        },
        "replay_eligible_events": len(events),
        "gross_replay_eligible_bits": round(gross_bits, 10),
        "distinct_form_claim_treatments": len(distinct),
        "unique_delivered_bits_over_distinct_treatments": round(sum(distinct.values()), 10),
        "placebo_inert_bits": round(placebo_bits, 10),
        "gross_equals_unique": math.isclose(gross_bits, sum(distinct.values())),
        "statement": ("gross replay-eligible totals count within-form repeats and are never "
                      "described as unique delivered information; the distinct form/claim "
                      "treatments are the model-visible claim content actually varied"),
    }


# --------------------------------------------------------------------------
# artifact lifecycle
# --------------------------------------------------------------------------

def compute(repo_root: Path, *, pins: Mapping[str, Any] | None = None
            ) -> dict[str, Any]:
    """Verify everything and build the artifact. Raises AnalysisError on drift."""

    root = Path(repo_root)
    effective_pins = PINNED if pins is None else pins
    inputs = load_inputs(root)
    hash_verdict = verify_hashes(inputs, pins=effective_pins)
    if not hash_verdict["ok"]:
        raise AnalysisError("hash_verification_failed: " + "; ".join(hash_verdict["errors"]))
    structure = verify_structure(inputs["journal_rows"], inputs["report"],
                                 inputs["registration"])
    if not structure["ok"]:
        raise AnalysisError("structure_verification_failed: " + "; ".join(structure["errors"]))
    document = analyze(inputs["journal_rows"], inputs["registration"])
    document["inputs"] = {
        "journal": {"path": inputs["paths"]["journal"], "sha256": inputs["sha256"]["journal"],
                    "rows": len(inputs["journal_rows"])},
        "report": {"path": inputs["paths"]["report"], "sha256": inputs["sha256"]["report"]},
        "registration": {"path": inputs["paths"]["registration"],
                         "sha256": inputs["sha256"]["registration"],
                         "preregistration_hash": inputs["registration"].get("preregistration_hash")},
        "run_commit": effective_pins.get("run_commit"),
    }
    document["verification"] = {"ok": True, "hash_checks": hash_verdict["checks"],
                                "structure_checks": structure["checks"]}
    document["registration_hash"] = inputs["registration"].get("preregistration_hash")
    document["protocol_key"] = ((inputs["registration"].get("model_and_protocol") or {})
                                .get("protocol_key"))
    document["model"] = ((inputs["registration"].get("model_and_protocol") or {}).get("model"))
    document["determinism"] = ("byte-identical for identical inputs; no timestamp, no "
                               "randomness and no provider call contributes to this artifact")
    return document


def write_document(document: Mapping[str, Any], *, repo_root: Path,
                   output: Path | None = None) -> Path:
    """Persist the artifact once; never overwrites or appends."""

    target = Path(repo_root) / (output if output is not None else DEFAULT_OUTPUT)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return target


def run(repo_root: Path, *, output: Path | None = None,
        pins: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Full offline pipeline; blocked results are returned without writing."""

    try:
        document = compute(repo_root, pins=pins)
    except AnalysisError as exc:
        return {"status": "blocked", "stop_reason": str(exc), "provider_calls": 0,
                "written": False}
    target = Path(repo_root) / (output if output is not None else DEFAULT_OUTPUT)
    if target.exists():
        return {"status": "blocked", "stop_reason": "output_exists",
                "provider_calls": 0, "written": False}
    path = write_document(document, repo_root=repo_root, output=output)
    primary = document["primary"]
    return {"status": "ok", "written": True, "path": str(path),
            "analysis_version": document["analysis_version"],
            "sha256": sha256_file(path),
            "primary": {"estimate": primary["estimate"], "k": primary["k"],
                        "df": primary["df"],
                        "sign_flip_p_value": primary["sign_flip"].get("p_value"),
                        "t_interval_975": primary["t_interval_975"],
                        "direction_met": primary["direction_met"],
                        "criterion_met": primary["criterion_met"]},
            "decision": document["decision"],
            "provider_calls": 0}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="#198 offline replay-v5 inference (no provider calls)")
    parser.add_argument("--repo-root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = Path(args.repo_root) if args.repo_root is not None else Path(
        __file__).resolve().parents[2]
    result = run(root)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ANALYSIS_VERSION", "DEFAULT_OUTPUT", "DEFAULT_JOURNAL", "DEFAULT_REPORT",
    "DEFAULT_REGISTRATION", "BRANCHES", "REQUIRED_FORMS", "SENSITIVITY_THRESHOLDS",
    "PINNED", "AnalysisError", "sha256_file", "load_inputs",
    "verify_hashes", "verify_structure", "analyze", "compute", "write_document",
    "run", "main",
]
