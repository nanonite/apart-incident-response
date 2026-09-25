"""#193 — matched real/placebo/null Jev replay preregistration v4 (offline lock).

Successor registration consuming the authoritative #192 decision artifact
(17 replay-eligible one-way B→A events across the six frozen prompt forms,
distribution 1/4/4/1/4/3) for the #159 same-pre-read-state Jev Choice replay.
It freezes the matched branch construction (real / inert placebo / null over
one identical pre-read state C), the equal-form estimand, the exact
inference rules, guards, missingness rules, fallback branches, sensitivity
plan, and limitations.

No replay is executed here: no provider calls, no live authorization, no
modification or pooling of any prior artifact. ``live_collection_authorized``
is always false and locking this registration does not authorize #159
execution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import jev_choice as jc
from . import jev_choice_v2 as jc2
from . import jev_replay as jr
from . import jev_replay_inference as ji
from . import jev_replay_preregistration as pr
from . import jev_replay_preregistration_v2 as prv2
from . import jev_six_form_coverage_audit as audit
from . import task_families as tf
from .communication_protocol import DependenceRegime, ReasoningComplexity


JEV_REPLAY_V4_PREREG_VERSION = "stage2-jev-choice-replay-v4"
JEV_REPLAY_V4_DRAFT_STATUS = "draft_pending_review_v4"
JEV_REPLAY_V4_LOCKED_STATUS = "locked_for_jev_choice_replay_v4"

#: All v4 outputs live under runs/epic-126/replay-v4/: the registrations'
#: prior-ID scan globs (runs/epic-126/*.json[.l] and runs/*.json[.l]) are
#: non-recursive, so keeping the v4 trio in a subdirectory permanently keeps
#: it out of earlier registrations' rebuild evidence (same rationale as the
#: decisions/ subdirectory).
DEFAULT_OUTPUT_V4 = Path("runs/epic-126/replay-v4/jev-choice-replay-preregistration-v4.json")
DEFAULT_JOURNAL_V4 = Path("runs/epic-126/replay-v4/jev-choice-replay-v4.jsonl")
DEFAULT_REPORT_V4 = Path("runs/epic-126/replay-v4/jev-choice-replay-report-v4.json")

DECISION_ARTIFACT = "runs/epic-126/decisions/jev-v7-coverage-decision.json"
DECISION_SHA256 = "3f45b8bf35ca87fe59d754c8426b256ed76aeab8e94a37881e7a768a1be5431b"
DECISION_BASELINE_COMMIT = "cad2c80"

#: The six frozen prompt forms (identical to #189/#192).
FROZEN_FORM_IDS = (
    "0a3349e16c9633b4d559dfbb808d1e50d0446d8f92160a0feddd1e37299796ee",
    "1c1d9f6b5c9271ad8e74de180c3e397e1369d326564c9a08ba0840eff0b148fc",
    "2954f5684bcd198ed8eea0956cf573f93cde628d6dfa7472fc57f556bd089b2c",
    "3196a8d69f844702db012816def7d7866e7416e9fadc9f28eaa7f12ac16a8569",
    "55968fe191b18f37d1951d71f777115f753e0b9a6da526015f3db5251a1383eb",
    "ce847ac53b6e344103bc775aede5212b2be6fbd568dc1d85fd24cbde8f585222",
)
#: Required event distribution in sorted-form order: 1/4/4/1/4/3.
EXPECTED_FORM_DISTRIBUTION = (1, 4, 4, 1, 4, 3)
EXPECTED_EVENT_COUNT = 17

LOG2_3 = math.log2(3)

#: Replay call arithmetic: 17 events x 3 branches, retry-inclusive ceiling.
PLANNED_JEV_CALLS = EXPECTED_EVENT_COUNT * 3          # 51
RETRY_RESERVE_FACTOR = 1 + pr.JEV_REPLAY_MAX_RETRIES  # 3
PHYSICAL_REQUEST_CEILING = PLANNED_JEV_CALLS * RETRY_RESERVE_FACTOR  # 153
PLANNED_LING_CALLS = 0
INPUT_TOKEN_CEILING = pr.JEV_REPLAY_INPUT_TOKEN_CEILING   # 8192
INPUT_USD_PER_MTOK = pr.JEV_REPLAY_INPUT_USD_PER_MTOK     # 0.042
WORST_CASE_CALL_COST_USD = round(INPUT_TOKEN_CEILING * INPUT_USD_PER_MTOK / 1_000_000, 12)
WORST_CASE_COST_USD = round(PHYSICAL_REQUEST_CEILING * WORST_CASE_CALL_COST_USD, 9)
COST_CAP_USD = 1.0

#: The #195 replay runner bound into this registration.
RUNNER_SOURCE_REL = "src/apart_incident_response/jev_replay_runner_v4.py"
#: Pre-runner offline lock superseded by the runner-bound amendment.
SUPERSEDED_OFFLINE_LOCK_HASH = (
    "ffb46af295335fc7f8c30eae2f114e47f52dbee0f810ddc1196629b322d515b1")

#: Source files whose semantics this registration binds (hash stored in JSON).
REPLAY_V4_SOURCE_FILES = (
    "src/apart_incident_response/task_families.py",
    "src/apart_incident_response/communication_protocol.py",
    "src/apart_incident_response/finite_information.py",
    "src/apart_incident_response/jev_choice.py",
    "src/apart_incident_response/jev_choice_v2.py",
    "src/apart_incident_response/jev_replay.py",
    "src/apart_incident_response/jev_replay_inference.py",
    "src/apart_incident_response/jev_replay_preregistration.py",
    "src/apart_incident_response/jev_replay_preregistration_v2.py",
    "src/apart_incident_response/jev_six_form_coverage_audit.py",
    "src/apart_incident_response/jev_v7_coverage_decision.py",
    "src/apart_incident_response/jev_replay_preregistration_v4.py",
    "src/apart_incident_response/jev_replay_runner_v4.py",
)

#: Prior output paths the v4 verifier must refuse as v4 outputs.
OLD_OUTPUT_PATHS_V4 = (
    "runs/epic-126/jev-choice-replay-preregistration.json",
    "runs/epic-126/jev-choice-pilot.jsonl",
    "runs/epic-126/jev-choice-pilot-report.json",
    "runs/epic-126/jev-choice-replay-preregistration-v2.json",
    "runs/epic-126/jev-choice-pilot-v2.jsonl",
    "runs/epic-126/jev-choice-pilot-report-v2.json",
    "runs/epic-126/jev-choice-normalization-probe-v2.jsonl",
    "runs/epic-126/jev-choice-normalization-probe-report-v2.json",
    "runs/epic-126/jev-choice-replay-preregistration-v3.json",
    "runs/epic-126/jev-choice-pilot-v3.jsonl",
    "runs/epic-126/jev-choice-pilot-report-v3.json",
    "runs/epic-126/jev-choice-capability.jsonl",
    "runs/epic-126/jev-choice-capability-report.json",
    "runs/epic-126/jev-writer-ladder-preregistration-v4.json",
    "runs/epic-126/jev-writer-ladder-preregistration-v5.json",
    "runs/epic-126/jev-writer-exact-bridge-v5.jsonl",
    "runs/epic-126/jev-writer-exact-bridge-report-v5.json",
    "runs/epic-126/jev-coverage-manifest-preregistration-v6.json",
    "runs/epic-126/jev-coverage-manifest-v6.jsonl",
    "runs/epic-126/jev-coverage-manifest-report-v6.json",
    "runs/epic-126/jev-coverage-manifest-preregistration-v7.json",
    "runs/epic-126/jev-coverage-manifest-v7.jsonl",
    "runs/epic-126/jev-coverage-manifest-report-v7.json",
)

#: Frozen branch-order construction: deterministic, hash-free, lexicographic.
BRANCHES = ("real", "placebo", "null")
BRANCH_PERMUTATIONS = (
    ("real", "placebo", "null"),
    ("real", "null", "placebo"),
    ("placebo", "real", "null"),
    ("placebo", "null", "real"),
    ("null", "real", "placebo"),
    ("null", "placebo", "real"),
)

#: Retry-inclusive worst-case next-call reservation (one logical branch).
NEXT_CALL_RESERVE_USD = round(WORST_CASE_CALL_COST_USD * RETRY_RESERVE_FACTOR, 12)

#: Frozen guard estimands (exact formulas; evaluated per event).
GUARD_FORMULAS = {
    "delta_p_target_i": "p_target(real_i) - p_target(placebo_i)",
    "delta_feasible_mass_i": "mass_SA(real_i) - mass_SA(placebo_i)",
    "mass_SA": ("sum of the normalized Choice probabilities over the frozen authoritative "
                "pre-read feasible_set for receiver A"),
    "target_ok_i": "delta_p_target_i >= 0.0",
    "mass_ok_i": "delta_feasible_mass_i >= -0.01",
    "useful_uptake_i": "(H_real_i - H_placebo_i < 0) and target_ok_i and mass_ok_i",
    "computation_rule": "compute all metrics only from the accepted normalized vector",
    "reporting_rule": ("report guard values per event and aggregate them within form; guards "
                       "never remove an otherwise valid real/placebo pair from the primary "
                       "entropy estimate; entropy reduction alone is never called useful "
                       "uptake when either guard fails; null remains excluded from these "
                       "primary real-versus-placebo guards"),
}

#: Frozen operational execution and missingness rules for the future runner.
EXECUTION_POLICY = {
    "preflight": [
        "exact reviewed registration hash and repository-backed verification",
        "exact event and branch-order manifests",
        "model, endpoint, codec, protocol key, retry and normalization settings",
        "request, state, option and treatment hashes",
        "credentials present but never printed or retained",
        "registered journal/report paths absent",
        "enforced request and cost caps",
        "no provider call before every preflight check passes",
    ],
    "output_lifecycle": {
        "overwrite": False,
        "automatic_resume": False,
        "append_to_prior_replay_artifacts": False,
        "fresh_execution_after_partial_run": ("a fresh execution after a partial/stopped run "
                                              "requires a new review and explicit authorization"),
        "raw_provider_envelopes_retained": False,
        "credentials_retained": False,
    },
    "journal": {
        "kind": "append-only branch-attempt journal",
        "row_unit": "one durable row per logical (event_id, branch) execution",
        "durability": "append, flush, and fsync after every logical branch outcome",
        "unique_key": ["event_id", "branch"],
        "duplicate_key_policy": "fail closed",
        "row_fields": ["planned_branch_position", "actual_branch_position", "request_hash",
                       "state_hash", "protocol_key", "resolved_model", "physical_attempts",
                       "vector and normalization diagnostics", "validity", "usage",
                       "error_class", "cap counters"],
        "branch_order_persistence": ("both planned and actual branch order are persisted per "
                                     "row and per event; a runner must fail closed if actual "
                                     "execution order differs from the frozen branch_schedule"),
        "report_grouping": ("the final report groups branch rows into event-level "
                            "real/placebo/null records for the registered replay validator "
                            "and inference"),
        "partial_triplets": "partial triplets must remain observable rather than being lost",
    },
    "per_branch": {
        "retries": "registered retryable transport statuses only, maximum two",
        "physical_attempts_include_retries": True,
        "cost_reservation": ("reserve the registered retry-inclusive worst-case next-call "
                             f"cost ({NEXT_CALL_RESERVE_USD} USD) before each logical branch"),
        "cost_reservation_usd": NEXT_CALL_RESERVE_USD,
        "nonterminal_invalid": ("a nonterminal invalid branch is journaled and does not cause "
                                "the remaining branches in that event to be skipped"),
        "complete_pair": ("an event is a primary complete pair only when real and placebo are "
                          "both valid"),
        "null_validity": ("reported separately and not required for the primary real/placebo "
                          "pair"),
        "imputation": "none",
    },
    "immediate_terminal_stops": [
        "request cap or cost cap before the next call",
        "model drift",
        "protocol-key drift",
        "request/state/option identity drift",
        "malformed or non-finite/negative/option-mismatched vectors",
        "hard normalization deviation above 0.05",
        "argmax shift after normalization",
        "output collision",
        "registration or source/treatment hash drift",
    ],
    "nonterminal_invalidity": {
        "band": ("an accepted transport response outside the primary normalization band but "
                 "within the registered suspect sensitivity band"),
        "policy": ("recorded invalid with its safe raw diagnostics retained; never "
                   "reinterpreted as valid; continue unless a registered terminal rule "
                   "applies"),
    },
    "provider_failures": {
        "retry_exhaustion": "record a sanitized invalid branch row",
        "consecutive_terminal_failure_stop": 2,
        "reset": "the consecutive-failure count resets after a successful valid response",
        "retention": "never retain response bodies or credentials",
    },
    "stopping_report": ("stopping preserves a partial report with planned/attempted/valid/"
                        "invalid/unattempted counts by branch, event, and form"),
}

#: Frozen estimator, inference, guards, missingness, sensitivity, limitations.
ESTIMAND = {
    "experimental_unit": "prompt form",
    "events": EXPECTED_EVENT_COUNT,
    "k": 6,
    "events_are_independent_units": False,
    "event_contrast": "d_i = H_real,i - H_placebo,i",
    "form_contrast": "mean of d_i within prompt form f",
    "primary": ("Delta = equal-weight mean over the six frozen forms of the within-form mean "
                "of H_real - H_placebo"),
    "directional_prediction": "Delta < 0",
    "null_branch": {
        "retained_for": ["H_real - H_null", "H_placebo - H_null manipulation checks"],
        "excluded_from": ("the algebraically cancelling primary real-versus-placebo contrast"),
    },
    "unit_notes": [
        "the 17 events are replicates within six prompt forms, not 17 independent states",
        "repeated instances inside a form are averaged, never treated as independent units",
        "no instance-level t-test or Wilcoxon test may be used as primary inference",
    ],
}

INFERENCE = {
    "primary_test": "exhaustive two-sided cluster sign-flip over the six form means",
    "interval": "form-mean t interval with df = 5",
    "report": ["the sign-flip p-value", "the form-mean t interval"],
    "direction_requirement": "the observed equal-form mean must be negative",
    "min_two_sided_p_k6_expression": "2/64",
    "min_two_sided_p_k6": 0.03125,
    "min_two_sided_p_k5_expression": "2/32",
    "min_two_sided_p_k5": 0.0625,
    "prohibited_as_primary": ["instance-level t-test", "instance-level Wilcoxon test",
                              "treating the 17 events as independent states"],
}

GUARDS = {
    "target_probability_delta": 0.0,
    "feasible_set_mass_epsilon": 0.01,
    "reporting": ("reported separately by form and event; never used to filter the primary "
                  "entropy estimate"),
    "useful_uptake_rule": ("an entropy reduction alone must never be labeled useful uptake if "
                           "the target-probability guard fails"),
    "reference_set": ("the frozen authoritative pre-read feasible_set for receiver A, stored "
                      "and hashed per event"),
    "formulas": dict(GUARD_FORMULAS),
}

MISSINGNESS = {
    "complete_pair": "a primary event pair is complete only when real and placebo are both valid",
    "report": "planned, attempted, valid, invalid and complete pairs by branch and by form",
    "primary_requirement": ("at least one complete real/placebo pair in every one of the six "
                            "frozen forms"),
    "target": "retain all 17 events",
    "imputation": "never impute missing pairs",
    "five_form_fallback": ("interval-only descriptive reporting; a two-sided sign-flip p below "
                           "0.05 is forbidden; no causal gate is released"),
    "below_five_forms": "replay-coverage failure",
}

SENSITIVITY = {
    "normalization_thresholds": [1e-6, 0.01, 0.03, 0.05],
    "report": ["exact versus materially renormalized rows",
               "maximum probability adjustment",
               "maximum induced entropy change",
               "argmax changes"],
    "secondary_analyses": ["form-cluster bootstrap", "sign test on form means",
                           "instance-weighted mean"],
    "not_implemented": ["hierarchical model", "Wilcoxon on form means"],
    "rule": "secondary sensitivity only; a secondary analysis never overrides the primary result",
}

LIMITATIONS = {
    "k_cap": ("k is capped at six by the generator's closed form space; fresh instance IDs "
              "cannot increase k"),
    "mde_or_ci_bits": 0.203,
    "mde_context": ("the planning-context approximate detectable-effect / confidence-interval "
                    "limitation is about 0.203 bits (t(0.975,5) x 0.1933 / sqrt(6))"),
    "null_result": "a null result cannot exclude effects smaller than roughly 0.2 bits",
    "conditional_on": ["the six frozen planning-low prompt forms",
                       "the paid Ling route that generated the messages"],
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_decision(repo_root: Path | None = None) -> dict[str, Any]:
    """Load the pinned #192 decision artifact; fail closed on hash drift."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    path = root / DECISION_ARTIFACT
    if not path.is_file():
        raise ValueError("#192 decision artifact missing")
    actual = sha256_file(path)
    if actual != DECISION_SHA256:
        raise ValueError(f"#192 decision artifact hash drift: {actual}")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("artifact_version") != "jev-v7-coverage-decision-v1":
        raise ValueError("unexpected decision artifact version")
    return document


def _regenerate_instance(instance_id: str) -> Any:
    match = re.match(r"^planning-([0-9a-f]{8})$", instance_id)
    if not match:
        raise ValueError(f"malformed instance id: {instance_id}")
    seed = int(match.group(1), 16)
    instance = tf.generate_instance("planning", seed, DependenceRegime.N,
                                    ReasoningComplexity.LOW)
    if instance.instance_id != instance_id:
        raise ValueError(f"instance id does not match seed: {instance_id}")
    return instance


def branch_position_balance(schedule: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """Per-position branch counts and balance metrics for a branch schedule."""

    positions: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}
    for branches in schedule.values():
        for index, branch in enumerate(branches, start=1):
            slot = positions.setdefault(str(index), {})
            slot[branch] = slot.get(branch, 0) + 1
            totals[branch] = totals.get(branch, 0) + 1
    differences = [max(slot.values()) - min(slot.values()) for slot in positions.values()]
    return {"by_position": {key: dict(sorted(value.items()))
                            for key, value in sorted(positions.items())},
            "per_branch_totals": dict(sorted(totals.items())),
            "max_position_difference": max(differences) if differences else 0}


def build_branch_schedule(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Deterministic event-major branch schedule from frozen identity only.

    Event execution follows the #192 decision order; the three branches of one
    event run adjacently. The per-event permutation is
    ``BRANCH_PERMUTATIONS[(lexicographic_form_index + within_form_event_index) % 6]``
    — a lexicographic, hash-free rotation depending only on frozen form and
    event identity, never on outcomes. With the frozen 1/4/4/1/4/3
    distribution this yields all six permutations, per-position branch counts
    differing by at most one, and17 executions of each branch.
    """

    event_order = [str(event["event_id"]) for event in events]
    by_form: dict[str, list[str]] = {}
    for event in events:
        by_form.setdefault(str(event["prompt_form_id"]), []).append(str(event["event_id"]))
    schedule: dict[str, list[str]] = {}
    form_roles: dict[str, Any] = {}
    for form_index, form in enumerate(sorted(by_form)):
        roles = []
        for within_form_index, event_id in enumerate(by_form[form]):
            permutation_index = (form_index + within_form_index) % len(BRANCH_PERMUTATIONS)
            branches = list(BRANCH_PERMUTATIONS[permutation_index])
            schedule[event_id] = branches
            roles.append({"event_id": event_id, "within_form_index": within_form_index,
                          "permutation_index": permutation_index, "branches": branches})
        form_roles[form] = {"lexicographic_form_index": form_index,
                            "rotation_start": form_index, "events": roles}
    ordered_schedule = {event_id: schedule[event_id] for event_id in event_order}
    balance = branch_position_balance(ordered_schedule)
    return {"event_major": True,
            "execution_order": ("events in #192 decision order; the three branches of one "
                                "event are executed adjacently before the next event"),
            "allowed_branches": list(BRANCHES),
            "permutations": [list(permutation) for permutation in BRANCH_PERMUTATIONS],
            "assignment_rule": ("per-event permutation = BRANCH_PERMUTATIONS[(lexicographic "
                               "form index + within-form event index) % 6]; depends only on "
                               "frozen form and event identity, never on outcomes"),
            "event_order": event_order,
            "schedule": ordered_schedule,
            "form_roles": form_roles,
            "position_balance": balance,
            "expected_max_position_difference": 1}


def pre_read_body(instance: Any, model: str) -> tuple[dict[str, Any], Any]:
    """Build the frozen pre-read state C and its request body for receiver A."""

    adapter = jc.JevChoiceAdapter(object(), model=model)
    state = adapter.build_state(instance, "A", "ISO")
    body = jr.pre_read_request_body(
        state=dict(state.state), question_id=state.question_id,
        instructions=state.instructions,
        option_ids=[option.option_id for option in state.options],
        model=adapter.model)
    if jr.prompt_form_id(body) != state.request_hash:
        raise ValueError(f"pre-read form id mismatch for {instance.instance_id}")
    return body, state


def consume_decision_events(decision: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validate the pinned decision artifact's event set; fail closed."""

    events = list(decision.get("events") or [])
    if len(events) != EXPECTED_EVENT_COUNT:
        raise ValueError(f"expected {EXPECTED_EVENT_COUNT} events, found {len(events)}")
    event_ids = [str(event.get("event_id")) for event in events]
    if len(set(event_ids)) != EXPECTED_EVENT_COUNT:
        raise ValueError("decision event ids are not unique")
    counts: dict[str, int] = {}
    for event in events:
        form = str(event.get("prompt_form_id"))
        if form not in FROZEN_FORM_IDS:
            raise ValueError(f"event references a non-frozen prompt form: {form}")
        counts[form] = counts.get(form, 0) + 1
        if event.get("writer_id") != "B" or event.get("reader_id") != "A":
            raise ValueError(f"event {event.get('event_id')} is not a B->A event")
        if event.get("receiver_valid") is not True:
            raise ValueError(f"event {event.get('event_id')} is not receiver-valid")
        i_m = event.get("i_m_bits")
        if not (isinstance(i_m, (int, float)) and math.isclose(float(i_m), LOG2_3,
                                                               rel_tol=0.0, abs_tol=1e-12)):
            raise ValueError(f"event {event.get('event_id')} is not informative at log2(3)")
        if not event.get("exposure_ids"):
            raise ValueError(f"event {event.get('event_id')} lacks exposure provenance")
        for field in ("request_hash", "state_hash", "message_id"):
            if not event.get(field):
                raise ValueError(f"event {event.get('event_id')} lacks {field}")
    distribution = tuple(counts.get(form, 0) for form in FROZEN_FORM_IDS)
    if distribution != EXPECTED_FORM_DISTRIBUTION:
        raise ValueError(f"form distribution {distribution} != {EXPECTED_FORM_DISTRIBUTION}")
    return events


def build_event_binding(event: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze the matched branch construction for one event (offline)."""

    instance = _regenerate_instance(str(event["instance_id"]))
    body, state = pre_read_body(instance, pr.JEV_REPLAY_MODEL)
    if jr.prompt_form_id(body) != event.get("prompt_form_id"):
        raise ValueError(f"prompt_form_id mismatch for {event['event_id']}")

    real_claim = str(event["claim"])
    info = instance.information("A", real_claim, str(event["message_id"]))
    if info.status != "accepted" or info.delta_i_bits is None \
            or not math.isclose(float(info.delta_i_bits), LOG2_3, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"real claim not informative at log2(3): {event['event_id']}")
    if not instance.holds_claim("B", real_claim):
        raise ValueError(f"real claim not owned by B: {event['event_id']}")

    placebo_claim = str(list(instance.private_clues["A"])[0])
    placebo_info = instance.information("A", placebo_claim, "placebo")
    placebo_delta = placebo_info.delta_i_bits
    if (placebo_info.status != "accepted" or placebo_delta is None
            or float(placebo_delta) != 0.0):
        raise ValueError(f"placebo claim not inert: {event['event_id']}")
    extended = instance.clue_consistent(set(instance.private_clues["A"]) | {placebo_claim})
    if extended != instance.private_solutions["A"]:
        raise ValueError(f"placebo claim reduces the receiver's feasible set: {event['event_id']}")

    real_text = jr.serialize_message(real_claim)
    placebo_text = jr.serialize_placebo_message(placebo_claim)
    state_json = json.dumps(dict(state.state), sort_keys=True)
    target = str(instance.target)
    if target and target in state_json:
        raise ValueError(f"target leakage in pre-read state: {event['event_id']}")
    for marker in ("joint_solutions", "joint_candidate", "joint_solution"):
        if marker in state_json:
            raise ValueError(f"answer-key marker leakage in pre-read state: {event['event_id']}")

    feasible_set = sorted(str(value) for value in instance.private_solutions["A"])
    clue_consistent = sorted(str(value) for value in
                             instance.clue_consistent(instance.private_clues["A"]))
    if feasible_set != clue_consistent:
        raise ValueError(f"authoritative feasible set drifted from the clue-consistent "
                         f"pre-read set: {event['event_id']}")

    option_ids = sorted(str(label) for label in instance.solutions)
    return {
        "event_id": str(event["event_id"]),
        "instance_id": str(event["instance_id"]),
        "prompt_form_id": str(event["prompt_form_id"]),
        "real": {
            "message_id": str(event["message_id"]),
            "claim": real_claim,
            "writer_id": "B",
            "reader_id": "A",
            "i_m_bits": float(event["i_m_bits"]),
            "exposure_ids": list(event.get("exposure_ids") or []),
            "write_sequence": event.get("write_sequence"),
            "ownership_verified": True,
            "informative_verified": True,
        },
        "placebo": {
            "claim": placebo_claim,
            "i_m_bits": 0.0,
            "synthetic": True,
            "origin": jr.PLACEBO_ORIGIN,
            "construction": jr.PLACEBO_CONSTRUCTION,
            "envelope": jr.MESSAGE_ENVELOPE_TEMPLATE,
            "receiver_known": True,
            "inert_verified": True,
        },
        "pre_read": {
            "state_hash": jr.canonical_hash(dict(state.state)),
            "request_body_hash": jr.prompt_form_id(body),
            "feasible_set": feasible_set,
            "feasible_set_hash": jr.canonical_hash(feasible_set),
            "feasible_set_verified": True,
            "feasible_set_source": ("authoritative receiver-A pre-read private_solutions "
                                    "equals the clue-consistent pre-read set"),
            "branch_request_hashes": {
                "real": jr.prompt_form_id(jr.branch_request_body(body, real_text)),
                "placebo": jr.prompt_form_id(jr.branch_request_body(body, placebo_text)),
                "null": jr.prompt_form_id(jr.branch_request_body(body, None)),
            },
            "option_ids": option_ids,
            "target_id": target,
        },
    }


def treatment_hash_v4(*, decision_sha256: str, wording_hash: str,
                      normalization_policy_hash: str) -> str:
    payload = {
        "decision_artifact_sha256": decision_sha256,
        "message_wording_hash": wording_hash,
        "envelope": jr.MESSAGE_ENVELOPE_TEMPLATE,
        "placebo_construction": jr.PLACEBO_CONSTRUCTION,
        "placebo_origin": jr.PLACEBO_ORIGIN,
        "normalization_policy_hash": normalization_policy_hash,
        "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
        "branch_modes": ["real", "placebo", "null"],
        "estimand": ESTIMAND["primary"],
        "directional_prediction": ESTIMAND["directional_prediction"],
        "runner_source_file": RUNNER_SOURCE_REL,
        "runner_version": "jev-choice-replay-runner-v4",
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def output_paths() -> dict[str, str]:
    return {"registration": str(DEFAULT_OUTPUT_V4), "journal": str(DEFAULT_JOURNAL_V4),
            "report": str(DEFAULT_REPORT_V4), "event_source": DECISION_ARTIFACT}


def _source_files_hash(repo_root: Path) -> str:
    digest = hashlib.sha256()
    missing = []
    for relative in REPLAY_V4_SOURCE_FILES:
        path = repo_root / relative
        if not path.is_file():
            missing.append(relative)
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    if missing:
        raise ValueError(f"missing source files for hashing: {missing}")
    return digest.hexdigest()


def build_replay_preregistration_v4(*, approved: bool = False,
                                    repo_root: Path | None = None) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    decision = load_decision(root)
    events = consume_decision_events(decision)

    floor_k6 = ji.sign_flip_two_sided([-1.0] * 6)["min_p_value"]
    if floor_k6 != 2 / 64:
        raise ValueError("sign-flip floor for k=6 is not 2/64")

    bindings = [build_event_binding(event) for event in events]
    branch_schedule = build_branch_schedule(events)
    if list(branch_schedule["event_order"]) != [str(event["event_id"]) for event in events]:
        raise ValueError("branch schedule event order differs from the decision order")
    form_ids = sorted({binding["prompt_form_id"] for binding in bindings})
    if tuple(len([b for b in bindings if b["prompt_form_id"] == form]) for form in form_ids) \
            != EXPECTED_FORM_DISTRIBUTION:
        raise ValueError("bound event distribution differs from 1/4/4/1/4/3")
    form_membership = {form: [binding["event_id"] for binding in bindings
                              if binding["prompt_form_id"] == form] for form in form_ids}

    normalization_policy = prv2.normalization_policy()
    normalization_policy_hash = prv2.normalization_policy_hash()
    wording_hash = jr.message_wording_hash()
    upstream = dict(decision.get("inputs", {}).get("sha256") or {})

    document: dict[str, Any] = {
        "preregistration_version": JEV_REPLAY_V4_PREREG_VERSION,
        "issue": "#159",
        "amended_by_task": "#193",
        "stage": "planning-low-matched-jev-replay",
        "status": JEV_REPLAY_V4_LOCKED_STATUS if approved else JEV_REPLAY_V4_DRAFT_STATUS,
        "approval_required": not approved,
        "approval": ({"approved": True, "approved_by": "offline-registration-lock",
                      "scope": "replay_v4_registration_lock_only",
                      "live_collection_authorized": False}
                     if approved else
                     {"approved": False, "live_collection_authorized": False}),
        "pending_decisions": ([] if approved else [
            "reviewer lock of this v4 replay registration (offline only)",
        ]) + [
            "locking this registration does NOT authorize #159 execution; live replay requires "
            "a separate review and explicit live authorization after this lock is approved",
        ],
        "purpose": ("amend and lock the #159 matched real/placebo/null Jev replay plan on top "
                    "of the coverage-qualified #192 event set, without rerunning collection"),
        "successor_of": {
            "v1": "runs/epic-126/jev-choice-replay-preregistration.json",
            "v2": "runs/epic-126/jev-choice-replay-preregistration-v2.json",
            "v3": "runs/epic-126/jev-choice-replay-preregistration-v3.json",
            "note": ("v1-v3 registrations and all prior journals/reports are never modified, "
                     "resumed, pooled with, or reinterpreted; v4 uses fresh paths only"),
            "immutable": True,
        },
        "provenance": {
            "event_source": {
                "path": DECISION_ARTIFACT,
                "sha256": DECISION_SHA256,
                "artifact_version": "jev-v7-coverage-decision-v1",
                "baseline_commit": DECISION_BASELINE_COMMIT,
                "coverage_statement": (
                    decision.get("decisions", {}).get("coverage_replay_readiness", {})
                    .get("statement")),
                "collection_statement": (
                    decision.get("decisions", {}).get("collection_completeness", {})
                    .get("statement")),
            },
            "upstream_sha256": upstream,
            "upstream_registration_content_hash": (
                decision.get("inputs", {}).get("registration_content_hash")),
            "event_count": len(bindings),
            "form_count": len(form_ids),
            "partial_run_note": ("the incomplete 32/36 v7 collection is NOT a completed "
                                 "fixed-N sample; this registration consumes its frozen event "
                                 "set as-is"),
        },
        "forms": {
            "covered_form_ids": form_ids,
            "form_event_counts": {form: len(form_membership[form]) for form in form_ids},
            "form_membership": form_membership,
            "expected_distribution": list(EXPECTED_FORM_DISTRIBUTION),
            "distribution_order": "sorted prompt_form_id order",
            "form_manifest_hash": hashlib.sha256(
                json.dumps(form_ids, sort_keys=True).encode("utf-8")).hexdigest(),
            "k": 6,
        },
        "events": bindings,
        "branch_schedule": branch_schedule,
        "branch_design": {
            "branches": ["real", "placebo", "null"],
            "pre_read_state": (
                "one identical model-visible C per event: the receiver-A pre-read state "
                "(family, complexity, agent_id, clues) with the registered model, question id, "
                "instructions and criteria; prompt_form_id equals the frozen #189/#192 form id"),
            "real": "C plus serialize_message(the exact accepted B-owned claim selected by #192)",
            "placebo": ("C plus serialize_placebo_message(a receiver-already-known clue of A "
                        "with authoritative I_m = 0 and no feasible-set reduction); synthetic "
                        "origin stays controller-side"),
            "null": "C with no message",
            "envelope": {
                "template": jr.MESSAGE_ENVELOPE_TEMPLATE,
                "identical_for_real_and_placebo": True,
                "wording_hash": wording_hash,
                "source_neutral": True,
            },
            "sender_identity_model_visible": False,
            "synthetic_origin_model_visible": False,
            "only_difference_between_branches": "state.visible_messages",
            "branch_request_reconstruction": (
                "each branch request is the frozen pre-read body with visible_messages set to "
                "the envelope text (real/placebo) or [] (null); request hashes are frozen "
                "per event and recomputed by the verifier"),
            "no_ling_calls": ("real messages come from the frozen #192 event set and placebo "
                              "is controller-injected; replay needs no Ling call"),
            "execution_order": ("frozen in branch_schedule: event-major over the #192 decision "
                                "order with one counterbalanced permutation per event; the "
                                "future runner must fail closed on any deviation"),
        },
        "estimand": dict(ESTIMAND),
        "inference": dict(INFERENCE),
        "guards": dict(GUARDS),
        "missingness": dict(MISSINGNESS),
        "sensitivity": dict(SENSITIVITY),
        "limitations": dict(LIMITATIONS),
        "model_and_protocol": {
            "provider": "jev",
            "model": pr.JEV_REPLAY_MODEL,
            "endpoint": pr.JEV_REPLAY_ENDPOINT,
            "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
            "protocol_key": prv6_protocol_key(),
            "max_retries": pr.JEV_REPLAY_MAX_RETRIES,
            "retryable_statuses": sorted(jc.JEV_RETRYABLE_STATUSES),
            "backoff": {"initial_seconds": jc.JEV_BACKOFF_INITIAL,
                        "max_seconds": jc.JEV_BACKOFF_MAX,
                        "jitter": jc.JEV_BACKOFF_JITTER},
            "normalization_policy": normalization_policy,
            "normalization_policy_hash": normalization_policy_hash,
            "normalization_mode": "normalize-all-accepted-vectors (capture-then-judge)",
        },
        "caps": {
            "planned_calls": {
                "jev": PLANNED_JEV_CALLS, "ling": PLANNED_LING_CALLS,
                "combined": PLANNED_JEV_CALLS,
                "arithmetic": (f"{EXPECTED_EVENT_COUNT} events x 3 branches "
                               f"(real/placebo/null) = {PLANNED_JEV_CALLS} Jev receiver calls; "
                               "the replay design makes no Ling call"),
            },
            "physical_requests": PHYSICAL_REQUEST_CEILING,
            "provider_partition": {
                "jev": PHYSICAL_REQUEST_CEILING, "ling": 0, "total": PHYSICAL_REQUEST_CEILING,
                "arithmetic": (f"{PLANNED_JEV_CALLS} x (1 + registered max_retries "
                               f"{pr.JEV_REPLAY_MAX_RETRIES}) = {PHYSICAL_REQUEST_CEILING} "
                               "physical Jev attempts (retry-inclusive ceiling)"),
            },
            "retry_reserve": {"physical": PHYSICAL_REQUEST_CEILING - PLANNED_JEV_CALLS,
                              "max_retries": pr.JEV_REPLAY_MAX_RETRIES},
            "cost_cap_usd": COST_CAP_USD,
            "input_token_ceiling": INPUT_TOKEN_CEILING,
            "input_usd_per_mtok": INPUT_USD_PER_MTOK,
            "worst_case_call_cost_usd": WORST_CASE_CALL_COST_USD,
            "worst_case_cost_usd": WORST_CASE_COST_USD,
            "worst_case_arithmetic": (
                f"{PHYSICAL_REQUEST_CEILING} x {INPUT_TOKEN_CEILING} x {INPUT_USD_PER_MTOK} "
                f"/ 1e6 = {WORST_CASE_COST_USD} <= ceiling {COST_CAP_USD}"),
            "worst_case_next_call_cost_usd": NEXT_CALL_RESERVE_USD,
            "next_call_reservation_arithmetic": (
                f"{WORST_CASE_CALL_COST_USD} x (1 + max_retries "
                f"{pr.JEV_REPLAY_MAX_RETRIES}) = {NEXT_CALL_RESERVE_USD} reserved before each "
                "logical branch"),
            "ling_budget": {
                "planned_calls": 0,
                "physical_cap": 0,
                "justification": ("no Ling call exists in the replay design: real messages are "
                                  "taken from the frozen #192 event set, the placebo is "
                                  "controller-injected, and only the Jev receiver is called"),
            },
            "status": ("locked; live_collection_authorized=false" if approved
                       else "draft; not authorized"),
        },
        "execution_policy": dict(EXECUTION_POLICY),
        "runner_policy": {
            "required_before_live": True,
            "runner_implemented": True,
            "runner_source_files": [RUNNER_SOURCE_REL],
            "runner_source_bound": RUNNER_SOURCE_REL in REPLAY_V4_SOURCE_FILES,
            "policy": (f"the #195 replay runner is implemented in {RUNNER_SOURCE_REL} and "
                       "included in REPLAY_V4_SOURCE_FILES; adding the runner does not "
                       "authorize execution — live execution still requires a separate "
                       "explicit authorization"),
            "adding_runner_authorizes_collection": False,
            "live_execution_rule": ("this registration lock is not live authorization; live "
                                    "execution requires the source-bound runner plus a "
                                    "separate explicit authorization"),
            "superseded_offline_lock": {
                "preregistration_hash": SUPERSEDED_OFFLINE_LOCK_HASH,
                "note": ("pre-runner offline lock; original content preserved in git commits "
                         "d97a459 and a2a9e31; superseded by this runner-bound amendment"),
            },
        },
        "claim_scope": {
            "type": "matched real/placebo/null replay preregistration (offline lock)",
            "experimental_unit": "prompt form",
            "k": 6,
            "events": EXPECTED_EVENT_COUNT,
            "statement": ("conditional on the six frozen planning-low forms and the paid Ling "
                          "route that generated the messages; locking is not live "
                          "authorization; fresh instance IDs never increase k"),
        },
        "outputs": output_paths(),
        "source_files": list(REPLAY_V4_SOURCE_FILES),
        "source_files_hash": _source_files_hash(root),
        "treatment_hash": treatment_hash_v4(decision_sha256=DECISION_SHA256,
                                            wording_hash=wording_hash,
                                            normalization_policy_hash=normalization_policy_hash),
        "message_wording_hash": wording_hash,
        "live_collection_authorized": False,
        "lock_is_not_live_authorization": True,
    }
    payload = json.dumps({key: value for key, value in document.items()
                          if key != "preregistration_hash"}, sort_keys=True)
    document["preregistration_hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return document


def prv6_protocol_key() -> str:
    return jc2.jev_choice_protocol_key_v2(model=pr.JEV_REPLAY_MODEL,
                                          endpoint=pr.JEV_REPLAY_ENDPOINT,
                                          max_retries=pr.JEV_REPLAY_MAX_RETRIES,
                                          instructions=jc.JEV_CHOICE_INSTRUCTIONS,
                                          question_id=jc.JEV_QUESTION_ID)


def verify_against_jev_replay_preregistration_v4(
        document: Mapping[str, Any], *, repo_root: Path | None = None,
        model: str | None = None, endpoint: str | None = None,
        protocol_key: str | None = None, require_approval: bool = True,
        journal_exists: bool | None = None,
        report_exists: bool | None = None) -> dict[str, Any]:
    """Repository-backed fail-closed verifier for the v4 replay registration."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    errors: list[str] = []

    if document.get("preregistration_version") != JEV_REPLAY_V4_PREREG_VERSION:
        errors.append("wrong registration version")
    if document.get("status") != JEV_REPLAY_V4_LOCKED_STATUS:
        errors.append("registration is not locked for the matched replay v4")
    if require_approval and (document.get("approval_required")
                             or not document.get("approval", {}).get("approved")):
        errors.append("registration lock approval is missing")
    if document.get("approval", {}).get("scope") != "replay_v4_registration_lock_only":
        errors.append("approval scope is not the v4 replay registration lock")
    if document.get("approval", {}).get("live_collection_authorized") is not False:
        errors.append("lock must not authorize live collection")
    if document.get("live_collection_authorized") is not False:
        errors.append("live_collection_authorized must be false")
    if document.get("lock_is_not_live_authorization") is not True:
        errors.append("lock-is-not-live-authorization declaration missing")

    try:
        decision = load_decision(root)
        expected_events = consume_decision_events(decision)
    except ValueError as exc:
        errors.append(f"decision_artifact_invalid: {exc}")
        decision, expected_events = None, []

    if decision is not None:
        recorded_upstream = (document.get("provenance", {}).get("upstream_sha256") or {})
        for relative, expected in recorded_upstream.items():
            path = root / relative
            actual = sha256_file(path) if path.is_file() else None
            if actual != expected:
                errors.append(f"upstream artifact drift: {relative}")
                break
        event_source = document.get("provenance", {}).get("event_source", {})
        if event_source.get("sha256") != DECISION_SHA256:
            errors.append("decision artifact pin drift")

    recorded_events = list(document.get("events") or [])
    recorded_ids = [str(event.get("event_id")) for event in recorded_events]
    expected_ids = [str(event.get("event_id")) for event in expected_events]
    if len(set(recorded_ids)) != len(recorded_ids):
        errors.append("duplicate event ids in registration")
    missing = [eid for eid in expected_ids if eid not in set(recorded_ids)]
    extra = [eid for eid in recorded_ids if eid not in set(expected_ids)]
    if missing:
        errors.append(f"missing event ids: {missing[:3]}")
    if extra:
        errors.append(f"extra event ids: {extra[:3]}")
    if not missing and not extra and recorded_ids != expected_ids:
        errors.append("event ids are reordered relative to the decision artifact")
    if len(recorded_events) != EXPECTED_EVENT_COUNT:
        errors.append(f"expected {EXPECTED_EVENT_COUNT} events, found {len(recorded_events)}")

    forms_block = document.get("forms", {})
    expected_counts = ({form: sum(1 for event in expected_events
                                  if event["prompt_form_id"] == form)
                        for form in FROZEN_FORM_IDS}) if expected_events else {}
    if set(forms_block.get("covered_form_ids") or []) != set(FROZEN_FORM_IDS):
        errors.append("covered form set differs from the six frozen forms")
    if forms_block.get("form_event_counts") != expected_counts:
        errors.append("per-form event counts differ from the decision artifact")
    if tuple(forms_block.get("expected_distribution") or ()) != EXPECTED_FORM_DISTRIBUTION:
        errors.append("expected distribution is not 1/4/4/1/4/3")
    distribution = tuple(len([e for e in recorded_events
                              if e.get("prompt_form_id") == form])
                         for form in FROZEN_FORM_IDS)
    if distribution != EXPECTED_FORM_DISTRIBUTION:
        errors.append(f"bound event distribution {distribution} != 1/4/4/1/4/3")
    membership = forms_block.get("form_membership") or {}
    if {form: [e.get("event_id") for e in recorded_events
               if e.get("prompt_form_id") == form] for form in sorted(membership)} \
            != {form: list(membership.get(form) or []) for form in sorted(membership)}:
        errors.append("form membership does not match the bound events")
    if forms_block.get("form_manifest_hash") != hashlib.sha256(
            json.dumps(sorted(FROZEN_FORM_IDS), sort_keys=True).encode("utf-8")).hexdigest():
        errors.append("form manifest hash mismatch")

    # frozen counterbalanced branch schedule
    try:
        expected_schedule = build_branch_schedule(expected_events)
    except Exception as exc:
        expected_schedule = None
        errors.append(f"branch schedule rebuild failed: {type(exc).__name__}: {exc}")
    schedule_block = document.get("branch_schedule") or {}
    if expected_schedule is not None and schedule_block != expected_schedule:
        errors.append("branch schedule drift from the frozen construction")
    if schedule_block.get("event_order") != [str(event.get("event_id"))
                                             for event in recorded_events]:
        errors.append("branch schedule event order differs from the bound events")
    if set(schedule_block.get("allowed_branches") or []) != set(BRANCHES):
        errors.append("branch schedule allows branches other than real/placebo/null")
    schedule_table = schedule_block.get("schedule") or {}
    if set(schedule_table) != {str(event.get("event_id")) for event in recorded_events}:
        errors.append("branch schedule is missing or has extra events")
    for event_id, branches in schedule_table.items():
        if (not isinstance(branches, list) or len(branches) != 3
                or sorted(branches) != sorted(BRANCHES)):
            errors.append(f"branch schedule entry is not a permutation of the branches: "
                          f"{event_id}")
            break
    used_permutations = {tuple(branches) for branches in schedule_table.values()}
    if used_permutations != set(BRANCH_PERMUTATIONS):
        errors.append("branch schedule does not represent all six permutations")
    balance = schedule_block.get("position_balance") or {}
    if balance != branch_position_balance(schedule_table):
        errors.append("branch position balance drift")
    elif int(balance.get("max_position_difference") or 99) > 1:
        errors.append("branch position counts differ by more than one")
    if balance.get("per_branch_totals") != {"null": 17, "placebo": 17, "real": 17}:
        errors.append("branch totals are not 17/17/17 across the 17 events")
    form_roles = schedule_block.get("form_roles") or {}
    if set(form_roles) != set(FROZEN_FORM_IDS):
        errors.append("branch schedule form coverage drift")
    for form, role in form_roles.items():
        events_in_form = [str(event.get("event_id")) for event in recorded_events
                          if event.get("prompt_form_id") == form]
        role_events = [entry.get("event_id") for entry in (role or {}).get("events", [])]
        if role_events != events_in_form:
            errors.append(f"branch schedule within-form event order drift: {form}")
            break
        permutations = [tuple(entry.get("branches") or ()) for entry in
                        (role or {}).get("events", [])]
        if len(set(permutations)) != len(permutations):
            errors.append(f"branch schedule does not rotate within form: {form}")
            break

    # per-event authoritative checks against regenerated instances
    for event in recorded_events:
        event_id = str(event.get("event_id"))
        try:
            instance = _regenerate_instance(str(event.get("instance_id")))
        except ValueError as exc:
            errors.append(f"event {event_id}: {exc}")
            continue
        real = event.get("real") or {}
        if real.get("writer_id") != "B" or real.get("reader_id") != "A":
            errors.append(f"event {event_id}: non-B->A real message")
        if event.get("prompt_form_id") not in FROZEN_FORM_IDS:
            errors.append(f"event {event_id}: prompt form is not one of the frozen six")
        real_claim = str(real.get("claim") or "")
        info = instance.information("A", real_claim, str(real.get("message_id") or "m"))
        if (info.status != "accepted" or info.delta_i_bits is None
                or not math.isclose(float(info.delta_i_bits), LOG2_3,
                                    rel_tol=0.0, abs_tol=1e-12)):
            errors.append(f"event {event_id}: real claim not informative at log2(3)")
        if not instance.holds_claim("B", real_claim):
            errors.append(f"event {event_id}: real claim not owned by B")
        if not math.isclose(float(real.get("i_m_bits") or -1.0), LOG2_3,
                            rel_tol=0.0, abs_tol=1e-12):
            errors.append(f"event {event_id}: frozen real I_m is not log2(3)")

        placebo = event.get("placebo") or {}
        placebo_claim = str(placebo.get("claim") or "")
        if placebo_claim not in [str(c) for c in instance.private_clues.get("A", ())]:
            errors.append(f"event {event_id}: placebo claim is not receiver-known")
        else:
            placebo_info = instance.information("A", placebo_claim, "placebo")
            placebo_delta = placebo_info.delta_i_bits
            extended = instance.clue_consistent(
                set(instance.private_clues.get("A", ())) | {placebo_claim})
            if (placebo_info.status != "accepted"
                    or placebo_delta is None or float(placebo_delta) != 0.0
                    or extended != instance.private_solutions["A"]
                    or placebo.get("i_m_bits") not in (0, 0.0)
                    or placebo.get("synthetic") is not True
                    or placebo.get("construction") != jr.PLACEBO_CONSTRUCTION
                    or placebo.get("envelope") != jr.MESSAGE_ENVELOPE_TEMPLATE):
                errors.append(f"event {event_id}: placebo claim is not inert")
        if placebo.get("origin") != jr.PLACEBO_ORIGIN:
            errors.append(f"event {event_id}: placebo origin drift")

        try:
            body, state = pre_read_body(instance, pr.JEV_REPLAY_MODEL)
        except ValueError as exc:
            errors.append(f"event {event_id}: {exc}")
            continue
        pre_read = event.get("pre_read") or {}
        if jr.prompt_form_id(body) != event.get("prompt_form_id"):
            errors.append(f"event {event_id}: branch-state prompt_form_id mismatch")
        if pre_read.get("request_body_hash") != jr.prompt_form_id(body):
            errors.append(f"event {event_id}: request body hash mismatch")
        if pre_read.get("state_hash") != jr.canonical_hash(dict(state.state)):
            errors.append(f"event {event_id}: pre-read state hash mismatch")
        expected_branches = {
            "real": jr.prompt_form_id(jr.branch_request_body(
                body, jr.serialize_message(real_claim))),
            "placebo": jr.prompt_form_id(jr.branch_request_body(
                body, jr.serialize_placebo_message(placebo_claim))),
            "null": jr.prompt_form_id(jr.branch_request_body(body, None)),
        }
        if pre_read.get("branch_request_hashes") != expected_branches:
            errors.append(f"event {event_id}: branch request hash mismatch")
        if sorted(pre_read.get("option_ids") or []) != sorted(
                str(label) for label in instance.solutions):
            errors.append(f"event {event_id}: option drift")
        state_json = json.dumps(dict(state.state), sort_keys=True)
        target = str(instance.target)
        if target and target in state_json:
            errors.append(f"event {event_id}: target leakage")
        for marker in ("joint_solutions", "joint_candidate", "joint_solution"):
            if marker in state_json:
                errors.append(f"event {event_id}: answer-key marker leakage")
                break

        authoritative_set = sorted(str(value)
                                   for value in instance.private_solutions["A"])
        clue_consistent = sorted(str(value) for value in
                                 instance.clue_consistent(instance.private_clues["A"]))
        if authoritative_set != clue_consistent:
            errors.append(f"event {event_id}: authoritative feasible set drifted from the "
                          f"clue-consistent pre-read set")
        if pre_read.get("feasible_set") != authoritative_set:
            errors.append(f"event {event_id}: feasible set drift")
        if pre_read.get("feasible_set_hash") != jr.canonical_hash(authoritative_set):
            errors.append(f"event {event_id}: feasible set hash drift")
        if pre_read.get("feasible_set_verified") is not True:
            errors.append(f"event {event_id}: feasible set verification missing")
        if pre_read.get("target_id") != target:
            errors.append(f"event {event_id}: target id drift")

    # frozen design blocks
    estimand = document.get("estimand") or {}
    if estimand.get("experimental_unit") != "prompt form" or estimand.get("k") != 6:
        errors.append("experimental unit or k drift")
    if estimand.get("events_are_independent_units") is not False:
        errors.append("registration must not treat the events as independent units")
    if estimand.get("event_contrast") != ESTIMAND["event_contrast"] \
            or estimand.get("directional_prediction") != ESTIMAND["directional_prediction"]:
        errors.append("estimand drift")
    if "equal-weight mean" not in str(estimand.get("primary")):
        errors.append("primary estimand is not the equal-form mean")
    inference = document.get("inference") or {}
    for key, expected in (("primary_test", INFERENCE["primary_test"]),
                          ("interval", INFERENCE["interval"]),
                          ("min_two_sided_p_k6", 0.03125),
                          ("min_two_sided_p_k5", 0.0625)):
        if inference.get(key) != expected:
            errors.append(f"inference rule drift: {key}")
    if "negative" not in str(inference.get("direction_requirement")):
        errors.append("direction requirement missing")
    guards = document.get("guards") or {}
    if guards.get("target_probability_delta") != 0.0 \
            or guards.get("feasible_set_mass_epsilon") != 0.01:
        errors.append("guard thresholds drift")
    if "never used to filter" not in str(guards.get("reporting")):
        errors.append("guards must not filter the primary estimate")
    formulas = guards.get("formulas") or {}
    for key, expected in GUARD_FORMULAS.items():
        if formulas.get(key) != expected:
            if key in ("target_ok_i", "mass_ok_i"):
                errors.append(f"guard comparison drift: {key}")
            else:
                errors.append(f"guard formula drift: {key}")
    if "frozen authoritative pre-read feasible_set" not in str(guards.get("reference_set")):
        errors.append("guard reference-set definition drift")
    missingness = document.get("missingness") or {}
    if missingness.get("imputation") != "never impute missing pairs":
        errors.append("missingness imputation rule drift")
    if "every one of the six" not in str(missingness.get("primary_requirement")):
        errors.append("six-form complete-pair requirement missing")
    if "no causal gate" not in str(missingness.get("five_form_fallback")) \
            or "0.05" not in str(missingness.get("five_form_fallback")):
        errors.append("five-form fallback rule drift")
    if missingness.get("below_five_forms") != "replay-coverage failure":
        errors.append("below-five rule drift")
    sensitivity = document.get("sensitivity") or {}
    if sensitivity.get("normalization_thresholds") != [1e-6, 0.01, 0.03, 0.05]:
        errors.append("sensitivity thresholds drift")
    if "never overrides the primary result" not in str(sensitivity.get("rule")):
        errors.append("secondary-analysis rule drift")
    limitations = document.get("limitations") or {}
    if limitations.get("mde_or_ci_bits") != 0.203:
        errors.append("MDE limitation drift")

    # protocol, caps, outputs
    protocol = document.get("model_and_protocol") or {}
    if protocol.get("model") != pr.JEV_REPLAY_MODEL or (model is not None
                                                        and model != pr.JEV_REPLAY_MODEL):
        errors.append("wrong Jev model")
    if protocol.get("endpoint") != pr.JEV_REPLAY_ENDPOINT or (
            endpoint is not None and endpoint != pr.JEV_REPLAY_ENDPOINT):
        errors.append("wrong Jev endpoint")
    if protocol.get("codec_version") != jc2.JEV_CHOICE_V2_CODEC_VERSION:
        errors.append("wrong codec version")
    key = str(protocol_key or protocol.get("protocol_key") or "")
    if not key or jc.is_jev_protocol_key(key):
        errors.append("protocol key is missing or a v1 key")
    elif not jc2.is_jev_v2_protocol_key(key) or key != prv6_protocol_key():
        errors.append("protocol key is not the registered v2 Jev key")
    if protocol_key is not None and protocol_key != protocol.get("protocol_key"):
        errors.append("runtime protocol key differs from the registration")
    if protocol.get("normalization_policy_hash") != prv2.normalization_policy_hash():
        errors.append("normalization policy drift")
    wire_keys = set()

    def _collect(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                _collect(value)
        elif isinstance(node, list):
            for value in node:
                _collect(value)
        elif isinstance(node, str) and node.startswith("jev-choice-wire") and "|" in node:
            wire_keys.add(node)

    _collect(document)
    if wire_keys - {protocol.get("protocol_key")}:
        errors.append("mixed or non-Jev protocol keys present")

    caps = document.get("caps") or {}
    planned = caps.get("planned_calls") or {}
    partition = caps.get("provider_partition") or {}
    if (planned.get("jev"), planned.get("ling"), planned.get("combined")) != (51, 0, 51):
        errors.append("planned call arithmetic drift (expected 51 Jev / 0 Ling)")
    if caps.get("physical_requests") != 153:
        errors.append("physical request ceiling drift (expected 153)")
    if partition.get("jev") != 153 or partition.get("ling") != 0 or partition.get("total") != 153:
        errors.append("provider partition drift")
    if int(partition.get("jev", 0)) != PLANNED_JEV_CALLS * RETRY_RESERVE_FACTOR:
        errors.append("physical ceiling is not the retry-inclusive 51 x 3")
    if caps.get("cost_cap_usd") != COST_CAP_USD or COST_CAP_USD > 1.0:
        errors.append("cost ceiling drift")
    if caps.get("worst_case_cost_usd") != WORST_CASE_COST_USD:
        errors.append("worst-case cost drift")
    if caps.get("worst_case_next_call_cost_usd") != NEXT_CALL_RESERVE_USD:
        errors.append("next-call cost reservation drift")
    if f"{NEXT_CALL_RESERVE_USD}" not in str(caps.get("next_call_reservation_arithmetic", "")):
        errors.append("next-call reservation arithmetic missing")
    if float(caps.get("worst_case_cost_usd", 1e9)) > float(caps.get("cost_cap_usd", 0.0)):
        errors.append("worst-case cost exceeds the cost ceiling")
    ling_budget = caps.get("ling_budget") or {}
    if ling_budget.get("planned_calls") != 0 or ling_budget.get("physical_cap") != 0:
        errors.append("replay registration must not carry a Ling budget")

    policy = document.get("execution_policy") or {}

    def policy_check(condition: bool, name: str) -> None:
        if not condition:
            errors.append(f"execution policy drift: {name}")

    preflight_items = " | ".join(policy.get("preflight") or [])
    for required in ("registration hash", "branch-order manifests", "protocol key",
                     "treatment hashes", "never printed", "paths absent",
                     "request and cost caps", "no provider call before"):
        policy_check(required in preflight_items, f"preflight.{required}")
    lifecycle = policy.get("output_lifecycle") or {}
    policy_check(lifecycle.get("overwrite") is False, "output_lifecycle.overwrite")
    policy_check(lifecycle.get("automatic_resume") is False,
                 "output_lifecycle.automatic_resume")
    policy_check(lifecycle.get("append_to_prior_replay_artifacts") is False,
                 "output_lifecycle.append_to_prior_replay_artifacts")
    policy_check("new review and explicit authorization" in
                 str(lifecycle.get("fresh_execution_after_partial_run")),
                 "output_lifecycle.fresh_execution_after_partial_run")
    policy_check(lifecycle.get("raw_provider_envelopes_retained") is False
                 and lifecycle.get("credentials_retained") is False,
                 "output_lifecycle.retention")
    journal_policy = policy.get("journal") or {}
    policy_check(journal_policy.get("kind") == "append-only branch-attempt journal",
                 "journal.kind")
    policy_check("one durable row per logical (event_id, branch) execution"
                 in str(journal_policy.get("row_unit")), "journal.row_unit")
    policy_check("fsync after every logical branch outcome"
                 in str(journal_policy.get("durability")), "journal.durability")
    policy_check(journal_policy.get("unique_key") == ["event_id", "branch"],
                 "journal.unique_key")
    policy_check(journal_policy.get("duplicate_key_policy") == "fail closed",
                 "journal.duplicate_key_policy")
    row_fields = journal_policy.get("row_fields") or []
    for required in ("planned_branch_position", "actual_branch_position", "request_hash",
                     "state_hash", "protocol_key", "physical_attempts", "validity",
                     "usage", "error_class", "cap counters"):
        policy_check(required in row_fields, f"journal.row_fields.{required}")
    policy_check("fail closed if actual" in str(journal_policy.get("branch_order_persistence")),
                 "journal.branch_order_persistence")
    policy_check("event-level real/placebo/null records"
                 in str(journal_policy.get("report_grouping")), "journal.report_grouping")
    policy_check("remain observable" in str(journal_policy.get("partial_triplets")),
                 "journal.partial_triplets")
    per_branch = policy.get("per_branch") or {}
    policy_check("maximum two" in str(per_branch.get("retries")), "per_branch.retries")
    policy_check(per_branch.get("physical_attempts_include_retries") is True,
                 "per_branch.physical_attempts_include_retries")
    policy_check(per_branch.get("cost_reservation_usd") == NEXT_CALL_RESERVE_USD
                 and f"{NEXT_CALL_RESERVE_USD}" in str(per_branch.get("cost_reservation")),
                 "per_branch.cost_reservation")
    policy_check("does not cause the remaining branches" in
                 str(per_branch.get("nonterminal_invalid")), "per_branch.nonterminal_invalid")
    policy_check("real and placebo are both valid" in str(per_branch.get("complete_pair")),
                 "per_branch.complete_pair")
    policy_check("not required for the primary" in str(per_branch.get("null_validity")),
                 "per_branch.null_validity")
    policy_check(per_branch.get("imputation") == "none", "per_branch.imputation")
    expected_stops = [
        "request cap or cost cap before the next call", "model drift", "protocol-key drift",
        "request/state/option identity drift",
        "malformed or non-finite/negative/option-mismatched vectors",
        "hard normalization deviation above 0.05", "argmax shift after normalization",
        "output collision", "registration or source/treatment hash drift"]
    if list(policy.get("immediate_terminal_stops") or []) != expected_stops:
        errors.append("terminal stop classes drift")
    nonterminal = policy.get("nonterminal_invalidity") or {}
    policy_check("recorded invalid" in str(nonterminal.get("policy"))
                 and "never" in str(nonterminal.get("policy"))
                 and "continue unless" in str(nonterminal.get("policy")),
                 "nonterminal_invalidity.policy")
    policy_check("suspect sensitivity band" in str(nonterminal.get("band")),
                 "nonterminal_invalidity.band")
    provider = policy.get("provider_failures") or {}
    policy_check("sanitized invalid branch row" in str(provider.get("retry_exhaustion")),
                 "provider_failures.retry_exhaustion")
    policy_check(provider.get("consecutive_terminal_failure_stop") == 2,
                 "provider_failures.consecutive_terminal_failure_stop")
    policy_check("successful valid response" in str(provider.get("reset")),
                 "provider_failures.reset")
    policy_check("never retain response bodies" in str(provider.get("retention")),
                 "provider_failures.retention")
    stopping = str(policy.get("stopping_report") or "")
    policy_check("planned/attempted/valid/invalid/unattempted" in stopping
                 and "by branch, event, and form" in stopping, "stopping_report")

    runner_policy = document.get("runner_policy") or {}
    if runner_policy.get("required_before_live") is not True:
        errors.append("runner policy missing")
    if runner_policy.get("runner_implemented") is not True:
        errors.append("runner must be implemented and source-bound in this lock")
    if runner_policy.get("runner_source_files") != [RUNNER_SOURCE_REL]:
        errors.append("runner source file mismatch")
    if runner_policy.get("runner_source_bound") is not True:
        errors.append("runner source binding declaration missing")
    if RUNNER_SOURCE_REL not in REPLAY_V4_SOURCE_FILES:
        errors.append("runner module missing from REPLAY_V4_SOURCE_FILES")
    if runner_policy.get("adding_runner_authorizes_collection") is not False:
        errors.append("adding a runner must not authorize collection")
    if "does not authorize execution" not in str(runner_policy.get("policy", "")):
        errors.append("runner policy must state that adding the runner does not authorize "
                      "execution")
    if "separate explicit authorization" not in str(runner_policy.get("live_execution_rule", "")):
        errors.append("runner live-execution rule drift")
    superseded = runner_policy.get("superseded_offline_lock") or {}
    if superseded.get("preregistration_hash") != SUPERSEDED_OFFLINE_LOCK_HASH:
        errors.append("superseded offline lock hash missing or drifted")

    outputs = document.get("outputs") or {}
    if outputs != output_paths():
        errors.append("output paths differ from the fresh v4 paths")
    for old in OLD_OUTPUT_PATHS_V4:
        if any(old in str(value) for value in outputs.values()):
            errors.append(f"old output path rejected: {old}")
    journal_path = root / str(outputs.get("journal", DEFAULT_JOURNAL_V4))
    report_path = root / str(outputs.get("report", DEFAULT_REPORT_V4))
    journal_bad = journal_exists if journal_exists is not None else journal_path.exists()
    report_bad = report_exists if report_exists is not None else report_path.exists()
    if journal_bad:
        errors.append("future replay journal already exists")
    if report_bad:
        errors.append("future replay report already exists")

    try:
        expected = build_replay_preregistration_v4(approved=True, repo_root=root)
    except Exception as exc:
        errors.append(f"rebuild_failed: {type(exc).__name__}: {exc}")
        expected = None
    if expected is not None:
        if document.get("preregistration_hash") != expected.get("preregistration_hash"):
            errors.append("registration hash drift from the repository state")
        recorded = {key: value for key, value in document.items()
                    if key != "preregistration_hash"}
        wanted = {key: value for key, value in expected.items()
                  if key != "preregistration_hash"}
        if recorded != wanted:
            errors.append("registration content drift from the repository state")
        if document.get("source_files_hash") != _source_files_hash(root):
            errors.append("source hash does not match the checked-out sources")
        if document.get("treatment_hash") != expected.get("treatment_hash"):
            errors.append("treatment hash drift")

    return {"ok": not errors, "errors": errors,
            "registration_hash": document.get("preregistration_hash"),
            "event_count": len(recorded_events), "k": 6,
            "planned_jev": PLANNED_JEV_CALLS,
            "physical_ceiling": PHYSICAL_REQUEST_CEILING,
            "live_collection_authorized": False}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="#193 matched replay preregistration v4")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_V4)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--approve", action="store_true",
                        help="write the locked registration (offline lock, never live "
                             "authorization)")
    args = parser.parse_args(argv)
    root = Path(args.repo_root) if args.repo_root is not None else _repo_root()
    document = build_replay_preregistration_v4(approved=args.approve, repo_root=root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
                           encoding="utf-8")
    verification = verify_against_jev_replay_preregistration_v4(
        document, repo_root=root)
    print(json.dumps({
        "preregistration_version": document["preregistration_version"],
        "status": document["status"],
        "live_collection_authorized": document["live_collection_authorized"],
        "events": len(document["events"]), "k": document["forms"]["k"],
        "distribution": document["forms"]["expected_distribution"],
        "planned_calls": document["caps"]["planned_calls"],
        "physical_requests": document["caps"]["physical_requests"],
        "worst_case_cost_usd": document["caps"]["worst_case_cost_usd"],
        "preregistration_hash": document["preregistration_hash"],
        "verify_ok": verification["ok"],
        "verify_errors": verification["errors"],
        "provider_calls": 0,
        "output": str(args.output),
    }, indent=2, sort_keys=True, allow_nan=False))
    return 0 if verification["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "JEV_REPLAY_V4_PREREG_VERSION", "JEV_REPLAY_V4_DRAFT_STATUS",
    "JEV_REPLAY_V4_LOCKED_STATUS", "DEFAULT_OUTPUT_V4", "DEFAULT_JOURNAL_V4",
    "DEFAULT_REPORT_V4", "DECISION_ARTIFACT", "DECISION_SHA256",
    "DECISION_BASELINE_COMMIT", "FROZEN_FORM_IDS", "EXPECTED_FORM_DISTRIBUTION",
    "EXPECTED_EVENT_COUNT", "LOG2_3", "PLANNED_JEV_CALLS", "PLANNED_LING_CALLS",
    "RETRY_RESERVE_FACTOR", "PHYSICAL_REQUEST_CEILING", "INPUT_TOKEN_CEILING",
    "INPUT_USD_PER_MTOK", "WORST_CASE_CALL_COST_USD", "WORST_CASE_COST_USD",
    "COST_CAP_USD", "REPLAY_V4_SOURCE_FILES", "OLD_OUTPUT_PATHS_V4", "ESTIMAND",
    "INFERENCE", "GUARDS", "MISSINGNESS", "SENSITIVITY", "LIMITATIONS",
    "sha256_file", "load_decision", "consume_decision_events", "pre_read_body",
    "build_event_binding", "treatment_hash_v4", "output_paths", "prv6_protocol_key",
    "build_replay_preregistration_v4",
    "verify_against_jev_replay_preregistration_v4", "main",
]
