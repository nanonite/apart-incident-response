"""#158 — successor Jev Choice replay registration v2 (offline lock).

Successor to the locked v1 registration in
:mod:`apart_incident_response.jev_replay_preregistration`. v1 is preserved
byte-for-byte and is not overwritten, reinterpreted or pooled with v2. This
module builds the capture-then-judge v2 registration, its normalization policy
block, its changed source/treatment hashes, its fresh versioned output paths,
and a separately gated repeat diagnostic registration for the identical
``COMM_CONTROL`` request. It also provides a repository-backed verifier that
rejects v1 protocol keys, v1 output paths, settings/hash drift and tolerance
drift.

Locking is separate from authorizing live collection: the locked v2
registration always carries ``live_collection_authorized: false``. No API calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import jev_choice as jc
from . import jev_choice_v2 as jc2
from . import jev_replay_preregistration as pr
from . import task_families as tf


JEV_REPLAY_V2_PREREG_VERSION = "stage2-jev-choice-replay-v2"
JEV_REPLAY_V2_DRAFT_STATUS = "draft_pending_review_v2"
JEV_REPLAY_V2_LOCKED_STATUS = "locked_for_jev_choice_replay_v2"
JEV_REPLAY_V2_PROTOCOL_PREFIX = jc2.JEV_V2_PROTOCOL_KEY_PREFIX

#: Fresh versioned paths. No v1 path may appear as a v2 output.
DEFAULT_JOURNAL_V2 = Path("runs/epic-126/jev-choice-pilot-v2.jsonl")
DEFAULT_OUTPUT_V2 = Path("runs/epic-126/jev-choice-replay-preregistration-v2.json")
DEFAULT_REPORT_V2 = Path("runs/epic-126/jev-choice-pilot-report-v2.json")
DEFAULT_DIAGNOSTICS_V2 = Path("runs/epic-126/jev-choice-normalization-diagnostics-v2.json")
DEFAULT_PROBE_V2 = Path("runs/epic-126/jev-choice-normalization-probe-v2.json")

#: v1 output paths the v2 verifier must refuse.
OLD_OUTPUT_PATHS = (
    "runs/epic-126/jev-choice-replay-preregistration.json",
    "runs/epic-126/jev-choice-pilot.jsonl",
    "runs/epic-126/jev-choice-pilot-report.json",
)

JEV_REPLAY_V2_SOURCE_FILES = (
    "src/apart_incident_response/task_families.py",
    "src/apart_incident_response/communication_protocol.py",
    "src/apart_incident_response/jev_protocol.py",
    "src/apart_incident_response/jev_choice.py",
    "src/apart_incident_response/jev_choice_v2.py",
    "src/apart_incident_response/jev_replay.py",
    "src/apart_incident_response/jev_replay_inference.py",
    "src/apart_incident_response/jev_normalization_sensitivity.py",
    "src/apart_incident_response/jev_choice_pilot_v2.py",
    "src/apart_incident_response/jev_normalization_probe_v2.py",
)

#: Frozen diagnostic-probe constants (the probe is prepared, never executed here).
PROBE_REQUEST_HASH_PREFIX = "2ba516131bdb"
PROBE_REQUEST_HASH_FULL = "2ba516131bdb635c3fe972dbe2c017fd512bbd2727c054eb84bc8530cab403c1"
PROBE_K_RANGE = (12, 20)
PROBE_K = 16
PROBE_MAX_RETRIES = pr.JEV_REPLAY_MAX_RETRIES
PROBE_REQUEST_CAP = PROBE_K * (PROBE_MAX_RETRIES + 1)
PROBE_INPUT_TOKEN_CEILING = pr.JEV_REPLAY_INPUT_TOKEN_CEILING
PROBE_INPUT_USD_PER_MTOK = pr.JEV_REPLAY_INPUT_USD_PER_MTOK
PROBE_COST_CAP_USD = 0.25
PROBE_REJECTION_RATES_AT = (1e-6, 0.01, 0.03)
PROBE_STOP_ABSOLUTE_DEVIATION = jc2.HARD_DEVIATION_CEILING

DETERMINISM_STANCE = {
    "seed_supported": False,
    "temperature_supported": False,
    "evidence": ("the official Choice request contract (docs/jev-choice-wire-contract.md) and the pinned "
                 "local jev-dsl fixture expose only model/state/questions; no seed or temperature field "
                 "is documented or present"),
    "request_fields_sent": ["model", "state", "questions"],
    "field_sending_rule": ("do not send seed or temperature unless official/local evidence explicitly "
                           "supports them"),
    "classification": "stochastic",
    "consequence": ("repeated samples per prompt form are required; diagnostic repetitions of one frozen "
                    "request are not independent prompt forms"),
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_files_hash(repo_root: Path) -> str:
    digest = hashlib.sha256()
    missing = []
    for relative in JEV_REPLAY_V2_SOURCE_FILES:
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


def normalization_policy() -> dict[str, Any]:
    return {
        "capture_then_judge": True,
        "raw_provider_envelope_retained": False,
        "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
        "tiers": {
            "exact": {"max_absolute_deviation": jc2.EXACT_DEVIATION_TOLERANCE, "inclusive": True,
                      "renormalized": True, "material_correction": False, "valid": True},
            "complete_renormalized": {"min_absolute_deviation_exclusive": jc2.EXACT_DEVIATION_TOLERANCE,
                                      "max_absolute_deviation": jc2.PRIMARY_ACCEPTANCE_BOUND,
                                      "boundary_inclusive_with_machine_epsilon": True,
                                      "boundary_epsilon": jc2.NORMALIZATION_BOUNDARY_EPSILON,
                                      "renormalized": True, "material_correction": True, "valid": True},
            "not_normalized_suspect": {"min_absolute_deviation_exclusive": jc2.PRIMARY_ACCEPTANCE_BOUND,
                                       "max_absolute_deviation": jc2.HARD_DEVIATION_CEILING,
                                       "renormalized": False, "valid": False,
                                       "role": "sensitivity diagnostic only; not accepted"},
            "not_normalized_hard": {"min_absolute_deviation_exclusive": jc2.HARD_DEVIATION_CEILING,
                                    "renormalized": False, "valid": False,
                                    "role": "invalid; triggers the registered hard stop"},
        },
        "renormalization": {
            "formula": "p_normalized[i] = p_raw[i] / sum(p_raw)",
            "applied_to": "every accepted vector (exact and complete_renormalized)",
            "exact_tier_rescale": "within 1e-6; usually a numerical no-op but applied for one invariant",
            "material_correction_band": "complete_renormalized",
            "argmax_preservation_required": True,
            "fail_closed_class": "argmax_shifted_on_renormalization",
        },
        "raw_vs_normalized_metrics": {
            "normalized_vector_used_for": ["entropy_bits", "p_target", "feasible_mass", "brier_score",
                                           "log_loss", "selection_validation",
                                           "downstream_replay_inference"],
            "raw_retained_separately": ["raw_probabilities", "raw_probability_sum",
                                        "signed_normalization_deviation",
                                        "absolute_normalization_deviation"],
        },
        "sensitivity_grid": list(jc2.SENSITIVITY_GRID),
        "quantization_bound": jc2.QUANTIZATION_BOUND,
        "hard_ceiling": jc2.HARD_DEVIATION_CEILING,
        "diagnostics_fields": [
            "option_count", "raw_probability_sum", "signed_normalization_deviation",
            "absolute_normalization_deviation", "minimum_probability", "maximum_probability",
            "zero_count", "all_finite", "all_nonnegative", "shape_valid", "invalid_classes",
            "raw_argmax_set", "normalization_tier", "renormalized", "argmax_preserved",
            "normalization_adjustment", "entropy_raw_bits", "entropy_normalized_bits",
        ],
        "invalidity": {
            "never_repaired": ["empty", "missing", "nonnumeric", "non_finite", "negative",
                               "option_mismatched"],
            "exact_option_identity_required": True,
            "raw_vector_retained_on_invalid": "when safe (finite); non-finite values are encoded as strings",
            "malformed_envelope_may_lack_vector": True,
        },
        "policy_fingerprint": "",
    }


def normalization_policy_hash() -> str:
    policy = normalization_policy()
    policy.pop("policy_fingerprint", None)
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode("utf-8")).hexdigest()


def treatment_hash_v2() -> str:
    """Register the generator treatment plus the v2 normalization policy."""

    return hashlib.sha256(json.dumps({
        "manifest_treatment_hash": pr.treatment_hash(),
        "normalization_policy_hash": normalization_policy_hash(),
        "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
    }, sort_keys=True).encode("utf-8")).hexdigest()


def output_paths() -> dict[str, str]:
    return {
        "registration": str(DEFAULT_OUTPUT_V2),
        "journal": str(DEFAULT_JOURNAL_V2),
        "report": str(DEFAULT_REPORT_V2),
        "diagnostics": str(DEFAULT_DIAGNOSTICS_V2),
        "probe_registration": str(DEFAULT_PROBE_V2),
    }


def _probe_worst_case_cost_usd() -> float:
    return round(PROBE_REQUEST_CAP * PROBE_INPUT_TOKEN_CEILING * PROBE_INPUT_USD_PER_MTOK / 1_000_000, 9)


def probe_preregistration_hash(document: Mapping[str, Any]) -> str:
    """Canonical hash of a probe document (everything except its own hash)."""

    payload = json.dumps({key: value for key, value in document.items() if key != "probe_hash"},
                         sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_probe_preregistration() -> dict[str, Any]:
    """Prepare (never execute) the separately gated repeat diagnostic."""

    document: dict[str, Any] = {
        "probe_version": "jev-choice-normalization-probe-v2",
        "status": "locked_for_review",
        "execution_authorized": False,
        "live_collection_authorized": False,
        "approval_requirement": ("separate future live approval; this lock is not live authorization"),
        "purpose": ("estimate normalization deviation and rejection rates on the identical COMM_CONTROL "
                    "request whose vector was lost under strict v1, and retain every raw vector"),
        "source": {
            "request_hash_prefix": PROBE_REQUEST_HASH_PREFIX,
            "request_hash_full": PROBE_REQUEST_HASH_FULL,
            "condition": "COMM",
            "visible_messages": [],
            "instance_seed": pr.JEV_REPLAY_SEED_BASE,
            "note": "identical request for COMM and COMM_CONTROL; the v1 run rejected it as not_normalized",
        },
        "design": {
            "k_range": list(PROBE_K_RANGE),
            "recommended_k": PROBE_K,
            "frozen_k": PROBE_K,
            "rationale": ("K=16 sits mid-range: enough repetitions to resolve a sub-1% rejection rate at "
                          "the strict 1e-6 tolerance while keeping the physical-request cap small"),
            "record_every_raw_vector": True,
            "record_every_deviation": True,
            "rejection_rates_at": list(PROBE_REJECTION_RATES_AT),
            "stop_if_absolute_deviation_above": PROBE_STOP_ABSOLUTE_DEVIATION,
            "stop_rule": "not_normalized_hard",
            "independent_prompt_forms": False,
            "note": ("repetitions of one frozen request are stochastic repeats, not independent prompt "
                     "forms; they cannot be used as independent units in the form-level contrast"),
        },
        "caps": {
            "physical_requests": PROBE_REQUEST_CAP,
            "cost_cap_usd": PROBE_COST_CAP_USD,
            "input_token_ceiling": PROBE_INPUT_TOKEN_CEILING,
            "input_usd_per_mtok": PROBE_INPUT_USD_PER_MTOK,
            "worst_case_cost_usd": _probe_worst_case_cost_usd(),
            "max_retries": PROBE_MAX_RETRIES,
        },
        "model_and_protocol": {
            "provider": "jev", "model": pr.JEV_REPLAY_MODEL, "endpoint": pr.JEV_REPLAY_ENDPOINT,
            "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
            "protocol_key": jc2.jev_choice_protocol_key_v2(model=pr.JEV_REPLAY_MODEL,
                                                           endpoint=pr.JEV_REPLAY_ENDPOINT,
                                                           max_retries=PROBE_MAX_RETRIES),
        },
        "determinism": dict(DETERMINISM_STANCE),
        "normalization_policy_hash": normalization_policy_hash(),
        "outputs": {"probe_report": "runs/epic-126/jev-choice-normalization-probe-report-v2.json",
                    "probe_journal": "runs/epic-126/jev-choice-normalization-probe-v2.jsonl"},
    }
    document["probe_hash"] = probe_preregistration_hash(document)
    return document


def build_replay_preregistration_v2(*, journal_path: Path = pr.DEFAULT_JOURNAL,
                                    seed_bases: Sequence[int] = pr.FORM_CAPACITY_SEED_BASES,
                                    approved: bool = False,
                                    repo_root: Path | None = None) -> dict[str, Any]:
    repo_root = repo_root or _repo_root()
    journal = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    j3_hashes = {str(row.get("request_hash")) for row in journal}
    capacity = pr.audit_form_capacity(seed_bases, j3_hashes=j3_hashes)
    sd = pr.between_form_sd(journal)
    forms = pr.frozen_forms()
    policy = normalization_policy()
    probe = build_probe_preregistration()
    base = pr.build_replay_preregistration(journal_path=journal_path, approved=False, repo_root=repo_root)
    worst_case_cost = round(pr.JEV_REPLAY_REQUEST_CAP * pr.JEV_REPLAY_INPUT_TOKEN_CEILING
                            * pr.JEV_REPLAY_INPUT_USD_PER_MTOK / 1_000_000, 9)

    document: dict[str, Any] = {
        "preregistration_version": JEV_REPLAY_V2_PREREG_VERSION,
        "successor_of": {
            "preregistration_version": pr.JEV_REPLAY_PREREG_VERSION,
            "v1_artifact": "runs/epic-126/jev-choice-replay-preregistration.json",
            "v1_preserved_byte_for_byte": True,
            "note": "v1 is not overwritten, reinterpreted, pooled with v2, or resumed",
        },
        "stage": "jev-choice-replay-v2",
        "status": JEV_REPLAY_V2_LOCKED_STATUS if approved else JEV_REPLAY_V2_DRAFT_STATUS,
        "approval_required": not approved,
        "approval": ({"approved": True, "approved_by": "reviewer",
                      "scope": "v2_registration_lock_only", "live_collection_authorized": False}
                     if approved else {"approved": False, "live_collection_authorized": False}),
        "pending_decisions": ([] if approved else [
            "reviewer lock of this v2 registration (separate from any live authorization)",
            "confirm the v2 request/cost caps after the worst-case accounting",
            "confirm the separately gated diagnostic probe K and caps",
        ]),
        "claim_scope": {
            "type": "form-conditioned pilot",
            "statement": ("pilot conditional on the six frozen prompt forms; new seed IDs do not create new "
                          "prompt forms. v2 changes only the probability-vector acceptance policy, never the "
                          "prompt. Not calibration."),
            "forms": 6,
        },
        "experimental_unit": "model-visible pre-read prompt form",
        "estimand": {
            "primary_outcome": "entropy_bits",
            "event_difference": "H_real - H_placebo",
            "form_effect": "within-form mean of the event difference",
            "estimand": "equal-weight mean across distinct forms",
            "directional_prediction": "delta < 0",
            "note": "all metrics use the v2-normalized vector; the raw vector is retained separately",
        },
        "normalization": policy,
        "determinism": dict(DETERMINISM_STANCE),
        "guards": dict(base["guards"]),
        "placebo": dict(base["placebo"]),
        "message_envelope": dict(base["message_envelope"]),
        "board_evidence": base["board_evidence"],
        "eligibility": base["eligibility"],
        "conditions": base["conditions"],
        "decision_rule": base["decision_rule"],
        "inference": base["inference"],
        "complete_pair_rule": base["complete_pair_rule"],
        "missingness": base["missingness"],
        "missing_real_message_rule": base["missing_real_message_rule"],
        "model_and_protocol": {
            "provider": "jev", "model": pr.JEV_REPLAY_MODEL, "endpoint": pr.JEV_REPLAY_ENDPOINT,
            "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
            "protocol_key_prefix": JEV_REPLAY_V2_PROTOCOL_PREFIX,
            "protocol_key": jc2.jev_choice_protocol_key_v2(model=pr.JEV_REPLAY_MODEL,
                                                           endpoint=pr.JEV_REPLAY_ENDPOINT,
                                                           max_retries=pr.JEV_REPLAY_MAX_RETRIES,
                                                           instructions=jc.JEV_CHOICE_INSTRUCTIONS,
                                                           question_id=jc.JEV_QUESTION_ID),
            "ling": "pinned free Ling writer on OpenRouter free quota",
        },
        "ling_contract": pr.ling_contract(),
        "retry_policy": {
            "max_retries": pr.JEV_REPLAY_MAX_RETRIES,
            "retryable_statuses": pr.JEV_REPLAY_RETRYABLE,
            "backoff_seconds": 0.5, "backoff_max_seconds": 5.0,
        },
        "invalidity_classes": sorted(set(jc.INVALID_RESPONSE_CLASSES) | set(jc2.JEV_V2_INVALID_CLASSES)),
        "generator": {
            "generator_version": tf.GENERATOR_VERSION,
            "checker_version": tf.CHECKER_VERSION,
            "source_files": list(JEV_REPLAY_V2_SOURCE_FILES),
            "source_files_hash": _source_files_hash(repo_root),
            "manifest_treatment_hash": pr.treatment_hash(),
            "normalization_policy_hash": normalization_policy_hash(),
            "treatment_hash": treatment_hash_v2(),
        },
        "frozen_forms": forms,
        "form_capacity_audit": capacity,
        "power": {
            "label": "illustrative and secondary", "k_forms": 6, "between_form_sd_bits": sd,
            "sd_caveat": ("the observed J3 between-form SD is from ISO-minus-FULL, not the real-minus-placebo "
                          "estimand; use only as an illustrative sensitivity value, not a plug-in variance"),
            "illustrative_required_forms": {
                "delta_0.10": pr.illustrative_required_forms(0.10, sd) if sd else None,
                "delta_0.20": pr.illustrative_required_forms(0.20, sd) if sd else None,
            },
        },
        "manifest": {
            "family": "planning", "complexity": "low", "regime": "N",
            "seed_base": pr.JEV_REPLAY_SEED_BASE, "per_block": pr.JEV_REPLAY_PER_BLOCK,
            "instance_ids": forms["instance_ids"], "manifest_hash": forms["manifest_hash"],
        },
        "stop_rules": sorted(set(pr.JEV_REPLAY_STOP_RULES) |
                             {"not_normalized_hard", "argmax_shifted_on_renormalization"}),
        "caps": {
            "physical_requests": pr.JEV_REPLAY_REQUEST_CAP,
            "cost_cap_usd": pr.JEV_REPLAY_COST_CAP_USD,
            "input_token_ceiling": pr.JEV_REPLAY_INPUT_TOKEN_CEILING,
            "input_usd_per_mtok": pr.JEV_REPLAY_INPUT_USD_PER_MTOK,
            "worst_case_cost_usd": worst_case_cost,
            "provider_partition": {
                "jev": pr.JEV_REPLAY_JEV_REQUEST_CAP,
                "ling": pr.JEV_REPLAY_LING_REQUEST_CAP,
                "total": pr.JEV_REPLAY_REQUEST_CAP,
                "note": ("each transport enforces its own partition per physical attempt, so retries count "
                         "against that provider's share and the combined total cannot exceed the ceiling"),
            },
            "planned_calls": dict(pr.JEV_REPLAY_PLANNED_CALLS),
            "planned_physical_requests": pr.JEV_REPLAY_PLANNED_REQUESTS,
            "planned_by_provider": {"jev": pr.JEV_REPLAY_PLANNED_JEV_REQUESTS,
                                    "ling": pr.JEV_REPLAY_PLANNED_LING_REQUESTS},
            "retry_reserve": pr.JEV_REPLAY_RETRY_RESERVE,
            "status": ("locked; live_collection_authorized=false" if approved
                       else "draft; not authorized"),
        },
        "outputs": output_paths(),
        "diagnostic_probe": {
            "probe_version": probe["probe_version"],
            "probe_hash": probe["probe_hash"],
            "frozen_k": probe["design"]["frozen_k"],
            "request_cap": probe["caps"]["physical_requests"],
            "cost_cap_usd": probe["caps"]["cost_cap_usd"],
            "execution_authorized": False,
            "live_collection_authorized": False,
            "requires_separate_future_approval": True,
        },
    }
    payload = json.dumps({key: value for key, value in document.items()
                          if key != "preregistration_hash"}, sort_keys=True)
    document["preregistration_hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return document


def verify_against_jev_replay_preregistration_v2(document: Mapping[str, Any], *,
                                                 instance_ids: Sequence[str], model: str,
                                                 endpoint: str, protocol_key: str,
                                                 planned_requests: int | None = None,
                                                 repo_root: Path | None = None) -> dict[str, Any]:
    """Repository-backed v2 verifier. Fails closed on v1 keys, v1 paths, drift and tolerance drift."""

    repo_root = repo_root or _repo_root()
    errors: list[str] = []
    if document.get("status") != JEV_REPLAY_V2_LOCKED_STATUS:
        errors.append("registration is not locked for the Jev Choice replay v2")
    if document.get("approval_required") or not document.get("approval", {}).get("approved"):
        errors.append("reviewer v2 lock approval is missing")
    if document.get("approval", {}).get("live_collection_authorized") is not False:
        errors.append("live collection must not be authorized by the v2 lock")
    if document.get("preregistration_version") != JEV_REPLAY_V2_PREREG_VERSION:
        errors.append("wrong registration version")

    expected = build_replay_preregistration_v2(approved=True, repo_root=repo_root)
    recorded_hash = document.get("preregistration_hash")
    if recorded_hash != expected["preregistration_hash"]:
        errors.append("v2 registration hash drift from the repository state")
    recorded_content = {key: value for key, value in document.items() if key != "preregistration_hash"}
    expected_content = {key: value for key, value in expected.items() if key != "preregistration_hash"}
    if recorded_content != expected_content:
        errors.append("v2 registration settings drift from the repository state")

    model_and_protocol = document.get("model_and_protocol", {})
    if protocol_key != model_and_protocol.get("protocol_key"):
        errors.append("protocol key differs from the locked v2 registration")
    if not jc2.is_jev_v2_protocol_key(str(protocol_key)):
        errors.append("protocol key is not a v2 Jev key")
    if jc.is_jev_protocol_key(str(protocol_key)):
        errors.append("v1 protocol key rejected")
    if str(protocol_key).startswith(jc.JEV_PROTOCOL_KEY_PREFIX):
        errors.append("v1 protocol key prefix rejected")
    if not str(protocol_key).startswith(JEV_REPLAY_V2_PROTOCOL_PREFIX):
        errors.append("protocol key is missing the v2 prefix")
    expected_key = jc2.jev_choice_protocol_key_v2(
        model=model, endpoint=endpoint, max_retries=pr.JEV_REPLAY_MAX_RETRIES,
        instructions=jc.JEV_CHOICE_INSTRUCTIONS, question_id=jc.JEV_QUESTION_ID)
    if protocol_key != expected_key:
        errors.append("protocol key is not reproducible from the locked v2 settings")
    if model != model_and_protocol.get("model"):
        errors.append(f"model {model!r} != locked {model_and_protocol.get('model')!r}")
    if endpoint != model_and_protocol.get("endpoint"):
        errors.append(f"endpoint {endpoint!r} != locked {model_and_protocol.get('endpoint')!r}")

    normalization = document.get("normalization", {})
    if normalization != normalization_policy():
        errors.append("normalization tolerance drift from the frozen v2 policy")
    if normalization.get("sensitivity_grid") != list(jc2.SENSITIVITY_GRID):
        errors.append("sensitivity grid drift")
    tiers = normalization.get("tiers", {})
    if tiers.get("complete_renormalized", {}).get("max_absolute_deviation") \
            != jc2.PRIMARY_ACCEPTANCE_BOUND:
        errors.append("primary acceptance bound drift")
    if tiers.get("complete_renormalized", {}).get("min_absolute_deviation_exclusive") \
            != jc2.EXACT_DEVIATION_TOLERANCE:
        errors.append("exact tolerance drift")
    if tiers.get("not_normalized_hard", {}).get("min_absolute_deviation_exclusive") \
            != jc2.HARD_DEVIATION_CEILING:
        errors.append("hard ceiling drift")

    outputs = document.get("outputs", {})
    output_values = [str(value) for value in outputs.values() if isinstance(value, str)]
    for old in OLD_OUTPUT_PATHS:
        if any(old in value for value in output_values):
            errors.append(f"old v1 output path rejected: {old}")
    if outputs != output_paths():
        errors.append("output paths differ from the fresh v2 paths")

    forms = document.get("frozen_forms", {})
    frozen_ids = list(forms.get("instance_ids", []))
    if sorted(instance_ids) != sorted(frozen_ids):
        errors.append(f"selected instance ids differ from the frozen manifest "
                      f"({len(instance_ids)} selected vs {len(frozen_ids)} expected)")
    if forms.get("paired_forms") != 6:
        errors.append("frozen manifest is not the six paired forms")
    manifest_hash = forms.get("manifest_hash")
    if manifest_hash != hashlib.sha256(json.dumps(frozen_ids, sort_keys=True).encode()).hexdigest():
        errors.append("frozen manifest hash mismatch")

    caps = document.get("caps", {})
    request_cap = caps.get("physical_requests")
    if request_cap != pr.JEV_REPLAY_REQUEST_CAP:
        errors.append("request cap differs from the locked v2 registration")
    if planned_requests is not None and request_cap is not None and planned_requests > request_cap:
        errors.append(f"planned requests {planned_requests} exceed the cap {request_cap}")
    if caps.get("cost_cap_usd") != pr.JEV_REPLAY_COST_CAP_USD:
        errors.append("cost cap differs from the locked v2 registration")
    if float(caps.get("worst_case_cost_usd", 0.0)) > float(caps.get("cost_cap_usd", 0.0)):
        errors.append("worst-case cost exceeds the registered cap")
    return {"ok": not errors, "errors": errors, "expected_protocol_key": expected_key,
            "actual_protocol_key": protocol_key, "expected_instance_ids": frozen_ids,
            "manifest_hash": manifest_hash, "registration_hash": recorded_hash,
            "planned_requests": planned_requests, "request_cap": request_cap,
            "worst_case_cost_usd": caps.get("worst_case_cost_usd")}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E4 successor Jev Choice replay preregistration v2")
    parser.add_argument("--journal", type=Path, default=pr.DEFAULT_JOURNAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_V2)
    parser.add_argument("--probe-output", type=Path, default=DEFAULT_PROBE_V2)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--approve", action="store_true",
                        help="lock the v2 registration (not live authorization)")
    args = parser.parse_args(argv)
    document = build_replay_preregistration_v2(journal_path=args.journal, approved=args.approve,
                                               repo_root=args.repo_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
                           encoding="utf-8")
    probe = build_probe_preregistration()
    args.probe_output.parent.mkdir(parents=True, exist_ok=True)
    args.probe_output.write_text(json.dumps(probe, indent=2, sort_keys=True, allow_nan=False) + "\n",
                                 encoding="utf-8")
    print(json.dumps({
        "preregistration_version": document["preregistration_version"],
        "status": document["status"],
        "live_collection_authorized": document["approval"].get("live_collection_authorized"),
        "protocol_key": document["model_and_protocol"]["protocol_key"],
        "planned_physical_requests": document["caps"]["planned_physical_requests"],
        "request_cap": document["caps"]["physical_requests"],
        "worst_case_cost_usd": document["caps"]["worst_case_cost_usd"],
        "cost_cap_usd": document["caps"]["cost_cap_usd"],
        "preregistration_hash": document["preregistration_hash"],
        "diagnostic_probe_hash": probe["probe_hash"],
        "diagnostic_probe_k": probe["design"]["frozen_k"],
        "diagnostic_probe_request_cap": probe["caps"]["physical_requests"],
        "diagnostic_probe_cost_cap_usd": probe["caps"]["cost_cap_usd"],
        "output": str(args.output),
        "probe_output": str(args.probe_output),
    }, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "JEV_REPLAY_V2_PREREG_VERSION", "JEV_REPLAY_V2_DRAFT_STATUS", "JEV_REPLAY_V2_LOCKED_STATUS",
    "JEV_REPLAY_V2_PROTOCOL_PREFIX", "DEFAULT_JOURNAL_V2", "DEFAULT_OUTPUT_V2", "DEFAULT_REPORT_V2",
    "DEFAULT_DIAGNOSTICS_V2", "DEFAULT_PROBE_V2", "OLD_OUTPUT_PATHS", "JEV_REPLAY_V2_SOURCE_FILES",
    "PROBE_K", "PROBE_K_RANGE", "PROBE_REQUEST_CAP", "PROBE_COST_CAP_USD", "PROBE_REJECTION_RATES_AT",
    "PROBE_STOP_ABSOLUTE_DEVIATION", "PROBE_REQUEST_HASH_PREFIX", "PROBE_REQUEST_HASH_FULL",
    "DETERMINISM_STANCE", "normalization_policy", "normalization_policy_hash", "treatment_hash_v2",
    "output_paths", "probe_preregistration_hash", "build_probe_preregistration",
    "build_replay_preregistration_v2",
    "verify_against_jev_replay_preregistration_v2", "main",
]
