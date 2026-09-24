"""#190 — fresh form-balanced L4X coverage manifest preregistration v6 (offline lock).

Selects one fresh, fixed-N, form-balanced planning-low manifest (six known
pre-read prompt forms x six fresh instances, N=36) by deterministic offline
form identity only, and drafts/locks the successor registration for the
original-treatment L4X bridge. The registration binds treatment, source,
geometry, prompt and protocol semantics, freezes the fixed-N/no-outcome-
stopping design, the 144/36/180 planned-call arithmetic and the retry-inclusive
physical partitions, and leaves the coverage decision to #192.

``live_collection_authorized`` is always false; locking this registration is
not live authorization. No API calls: the builder, verifier and CLI never
construct a provider transport.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import behavioral_discovery as bd
from . import jev_choice as jc
from . import jev_choice_v2 as jc2
from . import jev_ling_writer_v3 as writer_v3
from . import jev_ling_writer_v5 as writer_v5
from . import jev_replay_preregistration as pr
from . import jev_replay_preregistration_v2 as prv2
from . import jev_six_form_coverage_audit as audit
from . import jev_writer_exact_bridge_v5 as bridge
from . import jev_writer_ladder_v5 as ladder
from . import task_families as tf
from .communication_protocol import DependenceRegime, ReasoningComplexity


COVERAGE_PREREG_VERSION = "stage2-jev-coverage-manifest-v6"
COVERAGE_DRAFT_STATUS = "draft_pending_review_v6"
COVERAGE_LOCKED_STATUS = "locked_for_jev_coverage_manifest_v6"

DEFAULT_OUTPUT_V6 = Path("runs/epic-126/jev-coverage-manifest-preregistration-v6.json")
DEFAULT_JOURNAL_V6 = Path("runs/epic-126/jev-coverage-manifest-v6.jsonl")
DEFAULT_REPORT_V6 = Path("runs/epic-126/jev-coverage-manifest-report-v6.json")
DEFAULT_AUDIT_V1 = Path("runs/epic-126/jev-six-form-coverage-audit-v1.json")

#: All three v6-owned paths are excluded from the prior-ID scan: the
#: registration itself, and the future journal/report #191 will write. Without
#: this the scan would ingest its own outputs and the manifest would appear to
#: overlap itself once collection starts.
V6_OWNED_FILE_NAMES = frozenset({
    DEFAULT_OUTPUT_V6.name, DEFAULT_JOURNAL_V6.name, DEFAULT_REPORT_V6.name,
})
V6_OWNED_PATHS = (str(DEFAULT_OUTPUT_V6), str(DEFAULT_JOURNAL_V6), str(DEFAULT_REPORT_V6))

#: Fixed offline seed scan window. Selection consults form identity only.
SEED_SCAN_BASE = 75000
SEED_SCAN_WINDOW = 256
SEED_SCAN_END = SEED_SCAN_BASE + SEED_SCAN_WINDOW - 1

INSTANCES_PER_FORM = 6
FORM_COUNT = 6
BLOCK_N = INSTANCES_PER_FORM * FORM_COUNT

#: The exact six pre-read prompt forms frozen by #189.
FROZEN_FORM_IDS = (
    "0a3349e16c9633b4d559dfbb808d1e50d0446d8f92160a0feddd1e37299796ee",
    "1c1d9f6b5c9271ad8e74de180c3e397e1369d326564c9a08ba0840eff0b148fc",
    "2954f5684bcd198ed8eea0956cf573f93cde628d6dfa7472fc57f556bd089b2c",
    "3196a8d69f844702db012816def7d7866e7416e9fadc9f28eaa7f12ac16a8569",
    "55968fe191b18f37d1951d71f777115f753e0b9a6da526015f3db5251a1383eb",
    "ce847ac53b6e344103bc775aede5212b2be6fbd568dc1d85fd24cbde8f585222",
)

#: Planned logical calls from the exact bridge treatment (N=36).
PLANNED_LING_PER_INSTANCE = len(ladder.EXACT_BRIDGE_AGENTS) * ladder.EXACT_BRIDGE_TURNS  # 4
PLANNED_JEV_PER_INSTANCE = 1
PLANNED_LING = BLOCK_N * PLANNED_LING_PER_INSTANCE  # 144
PLANNED_JEV = BLOCK_N * PLANNED_JEV_PER_INSTANCE    # 36
PLANNED_REQUESTS = PLANNED_LING + PLANNED_JEV       # 180

#: Retry-inclusive physical partitions: planned x (1 + registered max retries).
RETRY_RESERVE_FACTOR = 1 + pr.JEV_REPLAY_MAX_RETRIES  # 3
LING_REQUEST_CAP = PLANNED_LING * RETRY_RESERVE_FACTOR  # 432
JEV_REQUEST_CAP = PLANNED_JEV * RETRY_RESERVE_FACTOR    # 108
COMBINED_REQUEST_CAP = LING_REQUEST_CAP + JEV_REQUEST_CAP  # 540
COST_CAP_USD = 1.0
INPUT_TOKEN_CEILING = pr.JEV_REPLAY_INPUT_TOKEN_CEILING
INPUT_USD_PER_MTOK = pr.JEV_REPLAY_INPUT_USD_PER_MTOK
WORST_CASE_CALL_COST_USD = round(INPUT_TOKEN_CEILING * INPUT_USD_PER_MTOK / 1_000_000, 12)
WORST_CASE_COST_USD = round(COMBINED_REQUEST_CAP * WORST_CASE_CALL_COST_USD, 9)

#: Prior planning/registered seed ranges relevant to this experiment.
PRIOR_SEED_RANGES = (
    (16400, 16419), (16500, 16519), (16600, 16602), (39000, 39001), (41000, 41001),
    (70000, 70016), (71000, 71016), (72000, 72016), (73000, 73016), (74000, 74016),
    (80000, 80016),
)
PRIOR_SCAN_PATTERNS = ("runs/epic-126/*.json", "runs/epic-126/*.jsonl",
                       "runs/*.json", "runs/*.jsonl")

OLD_OUTPUT_PATHS_V6 = (
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
    "runs/epic-126/jev-writer-ladder-preregistration-v5.json",
    "runs/epic-126/jev-writer-ladder-v5.jsonl",
    "runs/epic-126/jev-writer-ladder-report-v5.json",
    "runs/epic-126/jev-writer-exact-bridge-v5.jsonl",
    "runs/epic-126/jev-writer-exact-bridge-report-v5.json",
    "runs/epic-126/jev-writer-treatment-audit-v4.json",
    "runs/epic-126/jev-choice-normalization-probe-v2.jsonl",
    "runs/epic-126/jev-choice-normalization-probe-report-v2.json",
    "runs/epic-126/jev-choice-capability.jsonl",
    "runs/epic-126/jev-choice-capability-report.json",
    "runs/epic-126/jev-choice-wire-smoke-report.json",
)

#: Source files whose semantics this registration binds.
COVERAGE_SOURCE_FILES = (
    "src/apart_incident_response/task_families.py",
    "src/apart_incident_response/communication_protocol.py",
    "src/apart_incident_response/finite_information.py",
    "src/apart_incident_response/communication_events.py",
    "src/apart_incident_response/communication_runner.py",
    "src/apart_incident_response/behavioral_discovery.py",
    "src/apart_incident_response/jev_protocol.py",
    "src/apart_incident_response/jev_choice.py",
    "src/apart_incident_response/jev_choice_v2.py",
    "src/apart_incident_response/jev_choice_smoke.py",
    "src/apart_incident_response/jev_replay.py",
    "src/apart_incident_response/jev_replay_inference.py",
    "src/apart_incident_response/jev_replay_preregistration.py",
    "src/apart_incident_response/jev_replay_preregistration_v2.py",
    "src/apart_incident_response/jev_choice_pilot.py",
    "src/apart_incident_response/jev_ling_writer_v3.py",
    "src/apart_incident_response/jev_ling_writer_v5.py",
    "src/apart_incident_response/jev_writer_ladder_v5.py",
    "src/apart_incident_response/jev_writer_exact_bridge_v5.py",
    "src/apart_incident_response/jev_writer_treatment_audit.py",
    "src/apart_incident_response/jev_six_form_coverage_audit.py",
    "src/apart_incident_response/jev_coverage_manifest_preregistration_v6.py",
    "src/apart_incident_response/jev_coverage_bridge_v6.py",
)

RECEIVER_AGENT = "A"
WRITER_AGENTS = tuple(ladder.EXACT_BRIDGE_AGENTS)

#: The #191 coverage runner module bound into this registration.
RUNNER_SOURCE_REL = "src/apart_incident_response/jev_coverage_bridge_v6.py"
#: Prior runner-less offline lock superseded by the runner-bound amendment.
SUPERSEDED_OFFLINE_LOCK_HASH = (
    "41c14acebba674180bf7878e519b53422513ae2612133cee03e94e3ca608ce5c")
_INSTANCE_ID_RE = re.compile(r"^planning-([0-9a-f]{8})$")


def _is_v6_owned(path: Path) -> bool:
    """True for the registration and the future journal/report this lock owns."""

    return path.name in V6_OWNED_FILE_NAMES


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_files_hash(repo_root: Path) -> str:
    digest = hashlib.sha256()
    missing = []
    for relative in COVERAGE_SOURCE_FILES:
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
    return {"registration": str(DEFAULT_OUTPUT_V6), "journal": str(DEFAULT_JOURNAL_V6),
            "report": str(DEFAULT_REPORT_V6), "audit_input": str(DEFAULT_AUDIT_V1)}


def prompt_binding() -> dict[str, Any]:
    """Hash-bindable description of the original-treatment Ling prompt path."""

    binding = {
        "path": ("communication_runner.AgentContext -> behavioral_discovery.treatment_prompt"
                 " -> json.dumps(sort_keys=True)"),
        "prompt_schema_version": bd.PROMPT_SCHEMA_VERSION,
        "prompt_fields": list(bd.TREATMENT_PROMPT_FIELDS),
        "output_grammar": "ANSWER: <label> + optional MESSAGE: <claim>; answer-only = silence",
        "serialization": "json.dumps(treatment_prompt(context), sort_keys=True)",
        "provider_version": bd.BEHAVIORAL_VERSION,
        "temperature": 0.0,
        "max_tokens": ladder.EXACT_BRIDGE_TOKEN_BUDGET,
        "seed_behavior": {"algorithm": bd.PROVIDER_SEED_ALGORITHM,
                          "inputs": "provider_seed(instance_id, 'COMM', turn, agent_id)",
                          "sent_as_seed_field": True},
    }
    binding["prompt_hash"] = hashlib.sha256(
        json.dumps({key: binding[key] for key in
                    ("path", "prompt_schema_version", "prompt_fields", "output_grammar",
                     "serialization")}, sort_keys=True).encode("utf-8")).hexdigest()
    return binding


def protocol_key_v6() -> str:
    return jc2.jev_choice_protocol_key_v2(model=pr.JEV_REPLAY_MODEL,
                                          endpoint=pr.JEV_REPLAY_ENDPOINT,
                                          max_retries=pr.JEV_REPLAY_MAX_RETRIES,
                                          instructions=jc.JEV_CHOICE_INSTRUCTIONS,
                                          question_id=jc.JEV_QUESTION_ID)


def _collect_prior_ids(root: Path) -> set[str]:
    """Union of artifact-recorded instance ids and documented seed ranges.

    All three v6-owned paths (registration, future journal, future report) are
    skipped so the scan can never ingest the manifest it is checking against.
    """

    found: set[str] = set()
    id_pattern = re.compile(r'"instance_id":\s*"([^"]+)"')
    for pattern in PRIOR_SCAN_PATTERNS:
        for path in sorted(root.glob(pattern)):
            if _is_v6_owned(path):
                continue
            if path.suffix == ".jsonl":
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                found.update(id_pattern.findall(text))
                continue
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                continue

            def walk(node: Any) -> None:
                if isinstance(node, dict):
                    for key, value in node.items():
                        if key == "instance_ids" and isinstance(value, list):
                            found.update(str(item) for item in value)
                        elif key == "instance_id" and isinstance(value, str):
                            found.add(value)
                        else:
                            walk(value)
                elif isinstance(node, list):
                    for value in node:
                        walk(value)

            walk(document)
    for low, high in PRIOR_SEED_RANGES:
        for seed in range(low, high + 1):
            found.add(tf.generate_instance("planning", seed, DependenceRegime.N,
                                            ReasoningComplexity.LOW).instance_id)
    return found


def prior_instance_ids(repo_root: Path | None = None) -> dict[str, Any]:
    """Evidence for every prior registered or collected instance id in scope.

    Sources: all instance ids recorded in epic-126 JSON/JSONL artifacts (wire
    smoke, capability, planning-low manifests, pilots, ladders, bridge, audits)
    plus the documented prior seed ranges. All three v6-owned paths
    (registration, future journal, future report) are excluded from both the
    id set and this source list, so the evidence is stable before collection,
    after #191 writes its outputs, and across re-verification.
    """

    root = Path(repo_root) if repo_root is not None else _repo_root()
    sources: list[str] = []
    for pattern in PRIOR_SCAN_PATTERNS:
        for path in sorted(root.glob(pattern)):
            if _is_v6_owned(path):
                continue
            sources.append(path.relative_to(root).as_posix())
    ordered = sorted(_collect_prior_ids(root))
    return {"instance_id_count": len(ordered),
            "instance_ids_sha256": hashlib.sha256(
                json.dumps(ordered, sort_keys=True).encode("utf-8")).hexdigest(),
            "sources": sorted(set(sources)),
            "seed_ranges": [{"low": low, "high": high} for low, high in PRIOR_SEED_RANGES],
            "excluded": list(V6_OWNED_PATHS),
            "note": ("the v6 registration and the future v6 journal/report are excluded so this "
                     "evidence is stable before collection, after #191 writes its outputs, and "
                     "across re-verification")}


def scan_window() -> list[tuple[int, Any, str]]:
    """Score the fixed seed window by pre-read A prompt form (offline only)."""

    instances = [tf.generate_instance("planning", seed, DependenceRegime.N,
                                      ReasoningComplexity.LOW)
                 for seed in range(SEED_SCAN_BASE, SEED_SCAN_END + 1)]
    forms = audit.pre_read_form_ids(instances)
    return [(seed, instance, forms[instance.instance_id])
            for seed, instance in zip(range(SEED_SCAN_BASE, SEED_SCAN_END + 1), instances)]


def select_form_balanced_manifest() -> tuple[dict[str, Any], list[Any]]:
    """Deterministic offline selection: six fresh instances for each frozen form.

    Inputs are seeds and the #189-canonical pre-read form identity only. Model
    outcomes, writer behavior and live artifacts are never consulted. Selection
    order: ascending seed; the first six instances landing in each form within
    the fixed window are taken.
    """

    membership: dict[str, list[str]] = {form: [] for form in FROZEN_FORM_IDS}
    instances_by_id: dict[str, Any] = {}
    scored = 0
    for _seed, instance, form in scan_window():
        scored += 1
        if form not in membership:
            raise ValueError(f"instance maps outside the frozen six-form set: {form}")
        if len(membership[form]) < INSTANCES_PER_FORM:
            membership[form].append(instance.instance_id)
            instances_by_id[instance.instance_id] = instance
    incomplete = sorted(form for form, ids in membership.items() if len(ids) != INSTANCES_PER_FORM)
    if incomplete:
        raise ValueError(f"seed window did not complete six-per-form: {incomplete}")
    ordered_ids = sorted(instances_by_id, key=lambda instance_id: int(instance_id.split("-")[1], 16))
    instances = [instances_by_id[instance_id] for instance_id in ordered_ids]
    completion_seed = max(int(instance_id.split("-")[1], 16) for instance_id in ordered_ids)
    meta = {
        "instance_ids": ordered_ids,
        "instance_seeds": [int(instance_id.split("-")[1], 16) for instance_id in ordered_ids],
        "form_membership": {form: list(membership[form]) for form in sorted(membership)},
        "form_counts": {form: len(membership[form]) for form in sorted(membership)},
        "iso_form_ids": sorted(FROZEN_FORM_IDS),
        "scan": {
            "seed_base": SEED_SCAN_BASE,
            "window": SEED_SCAN_WINDOW,
            "seed_end": SEED_SCAN_END,
            "seeds_scored": scored,
            "selection_order": "ascending seed",
            "selection_rule": "first six instances per frozen form within the fixed window",
            "completion_seed": completion_seed,
            "inputs": ("offline pre-read prompt form identity only; no model outcomes, writer "
                       "behavior, or live artifacts are consulted"),
            "freshness": "all seeds >= SEED_SCAN_BASE; disjoint from every prior seed range",
        },
    }
    return meta, instances


def manifest_treatment_hash(instances: Sequence[Any], form_of: Mapping[str, str]) -> str:
    """Model-visible treatment hash over the fresh 36-instance manifest."""

    rows = []
    for instance in instances:
        rows.append({
            "instance_id": instance.instance_id,
            "seed": instance.seed,
            "iso_form_id": form_of[instance.instance_id],
            "option_ids": sorted(instance.solutions),
            "private_clues": {"A": list(instance.private_clues.get("A", ())),
                              "B": list(instance.private_clues.get("B", ()))},
            "joint_solutions": sorted(instance.joint_solutions),
        })
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode("utf-8")).hexdigest()


def treatment_hash_v6(*, manifest_treatment: str, information_geometry: str,
                      prompt_hash: str) -> str:
    return hashlib.sha256(json.dumps({
        "manifest_treatment_hash": manifest_treatment,
        "information_geometry_hash": information_geometry,
        "normalization_policy_hash": prv2.normalization_policy_hash(),
        "writer_schema_hash": writer_v5.writer_schema_hash(),
        "writer_transport_version": writer_v3.LING_WRITER_TRANSPORT_VERSION,
        "prompt_hash": prompt_hash,
        "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
        "bridge_mode": bridge.BRIDGE_VERSION,
    }, sort_keys=True).encode("utf-8")).hexdigest()


def sizing_rationale() -> dict[str, Any]:
    rate = 9 / 17
    per_form = 1.0 - (1.0 - rate) ** INSTANCES_PER_FORM
    all_forms = per_form ** FORM_COUNT
    return {
        "historical_eligible_rate": {"numerator": 9, "denominator": 17, "value": rate,
                                     "expression": "9/17", "rounded": round(rate, 3)},
        "assumption": ("simplifying constant-rate/independence assumption across instances and "
                       "forms; this is an assumption-based sizing heuristic, not evidence that "
                       "eligibility is independent or constant across forms"),
        "p_one_form_ge_one": {"expression": "1 - (1 - 9/17)^6", "value": per_form,
                              "rounded": round(per_form, 3)},
        "p_all_six_ge_one": {"expression": "[1 - (1 - 9/17)^6]^6", "value": all_forms,
                             "rounded": round(all_forms, 3)},
        "source": "#189 audit fresh_coverage_handoff (historical sizing context only)",
        "pooling": "prior data is never pooled with this block for the primary coverage decision",
    }


def eligibility_rule() -> list[str]:
    return [
        "receiver valid",
        "accepted B-owned claim delivered to A",
        "authoritative I_m > 0",
        "claim not already known to A",
        "verified write payload identity",
        "verified A read after the write with a nonempty exposure ID",
        "no rejection evidence",
        "at most one deduplicated claim per pre-read state",
        "A->B messages excluded from primary replay eligibility",
    ]


def build_coverage_manifest_preregistration_v6(*, approved: bool = False,
                                               repo_root: Path | None = None) -> dict[str, Any]:
    repo_root = repo_root or _repo_root()
    if RUNNER_SOURCE_REL not in COVERAGE_SOURCE_FILES:
        raise ValueError("runner module missing from COVERAGE_SOURCE_FILES")
    selection, instances = select_form_balanced_manifest()
    instance_ids = selection["instance_ids"]
    if len(instance_ids) != BLOCK_N or len(set(instance_ids)) != BLOCK_N:
        raise ValueError("manifest must contain exactly 36 unique instance ids")
    if set(selection["iso_form_ids"]) != set(FROZEN_FORM_IDS):
        raise ValueError("selected form set differs from the #189 frozen six-form set")
    forms = pr.frozen_forms()
    if set(forms["iso_form_ids"]) != set(FROZEN_FORM_IDS):
        raise ValueError("registered frozen forms differ from the #189 frozen six-form set")
    audit_path = repo_root / DEFAULT_AUDIT_V1
    if audit_path.is_file():
        audit_document = json.loads(audit_path.read_text(encoding="utf-8"))
        audit_forms = sorted(row["prompt_form_id"] for row in audit_document.get("forms", []))
        if audit_forms != sorted(FROZEN_FORM_IDS):
            raise ValueError("#189 audit artifact form set drift")
    else:
        raise ValueError(f"missing #189 audit artifact: {DEFAULT_AUDIT_V1}")

    prior = prior_instance_ids(repo_root)
    overlap = sorted(set(instance_ids) & _prior_id_set(repo_root))
    if overlap:
        raise ValueError(f"manifest overlaps prior instance ids: {overlap[:5]}")
    form_of = {instance_id: form for form, ids in selection["form_membership"].items()
               for instance_id in ids}
    manifest_hash = hashlib.sha256(json.dumps(instance_ids, sort_keys=True).encode()).hexdigest()
    form_manifest_hash = hashlib.sha256(
        json.dumps(selection["iso_form_ids"], sort_keys=True).encode()).hexdigest()
    manifest_treatment = manifest_treatment_hash(instances, form_of)
    geometry_hash = audit.information_geometry_hash(instances)
    prompt = prompt_binding()

    document: dict[str, Any] = {
        "preregistration_version": COVERAGE_PREREG_VERSION,
        "successor_of": {
            "v1": "runs/epic-126/jev-choice-replay-preregistration.json",
            "v2": "runs/epic-126/jev-choice-replay-preregistration-v2.json",
            "v3": "runs/epic-126/jev-choice-replay-preregistration-v3.json",
            "v4": "runs/epic-126/jev-writer-ladder-preregistration-v4.json",
            "v5": "runs/epic-126/jev-writer-ladder-preregistration-v5.json",
            "frozen_live_result": "runs/epic-126/jev-writer-exact-bridge-report-v5.json",
            "frozen_audit": str(DEFAULT_AUDIT_V1),
            "immutable": True,
            "note": ("v1-v5 registrations and the frozen 17-instance L4X v5 journal/report are "
                     "never modified, resumed, appended to, pooled with, or reinterpreted by "
                     "this registration"),
        },
        "stage": "planning-low-six-form-coverage",
        "status": COVERAGE_LOCKED_STATUS if approved else COVERAGE_DRAFT_STATUS,
        "approval_required": not approved,
        "approval": ({"approved": True, "approved_by": "offline-registration-lock",
                      "scope": "v6_registration_lock_only", "live_collection_authorized": False}
                     if approved else
                     {"approved": False, "live_collection_authorized": False}),
        "pending_decisions": ([] if approved else [
            "reviewer lock of this v6 coverage-manifest registration (offline only)",
            "reviewer approval of #190 before #191 begins",
        ]) + [
            "separate live authorization and a passing runner preflight are required before "
            "any provider call in #191",
            "confirm the 144/36/180 planned calls, the 432/108/540 physical partitions and "
            "the $1.00 cost ceiling",
        ],
        "purpose": ("collect one fresh, fixed-N, form-balanced planning-low L4X block "
                    "(six known forms x six fresh instances, N=36) for the six-form coverage "
                    "decision, without appending to the frozen 17-instance block"),
        "claim_scope": {
            "type": "form-balanced coverage collection registration",
            "forms": FORM_COUNT,
            "n": BLOCK_N,
            "unit": "prompt form",
            "statement": ("36 fresh instance IDs are within-form replicates over the same six "
                          "frozen prompt forms; fresh IDs do not create new forms and do not "
                          "increase k beyond six; coverage collection is not causal uptake and "
                          "collection itself must not start #159"),
        },
        "treatment": {
            "mode": bridge.BRIDGE_VERSION,
            "family": "planning", "complexity": "low", "regime": "N",
            "agents": list(WRITER_AGENTS), "turns": ladder.EXACT_BRIDGE_TURNS,
            "token_budget": ladder.EXACT_BRIDGE_TOKEN_BUDGET,
            "seed_algorithm": ladder.EXACT_BRIDGE_SEED_ALGORITHM,
            "visibility": ("peer-only board rows; the Jev receiver A sees only accepted "
                           "B-authored claims; rejected writes are never visible"),
            "ownership": ("accepted board writes require exact instance.holds_claim ownership; "
                          "non_owned_claim is rejected and journaled"),
            "primary_direction": "one-way B->A",
            "final_receiver": f"{RECEIVER_AGENT} via Jev Choice wire v2",
            "exposure_id": bridge.JEV_FINALIZER_EXPOSURE_ID,
            "writer_prompt": prompt,
            "writer_transport": writer_v3.writer_transport_spec(),
            "writer_observability": writer_v5.writer_schema(),
            "writers": "Ling performs the original COMM interaction for both agents and turns",
        },
        "model_and_protocol": {
            "provider": "jev", "model": pr.JEV_REPLAY_MODEL, "endpoint": pr.JEV_REPLAY_ENDPOINT,
            "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
            "state_schema": jc.JEV_CHOICE_STATE_SCHEMA,
            "protocol_key": protocol_key_v6(),
            "max_retries": pr.JEV_REPLAY_MAX_RETRIES,
            "retryable_statuses": sorted(jc.JEV_RETRYABLE_STATUSES),
            "backoff": {"initial_seconds": jc.JEV_BACKOFF_INITIAL, "max_seconds": jc.JEV_BACKOFF_MAX,
                        "jitter": jc.JEV_BACKOFF_JITTER},
            "normalization_policy_hash": prv2.normalization_policy_hash(),
            "ling_provider": "openrouter",
            "ling_model": pr.LING_MODEL,
            "ling_endpoint": pr.LING_ENDPOINT,
        },
        "generator": {
            "generator_version": tf.GENERATOR_VERSION,
            "checker_version": tf.CHECKER_VERSION,
            "source_files": list(COVERAGE_SOURCE_FILES),
            "source_files_hash": _source_files_hash(repo_root),
            "manifest_treatment_hash": manifest_treatment,
            "information_geometry_hash": geometry_hash,
            "treatment_hash": treatment_hash_v6(manifest_treatment=manifest_treatment,
                                                information_geometry=geometry_hash,
                                                prompt_hash=prompt["prompt_hash"]),
        },
        "manifest": {
            "family": "planning", "complexity": "low", "regime": "N",
            "selection": selection["scan"],
            "instance_ids": instance_ids,
            "instance_seeds": selection["instance_seeds"],
            "form_membership": selection["form_membership"],
            "form_counts": selection["form_counts"],
            "iso_form_ids": selection["iso_form_ids"],
            "paired_forms": FORM_COUNT,
            "instances_per_form": INSTANCES_PER_FORM,
            "n": BLOCK_N,
            "manifest_hash": manifest_hash,
            "form_manifest_hash": form_manifest_hash,
            "disjointness": {
                "ok": not overlap,
                "overlap": overlap,
                "prior_instance_ids": prior,
                "frozen_block_first_id": "planning-00011940",
                "frozen_block_last_id": "planning-00011950",
            },
        },
        "coverage_design": {
            "instances_per_form": INSTANCES_PER_FORM,
            "forms": FORM_COUNT,
            "n": BLOCK_N,
            "fixed_n": True,
            "every_planned_instance_runs": ("all 36 planned instances run regardless of earlier "
                                            "messages or exposures"),
            "no_stopping_after_first_message": True,
            "no_stopping_after_form_exposure": True,
            "no_seed_replacement": "no seed replacement after any outcome is observed",
            "no_pooling_with_frozen_block": (
                "the frozen 17-instance L4X v5 block is never pooled with this block for the "
                "primary coverage decision"),
            "prior_data_role": "historical sizing context only",
            "experimental_unit": "prompt form",
            "k": FORM_COUNT,
            "k_limit_note": ("fresh IDs are within-form replicates; the known form space "
                             "contains only six forms, so fresh IDs cannot increase k"),
        },
        "sizing_rationale": sizing_rationale(),
        "runner_policy": {
            "required_before_live": True,
            "runner_implemented": True,
            "runner_source_files": [RUNNER_SOURCE_REL],
            "runner_source_bound": RUNNER_SOURCE_REL in COVERAGE_SOURCE_FILES,
            "policy": ("the v6 coverage runner is implemented in "
                       f"{RUNNER_SOURCE_REL} and included in COVERAGE_SOURCE_FILES; "
                       "this runner-bound lock still does not authorize collection - "
                       "separate reviewer live authorization is required before any "
                       "provider call, and the runner preflight must pass"),
            "adding_runner_authorizes_collection": False,
            "live_execution_rule": ("live execution is forbidden until the amended "
                                    "registration hash with the runner in the source binding "
                                    "has been reviewed and separately live-authorized; this "
                                    "lock is not live authorization"),
            "superseded_offline_lock": {
                "preregistration_hash": SUPERSEDED_OFFLINE_LOCK_HASH,
                "note": ("runner-less offline lock superseded by this runner-bound "
                         "amendment; the verifier rejects the superseded hash"),
            },
        },
        "evidence_requirements": [
            "writer outcomes by agent and turn",
            "accepted/rejected board writes",
            "exact claim and ownership",
            "authoritative I_m from A's perspective",
            "write/read event sequence and exposure ID",
            "B->A direction",
            "Jev receiver attempted/valid/invalid status",
            "normalized and raw probability vectors plus diagnostics",
            "request/state hashes and protocol key",
            "model/version and usage",
            "provider physical-attempt counters",
            "prompt_form_id",
            "raw_response_retained=false",
            "credentials_retained=false",
        ],
        "eligibility_rule": eligibility_rule(),
        "coverage_outcomes": {
            "six_forms_covered": "release the coverage gate for #192/#193 review",
            "five_forms_covered": ("interval-only descriptive fallback; no alpha=0.05 two-sided "
                                   "sign-flip claim is permitted"),
            "fewer_than_five_or_gate_failure": ("stop and report inducement/coverage failure when "
                                                "fewer than five forms are covered or the "
                                                "validity/provenance gates fail"),
            "collection_starts_no_159": "collection itself must not start #159",
            "decision_owner": "#192 makes the coverage decision; this registration only collects "
                              "the evidence",
        },
        "stop_rules": sorted(set(pr.JEV_REPLAY_STOP_RULES) |
                             {"writer_error_terminal", "writer_rate_limited_terminal",
                              "empty_output", "truncated_output", "unparsed_output",
                              "invalid_answer", "not_normalized_hard",
                              "argmax_shifted_on_renormalization", "output_exists",
                              "report_exists"}),
        "invalidity_classes": {
            "writer_stop": sorted(bridge.STOP_WRITER_OUTCOMES),
            "writer_rejected": ["non_owned_claim"],
            "receiver": sorted(jc2.JEV_V2_INVALID_CLASSES),
            "provenance": sorted(set(audit.REJECTIONS) | {"unverified_real_evidence"}),
        },
        "caps": {
            "planned_calls": {
                "ling": PLANNED_LING, "jev": PLANNED_JEV, "combined": PLANNED_REQUESTS,
                "ling_per_instance": PLANNED_LING_PER_INSTANCE,
                "jev_per_instance": PLANNED_JEV_PER_INSTANCE,
                "arithmetic": (f"Ling = {BLOCK_N} instances x {PLANNED_LING_PER_INSTANCE} writer "
                               f"calls (2 agents x 2 turns) = {PLANNED_LING}; "
                               f"Jev = {BLOCK_N} instances x 1 receiver = {PLANNED_JEV}; "
                               f"combined = {PLANNED_REQUESTS}"),
            },
            "physical_requests": COMBINED_REQUEST_CAP,
            "provider_partition": {
                "jev": JEV_REQUEST_CAP, "ling": LING_REQUEST_CAP,
                "total": COMBINED_REQUEST_CAP,
                "arithmetic": (f"retry-inclusive: each partition = planned x (1 + registered "
                               f"max_retries={pr.JEV_REPLAY_MAX_RETRIES}) = planned x "
                               f"{RETRY_RESERVE_FACTOR}: Ling {PLANNED_LING}x{RETRY_RESERVE_FACTOR}"
                               f"={LING_REQUEST_CAP}, Jev {PLANNED_JEV}x{RETRY_RESERVE_FACTOR}="
                               f"{JEV_REQUEST_CAP}; combined {LING_REQUEST_CAP}+{JEV_REQUEST_CAP}"
                               f"={COMBINED_REQUEST_CAP}"),
                "note": ("partitions are non-overlapping by provider; every physical attempt "
                         "including retries is counted against the issuing provider; "
                         f"no-retry execution needs only {PLANNED_REQUESTS} <= "
                         f"{COMBINED_REQUEST_CAP} with {PLANNED_LING} <= {LING_REQUEST_CAP} and "
                         f"{PLANNED_JEV} <= {JEV_REQUEST_CAP}"),
            },
            "retry_reserve": {
                "per_call_max_physical_attempts": RETRY_RESERVE_FACTOR,
                "max_retries": pr.JEV_REPLAY_MAX_RETRIES,
                "combined_reserve": COMBINED_REQUEST_CAP - PLANNED_REQUESTS,
            },
            "cost_cap_usd": COST_CAP_USD,
            "input_token_ceiling": INPUT_TOKEN_CEILING,
            "input_usd_per_mtok": INPUT_USD_PER_MTOK,
            "worst_case_call_cost_usd": WORST_CASE_CALL_COST_USD,
            "worst_case_cost_usd": WORST_CASE_COST_USD,
            "worst_case_arithmetic": (f"{COMBINED_REQUEST_CAP} x {INPUT_TOKEN_CEILING} tokens x "
                                      f"${INPUT_USD_PER_MTOK}/Mtok / 1e6 = "
                                      f"${WORST_CASE_COST_USD} <= ${COST_CAP_USD} ceiling"),
            "pacing": {"min_attempt_interval_seconds": writer_v3.LING_MIN_ATTEMPT_INTERVAL_SECONDS,
                       "algorithm": writer_v3.LING_PACING_ALGORITHM,
                       "scope": "every Ling physical attempt, across logical calls and retries"},
            "status": ("locked; live_collection_authorized=false" if approved
                       else "draft; not authorized"),
        },
        "outputs": output_paths(),
        "live_collection_authorized": False,
        "lock_is_not_live_authorization": True,
    }
    payload = json.dumps({key: value for key, value in document.items()
                          if key != "preregistration_hash"}, sort_keys=True)
    document["preregistration_hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return document


def _prior_id_set(repo_root: Path | None = None) -> set[str]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    return _collect_prior_ids(root)


def verify_against_coverage_manifest_preregistration_v6(
        document: Mapping[str, Any], *, repo_root: Path | None = None,
        model: str | None = None, endpoint: str | None = None,
        protocol_key: str | None = None, check_credentials: bool = False,
        ling_key_present: bool | None = None, journal_exists: bool | None = None,
        report_exists: bool | None = None) -> dict[str, Any]:
    """Repository-backed verifier; fails closed on any registered drift.

    Offline by default (``check_credentials=False``). The credential checks run
    only when a proposed live preflight is being validated; they read local
    environment/files and never issue a request.
    """

    root = Path(repo_root) if repo_root is not None else _repo_root()
    errors: list[str] = []

    if document.get("preregistration_version") != COVERAGE_PREREG_VERSION:
        errors.append("wrong registration version")
    if document.get("status") != COVERAGE_LOCKED_STATUS:
        errors.append("registration is not locked for the coverage manifest v6")
    if document.get("approval_required") or not document.get("approval", {}).get("approved"):
        errors.append("registration lock approval is missing")
    if document.get("approval", {}).get("scope") != "v6_registration_lock_only":
        errors.append("approval scope is not the v6 registration lock")
    if document.get("approval", {}).get("live_collection_authorized") is not False:
        errors.append("lock must not authorize live collection")
    if document.get("live_collection_authorized") is not False:
        errors.append("live_collection_authorized must be false")
    if document.get("lock_is_not_live_authorization") is not True:
        errors.append("lock-is-not-live-authorization declaration missing")

    try:
        expected = build_coverage_manifest_preregistration_v6(approved=True, repo_root=root)
    except Exception as exc:  # fail closed: drift or missing inputs
        errors.append(f"rebuild_failed: {type(exc).__name__}: {exc}")
        expected = None
    if expected is not None:
        if document.get("preregistration_hash") != expected.get("preregistration_hash"):
            errors.append("registration hash drift from the repository state")
        recorded = {key: value for key, value in document.items() if key != "preregistration_hash"}
        wanted = {key: value for key, value in expected.items() if key != "preregistration_hash"}
        if recorded != wanted:
            errors.append("registration content drift from the repository state")
        generator = document.get("generator", {})
        expected_generator = expected.get("generator", {})
        if generator.get("source_files_hash") != expected_generator.get("source_files_hash"):
            errors.append("source hash drift from the repository state")
        if generator.get("manifest_treatment_hash") != expected_generator.get(
                "manifest_treatment_hash"):
            errors.append("manifest treatment hash drift from the repository state")
        if generator.get("information_geometry_hash") != expected_generator.get(
                "information_geometry_hash"):
            errors.append("information geometry hash drift from the repository state")
        try:
            if generator.get("source_files_hash") != _source_files_hash(root):
                errors.append("source hash does not match the checked-out sources")
        except ValueError as exc:
            errors.append(f"source hash unavailable: {exc}")

    manifest = document.get("manifest", {})
    instance_ids = [str(item) for item in manifest.get("instance_ids", [])]
    if len(instance_ids) != BLOCK_N:
        errors.append(f"manifest must contain exactly {BLOCK_N} instance ids")
    if len(set(instance_ids)) != len(instance_ids):
        errors.append("manifest contains duplicate instance ids")
    if manifest.get("n") != BLOCK_N or manifest.get("instances_per_form") != INSTANCES_PER_FORM \
            or manifest.get("paired_forms") != FORM_COUNT:
        errors.append("manifest n / instances-per-form / form count drift")
    if set(manifest.get("iso_form_ids", [])) != set(FROZEN_FORM_IDS):
        errors.append("manifest form set is not the #189 frozen six-form set")
    form_counts = manifest.get("form_counts", {})
    if set(form_counts) != set(FROZEN_FORM_IDS) or any(
            form_counts.get(form) != INSTANCES_PER_FORM for form in FROZEN_FORM_IDS):
        errors.append("every frozen form must have exactly six instances")
    if manifest.get("manifest_hash") != hashlib.sha256(
            json.dumps(instance_ids, sort_keys=True).encode()).hexdigest():
        errors.append("manifest hash mismatch")
    if manifest.get("form_manifest_hash") != hashlib.sha256(
            json.dumps(sorted(FROZEN_FORM_IDS), sort_keys=True).encode()).hexdigest():
        errors.append("form manifest hash mismatch")

    membership = manifest.get("form_membership", {})
    if set(membership) != set(FROZEN_FORM_IDS):
        errors.append("form membership keys are not the frozen six forms")
    seen: set[str] = set()
    for form, ids in membership.items():
        if len(ids) != INSTANCES_PER_FORM:
            errors.append(f"form {form} does not have exactly six instances")
        if set(ids) & seen:
            errors.append("an instance appears in more than one form")
        seen.update(str(item) for item in ids)
    if seen != set(instance_ids):
        errors.append("form membership does not partition the manifest instance ids")
    for instance_id in sorted(seen):
        match = _INSTANCE_ID_RE.match(instance_id)
        if not match:
            errors.append(f"malformed planning instance id: {instance_id}")
            continue
        seed = int(match.group(1), 16)
        instance = tf.generate_instance("planning", seed, DependenceRegime.N,
                                        ReasoningComplexity.LOW)
        if instance.instance_id != instance_id:
            errors.append(f"instance id does not match its seed: {instance_id}")
        form = audit.pre_read_form_ids([instance])[instance_id]
        if instance_id not in membership.get(form, []):
            errors.append(f"instance {instance_id} is registered under the wrong form")

    overlap = sorted(set(instance_ids) & _prior_id_set(root))
    if overlap:
        errors.append(f"manifest overlaps prior instance ids: {overlap[:5]}")
    if manifest.get("disjointness", {}).get("ok") is not True \
            or manifest.get("disjointness", {}).get("overlap"):
        errors.append("recorded disjointness evidence is not clean")

    protocol = document.get("model_and_protocol", {})
    key = str(protocol_key or protocol.get("protocol_key", ""))
    if protocol_key is not None and protocol_key != protocol.get("protocol_key"):
        errors.append("runtime protocol key differs from the registration")
    if not key or jc.is_jev_protocol_key(key):
        errors.append("protocol key is missing or a v1 key")
    elif not jc2.is_jev_v2_protocol_key(key):
        errors.append("protocol key is not a v2 Jev key")
    elif key != protocol_key_v6():
        errors.append("protocol key is not reproducible from the locked settings")
    resolved_model = model if model is not None else protocol.get("model")
    resolved_endpoint = endpoint if endpoint is not None else protocol.get("endpoint")
    if resolved_model != pr.JEV_REPLAY_MODEL:
        errors.append("wrong Jev model")
    if resolved_endpoint != pr.JEV_REPLAY_ENDPOINT:
        errors.append("wrong Jev endpoint")
    if model is not None and model != protocol.get("model"):
        errors.append("runtime model differs from the registration")
    if endpoint is not None and endpoint != protocol.get("endpoint"):
        errors.append("runtime endpoint differs from the registration")
    if protocol.get("codec_version") != jc2.JEV_CHOICE_V2_CODEC_VERSION:
        errors.append("codec version drift")
    if protocol.get("state_schema") != jc.JEV_CHOICE_STATE_SCHEMA:
        errors.append("state schema drift")
    if protocol.get("max_retries") != pr.JEV_REPLAY_MAX_RETRIES \
            or protocol.get("retryable_statuses") != sorted(jc.JEV_RETRYABLE_STATUSES):
        errors.append("Jev retry policy drift")

    wire_keys: set[str] = set()

    def _collect_keys(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                _collect_keys(value)
        elif isinstance(node, list):
            for value in node:
                _collect_keys(value)
        elif isinstance(node, str) and node.startswith("jev-choice-wire") and "|" in node:
            wire_keys.add(node)

    _collect_keys(document)
    if wire_keys - {key}:
        errors.append("mixed or non-Jev protocol keys present")

    treatment = document.get("treatment", {})
    if treatment.get("mode") != bridge.BRIDGE_VERSION:
        errors.append("bridge treatment mode drift")
    if treatment.get("family") != "planning" or treatment.get("complexity") != "low" \
            or treatment.get("regime") != "N":
        errors.append("family/complexity/regime drift")
    if treatment.get("turns") != ladder.EXACT_BRIDGE_TURNS \
            or list(treatment.get("agents", [])) != list(ladder.EXACT_BRIDGE_AGENTS):
        errors.append("turns/agents drift")
    if treatment.get("token_budget") != ladder.EXACT_BRIDGE_TOKEN_BUDGET:
        errors.append("token budget drift")
    if treatment.get("seed_algorithm") != ladder.EXACT_BRIDGE_SEED_ALGORITHM:
        errors.append("seed algorithm drift")
    if treatment.get("exposure_id") != bridge.JEV_FINALIZER_EXPOSURE_ID:
        errors.append("exposure id drift")
    if treatment.get("primary_direction") != "one-way B->A" \
            or treatment.get("final_receiver") != f"{RECEIVER_AGENT} via Jev Choice wire v2":
        errors.append("direction/receiver drift")
    if treatment.get("writer_prompt") != prompt_binding():
        errors.append("prompt path/schema/grammar hash drift")
    if treatment.get("writer_transport") != writer_v3.writer_transport_spec():
        errors.append("writer transport/pacing/retry drift")
    if treatment.get("writer_observability") != writer_v5.writer_schema():
        errors.append("writer observability schema drift")
    if document.get("coverage_design", {}).get("fixed_n") is not True \
            or document.get("coverage_design", {}).get("n") != BLOCK_N:
        errors.append("fixed-N contract missing")
    if document.get("coverage_design", {}).get("no_seed_replacement") is None:
        errors.append("no-seed-replacement contract missing")

    runner_policy = document.get("runner_policy", {})
    if runner_policy.get("required_before_live") is not True:
        errors.append("runner policy missing: the #191 runner must be source-bound before live")
    if runner_policy.get("runner_implemented") is not True:
        errors.append("runner must be implemented and source-bound in this lock")
    if runner_policy.get("runner_source_files") != [RUNNER_SOURCE_REL]:
        errors.append("runner source file mismatch")
    if runner_policy.get("runner_source_bound") is not True:
        errors.append("runner source binding declaration missing")
    if RUNNER_SOURCE_REL not in COVERAGE_SOURCE_FILES:
        errors.append("runner module missing from COVERAGE_SOURCE_FILES")
    if runner_policy.get("adding_runner_authorizes_collection") is not False:
        errors.append("adding the runner must not authorize collection")
    if "live execution is forbidden" not in str(runner_policy.get("live_execution_rule", "")):
        errors.append("live-execution rule for the amended runner lock is missing")
    superseded = runner_policy.get("superseded_offline_lock", {})
    if superseded.get("preregistration_hash") != SUPERSEDED_OFFLINE_LOCK_HASH:
        errors.append("superseded offline lock hash missing or drifted")

    caps = document.get("caps", {})
    planned = caps.get("planned_calls", {})
    partition = caps.get("provider_partition", {})
    if (planned.get("ling") != PLANNED_LING or planned.get("jev") != PLANNED_JEV
            or planned.get("combined") != PLANNED_REQUESTS):
        errors.append("planned call arithmetic drift (expected 144/36/180)")
    if caps.get("physical_requests") != COMBINED_REQUEST_CAP:
        errors.append("combined physical request cap drift")
    if partition.get("jev") != JEV_REQUEST_CAP or partition.get("ling") != LING_REQUEST_CAP \
            or partition.get("total") != COMBINED_REQUEST_CAP:
        errors.append("provider partition drift")
    if int(partition.get("jev", 0)) + int(partition.get("ling", 0)) != \
            int(partition.get("total", -1)):
        errors.append("provider partitions do not sum to the combined cap")
    if PLANNED_LING > LING_REQUEST_CAP or PLANNED_JEV > JEV_REQUEST_CAP \
            or PLANNED_REQUESTS > COMBINED_REQUEST_CAP:
        errors.append("planned calls exceed the registered caps")
    if float(caps.get("cost_cap_usd", 0.0)) != COST_CAP_USD:
        errors.append("cost ceiling drift")
    if float(caps.get("worst_case_cost_usd", 1e9)) > float(caps.get("cost_cap_usd", 0.0)):
        errors.append("worst-case cost exceeds the cost ceiling")
    if caps.get("input_token_ceiling") != INPUT_TOKEN_CEILING \
            or caps.get("input_usd_per_mtok") != INPUT_USD_PER_MTOK:
        errors.append("token ceiling or price drift")
    if caps.get("pacing", {}).get("min_attempt_interval_seconds") != \
            writer_v3.LING_MIN_ATTEMPT_INTERVAL_SECONDS:
        errors.append("Ling pacing drift")

    outputs = document.get("outputs", {})
    if outputs != output_paths():
        errors.append("output paths differ from the fresh v6 paths")
    for old in OLD_OUTPUT_PATHS_V6:
        if any(old in str(value) for value in outputs.values()):
            errors.append(f"old v1-v5 output path rejected: {old}")
    journal_path = root / DEFAULT_JOURNAL_V6
    report_path = root / DEFAULT_REPORT_V6
    journal_bad = journal_exists if journal_exists is not None else journal_path.exists()
    report_bad = report_exists if report_exists is not None else report_path.exists()
    if journal_bad:
        errors.append("future coverage journal already exists")
    if report_bad:
        errors.append("future coverage report already exists")

    audit_path = root / DEFAULT_AUDIT_V1
    if not audit_path.is_file():
        errors.append("missing #189 audit artifact")
    else:
        audit_document = json.loads(audit_path.read_text(encoding="utf-8"))
        audit_forms = sorted(row.get("prompt_form_id")
                             for row in audit_document.get("forms", []))
        if audit_forms != sorted(FROZEN_FORM_IDS):
            errors.append("#189 audit artifact form set drift")

    if check_credentials:
        credentials = jc.load_jev_credentials()
        if not (credentials.present and credentials.shape_ok):
            errors.append("jev credentials missing for the proposed live preflight")
        ling_ok = bd._api_key() is not None if ling_key_present is None else bool(ling_key_present)
        if not ling_ok:
            errors.append("ling credentials missing for the proposed live preflight")

    return {
        "ok": not errors,
        "errors": errors,
        "registration_hash": document.get("preregistration_hash"),
        "manifest_hash": manifest.get("manifest_hash"),
        "planned_requests": PLANNED_REQUESTS,
        "request_cap": COMBINED_REQUEST_CAP,
        "live_collection_authorized": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="#190 coverage-manifest preregistration v6")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_V6)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--approve", action="store_true",
                        help="write the locked registration (offline lock, never live authorization)")
    args = parser.parse_args(argv)
    document = build_coverage_manifest_preregistration_v6(approved=args.approve,
                                                          repo_root=args.repo_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
                           encoding="utf-8")
    verification = verify_against_coverage_manifest_preregistration_v6(
        document, repo_root=args.repo_root)
    print(json.dumps({
        "preregistration_version": document["preregistration_version"],
        "status": document["status"],
        "live_collection_authorized": document["live_collection_authorized"],
        "manifest_n": document["manifest"]["n"],
        "instances_per_form": document["manifest"]["instances_per_form"],
        "manifest_hash": document["manifest"]["manifest_hash"],
        "planned_calls": document["caps"]["planned_calls"],
        "request_cap": document["caps"]["physical_requests"],
        "cost_cap_usd": document["caps"]["cost_cap_usd"],
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
    "COVERAGE_PREREG_VERSION", "COVERAGE_DRAFT_STATUS", "COVERAGE_LOCKED_STATUS",
    "DEFAULT_OUTPUT_V6", "DEFAULT_JOURNAL_V6", "DEFAULT_REPORT_V6", "DEFAULT_AUDIT_V1",
    "SEED_SCAN_BASE", "SEED_SCAN_WINDOW", "SEED_SCAN_END", "INSTANCES_PER_FORM",
    "FORM_COUNT", "BLOCK_N", "FROZEN_FORM_IDS", "PLANNED_LING", "PLANNED_JEV",
    "PLANNED_REQUESTS", "RETRY_RESERVE_FACTOR", "LING_REQUEST_CAP", "JEV_REQUEST_CAP",
    "COMBINED_REQUEST_CAP", "COST_CAP_USD", "WORST_CASE_CALL_COST_USD",
    "WORST_CASE_COST_USD", "PRIOR_SEED_RANGES", "PRIOR_SCAN_PATTERNS",
    "OLD_OUTPUT_PATHS_V6", "COVERAGE_SOURCE_FILES", "V6_OWNED_FILE_NAMES", "V6_OWNED_PATHS",
    "RUNNER_SOURCE_REL", "SUPERSEDED_OFFLINE_LOCK_HASH",
    "output_paths", "prompt_binding", "protocol_key_v6", "prior_instance_ids",
    "scan_window", "select_form_balanced_manifest", "manifest_treatment_hash",
    "treatment_hash_v6", "sizing_rationale", "eligibility_rule",
    "build_coverage_manifest_preregistration_v6",
    "verify_against_coverage_manifest_preregistration_v6", "main",
]
