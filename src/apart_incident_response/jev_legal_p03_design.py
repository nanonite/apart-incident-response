"""L03 (#221): offline legal:low design classification and discovery design.

Everything here is derived from files already on disk (the L02 census, the
frozen #200/#207/#215 artifacts, the protocol and the program amendment) plus
the deterministic six-family generator. The module:

1. derives the observed independent form count ``k`` from L02 and *rebuilds*
   it from the generator, computes the exact two-sided sign-flip floor
   ``2/2^k`` (``2/16 = 0.125`` at ``k = 4``), and lays out the attainability
   grid under declared Holm multiplicity;
2. classifies the design with a deterministic, ordered decision rule:
   structural gate fail -> no-go, capacity gate fail -> no-go, otherwise
   ``k < 6`` -> descriptive discovery and ``k >= 6`` -> potentially
   confirmatory design subject to every other gate. Legal:low at ``k = 4``
   is classified **descriptive discovery**;
3. fixes an outcome-blind, capacity-derived fixed-N discovery screen (first
   ``INSTANCES_PER_FORM`` seeds per form in ascending seed order inside the
   L02 discovery window), a prospective coverage rule, and a compared grid of
   feasible request/cost scenarios with stop conditions.

No provider call, probe, live journal, authorization inference or modification
of frozen hypothesis artifact is made or recorded by any code path in this
module: a process-wide audit hook observes every network event and the build
fails closed if one occurs. This artifact is a design decision, never a
registration, a lock or an authorization.

The artifact is deterministic: ``build_design`` reproduces it byte-for-byte
from the frozen inputs and the generator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping, Sequence

from apart_incident_response import jev_legal_form_census as l02
from apart_incident_response import jev_replication_preregistration as rep

DESIGN_VERSION = "jev-legal-p03-design-v1"
DESIGN_PATH = Path("runs/next-phase/legal/jev-legal-p03-design-v1.json")
DOC_PATH = Path("docs/jev-legal-p03-design.md")

PROTOCOL_PATH = Path("docs/jev-discovery-confirmation-plan.md")
SEQUENCE_PATH = Path("docs/jev-legal-task-sequence.md")
PROGRAM_PATH = Path("docs/jev-cross-family-entropy-program-v1.md")
L01_EVIDENCE_PATH = Path("runs/next-phase/legal/jev-legal-p01-evidence-v1.json")
L01_DOC_PATH = Path("docs/jev-legal-p01-baseline.md")
L02_CENSUS_PATH = Path("runs/next-phase/legal/jev-legal-p02-form-census-v1.json")
L02_DOC_PATH = Path("docs/jev-legal-p02-capacity.md")
AUDIT_200_PATH = Path("runs/epic-126/replication/jev-replication-form-audit-v1.json")
JOURNAL_207_PATH = Path("runs/next-phase/hypothesis/jev-discovery-v1/"
                        "jev-discovery-collection.jsonl")
REPORT_207_PATH = Path("runs/next-phase/hypothesis/jev-discovery-v1/"
                       "jev-discovery-collection-report.json")
TERMINAL_215_PATH = Path("docs/jev-hypothesis-low-terminal-decision.md")

FAMILY = "legal"
COMPLEXITY = "low"
REGIME = "N"

#: Selection quantum and window size inherited from the frozen generator
#: constants: capacity counts are seeds, never independent form units.
INSTANCES_PER_FORM = rep.INSTANCES_PER_FORM
WINDOW_SIZE = rep.SEED_SCAN_WINDOW
DISCOVERY_WINDOW_SPAN = (88000, 88511)
CLOSURE_PROBE_WINDOW_SPAN = (89000, 89511)
RESERVED_HYPOTHESIS_SPAN = (85000, 87511)
RESERVED_HYPOTHESIS_WINDOWS = ((85000, 85511), (86000, 86511), (87000, 87511))

#: Recorded self-hash of the L02 census (recomputed from its bytes, never
#: accepted from prose).
L02_CENSUS_CONTENT_HASH = "b01aa7de17cb21d18b7dd83a12764da7ff265a18b7089f2c2be7eaaf6b72b775"

#: Statistical contract: exact two-sided cluster sign-flip at alpha = .05.
ALPHA = 0.05
ALPHA_EXACT = Fraction(1, 20)
#: Smallest k whose best-case floor 2/2^k reaches unadjusted alpha = .05.
CONFIRMATORY_MIN_K = 6
#: Declared Holm family sizes considered in the attainability grid: the
#: single-registration case, a two-hypothesis family, and the program's
#: seven-to-eight-family breadth target.
MULTIPLICITY_FAMILY_COUNTS = (1, 2, 7, 8)
K_BAND_ROWS = (4, 5, 6, 7, 8, 9)

#: Retry-inclusive accounting: one logical call may become three physical
#: requests (max_retries 2). Four writer calls (2 agents x 2 turns) plus one
#: receiver call per collected instance, matching the original L4X treatment.
RETRY_MULTIPLIER = 3
WRITER_CALLS_PER_INSTANCE = 4
RECEIVER_CALLS_PER_INSTANCE = 1
REPLAY_BRANCHES = 3

#: Frozen rate card carried from the #200/#205 registration as *arithmetic
#: precedent only*: no route, model or budget is authorized for the legal
#: family until L04 registers one and L07 supplies a scope-bound user
#: authorization.
LING_PROMPT_USD_PER_MTOK = rep.LING_PROMPT_USD_PER_MTOK
LING_COMPLETION_USD_PER_MTOK = rep.LING_COMPLETION_USD_PER_MTOK
LING_INPUT_TOKEN_CEILING = rep.LING_INPUT_TOKEN_CEILING
LING_OUTPUT_TOKEN_CEILING = rep.LING_OUTPUT_TOKEN_CEILING
JEV_INPUT_USD_PER_MTOK = rep.JEV_INPUT_USD_PER_MTOK
JEV_INPUT_TOKEN_CEILING = rep.JEV_INPUT_TOKEN_CEILING

#: Planning ceilings used to compare scenarios (registered values belong to
#: L04). A scenario is feasible only if its worst-case cost fits them.
COST_CEILING_COLLECTION_USD = 0.20
COST_CEILING_REPLAY_USD = 0.10
COST_CEILING_PROGRAM_USD = 0.30
#: Candidate seeds-per-form sizes compared in the scenario grid.
SCENARIO_SEEDS_PER_FORM = (2, 4, 8)

#: Proposed, currently absent live output paths. Nothing here creates them.
DISCOVERY_ID = "jev-discovery-v1"
DISCOVERY_DIR = f"runs/next-phase/legal/{DISCOVERY_ID}"
PROPOSED_PATHS = {
    "discovery_journal": f"{DISCOVERY_DIR}/jev-discovery-collection.jsonl",
    "discovery_report": f"{DISCOVERY_DIR}/jev-discovery-collection-report.json",
    "exploratory_replay_journal": f"{DISCOVERY_DIR}/jev-exploratory-replay.jsonl",
    "exploratory_replay_report": f"{DISCOVERY_DIR}/jev-exploratory-replay-report.json",
}

NETWORK_EVENT_PREFIXES = ("socket.", "urllib.", "http.client.", "ftplib.")

#: Frozen inputs: recomputed from disk on every build. Expected prefixes are
#: pins carried from earlier verified records or task text, never the hash.
FROZEN_INPUTS: tuple[dict[str, Any], ...] = (
    {"path": str(PROTOCOL_PATH), "role": "research protocol (scientific contract)",
     "expected_sha256_prefix": "501e21b6"},
    {"path": str(AUDIT_200_PATH), "role": "#200 frozen form-capacity audit",
     "expected_sha256_prefix": "cb529cd6"},
    {"path": str(JOURNAL_207_PATH), "role": "#207 terminal P06 discovery journal",
     "expected_sha256_prefix": "4e8de096"},
    {"path": str(REPORT_207_PATH), "role": "#207 terminal P06 collection report",
     "expected_sha256_prefix": "3086ceac"},
    {"path": str(TERMINAL_215_PATH), "role": "#215 terminal family report",
     "expected_sha256_prefix": "89ef2aaf"},
    {"path": str(L01_EVIDENCE_PATH), "role": "L01 evidence index (#219)",
     "expected_sha256_prefix": "b2d07266"},
    {"path": str(L01_DOC_PATH), "role": "L01 baseline narrative (#219)",
     "expected_sha256_prefix": "8926f48d"},
    {"path": str(SEQUENCE_PATH), "role": "legal family task sequence (#218)",
     "expected_sha256_prefix": "884b0ed4"},
    {"path": str(PROGRAM_PATH), "role": "cross-family program amendment (2026-09-29)",
     "expected_sha256_prefix": None},
    {"path": str(L02_CENSUS_PATH), "role": "L02 form census (#220), predecessor handoff",
     "expected_sha256_prefix": None},
    {"path": str(L02_DOC_PATH), "role": "L02 capacity narrative (#220)",
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


class DesignError(ValueError):
    """Fail-closed design build or verification violation."""


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
# helpers
# --------------------------------------------------------------------------

def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _content_hash(document: Mapping[str, Any]) -> str:
    payload = json.dumps({key: value for key, value in document.items()
                          if key != "content_hash"}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _render(document: Mapping[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _decimal(value: Fraction) -> str:
    """Exact decimal rendering of a dyadic rational (0.125, 0.00390625, ...)."""

    return str(float(value))


# --------------------------------------------------------------------------
# derivation: k, sign-flip floor, multiplicity grid
# --------------------------------------------------------------------------

def _sign_flip_floor(k: int) -> dict[str, Any]:
    """Exact two-sided sign-flip floor 2/2^k, derived from k alone."""

    if k < 1:
        raise DesignError(f"form count must be positive, found {k}")
    denominator = 2 ** k
    exact = Fraction(2, denominator)
    return {
        "formula": "2/2^k",
        "k": k,
        "numerator": 2,
        "denominator": denominator,
        "exact_fraction": f"2/{denominator}",
        "reduced_fraction": str(exact),
        "value": _decimal(exact),
        "derivation": (f"with k = {k} independent forms the exhaustive two-sided cluster "
                       f"sign-flip enumerates 2^{k} = {denominator} sign assignments; the most "
                       f"extreme assignment ties the observed statistic on each side, so the "
                       f"smallest attainable two-sided p is 2/{denominator} = "
                       f"{_decimal(exact)}"),
        "best_case_floor": ("ties and zero effects can only make the attainable p larger; "
                            "this floor assumes defensible form-level sign exchangeability"),
    }


def _min_k_for(threshold: Fraction) -> int:
    """Smallest k whose best-case floor 2/2^k reaches the threshold."""

    k = 1
    while k <= 64:
        if Fraction(2, 2 ** k) <= threshold:
            return k
        k += 1
    raise DesignError(f"no k <= 64 satisfies the threshold {threshold}")


def _k_bands() -> list[dict[str, Any]]:
    bands = []
    for k in K_BAND_ROWS:
        floor = Fraction(2, 2 ** k)
        confirmatory = floor <= ALPHA_EXACT
        bands.append({
            "k": k,
            "attainable_two_sided_sign_flip_floor": _decimal(floor),
            "floor_le_alpha_0_05": confirmatory,
            "unadjusted_alpha_0_05_classification": (
                "potentially confirmatory, subject to all other gates" if confirmatory
                else "descriptive/estimation only"),
        })
    return bands


def _multiplicity_grid() -> list[dict[str, Any]]:
    """Holm first-step thresholds and the smallest k that can reach them."""

    rows = []
    for families in MULTIPLICITY_FAMILY_COUNTS:
        threshold = ALPHA_EXACT / families
        min_k = _min_k_for(threshold)
        rows.append({
            "registered_family_count": families,
            "holm_first_step_threshold_fraction": str(threshold),
            "holm_first_step_threshold": format(float(threshold), ".10g"),
            "threshold_derivation": (f"alpha .05 / {families} = {str(threshold)} = "
                                     f"{format(float(threshold), '.10g')}"),
            "min_k_for_attainable_floor": min_k,
            "floor_at_min_k": _decimal(Fraction(2, 2 ** min_k)),
            "k4_floor_eligible": Fraction(2, 16) <= threshold,
            "note": ("single-registration threshold; repeated singletons do not give .05 "
                     "error control across the program" if families == 1 else
                     "first ordered Holm p must be at most this value"
                     if families == 2 else
                     "cross-family breadth target from the program amendment; applies only "
                     "if these family hypotheses are actually in the frozen multiplicity set"),
        })
    return rows


# --------------------------------------------------------------------------
# gates and classification
# --------------------------------------------------------------------------

def _structural_gate(census: Mapping[str, Any]) -> dict[str, Any]:
    """Peer-information structure and closure: pass/fail with named evidence."""

    closure = census.get("closure") or {}
    per_window = ((census.get("structural_preconditions") or {}).get("per_window")) or {}
    form_records = ((census.get("form_records") or {}).get("per_form")) or {}
    checks = {
        "form_space_closed_and_proven": closure.get("proven") is True
        and closure.get("status") == "closed",
        "closed_finite_solution_set_every_window": bool(per_window) and all(
            window.get("closed_finite_solution_set") for window in per_window.values()),
        "finalizer_needs_peer_every_window": bool(per_window) and all(
            window.get("finalizer_needs_peer") for window in per_window.values()),
        "b_owned_informative_claims_full_window": bool(per_window) and all(
            window.get("informative_b_owned_claims") == WINDOW_SIZE
            for window in per_window.values()),
        "one_bit_b_to_a_information": bool(per_window) and all(
            window.get("b_to_a_information_bits") == [1.0]
            for window in per_window.values()),
        "channel_eligible_every_window": bool(per_window) and all(
            window.get("eligible") for window in per_window.values()),
        "placebo_inert_for_every_form": bool(form_records) and all(
            record.get("placebo_claim", {}).get("inert")
            and record.get("placebo_claim", {}).get("owned_by_a")
            for record in form_records.values()),
        "receiver_option_set_fixed_across_forms": len({
            record.get("option_set_hash") for record in form_records.values()}) == 1,
    }
    return {
        "gate": "structural",
        "question": ("does legal:low offer an authentic peer-owned information opportunity "
                     "and a measurable receiver decision on a fixed option set"),
        "evidence": ("L02 structural preconditions, closure proof and per-form records, "
                     "recomputed by the generator and pinned here by content hash"),
        "checks": checks,
        "passed": all(checks.values()),
    }


def _capacity_gate(census: Mapping[str, Any], scan: Mapping[str, Sequence[int]],
                   form_ids: Sequence[str]) -> dict[str, Any]:
    """Can the fixed-N screen be built from recorded capacity alone?"""

    capacity = census.get("form_capacity") or {}
    per_form = capacity.get("per_form_capacity") or {}
    discovery_counts = {form: int(per_form.get(form, {}).get("discovery", 0))
                        for form in form_ids}
    probe_counts = {form: int(per_form.get(form, {}).get("closure_probe", 0))
                    for form in form_ids}
    scan_counts = {form: len(seeds) for form, seeds in scan.items()}
    min_discovery = min(discovery_counts.values(), default=0)
    scarcest_cell = min(list(discovery_counts.values()) + list(probe_counts.values()),
                        default=0)
    windows = ((census.get("windows") or {}).get("windows")) or []
    discovery_window = next((w for w in windows if w.get("role") == "discovery"), {})
    checks = {
        "k_matches_l02_form_capacity": capacity.get("k") == len(form_ids),
        "generator_scan_matches_census_counts": scan_counts == discovery_counts,
        "every_form_has_at_least_quantum_seeds": min_discovery >= INSTANCES_PER_FORM,
        "scarcest_cell_has_at_least_quantum_seeds": scarcest_cell >= INSTANCES_PER_FORM,
        "discovery_window_recorded": [
            discovery_window.get("base"), discovery_window.get("end")] == list(
            DISCOVERY_WINDOW_SPAN),
        "closure_probe_window_recorded_and_unselectable": any(
            w.get("role") == "closure_probe"
            and [w.get("base"), w.get("end")] == list(CLOSURE_PROBE_WINDOW_SPAN)
            for w in windows),
        "distinct_seeds_are_not_form_units": capacity.get(
            "distinct_seeds_are_not_form_units") is True,
        "no_held_out_window_fixed": ((census.get("windows") or {}).get("held_out_window")
                                     or {}).get("fixed_by_l02") is False,
    }
    return {
        "gate": "capacity",
        "question": ("does recorded per-form capacity support the outcome-blind fixed-N "
                     "screen without inventing forms or windows"),
        "evidence": ("L02 form capacity per form per window and the rebuilt generator scan "
                     "of the discovery window"),
        "discovery_window_per_form_seeds": discovery_counts,
        "closure_probe_window_per_form_seeds": probe_counts,
        "min_seeds_per_form_discovery_window": min_discovery,
        "scarcest_cell_both_windows": scarcest_cell,
        "selection_quantum": INSTANCES_PER_FORM,
        "checks": checks,
        "passed": all(checks.values()),
    }


def _classification(k: int, floor: Mapping[str, Any], structural: Mapping[str, Any],
                    capacity: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic, ordered decision rule evaluated against the two gates."""

    floor_value = Fraction(2, 2 ** k)
    rules = [
        "if the structural gate fails -> no_go: write a no-go design decision, never a "
        "runnable registration",
        "if the capacity gate fails -> no_go: capacity cannot be satisfied outcome-blind "
        "from the recorded windows",
        "if the attainable exact two-sided sign-flip floor 2/2^k exceeds alpha .05 "
        "(k < 6) -> descriptive_discovery: pilot/estimation only",
        "if k >= 6 -> potentially_confirmatory_design, still subject to every other gate, "
        "the declared multiplicity rule, coverage, and a separate L07 authorization",
    ]
    if not structural["passed"] or not capacity["passed"]:
        decision = "no_go"
        trace = [
            {"rule": 1, "result": "structural gate passed -> continue"
             if structural["passed"] else "structural gate failed -> no_go"},
            {"rule": 2, "result": "capacity gate passed -> continue"
             if (structural["passed"] and capacity["passed"])
             else "capacity gate failed -> no_go"},
        ]
    elif floor_value > ALPHA_EXACT:
        decision = "descriptive_discovery"
        trace = [
            {"rule": 1, "result": "structural gate passed -> continue"},
            {"rule": 2, "result": "capacity gate passed -> continue"},
            {"rule": 3, "result": (f"floor {floor['value']} > 0.05 "
                                   "-> descriptive_discovery")},
            {"rule": 4, "result": "not reached"},
        ]
    else:
        decision = "potentially_confirmatory_design"
        trace = [
            {"rule": 1, "result": "structural gate passed -> continue"},
            {"rule": 2, "result": "capacity gate passed -> continue"},
            {"rule": 3, "result": f"floor {floor['value']} <= 0.05 -> continue"},
            {"rule": 4, "result": "k >= 6 -> potentially_confirmatory_design"},
        ]
    return {
        "decision": decision,
        "decision_rule": rules,
        "decision_trace": trace,
        "descriptive_discovery_vs_no_go": (
            "no-go is reserved for a failed structural or capacity gate: both gates pass "
            "here, so the family is runnable as descriptive discovery. It is not a no-go, "
            "and it is not confirmatory: the attainable floor 2/2^4 = 0.125 exceeds "
            "alpha .05 at any effect size, so no dichotomous rejection is attainable on "
            "this generator version."),
        "descriptive_pilot_vs_potentially_confirmatory": (
            "a descriptive pilot reports estimates and guards with no rejection claim and "
            "no alpha spent; potentially confirmatory work requires k >= 6 (floor "
            "<= .05) before declared multiplicity, plus fresh data, a registered error "
            "criterion, defensible exchangeability and a separate authorization. Legal:low "
            "at k = 4 is a descriptive pilot under every multiplicity rule in this "
            "artifact."),
        "generator_version_scope": (
            "this classification binds the closed four-form legal:low generator version "
            "audited by L02; a redesigned generator is a new protocol boundary with a new "
            "audit, not an upgrade of this decision"),
        "status": "offline design decision; not a registration, lock or authorization",
    }


# --------------------------------------------------------------------------
# outcome-blind fixed-N screen
# --------------------------------------------------------------------------

def _scan_forms(family: str, base: int, window: int) -> dict[str, list[int]]:
    """Rebuild form -> ascending seeds from the generator (offline only)."""

    forms: dict[str, list[int]] = {}
    for seed in range(base, base + window):
        instance = rep.instance_for(family, seed)
        forms.setdefault(rep.pre_read_form_id(instance), []).append(seed)
    return {form: sorted(seeds) for form, seeds in sorted(forms.items())}


def _cost_model() -> dict[str, Any]:
    ling_call = (LING_INPUT_TOKEN_CEILING * LING_PROMPT_USD_PER_MTOK
                 + LING_OUTPUT_TOKEN_CEILING * LING_COMPLETION_USD_PER_MTOK) / 1_000_000
    jev_call = JEV_INPUT_TOKEN_CEILING * JEV_INPUT_USD_PER_MTOK / 1_000_000
    return {
        "ling_worst_physical_call_usd": round(ling_call, 12),
        "jev_worst_physical_call_usd": round(jev_call, 12),
        "ling_prompt_usd_per_mtok": LING_PROMPT_USD_PER_MTOK,
        "ling_completion_usd_per_mtok": LING_COMPLETION_USD_PER_MTOK,
        "ling_input_token_ceiling": LING_INPUT_TOKEN_CEILING,
        "ling_output_token_ceiling": LING_OUTPUT_TOKEN_CEILING,
        "jev_input_usd_per_mtok": JEV_INPUT_USD_PER_MTOK,
        "jev_input_token_ceiling": JEV_INPUT_TOKEN_CEILING,
        "retry_inclusive_physical_per_logical": RETRY_MULTIPLIER,
        "status": ("planning arithmetic carried from the #200/#205 registration; the legal "
                   "family has no registered or authorized route"),
    }


def _scenario(seeds_per_form: int, capacity_min: int, form_count: int) -> dict[str, Any]:
    """Request counts and worst-case cost for one candidate screen size."""

    block_n = seeds_per_form * form_count
    cost = _cost_model()
    writer_logical = block_n * WRITER_CALLS_PER_INSTANCE
    receiver_logical = block_n * RECEIVER_CALLS_PER_INSTANCE
    replay_logical = block_n * REPLAY_BRANCHES
    writer_physical = writer_logical * RETRY_MULTIPLIER
    receiver_physical = receiver_logical * RETRY_MULTIPLIER
    replay_physical = replay_logical * RETRY_MULTIPLIER
    collection_worst = (writer_physical * cost["ling_worst_physical_call_usd"]
                        + receiver_physical * cost["jev_worst_physical_call_usd"])
    replay_worst = replay_physical * cost["jev_worst_physical_call_usd"]
    quantum_ok = seeds_per_form >= INSTANCES_PER_FORM
    capacity_ok = seeds_per_form <= capacity_min
    collection_ok = collection_worst <= COST_CEILING_COLLECTION_USD
    replay_ok = replay_worst <= COST_CEILING_REPLAY_USD
    program_ok = collection_worst + replay_worst <= COST_CEILING_PROGRAM_USD
    reasons = []
    if not quantum_ok:
        reasons.append(f"fewer than INSTANCES_PER_FORM = {INSTANCES_PER_FORM} seeds per form")
    if not capacity_ok:
        reasons.append(f"exceeds scarcest per-form capacity {capacity_min}")
    if not collection_ok:
        reasons.append(f"collection worst case {collection_worst:.9f} exceeds "
                       f"${COST_CEILING_COLLECTION_USD:.2f}")
    if not replay_ok:
        reasons.append(f"replay worst case {replay_worst:.9f} exceeds "
                       f"${COST_CEILING_REPLAY_USD:.2f}")
    if not program_ok:
        reasons.append(f"program worst case {collection_worst + replay_worst:.9f} exceeds "
                       f"${COST_CEILING_PROGRAM_USD:.2f}")
    return {
        "seeds_per_form": seeds_per_form,
        "fixed_n": block_n,
        "quantum_ok": quantum_ok,
        "capacity_ok": capacity_ok,
        "collection": {
            "planned": {"writer": writer_logical, "receiver": receiver_logical,
                        "combined": writer_logical + receiver_logical},
            "physical": {"writer": writer_physical, "receiver": receiver_physical,
                         "combined": writer_physical + receiver_physical},
            "worst_case_cost_usd": round(collection_worst, 12),
            "cost_ceiling_usd": COST_CEILING_COLLECTION_USD,
            "within_ceiling": collection_ok,
        },
        "exploratory_replay": {
            "planned": {"jev": replay_logical, "writer": 0, "combined": replay_logical},
            "physical": {"jev": replay_physical, "writer": 0,
                         "combined": replay_physical},
            "events_max": block_n,
            "branches": REPLAY_BRANCHES,
            "worst_case_cost_usd": round(replay_worst, 12),
            "cost_ceiling_usd": COST_CEILING_REPLAY_USD,
            "within_ceiling": replay_ok,
        },
        "program": {
            "worst_case_cost_usd": round(collection_worst + replay_worst, 12),
            "cost_ceiling_usd": COST_CEILING_PROGRAM_USD,
            "within_ceiling": program_ok,
        },
        "feasible": quantum_ok and capacity_ok and collection_ok and replay_ok and program_ok,
        "infeasible_reasons": reasons,
    }


def _scenario_grid(capacity_min: int, form_count: int) -> dict[str, Any]:
    """Compare candidate screens and pick the smallest feasible size."""

    scenarios = [_scenario(size, capacity_min, form_count)
                 for size in SCENARIO_SEEDS_PER_FORM]
    feasible = [s for s in scenarios if s["feasible"]]
    if not feasible:
        raise DesignError("no feasible discovery screen under the recorded capacity")
    chosen = min(feasible, key=lambda s: s["seeds_per_form"])
    for scenario in scenarios:
        scenario["selected"] = scenario["seeds_per_form"] == chosen["seeds_per_form"]
    return {
        "cost_model": _cost_model(),
        "planning_ceilings_usd": {
            "collection": COST_CEILING_COLLECTION_USD,
            "exploratory_replay": COST_CEILING_REPLAY_USD,
            "program": COST_CEILING_PROGRAM_USD,
        },
        "candidate_sizes": list(SCENARIO_SEEDS_PER_FORM),
        "scenarios": scenarios,
        "selection_rule": (
            "s* = the smallest seeds-per-form value that is at least INSTANCES_PER_FORM = 4, "
            "at most the scarcest per-form discovery-window capacity, and whose "
            "retry-inclusive worst-case collection, replay and program costs fit the "
            "planning ceilings; the screen then takes the first s* seeds per form in "
            "ascending seed order inside the discovery window"),
        "selected_seeds_per_form": chosen["seeds_per_form"],
        "selected_fixed_n": chosen["fixed_n"],
        "comparison": (
            "s = 2 fails the registered selection quantum before any cost is considered; "
            "s = 4 fits every ceiling with the collection worst case 0.146276352 <= 0.20 "
            "and program worst case 0.195821568 <= 0.30; s = 8 exceeds the collection "
            "ceiling (0.292552704 > 0.20) and the program ceiling (0.391643136 > 0.30). "
            "The rule is a pure function of capacity and the rate card, so no outcome, "
            "emission or entropy value can enter it"),
        "authorization_status": (
            "planning arithmetic only: L04 registers the legal route, rates, caps and stop "
            "rule as new registration fields, and only L07 may authorize any request"),
    }


def _discovery_screen(form_ids: Sequence[str], scan: Mapping[str, Sequence[int]],
                      seeds_per_form: int, capacity: Mapping[str, Any]) -> dict[str, Any]:
    """Fixed-N manifest: first seeds per form, ascending, outcome-blind."""

    manifest: list[dict[str, Any]] = []
    for form in sorted(form_ids):
        chosen = sorted(scan[form])[:seeds_per_form]
        if len(chosen) != seeds_per_form:
            raise DesignError(f"form {form} has only {len(chosen)} selectable seeds")
        for seed in chosen:
            instance = rep.instance_for(FAMILY, seed)
            manifest.append({"instance_id": instance.instance_id, "seed": seed,
                             "prompt_form_id": form})
    block_n = seeds_per_form * len(form_ids)
    if len(manifest) != block_n:
        raise DesignError(f"screen must contain exactly {block_n} instances")
    membership: dict[str, list[str]] = {}
    for entry in manifest:
        membership.setdefault(str(entry["prompt_form_id"]), []).append(
            str(entry["instance_id"]))
    discovery_capacity = {form: capacity["per_form_capacity"][form]["discovery"]
                          for form in form_ids}
    return {
        "window": {"role": "discovery", "base": DISCOVERY_WINDOW_SPAN[0],
                   "end": DISCOVERY_WINDOW_SPAN[1],
                   "window": DISCOVERY_WINDOW_SPAN[1] - DISCOVERY_WINDOW_SPAN[0] + 1},
        "instances_per_form": seeds_per_form,
        "fixed_n": block_n,
        "selection_rule": (
            f"first {seeds_per_form} seeds per form in ascending seed order inside the L02 "
            "discovery window; fixed N; no outcome-based stopping; selection uses only the "
            "generator's form assignment and the recorded capacity"),
        "outcome_blind": True,
        "consulted_outcomes": [],
        "outcome_blind_derivation": (
            "the rule is a pure function of the pinned discovery window, the rebuilt form "
            "assignment and INSTANCES_PER_FORM; emission, guard, entropy and writer results "
            "are never consulted, and the closure-probe window and every prior window are "
            "excluded by construction"),
        "form_membership": {form: sorted(ids) for form, ids in sorted(membership.items())},
        "manifest": manifest,
        "manifest_hash": _digest(manifest),
        "per_form_spare_capacity": {
            form: int(discovery_capacity[form]) - seeds_per_form for form in form_ids},
        "capacity_note": (
            "spare capacity is headroom recorded for coverage reporting only; it never "
            "licenses seed replacement, replenishment or extra forms"),
        "closure_probe_window_selectable": False,
        "closure_probe_window": list(CLOSURE_PROBE_WINDOW_SPAN),
        "held_out_window": {
            "fixed_here": False,
            "statement": ("no held-out/confirmation window is chosen by this task; any later "
                          "held-out window must use the L02 inventory-first rule before its "
                          "own outcomes exist"),
        },
    }


def _coverage_rule(capacity: Mapping[str, Any]) -> dict[str, Any]:
    """Prospective coverage rule, frozen from capacity before any collection."""

    return {
        "prospective": True,
        "frozen_before_collection": True,
        "basis": ("L02 per-form discovery-window capacity (minimum "
                  f"{min(v['discovery'] for v in capacity['per_form_capacity'].values())} "
                  "seeds per form; scarcest cell across both windows "
                  f"{capacity['min_seeds_per_form']}) against the selection quantum "
                  f"{INSTANCES_PER_FORM}"),
        "instances_per_form": INSTANCES_PER_FORM,
        "min_complete_per_form": 1,
        "permissible_within_form_missingness": (
            f"up to {INSTANCES_PER_FORM - 1} of {INSTANCES_PER_FORM} seeds per form may be "
            "missing; at least 1 complete instance per form is required"),
        "complete_case_scope": (
            "the set of planned instances with all required fields: structural need, "
            "emission or recorded silence, verified B ownership, accepted board write "
            "followed by A read exposure, and information; reported by stage, form and "
            "branch with reasons"),
        "discovery_screen_requirements": [
            "every registered form must have at least one instance with structural need "
            "(finalizer_needs_peer)",
            "every registered form must have at least one instance with voluntary emission "
            "(B-authored claim) or recorded silence",
            "every registered form must have at least one instance with verified B ownership "
            "and an accepted board write followed by A read exposure",
        ],
        "missing_entire_form": (
            "blocks the registered full-form estimand; label any available-form estimate "
            "descriptive and report it with its denominator"),
        "no_imputation": True,
        "no_seed_replacement": True,
        "no_form_removal_after_outcomes": True,
        "no_replenishment_from_spare_capacity": True,
        "selection_risk": (
            "if within-form missingness is not random, the complete-case estimate may be "
            "biased; this rule freezes the permissible missingness before collection and "
            "reports the resulting complete-case scope and selection risk"),
        "reporting": (
            "report planned, attempted, emitted, eligible, replayed, valid, complete and "
            "missing counts by stage, form and branch, with reasons; average valid complete "
            "pairs within their frozen forms regardless of guards"),
    }


def _stops() -> list[str]:
    return [
        "request cap or cost cap reached before the next call",
        "all fixed-N instances attempted (fixed schedule; completion ends the block)",
        "model or endpoint drift from the registered value",
        "protocol-key, normalization-policy or option-set identity drift",
        "request/state/option identity drift or registration, source, treatment or "
        "geometry hash drift",
        "malformed, non-finite, negative or option-mismatched receiver vector",
        "hard normalization deviation above the registered ceiling or argmax shift after "
        "normalization",
        "writer terminal errors (empty_output, truncated_output, unparsed_output, "
        "invalid_answer, writer_error, rate-limited)",
        "two consecutive terminal provider failures",
        "output collision (journal or report path already exists)",
        "any audit exception that breaks provenance or treatment integrity",
    ]


# --------------------------------------------------------------------------
# estimand, exchangeability, constraints
# --------------------------------------------------------------------------

def _estimand() -> dict[str, Any]:
    return {
        "h0": "Delta = 0",
        "h1": "Delta < 0",
        "estimand": "equal-weight form mean of real-minus-placebo entropy",
        "formula": ("d_fe = H(real message | C_fe) - H(matched placebo | C_fe); "
                    "d_f = mean_e(d_fe) within form f; Delta = (1/k) sum_f d_f"),
        "primary_test": ("exhaustive two-sided exact cluster sign-flip over all 2^k sign "
                         "assignments with a frozen numerical tie tolerance, plus a "
                         "negative-direction requirement"),
        "one_sided_switch_forbidden": (
            "the scientific alternative is directional but the operational test stays "
            "two-sided; a one-sided design would need its own registration"),
        "interval": ("form-mean t interval with df = k - 1, unadjusted unless a simultaneous "
                     "interval was registered; an interval half-width is not a power-based "
                     "MDE"),
        "experimental_unit": "prompt form",
        "closed_form_space_meaning": (
            "E_f is a uniform average over the registered finite legal forms, not a "
            "population of prompts"),
        "guards_never_filter_the_estimate": True,
        "preserved_from": "docs/jev-discovery-confirmation-plan.md (byte-identical input)",
        "statement": (
            "the registered legal estimand is preserved unchanged: H0 Delta = 0, "
            "H1 Delta < 0, equal-weight form mean of real-minus-placebo entropy on the fixed "
            "eight-option set, tested two-sided with a negative-direction requirement"),
    }


def _exchangeability(census: Mapping[str, Any]) -> dict[str, Any]:
    dependence = census.get("dependence_assessment") or {}
    return {
        "shared_template_hash": dependence.get("template_hash"),
        "identical_except": dependence.get("identical_except"),
        "structure": dependence.get("structure"),
        "factorial_pairs": dependence.get("factorial_pairs"),
        "hash_distinct_not_independent": True,
        "limit": (
            "the four legal forms are hash-distinct but template-identical: they share "
            "model, question, instructions, the disposition-0..7 options and state "
            "structure, differing only in state.clues (bit0, bit2). A template-level effect "
            "would shift all four forms together, so form-level sign flips are not "
            "guaranteed to be exchangeable"),
        "consequence": (
            "the exact two-sided sign-flip p at k = 4 is reported as a descriptive, "
            "assumption-dependent statistic with the exchangeability assumption labeled, "
            "never as assumption-free inference; the companion t interval carries "
            "distributional assumptions that are especially fragile at k = 4"),
        "seeds_do_not_fix_exchangeability": (
            "more seeds within a form improve emission, coverage, variability and guard "
            "estimates but change neither k nor exchangeability; independent cluster "
            "exchangeability under the null must be defended on template/dependence "
            "grounds, not on hash-distinctness"),
        "pooling_forbidden": (
            "forms are not pooled across families and duplicates are not split: a "
            "cross-family claim needs its own registered estimand and error contract, and "
            "legal:low cannot become confirmatory by pooling with another family"),
        "more_forms_require_redesign": (
            "raising k means a prospective, versioned generator redesign with its own audit "
            "(a new protocol boundary), never extra seeds or reordered history; this task "
            "performs no redesign"),
    }


def _constraints() -> list[dict[str, str]]:
    return [
        {"constraint": "no provider call, probe, live journal or network request of any kind",
         "basis": "#221 task text and chain direction; only the later L07 gate can grant a "
                  "separate explicit authorization",
         "consequence": "every number in this artifact is offline derivation or planning "
                        "arithmetic"},
        {"constraint": "a failed or stopped predecessor never authorizes its successor",
         "basis": "research protocol and legal task sequence",
         "consequence": "closing #220/#221 with evidence releases planning work only"},
        {"constraint": "preserve frozen #200 and terminal #207/#215 files byte-identically",
         "basis": "#221 task text",
         "consequence": "they are read-only pinned inputs here, rehashed before and after "
                        "the build"},
        {"constraint": "preserve the registered legal estimand and the two-sided exact "
                       "sign-flip test",
         "basis": "research protocol; program amendment",
         "consequence": "no one-sided switch, no guard filtering, no imputation"},
        {"constraint": "observed independent form count k comes from L02; seeds are never "
                       "counted as forms",
         "basis": "L02 census and program amendment",
         "consequence": "k = 4 and floor 0.125 are findings to cite, not re-decide"},
        {"constraint": "planning-low and hypothesis-low outcomes supply no legal-family "
                       "effect-size prior",
         "basis": "legal task sequence and program amendment",
         "consequence": "no power, MDE or effect-size claim borrows those results"},
        {"constraint": "do not silently redesign the generator",
         "basis": "program amendment",
         "consequence": "a larger form space is a new version with its own audit; this "
                        "classification binds the audited four-form version"},
        {"constraint": "do not re-order the frozen historical queue",
         "basis": "program amendment (hypothesis -> legal -> lexicon -> poetry -> reference)",
         "consequence": "capacity-based prioritization must use offline structural facts "
                        "and disclose any departure"},
        {"constraint": "the motivating paper is not Jev entropy evidence",
         "basis": "program amendment",
         "consequence": "its performance results are no effect-size prior and no validation "
                        "of an entropy detector"},
        {"constraint": "#227's offline family-capacity and expansion audit precedes #222",
         "basis": "program amendment worker order #221 -> #227 -> #222",
         "consequence": "this handoff supplies no authorization and cannot mutate this "
                        "artifact or an eventual L04 lock"},
        {"constraint": "k = 4 cannot become confirmatory by adding seeds or pooling "
                       "families",
         "basis": "program amendment",
         "consequence": "the family stays descriptive under every multiplicity rule "
                        "recorded here"},
        {"constraint": "L04 must register route, model, token budget, cost rates, request "
                       "caps and stop rules as new registration fields",
         "basis": "legal task sequence; L01 baseline",
         "consequence": "the stopped hypothesis Ling route carries no authorization into "
                        "the legal family"},
        {"constraint": "seed selection stays outcome-blind and capacity-derived",
         "basis": "research protocol",
         "consequence": "emission, guard and entropy values never enter the rule"},
        {"constraint": "no held-out window is chosen here",
         "basis": "L02 handoff and research protocol",
         "consequence": "a later window uses the inventory-first rule before its own "
                        "outcomes exist"},
    ]


def _non_claims() -> list[str]:
    return [
        "no provider call, probe or live journal was made or authorized",
        "this artifact is not a registration, a lock or an authorization",
        "no confirmatory or significance-style claim for legal:low at k = 4",
        "no population-level generalization: the four forms are the entire finite form space",
        "no effect-size prior is taken from planning-low or hypothesis-low",
        "seeds are not forms and never increase k",
        "forms are never pooled across families to obtain a smaller p-value",
        "the generator is not redesigned and the frozen queue is not re-ordered",
        "the motivating paper's benchmark results are not Jev entropy evidence",
        "no route, model, budget or stop rule is approved for the legal family here",
        "capacity headroom is not permission to replace missing seeds",
    ]


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def build_design(repo_root: Path | str) -> dict[str, Any]:
    """Deterministic, offline L03 design decision. No provider call."""

    root = Path(repo_root)
    _install_network_audit_hook()
    _NETWORK_EVENTS.clear()

    frozen_inputs = l02.hash_inputs(root, FROZEN_INPUTS)
    source_inputs = l02.hash_inputs(root, [{"path": path, "role": "generator/hashing source",
                                            "expected_sha256_prefix": None}
                                           for path in SOURCE_INPUTS])
    before = {entry["path"]: entry["sha256"] for entry in frozen_inputs + source_inputs}

    census = load_json(root / L02_CENSUS_PATH)
    l02_content_ok = _content_hash(census) == L02_CENSUS_CONTENT_HASH

    # 1. Rebuild k from the generator; L02's recorded form count is the claim.
    windows = (census.get("windows") or {}).get("windows") or []
    discovery_window = next((w for w in windows if w.get("role") == "discovery"), None)
    if discovery_window is None:
        raise DesignError("L02 census has no discovery window")
    base, span = int(discovery_window["base"]), int(discovery_window["window"])
    if [base, base + span - 1] != list(DISCOVERY_WINDOW_SPAN):
        raise DesignError(f"discovery window drift: {base}..{base + span - 1}")
    scan = _scan_forms(FAMILY, base, span)
    form_ids = sorted(scan)
    recorded_ids = sorted((census.get("form_capacity") or {}).get("form_ids") or [])
    if form_ids != recorded_ids:
        raise DesignError("generator form set disagrees with the L02 census")

    k = len(form_ids)
    floor = _sign_flip_floor(k)
    bands = _k_bands()
    multiplicity = _multiplicity_grid()

    # 2. Gates, then the deterministic decision.
    structural = _structural_gate(census)
    capacity = _capacity_gate(census, scan, form_ids)
    classification = _classification(k, floor, structural, capacity)

    # 3. Capacity-derived screen size, then the fixed-N manifest.
    discovery_counts = {form: int(census["form_capacity"]["per_form_capacity"][form]
                                  ["discovery"]) for form in form_ids}
    capacity_min = min(discovery_counts.values())
    scenarios = _scenario_grid(capacity_min, k)
    screen = _discovery_screen(form_ids, scan, scenarios["selected_seeds_per_form"],
                               census["form_capacity"])

    coverage = _coverage_rule(census["form_capacity"])
    stops = _stops()
    estimand = _estimand()
    exchangeability = _exchangeability(census)
    constraints = _constraints()

    # 4. The L04 handoff (and the #227 scope note) are assembled before the
    #    checks so that the checks can verify them against the same values the
    #    artifact records.
    handoff_conditions = [
        "#221 must be closed by the plugin after reviewer approval before L04 runs",
        ("#227 (offline cross-family capacity and expansion audit) must complete first: the "
         "worker order is #221 -> #227 -> #222, and #227 grants no authorization and cannot "
         "mutate this artifact or an L04 lock"),
        ("classification, k, floor, gates and the selection rule are recorded findings to "
         "cite, not assumptions to re-decide"),
        ("L04 registers route, model, token budget, cost rates, retry-inclusive request and "
         "dollar caps, stop rules and fresh paths as new registration fields; the stopped "
         "hypothesis Ling route carries nothing forward"),
        ("no provider call is authorized by this artifact; L07 supplies a separate "
         "scope-bound user authorization covering exact stage, route and caps"),
        "a failed or stopped predecessor never authorizes its successor",
    ]
    handoff_to_227 = {
        "issue": 227,
        "scope": ("offline audit of every remaining existing family across predeclared "
                  "eligible complexity/regime cells plus prospective full task-family "
                  "designs: enumerate canonical model-visible pre-read forms, prove or "
                  "qualify closure, record per-form capacity and shared-template "
                  "dependence, report structural B->A need and authoritative information, "
                  "inventory prior IDs/seeds and inaccessible artifacts, and specify "
                  "additional families only as substantial multi-step tasks with authentic "
                  "peer-owned information, a matched inert placebo and measurable receiver "
                  "Choice uncertainty - never microbenchmarks or a paper's benchmark name"),
        "not_performed_here": ("this task classifies legal:low only; the cross-family "
                               "capacity and expansion inventory belongs to #227 and its "
                               "outcome can demand a new program version but cannot rewrite "
                               "this decision"),
        "grants_authorization": False,
    }
    handoff = {
        "to": "L04",
        "issue": 222,
        "deliverable": ("fresh legal discovery registration or an explicit no-go; this "
                        "design decision is input, never a registration"),
        "conditions": handoff_conditions,
        "handoff_to_227": handoff_to_227,
    }

    # 5. Overlap facts recomputed without rescanning the manifest tree: every
    #    selectable seed must avoid the documented and reserved prior ranges.
    reserved_ranges = tuple((int(low), int(high))
                            for low, high in rep.PRIOR_SEED_RANGES) + \
        RESERVED_HYPOTHESIS_WINDOWS
    selected_seeds = [entry["seed"] for entry in screen["manifest"]]
    forbidden_hits = sorted({seed for seed in selected_seeds
                             if any(low <= seed <= high for low, high in reserved_ranges)})
    overlap = census.get("seed_id_overlap") or {}
    prior_legal_ids = overlap.get("prior_legal_family_instance_ids") or []

    proposed_absent = {name: not (root / path).exists()
                       for name, path in PROPOSED_PATHS.items()}
    doc_text = (root / DOC_PATH).read_text(encoding="utf-8") if (root / DOC_PATH).exists() \
        else ""
    authorizes_text = ("nothing beyond L04 planning; no provider call, no probe, no "
                       "collection, no registration lock, no live run, no authorization "
                       "inference; a failed predecessor never authorizes its successor")

    l01 = load_json(root / L01_EVIDENCE_PATH)
    l01_hashes_match = all(
        sha256_of(root / entry["path"]) == entry["sha256"]
        for entry in list(l01.get("inputs") or []) + list(l01.get("supporting_inputs") or []))

    l02_checks = list(census.get("checks") or [])
    l02_ok = bool(l02_checks) and all(bool(check.get("ok")) for check in l02_checks)
    l02_hashes_match = all(
        sha256_of(root / entry["path"]) == entry["sha256"]
        for entry in list((census.get("frozen_input_evidence") or {}).get("inputs") or [])
        + list((census.get("frozen_input_evidence") or {}).get("sources") or []))

    after = {entry["path"]: sha256_of(root / entry["path"])
             for entry in frozen_inputs + source_inputs}
    events = network_events()

    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any) -> dict[str, Any]:
        entry = {"check": name, "ok": bool(ok), "detail": detail}
        checks.append(entry)
        return entry

    check("design_version_matches", DESIGN_VERSION == "jev-legal-p03-design-v1",
          DESIGN_VERSION)
    check("frozen_input_prefixes_match",
          all(entry["prefix_match"] for entry in frozen_inputs
              if entry["expected_sha256_prefix"] is not None),
          {entry["path"]: {"sha256": entry["sha256"], "prefix_match": entry["prefix_match"]}
           for entry in frozen_inputs})
    check("generator_sources_recomputed",
          len(source_inputs) == len(SOURCE_INPUTS)
          and all(entry["sha256"] for entry in source_inputs),
          {entry["path"]: entry["sha256"] for entry in source_inputs})
    check("l02_census_content_hash_recomputes", l02_content_ok,
          {"recorded": L02_CENSUS_CONTENT_HASH,
           "recomputed": _content_hash(census)})
    check("l02_handoff_targets_this_task",
          (census.get("handoff") or {}).get("to") == "L03"
          and (census.get("handoff") or {}).get("issue") == 221,
          census.get("handoff"))
    check("l02_checks_all_pass_with_zero_network",
          l02_ok and (census.get("network_audit") or {}).get("events") == 0
          and (census.get("network_audit") or {}).get("provider_calls") == 0,
          {"checks": len(l02_checks),
           "failed": [c["check"] for c in l02_checks if not c.get("ok")],
           "network_audit": census.get("network_audit")})
    check("l02_recorded_hashes_match_current_bytes", l02_hashes_match,
          "every input and source digest pinned by L02 recomputes from disk")
    check("l01_predecessor_handoff_verified",
          l01_hashes_match and all(bool(c.get("ok")) for c in l01.get("checks") or []),
          {"inputs_recompute": l01_hashes_match,
           "checks": len(l01.get("checks") or [])})
    check("k_matches_generator_rebuild", k == 4 and form_ids == recorded_ids,
          {"k": k, "form_ids": form_ids})
    check("growth_checkpoints_show_saturation",
          (census["census"]["discovery"].get("growth_checkpoints")
           == [[32, 4], [64, 4], [128, 4], [256, 4], [512, 4]]),
          census["census"]["discovery"].get("growth_checkpoints"))
    check("sign_flip_floor_derived_from_k",
          floor["denominator"] == 2 ** k and floor["exact_fraction"] == f"2/{2 ** k}"
          and floor["value"] == "0.125" and floor["reduced_fraction"] == "1/8",
          floor)
    check("floor_exceeds_unadjusted_alpha",
          Fraction(floor["value"]) > ALPHA_EXACT and floor["value"] == "0.125",
          {"floor": floor["value"], "alpha": ALPHA})
    check("confirmatory_minimum_is_six_forms",
          CONFIRMATORY_MIN_K == _min_k_for(ALPHA_EXACT) == 6 and k < CONFIRMATORY_MIN_K,
          {"min_k": CONFIRMATORY_MIN_K, "k": k})
    check("multiplicity_only_demands_more_forms",
          all(row["min_k_for_attainable_floor"] >= CONFIRMATORY_MIN_K
              for row in multiplicity)
          and not any(row["k4_floor_eligible"] for row in multiplicity),
          multiplicity)
    check("classification_is_descriptive_discovery",
          classification["decision"] == "descriptive_discovery"
          and "no_go" not in classification["decision"]
          and "confirmatory_design" not in classification["decision"],
          classification["decision"])
    check("structural_gate_passes", structural["passed"], structural["checks"])
    check("capacity_gate_passes", capacity["passed"], capacity["checks"])
    check("decision_rule_is_ordered_and_traceable",
          len(classification["decision_rule"]) == 4
          and classification["decision_trace"][-1]["result"] in
          ("not reached", "k >= 6 -> potentially_confirmatory_design"),
          classification["decision_trace"])
    check("estimand_preserved",
          estimand["h0"] == "Delta = 0" and estimand["h1"] == "Delta < 0"
          and estimand["estimand"] == "equal-weight form mean of real-minus-placebo entropy"
          and "two-sided" in estimand["primary_test"]
          and estimand["guards_never_filter_the_estimate"] is True,
          estimand["statement"])
    check("exchangeability_limit_stated",
          exchangeability["hash_distinct_not_independent"] is True
          and exchangeability["shared_template_hash"]
          and "assumption-dependent" in exchangeability["consequence"]
          and "assumption-free" in exchangeability["consequence"],
          exchangeability["consequence"])
    check("seeds_not_counted_as_forms",
          (census["form_capacity"].get("distinct_seeds_are_not_form_units")) is True
          and screen["outcome_blind"] is True
          and floor["k"] == k,
          {"k": k, "fixed_n": screen["fixed_n"],
           "instances_per_form": screen["instances_per_form"]})
    constraint_text = " ".join(" ".join(constraint.values()) for constraint in constraints)
    check("no_effect_size_prior_from_other_families",
          "planning-low" in constraint_text and "hypothesis-low" in constraint_text
          and "effect-size prior" in constraint_text
          and any("effect-size prior" in claim for claim in _non_claims()),
          [claim for claim in _non_claims() if "prior" in claim])
    check("fixed_n_screen_outcome_blind",
          screen["outcome_blind"] is True and screen["consulted_outcomes"] == []
          and "ascending seed order" in screen["selection_rule"],
          {"selection_rule": screen["selection_rule"],
           "consulted_outcomes": screen["consulted_outcomes"]})
    check("manifest_matches_generator",
          all(entry["prompt_form_id"] == rep.pre_read_form_id(
                  rep.instance_for(FAMILY, entry["seed"]))
              and entry["instance_id"] == rep.instance_for(
                  FAMILY, entry["seed"]).instance_id
              for entry in screen["manifest"]),
          {"entries": len(screen["manifest"]), "manifest_hash": screen["manifest_hash"]})
    check("manifest_four_per_form_and_fixed_n",
          screen["fixed_n"] == 4 * len(form_ids) == 16
          and all(len(ids) == screen["instances_per_form"]
                  for ids in screen["form_membership"].values()),
          {"fixed_n": screen["fixed_n"],
           "per_form": {form: len(ids) for form, ids in
                        screen["form_membership"].items()}})
    check("manifest_inside_discovery_window_and_disjoint_from_prior",
          all(DISCOVERY_WINDOW_SPAN[0] <= seed <= DISCOVERY_WINDOW_SPAN[1]
              for seed in selected_seeds)
          and forbidden_hits == []
          and overlap.get("selected_seeds_overlapping_prior") == []
          and overlap.get("selected_ids_overlapping_prior") == [],
          {"forbidden_hits": forbidden_hits,
           "prior_overlaps": overlap.get("selected_seeds_overlapping_prior"),
           "prior_legal_instance_ids": len(prior_legal_ids)})
    check("closure_probe_window_never_selectable",
          screen["closure_probe_window_selectable"] is False
          and not any(CLOSURE_PROBE_WINDOW_SPAN[0] <= seed <= CLOSURE_PROBE_WINDOW_SPAN[1]
                      for seed in selected_seeds),
          screen["closure_probe_window"])
    check("held_out_window_not_chosen_here",
          screen["held_out_window"]["fixed_here"] is False
          and ((census.get("windows") or {}).get("held_out_window") or {}).get(
              "fixed_by_l02") is False,
          screen["held_out_window"]["statement"])
    check("scenario_selection_is_deterministic",
          scenarios["selected_seeds_per_form"] == 4
          and [s["seeds_per_form"] for s in scenarios["scenarios"]
               if s["feasible"]] == [4]
          and scenarios["scenarios"][0]["infeasible_reasons"]
          and scenarios["scenarios"][2]["infeasible_reasons"],
          {"rule": scenarios["selection_rule"],
           "feasible": [s["seeds_per_form"] for s in scenarios["scenarios"] if s["feasible"]]})
    check("scenario_costs_recompute_from_rate_card",
          all(s["collection"]["worst_case_cost_usd"] == round(
                  s["fixed_n"] * WRITER_CALLS_PER_INSTANCE * RETRY_MULTIPLIER
                  * _cost_model()["ling_worst_physical_call_usd"]
                  + s["fixed_n"] * RECEIVER_CALLS_PER_INSTANCE * RETRY_MULTIPLIER
                  * _cost_model()["jev_worst_physical_call_usd"], 12)
              and s["exploratory_replay"]["worst_case_cost_usd"] == round(
                  s["fixed_n"] * REPLAY_BRANCHES * RETRY_MULTIPLIER
                  * _cost_model()["jev_worst_physical_call_usd"], 12)
              for s in scenarios["scenarios"]),
          {str(s["seeds_per_form"]): s["program"]["worst_case_cost_usd"]
           for s in scenarios["scenarios"]})
    check("stop_conditions_registered",
          any("cost cap" in stop for stop in stops)
          and any("fixed schedule" in stop for stop in stops)
          and any("truncated_output" in stop for stop in stops)
          and any("two consecutive terminal provider failures" in stop for stop in stops),
          {"stops": len(stops)})
    check("coverage_rule_prospective_and_freezes_missingness",
          coverage["prospective"] is True and coverage["frozen_before_collection"] is True
          and coverage["min_complete_per_form"] == 1
          and coverage["no_imputation"] is True
          and coverage["no_seed_replacement"] is True
          and coverage["no_form_removal_after_outcomes"] is True
          and coverage["no_replenishment_from_spare_capacity"] is True,
          coverage["permissible_within_form_missingness"])
    check("proposed_output_paths_fresh_and_absent",
          all(proposed_absent.values())
          and all(path.startswith("runs/next-phase/legal/") for path in PROPOSED_PATHS.values()),
          PROPOSED_PATHS)
    check("constraints_cover_no_calls_and_l07_gate",
          any("no provider call" in c["constraint"] for c in constraints)
          and any("L07" in c["basis"] for c in constraints)
          and any("#227" in c["basis"] for c in constraints)
          and "byte-identically" in constraint_text
          and "frozen historical queue" in constraint_text
          and "redesign the generator" in constraint_text,
          [c["constraint"] for c in constraints])
    check("handoff_to_l04_records_227_predecessor",
          handoff["to"] == "L04" and handoff["issue"] == 222
          and handoff["handoff_to_227"]["grants_authorization"] is False
          and any("#227" in condition for condition in handoff["conditions"])
          and any("L07" in condition for condition in handoff["conditions"])
          and any("predecessor" in condition for condition in handoff["conditions"]),
          {"conditions": len(handoff["conditions"]),
           "handoff_to_227_grants_authorization":
               handoff["handoff_to_227"]["grants_authorization"]})
    check("frozen_200_207_and_215_byte_identical_after_build", before == after,
          "every frozen and source digest recomputed at the end equals the digest at start")
    check("zero_network_events_under_audit_hook", not events,
          {"events": list(events), "provider_calls": 0})
    check("no_authorization_recorded",
          "no provider call" in authorizes_text and "no live run" in authorizes_text
          and "authorization inference" in authorizes_text,
          authorizes_text)
    check("doc_pins_recomputed_input_hashes",
          bool(doc_text) and str(DESIGN_PATH) in doc_text and DESIGN_VERSION in doc_text
          and all(entry["sha256"] in doc_text for entry in frozen_inputs),
          {"doc": str(DOC_PATH),
           "digests": {entry["path"]: entry["sha256"] for entry in frozen_inputs}})
    check("output_path_is_fresh_and_scoped",
          str(DESIGN_PATH).startswith("runs/next-phase/legal/")
          and str(DESIGN_PATH) not in l02.HYPOTHESIS_OUTPUT_PATHS
          and str(DESIGN_PATH) != str(L02_CENSUS_PATH),
          {"design_path": str(DESIGN_PATH)})

    document: dict[str, Any] = {
        "design_version": DESIGN_VERSION,
        "issue": "#221",
        "parent_issue": "#218",
        "root_issue": "#159",
        "milestone": "L03",
        "predecessor_issue": "#220",
        "successor_issue": "#222",
        "family": FAMILY,
        "complexity": COMPLEXITY,
        "regime": REGIME,
        "stage": ("offline design classification, attainability derivation and outcome-blind "
                  "discovery screen"),
        "protocol": str(PROTOCOL_PATH),
        "task_sequence": str(SEQUENCE_PATH),
        "program_amendment": str(PROGRAM_PATH),
        "offline_only": True,
        "authorizes": authorizes_text,
        "provider_calls": 0,
        "input_evidence": {"inputs": frozen_inputs, "sources": source_inputs},
        "predecessor_evidence": {
            "path": str(L02_CENSUS_PATH),
            "artifact": census.get("census_version"),
            "content_hash": census.get("content_hash"),
            "content_hash_recomputes": l02_content_ok,
            "checks": len(l02_checks),
            "all_checks_pass": l02_ok,
            "network_events": (census.get("network_audit") or {}).get("events"),
            "recorded_hashes_match_current_bytes": l02_hashes_match,
            "handoff_deliverable": (census.get("handoff") or {}).get("deliverable"),
            "l01_recorded_hashes_match_current_bytes": l01_hashes_match,
        },
        "derivation": {
            "k_observed": k,
            "k_source": ("L02 form_capacity.k and the recorded form set, rebuilt here from "
                         "the generator over the pinned discovery window; the observed "
                         "growth checkpoints saturate at 4 forms by 32 seeds"),
            "form_ids": form_ids,
            "form_set_hash": _digest(form_ids),
            "seeds_are_not_forms": (
                "distinct seeds within a form improve measurement of emission, coverage, "
                "variability and guards but never add form units; the experimental unit is "
                "the prompt form"),
            "sign_flip_floor": floor,
            "attainable_floor_grid": bands,
            "alpha": ALPHA,
            "unadjusted_requirement": (
                "at alpha .05 a potentially confirmatory design needs k >= 6 (floor "
                "0.03125 <= .05); six forms are necessary, not sufficient for power or "
                "multiplicity-adjusted rejection"),
            "declared_multiplicity": {
                "rule": "Holm step-down at .05 is the default for any future registered "
                        "family set; a single registration is legitimate but repeated "
                        "singletons do not give program-wide .05 control",
                "family_set_frozen_before_outcomes": True,
                "grid": multiplicity,
                "consequence": (
                    "legal:low at k = 4 has a best-case floor of 0.125, above every first-"
                    "step threshold in the grid, so no declared multiplicity rule can make "
                    "this generator version confirmatory; adjusted multiplicity can only "
                    "demand more forms"),
            },
            "exchangeability_limits": exchangeability,
            "estimand": estimand,
            "priors": {
                "planning_low_effect_size_prior_used": False,
                "hypothesis_low_effect_size_prior_used": False,
                "statement": ("planning-low's conditional confirmatory result and "
                              "hypothesis-low's inconclusive stop supply no legal-family "
                              "effect size, power or prior; the motivating paper supplies "
                              "none either"),
            },
        },
        "classification": classification,
        "constraints": constraints,
        "discovery_screen": screen,
        "coverage_rule": coverage,
        "request_cost_scenarios": scenarios,
        "stop_conditions": {
            "stops": stops,
            "semantics": ("fixed schedule with no outcome-based stopping or seed "
                          "replacement; the cap closest to the next call wins; any stop "
                          "keeps the whole fixed manifest as an immutable journal including "
                          "failure and not-attempted rows and routes to a terminal report; "
                          "resuming requires a new registration and fresh paths"),
        },
        "reserved_paths": {
            "proposed": PROPOSED_PATHS,
            "proposed_not_created": True,
            "absent_at_build": proposed_absent,
            "lifecycle": ("fresh paths only: no resume, no append, no overwrite, no path "
                          "overrides; this artifact creates none of them"),
        },
        "non_claims": _non_claims(),
        "limitations": [
            ("Offline only: no provider call, probe, live journal or network event was made "
             "or authorized by this task."),
            ("Frozen #200 and terminal #207/#215 files are read-only inputs here and were "
             "preserved byte-identically."),
            ("The classification binds the audited four-form legal:low generator version; a "
             "redesigned generator is a new protocol boundary, not extra seeds."),
            ("Closure of the form space does not establish statistical independence: the "
             "four forms share one template, so sign-flip inference stays "
             "assumption-dependent and descriptive."),
            ("Cost figures are planning arithmetic from a carried rate card; no legal route, "
             "model, budget or cap is registered or authorized by this artifact."),
            ("Capacity, inventory exceptions and prior-overlap facts are cited from the "
             "hash-pinned L02 census; its 20 inaccessible locations remain open audit "
             "exceptions, never empty sets."),
            ("A failed or stopped predecessor never authorizes a successor: nothing here "
             "approves legal:low collection, a route, a budget or any provider call."),
        ],
        "checks": checks,
        "network_audit": {"hook": "sys.addaudithook(" + ", ".join(NETWORK_EVENT_PREFIXES) + ")",
                          "events": len(events), "event_names": list(events),
                          "provider_calls": 0},
        "deterministic_rebuild": {
            "builder": "src/apart_incident_response/jev_legal_p03_design.py",
            "rebuild_command": "python -m apart_incident_response.jev_legal_p03_design "
                               "--repo-root .",
            "byte_reproducible": True,
            "fail_closed_on_drift": True,
        },
        "handoff": handoff,
    }
    document["content_hash"] = _content_hash(document)
    if events:
        raise DesignError(f"network events during offline build: {events}")
    return document


def write_design(document: Mapping[str, Any], *, repo_root: Path | str) -> Path:
    target = Path(repo_root) / DESIGN_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        handle.write(_render(document))
    return target


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

def verify_design(document: Mapping[str, Any], *, repo_root: Path | str) -> dict[str, Any]:
    """Fail-closed verification: rebuild, compare byte-for-byte, run checks."""

    root = Path(repo_root)
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

    check("design_version", document.get("design_version") == DESIGN_VERSION,
          document.get("design_version"))
    check("content_hash_matches",
          document.get("content_hash") == _content_hash(document),
          document.get("content_hash"))
    try:
        rebuilt = build_design(root)
        check("design_rebuilds_byte_for_byte", rebuilt == document, None)
        check("design_file_is_byte_reproducible",
              (root / DESIGN_PATH).read_text(encoding="utf-8") == _render(rebuilt), None)
        failed_build = [entry["check"] for entry in rebuilt["checks"] if not entry["ok"]]
        check("rebuilt_design_checks_all_pass", not failed_build, failed_build)
        for entry in rebuilt["checks"]:
            checks.append(dict(entry))
            if not entry["ok"]:
                errors.append(f"{entry['check']}: {entry['detail']}")
    except (DesignError, OSError, json.JSONDecodeError) as exc:
        check("design_rebuilds_byte_for_byte", False, f"{type(exc).__name__}: {exc}")

    failed_artifact = [entry["check"] for entry in document.get("checks") or []
                       if not entry.get("ok")]
    check("artifact_checks_all_pass", not failed_artifact, failed_artifact)
    network = document.get("network_audit") or {}
    check("artifact_zero_provider_calls",
          network.get("events") == 0 and network.get("provider_calls") == 0
          and document.get("provider_calls") == 0, network)
    classification = document.get("classification") or {}
    check("classification_is_descriptive_discovery",
          classification.get("decision") == "descriptive_discovery", classification.get(
              "decision"))
    check("k_and_floor_recorded",
          (document.get("derivation") or {}).get("k_observed") == 4
          and ((document.get("derivation") or {}).get("sign_flip_floor") or {}).get("value")
          == "0.125", None)
    handoff = document.get("handoff") or {}
    check("handoff_to_l04", handoff.get("to") == "L04" and handoff.get("issue") == 222,
          handoff)
    check("handoff_records_227_predecessor",
          any("#227" in condition for condition in handoff.get("conditions") or [])
          and (handoff.get("handoff_to_227") or {}).get("grants_authorization") is False,
          handoff.get("handoff_to_227"))
    check("offline_scope_recorded",
          document.get("offline_only") is True
          and "no provider call" in str(document.get("authorizes")),
          document.get("authorizes"))

    return {"mode": f"{DESIGN_VERSION}-verification", "ok": not errors,
            "errors": errors, "failed": [entry["check"] for entry in checks if not entry["ok"]],
            "checks": checks, "content_hash": document.get("content_hash"),
            "provider_calls": 0}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="L03 legal design classification (offline; deterministic rebuild; "
                    "zero provider calls)")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--build", action="store_true",
                        help="write the design artifact to its fresh path (never overwrites)")
    args = parser.parse_args(argv)
    root = (Path(args.repo_root) if args.repo_root is not None
            else Path(__file__).resolve().parents[2])

    if args.build:
        document = build_design(root)
        write_design(document, repo_root=root)
        print(json.dumps({"mode": DESIGN_VERSION, "status": "built", "path": str(DESIGN_PATH),
                          "content_hash": document["content_hash"],
                          "classification": document["classification"]["decision"],
                          "checks_run": len(document["checks"]),
                          "failed": [entry["check"] for entry in document["checks"]
                                     if not entry["ok"]],
                          "provider_calls": 0}, indent=2, sort_keys=True))
        return 0

    path = root / DESIGN_PATH
    if not path.is_file():
        print(json.dumps({"mode": DESIGN_VERSION, "status": "missing", "path": str(DESIGN_PATH),
                          "provider_calls": 0}, indent=2, sort_keys=True))
        return 2
    verification = verify_design(load_json(path), repo_root=root)
    print(json.dumps(verification, indent=2, sort_keys=True, allow_nan=False))
    return 0 if verification["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DESIGN_VERSION", "DESIGN_PATH", "DOC_PATH", "PROTOCOL_PATH", "SEQUENCE_PATH",
    "PROGRAM_PATH", "FAMILY", "COMPLEXITY", "REGIME", "INSTANCES_PER_FORM", "WINDOW_SIZE",
    "DISCOVERY_WINDOW_SPAN", "CLOSURE_PROBE_WINDOW_SPAN", "RESERVED_HYPOTHESIS_SPAN",
    "L02_CENSUS_CONTENT_HASH", "ALPHA", "CONFIRMATORY_MIN_K", "MULTIPLICITY_FAMILY_COUNTS",
    "RETRY_MULTIPLIER", "WRITER_CALLS_PER_INSTANCE", "RECEIVER_CALLS_PER_INSTANCE",
    "REPLAY_BRANCHES", "COST_CEILING_COLLECTION_USD", "COST_CEILING_REPLAY_USD",
    "COST_CEILING_PROGRAM_USD", "SCENARIO_SEEDS_PER_FORM", "DISCOVERY_DIR", "PROPOSED_PATHS",
    "FROZEN_INPUTS", "SOURCE_INPUTS", "NETWORK_EVENT_PREFIXES",
    "DesignError", "sha256_of", "load_json", "network_events", "_sign_flip_floor",
    "_min_k_for", "_scan_forms", "_cost_model", "_scenario", "build_design", "write_design",
    "verify_design", "main",
]
