"""E4 — Jev Choice replay preregistration and form-level power draft (#185).

Offline. Audits how many distinct prompt forms the generator can produce, decides
between a study conditional on the six known forms and a generator redesign, and
drafts a manifest, guards, complete-pair rules, stop rules, and caps. The
registration is a DRAFT: it is not locked and authorizes no live collection.
Packet tasks #173/#175 are out of scope.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import jev_preregistration as jp
from . import jev_replay_inference as ji
from . import task_families as tf
from .communication_protocol import DependenceRegime, ReasoningComplexity
from .jev_choice import JEV_CHOICE_CODEC_VERSION, JevChoiceAdapter


JEV_REPLAY_PREREG_VERSION = "stage2-jev-choice-replay-v1"
FORM_CAPACITY_SEED_BASES = (70000, 71000, 72000, 73000, 74000)
JEV_REPLAY_SEED_BASE = 72000
JEV_REPLAY_PER_BLOCK = 17
DEFAULT_JOURNAL = Path("runs/epic-126/jev-choice-capability.jsonl")
DEFAULT_OUTPUT = Path("runs/epic-126/jev-choice-replay-preregistration.json")
DRAFT_REQUEST_CAP = 300
DRAFT_COST_CAP_USD = 1.0


class _NoopClient:
    provider = "jev"
    endpoint = "https://api.typesafe.ai/v1/systemone"
    max_retries = jp.JEV_CAPABILITY_MAX_RETRIES
    max_physical_requests = None
    physical_attempts = 0

    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:  # pragma: no cover
        raise RuntimeError("preflight client must never issue a request")


def _forms_for_block(seed_base: int, per_block: int) -> dict[str, str]:
    adapter = JevChoiceAdapter(_NoopClient(), model=jp.JEV_CAPABILITY_MODEL)
    forms: dict[str, str] = {}
    for replicate in range(per_block):
        instance = tf.generate_instance("planning", seed_base + replicate, DependenceRegime.N,
                                        ReasoningComplexity.LOW)
        for condition in ("ISO", "FULL"):
            state = adapter.build_state(instance, "A", condition)
            forms[state.request_hash] = condition
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
            forms = _forms_for_block(int(seed_base), per_block)
            row["new_forms_vs_j3"] = len(set(forms) - j3_hashes)
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


def between_form_sd(journal: Sequence[Mapping[str, Any]]) -> float | None:
    regression = ji.j3_iso_full_regression(journal)
    means = regression["form_means"]
    if len(means) < 2:
        return None
    mean = sum(means) / len(means)
    return math.sqrt(sum((value - mean) ** 2 for value in means) / (len(means) - 1))


def illustrative_required_forms(delta: float, sd: float, *, alpha: float = 0.05,
                                power: float = 0.80) -> int | None:
    """Illustrative form count for a target delta (z-approximation; secondary)."""

    if delta <= 0:
        return None
    z_alpha = 1.959964
    z_power = 0.841621
    return math.ceil(((z_alpha + z_power) * sd / delta) ** 2)


def build_replay_preregistration(*, journal_path: Path = DEFAULT_JOURNAL,
                                 seed_bases: Sequence[int] = FORM_CAPACITY_SEED_BASES) -> dict[str, Any]:
    journal = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    j3_hashes = {str(row.get("request_hash")) for row in journal}
    capacity = audit_form_capacity(seed_bases, j3_hashes=j3_hashes)
    sd = between_form_sd(journal)
    document: dict[str, Any] = {
        "preregistration_version": JEV_REPLAY_PREREG_VERSION,
        "stage": "jev-choice-replay",
        "status": "draft_pending_review",
        "approval_required": True,
        "approval": {"approved": False, "live_collection_authorized": False},
        "pending_decisions": [
            "reviewer lock of this draft (separate from any live authorization)",
            "confirm the draft request/cost caps after the planned-call breakdown",
            "confirm the controller-injected placebo wording",
        ],
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
            "construction": "preregistered, controller-injected typed claim already known to the receiver",
            "requirements": ["verified I_m = 0", "no feasible-set reduction",
                             "synthetic origin recorded outside the model-visible message"],
            "note": "the current audited instances have no B-owned zero-information claim, so a naturally "
                    "B-owned placebo is not feasible without a generator change",
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
        "model_and_protocol": {
            "model": jp.JEV_CAPABILITY_MODEL,
            "endpoint": jp.JEV_CAPABILITY_ENDPOINT,
            "codec_version": JEV_CHOICE_CODEC_VERSION,
        },
        "form_capacity_audit": capacity,
        "power": {
            "label": "illustrative and secondary",
            "k_forms": 6,
            "between_form_sd_bits": sd,
            "sd_caveat": "the observed J3 between-form SD is from ISO-minus-FULL, not the real-minus-placebo "
                         "estimand; use only as an illustrative sensitivity value, not a plug-in variance",
            "illustrative_required_forms": {
                "delta_0.10": illustrative_required_forms(0.10, sd) if sd else None,
                "delta_0.20": illustrative_required_forms(0.20, sd) if sd else None,
            },
        },
        "manifest": {
            "family": "planning",
            "complexity": "low",
            "regime": "N",
            "seed_base": JEV_REPLAY_SEED_BASE,
            "per_block": JEV_REPLAY_PER_BLOCK,
            "note": "seed-disjoint IDs do not create new forms; the study is conditional on the six forms "
                    "regardless of the block chosen",
        },
        "stop_rules": ["request_cap", "cost_cap", "repeated_http_failure", "contract_mismatch", "model_drift",
                       "missing_checker_evidence"],
        "caps": {
            "physical_requests": DRAFT_REQUEST_CAP,
            "cost_cap_usd": DRAFT_COST_CAP_USD,
            "ling": "pinned free model; OpenRouter free quota",
            "planned_calls": {
                "jev_pre_read_iso_full": "17 instances x 2 conditions = 34",
                "jev_replay_real_placebo_null": "17 instances x 3 branches = 51",
                "ling_writer": "one writer turn per optional-board event (upper bound 17)",
                "retry_allowance": "per Jev retry policy (max 2 retries; 408/429/5xx/529)",
                "note": "ceilings only; freeze after review",
            },
            "missing_real_message_rule": "when optional board use leaves a form without a real message that "
                                         "form is reported incomplete; because the primary analysis requires a "
                                         "real pair in all six forms, a missing real message makes the result "
                                         "incomplete rather than triggering substitution",
            "status": "draft; not authorized",
        },
    }
    payload = json.dumps({key: value for key, value in document.items()
                          if key != "preregistration_hash"}, sort_keys=True)
    document["preregistration_hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E4 Jev Choice replay preregistration (draft)")
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    document = build_replay_preregistration(journal_path=args.journal)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "preregistration_version": document["preregistration_version"],
        "status": document["status"],
        "capacity_paired_forms": document["form_capacity_audit"]["capacity_paired_forms"],
        "new_forms_vs_j3_in_72000": document["form_capacity_audit"]["blocks"]["72000"]["new_forms_vs_j3"],
        "between_form_sd_bits": document["power"]["between_form_sd_bits"],
        "recommendation": document["form_capacity_audit"]["recommendation"],
        "preregistration_hash": document["preregistration_hash"],
    }, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "JEV_REPLAY_PREREG_VERSION", "FORM_CAPACITY_SEED_BASES", "JEV_REPLAY_SEED_BASE",
    "DRAFT_REQUEST_CAP", "DRAFT_COST_CAP_USD", "audit_form_capacity", "between_form_sd",
    "illustrative_required_forms", "build_replay_preregistration", "main",
]
