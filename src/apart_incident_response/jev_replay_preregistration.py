"""E4 — Jev Choice replay preregistration, lock, and verifier (#185).

Offline. Audits distinct prompt-form capacity, freezes the six-form pilot
manifest, model/endpoint/protocol hashes, serializer and placebo wording,
condition/turn settings, retry policy, caps, invalidity classes, stop rules and
the missing-real-message rule; and provides a repository-backed verifier that
rejects draft status, hash/settings drift, mixed protocols, wrong manifests and
over-budget plans before any provider call.

The locked registration always carries ``live_collection_authorized: false``:
locking is separate from authorizing live collection. No API calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import jev_choice as jc
from . import jev_preregistration as jp
from . import jev_replay as jr
from . import jev_replay_inference as ji
from . import task_families as tf
from .communication_protocol import DependenceRegime, ReasoningComplexity
from .jev_choice import JEV_CHOICE_CODEC_VERSION, JevChoiceAdapter


JEV_REPLAY_PREREG_VERSION = "stage2-jev-choice-replay-v1"
JEV_REPLAY_DRAFT_STATUS = "draft_pending_review"
JEV_REPLAY_LOCKED_STATUS = "locked_for_jev_choice_replay"
FORM_CAPACITY_SEED_BASES = (70000, 71000, 72000, 73000, 74000)
JEV_REPLAY_SEED_BASE = 72000
JEV_REPLAY_PER_BLOCK = 17
JEV_REPLAY_MODEL = jp.JEV_CAPABILITY_MODEL
JEV_REPLAY_ENDPOINT = jp.JEV_CAPABILITY_ENDPOINT
JEV_REPLAY_MAX_RETRIES = jp.JEV_CAPABILITY_MAX_RETRIES
JEV_REPLAY_RETRYABLE = sorted(jc.JEV_RETRYABLE_STATUSES)
JEV_REPLAY_TURNS = {"ISO": 1, "FULL": 1, "COMM": 2}
JEV_REPLAY_REQUEST_CAP = 300
JEV_REPLAY_COST_CAP_USD = 1.0
#: Worst-case planned physical requests by arm (17 instances each).
JEV_REPLAY_PLANNED_CALLS = {
    "iso_jev_receiver": 17,
    "full_jev_receiver": 17,
    "comm_ling_writer": 17,
    "comm_jev_receiver": 17,
    "comm_control_ling_writer": 17,
    "comm_control_jev_receiver": 17,
}
JEV_REPLAY_PLANNED_REQUESTS = sum(JEV_REPLAY_PLANNED_CALLS.values())
JEV_REPLAY_RETRY_RESERVE = JEV_REPLAY_REQUEST_CAP - JEV_REPLAY_PLANNED_REQUESTS
JEV_REPLAY_INPUT_TOKEN_CEILING = 8192
JEV_REPLAY_INPUT_USD_PER_MTOK = 0.042
JEV_REPLAY_STOP_RULES = ("request_cap", "cost_cap", "repeated_http_failure", "contract_mismatch",
                         "model_drift", "missing_checker_evidence")
JEV_REPLAY_SOURCE_FILES = (
    "src/apart_incident_response/task_families.py",
    "src/apart_incident_response/communication_protocol.py",
    "src/apart_incident_response/jev_protocol.py",
    "src/apart_incident_response/jev_choice.py",
    "src/apart_incident_response/jev_replay.py",
    "src/apart_incident_response/jev_replay_inference.py",
)

DEFAULT_JOURNAL = Path("runs/epic-126/jev-choice-capability.jsonl")
DEFAULT_OUTPUT = Path("runs/epic-126/jev-choice-replay-preregistration.json")


class _NoopClient:
    provider = "jev"
    endpoint = JEV_REPLAY_ENDPOINT
    max_retries = JEV_REPLAY_MAX_RETRIES
    max_physical_requests = None
    physical_attempts = 0

    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:  # pragma: no cover
        raise RuntimeError("preflight client must never issue a request")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_files_hash(repo_root: Path) -> str:
    digest = hashlib.sha256()
    missing = []
    for relative in JEV_REPLAY_SOURCE_FILES:
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


def _forms_for_block(seed_base: int, per_block: int) -> dict[str, str]:
    adapter = JevChoiceAdapter(_NoopClient(), model=JEV_REPLAY_MODEL)
    forms: dict[str, str] = {}
    for replicate in range(per_block):
        instance = tf.generate_instance("planning", seed_base + replicate, DependenceRegime.N,
                                        ReasoningComplexity.LOW)
        for condition in ("ISO", "FULL"):
            forms[adapter.build_state(instance, "A", condition).request_hash] = condition
    return forms


def audit_form_capacity(seed_bases: Sequence[int] = FORM_CAPACITY_SEED_BASES,
                        per_block: int = JEV_REPLAY_PER_BLOCK,
                        j3_hashes: set[str] | None = None) -> dict[str, Any]:
    blocks: dict[str, dict[str, Any]] = {}
    union_conditions: dict[str, str] = {}
    for seed_base in seed_bases:
        forms = _forms_for_block(seed_base, per_block)
        union_conditions.update(forms)
        blocks[str(seed_base)] = {
            "distinct_iso": sum(1 for condition in forms.values() if condition == "ISO"),
            "distinct_full": sum(1 for condition in forms.values() if condition == "FULL"),
            "distinct_total": len(forms),
        }
    if j3_hashes is not None:
        for seed_base, row in blocks.items():
            row["new_forms_vs_j3"] = len(set(_forms_for_block(int(seed_base), per_block)) - j3_hashes)
    distinct_iso = sum(1 for condition in union_conditions.values() if condition == "ISO")
    distinct_full = sum(1 for condition in union_conditions.values() if condition == "FULL")
    return {
        "blocks": blocks,
        "union_distinct_request_forms": len(union_conditions),
        "distinct_iso_forms": distinct_iso,
        "distinct_full_forms": distinct_full,
        "capacity_paired_forms": min(distinct_iso, distinct_full),
        "note": "seed disjointness does not create new prompt forms: the generator yields six paired "
                "ISO/FULL forms across every seed block audited",
        "recommendation": "conditional on the six known frozen forms; a generator redesign is required "
                          "for genuinely new forms",
    }


def frozen_forms(*, seed_base: int = JEV_REPLAY_SEED_BASE,
                 per_block: int = JEV_REPLAY_PER_BLOCK) -> dict[str, Any]:
    """Freeze the 17-instance manifest and the six paired ISO pre-read form IDs."""

    adapter = JevChoiceAdapter(_NoopClient(), model=JEV_REPLAY_MODEL)
    instance_ids: list[str] = []
    iso_forms: dict[str, str] = {}
    for replicate in range(per_block):
        instance = tf.generate_instance("planning", seed_base + replicate, DependenceRegime.N,
                                        ReasoningComplexity.LOW)
        instance_ids.append(instance.instance_id)
        iso_forms[adapter.build_state(instance, "A", "ISO").request_hash] = instance.instance_id
    form_ids = sorted(iso_forms)
    return {
        "seed_base": seed_base,
        "per_block": per_block,
        "paired_forms": len(form_ids),
        "iso_form_ids": form_ids,
        "instance_ids": instance_ids,
        "manifest_hash": hashlib.sha256(json.dumps(instance_ids, sort_keys=True).encode()).hexdigest(),
        "form_manifest_hash": hashlib.sha256(json.dumps(form_ids, sort_keys=True).encode()).hexdigest(),
    }


def treatment_hash(*, seed_base: int = JEV_REPLAY_SEED_BASE,
                   per_block: int = JEV_REPLAY_PER_BLOCK) -> str:
    """Hash the generated, model-visible treatment behind the frozen manifest."""

    adapter = JevChoiceAdapter(_NoopClient(), model=JEV_REPLAY_MODEL)
    rows = []
    for replicate in range(per_block):
        instance = tf.generate_instance("planning", seed_base + replicate, DependenceRegime.N,
                                        ReasoningComplexity.LOW)
        rows.append({
            "instance_id": instance.instance_id, "seed": instance.seed,
            "iso_form_id": adapter.build_state(instance, "A", "ISO").request_hash,
            "option_ids": sorted(instance.solutions),
            "private_clues": {"A": list(instance.private_clues.get("A", ())),
                              "B": list(instance.private_clues.get("B", ()))},
            "joint_solutions": sorted(instance.joint_solutions),
        })
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def between_form_sd(journal: Sequence[Mapping[str, Any]]) -> float | None:
    means = ji.j3_iso_full_regression(journal)["form_means"]
    if len(means) < 2:
        return None
    mean = sum(means) / len(means)
    return math.sqrt(sum((value - mean) ** 2 for value in means) / (len(means) - 1))


def illustrative_required_forms(delta: float, sd: float, *, alpha: float = 0.05,
                                power: float = 0.80) -> int | None:
    if delta <= 0:
        return None
    return math.ceil(((1.959964 + 0.841621) * sd / delta) ** 2)


def _worst_case_cost_usd() -> float:
    return round(JEV_REPLAY_REQUEST_CAP * JEV_REPLAY_INPUT_TOKEN_CEILING * JEV_REPLAY_INPUT_USD_PER_MTOK
                 / 1_000_000, 9)


def build_replay_preregistration(*, journal_path: Path = DEFAULT_JOURNAL,
                                 seed_bases: Sequence[int] = FORM_CAPACITY_SEED_BASES,
                                 approved: bool = False, repo_root: Path | None = None) -> dict[str, Any]:
    repo_root = repo_root or _repo_root()
    journal = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    j3_hashes = {str(row.get("request_hash")) for row in journal}
    capacity = audit_form_capacity(seed_bases, j3_hashes=j3_hashes)
    sd = between_form_sd(journal)
    forms = frozen_forms()
    document: dict[str, Any] = {
        "preregistration_version": JEV_REPLAY_PREREG_VERSION,
        "stage": "jev-choice-replay",
        "status": JEV_REPLAY_LOCKED_STATUS if approved else JEV_REPLAY_DRAFT_STATUS,
        "approval_required": not approved,
        "approval": ({"approved": True, "approved_by": "reviewer",
                      "scope": "registration_lock_only", "live_collection_authorized": False}
                     if approved else {"approved": False, "live_collection_authorized": False}),
        "pending_decisions": ([] if approved else [
            "reviewer lock of this draft (separate from any live authorization)",
            "confirm the request/cost caps after the worst-case accounting",
            "confirm the controller-injected placebo wording",
        ]),
        "claim_scope": {
            "type": "form-conditioned pilot",
            "statement": "pilot conditional on the six frozen prompt forms; new seed IDs do not create new "
                         "prompt forms. The t interval and sign-flip result are assumption-dependent "
                         "summaries of these forms, not evidence of generalization; a generator redesign is "
                         "required before a broader claim. Not calibration.",
            "forms": 6,
        },
        "experimental_unit": "model-visible pre-read prompt form",
        "estimand": {
            "primary_outcome": "entropy_bits",
            "event_difference": "H_real - H_placebo",
            "form_effect": "within-form mean of the event difference",
            "estimand": "equal-weight mean across distinct forms",
            "directional_prediction": "delta < 0",
            "null_branch": "cancels from the primary contrast; retained for real-minus-null and "
                           "placebo-minus-null manipulation checks",
        },
        "guards": {
            "filtering": "never used to filter the primary estimate; every pre-eligible, valid real/placebo "
                         "pair enters the entropy analysis and the guards are reported alongside it",
            "target_probability": {"guard": "p_target(real) >= p_target(placebo) + delta", "margin_delta": 0.0},
            "feasible_set_mass": {"guard": "mass_F(real) >= mass_F(placebo) - epsilon",
                                  "reference_set": "F = pre-read clue-consistent set S(C), fixed by C and "
                                                   "independent of the real message",
                                  "epsilon": 0.01},
            "reporting": "form-level guard differences and event-level violations",
            "objective_information": "I_m kept distinct from model entropy",
        },
        "placebo": {
            "construction": jr.PLACEBO_CONSTRUCTION,
            "envelope": jr.MESSAGE_ENVELOPE_TEMPLATE,
            "origin": jr.PLACEBO_ORIGIN,
            "synthetic": jr.PLACEBO_SYNTHETIC,
            "wording_hash": jr.message_wording_hash(),
            "requirements": ["claim is one of the receiver's own pre-read private clues",
                             "authoritative I_m against the receiver's pre-read feasible set is 0",
                             "the pre-read feasible set is unchanged",
                             "same source-neutral envelope as the real arm; synthetic origin controller-side"],
        },
        "message_envelope": {
            "template": jr.MESSAGE_ENVELOPE_TEMPLATE,
            "real_arm": "peer_clue: <claim>",
            "placebo_arm": "peer_clue: <known receiver clue>",
            "source_neutral": True,
            "branch_request_rule": "each branch request = the frozen pre-read body with state.visible_messages "
                                   "set to [] (null) or one peer_clue message; branch request_hash is recomputed "
                                   "and must match the stored value",
        },
        "board_evidence": {
            "schema": "communication_events.CommunicationEventLog (board_write, peer_read_exposure, "
                      "board_write_rejected)",
            "rule": "the real arm is proven only if the retained log has an accepted board_write by the writer "
                    "whose normalized_claim/raw_text equal the claim and whose receiver_id is the reader, "
                    "followed by a peer_read_exposure by the reader with the recorded exposure_id; a "
                    "board_write_rejected or a missing/mismatched read fails closed as unverified_real_evidence",
        },
        "eligibility": {
            "real_message": "ownership (instance.holds_claim) and I_m are recomputed from the generated instance; "
                            "the write-to-read link is verified against the retained CommunicationEventLog "
                            "board events. Missing, rejected, or mismatched evidence fails closed as "
                            "unverified_real_evidence.",
            "placebo": "the claim is a receiver-already-known pre-read clue with authoritative I_m = 0 and an "
                       "unchanged feasible set",
        },
        "conditions": {
            "arms": ["ISO (Jev receiver pre-read)", "FULL (Jev receiver, saturated bound)",
                     "COMM optional board (Ling writer / Jev receiver)",
                     "COMM turn-matched no-information control (Ling writer / Jev receiver, no board write)"],
            "condition_turns": dict(JEV_REPLAY_TURNS),
            "turn_matched_control": {
                "description": "same COMM turn structure with no real board write; preserves optional silence "
                               "and never manufactures a real write",
                "purpose": "absorbs the extra finalizer turn so the board effect is not confounded with turns",
                "model_visible": "no peer_clue message; empty visible_messages",
            },
            "optional_silence": True,
        },
        "decision_rule": {
            "primary_test": "two-sided exact cluster sign-flip on form means",
            "additional_requirement": "negative effect (form_mean < 0)",
            "interval_reported_alongside": "form-mean t interval (df=k-1)",
            "no_one_sided_switch": True,
            "null_branch": "separate manipulation check",
        },
        "inference": {
            "primary": "form-mean t interval (df=k-1) and exhaustive two-sided cluster sign-flip p",
            "minimum_two_sided_p_at_k6": 2 / (2 ** 6),
            "minimum_two_sided_p_at_k5": 2 / (2 ** 5),
            "sensitivities_secondary": ["form-cluster bootstrap", "sign test on form means",
                                        "instance-weighted estimate", "hierarchical model (only if defensible)"],
        },
        "complete_pair_rule": "require at least one valid real/placebo pair in each of the six forms for the "
                              "six-form primary analysis; aim for two or more planned opportunities per form; "
                              "if a form is lost the result is incomplete (five-form minimum two-sided "
                              "sign-flip p = 0.0625). Incomplete pairs reported, not dropped.",
        "missingness": "planned/attempted/valid/complete/incomplete reported per form and per branch; a failed "
                       "attempt is distinguished from an unattempted branch",
        "missing_real_message_rule": "when optional board use leaves a form without a real message that form is "
                                     "reported incomplete; because the primary analysis requires a real pair in "
                                     "all six forms, a missing real message makes the result incomplete rather "
                                     "than triggering substitution",
        "model_and_protocol": {
            "provider": "jev", "model": JEV_REPLAY_MODEL, "endpoint": JEV_REPLAY_ENDPOINT,
            "codec_version": JEV_CHOICE_CODEC_VERSION,
            "protocol_key": jc.jev_choice_protocol_key(model=JEV_REPLAY_MODEL, endpoint=JEV_REPLAY_ENDPOINT,
                                                       max_retries=JEV_REPLAY_MAX_RETRIES,
                                                       instructions=jc.JEV_CHOICE_INSTRUCTIONS,
                                                       question_id=jc.JEV_QUESTION_ID),
            "ling": "pinned free Ling writer on OpenRouter free quota",
        },
        "retry_policy": {
            "max_retries": JEV_REPLAY_MAX_RETRIES,
            "retryable_statuses": JEV_REPLAY_RETRYABLE,
            "backoff_seconds": 0.5, "backoff_max_seconds": 5.0,
        },
        "invalidity_classes": sorted(set(jc.INVALID_RESPONSE_CLASSES) | set(jr.INVALID_REPLAY_PROBLEMS)),
        "generator": {
            "generator_version": tf.GENERATOR_VERSION, "checker_version": tf.CHECKER_VERSION,
            "source_files": list(JEV_REPLAY_SOURCE_FILES),
            "source_files_hash": _source_files_hash(repo_root),
            "treatment_hash": treatment_hash(),
        },
        "frozen_forms": forms,
        "form_capacity_audit": capacity,
        "power": {
            "label": "illustrative and secondary", "k_forms": 6, "between_form_sd_bits": sd,
            "sd_caveat": "the observed J3 between-form SD is from ISO-minus-FULL, not the real-minus-placebo "
                         "estimand; use only as an illustrative sensitivity value, not a plug-in variance",
            "illustrative_required_forms": {
                "delta_0.10": illustrative_required_forms(0.10, sd) if sd else None,
                "delta_0.20": illustrative_required_forms(0.20, sd) if sd else None,
            },
        },
        "manifest": {
            "family": "planning", "complexity": "low", "regime": "N",
            "seed_base": JEV_REPLAY_SEED_BASE, "per_block": JEV_REPLAY_PER_BLOCK,
            "instance_ids": forms["instance_ids"], "manifest_hash": forms["manifest_hash"],
        },
        "stop_rules": list(JEV_REPLAY_STOP_RULES),
        "caps": {
            "physical_requests": JEV_REPLAY_REQUEST_CAP,
            "cost_cap_usd": JEV_REPLAY_COST_CAP_USD,
            "input_token_ceiling": JEV_REPLAY_INPUT_TOKEN_CEILING,
            "input_usd_per_mtok": JEV_REPLAY_INPUT_USD_PER_MTOK,
            "worst_case_cost_usd": _worst_case_cost_usd(),
            "planned_calls": dict(JEV_REPLAY_PLANNED_CALLS),
            "planned_physical_requests": JEV_REPLAY_PLANNED_REQUESTS,
            "retry_reserve": JEV_REPLAY_RETRY_RESERVE,
            "status": ("locked; live_collection_authorized=false" if approved
                       else "draft; not authorized"),
        },
    }
    payload = json.dumps({key: value for key, value in document.items()
                          if key != "preregistration_hash"}, sort_keys=True)
    document["preregistration_hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return document


def verify_against_jev_replay_preregistration(document: Mapping[str, Any], *, instance_ids: Sequence[str],
                                              model: str, endpoint: str, protocol_key: str,
                                              planned_requests: int | None = None,
                                              repo_root: Path | None = None) -> dict[str, Any]:
    """Repository-backed verifier. Fails closed on draft status, hash/settings
    drift, mixed protocols, wrong manifests and over-budget plans."""

    repo_root = repo_root or _repo_root()
    errors: list[str] = []
    if document.get("status") != JEV_REPLAY_LOCKED_STATUS:
        errors.append("registration is not locked for the Jev Choice replay")
    if document.get("approval_required") or not document.get("approval", {}).get("approved"):
        errors.append("reviewer lock approval is missing")
    if document.get("approval", {}).get("live_collection_authorized") is not False:
        errors.append("live collection must not be authorized by the lock")
    recorded_hash = document.get("preregistration_hash")
    expected = build_replay_preregistration(approved=True, repo_root=repo_root)
    if recorded_hash != expected["preregistration_hash"]:
        errors.append("registration hash drift from the repository state")
    recorded_content = {key: value for key, value in document.items() if key != "preregistration_hash"}
    expected_content = {key: value for key, value in expected.items() if key != "preregistration_hash"}
    if recorded_content != expected_content:
        errors.append("registration settings drift from the repository state")
    if document.get("preregistration_version") != JEV_REPLAY_PREREG_VERSION:
        errors.append("wrong registration version")

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

    model_and_protocol = document.get("model_and_protocol", {})
    if model != model_and_protocol.get("model"):
        errors.append(f"model {model!r} != locked {model_and_protocol.get('model')!r}")
    if endpoint != model_and_protocol.get("endpoint"):
        errors.append(f"endpoint {endpoint!r} != locked {model_and_protocol.get('endpoint')!r}")
    if protocol_key != model_and_protocol.get("protocol_key"):
        errors.append("protocol key differs from the locked registration")
    if not jc.is_jev_protocol_key(str(protocol_key)):
        errors.append("protocol key is not a Jev key")
    expected_key = jc.jev_choice_protocol_key(model=model, endpoint=endpoint,
                                              max_retries=JEV_REPLAY_MAX_RETRIES,
                                              instructions=jc.JEV_CHOICE_INSTRUCTIONS,
                                              question_id=jc.JEV_QUESTION_ID)
    if protocol_key != expected_key:
        errors.append("protocol key is not reproducible from the locked settings")

    caps = document.get("caps", {})
    request_cap = caps.get("physical_requests")
    if request_cap != JEV_REPLAY_REQUEST_CAP:
        errors.append("request cap differs from the locked registration")
    if planned_requests is not None and request_cap is not None and planned_requests > request_cap:
        errors.append(f"planned requests {planned_requests} exceed the cap {request_cap}")
    if caps.get("cost_cap_usd") != JEV_REPLAY_COST_CAP_USD:
        errors.append("cost cap differs from the locked registration")
    if float(caps.get("worst_case_cost_usd", 0.0)) > float(caps.get("cost_cap_usd", 0.0)):
        errors.append("worst-case cost exceeds the registered cap")
    return {"ok": not errors, "errors": errors, "expected_protocol_key": expected_key,
            "actual_protocol_key": protocol_key, "expected_instance_ids": frozen_ids,
            "manifest_hash": manifest_hash, "registration_hash": recorded_hash,
            "planned_requests": planned_requests, "request_cap": request_cap,
            "worst_case_cost_usd": caps.get("worst_case_cost_usd")}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E4 Jev Choice replay preregistration")
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--approve", action="store_true", help="lock the registration (not live authorization)")
    args = parser.parse_args(argv)
    document = build_replay_preregistration(journal_path=args.journal, approved=args.approve,
                                            repo_root=args.repo_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "preregistration_version": document["preregistration_version"],
        "status": document["status"],
        "live_collection_authorized": document["approval"].get("live_collection_authorized"),
        "capacity_paired_forms": document["form_capacity_audit"]["capacity_paired_forms"],
        "planned_physical_requests": document["caps"]["planned_physical_requests"],
        "request_cap": document["caps"]["physical_requests"],
        "worst_case_cost_usd": document["caps"]["worst_case_cost_usd"],
        "cost_cap_usd": document["caps"]["cost_cap_usd"],
        "preregistration_hash": document["preregistration_hash"],
    }, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "JEV_REPLAY_PREREG_VERSION", "JEV_REPLAY_DRAFT_STATUS", "JEV_REPLAY_LOCKED_STATUS",
    "JEV_REPLAY_SEED_BASE", "JEV_REPLAY_REQUEST_CAP", "JEV_REPLAY_COST_CAP_USD",
    "JEV_REPLAY_PLANNED_CALLS", "JEV_REPLAY_PLANNED_REQUESTS", "JEV_REPLAY_TURNS",
    "audit_form_capacity", "frozen_forms", "treatment_hash", "between_form_sd",
    "illustrative_required_forms", "build_replay_preregistration",
    "verify_against_jev_replay_preregistration", "main",
]
