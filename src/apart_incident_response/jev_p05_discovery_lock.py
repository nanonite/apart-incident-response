"""P05 (#206): offline preflight and the versioned discovery lock.

This module never makes a provider call. It runs a fail-closed offline
preflight over the P04 discovery registration and its frozen inputs, then
builds a byte-reproducible lock artifact that fixes the design that a
*separate* live authorization reference would have to cover.

Locking is not authorization. The lock deliberately records that the
authorization reference has not been supplied, and ``verify_lock`` fails
closed unless the independent review record exists and approves this exact
lock hash. Neither the lock, the credentials present in the environment, nor
the prompt may be read as approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from apart_incident_response.jev_p04_design_classification import (
    AUDIT_CONTENT_HASH,
    AUDIT_PATH,
    CENSUS_CONTENT_HASH,
    CENSUS_PATH,
    PREREGISTRATION_HASH,
    REGISTRATION_200_PATH,
    REGISTRATION_PATH,
    REGISTRATION_VERSION,
    SCOPE_CONTENT_HASH,
    SCOPE_PATH,
    verify_registration,
)

LOCK_VERSION = "jev-discovery-lock-v1"
REVIEW_VERSION = "jev-discovery-lock-review-v1"
LOCK_PATH = "runs/next-phase/jev-p05-discovery-lock-v1.json"
REVIEW_PATH = "runs/next-phase/jev-p05-discovery-lock-review-v1.json"

ISSUE = "#206"
PARENT_ISSUE = "#201"
ROOT_ISSUE = "#159"
PROTOCOL = "docs/jev-discovery-confirmation-plan.md"
PLAN_PATH = "docs/jev-discovery-confirmation-plan.md"
P04_DOC_PATH = "docs/jev-p04-design-classification.md"

LOCK_STATUS = "locked_pending_separate_live_authorization"
PENDING_REVIEW_STATUS = "pending_independent_review"
APPROVED_REVIEW_STATUS = "approved"

P04_REGISTRATION_HASH = "6fa6149770b620cd3a026a6415f8e4d97e800e8af5237794de7b29fca6dacfac"
K = 4
FLOOR = "0.125"
CLASSIFICATION = "pilot"

AUTHORIZATION_MUST_COVER = ["stage", "route", "request_caps", "cost_caps"]

MAY_NOT_BE_INFERRED_FROM = [
    "this lock",
    "the locked registration",
    "credentials present in the environment",
    "the task prompt or plan document",
    "the presence of reserved output paths",
]


class DiscoveryLockError(ValueError):
    """Fail-closed preflight, build or verification violation."""


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _render(document: Mapping[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _hash_excluding(document: Mapping[str, Any], excluded_key: str) -> str:
    payload = json.dumps({key: value for key, value in document.items()
                          if key != excluded_key}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _lock_hash(document: Mapping[str, Any]) -> str:
    """Content hash of a lock document (excludes its own lock_hash)."""
    return _hash_excluding(document, "lock_hash")


def _registration_hash(document: Mapping[str, Any]) -> str:
    """Content hash of the P04 registration (excludes its own registration_hash)."""
    return _hash_excluding(document, "registration_hash")


def _registration(repo_root: Path) -> dict[str, Any]:
    path = repo_root / REGISTRATION_PATH
    if not path.is_file():
        raise DiscoveryLockError(f"missing P04 registration at {REGISTRATION_PATH}")
    return _load_json(path)


# --------------------------------------------------------------------------
# offline preflight
# --------------------------------------------------------------------------

def run_preflight(repo_root: Path) -> dict[str, Any]:
    """Fail-closed offline preflight over the inputs P05 locks. Zero calls."""
    root = Path(repo_root)
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

    try:
        registration = _registration(root)
    except (DiscoveryLockError, OSError, json.JSONDecodeError) as exc:
        check("p04_registration_present", False, f"{type(exc).__name__}: {exc}")
        return {"mode": f"{LOCK_VERSION}-preflight", "ok": False, "errors": errors,
                "failed": [entry["check"] for entry in checks if not entry["ok"]],
                "checks": checks, "provider_calls": 0, "status": "offline"}

    check("p04_registration_present", True, str(REGISTRATION_PATH))
    check("p04_registration_hash_recomputes",
          _registration_hash(registration) == P04_REGISTRATION_HASH,
          _registration_hash(registration))
    check("p04_registration_version",
          registration.get("preregistration_version") == REGISTRATION_VERSION,
          registration.get("preregistration_version"))

    sub = verify_registration(registration, repo_root=root)
    check("p04_registration_verifies_green", sub.get("ok") is True
          and sub.get("failed") == [], {"failed": sub.get("failed"),
                                        "checks": len(sub.get("checks", []))})
    check("p04_status_is_draft_pending_review",
          registration.get("status") == "draft_pending_review",
          registration.get("status"))

    evidence = registration.get("input_evidence") or {}
    check("audit_200_file_sha256",
          evidence.get("audit_200", {}).get("file_sha256") == _sha256_file(root / AUDIT_PATH),
          None)
    check("audit_200_content_hash_pin",
          evidence.get("audit_200", {}).get("audit_content_hash") == AUDIT_CONTENT_HASH
          and registration.get("input_evidence", {}).get("audit_200", {})
          .get("audit_content_hash") == AUDIT_CONTENT_HASH, None)
    check("registration_200_file_sha256",
          evidence.get("registration_200", {}).get("file_sha256")
          == _sha256_file(root / REGISTRATION_200_PATH), None)
    check("registration_200_hash_pin",
          evidence.get("registration_200", {}).get("preregistration_hash")
          == PREREGISTRATION_HASH, None)
    check("scope_freeze_p02_hashes",
          evidence.get("scope_freeze_p02", {}).get("file_sha256")
          == _sha256_file(root / SCOPE_PATH)
          and evidence.get("scope_freeze_p02", {}).get("content_hash") == SCOPE_CONTENT_HASH,
          None)
    check("census_p03_hashes",
          evidence.get("census_p03", {}).get("file_sha256") == _sha256_file(root / CENSUS_PATH)
          and evidence.get("census_p03", {}).get("content_hash") == CENSUS_CONTENT_HASH, None)
    check("frozen_200_artifacts_preserved",
          _sha256_file(root / AUDIT_PATH) == evidence.get("audit_200", {}).get("file_sha256")
          and _sha256_file(root / REGISTRATION_200_PATH)
          == evidence.get("registration_200", {}).get("file_sha256"), None)

    classification = registration.get("design_classification") or {}
    check("k_is_4", classification.get("k") == K, classification.get("k"))
    check("attainable_floor_is_0_125",
          classification.get("attainable_two_sided_sign_flip_floor") == FLOOR,
          classification.get("attainable_two_sided_sign_flip_floor"))
    check("floor_above_0_05", classification.get("floor_above_0_05") is True, None)
    check("classification_is_pilot", classification.get("classification") == CLASSIFICATION,
          classification.get("classification"))
    check("fresh_seed_replication_descriptive",
          "descriptive only" in str(classification.get("fresh_seed_replication")),
          classification.get("fresh_seed_replication"))
    check("estimand_h0_h1",
          classification.get("estimand")
          == "equal-weight form mean of real-minus-placebo entropy"
          and classification.get("h0") == "Delta = 0"
          and classification.get("h1") == "Delta < 0", None)
    check("guards_never_filter", classification.get("guards_never_filter_the_estimate") is True,
          None)
    check("no_planning_low_prior",
          classification.get("no_planning_low_effect_size_prior") is True, None)

    fixed_n = registration.get("fixed_n") or {}
    window = fixed_n.get("window") or {}
    check("fixed_n_block_16", fixed_n.get("block_n") == 16, fixed_n.get("block_n"))
    check("fixed_n_4_per_form",
          fixed_n.get("instances_per_form") == 4 and fixed_n.get("form_count") == 4,
          {"instances_per_form": fixed_n.get("instances_per_form"),
           "form_count": fixed_n.get("form_count")})
    check("fixed_n_window_discovery",
          window.get("base") == 85000 and window.get("end") == 85511, window)
    check("manifest_16_entries", len(fixed_n.get("manifest") or []) == 16,
          len(fixed_n.get("manifest") or []))
    check("manifest_matches_200_primary",
          fixed_n.get("matches_200_audit_primary_block") is True, None)
    check("selection_rule_fixed_no_stopping",
          "no outcome-based stopping" in str(fixed_n.get("selection_rule")),
          fixed_n.get("selection_rule"))

    treatment = registration.get("treatment") or {}
    check("treatment_original_l4x",
          treatment.get("mode") == "exact-original-comm-bridge"
          and treatment.get("family") == "hypothesis"
          and treatment.get("complexity") == "low"
          and treatment.get("regime") == "N"
          and treatment.get("turns") == 2
          and treatment.get("primary_direction") == "one-way B->A"
          and treatment.get("final_receiver") == "A via Jev Choice wire v2", None)
    check("treatment_one_way_board_evidence",
          "board_write" in str(treatment.get("board_evidence"))
          and "peer_read_exposure" in str(treatment.get("board_evidence")), None)

    route = registration.get("route") or {}
    ling = route.get("ling") or {}
    jev = route.get("jev") or {}
    normalization = route.get("normalization") or {}
    check("route_ling_paid_openrouter",
          ling.get("model") == "inclusionai/ling-3.0-flash-vl"
          and "openrouter.ai" in str(ling.get("endpoint"))
          and "paid OpenRouter SKU" in str(ling.get("route")), None)
    check("route_jev_systemone",
          jev.get("model") == "jev-1.13.0"
          and "api.typesafe.ai" in str(jev.get("endpoint"))
          and jev.get("codec_version") == "jev-choice-wire-v2", None)
    check("normalization_hard_ceiling_0_05",
          normalization.get("hard_ceiling") == 0.05
          and normalization.get("policy", {}).get("hard_ceiling") == 0.05, None)
    check("normalization_policy_hash",
          normalization.get("policy_hash")
          == "292ac217f1cf54083252e6363a16a48596daab72a8ca06d4569c20f861b7e1e9",
          normalization.get("policy_hash"))

    budgets = registration.get("budgets") or {}
    collection = budgets.get("discovery_collection") or {}
    replay = budgets.get("exploratory_replay") or {}
    program = budgets.get("program") or {}
    cost = budgets.get("cost_model") or {}
    check("collection_request_caps",
          collection.get("planned") == {"combined": 80, "jev": 16, "ling": 64}
          and collection.get("physical") == {"combined": 240, "jev": 48, "ling": 192}, None)
    check("replay_request_caps",
          replay.get("branches") == 3 and replay.get("events_max") == 16
          and replay.get("planned", {}).get("jev") == 48
          and replay.get("physical", {}).get("jev") == 144, None)
    check("program_request_caps",
          program.get("planned") == {"combined": 128, "jev": 64, "ling": 64}
          and program.get("physical") == {"combined": 384, "jev": 192, "ling": 192}, None)
    check("cost_model_rates",
          cost.get("ling_worst_physical_call_usd") == 0.00067584
          and cost.get("jev_worst_physical_call_usd") == 0.000344064, None)
    check("next_call_reservations",
          collection.get("next_call_reservation_usd") == {"jev": 0.001032192,
                                                          "ling": 0.00202752}, None)
    check("cost_ceilings_and_worst_cases",
          collection.get("cost_ceiling_usd") == 0.2
          and collection.get("worst_case_cost_usd") == 0.146276352
          and replay.get("cost_ceiling_usd") == 0.1
          and replay.get("worst_case_cost_usd") == 0.049545216
          and program.get("cost_ceiling_usd") == 0.3
          and program.get("worst_case_cost_usd") == 0.195821568, None)
    check("worst_case_within_ceiling",
          collection.get("worst_case_cost_usd", 1e9) <= collection.get("cost_ceiling_usd", 0.0)
          and replay.get("worst_case_cost_usd", 1e9) <= replay.get("cost_ceiling_usd", 0.0)
          and program.get("worst_case_cost_usd", 1e9) <= program.get("cost_ceiling_usd", 0.0),
          None)

    stops = registration.get("stops") or []
    check("terminal_stops_registered",
          any("cost cap" in str(item) for item in stops)
          and any("hash drift" in str(item) for item in stops)
          and any("output collision" in str(item) for item in stops)
          and any("two consecutive terminal provider failures" in str(item) for item in stops),
          len(stops))

    paths = registration.get("paths") or {}
    live_paths = [str(value) for key, value in paths.items() if key != "registration"]
    check("live_paths_registered",
          len(live_paths) == 4 and all(str(value).startswith(
              "runs/next-phase/hypothesis/jev-discovery-v1/") for value in live_paths),
          sorted(live_paths))
    check("live_paths_absent",
          not any((root / value).exists() for value in live_paths),
          sorted(value for value in live_paths if (root / value).exists()))
    check("paths_outside_epic_126",
          all(not str(value).startswith("runs/epic-126/") for value in paths.values()),
          sorted(paths))
    lifecycle = registration.get("path_lifecycle") or {}
    check("path_lifecycle_fresh_only",
          lifecycle.get("resume") is False and lifecycle.get("append") is False
          and lifecycle.get("overwrite") is False
          and lifecycle.get("path_overrides") is False
          and lifecycle.get("fresh_paths") is True, lifecycle)

    coverage = registration.get("coverage_rules") or {}
    check("coverage_no_imputation_no_replacement",
          coverage.get("no_imputation") is True
          and coverage.get("no_seed_replacement") is True
          and coverage.get("no_form_removal_after_outcomes") is True, None)
    check("coverage_missing_form_rule",
          "blocks confirmation" in str(coverage.get("missing_entire_form"))
          and "descriptive" in str(coverage.get("missing_entire_form")), None)

    exploratory = registration.get("exploratory_replay") or {}
    check("exploratory_replay_labeled",
          "exploratory" in str(exploratory.get("label"))
          and "never confirmatory" in str(exploratory.get("label")), None)
    check("exploratory_replay_separate_authorization",
          "separately covered by P05 authorization"
          in str(exploratory.get("coverage", exploratory.get("authorization_note", "")))
          or "separately covered by P05 authorization"
          in json.dumps(exploratory), None)

    authorization = registration.get("authorization") or {}
    check("locking_is_not_authorization",
          authorization.get("locking_is_not_authorization") is True
          and authorization.get("approval_may_not_be_inferred_from_locking") is True
          and authorization.get("separate_live_authorization_required_after_locking") is True
          and authorization.get("approval_must_be_a_supplied_reference") is True, None)
    check("pending_review_items_recorded",
          len(authorization.get("pending_review") or []) == 4, None)
    check("registration_offline_only",
          registration.get("offline_only") is True
          and "no provider call" in str(registration.get("authorizes")), None)

    return {"mode": f"{LOCK_VERSION}-preflight", "ok": not errors,
            "errors": errors,
            "failed": [entry["check"] for entry in checks if not entry["ok"]],
            "checks": checks, "checks_run": len(checks),
            "provider_calls": 0, "status": "offline"}


# --------------------------------------------------------------------------
# authorization scope
# --------------------------------------------------------------------------

def authorization_scope(registration: Mapping[str, Any]) -> dict[str, Any]:
    """Exactly the scope a separate live authorization reference must cover."""
    budgets = registration.get("budgets") or {}
    collection = budgets.get("discovery_collection") or {}
    replay = budgets.get("exploratory_replay") or {}
    program = budgets.get("program") or {}
    return {
        "stage": registration.get("stage"),
        "family": registration.get("family"),
        "route": registration.get("route"),
        "request_caps": {
            "block_n": budgets.get("block_n"),
            "retry_model": "every logical call may execute up to 3 physical attempts "
                           "(1 + max_retries 2); all caps are retry inclusive",
            "discovery_collection_planned": collection.get("planned"),
            "discovery_collection_physical": collection.get("physical"),
            "exploratory_replay_planned": replay.get("planned"),
            "exploratory_replay_physical": replay.get("physical"),
            "exploratory_replay_branches": replay.get("branches"),
            "exploratory_replay_events_max": replay.get("events_max"),
            "program_planned": program.get("planned"),
            "program_physical": program.get("physical"),
        },
        "cost_caps": {
            "discovery_collection_ceiling_usd": collection.get("cost_ceiling_usd"),
            "discovery_collection_worst_case_usd": collection.get("worst_case_cost_usd"),
            "exploratory_replay_ceiling_usd": replay.get("cost_ceiling_usd"),
            "exploratory_replay_worst_case_usd": replay.get("worst_case_cost_usd"),
            "program_ceiling_usd": program.get("cost_ceiling_usd"),
            "program_worst_case_usd": program.get("worst_case_cost_usd"),
            "next_call_reservation_usd": {
                "discovery_collection": collection.get("next_call_reservation_usd"),
                "exploratory_replay": replay.get("next_call_reservation_usd"),
            },
        },
        "stops": registration.get("stops"),
        "paths": registration.get("paths"),
        "path_lifecycle": registration.get("path_lifecycle"),
    }


# --------------------------------------------------------------------------
# lock build
# --------------------------------------------------------------------------

def build_lock(repo_root: Path) -> dict[str, Any]:
    """Build the byte-reproducible discovery lock from the P04 registration."""
    root = Path(repo_root)
    registration = _registration(root)
    preflight = run_preflight(root)
    if not preflight["ok"]:
        raise DiscoveryLockError(
            f"offline preflight failed: {', '.join(preflight['failed'])}")

    evidence_rows = [
        (AUDIT_PATH, "#200 frozen form audit (input evidence)"),
        (REGISTRATION_200_PATH, "#200 frozen draft registration (input evidence)"),
        (SCOPE_PATH, "P02 scope freeze (input evidence)"),
        (CENSUS_PATH, "P03 form census (input evidence)"),
        (REGISTRATION_PATH, "P04 discovery registration (locked by this record)"),
        (P04_DOC_PATH, "P04 design classification narrative"),
        (PLAN_PATH, "protocol: hypotheses and sequential research plan"),
    ]
    evidence_paths = [
        {"path": str(path), "role": role, "sha256": _sha256_file(root / path)}
        for path, role in evidence_rows
    ]

    document: dict[str, Any] = {
        "issue": ISSUE,
        "parent_issue": PARENT_ISSUE,
        "root_issue": ROOT_ISSUE,
        "task": "P05",
        "lock_version": LOCK_VERSION,
        "status": LOCK_STATUS,
        "protocol": PROTOCOL,
        "offline_only": True,
        "authorizes": "nothing beyond locking the reviewed offline discovery design; "
                      "no provider call, no collection, no live run",
        "locked_registration": {
            "path": str(REGISTRATION_PATH),
            "preregistration_version": registration.get("preregistration_version"),
            "registration_hash": registration.get("registration_hash"),
            "status_at_lock": registration.get("status"),
            "file_sha256": _sha256_file(root / REGISTRATION_PATH),
        },
        "offline_preflight": {
            "mode": preflight["mode"],
            "ok": preflight["ok"],
            "checks_run": preflight["checks_run"],
            "failed": preflight["failed"],
            "provider_calls": 0,
        },
        "preserved": {
            "frozen_200_artifacts": [
                {"path": str(AUDIT_PATH), "sha256": _sha256_file(root / AUDIT_PATH)},
                {"path": str(REGISTRATION_200_PATH),
                 "sha256": _sha256_file(root / REGISTRATION_200_PATH)},
            ],
            "k": K,
            "attainable_two_sided_sign_flip_floor": FLOOR,
            "classification": CLASSIFICATION,
            "descriptive_only": True,
            "fresh_seed_replication": "descriptive only; a fresh-seed replication block "
                                      "cannot become confirmatory on this family",
            "estimand": "equal-weight form mean of real-minus-placebo entropy",
            "h0": "Delta = 0",
            "h1": "Delta < 0",
            "guards_never_filter_the_estimate": True,
            "no_planning_low_effect_size_prior": True,
        },
        "authorization_scope": authorization_scope(registration),
        "authorization_reference": {
            "state": "pending_not_supplied",
            "reference": None,
            "recorded_at": None,
            "required_before": "any provider call, including the first discovery-collection "
                               "call and any exploratory replay call",
            "must_cover": AUTHORIZATION_MUST_COVER,
            "may_not_be_inferred_from": MAY_NOT_BE_INFERRED_FROM,
            "blocks": "#207 (P06) remains blocked until a separate explicit reference is "
                      "supplied and recorded",
        },
        "review": {
            "required": True,
            "independent": True,
            "record_path": REVIEW_PATH,
            "reviewed_against": [ISSUE, PROTOCOL],
            "completeness_rule": f"verify_lock fails unless the review record exists, names "
                                 f"this lock's lock_hash as reviewed_lock_hash, records "
                                 f"verdict '{APPROVED_REVIEW_STATUS}', and carries no "
                                 f"blocking findings",
        },
        "evidence_paths": evidence_paths,
    }
    document["lock_hash"] = _lock_hash(document)
    return document


def write_lock(document: Mapping[str, Any], *, repo_root: Path) -> Path:
    """Write the lock artifact; refuse to overwrite a differing artifact."""
    root = Path(repo_root)
    path = root / LOCK_PATH
    rendered = _render(document)
    if path.exists():
        if path.read_text(encoding="utf-8") != rendered:
            raise DiscoveryLockError(
                f"{LOCK_PATH} already exists with different content; a locked artifact "
                "is never overwritten")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

def verify_lock(document: Mapping[str, Any], *, repo_root: Path) -> dict[str, Any]:
    """Fail-closed verification: rebuild, re-hash, re-run preflight, review."""
    root = Path(repo_root)
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

    try:
        rebuilt = build_lock(root)
        check("lock_rebuilds_byte_for_byte", rebuilt == document, None)
        check("lock_file_is_byte_reproducible",
              (root / LOCK_PATH).read_text(encoding="utf-8") == _render(rebuilt), None)
    except (DiscoveryLockError, OSError, json.JSONDecodeError) as exc:
        check("lock_rebuilds_byte_for_byte", False, f"{type(exc).__name__}: {exc}")

    check("lock_version", document.get("lock_version") == LOCK_VERSION,
          document.get("lock_version"))
    check("lock_status", document.get("status") == LOCK_STATUS, document.get("status"))
    check("issue_identity",
          document.get("issue") == ISSUE and document.get("parent_issue") == PARENT_ISSUE
          and document.get("root_issue") == ROOT_ISSUE, None)
    check("lock_hash_recomputes",
          document.get("lock_hash") == _lock_hash(document), document.get("lock_hash"))

    locked = document.get("locked_registration") or {}
    check("registration_hash_pinned",
          locked.get("registration_hash") == P04_REGISTRATION_HASH,
          locked.get("registration_hash"))
    check("registration_file_sha256",
          locked.get("file_sha256") == _sha256_file(root / REGISTRATION_PATH),
          locked.get("file_sha256"))
    check("registration_status_at_lock_is_draft",
          locked.get("status_at_lock") == "draft_pending_review",
          locked.get("status_at_lock"))

    preflight = run_preflight(root)
    embedded = document.get("offline_preflight") or {}
    check("embedded_preflight_ok", embedded.get("ok") is True
          and embedded.get("failed") == [], embedded)
    check("embedded_preflight_matches_fresh",
          embedded.get("checks_run") == preflight.get("checks_run")
          and embedded.get("ok") == preflight.get("ok")
          and embedded.get("failed") == preflight.get("failed"),
          {"embedded": embedded.get("checks_run"), "fresh": preflight.get("checks_run")})
    check("preflight_provider_calls_zero",
          embedded.get("provider_calls") == 0
          and preflight.get("provider_calls") == 0, None)

    registration = _registration(root)
    check("registration_still_verifies_green",
          verify_registration(registration, repo_root=root).get("ok") is True, None)

    evidence = document.get("evidence_paths") or []
    check("evidence_paths_complete",
          {row.get("path") for row in evidence} == {
              str(AUDIT_PATH), str(REGISTRATION_200_PATH), str(SCOPE_PATH),
              str(CENSUS_PATH), str(REGISTRATION_PATH), P04_DOC_PATH, PLAN_PATH},
          sorted(row.get("path") for row in evidence))
    recompute_ok = True
    for row in evidence:
        target = root / str(row.get("path"))
        if not target.is_file() or _sha256_file(target) != row.get("sha256"):
            recompute_ok = False
    check("evidence_path_hashes_recompute", recompute_ok,
          [row.get("path") for row in evidence
           if not (root / str(row.get("path"))).is_file()
           or _sha256_file(root / str(row.get("path"))) != row.get("sha256")])
    check("evidence_includes_frozen_200",
          any(row.get("path") == str(AUDIT_PATH) for row in evidence)
          and any(row.get("path") == str(REGISTRATION_200_PATH) for row in evidence), None)

    preserved = document.get("preserved") or {}
    frozen = preserved.get("frozen_200_artifacts") or []
    check("frozen_200_artifacts_preserved",
          {row.get("path"): row.get("sha256") for row in frozen}
          == {str(AUDIT_PATH): _sha256_file(root / AUDIT_PATH),
              str(REGISTRATION_200_PATH): _sha256_file(root / REGISTRATION_200_PATH)}, None)
    check("k4_preserved", preserved.get("k") == K, preserved.get("k"))
    check("floor_preserved",
          preserved.get("attainable_two_sided_sign_flip_floor") == FLOOR,
          preserved.get("attainable_two_sided_sign_flip_floor"))
    check("classification_preserved", preserved.get("classification") == CLASSIFICATION,
          preserved.get("classification"))
    check("descriptive_only_preserved",
          preserved.get("descriptive_only") is True
          and "descriptive only" in str(preserved.get("fresh_seed_replication")), None)
    check("estimand_and_hypotheses_preserved",
          preserved.get("estimand")
          == "equal-weight form mean of real-minus-placebo entropy"
          and preserved.get("h0") == "Delta = 0"
          and preserved.get("h1") == "Delta < 0", None)
    check("guards_and_no_prior_preserved",
          preserved.get("guards_never_filter_the_estimate") is True
          and preserved.get("no_planning_low_effect_size_prior") is True, None)

    scope = document.get("authorization_scope") or {}
    check("scope_stage_matches_registration",
          scope.get("stage") == registration.get("stage"), scope.get("stage"))
    check("scope_route_matches_registration",
          scope.get("route") == registration.get("route"), None)
    check("scope_request_caps_match_registration",
          scope.get("request_caps") == authorization_scope(registration).get("request_caps"),
          None)
    check("scope_cost_caps_match_registration",
          scope.get("cost_caps") == authorization_scope(registration).get("cost_caps"), None)
    check("scope_stops_and_paths_match_registration",
          scope.get("stops") == registration.get("stops")
          and scope.get("paths") == registration.get("paths"), None)
    check("scope_program_ceiling_is_0_30",
          scope.get("cost_caps", {}).get("program_ceiling_usd") == 0.3, None)

    reference = document.get("authorization_reference") or {}
    check("authorization_reference_pending",
          reference.get("state") == "pending_not_supplied"
          and reference.get("reference") is None
          and reference.get("recorded_at") is None, reference)
    check("authorization_must_cover_exact_scope",
          reference.get("must_cover") == AUTHORIZATION_MUST_COVER,
          reference.get("must_cover"))
    check("authorization_not_inferable",
          reference.get("may_not_be_inferred_from") == MAY_NOT_BE_INFERRED_FROM, None)
    check("authorization_blocks_successor",
          "#207" in str(reference.get("blocks")), reference.get("blocks"))
    check("lock_is_not_authorization",
          document.get("offline_only") is True
          and "no provider call" in str(document.get("authorizes"))
          and "no live run" in str(document.get("authorizes")), document.get("authorizes"))

    lifecycle = (document.get("authorization_scope") or {}).get("path_lifecycle") or {}
    live_paths = [str(value) for key, value in
                  ((document.get("authorization_scope") or {}).get("paths") or {}).items()
                  if key != "registration"]
    check("live_paths_still_absent",
          not any((root / value).exists() for value in live_paths),
          sorted(value for value in live_paths if (root / value).exists()))
    check("path_lifecycle_fresh_only",
          lifecycle.get("resume") is False and lifecycle.get("append") is False
          and lifecycle.get("overwrite") is False, lifecycle)

    review_spec = document.get("review") or {}
    check("review_required_and_independent",
          review_spec.get("required") is True and review_spec.get("independent") is True
          and review_spec.get("record_path") == REVIEW_PATH, review_spec)
    check("reviewed_against_issue_and_protocol",
          review_spec.get("reviewed_against") == [ISSUE, PROTOCOL], review_spec)

    review_path = root / str(review_spec.get("record_path", REVIEW_PATH))
    if not review_path.is_file():
        check("review_record_exists", False, str(review_spec.get("record_path")))
        check("review_record_approved", False, "missing")
        check("review_record_matches_lock_hash", False, "missing")
        check("review_record_no_blocking_findings", False, "missing")
        check("review_record_covers_required_scope", False, "missing")
    else:
        record = _load_json(review_path)
        check("review_record_exists", True, str(review_spec.get("record_path")))
        check("review_record_version",
              record.get("review_version") == REVIEW_VERSION,
              record.get("review_version"))
        check("review_record_approved",
              record.get("verdict") == APPROVED_REVIEW_STATUS, record.get("verdict"))
        check("review_record_matches_lock_hash",
              record.get("reviewed_lock_hash") == document.get("lock_hash"),
              {"record": record.get("reviewed_lock_hash"),
               "lock": document.get("lock_hash")})
        findings = record.get("blocking_findings") or []
        check("review_record_no_blocking_findings", findings == [], findings)
        check("review_record_covers_required_scope",
              record.get("reviewed_against") == [ISSUE, PROTOCOL],
              record.get("reviewed_against"))

    return {"mode": f"{LOCK_VERSION}-verification", "ok": not errors,
            "errors": errors,
            "failed": [entry["check"] for entry in checks if not entry["ok"]],
            "checks": checks, "checks_run": len(checks),
            "lock_hash": document.get("lock_hash"),
            "status": document.get("status"),
            "authorization_reference_state": reference.get("state"),
            "provider_calls": 0}


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="P05 discovery lock (offline preflight, byte-reproducible lock, "
                    "fail-closed verification; zero provider calls)")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--preflight", action="store_true",
                        help="run only the offline preflight over the P04 inputs")
    parser.add_argument("--build", action="store_true",
                        help="write the lock artifact to its fresh path (never overwrites)")
    args = parser.parse_args(argv)
    root = Path(args.repo_root) if args.repo_root is not None else Path(
        __file__).resolve().parents[2]

    if args.preflight:
        preflight = run_preflight(root)
        print(json.dumps(preflight, indent=2, sort_keys=True, allow_nan=False))
        return 0 if preflight["ok"] else 2

    if args.build:
        try:
            document = build_lock(root)
            path = write_lock(document, repo_root=root)
        except DiscoveryLockError as exc:
            print(json.dumps({"mode": LOCK_VERSION, "status": "error", "error": str(exc),
                              "provider_calls": 0}, indent=2, sort_keys=True))
            return 2
        print(json.dumps({"mode": LOCK_VERSION, "status": LOCK_STATUS,
                          "path": str(path.relative_to(root)),
                          "lock_hash": document["lock_hash"],
                          "provider_calls": 0}, indent=2, sort_keys=True))
        return 0

    path = root / LOCK_PATH
    if not path.is_file():
        print(json.dumps({"mode": LOCK_VERSION, "status": "missing", "path": LOCK_PATH,
                          "provider_calls": 0}, indent=2, sort_keys=True))
        return 2
    document = _load_json(path)
    verification = verify_lock(document, repo_root=root)
    print(json.dumps(verification, indent=2, sort_keys=True, allow_nan=False))
    return 0 if verification["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "LOCK_VERSION", "REVIEW_VERSION", "LOCK_PATH", "REVIEW_PATH", "ISSUE",
    "PARENT_ISSUE", "ROOT_ISSUE", "PROTOCOL", "LOCK_STATUS",
    "PENDING_REVIEW_STATUS", "APPROVED_REVIEW_STATUS", "AUTHORIZATION_MUST_COVER",
    "MAY_NOT_BE_INFERRED_FROM", "P04_REGISTRATION_HASH", "K", "FLOOR",
    "CLASSIFICATION", "DiscoveryLockError", "run_preflight", "authorization_scope",
    "build_lock", "write_lock", "verify_lock", "main",
]
