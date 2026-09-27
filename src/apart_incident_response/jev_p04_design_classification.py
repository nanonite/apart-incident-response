"""P04 — classify design and plan discovery (#205).

Offline only. No provider call is made by any code path in this module.

This module classifies the ``hypothesis:low`` next-family design and drafts
the discovery registration for Chainlink #205 under #201 under #159. It
produces:

1. A **design classification**: k and the attainable exact two-sided sign-flip
   floor, and the pilot-versus-potentially-confirmatory classification. The
   P03 census closed the form space at k = 4, so the attainable floor is
   2/2^4 = 0.125 > 0.05: no dichotomous rejection at alpha = 0.05 is
   attainable at any effect size on this family. The design is a **pilot**
   (descriptive/estimation only), not potentially confirmatory; a potentially
   confirmatory design needs k >= 6. ``hypothesis`` remains descriptive,
   including for its fresh-seed replication block.
2. A **discovery registration** (draft, offline) freezing the discovery-stage
   design: fixed N (16 instances = 4 per form x 4 forms on the discovery
   window 85000-85511), treatment/route (original L4X communication treatment
   via the paid Ling route; Jev receiver), budgets (discovery collection plus
   optional exploratory replay), terminal stops, fresh output paths, and
   coverage rules (permissible within-form missingness, complete-case scope,
   no imputation, no seed replacement, no form removal after outcomes).

The registration is deterministic: ``build_registration`` reproduces the
artifact byte-for-byte from the frozen generator and the current disk state.
The artifact lives outside ``runs/epic-126/`` so the frozen #200 audit's
byte-reproducibility (which scans ``runs/epic-126/**``) is preserved.

The registration resolves the two #200 wording defects logged in P01 section 5:
the six-form confirmatory minimum (not five) and the interval half-width
labeling (not a power-based MDE). It authorizes nothing beyond P05 planning:
no provider call, no collection, no registration lock, no live run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import jev_form_census as census
from . import jev_replication_preregistration as rep
from . import task_families as tf


REGISTRATION_VERSION = "jev-discovery-registration-v1"
REGISTRATION_PATH = Path("runs/next-phase/jev-p04-discovery-registration-v1.json")
DRAFT_STATUS = "draft_pending_review"

#: The registration lives outside runs/epic-126/ so the frozen #200 audit's
#: byte-reproducibility (which scans runs/epic-126/**) is preserved.
FAMILY = "hypothesis"

#: Discovery-stage seed window (the #200 `primary` block, relabeled `discovery`
#: in the P02 scope freeze). Fixed N = 16 = 4 per form x 4 forms.
DISCOVERY_BASE = rep.SEED_SCAN_BASE
DISCOVERY_WINDOW = rep.SEED_SCAN_WINDOW
DISCOVERY_END = rep.SEED_SCAN_END

INSTANCES_PER_FORM = rep.INSTANCES_PER_FORM
BLOCK_N = rep.BLOCK_N

#: Frozen input pins (recomputed from disk at build time; fail closed on drift).
AUDIT_PATH = rep.AUDIT_PATH
REGISTRATION_200_PATH = rep.REGISTRATION_PATH
SCOPE_PATH = census.SCOPE_PATH
CENSUS_PATH = census.CENSUS_PATH

AUDIT_CONTENT_HASH = rep.AUDIT_CONTENT_HASH if hasattr(rep, "AUDIT_CONTENT_HASH") \
    else "5242e9cfa35e3a77c54045475428dd617cf93cb16d464b55ad679adc35f80a83"
PREREGISTRATION_HASH = "ff186a066e6af093ecc383e668d948bdca7c1ef8f84b5752b88db47960a6ec6d"
SCOPE_CONTENT_HASH = census.SCOPE_CONTENT_HASH
CENSUS_CONTENT_HASH = "ee0ba3a1714828b3e39834280a0a2eb7850f1cc0526463eb59d3bc4b7026fe14"

#: k bands for the pilot-versus-potentially-confirmatory classification.
#: The attainable exact two-sided sign-flip floor is 2/2^k; a potentially
#: confirmatory design at unadjusted alpha = .05 needs k >= 6 (floor 0.03125).
K_BANDS = (
    {"k": 4, "floor": "0.125", "classification": "pilot (descriptive/estimation only)"},
    {"k": 5, "floor": "0.0625", "classification": "descriptive/estimation only"},
    {"k": 6, "floor": "0.03125",
     "classification": "potentially confirmatory, subject to all other gates"},
    {"k": 7, "floor": "0.015625",
     "classification": "potentially confirmatory, subject to all other gates"},
)

#: Reserved live output paths (proposed, currently absent). They live under
#: runs/next-phase/ — not runs/epic-126/next-phase/ — because the frozen #200
#: scan (runs/epic-126/**/*.json[l]) picks up instance ids from any file under
#: runs/epic-126/ and would break the frozen prior-instance-id pin (8945 ids,
#: sha256 429e8c54…) once a live journal exists. This matches the P02/P03
#: precedent of keeping next-phase artifacts outside runs/epic-126/.
REGISTRATION_ID = "jev-discovery-v1"
DISCOVERY_DIR = f"runs/next-phase/{FAMILY}/{REGISTRATION_ID}"
PATHS = {
    "registration": str(REGISTRATION_PATH),
    "discovery_journal": f"{DISCOVERY_DIR}/jev-discovery-collection.jsonl",
    "discovery_report": f"{DISCOVERY_DIR}/jev-discovery-collection-report.json",
    "exploratory_replay_journal": f"{DISCOVERY_DIR}/jev-exploratory-replay.jsonl",
    "exploratory_replay_report": f"{DISCOVERY_DIR}/jev-exploratory-replay-report.json",
}

#: Frozen cost model (USD per million tokens), carried from the #200
#: registration. Every bound below is retry inclusive.
LING_PROMPT_USD_PER_MTOK = rep.LING_PROMPT_USD_PER_MTOK
LING_COMPLETION_USD_PER_MTOK = rep.LING_COMPLETION_USD_PER_MTOK
LING_INPUT_TOKEN_CEILING = rep.LING_INPUT_TOKEN_CEILING
LING_OUTPUT_TOKEN_CEILING = rep.LING_OUTPUT_TOKEN_CEILING
JEV_INPUT_USD_PER_MTOK = rep.JEV_INPUT_USD_PER_MTOK
JEV_INPUT_TOKEN_CEILING = rep.JEV_INPUT_TOKEN_CEILING


class DesignClassificationError(ValueError):
    """Fail-closed classification, build or verification violation."""


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _content_hash(document: Mapping[str, Any]) -> str:
    payload = json.dumps({key: value for key, value in document.items()
                          if key != "registration_hash"}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _render(document: Mapping[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n"


# --------------------------------------------------------------------------
# design classification
# --------------------------------------------------------------------------

def classify_design(census_document: Mapping[str, Any]) -> dict[str, Any]:
    """Classify the design from the P03 census: k, floor, pilot vs confirmatory.

    The attainable exact two-sided sign-flip floor is 2/2^k. A potentially
    confirmatory design at unadjusted alpha = .05 needs k >= 6 (floor 0.03125);
    k = 4 and k = 5 are descriptive/estimation only. With k = 4 the floor is
    0.125 > 0.05, so the hypothesis design is a pilot, not potentially
    confirmatory, and remains descriptive even for a fresh-seed replication.
    """
    capacity = census_document.get("form_capacity") or {}
    k = int(capacity.get("k"))
    if k != 4:
        raise DesignClassificationError(f"expected k = 4 from the P03 census, found {k}")
    floor = 2 / (2 ** k)
    if floor > 0.05:
        classification = "pilot"
        pilot_vs = ("pilot (descriptive/estimation only): k = 4 < 6, so the design is a "
                    "pilot, not potentially confirmatory; no dichotomous rejection at "
                    "alpha = 0.05 is attainable at any effect size on this family")
    else:
        classification = "potentially confirmatory"
        pilot_vs = (f"potentially confirmatory: k = {k} >= 6, subject to all other gates")
    return {
        "k": k,
        "attainable_two_sided_sign_flip_floor": str(floor),
        "floor_above_0_05": floor > 0.05,
        "classification": classification,
        "pilot_vs_potentially_confirmatory": pilot_vs,
        "k_bands": [dict(band) for band in K_BANDS],
        "fresh_seed_replication": ("descriptive only; a fresh-seed replication block "
                                   "cannot become confirmatory on this family"),
        "h0": "Delta = 0",
        "h1": "Delta < 0",
        "estimand": "equal-weight form mean of real-minus-placebo entropy",
        "experimental_unit": "prompt form",
        "guards_never_filter_the_estimate": True,
        "no_planning_low_effect_size_prior": True,
        "distinct_seed_ids_are_not_independent_forms": True,
        "statement": ("the hypothesis form space is closed at k = 4 (P03 census), so the "
                      "attainable exact two-sided sign-flip floor is 2/2^4 = 0.125 > 0.05. "
                      "No dichotomous rejection at alpha = 0.05 is attainable at any effect "
                      "size on this family. The design is a pilot (descriptive/estimation "
                      "only), not potentially confirmatory; a potentially confirmatory "
                      "design needs k >= 6. hypothesis remains descriptive, including for "
                      "its fresh-seed replication block. Guards never filter the estimate; "
                      "all forms and missingness are reported without imputation. No "
                      "planning-low effect-size prior is used anywhere. Distinct seed ids "
                      "are not independent forms; the experimental unit is the prompt form."),
    }


# --------------------------------------------------------------------------
# fixed N and manifest
# --------------------------------------------------------------------------

def _discovery_manifest(family: str) -> dict[str, Any]:
    """Fixed-N discovery manifest: first 4 seeds per form, ascending, on the
    discovery window. Rebuilt from the generator; must match the #200 audit
    primary block (same window, same selection rule)."""
    forms: dict[str, list[int]] = {}
    for seed in range(DISCOVERY_BASE, DISCOVERY_BASE + DISCOVERY_WINDOW):
        instance = rep.instance_for(family, seed)
        forms.setdefault(rep.pre_read_form_id(instance), []).append(seed)
    manifest = []
    for form in sorted(forms):
        chosen = sorted(forms[form])[:INSTANCES_PER_FORM]
        if len(chosen) != INSTANCES_PER_FORM:
            raise DesignClassificationError(
                f"form {form} has only {len(chosen)} seeds in the discovery window")
        for seed in chosen:
            instance = rep.instance_for(family, seed)
            manifest.append({"instance_id": instance.instance_id, "seed": seed,
                             "prompt_form_id": form})
    if len(manifest) != BLOCK_N:
        raise DesignClassificationError(
            f"discovery manifest must have exactly {BLOCK_N} instances")
    membership: dict[str, list[str]] = {}
    for entry in manifest:
        membership.setdefault(str(entry["prompt_form_id"]), []).append(
            str(entry["instance_id"]))
    return {
        "block": "discovery",
        "window": {"base": DISCOVERY_BASE, "end": DISCOVERY_END,
                   "window": DISCOVERY_WINDOW},
        "selection_rule": ("first INSTANCES_PER_FORM seeds per form in ascending seed "
                           "order within the window; fixed N; no outcome-based stopping"),
        "instances_per_form": INSTANCES_PER_FORM,
        "block_n": BLOCK_N,
        "manifest": manifest,
        "form_membership": {form: sorted(ids) for form, ids in sorted(membership.items())},
        "manifest_hash": _digest(manifest),
    }


# --------------------------------------------------------------------------
# treatment and route
# --------------------------------------------------------------------------

def _treatment() -> dict[str, Any]:
    """Original L4X communication treatment, carried from the #200 draft."""
    from . import jev_coverage_manifest_preregistration_v7 as prv7
    from . import jev_ling_writer_v3 as w3
    from . import jev_ling_writer_v5 as w5
    from . import jev_writer_ladder_v5 as ladder
    from . import jev_replay_preregistration as pr
    return {
        "mode": "exact-original-comm-bridge",
        "family": FAMILY,
        "complexity": "low",
        "regime": "N",
        "generator_version": tf.GENERATOR_VERSION,
        "agents": ["A", "B"],
        "turns": 2,
        "primary_direction": "one-way B->A",
        "final_receiver": "A via Jev Choice wire v2",
        "exposure_id": "jev-finalizer",
        "visibility": ("peer-only board rows; the Jev receiver A sees only accepted "
                       "B-authored claims; rejected writes are never visible"),
        "ownership": ("accepted board writes require exact instance.holds_claim "
                      "ownership; non_owned_claim is rejected and journaled"),
        "board_evidence": ("an accepted board_write by the writer whose normalized_claim "
                          "and raw_text equal the claim and whose receiver_id is A, "
                          "followed by an A peer_read_exposure with a nonempty exposure_id "
                          "and read sequence strictly after the write; rejected or missing "
                          "evidence yields no event"),
        "writer_prompt": rep.prompt_binding(),
        "writer_transport": {
            "model": prv7.PAID_LING_MODEL,
            "endpoint": pr.LING_ENDPOINT,
            "key_loader": "behavioral_discovery._api_key",
            "temperature": pr.LING_TEMPERATURE,
            "token_budget": ladder.EXACT_BRIDGE_TOKEN_BUDGET,
            "pacing_algorithm": w3.LING_PACING_ALGORITHM,
            "min_attempt_interval_seconds": w3.LING_MIN_ATTEMPT_INTERVAL_SECONDS,
            "backoff_initial_seconds": w3.LING_BACKOFF_INITIAL_SECONDS,
            "backoff_max_seconds": w3.LING_BACKOFF_MAX_SECONDS,
            "max_retries": w3.LING_MAX_RETRIES,
            "retryable_statuses": list(w3.LING_RETRYABLE_STATUSES),
            "supported_retry_headers": list(w3.LING_SUPPORTED_RETRY_HEADERS),
            "writer_outcomes_version": w5.WRITER_OUTCOMES_VERSION,
            "writer_parser_version": w5.WRITER_PARSER_VERSION,
        },
    }


def _route() -> dict[str, Any]:
    """Paid Ling route and Jev receiver, carried from the #200 draft."""
    from . import jev_coverage_manifest_preregistration_v7 as prv7
    from . import jev_ling_writer_v3 as w3
    from . import jev_choice_v2 as jc2
    from . import jev_choice as jc
    from . import jev_replay_preregistration as pr
    from . import jev_replay_preregistration_v2 as prv2
    from . import jev_replay_preregistration_v4 as prv4
    return {
        "ling": {
            "model": prv7.PAID_LING_MODEL,
            "endpoint": pr.LING_ENDPOINT,
            "key_loader": "behavioral_discovery._api_key",
            "route": "paid OpenRouter SKU (the free SKU is not routable)",
            "temperature": pr.LING_TEMPERATURE,
            "pacing": "ling-writer-openrouter-pacing-v3, 3.25 s between physical attempts",
            "pacing_algorithm": w3.LING_PACING_ALGORITHM,
            "min_attempt_interval_seconds": w3.LING_MIN_ATTEMPT_INTERVAL_SECONDS,
            "max_retries": w3.LING_MAX_RETRIES,
            "retryable_statuses": list(w3.LING_RETRYABLE_STATUSES),
        },
        "jev": {
            "model": pr.JEV_REPLAY_MODEL,
            "endpoint": pr.JEV_REPLAY_ENDPOINT,
            "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
            "protocol_key": prv4.prv6_protocol_key(),
            "max_retries": pr.JEV_REPLAY_MAX_RETRIES,
            "retryable_statuses": sorted(jc.JEV_RETRYABLE_STATUSES),
            "timeout_seconds": jc.JEV_TIMEOUT_DEFAULT,
            "backoff": {"initial_seconds": jc.JEV_BACKOFF_INITIAL,
                        "max_seconds": jc.JEV_BACKOFF_MAX,
                        "jitter": jc.JEV_BACKOFF_JITTER},
        },
        "normalization": {
            "policy": prv2.normalization_policy(),
            "policy_hash": prv2.normalization_policy_hash(),
            "tiers": ["exact", "complete_renormalized"],
            "hard_ceiling": 0.05,
            "rule": "normalize every accepted vector before any metric",
        },
    }


# --------------------------------------------------------------------------
# budgets
# --------------------------------------------------------------------------

def _cost_model() -> dict[str, Any]:
    ling_call = (LING_INPUT_TOKEN_CEILING * LING_PROMPT_USD_PER_MTOK
                 + LING_OUTPUT_TOKEN_CEILING * LING_COMPLETION_USD_PER_MTOK) / 1_000_000
    jev_call = JEV_INPUT_TOKEN_CEILING * JEV_INPUT_USD_PER_MTOK / 1_000_000
    return {"ling_worst_physical_call_usd": round(ling_call, 12),
            "jev_worst_physical_call_usd": round(jev_call, 12),
            "ling_input_token_ceiling": LING_INPUT_TOKEN_CEILING,
            "ling_output_token_ceiling": LING_OUTPUT_TOKEN_CEILING,
            "jev_input_token_ceiling": JEV_INPUT_TOKEN_CEILING,
            "ling_prompt_usd_per_mtok": LING_PROMPT_USD_PER_MTOK,
            "ling_completion_usd_per_mtok": LING_COMPLETION_USD_PER_MTOK,
            "jev_input_usd_per_mtok": JEV_INPUT_USD_PER_MTOK}


def _budgets() -> dict[str, Any]:
    """One discovery block (16 instances): collection then optional replay.

    Collection: 16 x 4 Ling (2 agents x 2 turns) + 16 x 1 Jev (one final read
    per instance). Exploratory replay: at most one event per collected
    instance x 3 branches (real/placebo/null). Every bound is retry inclusive
    (x3 physical per logical call).
    """
    ling_logical = BLOCK_N * 4
    jev_collection = BLOCK_N * 1
    replay_events_max = BLOCK_N
    jev_replay = replay_events_max * 3
    ling_physical = ling_logical * 3
    jev_collection_physical = jev_collection * 3
    jev_replay_physical = jev_replay * 3
    cost = _cost_model()
    collection_worst = (ling_physical * cost["ling_worst_physical_call_usd"]
                        + jev_collection_physical * cost["jev_worst_physical_call_usd"])
    replay_worst = jev_replay_physical * cost["jev_worst_physical_call_usd"]
    return {
        "discovery_collection": {
            "planned": {"ling": ling_logical, "jev": jev_collection,
                        "combined": ling_logical + jev_collection},
            "physical": {"ling": ling_physical, "jev": jev_collection_physical,
                         "combined": ling_physical + jev_collection_physical},
            "cost_ceiling_usd": 0.20,
            "worst_case_cost_usd": round(collection_worst, 12),
            "next_call_reservation_usd": {
                "ling": round(cost["ling_worst_physical_call_usd"] * 3, 12),
                "jev": round(cost["jev_worst_physical_call_usd"] * 3, 12)},
        },
        "exploratory_replay": {
            "planned": {"jev": jev_replay, "ling": 0, "combined": jev_replay},
            "physical": {"jev": jev_replay_physical, "ling": 0,
                         "combined": jev_replay_physical},
            "events_max": replay_events_max,
            "branches": 3,
            "cost_ceiling_usd": 0.10,
            "worst_case_cost_usd": round(replay_worst, 12),
            "next_call_reservation_usd": {
                "jev": round(cost["jev_worst_physical_call_usd"] * 3, 12)},
        },
        "program": {
            "planned": {"ling": ling_logical, "jev": jev_collection + jev_replay,
                        "combined": ling_logical + jev_collection + jev_replay},
            "physical": {"ling": ling_physical,
                         "jev": jev_collection_physical + jev_replay_physical,
                         "combined": ling_physical + jev_collection_physical
                         + jev_replay_physical},
            "cost_ceiling_usd": 0.30,
            "worst_case_cost_usd": round(collection_worst + replay_worst, 12),
            "arithmetic": ("1 block x (collection: 16 x 4 Ling + 16 x 1 Jev; "
                           "exploratory replay: <=16 events x 3 Jev), each x "
                           "(1 + max_retries 2)"),
        },
        "cost_model": cost,
        "block_n": BLOCK_N,
    }


# --------------------------------------------------------------------------
# stops, paths, coverage rules
# --------------------------------------------------------------------------

def _stops() -> list[str]:
    return [
        "request or cost cap before the next call",
        "model drift",
        "protocol-key drift",
        "request/state/option identity drift",
        "malformed, non-finite, negative or option-mismatched vector",
        "hard normalization deviation above 0.05",
        "argmax shift after normalization",
        "output collision (journal or report already exists)",
        "registration, source, treatment or geometry hash drift",
        "writer terminal errors (empty_output, truncated_output, unparsed_output, "
        "invalid_answer, writer_error, rate-limited)",
        "two consecutive terminal provider failures",
    ]


def _coverage_rules() -> dict[str, Any]:
    """Permissible within-form missingness and complete-case scope, frozen
    before collection. A missing entire form blocks confirmation of the
    registered full-form estimand; no imputation, no seed replacement, no
    form removal after outcomes."""
    return {
        "permissible_within_form_missingness": ("up to 3 of 4 seeds per form may be "
                                                "missing; at least 1 complete instance "
                                                "per form is required"),
        "min_complete_per_form": 1,
        "instances_per_form": INSTANCES_PER_FORM,
        "complete_case_scope": ("the set of planned instances with all required fields: "
                                "structural need, emission/silence, ownership, board "
                                "write/read exposure, and information; reported by stage, "
                                "form, and branch with reasons"),
        "missing_entire_form": ("blocks confirmation of the registered full-form "
                                "estimand; label any available-form estimate descriptive"),
        "no_imputation": True,
        "no_seed_replacement": True,
        "no_form_removal_after_outcomes": True,
        "selection_risk": ("if within-form missingness is not random, the complete-case "
                           "estimate may be biased; the registration freezes the "
                           "permissible missingness before collection and reports the "
                           "resulting complete-case scope and selection risk"),
        "discovery_screen_requirements": [
            "every registered form must have at least one instance with structural need "
            "(finalizer_needs_peer)",
            "every registered form must have at least one instance with voluntary emission "
            "(B-authored claim) or recorded silence",
            "every registered form must have at least one instance with verified B ownership "
            "and an accepted board write followed by A read exposure",
        ],
        "exploratory_replay_requirements": [
            "every registered form must have at least one complete real/placebo pair",
            "a missing entire form blocks the full-form estimand; the available-form "
            "estimate is descriptive",
        ],
        "reporting": ("report planned, attempted, emitted, eligible, replayed, valid, "
                      "complete, and missing counts by stage, form, and branch, with "
                      "reasons; average valid complete pairs within their frozen forms, "
                      "regardless of guards"),
    }


# --------------------------------------------------------------------------
# registration build
# --------------------------------------------------------------------------

def build_registration(repo_root: Path) -> dict[str, Any]:
    """Deterministic, offline discovery registration build. No provider call."""
    root = Path(repo_root)

    audit = _load_json(root / AUDIT_PATH)
    if audit.get("audit_content_hash") != AUDIT_CONTENT_HASH:
        raise DesignClassificationError("#200 audit content hash drift")
    registration_200 = _load_json(root / REGISTRATION_200_PATH)
    if registration_200.get("preregistration_hash") != PREREGISTRATION_HASH:
        raise DesignClassificationError("#200 registration hash drift")
    scope = _load_json(root / SCOPE_PATH)
    if scope.get("content_hash") != SCOPE_CONTENT_HASH:
        raise DesignClassificationError("P02 scope freeze content hash drift")
    census_document = _load_json(root / CENSUS_PATH)
    if census_document.get("content_hash") != CENSUS_CONTENT_HASH:
        raise DesignClassificationError("P03 census content hash drift")

    family = audit["family_selection"]["selected_family"]
    if family != FAMILY:
        raise DesignClassificationError(f"family drift: {family}")

    classification = classify_design(census_document)
    manifest = _discovery_manifest(family)
    budgets = _budgets()
    route = _route()
    treatment = _treatment()

    # The discovery manifest must match the #200 audit primary block (same
    # window, same selection rule); the P02 scope freeze relabeled that block
    # as the discovery-stage window.
    audit_primary = audit["blocks"]["primary"]["manifest"]
    if manifest["manifest"] != audit_primary:
        raise DesignClassificationError(
            "discovery manifest disagrees with the #200 audit primary block")

    document: dict[str, Any] = {
        "preregistration_version": REGISTRATION_VERSION,
        "status": DRAFT_STATUS,
        "stage": "hypothesis:low discovery screen and optional exploratory replay",
        "issue": "#205",
        "parent_issue": "#201",
        "root_issue": "#159",
        "family": family,
        "complexity": "low",
        "regime": "N",
        "offline_only": True,
        "protocol": "docs/jev-discovery-confirmation-plan.md",
        "authorizes": ("nothing beyond P05 planning; no provider call, no collection, "
                       "no registration lock, no live run"),
        "reuse": ("#200 audit/registration reused as input evidence (hash-pinned); "
                  "P02 scope freeze and P03 census reused as input evidence "
                  "(hash-pinned); frozen artifacts preserved byte-for-byte"),
        "input_evidence": {
            "audit_200": {"path": str(AUDIT_PATH),
                          "audit_content_hash": audit["audit_content_hash"],
                          "file_sha256": _sha256_file(root / AUDIT_PATH)},
            "registration_200": {"path": str(REGISTRATION_200_PATH),
                                 "preregistration_hash": registration_200["preregistration_hash"],
                                 "file_sha256": _sha256_file(root / REGISTRATION_200_PATH)},
            "scope_freeze_p02": {"path": str(SCOPE_PATH),
                                 "content_hash": scope["content_hash"],
                                 "file_sha256": _sha256_file(root / SCOPE_PATH)},
            "census_p03": {"path": str(CENSUS_PATH),
                           "content_hash": census_document["content_hash"],
                           "file_sha256": _sha256_file(root / CENSUS_PATH)},
        },
        "design_classification": classification,
        "fixed_n": {
            "instances_per_form": INSTANCES_PER_FORM,
            "form_count": classification["k"],
            "block_n": BLOCK_N,
            "block": "discovery",
            "window": {"base": DISCOVERY_BASE, "end": DISCOVERY_END,
                       "window": DISCOVERY_WINDOW},
            "selection_rule": manifest["selection_rule"],
            "manifest": manifest["manifest"],
            "form_membership": manifest["form_membership"],
            "manifest_hash": manifest["manifest_hash"],
            "matches_200_audit_primary_block": True,
        },
        "treatment": treatment,
        "route": route,
        "budgets": budgets,
        "stops": _stops(),
        "paths": dict(PATHS),
        "path_lifecycle": {
            "fresh_paths": True,
            "resume": False,
            "append": False,
            "overwrite": False,
            "path_overrides": False,
            "rule": ("each phase writes only its own registered paths; a stopped run "
                     "requires a new registration and a new review before any fresh "
                     "attempt"),
            "location_note": ("reserved live output paths live under runs/next-phase/, "
                              "not runs/epic-126/next-phase/, because the frozen #200 "
                              "scan (runs/epic-126/**/*.json[l]) picks up instance ids "
                              "from any file under runs/epic-126/ and would break the "
                              "frozen prior-instance-id pin once a live journal exists; "
                              "this matches the P02/P03 precedent"),
        },
        "coverage_rules": _coverage_rules(),
        "exploratory_replay": {
            "status": "optional; separately covered by P05 authorization",
            "label": "exploratory; never confirmatory",
            "branches": ["real", "placebo", "null"],
            "real": ("the exact accepted B-owned claim for the pre-read state, bound per "
                     "instance as B's single owned private clue"),
            "placebo": ("controller-injected source-neutral re-presentation of a "
                        "receiver-already-known A clue with I_m = 0 and no feasible-set "
                        "reduction, same envelope as the real arm"),
            "null": "no message",
            "fixed_across_branches": ["receiver model", "option set", "wording", "target",
                                      "timing", "pre-read state C"],
            "only_difference": "state.visible_messages",
            "estimand": "equal-weight form mean of real-minus-placebo entropy",
            "inference": ("descriptive only; k = 4 floor 0.125 > 0.05, so no "
                          "significance-style claim is made"),
            "may_not_pool_with_held_out": True,
        },
        "inference_plan": {
            "primary_test": "exhaustive two-sided cluster sign-flip over the k form means",
            "interval": "form-mean t interval with df = k - 1 (k = 4 => df = 3)",
            "alpha": 0.05,
            "direction_requirement": "the observed equal-form mean must be negative",
            "minimum_forms_for_confirmatory": 6,
            "minimum_form_rule": ("a dichotomous confirmatory claim requires at least six "
                                  "distinct prompt forms; fewer than six is descriptive "
                                  "(k = 4 and k = 5) or replay-coverage failure"),
            "attainable_two_sided_floor_by_k": {str(band["k"]): band["floor"]
                                                for band in K_BANDS},
            "k_from_census": classification["k"],
            "consequence": ("k = 4 < 6, so the attainable exact two-sided sign-flip "
                            "floor is 0.125 > 0.05; no dichotomous rejection at "
                            "alpha = 0.05 is attainable at any effect size on this family"),
            "prohibited_as_primary": ["instance-level t-test", "instance-level Wilcoxon test",
                                      "instance-weighted mean",
                                      "treating events as independent states"],
            "imputation": "never impute missing pairs",
            "guards": {"target_probability_delta": 0.0, "feasible_set_mass_epsilon": 0.01,
                       "reporting": ("reported separately by form and event; never used to "
                                     "filter the primary entropy estimate"),
                       "useful_uptake_rule": ("an entropy drop alone is never useful uptake "
                                              "when either guard fails")},
            "interval_half_width": {
                "formula": "t(0.975, k-1) x SD_between / sqrt(k)",
                "label": ("illustrative interval half-width, not a power-based MDE; the "
                          "planning-low estimate and p-value are not used as a prior or an "
                          "effect-size guarantee"),
                "not_a_prior": True,
            },
            "missingness": {
                "complete_pair": "real and placebo both valid",
                "primary_requirement": "at least one complete pair in every registered form",
                "below_six_forms": "descriptive/estimation only",
                "missing_entire_form": ("blocks confirmation of the registered full-form "
                                        "estimand; label any available-form estimate "
                                        "descriptive"),
            },
        },
        "multiplicity": {
            "family_level_control": "Holm step-down across the registered family set",
            "registered_family_set": [family],
            "registered_family_count": 1,
            "single_family_reduction": ("with exactly one registered family the "
                                        "Holm-adjusted p equals the raw p; no "
                                        "cross-family claim follows"),
            "family_set_frozen_before_outcomes": True,
            "future_families": ("any additional family requires its own preregistration "
                                "and its own discovery/confirmation blocks; it may never "
                                "be added to this family set after outcomes are visible"),
            "forbidden": ["sweeping families and selecting a winner post hoc",
                          "adding a family after outcomes are visible",
                          "removing a registered family after outcomes are visible"],
        },
        "authorization": {
            "separate_live_authorization_required_after_locking": True,
            "locking_is_not_authorization": True,
            "approval_must_be_a_supplied_reference": True,
            "approval_may_not_be_inferred_from_locking": True,
            "pending_review": [
                "reviewer decision on the design classification (k = 4, floor 0.125, pilot)",
                "reviewer decision on the fixed-N discovery manifest and selection rule",
                "reviewer decision on treatment/route, budgets, stops, paths and coverage "
                "rules",
                "a separate explicit live authorization reference is required before any "
                "provider call; locking this registration is not that authorization",
            ],
        },
        "non_claims": [
            "no population-level claim", "no cross-family claim", "no calibration claim",
            "no instance-level claim", "no unique-information claim",
            "no generalization beyond the registered forms",
            "no use of the planning-low estimate or p-value as a prior or effect-size "
            "guarantee",
            "no post-hoc family sweep or winner selection",
            "no confirmatory claim from the k = 4 design or its fresh-seed replication",
        ],
        "deterministic_rebuild": {
            "builder": "src/apart_incident_response/jev_p04_design_classification.py",
            "rebuild_command": "python -m apart_incident_response.jev_p04_design_classification --repo-root .",
            "byte_reproducible": True,
        },
    }
    document["registration_hash"] = _content_hash(document)
    return document


def write_registration(document: Mapping[str, Any], *, repo_root: Path) -> Path:
    target = Path(repo_root) / REGISTRATION_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        handle.write(_render(document))
    return target


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

def verify_registration(document: Mapping[str, Any], *, repo_root: Path) -> dict[str, Any]:
    """Fail-closed verification: rebuild, compare byte-for-byte, run checks."""
    root = Path(repo_root)
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

    errors: list[str] = []

    check("registration_version", document.get("preregistration_version") == REGISTRATION_VERSION,
          document.get("preregistration_version"))
    check("status_is_draft", document.get("status") == DRAFT_STATUS,
          document.get("status"))
    check("approval_not_inferred_from_locking",
          document.get("authorization", {}).get("locking_is_not_authorization") is True
          and document.get("authorization", {}).get("approval_may_not_be_inferred_from_locking") is True
          and document.get("authorization", {}).get("separate_live_authorization_required_after_locking") is True,
          None)

    try:
        rebuilt = build_registration(root)
        check("registration_rebuilds_byte_for_byte", rebuilt == document, None)
        check("registration_file_is_byte_reproducible",
              (root / REGISTRATION_PATH).read_text(encoding="utf-8") == _render(rebuilt), None)
    except (DesignClassificationError, OSError, json.JSONDecodeError) as exc:
        check("registration_rebuilds_byte_for_byte", False, f"{type(exc).__name__}: {exc}")

    classification = document.get("design_classification") or {}
    check("k_is_4", classification.get("k") == 4, classification.get("k"))
    check("attainable_floor_is_0_125",
          classification.get("attainable_two_sided_sign_flip_floor") == "0.125",
          classification.get("attainable_two_sided_sign_flip_floor"))
    check("floor_above_0_05", classification.get("floor_above_0_05") is True, None)
    check("classification_is_pilot", classification.get("classification") == "pilot",
          classification.get("classification"))
    check("pilot_vs_potentially_confirmatory_recorded",
          "pilot" in str(classification.get("pilot_vs_potentially_confirmatory"))
          and "not potentially confirmatory" in str(classification.get("pilot_vs_potentially_confirmatory")),
          classification.get("pilot_vs_potentially_confirmatory"))
    check("k_bands_recorded",
          [band.get("k") for band in classification.get("k_bands", [])] == [4, 5, 6, 7],
          classification.get("k_bands"))
    check("fresh_seed_replication_descriptive",
          "descriptive only" in str(classification.get("fresh_seed_replication")),
          classification.get("fresh_seed_replication"))
    check("h0_h1_recorded",
          classification.get("h0") == "Delta = 0" and classification.get("h1") == "Delta < 0",
          None)
    check("estimand_recorded",
          classification.get("estimand") == "equal-weight form mean of real-minus-placebo entropy",
          classification.get("estimand"))
    check("guards_never_filter",
          classification.get("guards_never_filter_the_estimate") is True, None)
    check("no_planning_low_prior",
          classification.get("no_planning_low_effect_size_prior") is True, None)
    check("distinct_seed_ids_not_independent_forms",
          classification.get("distinct_seed_ids_are_not_independent_forms") is True, None)

    fixed_n = document.get("fixed_n") or {}
    check("fixed_n_block_n_16", fixed_n.get("block_n") == 16, fixed_n.get("block_n"))
    check("fixed_n_instances_per_form_4",
          fixed_n.get("instances_per_form") == 4, fixed_n.get("instances_per_form"))
    check("fixed_n_form_count_4", fixed_n.get("form_count") == 4,
          fixed_n.get("form_count"))
    check("fixed_n_window",
          fixed_n.get("window", {}).get("base") == DISCOVERY_BASE
          and fixed_n.get("window", {}).get("end") == DISCOVERY_END,
          fixed_n.get("window"))
    manifest = fixed_n.get("manifest") or []
    check("manifest_has_16_instances", len(manifest) == 16, len(manifest))
    counts = Counter(entry.get("prompt_form_id") for entry in manifest)
    check("manifest_4_per_form",
          all(count == INSTANCES_PER_FORM for count in counts.values()) and len(counts) == 4,
          dict(counts))
    check("manifest_matches_200_audit_primary_block",
          fixed_n.get("matches_200_audit_primary_block") is True, None)

    budgets = document.get("budgets") or {}
    collection = budgets.get("discovery_collection") or {}
    replay = budgets.get("exploratory_replay") or {}
    program = budgets.get("program") or {}
    cost = budgets.get("cost_model") or {}
    check("budget_arithmetic",
          collection.get("planned", {}).get("ling") == BLOCK_N * 4
          and collection.get("planned", {}).get("jev") == BLOCK_N
          and collection.get("physical", {}).get("ling") == BLOCK_N * 4 * 3
          and collection.get("physical", {}).get("jev") == BLOCK_N * 3
          and replay.get("planned", {}).get("jev") == BLOCK_N * 3
          and replay.get("physical", {}).get("jev") == BLOCK_N * 9, None)
    check("cost_model_matches_registered_rates",
          cost.get("ling_worst_physical_call_usd") == round(
              (8192 * 0.06 + 1024 * 0.18) / 1_000_000, 12)
          and cost.get("jev_worst_physical_call_usd") == round(8192 * 0.042 / 1_000_000, 12),
          cost)
    check("cost_within_ceiling",
          program.get("worst_case_cost_usd", 1e9) <= program.get("cost_ceiling_usd", 0.0)
          and collection.get("worst_case_cost_usd", 1e9)
          <= collection.get("cost_ceiling_usd", 0.0)
          and replay.get("worst_case_cost_usd", 1e9) <= replay.get("cost_ceiling_usd", 0.0),
          {"program": program.get("worst_case_cost_usd"),
           "collection": collection.get("worst_case_cost_usd"),
           "replay": replay.get("worst_case_cost_usd")})

    stops = document.get("stops") or []
    check("terminal_stops_registered",
          any("output collision" in str(item) for item in stops)
          and any("hash drift" in str(item) for item in stops)
          and any("cost cap" in str(item) for item in stops), len(stops))

    paths = document.get("paths") or {}
    check("paths_registered",
          all(key in paths for key in ("registration", "discovery_journal", "discovery_report",
                                       "exploratory_replay_journal", "exploratory_replay_report")),
          sorted(paths))
    live_paths = {key: str(path) for key, path in paths.items() if key != "registration"}
    check("paths_are_fresh",
          not any((root / path).exists() for path in live_paths.values()),
          sorted(path for path in live_paths.values() if (root / path).exists()))
    check("paths_outside_epic_126",
          all(not str(path).startswith("runs/epic-126/") for path in paths.values()),
          sorted(paths))

    coverage = document.get("coverage_rules") or {}
    check("coverage_rules_registered",
          coverage.get("no_imputation") is True
          and coverage.get("no_seed_replacement") is True
          and coverage.get("no_form_removal_after_outcomes") is True
          and coverage.get("min_complete_per_form") == 1, None)
    check("coverage_missing_entire_form_rule",
          "blocks confirmation" in str(coverage.get("missing_entire_form"))
          and "descriptive" in str(coverage.get("missing_entire_form")),
          coverage.get("missing_entire_form"))

    inference = document.get("inference_plan") or {}
    check("six_form_minimum",
          inference.get("minimum_forms_for_confirmatory") == 6,
          inference.get("minimum_forms_for_confirmatory"))
    check("interval_half_width_labeled_not_mde",
          "not a power-based MDE" in str(inference.get("interval_half_width", {}).get("label")),
          inference.get("interval_half_width"))
    check("no_imputation_registered",
          inference.get("imputation") == "never impute missing pairs", None)
    check("guards_never_filter_registered",
          "never used to filter" in str(inference.get("guards", {}).get("reporting")), None)

    exploratory = document.get("exploratory_replay") or {}
    check("exploratory_replay_labeled_exploratory",
          "exploratory" in str(exploratory.get("label"))
          and "never confirmatory" in str(exploratory.get("label")),
          exploratory.get("label"))
    check("exploratory_replay_descriptive_only",
          "descriptive only" in str(exploratory.get("inference")),
          exploratory.get("inference"))

    evidence = document.get("input_evidence") or {}
    check("input_evidence_hashes_match",
          evidence.get("audit_200", {}).get("audit_content_hash") == AUDIT_CONTENT_HASH
          and evidence.get("registration_200", {}).get("preregistration_hash") == PREREGISTRATION_HASH
          and evidence.get("scope_freeze_p02", {}).get("content_hash") == SCOPE_CONTENT_HASH
          and evidence.get("census_p03", {}).get("content_hash") == CENSUS_CONTENT_HASH,
          None)
    check("input_evidence_file_hashes_match",
          evidence.get("audit_200", {}).get("file_sha256") == _sha256_file(root / AUDIT_PATH)
          and evidence.get("registration_200", {}).get("file_sha256")
          == _sha256_file(root / REGISTRATION_200_PATH)
          and evidence.get("scope_freeze_p02", {}).get("file_sha256") == _sha256_file(root / SCOPE_PATH)
          and evidence.get("census_p03", {}).get("file_sha256") == _sha256_file(root / CENSUS_PATH),
          None)

    return {"mode": f"{REGISTRATION_VERSION}-verification", "ok": not errors,
            "errors": errors, "failed": [entry["check"] for entry in checks
                                         if not entry["ok"]],
            "checks": checks,
            "registration_hash": document.get("registration_hash"),
            "status": document.get("status"),
            "provider_calls": 0}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="P04 design classification and discovery registration "
                    "(offline; deterministic rebuild; zero provider calls)")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--build", action="store_true",
                        help="write the registration artifact to its fresh path (never overwrites)")
    args = parser.parse_args(argv)
    root = Path(args.repo_root) if args.repo_root is not None else Path(__file__).resolve().parents[2]

    if args.build:
        document = build_registration(root)
        write_registration(document, repo_root=root)
        print(json.dumps({"mode": REGISTRATION_VERSION, "status": DRAFT_STATUS,
                          "path": str(REGISTRATION_PATH),
                          "registration_hash": document["registration_hash"],
                          "provider_calls": 0}, indent=2, sort_keys=True))
        return 0

    path = root / REGISTRATION_PATH
    if not path.is_file():
        print(json.dumps({"mode": REGISTRATION_VERSION, "status": "missing",
                          "path": str(REGISTRATION_PATH),
                          "provider_calls": 0}, indent=2, sort_keys=True))
        return 2
    document = _load_json(path)
    verification = verify_registration(document, repo_root=root)
    print(json.dumps(verification, indent=2, sort_keys=True, allow_nan=False))
    return 0 if verification["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "REGISTRATION_VERSION", "REGISTRATION_PATH", "DRAFT_STATUS", "FAMILY",
    "DISCOVERY_BASE", "DISCOVERY_WINDOW", "DISCOVERY_END", "INSTANCES_PER_FORM",
    "BLOCK_N", "AUDIT_PATH", "REGISTRATION_200_PATH", "SCOPE_PATH", "CENSUS_PATH",
    "AUDIT_CONTENT_HASH", "PREREGISTRATION_HASH", "SCOPE_CONTENT_HASH",
    "CENSUS_CONTENT_HASH", "K_BANDS", "REGISTRATION_ID", "DISCOVERY_DIR", "PATHS",
    "DesignClassificationError", "classify_design", "build_registration",
    "write_registration", "verify_registration", "main",
]
