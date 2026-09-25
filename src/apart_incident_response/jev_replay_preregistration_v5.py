"""#197 — replay-v5 matched Jev replay registration (successor to replay-v4).

Builds a fresh, fail-closed registration for a new matched real/placebo/null
Jev replay attempt after the authorized replay-v4 run stopped on
``provider_failure_limit`` with its registered outputs now occupied.

Design rules:

- **Nothing scientific changes.** The 17-event manifest, six-form scope, B→A
  real branch, placebo and null branches, counterbalanced branch schedule,
  estimand, guards, missingness and inference blocks are derived from the v4
  builder and asserted byte-identical, except for the enumerated v5 keys
  (paths, supersession, operational policy, runner binding, hashes).
- **v4 is immutable historical state.** Its registration, journal and report
  hashes are pinned and re-verified on every build and verification; v5 never
  resumes, appends to, overwrites, pools or reinterprets them.
- **Locking is not authorization.** ``live_collection_authorized`` stays false;
  live execution needs a separate reviewer authorization reference.

Verification is repository-backed and fail-closed: fresh output paths, exact
manifest and event order, branch request/state hashes, model/endpoint/codec/
protocol/normalization pins, caps with retry-inclusive cost reservation,
source/treatment hashes, no mixed protocols, no stale registration hash, and
optional credential presence (never printed).
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from . import jev_choice as jc
from . import jev_choice_v2 as jc2
from . import jev_replay as jr
from . import jev_replay_preregistration as pr
from . import jev_replay_preregistration_v2 as prv2
from . import jev_replay_preregistration_v4 as prv4


JEV_REPLAY_V5_PREREG_VERSION = "stage2-jev-choice-replay-v5"
JEV_REPLAY_V5_LOCKED_STATUS = "locked_for_jev_choice_replay_v5"
JEV_REPLAY_V5_DRAFT_STATUS = "draft_pending_review_v5"
REPLAY_RUNNER_VERSION_V5 = "jev-choice-replay-runner-v5"

DEFAULT_OUTPUT_V5 = Path("runs/epic-126/replay-v5/jev-choice-replay-preregistration-v5.json")
DEFAULT_JOURNAL_V5 = Path("runs/epic-126/replay-v5/jev-choice-replay-v5.jsonl")
DEFAULT_REPORT_V5 = Path("runs/epic-126/replay-v5/jev-choice-replay-report-v5.json")
OLD_OUTPUT_PATHS_V5 = (
    str(prv4.DEFAULT_OUTPUT_V4), str(prv4.DEFAULT_JOURNAL_V4),
    str(prv4.DEFAULT_REPORT_V4),
) + tuple(prv4.OLD_OUTPUT_PATHS_V4)

RUNNER_SOURCE_REL_V5 = "src/apart_incident_response/jev_replay_runner_v5.py"
RUNNER_SOURCE_REL_V4 = prv4.RUNNER_SOURCE_REL
AMENDED_BY_TASK = "#197"

#: Bounded inter-attempt pacing for the Jev transport. See operational_policy
#: for the arithmetic justification; retry counts, statuses and caps are unset.
BACKOFF_V5 = {"initial_seconds": 2.0, "max_seconds": 10.0, "jitter": 0.25}
BACKOFF_V4 = {"initial_seconds": 0.5, "max_seconds": 5.0, "jitter": 0.25}
BACKOFF_V5_WINDOW_SECONDS = 6.0     # 2.0 + 4.0 across three physical attempts
BACKOFF_V4_WINDOW_SECONDS = 1.5     # 0.5 + 1.0 across three physical attempts

#: Immutable historical inputs: the stopped replay-v4 artifacts.
V4_PINS = {
    "registration": {"path": str(prv4.DEFAULT_OUTPUT_V4),
                     "sha256": "5ea64f8218ed1ddabb2cab5a081dea666e686683a2a67ea9a186a9409ea40ee2"},
    "journal": {"path": str(prv4.DEFAULT_JOURNAL_V4),
                "sha256": "5a870d5f643f3716c70b8350ab19ff256834f9079e6364931661630587b24b62",
                "rows": 2},
    "report": {"path": str(prv4.DEFAULT_REPORT_V4),
               "sha256": "71a7f2c401bb67d5db5d0758188531361ae42cd6aedd4de92d3100c727f3a8a2"},
}
V4_LOCKED_HASH = "97217b478ee84797c642944732211d563666e11f3c1bd809593da848a1946eb4"
V4_RUN_APPROVAL = "reviewer-approved-2026-09-25-jev-replay-v4-97217b47"

#: Every source file v5 binds. The v4 list is retained because v5's builder
#: reuses the v4 builder and v5's runner delegates schedule execution to the
#: v4 runner module; both v5 modules are appended.
V5_SOURCE_FILES = tuple(prv4.REPLAY_V4_SOURCE_FILES) + (
    "src/apart_incident_response/jev_replay_preregistration_v5.py",
    "src/apart_incident_response/jev_replay_runner_v5.py",
)

#: The only v4 keys v5 is allowed to change. Everything else must be byte-equal.
V5_OVERRIDE_KEYS = frozenset({
    "preregistration_version", "status", "amended_by_task", "purpose",
    "pending_decisions", "outputs", "successor_of", "approval",
    "model_and_protocol", "runner_policy", "source_files", "source_files_hash",
    "treatment_hash", "preregistration_hash",
})
#: Keys v5 adds on top of the v4 document.
V5_ONLY_KEYS = frozenset({"supersedes", "operational_policy"})


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def output_paths() -> dict[str, str]:
    return {"registration": str(DEFAULT_OUTPUT_V5), "journal": str(DEFAULT_JOURNAL_V5),
            "report": str(DEFAULT_REPORT_V5), "event_source": prv4.DECISION_ARTIFACT}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_files_hash_v5(repo_root: Path) -> str:
    digest = hashlib.sha256()
    missing = []
    for relative in V5_SOURCE_FILES:
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


def treatment_hash_v5(*, decision_sha256: str, wording_hash: str,
                      normalization_policy_hash: str) -> str:
    """v4 treatment hash with only the runner binding replaced.

    Every treatment-defining field (decision artifact, wording, envelope,
    placebo construction/origin, normalization policy, codec, branch modes,
    estimand, direction) is identical to v4; only ``runner_source_file`` /
    ``runner_version`` change plus the explicit delegate entry.
    """

    payload = {
        "decision_artifact_sha256": decision_sha256,
        "message_wording_hash": wording_hash,
        "envelope": jr.MESSAGE_ENVELOPE_TEMPLATE,
        "placebo_construction": jr.PLACEBO_CONSTRUCTION,
        "placebo_origin": jr.PLACEBO_ORIGIN,
        "normalization_policy_hash": normalization_policy_hash,
        "codec_version": jc2.JEV_CHOICE_V2_CODEC_VERSION,
        "branch_modes": ["real", "placebo", "null"],
        "estimand": prv4.ESTIMAND["primary"],
        "directional_prediction": prv4.ESTIMAND["directional_prediction"],
        "runner_source_file": RUNNER_SOURCE_REL_V5,
        "runner_source_delegate": RUNNER_SOURCE_REL_V4,
        "runner_version": REPLAY_RUNNER_VERSION_V5,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def treatment_hash_v4_baseline(*, decision_sha256: str, wording_hash: str,
                               normalization_policy_hash: str) -> str:
    """The v4 treatment hash, used to prove only the runner binding moved."""

    return prv4.treatment_hash_v4(decision_sha256=decision_sha256,
                                  wording_hash=wording_hash,
                                  normalization_policy_hash=normalization_policy_hash)


def _content_hash(document: Mapping[str, Any]) -> str:
    payload = json.dumps({key: value for key, value in document.items()
                          if key != "preregistration_hash"}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _verify_v4_pins(repo_root: Path) -> dict[str, Any]:
    """Re-hash the immutable v4 artifacts and read their recorded outcome."""

    root = Path(repo_root)
    observed: dict[str, Any] = {}
    for name, pin in V4_PINS.items():
        path = root / str(pin["path"])
        if not path.is_file():
            raise ValueError(f"superseded v4 artifact missing: {pin['path']}")
        actual = sha256_file(path)
        if actual != pin["sha256"]:
            raise ValueError(f"superseded v4 artifact drift: {pin['path']}")
        observed[name] = {"path": pin["path"], "sha256": actual}
    report = json.loads((root / str(V4_PINS["report"]["path"])).read_text(encoding="utf-8"))
    observed["stopped_run"] = {
        "approval": report.get("approval"),
        "registration_hash": report.get("registration_hash"),
        "status": report.get("status"),
        "stop_reason": report.get("stop_reason"),
        "attempted_branches": report.get("attempted_branches"),
        "valid_branches": report.get("valid_branches"),
        "invalid_branches": report.get("invalid_branches"),
        "unattempted_branches": report.get("unattempted_branches"),
        "physical_attempts_jev": (report.get("physical_attempts") or {}).get("jev"),
        "estimated_cost_usd": report.get("estimated_cost_usd"),
        "error_class": "transport_error on both attempted branches",
    }
    return observed


def _operational_policy(caps: Mapping[str, Any]) -> dict[str, Any]:
    """The five operational decisions required by the stopped v4 run."""

    planned = caps.get("planned_calls") or {}
    partition = caps.get("provider_partition") or {}
    return {
        "basis": (
            "the authorized replay-v4 attempt stopped on provider_failure_limit after 2 of 51 "
            "branches, each exhausting its 3 registered physical attempts as sanitized "
            "transport_error, with 0 tokens and $0.00 cost on the first event; #196 then "
            "established that both registered provider routes are reachable on attempt 1"),
        "decisions": {
            "retry_policy": {
                "decision": "preserve",
                "max_retries": 2,
                "physical_attempts_per_logical_call": 3,
                "retryable_statuses": sorted(pr.JEV_REPLAY_RETRYABLE),
                "rationale": ("the registered retry budget was not shown to be wrong: the stop was a "
                              "transport availability event, and increasing retry counts would raise the "
                              "physical ceiling without evidence"),
            },
            "terminal_failure_rule": {
                "decision": "preserve",
                "rule": ("stop after two consecutive terminal provider/transport failures; the counter "
                         "resets only after a valid branch"),
                "rationale": ("fail-closed by design; weakening the threshold without cause would trade "
                              "safety for availability"),
            },
            "jev_token_budget": {
                "decision": "preserve",
                "input_token_ceiling": caps.get("input_token_ceiling"),
                "input_usd_per_mtok": caps.get("input_usd_per_mtok"),
                "rationale": ("the stopped run returned zero usage, so no budget evidence exists; the #196 "
                              "Jev probe used 420 input tokens against the registered 8192 ceiling"),
            },
            "bounded_pacing": {
                "decision": "change_bounded",
                "field": "model_and_protocol.backoff",
                "from": dict(BACKOFF_V4),
                "to": dict(BACKOFF_V5),
                "registered_window_per_logical_call_seconds": BACKOFF_V5_WINDOW_SECONDS,
                "previous_window_seconds": BACKOFF_V4_WINDOW_SECONDS,
                "applies_to": "retry attempts only; no sleep occurs on the happy path",
                "unchanged": ["retry count", "retryable statuses", "jitter", "timeout",
                              "terminal failure rule", "all caps"],
                "rationale": (
                    "the v4 schedule allowed at most 0.5 + 1.0 = 1.5 s of backoff across the three "
                    "physical attempts of one logical call, so the two-consecutive-failure terminal rule "
                    "can fire after roughly 3 s of registered backoff on the very first event; widening "
                    "the spacing to 2.0 + 4.0 = 6.0 s (capped at 10 s per backoff) is the minimal change "
                    "that gives a transient a wider window while altering no count, status, cap or "
                    "fail-closed rule"),
            },
            "timeout": {
                "decision": "preserve",
                "seconds": 30.0,
                "rationale": ("the #196 Jev probe returned promptly and produced no timeout evidence; "
                              "raising it would slow failure detection without cause"),
            },
            "output_lifecycle": {
                "decision": "fresh_paths_no_resume",
                "journal": str(DEFAULT_JOURNAL_V5),
                "report": str(DEFAULT_REPORT_V5),
                "no_resume": True,
                "no_append": True,
                "no_overwrite": True,
                "no_path_overrides": True,
                "rationale": ("the v4 registered outputs are occupied by a stopped run and v4 policy "
                              "forbids resume/append/overwrite; any fresh execution needs fresh paths "
                              "plus a new review and explicit authorization"),
            },
            "physical_request_and_cost_caps": {
                "decision": "preserve",
                "planned_jev": planned.get("jev"),
                "planned_ling": planned.get("ling"),
                "planned_combined": planned.get("combined"),
                "physical_requests": caps.get("physical_requests"),
                "provider_partition": dict(partition),
                "retry_reserve": caps.get("retry_reserve"),
                "cost_cap_usd": caps.get("cost_cap_usd"),
                "worst_case_cost_usd": caps.get("worst_case_cost_usd"),
                "worst_case_next_call_cost_usd": caps.get("worst_case_next_call_cost_usd"),
                "arithmetic": caps.get("next_call_reservation_arithmetic"),
                "rationale": ("the design and its retry-inclusive arithmetic are unchanged: 51 logical "
                              "x 3 = 153 physical, reserve 102, worst case $0.052641792 <= $1.00"),
            },
        },
    }


def build_replay_preregistration_v5(*, approved: bool = False,
                                    repo_root: Path | None = None) -> dict[str, Any]:
    """Derive the v5 registration from the frozen v4 builder (offline)."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    baseline = prv4.build_replay_preregistration_v4(approved=approved, repo_root=root)
    pins = _verify_v4_pins(root)

    document: dict[str, Any] = copy.deepcopy(baseline)
    document["preregistration_version"] = JEV_REPLAY_V5_PREREG_VERSION
    document["status"] = (JEV_REPLAY_V5_LOCKED_STATUS if approved
                          else JEV_REPLAY_V5_DRAFT_STATUS)
    document["amended_by_task"] = AMENDED_BY_TASK
    document["purpose"] = (
        "fresh matched real/placebo/null Jev replay registration prepared under #197 after the "
        "authorized replay-v4 attempt stopped on provider_failure_limit; scientific content is "
        "inherited unchanged from the v4 lock and only lifecycle, supersession, bounded pacing "
        "and runner binding differ")
    document["pending_decisions"] = [
        "reviewer acceptance of this v5 lock (offline only)",
        "a separate explicit live authorization reference citing this registration hash before "
        "any replay-v5 run; locking and runner binding are not execution authorization",
        "the stopped v4 outputs remain occupied and are never resumed, appended or overwritten",
    ]
    document["outputs"] = output_paths()
    document["successor_of"] = {
        **{key: value for key, value in baseline.get("successor_of", {}).items()
           if key in ("v1", "v2", "v3", "immutable")},
        "v4": {"registration": str(prv4.DEFAULT_OUTPUT_V4),
               "preregistration_hash": V4_LOCKED_HASH,
               "sha256": V4_PINS["registration"]["sha256"],
               "status": "stopped",
               "stop_reason": pins["stopped_run"].get("stop_reason")},
        "note": ("v1-v4 registrations, journals and reports are immutable historical state: never "
                 "modified, resumed, appended, pooled with or reinterpreted; v5 uses fresh paths only"),
        "immutable": True,
    }
    document["approval"] = {
        **(baseline.get("approval") or {}),
        "scope": "replay_v5_registration_lock_only",
    }

    model_and_protocol = copy.deepcopy(baseline["model_and_protocol"])
    model_and_protocol["backoff"] = dict(BACKOFF_V5)
    document["model_and_protocol"] = model_and_protocol

    document["runner_policy"] = {
        "required_before_live": True,
        "runner_implemented": True,
        "runner_source_files": [RUNNER_SOURCE_REL_V5, RUNNER_SOURCE_REL_V4],
        "runner_source_bound": all(name in V5_SOURCE_FILES
                                   for name in (RUNNER_SOURCE_REL_V5, RUNNER_SOURCE_REL_V4)),
        "runner_delegate": {
            "entrypoint": RUNNER_SOURCE_REL_V5,
            "executes_schedule_via": RUNNER_SOURCE_REL_V4,
            "note": ("v5 owns registration loading, preflight, pacing and report provenance; the "
                     "reviewed v4 schedule executor, durable branch journal and stop rules are "
                     "reused unchanged and both modules are source-bound"),
        },
        "policy": (f"the #197 replay runner is implemented in {RUNNER_SOURCE_REL_V5} and delegates "
                   f"schedule execution to {RUNNER_SOURCE_REL_V4}; both are included in "
                   "V5_SOURCE_FILES and adding the runner does not authorize execution — live "
                   "execution still requires a separate explicit authorization"),
        "adding_runner_authorizes_collection": False,
        "live_execution_rule": ("this registration lock is not live authorization; live execution "
                                "requires the source-bound runner plus a separate explicit "
                                "authorization reference citing this registration hash"),
        "supersedes_v4_registration": {
            "preregistration_hash": V4_LOCKED_HASH,
            "path": str(prv4.DEFAULT_OUTPUT_V4),
            "sha256": V4_PINS["registration"]["sha256"],
            "note": ("v4 lock and its stopped run are superseded, not deleted: preserved byte-for-byte "
                     "as immutable historical inputs"),
        },
    }
    document["source_files"] = list(V5_SOURCE_FILES)
    document["source_files_hash"] = _source_files_hash_v5(root)
    document["treatment_hash"] = treatment_hash_v5(
        decision_sha256=prv4.DECISION_SHA256,
        wording_hash=jr.message_wording_hash(),
        normalization_policy_hash=prv2.normalization_policy_hash())
    document["supersedes"] = {
        "version": prv4.JEV_REPLAY_V4_PREREG_VERSION,
        "preregistration_hash": V4_LOCKED_HASH,
        "registration": pins["registration"],
        "journal": {**pins["journal"], "rows": V4_PINS["journal"]["rows"]},
        "report": pins["report"],
        "stopped_run": pins["stopped_run"],
        "rule": ("the v4 registration, journal and report are immutable historical inputs: never "
                 "resumed, appended, overwritten, pooled, reinterpreted or deleted by v5"),
    }
    document["operational_policy"] = _operational_policy(document["caps"])
    document["preregistration_hash"] = _content_hash(document)
    return document


def write_registration(document: Mapping[str, Any], *, repo_root: Path) -> Path:
    """Persist the registration once; never overwrites."""

    target = Path(repo_root) / DEFAULT_OUTPUT_V5
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return target


def load_locked_registration(*, repo_root: Path,
                             pinned_hash: str | None = None) -> dict[str, Any]:
    path = Path(repo_root) / DEFAULT_OUTPUT_V5
    if not path.is_file():
        raise ValueError("v5 replay registration missing")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("preregistration_version") != JEV_REPLAY_V5_PREREG_VERSION:
        raise ValueError("wrong registration version")
    if document.get("status") != JEV_REPLAY_V5_LOCKED_STATUS:
        raise ValueError("registration is not locked for the matched replay v5")
    if document.get("live_collection_authorized") is not False:
        raise ValueError("live_collection_authorized must be false")
    if document.get("lock_is_not_live_authorization") is not True:
        raise ValueError("lock-is-not-live-authorization declaration missing")
    if pinned_hash is not None and document.get("preregistration_hash") != pinned_hash:
        raise ValueError("registration hash drift")
    return document


def verify_against_jev_replay_preregistration_v5(
        document: Mapping[str, Any], *, repo_root: Path | None = None,
        require_approval: bool = True, journal_exists: bool | None = None,
        report_exists: bool | None = None,
        check_credentials: bool = False) -> dict[str, Any]:
    """Repository-backed, fail-closed verifier for the v5 registration."""

    root = Path(repo_root) if repo_root is not None else _repo_root()
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

    # ---- identity, approval and authorization flags ----
    check("registration_version",
          document.get("preregistration_version") == JEV_REPLAY_V5_PREREG_VERSION,
          document.get("preregistration_version"))
    check("status_locked", document.get("status") == JEV_REPLAY_V5_LOCKED_STATUS,
          document.get("status"))
    approval = document.get("approval") or {}
    check("approval_lock_scope",
          approval.get("approved") is True
          and approval.get("scope") == "replay_v5_registration_lock_only"
          and approval.get("live_collection_authorized") is False,
          approval.get("scope"))
    if require_approval:
        check("approval_present", approval.get("approved") is True and
              not document.get("approval_required"), None)
    check("live_collection_not_authorized",
          document.get("live_collection_authorized") is False
          and document.get("lock_is_not_live_authorization") is True, None)

    # ---- immutable v4 historical inputs ----
    try:
        pins = _verify_v4_pins(root)
        check("superseded_v4_artifacts_pinned", True,
              {name: pin["sha256"] for name, pin in V4_PINS.items()})
    except ValueError as exc:
        pins = None
        check("superseded_v4_artifacts_pinned", False, str(exc))
    supersedes = document.get("supersedes") or {}
    check("superseded_v4_lock_pinned",
          supersedes.get("preregistration_hash") == V4_LOCKED_HASH
          and supersedes.get("registration", {}).get("sha256")
          == V4_PINS["registration"]["sha256"], supersedes.get("preregistration_hash"))
    check("superseded_stopped_run_recorded",
          pins is not None
          and supersedes.get("stopped_run", {}).get("stop_reason")
          == pins["stopped_run"].get("stop_reason")
          and supersedes.get("stopped_run", {}).get("status") == "stopped",
          (supersedes.get("stopped_run") or {}).get("stop_reason"))

    # ---- frozen scientific content: rebuild and re-verify v4 ----
    baseline: dict[str, Any] | None = None
    try:
        baseline = prv4.build_replay_preregistration_v4(approved=True, repo_root=root)
        check("v4_baseline_rebuilds", True, None)
    except Exception as exc:  # noqa: BLE001 - fail closed with the reason
        check("v4_baseline_rebuilds", False, f"{type(exc).__name__}: {exc}")
    if baseline is not None:
        # v4 output freshness is deliberately evaluated as of v4 lock time: v4 is
        # superseded historical state whose outputs are pinned above instead, and
        # v5 carries its own freshness checks below.
        v4_state = prv4.verify_against_jev_replay_preregistration_v4(
            baseline, repo_root=root, require_approval=False,
            journal_exists=False, report_exists=False)
        check("frozen_scientific_content_verified", v4_state["ok"], v4_state["errors"])

        unknown = (set(document) - set(baseline)) - set(V5_ONLY_KEYS)
        missing = (set(baseline) - set(document)) - set(V5_OVERRIDE_KEYS)
        check("no_unexpected_or_missing_keys", not unknown and not missing,
              {"unknown": sorted(unknown), "missing": sorted(missing)})
        drift = [key for key, value in baseline.items()
                 if key not in V5_OVERRIDE_KEYS and document.get(key) != value]
        check("scientific_blocks_identical_to_v4", not drift, drift)

        base_mp = baseline.get("model_and_protocol") or {}
        doc_mp = document.get("model_and_protocol") or {}
        check("model_protocol_pins_identical_to_v4",
              {k: v for k, v in doc_mp.items() if k != "backoff"}
              == {k: v for k, v in base_mp.items() if k != "backoff"},
              sorted(set(base_mp) ^ set(doc_mp)))
        check("treatment_hash_differs_only_by_runner_binding",
              baseline.get("treatment_hash") != document.get("treatment_hash")
              and document.get("treatment_hash") == treatment_hash_v5(
                  decision_sha256=prv4.DECISION_SHA256,
                  wording_hash=jr.message_wording_hash(),
                  normalization_policy_hash=prv2.normalization_policy_hash()),
              document.get("treatment_hash"))

    # ---- estimand / inference / missingness requirements (requirement 2) ----
    estimand = document.get("estimand") or {}
    inference = document.get("inference") or {}
    guards = document.get("guards") or {}
    missingness = document.get("missingness") or {}
    check("equal_weight_prompt_form_estimand",
          estimand.get("experimental_unit") == "prompt form" and estimand.get("k") == 6
          and "equal-weight mean" in str(estimand.get("primary"))
          and estimand.get("events_are_independent_units") is False
          and estimand.get("event_contrast") == "d_i = H_real,i - H_placebo,i",
          estimand.get("primary"))
    check("exact_signflip_plus_form_t_interval",
          "sign-flip" in str(inference.get("primary_test"))
          and "t interval" in str(inference.get("interval"))
          and inference.get("min_two_sided_p_k6") == 0.03125, None)
    check("no_instance_level_inference",
          "instance-level t-test" in (inference.get("prohibited_as_primary") or []), None)
    check("no_imputation", missingness.get("imputation") == "never impute missing pairs",
          missingness.get("imputation"))
    check("five_form_fallback_descriptive_only",
          "interval-only descriptive" in str(missingness.get("five_form_fallback"))
          and "no causal gate" in str(missingness.get("five_form_fallback")),
          missingness.get("five_form_fallback"))
    check("guards_never_filter",
          "never used to filter" in str(guards.get("reporting"))
          and guards.get("target_probability_delta") == 0.0
          and guards.get("feasible_set_mass_epsilon") == 0.01, None)

    # ---- manifest, event order, branch request/state hashes ----
    try:
        decision = prv4.load_decision(root)
        expected_events = prv4.consume_decision_events(decision)
        check("decision_artifact_pinned", True, prv4.DECISION_SHA256)
    except ValueError as exc:
        expected_events = []
        check("decision_artifact_pinned", False, str(exc))
    recorded = list(document.get("events") or [])
    recorded_ids = [str(event.get("event_id")) for event in recorded]
    expected_ids = [str(event.get("event_id")) for event in expected_events]
    check("event_ids_exact_unique_ordered",
          recorded_ids == expected_ids and len(set(recorded_ids)) == prv4.EXPECTED_EVENT_COUNT,
          {"recorded": len(recorded_ids), "expected": len(expected_ids)})
    try:
        expected_schedule = prv4.build_branch_schedule(expected_events)
        check("branch_schedule_event_major",
              document.get("branch_schedule") == expected_schedule
              and expected_schedule.get("event_major") is True, None)
    except Exception as exc:  # noqa: BLE001
        check("branch_schedule_event_major", False, f"{type(exc).__name__}: {exc}")
    if expected_events:
        try:
            expected_bindings = [prv4.build_event_binding(event) for event in expected_events]
            check("branch_request_and_state_hashes",
                  recorded == expected_bindings, None)
        except Exception as exc:  # noqa: BLE001
            check("branch_request_and_state_hashes", False, f"{type(exc).__name__}: {exc}")
    forms = document.get("forms") or {}
    check("six_form_scope",
          set(forms.get("covered_form_ids") or []) == set(prv4.FROZEN_FORM_IDS)
          and tuple(forms.get("expected_distribution") or ()) == prv4.EXPECTED_FORM_DISTRIBUTION,
          forms.get("expected_distribution"))

    # ---- protocol pins ----
    protocol = document.get("model_and_protocol") or {}
    check("jev_model_matches", protocol.get("model") == pr.JEV_REPLAY_MODEL,
          protocol.get("model"))
    check("jev_endpoint_matches", protocol.get("endpoint") == pr.JEV_REPLAY_ENDPOINT,
          protocol.get("endpoint"))
    check("codec_version", protocol.get("codec_version") == jc2.JEV_CHOICE_V2_CODEC_VERSION,
          protocol.get("codec_version"))
    check("normalization_policy",
          protocol.get("normalization_policy_hash") == prv2.normalization_policy_hash()
          and protocol.get("normalization_policy") == prv2.normalization_policy(), None)
    key = str(protocol.get("protocol_key") or "")
    check("jev_protocol_key", bool(key) and not jc.is_jev_protocol_key(key)
          and protocol.get("protocol_key") == prv4.prv6_protocol_key(), key)
    check("bounded_pacing_registered", protocol.get("backoff") == dict(BACKOFF_V5),
          protocol.get("backoff"))
    check("max_retries_preserved", protocol.get("max_retries") == 2, protocol.get("max_retries"))
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
    check("no_mixed_protocol_keys", wire_keys == {key}, sorted(wire_keys))

    # ---- caps and retry-inclusive reservation ----
    caps = document.get("caps") or {}
    planned = caps.get("planned_calls") or {}
    partition = caps.get("provider_partition") or {}
    check("planned_calls_51_0",
          (planned.get("jev"), planned.get("ling"), planned.get("combined")) == (51, 0, 51),
          planned)
    check("physical_cap_retry_inclusive",
          caps.get("physical_requests") == 153
          and partition.get("jev") == 153 and partition.get("ling") == 0
          and partition.get("total") == 153
          and 51 * 3 == caps.get("physical_requests"), partition)
    check("retry_inclusive_cost_reservation",
          caps.get("worst_case_next_call_cost_usd") == prv4.NEXT_CALL_RESERVE_USD
          and f"{prv4.NEXT_CALL_RESERVE_USD}" in str(caps.get("next_call_reservation_arithmetic"))
          and caps.get("worst_case_cost_usd") == prv4.WORST_CASE_COST_USD
          and float(caps.get("worst_case_cost_usd", 1e9)) <= float(caps.get("cost_cap_usd", 0.0)),
          {"reserve": caps.get("worst_case_next_call_cost_usd"),
           "worst": caps.get("worst_case_cost_usd")})
    ling_budget = caps.get("ling_budget") or {}
    check("no_ling_budget", ling_budget.get("planned_calls") == 0
          and ling_budget.get("physical_cap") == 0, ling_budget)

    # ---- outputs: fresh, v5, never stale ----
    outputs = document.get("outputs") or {}
    check("outputs_are_v5", outputs == output_paths(), outputs)
    journal_path = root / str(outputs.get("journal", DEFAULT_JOURNAL_V5))
    report_path = root / str(outputs.get("report", DEFAULT_REPORT_V5))
    journal_bad = journal_exists if journal_exists is not None else journal_path.exists()
    report_bad = report_exists if report_exists is not None else report_path.exists()
    check("fresh_output_paths", not journal_bad, str(journal_path))
    check("fresh_output_paths_report", not report_bad, str(report_path))
    stale = [str(value) for value in outputs.values()
             if str(value) in OLD_OUTPUT_PATHS_V5]
    check("no_stale_or_superseded_output_paths", not stale, stale)

    # ---- source and treatment binding ----
    check("source_files_bound", list(document.get("source_files") or []) == list(V5_SOURCE_FILES),
          len(document.get("source_files") or []))
    try:
        check("source_files_hash_matches",
              document.get("source_files_hash") == _source_files_hash_v5(root),
              document.get("source_files_hash"))
    except ValueError as exc:
        check("source_files_hash_matches", False, str(exc))
    runner_policy = document.get("runner_policy") or {}
    check("runner_policy_satisfied",
          runner_policy.get("runner_implemented") is True
          and runner_policy.get("runner_source_files") == [RUNNER_SOURCE_REL_V5,
                                                           RUNNER_SOURCE_REL_V4]
          and runner_policy.get("runner_source_bound") is True
          and all(name in list(document.get("source_files") or [])
                  for name in (RUNNER_SOURCE_REL_V5, RUNNER_SOURCE_REL_V4)),
          runner_policy.get("runner_source_files"))
    check("runner_binding_does_not_authorize",
          runner_policy.get("adding_runner_authorizes_collection") is False
          and "does not authorize execution" in str(runner_policy.get("policy", ""))
          and "separate explicit authorization" in str(runner_policy.get("live_execution_rule", "")),
          None)

    # ---- operational policy completeness ----
    policy = document.get("operational_policy") or {}
    decisions = policy.get("decisions") or {}
    expected_decision_keys = {"retry_policy", "terminal_failure_rule", "jev_token_budget",
                              "bounded_pacing", "timeout", "output_lifecycle",
                              "physical_request_and_cost_caps"}
    check("operational_decisions_recorded", set(decisions) == expected_decision_keys,
          sorted(decisions))
    check("no_resume_policy_registered",
          decisions.get("output_lifecycle", {}).get("no_resume") is True
          and decisions.get("output_lifecycle", {}).get("no_append") is True
          and decisions.get("output_lifecycle", {}).get("no_overwrite") is True, None)

    # ---- byte-reproducibility: no stale hash ----
    try:
        expected = build_replay_preregistration_v5(approved=True, repo_root=root)
        check("registration_content_matches",
              {k: v for k, v in document.items() if k != "preregistration_hash"}
              == {k: v for k, v in expected.items() if k != "preregistration_hash"}, None)
        check("registration_hash_matches",
              document.get("preregistration_hash") == expected.get("preregistration_hash")
              and document.get("preregistration_hash") == _content_hash(document),
              document.get("preregistration_hash"))
    except Exception as exc:  # noqa: BLE001
        check("registration_rebuilds", False, f"{type(exc).__name__}: {exc}")

    if check_credentials:
        from . import behavioral_discovery as bd
        credentials = jc.load_jev_credentials()
        check("jev_credentials_present",
              bool(credentials.present and credentials.shape_ok), credentials.redacted())
        ling_key = bd._api_key()
        check("ling_credentials_present_not_required",
              True, {"present": bool(ling_key)})

    return {"ok": not errors, "errors": errors, "checks": checks,
            "registration_hash": document.get("preregistration_hash"),
            "event_count": len(recorded), "k": 6,
            "planned_jev": prv4.PLANNED_JEV_CALLS,
            "physical_ceiling": prv4.PHYSICAL_REQUEST_CEILING,
            "live_collection_authorized": False}


__all__ = [
    "JEV_REPLAY_V5_PREREG_VERSION", "JEV_REPLAY_V5_LOCKED_STATUS",
    "JEV_REPLAY_V5_DRAFT_STATUS", "REPLAY_RUNNER_VERSION_V5", "DEFAULT_OUTPUT_V5",
    "DEFAULT_JOURNAL_V5", "DEFAULT_REPORT_V5", "OLD_OUTPUT_PATHS_V5",
    "RUNNER_SOURCE_REL_V5", "RUNNER_SOURCE_REL_V4", "AMENDED_BY_TASK",
    "BACKOFF_V5", "BACKOFF_V4", "V4_PINS", "V4_LOCKED_HASH", "V4_RUN_APPROVAL",
    "V5_SOURCE_FILES", "V5_OVERRIDE_KEYS", "V5_ONLY_KEYS",
    "output_paths", "treatment_hash_v5", "treatment_hash_v4_baseline",
    "build_replay_preregistration_v5", "write_registration",
    "load_locked_registration", "verify_against_jev_replay_preregistration_v5",
]
