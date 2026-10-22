"""L04 (#222): offline legal:low fresh discovery registration, draft pending review.

Chainlink **#222** under **#218** under **#159**. Predecessor chain consumed as
hash-pinned read-only inputs: L01 (#219), L02 (#220), L03 (#221) and the
approved offline cross-family capacity audit #227 (`#221 -> #227 -> #222`).

The L03 decision is `descriptive_discovery` — no-go is off the table — so this
module freezes the fresh legal discovery registration. Everything is derived
offline from files already on disk plus the deterministic six-family
generator; the module makes **no provider call, no probe, and no network
request of any kind**: a process-wide audit hook observes every network event
and the build fails closed if one occurs.

What the registration freezes (all as new legal-family registration fields):

1. the fixed-N discovery manifest carried from the L03 screen: first
   ``INSTANCES_PER_FORM`` seeds per form in ascending seed order inside the L02
   discovery window 88000-88511, k = 4 forms, fixed N = 16, outcome-blind;
2. the original L4X treatment bytes (mode, turns, agents, temperature,
   provider seed, grammar, evolving visible-message state, 1024 max tokens)
   bound into a treatment hash over the legal manifest;
3. the writer output policy: the registered ``max_tokens`` and the truncation
   policy justified by the L01 (#219) diagnosis of the hypothesis:low HTTP-200
   output-cap stop;
4. the legal family's own first-time route registration (paid OpenRouter Ling
   writer, Typesafe Jev receiver, normalization policy) independently chosen
   and costed from the carried rate card;
5. pacing and retry-inclusive request caps, hard dollar ceilings, terminal
   stop conditions and next-call reservations;
6. ownership/read-after-write exposure checks, information rules and the
   prospective coverage rule;
7. unique, fresh, currently-absent output paths with an explicit
   no-resume / no-append / no-overwrite / no-replacement lifecycle,
   retaining every silence and failure as journal rows.

Nothing authorizes a call: the artifact stays ``draft_pending_review`` with
authorization pending, and only the separate, scope-bound L07 gate (#225) can
supply the explicit user authorization. The stopped hypothesis:low
registration and its authorization record are pinned here solely as
non-reuse controls: no seed window, manifest, authorization, or outcome
carries forward from them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_choice_v2 as jc2
from apart_incident_response import jev_cross_family_audit as audit227
from apart_incident_response import jev_coverage_manifest_preregistration_v7 as prv7
from apart_incident_response import jev_legal_form_census as l02
from apart_incident_response import jev_legal_p03_design as l03
from apart_incident_response import jev_ling_writer_v3 as w3
from apart_incident_response import jev_ling_writer_v5 as w5
from apart_incident_response import jev_p04_design_classification as hyp_p04
from apart_incident_response import jev_replay_preregistration as pr
from apart_incident_response import jev_replay_preregistration_v2 as prv2
from apart_incident_response import jev_replay_preregistration_v4 as prv4
from apart_incident_response import jev_replication_preregistration as rep
from apart_incident_response import jev_writer_ladder_v5 as ladder
from apart_incident_response import task_families as tf

REGISTRATION_VERSION = "jev-legal-p04-discovery-registration-v1"
REGISTRATION_PATH = Path("runs/next-phase/legal/jev-legal-p04-discovery-registration-v1.json")
DOC_PATH = Path("docs/jev-legal-p04-registration.md")
DRAFT_STATUS = "draft_pending_review"

FAMILY = l03.FAMILY
COMPLEXITY = l03.COMPLEXITY
REGIME = l03.REGIME

PROTOCOL_PATH = l03.PROTOCOL_PATH
SEQUENCE_PATH = l03.SEQUENCE_PATH
PROGRAM_PATH = l03.PROGRAM_PATH
L01_EVIDENCE_PATH = l03.L01_EVIDENCE_PATH
L01_DOC_PATH = l03.L01_DOC_PATH
L02_CENSUS_PATH = l03.L02_CENSUS_PATH
L02_DOC_PATH = l03.L02_DOC_PATH
L03_DESIGN_PATH = l03.DESIGN_PATH
L03_DOC_PATH = l03.DOC_PATH
AUDIT_200_PATH = l03.AUDIT_200_PATH
JOURNAL_207_PATH = l03.JOURNAL_207_PATH
REPORT_207_PATH = l03.REPORT_207_PATH
TERMINAL_215_PATH = l03.TERMINAL_215_PATH
AUDIT_227_PATH = audit227.ARTIFACT_PATH
AUDIT_227_DOC_PATH = Path("docs/jev-cross-family-capacity-audit-v1.md")

#: The stopped hypothesis registration and its authorization record: pinned
#: byte-for-byte as non-reuse controls only. No field, authorization, seed
#: window or outcome carries forward from them into this family.
STOPPED_REGISTRATION_PATH = hyp_p04.REGISTRATION_PATH
STOPPED_AUTHORIZATION_PATH = Path("runs/next-phase/jev-discovery-authorization-record-v1.json")

DISCOVERY_WINDOW = l03.DISCOVERY_WINDOW_SPAN
CLOSURE_PROBE_WINDOW = l03.CLOSURE_PROBE_WINDOW_SPAN
INSTANCES_PER_FORM = l03.INSTANCES_PER_FORM
BLOCK_N = INSTANCES_PER_FORM * 4

#: Self-recorded content hashes that must recompute from bytes (never accepted
#: from prose): the L02 census, the L03 design and the #227 audit artifact.
L02_CENSUS_CONTENT_HASH = "b01aa7de17cb21d18b7dd83a12764da7ff265a18b7089f2c2be7eaaf6b72b775"
L03_DESIGN_CONTENT_HASH = "adf52cb7b7d62e532acc0b8f26c000582e4a291767f737558f016fdf9eafed06"
AUDIT_227_CONTENT_HASH = "e71252a607f35cde67dbaf5e66f3abbc8d57c3064cbb88d79a90ff0e31175684"
AUDIT_227_AUTHORIZATION = "none; no live collection or replay permitted"

#: Non-reuse controls recomputed from their bytes: the stopped hypothesis
#: registration content hash and its scope digest.
STOPPED_REGISTRATION_HASH = "6fa6149770b620cd3a026a6415f8e4d97e800e8af5237794de7b29fca6dacfac"
STOPPED_SCOPE_DIGEST = "938da9116805967253417c53709cd85d56d1913ac0142032d0d4732f50c04061"

#: The separate, scope-bound live-authorization gate that must run after
#: registration review and lock; the legal loop itself halts before it.
L07_GATE_DOC = Path("docs/jev-discovery-authorization-gate.md")
L07_GATE_ISSUE = "#225"

#: Cost model and ceilings: the rates are the chain's frozen card (carried
#: through #200/#205/L01/L03 only after recomputation); the legal-family
#: dollar ceilings become *registered hard ceilings* here.
LING_PROMPT_USD_PER_MTOK = rep.LING_PROMPT_USD_PER_MTOK
LING_COMPLETION_USD_PER_MTOK = rep.LING_COMPLETION_USD_PER_MTOK
LING_INPUT_TOKEN_CEILING = rep.LING_INPUT_TOKEN_CEILING
LING_OUTPUT_TOKEN_CEILING = rep.LING_OUTPUT_TOKEN_CEILING
JEV_INPUT_USD_PER_MTOK = rep.JEV_INPUT_USD_PER_MTOK
JEV_INPUT_TOKEN_CEILING = rep.JEV_INPUT_TOKEN_CEILING
RETRY_MULTIPLIER = l03.RETRY_MULTIPLIER
WRITER_CALLS_PER_INSTANCE = l03.WRITER_CALLS_PER_INSTANCE
RECEIVER_CALLS_PER_INSTANCE = l03.RECEIVER_CALLS_PER_INSTANCE
REPLAY_BRANCHES = l03.REPLAY_BRANCHES
COST_CEILING_COLLECTION_USD = l03.COST_CEILING_COLLECTION_USD
COST_CEILING_REPLAY_USD = l03.COST_CEILING_REPLAY_USD
COST_CEILING_PROGRAM_USD = l03.COST_CEILING_PROGRAM_USD

#: Fresh, unique, currently absent live output paths (proposed by L03, frozen
#: here as registered paths; nothing in this module creates them).
DISCOVERY_ID = l03.DISCOVERY_ID
DISCOVERY_DIR = l03.DISCOVERY_DIR
LIVE_PATHS: dict[str, str] = dict(l03.PROPOSED_PATHS)
PATHS: dict[str, str] = {
    "registration": str(REGISTRATION_PATH),
    "discovery_journal": LIVE_PATHS["discovery_journal"],
    "discovery_report": LIVE_PATHS["discovery_report"],
    "exploratory_replay_journal": LIVE_PATHS["exploratory_replay_journal"],
    "exploratory_replay_report": LIVE_PATHS["exploratory_replay_report"],
}

#: The registered manifest must be exactly the L03 screen, seed for seed.
L03_SCREEN_MANIFEST_HASH = "1eeda0eacc2d891e8117e2816c7a7bf2c65c3962c8e1fa102acdc4766deefb26"

#: Offline launcher/worker route fixed by the program amendment: an explicit
#: free OpenCode coding-model route for worker and reviewer sessions. This is
#: the coding-agent route only; it is not an experimental provider, it uses no
#: paid coding model, and this task must not migrate the toolchain to
#: OpenCode Zen/Go (whose transports are not substitutable for the registered
#: experimental routes either).
OFFLINE_WORKER_ROUTE = {
    "worker_model": "opencode/mimo-v2.6-flash-free",
    "reviewer_model": "opencode/mimo-v2.6-flash-free",
    "source": "docs/jev-cross-family-entropy-program-v1.md launcher paragraph",
    "kind": "coding-agent route for offline worker/reviewer sessions only",
    "not_an_experimental_provider": True,
    "no_silent_migration": ("this task does not migrate to OpenCode Zen or OpenCode Go; "
                            "OpenCode Go has no interchangeable Ling route in the current "
                            "registration"),
    "no_paid_coding_model": True,
}

NETWORK_EVENT_PREFIXES = l03.NETWORK_EVENT_PREFIXES

#: Frozen inputs recomputed from disk on every build; full digests are pinned,
#: so a mismatch on any single byte fails the build closed. The final two
#: entries are non-reuse controls and are never used as design inputs.
FROZEN_INPUTS: tuple[dict[str, Any], ...] = (
    {"path": str(PROTOCOL_PATH), "role": "research protocol (scientific contract)",
     "expected_sha256": "501e21b6dea760371b0bf368046d8bacd203f6b92f0af754a7955d1f738677f7"},
    {"path": str(SEQUENCE_PATH), "role": "legal family task sequence (#218)",
     "expected_sha256": "884b0ed4329cc47888e797478f8f00b57f7f5c9d679998d154f5a789397d0394"},
    {"path": str(PROGRAM_PATH), "role": "cross-family program amendment (2026-09-29)",
     "expected_sha256": "d9acace24a0cdbfc9a41e331b1fd422f07f22e3fc01480e6408af78d9de4be05"},
    {"path": str(AUDIT_200_PATH), "role": "#200 frozen form-capacity audit",
     "expected_sha256": "cb529cd61e0e662bfa19fc4998e89fa59a0bf0d63e14f77498035466d6bce89d"},
    {"path": str(JOURNAL_207_PATH), "role": "#207 terminal P06 discovery journal",
     "expected_sha256": "4e8de096f2c30a6a36a94a0f79e5f450c2e196123e3eafe1c310a92c4f334c83"},
    {"path": str(REPORT_207_PATH), "role": "#207 terminal P06 collection report",
     "expected_sha256": "3086ceac558ff922bd083db3795f5f1aa5c7127813daba8bfd71ae1fbef09d3c"},
    {"path": str(TERMINAL_215_PATH), "role": "#215 terminal family report",
     "expected_sha256": "89ef2aafb5e28f12d0db707499c583d89cdcc490d105c23c3c56b39e11818d0b"},
    {"path": str(L01_EVIDENCE_PATH), "role": "L01 evidence index (#219)",
     "expected_sha256": "b2d0726619f5a18ce1ed5a54c5197d51709b1e0473b58ee129c74592b7b707e3"},
    {"path": str(L01_DOC_PATH), "role": "L01 baseline narrative (#219)",
     "expected_sha256": "8926f48d85338163fae0f9434f63c62b380f6402580bb57cd1d35b25d0471870"},
    {"path": str(L02_CENSUS_PATH), "role": "L02 form census (#220)",
     "expected_sha256": "4bffa5cda2433a81efb41025f42fdd82c585c41798ff2c55e9d853aa45681d24"},
    {"path": str(L02_DOC_PATH), "role": "L02 capacity narrative (#220)",
     "expected_sha256": "25fac868d502b05ede479fa7e68161f8f4fd4db33267a0f01d710f2d0adec2fa"},
    {"path": str(L03_DESIGN_PATH), "role": "L03 design decision (#221), predecessor handoff",
     "expected_sha256": "688bc7875ff7b81bb70d60076e137b0274559b484d597f6f643ae2fb48c827ab"},
    {"path": str(L03_DOC_PATH), "role": "L03 design narrative (#221)",
     "expected_sha256": "24bd6d7e8cec205bf5b5cee96f98f09afad17c85a1e825c012b536e3a2716f79"},
    {"path": str(AUDIT_227_PATH),
     "role": "#227 approved cross-family capacity audit (machine-readable)",
     "expected_sha256": "13c526761c1f10e71382a5c5d142e47585539bad66238d3a6bfd49646b17271e"},
    {"path": str(AUDIT_227_DOC_PATH), "role": "#227 audit narrative",
     "expected_sha256": "ca8a3fefac6221b862245ed2a8bac9b43b5411dc9447e00016375192ca16c75f"},
    {"path": str(STOPPED_REGISTRATION_PATH),
     "role": "stopped hypothesis registration - non-reuse control, never inherited",
     "expected_sha256": "78f7cd03c3afc12c94c3ba09839e4ac6ba667a3f68b96871571b274ae7d3ab11"},
    {"path": str(STOPPED_AUTHORIZATION_PATH),
     "role": "stopped hypothesis authorization record - non-reuse control, never inherited",
     "expected_sha256": "77962311dc723b7bf0eab0bda042078ec5d8a903120dd37b023c7b93d2e6d8eb"},
)

#: Generator and hashing sources pinned so the rebuild is a build of *these*
#: bytes: every module this builder computes through, except itself.
SOURCE_INPUTS: tuple[str, ...] = l03.SOURCE_INPUTS + (
    "src/apart_incident_response/jev_legal_p03_design.py",
    "src/apart_incident_response/jev_cross_family_audit.py",
    "src/apart_incident_response/jev_p04_design_classification.py",
)


class RegistrationError(ValueError):
    """Fail-closed registration build or verification violation."""


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


def _content_hash(document: Mapping[str, Any], *, hash_key: str) -> str:
    """Canonical content hash of an artifact with a self-recorded hash key."""

    payload = json.dumps({key: value for key, value in document.items()
                          if key != hash_key}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _render(document: Mapping[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _hashed_inputs(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    frozen = l02.hash_inputs(root, [
        {"path": entry["path"], "role": entry["role"],
         "expected_sha256_prefix": entry["expected_sha256"]}
        for entry in FROZEN_INPUTS])
    sources = l02.hash_inputs(root, [
        {"path": path, "role": "generator/hashing source", "expected_sha256_prefix": None}
        for path in SOURCE_INPUTS])
    return frozen, sources


def _reserved_seed_spans() -> tuple[tuple[int, int], ...]:
    """Documented prior seed ranges plus the reserved hypothesis windows."""

    documented = tuple((int(low), int(high)) for low, high in rep.PRIOR_SEED_RANGES)
    return documented + RESERVED_HYPOTHESIS_SPANS


#: Reserved hypothesis span (frozen by L02): 85000-87511, never reused.
RESERVED_HYPOTHESIS_SPANS: tuple[tuple[int, int], ...] = (
    (85000, 85511), (86000, 86511), (87000, 87511))


# --------------------------------------------------------------------------
# the L4X treatment and the legal treatment hash (treatment bytes)
# --------------------------------------------------------------------------

def legal_treatment() -> dict[str, Any]:
    """Original L4X communication treatment, registered for legal:low."""

    return {
        "mode": "exact-original-comm-bridge",
        "rung": "L4X",
        "family": FAMILY,
        "complexity": COMPLEXITY,
        "regime": REGIME,
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
        "writer_prompt": rep.prompt_binding(),
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
    }


def legal_manifest_treatment_hash(manifest: Sequence[Mapping[str, Any]]) -> str:
    """Treatment bytes of the legal manifest: one digest over all 16 rows."""

    rows = []
    for entry in sorted(manifest, key=lambda row: int(row["seed"])):
        instance = rep.instance_for(FAMILY, int(entry["seed"]))
        rows.append({"instance_id": instance.instance_id, "seed": instance.seed,
                     "iso_form_id": entry["prompt_form_id"],
                     "option_ids": sorted(instance.solutions),
                     "private_clues": {"A": list(instance.private_clues.get("A", ())),
                                       "B": list(instance.private_clues.get("B", ()))},
                     "joint_solutions": sorted(instance.joint_solutions)})
    return _digest(rows)


def information_geometry_hash(census_document: Mapping[str, Any]) -> str:
    """Digest of the per-form authoritative information geometry (L02 census)."""

    per_form = ((census_document.get("form_records") or {}).get("per_form")) or {}
    rows = [
        {"form_id": form,
         "option_ids": record["option_ids"],
         "option_count": record["option_count"],
         "pre_read_request_body_hash": record["pre_read_request_body_hash"],
         "pre_read_state_hash": record["pre_read_state_hash"],
         "branch_request_hashes": record["branch_request_hashes"],
         "branch_state_hashes": record["branch_state_hashes"],
         "a_finalizer_peer_need": record["a_finalizer_peer_need"],
         "authoritative_b_owned_informative_claim":
             record["authoritative_b_owned_informative_claim"],
         "placebo_claim": record["placebo_claim"],
         "form_cell": record["form_cell"]}
        for form, record in sorted(per_form.items())]
    return _digest(rows)


def legal_treatment_hash(treatment: Mapping[str, Any], manifest_treatment: str,
                         geometry: str) -> str:
    """Treatment hash binding L4X bytes, manifest, geometry and route pins."""

    writer_prompt = treatment["writer_prompt"]
    transport = treatment["writer_transport"]
    return _digest({
        "family": FAMILY, "complexity": COMPLEXITY, "regime": REGIME,
        "mode": treatment["mode"], "rung": treatment["rung"],
        "turns": treatment["turns"], "agents": treatment["agents"],
        "primary_direction": treatment["primary_direction"],
        "final_receiver": treatment["final_receiver"],
        "exposure_id": treatment["exposure_id"],
        "visibility": treatment["visibility"], "ownership": treatment["ownership"],
        "board_evidence": treatment["board_evidence"],
        "max_tokens": transport["token_budget"],
        "temperature": transport["temperature"],
        "writer_prompt_hash": writer_prompt["prompt_hash"],
        "output_grammar": writer_prompt["output_grammar"],
        "seed_algorithm": writer_prompt["seed_behavior"]["algorithm"],
        "writer_transport_version": w3.LING_WRITER_TRANSPORT_VERSION,
        "writer_schema_hash": w5.writer_schema_hash(),
        "writer_outcomes_version": w5.WRITER_OUTCOMES_VERSION,
        "writer_parser_version": w5.WRITER_PARSER_VERSION,
        "writer_model": transport["model"], "writer_endpoint": transport["endpoint"],
        "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
        "protocol_key": prv4.prv6_protocol_key(),
        "normalization_policy_hash": prv2.normalization_policy_hash(),
        "manifest_treatment_hash": manifest_treatment,
        "information_geometry_hash": geometry,
        "branch_modes": ["real", "placebo", "null"],
        "estimand": "equal-weight form mean of real-minus-placebo entropy",
        "directional_prediction": "Delta < 0",
    })


# --------------------------------------------------------------------------
# route registration (independently chosen and costed for this family)
# --------------------------------------------------------------------------

def legal_route() -> dict[str, Any]:
    """First legal-family route registration; authorization stays pending."""

    return {
        "registered_by": REGISTRATION_VERSION,
        "registered_here_for_family": (
            "legal:low has no prior registered or authorized route; this registration "
            "is the family's first route registration and is made for this family only"),
        "authorization": "pending; only the separate L07 gate can authorize any request",
        "carries_nothing_forward": ("the stopped hypothesis:low route and its authorization "
                                    "record carry no authorization, budget leftover, "
                                    "pricing outcome or rate-limit conclusion into this "
                                    "family"),
        "independently_chosen_and_costed": (
            "chosen for this exact stage (legal:low discovery screen and optional "
            "exploratory replay) and costed by this registration's own budget arithmetic "
            "from the frame's frozen rate card; no hypothesis-family registration is "
            "imported or extended"),
        "ling": {
            "model": prv7.PAID_LING_MODEL,
            "endpoint": pr.LING_ENDPOINT,
            "key_loader": "behavioral_discovery._api_key",
            "route": "paid OpenRouter SKU (the free SKU is not routable)",
            "temperature": pr.LING_TEMPERATURE,
            "max_tokens": rep.LING_OUTPUT_TOKEN_CEILING,
            "pacing": (w3.LING_WRITER_TRANSPORT_VERSION + ", "
                       f"{w3.LING_MIN_ATTEMPT_INTERVAL_SECONDS} s between physical attempts"),
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
        "jev": {
            "model": pr.JEV_REPLAY_MODEL,
            "endpoint": pr.JEV_REPLAY_ENDPOINT,
            "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
            "protocol_key": prv4.prv6_protocol_key(),
            "max_retries": pr.JEV_REPLAY_MAX_RETRIES,
            "retryable_statuses": sorted(jc.JEV_RETRYABLE_STATUSES),
            "timeout_seconds": jc.JEV_TIMEOUT_DEFAULT,
            "backoff": {"initial_seconds": jc.JEV_BACKOFF_INITIAL,
                        "max_seconds": jc.JEV_BACKOFF_MAX,
                        "jitter": jc.JEV_BACKOFF_JITTER},
        },
        "normalization": {
            "policy": prv2.normalization_policy(),
            "policy_hash": prv2.normalization_policy_hash(),
            "tiers": ["exact", "complete_renormalized"],
            "hard_ceiling": 0.05,
            "rule": "normalize every accepted vector before any metric",
        },
    }


# --------------------------------------------------------------------------
# writer output policy: max_tokens and truncation, justified by L01
# --------------------------------------------------------------------------

def writer_output_policy(l01_evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Registered token budget and truncation policy, grounded in L01 (#219)."""

    diagnosis = (l01_evidence.get("truncation_diagnosis") or {}) if l01_evidence else {}
    budget_block = (diagnosis.get("output_cap_budget") or {}) if diagnosis else {}
    bound = (budget_block.get("bound") or {}) if budget_block else {}
    journal_stats = ((l01_evidence.get("recomputation") or {}).get("journal") or {}) \
        if l01_evidence else {}
    status_counts = journal_stats.get("status_counts") or {}
    attempted_seeds = sum(int(count) for key, count in status_counts.items()
                          if key != "not_attempted")
    return {
        "max_tokens": ladder.EXACT_BRIDGE_TOKEN_BUDGET,
        "registered_here": ("the writer token budget is a new legal-family registration "
                            "field; it is registered explicitly here, never inherited"),
        "value_preserved": ("1024 preserves the original L4X treatment bytes; the task "
                            "sequence keeps the original treatment unless a new treatment "
                            "is registered and reviewed as a different design, and L01 "
                            "records no evidence-supported change"),
        "justification_from_l01": {
            "diagnosis_stop_kind": str(budget_block and diagnosis.get("stop_kind")),
            "recorded_stop_reason": diagnosis.get("recorded_stop_reason"),
            "max_tokens_sent_per_hypothesis_request":
                budget_block.get("max_tokens_sent_per_request"),
            "binding_constraint": (
                "L01 shows the hypothesis:low stop was an HTTP 200 writer output-cap "
                "classification: non-empty content with finish_reason 'length' at the "
                "registered 1024-token budget, which was the binding constraint of that "
                "call"),
            "no_counterfactual": (
                "L01 records that no counterfactual exists and that one truncated call "
                "from one attempted seed cannot show that 1024 tokens is systematically "
                "too small, so this registration presents no token-budget change as "
                "evidence-based repair"),
            "l01_doc": str(L01_DOC_PATH),
            "l01_evidence": str(L01_EVIDENCE_PATH),
            "hypothesis_attempted_seeds": attempted_seeds,
            "hypothesis_attempted_seeds_source": (
                "L01 recomputation (key: status_counts, attempted rows minus "
                "not_attempted) for the #207 journal"),
            "attempted_value_recorded_by_l01": attempted_seeds,
        },
        "truncation_classification": [
            "empty content classifies as empty_output (checked first)",
            "non-empty content with finish_reason 'length' classifies as truncated_output",
            "rate limiting is a distinct terminal class: HTTP 429, error_class "
            "writer_http_429_rate_limited, parsed retry-after header, retry_ordinal > 0; "
            "L01 shows the recorded stop had none of those signals",
        ],
        "truncation_policy": {
            "truncated_output_is_a_registered_terminal_writer_error": True,
            "stop_before_next_call": True,
            "no_automatic_continuation": True,
            "no_automatic_budget_escalation": True,
            "no_mid_run_repair": True,
            "truncated_content_never_used_as_event_evidence": True,
            "no_silent_reclassification": ("a truncated attempt is journaled verbatim with "
                                           "failure_reason writer_error:truncated_output; "
                                           "its partial text is never parsed into an event"),
        },
        "enforcement_gates_registered": [
            "writer request identity check rejects max_tokens != 1024 "
            "(writer_request_identity_drift)",
            "offline preflight requires writer_contract token_budget == 1024 and "
            "ling_output_token_ceiling == 1024",
            "every journaled attempt records max_tokens: 1024",
        ],
        "repair_path": ("a future token-budget repair is not a resume or an edit: it is a "
                        "new registration version with fresh paths, its own review, and "
                        "its own separate L07 authorization; a stopped legal block keeps "
                        "the whole fixed manifest as an immutable journal and routes to a "
                        "terminal report"),
        "budget_binding_recomputed": {
            "truncated_call_output_tokens_upper_bound":
                bound.get("truncated_call_output_tokens_upper_bound"),
            "silence_calls_output_tokens_lower_bound":
                bound.get("silence_calls_output_tokens_lower_bound"),
            "note": ("those bounds describe the stopped hypothesis run only; they carry no "
                     "expectation into the legal block"),
        },
    }


# --------------------------------------------------------------------------
# budgets, request caps, cost arithmetic (registered as new legal fields)
# --------------------------------------------------------------------------

def cost_model() -> dict[str, Any]:
    """Worst-case per-physical-call cost from the frame's frozen rate card."""

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


def budgets() -> dict[str, Any]:
    """One discovery block (16 instances): collection then optional replay."""

    cost = cost_model()
    writer_logical = BLOCK_N * WRITER_CALLS_PER_INSTANCE
    receiver_logical = BLOCK_N * RECEIVER_CALLS_PER_INSTANCE
    replay_events_max = BLOCK_N
    jev_replay = replay_events_max * REPLAY_BRANCHES
    collection_worst = (writer_logical * RETRY_MULTIPLIER
                        * cost["ling_worst_physical_call_usd"]
                        + receiver_logical * RETRY_MULTIPLIER
                        * cost["jev_worst_physical_call_usd"])
    replay_worst = (jev_replay * RETRY_MULTIPLIER * cost["jev_worst_physical_call_usd"])
    return {
        "block_n": BLOCK_N,
        "cost_model": cost,
        "discovery_collection": {
            "planned": {"writer": writer_logical, "receiver": receiver_logical,
                        "combined": writer_logical + receiver_logical},
            "physical": {"writer": writer_logical * RETRY_MULTIPLIER,
                         "receiver": receiver_logical * RETRY_MULTIPLIER,
                         "combined": (writer_logical + receiver_logical)
                         * RETRY_MULTIPLIER},
            "hard_cost_ceiling_usd": COST_CEILING_COLLECTION_USD,
            "worst_case_cost_usd": round(collection_worst, 12),
            "within_hard_ceiling": collection_worst <= COST_CEILING_COLLECTION_USD,
            "next_call_reservation_usd": {
                "ling": round(cost["ling_worst_physical_call_usd"] * RETRY_MULTIPLIER, 12),
                "jev": round(cost["jev_worst_physical_call_usd"] * RETRY_MULTIPLIER, 12)},
            "rate_card_status": ("rates are the chain's frozen card (L03 planning "
                                 "precedent, recomputed here); ceiling 0.20 becomes a "
                                 "registered hard ceiling of this registration"),
        },
        "exploratory_replay": {
            "planned": {"jev": jev_replay, "writer": 0, "combined": jev_replay},
            "physical": {"jev": jev_replay * RETRY_MULTIPLIER, "writer": 0,
                         "combined": jev_replay * RETRY_MULTIPLIER},
            "events_max": replay_events_max,
            "branches": REPLAY_BRANCHES,
            "hard_cost_ceiling_usd": COST_CEILING_REPLAY_USD,
            "worst_case_cost_usd": round(replay_worst, 12),
            "within_hard_ceiling": replay_worst <= COST_CEILING_REPLAY_USD,
            "next_call_reservation_usd": {
                "jev": round(cost["jev_worst_physical_call_usd"] * RETRY_MULTIPLIER, 12)},
        },
        "program": {
            "planned": {"writer": writer_logical,
                        "jev": receiver_logical + jev_replay,
                        "combined": writer_logical + receiver_logical + jev_replay},
            "physical": {"writer": writer_logical * RETRY_MULTIPLIER,
                         "jev": (receiver_logical + jev_replay) * RETRY_MULTIPLIER,
                         "combined": (writer_logical + receiver_logical + jev_replay)
                         * RETRY_MULTIPLIER},
            "hard_cost_ceiling_usd": COST_CEILING_PROGRAM_USD,
            "worst_case_cost_usd": round(collection_worst + replay_worst, 12),
            "within_hard_ceiling": (collection_worst + replay_worst)
            <= COST_CEILING_PROGRAM_USD,
            "arithmetic": ("1 block x (collection: 16 x 4 Ling + 16 x 1 Jev; exploratory "
                           "replay: <=16 events x 3 Jev), each x (1 + max_retries 2)"),
            "ceiling_status": ("the $0.30 program ceiling equals the L03-approved planning "
                               "ceiling and is registered as this registration's hard "
                               "ceiling; the worst case recomputes to "
                               "$0.146276352 + $0.049545216 = $0.195821568 <= $0.30"),
        },
    }


def request_caps() -> dict[str, Any]:
    """Pacing and retry-inclusive physical request caps (registered)."""

    cost = cost_model()
    return {
        "retry_inclusive_semantics": ("every bound counts physical requests, including "
                                      "retries: one logical call may become up to 3 "
                                      "physical attempts (max_retries 2)"),
        "pacing": {
            "ling_min_attempt_interval_seconds": w3.LING_MIN_ATTEMPT_INTERVAL_SECONDS,
            "ling_pacing_algorithm": w3.LING_PACING_ALGORITHM,
            "ling_writer_transport_version": w3.LING_WRITER_TRANSPORT_VERSION,
            "ling_backoff": {"initial_seconds": w3.LING_BACKOFF_INITIAL_SECONDS,
                             "max_seconds": w3.LING_BACKOFF_MAX_SECONDS},
            "jev_backoff": {"initial_seconds": jc.JEV_BACKOFF_INITIAL,
                            "max_seconds": jc.JEV_BACKOFF_MAX,
                            "jitter": jc.JEV_BACKOFF_JITTER},
            "jev_timeout_seconds": jc.JEV_TIMEOUT_DEFAULT,
        },
        "max_retries": {"ling": w3.LING_MAX_RETRIES, "jev": pr.JEV_REPLAY_MAX_RETRIES},
        "discovery_collection": {
            "planned_logical": {"writer": BLOCK_N * WRITER_CALLS_PER_INSTANCE,
                                "receiver": BLOCK_N * RECEIVER_CALLS_PER_INSTANCE,
                                "combined": BLOCK_N * (WRITER_CALLS_PER_INSTANCE
                                                       + RECEIVER_CALLS_PER_INSTANCE)},
            "physical_writer_max":
                BLOCK_N * WRITER_CALLS_PER_INSTANCE * RETRY_MULTIPLIER,
            "physical_receiver_max":
                BLOCK_N * RECEIVER_CALLS_PER_INSTANCE * RETRY_MULTIPLIER,
            "physical_combined_max": BLOCK_N * (WRITER_CALLS_PER_INSTANCE
                                                + RECEIVER_CALLS_PER_INSTANCE)
            * RETRY_MULTIPLIER,
        },
        "exploratory_replay": {
            "planned_logical": {"jev": BLOCK_N * REPLAY_BRANCHES, "writer": 0,
                                "combined": BLOCK_N * REPLAY_BRANCHES},
            "events_max": BLOCK_N,
            "branches": REPLAY_BRANCHES,
            "physical_jev_max": BLOCK_N * REPLAY_BRANCHES * RETRY_MULTIPLIER,
        },
        "program": {
            "planned_logical": {
                "writer": BLOCK_N * WRITER_CALLS_PER_INSTANCE,
                "jev": BLOCK_N * (RECEIVER_CALLS_PER_INSTANCE + REPLAY_BRANCHES),
                "combined": BLOCK_N * (WRITER_CALLS_PER_INSTANCE
                                       + RECEIVER_CALLS_PER_INSTANCE + REPLAY_BRANCHES)},
            "physical_writer_max": BLOCK_N * WRITER_CALLS_PER_INSTANCE * RETRY_MULTIPLIER,
            "physical_jev_max": BLOCK_N * (RECEIVER_CALLS_PER_INSTANCE + REPLAY_BRANCHES)
            * RETRY_MULTIPLIER,
            "physical_combined_max": BLOCK_N * (WRITER_CALLS_PER_INSTANCE
                                                + RECEIVER_CALLS_PER_INSTANCE
                                                + REPLAY_BRANCHES) * RETRY_MULTIPLIER,
        },
        "next_call_reservation_usd": {
            "ling": round(cost["ling_worst_physical_call_usd"] * RETRY_MULTIPLIER, 12),
            "jev": round(cost["jev_worst_physical_call_usd"] * RETRY_MULTIPLIER, 12)},
        "reservation_rule": ("stop before the next call whenever issuing it would exceed "
                             "the request cap or the hard cost ceiling; the reservations "
                             "are the retry-inclusive worst cost of one more logical call "
                             "for each role, so the cap closest to the next call wins"),
        "no_credit_from_unused_budgets": ("physical requests or dollars unused by a "
                                          "stopped or short run authorize no retry, "
                                          "extension or carry-over"),
    }


# --------------------------------------------------------------------------
# ownership / read-after-write, information rules, coverage, retention
# --------------------------------------------------------------------------

def ownership_and_exposure_checks() -> dict[str, Any]:
    """Ownership, read-after-write and treatment-integrity checks (registered)."""

    return {
        "ownership_check": {
            "rule": ("every board write carrying the peer claim must be authored by B and "
                     "match instance.holds_claim exactly; a non-owned claim is rejected "
                     "(non_owned_claim) and journaled, never delivered"),
            "rejection_journaled": True,
        },
        "accepted_write_requirements": ["writer is B",
                                        "normalized_claim equals the claim",
                                        "raw_text equals the claim (byte exact)",
                                        "receiver_id is A",
                                        "write status is accepted"],
        "read_after_write": {
            "required": ("A reads what B wrote: an accepted board_write by B followed by "
                         "an A peer_read_exposure with a nonempty exposure_id "
                         "(jev-finalizer) whose read sequence is strictly greater than "
                         "the write sequence"),
            "missing_or_out_of_order": ("rejected or missing read-after-write evidence "
                                        "yields no event and is journaled; no receiver "
                                        "evaluation happens on unexposed state"),
            "single_delivery": ("each accepted write is read by A once through the "
                                "exposure record; no re-read, extra delivery or replayed "
                                "write is permitted"),
        },
        "placebo_check": {
            "rule": ("the matched placebo is an A-owned, receiver-known claim "
                     "re-presented in the same envelope with I_m = 0.0 and no "
                     "feasible-set change; it is inert by construction"),
            "verified_against": "L02 per-form placebo_claim records",
        },
        "receiver_known_claims_excluded": ("a real claim must not already be known to A "
                                           "in the pre-read state; receiver-known claims "
                                           "never enter the real arm"),
        "one_deduplicated_informative_claim_per_state": True,
        "board_visibility": "peer-only rows; rejected writes are never visible",
        "treatment_integrity": ("hold pre-read state, model, options, instructions, target "
                                "and timing fixed across real/placebo/null; only "
                                "visible_messages differ"),
        "every_failure_journaled": ("each failed eligibility or integrity check is recorded "
                                    "in the collection denominator with a reason; the run "
                                    "never silently drops a planned instance"),
    }


def information_rules(census_document: Mapping[str, Any]) -> dict[str, Any]:
    """Authoritative information contract frozen from the L02 census records."""

    per_form = ((census_document.get("form_records") or {}).get("per_form")) or {}
    claim_bits = sorted({float(record["authoritative_b_owned_informative_claim"]["i_m_bits"])
                         for record in per_form.values()})
    placebo_inert = all(record["placebo_claim"]["inert"]
                        and record["placebo_claim"]["owned_by_a"]
                        and float(record["placebo_claim"]["i_m_bits"]) == 0.0
                        for record in per_form.values())
    return {
        "real_claim_information_bits": claim_bits,
        "real_claim_pin": ("each pre-read state has exactly one authoritative B-owned "
                           "informative claim worth "
                           f"{claim_bits[0] if len(claim_bits) == 1 else claim_bits} bits "
                           "(ExactInformationEvaluator): A's feasible set drops from 2 to "
                           "1 once the message is exposed; this is structural-census "
                           "evidence, not an observed emission"),
        "evaluator": "ExactInformationEvaluator (AcceptableInformationCheck)",
        "placebo_information_bits": 0.0,
        "placebo_inert_for_every_form": placebo_inert,
        "placebo_pin": ("the placebo is a controller-injected re-presentation of a "
                        "receiver-known A clue: I_m = 0.0, no feasible-set reduction, "
                        "same envelope as the real arm"),
        "null_arm": "no message; reserved for manipulation checks only",
        "deduplication": ("one deduplicated informative claim per state; duplicate claims "
                          "split nothing and pool nothing"),
        "reported_separately": ("delivered information (I_m), entropy change (d_fe) and "
                                "matched-contrast uptake are three separate quantities: "
                                "exposure proves delivery, not uptake; entropy reduction "
                                "does not prove calibration"),
        "basis": ("L02 census per-form authoritative B-owned informative-claim records, "
                  "recomputed by the generator and pinned here by content hash"),
    }


def coverage_rules(design3: Mapping[str, Any]) -> dict[str, Any]:
    """The L03 prospective coverage rule, frozen verbatim into the registration."""

    return dict((design3.get("coverage_rule") or {})) | {
        "registered_here": ("this is the registered coverage rule for the legal discovery "
                            "screen; it is frozen before any collection"),
    }


def silence_and_failure_retention() -> dict[str, Any]:
    """All silences and failures are retained rows, never filtered or dropped."""

    return {
        "retain_silences": True,
        "retain_failures": True,
        "retain_not_attempted_rows": True,
        "journal_row_contract": ("every planned manifest instance appears exactly once, in "
                                 "manifest order, whatever happened: emitted, silence, "
                                 "failed (with failure_reason) or not_attempted (with the "
                                 "stop reason)"),
        "denominators": ("planned, attempted, emitted, eligible, valid, complete and "
                         "missing counts are reported by stage, form and branch with "
                         "reasons; guard results never filter the primary estimate"),
        "stop_semantics": ("any stop keeps the whole fixed manifest as an immutable journal "
                           "including failure and not-attempted rows and routes to a "
                           "terminal report; a stopped run authorizes no retry"),
    }


# --------------------------------------------------------------------------
# fixed N, classification, inference, multiplicity, authorization, handoff
# --------------------------------------------------------------------------

def discovery_manifest(scan: Mapping[str, Sequence[int]]) -> dict[str, Any]:
    """Fixed-N manifest: first 4 seeds per form, ascending, outcome-blind."""

    manifest: list[dict[str, Any]] = []
    for form in sorted(scan):
        chosen = sorted(scan[form])[:INSTANCES_PER_FORM]
        if len(chosen) < INSTANCES_PER_FORM:
            raise RegistrationError(f"form {form} has only {len(chosen)} selectable seeds")
        for seed in chosen:
            instance = rep.instance_for(FAMILY, seed)
            manifest.append({"instance_id": instance.instance_id, "seed": seed,
                             "prompt_form_id": form})
    if len(manifest) != BLOCK_N:
        raise RegistrationError(f"manifest must contain exactly {BLOCK_N} instances")
    membership: dict[str, list[str]] = {}
    for entry in manifest:
        membership.setdefault(str(entry["prompt_form_id"]), []).append(
            str(entry["instance_id"]))
    return {
        "block": "discovery",
        "window": {"role": "discovery", "base": DISCOVERY_WINDOW[0],
                   "end": DISCOVERY_WINDOW[1],
                   "window": DISCOVERY_WINDOW[1] - DISCOVERY_WINDOW[0] + 1},
        "instances_per_form": INSTANCES_PER_FORM,
        "form_count": len(membership),
        "block_n": BLOCK_N,
        "selection_rule": (f"first {INSTANCES_PER_FORM} seeds per form in ascending seed "
                           "order inside the L02 discovery window; fixed N; no "
                           "outcome-based stopping or seed substitution"),
        "outcome_blind": True,
        "consulted_outcomes": [],
        "manifest": manifest,
        "form_membership": {form: sorted(ids) for form, ids in sorted(membership.items())},
        "manifest_hash": _digest(manifest),
        "matches_l03_screen": True,
        "closure_probe_window_unselectable": True,
        "closure_probe_window": list(CLOSURE_PROBE_WINDOW),
        "held_out_window": {
            "registered_here": False,
            "statement": ("no held-out or confirmation window is registered by this task; "
                          "any later window must be chosen by the L02 inventory-first rule "
                          "before its own outcomes exist"),
        },
    }


def design_classification(design3: Mapping[str, Any]) -> dict[str, Any]:
    """Carry the L03 descriptive-discovery decision (cite it, never re-decide)."""

    derivation = design3.get("derivation") or {}
    classification = design3.get("classification") or {}
    floor_by_k = {str(row["k"]): row["attainable_two_sided_sign_flip_floor"]
                  for row in derivation.get("attainable_floor_grid") or []}
    return {
        "decision_from_l03": classification.get("decision"),
        "classification": "pilot (descriptive/estimation only)",
        "k": derivation.get("k_observed"),
        "attainable_two_sided_sign_flip_floor":
            (derivation.get("sign_flip_floor") or {}).get("value"),
        "floor_derivation": "2/2^k = 2/2^4 = 2/16 = 1/8 = 0.125",
        "floor_above_0_05": True,
        "confirmatory_minimum_k": 6,
        "attainable_floor_by_k": floor_by_k,
        "gate_evidence": {
            "structural_gate": "pass (L03, recomputed against the L02 census)",
            "capacity_gate": "pass (L03, recomputed per form per window)",
        },
        "decision_traces_to": f"{str(L03_DESIGN_PATH)} classification.decision_trace",
        "no_cross_family_promotion": ("audit #227 adds no form to this family and cannot "
                                      "promote this four-form version toward a "
                                      "confirmatory design; its 7-8-family Holm "
                                      "arithmetic is prospective program context only"),
        "fresh_seed_replication": ("descriptive only; a fresh-seed block cannot become "
                                   "confirmatory on this family"),
        "h0": "Delta = 0",
        "h1": "Delta < 0",
        "estimand": "equal-weight form mean of real-minus-placebo entropy",
        "experimental_unit": "prompt form",
        "seeds_are_not_forms": True,
        "guards_never_filter_the_estimate": True,
        "no_planning_low_effect_size_prior": True,
        "no_hypothesis_low_effect_size_prior": True,
        "exchangeability_limits": derivation.get("exchangeability_limits"),
        "statement": ("L03 (issue #221) classified legal:low at k = 4 as descriptive "
                      "discovery and this registration freezes a runnable descriptive "
                      "discovery screen: the exact two-sided sign-flip floor 2/2^4 = "
                      "0.125 exceeds alpha .05, so no dichotomous rejection is attainable "
                      "at any effect size on this closed four-form version; the screen "
                      "reports estimation with labeled, assumption-dependent "
                      "exchangeability, retaining every silence and failure"),
    }


def inference_plan(classification: Mapping[str, Any]) -> dict[str, Any]:
    """Registered inference plan for the descriptive discovery screen."""

    return {
        "primary_test": "exhaustive two-sided cluster sign-flip over the k form means",
        "direction_requirement": "the observed equal-form mean must be negative",
        "alpha": 0.05,
        "attainable_two_sided_floor_by_k": dict(classification["attainable_floor_by_k"]),
        "k_from_l03": classification["k"],
        "consequence": ("k = 4 < 6, so the attainable exact two-sided sign-flip floor is "
                        "0.125 > 0.05; no dichotomous rejection at alpha = 0.05 is "
                        "attainable at any effect size on this family"),
        "assumption_dependent_inference": ("form-level sign flips are assumption-dependent "
                                           "(template-identical forms); any exact p is "
                                           "reported as a descriptive, labeled statistic, "
                                           "never assumption-free inference"),
        "minimum_forms_for_confirmatory": 6,
        "minimum_form_rule": ("a dichotomous confirmatory claim requires at least six "
                              "distinct prompt forms; k = 4 and k = 5 are "
                              "descriptive/estimation only"),
        "interval": "form-mean t interval with df = k - 1 (k = 4 => df = 3)",
        "interval_half_width": {
            "formula": "t(0.975, k-1) x SD_between / sqrt(k)",
            "label": ("illustrative interval half-width, not a power-based MDE; "
                      "planning-low and hypothesis-low outcomes are not used as a prior "
                      "or an effect-size guarantee"),
            "not_a_prior": True,
        },
        "prohibited_as_primary": ["instance-level t-test", "instance-level Wilcoxon test",
                                  "instance-weighted mean",
                                  "treating events as independent states",
                                  "one-sided switch without a new registration",
                                  "pooling forms or families for a smaller p-value"],
        "imputation": "never impute missing pairs",
        "guards": {"target_probability_delta": 0.0,
                   "feasible_set_mass_epsilon": 0.01,
                   "reporting": ("reported separately by form and event; never used to "
                                 "filter the primary entropy estimate"),
                   "useful_uptake_rule": ("an entropy drop alone is never useful uptake "
                                          "when either guard fails")},
        "missingness": {
            "complete_pair": "real and placebo both valid",
            "primary_requirement": "at least one complete pair in every registered form",
            "below_six_forms": "descriptive/estimation only",
            "missing_entire_form": ("blocks the registered full-form estimand; label any "
                                    "available-form estimate descriptive"),
        },
    }


def multiplicity() -> dict[str, Any]:
    """Registered family-level multiplicity contract."""

    return {
        "family_level_control": "Holm step-down across the registered family set",
        "registered_family_set": [FAMILY],
        "registered_family_count": 1,
        "single_family_reduction": ("with exactly one registered family the Holm-adjusted "
                                    "p equals the raw p; no cross-family control follows"),
        "family_set_frozen_before_outcomes": True,
        "cross_family_note": ("audit #227 records that a Holm family of 7 or 8 family "
                              "hypotheses would need k >= 9 in its first ordered test; "
                              "that program-level arithmetic is prospective context, "
                              "registers no cross-family set here, cannot make this "
                              "four-form family confirmatory, and may never be satisfied "
                              "by pooling legal with another family"),
        "future_families": ("any additional family or cross-family registration requires "
                            "its own preregistration, multiplicity contract and "
                            "authorization gate; it may never join this set after "
                            "outcomes are visible"),
        "forbidden": ["sweeping families and selecting a winner post hoc",
                      "adding a family after outcomes are visible",
                      "removing a registered family after outcomes are visible",
                      "pooling legal with another family for a smaller p-value",
                      "splitting duplicates to obtain a smaller p-value"],
    }


def authorization(l01_evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Authorization contract: everything pending, nothing inferred."""

    route_status = ((l01_evidence.get("historical_facts") or {})
                    .get("legal_family_route_status") or {})
    return {
        "authorization_status": "pending",
        "status": ("no legal-family authorization exists; this registration grants none, "
                   "even after any review or lock"),
        "separate_live_authorization_required_after_locking": True,
        "locking_is_not_authorization": True,
        "approval_must_be_a_supplied_reference": True,
        "approval_may_not_be_inferred_from_locking": True,
        "approval_may_not_be_inferred_from_predecessor_closure": True,
        "failed_predecessor_never_authorizes_successor": True,
        "l07_gate": {
            "issue": L07_GATE_ISSUE,
            "doc": str(L07_GATE_DOC),
            "must_cover": ("exact stage, route, pacing, retry-inclusive physical request "
                           "caps and dollar caps; anything narrower or wider demands a "
                           "new registration version first"),
            "loop_halts_before": L07_GATE_ISSUE,
        },
        "route_registered": False,
        "route_authorized": False,
        "route_status_note": route_status.get("statement")
        or "legal route registration status per L01",
        "no_provider_call_of_any_kind": ("no probe, dry call, schema call or free-SKU call "
                                         "is permitted by this registration, by task text, "
                                         "by credentials, or by any issue event; only the "
                                         "L07 explicit reference permits any request"),
        "pending_review": [
            "reviewer decision on the L03-carried classification (k = 4, floor 0.125, "
            "descriptive discovery)",
            "reviewer decision on the fixed-N manifest, selection rule and the registered "
            "family hypothesis set",
            "reviewer decision on the L4X treatment bytes, the writer output policy "
            "(max_tokens 1024, truncation classification per L01) and the registered "
            "route/normalization pins",
            "reviewer decision on budgets, request caps, dollar ceilings, stops, paths "
            "and coverage rules",
            "a separate explicit live authorization reference from L07 is required before "
            "any provider call; locking or reviewing this registration is not that "
            "authorization",
        ],
    }


def non_claims() -> list[str]:
    return [
        "no provider call, probe or live journal was made or authorized",
        "this registration authorizes nothing beyond L05 planning",
        "no confirmatory or significance-style claim for legal:low at k = 4",
        "no population-level generalization beyond the four registered forms",
        "no effect-size prior from planning-low, hypothesis-low or the motivating paper",
        "no cross-family claim, pooling or winner selection",
        "no approval, credential, issue text or lock implies live authorization",
        "the stopped hypothesis registration and its windows are not reused",
        "no generator redesign and no reordering of the frozen historical queue",
        "spare capacity is not permission to replace missing seeds",
        "#227's proposals are not runnable families and count toward no target here",
    ]


def handoff_to_l05() -> dict[str, Any]:
    return {
        "to": "L05",
        "issue": 223,
        "deliverable": ("legal runner and fail-closed preflight, tested offline, "
                        "consuming exactly this registration"),
        "runnable_registration": True,
        "conditions": [
            "#222 must be closed by the plugin after reviewer approval before L05 runs; "
            "this artifact does not open or advance #223 itself",
            "the runner must consume the registered manifest, treatment bytes, route pins, "
            "budgets, request caps, stops and paths exactly, and refuse any drift",
            "the preflight must make zero provider calls and fail closed without the "
            "reviewed lock and the separate explicit L07 authorization reference",
            "missing or rejected live output paths fail the preflight; output collision "
            "with any registered path is a stop",
            "all tests and the deterministic rebuild must pass offline",
        ],
        "requires_before_any_call": ["L06 reviewed lock (#224)",
                                     "L07 explicit scope-bound user authorization (#225)"],
    }


# --------------------------------------------------------------------------
# constraints and limitations
# --------------------------------------------------------------------------

def _constraints() -> list[dict[str, str]]:
    return [
        {"constraint": "no provider call, probe, dry call or live journal of any kind",
         "basis": "#222 task text and chain direction; only the later L07 gate can grant a "
                  "separate explicit user authorization",
         "consequence": "every number here is offline derivation, recomputation or "
                        "planning arithmetic re-run from disk"},
        {"constraint": "a failed or stopped predecessor never authorizes its successor",
         "basis": "research protocol and legal task sequence",
         "consequence": "no hypothesis-family stop, silence, tolerance or instrument event "
                        "carries into legal, and no successor task is opened by this "
                        "artifact"},
        {"constraint": "preserve frozen #200 and terminal #207/#215 files byte-identically",
         "basis": "#222 task text",
         "consequence": "they are read-only pinned inputs, rehashed before and after the "
                        "build and fail-closed on any drift"},
        {"constraint": "preserve the registered estimand, the two-sided test and the "
                       "negative-direction requirement",
         "basis": "research protocol; L03 handoff",
         "consequence": "no one-sided switch, no guard filtering, no imputation, no "
                        "instance-level primary inference"},
        {"constraint": "the stopped hypothesis registration is a non-reuse control",
         "basis": "#222 task text ('do not ... reuse the stopped hypothesis registration')",
         "consequence": "no seed window, manifest id, output path, authorization or "
                        "outcome carries over; this registration freezes its own fields "
                        "explicitly"},
        {"constraint": "do not migrate the toolchain to OpenCode Zen or OpenCode Go",
         "basis": "operator direction for this run",
         "consequence": "offline worker/reviewer sessions stay on the explicit free "
                        "opencode/mimo-v2.6-flash-free route of the program amendment; "
                        "OpenCode Go has no interchangeable Ling route anyway"},
        {"constraint": "#227 is consumed as approved program context only",
         "basis": "#222 task text; program amendment worker order #221 -> #227 -> #222",
         "consequence": "the audit cannot promote legal:low, register a family, count "
                        "proposals, or mutate the L02 census and L03 decision"},
        {"constraint": "route, model, token budget, rates, request caps, dollar ceilings "
                       "and stop rules are registered here as new legal fields",
         "basis": "legal task sequence; L01 baseline; L03 handoff",
         "consequence": "the stopped hypothesis Ling route carries no authorization and "
                        "nothing is silently inherited"},
        {"constraint": "seed selection stays outcome-blind and capacity-derived",
         "basis": "research protocol; L03 screen rule",
         "consequence": "emission, guard, entropy and writer outcomes never enter the rule"},
        {"constraint": "no held-out or confirmation window is registered here",
         "basis": "L02/L03 handoffs",
         "consequence": "any later window uses the L02 inventory-first rule before its "
                        "own outcomes exist"},
        {"constraint": "retain all silences, failures and not-attempted rows",
         "basis": "research protocol; L03 coverage rule and stop semantics",
         "consequence": "the denominator never shrinks and a stop never drops a planned "
                        "instance from the journal"},
    ]


def _limitations() -> list[str]:
    return [
        "Offline only: no provider call, probe or network event was made or authorized.",
        "Draft pending review only: L06 review/lock and an explicit L07 authorization are "
        "still required before any call; the legal loop halts before #225.",
        "Descriptive by design: k = 4 keeps the exact two-sided sign-flip floor at 0.125, "
        "so the screen estimates effects, variance and coverage without spending alpha.",
        "Exchangeability is assumption-dependent: template-identical forms mean any exact "
        "p is reported as a labeled descriptive statistic, never as assumption-free "
        "inference.",
        "Cost figures recompute from the chain's frozen rate card; observed spend depends "
        "on a future L07-authorized run and is not assumed here.",
        "Seed/instance-id disjointness is inherited from the hash-pinned L02 inventory, "
        "whose 20 recorded inaccessible locations remain open audit exceptions, never "
        "empty sets.",
        "The writer output policy keeps the L4X 1024-token budget on L01's own terms: the "
        "truncation stop is retained as terminal, and a budget repair would be a new "
        "registration version with fresh paths.",
    ]


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def build_registration(repo_root: Path | str) -> dict[str, Any]:
    """Deterministic, offline L04 registration build. No provider call."""

    root = Path(repo_root)
    _install_network_audit_hook()
    _NETWORK_EVENTS.clear()

    frozen_inputs, source_inputs = _hashed_inputs(root)
    before = {entry["path"]: entry["sha256"] for entry in frozen_inputs + source_inputs}

    # ---- pinned predecessor chain recomputed from bytes -------------------
    census_document = load_json(root / L02_CENSUS_PATH)
    if _content_hash(census_document, hash_key="content_hash") != L02_CENSUS_CONTENT_HASH:
        raise RegistrationError("L02 census content hash drift")
    design3 = load_json(root / L03_DESIGN_PATH)
    if _content_hash(design3, hash_key="content_hash") != L03_DESIGN_CONTENT_HASH:
        raise RegistrationError("L03 design content hash drift")
    if design3.get("design_version") != "jev-legal-p03-design-v1":
        raise RegistrationError("L03 design version drift")
    if classification_decision(design3) != "descriptive_discovery":
        raise RegistrationError("L03 decision is not descriptive_discovery, so a runnable "
                                "registration must not be fabricated")
    audit_artifact = load_json(root / AUDIT_227_PATH)
    if audit227._content_hash(audit_artifact) != AUDIT_227_CONTENT_HASH:
        raise RegistrationError("#227 audit content hash drift")
    if audit_artifact.get("authorization") != AUDIT_227_AUTHORIZATION:
        raise RegistrationError("#227 audit authorization statement drift")
    audit_doc_entries = audit_artifact.get("inputs_sha256") or {}
    drifted = {rel: digest for rel, digest in audit_doc_entries.items()
               if sha256_of(root / rel) != digest}
    if drifted:
        raise RegistrationError(f"#227 audit pinned inputs drifted from disk: {drifted}")
    l01_evidence = load_json(root / L01_EVIDENCE_PATH)
    stopped = load_json(root / STOPPED_REGISTRATION_PATH)
    if _content_hash(stopped, hash_key="registration_hash") != STOPPED_REGISTRATION_HASH:
        raise RegistrationError("stopped-hypothesis registration control drift")
    stopped_auth = load_json(root / STOPPED_AUTHORIZATION_PATH)
    if stopped_auth.get("scope_digest_sha256") != STOPPED_SCOPE_DIGEST:
        raise RegistrationError("stopped-hypothesis scope-digest control drift")

    design3_checks = list(design3.get("checks") or [])
    design3_ok = bool(design3_checks) and all(bool(entry.get("ok")) for entry in design3_checks)
    if not design3_ok:
        raise RegistrationError("L03 design check drift")
    if ((design3.get("network_audit") or {}).get("events") != 0
            or (design3.get("network_audit") or {}).get("provider_calls") != 0):
        raise RegistrationError("L03 network audit drift")
    design3_handoff = (design3.get("handoff") or {})
    if design3_handoff.get("to") != "L04" or design3_handoff.get("issue") != 222:
        raise RegistrationError("L03 handoff does not target this task")
    l01_checks = list(l01_evidence.get("checks") or [])
    if not l01_checks or not all(bool(entry.get("ok")) for entry in l01_checks):
        raise RegistrationError("L01 evidence checks do not all pass")
    l01_route_status = ((l01_evidence.get("historical_facts") or {})
                        .get("legal_family_route_status") or {})
    if l01_route_status.get("registered") is not False \
            or l01_route_status.get("authorized") is not False:
        raise RegistrationError("L01 route-status control drift")

    # ---- rebuild k, the form set and the manifest from the generator ------
    windows = ((census_document.get("windows") or {}).get("windows")) or []
    discovery_window = next(w for w in windows if w.get("role") == "discovery")
    base, span = int(discovery_window["base"]), int(discovery_window["window"])
    if [base, base + span - 1] != list(DISCOVERY_WINDOW):
        raise RegistrationError(f"discovery window drift: {base}..{base + span - 1}")
    scan = l03._scan_forms(FAMILY, base, span)
    form_ids = sorted(scan)
    recorded_form_ids = sorted(
        ((census_document.get("form_capacity") or {}).get("form_ids")) or [])
    if form_ids != recorded_form_ids or len(form_ids) != 4:
        raise RegistrationError("generator form set disagrees with the L02 census")

    manifest = discovery_manifest(scan)
    screen = (design3.get("discovery_screen") or {})
    if screen.get("manifest") != manifest["manifest"]:
        raise RegistrationError("manifest disagrees with the L03 screen")
    if screen.get("manifest_hash") != L03_SCREEN_MANIFEST_HASH:
        raise RegistrationError("L03 screen manifest hash drift")

    # ---- treatment, route, budgets, stops, coverage -----------------------
    treatment = legal_treatment()
    manifest_treatment_hash = legal_manifest_treatment_hash(manifest["manifest"])
    geometry = information_geometry_hash(census_document)
    treatment["manifest_treatment_hash"] = manifest_treatment_hash
    treatment["information_geometry_hash"] = geometry
    treatment["treatment_hash"] = legal_treatment_hash(treatment, manifest_treatment_hash,
                                                       geometry)
    route = legal_route()
    registered_budgets = budgets()
    caps = request_caps()
    policy = writer_output_policy(l01_evidence)
    classification = design_classification(design3)
    inference = inference_plan(classification)
    coverage = coverage_rules(design3)
    retention = silence_and_failure_retention()
    ownership = ownership_and_exposure_checks()
    information = information_rules(census_document)
    constraints = _constraints()
    authorization_contract = authorization(l01_evidence)
    stops_list = list((design3.get("stop_conditions") or {}).get("stops") or [])

    # ---- L03 planning arithmetic carried into the registered ceilings -----
    scenarios = (design3.get("request_cost_scenarios") or {})
    selected = next(s for s in (scenarios.get("scenarios") or []) if s.get("selected"))
    if selected["fixed_n"] != BLOCK_N or scenarios.get("selected_fixed_n") != BLOCK_N:
        raise RegistrationError("L03 selected scenario disagrees with the fixed N")
    arithmetic_match = {
        "collection_worst": selected["collection"]["worst_case_cost_usd"]
        == registered_budgets["discovery_collection"]["worst_case_cost_usd"],
        "replay_worst": selected["exploratory_replay"]["worst_case_cost_usd"]
        == registered_budgets["exploratory_replay"]["worst_case_cost_usd"],
        "program_worst": selected["program"]["worst_case_cost_usd"]
        == registered_budgets["program"]["worst_case_cost_usd"],
        "collection_planned": selected["collection"]["planned"]
        == registered_budgets["discovery_collection"]["planned"],
        "collection_physical": selected["collection"]["physical"]
        == registered_budgets["discovery_collection"]["physical"],
        "replay_planned": selected["exploratory_replay"]["planned"]
        == registered_budgets["exploratory_replay"]["planned"],
        "replay_physical": selected["exploratory_replay"]["physical"]
        == registered_budgets["exploratory_replay"]["physical"],
        "program_planned_sums": registered_budgets["program"]["planned"]["combined"]
        == (registered_budgets["discovery_collection"]["planned"]["combined"]
            + registered_budgets["exploratory_replay"]["planned"]["combined"]),
        "program_physical_sums": registered_budgets["program"]["physical"]["combined"]
        == (registered_budgets["discovery_collection"]["physical"]["combined"]
            + registered_budgets["exploratory_replay"]["physical"]["combined"]),
    }
    if not all(arithmetic_match.values()):
        raise RegistrationError("registered budget arithmetic disagrees with L03")

    # ---- path freshness and uniqueness -----------------------------------
    prior_path_registry = ({path for path in l02.HYPOTHESIS_OUTPUT_PATHS}
                           | set(rep.OWNED_PATHS)
                           | {str(hyp_p04.REGISTRATION_PATH),
                              str(STOPPED_AUTHORIZATION_PATH)})
    engaged_paths = set(PATHS.values())
    all_registered_paths = sorted(engaged_paths | {str(REGISTRATION_PATH), str(DOC_PATH)})
    if not engaged_paths.isdisjoint(prior_path_registry):
        raise RegistrationError("a registered live path collides with an older artifact")
    if len(set(all_registered_paths)) != len(all_registered_paths):
        raise RegistrationError("registered paths are not pairwise unique")
    if not all(path.startswith("runs/next-phase/legal/") for path in engaged_paths):
        raise RegistrationError("registered live paths must stay in this chain namespace")
    live_absent = {name: not (root / path).exists() for name, path in LIVE_PATHS.items()}

    doc_text = (root / DOC_PATH).read_text(encoding="utf-8") if (root / DOC_PATH).exists() \
        else ""

    after = {entry["path"]: sha256_of(root / entry["path"])
             for entry in frozen_inputs + source_inputs}
    events = network_events()

    checks = _registration_checks(
        root=root, frozen_inputs=frozen_inputs, source_inputs=source_inputs,
        census_document=census_document, design3=design3, design3_checks=design3_checks,
        design3_ok=design3_ok, design3_handoff=design3_handoff,
        audit_artifact=audit_artifact, audit_doc_entries=audit_doc_entries,
        l01_evidence=l01_evidence, l01_route_status=l01_route_status,
        stopped=stopped, stopped_auth=stopped_auth, scan=scan, form_ids=form_ids,
        manifest=manifest, screen=screen, treatment=treatment,
        manifest_treatment_hash=manifest_treatment_hash, geometry=geometry, route=route,
        budgets=registered_budgets, caps=caps, policy=policy,
        classification=classification, inference=inference, coverage=coverage,
        retention=retention, ownership=ownership, information=information,
        constraints=constraints, authorization=authorization_contract, stops=stops_list,
        arithmetic_match=arithmetic_match, selected=selected, live_absent=live_absent,
        all_registered_paths=all_registered_paths, engaged_paths=engaged_paths,
        doc_text=doc_text, before=before, after=after, events=events)

    document: dict[str, Any] = _document(
        frozen_inputs=frozen_inputs, source_pins=source_inputs,
        multiplicity=multiplicity(), non_claims=non_claims(),
        handoff=handoff_to_l05(), checks_record=checks, events=events,
        census_document=census_document, design3=design3, design3_checks=design3_checks,
        design3_ok=design3_ok, design3_handoff=design3_handoff,
        audit_artifact=audit_artifact, l01_evidence=l01_evidence,
        l01_route_status=l01_route_status, stopped_auth=stopped_auth,
        manifest=manifest, screen=screen, treatment=treatment, route=route,
        budgets=registered_budgets, caps=caps, policy=policy,
        classification=classification, inference=inference, coverage=coverage,
        retention=retention, ownership=ownership, information=information,
        constraints=constraints, authorization=authorization_contract, stops=stops_list,
        live_absent=live_absent, all_registered_paths=all_registered_paths,
        doc_text=doc_text)

    document["registration_hash"] = _content_hash(document, hash_key="registration_hash")
    if events:
        raise RegistrationError(f"network events during offline build: {events}")
    return document


def classification_decision(design3: Mapping[str, Any]) -> Any:
    return (design3.get("classification") or {}).get("decision")


# --------------------------------------------------------------------------
# named build checks
# --------------------------------------------------------------------------

def _registration_checks(**ctx: Any) -> list[dict[str, Any]]:
    """Named checks evaluated against rebuilt values before emitting them."""

    root: Path = ctx["root"]
    frozen_inputs = ctx["frozen_inputs"]
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    check("registration_version_matches",
          REGISTRATION_VERSION == "jev-legal-p04-discovery-registration-v1",
          REGISTRATION_VERSION)
    check("frozen_input_digests_recompute_in_full",
          all(entry["prefix_match"] for entry in frozen_inputs),
          {entry["path"]: {"sha256": entry["sha256"], "prefix_length":
                           len(entry.get("expected_sha256_prefix") or "")}
           for entry in frozen_inputs})
    check("generator_sources_recomputed",
          len(ctx["source_inputs"]) == len(SOURCE_INPUTS)
          and all(entry["sha256"] for entry in ctx["source_inputs"]),
          {entry["path"]: entry["sha256"] for entry in ctx["source_inputs"]})
    check("l02_census_content_hash_recomputes",
          _content_hash(ctx["census_document"], hash_key="content_hash")
          == L02_CENSUS_CONTENT_HASH,
          {"recorded": L02_CENSUS_CONTENT_HASH})
    check("l03_design_content_hash_and_version_recompute",
          _content_hash(ctx["design3"], hash_key="content_hash") == L03_DESIGN_CONTENT_HASH
          and ctx["design3"].get("design_version") == "jev-legal-p03-design-v1",
          L03_DESIGN_CONTENT_HASH)
    check("l03_checks_all_pass_with_zero_network",
          ctx["design3_ok"] and ((ctx["design3"].get("network_audit") or {}).get("events") == 0
                                 and ((ctx["design3"].get("network_audit") or {})
                                      .get("provider_calls") == 0)),
          {"checks": len(ctx["design3_checks"])})
    check("l03_handoff_targets_this_task",
          ctx["design3_handoff"].get("to") == "L04" and ctx["design3_handoff"].get("issue") == 222,
          ctx["design3_handoff"].get("deliverable"))
    check("l03_decision_is_descriptive_discovery",
          classification_decision(ctx["design3"]) == "descriptive_discovery",
          classification_decision(ctx["design3"]))
    check("l03_recorded_input_hashes_recompute_from_disk",
          all(sha256_of(root / entry["path"]) == entry["sha256"]
              for entry in list(((ctx["design3"].get("input_evidence") or {}).get("inputs"))
                               or [])
              + list(((ctx["design3"].get("input_evidence") or {}).get("sources")) or [])),
          "every digest recorded by the L03 design recomputes from disk bytes")
    check("audit_227_content_hash_recomputes",
          audit227._content_hash(ctx["audit_artifact"]) == AUDIT_227_CONTENT_HASH,
          {"recorded": AUDIT_227_CONTENT_HASH,
           "recomputed": audit227._content_hash(ctx["audit_artifact"])})
    check("audit_227_pin_inputs_match_current_bytes",
          all(sha256_of(root / rel) == digest
              for rel, digest in (ctx["audit_artifact"].get("inputs_sha256") or {}).items()),
          "the #227 audit artifact's pinned inputs are byte-identical on disk")
    check("audit_227_grants_no_authorization_and_keeps_legal_descriptive",
          ctx["audit_artifact"].get("authorization") == AUDIT_227_AUTHORIZATION
          and ((ctx["audit_artifact"].get("breadth") or {}).get("design_limited") == ["legal:low"])
          and ((ctx["audit_artifact"].get("breadth") or {}).get("no_cross_family_pooling") is True)
          and "design backlog only" in str(((ctx["audit_artifact"].get("queue") or {})
                                            .get("status"))),
          {"authorization": ctx["audit_artifact"].get("authorization"),
           "design_limited": ((ctx["audit_artifact"].get("breadth") or {}).get("design_limited"))})
    check("l01_predecessor_checks_all_pass",
          bool(l01_evidence_checks(ctx)) and all(bool(entry.get("ok"))
                                                 for entry in l01_evidence_checks(ctx)),
          {"checks": len(l01_evidence_checks(ctx))})
    check("l01_records_no_route_registration_or_authorization_for_legal",
          ctx["l01_route_status"].get("registered") is False
          and ctx["l01_route_status"].get("authorized") is False
          and (((ctx["l01_evidence"].get("historical_facts") or {})
                .get("authorization_carried_into_legal_family")) is False),
          ctx["l01_route_status"].get("statement"))
    check("stopped_registration_control_hash_recomputes",
          _content_hash(ctx["stopped"], hash_key="registration_hash")
          == STOPPED_REGISTRATION_HASH,
          STOPPED_REGISTRATION_HASH)
    check("stopped_scope_digest_control_recomputes",
          ctx["stopped_auth"].get("scope_digest_sha256") == STOPPED_SCOPE_DIGEST,
          STOPPED_SCOPE_DIGEST)
    check("stopped_windows_never_reused_by_this_manifest",
          not any(any(low <= entry["seed"] <= high
                      for low, high in RESERVED_HYPOTHESIS_SPANS)
                  for entry in ctx["manifest"]["manifest"]),
          {"reserved_windows": [list(span) for span in RESERVED_HYPOTHESIS_SPANS],
           "registered_window": [DISCOVERY_WINDOW[0], DISCOVERY_WINDOW[1]]})
    check("status_is_draft_pending_review", DRAFT_STATUS == "draft_pending_review",
          DRAFT_STATUS)
    check("authorization_pending_with_separate_l07_gate",
          ctx["authorization"]["authorization_status"] == "pending"
          and ctx["authorization"]["separate_live_authorization_required_after_locking"]
          is True and ctx["authorization"]["route_authorized"] is False
          and ctx["authorization"]["l07_gate"]["issue"] == L07_GATE_ISSUE,
          ctx["authorization"]["status"])
    check("k_matches_generator_rebuild_and_census",
          len(ctx["form_ids"]) == 4 and sorted(ctx["scan"]) == sorted(ctx["form_ids"]),
          {"k": len(ctx["form_ids"]), "form_ids": ctx["form_ids"]})
    check("sign_flip_floor_recomputed_and_descriptive",
          ctx["classification"]["attainable_two_sided_sign_flip_floor"] == "0.125"
          and ctx["classification"]["floor_above_0_05"] is True
          and ctx["classification"]["decision_from_l03"] == "descriptive_discovery",
          ctx["classification"]["floor_derivation"])
    check("manifest_matches_generator",
          all(entry["prompt_form_id"] == rep.pre_read_form_id(rep.instance_for(
                  FAMILY, entry["seed"]))
              and entry["instance_id"] == rep.instance_for(
                  FAMILY, entry["seed"]).instance_id
              for entry in ctx["manifest"]["manifest"]),
          {"entries": len(ctx["manifest"]["manifest"]),
           "manifest_hash": ctx["manifest"]["manifest_hash"]})
    check("manifest_matches_l03_screen_exactly",
          ctx["screen"].get("manifest") == ctx["manifest"]["manifest"]
          and ctx["screen"].get("manifest_hash") == L03_SCREEN_MANIFEST_HASH
          and ctx["manifest"]["manifest_hash"] == L03_SCREEN_MANIFEST_HASH,
          ctx["manifest"]["manifest_hash"])
    check("manifest_inside_discovery_window_and_disjoint_from_prior",
          all(DISCOVERY_WINDOW[0] <= entry["seed"] <= DISCOVERY_WINDOW[1]
              for entry in ctx["manifest"]["manifest"])
          and not any(CLOSURE_PROBE_WINDOW[0] <= entry["seed"] <= CLOSURE_PROBE_WINDOW[1]
                      for entry in ctx["manifest"]["manifest"]),
          {"window": [DISCOVERY_WINDOW[0], DISCOVERY_WINDOW[1]],
           "closure_probe": list(CLOSURE_PROBE_WINDOW),
           "reserved": [list(span) for span in _reserved_seed_spans()]})
    check("closure_probe_window_never_selectable",
          ctx["manifest"]["closure_probe_window_unselectable"] is True,
          ctx["manifest"]["closure_probe_window"])
    check("held_out_window_not_registered",
          ctx["manifest"]["held_out_window"]["registered_here"] is False,
          ctx["manifest"]["held_out_window"]["statement"])
    check("outcome_blind_selection",
          ctx["manifest"]["outcome_blind"] is True
          and ctx["manifest"]["consulted_outcomes"] == [],
          ctx["manifest"]["selection_rule"])
    check("l4x_treatment_bytes_preserved",
          _treatment_matches_l4x(ctx["treatment"]),
          {"mode": ctx["treatment"]["mode"],
           "token_budget": ctx["treatment"]["writer_transport"]["token_budget"],
           "temperature": ctx["treatment"]["writer_transport"]["temperature"],
           "turns": ctx["treatment"]["turns"]})
    check("treatment_hash_recomputes",
          ctx["treatment"]["treatment_hash"] == legal_treatment_hash(
              ctx["treatment"], ctx["treatment"]["manifest_treatment_hash"],
              ctx["treatment"]["information_geometry_hash"])
          and ctx["treatment"]["manifest_treatment_hash"]
          == legal_manifest_treatment_hash(ctx["manifest"]["manifest"])
          and ctx["treatment"]["information_geometry_hash"]
          == information_geometry_hash(ctx["census_document"]),
          ctx["treatment"]["treatment_hash"])
    check("writer_output_policy_justified_by_l01",
          ctx["policy"]["max_tokens"] == 1024
          and ctx["policy"]["max_tokens"] == rep.LING_OUTPUT_TOKEN_CEILING
          and ctx["policy"]["justification_from_l01"]["diagnosis_stop_kind"]
          == "http_200_writer_output_cap"
          and ctx["policy"]["justification_from_l01"]["hypothesis_attempted_seeds"] == 1
          and bool(ctx["policy"]["justification_from_l01"]["no_counterfactual"])
          and any("truncated_output" in item
                  for item in ctx["policy"]["truncation_classification"])
          and (ctx["policy"]["truncation_policy"]
               ["truncated_output_is_a_registered_terminal_writer_error"]) is True
          and (ctx["policy"]["truncation_policy"]["no_automatic_budget_escalation"]) is True
          and (ctx["policy"]["truncation_policy"]["no_mid_run_repair"]) is True,
          ctx["policy"]["justification_from_l01"]["binding_constraint"])
    check("route_registered_first_time_with_authorization_pending",
          ctx["route"]["registered_by"] == REGISTRATION_VERSION
          and "no prior registered or authorized route"
          in ctx["route"]["registered_here_for_family"]
          and ctx["route"]["authorization"].startswith("pending")
          and bool(ctx["route"]["carries_nothing_forward"])
          and bool(ctx["route"]["independently_chosen_and_costed"]),
          ctx["route"]["registered_here_for_family"])
    check("ling_route_pins_match_registered_constants",
          (ctx["route"]["ling"]["model"] == prv7.PAID_LING_MODEL
           and ctx["route"]["ling"]["endpoint"] == pr.LING_ENDPOINT
           and ctx["route"]["ling"]["temperature"] == pr.LING_TEMPERATURE
           and ctx["route"]["ling"]["max_tokens"] == rep.LING_OUTPUT_TOKEN_CEILING
           and ctx["route"]["ling"]["min_attempt_interval_seconds"]
           == w3.LING_MIN_ATTEMPT_INTERVAL_SECONDS
           and ctx["route"]["ling"]["max_retries"] == w3.LING_MAX_RETRIES),
          ctx["route"]["ling"]["pacing"])
    check("jev_route_and_normalization_pins_match",
          (ctx["route"]["jev"]["model"] == pr.JEV_REPLAY_MODEL
           and ctx["route"]["jev"]["endpoint"] == pr.JEV_REPLAY_ENDPOINT
           and ctx["route"]["jev"]["protocol_key"] == prv4.prv6_protocol_key()
           and ctx["route"]["normalization"]["policy_hash"]
           == prv2.normalization_policy_hash()
           and ctx["route"]["normalization"]["hard_ceiling"] == 0.05),
          {"protocol_key": ctx["route"]["jev"]["protocol_key"],
           "normalization_policy": ctx["route"]["normalization"]["policy_hash"]})
    cost = ctx["budgets"]["cost_model"]
    check("cost_model_recomputes_from_rate_card",
          cost["ling_worst_physical_call_usd"]
          == round((rep.LING_INPUT_TOKEN_CEILING * rep.LING_PROMPT_USD_PER_MTOK
                    + rep.LING_OUTPUT_TOKEN_CEILING * rep.LING_COMPLETION_USD_PER_MTOK)
                   / 1_000_000, 12)
          and cost["jev_worst_physical_call_usd"]
          == round(rep.JEV_INPUT_TOKEN_CEILING * rep.JEV_INPUT_USD_PER_MTOK / 1_000_000, 12),
          cost)
    check("budget_arithmetic_carries_l03_selected_scenario",
          all(ctx["arithmetic_match"].values()) and ctx["selected"]["fixed_n"] == BLOCK_N,
          {"collection_usd": ctx["selected"]["collection"]["worst_case_cost_usd"],
           "replay_usd": ctx["selected"]["exploratory_replay"]["worst_case_cost_usd"],
           "program_usd": ctx["selected"]["program"]["worst_case_cost_usd"]})
    check("hard_ceilings_registered_and_worst_cases_fit",
          ctx["budgets"]["discovery_collection"]["within_hard_ceiling"] is True
          and ctx["budgets"]["exploratory_replay"]["within_hard_ceiling"] is True
          and ctx["budgets"]["program"]["within_hard_ceiling"] is True
          and ctx["budgets"]["program"]["hard_cost_ceiling_usd"] == 0.30,
          {stage: {"worst_case_cost_usd": ctx["budgets"][stage]["worst_case_cost_usd"],
                   "hard_cost_ceiling_usd": ctx["budgets"][stage]["hard_cost_ceiling_usd"]}
           for stage in ("discovery_collection", "exploratory_replay", "program")})
    check("physical_counting_is_retry_inclusive_and_paced",
          ctx["caps"]["discovery_collection"]["physical_combined_max"]
          == (BLOCK_N * WRITER_CALLS_PER_INSTANCE + BLOCK_N * RECEIVER_CALLS_PER_INSTANCE)
          * RETRY_MULTIPLIER
          and ctx["caps"]["exploratory_replay"]["physical_jev_max"]
          == BLOCK_N * REPLAY_BRANCHES * RETRY_MULTIPLIER
          and ctx["caps"]["program"]["physical_combined_max"] == 384
          and ctx["caps"]["pacing"]["ling_min_attempt_interval_seconds"]
          == w3.LING_MIN_ATTEMPT_INTERVAL_SECONDS
          and ctx["caps"]["reservation_rule"].startswith("stop before the next call"),
          {"collection": ctx["caps"]["discovery_collection"]["physical_combined_max"],
           "replay": ctx["caps"]["exploratory_replay"]["physical_jev_max"],
           "program": ctx["caps"]["program"]["physical_combined_max"]})
    check("terminal_stops_carry_the_l03_stop_list",
          ctx["stops"] == list(((ctx["design3"].get("stop_conditions") or {}).get("stops"))
                               or [])
          and any("truncated_output" in stop for stop in ctx["stops"])
          and any("two consecutive terminal provider failures" in stop
                  for stop in ctx["stops"])
          and any("output collision" in stop for stop in ctx["stops"]),
          {"stops": len(ctx["stops"])})
    check("coverage_rule_carries_l03_rule_verbatim",
          {key: value for key, value in ctx["coverage"].items() if key != "registered_here"}
          == dict(ctx["design3"].get("coverage_rule") or {}),
          ctx["coverage"]["registered_here"])
    check("coverage_freezes_missingness_before_collection",
          ctx["coverage"]["frozen_before_collection"] is True
          and ctx["coverage"]["no_imputation"] is True
          and ctx["coverage"]["no_seed_replacement"] is True
          and ctx["coverage"]["no_form_removal_after_outcomes"] is True
          and ctx["coverage"]["no_replenishment_from_spare_capacity"] is True
          and ctx["coverage"]["min_complete_per_form"] == 1,
          ctx["coverage"]["basis"])
    check("ownership_and_read_after_write_checks_registered",
          all(key in ctx["ownership"]
              for key in ("ownership_check", "accepted_write_requirements",
                          "read_after_write", "placebo_check",
                          "receiver_known_claims_excluded",
                          "one_deduplicated_informative_claim_per_state"))
          and "strictly greater than" in ctx["ownership"]["read_after_write"]["required"]
          and bool(ctx["ownership"]["every_failure_journaled"])
          and ctx["ownership"]["ownership_check"]["rejection_journaled"] is True,
          sorted(ctx["ownership"]))
    check("information_rules_recompute_from_census",
          ctx["information"]["real_claim_information_bits"] == [1.0]
          and ctx["information"]["placebo_inert_for_every_form"] is True
          and ctx["information"]["placebo_information_bits"] == 0.0
          and ctx["information"]["evaluator"]
          == "ExactInformationEvaluator (AcceptableInformationCheck)",
          ctx["information"]["real_claim_pin"])
    check("silence_and_failure_retention_registered",
          ctx["retention"]["retain_silences"] is True
          and ctx["retention"]["retain_failures"] is True
          and ctx["retention"]["retain_not_attempted_rows"] is True
          and "immutable journal" in str(ctx["retention"]["stop_semantics"]),
          ctx["retention"]["journal_row_contract"])
    check("paths_unique_fresh_absent_and_scoped",
          all(ctx["live_absent"].values())
          and ctx["engaged_paths"].isdisjoint({path for path in l02.HYPOTHESIS_OUTPUT_PATHS})
          and ctx["engaged_paths"].isdisjoint(set(rep.OWNED_PATHS))
          and ctx["engaged_paths"].isdisjoint({str(hyp_p04.REGISTRATION_PATH),
                                               str(STOPPED_AUTHORIZATION_PATH)})
          and len(ctx["all_registered_paths"]) == len(set(ctx["all_registered_paths"]))
          and all(path.startswith("runs/next-phase/legal/")
                  for path in ctx["engaged_paths"]),
          {"registered_paths": ctx["all_registered_paths"], "absent": ctx["live_absent"]})
    check("doc_pins_recomputed_input_hashes",
          bool(ctx["doc_text"]) and str(REGISTRATION_PATH) in ctx["doc_text"]
          and REGISTRATION_VERSION in ctx["doc_text"]
          and all(entry["sha256"] in ctx["doc_text"] for entry in frozen_inputs),
          {"doc": str(DOC_PATH),
           "digests": [entry["sha256"] for entry in frozen_inputs]})
    check("frozen_inputs_byte_identical_after_build",
          ctx["before"] == ctx["after"],
          "every frozen and source digest at the end equals the digest at the start")
    check("zero_network_events_under_audit_hook", not ctx["events"],
          {"events": list(ctx["events"]), "provider_calls": 0})
    return checks


def l01_evidence_checks(ctx: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return list((ctx["l01_evidence"].get("checks")) or [])  # type: ignore[arg-type]


def _treatment_matches_l4x(treatment: Mapping[str, Any]) -> bool:
    """The L4X treatment bytes that must hold unchanged for this family."""

    transport = treatment["writer_transport"]
    return (treatment["mode"] == "exact-original-comm-bridge"
            and treatment["rung"] == "L4X"
            and treatment["turns"] == 2
            and treatment["agents"] == ["A", "B"]
            and transport["token_budget"] == 1024
            and transport["temperature"] == 0.0
            and treatment["writer_prompt"]["output_grammar"].startswith("ANSWER:"))


# --------------------------------------------------------------------------
# document assembly
# --------------------------------------------------------------------------

def _document(**ctx: Any) -> dict[str, Any]:
    """Assemble the registration document from already-verified blocks."""

    return {
        "preregistration_version": REGISTRATION_VERSION,
        "registration_path": str(REGISTRATION_PATH),
        "status": DRAFT_STATUS,
        "stage": "legal:low discovery screen and optional exploratory replay",
        "issue": "#222",
        "milestone": "L04",
        "parent_issue": "#218",
        "root_issue": "#159",
        "predecessor_issue": "#221",
        "cross_family_audit_issue": "#227",
        "successor_issue": "#223",
        "family": FAMILY,
        "complexity": COMPLEXITY,
        "regime": REGIME,
        "protocol": str(PROTOCOL_PATH),
        "task_sequence": str(SEQUENCE_PATH),
        "program_amendment": str(PROGRAM_PATH),
        "offline_only": True,
        "authorizes": ("nothing beyond L05 planning; no provider call, no probe, no "
                       "collection, no registration lock, no live run; a failed or "
                       "stopped predecessor never authorizes a successor"),
        "provider_calls": 0,
        "reuse": ("every input is a hash-pinned read-only file; the stopped hypothesis "
                  "registration and authorization record are pinned as non-reuse "
                  "controls only; no field of this registration is an authorization"),
        "input_evidence": {"frozen_inputs": ctx["frozen_inputs"],
                           "source_pins": ctx["source_pins"]},
        "predecessor_chain": {
            "l01": {"path": str(L01_EVIDENCE_PATH),
                    "checks_recorded": len(l01_evidence_checks(ctx)),
                    "all_checks_pass": all(bool(entry.get("ok"))
                                           for entry in l01_evidence_checks(ctx))},
            "l02": {"path": str(L02_CENSUS_PATH), "content_hash": L02_CENSUS_CONTENT_HASH,
                    "content_hash_recomputes": True},
            "l03": {"path": str(L03_DESIGN_PATH), "content_hash": L03_DESIGN_CONTENT_HASH,
                    "content_hash_recomputes": True,
                    "decision": classification_decision(ctx["design3"]),
                    "checks_recorded": len(ctx["design3_checks"]),
                    "all_checks_pass": ctx["design3_ok"],
                    "handoff_to": [ctx["design3_handoff"].get("to"),
                                   ctx["design3_handoff"].get("issue")]},
            "audit_227": {"path": str(AUDIT_227_PATH),
                          "content_hash": AUDIT_227_CONTENT_HASH,
                          "content_hash_recomputes": True,
                          "authorization": AUDIT_227_AUTHORIZATION},
        },
        "cross_family_audit_consumption": {
            "issue": 227,
            "artifact": str(AUDIT_227_PATH),
            "doc": str(AUDIT_227_DOC_PATH),
            "content_hash": AUDIT_227_CONTENT_HASH,
            "used_for": ("program context only: prospective breadth inventory, per-family "
                         "cell classifications and generator-version scope, consumed "
                         "after approval as the #222 gate"),
            "carried_readings": {
                "audited_cells": "lexicon/poetry/reference x low-medium-high, all k = 4",
                "reference_high": "no_go under this source version (mod-3 form collisions)",
                "legal_status_per_audit": "design_limited: legal remains descriptive",
                "proposed_families": ("repository_repair and iterative_packing_research "
                                      "are proposals only, not runnable and not counted"),
                "windows": ("the audit reserved 90000-90511 and 91000-91511 for other "
                            "families; no legal window changes"),
            },
            "does_not": ["promote legal:low k = 4",
                         "authorize any call or route",
                         "count proposals toward the breadth target",
                         "mutate the L02 census or the L03 decision",
                         "supply a legal effect-size prior"],
        },
        "stopped_predecessor_non_reuse": {
            "pinned_controls": [
                {"path": str(STOPPED_REGISTRATION_PATH),
                 "role": "stopped hypothesis registration",
                 "content_hash": STOPPED_REGISTRATION_HASH},
                {"path": str(STOPPED_AUTHORIZATION_PATH),
                 "role": "stopped hypothesis authorization record",
                 "scope_digest_sha256": STOPPED_SCOPE_DIGEST},
            ],
            "not_reused": ["seed windows and manifest (this registration uses the L02 "
                           "window 88000-88511)",
                           "instance ids, output paths or any authorization",
                           "the historical registration, lock or scope as an "
                           "authorization",
                           "any positive or negative entropy result as a prior"],
            "statement": ("#207/#215 hypothesis facts stay historical; the paid "
                          "hypothesis route carries no authorization into legal:low and "
                          "no stopped-run budget leftover carries forward"),
        },
        "offline_tooling": dict(OFFLINE_WORKER_ROUTE),
        "design_classification": ctx["classification"],
        "fixed_n": {
            "instances_per_form": INSTANCES_PER_FORM,
            "form_count": ctx["manifest"]["form_count"],
            "block_n": BLOCK_N,
            "block": "discovery",
            "window": ctx["manifest"]["window"],
            "selection_rule": ctx["manifest"]["selection_rule"],
            "manifest": ctx["manifest"]["manifest"],
            "form_membership": ctx["manifest"]["form_membership"],
            "manifest_hash": ctx["manifest"]["manifest_hash"],
            "matches_l03_screen": True,
            "l03_screen_manifest_hash": ctx["screen"].get("manifest_hash"),
            "closure_probe_window_unselectable": True,
            "closure_probe_window": ctx["manifest"]["closure_probe_window"],
            "held_out_window": ctx["manifest"]["held_out_window"],
            "outcome_blind": True,
            "consulted_outcomes": [],
            "spare_capacity_note": ctx["screen"].get("capacity_note"),
        },
        "treatment": ctx["treatment"],
        "route": ctx["route"],
        "writer_output_policy": ctx["policy"],
        "budgets": ctx["budgets"],
        "request_caps": ctx["caps"],
        "stops": list(ctx["stops"]),
        "stop_semantics": (ctx["design3"].get("stop_conditions") or {}).get("semantics"),
        "paths": dict(PATHS),
        "path_lifecycle": {
            "fresh_paths": True,
            "resume": False,
            "append": False,
            "overwrite": False,
            "path_overrides": False,
            "all_registered_paths": ctx["all_registered_paths"],
            "rule": ("each phase writes only its own registered paths; a stopped run "
                     "requires a new registration, a new review and fresh paths before "
                     "any later attempt; the registration path itself is created once "
                     "and never overwritten"),
            "location_note": ("registered live outputs live under runs/next-phase/legal/ "
                              "(this chain's own namespace) so the frozen #200 scan "
                              "(runs/epic-126/**/*.json[l]) and every other chain's "
                              "namespace stay untouched; this matches the L02 census "
                              "walk excluding runs/next-phase/legal/"),
            "absent_at_build": ctx["live_absent"],
        },
        "ownership_and_exposure_checks": ctx["ownership"],
        "information_rules": ctx["information"],
        "coverage_rules": ctx["coverage"],
        "silence_and_failure_retention": ctx["retention"],
        "exploratory_replay": {
            "status": "optional; separately covered by the L07 authorization scope",
            "label": "exploratory; never confirmatory",
            "branches": ["real", "placebo", "null"],
            "real": ("the exact accepted B-owned claim for the pre-read state, bound per "
                     "instance as B's single owned private clue"),
            "placebo": ("controller-injected source-neutral re-presentation of a "
                        "receiver-already-known A clue with I_m = 0 and no feasible-set "
                        "reduction, same envelope as the real arm"),
            "null": "no message",
            "fixed_across_branches": ["receiver model", "option set", "wording", "target",
                                      "timing", "pre-read state C"],
            "only_difference": "state.visible_messages",
            "estimand": "equal-weight form mean of real-minus-placebo entropy",
            "inference": ("descriptive only; k = 4 floor 0.125 > 0.05, so no "
                          "significance-style claim is made"),
            "may_not_pool_with_held_out": True,
        },
        "inference_plan": ctx["inference"],
        "multiplicity": ctx["multiplicity"],
        "constraints": ctx["constraints"],
        "authorization": ctx["authorization"],
        "non_claims": ctx["non_claims"],
        "limitations": _limitations(),
        "deterministic_rebuild": {
            "builder": "src/apart_incident_response/jev_legal_p04_registration.py",
            "rebuild_command": "python -m apart_incident_response.jev_legal_p04_registration "
                               "--repo-root .",
            "byte_reproducible": True,
            "fail_closed_on_drift": True,
        },
        "handoff_to_l05": ctx["handoff"],
        "checks": ctx["checks_record"],
        "network_audit": {
            "hook": "sys.addaudithook(" + ", ".join(NETWORK_EVENT_PREFIXES) + ")",
            "events": len(ctx["events"]), "event_names": list(ctx["events"]),
            "provider_calls": 0,
        },
    }


def write_registration(document: Mapping[str, Any], *, repo_root: Path | str) -> Path:
    """Create the registration file once (open "x"); never overwrites."""

    target = Path(repo_root) / REGISTRATION_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        handle.write(_render(document))
    return target


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

def verify_registration(document: Mapping[str, Any],
                        *, repo_root: Path | str) -> dict[str, Any]:
    """Fail-closed verification: rebuild, compare byte-for-byte, run checks."""

    root = Path(repo_root)
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

    check("registration_version",
          document.get("preregistration_version") == REGISTRATION_VERSION,
          document.get("preregistration_version"))
    check("status_is_draft_pending_review", document.get("status") == DRAFT_STATUS,
          document.get("status"))
    check("registration_hash_matches",
          document.get("registration_hash")
          == _content_hash(document, hash_key="registration_hash"),
          document.get("registration_hash"))
    authorization_block = document.get("authorization") or {}
    check("authorization_pending",
          authorization_block.get("authorization_status") == "pending"
          and authorization_block.get(
              "separate_live_authorization_required_after_locking") is True
          and (authorization_block.get("l07_gate") or {}).get("issue") == L07_GATE_ISSUE,
          authorization_block.get("authorization_status"))

    try:
        rebuilt = build_registration(root)
        check("registration_rebuilds_byte_for_byte", rebuilt == document, None)
        check("registration_file_is_byte_reproducible",
              (root / REGISTRATION_PATH).read_text(encoding="utf-8") == _render(rebuilt),
              None)
        failed_rebuild = [entry["check"] for entry in rebuilt["checks"] if not entry["ok"]]
        check("rebuilt_registration_checks_all_pass", not failed_rebuild, failed_rebuild)
        for entry in rebuilt["checks"]:
            checks.append(dict(entry))
            if not entry["ok"]:
                errors.append(f"{entry['check']}: {entry['detail']}")
    except (RegistrationError, OSError, json.JSONDecodeError, KeyError) as exc:
        check("registration_rebuilds_byte_for_byte", False, f"{type(exc).__name__}: {exc}")

    classification = (document.get("design_classification") or {})
    check("classification_carries_l03_descriptive_decision",
          classification.get("decision_from_l03") == "descriptive_discovery"
          and classification.get("attainable_two_sided_sign_flip_floor") == "0.125",
          classification.get("decision_from_l03"))
    fixed_n = (document.get("fixed_n") or {})
    check("fixed_n_manifest_16_and_four_forms",
          fixed_n.get("block_n") == 16 and fixed_n.get("form_count") == 4
          and len(fixed_n.get("manifest") or []) == 16, fixed_n.get("block_n"))
    budgets_block = (document.get("budgets") or {})
    program = (budgets_block.get("program") or {})
    collection = (budgets_block.get("discovery_collection") or {})
    check("budget_arithmetic_within_registered_ceilings",
          program.get("worst_case_cost_usd", 1e9) <= program.get("hard_cost_ceiling_usd", 0.0)
          and collection.get("worst_case_cost_usd", 1e9)
          <= collection.get("hard_cost_ceiling_usd", 0.0),
          {"program": program.get("worst_case_cost_usd"),
           "collection": collection.get("worst_case_cost_usd")})
    paths = (document.get("paths") or {})
    live_paths = {key: value for key, value in paths.items() if key != "registration"}
    check("live_paths_absent",
          not any((root / path).exists() for path in live_paths.values()),
          sorted(path for path in live_paths.values() if (root / path).exists()))
    lifecycle = (document.get("path_lifecycle") or {})
    check("path_lifecycle_no_resume_no_replace",
          lifecycle.get("resume") is False and lifecycle.get("append") is False
          and lifecycle.get("overwrite") is False
          and lifecycle.get("path_overrides") is False, lifecycle.get("rule"))
    policy = (document.get("writer_output_policy") or {})
    check("writer_output_policy_registered",
          policy.get("max_tokens") == 1024
          and (policy.get("truncation_policy") or {}
               ).get("no_automatic_budget_escalation") is True
          and "no counterfactual" in str((policy.get("justification_from_l01") or {})
                                         .get("no_counterfactual")),
          policy.get("max_tokens"))
    check("offline_scope_recorded",
          document.get("offline_only") is True and document.get("provider_calls") == 0
          and "no provider call" in str(document.get("authorizes")),
          document.get("authorizes"))

    return {"mode": f"{REGISTRATION_VERSION}-verification", "ok": not errors,
            "errors": errors,
            "failed": [entry["check"] for entry in checks if not entry["ok"]],
            "checks": checks, "registration_hash": document.get("registration_hash"),
            "status": document.get("status"), "provider_calls": 0}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="L04 legal discovery registration (offline; deterministic rebuild; "
                    "zero provider calls)")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--build", action="store_true",
                        help="write the registration artifact to its fresh path "
                             "(never overwrites)")
    args = parser.parse_args(argv)
    root = (Path(args.repo_root) if args.repo_root is not None
            else Path(__file__).resolve().parents[2])

    if args.build:
        document = build_registration(root)
        write_registration(document, repo_root=root)
        print(json.dumps({"mode": REGISTRATION_VERSION, "status": document["status"],
                          "path": str(REGISTRATION_PATH),
                          "registration_hash": document["registration_hash"],
                          "checks_run": len(document["checks"]),
                          "failed": [entry["check"] for entry in document["checks"]
                                     if not entry["ok"]],
                          "provider_calls": 0}, indent=2, sort_keys=True))
        return 0

    path = root / REGISTRATION_PATH
    if not path.is_file():
        print(json.dumps({"mode": REGISTRATION_VERSION, "status": "missing",
                          "path": str(REGISTRATION_PATH), "provider_calls": 0},
                         indent=2, sort_keys=True))
        return 2
    verification = verify_registration(load_json(path), repo_root=root)
    print(json.dumps(verification, indent=2, sort_keys=True, allow_nan=False))
    return 0 if verification["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "REGISTRATION_VERSION", "REGISTRATION_PATH", "DOC_PATH", "DRAFT_STATUS",
    "FAMILY", "COMPLEXITY", "REGIME", "DISCOVERY_WINDOW", "CLOSURE_PROBE_WINDOW",
    "INSTANCES_PER_FORM", "BLOCK_N", "LIVE_PATHS", "PATHS", "OFFLINE_WORKER_ROUTE",
    "RESERVED_HYPOTHESIS_SPANS", "L02_CENSUS_CONTENT_HASH", "L03_DESIGN_CONTENT_HASH",
    "AUDIT_227_CONTENT_HASH", "STOPPED_REGISTRATION_HASH", "STOPPED_SCOPE_DIGEST",
    "L07_GATE_DOC", "L07_GATE_ISSUE", "FROZEN_INPUTS", "SOURCE_INPUTS",
    "L03_SCREEN_MANIFEST_HASH", "RegistrationError", "sha256_of", "load_json",
    "network_events", "legal_treatment", "legal_manifest_treatment_hash",
    "information_geometry_hash", "legal_treatment_hash", "legal_route",
    "writer_output_policy", "cost_model", "budgets", "request_caps",
    "ownership_and_exposure_checks", "information_rules", "coverage_rules",
    "silence_and_failure_retention", "discovery_manifest", "design_classification",
    "inference_plan", "multiplicity", "authorization", "non_claims", "handoff_to_l05",
    "build_registration", "write_registration", "verify_registration", "main",
]
