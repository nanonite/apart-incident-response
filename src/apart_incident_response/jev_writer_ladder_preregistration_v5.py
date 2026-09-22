"""#187 (repaired) — planning-low writer-ladder successor preregistration v5 (offline lock).

Drafts and verifies a fresh successor registration for the observable writer
ladder. It never modifies, resumes, pools with, or reinterprets any v1–v3
artifact. ``live_collection_authorized`` is always false; offline locking is not
live authorization. No API calls.
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
from . import jev_ling_writer_v5 as writer_v5
from . import jev_replay_preregistration as pr
from . import jev_replay_preregistration_v2 as prv2
from . import jev_writer_ladder_v5 as ladder
from . import task_families as tf


WRITER_LADDER_PREREG_VERSION = "stage2-jev-writer-ladder-v5"
WRITER_LADDER_DRAFT_STATUS = "draft_pending_review_v5"
WRITER_LADDER_LOCKED_STATUS = "locked_for_jev_writer_ladder_v5"

DEFAULT_JOURNAL_V5 = Path("runs/epic-126/jev-writer-ladder-v5.jsonl")
DEFAULT_OUTPUT_V5 = Path("runs/epic-126/jev-writer-ladder-preregistration-v5.json")
DEFAULT_REPORT_V5 = Path("runs/epic-126/jev-writer-ladder-report-v5.json")
DEFAULT_AUDIT_V4 = Path("runs/epic-126/jev-writer-treatment-audit-v4.json")

# Non-overlapping sub-partitions: ladder + bridge sum to the combined cap.
JEV_LADDER_REQUEST_CAP = 216
LING_LADDER_REQUEST_CAP = 220
LADDER_REQUEST_CAP = JEV_LADDER_REQUEST_CAP + LING_LADDER_REQUEST_CAP
LADDER_COST_CAP_USD = 0.5
JEV_BRIDGE_REQUEST_CAP = 34
LING_BRIDGE_REQUEST_CAP = 80
COMBINED_JEV_REQUEST_CAP = JEV_LADDER_REQUEST_CAP + JEV_BRIDGE_REQUEST_CAP
COMBINED_LING_REQUEST_CAP = LING_LADDER_REQUEST_CAP + LING_BRIDGE_REQUEST_CAP
COMBINED_REQUEST_CAP = COMBINED_JEV_REQUEST_CAP + COMBINED_LING_REQUEST_CAP
LADDER_INPUT_TOKEN_CEILING = pr.JEV_REPLAY_INPUT_TOKEN_CEILING
LADDER_INPUT_USD_PER_MTOK = pr.JEV_REPLAY_INPUT_USD_PER_MTOK
LADDER_LIVE_RUNGS = [rung for rung in ladder.LADDER_RUNGS if not rung.bridge]
LADDER_RUNG_COUNT = len(LADDER_LIVE_RUNGS)
LADDER_INSTANCE_COUNT = pr.JEV_REPLAY_PER_BLOCK
LADDER_PLANNED_PER_RUNG = LADDER_INSTANCE_COUNT * 2 * 2  # 2 arms x (writer + receiver)
LADDER_PLANNED_REQUESTS = LADDER_RUNG_COUNT * LADDER_PLANNED_PER_RUNG
BRIDGE_PLANNED_PER_INSTANCE = len(ladder.EXACT_BRIDGE_AGENTS) * ladder.EXACT_BRIDGE_TURNS + 1
BRIDGE_PLANNED_REQUESTS = LADDER_INSTANCE_COUNT * BRIDGE_PLANNED_PER_INSTANCE
LADDER_PLANNED_JEV = LADDER_RUNG_COUNT * LADDER_INSTANCE_COUNT * 2
LADDER_PLANNED_LING = LADDER_RUNG_COUNT * LADDER_INSTANCE_COUNT * 2
BRIDGE_PLANNED_JEV = LADDER_INSTANCE_COUNT
BRIDGE_PLANNED_LING = LADDER_INSTANCE_COUNT * len(ladder.EXACT_BRIDGE_AGENTS) * ladder.EXACT_BRIDGE_TURNS
TOTAL_PLANNED_REQUESTS = LADDER_PLANNED_REQUESTS + BRIDGE_PLANNED_REQUESTS
BRIDGE_REQUEST_CAP = JEV_BRIDGE_REQUEST_CAP + LING_BRIDGE_REQUEST_CAP
BRIDGE_JEV_CAP = JEV_BRIDGE_REQUEST_CAP
BRIDGE_LING_CAP = LING_BRIDGE_REQUEST_CAP
BRIDGE_COST_CAP_USD = 0.5

OLD_OUTPUT_PATHS_V5 = (
    "runs/epic-126/jev-choice-replay-preregistration.json",
    "runs/epic-126/jev-choice-pilot.jsonl",
    "runs/epic-126/jev-choice-pilot-report.json",
    "runs/epic-126/jev-choice-replay-preregistration-v2.json",
    "runs/epic-126/jev-choice-pilot-v2.jsonl",
    "runs/epic-126/jev-choice-pilot-report-v2.json",
    "runs/epic-126/jev-choice-replay-preregistration-v3.json",
    "runs/epic-126/jev-choice-pilot-v3.jsonl",
    "runs/epic-126/jev-choice-pilot-report-v3.json",
    "runs/epic-126/jev-writer-ladder-preregistration-v4.json",
    "runs/epic-126/jev-writer-ladder-v4.jsonl",
    "runs/epic-126/jev-writer-ladder-report-v4.json",
)

JEV_WRITER_LADDER_SOURCE_FILES = (
    "src/apart_incident_response/task_families.py",
    "src/apart_incident_response/communication_protocol.py",
    "src/apart_incident_response/communication_runner.py",
    "src/apart_incident_response/behavioral_discovery.py",
    "src/apart_incident_response/jev_protocol.py",
    "src/apart_incident_response/jev_choice.py",
    "src/apart_incident_response/jev_choice_v2.py",
    "src/apart_incident_response/jev_choice_smoke.py",
    "src/apart_incident_response/jev_replay.py",
    "src/apart_incident_response/jev_replay_inference.py",
    "src/apart_incident_response/jev_normalization_sensitivity.py",
    "src/apart_incident_response/jev_choice_pilot.py",
    "src/apart_incident_response/jev_replay_preregistration.py",
    "src/apart_incident_response/jev_replay_preregistration_v2.py",
    "src/apart_incident_response/jev_replay_preregistration_v3.py",
    "src/apart_incident_response/jev_ling_writer_v3.py",
    "src/apart_incident_response/jev_ling_writer_v5.py",
    "src/apart_incident_response/jev_writer_treatment_audit.py",
    "src/apart_incident_response/jev_writer_exact_bridge_v5.py",
    "src/apart_incident_response/jev_writer_ladder_v5.py",
    "src/apart_incident_response/jev_writer_ladder_pilot_v5.py",
    "src/apart_incident_response/jev_writer_ladder_preregistration_v5.py",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_files_hash(repo_root: Path) -> str:
    digest = hashlib.sha256()
    missing = []
    for relative in JEV_WRITER_LADDER_SOURCE_FILES:
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


def output_paths() -> dict[str, str]:
    return {"registration": str(DEFAULT_OUTPUT_V5), "journal": str(DEFAULT_JOURNAL_V5),
            "report": str(DEFAULT_REPORT_V5), "treatment_audit": str(DEFAULT_AUDIT_V4),
            "bridge_journal": "runs/epic-126/jev-writer-exact-bridge-v5.jsonl",
            "bridge_report": "runs/epic-126/jev-writer-exact-bridge-report-v5.json"}


def _worst_case_cost_usd() -> float:
    return round(COMBINED_REQUEST_CAP * LADDER_INPUT_TOKEN_CEILING * LADDER_INPUT_USD_PER_MTOK / 1_000_000, 9)


def treatment_hash_v5() -> str:
    return hashlib.sha256(json.dumps({
        "manifest_treatment_hash": pr.treatment_hash(),
        "normalization_policy_hash": prv2.normalization_policy_hash(),
        "ladder_hash": ladder.ladder_hash(),
        "writer_schema_hash": writer_v5.writer_schema_hash(),
        "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
    }, sort_keys=True).encode("utf-8")).hexdigest()


def build_writer_ladder_preregistration_v5(*, approved: bool = False,
                                           repo_root: Path | None = None) -> dict[str, Any]:
    repo_root = repo_root or _repo_root()
    forms = pr.frozen_forms()
    base = pr.build_replay_preregistration(approved=False, repo_root=repo_root)
    document: dict[str, Any] = {
        "preregistration_version": WRITER_LADDER_PREREG_VERSION,
        "successor_of": {
            "v1": "runs/epic-126/jev-choice-replay-preregistration.json",
            "v2": "runs/epic-126/jev-choice-replay-preregistration-v2.json",
            "v3": "runs/epic-126/jev-choice-replay-preregistration-v3.json",
            "stopped_v3_result": "runs/epic-126/jev-choice-pilot-report-v3.json",
            "stopped_v3_commit": "e6d9630",
            "superseded_v4": "runs/epic-126/jev-writer-ladder-preregistration-v4.json",
            "v4_note": "v4 was never live-approved and is superseded by this repaired v5",
            "immutable": True,
            "note": "v1-v3 are not modified, resumed, pooled with, or reinterpreted; v4 is preserved",
        },
        "stage": "planning-low-writer-ladder",
        "status": WRITER_LADDER_LOCKED_STATUS if approved else WRITER_LADDER_DRAFT_STATUS,
        "approval_required": not approved,
        "approval": ({"approved": True, "approved_by": "reviewer",
                      "scope": "v5_registration_lock_only", "live_collection_authorized": False}
                     if approved else {"approved": False, "live_collection_authorized": False}),
        "pending_decisions": ([] if approved else [
            "reviewer lock of this v5 ladder registration (separate from any live authorization)",
            "confirm the ladder rungs and the L5 INDUCED positive control",
            "confirm the request/cost caps and the missingness reporting",
        ]),
        "purpose": ("resolve why the paced v3 standalone writer produced 17/17 COMM silence by measuring an "
                    "observable writer ladder over the same instances and forms, holding the Jev receiver fixed"),
        "claim_scope": {
            "type": "writer-emission instrumentation ladder",
            "statement": ("emission, exposure, post-read correlation and causal uptake are separate; a rung "
                          "that writes is not causal uptake and no rung may be selected post hoc for a "
                          "confirmatory claim"),
            "forms": 6,
        },
        "writer_ladder": ladder.ladder_schema(),
        "writer_observability": writer_v5.writer_schema(),
        "writer_transport": writer_v3.writer_transport_spec(),
        "interpretation_rules": dict(ladder.INTERPRETATION_RULES),
        "deviation_record": {
            "L4": ("renamed to the full-context standalone writer (approximate original schema); it is "
                   "single-turn B and is not claimed to reproduce the original protocol."),
            "L4X": ("exact original COMM bridge: two agents x two turns, provider_seed, 1024 max tokens, "
                    "evolving visible-message state and the original ANSWER/optional-MESSAGE grammar."),
            "seed_behavior": ("L4X sends provider_seed(instance|condition|turn|agent) and 1024 tokens exactly "
                              "as the original treatment; the standalone rungs send no seed and use "
                              f"{pr.LING_MAX_TOKENS} tokens."),
            "grammar": ("L0-L3 and L5 use the explicit `MESSAGE: <clue> or SILENCE` grammar; L4/L4X use the "
                        "original `ANSWER: <label>` + optional `message:` grammar with answer-only silence."),
        },
        "model_and_protocol": {
            "provider": "jev", "model": pr.JEV_REPLAY_MODEL, "endpoint": pr.JEV_REPLAY_ENDPOINT,
            "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
            "protocol_key": jc2.jev_choice_protocol_key_v2(model=pr.JEV_REPLAY_MODEL,
                                                           endpoint=pr.JEV_REPLAY_ENDPOINT,
                                                           max_retries=pr.JEV_REPLAY_MAX_RETRIES,
                                                           instructions=jc.JEV_CHOICE_INSTRUCTIONS,
                                                           question_id=jc.JEV_QUESTION_ID),
        },
        "ling_contract": pr.ling_contract(),
        "generator": {
            "generator_version": tf.GENERATOR_VERSION,
            "checker_version": tf.CHECKER_VERSION,
            "source_files": list(JEV_WRITER_LADDER_SOURCE_FILES),
            "source_files_hash": _source_files_hash(repo_root),
            "manifest_treatment_hash": pr.treatment_hash(),
            "ladder_hash": ladder.ladder_hash(),
            "writer_schema_hash": writer_v5.writer_schema_hash(),
            "treatment_hash": treatment_hash_v5(),
        },
        "manifest": {
            "family": "planning", "complexity": "low", "regime": "N",
            "seed_base": pr.JEV_REPLAY_SEED_BASE, "per_block": pr.JEV_REPLAY_PER_BLOCK,
            "instance_ids": forms["instance_ids"], "manifest_hash": forms["manifest_hash"],
            "paired_forms": forms["paired_forms"], "iso_form_ids": forms["iso_form_ids"],
        },
        "arms": ["COMM (writer turn + Jev receiver)", "COMM_CONTROL (turn-matched, never writes)"],
        "stop_rules": sorted(set(pr.JEV_REPLAY_STOP_RULES) |
                             {"writer_error_terminal", "writer_rate_limited_terminal",
                              "empty_output", "truncated_output", "unparsed_output", "invalid_answer",
                              "not_normalized_hard", "argmax_shifted_on_renormalization",
                              "output_exists", "report_exists"}),
        "caps": {
            "physical_requests": COMBINED_REQUEST_CAP,
            "cost_cap_usd": LADDER_COST_CAP_USD + BRIDGE_COST_CAP_USD,
            "input_token_ceiling": LADDER_INPUT_TOKEN_CEILING,
            "input_usd_per_mtok": LADDER_INPUT_USD_PER_MTOK,
            "worst_case_cost_usd": _worst_case_cost_usd(),
            "provider_partition": {
                "jev": COMBINED_JEV_REQUEST_CAP, "ling": COMBINED_LING_REQUEST_CAP,
                "total": COMBINED_REQUEST_CAP,
                "note": "combined ceiling; ladder and bridge use non-overlapping sub-partitions whose "
                        "sums equal this ceiling, each per physical attempt with retries included"},
            "ladder_partition": {
                "jev": JEV_LADDER_REQUEST_CAP, "ling": LING_LADDER_REQUEST_CAP,
                "total": LADDER_REQUEST_CAP, "cost_cap_usd": LADDER_COST_CAP_USD,
                "planned_requests": LADDER_PLANNED_REQUESTS,
                "note": "ladder sub-partition; sums with the bridge sub-partition equal the combined cap"},
            "bridge_partition": {
                "jev": JEV_BRIDGE_REQUEST_CAP, "ling": LING_BRIDGE_REQUEST_CAP,
                "total": BRIDGE_REQUEST_CAP, "cost_cap_usd": BRIDGE_COST_CAP_USD,
                "planned_requests": BRIDGE_PLANNED_REQUESTS,
                "note": "bridge sub-partition; sums with the ladder sub-partition equal the combined cap"},
            "planned_requests": TOTAL_PLANNED_REQUESTS,
            "planned_ladder_requests": LADDER_PLANNED_REQUESTS,
            "planned_bridge_requests": BRIDGE_PLANNED_REQUESTS,
            "planned_per_rung": LADDER_PLANNED_PER_RUNG,
            "planned_by_provider": {"jev": LADDER_PLANNED_JEV + BRIDGE_PLANNED_JEV,
                                    "ling": LADDER_PLANNED_LING + BRIDGE_PLANNED_LING},
            "retry_reserve": COMBINED_REQUEST_CAP - TOTAL_PLANNED_REQUESTS,
            "status": ("locked; live_collection_authorized=false" if approved
                       else "draft; not authorized"),
        },
        "missingness_and_reporting": {
            "per_rung": ["planned_cases", "planned_provider_calls", "attempted_cases", "writer_valid",
                         "writer_invalid", "receiver_valid", "receiver_invalid", "receiver_unattempted",
                         "joint_valid", "writer_outcome_counts_by_arm", "exact_owned_accepted_writes",
                         "rejected_claims", "verified_read_exposures", "authoritative_i_m", "i_m_bits",
                         "distinct_forms", "provider_requests", "tokens", "cost", "missingness"],
            "concepts_separate": ["emission", "exposure", "post_read_correlation", "causal_uptake"],
            "induced_excluded_from_voluntary": True,
            "fullness": "partial and missing rows are reported, never dropped or substituted",
        },
        "exact_bridge": {
            "planned_requests": BRIDGE_PLANNED_REQUESTS,
            "physical_requests": BRIDGE_REQUEST_CAP,
            "jev_partition": BRIDGE_JEV_CAP,
            "ling_partition": BRIDGE_LING_CAP,
            "cost_cap_usd": BRIDGE_COST_CAP_USD,
            "turns": ladder.EXACT_BRIDGE_TURNS,
            "agents": list(ladder.EXACT_BRIDGE_AGENTS),
            "token_budget": ladder.EXACT_BRIDGE_TOKEN_BUDGET,
            "seed_algorithm": ladder.EXACT_BRIDGE_SEED_ALGORITHM,
        },
        "outputs": output_paths(),
        "live_collection_authorized": False,
        "analysis_boundary": base["analysis_boundary"] if "analysis_boundary" in base else None,
    }
    payload = json.dumps({key: value for key, value in document.items()
                          if key != "preregistration_hash"}, sort_keys=True)
    document["preregistration_hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return document


def verify_against_writer_ladder_preregistration_v5(document: Mapping[str, Any], *,
                                                    instance_ids: Sequence[str], model: str,
                                                    endpoint: str, protocol_key: str,
                                                    planned_requests: int | None = None,
                                                    repo_root: Path | None = None) -> dict[str, Any]:
    repo_root = repo_root or _repo_root()
    errors: list[str] = []
    if document.get("status") != WRITER_LADDER_LOCKED_STATUS:
        errors.append("registration is not locked for the writer ladder v5")
    if document.get("approval_required") or not document.get("approval", {}).get("approved"):
        errors.append("reviewer v5 lock approval is missing")
    if document.get("approval", {}).get("live_collection_authorized") is not False:
        errors.append("live collection must not be authorized by the v5 lock")
    if document.get("preregistration_version") != WRITER_LADDER_PREREG_VERSION:
        errors.append("wrong registration version")

    expected = build_writer_ladder_preregistration_v5(approved=True, repo_root=repo_root)
    if document.get("preregistration_hash") != expected["preregistration_hash"]:
        errors.append("v5 registration hash drift from the repository state")
    recorded = {key: value for key, value in document.items() if key != "preregistration_hash"}
    wanted = {key: value for key, value in expected.items() if key != "preregistration_hash"}
    if recorded != wanted:
        errors.append("v5 registration settings drift from the repository state")

    model_and_protocol = document.get("model_and_protocol", {})
    if protocol_key != model_and_protocol.get("protocol_key"):
        errors.append("protocol key differs from the locked v5 registration")
    if jc.is_jev_protocol_key(str(protocol_key)):
        errors.append("v1 protocol key rejected")
    if not jc2.is_jev_v2_protocol_key(str(protocol_key)):
        errors.append("protocol key is not a v2 Jev key")
    if protocol_key != jc2.jev_choice_protocol_key_v2(
            model=model, endpoint=endpoint, max_retries=pr.JEV_REPLAY_MAX_RETRIES,
            instructions=jc.JEV_CHOICE_INSTRUCTIONS, question_id=jc.JEV_QUESTION_ID):
        errors.append("protocol key is not reproducible from the locked v5 settings")
    if model != model_and_protocol.get("model") or endpoint != model_and_protocol.get("endpoint"):
        errors.append("model or endpoint differs from the locked v5 registration")

    if document.get("writer_ladder") != ladder.ladder_schema():
        errors.append("writer ladder definitions/templates drift")
    if document.get("writer_observability") != writer_v5.writer_schema():
        errors.append("writer observability schema drift")
    if document.get("writer_transport") != writer_v3.writer_transport_spec():
        errors.append("writer pacing/retry policy drift")
    if document.get("interpretation_rules") != ladder.INTERPRETATION_RULES:
        errors.append("interpretation-rule drift")
    transport = document.get("writer_transport", {})
    if transport.get("min_attempt_interval_seconds") != writer_v3.LING_MIN_ATTEMPT_INTERVAL_SECONDS:
        errors.append("Ling minimum attempt interval drift")
    if transport.get("max_retries") != writer_v3.LING_MAX_RETRIES:
        errors.append("retry count drift")
    if transport.get("supported_retry_headers") != list(writer_v3.LING_SUPPORTED_RETRY_HEADERS):
        errors.append("retry header drift")

    outputs = document.get("outputs", {})
    for old in OLD_OUTPUT_PATHS_V5:
        if any(old in str(value) for value in outputs.values()):
            errors.append(f"old v1/v2/v3/v4 output path rejected: {old}")
    if outputs != output_paths():
        errors.append("output paths differ from the fresh v5 paths")

    forms = document.get("manifest", {})
    if sorted(instance_ids) != sorted(list(forms.get("instance_ids", []))):
        errors.append("instance ids differ from the frozen manifest")
    if forms.get("paired_forms") != 6:
        errors.append("manifest is not the six paired forms")
    if forms.get("manifest_hash") != hashlib.sha256(
            json.dumps(list(forms.get("instance_ids", [])), sort_keys=True).encode()).hexdigest():
        errors.append("manifest hash mismatch")

    caps = document.get("caps", {})
    if caps.get("physical_requests") != COMBINED_REQUEST_CAP:
        errors.append("combined request cap drift")
    if planned_requests is not None and planned_requests > caps.get("physical_requests", 0):
        errors.append("planned requests exceed the cap")
    if caps.get("cost_cap_usd") != LADDER_COST_CAP_USD + BRIDGE_COST_CAP_USD:
        errors.append("combined cost cap drift")
    if float(caps.get("worst_case_cost_usd", 0.0)) > float(caps.get("cost_cap_usd", 0.0)):
        errors.append("worst-case cost exceeds the cap")
    partition = caps.get("provider_partition", {})
    ladder_cap = caps.get("ladder_partition", {})
    bridge_cap = caps.get("bridge_partition", {})
    bridge_block = document.get("exact_bridge", {})
    if (ladder_cap.get("jev", -1) + bridge_cap.get("jev", -1) != partition.get("jev")
            or ladder_cap.get("ling", -1) + bridge_cap.get("ling", -1) != partition.get("ling")):
        errors.append("ladder and bridge sub-partitions overlap or do not sum to the combined partition")
    if partition.get("jev") != COMBINED_JEV_REQUEST_CAP or partition.get("ling") != COMBINED_LING_REQUEST_CAP:
        errors.append("combined provider partition drift")
    if (bridge_block.get("jev_partition") != bridge_cap.get("jev")
            or bridge_block.get("ling_partition") != bridge_cap.get("ling")
            or bridge_block.get("physical_requests") != bridge_cap.get("total")
            or bridge_block.get("cost_cap_usd") != bridge_cap.get("cost_cap_usd")):
        errors.append("exact_bridge caps differ from the bridge sub-partition")
    if bridge_block.get("token_budget") != ladder.EXACT_BRIDGE_TOKEN_BUDGET \
            or bridge_block.get("turns") != ladder.EXACT_BRIDGE_TURNS \
            or list(bridge_block.get("agents", [])) != list(ladder.EXACT_BRIDGE_AGENTS) \
            or bridge_block.get("seed_algorithm") != ladder.EXACT_BRIDGE_SEED_ALGORITHM:
        errors.append("exact_bridge prompt/seed/turn settings drift")
    planned_jev = LADDER_PLANNED_JEV + BRIDGE_PLANNED_JEV
    planned_ling = LADDER_PLANNED_LING + BRIDGE_PLANNED_LING
    if planned_jev > partition.get("jev", 0) or planned_ling > partition.get("ling", 0):
        errors.append("planned calls exceed the combined partition")
    return {"ok": not errors, "errors": errors, "registration_hash": document.get("preregistration_hash"),
            "planned_requests": planned_requests, "request_cap": caps.get("physical_requests"),
            "ladder_hash": ladder.ladder_hash(), "writer_schema_hash": writer_v5.writer_schema_hash()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="#187 planning-low writer-ladder preregistration v4")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_V5)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args(argv)
    document = build_writer_ladder_preregistration_v5(approved=args.approve, repo_root=args.repo_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "preregistration_version": document["preregistration_version"],
        "status": document["status"],
        "live_collection_authorized": document["approval"].get("live_collection_authorized"),
        "ladder_hash": document["writer_ladder"]["ladder_version"],
        "writer_outcomes_version": document["writer_observability"]["writer_outcomes_version"],
        "planned_requests": document["caps"]["planned_requests"],
        "request_cap": document["caps"]["physical_requests"],
        "provider_partition": document["caps"]["provider_partition"],
        "worst_case_cost_usd": document["caps"]["worst_case_cost_usd"],
        "preregistration_hash": document["preregistration_hash"],
        "output": str(args.output),
    }, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "WRITER_LADDER_PREREG_VERSION", "WRITER_LADDER_DRAFT_STATUS", "WRITER_LADDER_LOCKED_STATUS",
    "DEFAULT_JOURNAL_V5", "DEFAULT_OUTPUT_V5", "DEFAULT_REPORT_V5", "DEFAULT_AUDIT_V4",
    "BRIDGE_PLANNED_REQUESTS", "TOTAL_PLANNED_REQUESTS", "BRIDGE_REQUEST_CAP", "BRIDGE_JEV_CAP",
    "BRIDGE_LING_CAP", "BRIDGE_COST_CAP_USD",
    "JEV_LADDER_REQUEST_CAP", "LING_LADDER_REQUEST_CAP", "LADDER_REQUEST_CAP", "LADDER_COST_CAP_USD",
    "JEV_BRIDGE_REQUEST_CAP", "LING_BRIDGE_REQUEST_CAP", "COMBINED_JEV_REQUEST_CAP",
    "COMBINED_LING_REQUEST_CAP", "COMBINED_REQUEST_CAP", "LADDER_PLANNED_JEV", "LADDER_PLANNED_LING",
    "BRIDGE_PLANNED_JEV", "BRIDGE_PLANNED_LING",
    "LADDER_PLANNED_REQUESTS", "OLD_OUTPUT_PATHS_V5", "JEV_WRITER_LADDER_SOURCE_FILES",
    "output_paths", "treatment_hash_v5", "build_writer_ladder_preregistration_v5",
    "verify_against_writer_ladder_preregistration_v5", "main",
]
