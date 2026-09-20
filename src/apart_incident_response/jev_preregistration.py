"""J3d — offline Jev Choice capability/calibration preregistration (#179).

Freezes a versioned registration for a bounded Jev Choice capability and
calibration probe on held-out repaired planning-low instances. Offline only: no
live calls. The registration is a **draft** until a reviewer approves; approving
it does not authorize #180 live collection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import jev_choice as jc
from . import task_families as tf
from .communication_protocol import DependenceRegime, ReasoningComplexity
from .jev_protocol import audit_instance
from .jev_choice_smoke import DEFAULT_MANIFEST as JEV_PLANNING_LOW_MANIFEST


JEV_CAPABILITY_VERSION = "stage2-jev-choice-capability-v1"
JEV_CAPABILITY_STAGE = "jev-choice-capability"
JEV_CAPABILITY_SEED_BASE = 71000
JEV_CAPABILITY_PER_CELL = 17
JEV_CAPABILITY_CONDITIONS = ("ISO", "FULL")
JEV_CAPABILITY_MODEL = jc.JEV_DEFAULT_MODEL
JEV_CAPABILITY_ENDPOINT = jc.JEV_SYSTEMONE_ENDPOINT
JEV_CAPABILITY_MAX_RETRIES = jc.JEV_MAX_RETRIES
JEV_CAPABILITY_PLANNED_REQUESTS = JEV_CAPABILITY_PER_CELL * len(JEV_CAPABILITY_CONDITIONS)
JEV_CAPABILITY_RETRY_RESERVE = JEV_CAPABILITY_PLANNED_REQUESTS
JEV_CAPABILITY_REQUEST_CAP = JEV_CAPABILITY_PLANNED_REQUESTS + JEV_CAPABILITY_RETRY_RESERVE
JEV_CAPABILITY_COST_CAP_USD = 1.0
JEV_CAPABILITY_INPUT_TOKEN_CEILING = 8192
JEV_CAPABILITY_INPUT_USD_PER_MTOK = 0.042
JEV_CAPABILITY_MIN_INTERVAL_SECONDS = 0.25
JEV_CAPABILITY_ALPHA = 0.05
JEV_CAPABILITY_DIAGNOSTICS_NOT_RUN = ("COMM", "ORACLE", "INDUCED", "Noul", "Score")
JEV_CAPABILITY_STOP_RULES = (
    "request_cap", "cost_cap", "repeated_http_failure", "contract_mismatch",
    "model_drift", "missing_checker_evidence",
)
JEV_CAPABILITY_MAX_SEEDS_PER_CELL = 40


def jev_capability_instances(seeds_per_cell: int = JEV_CAPABILITY_PER_CELL) -> list[tf.FamilyInstance]:
    if seeds_per_cell <= 0 or seeds_per_cell > JEV_CAPABILITY_MAX_SEEDS_PER_CELL:
        raise ValueError("invalid Jev capability seeds_per_cell")
    instances = [tf.generate_instance("planning", JEV_CAPABILITY_SEED_BASE + replicate,
                                      DependenceRegime.N, ReasoningComplexity.LOW)
                 for replicate in range(seeds_per_cell)]
    ids = [instance.instance_id for instance in instances]
    if len(set(ids)) != len(ids):
        raise ValueError("Jev capability seed block produced duplicate instance ids")
    return instances


def _cost_ceiling_usd(requests: int) -> float:
    return round(requests * JEV_CAPABILITY_INPUT_TOKEN_CEILING * JEV_CAPABILITY_INPUT_USD_PER_MTOK / 1_000_000, 9)


def build_jev_choice_capability_preregistration(*, repo_root: Path, generator_commit: str | None = None,
                                                approved: bool = False) -> dict[str, Any]:
    """Draft (or lock) the Jev Choice capability/calibration registration."""

    instances = jev_capability_instances()
    instance_ids = [instance.instance_id for instance in instances]
    audits = [audit_instance(instance) for instance in instances]
    if not all(audit["all_pass"] for audit in audits):
        raise ValueError("held-out Jev capability instances failed the leak/invariant audit")

    manifest_hash = hashlib.sha256(json.dumps(instance_ids, sort_keys=True).encode()).hexdigest()
    protocol_key = jc.jev_choice_protocol_key(model=JEV_CAPABILITY_MODEL, endpoint=JEV_CAPABILITY_ENDPOINT,
                                              max_retries=JEV_CAPABILITY_MAX_RETRIES,
                                              instructions=jc.JEV_CHOICE_INSTRUCTIONS,
                                              question_id=jc.JEV_QUESTION_ID)

    manifest_path = repo_root / JEV_PLANNING_LOW_MANIFEST
    disjoint_from: str | None = None
    smoke_ids: list[str] = []
    if manifest_path.is_file():
        planning_low = json.loads(manifest_path.read_text(encoding="utf-8"))
        disjoint_from = planning_low.get("manifest_hash")
        smoke_ids = list(planning_low.get("instance_ids", []))[:2]
        if set(instance_ids) & set(planning_low.get("instance_ids", [])):
            raise ValueError("Jev capability block overlaps the frozen planning-low manifest")

    document: dict[str, Any] = {
        "preregistration_version": JEV_CAPABILITY_VERSION,
        "stage": JEV_CAPABILITY_STAGE,
        "status": "locked_for_jev_choice_capability" if approved else "draft_pending_review",
        "approval_required": not approved,
        "approval": ({"approved": True, "approved_by": "reviewer",
                      "request_cap": JEV_CAPABILITY_REQUEST_CAP,
                      "cost_cap_usd": JEV_CAPABILITY_COST_CAP_USD} if approved
                     else {"approved": False}),
        "approved_decisions": (["Jev Choice capability/calibration probe: 17 held-out planning-low "
                                "instances x ISO/FULL",
                                f"{JEV_CAPABILITY_REQUEST_CAP} physical requests maximum, including "
                                "retries; $1 cost cap",
                                "pinned jev-1.13.0 at the TypeSafe System One endpoint"] if approved else []),
        "pending_decisions": ([] if approved else ["review held-out Jev capability/calibration design and caps"]),
        "proposed_decisions": ([] if approved else [
            "Jev Choice capability/calibration probe on 17 held-out planning-low instances x ISO/FULL",
            f"{JEV_CAPABILITY_REQUEST_CAP}-request and $1 live caps",
        ]),
        "generator_commit": generator_commit,
        "generator_version": tf.GENERATOR_VERSION,
        "checker_version": tf.CHECKER_VERSION,
        "protocol_boundary": {
            "jev_protocol_key": protocol_key,
            "codec_version": jc.JEV_CHOICE_CODEC_VERSION,
            "ling_protocol_key_excluded": True,
            "scaffold_artifacts_excluded": True,
            "note": "Jev artifacts are keyed by the additive Jev protocol key and must not be pooled "
                    "with Ling artifacts or the offline scaffold; the analysis loader refuses mixed keys",
        },
        "provider_settings": {
            "provider": "jev",
            "endpoint": JEV_CAPABILITY_ENDPOINT,
            "model": JEV_CAPABILITY_MODEL,
            "codec_version": jc.JEV_CHOICE_CODEC_VERSION,
            "question_id": jc.JEV_QUESTION_ID,
            "instructions": jc.JEV_CHOICE_INSTRUCTIONS,
            "state_schema": jc.JEV_CHOICE_STATE_SCHEMA,
            "criteria_policy": jc.JEV_CHOICE_CRITERIA_POLICY,
            "option_id_policy": jc.JEV_CHOICE_OPTION_ID_POLICY,
            "normalization_tolerance": jc.NORMALIZATION_TOLERANCE,
            "max_retries": JEV_CAPABILITY_MAX_RETRIES,
            "retryable_statuses": sorted(jc.JEV_RETRYABLE_STATUSES),
            "expected_protocol_key": protocol_key,
        },
        "caps": {
            "min_interval_seconds": JEV_CAPABILITY_MIN_INTERVAL_SECONDS,
            "max_cost_usd": JEV_CAPABILITY_COST_CAP_USD,
            "max_requests": JEV_CAPABILITY_REQUEST_CAP,
            "input_token_ceiling": JEV_CAPABILITY_INPUT_TOKEN_CEILING,
            "input_usd_per_mtok": JEV_CAPABILITY_INPUT_USD_PER_MTOK,
            "estimated_cost_planned_usd": _cost_ceiling_usd(JEV_CAPABILITY_PLANNED_REQUESTS),
            "estimated_cost_ceiling_usd": _cost_ceiling_usd(JEV_CAPABILITY_REQUEST_CAP),
            "stop_rules": list(JEV_CAPABILITY_STOP_RULES),
        },
        "jev_capability": {
            "status": "locked" if approved else "proposed",
            "seed_base": JEV_CAPABILITY_SEED_BASE,
            "per_cell_instances": JEV_CAPABILITY_PER_CELL,
            "instance_ids": instance_ids,
            "instance_seeds": [instance.seed for instance in instances],
            "manifest_hash": manifest_hash,
            "conditions_run": list(JEV_CAPABILITY_CONDITIONS),
            "diagnostics_not_run": list(JEV_CAPABILITY_DIAGNOSTICS_NOT_RUN),
            "planned_requests": JEV_CAPABILITY_PLANNED_REQUESTS,
            "retry_preflight_reserve": JEV_CAPABILITY_RETRY_RESERVE,
            "request_cap": JEV_CAPABILITY_REQUEST_CAP,
            "cost_cap_usd": JEV_CAPABILITY_COST_CAP_USD,
            "held_out": {
                "smoke_instance_ids": smoke_ids,
                "disjoint_from_planning_low_manifest_hash": disjoint_from,
                "note": "J3 capability block (seed base 71000) is disjoint from the wire smoke and the "
                        "frozen planning-low manifest; J5 must use a further disjoint block",
            },
            "leak_audit": {"instances": len(audits),
                           "all_pass": all(audit["all_pass"] for audit in audits)},
        },
        "capability_metrics": {
            "primary": ["full_vector_validity", "option_identity", "normalization", "task_validity_full"],
            "full_vector_validity": "share of attempted cases returning the documented Choice envelope "
                                    "with an exact option-key set and finite in-range probabilities",
            "option_identity": "criteria keys equal the exact sorted public candidate ids and the answer "
                               "probability keys equal them",
            "normalization": "probability sum within the codec normalization tolerance",
            "task_validity_full": "FULL-selected option accepted by the checker on instances whose pooled "
                                  "clues determine a unique target",
            "iso_mass_on_consistent_set": "descriptive: ISO probability mass on the private "
                                          "clue-consistent candidate set",
        },
        "calibration_diagnostics": {
            "primary": ["p_correct", "brier", "log_loss", "reliability_bins"],
            "uncertainty": "Wilson interval for p_correct; reliability bins reported with counts and "
                           "intervals (Newcombe for paired contrasts)",
            "footnote": f"{JEV_CAPABILITY_PER_CELL} held-out instances is a small probe; reliability bins "
                        "are descriptive and do not establish calibration",
            "alpha": JEV_CAPABILITY_ALPHA,
        },
        "go_no_go": {
            "continue_if": ["preflight passes",
                            "full_vector_validity == 1.0 on attempted cases",
                            "task_validity_full >= 0.9 (at most one invalid)",
                            "no stop rule fired"],
            "stop_if": ["any contract mismatch", "resolved model differs from the pinned model",
                        "request or cost cap reached", "task_validity_full below threshold"],
            "decision_owner": "reviewer",
            "note": "a passing probe does not establish calibration and does not authorize #157",
        },
    }
    payload = json.dumps({key: value for key, value in document.items() if key != "preregistration_hash"},
                         sort_keys=True)
    document["preregistration_hash"] = hashlib.sha256(payload.encode()).hexdigest()
    return document


def verify_against_jev_choice_preregistration(document: Mapping[str, Any], *, instance_ids: Sequence[str],
                                              model: str, endpoint: str, codec_version: str,
                                              question_id: str, instructions: str,
                                              planned_requests: int | None = None) -> dict[str, Any]:
    """Verify a planned Jev capability probe against the locked registration."""

    errors: list[str] = []
    if str(document.get("preregistration_version", "")) != JEV_CAPABILITY_VERSION:
        errors.append("not a Jev Choice capability registration")
    if document.get("status") != "locked_for_jev_choice_capability":
        errors.append("registration is not locked for the Jev Choice capability probe")
    if document.get("approval_required") or not document.get("approval", {}).get("approved"):
        errors.append("Jev capability reviewer approval is missing")
    block = document.get("jev_capability", {})
    if block.get("status") != "locked":
        errors.append("Jev capability block is not locked")
    frozen_ids = list(block.get("instance_ids", []))
    if sorted(instance_ids) != sorted(frozen_ids):
        errors.append(f"selected instance ids differ from the frozen Jev manifest "
                      f"({len(instance_ids)} selected vs {len(frozen_ids)} expected)")
    manifest_hash = block.get("manifest_hash")
    recomputed = hashlib.sha256(json.dumps(frozen_ids, sort_keys=True).encode()).hexdigest()
    if manifest_hash != recomputed:
        errors.append("frozen Jev manifest hash mismatch")
    selected_hash = hashlib.sha256(json.dumps(list(instance_ids), sort_keys=True).encode()).hexdigest()
    if manifest_hash is not None and selected_hash != manifest_hash:
        errors.append("selected manifest hash differs from the frozen Jev manifest")
    provider_settings = document.get("provider_settings", {})
    if model != provider_settings.get("model"):
        errors.append(f"model {model!r} != locked {provider_settings.get('model')!r}")
    if endpoint != provider_settings.get("endpoint"):
        errors.append(f"endpoint {endpoint!r} != locked {provider_settings.get('endpoint')!r}")
    if codec_version != provider_settings.get("codec_version"):
        errors.append(f"codec {codec_version!r} != locked {provider_settings.get('codec_version')!r}")
    if question_id != provider_settings.get("question_id"):
        errors.append(f"question id {question_id!r} != locked {provider_settings.get('question_id')!r}")
    if instructions != provider_settings.get("instructions"):
        errors.append("instructions differ from the locked Jev registration")
    actual_key = jc.jev_choice_protocol_key(model=model, endpoint=endpoint,
                                            max_retries=provider_settings.get("max_retries"),
                                            instructions=instructions, question_id=question_id)
    expected_key = provider_settings.get("expected_protocol_key")
    if actual_key != expected_key:
        errors.append("protocol key differs from the locked Jev registration")
    if not jc.is_jev_protocol_key(str(expected_key)):
        errors.append("locked protocol key is not a Jev key")
    request_cap = block.get("request_cap")
    caps = document.get("caps", {})
    if caps.get("max_requests") != request_cap or caps.get("max_cost_usd") != block.get("cost_cap_usd"):
        errors.append("Jev capability active caps disagree with the registered block")
    if planned_requests is not None and request_cap is not None and planned_requests > request_cap:
        errors.append(f"planned requests {planned_requests} exceed the Jev request cap {request_cap}")
    return {"ok": not errors, "errors": errors, "expected_protocol_key": expected_key,
            "actual_protocol_key": actual_key, "expected_instance_ids": frozen_ids,
            "manifest_hash": manifest_hash, "planned_requests": planned_requests, "request_cap": request_cap}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="J3d Jev Choice capability/calibration preregistration")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--generator-commit", default=None)
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    document = build_jev_choice_capability_preregistration(repo_root=args.repo_root,
                                                           generator_commit=args.generator_commit,
                                                           approved=args.approve)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
                               encoding="utf-8")
    print(json.dumps({
        "preregistration_version": document["preregistration_version"],
        "status": document["status"],
        "instance_count": len(document["jev_capability"]["instance_ids"]),
        "conditions": document["jev_capability"]["conditions_run"],
        "manifest_hash": document["jev_capability"]["manifest_hash"],
        "active_instance_count": document["jev_capability"]["per_cell_instances"],
        "active_request_cap": JEV_CAPABILITY_REQUEST_CAP,
        "active_cost_cap_usd": JEV_CAPABILITY_COST_CAP_USD,
        "preregistration_hash": document["preregistration_hash"],
    }, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "JEV_CAPABILITY_VERSION", "JEV_CAPABILITY_STAGE", "JEV_CAPABILITY_SEED_BASE",
    "JEV_CAPABILITY_PER_CELL", "JEV_CAPABILITY_CONDITIONS", "JEV_CAPABILITY_MODEL",
    "JEV_CAPABILITY_ENDPOINT", "JEV_CAPABILITY_MAX_RETRIES", "JEV_CAPABILITY_PLANNED_REQUESTS",
    "JEV_CAPABILITY_RETRY_RESERVE", "JEV_CAPABILITY_REQUEST_CAP", "JEV_CAPABILITY_COST_CAP_USD",
    "JEV_CAPABILITY_INPUT_TOKEN_CEILING", "JEV_CAPABILITY_STOP_RULES",
    "JEV_CAPABILITY_DIAGNOSTICS_NOT_RUN", "jev_capability_instances",
    "build_jev_choice_capability_preregistration", "verify_against_jev_choice_preregistration", "main",
]
