"""P03 — versioned form-capacity census and independence audit (#204).

Offline only. No provider call is made by any code path in this module.

This module builds the versioned census for the ``hypothesis:low`` next-family
pilot (Chainlink #204 under #201 under #159), reusing the frozen #200 audit as
input evidence and rechecking current manifest coverage. It produces:

1. A versioned census over the three frozen seed windows (primary,
   closure_probe, confirmation): per-form seed capacity, growth checkpoints,
   and the distinct prompt-form set.
2. Closure evidence: observed saturation (census checkpoints plus the
   disjoint closure probe) AND a generator-level closure proof by exhaustive
   enumeration of the finite generator state space. The prompt form is a
   deterministic function of ``(bit0, bit2)`` of the target, which has exactly
   four values; all four are realized, so the form space is exactly four
   forms — closed, proven, not merely observed.
3. Pre-read hashes for each form (request body hash, pre-read state hash, and
   the real/placebo/null branch request and state hashes).
4. A shared-template/dependence assessment: the four forms share one template
   and differ only in ``state.clues``, so they are hash-distinct but not
   independent prompts; form-level sign flips are assumption-dependent.
5. A seed/ID overlap report against the current prior-instance-id set, with
   current manifest coverage rechecked against the #200 pin.

The census is deterministic: ``build_census`` reproduces the artifact
byte-for-byte from the frozen generator and the current disk state. The
artifact lives outside ``runs/epic-126/`` so the frozen #200 audit's
byte-reproducibility (which scans ``runs/epic-126/**``) is preserved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import jev_replay_preregistration_v4 as prv4
from . import jev_replication_preregistration as rep


CENSUS_VERSION = "jev-form-census-v1"
CENSUS_PATH = Path("runs/next-phase/jev-form-census-v1.json")

#: The census lives outside runs/epic-126/ so the frozen #200 audit's
#: byte-reproducibility (which scans runs/epic-126/**) is preserved.
FAMILY = "hypothesis"

WINDOWS = {
    "primary": {"base": rep.SEED_SCAN_BASE, "window": rep.SEED_SCAN_WINDOW,
                "role": "discovery-stage seed census and manifest selection (P05-P07)"},
    "closure_probe": {"base": rep.CLOSURE_PROBE_BASE, "window": rep.CLOSURE_PROBE_WINDOW,
                      "role": "offline closure test only; no seed may be selected from it"},
    "confirmation": {"base": rep.CONFIRMATION_SCAN_BASE, "window": rep.CONFIRMATION_SCAN_WINDOW,
                     "role": "fresh-seed held-out block manifest (P08-P13)"},
}

SEED_GROWTH_CHECKPOINTS = rep.SEED_GROWTH_CHECKPOINTS
INSTANCES_PER_FORM = rep.INSTANCES_PER_FORM
BLOCK_N = rep.BLOCK_N

#: Frozen input pins (recomputed from disk at build time; fail closed on drift).
AUDIT_PATH = rep.AUDIT_PATH
REGISTRATION_PATH = rep.REGISTRATION_PATH
SCOPE_PATH = Path("runs/next-phase/jev-p02-scope-freeze.json")

AUDIT_CONTENT_HASH = "5242e9cfa35e3a77c54045475428dd617cf93cb16d464b55ad679adc35f80a83"
PREREGISTRATION_HASH = "ff186a066e6af093ecc383e668d948bdca7c1ef8f84b5752b88db47960a6ec6d"
SCOPE_CONTENT_HASH = "4cf5556c8e9c0811653e4b4d726a7b437d43bd63134cad0f80b84eb9148ec59b"
PRIOR_INSTANCE_ID_COUNT = 8945
PRIOR_INSTANCE_IDS_SHA256 = "429e8c54720d1a472d9e191fedc0510ade291680514f2dae4dff8c2a747607f9"

#: The finite target space of the hypothesis generator at LOW complexity:
#: the target is one of eight candidates, and the prompt form is a function
#: of (bit0, bit2) of the target number.
TARGET_SPACE = tuple(range(8))


class CensusError(ValueError):
    """Fail-closed census build or verification violation."""


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(document: Mapping[str, Any]) -> str:
    payload = json.dumps({key: value for key, value in document.items()
                          if key != "content_hash"}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _render(document: Mapping[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n"


# --------------------------------------------------------------------------
# census windows
# --------------------------------------------------------------------------

def _scan_window(family: str, base: int, window: int) -> dict[str, Any]:
    """Deterministic per-window census: forms, seeds, growth checkpoints."""
    scan = rep._scan_forms(family, base, window)
    return {
        "distinct_forms": scan["distinct_forms"],
        "growth_checkpoints": scan["growth_checkpoints"],
        "per_form_seed_counts": {form: len(seeds)
                                 for form, seeds in sorted(scan["forms"].items())},
        "forms": scan["forms"],
    }


# --------------------------------------------------------------------------
# closure evidence
# --------------------------------------------------------------------------

def _first_seed_per_target(family: str, base: int, window: int) -> dict[int, int]:
    """First seed in the window realizing each target number 0..7."""
    first: dict[int, int] = {}
    for seed in range(base, base + window):
        instance = rep.instance_for(family, seed)
        number = int(instance.target.rsplit("-", 1)[-1])
        if number not in first:
            first[number] = seed
    return first


def _closure_enumeration(family: str, base: int, window: int) -> list[dict[str, Any]]:
    """Exhaustive enumeration of the finite generator form space.

    The prompt form is the sha256 of the model-visible ISO pre-read request
    body. For the hypothesis family at LOW complexity and regime N the body
    is a deterministic function of ``(bit0, bit2)`` of the target (the state
    carries only A's private clues ``bit0``/``bit2``; model, question,
    instructions and the eight options are fixed). ``(bit0, bit2)`` has exactly
    four values, so at most four distinct forms can ever be produced. This
    enumeration computes the form for every target number 0..7 (which covers
    all four ``(bit0, bit2)`` pairs) through the real generator code path.
    """
    first = _first_seed_per_target(family, base, window)
    rows = []
    for number in TARGET_SPACE:
        if number not in first:
            raise CensusError(f"target number {number} is not realized in the window")
        seed = first[number]
        instance = rep.instance_for(family, seed)
        rows.append({
            "target": instance.target,
            "target_number": number,
            "bit0": number & 1,
            "bit1": (number >> 1) & 1,
            "bit2": (number >> 2) & 1,
            "bit0_bit2": [number & 1, (number >> 2) & 1],
            "form_id": rep.pre_read_form_id(instance),
            "first_seed_in_primary_window": seed,
        })
    return rows


def _closure_argument(family: str, base: int, window: int,
                      form_ids: Sequence[str]) -> dict[str, Any]:
    rows = _closure_enumeration(family, base, window)
    distinct_forms = sorted({row["form_id"] for row in rows})
    form_to_targets: dict[str, list[str]] = {}
    for row in rows:
        form_to_targets.setdefault(row["form_id"], []).append(row["target"])
    # Computational check: the form is a function of (bit0, bit2) only.
    by_pair: dict[tuple[int, int], set[str]] = {}
    for row in rows:
        by_pair.setdefault(tuple(row["bit0_bit2"]), set()).add(row["form_id"])
    pair_is_function = all(len(forms) == 1 for forms in by_pair.values())
    if not pair_is_function:
        raise CensusError("the prompt form is not a function of (bit0, bit2)")
    if sorted(distinct_forms) != sorted(form_ids):
        raise CensusError("enumerated form set disagrees with the #200 audit form set")
    return {
        "form_derivation": ("sha256 of the model-visible ISO pre-read request body "
                            "(model + state + question/instructions/criteria) produced only "
                            "from generator/task structure; no outcome enters the hash"),
        "fixed_components": ["model", "question_id", "instructions",
                             "criteria/options (candidate-0..candidate-7)",
                             "state.family", "state.complexity", "state.agent_id"],
        "varying_component": ("state.clues = A's private clues = (bit0, bit2) of the "
                              "target; B's clue (bit1) is not in the pre-read body"),
        "finite_state_space": "(bit0, bit2) in {0,1} x {0,1}",
        "upper_bound_distinct_forms": 4,
        "exhaustive_enumeration": rows,
        "distinct_forms_enumerated": len(distinct_forms),
        "realized_forms": len(distinct_forms),
        "form_is_function_of_bit0_bit2": pair_is_function,
        "form_to_targets": {form: sorted(targets)
                            for form, targets in sorted(form_to_targets.items())},
        "conclusion": ("the prompt form is a deterministic function of (bit0, bit2) of the "
                       "target, which has exactly four values; exhaustive enumeration of all "
                       "eight target numbers realizes exactly four distinct forms, matching "
                       "the #200 audit form set. The form space is therefore closed at k = 4, "
                       "proven by exhaustive enumeration of the finite generator state space, "
                       "not merely observed saturation."),
    }


# --------------------------------------------------------------------------
# pre-read hashes
# --------------------------------------------------------------------------

def _pre_read_hashes_per_form(family: str, base: int, window: int,
                              form_ids: Sequence[str]) -> dict[str, Any]:
    """Full pre-read hash record for one representative instance per form."""
    first_seed: dict[str, int] = {}
    for seed in range(base, base + window):
        instance = rep.instance_for(family, seed)
        form = rep.pre_read_form_id(instance)
        if form in set(form_ids) and form not in first_seed:
            first_seed[form] = seed
    missing = [form for form in form_ids if form not in first_seed]
    if missing:
        raise CensusError(f"forms not realized in the window: {missing}")
    out = {}
    for form in form_ids:
        seed = first_seed[form]
        instance = rep.instance_for(family, seed)
        geometry = rep._instance_geometry(instance)
        hashes = rep.branch_hashes(instance, geometry["real_claim"],
                                   geometry["placebo_claim"])
        out[form] = {
            "representative_instance": instance.instance_id,
            "seed": seed,
            "target": instance.target,
            "pre_read_request_body_hash": hashes["pre_read_request_body_hash"],
            "pre_read_state_hash": hashes["pre_read_state_hash"],
            "real_claim": geometry["real_claim"],
            "placebo_claim": geometry["placebo_claim"],
            "branch_request_hashes": hashes["branch_request_hashes"],
            "branch_state_hashes": hashes["branch_state_hashes"],
        }
    return out


# --------------------------------------------------------------------------
# shared-template / dependence assessment
# --------------------------------------------------------------------------

def _dependence_assessment(family: str, base: int, window: int,
                           form_ids: Sequence[str]) -> dict[str, Any]:
    """Show the forms share one template and differ only in state.clues."""
    bodies: dict[str, dict[str, Any]] = {}
    for seed in range(base, base + window):
        instance = rep.instance_for(family, seed)
        form = rep.pre_read_form_id(instance)
        if form in set(form_ids) and form not in bodies:
            body, _ = prv4.pre_read_body(instance, rep.pr.JEV_REPLAY_MODEL)
            bodies[form] = body
        if len(bodies) == len(form_ids):
            break
    missing = [form for form in form_ids if form not in bodies]
    if missing:
        raise CensusError(f"forms not realized in the window: {missing}")

    def _template(body: Mapping[str, Any]) -> dict[str, Any]:
        template = json.loads(json.dumps(body))
        template["state"] = {key: value for key, value in template["state"].items()
                             if key != "clues"}
        return template

    templates = {form: _template(body) for form, body in bodies.items()}
    template_values = list(templates.values())
    shared = all(template == template_values[0] for template in template_values)
    if not shared:
        raise CensusError("the forms do not share a common template")
    template_rep = template_values[0]
    question = next(iter(template_rep["questions"].values()))
    form_cells = {}
    for form in form_ids:
        clues = bodies[form]["state"]["clues"]
        bit0 = int(clues[0].rsplit("=", 1)[1])
        bit2 = int(clues[1].rsplit("=", 1)[1])
        form_cells[form] = {"bit0": bit0, "bit2": bit2, "clues": list(clues)}
    return {
        "shared_template": shared,
        "template_hash": rep._digest(template_rep),
        "template": {
            "model": template_rep["model"],
            "state_keys_except_clues": sorted(key for key in template_rep["state"]
                                              if key != "clues"),
            "question_id": next(iter(template_rep["questions"].keys())),
            "instructions": question["instructions"],
            "option_count": len(question["criteria"]),
            "option_ids": sorted(question["criteria"]),
        },
        "identical_except": ["state.clues"],
        "form_cells": form_cells,
        "structure": ("complete 2x2 factorial over (bit0, bit2); the four forms are the "
                      "entire finite form space, not a sample from a larger prompt "
                      "population"),
        "hash_distinct_not_independent": True,
        "consequence": ("the four forms are hash-distinct but template-identical: they share "
                        "model, question, instructions, options and state structure, and "
                        "differ only in the state clue values (bit0, bit2). They are "
                        "therefore not independent prompts; a template-level effect would "
                        "shift all four forms together. Form-level sign flips are "
                        "assumption-dependent: the exact two-sided sign-flip p is reported "
                        "as a descriptive statistic with the exchangeability assumption "
                        "labeled, never as assumption-free inference. With k = 4 the "
                        "attainable exact two-sided sign-flip floor is 2/2^4 = 0.125 > "
                        "0.05, so no dichotomous rejection at alpha = 0.05 is attainable at "
                        "any effect size on this family regardless; the pilot and its "
                        "fresh-seed replication remain descriptive/estimation only."),
    }


# --------------------------------------------------------------------------
# seed/ID overlap report and current manifest coverage
# --------------------------------------------------------------------------

def _seed_id_overlap(repo_root: Path, audit: Mapping[str, Any],
                     prior: Mapping[str, Any]) -> dict[str, Any]:
    primary_ids = [entry["instance_id"] for entry in audit["blocks"]["primary"]["manifest"]]
    confirmation_ids = [entry["instance_id"]
                        for entry in audit["blocks"]["confirmation"]["manifest"]]
    selected = set(primary_ids) | set(confirmation_ids)
    prior_ids = set(prior["_ids"])
    overlap_prior = sorted(selected & prior_ids)
    cross = sorted(set(primary_ids) & set(confirmation_ids))
    selected_seeds = sorted({entry["seed"] for entry in
                             audit["blocks"]["primary"]["manifest"]
                             + audit["blocks"]["confirmation"]["manifest"]})
    seed_range_overlaps = []
    for low, high in rep.PRIOR_SEED_RANGES:
        for seed in selected_seeds:
            if low <= seed <= high:
                seed_range_overlaps.append({"seed": seed, "range": [low, high]})
    return {
        "prior_instance_id_count": prior["instance_id_count"],
        "prior_instance_ids_sha256": prior["instance_ids_sha256"],
        "prior_sources_count": len(prior["sources"]),
        "documented_seed_ranges": [{"low": low, "high": high}
                                   for low, high in rep.PRIOR_SEED_RANGES],
        "selected_ids": {"primary": primary_ids, "confirmation": confirmation_ids},
        "selected_seeds": selected_seeds,
        "selected_ids_overlapping_prior": overlap_prior,
        "primary_vs_confirmation_overlap": cross,
        "documented_seed_range_overlaps": seed_range_overlaps,
        "disjoint_from_all_prior_artifacts": not overlap_prior and not cross
        and not seed_range_overlaps,
    }


def _current_manifest_coverage(repo_root: Path, audit: Mapping[str, Any],
                               prior: Mapping[str, Any]) -> dict[str, Any]:
    """Recheck current manifest coverage against the #200 pin."""
    current_sources = set(prior["sources"])
    audit_sources = set(audit["disjointness"]["prior_sources"])
    new_manifests = sorted(current_sources - audit_sources)
    missing_manifests = sorted(audit_sources - current_sources)
    matches_pin = (prior["instance_id_count"] == PRIOR_INSTANCE_ID_COUNT
                   and prior["instance_ids_sha256"] == PRIOR_INSTANCE_IDS_SHA256
                   and prior["instance_ids_sha256"]
                   == audit["disjointness"]["prior_instance_ids_sha256"])
    return {
        "rechecked_against_current_disk": True,
        "prior_id_set_matches_200_pin": matches_pin,
        "current_scan_source_count": len(current_sources),
        "audit_200_scan_source_count": len(audit_sources),
        "new_manifests_since_200_audit": new_manifests,
        "missing_manifests_since_200_audit": missing_manifests,
        "artifacts_outside_200_scan_scope": [
            "runs/next-phase/jev-p02-scope-freeze.json",
            "docs/jev-p01-evidence-index.md",
            "docs/jev-p02-scope-freeze.md",
        ],
        "inaccessible_manifests": ["runs/container-isolation.json"],
        "statement": ("current manifest coverage is unchanged since the #200 audit: the "
                      "prior-instance-id set reproduces the #200 pin exactly "
                      f"({PRIOR_INSTANCE_ID_COUNT} ids, sha256 "
                      f"{PRIOR_INSTANCE_IDS_SHA256[:16]}...), the scan finds the same "
                      f"{len(audit_sources)} sources, and no new manifest with instance "
                      "ids appears under the #200 scan patterns. The P01/P02 artifacts "
                      "live outside the #200 scan scope and are recorded here, never "
                      "treated as empty sets."),
    }


# --------------------------------------------------------------------------
# census build
# --------------------------------------------------------------------------

def build_census(repo_root: Path) -> dict[str, Any]:
    """Deterministic, offline form-capacity census. No provider call."""
    root = Path(repo_root)

    audit = _load_json(root / AUDIT_PATH)
    if audit.get("audit_content_hash") != AUDIT_CONTENT_HASH:
        raise CensusError("#200 audit content hash drift")
    registration = _load_json(root / REGISTRATION_PATH)
    if registration.get("preregistration_hash") != PREREGISTRATION_HASH:
        raise CensusError("#200 registration hash drift")
    scope = _load_json(root / SCOPE_PATH)
    if scope.get("content_hash") != SCOPE_CONTENT_HASH:
        raise CensusError("P02 scope freeze content hash drift")

    family = audit["family_selection"]["selected_family"]
    if family != FAMILY:
        raise CensusError(f"family drift: {family}")
    form_ids = sorted(audit["form_capacity"]["form_ids"])
    if len(form_ids) != 4:
        raise CensusError(f"expected 4 forms, found {len(form_ids)}")

    census = {name: _scan_window(family, spec["base"], spec["window"])
              for name, spec in WINDOWS.items()}
    for name, window_census in census.items():
        if window_census["distinct_forms"] != 4:
            raise CensusError(f"window {name} has {window_census['distinct_forms']} forms")
        if sorted(window_census["forms"]) != form_ids:
            raise CensusError(f"window {name} form set disagrees with the #200 audit")

    per_form_capacity = {}
    for form in form_ids:
        per_form_capacity[form] = {
            name: census[name]["per_form_seed_counts"][form] for name in WINDOWS
        }
        per_form_capacity[form]["total_seeds"] = sum(
            census[name]["per_form_seed_counts"][form] for name in WINDOWS)

    prior = rep._prior_instance_ids(root)
    overlap = _seed_id_overlap(root, audit, prior)
    coverage = _current_manifest_coverage(root, audit, prior)
    closure_arg = _closure_argument(family, WINDOWS["primary"]["base"],
                                    WINDOWS["primary"]["window"], form_ids)
    pre_read = _pre_read_hashes_per_form(family, WINDOWS["primary"]["base"],
                                         WINDOWS["primary"]["window"], form_ids)
    dependence = _dependence_assessment(family, WINDOWS["primary"]["base"],
                                        WINDOWS["primary"]["window"], form_ids)

    document: dict[str, Any] = {
        "census_version": CENSUS_VERSION,
        "issue": "#204",
        "parent_issue": "#201",
        "root_issue": "#159",
        "family": family,
        "complexity": "low",
        "regime": "N",
        "stage": "offline form-capacity and independence audit",
        "protocol": "docs/jev-discovery-confirmation-plan.md",
        "offline_only": True,
        "authorizes": ("nothing beyond P04 planning; no provider call, no collection, "
                       "no registration lock, no live run"),
        "reuse": ("#200 audit reused as input evidence (hash-pinned); current manifest "
                  "coverage rechecked against the #200 pin"),
        "input_evidence": {
            "audit_200": {"path": str(AUDIT_PATH),
                          "audit_content_hash": audit["audit_content_hash"],
                          "file_sha256": _sha256_file(root / AUDIT_PATH)},
            "registration_200": {"path": str(REGISTRATION_PATH),
                                 "preregistration_hash": registration["preregistration_hash"],
                                 "file_sha256": _sha256_file(root / REGISTRATION_PATH)},
            "scope_freeze_p02": {"path": str(SCOPE_PATH),
                                 "content_hash": scope["content_hash"],
                                 "file_sha256": _sha256_file(root / SCOPE_PATH)},
        },
        "windows": {name: {"base": spec["base"], "end": spec["base"] + spec["window"] - 1,
                           "window": spec["window"], "role": spec["role"]}
                    for name, spec in WINDOWS.items()},
        "census": census,
        "form_capacity": {
            "family": family,
            "k": len(form_ids),
            "form_ids": form_ids,
            "form_set_hash": audit["form_capacity"]["form_set_hash"],
            "per_form_capacity": per_form_capacity,
            "instances_per_form": INSTANCES_PER_FORM,
            "block_n": BLOCK_N,
            "selection_rule": ("first INSTANCES_PER_FORM seeds per form in ascending seed "
                               "order within the window; fixed N; no outcome-based stopping"),
        },
        "closure": {
            "status": "closed",
            "basis": "generator-level exhaustive enumeration of the finite form space",
            "observed_saturation": {
                "primary_growth_checkpoints": census["primary"]["growth_checkpoints"],
                "closure_probe_distinct_forms": census["closure_probe"]["distinct_forms"],
                "closure_probe_new_forms": 0,
                "all_windows_distinct_forms": sorted(
                    census[name]["distinct_forms"] for name in WINDOWS),
            },
            "generator_argument": closure_arg,
            "residual_unknowns": [
                ("the closure proof covers only this generator configuration (hypothesis "
                 "family, LOW complexity, regime N, Jev ISO pre-read); it does not extend "
                 "to other families, complexities, regimes or receiver conditions"),
                ("closure of the form space does not establish statistical independence of "
                 "the four forms; they share one template and differ only in state.clues"),
                ("the census is a deterministic offline artifact; it contains no live "
                 "outcome and authorizes no collection"),
            ],
            "statement": ("the prompt-form space of the hypothesis family at LOW complexity "
                          "and regime N is closed at k = 4, proven by exhaustive enumeration "
                          "of the finite generator state space (the form is a function of "
                          "(bit0, bit2) of the target, which has four values, all realized). "
                          "This upgrades the #200 audit's observed-saturation closure to a "
                          "proven closure for this configuration; the residual unknowns above "
                          "are stated, not hidden."),
        },
        "pre_read_hashes": {
            "derivation": ("jev_replay.prompt_form_id(jev_replay_preregistration_v4."
                           "pre_read_body(...)) for the request body; "
                           "jev_replay.canonical_hash for the state; branch hashes via "
                           "jev_replication_preregistration.branch_hashes"),
            "per_form": pre_read,
        },
        "dependence_assessment": dependence,
        "seed_id_overlap": overlap,
        "current_manifest_coverage": coverage,
        "design_consequence": {
            "k": len(form_ids),
            "attainable_two_sided_sign_flip_floor": "0.125",
            "floor_above_0_05": True,
            "classification": "descriptive/estimation only",
            "fresh_seed_replication": ("descriptive only; a fresh-seed replication block "
                                       "cannot become confirmatory on this family"),
            "h0": "Delta = 0",
            "h1": "Delta < 0",
            "estimand": "equal-weight form mean of real-minus-placebo entropy",
        },
        "deterministic_rebuild": {
            "builder": "src/apart_incident_response/jev_form_census.py",
            "rebuild_command": "python -m apart_incident_response.jev_form_census --repo-root .",
            "byte_reproducible": True,
        },
    }
    document["content_hash"] = _content_hash(document)
    return document


def write_census(document: Mapping[str, Any], *, repo_root: Path) -> Path:
    target = Path(repo_root) / CENSUS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        handle.write(_render(document))
    return target


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

def verify_census(document: Mapping[str, Any], *, repo_root: Path) -> dict[str, Any]:
    """Fail-closed verification: rebuild, compare byte-for-byte, run checks."""
    root = Path(repo_root)
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

    errors: list[str] = []

    check("census_version", document.get("census_version") == CENSUS_VERSION,
          document.get("census_version"))
    check("content_hash_matches",
          document.get("content_hash") == _content_hash(document),
          document.get("content_hash"))

    try:
        rebuilt = build_census(root)
        check("census_rebuilds_byte_for_byte", rebuilt == document, None)
        check("census_file_is_byte_reproducible",
              (root / CENSUS_PATH).read_text(encoding="utf-8") == _render(rebuilt), None)
    except (CensusError, OSError, json.JSONDecodeError) as exc:
        check("census_rebuilds_byte_for_byte", False, f"{type(exc).__name__}: {exc}")

    capacity = document.get("form_capacity") or {}
    check("k_is_4", capacity.get("k") == 4, capacity.get("k"))
    check("form_ids_match_200_audit",
          sorted(capacity.get("form_ids") or [])
          == sorted((_load_json(root / AUDIT_PATH)["form_capacity"]["form_ids"])),
          capacity.get("form_ids"))
    check("form_set_hash_matches_200_audit",
          capacity.get("form_set_hash")
          == _load_json(root / AUDIT_PATH)["form_capacity"]["form_set_hash"],
          capacity.get("form_set_hash"))
    per_form = capacity.get("per_form_capacity") or {}
    check("per_form_capacity_covers_all_windows",
          all(set(entry) == {"primary", "closure_probe", "confirmation", "total_seeds"}
              for entry in per_form.values()), None)
    check("per_form_capacity_sums_to_window_sizes",
          all(sum(entry[name] for entry in per_form.values()) == 512
              for name in ("primary", "closure_probe", "confirmation")), None)

    closure = document.get("closure") or {}
    check("closure_status_closed", closure.get("status") == "closed",
          closure.get("status"))
    argument = closure.get("generator_argument") or {}
    enumeration = argument.get("exhaustive_enumeration") or []
    check("closure_enumeration_covers_all_eight_targets",
          sorted(row.get("target_number") for row in enumeration) == list(TARGET_SPACE),
          len(enumeration))
    check("closure_enumeration_realizes_exactly_four_forms",
          argument.get("distinct_forms_enumerated") == 4
          and argument.get("realized_forms") == 4, argument.get("distinct_forms_enumerated"))
    check("closure_form_is_function_of_bit0_bit2",
          argument.get("form_is_function_of_bit0_bit2") is True, None)
    check("closure_upper_bound_is_four",
          argument.get("upper_bound_distinct_forms") == 4, None)
    check("closure_residual_unknowns_stated",
          isinstance(closure.get("residual_unknowns"), list)
          and len(closure.get("residual_unknowns") or []) >= 3, None)

    pre_read = document.get("pre_read_hashes", {}).get("per_form") or {}
    check("pre_read_hashes_cover_all_forms",
          sorted(pre_read) == sorted(capacity.get("form_ids") or []), None)
    hashes_ok = True
    for form, record in pre_read.items():
        if record.get("pre_read_request_body_hash") != form:
            hashes_ok = False
        if not record.get("pre_read_state_hash") or not record.get("branch_request_hashes"):
            hashes_ok = False
    check("pre_read_body_hash_equals_form_id", hashes_ok, None)

    dependence = document.get("dependence_assessment") or {}
    check("shared_template", dependence.get("shared_template") is True, None)
    check("template_identical_except_state_clues",
          dependence.get("identical_except") == ["state.clues"], None)
    check("hash_distinct_not_independent",
          dependence.get("hash_distinct_not_independent") is True, None)
    check("dependence_consequence_labels_sign_flips_assumption_dependent",
          "assumption-dependent" in str(dependence.get("consequence")), None)

    overlap = document.get("seed_id_overlap") or {}
    check("no_selected_id_overlaps_prior",
          overlap.get("selected_ids_overlapping_prior") == [], None)
    check("no_primary_confirmation_overlap",
          overlap.get("primary_vs_confirmation_overlap") == [], None)
    check("no_seed_range_overlap",
          overlap.get("documented_seed_range_overlaps") == [], None)
    check("disjoint_from_all_prior_artifacts",
          overlap.get("disjoint_from_all_prior_artifacts") is True, None)
    check("prior_id_set_matches_200_pin",
          overlap.get("prior_instance_id_count") == PRIOR_INSTANCE_ID_COUNT
          and overlap.get("prior_instance_ids_sha256") == PRIOR_INSTANCE_IDS_SHA256, None)

    coverage = document.get("current_manifest_coverage") or {}
    check("manifest_coverage_rechecked",
          coverage.get("rechecked_against_current_disk") is True
          and coverage.get("prior_id_set_matches_200_pin") is True, None)
    check("no_new_manifests_since_200_audit",
          coverage.get("new_manifests_since_200_audit") == [], None)
    check("inaccessible_manifests_recorded_not_empty",
          isinstance(coverage.get("inaccessible_manifests"), list)
          and len(coverage.get("inaccessible_manifests") or []) >= 1, None)

    consequence = document.get("design_consequence") or {}
    check("k4_descriptive_only_recorded",
          consequence.get("k") == 4
          and consequence.get("attainable_two_sided_sign_flip_floor") == "0.125"
          and consequence.get("classification") == "descriptive/estimation only",
          consequence.get("classification"))

    return {"mode": f"{CENSUS_VERSION}-verification", "ok": not errors,
            "errors": errors, "failed": [entry["check"] for entry in checks
                                         if not entry["ok"]],
            "checks": checks,
            "content_hash": document.get("content_hash"),
            "provider_calls": 0}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="P03 form-census (offline; deterministic rebuild; zero provider calls)")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--build", action="store_true",
                        help="write the census artifact to its fresh path (never overwrites)")
    args = parser.parse_args(argv)
    root = Path(args.repo_root) if args.repo_root is not None else Path(__file__).resolve().parents[2]

    if args.build:
        document = build_census(root)
        write_census(document, repo_root=root)
        print(json.dumps({"mode": CENSUS_VERSION, "status": "built", "path": str(CENSUS_PATH),
                          "content_hash": document["content_hash"],
                          "provider_calls": 0}, indent=2, sort_keys=True))
        return 0

    path = root / CENSUS_PATH
    if not path.is_file():
        print(json.dumps({"mode": CENSUS_VERSION, "status": "missing", "path": str(CENSUS_PATH),
                          "provider_calls": 0}, indent=2, sort_keys=True))
        return 2
    document = _load_json(path)
    verification = verify_census(document, repo_root=root)
    print(json.dumps(verification, indent=2, sort_keys=True, allow_nan=False))
    return 0 if verification["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CENSUS_VERSION", "CENSUS_PATH", "FAMILY", "WINDOWS", "SEED_GROWTH_CHECKPOINTS",
    "INSTANCES_PER_FORM", "BLOCK_N", "AUDIT_PATH", "REGISTRATION_PATH", "SCOPE_PATH",
    "AUDIT_CONTENT_HASH", "PREREGISTRATION_HASH", "SCOPE_CONTENT_HASH",
    "PRIOR_INSTANCE_ID_COUNT", "PRIOR_INSTANCE_IDS_SHA256", "TARGET_SPACE",
    "CensusError", "build_census", "write_census", "verify_census", "main",
]
