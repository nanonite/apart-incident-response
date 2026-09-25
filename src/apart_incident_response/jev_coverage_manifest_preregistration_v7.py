"""#191 review repair — v7 successor registration (paid Ling SKU, fresh paths).

Offline builder/verifier for the v7 coverage-manifest registration. v7 is the
successor to the v6 lock (628de647…) after the authorized v6 run stopped on
HTTP 404 for ``inclusionai/ling-3.0-flash-vl:free``, which the OpenRouter
routable catalog does not contain. v7:

- reuses the identical frozen 36-instance manifest (v6 produced no model
  output and no task outcome, so no outcome-based selection is introduced);
- switches only the Ling SKU to the paid ``inclusionai/ling-3.0-flash-vl``
  (same base OpenRouter model identifier and unchanged prompt protocol;
  provider routing or serving configuration may differ);
- freezes paid-route pricing from the catalog snapshot captured by the
  capped transport probe and recomputes the worst-case cost bound;
- requires the successful probe artifact and the catalog/availability gate
  before any live authorization;
- uses fresh v7 registration/journal/report paths; v6 outputs are pinned
  sha256 inputs, preserved unchanged.

``live_collection_authorized`` stays false; locking is not live
authorization and a new review must grant it explicitly. No API calls are
made by this module.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import behavioral_discovery as bd
from . import jev_choice as jc
from . import jev_coverage_manifest_preregistration_v6 as prv6
from . import jev_coverage_probe_v7 as probe
from . import jev_openrouter_catalog as catalog
from . import jev_replay_preregistration as pr
from . import task_families as tf
from .communication_protocol import DependenceRegime, ReasoningComplexity


COVERAGE_PREREG_VERSION = "stage2-jev-coverage-manifest-v7"
COVERAGE_DRAFT_STATUS = "draft_pending_review_v7"
COVERAGE_LOCKED_STATUS = "locked_for_jev_coverage_manifest_v7"

DEFAULT_OUTPUT_V7 = Path("runs/epic-126/jev-coverage-manifest-preregistration-v7.json")
DEFAULT_JOURNAL_V7 = Path("runs/epic-126/jev-coverage-manifest-v7.jsonl")
DEFAULT_REPORT_V7 = Path("runs/epic-126/jev-coverage-manifest-report-v7.json")
PROBE_PATH = "runs/epic-126/jev-ling-transport-probe-v7.json"

PAID_LING_MODEL = "inclusionai/ling-3.0-flash-vl"
PREVIOUS_LING_MODEL = "inclusionai/ling-3.0-flash-vl:free"

#: sha256 of the successful probe artifact (review repair item 5).
EXPECTED_PROBE_SHA256 = "06d22e8741ee490b93c7c6f78535c480f4f67a8f53f3ac1ca589f3d639abb534"

#: v6 predecessor lock and its preserved frozen outputs (commit 935bdbf).
V6_PREREGISTRATION_PATH = "runs/epic-126/jev-coverage-manifest-preregistration-v6.json"
V6_PREREGISTRATION_HASH = (
    "628de6470751c4361a626de362796f6f08066ac9970224eeb688914b523c16dd")
V6_PREREGISTRATION_SHA256 = "63be1ccbff954cd4c55be303d3a9569e592b336a976c6fcc824fb2fbcda1c9f5"
V6_JOURNAL_PATH = "runs/epic-126/jev-coverage-manifest-v6.jsonl"
V6_JOURNAL_SHA256 = "f5a7a0d8c1f54a0e65864ca3e2ba9589d22be3989639fa50b98202aaa1d6c364"
V6_REPORT_PATH = "runs/epic-126/jev-coverage-manifest-report-v6.json"
V6_REPORT_SHA256 = "a6f5253cbef7aa4534df3520aaa88a7e3918bb97903a3f2ff264013edb6b195c"

#: Frozen paid-route pricing (USD per million tokens) from the probe's
#: OpenRouter catalog snapshot; a live catalog re-fetch must agree.
LING_PROMPT_USD_PER_MTOK = probe.LING_PROMPT_USD_PER_MTOK          # 0.06
LING_COMPLETION_USD_PER_MTOK = probe.LING_COMPLETION_USD_PER_MTOK  # 0.18
#: Conservative Ling input ceiling: the runner does not enforce a prompt-size
#: bound, so the frozen cost model prices every Ling attempt at the same 8192
#: input-token ceiling used for Jev (the previous 4096 assumption was not
#: enforced anywhere and is intentionally retired).
LING_INPUT_TOKEN_CEILING = 8192
LING_OUTPUT_TOKEN_CEILING = 1024  # registered writer token budget
JEV_INPUT_USD_PER_MTOK = pr.JEV_REPLAY_INPUT_USD_PER_MTOK          # 0.042 (output free)
JEV_INPUT_TOKEN_CEILING = pr.JEV_REPLAY_INPUT_TOKEN_CEILING        # 8192
COST_CAP_USD = 1.0

LING_WORST_CALL_USD = round(
    (LING_INPUT_TOKEN_CEILING * LING_PROMPT_USD_PER_MTOK
     + LING_OUTPUT_TOKEN_CEILING * LING_COMPLETION_USD_PER_MTOK) / 1_000_000, 12)
LING_WORST_TOTAL_USD = round(LING_WORST_CALL_USD * prv6.LING_REQUEST_CAP, 9)
JEV_WORST_CALL_USD = round(JEV_INPUT_TOKEN_CEILING * JEV_INPUT_USD_PER_MTOK / 1_000_000, 12)
JEV_WORST_TOTAL_USD = round(JEV_WORST_CALL_USD * prv6.JEV_REQUEST_CAP, 9)
WORST_CASE_TOTAL_USD = round(LING_WORST_TOTAL_USD + JEV_WORST_TOTAL_USD, 9)
LING_NEXT_CALL_RESERVE_USD = round(
    LING_WORST_CALL_USD * (1 + pr.JEV_REPLAY_MAX_RETRIES), 12)
JEV_NEXT_CALL_RESERVE_USD = round(
    JEV_WORST_CALL_USD * (1 + pr.JEV_REPLAY_MAX_RETRIES), 12)

RUNNER_SOURCE_REL = "src/apart_incident_response/jev_coverage_bridge_v7.py"

#: v7-owned paths excluded from the prior-instance scan (self-output safety).
V7_OWNED_FILE_NAMES = frozenset({
    DEFAULT_OUTPUT_V7.name, DEFAULT_JOURNAL_V7.name, DEFAULT_REPORT_V7.name,
})
V7_OWNED_PATHS = (str(DEFAULT_OUTPUT_V7), str(DEFAULT_JOURNAL_V7), str(DEFAULT_REPORT_V7))

#: All prior registrations/artifacts pinned unchanged, including the v6 trio.
PRESERVED_INPUT_SHA256: dict[str, str] = {
    **{"runs/epic-126/jev-coverage-manifest-preregistration-v6.json":
       V6_PREREGISTRATION_SHA256,
       "runs/epic-126/jev-coverage-manifest-v6.jsonl": V6_JOURNAL_SHA256,
       "runs/epic-126/jev-coverage-manifest-report-v6.json": V6_REPORT_SHA256},
    PROBE_PATH: EXPECTED_PROBE_SHA256,
}

V7_SOURCE_FILES = (
    *prv6.COVERAGE_SOURCE_FILES,
    "src/apart_incident_response/jev_openrouter_catalog.py",
    "src/apart_incident_response/jev_coverage_probe_v7.py",
    "src/apart_incident_response/jev_coverage_manifest_preregistration_v7.py",
    "src/apart_incident_response/jev_coverage_bridge_v7.py",
)

_INSTANCE_ID_RE = re.compile(r"^planning-([0-9a-f]{8})$")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_files_hash(repo_root: Path) -> str:
    digest = hashlib.sha256()
    missing = []
    for relative in V7_SOURCE_FILES:
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
    return {"registration": str(DEFAULT_OUTPUT_V7), "journal": str(DEFAULT_JOURNAL_V7),
            "report": str(DEFAULT_REPORT_V7), "probe_input": PROBE_PATH,
            "audit_input": str(prv6.DEFAULT_AUDIT_V1)}


def cost_model() -> dict[str, Any]:
    """Frozen paid-route cost model with recomputable worst-case arithmetic."""

    return {
        "ling_provider": "openrouter",
        "ling_model": PAID_LING_MODEL,
        "ling_prompt_usd_per_mtok": LING_PROMPT_USD_PER_MTOK,
        "ling_completion_usd_per_mtok": LING_COMPLETION_USD_PER_MTOK,
        "ling_input_token_ceiling": LING_INPUT_TOKEN_CEILING,
        "ling_output_token_ceiling": LING_OUTPUT_TOKEN_CEILING,
        "ling_worst_call_usd": LING_WORST_CALL_USD,
        "ling_next_call_reserve_usd": LING_NEXT_CALL_RESERVE_USD,
        "jev_input_usd_per_mtok": JEV_INPUT_USD_PER_MTOK,
        "jev_output_usd_per_mtok": 0.0,
        "jev_input_token_ceiling": JEV_INPUT_TOKEN_CEILING,
        "jev_worst_call_usd": JEV_WORST_CALL_USD,
        "jev_next_call_reserve_usd": JEV_NEXT_CALL_RESERVE_USD,
        "ling_worst_total_usd": LING_WORST_TOTAL_USD,
        "jev_worst_total_usd": JEV_WORST_TOTAL_USD,
        "worst_case_total_usd": WORST_CASE_TOTAL_USD,
        "arithmetic": (
            f"Ling: {LING_INPUT_TOKEN_CEILING}x{LING_PROMPT_USD_PER_MTOK} + "
            f"{LING_OUTPUT_TOKEN_CEILING}x{LING_COMPLETION_USD_PER_MTOK} per Mtok = "
            f"{LING_WORST_CALL_USD}/call x {prv6.LING_REQUEST_CAP} = {LING_WORST_TOTAL_USD}; "
            f"Jev: {JEV_INPUT_TOKEN_CEILING}x{JEV_INPUT_USD_PER_MTOK} = {JEV_WORST_CALL_USD}/call "
            f"x {prv6.JEV_REQUEST_CAP} = {JEV_WORST_TOTAL_USD}; "
            f"total {WORST_CASE_TOTAL_USD} <= ceiling {COST_CAP_USD}"),
        "pricing_source": (f"OpenRouter catalog snapshot recorded in {PROBE_PATH} "
                           " (prompt 0.06 / completion 0.18 USD per Mtok); Jev rate is the "
                           "registered v1-v6 input rate with free output"),
        "note": ("the v1-v6 assumption of a free Ling route is NOT reused: paid prompt and "
                 "completion tokens are both priced for every Ling attempt"),
    }


def _is_v7_owned(path: Path) -> bool:
    return path.name in V7_OWNED_FILE_NAMES


def _prior_id_set_v7(root: Path) -> set[str]:
    """Prior instance ids, excluding v6- and v7-owned outputs (self-scan safety)."""

    excluded = prv6.V6_OWNED_FILE_NAMES | V7_OWNED_FILE_NAMES
    found: set[str] = set()
    id_pattern = re.compile(r'"instance_id":\s*"([^"]+)"')
    for pattern in prv6.PRIOR_SCAN_PATTERNS:
        for path in sorted(root.glob(pattern)):
            if path.name in excluded:
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
    for low, high in prv6.PRIOR_SEED_RANGES:
        for seed in range(low, high + 1):
            found.add(tf.generate_instance("planning", seed, DependenceRegime.N,
                                            ReasoningComplexity.LOW).instance_id)
    return found


def prior_instance_ids_v7(repo_root: Path | None = None) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    excluded = prv6.V6_OWNED_FILE_NAMES | V7_OWNED_FILE_NAMES
    sources: list[str] = []
    for pattern in prv6.PRIOR_SCAN_PATTERNS:
        for path in sorted(root.glob(pattern)):
            if path.name in excluded:
                continue
            sources.append(path.relative_to(root).as_posix())
    ordered = sorted(_prior_id_set_v7(root))
    return {"instance_id_count": len(ordered),
            "instance_ids_sha256": hashlib.sha256(
                json.dumps(ordered, sort_keys=True).encode("utf-8")).hexdigest(),
            "sources": sorted(set(sources)),
            "seed_ranges": [{"low": low, "high": high} for low, high in prv6.PRIOR_SEED_RANGES],
            "excluded": sorted([str(p) for p in prv6.V6_OWNED_PATHS] + list(V7_OWNED_PATHS)),
            "note": ("v6 and v7 owned registration/journal/report paths are excluded so this "
                     "evidence stays stable before and after the v7 outputs exist")}


def probe_binding(repo_root: Path | None = None) -> dict[str, Any]:
    """Verify the immutable probe artifact and derive its bound interpretation.

    The historical artifact is never modified (sha256 pinned). Its
    interpretation is registration-side: ``routing_success`` (HTTP 200, one
    attempt, no writer error) vs ``writer_output_validated`` (usable parsed
    writer output — false for the committed probe: finish_reason=length,
    empty_output). The approval basis is recorded accurately.
    """

    root = Path(repo_root) if repo_root is not None else _repo_root()
    path = root / PROBE_PATH
    if not path.is_file():
        raise ValueError("transport probe artifact missing")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != EXPECTED_PROBE_SHA256:
        raise ValueError(f"transport probe artifact hash drift: {actual}")
    document = json.loads(path.read_text(encoding="utf-8"))
    entries_raw = (document.get("catalog") or {}).get("entries")
    entries = entries_raw if isinstance(entries_raw, dict) else {}
    interpretation = probe.interpret_probe_artifact(document)
    if interpretation["routing_success"] is not True:
        raise ValueError("transport probe did not achieve routing success")
    if interpretation["writer_output_validated"] is not False:
        raise ValueError("probe artifact unexpectedly claims validated writer output")
    if document.get("model") != PAID_LING_MODEL:
        raise ValueError("transport probe used the wrong model")
    attempts = document.get("attempts") or {}
    if attempts.get("physical") != 1 or attempts.get("cap") != 1:
        raise ValueError("transport probe attempts are not within the single-attempt cap")
    frozen = document.get("pricing_frozen_usd_per_mtok") or {}
    if (frozen.get("prompt") != LING_PROMPT_USD_PER_MTOK
            or frozen.get("completion") != LING_COMPLETION_USD_PER_MTOK):
        raise ValueError("transport probe pricing differs from the frozen cost model")
    target = entries.get(PAID_LING_MODEL) or {}
    free = entries.get(PREVIOUS_LING_MODEL) or {}
    if (not isinstance(target, dict) or target.get("present") is not True
            or not isinstance(free, dict) or free.get("present") is not False):
        raise ValueError("transport probe catalog evidence drifted")
    outcome = document.get("outcome") or {}
    return {"artifact": PROBE_PATH, "sha256": actual, "probe_version": document.get("probe_version"),
            "model": PAID_LING_MODEL,
            "routing_success": True,
            "transport_success": True,
            "writer_output_validated": False,
            "probe_scope": probe.PROBE_SCOPE,
            "approval_basis": probe.APPROVAL_BASIS,
            "interpretation_note": ("registration-side interpretation of the immutable probe "
                                    "artifact; the artifact itself is never modified"),
            "original_outcome": {key: outcome.get(key) for key in
                                 ("outcome", "finish_reason", "parser_classification",
                                  "content_length", "error_class")},
            "attempts": {"physical": attempts.get("physical"), "cap": attempts.get("cap")},
            "pricing_usd_per_mtok": {"prompt": LING_PROMPT_USD_PER_MTOK,
                                     "completion": LING_COMPLETION_USD_PER_MTOK},
            "estimated_cost_usd": (document.get("cost") or {}).get("estimated_cost_usd"),
            "cost_ceiling_usd": (document.get("cost") or {}).get("cost_ceiling_usd"),
            "catalog": {"target_present": True, "free_sku_present": False,
                        "model_count": (document.get("catalog") or {}).get("model_count")},
            "scope": "nonexperimental_transport_probe; not experimental data",
            "required_before_live": True}


def _pinned_v6_base(repo_root: Path) -> dict[str, Any]:
    """Load the committed v6 registration by pinned sha256 as the v7 base.

    Deriving the base from the pinned artifact (instead of rebuilding v6)
    keeps v7 rebuilds deterministic: v6's own builder treats any newer file
    that carries the 36 manifest IDs — including the v7 registration itself —
    as a prior-instance overlap.
    """

    path = repo_root / V6_PREREGISTRATION_PATH
    if not path.is_file():
        raise ValueError("v6 registration missing")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != V6_PREREGISTRATION_SHA256:
        raise ValueError(f"v6 registration hash drift: {actual}")
    base = json.loads(path.read_text(encoding="utf-8"))
    if base.get("preregistration_hash") != V6_PREREGISTRATION_HASH:
        raise ValueError("v6 preregistration content hash drift")
    if base.get("manifest", {}).get("manifest_hash") != \
            "c4221e7db05fbdcba7b441099cb59d84147fa00d25569000ae2f416ca7233ad1":
        raise ValueError("v6 manifest hash drift")
    if base.get("status") != prv6.COVERAGE_LOCKED_STATUS:
        raise ValueError("v6 base registration is not locked")
    return base


def build_coverage_manifest_preregistration_v7(*, approved: bool = False,
                                               repo_root: Path | None = None) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    if RUNNER_SOURCE_REL not in V7_SOURCE_FILES:
        raise ValueError("runner module missing from V7_SOURCE_FILES")
    probe_record = probe_binding(root)
    base = _pinned_v6_base(root)
    document = copy.deepcopy(base)

    if base["manifest"]["manifest_hash"] != \
            "c4221e7db05fbdcba7b441099cb59d84147fa00d25569000ae2f416ca7233ad1":
        raise ValueError("v6 manifest hash drifted; v7 must reuse the exact v6 manifest")

    document["preregistration_version"] = COVERAGE_PREREG_VERSION
    document["status"] = COVERAGE_LOCKED_STATUS if approved else COVERAGE_DRAFT_STATUS
    document["approval_required"] = not approved
    document["approval"] = ({"approved": True, "approved_by": "offline-registration-lock",
                             "scope": "v7_registration_lock_only",
                             "live_collection_authorized": False}
                            if approved else
                            {"approved": False, "live_collection_authorized": False})
    document["stage"] = "planning-low-six-form-coverage-v7"
    document["pending_decisions"] = [
        "reviewer review of this v7 successor (paid ling SKU, frozen pricing, probe binding)",
        "new explicit live authorization required after this review; the successful probe "
        "does not authorize collection",
    ] + ([] if approved else ["reviewer lock of this v7 registration (offline only)"])
    document["purpose"] = (
        "successor coverage registration after the v6 run stopped on HTTP 404 for the "
        "unrouteable free ling SKU: same frozen 36-instance manifest, paid same-model SKU, "
        "catalog/availability gate and capped transport probe required before live review")

    document["successor_of"] = {
        **{key: value for key, value in base.get("successor_of", {}).items()
           if key in ("v1", "v2", "v3", "v4", "v5", "frozen_audit", "immutable")},
        "v6_registration": {"path": V6_PREREGISTRATION_PATH,
                            "preregistration_hash": V6_PREREGISTRATION_HASH,
                            "sha256": V6_PREREGISTRATION_SHA256},
        "v6_frozen_outputs": {
            "journal": {"path": V6_JOURNAL_PATH, "sha256": V6_JOURNAL_SHA256},
            "report": {"path": V6_REPORT_PATH, "sha256": V6_REPORT_SHA256},
            "result": ("registered stop at writer HTTP 404; no model output, no task outcome; "
                       "preserved byte-identical and never appended to")},
        "note": ("v1-v6 registrations and the v6 live outputs are never modified, resumed, "
                 "appended to, pooled with, or reinterpreted; v7 uses fresh paths only"),
    }

    document["manifest"] = {
        **base["manifest"],
        "manifest_reuse_justification": (
            "v6 produced no model output and no task outcome (registered stop at writer HTTP 404 "
            "before any message, exposure, or Jev call), so reusing the identical 36-instance "
            "manifest introduces no outcome-based selection; instance IDs, order, seeds, form "
            "membership and manifest hash are unchanged"),
        "reused_from": V6_PREREGISTRATION_PATH,
    }
    document["manifest"]["disjointness"] = {
        "ok": True, "overlap": [],
        "prior_instance_ids": prior_instance_ids_v7(root),
        "frozen_block_first_id": "planning-00011940",
        "frozen_block_last_id": "planning-00011950",
    }

    document["model_and_protocol"] = {
        **base["model_and_protocol"],
        "ling_model": PAID_LING_MODEL,
        "ling_previous_model": PREVIOUS_LING_MODEL,
        "ling_model_change_note": (
            "v6 was registered on inclusionai/ling-3.0-flash-vl:free, which is absent from "
            "OpenRouter's routable catalog and returned HTTP 404; v7 uses the paid "
            "inclusionai/ling-3.0-flash-vl: same base OpenRouter model identifier and "
            "unchanged prompt protocol; provider routing or serving configuration may "
            "differ. v7 findings are conditional on the paid route and must not "
            "automatically be pooled with free-route behavioral rates. No prompt, seed, "
            "grammar, pacing, cap or manifest change is made"),
    }
    document["transport_probe"] = probe_record
    document["catalog_gate"] = {
        "module": "apart_incident_response.jev_openrouter_catalog",
        "catalog_url": catalog.CATALOG_URL,
        "required_before_live": True,
        "live_recheck_required": True,
        "recorded_from_probe": probe_record["catalog"],
        "note": ("read-only catalog lookup before any experimental collection: the target "
                 "paid SKU must be present with positive pricing; free-SKU absence is the "
                 "recorded v6 root-cause diagnostic"),
    }
    document["model_routing_repair"] = {
        "root_cause": ("the free SKU inclusionai/ling-3.0-flash-vl:free was absent from "
                       "OpenRouter's routable catalog while its public model page still "
                       "advertised it, producing HTTP 404 on the first writer call"),
        "evidence": [PROBE_PATH,
                     "runs/epic-126/jev-coverage-manifest-report-v6.json"],
        "resolution": ("route the same base OpenRouter model identifier via the paid "
                       "inclusionai/ling-3.0-flash-vl SKU; provider routing or serving "
                       "configuration may differ from the free route"),
        "treatment_drift": ("same base OpenRouter model identifier and unchanged prompt "
                            "protocol; provider routing or serving configuration may differ. "
                            "v7 findings are conditional on the paid route and must not "
                            "automatically be pooled with free-route behavioral rates; "
                            "alternatives with other models were rejected as larger drift"),
        "rejected_alternatives": "switching to a different vendor/model family",
    }

    document["caps"] = {
        **base["caps"],
        "cost_model": cost_model(),
        "worst_case_ling_usd": LING_WORST_TOTAL_USD,
        "worst_case_jev_usd": JEV_WORST_TOTAL_USD,
        "worst_case_call_cost_usd": LING_WORST_CALL_USD,
        "worst_case_cost_usd": WORST_CASE_TOTAL_USD,
        "worst_case_arithmetic": cost_model()["arithmetic"],
        "cost_cap_usd": COST_CAP_USD,
        "input_token_ceiling": JEV_INPUT_TOKEN_CEILING,
        "input_usd_per_mtok": JEV_INPUT_USD_PER_MTOK,
        "status": ("locked; live_collection_authorized=false" if approved
                   else "draft; not authorized"),
    }
    document["outputs"] = output_paths()
    document["generator"] = {
        **base["generator"],
        "source_files": list(V7_SOURCE_FILES),
        "source_files_hash": _source_files_hash(root),
    }
    document["runner_policy"] = {
        "required_before_live": True,
        "runner_implemented": True,
        "runner_source_files": [RUNNER_SOURCE_REL],
        "runner_source_bound": RUNNER_SOURCE_REL in V7_SOURCE_FILES,
        "probe_required": {"artifact": PROBE_PATH, "sha256": EXPECTED_PROBE_SHA256,
                           "success_required": True},
        "catalog_gate_required": True,
        "policy": (f"the v7 coverage runner is implemented in {RUNNER_SOURCE_REL} and included "
                   "in V7_SOURCE_FILES; the transport probe must succeed and the catalog gate "
                   "must pass before live collection; this lock still does not authorize "
                   "collection"),
        "adding_runner_authorizes_collection": False,
        "live_execution_rule": (
            "live execution is forbidden until a new review grants explicit live authorization "
            "referencing this v7 lock, after the transport probe succeeded and the catalog "
            "gate passes; this lock is not live authorization"),
        "predecessor_lock": {"preregistration_hash": V6_PREREGISTRATION_HASH,
                             "note": ("v6 runner-bound lock; superseded by this v7 successor "
                                      "while the v6 outputs remain frozen")},
    }
    document["preserved_inputs"] = dict(PRESERVED_INPUT_SHA256)
    document["claim_scope"] = {
        **base["claim_scope"],
        "v7_addendum": ("paid-SKU routing repair only: the reused manifest carries no v6 model "
                        "output or task outcome, so no outcome-based selection exists; k "
                        "remains six forms"),
    }

    payload = json.dumps({key: value for key, value in document.items()
                          if key != "preregistration_hash"}, sort_keys=True)
    document["preregistration_hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return document


def verify_against_coverage_manifest_preregistration_v7(
        document: Mapping[str, Any], *, repo_root: Path | None = None,
        model: str | None = None, endpoint: str | None = None,
        protocol_key: str | None = None, check_credentials: bool = False,
        ling_key_present: bool | None = None, check_catalog: bool = False,
        catalog_document: Mapping[str, Any] | None = None,
        journal_exists: bool | None = None, report_exists: bool | None = None,
        require_approval: bool = True) -> dict[str, Any]:
    """Repository-backed v7 verifier; fails closed on any registered drift."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    errors: list[str] = []

    if document.get("preregistration_version") != COVERAGE_PREREG_VERSION:
        errors.append("wrong registration version")
    if document.get("status") != COVERAGE_LOCKED_STATUS:
        errors.append("registration is not locked for the coverage manifest v7")
    if require_approval and (document.get("approval_required")
                             or not document.get("approval", {}).get("approved")):
        errors.append("registration lock approval is missing")
    if document.get("approval", {}).get("scope") != "v7_registration_lock_only":
        errors.append("approval scope is not the v7 registration lock")
    if document.get("approval", {}).get("live_collection_authorized") is not False:
        errors.append("lock must not authorize live collection")
    if document.get("live_collection_authorized") is not False:
        errors.append("live_collection_authorized must be false")
    if document.get("lock_is_not_live_authorization") is not True:
        errors.append("lock-is-not-live-authorization declaration missing")
    if document.get("resume_permitted", False) is not False:
        errors.append("resume must not be permitted")

    try:
        expected = build_coverage_manifest_preregistration_v7(approved=True, repo_root=root)
    except Exception as exc:  # fail closed: drift or missing inputs
        errors.append(f"rebuild_failed: {type(exc).__name__}: {exc}")
        expected = None
    if expected is not None:
        if document.get("preregistration_hash") != expected.get("preregistration_hash"):
            errors.append("registration hash drift from the repository state")
        recorded = {key: value for key, value in document.items()
                    if key != "preregistration_hash"}
        wanted = {key: value for key, value in expected.items()
                  if key != "preregistration_hash"}
        if recorded != wanted:
            errors.append("registration content drift from the repository state")
        generator = document.get("generator", {})
        expected_generator = expected.get("generator", {})
        for key, label in (("source_files_hash", "source hash"),
                           ("manifest_treatment_hash", "manifest treatment hash"),
                           ("information_geometry_hash", "information geometry hash")):
            if generator.get(key) != expected_generator.get(key):
                errors.append(f"{label} drift from the repository state")
        try:
            if generator.get("source_files_hash") != _source_files_hash(root):
                errors.append("source hash does not match the checked-out sources")
        except ValueError as exc:
            errors.append(f"source hash unavailable: {exc}")

    manifest = document.get("manifest", {})
    instance_ids = [str(item) for item in manifest.get("instance_ids", [])]
    if len(instance_ids) != prv6.BLOCK_N or len(set(instance_ids)) != prv6.BLOCK_N:
        errors.append(f"manifest must contain {prv6.BLOCK_N} unique instance ids")
    if manifest.get("manifest_hash") != \
            "c4221e7db05fbdcba7b441099cb59d84147fa00d25569000ae2f416ca7233ad1":
        errors.append("manifest hash differs from the frozen v6 manifest hash")
    if manifest.get("reused_from") != V6_PREREGISTRATION_PATH:
        errors.append("manifest reuse source missing")
    if "no outcome-based selection" not in str(manifest.get("manifest_reuse_justification", "")):
        errors.append("manifest reuse justification missing")
    form_counts = manifest.get("form_counts", {})
    if set(form_counts) != set(prv6.FROZEN_FORM_IDS) or any(
            form_counts.get(form) != prv6.INSTANCES_PER_FORM for form in prv6.FROZEN_FORM_IDS):
        errors.append("manifest must hold exactly six instances per frozen form")
    disjointness = manifest.get("disjointness", {})
    if disjointness.get("ok") is not True or disjointness.get("overlap"):
        errors.append("recorded disjointness evidence is not clean")
    if set(instance_ids) & _prior_id_set_v7(root):
        errors.append("manifest overlaps prior instance ids")

    protocol = document.get("model_and_protocol", {})
    if protocol.get("ling_model") != PAID_LING_MODEL:
        errors.append("ling model must be the paid inclusionai/ling-3.0-flash-vl")
    if protocol.get("ling_previous_model") != PREVIOUS_LING_MODEL:
        errors.append("previous ling model record missing")
    if protocol.get("model") != pr.JEV_REPLAY_MODEL:
        errors.append("wrong Jev model")
    if protocol.get("endpoint") != pr.JEV_REPLAY_ENDPOINT:
        errors.append("wrong Jev endpoint")
    if model is not None and model != protocol.get("model"):
        errors.append("runtime model differs from the registration")
    if endpoint is not None and endpoint != protocol.get("endpoint"):
        errors.append("runtime endpoint differs from the registration")
    key = str(protocol_key or protocol.get("protocol_key", ""))
    if not key or jc.is_jev_protocol_key(key):
        errors.append("protocol key is missing or a v1 key")
    elif not jc2_is_v2(key) or key != prv6.protocol_key_v6():
        errors.append("protocol key is not the registered v2 Jev key")
    if protocol_key is not None and protocol_key != protocol.get("protocol_key"):
        errors.append("runtime protocol key differs from the registration")

    frozen_cost = document.get("caps", {}).get("cost_model", {})
    if frozen_cost != cost_model():
        errors.append("cost model drift from the frozen paid-route pricing")
    caps = document.get("caps", {})
    if caps.get("worst_case_cost_usd") != WORST_CASE_TOTAL_USD:
        errors.append("worst-case cost drift")
    if float(caps.get("worst_case_cost_usd", 1e9)) > float(caps.get("cost_cap_usd", 0.0)):
        errors.append("worst-case cost exceeds the cost ceiling")
    if caps.get("cost_cap_usd") != COST_CAP_USD:
        errors.append("cost ceiling drift")
    planned = caps.get("planned_calls", {})
    partition = caps.get("provider_partition", {})
    if (planned.get("ling"), planned.get("jev"), planned.get("combined")) != (144, 36, 180):
        errors.append("planned call arithmetic drift (expected 144/36/180)")
    if (partition.get("ling"), partition.get("jev"), partition.get("total")) != (432, 108, 540):
        errors.append("provider partition drift (expected 432/108/540)")

    outputs = document.get("outputs", {})
    if outputs != output_paths():
        errors.append("output paths differ from the fresh v7 paths")
    for old in (*prv6.OLD_OUTPUT_PATHS_V6, V6_PREREGISTRATION_PATH, V6_JOURNAL_PATH,
                V6_REPORT_PATH):
        if any(old in str(value) for value in outputs.values()):
            errors.append(f"old v1-v6 output path rejected: {old}")
    journal_path = root / str(outputs.get("journal", DEFAULT_JOURNAL_V7))
    report_path = root / str(outputs.get("report", DEFAULT_REPORT_V7))
    journal_bad = journal_exists if journal_exists is not None else journal_path.exists()
    report_bad = report_exists if report_exists is not None else report_path.exists()
    if journal_bad:
        errors.append("future coverage journal already exists")
    if report_bad:
        errors.append("future coverage report already exists")

    probe_record = document.get("transport_probe", {})
    if probe_record.get("sha256") != EXPECTED_PROBE_SHA256:
        errors.append("probe binding sha256 drift")
    if probe_record.get("routing_success") is not True:
        errors.append("probe binding must record routing_success true")
    if probe_record.get("writer_output_validated") is not False:
        errors.append("probe must not claim validated writer output")
    if probe_record.get("model") != PAID_LING_MODEL:
        errors.append("probe binding model drift")
    if probe_record.get("attempts", {}).get("physical") != 1:
        errors.append("probe attempts are not within the single-attempt cap")
    if probe_record.get("probe_scope") != probe.PROBE_SCOPE:
        errors.append("probe scope drift")
    if probe_record.get("approval_basis") != probe.APPROVAL_BASIS:
        errors.append("probe approval basis drift")
    try:
        derived = probe_binding(root)
        for key in ("sha256", "routing_success", "writer_output_validated",
                    "probe_scope", "approval_basis", "attempts", "pricing_usd_per_mtok",
                    "catalog", "original_outcome"):
            if probe_record.get(key) != derived.get(key):
                errors.append(f"probe binding differs from derived interpretation: {key}")
                break
    except ValueError as exc:
        errors.append(f"probe artifact invalid: {exc}")

    gate_record = document.get("catalog_gate", {})
    if gate_record.get("required_before_live") is not True:
        errors.append("catalog gate requirement missing")
    recorded = gate_record.get("recorded_from_probe", {})
    if recorded.get("target_present") is not True:
        errors.append("recorded catalog evidence lacks the target SKU")
    if check_catalog:
        try:
            fetched = catalog_document if catalog_document is not None \
                else catalog.fetch_model_catalog()
        except Exception as exc:
            errors.append(f"catalog fetch failed: {type(exc).__name__}: {exc}")
            fetched = None
        if fetched is not None:
            gate = catalog.catalog_availability_gate(PAID_LING_MODEL, catalog=fetched)
            if not gate["ok"]:
                errors.append(f"live catalog gate failed: {gate['failed']}")
            entry = gate["diagnostics"]["target_entry"]
            prompt_tok = catalog.positive_rate(entry.get("prompt_usd_per_tok"))
            completion_tok = catalog.positive_rate(entry.get("completion_usd_per_tok"))
            prompt_rate = prompt_tok * 1_000_000 if prompt_tok is not None else None
            completion_rate = completion_tok * 1_000_000 if completion_tok is not None else None
            if (prompt_rate != LING_PROMPT_USD_PER_MTOK
                    or completion_rate != LING_COMPLETION_USD_PER_MTOK):
                errors.append("live catalog pricing drift from the frozen cost model")

    runner_policy = document.get("runner_policy", {})
    if runner_policy.get("required_before_live") is not True:
        errors.append("runner policy missing")
    if runner_policy.get("runner_implemented") is not True:
        errors.append("runner must be implemented and source-bound in this lock")
    if runner_policy.get("runner_source_files") != [RUNNER_SOURCE_REL]:
        errors.append("runner source file mismatch")
    if runner_policy.get("runner_source_bound") is not True:
        errors.append("runner source binding declaration missing")
    if RUNNER_SOURCE_REL not in V7_SOURCE_FILES:
        errors.append("runner module missing from V7_SOURCE_FILES")
    if runner_policy.get("adding_runner_authorizes_collection") is not False:
        errors.append("adding the runner must not authorize collection")
    if "live execution is forbidden" not in str(runner_policy.get("live_execution_rule", "")):
        errors.append("live-execution rule missing")
    if runner_policy.get("probe_required", {}).get("sha256") != EXPECTED_PROBE_SHA256:
        errors.append("runner policy probe binding drift")
    if runner_policy.get("catalog_gate_required") is not True:
        errors.append("runner policy catalog gate requirement missing")
    predecessor = runner_policy.get("predecessor_lock", {})
    if predecessor.get("preregistration_hash") != V6_PREREGISTRATION_HASH:
        errors.append("predecessor v6 lock hash missing or drifted")

    preserved = document.get("preserved_inputs", {})
    if preserved != PRESERVED_INPUT_SHA256:
        errors.append("preserved input pin list drift")
    else:
        for relative, expected_sha in PRESERVED_INPUT_SHA256.items():
            path = root / relative
            actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            if actual != expected_sha:
                errors.append(f"preserved input unchanged check failed: {relative}")

    if check_credentials:
        credentials = jc.load_jev_credentials()
        if not (credentials.present and credentials.shape_ok):
            errors.append("jev credentials missing for the proposed live preflight")
        ling_ok = bd._api_key() is not None if ling_key_present is None else bool(ling_key_present)
        if not ling_ok:
            errors.append("ling credentials missing for the proposed live preflight")

    return {"ok": not errors, "errors": errors,
            "registration_hash": document.get("preregistration_hash"),
            "manifest_hash": manifest.get("manifest_hash"),
            "planned_requests": prv6.PLANNED_REQUESTS,
            "request_cap": prv6.COMBINED_REQUEST_CAP,
            "live_collection_authorized": False}


def jc2_is_v2(key: str) -> bool:
    from . import jev_choice_v2 as jc2
    return jc2.is_jev_v2_protocol_key(key)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="#191 repair: v7 coverage preregistration")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_V7)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--approve", action="store_true",
                        help="write the locked registration (offline lock, never live "
                             "authorization)")
    args = parser.parse_args(argv)
    document = build_coverage_manifest_preregistration_v7(approved=args.approve,
                                                          repo_root=args.repo_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
                           encoding="utf-8")
    verification = verify_against_coverage_manifest_preregistration_v7(
        document, repo_root=args.repo_root)
    print(json.dumps({
        "preregistration_version": document["preregistration_version"],
        "status": document["status"],
        "live_collection_authorized": document["live_collection_authorized"],
        "manifest_hash": document["manifest"]["manifest_hash"],
        "ling_model": document["model_and_protocol"]["ling_model"],
        "worst_case_cost_usd": document["caps"]["worst_case_cost_usd"],
        "cost_cap_usd": document["caps"]["cost_cap_usd"],
        "probe_routing_success": document["transport_probe"]["routing_success"],
        "probe_writer_output_validated": document["transport_probe"]["writer_output_validated"],
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
    "DEFAULT_OUTPUT_V7", "DEFAULT_JOURNAL_V7", "DEFAULT_REPORT_V7", "PROBE_PATH",
    "PAID_LING_MODEL", "PREVIOUS_LING_MODEL", "EXPECTED_PROBE_SHA256",
    "V6_PREREGISTRATION_PATH", "V6_PREREGISTRATION_HASH", "V6_PREREGISTRATION_SHA256",
    "V6_JOURNAL_PATH", "V6_JOURNAL_SHA256", "V6_REPORT_PATH", "V6_REPORT_SHA256",
    "LING_PROMPT_USD_PER_MTOK", "LING_COMPLETION_USD_PER_MTOK",
    "LING_INPUT_TOKEN_CEILING", "LING_OUTPUT_TOKEN_CEILING", "COST_CAP_USD",
    "LING_WORST_CALL_USD", "LING_WORST_TOTAL_USD", "JEV_WORST_TOTAL_USD",
    "WORST_CASE_TOTAL_USD", "LING_NEXT_CALL_RESERVE_USD", "JEV_NEXT_CALL_RESERVE_USD",
    "RUNNER_SOURCE_REL", "V7_OWNED_FILE_NAMES", "V7_OWNED_PATHS",
    "PRESERVED_INPUT_SHA256", "V7_SOURCE_FILES", "output_paths", "cost_model",
    "prior_instance_ids_v7", "_prior_id_set_v7", "probe_binding",
    "build_coverage_manifest_preregistration_v7",
    "verify_against_coverage_manifest_preregistration_v7", "main",
]
