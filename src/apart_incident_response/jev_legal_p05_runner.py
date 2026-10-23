"""L05 (#223): fail-closed runner and offline preflight for the legal family's
fresh discovery registration (L04, #222).

Offline by construction. This version is adapted from the stopped
hypothesis-family P06 runner only as a new legal module: the registered L04
artifact is consumed exactly, and any drift from the registered manifest,
treatment bytes, route pins, caps, stops or paths is refused before any call.

The live transport is never constructed until every release gate has passed:

1. the reviewed hash lock supplied by L06 (#224) exists at the registered
   lock path and pins this registration's version and hash,
2. a supplied, scope-bound authorization record (L07, #225, expected at the
   registered authorization-record path) is in ``authorized`` state with a
   reference that matches the record *and binds the record's scope digest*,
3. the preflight is green, output paths are fresh, and transport credentials
   are present.

Missing approval, drift, missing credentials or an output collision therefore
cause zero provider calls and no journal. A failed or stopped predecessor
never authorizes its successor; locking and review are not authorization.

Structure (both agents A and B on each of two turns) is the original L4X
communication bridge, re-derived per registered legal seed: four Ling writer
calls per seed, then one Jev Choice wire v2 final receiver A call per seed
(64 Ling + 16 Jev logical, retry-inclusive worst case 192 + 48 physical).
Structural need and form identity are derived from the deterministic
generator and the pre-read request; B-to-A ownership and A read-after-write
exposure are verified from real event evidence, never from transport-supplied
booleans. Seeds are never substituted, and the journal is never resumed,
appended, or overwritten: it is opened with ``"x"`` so an existing journal is
an output collision and the run refuses. Any stop keeps the whole registered
manifest as an immutable journal (one row per planned instance, in manifest
order, including failure and not-attempted rows).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from apart_incident_response import jev_legal_p04_registration as lp04
from apart_incident_response import jev_p06_discovery_runner as hyp_p06

RUNNER_VERSION = "jev-legal-p05-discovery-runner-v1"
PREFLIGHT_VERSION = "jev-legal-p05-discovery-preflight-v1"

# --------------------------------------------------------------------------
# registered L04 pins
# --------------------------------------------------------------------------

REGISTRATION_PATH = str(lp04.REGISTRATION_PATH)
REGISTRATION_VERSION = "jev-legal-p04-discovery-registration-v1"
REGISTRATION_HASH = "5f31630bae7fe414f054f78e1c4bb5ebf3b525d083cd3f91b81e1f89b427bde1"
REGISTRATION_STATUS = "draft_pending_review"

# Predecessor artifacts this version re-verifies offline.
L02_CENSUS_PATH = str(lp04.L02_CENSUS_PATH)
L03_DESIGN_PATH = str(lp04.L03_DESIGN_PATH)
L02_CENSUS_CONTENT_HASH = lp04.L02_CENSUS_CONTENT_HASH
L03_DESIGN_CONTENT_HASH = lp04.L03_DESIGN_CONTENT_HASH
L03_SCREEN_MANIFEST_HASH = "1eeda0eacc2d891e8117e2816c7a7bf2c65c3962c8e1fa102acdc4766deefb26"
TREATMENT_HASH = "413668459cf26ae7c78de0cb85f1b37fd538dda5082396ac09cfe163b4620e39"

# Release gates. The lock path is where L06 (#224) writes its reviewed hash
# lock; the authorization-record path is where L07 (#225) writes the separate,
# scope-bound user authorization record. Both are absent until those gates
# run, so this version fails closed today.
LOCK_PATH = "runs/next-phase/legal/jev-legal-p06-discovery-lock-v1.json"
LOCK_REVIEW_PATH = "runs/next-phase/legal/jev-legal-p06-discovery-lock-review-v1.json"
AUTH_PATH = "runs/next-phase/legal/jev-legal-discovery-authorization-record-v1.json"
LOCK_APPROVED_STATES = ("locked_pending_separate_live_authorization",)
AUTH_STATE_PENDING = "awaiting_explicit_reference"
AUTH_STATE_AUTHORIZED = "authorized"
AUTH_STATE_NO_RECORD = "no_record"
LOCK_STATE_PRESENT = "present"
LOCK_STATE_ABSENT = "absent"
MUST_COVER = ["stage", "route", "request_caps", "cost_caps"]
AUTHORIZATION_GATE_DOC = "docs/jev-discovery-authorization-gate.md"

# Versioned report of this L05 preflight (the deliverable named in #223).
PREFLIGHT_REPORT_PATH = "runs/next-phase/legal/jev-legal-p05-preflight-report-v1.json"

# Registered fixed-N discovery properties.
FAMILY = "legal"
COMPLEXITY = "low"
REGIME = "N"
BLOCK_N = 16
INSTANCES_PER_FORM = 4
FORM_COUNT = 4
STAGE = "legal:low discovery screen and optional exploratory replay"
DISCOVERY_WINDOW = (88000, 88511)
CLOSURE_PROBE_WINDOW = (89000, 89511)
HYPOTHESIS_SPAN_NEVER_REUSED = (85000, 87511)

# Registered route identity (pinned in the L04 registration).
LING_MODEL = "inclusionai/ling-3.0-flash-vl"
LING_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
LING_ROUTE_NOTE = "paid OpenRouter SKU (the free SKU is not routable)"
JEV_MODEL = "jev-1.13.0"
JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
JEV_CODEC_VERSION = "jev-choice-wire-v2"
NORMALIZATION_HARD_CEILING = 0.05

# Writer output policy (registered in L04: max_tokens 1024, truncation is a
# terminal writer error; no automatic continuation, escalation or repair).
WRITER_MAX_TOKENS = 1024

# Retry-inclusive semantics: one logical call may become 1 + max_retries 2
# physical attempts, so the reservation is checked before every call.
MAX_PHYSICAL_PER_CALL = 1 + 2

# Writer terminal outcomes that stop the run before the Jev receiver is
# called (the P06 terminal classes, carried by the L04 stop list).
WRITER_TERMINAL_OUTCOMES = hyp_p06.WRITER_TERMINAL_OUTCOMES

# Journal transport shared with the stopped hypothesis-family version: the
# append-only, "x"-opened, fsync-per-row structure is treatment-neutral.
DiscoveryJournal = hyp_p06.DiscoveryJournal
DiscoveryRunError = hyp_p06.DiscoveryRunError
DiscoveryTransport = hyp_p06.DiscoveryTransport


class LegalDiscoveryError(hyp_p06.DiscoveryRunError):
    """Fail-closed legal run, journal, gate or cap violation."""


def _digest(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def scope_digest(scope: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(scope, sort_keys=True).encode("utf-8")).hexdigest()


def lock_hash(lock: Mapping[str, Any]) -> str:
    """Hash a future L06 lock with the same serialization used by P05."""
    payload = {key: value for key, value in lock.items() if key != "lock_hash"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _load(root: Path, rel: str) -> dict[str, Any]:
    path = root / rel
    if not path.is_file():
        raise hyp_p06.DiscoveryRunError(f"missing artifact: {rel}")
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# exact scope-bound authorization
# --------------------------------------------------------------------------

def authorization_scope_for_registration(registration: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the exact authorization scope this registration permits.

    Any L07 record must carry this mapping (or one that provably matches it
    field-for-field) as its ``scope``; the record's ``scope_digest_sha256``
    must be the digest of this exact mapping, and the supplied human approval
    reference must embed that digest. Locking and review authorize nothing.
    """

    budgets = registration.get("budgets") or {}
    collection = budgets.get("discovery_collection") or {}
    replay = budgets.get("exploratory_replay") or {}
    program = budgets.get("program") or {}
    route = registration.get("route") or {}
    return {
        "authorization_gate": {"doc": AUTHORIZATION_GATE_DOC, "issue": "#225"},
        "cost_caps": {
            "discovery_collection_hard_cost_ceiling_usd":
                collection.get("hard_cost_ceiling_usd"),
            "exploratory_replay_hard_cost_ceiling_usd":
                replay.get("hard_cost_ceiling_usd"),
            "program_hard_cost_ceiling_usd": program.get("hard_cost_ceiling_usd"),
        },
        "fixed_n_manifest_hash": (registration.get("fixed_n") or {}).get("manifest_hash"),
        "fixed_n_planned_seeds": (registration.get("fixed_n") or {}).get("block_n"),
        "max_retries": {"jev": 2, "ling": 2},
        "must_cover": list(MUST_COVER),
        "program_physical_request_cap": (program.get("physical") or {}).get("combined"),
        "registration_hash": registration.get("registration_hash"),
        "registration_version": registration.get("preregistration_version"),
        "route": {
            "jev_codec_version": (route.get("jev") or {}).get("codec_version"),
            "jev_endpoint": (route.get("jev") or {}).get("endpoint"),
            "jev_max_retries": (route.get("jev") or {}).get("max_retries"),
            "jev_model": (route.get("jev") or {}).get("model"),
            "jev_protocol_key": (route.get("jev") or {}).get("protocol_key"),
            "jev_timeout_seconds": (route.get("jev") or {}).get("timeout_seconds"),
            "ling_endpoint": (route.get("ling") or {}).get("endpoint"),
            "ling_key_loader": (route.get("ling") or {}).get("key_loader"),
            "ling_max_retries": (route.get("ling") or {}).get("max_retries"),
            "ling_max_tokens": (route.get("ling") or {}).get("max_tokens"),
            "ling_min_attempt_interval_seconds":
                (route.get("ling") or {}).get("min_attempt_interval_seconds"),
            "ling_model": (route.get("ling") or {}).get("model"),
            "ling_route": (route.get("ling") or {}).get("route"),
            "normalization_hard_ceiling": (route.get("normalization") or {}).get(
                "hard_ceiling"),
            "normalization_policy_hash": (route.get("normalization") or {}).get(
                "policy_hash"),
        },
        "request_caps": {
            "discovery_collection_physical": collection.get("physical"),
            "discovery_collection_planned": collection.get("planned"),
            "exploratory_replay_physical": replay.get("physical"),
            "exploratory_replay_planned": replay.get("planned"),
        },
        "scope_digest_note":
            "the supplied authorization reference must embed this scope digest; "
            "locking or reviewing the registration is not authorization",
        "stage": registration.get("stage"),
    }


def scope_matches_registration(scope: Mapping[str, Any],
                               registration: Mapping[str, Any]) -> bool:
    """Whether a record's scope exactly equals the registered scope."""
    return scope == authorization_scope_for_registration(registration)


def reference_binds_scope_digest(reference: str, digest: str) -> bool:
    """Whether the supplied reference itself embeds the scope digest hex."""
    return bool(digest) and digest in reference


def evaluate_release_gates(lock: Mapping[str, Any] | None,
                           auth: Mapping[str, Any] | None,
                           approval: str | None,
                           registration: Mapping[str, Any],
                           lock_review: Mapping[str, Any] | None = None
                           ) -> tuple[str | None, str, str]:
    """Evaluate the L06 lock and L07 authorization gates, fail closed.

    Returns ``(stop_reason, lock_state, authorization_state)``. A missing lock
    file or missing/pending authorization record is a stop *before* any call;
    a supplied approval must match the record's reference and bind the record's
    scope digest.
    """

    registration_hash = registration.get("registration_hash")
    registration_version = registration.get("preregistration_version")
    lock_state = LOCK_STATE_ABSENT
    if isinstance(lock, Mapping):
        lock_state = LOCK_STATE_PRESENT
        if lock.get("registration_hash") != registration_hash:
            return "lock_registration_hash_drift", lock_state, AUTH_STATE_NO_RECORD
        if lock.get("preregistration_version") != registration_version:
            return "lock_registration_version_drift", lock_state, AUTH_STATE_NO_RECORD
        if lock.get("status") not in LOCK_APPROVED_STATES:
            return "lock_status_not_reviewed", lock_state, AUTH_STATE_NO_RECORD
        if lock.get("lock_hash") != lock_hash(lock):
            return "lock_hash_mismatch", lock_state, AUTH_STATE_NO_RECORD
    else:
        # Nothing is authorized without the L06 reviewed hash lock.
        return "lock_pending_l06", LOCK_STATE_ABSENT, AUTH_STATE_NO_RECORD

    lock_scope = lock.get("authorization_scope")
    if not isinstance(lock_scope, Mapping) or not lock_scope:
        return "lock_authorization_scope_missing", lock_state, AUTH_STATE_NO_RECORD
    if not scope_matches_registration(lock_scope, registration):
        return "lock_authorization_scope_drift", lock_state, AUTH_STATE_NO_RECORD
    review_spec = lock.get("review") or {}
    if (review_spec.get("required") is not True
            or review_spec.get("independent") is not True
            or review_spec.get("record_path") != LOCK_REVIEW_PATH):
        return "lock_review_contract_missing", lock_state, AUTH_STATE_NO_RECORD
    if not isinstance(lock_review, Mapping):
        return "lock_review_pending_l06", lock_state, AUTH_STATE_NO_RECORD
    if (lock_review.get("verdict") != "approved"
            or lock_review.get("reviewed_lock_hash") != lock.get("lock_hash")
            or lock_review.get("blocking_findings") != []):
        return "lock_review_not_approved_for_hash", lock_state, AUTH_STATE_NO_RECORD

    authorization_state = AUTH_STATE_NO_RECORD
    if not isinstance(auth, Mapping):
        return "authorization_pending", lock_state, authorization_state
    authorization_state = str(auth.get("state", AUTH_STATE_NO_RECORD))
    if authorization_state != AUTH_STATE_AUTHORIZED:
        return "authorization_pending", lock_state, authorization_state
    if auth.get("authorized") is not True:
        return "authorization_flag_not_set", lock_state, authorization_state
    reference = auth.get("reference")
    if not isinstance(reference, str) or not reference.strip():
        return "authorization_reference_missing", lock_state, authorization_state
    for field in ("supplied_by", "supplied_at", "decision"):
        if not isinstance(auth.get(field), str) or not str(auth.get(field)).strip():
            return f"authorization_{field}_missing", lock_state, authorization_state
    if auth.get("scope") != dict(lock_scope):
        return "authorization_scope_drift_from_lock", lock_state, authorization_state
    if not scope_matches_registration(dict(auth["scope"]), registration):
        return "authorization_scope_out_of_registered_scope", lock_state, authorization_state
    expected_digest = auth.get("scope_digest_sha256")
    if not isinstance(expected_digest, str) or scope_digest(dict(auth["scope"])) != expected_digest:
        return "scope_digest_mismatch", lock_state, authorization_state
    if auth.get("must_cover") != list(MUST_COVER):
        return "authorization_must_cover_drift", lock_state, authorization_state
    if auth.get("locking_is_not_authorization") is not True:
        return "authorization_non_inference_flags_missing", lock_state, authorization_state
    if approval is None or not approval.strip():
        return "approval_reference_not_supplied", lock_state, authorization_state
    if not isinstance(reference, str) or approval.strip() != reference.strip():
        return "approval_reference_mismatch", lock_state, authorization_state
    if not reference_binds_scope_digest(approval.strip(), expected_digest):
        return ("approval_reference_does_not_bind_scope_digest", lock_state,
                authorization_state)
    return None, lock_state, authorization_state


def _blocked(reason: str, *, authorization_state: str = AUTH_STATE_NO_RECORD,
             lock_state: str = LOCK_STATE_ABSENT,
             extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mode": RUNNER_VERSION,
        "status": "blocked",
        "stop_reason": reason,
        "authorization_state": authorization_state,
        "lock_state": lock_state,
        "planned_seeds": BLOCK_N,
        "provider_calls": 0,
        "credentials_retained": False,
    }
    payload.update(dict(extra or {}))
    return payload


# --------------------------------------------------------------------------
# registered-field validation (offline, mutatable for drift fixtures)
# --------------------------------------------------------------------------

def validate_registration_fields(registration: Mapping[str, Any]) -> list[str]:
    """Validate L04 registration fields independent of the on-disk bytes.

    Returns the list of failed check names; empty means every field matches
    the registered pins. Recomputation is offline: manifest identity, form
    membership and treatment bytes are re-derived from the deterministic
    generator and from the pinned predecessor artifacts' recorded values.
    """

    failures: list[str] = []

    def fail(name: str) -> None:
        if name not in failures:
            failures.append(name)

    fixed_n = registration.get("fixed_n") or {}
    manifest = fixed_n.get("manifest") or []
    if (fixed_n.get("block_n") != BLOCK_N or len(manifest) != BLOCK_N
            or fixed_n.get("instances_per_form") != INSTANCES_PER_FORM
            or fixed_n.get("form_count") != FORM_COUNT):
        fail("manifest_is_16_fixed_seeds")
    if fixed_n.get("window") != {"base": DISCOVERY_WINDOW[0], "role": "discovery",
                                 "end": DISCOVERY_WINDOW[1],
                                 "window": DISCOVERY_WINDOW[1] - DISCOVERY_WINDOW[0] + 1}:
        fail("manifest_window_matches_registered_discovery_window")
    if fixed_n.get("closure_probe_window") != list(CLOSURE_PROBE_WINDOW) or \
            fixed_n.get("closure_probe_window_unselectable") is not True:
        fail("closure_probe_window_unselectable")
    if fixed_n.get("consulted_outcomes") != [] or fixed_n.get("outcome_blind") is not True:
        fail("manifest_selection_is_outcome_blind")
    if (fixed_n.get("held_out_window") or {}).get("registered_here") is not False:
        fail("held_out_window_not_registered")
    if (fixed_n.get("spare_capacity_note") or "") == "":
        fail("spare_capacity_note_present")
    if fixed_n.get("manifest_hash") != L03_SCREEN_MANIFEST_HASH:
        fail("manifest_hash_matches_registered_pin")
    if fixed_n.get("l03_screen_manifest_hash") != L03_SCREEN_MANIFEST_HASH:
        fail("manifest_matches_l03_screen")

    # Manifest composition: per-form ascending seeds inside the discovery
    # window; the closure-probe and hypothesis spans are never selectable.
    per_form: dict[str, list[int]] = {}
    ids_seen: set[str] = set()
    for entry in manifest:
        if not isinstance(entry, Mapping):
            fail("manifest_entries_wellformed")
            continue
        seed = entry.get("seed")
        form = entry.get("prompt_form_id")
        instance_id = entry.get("instance_id")
        if not isinstance(seed, int) or not isinstance(form, str) or not isinstance(instance_id, str):
            fail("manifest_entries_wellformed")
            continue
        ids_seen.add(instance_id)
        if not (DISCOVERY_WINDOW[0] <= seed <= DISCOVERY_WINDOW[1]):
            fail("manifest_seeds_inside_discovery_window")
        if (CLOSURE_PROBE_WINDOW[0] <= seed <= CLOSURE_PROBE_WINDOW[1]
                or HYPOTHESIS_SPAN_NEVER_REUSED[0] <= seed <= HYPOTHESIS_SPAN_NEVER_REUSED[1]):
            fail("manifest_seeds_never_reuse_prior_or_probe_windows")
        per_form.setdefault(form, []).append(seed)
    if len(ids_seen) != len(manifest):
        fail("manifest_instance_ids_unique")
    if len(per_form) != FORM_COUNT or any(
            len(seeds) != INSTANCES_PER_FORM or seeds != sorted(seeds)
            for seeds in per_form.values()):
        fail("manifest_has_four_ascending_seeds_per_form")

    # Census/manifest IDs: regenerate each seed and compare the deterministic
    # instance id and pre-read form id against the registered row.
    registration_form_ids = {entry.get("prompt_form_id") for entry in manifest
                             if isinstance(entry, Mapping)}
    try:
        from apart_incident_response import jev_replication_preregistration as rep
        for entry in manifest:
            if not isinstance(entry, Mapping):
                continue
            instance = rep.instance_for(FAMILY, int(entry["seed"]))
            if instance.instance_id != entry.get("instance_id") or \
                    rep.pre_read_form_id(instance) != entry.get("prompt_form_id"):
                fail("manifest_ids_recompute_from_the_generator")
                break
    except Exception:  # noqa: BLE001 - fail closed on any generator failure
        fail("manifest_ids_recompute_from_the_generator")

    expected_membership: dict[str, list[str]] = {}
    for entry in manifest:
        if isinstance(entry, Mapping):
            expected_membership.setdefault(entry.get("prompt_form_id"), []).append(
                entry.get("instance_id"))
    membership = fixed_n.get("form_membership") or {}
    normalized = {form: sorted(ids) for form, ids in sorted(membership.items())}
    if normalized != {form: sorted(ids) for form, ids in sorted(expected_membership.items())}:
        fail("form_membership_matches_manifest")
    if registration_form_ids and set(membership) != registration_form_ids:
        fail("form_membership_covers_every_registered_form")

    # Route pins.
    route = registration.get("route") or {}
    ling = route.get("ling") or {}
    jev = route.get("jev") or {}
    norm = route.get("normalization") or {}
    if (ling.get("model") != LING_MODEL or ling.get("endpoint") != LING_ENDPOINT
            or ling.get("route") != LING_ROUTE_NOTE
            or ling.get("key_loader") != "behavioral_discovery._api_key"
            or ling.get("max_retries") != 2
            or ling.get("min_attempt_interval_seconds") != 3.25
            or ling.get("max_tokens") != WRITER_MAX_TOKENS
            or ling.get("temperature") != 0.0):
        fail("route_ling_registered_pins_match")
    if (jev.get("model") != JEV_MODEL or jev.get("endpoint") != JEV_ENDPOINT
            or jev.get("codec_version") != JEV_CODEC_VERSION
            or jev.get("max_retries") != 2
            or jev.get("timeout_seconds") != 30.0
            or jev.get("backoff") != {"initial_seconds": 0.5, "jitter": 0.25,
                                      "max_seconds": 5.0}
            or jev.get("retryable_statuses") != [408, 429, 500, 502, 503, 504, 529]):
        fail("route_jev_registered_pins_match")
    if (norm.get("hard_ceiling") != NORMALIZATION_HARD_CEILING):
        fail("route_normalization_hard_ceiling_matches")
    try:
        from apart_incident_response import jev_replay_preregistration_v4 as prv4
        from apart_incident_response import jev_replay_preregistration_v2 as prv2
        if (route.get("jev") or {}).get("protocol_key") != prv4.prv6_protocol_key():
            fail("route_jev_protocol_key_recomputes")
        if norm.get("policy_hash") != prv2.normalization_policy_hash():
            fail("route_normalization_policy_hash_recomputes")
    except Exception:  # noqa: BLE001 - fail closed
        fail("route_protocol_and_normalization_pins_recompute")

    # Treatment bytes: mode, rung, structure and the registered treatment
    # hash recomputed from manifest + census geometry.
    treatment = registration.get("treatment") or {}
    if (treatment.get("mode") != "exact-original-comm-bridge"
            or treatment.get("rung") != "L4X" or treatment.get("turns") != 2
            or treatment.get("agents") != ["A", "B"]
            or treatment.get("family") != FAMILY
            or treatment.get("complexity") != COMPLEXITY
            or treatment.get("regime") != REGIME
            or treatment.get("primary_direction") != "one-way B->A"):
        fail("treatment_l4x_bytes_match")
    writer_prompt = treatment.get("writer_prompt") or {}
    writer_transport = treatment.get("writer_transport") or {}
    if (writer_prompt.get("max_tokens") != WRITER_MAX_TOKENS
            or writer_prompt.get("temperature") != 0.0
            or writer_transport.get("token_budget") != WRITER_MAX_TOKENS
            or writer_transport.get("temperature") != 0.0):
        fail("writer_output_policy_max_tokens_1024")
    if treatment.get("treatment_hash") != TREATMENT_HASH:
        fail("treatment_hash_matches_registered_pin")
    try:
        recomputed_manifest_treatment = lp04.legal_manifest_treatment_hash(manifest)
        census_document = registration.get("_validation_census_document")
        # An empty mapping is not a real census: fail closed.
        if isinstance(census_document, Mapping) and census_document.get("form_records"):
            geometry = lp04.information_geometry_hash(census_document)
            recomputed = lp04.legal_treatment_hash(
                treatment, recomputed_manifest_treatment, geometry)
            if recomputed != TREATMENT_HASH or recomputed != treatment.get("treatment_hash"):
                fail("treatment_hash_recomputes_from_manifest_and_geometry")
            if recomputed_manifest_treatment != treatment.get("manifest_treatment_hash"):
                fail("manifest_treatment_hash_recomputes")
            if geometry != treatment.get("information_geometry_hash"):
                fail("information_geometry_hash_recomputes_from_census")
        else:
            fail("census_document_supplied_for_geometry_recompute")
    except Exception:  # noqa: BLE001 - fail closed
        fail("treatment_hash_recomputes_from_manifest_and_geometry")

    # Budgets, request caps and retry reserves.
    budgets = registration.get("budgets") or {}
    collection = budgets.get("discovery_collection") or {}
    replay = budgets.get("exploratory_replay") or {}
    program = budgets.get("program") or {}
    cost_model = budgets.get("cost_model") or {}
    if (collection.get("planned") != {"combined": 80, "receiver": 16, "writer": 64}
            or collection.get("physical") != {"combined": 240, "receiver": 48,
                                              "writer": 192}):
        fail("collection_request_caps_match_registered")
    if (replay.get("planned") != {"combined": 48, "jev": 48, "writer": 0}
            or replay.get("physical") != {"combined": 144, "jev": 144, "writer": 0}):
        fail("replay_request_caps_match_registered")
    if (program.get("planned") != {"combined": 128, "jev": 64, "writer": 64}
            or program.get("physical") != {"combined": 384, "jev": 192, "writer": 192}):
        fail("program_request_caps_match_registered")
    if collection.get("hard_cost_ceiling_usd") != 0.2 \
            or replay.get("hard_cost_ceiling_usd") != 0.1 \
            or program.get("hard_cost_ceiling_usd") != 0.3:
        fail("hard_cost_ceilings_match_registered")
    if collection.get("next_call_reservation_usd") != {"jev": 0.001032192,
                                                       "ling": 0.00202752}:
        fail("next_call_retry_reservations_match_registered")
    try:
        if (abs(collection.get("worst_case_cost_usd", -1) - 0.146276352) > 1e-12
                or abs(replay.get("worst_case_cost_usd", -1) - 0.049545216) > 1e-12
                or abs(program.get("worst_case_cost_usd", -1) - 0.195821568) > 1e-12):
            fail("budget_worst_case_arithmetic_matches_registered")
    except TypeError:
        fail("budget_worst_case_arithmetic_matches_registered")
    if (int(cost_model.get("ling_input_token_ceiling", 0)) != 8192
            or int(cost_model.get("ling_output_token_ceiling", 0)) != WRITER_MAX_TOKENS
            or int(cost_model.get("jev_input_token_ceiling", 0)) != 8192
            or float(cost_model.get("ling_prompt_usd_per_mtok", -1)) != 0.06
            or float(cost_model.get("ling_completion_usd_per_mtok", -1)) != 0.18
            or float(cost_model.get("jev_input_usd_per_mtok", -1)) != 0.042
            or float(cost_model.get("ling_worst_physical_call_usd", -1)) != 0.00067584
            or float(cost_model.get("jev_worst_physical_call_usd", -1)) != 0.000344064):
        fail("cost_model_matches_registered_rate_card")

    request_caps = registration.get("request_caps") or {}
    if (request_caps.get("max_retries") != {"jev": 2, "ling": 2}
            or MAX_PHYSICAL_PER_CALL != 3):
        fail("retry_inclusive_semantics_match_registered")

    # Stops, paths and lifecycle.
    stops = registration.get("stops") or []
    if len(stops) < 10 or not any("output collision" in str(s) for s in stops) \
            or not any("cost cap" in str(s) for s in stops) \
            or not any("truncated_output" in str(s) for s in stops) \
            or not any("429" in str(s) or "rate-limited" in str(s) for s in stops):
        fail("terminal_stops_carry_the_l03_stop_list")

    paths = registration.get("paths") or {}
    live = sorted(str(value) for key, value in paths.items() if key != "registration")
    if (len(live) != 4
            or {key for key in paths if key != "registration"} != {
                "discovery_journal", "discovery_report",
                "exploratory_replay_journal", "exploratory_replay_report"}):
        fail("registered_live_output_paths_present")
    if not all(value.startswith("runs/next-phase/legal/") for value in live):
        fail("registered_live_paths_scoped_to_legal_namespace")
    lifecycle = registration.get("path_lifecycle") or {}
    if (lifecycle.get("resume") is not False or lifecycle.get("append") is not False
            or lifecycle.get("overwrite") is not False
            or lifecycle.get("path_overrides") is not False):
        fail("path_lifecycle_forbids_resume_append_overwrite")

    # Authorization block: everything pending, nothing inferred.
    authorization = registration.get("authorization") or {}
    if (authorization.get("authorization_status") != "pending"
            or authorization.get("route_authorized") is not False
            or authorization.get("locking_is_not_authorization") is not True
            or authorization.get("approval_may_not_be_inferred_from_locking") is not True
            or authorization.get("approval_may_not_be_inferred_from_predecessor_closure")
            is not True
            or authorization.get("failed_predecessor_never_authorizes_successor")
            is not True
            or (authorization.get("l07_gate") or {}).get("issue") != "#225"):
        fail("authorization_block_is_fully_pending")

    # Status, hash and version self-consistency (hash itself is verified
    # against the on-disk bytes in the preflight).
    if registration.get("preregistration_version") != REGISTRATION_VERSION:
        fail("registration_version_matches_pin")
    if registration.get("status") != REGISTRATION_STATUS:
        fail("registration_status_is_draft_pending_review")
    if registration.get("registration_hash") != REGISTRATION_HASH:
        fail("registration_hash_matches_pin")
    if (registration.get("design_classification") or {}).get("decision_from_l03") \
            != "descriptive_discovery":
        fail("classification_carries_l03_descriptive_decision")
    if (registration.get("design_classification") or {}).get(
            "attainable_two_sided_sign_flip_floor") not in ("0.125", 0.125):
        fail("descriptive_floor_0_125_preserved")
    return failures


# --------------------------------------------------------------------------
# preflight
# --------------------------------------------------------------------------

def _fresh_live_output_paths(root: Path, registration: Mapping[str, Any]) -> tuple[bool, list[str]]:
    paths = registration.get("paths") or {}
    live = [str(value) for key, value in paths.items()
            if key != "registration" and isinstance(value, str)]
    return (not any((root / value).exists() for value in live), live)


def run_preflight(repo_root: Path, *, approval: str | None = None) -> dict[str, Any]:
    """Fail-closed offline preflight. Makes no provider call, ever.

    A process audit hook records socket/http/urllib/ftp events for the whole
    preflight window and the report asserts zero of them. The release-gate
    state is *reported*: a green preflight with ``authorized`` false still
    permits no call; the runner re-evaluates the gates itself.
    """

    root = Path(repo_root)
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        if any(entry["check"] == name for entry in checks):
            return
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

    # ---- zero-network audit window covers every load and every recompute
    events: list[str] = []
    active = {"on": True}

    def audit_hook(event: str, args: Any) -> None:
        if not active["on"]:
            return
        if event.startswith("socket.") or event.startswith("urllib.") \
                or event.startswith("http.client.") or event.startswith("ftplib."):
            events.append(event)
            raise LegalDiscoveryError(f"network event forbidden in offline preflight: {event}")

    auth: Mapping[str, Any] | None = None
    lock: Mapping[str, Any] | None = None
    lock_review: Mapping[str, Any] | None = None
    sys.addaudithook(audit_hook)
    try:
        try:
            registration = _load(root, REGISTRATION_PATH)
            check("registration_loads", True, None)
        except (hyp_p06.DiscoveryRunError, OSError, json.JSONDecodeError,
                KeyError, AttributeError, ValueError, TypeError) as exc:
            registration = {}
            check("registration_loads", False, f"{type(exc).__name__}: {exc}")
        if registration:
            _preflight_body(root, registration, check)
            if (root / LOCK_PATH).is_file():
                try:
                    lock = _load(root, LOCK_PATH)
                except (OSError, json.JSONDecodeError) as exc:
                    check("lock_record_loads", False, f"{type(exc).__name__}: {exc}")
                else:
                    check("lock_record_loads", True, None)
            if (root / AUTH_PATH).is_file():
                try:
                    auth = _load(root, AUTH_PATH)
                except (OSError, json.JSONDecodeError) as exc:
                    check("authorization_record_loads", False,
                          f"{type(exc).__name__}: {exc}")
                else:
                    check("authorization_record_loads", True, None)
            if (root / LOCK_REVIEW_PATH).is_file():
                try:
                    lock_review = _load(root, LOCK_REVIEW_PATH)
                except (OSError, json.JSONDecodeError) as exc:
                    check("lock_review_record_loads", False,
                          f"{type(exc).__name__}: {exc}")
                else:
                    check("lock_review_record_loads", True, None)
            try:
                expected_scope = authorization_scope_for_registration(registration)
            except Exception:  # noqa: BLE001 - fail closed
                expected_scope = {}
            check("expected_authorization_scope_derivable",
                  bool(expected_scope.get("registration_hash")), None)
    finally:
        active["on"] = False
    check("zero_network_events", not events, {"events": events})
    check("provider_calls_zero", True, {"provider_calls": 0})

    try:
        stop, lock_state, auth_state = evaluate_release_gates(
            lock, auth, approval, {}, lock_review)
    except Exception:  # noqa: BLE001 - fail closed
        stop, lock_state, auth_state = ("release_gate_evaluation_failed",
                                        LOCK_STATE_ABSENT, AUTH_STATE_NO_RECORD)
    # Re-evaluate against the real registration when it loaded.
    if registration:
        try:
            stop, lock_state, auth_state = evaluate_release_gates(
                lock, auth, approval, registration, lock_review)
        except Exception:  # noqa: BLE001 - fail closed
            stop, lock_state, auth_state = ("release_gate_evaluation_failed",
                                            LOCK_STATE_ABSENT, AUTH_STATE_NO_RECORD)

    return {
        "mode": PREFLIGHT_VERSION,
        "ok": not errors,
        "errors": errors,
        "failed": [entry["check"] for entry in checks if not entry["ok"]],
        "checks": checks,
        "checks_run": len(checks),
        "authorization_state": auth_state,
        "lock_state": lock_state,
        "authorized": stop is None,
        "release_gate_stop_reason": stop,
        "expected_authorization_scope":
            authorization_scope_for_registration(registration) if registration else {},
        "expected_authorization_scope_digest":
            scope_digest(authorization_scope_for_registration(registration))
            if registration else "",
        "registration_hash": REGISTRATION_HASH,
        "registration_version": REGISTRATION_VERSION,
        "lock_path": LOCK_PATH,
        "lock_review_path": LOCK_REVIEW_PATH,
        "authorization_record_path": AUTH_PATH,
        "planned_seeds": BLOCK_N,
        "network_audit": {
            "events": len(events),
            "event_names": events,
            "hook": "sys.addaudithook(socket., urllib., http.client., ftplib.)",
            "provider_calls": 0,
        },
        "provider_calls": 0,
        "status": "offline",
    }


def _preflight_body(root: Path, registration: Mapping[str, Any],
                    check: Callable[..., None]) -> None:
    """All on-disk checks against a loaded registration."""

    try:
        registration = _load(root, REGISTRATION_PATH)
    except (hyp_p06.DiscoveryRunError, OSError, json.JSONDecodeError) as exc:
        check("registration_loads", False, f"{type(exc).__name__}: {exc}")
        return
    check("registration_hash_pin",
          registration.get("registration_hash") == REGISTRATION_HASH,
          registration.get("registration_hash"))
    check("registration_version_pin",
          registration.get("preregistration_version") == REGISTRATION_VERSION,
          registration.get("preregistration_version"))
    check("registration_status_draft_pending_review",
          registration.get("status") == REGISTRATION_STATUS,
          registration.get("status"))
    try:
        from apart_incident_response.jev_legal_p04_registration import (
            _content_hash as lp04_content_hash,  # noqa: PLC0415
        )
        expected = lp04_content_hash(registration, hash_key="registration_hash")
        check("registration_hash_recomputes_from_bytes",
              registration.get("registration_hash") == expected, expected)
    except Exception as exc:  # noqa: BLE001 - fail closed
        check("registration_hash_recomputes_from_bytes", False,
              f"{type(exc).__name__}: {exc}")
    try:
        verification = lp04.verify_registration(registration, repo_root=root)
        check("registration_verifies_green", verification.get("ok") is True,
              verification.get("failed"))
    except Exception as exc:  # noqa: BLE001 - fail closed
        check("registration_verifies_green", False, f"{type(exc).__name__}: {exc}")

    # Predecessor artifacts re-verified from disk with their recorded pins.
    frozen_paths = [
        L02_CENSUS_PATH, L03_DESIGN_PATH,
        "runs/epic-126/replication/jev-replication-form-audit-v1.json",
        "runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection.jsonl",
        "runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection-report.json",
        "runs/next-phase/jev-p04-discovery-registration-v1.json",
        "runs/next-phase/jev-discovery-authorization-record-v1.json",
    ]
    evidence = registration.get("input_evidence") or {}
    expected_by_path = {entry["path"]: entry["sha256"]
                        for entry in evidence.get("frozen_inputs", [])}
    for rel in frozen_paths:
        expected = expected_by_path.get(rel)
        try:
            actual = _sha256_file(root / rel) if expected else None
        except OSError:
            actual = None
        check("predecessor_artifact_byte_identical:" + rel,
              expected is not None and actual == expected, actual)

    # Census and design pins.
    try:
        census_document = _load(root, L02_CENSUS_PATH)
        from apart_incident_response.jev_legal_p04_registration import (
            _content_hash,  # noqa: PLC0415
        )
        check("l02_census_content_hash_recomputes",
              _content_hash(census_document, hash_key="content_hash")
              == L02_CENSUS_CONTENT_HASH, L02_CENSUS_CONTENT_HASH)
    except Exception as exc:  # noqa: BLE001 - fail closed
        census_document = {}
        check("l02_census_content_hash_recomputes", False,
              f"{type(exc).__name__}: {exc}")
    try:
        design3 = _load(root, L03_DESIGN_PATH)
        from apart_incident_response.jev_legal_p04_registration import (
            _content_hash,  # noqa: PLC0415
        )
        check("l03_design_content_hash_recomputes",
              _content_hash(design3, hash_key="content_hash") == L03_DESIGN_CONTENT_HASH,
              L03_DESIGN_CONTENT_HASH)
        check("l03_decision_is_descriptive_k4",
              (design3.get("classification") or {}).get("decision")
              == "descriptive_discovery", (design3.get("classification") or {}).get("decision"))
        check("l03_screen_manifest_matches_registration",
              (design3.get("discovery_screen") or {}).get("manifest_hash")
              == L03_SCREEN_MANIFEST_HASH
              and (registration.get("fixed_n") or {}).get("manifest_hash")
              == L03_SCREEN_MANIFEST_HASH, None)
    except Exception as exc:  # noqa: BLE001 - fail closed
        design3 = {}
        check("l03_design_content_hash_recomputes", False,
              f"{type(exc).__name__}: {exc}")
        check("l03_decision_is_descriptive_k4", False, "design artifact missing")

    # Registered-field validation (pure; mutatable in fixtures).
    snapshot = json.loads(json.dumps(dict(registration), sort_keys=True))
    snapshot["_validation_census_document"] = census_document
    try:
        field_failures = validate_registration_fields(snapshot)
    except Exception as exc:  # noqa: BLE001 - malformed registration fails closed
        field_failures = [f"{type(exc).__name__}: {exc}"]
    check("registered_fields_validate", not field_failures, field_failures)

    # Fresh registered live output paths.
    fresh, live = _fresh_live_output_paths(root, registration)
    check("registered_live_output_paths_absent", fresh, live)
    check("registered_paths_count", len(live) == 4,
          {"registration": registration.get("registration_path"), "live": live})

    # The L05 preflight report path is fresh or byte-identical (never overwritten).
    report_file = root / PREFLIGHT_REPORT_PATH
    if report_file.exists():
        recheck = None
        try:
            preflight_blueprint = _report_blueprint(root, registration)
            recheck = root / PREFLIGHT_REPORT_PATH
            same = json.loads(recheck.read_text(encoding="utf-8")) == preflight_blueprint
        except Exception:  # noqa: BLE001 - fail closed
            same = False
        check("preflight_report_path_not_colliding", same, str(recheck))
    else:
        check("preflight_report_path_not_colliding", True, str(report_file))

    # Release gates are *reported* here, not passed: the lock and the
    # authorization record were loaded by run_preflight and are evaluated
    # there; this preflight is green today with authorized=False until L06
    # (#224) and L07 (#225) supply their records.
    return None


def _report_blueprint(root: Path, registration: Mapping[str, Any]) -> dict[str, Any]:
    """The deterministic report body ``main`` writes (or verifies) on disk.

    Computed without re-running the full preflight: fixed self-description of
    this version plus the release-gate status observed on this repo.
    """

    fresh, _ = _fresh_live_output_paths(root, registration)
    return {
        "mode": PREFLIGHT_VERSION,
        "registration_hash": REGISTRATION_HASH,
        "registration_version": REGISTRATION_VERSION,
        "lock_path": LOCK_PATH,
        "lock_review_path": LOCK_REVIEW_PATH,
        "authorization_record_path": AUTH_PATH,
        "planned_seeds": BLOCK_N,
        "registered_live_paths_absent": fresh,
        "status": "offline",
        "provider_calls": 0,
        "network_events": 0,
        "handoff": "L06 (#224): independent registration/runner review and hash lock; "
                   "L07 (#225) supplies the separate scope-bound user authorization",
    }


# --------------------------------------------------------------------------
# legal transport (constructed only after every release gate has passed)
# --------------------------------------------------------------------------

def _build_live_clients(registration: Mapping[str, Any]) -> tuple[Any, Any]:
    from apart_incident_response import jev_choice as jc
    from apart_incident_response import jev_ling_writer_v5 as ling_v5
    physical = (registration.get("request_caps") or {}).get(
        "discovery_collection", {}).get("physical", {})
    ling = ling_v5.LingWriterClientV5(
        model=LING_MODEL, endpoint=LING_ENDPOINT, max_retries=2,
        max_physical_requests=int(physical.get("writer", 0)),
        min_attempt_interval_seconds=3.25)
    jev = jc.JevChoiceClient(
        endpoint=JEV_ENDPOINT, model=JEV_MODEL, timeout=30.0,
        max_retries=2, max_physical_requests=int(physical.get("receiver", 0)),
        backoff_initial=0.5, backoff_max=5.0, backoff_jitter=0.25)
    return ling, jev


class ConfiguredLegalDiscoveryTransport(hyp_p06.DiscoveryTransport):
    """Paid OpenRouter writer plus Jev Choice v2 transport for the legal route.

    Only the live path constructs this class, and only after the lock,
    authorization, preflight and output-freshness gates have passed. No
    endpoint/model overrides or route fallbacks are accepted.
    """

    is_configured = True

    def __init__(self, registration: Mapping[str, Any], *,
                 ling_client: Any = None, jev_client: Any = None) -> None:
        from apart_incident_response import jev_choice_v2 as jc2
        from apart_incident_response import jev_replay_preregistration_v4 as prv4
        from apart_incident_response import jev_replay_preregistration_v2 as prv2

        route = registration.get("route") or {}
        ling_route = route.get("ling") or {}
        jev_route = route.get("jev") or {}
        norm = route.get("normalization") or {}
        treatment = registration.get("treatment") or {}
        writer_contract = treatment.get("writer_transport") or {}
        writer_prompt = treatment.get("writer_prompt") or {}
        budgets = registration.get("budgets") or {}
        collection = budgets.get("discovery_collection") or {}
        cost_model = budgets.get("cost_model") or {}
        request_caps = registration.get("request_caps") or {}
        expected_protocol_key = prv4.prv6_protocol_key()
        expected_norm_hash = prv2.normalization_policy_hash()
        self.normalization_policy_hash_value = expected_norm_hash
        self.protocol_key_value = expected_protocol_key
        norm_policy = norm.get("policy") or {}
        checks = (
            ling_route.get("model") == LING_MODEL
            and ling_route.get("endpoint") == LING_ENDPOINT
            and ling_route.get("route") == LING_ROUTE_NOTE
            and ling_route.get("key_loader") == "behavioral_discovery._api_key"
            and int(ling_route.get("max_retries", -1)) == 2
            and float(ling_route.get("min_attempt_interval_seconds", -1)) == 3.25
            and ling_route.get("max_tokens") == WRITER_MAX_TOKENS
            and float(ling_route.get("temperature", -1)) == 0.0
            and ling_route.get("retryable_statuses") == [408, 429, 500, 502, 503, 504, 529]
            and ling_route.get("pacing_algorithm")
            == "monotonic_min_interval_between_physical_attempt_starts"
            and writer_contract.get("model") == LING_MODEL
            and writer_contract.get("endpoint") == LING_ENDPOINT
            and int(writer_contract.get("max_retries", -1)) == 2
            and float(writer_contract.get("min_attempt_interval_seconds", -1)) == 3.25
            and float(writer_contract.get("backoff_initial_seconds", -1)) == 0.5
            and float(writer_contract.get("backoff_max_seconds", -1)) == 5.0
            and int(writer_contract.get("token_budget", -1)) == WRITER_MAX_TOKENS
            and float(writer_contract.get("temperature", -1)) == 0.0
            and writer_prompt.get("max_tokens") == WRITER_MAX_TOKENS
            and writer_prompt.get("temperature") == 0.0
            and writer_prompt.get("output_grammar")
            == "ANSWER: <label> + optional MESSAGE: <claim>; answer-only = silence"
            and jev_route.get("model") == JEV_MODEL
            and jev_route.get("endpoint") == JEV_ENDPOINT
            and int(jev_route.get("max_retries", -1)) == 2
            and float(jev_route.get("timeout_seconds", -1)) == 30.0
            and jev_route.get("backoff") == {"initial_seconds": 0.5, "jitter": 0.25,
                                             "max_seconds": 5.0}
            and jev_route.get("retryable_statuses") == [408, 429, 500, 502, 503, 504, 529]
            and jev_route.get("codec_version") == JEV_CODEC_VERSION
            and jev_route.get("protocol_key") == expected_protocol_key
            and float(norm.get("hard_ceiling", -1)) == NORMALIZATION_HARD_CEILING
            and norm.get("policy_hash") == expected_norm_hash
            and bool(norm_policy)
            and budgets.get("block_n") == BLOCK_N
            and collection.get("planned") == {"combined": 80, "receiver": 16, "writer": 64}
            and collection.get("physical")
            == {"combined": 240, "receiver": 48, "writer": 192}
            and float(collection.get("hard_cost_ceiling_usd", -1)) == 0.2
            and collection.get("next_call_reservation_usd")
            == {"jev": 0.001032192, "ling": 0.00202752}
            and (request_caps.get("max_retries") == {"jev": 2, "ling": 2})
            and int(cost_model.get("ling_input_token_ceiling", 0)) == 8192
            and int(cost_model.get("ling_output_token_ceiling", 0)) == WRITER_MAX_TOKENS
            and int(cost_model.get("jev_input_token_ceiling", 0)) == 8192
            and float(cost_model.get("ling_prompt_usd_per_mtok", -1)) == 0.06
            and float(cost_model.get("ling_completion_usd_per_mtok", -1)) == 0.18
            and float(cost_model.get("jev_input_usd_per_mtok", -1)) == 0.042
            and float(cost_model.get("ling_worst_physical_call_usd", -1)) == 0.00067584
            and float(cost_model.get("jev_worst_physical_call_usd", -1)) == 0.000344064
        )
        if not checks:
            raise LegalDiscoveryError("registered_transport_contract_drift")

        self.registration = registration
        self._cost_model = cost_model
        if ling_client is None or jev_client is None:
            built_ling, built_jev = _build_live_clients(registration)
            ling_client = ling_client if ling_client is not None else built_ling
            jev_client = jev_client if jev_client is not None else built_jev
        self.ling = ling_client
        self.jev = jev_client
        self.receiver = jc2.JevChoiceAdapterV2(self.jev, model=JEV_MODEL)
        self.is_configured = bool(
            getattr(self.ling, "api_key", None)
            and getattr(getattr(self.jev, "credentials", None), "present", False)
            and getattr(getattr(self.jev, "credentials", None), "shape_ok", False))

    def writer_completion(self, *, request: Mapping[str, Any]) -> Mapping[str, Any]:
        from apart_incident_response.jev_ling_writer_v5 import GRAMMAR_ORIGINAL_LING

        context = {
            "prompt": request["prompt"],
            "private_clues": request["private_clues"],
            "candidate_labels": request["candidate_labels"],
            "max_tokens": int(request["max_tokens"]),
            "grammar": GRAMMAR_ORIGINAL_LING,
            "seed": int(request["provider_seed"]),
        }
        before = int(getattr(self.ling, "physical_attempts", 0))
        try:
            outcome = self.ling.write_outcome(context)
        except Exception as exc:  # noqa: BLE001 - preserve physical/cost evidence
            diagnostics = list(getattr(self.ling, "last_call_diagnostics", ()))
            attempts = max(int(getattr(self.ling, "physical_attempts", before)) - before,
                           len(diagnostics))
            return {
                "attempts": attempts,
                "cost_usd": attempts * float(self._cost_model["ling_worst_physical_call_usd"]),
                "outcome": "writer_error", "claim": None,
                "error_class": f"writer_{type(exc).__name__}",
                "input_tokens": 0, "output_tokens": 0,
                "attempt_diagnostics": diagnostics,
                "request_identity": {
                    "model": LING_MODEL, "endpoint": LING_ENDPOINT,
                    "temperature": 0.0, "max_tokens": int(request["max_tokens"]),
                    "provider_seed": int(request["provider_seed"]),
                    "prompt_sha256": hashlib.sha256(
                        str(request["prompt"]).encode()).hexdigest(),
                },
            }
        # (success accounting continues below)
        attempts = len(getattr(self.ling, "last_call_diagnostics", ()))
        diagnostics = list(getattr(self.ling, "last_call_diagnostics", ()))
        input_tokens = outcome.get("input_tokens")
        output_tokens = outcome.get("output_tokens")
        costs = self._cost_model
        worst = float(costs["ling_worst_physical_call_usd"])
        failed_attempts = sum(1 for item in diagnostics if item.get("status") != 200)
        known_success = bool(diagnostics and diagnostics[-1].get("status") == 200)
        input_valid = (isinstance(input_tokens, int) and not isinstance(input_tokens, bool)
                       and input_tokens >= 0)
        output_valid = (isinstance(output_tokens, int)
                        and not isinstance(output_tokens, bool) and output_tokens >= 0)
        input_cost = (input_tokens * float(costs["ling_prompt_usd_per_mtok"]) / 1_000_000
                      if input_valid else worst)
        output_cost = (output_tokens * float(costs["ling_completion_usd_per_mtok"])
                       / 1_000_000 if output_valid else 0.0)
        final_cost = input_cost + output_cost
        if not known_success or not input_valid or not output_valid:
            final_cost = worst
        cost = failed_attempts * worst + (final_cost if known_success else 0.0)
        error_class = outcome.get("error_class")
        parsed_outcome = outcome.get("outcome")
        if parsed_outcome not in {"message_candidate", "non_owned_claim",
                                  "deliberate_silence", *WRITER_TERMINAL_OUTCOMES}:
            parsed_outcome = "writer_error"
            error_class = error_class or "writer_invalid_outcome"
        token_limit_error = (
            (input_valid and input_tokens > int(costs["ling_input_token_ceiling"]))
            or (output_valid and output_tokens > int(costs["ling_output_token_ceiling"])))
        token_usage_error = not input_valid or not output_valid
        request_identity = {
            "model": LING_MODEL, "endpoint": LING_ENDPOINT,
            "temperature": 0.0, "max_tokens": int(request["max_tokens"]),
            "provider_seed": int(request["provider_seed"]),
            "prompt_sha256": hashlib.sha256(str(request["prompt"]).encode()).hexdigest(),
        }
        return {
            "attempts": attempts, "cost_usd": cost,
            "outcome": ("writer_error" if token_limit_error or token_usage_error
                        else parsed_outcome),
            "claim": outcome.get("claim"),
            "error_class": ("writer_token_budget_exceeded" if token_limit_error else
                            "writer_malformed_usage" if token_usage_error else error_class),
            "input_tokens": input_tokens or 0, "output_tokens": output_tokens or 0,
            "request_identity": request_identity,
            "attempt_diagnostics": diagnostics,
        }

    def receiver_choice(self, *, request: Mapping[str, Any]) -> Mapping[str, Any]:
        state = request["state"]
        before = int(getattr(self.jev, "physical_attempts", 0))
        try:
            response, raw = self.receiver.complete_with_raw(state)
        except Exception as exc:  # noqa: BLE001 - preserve physical/cost evidence
            attempts = max(0, int(getattr(self.jev, "physical_attempts", before)) - before)
            return {
                "attempts": attempts,
                "cost_usd": attempts * float(self._cost_model["jev_worst_physical_call_usd"]),
                "status": "invalid", "error_class": f"transport_error_{type(exc).__name__}",
                "model": JEV_MODEL, "codec_version": JEV_CODEC_VERSION,
                "request_hash": state.request_hash,
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "request_identity": {
                    "model": JEV_MODEL, "endpoint": JEV_ENDPOINT,
                    "codec_version": JEV_CODEC_VERSION,
                    "protocol_key": self.protocol_key_value,
                    "request_hash": state.request_hash,
                    "option_ids": [option.option_id for option in state.options],
                },
            }
        attempts = int(getattr(self.jev, "physical_attempts", 0)) - before
        usage = dict(response.usage or {})
        costs = self._cost_model
        worst = float(costs["jev_worst_physical_call_usd"])
        input_tokens = usage.get("input_tokens")
        diagnostics = response.diagnostics.to_dict() if response.diagnostics is not None \
            else None
        success_http = attempts > 0 and isinstance(raw, Mapping) and bool(usage)
        successful_cost = (
            max(0, int(input_tokens)) * float(costs["jev_input_usd_per_mtok"]) / 1_000_000
            if isinstance(input_tokens, int) else worst)
        if not success_http or not isinstance(input_tokens, int):
            successful_cost = worst
        cost = max(0, attempts - 1) * worst + (successful_cost if attempts else 0.0)
        request_identity = {
            "model": JEV_MODEL, "endpoint": JEV_ENDPOINT,
            "codec_version": JEV_CODEC_VERSION,
            "protocol_key": self.protocol_key_value,
            "request_hash": state.request_hash,
            "option_ids": [option.option_id for option in state.options],
        }
        return {
            "attempts": attempts, "cost_usd": cost,
            "status": response.status,
            "error_class": response.error_class,
            "model": response.model,
            "codec_version": response.version,
            "selected_option_id": response.selected_option_id,
            "confidence": response.confidence,
            "probabilities": dict(response.probabilities),
            "raw_probabilities": dict(response.raw_probabilities),
            "usage": usage,
            "normalization_tier": response.normalization_tier,
            "renormalized": response.renormalized,
            "normalization_diagnostics": diagnostics,
            "request_hash": response.request_hash,
            "request_identity": request_identity,
        }


# --------------------------------------------------------------------------
# caps
# --------------------------------------------------------------------------

PROVIDER_BUDGET_KEY = {"ling": "writer", "jev": "receiver"}


class LegalCapTracker:
    """Retry-inclusive request and cost caps, enforced before every call.

    Collection caps: 64 Ling (writer) + 16 Jev (receiver) planned; 192 + 48
    physical; $0.20 collection hard ceiling. Program ceilings (384 physical,
    $0.30) are additionally enforced after every call.
    """

    MAX_PHYSICAL_PER_CALL = 1 + 2

    def __init__(self, budgets: Mapping[str, Any]) -> None:
        self.collection = budgets.get("discovery_collection") or {}
        self.cost_model = budgets.get("cost_model") or {}
        self.program = budgets.get("program") or {}
        self.program_cost_ceiling = float(self.program.get("hard_cost_ceiling_usd") or 0.0)
        self.program_physical_cap = int((self.program.get("physical") or {}).get(
            "combined", 0))
        self.ceiling = float(self.collection.get("hard_cost_ceiling_usd") or 0.0)
        self.reservation = dict(self.collection.get("next_call_reservation_usd") or {})
        self.planned = dict(self.collection.get("planned") or {})
        self.physical = dict(self.collection.get("physical") or {})
        self.planned_used = {"ling": 0, "jev": 0}
        self.physical_used = {"ling": 0, "jev": 0}
        self.cost_usd = 0.0

    def _key(self, provider: str) -> str:
        return PROVIDER_BUDGET_KEY[provider]

    def reason_before_call(self, provider: str) -> str | None:
        if provider not in self.physical_used:
            return f"unknown_provider:{provider}"
        key = self._key(provider)
        if self.planned_used[provider] + 1 > int(self.planned.get(key, 0)):
            return f"request_cap_planned:{provider}"
        if self.physical_used[provider] + self.MAX_PHYSICAL_PER_CALL > int(
                self.physical.get(key, 0)):
            return f"request_cap_physical:{provider}"
        reservation = float(self.reservation.get(provider, 0.0))
        if self.cost_usd + reservation > self.ceiling:
            return f"cost_cap_before_next_call:{provider}"
        return None

    def record(self, provider: str, *, attempts: int, cost_usd: float) -> None:
        self.planned_used[provider] += 1
        self.physical_used[provider] += attempts
        self.cost_usd += float(cost_usd)

    def reason_after_call(self, provider: str) -> str | None:
        key = self._key(provider)
        if self.planned_used[provider] > int(self.planned.get(key, 0)):
            return f"request_cap_planned:{provider}"
        if self.physical_used[provider] > int(self.physical.get(key, 0)):
            return f"request_cap_physical:{provider}"
        if self.cost_usd > self.ceiling:
            return "cost_cap_exceeded_after_call"
        combined = self.physical_used["ling"] + self.physical_used["jev"]
        if combined > self.program_physical_cap:
            return "program_request_cap_exceeded_after_call"
        if self.cost_usd > self.program_cost_ceiling:
            return "program_cost_cap_exceeded_after_call"
        return None

    def snapshot(self) -> dict[str, Any]:
        combined_physical = self.physical_used["ling"] + self.physical_used["jev"]
        combined_planned = self.planned_used["ling"] + self.planned_used["jev"]
        return {
            "planned_used": {"writer": self.planned_used["ling"],
                             "receiver": self.planned_used["jev"]},
            "physical_used": {"writer": self.physical_used["ling"],
                              "receiver": self.physical_used["jev"]},
            "planned_cap": dict(self.planned),
            "physical_cap": dict(self.physical),
            "cost_usd": round(self.cost_usd, 12),
            "cost_ceiling_usd": self.ceiling,
            "within_ceiling": self.cost_usd <= self.ceiling,
            "combined_planned_used": combined_planned,
            "combined_physical_used": combined_physical,
            "program_physical_cap": self.program_physical_cap,
            "program_cost_ceiling_usd": self.program_cost_ceiling,
            "within_program_physical_cap": combined_physical <= self.program_physical_cap,
            "within_program_cost_ceiling": self.cost_usd <= self.program_cost_ceiling,
        }


# --------------------------------------------------------------------------
# L4X execution helpers (legal family, same structure as the frozen writer)
# --------------------------------------------------------------------------

def _derive_instance(instance_id: str, seed: int) -> Any:
    """Regenerate the deterministic legal FamilyInstance for a registered seed."""
    from apart_incident_response import jev_replication_preregistration as rep
    instance = rep.instance_for(FAMILY, int(seed))
    if instance.instance_id != instance_id:
        raise LegalDiscoveryError("manifest_instance_id_drift")
    return instance


def _derive_structural_need(instance: Any) -> dict[str, Any]:
    analysis = instance.channel_analysis()
    return {
        "finalizer_needs_peer": bool(analysis["finalizer_needs_peer"]),
        "both_agents_needed": bool(analysis["both_agents_needed"]),
        "channel_complete": bool(analysis["channel_complete"]),
        "pooled_equals_joint": bool(analysis["pooled_equals_joint"]),
    }


def _derive_form_identity(instance: Any) -> dict[str, Any]:
    from apart_incident_response import jev_replay as jr
    from apart_incident_response import jev_replay_preregistration_v4 as prv4
    from apart_incident_response import jev_replication_preregistration as rep
    body, state = prv4.pre_read_body(instance, JEV_MODEL)
    return {
        "prompt_form_id": rep.pre_read_form_id(instance),
        "pre_read_request_hash": jr.prompt_form_id(body),
        "pre_read_state_hash": jr.canonical_hash(dict(state.state)),
        "option_ids": sorted(str(label) for label in instance.solutions),
        "target_id": str(instance.target),
    }


def _build_writer_prompt(instance: Any, agent: str, turn: int,
                         board: Sequence[Mapping[str, Any]], run_id: str) -> str:
    from apart_incident_response import behavioral_discovery as bd
    from apart_incident_response import jev_writer_ladder_v5 as ladder
    from apart_incident_response.communication_protocol import BatteryCondition
    from apart_incident_response.communication_runner import AgentContext
    view = {**instance.agent_view(agent, "COMM"), "is_finalizer": agent == bd.FINALIZER_AGENT,
            "finalizing_agent": bd.FINALIZER_AGENT}
    visible = tuple(dict(row) for row in board if row["author"] != agent)
    context = AgentContext(run_id, instance.instance_id, agent, BatteryCondition.COMM, turn,
                           view, visible, bd.PROMPT_SCHEMA_VERSION,
                           ladder.EXACT_BRIDGE_TOKEN_BUDGET)
    return json.dumps(bd.treatment_prompt(context), sort_keys=True)


def _build_receiver_state(instance: Any, board: Sequence[Mapping[str, Any]]) -> Any:
    from apart_incident_response import jev_choice_v2 as jc2
    from apart_incident_response import jev_replay as jr
    b_rows = [row for row in board if row["author"] == "B" and row["status"] == "accepted"]
    visible = [{"text": jr.serialize_message(str(row["text"]))} for row in b_rows]
    adapter = jc2.JevChoiceAdapterV2(object(), model=JEV_MODEL)
    return adapter.build_state(instance, "A", "COMM", visible_messages=visible)


def _receiver_response_error(response: Mapping[str, Any], state: Any) -> str | None:
    """Independently enforce the registered Choice response invariants."""
    if response.get("status") != "complete":
        return str(response.get("error_class") or "receiver_invalid")
    if response.get("model") not in (None, JEV_MODEL):
        return "model_drift"
    if response.get("codec_version") not in (None, JEV_CODEC_VERSION):
        return "protocol_key_drift"
    if response.get("request_hash") != state.request_hash:
        return "request_hash_drift"
    expected = {option.option_id for option in state.options}
    probabilities = response.get("probabilities")
    raw = response.get("raw_probabilities")
    for name, vector in (("probabilities", probabilities), ("raw_probabilities", raw)):
        if not isinstance(vector, Mapping) or set(vector) != expected:
            return "option_identity_drift"
        values = list(vector.values())
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(float(value)) or float(value) < 0.0 for value in values):
            return "invalid_probability_vector"
        if name == "probabilities" and abs(sum(float(v) for v in values) - 1.0) > 1e-9:
            return "normalized_vector_invalid"
        if name == "raw_probabilities" and abs(
                sum(float(v) for v in values) - 1.0) > NORMALIZATION_HARD_CEILING:
            return "normalization_hard_ceiling_exceeded"
    selected = response.get("selected_option_id")
    if selected not in expected:
        return "unknown_selection"
    peak = max(float(value) for value in probabilities.values())
    if float(probabilities[selected]) != peak:
        return "unknown_selection"
    confidence = response.get("confidence")
    if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence)) or not 0.0 <= float(confidence) <= 1.0):
        return "invalid_confidence"
    usage = response.get("usage")
    if not isinstance(usage, Mapping) or any(
            isinstance(usage.get(name), bool) or not isinstance(usage.get(name), int)
            or usage.get(name) < 0 for name in ("input_tokens", "output_tokens")):
        return "malformed_usage"
    diagnostics = response.get("normalization_diagnostics") or {}
    if not isinstance(diagnostics, Mapping):
        return "normalization_diagnostics_invalid"
    deviation = diagnostics.get("absolute_normalization_deviation")
    if deviation is not None:
        if (isinstance(deviation, bool) or not isinstance(deviation, (int, float))
                or not math.isfinite(float(deviation)) or float(deviation) < 0):
            return "normalization_diagnostics_invalid"
        if float(deviation) > NORMALIZATION_HARD_CEILING:
            return "normalization_hard_ceiling_exceeded"
    return None


def _seed_row(entry: Mapping[str, Any], *, sequence: int,
              stage: str) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "stage": stage,
        "family": FAMILY,
        "instance_id": entry.get("instance_id"),
        "prompt_form_id": entry.get("prompt_form_id"),
        "seed": entry.get("seed"),
        "attempted": False,
        "status": "not_attempted",
        "failure_reason": None,
        "structural_need": None,
        "form_identity": None,
        "emission": None,
        "ownership": None,
        "exposure": None,
        "information": None,
        "receiver": None,
        "request": None,
        "cost": {"usd": 0.0, "cumulative_usd": 0.0},
        "provider_calls": 0,
        "physical_attempts": {"ling": 0, "jev": 0, "combined": 0},
        "token_usage": {"ling_input_tokens": 0, "ling_output_tokens": 0,
                        "jev_input_tokens": 0, "jev_output_tokens": 0},
    }


# --------------------------------------------------------------------------
# the registered run
# --------------------------------------------------------------------------

def execute_legal_discovery_run(
    registration: Mapping[str, Any],
    lock: Mapping[str, Any] | None,
    auth: Mapping[str, Any] | None,
    *,
    lock_review: Mapping[str, Any] | None = None,
    repo_root: Path,
    approval: str | None,
    preflight: Mapping[str, Any],
    transport_factory: Callable[[], hyp_p06.DiscoveryTransport] | None = None,
    journal_path: Path | None = None,
    report_path: Path | None = None,
    row_hook: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Execute the registered legal discovery block, or refuse before any call.

    Every gate is checked before the transport is constructed and before the
    journal exists: release gates, preflight, output freshness, manifest
    integrity, and transport configuration. After any stop the remaining
    planned instances are journaled as ``not_attempted`` with the stop reason
    so the journal is always complete at the registered N.
    """

    root = Path(repo_root)
    paths = registration.get("paths") or {}
    stage = str(registration.get("stage") or STAGE)
    journal_path = journal_path or root / str(paths.get("discovery_journal", ""))
    report_path = report_path or root / str(paths.get("discovery_report", ""))

    stop, lock_state, auth_state = evaluate_release_gates(
        lock, auth, approval, registration, lock_review)
    if stop is not None:
        return _blocked(stop, authorization_state=auth_state, lock_state=lock_state)
    if not preflight.get("ok"):
        return _blocked("preflight_failed", authorization_state=auth_state,
                        lock_state=lock_state, extra={"failed": preflight.get("failed")})
    if journal_path.exists():
        return _blocked("output_collision:journal_exists",
                        authorization_state=auth_state, lock_state=lock_state,
                        extra={"path": str(journal_path)})
    if report_path.exists():
        return _blocked("output_collision:report_exists",
                        authorization_state=auth_state, lock_state=lock_state,
                        extra={"path": str(report_path)})

    manifest = list((registration.get("fixed_n") or {}).get("manifest") or [])
    block_n = int((registration.get("fixed_n") or {}).get("block_n") or BLOCK_N)
    if len(manifest) != block_n:
        return _blocked("manifest_drift", authorization_state=auth_state,
                        lock_state=lock_state, extra={"found": len(manifest)})
    if (registration.get("preregistration_version") != REGISTRATION_VERSION
            or registration.get("registration_hash") != REGISTRATION_HASH
            or lp04._content_hash(registration, hash_key="registration_hash")
            != REGISTRATION_HASH):
        return _blocked("registration_drift", authorization_state=auth_state,
                        lock_state=lock_state)

    treatment = registration.get("treatment") or {}
    exposure_id = str(treatment.get("exposure_id") or "jev-finalizer")
    max_tokens = int(treatment.get("writer_prompt", {}).get("max_tokens")
                     or WRITER_MAX_TOKENS)

    caps = LegalCapTracker(registration.get("budgets") or {})
    try:
        transport = transport_factory()
    except Exception as exc:  # noqa: BLE001 - fail closed before creating outputs
        return _blocked("transport_configuration_failed",
                        authorization_state=auth_state, lock_state=lock_state,
                        extra={"error_class": type(exc).__name__})
    if not getattr(transport, "is_configured", False):
        return _blocked("transport_not_configured",
                        authorization_state=auth_state, lock_state=lock_state)
    journal = DiscoveryJournal(journal_path)
    completed = {"ok": 0, "silence": 0, "failed": 0, "not_attempted": 0}
    stop_reason: str | None = None
    provider_calls = 0
    consecutive_terminal_failures = 0

    try:
        for index, entry in enumerate(manifest):
            row = _seed_row(entry, sequence=index + 1, stage=stage)
            cost_before_row = caps.cost_usd
            active_provider = "ling"
            call_accounted = False
            call_started = False
            if stop_reason is None:
                reason = caps.reason_before_call("ling")
                if reason is not None:
                    stop_reason = reason
            if stop_reason is None:
                row["attempted"] = True
                try:
                    instance = _derive_instance(str(entry["instance_id"]), int(entry["seed"]))
                    row["structural_need"] = _derive_structural_need(instance)
                    row["form_identity"] = _derive_form_identity(instance)

                    from apart_incident_response.communication_events import (
                        CommunicationEventLog,  # noqa: PLC0415
                    )
                    run_id = f"legal-discovery-{instance.instance_id}"
                    log = CommunicationEventLog(run_id)
                    board: list[dict[str, Any]] = []
                    board_info: dict[str, Any] = {}
                    rejected: list[dict[str, Any]] = []
                    writer_outcomes: list[dict[str, Any]] = []
                    writer_request_identities: list[dict[str, Any]] = []
                    invalid: str | None = None

                    for turn in range(2):
                        for agent in ("A", "B"):
                            reason = caps.reason_before_call("ling")
                            if reason is not None:
                                stop_reason = reason
                                invalid = reason
                                break
                            prompt = _build_writer_prompt(instance, agent, turn, board,
                                                          run_id)
                            from apart_incident_response import (
                                behavioral_discovery as bd,  # noqa: PLC0415
                            )
                            view = instance.agent_view(agent, "COMM")
                            provider_seed = bd.provider_seed(
                                instance.instance_id, "COMM", turn, agent)
                            active_provider = "ling"
                            call_accounted = False
                            call_started = True
                            result = transport.writer_completion(
                                request={"instance_id": instance.instance_id,
                                         "seed": instance.seed,
                                         "provider_seed": provider_seed,
                                         "agent": agent,
                                         "turn": turn,
                                         "prompt": prompt,
                                         "private_clues": list(
                                             view.get("private_clues", ())),
                                         "candidate_labels": sorted(
                                             str(label) for label in instance.solutions),
                                         "max_tokens": max_tokens,
                                         "model": LING_MODEL,
                                         "endpoint": LING_ENDPOINT})
                            raw_attempts = result.get("attempts", 1)
                            attempts_valid = (isinstance(raw_attempts, int)
                                              and not isinstance(raw_attempts, bool)
                                              and raw_attempts >= 0)
                            attempts = raw_attempts if attempts_valid else 1
                            raw_cost = result.get("cost_usd", 0.0)
                            try:
                                cost = float(raw_cost)
                            except (TypeError, ValueError):
                                cost = float("nan")
                            cost_valid = math.isfinite(cost) and cost >= 0
                            if not attempts_valid or not cost_valid:
                                cost = attempts * float(
                                    (registration.get("budgets") or {})
                                    .get("cost_model", {})
                                    .get("ling_worst_physical_call_usd", 0.0))
                            provider_calls += attempts
                            caps.record("ling", attempts=attempts, cost_usd=cost)
                            call_accounted = True
                            row["physical_attempts"]["ling"] += attempts
                            input_tokens = result.get("input_tokens", 0)
                            output_tokens = result.get("output_tokens", 0)
                            input_valid = (isinstance(input_tokens, int)
                                           and not isinstance(input_tokens, bool)
                                           and input_tokens >= 0)
                            output_valid = (isinstance(output_tokens, int)
                                            and not isinstance(output_tokens, bool)
                                            and output_tokens >= 0)
                            row["token_usage"]["ling_input_tokens"] += (
                                input_tokens if input_valid else 0)
                            row["token_usage"]["ling_output_tokens"] += (
                                output_tokens if output_valid else 0)
                            if not attempts_valid:
                                invalid = "writer_attempt_count_invalid"
                            elif attempts > LegalCapTracker.MAX_PHYSICAL_PER_CALL:
                                invalid = "writer_attempt_count_invalid"
                            elif not cost_valid:
                                invalid = "writer_cost_invalid"
                            elif not input_valid or not output_valid:
                                invalid = "writer_malformed_usage"
                            identity = result.get("request_identity")
                            if identity is not None:
                                if not isinstance(identity, Mapping) or (
                                        identity.get("model") != LING_MODEL
                                        or identity.get("endpoint") != LING_ENDPOINT
                                        or identity.get("temperature") != 0.0
                                        or identity.get("max_tokens") != max_tokens
                                        or identity.get("provider_seed") != provider_seed
                                        or identity.get("prompt_sha256")
                                        != hashlib.sha256(prompt.encode()).hexdigest()):
                                    invalid = invalid or "writer_request_identity_drift"
                                    stop_reason = invalid
                                else:
                                    writer_request_identities.append(dict(identity))
                            outcome = result.get("outcome")
                            if outcome not in {"message_candidate", "non_owned_claim",
                                               "deliberate_silence",
                                               *WRITER_TERMINAL_OUTCOMES}:
                                outcome = "writer_error"
                                result = dict(result, error_class="writer_invalid_outcome")
                            if outcome in {"message_candidate", "non_owned_claim"} and (
                                    not isinstance(result.get("claim"), str)
                                    or not result["claim"].strip()):
                                outcome = "writer_error"
                                result = dict(result, error_class="writer_invalid_claim")
                            writer_outcomes.append({
                                "agent": agent, "turn": turn, "outcome": outcome,
                                "claim": result.get("claim"),
                                "error_class": result.get("error_class"),
                                "physical_attempts": attempts,
                                "attempt_diagnostics": result.get("attempt_diagnostics", []),
                                "request_identity": identity,
                            })
                            if invalid is not None:
                                stop_reason = invalid
                                break
                            cap_violation = caps.reason_after_call("ling")
                            if cap_violation is not None:
                                invalid = cap_violation
                                stop_reason = cap_violation
                                break
                            if outcome == "message_candidate":
                                claim = str(result.get("claim"))
                                if instance.holds_claim(agent, claim):
                                    receiver_agent = "B" if agent == "A" else "A"
                                    message_id = f"message-{agent}-{turn}"
                                    info = instance.information(receiver_agent, claim,
                                                                message_id)
                                    board_row = {"message_id": message_id, "author": agent,
                                                 "receiver": receiver_agent, "text": claim,
                                                 "status": info.status,
                                                 "delta_i_bits": info.delta_i_bits,
                                                 "message_tokens": len(claim.split())}
                                    board.append(board_row)
                                    board_info[message_id] = info
                                    log.board_write(
                                        agent, info,
                                        message_tokens=board_row["message_tokens"],
                                        receiver_id=receiver_agent)
                                else:
                                    rejected.append({"agent": agent, "turn": turn,
                                                     "claim": claim})
                                    log.record("board_write_rejected", agent,
                                               status="rejected",
                                               payload={"reason": "claim_not_owned_by_writer",
                                                        "raw_text": claim})
                            elif outcome == "non_owned_claim":
                                rejected.append({"agent": agent, "turn": turn,
                                                 "claim": result.get("claim")})
                                log.record("board_write_rejected", agent, status="rejected",
                                           payload={"reason": "claim_not_owned_by_writer",
                                                    "raw_text": result.get("claim")})
                            elif outcome == "deliberate_silence":
                                pass
                            else:
                                invalid = str(result.get("error_class") or outcome)
                                stop_reason = invalid
                                break
                        if invalid is not None:
                            break

                    receiver_attempted = False
                    receiver_valid = False
                    receiver_error_class: str | None = None
                    receiver_row: dict[str, Any] = {}
                    if invalid is None:
                        protocol_key = getattr(transport, "protocol_key_value", "")
                        reason = caps.reason_before_call("jev")
                        if reason is not None:
                            stop_reason = reason
                            invalid = reason
                        else:
                            state = _build_receiver_state(instance, board)
                            receiver_request = {
                                "instance_id": instance.instance_id,
                                "seed": instance.seed,
                                "agent": "A",
                                "condition": "COMM",
                                "model": JEV_MODEL,
                                "endpoint": JEV_ENDPOINT,
                                "codec_version": JEV_CODEC_VERSION,
                                "protocol_key": protocol_key,
                                "request_hash": state.request_hash,
                                "state": state,
                            }
                            for board_row in [r for r in board
                                              if r["author"] == "B"
                                              and r["status"] == "accepted"]:
                                log.peer_read("A", board_info[board_row["message_id"]],
                                              exposure_id=exposure_id)
                            try:
                                active_provider = "jev"
                                call_accounted = False
                                call_started = True
                                response = transport.receiver_choice(request=receiver_request)
                            except Exception as exc:  # noqa: BLE001 - fail closed
                                receiver_error_class = f"jev_{type(exc).__name__}"
                                stop_reason = receiver_error_class
                                attempts = 1
                                cost = float((registration.get("budgets") or {})
                                             .get("cost_model", {})
                                             .get("jev_worst_physical_call_usd", 0.0))
                                provider_calls += attempts
                                caps.record("jev", attempts=attempts, cost_usd=cost)
                                row["physical_attempts"]["jev"] += attempts
                                row["cost"]["usd"] += cost
                                receiver_attempted = True
                                call_accounted = True
                                response = None
                            if response is not None:
                                receiver_attempted = True
                                raw_attempts = response.get("attempts", 1)
                                attempts_valid = (isinstance(raw_attempts, int)
                                                  and not isinstance(raw_attempts, bool)
                                                  and raw_attempts >= 0)
                                attempts = raw_attempts if attempts_valid else 1
                                raw_cost = response.get("cost_usd", 0.0)
                                try:
                                    cost = float(raw_cost)
                                except (TypeError, ValueError):
                                    cost = float("nan")
                                cost_valid = math.isfinite(cost) and cost >= 0
                                if not attempts_valid or not cost_valid:
                                    cost = attempts * float(
                                        (registration.get("budgets") or {})
                                        .get("cost_model", {})
                                        .get("jev_worst_physical_call_usd", 0.0))
                                provider_calls += attempts
                                caps.record("jev", attempts=attempts, cost_usd=cost)
                                call_accounted = True
                                row["physical_attempts"]["jev"] += attempts
                                usage = response.get("usage") or {}
                                input_tokens = (usage.get("input_tokens")
                                                if isinstance(usage, Mapping) else None)
                                output_tokens = (usage.get("output_tokens")
                                                 if isinstance(usage, Mapping) else None)
                                input_valid = (isinstance(input_tokens, int)
                                               and not isinstance(input_tokens, bool)
                                               and input_tokens >= 0)
                                output_valid = (isinstance(output_tokens, int)
                                                and not isinstance(output_tokens, bool)
                                                and output_tokens >= 0)
                                row["token_usage"]["jev_input_tokens"] += (
                                    input_tokens if input_valid else 0)
                                row["token_usage"]["jev_output_tokens"] += (
                                    output_tokens if output_valid else 0)
                                receiver_valid = (
                                    response.get("status") == "complete"
                                    and attempts_valid
                                    and attempts <= LegalCapTracker.MAX_PHYSICAL_PER_CALL
                                    and cost_valid and input_valid and output_valid)
                                receiver_error_class = response.get("error_class")
                                if not attempts_valid or attempts \
                                        > LegalCapTracker.MAX_PHYSICAL_PER_CALL:
                                    receiver_error_class = "jev_attempt_count_invalid"
                                elif not cost_valid:
                                    receiver_error_class = "jev_cost_invalid"
                                elif not input_valid or not output_valid:
                                    receiver_error_class = "malformed_usage"
                                if not receiver_valid:
                                    stop_reason = receiver_error_class or "receiver_invalid"
                                receiver_row = {
                                    "status": response.get("status"),
                                    "error_class": receiver_error_class,
                                    "normalization_tier": response.get("normalization_tier"),
                                    "renormalized": response.get("renormalized"),
                                    "resolved_model": response.get("model"),
                                    "selected_option_id": response.get("selected_option_id"),
                                    "confidence": response.get("confidence"),
                                    "probabilities": response.get("probabilities"),
                                    "raw_probabilities": response.get("raw_probabilities"),
                                    "usage": response.get("usage"),
                                    "request_hash": state.request_hash,
                                }
                                rid = response.get("request_identity")
                                if rid is not None and (
                                        not isinstance(rid, Mapping)
                                        or rid.get("model") != JEV_MODEL
                                        or rid.get("endpoint") != JEV_ENDPOINT
                                        or rid.get("codec_version") != JEV_CODEC_VERSION
                                        or rid.get("protocol_key") not in (protocol_key,)
                                        or rid.get("request_hash") != state.request_hash
                                        or rid.get("option_ids")
                                        != [option.option_id for option in state.options]):
                                    receiver_valid = False
                                    receiver_error_class = "request_identity_drift"
                                    stop_reason = "request_identity_drift"
                                if response.get("model") not in (None, JEV_MODEL):
                                    receiver_valid = False
                                    receiver_error_class = "model_drift"
                                    stop_reason = "model_drift"
                                if response.get("codec_version") not in (None,
                                                                         JEV_CODEC_VERSION):
                                    receiver_valid = False
                                    receiver_error_class = "protocol_key_drift"
                                    stop_reason = "protocol_key_drift"
                                norm_diag = response.get("normalization_diagnostics") or {}
                                if not isinstance(norm_diag, Mapping):
                                    norm_diag = {}
                                    receiver_valid = False
                                    receiver_error_class = "normalization_diagnostics_invalid"
                                    stop_reason = receiver_error_class
                                deviation = norm_diag.get("absolute_normalization_deviation")
                                if deviation is not None:
                                    if (isinstance(deviation, bool)
                                            or not isinstance(deviation, (int, float))
                                            or not math.isfinite(float(deviation))
                                            or float(deviation) < 0):
                                        receiver_valid = False
                                        receiver_error_class = "normalization_diagnostics_invalid"
                                        stop_reason = receiver_error_class
                                    elif float(deviation) > NORMALIZATION_HARD_CEILING:
                                        receiver_valid = False
                                        receiver_error_class = \
                                            "normalization_hard_ceiling_exceeded"
                                        stop_reason = receiver_error_class
                                if receiver_valid and response.get("request_hash") \
                                        != state.request_hash:
                                    receiver_valid = False
                                    receiver_error_class = "request_hash_drift"
                                    stop_reason = "request_hash_drift"
                                validation_error = (_receiver_response_error(
                                    response, state)
                                    or caps.reason_after_call("jev"))
                                if validation_error is not None:
                                    receiver_valid = False
                                    receiver_error_class = validation_error
                                    stop_reason = validation_error
                                if not receiver_valid and stop_reason is None:
                                    stop_reason = receiver_error_class or "receiver_invalid"
                                receiver_row["codec_version"] = response.get("codec_version")
                                receiver_row["normalization_diagnostics"] = response.get(
                                    "normalization_diagnostics")
                                receiver_row["request_identity"] = response.get(
                                    "request_identity")

                    evidence = hyp_p06._verify_board_evidence(log.events)
                    row["ownership"] = {
                        "b_to_a_ownership_verified":
                            evidence["accepted_b_to_a_writes"] > 0,
                        "accepted_b_to_a_writes": evidence["accepted_b_to_a_writes"],
                        "rejected_claims": rejected,
                    }
                    row["exposure"] = {
                        "read_after_write_verified": evidence["read_after_write_verified"],
                        "verified_read_exposures": evidence["verified_read_exposures"],
                        "reads": evidence["reads"],
                    }
                    row["emission"] = {
                        "writer_outcomes": writer_outcomes,
                        "writer_request_identities": writer_request_identities,
                        "board_messages": len(board),
                        "silence": all(o["outcome"] == "deliberate_silence"
                                       for o in writer_outcomes),
                    }
                    row["information"] = {
                        "i_m_bits": sum(float(r.get("delta_i_bits") or 0.0)
                                        for r in board if r["author"] == "B"),
                    }
                    row["receiver"] = receiver_row
                    row["request"] = {
                        "provider": "ling+jev",
                        "ling_model": LING_MODEL,
                        "ling_endpoint": LING_ENDPOINT,
                        "jev_model": JEV_MODEL,
                        "jev_endpoint": JEV_ENDPOINT,
                        "jev_codec_version": JEV_CODEC_VERSION,
                        "ling_planned_calls": 4,
                        "jev_planned_calls": 1,
                        "ling_attempts": row["physical_attempts"]["ling"],
                        "jev_attempts": row["physical_attempts"]["jev"],
                    }
                    row["cost"] = {"usd": round(caps.cost_usd - cost_before_row, 12),
                                   "cumulative_usd": round(caps.cost_usd, 12)}
                    row["provider_calls"] = (row["physical_attempts"]["ling"]
                                             + row["physical_attempts"]["jev"])
                    row["physical_attempts"]["combined"] = (
                        row["physical_attempts"]["ling"]
                        + row["physical_attempts"]["jev"])

                    if invalid is not None:
                        row["status"] = "failed"
                        row["failure_reason"] = f"writer_error:{invalid}"
                        completed["failed"] += 1
                        consecutive_terminal_failures += 1
                        if consecutive_terminal_failures >= 2:
                            stop_reason = "two_consecutive_terminal_provider_failures"
                    elif not receiver_attempted:
                        row["status"] = "failed"
                        row["failure_reason"] = f"not_attempted:{stop_reason}"
                        completed["failed"] += 1
                    elif not receiver_valid:
                        row["status"] = "failed"
                        row["failure_reason"] = f"receiver_error:{receiver_error_class}"
                        completed["failed"] += 1
                        consecutive_terminal_failures += 1
                        if consecutive_terminal_failures >= 2:
                            stop_reason = "two_consecutive_terminal_provider_failures"
                    elif row["emission"]["silence"]:
                        row["status"] = "silence"
                        completed["silence"] += 1
                    else:
                        row["status"] = "ok"
                        completed["ok"] += 1
                except Exception as exc:  # noqa: BLE001 - fail closed
                    row["status"] = "failed"
                    row["failure_reason"] = f"writer_error:{type(exc).__name__}"
                    completed["failed"] += 1
                    if call_started and not call_accounted:
                        cost_key = f"{active_provider}_worst_physical_call_usd"
                        failed_cost = float((registration.get("budgets") or {})
                                            .get("cost_model", {}).get(cost_key, 0.0))
                        # The transport raised without returning a physical
                        # attempt count. Charge the full retry reservation and
                        # stop; making another call could breach a cap.
                        reserved = LegalCapTracker.MAX_PHYSICAL_PER_CALL
                        caps.record(active_provider, attempts=reserved,
                                    cost_usd=reserved * failed_cost)
                        row["cost"]["usd"] += reserved * failed_cost
                        row["physical_attempts"][active_provider] += reserved
                        provider_calls += reserved
                    stop_reason = "unaccounted_transport_or_audit_exception"
                row["physical_attempts"]["combined"] = (
                    row["physical_attempts"]["ling"]
                    + row["physical_attempts"]["jev"])
                row["provider_calls"] = row["physical_attempts"]["combined"]
                row["cost"] = {"usd": round(caps.cost_usd - cost_before_row, 12),
                               "cumulative_usd": round(caps.cost_usd, 12)}
                if row_hook:
                    row_hook(row)
                journal.write(row)
                if stop_reason is not None:
                    for offset, remaining in enumerate(manifest[index + 1:], start=1):
                        remaining_row = _seed_row(remaining, sequence=index + 1 + offset,
                                                  stage=stage)
                        remaining_row["failure_reason"] = f"not_attempted:{stop_reason}"
                        completed["not_attempted"] += 1
                        if row_hook:
                            row_hook(remaining_row)
                        journal.write(remaining_row)
                    break
            else:
                row["failure_reason"] = f"not_attempted:{stop_reason}"
                completed["not_attempted"] += 1
                if row_hook:
                    row_hook(row)
                journal.write(row)
    finally:
        journal.close()

    report = {
        "mode": RUNNER_VERSION,
        "status": "completed" if stop_reason is None else "stopped",
        "stop_reason": stop_reason,
        "stage": stage,
        "family": FAMILY,
        "registration_version": registration.get("preregistration_version"),
        "registration_hash": registration.get("registration_hash"),
        "lock_path": LOCK_PATH if isinstance(lock, Mapping) else None,
        "authorization_reference": (auth or {}).get("reference"),
        "planned_seeds": len(manifest),
        "journaled_seeds": journal.rows,
        "journal_complete_at_registered_n": journal.rows == len(manifest),
        "counts": completed,
        "caps": caps.snapshot(),
        "provider_calls": provider_calls,
        "seeds": [entry.get("instance_id") for entry in manifest],
        "credentials_retained": False,
    }
    return report


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Legal L05 discovery preflight (offline by default; live "
                    "execution additionally requires the L06 reviewed lock and "
                    "an authorized, scope-bound L07 record plus --approval)")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--live", action="store_true",
                        help="execute the registered block (refused unless every "
                             "release gate passes and --approval matches its reference)")
    parser.add_argument("--approval", help="explicit live authorization reference")
    parser.add_argument("--no-report", action="store_true",
                        help="do not write (or verify) the versioned preflight report")
    args = parser.parse_args(argv)
    root = Path(args.repo_root) if args.repo_root is not None else Path(
        __file__).resolve().parents[2]

    preflight = run_preflight(root, approval=args.approval)
    print(json.dumps({"mode": preflight["mode"], "ok": preflight["ok"],
                      "failed": preflight["failed"],
                      "checks_run": preflight["checks_run"],
                      "lock_state": preflight["lock_state"],
                      "authorization_state": preflight["authorization_state"],
                      "authorized": preflight["authorized"],
                      "release_gate_stop_reason": preflight["release_gate_stop_reason"],
                      "registration_hash": preflight["registration_hash"],
                      "planned_seeds": preflight["planned_seeds"],
                      "network_events": preflight["network_audit"]["events"],
                      "provider_calls": 0, "status": preflight["status"]},
                     indent=2, sort_keys=True, allow_nan=False))
    if not preflight["ok"]:
        return 2

    if not args.no_report:
        target = root / PREFLIGHT_REPORT_PATH
        blueprint = _report_blueprint(root, _load(root, REGISTRATION_PATH))
        if target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            if existing != blueprint:
                print(json.dumps({"collided_report_path": str(target)}, indent=2,
                                 sort_keys=True))
                return 4
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(blueprint, indent=2, sort_keys=True,
                                        allow_nan=False) + "\n")

    if not args.live:
        return 0

    registration = _load(root, REGISTRATION_PATH)
    lock = _load(root, LOCK_PATH) if (root / LOCK_PATH).is_file() else None
    lock_review = _load(root, LOCK_REVIEW_PATH) \
        if (root / LOCK_REVIEW_PATH).is_file() else None
    auth = _load(root, AUTH_PATH) if (root / AUTH_PATH).is_file() else None
    report = execute_legal_discovery_run(
        registration, lock, auth, lock_review=lock_review,
        repo_root=root, approval=args.approval,
        preflight=preflight,
        # Constructed only after every gate passes; a pending or missing
        # authorization never reaches it.
        transport_factory=(lambda: ConfiguredLegalDiscoveryTransport(registration))
        if args.live else None)
    print(json.dumps({key: report.get(key) for key in
                      ("mode", "status", "stop_reason", "authorization_state",
                       "lock_state", "planned_seeds", "journaled_seeds",
                       "provider_calls")}, indent=2, sort_keys=True, allow_nan=False))
    if report.get("status") == "blocked":
        return 3
    target = root / str(registration["paths"]["discovery_report"])
    target.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite: the report path was verified fresh before the run.
    with target.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return 0 if report.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "RUNNER_VERSION", "PREFLIGHT_VERSION", "REGISTRATION_PATH", "REGISTRATION_VERSION",
    "REGISTRATION_HASH", "LOCK_PATH", "LOCK_REVIEW_PATH", "AUTH_PATH",
    "LOCK_APPROVED_STATES", "lock_hash",
    "AUTH_STATE_PENDING", "AUTH_STATE_AUTHORIZED", "AUTH_STATE_NO_RECORD",
    "LOCK_STATE_PRESENT", "LOCK_STATE_ABSENT", "MUST_COVER", "PREFLIGHT_REPORT_PATH",
    "FAMILY", "BLOCK_N", "INSTANCES_PER_FORM", "FORM_COUNT", "STAGE", "LING_MODEL",
    "LING_ENDPOINT", "JEV_MODEL", "JEV_ENDPOINT", "JEV_CODEC_VERSION",
    "NORMALIZATION_HARD_CEILING", "WRITER_MAX_TOKENS", "WRITER_TERMINAL_OUTCOMES",
    "LegalDiscoveryError", "DiscoveryJournal", "LegalCapTracker",
    "ConfiguredLegalDiscoveryTransport", "scope_digest",
    "authorization_scope_for_registration", "scope_matches_registration",
    "reference_binds_scope_digest", "evaluate_release_gates",
    "validate_registration_fields", "run_preflight", "execute_legal_discovery_run",
    "main",
]
