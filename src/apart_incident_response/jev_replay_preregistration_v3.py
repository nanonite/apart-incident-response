"""#186 — successor Jev Choice optional-board pilot registration v3 (offline lock).

Successor to the stopped v2 pilot registration. It freezes the Ling/OpenRouter
pacing repair (writer transport v3) and fresh versioned output paths without
modifying, resuming, pooling with, or reinterpreting the v1 or v2 artifacts. The
Jev codec and normalization policy are unchanged from v2.

Locking is separate from authorizing live collection: the locked v3 registration
always carries ``live_collection_authorized: false``. No API calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import jev_choice as jc
from . import jev_choice_v2 as jc2
from . import jev_ling_writer_v3 as writer_v3
from . import jev_replay_preregistration as pr
from . import jev_replay_preregistration_v2 as prv2
from . import task_families as tf


JEV_REPLAY_V3_PREREG_VERSION = "stage2-jev-choice-replay-v3"
JEV_REPLAY_V3_DRAFT_STATUS = "draft_pending_review_v3"
JEV_REPLAY_V3_LOCKED_STATUS = "locked_for_jev_choice_replay_v3"

DEFAULT_JOURNAL_V3 = Path("runs/epic-126/jev-choice-pilot-v3.jsonl")
DEFAULT_OUTPUT_V3 = Path("runs/epic-126/jev-choice-replay-preregistration-v3.json")
DEFAULT_REPORT_V3 = Path("runs/epic-126/jev-choice-pilot-report-v3.json")

#: All v1 and v2 output paths the v3 verifier must refuse as v3 outputs.
OLD_OUTPUT_PATHS = (
    "runs/epic-126/jev-choice-replay-preregistration.json",
    "runs/epic-126/jev-choice-pilot.jsonl",
    "runs/epic-126/jev-choice-pilot-report.json",
    "runs/epic-126/jev-choice-replay-preregistration-v2.json",
    "runs/epic-126/jev-choice-pilot-v2.jsonl",
    "runs/epic-126/jev-choice-pilot-report-v2.json",
    "runs/epic-126/jev-choice-normalization-probe-v2.json",
    "runs/epic-126/jev-choice-normalization-probe-v2.jsonl",
    "runs/epic-126/jev-choice-normalization-probe-report-v2.json",
    "runs/epic-126/jev-choice-normalization-diagnostics-v2.json",
)

JEV_REPLAY_V3_SOURCE_FILES = (
    "src/apart_incident_response/task_families.py",
    "src/apart_incident_response/communication_protocol.py",
    "src/apart_incident_response/behavioral_discovery.py",
    "src/apart_incident_response/jev_protocol.py",
    "src/apart_incident_response/jev_choice.py",
    "src/apart_incident_response/jev_choice_v2.py",
    "src/apart_incident_response/jev_choice_smoke.py",
    "src/apart_incident_response/jev_replay.py",
    "src/apart_incident_response/jev_replay_inference.py",
    "src/apart_incident_response/jev_normalization_sensitivity.py",
    # v1/v2 runtime dependencies actually imported by the v3 runner.
    "src/apart_incident_response/jev_choice_pilot.py",
    "src/apart_incident_response/jev_replay_preregistration.py",
    "src/apart_incident_response/jev_replay_preregistration_v2.py",
    # Offline repair modules and the registration module itself.
    "src/apart_incident_response/jev_ling_writer_v3.py",
    "src/apart_incident_response/jev_choice_pilot_v3.py",
    "src/apart_incident_response/jev_replay_preregistration_v3.py",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_files_hash(repo_root: Path) -> str:
    digest = hashlib.sha256()
    missing = []
    for relative in JEV_REPLAY_V3_SOURCE_FILES:
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


def writer_transport() -> dict[str, Any]:
    spec = writer_v3.writer_transport_spec()
    spec["writer_transport_hash"] = hashlib.sha256(
        json.dumps(spec, sort_keys=True).encode("utf-8")).hexdigest()
    return spec


def writer_transport_hash() -> str:
    spec = writer_v3.writer_transport_spec()
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode("utf-8")).hexdigest()


def treatment_hash_v3() -> str:
    return hashlib.sha256(json.dumps({
        "manifest_treatment_hash": pr.treatment_hash(),
        "normalization_policy_hash": prv2.normalization_policy_hash(),
        "writer_transport_hash": writer_transport_hash(),
        "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
    }, sort_keys=True).encode("utf-8")).hexdigest()


def output_paths() -> dict[str, str]:
    return {
        "registration": str(DEFAULT_OUTPUT_V3),
        "journal": str(DEFAULT_JOURNAL_V3),
        "report": str(DEFAULT_REPORT_V3),
    }


def build_replay_preregistration_v3(*, journal_path: Path = pr.DEFAULT_JOURNAL,
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
    base = pr.build_replay_preregistration(journal_path=journal_path, approved=False, repo_root=repo_root)
    worst_case_cost = round(pr.JEV_REPLAY_REQUEST_CAP * pr.JEV_REPLAY_INPUT_TOKEN_CEILING
                            * pr.JEV_REPLAY_INPUT_USD_PER_MTOK / 1_000_000, 9)

    document: dict[str, Any] = {
        "preregistration_version": JEV_REPLAY_V3_PREREG_VERSION,
        "successor_of": {
            "v1": {
                "preregistration_version": pr.JEV_REPLAY_PREREG_VERSION,
                "artifact": "runs/epic-126/jev-choice-replay-preregistration.json",
            },
            "v2": {
                "preregistration_version": prv2.JEV_REPLAY_V2_PREREG_VERSION,
                "artifact": "runs/epic-126/jev-choice-replay-preregistration-v2.json",
                "stopped_result": "runs/epic-126/jev-choice-pilot-report-v2.json",
                "stopped_commit": "c555597",
                "stopped_stop_reason": "writer_http_429_rate_limited",
                "immutable": True,
            },
            "note": ("v1 and v2 are not overwritten, resumed, pooled with, or reinterpreted; v3 changes only "
                     "the Ling/OpenRouter writer pacing and re-registers prospectively"),
        },
        "stage": "jev-choice-replay-v3",
        "status": JEV_REPLAY_V3_LOCKED_STATUS if approved else JEV_REPLAY_V3_DRAFT_STATUS,
        "approval_required": not approved,
        "approval": ({"approved": True, "approved_by": "reviewer",
                      "scope": "v3_registration_lock_only", "live_collection_authorized": False}
                     if approved else {"approved": False, "live_collection_authorized": False}),
        "pending_decisions": ([] if approved else [
            "reviewer lock of this v3 registration (separate from any live authorization)",
            "confirm the pacing, retry and cap policy after the stopped v2 429",
            "confirm the fresh v3 output paths before any live successor run",
        ]),
        "claim_scope": {
            "type": "form-conditioned pilot",
            "statement": ("pilot conditional on the six frozen prompt forms; v3 changes only the "
                          "Ling/OpenRouter pacing of the writer transport, never the prompt, the Jev codec "
                          "or the normalization policy. Not calibration."),
            "forms": 6,
        },
        "experimental_unit": "model-visible pre-read prompt form",
        "estimand": dict(prv2.build_replay_preregistration_v2(journal_path=journal_path, approved=False,
                                                              repo_root=repo_root)["estimand"]),
        "normalization": prv2.normalization_policy(),
        "determinism": dict(prv2.DETERMINISM_STANCE),
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
            "protocol_key": jc2.jev_choice_protocol_key_v2(model=pr.JEV_REPLAY_MODEL,
                                                           endpoint=pr.JEV_REPLAY_ENDPOINT,
                                                           max_retries=pr.JEV_REPLAY_MAX_RETRIES,
                                                           instructions=jc.JEV_CHOICE_INSTRUCTIONS,
                                                           question_id=jc.JEV_QUESTION_ID),
            "ling": "pinned free Ling writer on OpenRouter free quota (paced by writer transport v3)",
        },
        "ling_contract": pr.ling_contract(),
        "writer_transport": writer_transport(),
        "retry_policy": {
            "max_retries": pr.JEV_REPLAY_MAX_RETRIES,
            "retryable_statuses": pr.JEV_REPLAY_RETRYABLE,
            "backoff_seconds": 0.5, "backoff_max_seconds": 5.0,
        },
        "invalidity_classes": sorted(set(jc.INVALID_RESPONSE_CLASSES) | set(jc2.JEV_V2_INVALID_CLASSES)),
        "generator": {
            "generator_version": tf.GENERATOR_VERSION,
            "checker_version": tf.CHECKER_VERSION,
            "source_files": list(JEV_REPLAY_V3_SOURCE_FILES),
            "source_files_hash": _source_files_hash(repo_root),
            "manifest_treatment_hash": pr.treatment_hash(),
            "normalization_policy_hash": prv2.normalization_policy_hash(),
            "writer_transport_hash": writer_transport_hash(),
            "treatment_hash": treatment_hash_v3(),
        },
        "frozen_forms": forms,
        "form_capacity_audit": capacity,
        "power": dict(base["power"]),
        "manifest": {
            "family": "planning", "complexity": "low", "regime": "N",
            "seed_base": pr.JEV_REPLAY_SEED_BASE, "per_block": pr.JEV_REPLAY_PER_BLOCK,
            "instance_ids": forms["instance_ids"], "manifest_hash": forms["manifest_hash"],
        },
        "stop_rules": sorted(set(pr.JEV_REPLAY_STOP_RULES) |
                             {"not_normalized_hard", "argmax_shifted_on_renormalization",
                              "writer_rate_limited_terminal"}),
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
                         "against that provider's share and the combined total cannot exceed the ceiling; the "
                         "Ling partition must additionally accommodate the 3.25-second attempt interval"),
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
    }
    payload = json.dumps({key: value for key, value in document.items()
                          if key != "preregistration_hash"}, sort_keys=True)
    document["preregistration_hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return document


def verify_against_jev_replay_preregistration_v3(document: Mapping[str, Any], *,
                                                 instance_ids: Sequence[str], model: str,
                                                 endpoint: str, protocol_key: str,
                                                 writer_interval: float | None = None,
                                                 writer_transport_version: str | None = None,
                                                 planned_requests: int | None = None,
                                                 repo_root: Path | None = None) -> dict[str, Any]:
    """Repository-backed v3 verifier. Fails closed on v1/v2 protocol keys, old
    v1/v2 output paths, and source, timing, retry-policy, model, endpoint,
    manifest, cap or hash drift."""

    repo_root = repo_root or _repo_root()
    errors: list[str] = []
    if document.get("status") != JEV_REPLAY_V3_LOCKED_STATUS:
        errors.append("registration is not locked for the Jev Choice replay v3")
    if document.get("approval_required") or not document.get("approval", {}).get("approved"):
        errors.append("reviewer v3 lock approval is missing")
    if document.get("approval", {}).get("live_collection_authorized") is not False:
        errors.append("live collection must not be authorized by the v3 lock")
    if document.get("preregistration_version") != JEV_REPLAY_V3_PREREG_VERSION:
        errors.append("wrong registration version")
    if document.get("preregistration_version") in (pr.JEV_REPLAY_PREREG_VERSION,
                                                   prv2.JEV_REPLAY_V2_PREREG_VERSION):
        errors.append("v1/v2 registration version rejected")

    expected = build_replay_preregistration_v3(approved=True, repo_root=repo_root)
    recorded_hash = document.get("preregistration_hash")
    if recorded_hash != expected["preregistration_hash"]:
        errors.append("v3 registration hash drift from the repository state")
    recorded_content = {key: value for key, value in document.items() if key != "preregistration_hash"}
    expected_content = {key: value for key, value in expected.items() if key != "preregistration_hash"}
    if recorded_content != expected_content:
        errors.append("v3 registration settings drift from the repository state")

    model_and_protocol = document.get("model_and_protocol", {})
    if protocol_key != model_and_protocol.get("protocol_key"):
        errors.append("protocol key differs from the locked v3 registration")
    if jc.is_jev_protocol_key(str(protocol_key)) or str(protocol_key).startswith(jc.JEV_PROTOCOL_KEY_PREFIX):
        errors.append("v1 protocol key rejected")
    if not jc2.is_jev_v2_protocol_key(str(protocol_key)):
        errors.append("protocol key is not a v2 Jev key")
    expected_key = jc2.jev_choice_protocol_key_v2(
        model=model, endpoint=endpoint, max_retries=pr.JEV_REPLAY_MAX_RETRIES,
        instructions=jc.JEV_CHOICE_INSTRUCTIONS, question_id=jc.JEV_QUESTION_ID)
    if protocol_key != expected_key:
        errors.append("protocol key is not reproducible from the locked v3 settings")
    if model != model_and_protocol.get("model"):
        errors.append(f"model {model!r} != locked {model_and_protocol.get('model')!r}")
    if endpoint != model_and_protocol.get("endpoint"):
        errors.append(f"endpoint {endpoint!r} != locked {model_and_protocol.get('endpoint')!r}")

    transport = document.get("writer_transport", {})
    if transport != writer_transport():
        errors.append("writer transport timing/retry/provenance drift from the frozen v3 policy")
    if transport.get("min_attempt_interval_seconds") != writer_v3.LING_MIN_ATTEMPT_INTERVAL_SECONDS:
        errors.append("Ling minimum attempt interval drift")
    if transport.get("max_server_requested_delay_seconds") != writer_v3.LING_MAX_SERVER_REQUESTED_DELAY_SECONDS:
        errors.append("maximum server-requested delay drift")
    if transport.get("writer_transport_version") != writer_v3.LING_WRITER_TRANSPORT_VERSION:
        errors.append("writer transport version drift")
    if transport.get("supported_retry_headers") != list(writer_v3.LING_SUPPORTED_RETRY_HEADERS):
        errors.append("supported retry header drift")
    if transport.get("retryable_statuses") != list(writer_v3.LING_RETRYABLE_STATUSES):
        errors.append("retryable status drift")
    if transport.get("max_retries") != writer_v3.LING_MAX_RETRIES:
        errors.append("retry count drift")
    if transport.get("backoff_initial_seconds") != writer_v3.LING_BACKOFF_INITIAL_SECONDS \
            or transport.get("backoff_max_seconds") != writer_v3.LING_BACKOFF_MAX_SECONDS:
        errors.append("backoff settings drift")
    if transport.get("provenance_fields") != list(writer_v3.LING_PROVENANCE_FIELDS):
        errors.append("sanitized provenance schema drift")
    if writer_interval is not None and writer_interval != writer_v3.LING_MIN_ATTEMPT_INTERVAL_SECONDS:
        errors.append("instantiated writer interval differs from the locked v3 policy")
    if writer_transport_version is not None \
            and writer_transport_version != writer_v3.LING_WRITER_TRANSPORT_VERSION:
        errors.append("instantiated writer transport version differs from the locked v3 policy")

    if document.get("normalization") != prv2.normalization_policy():
        errors.append("normalization tolerance drift from the frozen v2 policy")
    if document.get("ling_contract") != pr.ling_contract():
        errors.append("Ling model/endpoint/prompt/decoding drift")

    outputs = document.get("outputs", {})
    output_values = [str(value) for value in outputs.values() if isinstance(value, str)]
    for old in OLD_OUTPUT_PATHS:
        if any(old in value for value in output_values):
            errors.append(f"old v1/v2 output path rejected: {old}")
    if outputs != output_paths():
        errors.append("output paths differ from the fresh v3 paths")

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
        errors.append("request cap differs from the locked v3 registration")
    if planned_requests is not None and request_cap is not None and planned_requests > request_cap:
        errors.append(f"planned requests {planned_requests} exceed the cap {request_cap}")
    if caps.get("cost_cap_usd") != pr.JEV_REPLAY_COST_CAP_USD:
        errors.append("cost cap differs from the locked v3 registration")
    if float(caps.get("worst_case_cost_usd", 0.0)) > float(caps.get("cost_cap_usd", 0.0)):
        errors.append("worst-case cost exceeds the registered cap")
    return {"ok": not errors, "errors": errors, "expected_protocol_key": expected_key,
            "actual_protocol_key": protocol_key, "expected_instance_ids": frozen_ids,
            "manifest_hash": manifest_hash, "registration_hash": recorded_hash,
            "planned_requests": planned_requests, "request_cap": request_cap,
            "writer_interval": writer_v3.LING_MIN_ATTEMPT_INTERVAL_SECONDS,
            "writer_transport_version": writer_v3.LING_WRITER_TRANSPORT_VERSION,
            "worst_case_cost_usd": caps.get("worst_case_cost_usd")}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E4 successor Jev Choice optional-board pilot v3")
    parser.add_argument("--journal", type=Path, default=pr.DEFAULT_JOURNAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_V3)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--approve", action="store_true",
                        help="lock the v3 registration (not live authorization)")
    args = parser.parse_args(argv)
    document = build_replay_preregistration_v3(journal_path=args.journal, approved=args.approve,
                                               repo_root=args.repo_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "preregistration_version": document["preregistration_version"],
        "status": document["status"],
        "live_collection_authorized": document["approval"].get("live_collection_authorized"),
        "protocol_key": document["model_and_protocol"]["protocol_key"],
        "writer_transport_version": document["writer_transport"]["writer_transport_version"],
        "writer_min_interval_seconds": document["writer_transport"]["min_attempt_interval_seconds"],
        "writer_max_server_delay_seconds": document["writer_transport"]["max_server_requested_delay_seconds"],
        "planned_physical_requests": document["caps"]["planned_physical_requests"],
        "request_cap": document["caps"]["physical_requests"],
        "worst_case_cost_usd": document["caps"]["worst_case_cost_usd"],
        "cost_cap_usd": document["caps"]["cost_cap_usd"],
        "preregistration_hash": document["preregistration_hash"],
        "output": str(args.output),
    }, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "JEV_REPLAY_V3_PREREG_VERSION", "JEV_REPLAY_V3_DRAFT_STATUS", "JEV_REPLAY_V3_LOCKED_STATUS",
    "DEFAULT_JOURNAL_V3", "DEFAULT_OUTPUT_V3", "DEFAULT_REPORT_V3", "OLD_OUTPUT_PATHS",
    "JEV_REPLAY_V3_SOURCE_FILES", "writer_transport", "writer_transport_hash", "treatment_hash_v3",
    "output_paths", "build_replay_preregistration_v3", "verify_against_jev_replay_preregistration_v3",
    "main",
]
