"""#200 — draft offline preregistration for a non-planning Jev replay replication.

Everything here is **offline and draft**. No provider call is made by any code
path in this module, the registration is written with
``status = draft_pending_review`` and ``live_collection_authorized = false``, and
locking (when a reviewer eventually approves it) is never treated as execution
approval.

What it produces:

1. A deterministic **form-capacity audit** over a fixed, disjoint seed window,
   with a second disjoint window used only to test whether the prompt-form
   space is closed, plus a third window reserved for a fresh-seed confirmation
   block. Prompt form identity is derived only from generator/task structure —
   the sha256 of the model-visible ISO pre-read request body.
2. A **draft registration** freezing the replication design (original L4X
   communication treatment, Jev receiver, real/placebo/null branches, one-way
   B-to-A exposure with authoritative ownership/board-log/exposure/I_m checks,
   equal-weight form-level estimand, no instance-level primary inference, no
   imputation), family-level multiplicity and confirmation rules, and all
   operational settings.

Selection of the family is outcome-blind: an alphabetically-first rule over the
non-planning families that pass structural preconditions. No prior live outcome
is consulted, and the planning-low estimate and p-value are never used as a
prior or an effect-size guarantee.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import behavioral_discovery as bd
from . import communication_protocol as cp
from . import finite_information as fi
from . import jev_choice as jc
from . import jev_choice_v2 as jc2
from . import jev_coverage_manifest_preregistration_v6 as prv6
from . import jev_coverage_manifest_preregistration_v7 as prv7
from . import jev_ling_writer_v3 as w3
from . import jev_ling_writer_v5 as w5
from . import jev_replay as jr
from . import jev_replay_preregistration as pr
from . import jev_replay_preregistration_v2 as prv2
from . import jev_replay_preregistration_v4 as prv4
from . import jev_writer_ladder_v5 as ladder
from . import task_families as tf


REPLICATION_VERSION = "stage3-jev-replay-replication-v1"
DRAFT_STATUS = "draft_pending_review"
LOCKED_STATUS = "locked_for_jev_replay_replication"
AUDIT_VERSION = "jev-replication-form-audit-v1"

AUDIT_PATH = Path("runs/epic-126/replication/jev-replication-form-audit-v1.json")
REGISTRATION_PATH = Path("runs/epic-126/replication/jev-replication-preregistration-v1.json")
COLLECTION_JOURNAL = Path("runs/epic-126/replication/jev-replication-collection.jsonl")
COLLECTION_REPORT = Path("runs/epic-126/replication/jev-replication-collection-report.json")
REPLAY_JOURNAL = Path("runs/epic-126/replication/jev-replay-replication.jsonl")
REPLAY_REPORT = Path("runs/epic-126/replication/jev-replay-replication-report.json")
OWNED_PATHS = (str(AUDIT_PATH), str(REGISTRATION_PATH), str(COLLECTION_JOURNAL),
               str(COLLECTION_REPORT), str(REPLAY_JOURNAL), str(REPLAY_REPORT))
OUTPUT_PATHS = {"collection_journal": str(COLLECTION_JOURNAL),
                "collection_report": str(COLLECTION_REPORT),
                "replay_journal": str(REPLAY_JOURNAL),
                "replay_report": str(REPLAY_REPORT),
                "audit": str(AUDIT_PATH), "registration": str(REGISTRATION_PATH)}

FAMILY_ORDER = ("hypothesis", "reference", "planning", "poetry", "legal", "lexicon")
EXCLUDED_FAMILIES = ("planning",)
NON_PLANNING_FAMILIES = tuple(name for name in FAMILY_ORDER if name not in EXCLUDED_FAMILIES)

# Fixed, disjoint seed windows. None overlaps a documented prior range.
SEED_SCAN_BASE = 85000
SEED_SCAN_WINDOW = 512
SEED_SCAN_END = SEED_SCAN_BASE + SEED_SCAN_WINDOW - 1
CLOSURE_PROBE_BASE = 86000
CLOSURE_PROBE_WINDOW = 512
CLOSURE_PROBE_END = CLOSURE_PROBE_BASE + CLOSURE_PROBE_WINDOW - 1
CONFIRMATION_SCAN_BASE = 87000
CONFIRMATION_SCAN_WINDOW = 512
CONFIRMATION_SCAN_END = CONFIRMATION_SCAN_BASE + CONFIRMATION_SCAN_WINDOW - 1
SEED_GROWTH_CHECKPOINTS = (32, 64, 128, 256, 512)

INSTANCES_PER_FORM = 4
FORMS_PER_BLOCK = 4
BLOCK_N = INSTANCES_PER_FORM * FORMS_PER_BLOCK
BLOCKS = ("primary", "confirmation")

#: Every documented prior seed range (all families, all recorded blocks).
PRIOR_SEED_RANGES = (
    (16000, 17104), (39000, 39001), (41000, 41001),
    (70000, 70016), (71000, 71016), (72000, 72016), (73000, 73016),
    (74000, 74016), (75000, 75255), (80000, 80016),
)
PRIOR_SCAN_PATTERNS = ("runs/epic-126/**/*.json", "runs/epic-126/**/*.jsonl",
                       "runs/*.json", "runs/*.jsonl")

SOURCE_FILES = (
    "src/apart_incident_response/jev_replication_preregistration.py",
    "src/apart_incident_response/task_families.py",
    "src/apart_incident_response/communication_protocol.py",
    "src/apart_incident_response/finite_information.py",
    "src/apart_incident_response/jev_choice.py",
    "src/apart_incident_response/jev_choice_v2.py",
    "src/apart_incident_response/jev_replay.py",
    "src/apart_incident_response/jev_replay_preregistration.py",
    "src/apart_incident_response/jev_replay_preregistration_v2.py",
    "src/apart_incident_response/jev_replay_preregistration_v4.py",
    "src/apart_incident_response/behavioral_discovery.py",
    "src/apart_incident_response/jev_ling_writer_v3.py",
    "src/apart_incident_response/jev_ling_writer_v5.py",
    "src/apart_incident_response/jev_coverage_manifest_preregistration_v6.py",
    "src/apart_incident_response/jev_coverage_manifest_preregistration_v7.py",
    "src/apart_incident_response/jev_writer_ladder_v5.py",
)

#: Frozen cost model (USD per million tokens) used for every bound below.
LING_PROMPT_USD_PER_MTOK = 0.06
LING_COMPLETION_USD_PER_MTOK = 0.18
LING_INPUT_TOKEN_CEILING = 8192
LING_OUTPUT_TOKEN_CEILING = 1024
JEV_INPUT_USD_PER_MTOK = 0.042
JEV_INPUT_TOKEN_CEILING = 8192

#: Illustrative between-form SD recorded in #185/#189 from the J3 ISO-minus-FULL
#: method demonstration. Sensitivity only: never a prior, never a plug-in
#: variance, and not derived from the planning-low estimate or p-value.
ILLUSTRATIVE_BETWEEN_FORM_SD_BITS = 0.1933


class ReplicationError(ValueError):
    """Fail-closed audit, build or verification violation."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _render(document: Mapping[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n"


_INSTANCE_CACHE: dict[tuple[str, int], Any] = {}
_FORM_CACHE: dict[str, str] = {}


def instance_for(family: str, seed: int) -> Any:
    """Deterministic generator memoised for repeated offline scans."""

    key = (family, seed)
    if key not in _INSTANCE_CACHE:
        _INSTANCE_CACHE[key] = tf.generate_instance(family, seed, cp.DependenceRegime.N,
                                                    cp.ReasoningComplexity.LOW)
    return _INSTANCE_CACHE[key]


def _instance_id(family: str, seed: int) -> str:
    """Instance ids are a pure format of (family, seed); no generation needed."""

    return f"{family}-{seed:08x}"


def _content_hash(document: Mapping[str, Any]) -> str:
    payload = json.dumps({key: value for key, value in document.items()
                          if key != "preregistration_hash"}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_files_hash(repo_root: Path) -> str:
    digest = hashlib.sha256()
    missing = []
    for relative in SOURCE_FILES:
        path = repo_root / relative
        if not path.is_file():
            missing.append(relative)
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    if missing:
        raise ReplicationError(f"missing source files for hashing: {missing}")
    return digest.hexdigest()


# --------------------------------------------------------------------------
# family selection (outcome blind)
# --------------------------------------------------------------------------

def structural_preconditions(family: str, *, base: int, window: int) -> dict[str, Any]:
    """Offline generator-structure checks. No live outcome is consulted."""

    solutions_ok = True
    finalizer_needs_peer = True
    informative_claims = 0
    b_clues = 0
    a_clues = 0
    deltas: set[float] = set()
    for seed in range(base, base + window):
        instance = instance_for(family, seed)
        solutions_ok = solutions_ok and bool(instance.solutions) \
            and instance.private_solutions["A"] <= instance.solutions
        analysis = instance.channel_analysis()
        finalizer_needs_peer = finalizer_needs_peer and bool(
            analysis.get("finalizer_needs_peer"))
        b_clues = len(instance.private_clues.get("B", ()))
        a_clues = len(instance.private_clues.get("A", ()))
        for claim in instance.private_clues.get("B", ()):
            if instance.claim_owner(claim) != "B":
                continue
            info = instance.information("A", claim, "probe")
            if info.status == "accepted" and (info.delta_i_bits or 0.0) > 0.0:
                informative_claims += 1
                deltas.add(round(float(info.delta_i_bits), 9))
    return {"family": family, "closed_finite_solution_set": solutions_ok,
            "finalizer_needs_peer": finalizer_needs_peer,
            "informative_b_owned_claims": informative_claims,
            "b_clues_per_instance": b_clues, "a_clues_per_instance": a_clues,
            "b_to_a_information_bits": sorted(deltas),
            "eligible": bool(solutions_ok and finalizer_needs_peer and informative_claims)}


def select_family(*, base: int = SEED_SCAN_BASE, window: int = SEED_SCAN_WINDOW) -> dict[str, Any]:
    """Declared, reproducible, outcome-blind family selection rule.

    Rule: among the non-planning families, take the alphabetically first
    (bytewise ascending family identifier) that passes the structural
    preconditions. The rule does not consult form capacity, prior live results,
    the planning-low estimate, or the planning-low p-value.
    """

    evaluations = [structural_preconditions(name, base=base, window=window)
                   for name in sorted(NON_PLANNING_FAMILIES)]
    eligible = [entry for entry in evaluations if entry["eligible"]]
    if not eligible:
        raise ReplicationError("no non-planning family passes the structural preconditions")
    chosen = eligible[0]
    return {
        "rule": ("alphabetically first (bytewise ascending) non-planning family that passes "
                 "the offline structural preconditions"),
        "candidates_in_rule_order": [entry["family"] for entry in evaluations],
        "excluded_families": list(EXCLUDED_FAMILIES),
        "exclusion_reason": "planning is excluded by requirement; this must be a new family",
        "preconditions": ["closed finite solution set",
                          "A-finalizer structurally needs the peer clue",
                          "at least one B-owned claim that is informative for A"],
        "selected_family": chosen["family"],
        "selected_evaluation": chosen,
        "evaluations": evaluations,
        "outcome_blind": True,
        "consulted_prior_live_outcomes": [],
        "rationale": (
            "the rule is fixed in advance and cannot encode a preference, so the choice "
            "carries no information about favourability; it is evaluated on generator "
            "structure only, before any live outcome exists for this family"),
        "anti_prior_statement": (
            "no prior live result (L4X bridge, v6/v7 coverage, pilots, normalization probe, "
            "the selection screen or the planning-low replay) was consulted, and the "
            "planning-low estimate and p-value are not used as a prior, an expectation or "
            "an effect-size guarantee anywhere in this registration"),
    }


# --------------------------------------------------------------------------
# form capacity audit
# --------------------------------------------------------------------------

def pre_read_form_id(instance: tf.FamilyInstance) -> str:
    """prompt_form_id derived only from generator/task structure."""

    cached = _FORM_CACHE.get(instance.instance_id)
    if cached is not None:
        return cached
    _, state = prv4.pre_read_body(instance, pr.JEV_REPLAY_MODEL)
    body = jr.pre_read_request_body(
        state=dict(state.state), question_id=state.question_id,
        instructions=state.instructions,
        option_ids=[option.option_id for option in state.options],
        model=pr.JEV_REPLAY_MODEL)
    form = jr.prompt_form_id(body)
    _FORM_CACHE[instance.instance_id] = form
    return form


def _scan_forms(family: str, base: int, window: int) -> dict[str, Any]:
    forms: dict[str, list[int]] = defaultdict(list)
    checkpoints = []
    seen: set[str] = set()
    for offset in range(window):
        seed = base + offset
        instance = instance_for(family, seed)
        forms[pre_read_form_id(instance)].append(seed)
        seen.add(pre_read_form_id(instance))
        if (offset + 1) in SEED_GROWTH_CHECKPOINTS:
            checkpoints.append([offset + 1, len(seen)])
    return {"distinct_forms": len(forms),
            "forms": {form: sorted(seeds) for form, seeds in sorted(forms.items())},
            "growth_checkpoints": checkpoints}


def form_space_status(primary_forms: Iterable[str],
                      probe_forms: Iterable[str]) -> str:
    """closed when the disjoint probe window adds no new form."""

    primary, probe = set(primary_forms), set(probe_forms)
    if probe - primary:
        return "open"
    return "closed"


def _prior_instance_ids(repo_root: Path) -> dict[str, Any]:
    """Every instance id recorded in prior artifacts plus documented seed ranges."""

    found: set[str] = set()
    sources: list[str] = []
    id_pattern = re.compile(r'"instance_id":\s*"([^"]+)"')
    for pattern in PRIOR_SCAN_PATTERNS:
        for path in sorted(repo_root.glob(pattern)):
            if path.name in {Path(item).name for item in OWNED_PATHS}:
                continue
            sources.append(path.relative_to(repo_root).as_posix())
            try:
                if path.suffix == ".jsonl":
                    found.update(id_pattern.findall(
                        path.read_text(encoding="utf-8", errors="ignore")))
                else:
                    document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
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

            if path.suffix == ".json":
                walk(document)
    documented: list[str] = []
    for low, high in PRIOR_SEED_RANGES:
        for seed in range(low, high + 1):
            for family in FAMILY_ORDER:
                documented.append(_instance_id(family, seed))
    found.update(documented)
    ordered = sorted(found)
    return {"instance_id_count": len(ordered),
            "instance_ids_sha256": _digest(ordered),
            "sources": sorted(set(sources)),
            "seed_ranges": [{"low": low, "high": high} for low, high in PRIOR_SEED_RANGES],
            "documented_seed_id_count": len(documented),
            "_ids": ordered}


def _select_block(family: str, base: int, window: int,
                  forms: Sequence[str]) -> list[dict[str, Any]]:
    """First INSTANCES_PER_FORM seeds per form, ascending; fixed N, no stopping."""

    by_form: dict[str, list[int]] = defaultdict(list)
    for offset in range(window):
        seed = base + offset
        instance = instance_for(family, seed)
        by_form[pre_read_form_id(instance)].append(seed)
    manifest = []
    for form in sorted(forms):
        chosen = sorted(by_form.get(form, []))[:INSTANCES_PER_FORM]
        if len(chosen) != INSTANCES_PER_FORM:
            raise ReplicationError(f"form {form} has only {len(chosen)} seeds in the window")
        for seed in chosen:
            instance = instance_for(family, seed)
            manifest.append({"instance_id": instance.instance_id, "seed": seed,
                             "prompt_form_id": form})
    if len(manifest) != BLOCK_N:
        raise ReplicationError(f"block manifest must have exactly {BLOCK_N} instances")
    return manifest


def _instance_geometry(instance: tf.FamilyInstance) -> dict[str, Any]:
    b_claims = sorted(instance.private_clues.get("B", ()))
    a_claims = list(instance.private_clues.get("A", ()))
    if len(b_claims) != 1:
        raise ReplicationError(
            f"{instance.instance_id}: expected exactly one B-owned clue, found {len(b_claims)}")
    real_claim = b_claims[0]
    real_info = instance.information("A", real_claim, "real")
    if real_info.status != "accepted" or real_info.delta_i_bits is None \
            or not float(real_info.delta_i_bits) > 0.0:
        raise ReplicationError(f"{instance.instance_id}: B claim is not informative for A")
    if instance.holds_claim("A", real_claim) or not instance.holds_claim("B", real_claim):
        raise ReplicationError(f"{instance.instance_id}: real claim ownership drift")
    if real_claim in a_claims:
        raise ReplicationError(f"{instance.instance_id}: real claim already known to A")
    if not a_claims:
        raise ReplicationError(f"{instance.instance_id}: no receiver-known placebo clue")
    placebo_claim = a_claims[0]
    placebo_info = instance.information("A", placebo_claim, "placebo")
    if placebo_info.status != "accepted" or placebo_info.delta_i_bits is None \
            or float(placebo_info.delta_i_bits) != 0.0:
        raise ReplicationError(f"{instance.instance_id}: placebo claim is not inert")
    extended = instance.clue_consistent(set(a_claims) | {placebo_claim})
    if extended != instance.private_solutions["A"]:
        raise ReplicationError(f"{instance.instance_id}: placebo does not reduce the feasible set")
    return {"instance_id": instance.instance_id, "seed": instance.seed,
            "option_ids": sorted(instance.solutions),
            "private_clues": {"A": list(a_claims), "B": b_claims},
            "joint_solutions": sorted(instance.joint_solutions),
            "real_claim": real_claim, "real_i_m_bits": float(real_info.delta_i_bits),
            "placebo_claim": placebo_claim, "placebo_i_m_bits": 0.0,
            "a_private_size": len(instance.private_solutions["A"]),
            "b_private_size": len(instance.private_solutions["B"]),
            "solution_count": len(instance.solutions)}


def branch_hashes(instance: tf.FamilyInstance, real_claim: str,
                  placebo_claim: str) -> dict[str, Any]:
    """Exact branch request/state hashes for all three replay branches."""

    body, iso_state = prv4.pre_read_body(instance, pr.JEV_REPLAY_MODEL)
    out: dict[str, Any] = {"pre_read_state_hash": jr.canonical_hash(dict(iso_state.state)),
                           "pre_read_request_body_hash": jr.prompt_form_id(body),
                           "branch_request_hashes": {}, "branch_state_hashes": {}}
    for branch, text in (("real", jr.serialize_message(real_claim)),
                         ("placebo", jr.serialize_placebo_message(placebo_claim)),
                         ("null", None)):
        branch_body = jr.branch_request_body(body, text)
        out["branch_request_hashes"][branch] = jr.prompt_form_id(branch_body)
        out["branch_state_hashes"][branch] = jr.canonical_hash(dict(branch_body["state"]))
    return out


def build_form_audit(repo_root: Path) -> dict[str, Any]:
    """Deterministic, offline form-capacity audit. No provider call."""

    root = Path(repo_root)
    selection = select_family()
    family = selection["selected_family"]

    primary = _scan_forms(family, SEED_SCAN_BASE, SEED_SCAN_WINDOW)
    probe = _scan_forms(family, CLOSURE_PROBE_BASE, CLOSURE_PROBE_WINDOW)
    status = form_space_status(primary["forms"], probe["forms"])
    forms = sorted(primary["forms"])
    if sorted(probe["forms"]) != forms:
        raise ReplicationError("closure probe disagrees with the primary form set")

    primary_manifest = _select_block(family, SEED_SCAN_BASE, SEED_SCAN_WINDOW, forms)
    confirmation_manifest = _select_block(family, CONFIRMATION_SCAN_BASE,
                                          CONFIRMATION_SCAN_WINDOW, forms)

    prior = _prior_instance_ids(root)
    primary_ids = [entry["instance_id"] for entry in primary_manifest]
    confirmation_ids = [entry["instance_id"] for entry in confirmation_manifest]
    overlap = sorted(set(primary_ids) & set(prior["_ids"])) \
        + sorted(set(confirmation_ids) & set(prior["_ids"]))
    cross = sorted(set(primary_ids) & set(confirmation_ids))
    seed_overlap = [pair for pair in PRIOR_SEED_RANGES
                    if not (SEED_SCAN_END < pair[0] or CONFIRMATION_SCAN_END < pair[1]
                            or CLOSURE_PROBE_END < pair[1] or pair[1] < SEED_SCAN_BASE)]

    geometry_rows = []
    for entry in list(primary_manifest) + list(confirmation_manifest):
        instance = instance_for(family, entry["seed"])
        if instance.instance_id != entry["instance_id"] \
                or _instance_id(family, entry["seed"]) != entry["instance_id"]:
            raise ReplicationError(f"instance id drift for seed {entry['seed']}")
        geometry_rows.append(_instance_geometry(instance))
    geometry_rows.sort(key=lambda row: row["instance_id"])

    document = {
        "audit_version": AUDIT_VERSION,
        "issue": "#200",
        "stage": "offline form-capacity audit for a non-planning replication",
        "family_selection": selection,
        "prompt_form_definition": {
            "unit": "prompt form",
            "derivation": ("sha256 of the model-visible ISO pre-read request body "
                           "(model + state + question/instructions/criteria) produced only "
                           "from generator/task structure; no outcome enters the hash"),
            "function": "jev_replay.prompt_form_id(jev_replay_preregistration_v4.pre_read_body(...))",
        },
        "windows": {
            "primary": {"base": SEED_SCAN_BASE, "window": SEED_SCAN_WINDOW,
                        "end": SEED_SCAN_END, "role": "form census and manifest selection"},
            "closure_probe": {"base": CLOSURE_PROBE_BASE, "window": CLOSURE_PROBE_WINDOW,
                              "end": CLOSURE_PROBE_END,
                              "role": "closure test only; no seed may be selected from it"},
            "confirmation": {"base": CONFIRMATION_SCAN_BASE, "window": CONFIRMATION_SCAN_WINDOW,
                             "end": CONFIRMATION_SCAN_END,
                             "role": "fresh-seed confirmation block manifest"},
            "disjoint_from_documented_prior_ranges": not seed_overlap,
            "documented_prior_range_overlaps": [list(pair) for pair in seed_overlap],
        },
        "form_capacity": {
            "family": family,
            "primary_distinct_forms": primary["distinct_forms"],
            "primary_growth_checkpoints": primary["growth_checkpoints"],
            "per_form_seed_counts": {form: len(seeds)
                                     for form, seeds in sorted(primary["forms"].items())},
            "closure_probe_distinct_forms": probe["distinct_forms"],
            "closure_probe_growth_checkpoints": probe["growth_checkpoints"],
            "new_forms_in_closure_probe": len(set(probe["forms"]) - set(primary["forms"])),
            "space": status,
            "closed": status == "closed",
            "form_ids": forms,
            "form_set_hash": _digest(sorted(forms)),
            "k_max": len(forms),
        },
        "structure": selection["selected_evaluation"],
        "instance_geometry": {
            "rows": geometry_rows,
            "information_geometry_hash": _digest(geometry_rows),
            "distinct_real_i_m_bits": sorted({row["real_i_m_bits"] for row in geometry_rows}),
            "distinct_a_private_sizes": sorted({row["a_private_size"] for row in geometry_rows}),
            "distinct_solution_counts": sorted({row["solution_count"] for row in geometry_rows}),
        },
        "blocks": {
            "instances_per_form": INSTANCES_PER_FORM,
            "block_n": BLOCK_N,
            "primary": {"manifest": primary_manifest, "form_membership": _membership(primary_manifest),
                        "manifest_hash": _digest(primary_manifest)},
            "confirmation": {"manifest": confirmation_manifest,
                             "form_membership": _membership(confirmation_manifest),
                             "manifest_hash": _digest(confirmation_manifest)},
            "selection_rule": ("first INSTANCES_PER_FORM seeds per form in ascending seed order "
                               "within the window; fixed N; no outcome-based stopping"),
        },
        "disjointness": {
            "prior_instance_id_count": prior["instance_id_count"],
            "prior_instance_ids_sha256": prior["instance_ids_sha256"],
            "prior_sources": prior["sources"],
            "documented_seed_ranges": prior["seed_ranges"],
            "selected_ids_overlapping_prior": sorted(overlap),
            "primary_vs_confirmation_overlap": sorted(cross),
            "selected_seeds": sorted({entry["seed"] for entry in
                                      primary_manifest + confirmation_manifest}),
            "disjoint_from_all_prior_artifacts": not overlap and not cross,
        },
    }
    document["audit_content_hash"] = _digest(document)
    return document


def _membership(manifest: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for entry in manifest:
        out[str(entry["prompt_form_id"])].append(str(entry["instance_id"]))
    return {form: sorted(ids) for form, ids in sorted(out.items())}


# --------------------------------------------------------------------------
# registration (draft)
# --------------------------------------------------------------------------

def prompt_binding() -> dict[str, Any]:
    return prv6.prompt_binding()


def information_geometry_hash(audit: Mapping[str, Any]) -> str:
    return str(audit["instance_geometry"]["information_geometry_hash"])


def manifest_treatment_hash(audit: Mapping[str, Any]) -> str:
    rows = []
    for name in BLOCKS:
        for entry in audit["blocks"][name]["manifest"]:
            instance = instance_for(str(audit["family_selection"]["selected_family"]),
                                   int(entry["seed"]))
            rows.append({"block": name, "instance_id": instance.instance_id,
                         "seed": instance.seed, "iso_form_id": entry["prompt_form_id"],
                         "option_ids": sorted(instance.solutions),
                         "private_clues": {"A": list(instance.private_clues.get("A", ())),
                                           "B": list(instance.private_clues.get("B", ()))},
                         "joint_solutions": sorted(instance.joint_solutions)})
    return _digest(rows)


def replication_treatment_hash(*, manifest_treatment: str, geometry: str,
                               prompt_hash: str) -> str:
    return _digest({
        "manifest_treatment_hash": manifest_treatment,
        "information_geometry_hash": geometry,
        "prompt_hash": prompt_hash,
        "normalization_policy_hash": prv2.normalization_policy_hash(),
        "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
        "protocol_key": prv4.prv6_protocol_key(),
        "writer_schema_hash": w5.writer_schema_hash(),
        "writer_transport_version": w3.LING_WRITER_TRANSPORT_VERSION,
        "branch_modes": ["real", "placebo", "null"],
        "primary_direction": "one-way B->A",
        "estimand": "equal-weight mean of the within-form means of H_real - H_placebo",
        "directional_prediction": "Delta < 0",
    })


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


def _caps() -> dict[str, Any]:
    """Two blocks x (collection then replay); every bound is retry inclusive."""

    blocks = len(BLOCKS)
    ling_logical = blocks * BLOCK_N * 4          # 2 agents x 2 turns per instance
    jev_collection = blocks * BLOCK_N * 1        # one final read per instance
    replay_events_max = blocks * BLOCK_N         # at most one event per collected instance
    jev_replay = replay_events_max * 3           # real / placebo / null
    ling_physical = ling_logical * 3
    jev_collection_physical = jev_collection * 3
    jev_replay_physical = jev_replay * 3
    cost = _cost_model()
    collection_worst = (ling_physical * cost["ling_worst_physical_call_usd"]
                        + jev_collection_physical * cost["jev_worst_physical_call_usd"])
    replay_worst = jev_replay_physical * cost["jev_worst_physical_call_usd"]
    return {
        "collection": {
            "planned": {"ling": ling_logical, "jev": jev_collection,
                        "combined": ling_logical + jev_collection},
            "physical": {"ling": ling_physical, "jev": jev_collection_physical,
                         "combined": ling_physical + jev_collection_physical},
            "cost_ceiling_usd": 0.40,
            "worst_case_cost_usd": round(collection_worst, 12),
            "next_call_reservation_usd": {"ling": round(cost["ling_worst_physical_call_usd"] * 3, 12),
                                          "jev": round(cost["jev_worst_physical_call_usd"] * 3, 12)},
        },
        "replay": {
            "planned": {"jev": jev_replay, "ling": 0, "combined": jev_replay},
            "physical": {"jev": jev_replay_physical, "ling": 0, "combined": jev_replay_physical},
            "events_max": replay_events_max,
            "branches": 3,
            "cost_ceiling_usd": 0.15,
            "worst_case_cost_usd": round(replay_worst, 12),
            "next_call_reservation_usd": {"jev": round(cost["jev_worst_physical_call_usd"] * 3, 12)},
        },
        "program": {
            "planned": {"ling": ling_logical, "jev": jev_collection + jev_replay,
                        "combined": ling_logical + jev_collection + jev_replay},
            "physical": {"ling": ling_physical,
                         "jev": jev_collection_physical + jev_replay_physical,
                         "combined": ling_physical + jev_collection_physical
                         + jev_replay_physical},
            "cost_ceiling_usd": 1.00,
            "worst_case_cost_usd": round(collection_worst + replay_worst, 12),
            "arithmetic": ("2 blocks x (collection: 16 x 4 Ling + 16 x 1 Jev; "
                           "replay: <=16 events x 3 Jev), each x (1 + max_retries 2)"),
        },
        "cost_model": cost,
        "blocks": blocks,
        "block_n": BLOCK_N,
    }


def _attainable_sign_flip_floor() -> dict[str, str]:
    return {str(k): str(2 / (2 ** k)) for k in (4, 5, 6)}


def build_registration(repo_root: Path,
                       audit: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build the DRAFT replication registration. Never locks, never authorizes."""

    root = Path(repo_root)
    audit_document = dict(audit) if audit is not None else build_form_audit(root)
    family = str(audit_document["family_selection"]["selected_family"])
    capacity = audit_document["form_capacity"]
    k_max = int(capacity["k_max"])
    caps = _caps()
    prompt = prompt_binding()
    mde = (3.182 * ILLUSTRATIVE_BETWEEN_FORM_SD_BITS / (k_max ** 0.5)
           if k_max >= 2 else None)

    document: dict[str, Any] = {
        "preregistration_version": REPLICATION_VERSION,
        "status": DRAFT_STATUS,
        "stage": "non-planning-family replication of the matched Jev replay",
        "issue": "#159",
        "created_by_task": "#200",
        "purpose": ("preregister, before any live outcome exists, a replication of the matched "
                    "real/placebo/null Jev replay on exactly one non-planning task family, "
                    "with its form capacity, multiplicity control, confirmation rule and "
                    "operational bounds fixed in advance"),
        "approval_required": True,
        "approval": {"approved": False, "approved_by": None,
                     "scope": "replication_registration_lock_is_not_execution_approval",
                     "live_collection_authorized": False},
        "lock_does_not_imply_approval": True,
        "live_collection_authorized": False,
        "lock_is_not_live_authorization": True,
        "pending_review": [
            "reviewer decision on the family selection rule and the structural audit",
            "reviewer decision on the k_max = 4 inference consequence recorded below",
            "reviewer decision on caps, partitions and terminal stops",
            "a separate explicit live authorization reference is required before any "
            "provider call; locking this registration is not that authorization",
        ],
        "family": family,
        "family_selection": dict(audit_document["family_selection"]),
        "form_capacity": dict(capacity),
        "audit_binding": {
            "path": str(AUDIT_PATH),
            "audit_version": audit_document["audit_version"],
            "audit_content_hash": audit_document["audit_content_hash"],
            "form_set_hash": capacity["form_set_hash"],
            "form_ids": list(capacity["form_ids"]),
            "space": capacity["space"],
        },
        "manifests": {name: dict(audit_document["blocks"][name]) for name in BLOCKS},
        "disjointness": dict(audit_document["disjointness"]),
        "treatment": {
            "mode": "exact-original-comm-bridge",
            "family": family,
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
            "writer_prompt": prompt,
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
        },
        "branches": {
            "modes": ["real", "placebo", "null"],
            "real": ("the exact accepted B-owned claim for the pre-read state, bound per "
                     "instance as B's single owned private clue"),
            "placebo": ("controller-injected source-neutral re-presentation of a "
                        "receiver-already-known A clue with I_m = 0 and no feasible-set "
                        "reduction, same envelope as the real arm"),
            "null": "no message",
            "fixed_across_branches": ["receiver model", "option set", "wording", "target",
                                      "timing", "pre-read state C"],
            "only_difference": "state.visible_messages",
            "envelope": jr.MESSAGE_ENVELOPE_TEMPLATE,
            "placebo_origin": jr.PLACEBO_ORIGIN,
            "placebo_construction": jr.PLACEBO_CONSTRUCTION,
        },
        "authoritative_checks": {
            "ownership": "instance.holds_claim('B', claim) and not holds_claim('A', claim)",
            "board_log": "board_write then A peer_read_exposure with sequencing and exposure_id",
            "exposure": "nonempty exposure id recorded by the reader, never invented",
            "i_m": "authoritative ExactInformationEvaluator accepted with delta_i_bits > 0",
            "receiver_known": "the real claim must be absent from A's private clues",
            "deduplication": "at most one accepted B-owned informative claim per pre-read state",
            "a_to_b_excluded": True,
        },
        "estimand": {
            "experimental_unit": "prompt form",
            "event_contrast": "d_i = H_real,i - H_placebo,i",
            "form_contrast": "mean of d_i within prompt form f",
            "primary": ("equal-weight mean over the registered forms of the within-form mean "
                        "of H_real - H_placebo"),
            "directional_prediction": "Delta < 0",
            "events_are_independent_units": False,
            "unit_notes": ["repeated instances inside a form are averaged, never treated as "
                           "independent units",
                           "no instance-level t-test or Wilcoxon test may be primary"],
            "null_branch": {"excluded_from": "the primary real-versus-placebo contrast",
                            "retained_for": ["H_real - H_null", "H_placebo - H_null "
                                             "manipulation checks"]},
        },
        "inference_plan": {
            "primary_test": "exhaustive two-sided cluster sign-flip over the k form means",
            "interval": f"form-mean t interval with df = k - 1 (k = {k_max} => df = {k_max - 1})",
            "alpha": 0.05,
            "direction_requirement": "the observed equal-form mean must be negative",
            "minimum_forms_for_confirmatory": 5,
            "minimum_form_rule": ("a dichotomous confirmatory claim requires at least five "
                                  "distinct prompt forms; fewer than five is replay-coverage "
                                  "failure for any confirmatory claim"),
            "five_form_fallback": ("with exactly five forms the result is interval-only "
                                   "descriptive: a two-sided sign-flip p below 0.05 is "
                                   "forbidden and no causal gate is released"),
            "attainable_two_sided_floor_by_k": _attainable_sign_flip_floor(),
            "k_max_from_audit": k_max,
            "audit_finding": (
                f"the selected family's prompt-form space is closed at k = {k_max}, so the "
                f"attainable exact two-sided sign-flip floor is 2/{2 ** k_max} = "
                f"{2 / (2 ** k_max)}; that is above 0.05, so no dichotomous rejection at "
                "alpha = 0.05 is attainable at any effect size on this family"),
            "consequence": (
                "unless a reviewer approves a different form unit in a separate "
                "registration, this replication is preregistered as an estimation and "
                "descriptive study: the equal-form estimate and its t interval are reported "
                "and no significance-style claim is made"),
            "prohibited_as_primary": ["instance-level t-test", "instance-level Wilcoxon test",
                                      "instance-weighted mean",
                                      "treating events as independent states"],
            "imputation": "never impute missing pairs",
            "guards": {"target_probability_delta": 0.0, "feasible_set_mass_epsilon": 0.01,
                       "reporting": ("reported separately by form and event; never used to "
                                     "filter the primary entropy estimate"),
                       "useful_uptake_rule": ("an entropy drop alone is never useful uptake "
                                              "when either guard fails")},
            "missingness": {
                "complete_pair": "real and placebo both valid",
                "primary_requirement": "at least one complete pair in every registered form",
                "below_five_forms": "replay-coverage failure",
                "below_registered_forms": ("replay-coverage failure: every registered form "
                                           "must contribute at least one complete pair"),
            },
            "mde": {
                "formula": "t(0.975, k-1) x SD_between / sqrt(k)",
                "illustrative_sd_bits": ILLUSTRATIVE_BETWEEN_FORM_SD_BITS,
                "illustrative_sd_source": ("between-form SD recorded in #185/#189 from the J3 "
                                           "ISO-minus-FULL method demonstration; illustrative "
                                           "sensitivity only"),
                "illustrative_mde_bits": round(mde, 6) if mde is not None else None,
                "not_a_prior": ("the planning-low estimate and p-value are not used as a prior "
                                "or an effect-size guarantee; this family's own between-form SD "
                                "is unknown until data exist"),
                "null_result": ("a null result cannot exclude effects below the illustrative "
                                "figure above"),
            },
        },
        "multiplicity": {
            "family_level_control": "Holm step-down across the registered family set",
            "registered_family_set": [family],
            "registered_family_count": 1,
            "single_family_reduction": ("with exactly one registered family the Holm-adjusted "
                                        "p equals the raw p; no cross-family claim follows"),
            "family_set_frozen_before_outcomes": True,
            "future_families": ("any additional family requires its own preregistration and "
                                "its own confirmation block; it may never be added to this "
                                "family set after outcomes are visible"),
            "forbidden": ["sweeping families and selecting a winner post hoc",
                          "adding a family after outcomes are visible",
                          "removing a registered family after outcomes are visible"],
            "confirmation": {
                "required_before_any_claim": True,
                "block": "confirmation",
                "seed_window": {"base": CONFIRMATION_SCAN_BASE,
                                "window": CONFIRMATION_SCAN_WINDOW, "end": CONFIRMATION_SCAN_END},
                "selection": ("the same deterministic first-INSTANCES_PER_FORM-per-form rule "
                              "on a window disjoint from the primary block and from every "
                              "documented prior range"),
                "n": BLOCK_N,
                "may_not_pool_with_primary_for_primary_estimate": True,
                "role": "confirmatory only; reported separately",
            },
        },
        "operational_settings": {
            "jev": {"model": pr.JEV_REPLAY_MODEL, "endpoint": pr.JEV_REPLAY_ENDPOINT,
                    "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
                    "protocol_key": prv4.prv6_protocol_key(),
                    "max_retries": pr.JEV_REPLAY_MAX_RETRIES,
                    "retryable_statuses": sorted(jc.JEV_RETRYABLE_STATUSES),
                    "timeout_seconds": jc.JEV_TIMEOUT_DEFAULT,
                    "backoff": {"initial_seconds": jc.JEV_BACKOFF_INITIAL,
                                "max_seconds": jc.JEV_BACKOFF_MAX,
                                "jitter": jc.JEV_BACKOFF_JITTER}},
            "normalization": {"policy": prv2.normalization_policy(),
                              "policy_hash": prv2.normalization_policy_hash(),
                              "tiers": ["exact", "complete_renormalized"],
                              "hard_ceiling": 0.05,
                              "rule": "normalize every accepted vector before any metric"},
            "ling": {"model": prv7.PAID_LING_MODEL, "endpoint": pr.LING_ENDPOINT,
                     "key_loader": "behavioral_discovery._api_key",
                     "route": "paid OpenRouter SKU (the free SKU is not routable)",
                     "temperature": pr.LING_TEMPERATURE,
                     "pacing": "ling-writer-openrouter-pacing-v3, 3.25 s between physical attempts"},
            "partitions": {
                "collection": {"ling_physical": _caps()["collection"]["physical"]["ling"],
                               "jev_physical": _caps()["collection"]["physical"]["jev"],
                               "note": "retries are charged to the issuing provider"},
                "replay": {"jev_physical": _caps()["replay"]["physical"]["jev"], "ling_physical": 0},
            },
            "terminal_stops": [
                "request or cost cap before the next call", "model drift", "protocol-key drift",
                "request/state/option identity drift",
                "malformed, non-finite, negative or option-mismatched vector",
                "hard normalization deviation above 0.05", "argmax shift after normalization",
                "output collision (journal or report already exists)",
                "registration, source, treatment or geometry hash drift",
                "writer terminal errors (empty_output, truncated_output, unparsed_output, "
                "invalid_answer, writer_error, rate-limited)",
                "two consecutive terminal provider failures",
            ],
            "output_lifecycle": {"fresh_paths": True, "resume": False, "append": False,
                                 "overwrite": False, "path_overrides": False,
                                 "rule": ("each phase writes only its own registered paths; a "
                                          "stopped run requires a new registration and a new "
                                          "review before any fresh attempt")},
            "caps": caps,
            "authorization": {
                "separate_live_authorization_required_after_locking": True,
                "locking_is_not_authorization": True,
                "approval_must_be_a_supplied_reference": True,
                "approval_may_not_be_inferred_from_locking": True,
            },
        },
        "outputs": dict(OUTPUT_PATHS),
        "claim_scope": {
            "type": "preregistered non-planning-family replication of a matched replay",
            "conditional_on": [f"the closed prompt-form space of the {family} family",
                               "the paid Ling route that generated the messages"],
            "k_max": k_max,
            "statement": ("conditional on the selected family's frozen forms and the paid Ling "
                          "route; fresh instance IDs never increase k"),
        },
        "non_claims": [
            "no population-level claim", "no cross-family claim", "no calibration claim",
            "no instance-level claim", "no unique-information claim",
            "no generalization beyond the registered forms",
            "no use of the planning-low estimate or p-value as a prior or effect-size guarantee",
            "no post-hoc family sweep or winner selection",
        ],
        "source_files": list(SOURCE_FILES),
        "source_files_hash": _source_files_hash(root),
    }
    document["information_geometry_hash"] = information_geometry_hash(audit_document)
    document["manifest_treatment_hash"] = manifest_treatment_hash(audit_document)
    document["treatment_hash"] = replication_treatment_hash(
        manifest_treatment=document["manifest_treatment_hash"],
        geometry=document["information_geometry_hash"],
        prompt_hash=str(prompt["prompt_hash"]))
    document["preregistration_hash"] = _content_hash(document)
    return document


def write_audit(document: Mapping[str, Any], *, repo_root: Path) -> Path:
    target = Path(repo_root) / AUDIT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        handle.write(_render(document))
    return target


def write_registration(document: Mapping[str, Any], *, repo_root: Path) -> Path:
    target = Path(repo_root) / REGISTRATION_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        handle.write(_render(document))
    return target


def load_registration(*, repo_root: Path, locked: bool = False) -> dict[str, Any]:
    path = Path(repo_root) / REGISTRATION_PATH
    if not path.is_file():
        raise ReplicationError("replication registration missing")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("preregistration_version") != REPLICATION_VERSION:
        raise ReplicationError("wrong replication registration version")
    expected = LOCKED_STATUS if locked else DRAFT_STATUS
    if document.get("status") != expected:
        raise ReplicationError(f"replication registration is not {expected}")
    return document


def verify_registration(document: Mapping[str, Any], *, repo_root: Path,
                        audit_document: Mapping[str, Any] | None = None,
                        require_approval: bool = False,
                        approval: str | None = None,
                        check_credentials: bool = False,
                        journal_exists: bool | None = None,
                        report_exists: bool | None = None) -> dict[str, Any]:
    """Fail-closed verification of the draft registration. No provider call."""

    root = Path(repo_root)
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

    errors: list[str] = []
    check("registration_version",
          document.get("preregistration_version") == REPLICATION_VERSION,
          document.get("preregistration_version"))
    check("status_is_draft", document.get("status") == DRAFT_STATUS, document.get("status"))
    check("approval_not_inferred_from_locking",
          document.get("approval_required") is True
          and (document.get("approval") or {}).get("approved") is False
          and document.get("lock_does_not_imply_approval") is True
          and document.get("live_collection_authorized") is False
          and document.get("lock_is_not_live_authorization") is True
          and (document.get("operational_settings", {}).get("authorization") or {})
          .get("approval_may_not_be_inferred_from_locking") is True, None)
    if require_approval:
        check("runtime_approval_present", bool(approval),
              None if approval else "approval required for --live")
    else:
        check("runtime_approval_present", True, "offline verification; no approval demanded")

    try:
        audit = dict(audit_document) if audit_document is not None else build_form_audit(root)
        check("audit_rebuilds", True, None)
    except ReplicationError as exc:
        audit = {}
        check("audit_rebuilds", False, str(exc))
    if audit:
        binding = document.get("audit_binding") or {}
        check("audit_content_hash_matches",
              binding.get("audit_content_hash") == audit.get("audit_content_hash"),
              binding.get("audit_content_hash"))
        check("audit_form_set_hash_matches",
              binding.get("form_set_hash") == audit["form_capacity"]["form_set_hash"],
              binding.get("form_set_hash"))
        audit_path = root / AUDIT_PATH
        if audit_path.is_file():
            try:
                on_disk = json.loads(audit_path.read_text(encoding="utf-8"))
                check("audit_file_matches_rebuild", on_disk == audit, None)
                check("audit_file_is_byte_reproducible",
                      audit_path.read_text(encoding="utf-8") == _render(audit), None)
            except (OSError, json.JSONDecodeError) as exc:
                check("audit_file_matches_rebuild", False, str(exc))
        else:
            check("audit_file_present_when_declared", False, str(AUDIT_PATH))

        selection = document.get("family_selection") or {}
        check("family_matches_selection_rule",
              selection.get("selected_family") == select_family()["selected_family"]
              == document.get("family"), document.get("family"))
        check("selection_is_outcome_blind",
              selection.get("outcome_blind") is True
              and selection.get("consulted_prior_live_outcomes") == []
              and "planning" in (selection.get("excluded_families") or []), None)
        capacity = document.get("form_capacity") or {}
        check("form_capacity_matches_audit",
              capacity.get("form_ids") == audit["form_capacity"]["form_ids"]
              and capacity.get("k_max") == audit["form_capacity"]["k_max"]
              and capacity.get("space") == audit["form_capacity"]["space"],
              capacity.get("space"))
        check("form_space_closed_recorded",
              capacity.get("closed") is True and capacity.get("space") == "closed",
              capacity.get("space"))
        check("k4_sign_flip_floor_recorded",
              (document.get("inference_plan") or {}).get("attainable_two_sided_floor_by_k", {})
              .get("4") == "0.125", None)

        membership_ok = True
        branch_ok = True
        branch_detail: list[Any] = []
        for block in BLOCKS:
            manifest = (audit["blocks"].get(block) or {}).get("manifest") or []
            if len(manifest) != BLOCK_N:
                membership_ok = False
            counts = Counter(entry["prompt_form_id"] for entry in manifest)
            if counts != Counter({form: INSTANCES_PER_FORM
                                  for form in audit["form_capacity"]["form_ids"]}):
                membership_ok = False
            for entry in manifest:
                instance = instance_for(document["family"], int(entry["seed"]))
                geometry = _instance_geometry(instance)
                hashes = branch_hashes(instance, geometry["real_claim"],
                                       geometry["placebo_claim"])
                if hashes["pre_read_request_body_hash"] != entry["prompt_form_id"]:
                    branch_ok = False
                    branch_detail.append({"instance": entry["instance_id"],
                                          "reason": "form drift"})
                recorded = (document.get("manifests", {}).get(block, {})
                            .get("branch_hashes") or {}).get(entry["instance_id"])
                if recorded is not None and recorded != hashes:
                    branch_ok = False
                    branch_detail.append({"instance": entry["instance_id"],
                                          "reason": "branch hash drift"})
        check("manifest_membership_fixed_n_per_form", membership_ok, None)
        check("branch_request_and_state_hashes_recompute", branch_ok, branch_detail)

        disjoint = document.get("disjointness") or {}
        check("prior_artifact_disjointness",
              disjoint.get("selected_ids_overlapping_prior") == []
              and disjoint.get("primary_vs_confirmation_overlap") == []
              and disjoint.get("disjoint_from_all_prior_artifacts") is True, None)
        check("seed_windows_disjoint_from_prior_ranges",
              (audit.get("windows") or {}).get("disjoint_from_documented_prior_ranges") is True,
              (audit.get("windows") or {}).get("documented_prior_range_overlaps"))
        check("manifest_hashes_match_audit",
              all(document.get("manifests", {}).get(block, {}).get("manifest_hash")
                  == audit["blocks"][block]["manifest_hash"] for block in BLOCKS), None)
        check("confirmation_block_is_fresh_seed",
              set(entry["instance_id"] for entry in
                  audit["blocks"]["confirmation"]["manifest"]).isdisjoint(
                  entry["instance_id"] for entry in audit["blocks"]["primary"]["manifest"]),
              None)

    # frozen design blocks
    estimand = document.get("estimand") or {}
    check("equal_weight_form_estimand",
          estimand.get("experimental_unit") == "prompt form"
          and "equal-weight mean" in str(estimand.get("primary"))
          and estimand.get("events_are_independent_units") is False, None)
    inference = document.get("inference_plan") or {}
    check("sign_flip_and_t_interval_primary",
          "sign-flip" in str(inference.get("primary_test"))
          and "form-mean t interval" in str(inference.get("interval"))
          and inference.get("direction_requirement") == "the observed equal-form mean must be negative",
          None)
    check("no_instance_level_primary",
          "instance-level t-test" in (inference.get("prohibited_as_primary") or []),
          None)
    check("no_imputation_registered", inference.get("imputation") == "never impute missing pairs",
          None)
    check("minimum_form_rule_and_five_form_fallback",
          inference.get("minimum_forms_for_confirmatory") == 5
          and "interval-only" in str(inference.get("five_form_fallback"))
          and "replay-coverage failure" in str(
              (inference.get("missingness") or {}).get("below_five_forms", "")), None)
    guards = inference.get("guards") or {}
    check("guards_never_filter",
          guards.get("target_probability_delta") == 0.0
          and guards.get("feasible_set_mass_epsilon") == 0.01
          and "never used to filter" in str(guards.get("reporting")), None)

    multiplicity = document.get("multiplicity") or {}
    check("family_level_holm_rule",
          "Holm" in str(multiplicity.get("family_level_control"))
          and multiplicity.get("family_set_frozen_before_outcomes") is True
          and multiplicity.get("registered_family_count") == 1, None)
    check("post_hoc_family_selection_forbidden",
          "selecting a winner post hoc" in " ".join(multiplicity.get("forbidden") or []),
          multiplicity.get("forbidden"))
    confirmation = multiplicity.get("confirmation") or {}
    check("fresh_seed_confirmation_required",
          confirmation.get("required_before_any_claim") is True
          and confirmation.get("n") == BLOCK_N
          and confirmation.get("may_not_pool_with_primary_for_primary_estimate") is True, None)

    operations = document.get("operational_settings") or {}
    jev = operations.get("jev") or {}
    check("jev_pins",
          jev.get("model") == pr.JEV_REPLAY_MODEL
          and jev.get("endpoint") == pr.JEV_REPLAY_ENDPOINT
          and jev.get("codec_version") == jc2.JEV_CHOICE_V2_CODEC_VERSION
          and jev.get("protocol_key") == prv4.prv6_protocol_key(), jev.get("model"))
    normalization = operations.get("normalization") or {}
    check("normalization_policy",
          normalization.get("policy_hash") == prv2.normalization_policy_hash()
          and normalization.get("policy") == prv2.normalization_policy(), None)
    ling = operations.get("ling") or {}
    check("ling_route_and_pacing",
          ling.get("model") == prv7.PAID_LING_MODEL
          and ling.get("endpoint") == pr.LING_ENDPOINT
          and ling.get("key_loader") == "behavioral_discovery._api_key"
          and ling.get("pacing", "").startswith("ling-writer-openrouter-pacing-v3"), None)
    check("retry_policy_registered",
          jev.get("max_retries") == 2 and jev.get("retryable_statuses")
          == sorted(jc.JEV_RETRYABLE_STATUSES), jev.get("max_retries"))
    stops = operations.get("terminal_stops") or []
    check("terminal_stops_registered",
          any("output collision" in str(item) for item in stops)
          and any("hash drift" in str(item) for item in stops)
          and any("cost cap" in str(item) for item in stops), len(stops))
    lifecycle = operations.get("output_lifecycle") or {}
    check("no_resume_append_overwrite",
          lifecycle.get("fresh_paths") is True and lifecycle.get("resume") is False
          and lifecycle.get("append") is False and lifecycle.get("overwrite") is False, None)

    caps = operations.get("caps") or {}
    collection = caps.get("collection") or {}
    replay = caps.get("replay") or {}
    program = caps.get("program") or {}
    cost = caps.get("cost_model") or {}
    check("caps_arithmetic",
          collection.get("planned", {}).get("ling") == len(BLOCKS) * BLOCK_N * 4
          and collection.get("physical", {}).get("ling")
          == len(BLOCKS) * BLOCK_N * 4 * 3
          and replay.get("planned", {}).get("jev") == len(BLOCKS) * BLOCK_N * 3
          and replay.get("physical", {}).get("jev") == len(BLOCKS) * BLOCK_N * 9, None)
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

    outputs = document.get("outputs") or {}
    check("outputs_are_fresh", all(str(outputs.get(key, "")) in OWNED_PATHS
                                   for key in outputs), sorted(outputs))
    for key in ("collection_journal", "collection_report", "replay_journal", "replay_report"):
        target = root / str(outputs.get(key, ""))
        bad = (journal_exists if journal_exists is not None and key.endswith("journal")
               else report_exists if report_exists is not None and key.endswith("report")
               else target.exists())
        check(f"{key}_fresh", not bad, str(target))
    check("outputs_disjoint_from_v4_and_v5",
          not (set(str(value) for value in outputs.values())
               & {str(prv4.DEFAULT_JOURNAL_V4), str(prv4.DEFAULT_REPORT_V4),
                  str(prv4.DEFAULT_OUTPUT_V4),
                  "runs/epic-126/replay-v5/jev-choice-replay-v5.jsonl",
                  "runs/epic-126/replay-v5/jev-choice-replay-report-v5.json"}), None)

    check("source_files_bound", list(document.get("source_files") or []) == list(SOURCE_FILES),
          len(document.get("source_files") or []))
    try:
        check("source_files_hash_matches",
              document.get("source_files_hash") == _source_files_hash(root),
              document.get("source_files_hash"))
    except ReplicationError as exc:
        check("source_files_hash_matches", False, str(exc))
    try:
        expected = build_registration(root, audit=audit or None)
        check("registration_content_matches",
              {k: v for k, v in document.items() if k != "preregistration_hash"}
              == {k: v for k, v in expected.items() if k != "preregistration_hash"}, None)
        check("registration_hash_matches",
              document.get("preregistration_hash") == expected.get("preregistration_hash")
              == _content_hash(document), document.get("preregistration_hash"))
    except Exception as exc:  # noqa: BLE001 - fail closed with the reason
        check("registration_rebuilds", False, f"{type(exc).__name__}: {exc}")

    wire_keys = set()

    def _collect(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                _collect(value)
        elif isinstance(node, list):
            for value in node:
                _collect(value)
        elif isinstance(node, str) and node.startswith("jev-choice-wire") and "|" in node:
            wire_keys.add(node)

    _collect(document)
    check("no_mixed_protocol_keys", wire_keys == {prv4.prv6_protocol_key()},
          sorted(wire_keys))

    if check_credentials:
        credentials = jc.load_jev_credentials()
        check("jev_credentials_present",
              bool(credentials.present and credentials.shape_ok), credentials.redacted())
        check("ling_credentials_present", bool(bd._api_key()), {"present": bool(bd._api_key())})

    return {"mode": f"{REPLICATION_VERSION}-preflight", "ok": not errors,
            "errors": errors, "failed": [entry["check"] for entry in checks
                                         if not entry["ok"]],
            "checks": checks,
            "registration_hash": document.get("preregistration_hash"),
            "status": document.get("status"),
            "live_collection_authorized": document.get("live_collection_authorized")}


def _blocked(reason: str, approval: str | None) -> dict[str, Any]:
    return {"mode": REPLICATION_VERSION, "status": "blocked", "stop_reason": reason,
            "approval": approval, "provider_calls": 0,
            "live_collection_authorized": False,
            "raw_response_retained": False, "credentials_retained": False}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="#200 replication preregistration (offline draft; live gated)")
    parser.add_argument("--live", action="store_true",
                        help="reserved; always refused while the registration is a draft")
    parser.add_argument("--approval", help="reviewer runtime authorization reference")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--lock", action="store_true",
                        help="write the audit and the DRAFT registration (never overwrites)")
    args = parser.parse_args(argv)
    root = Path(args.repo_root) if args.repo_root is not None else _repo_root()

    if args.lock:
        audit = build_form_audit(root)
        write_audit(audit, repo_root=root)
        document = build_registration(root, audit=audit)
        write_registration(document, repo_root=root)
        print(json.dumps({"mode": REPLICATION_VERSION, "status": DRAFT_STATUS,
                          "audit": str(AUDIT_PATH), "registration": str(REGISTRATION_PATH),
                          "audit_content_hash": audit["audit_content_hash"],
                          "preregistration_hash": document["preregistration_hash"],
                          "live_collection_authorized": False}, indent=2, sort_keys=True))
        return 0

    if args.live and not args.approval:
        print(json.dumps(_blocked("missing_approval", None), indent=2, sort_keys=True))
        return 2
    try:
        document = load_registration(repo_root=root)
    except ReplicationError as exc:
        print(json.dumps(_blocked(f"registration_load_failed: {exc}", args.approval),
                         indent=2, sort_keys=True))
        return 2
    verification = verify_registration(document, repo_root=root,
                                       require_approval=bool(args.live),
                                       approval=args.approval,
                                       check_credentials=bool(args.live))
    print(json.dumps(verification, indent=2, sort_keys=True, allow_nan=False))
    if not verification["ok"]:
        return 2
    if not args.live:
        print(json.dumps({"mode": REPLICATION_VERSION, "status": "offline",
                          "note": "verification only; no provider call made",
                          "registration_status": document.get("status"),
                          "lock_does_not_imply_approval": True,
                          "live_collection_authorized": False, "provider_calls": 0},
                         indent=2, sort_keys=True))
        return 0
    print(json.dumps(_blocked("draft_registration_requires_reviewer_lock_and_a_separate_"
                              "live_authorization_reference", args.approval),
                     indent=2, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "REPLICATION_VERSION", "DRAFT_STATUS", "LOCKED_STATUS", "AUDIT_VERSION",
    "AUDIT_PATH", "REGISTRATION_PATH", "COLLECTION_JOURNAL", "COLLECTION_REPORT",
    "REPLAY_JOURNAL", "REPLAY_REPORT", "OWNED_PATHS", "OUTPUT_PATHS",
    "FAMILY_ORDER", "NON_PLANNING_FAMILIES", "EXCLUDED_FAMILIES",
    "SEED_SCAN_BASE", "SEED_SCAN_WINDOW", "SEED_SCAN_END", "CLOSURE_PROBE_BASE",
    "CLOSURE_PROBE_WINDOW", "CLOSURE_PROBE_END", "CONFIRMATION_SCAN_BASE",
    "CONFIRMATION_SCAN_WINDOW", "CONFIRMATION_SCAN_END", "INSTANCES_PER_FORM",
    "BLOCK_N", "BLOCKS", "PRIOR_SEED_RANGES", "SOURCE_FILES",
    "ILLUSTRATIVE_BETWEEN_FORM_SD_BITS", "ReplicationError", "instance_for",
    "_instance_id", "pre_read_form_id", "form_space_status", "structural_preconditions",
    "select_family", "build_form_audit", "write_audit", "build_registration",
    "write_registration", "load_registration", "verify_registration", "branch_hashes",
    "manifest_treatment_hash", "replication_treatment_hash", "prompt_binding", "main",
]
