"""Offline, outcome-blind capacity audit for Chainlink #227.

The two new task families in this report are proposals, not generator entries,
registered experiments, or evidence of communication or entropy reduction.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from . import communication_protocol as cp
from . import jev_legal_form_census as legal_census
from . import jev_replay_preregistration as replay_registration
from . import jev_replay_preregistration_v4 as replay_v4
from . import task_families as tasks


VERSION = "jev-cross-family-capacity-v1"
ISSUE = 227
ARTIFACT_PATH = Path("research/jev/cross-family/jev-cross-family-capacity-v1.json")
FAMILIES = ("lexicon", "poetry", "reference")
COMPLEXITIES = tuple(cp.ReasoningComplexity)
REGIME = cp.DependenceRegime.N
HISTORICAL_QUEUE = ("hypothesis", "legal", "lexicon", "poetry", "reference")
LEGAL_RESERVED = ((88000, 88511), (89000, 89511))

# Closed predecessors and source contracts. Changing any of these needs a new
# audit version; dynamic input hashes alone would conceal a changed protocol.
INPUT_PINS = {
    "docs/jev-cross-family-entropy-program-v1.md": "d9acace24a0cdbfc9a41e331b1fd422f07f22e3fc01480e6408af78d9de4be05",
    "docs/jev-legal-p03-design.md": "24bd6d7e8cec205bf5b5cee96f98f09afad17c85a1e825c012b536e3a2716f79",
    "runs/next-phase/legal/jev-legal-p03-design-v1.json": "688bc7875ff7b81bb70d60076e137b0274559b484d597f6f643ae2fb48c827ab",
    "docs/jev-discovery-confirmation-plan.md": "501e21b6dea760371b0bf368046d8bacd203f6b92f0af754a7955d1f738677f7",
    "src/apart_incident_response/task_families.py": "b399bb15c96be98d2c4c7e00012448d9a3df9f1cd7deac0ff1375ecb3e1ea6c4",
    "src/apart_incident_response/jev_replay_preregistration_v4.py": "18213126c17746de44158c96fb2cb0c40812985c51b1c35233b57a09418302d3",
    "src/apart_incident_response/jev_choice.py": "9ce9920e5b902e4f68b5723a70f61f4cc8765c4d4fdae557ed93fbf7d3fb3695",
    "src/apart_incident_response/jev_replay.py": "5c1c2dfd68beb75e1ccdbbe281c88f879b4b34c98109d003ac3547c6c9d8a862",
    "src/apart_incident_response/jev_replay_preregistration.py": "c4a6978d0efd63e18cc53a10f806de030f7e4f3d2da13a37672999749fb405c0",
    "src/apart_incident_response/jev_legal_form_census.py": "216eecde0dd0640451b4f32d2ae866be6db165d2ac8911405d496766ff5256e5",
    "src/apart_incident_response/communication_protocol.py": "4efd8249491abcbdac4a48b6212b9e1eaf9dda98fe5fac7762a8669c531456c9",
}

PROPOSALS = (
    {
        "name": "repository_repair",
        "status": "proposal_only_not_audited_or_runnable",
        "task": "Repair a multi-file software repository through repeated diagnosis, edits and test runs.",
        "end_task_objective": "A patch passes a sealed regression suite without breaking existing tests.",
        "intermediate_artifacts": ["reproduction script", "patch", "test output", "counterexample log"],
        "objective_progress_checker": "isolated test runner reports reproducible passing and failing cases",
        "peer_owned_information": "B alone receives a reproducible failing trace from an independent test run; A owns the candidate patch and cannot inspect that trace before the message",
        "matched_placebo": "same envelope carrying an A-owned trace already visible in the frozen pre-read state, with zero new information",
        "fixed_choice_checkpoint": "after a frozen test batch, A chooses among a preregistered set of candidate next repairs; Choice entropy is measured on that exact option set",
        "fixed_choice_options": ["add_targeted_regression_test", "change_validation_logic", "change_state_transition", "collect_diagnostic_trace"],
        "link_to_success": "check whether the selected repair improves held-out test pass rate; entropy reduction alone does not count as success",
        "required_new_boundary": "new generator, oracle, treatment, replay, form-capacity audit and held-out task split",
        "offline_validation_needs": "prove every generated repository admits each option as a meaningful next action, that sealed tests objectively score the resulting multi-step patch, and that B-only traces do not leak into A's pre-read state or placebo",
    },
    {
        "name": "iterative_packing_research",
        "status": "proposal_only_not_audited_or_runnable",
        "task": "Develop and iteratively improve a packing solver across a multi-case benchmark.",
        "end_task_objective": "A validated solver improves score on sealed cases at a fixed compute budget.",
        "intermediate_artifacts": ["solver source", "reproducible benchmark result", "failed approach", "score history"],
        "objective_progress_checker": "independent scorer checks validity and score on a frozen case set",
        "peer_owned_information": "B alone sees a verifier-backed improvement or counterexample from its own solver branch; A has not observed it before the message",
        "matched_placebo": "same envelope carrying an A-known score or counterexample that cannot narrow A's frozen options",
        "fixed_choice_checkpoint": "A chooses the next solver approach from a preregistered finite set after receiving the peer message",
        "fixed_choice_options": ["revise_item_ordering", "revise_placement_heuristic", "add_local_search", "inspect_invalid_cases"],
        "link_to_success": "measure whether the choice leads to a valid higher-scoring solver on sealed cases",
        "required_new_boundary": "new multi-step environment, scorer, message oracle, fixed Choice checkpoint, source and treatment hashes, and fresh registration",
        "offline_validation_needs": "prove all four options remain meaningful across case variants, scorer determinism, B-only counterexample provenance, inert placebo information, and choice-to-sealed-score linkage",
    },
)

_audit_active = False
_network_events: list[str] = []
_hook_installed = False


def _network_hook(event: str, _args: tuple[Any, ...]) -> None:
    if _audit_active and (event.startswith("socket.") or event.startswith("urllib.")
                          or event.startswith("http.client.")):
        _network_events.append(event)
        raise RuntimeError(f"network event forbidden during offline audit: {event}")


def _enable_network_guard() -> None:
    global _audit_active, _hook_installed
    if not _hook_installed:
        sys.addaudithook(_network_hook)
        _hook_installed = True
    _network_events.clear()
    _audit_active = True


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _content_hash(value: dict[str, Any]) -> str:
    return _sha(_json_bytes({key: item for key, item in value.items()
                             if key != "content_hash"}))


def _render(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                       allow_nan=False) + "\n").encode("utf-8")


def _verify_inputs(root: Path) -> dict[str, str]:
    actual = {name: _sha((root / name).read_bytes()) for name in INPUT_PINS}
    drift = {name: {"expected": INPUT_PINS[name], "actual": digest}
             for name, digest in actual.items() if digest != INPUT_PINS[name]}
    if drift:
        raise ValueError(f"pinned predecessor or generator drift: {drift}")
    return actual


def _scan_cell(family: str, complexity: cp.ReasoningComplexity,
               windows: list[dict[str, Any]]) -> dict[str, Any]:
    by_window: dict[str, dict[str, int]] = {}
    target_forms: dict[str, set[str]] = defaultdict(set)
    form_semantics: dict[str, set[str]] = defaultdict(set)
    template_hashes: set[str] = set()
    option_hashes: set[str] = set()
    unique_ids: set[str] = set()
    structural_need = 0
    informative_b = 0
    channel_complete = 0
    all_targets: set[str] = set()
    expected_targets: set[str] | None = None
    for window in windows:
        counts: dict[str, int] = defaultdict(int)
        for seed in range(window["base"], window["end"] + 1):
            instance = tasks.generate_instance(family, seed, REGIME, complexity)
            body, state = replay_v4.pre_read_body(instance, replay_registration.JEV_REPLAY_MODEL)
            form = state.request_hash
            counts[form] += 1
            target_forms[instance.target].add(form)
            all_targets.add(instance.target)
            expected_targets = set(instance.solutions) if expected_targets is None else expected_targets
            unique_ids.add(instance.instance_id)
            form_semantics[form].add(_sha(_json_bytes(sorted(instance.private_solutions["A"]))))
            template = json.loads(json.dumps(body))
            template["state"]["clues"] = "<A private clues>"
            template_hashes.add(_sha(_json_bytes(template)))
            option_hashes.add(_sha(_json_bytes(body["questions"]["candidate"]["criteria"])))
            analysis = instance.channel_analysis()
            structural_need += bool(analysis["finalizer_needs_peer"])
            channel_complete += bool(analysis["channel_complete"])
            positive = False
            for claim in instance.private_clues["B"]:
                info = instance.information("A", claim, "audit")
                if (instance.claim_owner(claim) == "B" and info.status == "accepted"
                        and (info.delta_i_bits or 0) > 0):
                    positive = True
                    break
            informative_b += positive
        by_window[window["role"]] = dict(sorted(counts.items()))

    primary = by_window["discovery"]
    probe = by_window["closure_probe"]
    expected_count = sum(window["window"] for window in windows)
    all_targets_seen = all_targets == expected_targets
    stable_target_mapping = all(len(forms) == 1 for forms in target_forms.values())
    same_form_set = set(primary) == set(probe)
    semantic_collisions = sorted(form for form, sets in form_semantics.items()
                                 if len(sets) > 1)
    if len(unique_ids) != expected_count or not all_targets_seen or not stable_target_mapping:
        raise ValueError(f"incomplete deterministic scan for {family}:{complexity.value}")
    k = len(primary)
    p_floor = 2 / (2 ** k)
    eligible = (structural_need == expected_count and informative_b == expected_count
                and channel_complete == expected_count and not semantic_collisions
                and len(option_hashes) == 1 and same_form_set)
    return {
        "family": family,
        "complexity": complexity.value,
        "regime": REGIME.value,
        "k": k,
        "two_sided_sign_flip_floor": p_floor,
        "classification": ("no_go_structural_or_semantic" if not eligible else
                           "descriptive_only" if k < 6 else "potentially_confirmatory"),
        "discovery_per_form_capacity": primary,
        "closure_probe_per_form_capacity": probe,
        "minimum_discovery_per_form": min(primary.values()),
        "closed_form_space": {
            "status": "qualified_source_bound_and_two_window_census",
            "argument": "The pinned source exposes only A-owned bit-0 and bit-2 clue values in the pre-read state, giving at most four form combinations for these cells. Both disjoint 512-seed windows observed all four combinations and every finite target label. This is source-bound capacity for this version, not an independence proof or a claim about changed generators.",
            "all_target_labels_seen": all_targets_seen,
            "target_count": len(all_targets),
            "stable_target_to_form": stable_target_mapping,
            "probe_adds_forms": bool(set(probe) - set(primary)),
        },
        "structural": {
            "instances": expected_count,
            "finalizer_needs_peer": structural_need,
            "authoritative_b_owned_informative": informative_b,
            "channel_complete": channel_complete,
            "eligible_all_instances": eligible,
        },
        "state_semantics": {
            "forms_with_multiple_authoritative_a_sets": semantic_collisions,
            "same_option_set_across_instances": len(option_hashes) == 1,
            "shared_template_hashes": sorted(template_hashes),
            "hash_distinct_forms_are_not_proven_independent": True,
        },
        "independence_limit": "Forms share a template; exact form sign flips require separately defended exchangeability. Seeds are not additional form units.",
        "unadjusted_alpha_0_05_best_case_attainable": p_floor <= 0.05 and eligible,
        "holm_7_or_8_first_step_best_case_attainable": p_floor <= 0.05 / 8 and eligible,
        "unique_instance_ids": len(unique_ids),
    }


def _holm_grid() -> list[dict[str, Any]]:
    grid = []
    for m in (1, 2, 7, 8):
        threshold = 0.05 / m
        k = next(k for k in range(1, 64) if 2 / 2 ** k <= threshold)
        grid.append({"hypotheses": m, "first_step_alpha": threshold,
                     "minimum_k_for_best_case_first_step": k})
    return grid


def build(root: Path) -> dict[str, Any]:
    """Rebuild the complete read-only audit; raise on input or network drift."""
    global _audit_active
    root = Path(root)
    _enable_network_guard()
    try:
        inputs = _verify_inputs(root)
        if tuple(sorted(tasks.FAMILY_GENERATORS)) != tuple(sorted(("planning", "hypothesis",
                                                                      "legal", *FAMILIES))):
            raise ValueError("generator family set changed; version the program first")
        inventory, prior_seeds, prior_ids = legal_census.inventory_prior_artifacts(root)
        for low, high in LEGAL_RESERVED:
            prior_seeds.update(range(low, high + 1))
        windows, floor = legal_census.choose_windows(prior_seeds)
        selected_seeds = {seed for window in windows
                          for seed in range(window["base"], window["end"] + 1)}
        if selected_seeds & prior_seeds:
            raise ValueError("candidate windows overlap prior seeds")
        selected_ids = {f"{family}-{seed:08x}" for family in FAMILIES
                        for seed in selected_seeds}
        if selected_ids & prior_ids:
            raise ValueError("candidate windows overlap prior instance ids")
        cells = [_scan_cell(family, complexity, windows)
                 for family in FAMILIES for complexity in COMPLEXITIES]
        if _network_events:
            raise ValueError(f"network events during audit: {_network_events}")
        artifact: dict[str, Any] = {
            "version": VERSION,
            "issue": ISSUE,
            "stage": "offline_capacity_and_prospective_family_design",
            "inputs_sha256": inputs,
            "inventory": {
                "manifest_files_discovered": inventory["manifest_files_discovered"],
                "manifest_files_scanned": inventory["manifest_files_scanned"],
                "prior_seed_union_sha256": inventory["prior_seed_union"]["sha256"],
                "prior_seed_max_after_legal_reservation": max(prior_seeds),
                "legal_reserved_windows": [list(item) for item in LEGAL_RESERVED],
                "inaccessible_manifests": inventory["inaccessible_manifests"],
                "inaccessible_directories": inventory["inaccessible_directories"],
                "overlap_qualified_by_audit_exceptions": bool(inventory["inaccessible_manifests"] or inventory["inaccessible_directories"]),
            },
            "windows": {"rule": "L02 inventory-first 1000-stride rule; reserve both legal windows before selection",
                        "candidate_floor": floor, "selected": windows,
                        "no_seed_or_accessible_id_overlap": True,
                        "inaccessible_locations_are_unknown_not_empty": True},
            "cells": cells,
            "holm_best_case_attainability": _holm_grid(),
            "breadth": {"existing_generator_families": 6,
                        "historical_conditional_support": ["planning:low"],
                        "inconclusive": ["hypothesis:low"],
                        "design_limited": ["legal:low"],
                        "audited_here": list(FAMILIES),
                        "proposed_additional_families": len(PROPOSALS),
                        "target": "7-8 distinct task families; proposals do not count as audited, runnable or confirmatory",
                        "no_cross_family_pooling": True},
            "proposals": list(PROPOSALS),
            "queue": {"historical_frozen": list(HISTORICAL_QUEUE),
                      "offline_design_followup": [item["name"] for item in PROPOSALS],
                      "existing_family_next_cells_in_historical_order": ["lexicon:low", "poetry:low", "reference:low"],
                      "status": "design backlog only; no live collection registered or authorized; no outcome-based reordering"},
            "statistical_limit": "Within-family k is prompt forms, not seeds or family count; shared templates require a defensible exchangeability argument. Seven or eight Holm tests need k>=9 for the first best-case threshold under the registered two-sided sign-flip recipe.",
            "provider_calls": 0,
            "network_audit_events": list(_network_events),
            "authorization": "none; no live collection or replay permitted",
        }
        artifact["content_hash"] = _content_hash(artifact)
        return artifact
    finally:
        _audit_active = False


def verify(root: Path) -> dict[str, Any]:
    path = Path(root) / ARTIFACT_PATH
    on_disk = path.read_bytes()
    published = json.loads(on_disk)
    rebuilt = build(Path(root))
    checks = {
        "content_hash": published.get("content_hash") == _content_hash(published),
        "byte_identical_rebuild": on_disk == _render(rebuilt),
        "no_provider_calls": published.get("provider_calls") == 0,
        "zero_network_events": not published.get("network_audit_events"),
    }
    return {"ok": all(checks.values()), "checks": checks,
            "content_hash": rebuilt["content_hash"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if args.write and args.verify:
        parser.error("choose write or verify")
    if args.verify:
        result = verify(args.repo_root)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1
    artifact = build(args.repo_root)
    if args.write:
        path = args.repo_root / ARTIFACT_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            output.write(_render(artifact))
    print(json.dumps({"version": VERSION, "content_hash": artifact["content_hash"],
                      "cells": len(artifact["cells"]), "provider_calls": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
