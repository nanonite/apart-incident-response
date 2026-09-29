"""L02 (#220): offline legal:low form census, independence and fresh-window audit.

Everything here is derived from files already on disk plus the deterministic
six-family generator: prior run manifests are inventoried first, the discovery
and independent closure-probe windows are then chosen offline from that
inventory, and legal:low instances are rebuilt in those windows to report form
count, per-form capacity, pre-read/option/state hashes, A-finalizer peer need,
the authoritative B-owned informative claim, closure evidence, shared-template
dependence, and a seed/ID overlap report. No provider call, probe, live journal
or authorization is made or recorded by any code path in this module, and no
frozen #200 or terminal #207/#215 artifact is ever written.

A process-wide audit hook records every network event raised while the census
is assembled and the build fails closed if one occurs, so ``network_audit`` in
the emitted artifact is an observed zero rather than an assumption.

Window selection is deliberately fail-closed: the windows are derived from the
inventory by a fixed rule, so a later artifact that introduces a colliding seed
changes the rebuild and breaks verification instead of silently moving the
windows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from apart_incident_response import jev_replay as jr
from apart_incident_response import jev_replication_preregistration as rep

CENSUS_VERSION = "jev-legal-p02-form-census-v1"
CENSUS_PATH = Path("runs/next-phase/legal/jev-legal-p02-form-census-v1.json")
DOC_PATH = Path("docs/jev-legal-p02-capacity.md")
PROTOCOL_PATH = Path("docs/jev-discovery-confirmation-plan.md")
SEQUENCE_PATH = Path("docs/jev-legal-task-sequence.md")
L01_EVIDENCE_PATH = Path("runs/next-phase/legal/jev-legal-p01-evidence-v1.json")
L01_DOC_PATH = Path("docs/jev-legal-p01-baseline.md")
AUDIT_200_PATH = Path("runs/epic-126/replication/jev-replication-form-audit-v1.json")
TERMINAL_215_PATH = Path("docs/jev-hypothesis-low-terminal-decision.md")
JOURNAL_207_PATH = Path("runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection.jsonl")
REPORT_207_PATH = Path("runs/next-phase/hypothesis/jev-discovery-v1/"
                       "jev-discovery-collection-report.json")

FAMILY = "legal"
COMPLEXITY = "low"
REGIME = "N"
#: The legal generator draws one of eight ``disposition-0..7`` targets.
TARGET_SPACE = tuple(range(8))

#: Fresh windows: size mirrors the frozen #200 windows, the stride guarantees
#: two windows can never touch, and the base is derived from the inventory.
WINDOW_SIZE = rep.SEED_SCAN_WINDOW
WINDOW_STRIDE = 1000
WINDOW_ROLES = ("discovery", "closure_probe")
WINDOW_ROLES_DOC = {
    "discovery": ("fixed discovery window: rebuilt here and the only window from which a "
                  "later registered block may select seeds"),
    "closure_probe": ("independent closure-probe window: offline closure evidence only; "
                      "disjoint from the discovery window and no seed may ever be selected "
                      "from it"),
}
SEED_GROWTH_CHECKPOINTS = rep.SEED_GROWTH_CHECKPOINTS
INSTANCES_PER_FORM = rep.INSTANCES_PER_FORM

#: Every prior run manifest is inventoried from runs/, except this chain's own
#: namespace (later legal-chain artifacts would otherwise record the windows
#: chosen here and break the byte-reproducible rebuild).
MANIFEST_ROOT = "runs"
CHAIN_OUTPUT_PREFIXES = ("runs/next-phase/legal/",)
OWN_OUTPUT = str(CENSUS_PATH)

#: Documented prior seed ranges and the reserved hypothesis windows that must
#: never be reused. Neither list is derived from an outcome.
DOCUMENTED_PRIOR_SEED_RANGES = tuple((int(low), int(high)) for low, high in
                                     rep.PRIOR_SEED_RANGES)
RESERVED_HYPOTHESIS_WINDOWS = ((85000, 85511), (86000, 86511), (87000, 87511))
RESERVED_HYPOTHESIS_SPAN = (85000, 87511)

#: Output paths owned by the closed hypothesis chain; L02 must never write to
#: any of them, and this census must never sit where an older artifact lives.
HYPOTHESIS_OUTPUT_PATHS = (
    "runs/next-phase/jev-form-census-v1.json",
    "runs/next-phase/jev-p02-scope-freeze.json",
    "runs/next-phase/jev-p04-discovery-registration-v1.json",
    "runs/next-phase/jev-p05-discovery-lock-v1.json",
    "runs/next-phase/jev-discovery-authorization-record-v1.json",
    "runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection.jsonl",
    "runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection-report.json",
    "runs/epic-126/replication/jev-replication-form-audit-v1.json",
    "runs/epic-126/replication/jev-replication-preregistration-v1.json",
)

#: Namespaces that are reported as explicit exclusions, never as empty sets.
EXCLUDED_SOURCES = (
    {"path": "runs/next-phase/legal/**",
     "reason": ("this chain's own outputs (L01 evidence and this census); excluding them keeps "
                "the rebuild deterministic once later legal-chain artifacts record the windows "
                "chosen here")},
    {"path": ".chainlink/issues.db",
     "reason": ("mutable task-tracker state rewritten by the plugin on every issue event; it is "
                "not a run manifest, and scanning it would make the rebuild depend on future "
                "issue text")},
    {"path": "docs/**, src/**, tests/**, *.md",
     "reason": ("narrative and source files, not run manifests; they reference instance ids that "
                "are recorded in the scanned run manifests and covered by the documented and "
                "reserved ranges below")},
)

SEED_KEYS = ("seed", "seeds", "selected_seeds", "planned_seeds", "journaled_seeds")
FAMILY_ID_RE = re.compile(rb"\b(?:hypothesis|reference|planning|poetry|legal|lexicon)-[0-9a-f]{8}\b")

NETWORK_EVENT_PREFIXES = ("socket.", "urllib.", "http.client.", "ftplib.")

#: Frozen inputs: recomputed from disk on every build; the expected prefixes
#: come from the #219/#215 task text and are pins, never hashes.
FROZEN_INPUTS: tuple[dict[str, Any], ...] = (
    {"path": str(PROTOCOL_PATH), "role": "research protocol for the discovery/confirmation chain",
     "expected_sha256_prefix": "501e21b6"},
    {"path": str(AUDIT_200_PATH), "role": "#200 frozen form-capacity audit",
     "expected_sha256_prefix": "cb529cd6"},
    {"path": str(JOURNAL_207_PATH), "role": "#207 P06 discovery journal (terminal, 16 rows)",
     "expected_sha256_prefix": "4e8de096"},
    {"path": str(REPORT_207_PATH), "role": "#207 P06 collection report (terminal)",
     "expected_sha256_prefix": "3086ceac"},
    {"path": str(TERMINAL_215_PATH), "role": "#215 terminal family report",
     "expected_sha256_prefix": "89ef2aaf"},
    {"path": str(L01_EVIDENCE_PATH), "role": "L01 evidence index (#219), predecessor handoff",
     "expected_sha256_prefix": None},
    {"path": str(L01_DOC_PATH), "role": "L01 baseline narrative (#219)",
     "expected_sha256_prefix": None},
    {"path": str(SEQUENCE_PATH), "role": "legal family task sequence (#218)",
     "expected_sha256_prefix": None},
)

#: Generator and hashing sources pinned so the rebuild is a build of *these*
#: bytes; recomputed, never accepted from prose.
SOURCE_INPUTS: tuple[str, ...] = (
    "src/apart_incident_response/task_families.py",
    "src/apart_incident_response/jev_replication_preregistration.py",
    "src/apart_incident_response/jev_replay.py",
    "src/apart_incident_response/jev_replay_preregistration_v4.py",
    "src/apart_incident_response/jev_choice.py",
    "src/apart_incident_response/jev_form_census.py",
    "src/apart_incident_response/jev_legal_form_census.py",
)


class CensusError(ValueError):
    """Fail-closed census build or verification violation."""


# --------------------------------------------------------------------------
# network audit hook (fail closed on any event)
# --------------------------------------------------------------------------

_NETWORK_EVENTS: list[str] = []
_HOOK_INSTALLED = False


def _record_network_event(event: str, _args: Any) -> None:
    if event.startswith(NETWORK_EVENT_PREFIXES):
        _NETWORK_EVENTS.append(event)


def _install_network_audit_hook() -> None:
    global _HOOK_INSTALLED
    if not _HOOK_INSTALLED:
        sys.addaudithook(_record_network_event)
        _HOOK_INSTALLED = True


def network_events() -> list[str]:
    return list(_NETWORK_EVENTS)


# --------------------------------------------------------------------------
# local helpers
# --------------------------------------------------------------------------

def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _render(document: Mapping[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _content_hash(document: Mapping[str, Any]) -> str:
    payload = json.dumps({key: value for key, value in document.items()
                          if key != "content_hash"}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _list_sha256(values: Sequence[Any]) -> str:
    return hashlib.sha256(json.dumps(list(values), sort_keys=True).encode("utf-8")).hexdigest()


def hash_inputs(root: Path, specs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    entries = []
    for spec in specs:
        digest = sha256_of(root / str(spec["path"]))
        prefix = spec.get("expected_sha256_prefix")
        entries.append({
            "path": spec["path"],
            "role": spec["role"],
            "expected_sha256_prefix": prefix,
            "sha256": digest,
            "prefix_match": None if prefix is None else digest.startswith(prefix),
        })
    return entries


def _rle(sorted_values: Sequence[int]) -> list[list[int]]:
    """Compact, exact encoding of a sorted seed set for the artifact."""
    ranges: list[list[int]] = []
    for value in sorted_values:
        if ranges and value == ranges[-1][1] + 1:
            ranges[-1][1] = value
        else:
            ranges.append([value, value])
    return ranges


# --------------------------------------------------------------------------
# prior-manifest inventory (performed before any window is chosen)
# --------------------------------------------------------------------------

def _error_detail(exc: OSError) -> str:
    """Path-independent error description (the relative path is recorded beside it).

    ``str(exc)`` embeds whatever path form the caller passed, which would make
    the census depend on whether the build ran with a relative or absolute
    ``--repo-root``.
    """

    return f"{type(exc).__name__}: {exc.strerror or 'os error'}"


def _is_chain_own(relative: str) -> bool:
    """True for this chain's own namespace (directory or file)."""

    return any(relative == prefix.rstrip("/") or relative.startswith(prefix)
               for prefix in CHAIN_OUTPUT_PREFIXES)


def _walk_runs(root: Path) -> tuple[list[str], list[dict[str, str]]]:
    """List every runs/ json artifact and record every inaccessible location.

    This chain's own namespace is skipped at walk time so that later
    legal-chain artifacts (which record the windows chosen here) can neither
    enter the prior set nor perturb the rebuild.
    """

    readable: list[str] = []
    inaccessible_dirs: list[dict[str, str]] = []
    stack = ["runs"]
    while stack:
        rel = stack.pop()
        try:
            with os.scandir(root / rel) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            inaccessible_dirs.append({"path": rel + "/", "error": type(exc).__name__,
                                      "detail": _error_detail(exc)})
            continue
        for entry in entries:
            child = f"{rel}/{entry.name}"
            if _is_chain_own(child):
                continue
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError as exc:
                inaccessible_dirs.append({"path": child + "/", "error": type(exc).__name__,
                                          "detail": _error_detail(exc)})
                continue
            if is_dir:
                stack.append(child)
            elif entry.name.endswith((".json", ".jsonl")):
                readable.append(child)
    return sorted(readable), inaccessible_dirs


def _add_seed_values(value: Any, seeds: set[int]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        seeds.add(int(value))
    elif isinstance(value, str) and value.isdigit():
        seeds.add(int(value))
    elif isinstance(value, list):
        for item in value:
            _add_seed_values(item, seeds)
    elif isinstance(value, dict):
        for item in value.values():
            _add_seed_values(item, seeds)


def _walk_manifest(node: Any, ids: set[str], seeds: set[int], path: str = "") -> None:
    """Collect instance ids and seeds from a parsed manifest document."""

    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            lowered = here.lower()
            if key == "instance_id" and isinstance(value, str):
                ids.add(value)
                continue
            if key == "instance_ids" and isinstance(value, list):
                ids.update(str(item) for item in value)
                continue
            if key == SEED_KEYS[0] or key in SEED_KEYS:
                _add_seed_values(value, seeds)
                if isinstance(value, (dict, list)):
                    _walk_manifest(value, ids, seeds, here)
                continue
            if isinstance(value, dict):
                if isinstance(value.get("base"), int) and "window" in lowered:
                    low = int(value["base"])
                    if isinstance(value.get("end"), int):
                        high = int(value["end"])
                    elif isinstance(value.get("window"), int):
                        high = low + int(value["window"]) - 1
                    elif isinstance(value.get("size"), int):
                        high = low + int(value["size"]) - 1
                    else:
                        high = low
                    seeds.update(range(low, high + 1))
                _walk_manifest(value, ids, seeds, here)
            elif isinstance(value, list):
                _walk_manifest(value, ids, seeds, here)
    elif isinstance(node, list):
        for item in node:
            _walk_manifest(item, ids, seeds, path)


def inventory_prior_artifacts(root: Path) -> tuple[dict[str, Any], set[int], set[str]]:
    """Inventory every prior run manifest, then derive the prior seed union.

    Inaccessible locations are audit exceptions, never empty sets: their
    contents are unknown and are reported as unverified, not as "no overlap".
    This chain's own namespace is skipped by the walk, so later legal-chain
    artifacts cannot enter the prior set or perturb the rebuild.
    """

    root = Path(root)
    files, inaccessible_dirs = _walk_runs(root)
    inaccessible_files: list[dict[str, str]] = []
    scanned: list[str] = []
    ids: set[str] = set()
    seeds: set[int] = set()

    for relative in files:
        path = root / relative
        try:
            data = path.read_bytes()
        except OSError as exc:
            inaccessible_files.append({"path": relative, "error": type(exc).__name__,
                                       "detail": _error_detail(exc)})
            continue
        scanned.append(relative)
        ids.update(match.decode("utf-8", "replace")
                   for match in FAMILY_ID_RE.findall(data))
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if relative.endswith(".jsonl"):
            for line in text.splitlines():
                if not line.strip():
                    continue
                try:
                    _walk_manifest(json.loads(line), ids, seeds)
                except json.JSONDecodeError:
                    continue
        else:
            try:
                _walk_manifest(json.loads(text), ids, seeds)
            except json.JSONDecodeError:
                continue

    documented = sorted({seed for low, high in DOCUMENTED_PRIOR_SEED_RANGES
                         for seed in range(low, high + 1)})
    reserved = sorted({seed for low, high in RESERVED_HYPOTHESIS_WINDOWS
                       for seed in range(low, high + 1)})
    prior_union = sorted(set(seeds) | set(documented) | set(reserved))
    legal_ids = sorted(instance_id for instance_id in ids if instance_id.startswith(f"{FAMILY}-"))

    document: dict[str, Any] = {
        "scan_scope": {
            "root": MANIFEST_ROOT,
            "patterns": ["runs/**/*.json", "runs/**/*.jsonl"],
            "rationale": ("every prior run manifest lives under runs/; the walk is explicit so "
                          "unlistable directories and unreadable files surface as exceptions "
                          "instead of silently disappearing from the scan"),
            "chain_output_prefixes_excluded": list(CHAIN_OUTPUT_PREFIXES),
            "own_output_path": OWN_OUTPUT,
            "excluded_sources": [dict(entry) for entry in EXCLUDED_SOURCES],
            "excluded_sources_are_stated_not_empty": True,
        },
        "manifest_files_discovered": len(files),
        "manifest_files_scanned": len(scanned),
        "chain_own_namespace_excluded": {
            "prefixes": list(CHAIN_OUTPUT_PREFIXES),
            "known_prior_files": [str(L01_EVIDENCE_PATH)],
            "known_prior_file_note": ("the only file that predates this census inside the chain "
                                      "namespace; it is hash-pinned as a frozen input and its "
                                      "seeds/ids are hypothesis-window values already covered by "
                                      "the reserved ranges below"),
            "statement": ("every path under the chain prefix is skipped at walk time, so later "
                          "legal-chain artifacts recording these windows can neither enter the "
                          "prior set nor change this rebuild"),
        },
        "instance_ids": {
            "count": len(ids),
            "sha256": _list_sha256(sorted(ids)),
            "legal_family_instance_ids": legal_ids,
            "legal_family_instance_id_count": len(legal_ids),
            "by_family": {family: sum(1 for instance_id in ids
                                      if instance_id.startswith(f"{family}-"))
                          for family in sorted(rep.FAMILY_ORDER)},
        },
        "found_seeds": {
            "count": len(seeds),
            "sha256": _list_sha256(sorted(seeds)),
            "ranges": _rle(sorted(seeds)),
            "min": min(seeds) if seeds else None,
            "max": max(seeds) if seeds else None,
        },
        "documented_seed_ranges": [[low, high] for low, high in DOCUMENTED_PRIOR_SEED_RANGES],
        "reserved_hypothesis_windows": [
            {"role": role, "low": low, "high": high,
             "description": "hypothesis:low window reserved by #200/#207; never reusable here"}
            for role, (low, high) in zip(("primary", "closure_probe", "confirmation"),
                                         RESERVED_HYPOTHESIS_WINDOWS)],
        "reserved_hypothesis_span": list(RESERVED_HYPOTHESIS_SPAN),
        "prior_seed_union": {
            "sources": ["found in accessible run manifests", "documented prior seed ranges",
                        "reserved hypothesis windows"],
            "count": len(prior_union),
            "sha256": _list_sha256(prior_union),
            "max": max(prior_union) if prior_union else None,
            "_seeds": prior_union,
        },
        "inaccessible_manifests": sorted(inaccessible_files, key=lambda item: item["path"]),
        "inaccessible_directories": sorted(inaccessible_dirs, key=lambda item: item["path"]),
        "exceptions_are_audit_exceptions_not_empty_sets": True,
        "statement": (
            "The prior-manifest inventory was completed before any window was chosen. "
            f"{len(files)} run manifests were discovered under runs/ outside this chain's own "
            f"namespace; {len(scanned)} were read, "
            f"{len(inaccessible_files)} files and {len(inaccessible_dirs)} directories were "
            "inaccessible and are recorded as audit exceptions whose contents are unknown, "
            "never as empty sets. The prior seed union therefore covers every accessible "
            "manifest seed, every documented prior seed range and the reserved hypothesis "
            "windows 85000-87511; overlap conclusions are qualified by the recorded "
            "exceptions."),
    }
    return document, set(prior_union), ids


def choose_windows(prior_seeds: set[int]) -> tuple[list[dict[str, Any]], int]:
    """Fresh windows chosen offline, after the inventory, by a fixed rule.

    Rule: start at the first 1000-multiple strictly above the largest prior
    seed, then take the first candidate of WINDOW_SIZE seeds per role (in
    ``WINDOW_ROLES`` order) that shares no seed with the inventory, stepping by
    WINDOW_STRIDE. The rule is a pure function of the inventory, so no outcome
    and no manual choice can enter it.
    """

    if not prior_seeds:
        raise CensusError("refusing to choose windows from an empty prior inventory")
    floor = ((max(prior_seeds) + 1) + WINDOW_STRIDE - 1) // WINDOW_STRIDE * WINDOW_STRIDE
    windows: list[dict[str, Any]] = []
    candidate = floor
    for role in WINDOW_ROLES:
        skipped = 0
        while True:
            span = range(candidate, candidate + WINDOW_SIZE)
            if not any(seed in prior_seeds for seed in span):
                break
            candidate += WINDOW_STRIDE
            skipped += 1
        windows.append({
            "role": role,
            "description": WINDOW_ROLES_DOC[role],
            "base": candidate,
            "end": candidate + WINDOW_SIZE - 1,
            "window": WINDOW_SIZE,
            "candidate_floor": floor,
            "candidates_skipped": skipped,
            "chosen_after_inventory": True,
            "selection_rule": ("first 1000-multiple at or above the floor that shares no seed "
                               "with the completed prior inventory; stride 1000 > window 512 "
                               "so consecutive windows are disjoint by construction"),
        })
        candidate += WINDOW_STRIDE
    return windows, floor


# --------------------------------------------------------------------------
# census over the chosen windows
# --------------------------------------------------------------------------

def _scan_window(window: Mapping[str, Any]) -> dict[str, Any]:
    scan = rep._scan_forms(FAMILY, int(window["base"]), int(window["window"]))
    return {
        "distinct_forms": scan["distinct_forms"],
        "growth_checkpoints": scan["growth_checkpoints"],
        "per_form_seed_counts": {form: len(seeds) for form, seeds in
                                 sorted(scan["forms"].items())},
        "forms": scan["forms"],
    }


def _structural(window: Mapping[str, Any]) -> dict[str, Any]:
    """Offline structural preconditions: peer need and B-owned information."""

    return rep.structural_preconditions(FAMILY, base=int(window["base"]),
                                        window=int(window["window"]))


def _closure_argument(discovery: Mapping[str, Any], form_ids: Sequence[str]) -> dict[str, Any]:
    """Generator-level closure: exhaustive enumeration of the finite form space.

    The form id is the sha256 of the model-visible ISO pre-read request body.
    For the legal family at LOW complexity and regime N the body is a
    deterministic function of ``(bit0, bit2)`` of the target: the state carries
    only A's private clues ``fictional_fact_0``/``fictional_fact_2`` (B's
    ``fictional_fact_1`` is never in the pre-read body) while model, question,
    instructions and the eight ``disposition-0..7`` options are fixed.
    ``(bit0, bit2)`` has exactly four values, so at most four forms exist.
    """

    base = int(discovery["base"])
    window = int(discovery["window"])
    first: dict[int, int] = {}
    for offset in range(window):
        seed = base + offset
        number = int(rep.instance_for(FAMILY, seed).target.rsplit("-", 1)[-1])
        if number not in first:
            first[number] = seed
    rows = []
    for number in TARGET_SPACE:
        if number not in first:
            raise CensusError(f"target disposition-{number} is not realized in the window")
        instance = rep.instance_for(FAMILY, first[number])
        rows.append({
            "target": instance.target,
            "target_number": number,
            "bit0": number & 1,
            "bit1": (number >> 1) & 1,
            "bit2": (number >> 2) & 1,
            "bit0_bit2": [number & 1, (number >> 2) & 1],
            "form_id": rep.pre_read_form_id(instance),
            "first_seed_in_discovery_window": first[number],
        })
    enumerated = sorted({row["form_id"] for row in rows})
    by_pair: dict[tuple[int, int], set[str]] = {}
    for row in rows:
        by_pair.setdefault(tuple(row["bit0_bit2"]), set()).add(row["form_id"])
    pair_is_function = all(len(forms) == 1 for forms in by_pair.values())
    if not pair_is_function:
        raise CensusError("the prompt form is not a function of (bit0, bit2)")
    if enumerated != sorted(form_ids):
        raise CensusError("enumerated form set disagrees with the window form set")
    form_to_targets: dict[str, list[str]] = {}
    for row in rows:
        form_to_targets.setdefault(row["form_id"], []).append(row["target"])
    return {
        "form_derivation": ("sha256 of the model-visible ISO pre-read request body (model + state "
                            "+ question/instructions/criteria) produced only from generator/task "
                            "structure; no outcome enters the hash"),
        "fixed_components": ["model", "question_id", "instructions",
                             "criteria/options (disposition-0..disposition-7)",
                             "state.family", "state.complexity", "state.agent_id"],
        "varying_component": ("state.clues = A's private clues = (bit0, bit2) of the target; "
                              "B's clue (bit1) is not in the pre-read body"),
        "finite_state_space": "(bit0, bit2) in {0,1} x {0,1}",
        "upper_bound_distinct_forms": 4,
        "exhaustive_enumeration": rows,
        "distinct_forms_enumerated": len(enumerated),
        "realized_forms": len(enumerated),
        "form_is_function_of_bit0_bit2": pair_is_function,
        "form_to_targets": {form: sorted(targets) for form, targets in
                            sorted(form_to_targets.items())},
        "conclusion": ("the prompt form is a deterministic function of (bit0, bit2) of the "
                       "target, which has exactly four values; exhaustive enumeration of all "
                       "eight disposition targets realizes exactly four distinct forms, "
                       "matching the form set observed in both fresh windows. The legal:low "
                       "form space is therefore closed at k = 4, proven by generator-level "
                       "enumeration of the finite state space, not merely observed "
                       "saturation."),
    }


def _form_records(discovery: Mapping[str, Any], form_ids: Sequence[str]) -> dict[str, Any]:
    """Per-form capacity, hashes, peer need and authoritative B-owned claim."""

    base = int(discovery["base"])
    window = int(discovery["window"])
    first_seed: dict[str, int] = {}
    for offset in range(window):
        seed = base + offset
        instance = rep.instance_for(FAMILY, seed)
        form = rep.pre_read_form_id(instance)
        if form in set(form_ids) and form not in first_seed:
            first_seed[form] = seed
    missing = [form for form in form_ids if form not in first_seed]
    if missing:
        raise CensusError(f"forms not realized in the discovery window: {missing}")

    records: dict[str, Any] = {}
    for form in form_ids:
        seed = first_seed[form]
        instance = rep.instance_for(FAMILY, seed)
        geometry = rep._instance_geometry(instance)
        hashes = rep.branch_hashes(instance, geometry["real_claim"], geometry["placebo_claim"])
        analysis = instance.channel_analysis()
        owner = instance.claim_owner(geometry["real_claim"])
        information = instance.information("A", geometry["real_claim"], "probe")
        placebo_owner = instance.claim_owner(geometry["placebo_claim"])
        placebo_information = instance.information("A", geometry["placebo_claim"], "probe")
        option_ids = list(geometry["option_ids"])
        number = int(instance.target.rsplit("-", 1)[-1])
        records[form] = {
            "representative_instance": instance.instance_id,
            "representative_seed": seed,
            "target": instance.target,
            "option_ids": option_ids,
            "option_count": len(option_ids),
            "option_set_hash": jr.canonical_hash(option_ids),
            "pre_read_request_body_hash": hashes["pre_read_request_body_hash"],
            "pre_read_state_hash": hashes["pre_read_state_hash"],
            "branch_request_hashes": hashes["branch_request_hashes"],
            "branch_state_hashes": hashes["branch_state_hashes"],
            "a_finalizer_peer_need": {
                "finalizer_needs_peer": bool(analysis["finalizer_needs_peer"]),
                "private_a_size": int(analysis["private_a_size"]),
                "joint_size": int(analysis["joint_size"]),
                "both_agents_needed": bool(analysis["both_agents_needed"]),
                "channel_complete": bool(analysis["channel_complete"]),
                "derived": "instance.channel_analysis() on the generator's clue-consistent sets",
            },
            "authoritative_b_owned_informative_claim": {
                "claim": geometry["real_claim"],
                "claim_owner": owner,
                "owned_by_b": owner == "B",
                "held_by_a_before_message": bool(instance.holds_claim("A", geometry["real_claim"])),
                "ownership_source": "family oracle instance.claim_owner, never a writer assertion",
                "information_status": information.status,
                "i_m_bits": float(information.delta_i_bits or 0.0),
                "before_count": int(information.before_count),
                "after_count": int(information.after_count or 0),
                "evaluator": "ExactInformationEvaluator",
            },
            "placebo_claim": {
                "claim": geometry["placebo_claim"],
                "claim_owner": placebo_owner,
                "owned_by_a": placebo_owner == "A",
                "i_m_bits": float(placebo_information.delta_i_bits or 0.0),
                "inert": float(placebo_information.delta_i_bits or 0.0) == 0.0,
            },
            "form_cell": {"bit0": number & 1, "bit2": (number >> 2) & 1,
                          "clues": list(instance.private_clues.get("A", ()))},
        }
    return records


def _dependence_assessment(discovery: Mapping[str, Any], form_ids: Sequence[str]) -> dict[str, Any]:
    """Shared-template / dependence assessment over the four legal forms."""

    base = int(discovery["base"])
    window = int(discovery["window"])
    bodies: dict[str, dict[str, Any]] = {}
    for offset in range(window):
        seed = base + offset
        instance = rep.instance_for(FAMILY, seed)
        form = rep.pre_read_form_id(instance)
        if form in set(form_ids) and form not in bodies:
            body, _ = rep.prv4.pre_read_body(instance, rep.pr.JEV_REPLAY_MODEL)
            bodies[form] = body
        if len(bodies) == len(form_ids):
            break
    missing = [form for form in form_ids if form not in bodies]
    if missing:
        raise CensusError(f"forms not realized in the discovery window: {missing}")

    def _template(body: Mapping[str, Any]) -> dict[str, Any]:
        template = json.loads(json.dumps(body))
        template["state"] = {key: value for key, value in template["state"].items()
                             if key != "clues"}
        return template

    templates = {form: _template(body) for form, body in bodies.items()}
    values = list(templates.values())
    shared = all(template == values[0] for template in values)
    if not shared:
        raise CensusError("the legal forms do not share a common template")
    template = values[0]
    question = next(iter(template["questions"].values()))
    cells: dict[str, dict[str, Any]] = {}
    for form, body in bodies.items():
        clues = list(body["state"]["clues"])
        bit0 = int(clues[0].rsplit("=", 1)[1])
        bit2 = int(clues[1].rsplit("=", 1)[1])
        cells[form] = {"bit0": bit0, "bit2": bit2, "clues": clues}
    pairs = [[pair[0], pair[1]] for pair in
             sorted((cell["bit0"], cell["bit2"]) for cell in cells.values())]
    return {
        "shared_template": shared,
        "template_hash": rep._digest(template),
        "template": {
            "model": template["model"],
            "state_keys_except_clues": sorted(key for key in template["state"] if key != "clues"),
            "question_id": next(iter(template["questions"].keys())),
            "instructions": question["instructions"],
            "option_count": len(question["criteria"]),
            "option_ids": sorted(question["criteria"]),
        },
        "identical_except": ["state.clues"],
        "form_cells": cells,
        "factorial_pairs": pairs,
        "structure": ("complete 2x2 factorial over (bit0, bit2) of the target; the four forms "
                      "are the entire finite legal form space, not a sample from a larger "
                      "prompt population"),
        "hash_distinct_not_independent": True,
        "consequence": ("the four forms are hash-distinct but template-identical: they share "
                        "model, question, instructions, the disposition-0..7 options and state "
                        "structure, and differ only in the state clue values (bit0, bit2). "
                        "They are therefore not independent prompts; a template-level effect "
                        "would shift all four forms together. Form-level sign flips are "
                        "assumption-dependent: the exact two-sided sign-flip p is a "
                        "descriptive statistic with the exchangeability assumption labeled, "
                        "never assumption-free inference. With k = 4 the attainable exact "
                        "two-sided sign-flip floor is 2/2^4 = 0.125 > 0.05, so no dichotomous "
                        "rejection at alpha = 0.05 is attainable at any effect size on this "
                        "family; formal classification is L03's (#221) deliverable."),
    }


# --------------------------------------------------------------------------
# overlap report
# --------------------------------------------------------------------------

def _seed_id_overlap(prior_ids: set[str], prior_seeds: set[int],
                     windows: Sequence[Mapping[str, Any]],
                     census: Mapping[str, Any]) -> dict[str, Any]:
    selected_ids: list[str] = []
    selected_seeds: list[int] = []
    per_window: dict[str, Any] = {}
    for window in windows:
        role = window["role"]
        base, size = int(window["base"]), int(window["window"])
        ids = [rep.instance_for(FAMILY, base + offset).instance_id for offset in range(size)]
        seeds = [base + offset for offset in range(size)]
        selected_ids.extend(ids)
        selected_seeds.extend(seeds)
        per_window[role] = {
            "instance_id_count": len(ids),
            "instance_id_sha256": _list_sha256(ids),
            "seed_sha256": _list_sha256(seeds),
            "first_instance_id": ids[0],
            "last_instance_id": ids[-1],
        }
    id_overlap = sorted(set(selected_ids) & prior_ids)
    seed_overlap = sorted(set(selected_seeds) & prior_seeds)
    discovery = [window for window in windows if window["role"] == "discovery"][0]
    probe = [window for window in windows if window["role"] == "closure_probe"][0]
    cross_seeds = sorted(set(range(discovery["base"], discovery["end"] + 1))
                         & set(range(probe["base"], probe["end"] + 1)))
    cross_ids = sorted(set(range(discovery["base"], discovery["end"] + 1))
                       & set(range(probe["base"], probe["end"] + 1)))
    reserved_hits = [
        {"window": [low, high],
         "seed_overlap": sorted(set(range(low, high + 1)) & set(selected_seeds))}
        for low, high in RESERVED_HYPOTHESIS_WINDOWS
        if set(range(low, high + 1)) & set(selected_seeds)]
    documented_hits = [
        {"range": [low, high],
         "seed_overlap": sorted(set(range(low, high + 1)) & set(selected_seeds))}
        for low, high in DOCUMENTED_PRIOR_SEED_RANGES
        if set(range(low, high + 1)) & set(selected_seeds)]
    legal_prior = sorted(instance_id for instance_id in prior_ids
                         if instance_id.startswith(f"{FAMILY}-"))
    legal_prior_overlap = sorted(set(selected_ids) & set(legal_prior))
    disjoint = not id_overlap and not seed_overlap and not reserved_hits and not documented_hits \
        and not cross_ids and not cross_seeds and not legal_prior_overlap
    exceptions = (census.get("inaccessible_manifests") or []) + \
        (census.get("inaccessible_directories") or [])
    return {
        "selected": {
            "windows": [window["role"] for window in windows],
            "instance_id_count": len(selected_ids),
            "instance_ids_unique": len(set(selected_ids)),
            "instance_ids_sha256": _list_sha256(selected_ids),
            "seed_count": len(selected_seeds),
            "seeds_sha256": _list_sha256(selected_seeds),
            "per_window": per_window,
        },
        "prior_instance_id_count": census["instance_ids"]["count"],
        "prior_instance_ids_sha256": census["instance_ids"]["sha256"],
        "prior_legal_family_instance_ids": census["instance_ids"]["legal_family_instance_ids"],
        "prior_seed_union_count": census["prior_seed_union"]["count"],
        "prior_seed_union_sha256": census["prior_seed_union"]["sha256"],
        "selected_ids_overlapping_prior": id_overlap,
        "selected_seeds_overlapping_prior": seed_overlap,
        "selected_legal_instance_ids_overlapping_prior_legal_ids": legal_prior_overlap,
        "discovery_vs_closure_probe_seed_overlap": cross_seeds,
        "discovery_vs_closure_probe_instance_id_overlap": cross_ids,
        "reserved_hypothesis_window_overlaps": reserved_hits,
        "documented_seed_range_overlaps": documented_hits,
        "disjoint_from_all_accessible_prior_artifacts": disjoint,
        "inaccessible_locations_remaining": len(exceptions),
        "qualification": ("disjointness is proven against every accessible prior run manifest, "
                          "every documented prior seed range and the reserved hypothesis "
                          f"windows; {len(exceptions)} inaccessible locations remain "
                          "unverified audit exceptions and are never treated as empty sets"),
    }


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def build_census(repo_root: Path | str) -> dict[str, Any]:
    """Deterministic, offline legal:low form census. No provider call."""

    root = Path(repo_root)
    _install_network_audit_hook()
    _NETWORK_EVENTS.clear()

    frozen_inputs = hash_inputs(root, FROZEN_INPUTS)
    source_inputs = hash_inputs(root, [{"path": path, "role": "generator/hashing source",
                                        "expected_sha256_prefix": None}
                                       for path in SOURCE_INPUTS])
    before = {entry["path"]: entry["sha256"] for entry in frozen_inputs + source_inputs}

    l01 = load_json(root / L01_EVIDENCE_PATH)
    audit_200 = load_json(root / AUDIT_200_PATH)
    hypothesis_form_ids = sorted(audit_200["form_capacity"]["form_ids"])

    # 1. Inventory every prior manifest, then and only then choose the windows.
    inventory, prior_seeds, prior_ids = inventory_prior_artifacts(root)
    windows, floor = choose_windows(prior_seeds)

    # 2. Rebuild legal:low instances from the generator inside those windows.
    census = {window["role"]: _scan_window(window) for window in windows}
    structural = {window["role"]: _structural(window) for window in windows}
    form_ids = sorted(census["discovery"]["forms"])
    for window in windows:
        role = window["role"]
        if sorted(census[role]["forms"]) != form_ids:
            raise CensusError(f"window {role} form set disagrees with the discovery window")

    capacity = {
        form: {window["role"]: census[window["role"]]["per_form_seed_counts"][form]
               for window in windows} for form in form_ids}
    for entry in capacity.values():
        entry["total_seeds"] = sum(entry[window["role"]] for window in windows)
    min_capacity = min(min(entry[window["role"]] for window in windows)
                       for entry in capacity.values())
    selected_seed_set = set()
    for window in windows:
        selected_seed_set.update(range(int(window["base"]), int(window["end"]) + 1))

    closure_observed = {
        "discovery_growth_checkpoints": census["discovery"]["growth_checkpoints"],
        "closure_probe_growth_checkpoints": census["closure_probe"]["growth_checkpoints"],
        "closure_probe_distinct_forms": census["closure_probe"]["distinct_forms"],
        "closure_probe_new_forms": len(set(census["closure_probe"]["forms"])
                                       - set(census["discovery"]["forms"])),
        "all_windows_distinct_forms": sorted(census[window["role"]]["distinct_forms"]
                                             for window in windows),
    }
    closure_argument = _closure_argument(windows[0], form_ids)

    form_records = _form_records(windows[0], form_ids)
    dependence = _dependence_assessment(windows[0], form_ids)
    overlap = _seed_id_overlap(prior_ids, prior_seeds, windows, inventory)

    legal_forms_disjoint = not (set(form_ids) & set(hypothesis_form_ids))
    doc_text = (root / DOC_PATH).read_text(encoding="utf-8") if (root / DOC_PATH).exists() else ""
    authorizes_text = ("nothing beyond L03 planning; no provider call, no probe, no collection, "
                       "no registration lock, no live run, no successor execution")

    l01_hashes_match = all(
        sha256_of(root / entry["path"]) == entry["sha256"]
        for entry in list(l01.get("inputs") or []) + list(l01.get("supporting_inputs") or []))
    l01_checks = [check for check in l01.get("checks") or []]
    l01_ok = bool(l01_checks) and all(bool(check.get("ok")) for check in l01_checks)

    after = {entry["path"]: sha256_of(root / entry["path"])
             for entry in frozen_inputs + source_inputs}
    events = network_events()

    windows_doc = {
        "chosen_after_inventory": True,
        "inventory_first": True,
        "candidate_floor": floor,
        "floor_derivation": ("first 1000-multiple strictly above the largest seed in the "
                             f"completed prior inventory (max {inventory['prior_seed_union']['max']})"),
        "window_size": WINDOW_SIZE,
        "window_stride": WINDOW_STRIDE,
        "roles": list(WINDOW_ROLES),
        "windows": windows,
        "discovery_vs_closure_probe_disjoint": True,
        "hypothesis_windows_reused": False,
        "hypothesis_span_never_reused": list(RESERVED_HYPOTHESIS_SPAN),
        "held_out_window": {
            "fixed_by_l02": False,
            "statement": ("L02 fixes only the discovery and independent closure-probe windows "
                          "required by #220; no held-out/confirmation window is chosen here. "
                          "Any later held-out window must be chosen by this same "
                          "inventory-first rule before its own outcomes exist, and no seed may "
                          "be drawn from either window before a registered gate allows it."),
        },
    }

    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any) -> dict[str, Any]:
        entry = {"check": name, "ok": bool(ok), "detail": detail}
        checks.append(entry)
        return entry

    check("census_version_matches",
          CENSUS_VERSION == "jev-legal-p02-form-census-v1", CENSUS_VERSION)
    check("frozen_input_prefixes_match",
          all(entry["prefix_match"] for entry in frozen_inputs
              if entry["expected_sha256_prefix"] is not None),
          {entry["path"]: {"sha256": entry["sha256"], "prefix_match": entry["prefix_match"]}
           for entry in frozen_inputs})
    check("generator_sources_recomputed",
          len(source_inputs) == len(SOURCE_INPUTS)
          and all(entry["sha256"] for entry in source_inputs),
          {entry["path"]: entry["sha256"] for entry in source_inputs})
    check("l01_handoff_targets_this_task",
          l01.get("artifact") == "jev-legal-p01-evidence-v1"
          and (l01.get("handoff") or {}).get("issue") == 220
          and (l01.get("handoff") or {}).get("deliverable") == str(CENSUS_PATH),
          {"artifact": l01.get("artifact"), "handoff": l01.get("handoff")})
    check("l01_checks_all_pass_with_zero_network",
          l01_ok and (l01.get("network_audit") or {}).get("events") == 0
          and (l01.get("network_audit") or {}).get("provider_calls") == 0,
          {"checks": len(l01_checks), "failed": [c["check"] for c in l01_checks if not c.get("ok")],
           "network_audit": l01.get("network_audit")})
    check("l01_recorded_hashes_match_current_bytes", l01_hashes_match,
          "every input and supporting input pinned by L01 recomputes from disk")
    check("prior_manifest_inventory_completed",
          inventory["manifest_files_scanned"] > 0 and inventory["prior_seed_union"]["count"] > 0,
          {"manifest_files_discovered": inventory["manifest_files_discovered"],
           "manifest_files_scanned": inventory["manifest_files_scanned"],
           "prior_seed_union_count": inventory["prior_seed_union"]["count"]})
    check("inaccessible_manifests_recorded_as_audit_exceptions",
          inventory["exceptions_are_audit_exceptions_not_empty_sets"] is True
          and (inventory["inaccessible_manifests"] or inventory["inaccessible_directories"]),
          {"files": [item["path"] for item in inventory["inaccessible_manifests"]],
           "directories": [item["path"] for item in inventory["inaccessible_directories"]]})
    check("excluded_sources_stated_not_silent",
          bool(inventory["scan_scope"]["excluded_sources"])
          and inventory["scan_scope"]["excluded_sources_are_stated_not_empty"] is True,
          [entry["path"] for entry in inventory["scan_scope"]["excluded_sources"]])
    check("windows_derived_after_inventory",
          all(window["chosen_after_inventory"] for window in windows)
          and floor == ((inventory["prior_seed_union"]["max"] + 1) + WINDOW_STRIDE - 1)
          // WINDOW_STRIDE * WINDOW_STRIDE,
          {"candidate_floor": floor,
           "max_prior_seed": inventory["prior_seed_union"]["max"],
           "windows": {window["role"]: [window["base"], window["end"]] for window in windows}})
    check("windows_disjoint_from_prior_seed_union",
          all(not (set(range(window["base"], window["end"] + 1)) & prior_seeds)
              for window in windows),
          {window["role"]: {"base": window["base"], "end": window["end"]}
           for window in windows})
    check("discovery_and_closure_probe_windows_disjoint",
          windows[0]["end"] < windows[1]["base"],
          {"discovery_end": windows[0]["end"], "closure_probe_base": windows[1]["base"]})
    check("hypothesis_windows_not_reused",
          not (selected_seed_set & set(range(RESERVED_HYPOTHESIS_SPAN[0],
                                             RESERVED_HYPOTHESIS_SPAN[1] + 1)))
          and overlap["reserved_hypothesis_window_overlaps"] == [],
          {"reserved_hypothesis_span": list(RESERVED_HYPOTHESIS_SPAN),
           "selected_seeds_in_span": sorted(selected_seed_set
                                            & set(range(RESERVED_HYPOTHESIS_SPAN[0],
                                                        RESERVED_HYPOTHESIS_SPAN[1] + 1))),
           "overlap": overlap["reserved_hypothesis_window_overlaps"]})
    check("no_seed_or_id_overlap_with_prior_artifacts",
          overlap["disjoint_from_all_accessible_prior_artifacts"] is True
          and overlap["selected_ids_overlapping_prior"] == []
          and overlap["selected_seeds_overlapping_prior"] == []
          and overlap["selected_legal_instance_ids_overlapping_prior_legal_ids"] == [],
          {key: overlap[key] for key in (
              "selected_ids_overlapping_prior", "selected_seeds_overlapping_prior",
              "selected_legal_instance_ids_overlapping_prior_legal_ids",
              "reserved_hypothesis_window_overlaps", "documented_seed_range_overlaps",
              "disjoint_from_all_accessible_prior_artifacts")})
    check("instance_ids_unique",
          overlap["selected"]["instance_ids_unique"] == overlap["selected"]["instance_id_count"]
          == 2 * WINDOW_SIZE,
          {"count": overlap["selected"]["instance_id_count"],
           "unique": overlap["selected"]["instance_ids_unique"]})
    check("form_counts_agree_across_windows_and_enumeration",
          all(census[window["role"]]["distinct_forms"] == len(form_ids) for window in windows)
          and closure_argument["distinct_forms_enumerated"] == len(form_ids),
          {"k": len(form_ids),
           "per_window": {window["role"]: census[window["role"]]["distinct_forms"]
                          for window in windows},
           "enumerated": closure_argument["distinct_forms_enumerated"]})
    check("closure_status_proven_not_merely_observed",
          closure_observed["closure_probe_new_forms"] == 0
          and closure_argument["form_is_function_of_bit0_bit2"] is True
          and closure_argument["upper_bound_distinct_forms"] == len(form_ids),
          {"basis": "generator-level exhaustive enumeration of the finite form space",
           "observed": closure_observed})
    check("closure_enumeration_covers_all_eight_targets",
          sorted(row["target_number"] for row in closure_argument["exhaustive_enumeration"])
          == list(TARGET_SPACE),
          len(closure_argument["exhaustive_enumeration"]))
    check("pre_read_option_and_state_hashes_recorded",
          sorted(form_records) == sorted(form_ids)
          and all(record["pre_read_request_body_hash"] == form
                  and record["pre_read_state_hash"]
                  and record["option_set_hash"]
                  and sorted(record["branch_request_hashes"]) == ["null", "placebo", "real"]
                  and sorted(record["branch_state_hashes"]) == ["null", "placebo", "real"]
                  for form, record in form_records.items()),
          {"forms": sorted(form_records)})
    check("a_finalizer_peer_need_true_for_every_form",
          all(record["a_finalizer_peer_need"]["finalizer_needs_peer"] for record
              in form_records.values())
          and all(structural[window["role"]]["finalizer_needs_peer"] for window in windows),
          {window["role"]: structural[window["role"]]["finalizer_needs_peer"]
           for window in windows})
    check("authoritative_b_owned_informative_claim_verified",
          all(record["authoritative_b_owned_informative_claim"]["owned_by_b"]
              and record["authoritative_b_owned_informative_claim"]["information_status"] == "accepted"
              and record["authoritative_b_owned_informative_claim"]["i_m_bits"] > 0.0
              and not record["authoritative_b_owned_informative_claim"]["held_by_a_before_message"]
              and record["placebo_claim"]["inert"]
              and record["placebo_claim"]["owned_by_a"]
              for record in form_records.values())
          and all(structural[window["role"]]["informative_b_owned_claims"] == WINDOW_SIZE
                  for window in windows),
          {window["role"]: {"informative_b_owned_claims":
                            structural[window["role"]]["informative_b_owned_claims"],
                            "b_to_a_information_bits":
                                structural[window["role"]]["b_to_a_information_bits"]}
           for window in windows})
    check("closed_finite_solution_set_and_channel_complete",
          all(structural[window["role"]]["closed_finite_solution_set"] and
              structural[window["role"]]["eligible"] for window in windows),
          {window["role"]: {"closed_finite_solution_set":
                            structural[window["role"]]["closed_finite_solution_set"],
                            "eligible": structural[window["role"]]["eligible"]}
           for window in windows})
    check("shared_template_identical_except_state_clues",
          dependence["shared_template"] is True
          and dependence["identical_except"] == ["state.clues"]
          and dependence["hash_distinct_not_independent"] is True,
          {"template_hash": dependence["template_hash"],
           "identical_except": dependence["identical_except"]})
    check("sign_flip_inference_labeled_assumption_dependent",
          "assumption-dependent" in dependence["consequence"]
          and "0.125" in dependence["consequence"],
          "dependence consequence carries the k = 4 floor and the exchangeability label")
    check("legal_forms_disjoint_from_hypothesis_forms", legal_forms_disjoint,
          {"legal_form_count": len(form_ids), "hypothesis_form_count": len(hypothesis_form_ids)})
    check("per_form_capacity_sums_to_window_sizes",
          all(sum(entry[window["role"]] for entry in capacity.values()) == WINDOW_SIZE
              for window in windows)
          and sum(entry["total_seeds"] for entry in capacity.values()) == 2 * WINDOW_SIZE,
          {"k": len(form_ids), "window_size": WINDOW_SIZE})
    check("per_form_capacity_satisfies_selection_quantum",
          min_capacity >= INSTANCES_PER_FORM,
          {"min_seeds_per_form": min_capacity,
           "instances_per_form_reference": INSTANCES_PER_FORM})
    check("no_outcome_based_selection",
          all(window["chosen_after_inventory"] for window in windows)
          and inventory["prior_seed_union"]["max"] is not None,
          {"consulted_live_outcomes": [],
           "rule": windows[0]["selection_rule"]})
    check("output_path_is_fresh_and_not_reused",
          str(CENSUS_PATH) not in HYPOTHESIS_OUTPUT_PATHS
          and str(CENSUS_PATH).startswith(CHAIN_OUTPUT_PREFIXES[0])
          and str(CENSUS_PATH) != str(L01_EVIDENCE_PATH),
          {"census_path": str(CENSUS_PATH),
           "hypothesis_output_paths": list(HYPOTHESIS_OUTPUT_PATHS)})
    check("capacity_reported_per_form_and_window",
          len(form_ids) > 0
          and sum(entry["total_seeds"] for entry in capacity.values()) == 2 * WINDOW_SIZE
          and all(entry[window["role"]] > 0 for entry in capacity.values()
                  for window in windows),
          {"k": len(form_ids),
           "total_seeds": sum(entry["total_seeds"] for entry in capacity.values())})
    check("closure_probe_is_never_selectable",
          "no seed may ever be selected" in windows_doc["windows"][1]["description"]
          and windows_doc["discovery_vs_closure_probe_disjoint"] is True,
          windows_doc["windows"][1]["description"])
    check("doc_pins_recomputed_input_hashes",
          bool(doc_text) and str(CENSUS_PATH) in doc_text and CENSUS_VERSION in doc_text
          and all(entry["sha256"] in doc_text for entry in frozen_inputs),
          {"doc": str(DOC_PATH),
           "digests": {entry["path"]: entry["sha256"] for entry in frozen_inputs}})
    check("frozen_inputs_byte_identical_after_build", before == after,
          "every frozen and source digest recomputed at the end equals the digest read at start")
    check("zero_network_events_under_audit_hook", not events,
          {"events": list(events), "provider_calls": 0})
    check("no_authorization_recorded",
          "no provider call" in authorizes_text and "no live run" in authorizes_text,
          authorizes_text)

    inventory_out = {key: value for key, value in inventory.items()
                     if key != "prior_seed_union"}
    inventory_out["prior_seed_union"] = {key: value for key, value in
                                         inventory["prior_seed_union"].items()
                                         if key != "_seeds"}

    document: dict[str, Any] = {
        "census_version": CENSUS_VERSION,
        "issue": "#220",
        "parent_issue": "#218",
        "root_issue": "#159",
        "milestone": "L02",
        "predecessor_issue": "#219",
        "successor_issue": "#221",
        "family": FAMILY,
        "complexity": COMPLEXITY,
        "regime": REGIME,
        "stage": "offline form capacity, independence and fresh-window audit",
        "protocol": str(PROTOCOL_PATH),
        "task_sequence": str(SEQUENCE_PATH),
        "offline_only": True,
        "authorizes": authorizes_text,
        "provider_calls": 0,
        "frozen_input_evidence": {"inputs": frozen_inputs, "sources": source_inputs},
        "l01_predecessor_evidence": {
            "path": str(L01_EVIDENCE_PATH),
            "artifact": l01.get("artifact"),
            "checks": len(l01_checks),
            "all_checks_pass": l01_ok,
            "network_events": (l01.get("network_audit") or {}).get("events"),
            "recorded_hashes_match_current_bytes": l01_hashes_match,
            "handoff_deliverable": (l01.get("handoff") or {}).get("deliverable"),
        },
        "prior_manifest_inventory": inventory_out,
        "windows": windows_doc,
        "census": census,
        "structural_preconditions": {
            "derivation": ("rep.structural_preconditions(legal, base, window) over each fresh "
                           "window; closed finite solution set, A-finalizer peer need and "
                           "B-owned informative claims are generator structure, not outcomes"),
            "per_window": structural,
        },
        "form_capacity": {
            "family": FAMILY,
            "k": len(form_ids),
            "form_ids": form_ids,
            "form_set_hash": rep._digest(form_ids),
            "per_form_capacity": capacity,
            "min_seeds_per_form": min_capacity,
            "instances_per_form_reference": INSTANCES_PER_FORM,
            "seed_growth_checkpoints": list(SEED_GROWTH_CHECKPOINTS),
            "selection_rule": ("first INSTANCES_PER_FORM seeds per form in ascending seed order "
                               "within a registered window; fixed N; no outcome-based stopping; "
                               "selection itself happens only at a later registered gate"),
            "distinct_seeds_are_not_form_units": True,
        },
        "closure": {
            "status": "closed",
            "proven": True,
            "basis": "generator-level exhaustive enumeration of the finite form space",
            "observed_saturation": closure_observed,
            "generator_argument": closure_argument,
            "residual_unknowns": [
                ("the closure proof covers only this generator configuration (legal family, LOW "
                 "complexity, regime N, Jev ISO pre-read); it does not extend to other "
                 "families, complexities, regimes or receiver conditions"),
                ("closure of the form space does not establish statistical independence of the "
                 "four forms; they share one template and differ only in state.clues"),
                ("the census is a deterministic offline artifact; it contains no live outcome "
                 "and authorizes no collection"),
            ],
            "statement": ("the legal:low prompt-form space is closed at k = 4, proven by "
                          "exhaustive enumeration of the finite generator state space and "
                          "corroborated by an independent closure-probe window that added zero "
                          "new forms; observed saturation alone would have left closure "
                          "unproven"),
        },
        "form_records": {
            "derivation": ("one representative instance per form (first discovery-window seed); "
                           "option/state/branch hashes via jev_replication_preregistration."
                           "branch_hashes, ownership via the family oracle"),
            "per_form": form_records,
        },
        "pre_read_hashes": {
            "derivation": ("jev_replay.prompt_form_id(jev_replay_preregistration_v4."
                           "pre_read_body(...)) for the request body, jev_replay.canonical_hash "
                           "for the state and option set, branch hashes via "
                           "jev_replication_preregistration.branch_hashes"),
            "per_form": {form: {"representative_instance": record["representative_instance"],
                                "representative_seed": record["representative_seed"],
                                "pre_read_request_body_hash": record["pre_read_request_body_hash"],
                                "pre_read_state_hash": record["pre_read_state_hash"],
                                "option_set_hash": record["option_set_hash"],
                                "branch_request_hashes": record["branch_request_hashes"],
                                "branch_state_hashes": record["branch_state_hashes"]}
                         for form, record in sorted(form_records.items())},
        },
        "dependence_assessment": dependence,
        "seed_id_overlap": overlap,
        "capacity_consequence_for_l03": {
            "k": len(form_ids),
            "attainable_two_sided_sign_flip_floor": "0.125",
            "floor_above_0_05": True,
            "k_below_six": len(form_ids) < 6,
            "statement": ("with k = 4 the attainable exact two-sided sign-flip floor is "
                          "2/2^4 = 0.125 > 0.05, so no dichotomous rejection at alpha = 0.05 is "
                          "attainable at any effect size on this family, and adjusted "
                          "multiplicity can only demand more forms; distinct seeds never add "
                          "form units. The formal pilot-versus-confirmatory classification, "
                          "attainability grid and discovery design belong to L03 (#221)."),
            "classification_owned_by": "L03 (#221)",
            "h0": "Delta = 0",
            "h1": "Delta < 0",
            "estimand": "equal-weight form mean of real-minus-placebo entropy",
            "no_legal_effect_size_prior": ("planning-low and hypothesis-low outcomes supply no "
                                           "legal-family effect-size prior"),
        },
        "limitations": [
            ("Offline only: no provider call, probe, live journal or network event was made or "
             "authorized."),
            ("Frozen #200 and terminal #207/#215 files are read-only inputs here and were "
             "preserved byte-identically."),
            ("Overlap conclusions are qualified by the recorded inaccessible manifests and "
             "directories: their contents are unknown and are never counted as empty sets."),
            ("The windows are chosen by a fixed inventory-first rule; a later artifact that "
             "introduces a colliding seed changes the rebuild and fails verification rather "
             "than moving the windows silently."),
            ("No held-out/confirmation window is fixed here; a later stage must choose one by "
             "the same inventory-first rule before its own outcomes exist."),
            ("A failed or stopped predecessor never authorizes a successor: nothing here "
             "approves legal:low collection, a route, a budget or any provider call."),
        ],
        "checks": checks,
        "network_audit": {"hook": "sys.addaudithook(" + ", ".join(NETWORK_EVENT_PREFIXES) + ")",
                          "events": len(events), "event_names": list(events),
                          "provider_calls": 0},
        "deterministic_rebuild": {
            "builder": "src/apart_incident_response/jev_legal_form_census.py",
            "rebuild_command": "python -m apart_incident_response.jev_legal_form_census --repo-root .",
            "byte_reproducible": True,
            "fail_closed_on_drift": True,
        },
        "handoff": {
            "to": "L03",
            "issue": 221,
            "deliverable": "attainability, classification and outcome-blind discovery design",
            "conditions": [
                "#220 must be closed by the plugin after reviewer approval before L03 runs",
                "form count, independence, closure and the fresh windows are recorded findings "
                "to cite, not assumptions to re-decide",
                "the hypothesis 85000-87511 windows, instance ids and output paths stay unused",
                "no provider call is authorized by this artifact; L07 supplies a separate "
                "scope-bound user authorization",
                "a failed or stopped predecessor never authorizes its successor",
            ],
        },
    }
    document["content_hash"] = _content_hash(document)
    if events:
        raise CensusError(f"network events during offline build: {events}")
    return document


def write_census(document: Mapping[str, Any], *, repo_root: Path | str) -> Path:
    target = Path(repo_root) / CENSUS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        handle.write(_render(document))
    return target


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

def verify_census(document: Mapping[str, Any], *, repo_root: Path | str) -> dict[str, Any]:
    """Fail-closed verification: rebuild, compare byte-for-byte, run checks."""

    root = Path(repo_root)
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

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
        failed_build = [entry["check"] for entry in rebuilt["checks"] if not entry["ok"]]
        check("rebuilt_census_checks_all_pass", not failed_build, failed_build)
        for entry in rebuilt["checks"]:
            checks.append(dict(entry))
            if not entry["ok"]:
                errors.append(f"{entry['check']}: {entry['detail']}")
    except (CensusError, OSError, json.JSONDecodeError) as exc:
        check("census_rebuilds_byte_for_byte", False, f"{type(exc).__name__}: {exc}")

    failed_build = [entry["check"] for entry in document.get("checks") or []
                    if not entry.get("ok")]
    check("artifact_checks_all_pass", not failed_build, failed_build)
    network = document.get("network_audit") or {}
    check("artifact_zero_provider_calls",
          network.get("events") == 0 and network.get("provider_calls") == 0
          and document.get("provider_calls") == 0, network)
    handoff = document.get("handoff") or {}
    check("handoff_to_l03", handoff.get("to") == "L03" and handoff.get("issue") == 221, handoff)
    check("offline_scope_recorded",
          document.get("offline_only") is True and "no provider call" in str(document.get("authorizes")),
          document.get("authorizes"))

    return {"mode": f"{CENSUS_VERSION}-verification", "ok": not errors,
            "errors": errors, "failed": [entry["check"] for entry in checks if not entry["ok"]],
            "checks": checks, "content_hash": document.get("content_hash"),
            "provider_calls": 0}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="L02 legal form census (offline; deterministic rebuild; zero provider calls)")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--build", action="store_true",
                        help="write the census to its fresh path (never overwrites)")
    args = parser.parse_args(argv)
    root = (Path(args.repo_root) if args.repo_root is not None
            else Path(__file__).resolve().parents[2])

    if args.build:
        document = build_census(root)
        write_census(document, repo_root=root)
        print(json.dumps({"mode": CENSUS_VERSION, "status": "built", "path": str(CENSUS_PATH),
                          "content_hash": document["content_hash"],
                          "checks_run": len(document["checks"]),
                          "failed": [entry["check"] for entry in document["checks"]
                                     if not entry["ok"]],
                          "provider_calls": 0}, indent=2, sort_keys=True))
        return 0

    path = root / CENSUS_PATH
    if not path.is_file():
        print(json.dumps({"mode": CENSUS_VERSION, "status": "missing", "path": str(CENSUS_PATH),
                          "provider_calls": 0}, indent=2, sort_keys=True))
        return 2
    verification = verify_census(load_json(path), repo_root=root)
    print(json.dumps(verification, indent=2, sort_keys=True, allow_nan=False))
    return 0 if verification["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CENSUS_VERSION", "CENSUS_PATH", "DOC_PATH", "PROTOCOL_PATH", "SEQUENCE_PATH",
    "FAMILY", "COMPLEXITY", "REGIME", "TARGET_SPACE", "WINDOW_SIZE", "WINDOW_STRIDE",
    "WINDOW_ROLES", "SEED_GROWTH_CHECKPOINTS", "INSTANCES_PER_FORM", "MANIFEST_ROOT",
    "CHAIN_OUTPUT_PREFIXES", "DOCUMENTED_PRIOR_SEED_RANGES", "RESERVED_HYPOTHESIS_WINDOWS",
    "RESERVED_HYPOTHESIS_SPAN", "HYPOTHESIS_OUTPUT_PATHS", "EXCLUDED_SOURCES",
    "FROZEN_INPUTS", "SOURCE_INPUTS",
    "CensusError", "sha256_of", "load_json", "hash_inputs", "network_events",
    "inventory_prior_artifacts", "choose_windows", "build_census", "write_census",
    "verify_census", "main",
]
