"""#196 — bounded, offline-first provider diagnostics (issue #159 subtask).

Diagnoses the sanitized ``transport_error`` that stopped the authorized
replay-v4 attempt. Two independent, tiny probes — one Jev, one Ling — each
sends exactly one logical request with at most one physical attempt and writes
its own fresh artifact under ``runs/epic-126/diagnostics/``.

Scope boundaries enforced by this module:

- the stopped replay-v4 journal/report/registration are pinned by hash and are
  never opened for write, resumed, appended to, rerun or reinterpreted;
- eight mutually exclusive outcome classes separate credential/configuration
  failures, HTTP 401/403, HTTP 429, HTTP 404, 408/5xx/529 capacity, timeout or
  network failure, malformed response and valid response;
- no raw response body, header, key or authorization value is ever retained —
  only sanitized status, error class, model, provider, attempt counts, usage
  presence and bounded retry metadata;
- nothing here authorizes replay: ``live_collection_authorized`` stays false,
  the probes require ``--live`` plus an explicit approval reference, and the
  recorded probe successes are availability evidence only.

Offline by construction: the default CLI path and every blocked path make zero
provider calls and write no artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import behavioral_discovery as bd
from . import jev_choice as jc
from . import jev_choice_v2 as jc2
from . import jev_coverage_manifest_preregistration_v7 as prv7
from . import jev_ling_writer_v5 as writer_v5
from . import jev_replay_preregistration as pr
from . import jev_replay_preregistration_v4 as prv4


DIAG_VERSION = "jev-provider-diagnostics-v1"
DIAG_STATUS = "locked_for_jev_provider_diagnostics_v1"

DEFAULT_REGISTRATION = Path("runs/epic-126/diagnostics/jev-provider-diagnostics-preregistration-v1.json")
DEFAULT_JEV_PROBE_OUTPUT = Path("runs/epic-126/diagnostics/jev-transport-probe-v1.json")
DEFAULT_LING_PROBE_OUTPUT = Path("runs/epic-126/diagnostics/ling-transport-probe-v1.json")
OWNED_PATHS = (str(DEFAULT_REGISTRATION), str(DEFAULT_JEV_PROBE_OUTPUT),
               str(DEFAULT_LING_PROBE_OUTPUT))

# --- the eight mutually exclusive outcome classes -------------------------
CLASS_CREDENTIAL_OR_CONFIGURATION = "credential_or_configuration_failure"
CLASS_AUTH_REJECTED = "http_401_403_auth_rejected"
CLASS_RATE_LIMITED = "http_429_rate_or_quota_limited"
CLASS_UNAVAILABLE = "http_404_model_or_endpoint_unavailable"
CLASS_CAPACITY = "http_408_5xx_529_provider_capacity"
CLASS_NETWORK = "timeout_or_network_failure"
CLASS_MALFORMED = "malformed_response"
CLASS_VALID = "valid_response"

ERROR_CLASSES = (
    CLASS_CREDENTIAL_OR_CONFIGURATION,
    CLASS_AUTH_REJECTED,
    CLASS_RATE_LIMITED,
    CLASS_UNAVAILABLE,
    CLASS_CAPACITY,
    CLASS_NETWORK,
    CLASS_MALFORMED,
    CLASS_VALID,
)

CLASS_DEFINITIONS = {
    CLASS_CREDENTIAL_OR_CONFIGURATION: (
        "credential missing or malformed, or a local refusal/cap before any request was sent, "
        "or a residual non-retryable HTTP status not otherwise classified (the exact sanitized "
        "status is retained)"),
    CLASS_AUTH_REJECTED: "HTTP 401 or HTTP 403",
    CLASS_RATE_LIMITED: "HTTP 429 quota or rate limiting",
    CLASS_UNAVAILABLE: "HTTP 404 model or endpoint unavailable",
    CLASS_CAPACITY: "HTTP 408, any 5xx, or HTTP 529 provider capacity",
    CLASS_NETWORK: "timeout, DNS, connection or other transport failure with no HTTP status",
    CLASS_MALFORMED: "HTTP success whose body could not be parsed into the expected shape",
    CLASS_VALID: "HTTP success with a parseable response body",
}

CLASS_ORDER = ("credential check first, then non-2xx HTTP status, then parse failure, "
               "then success, then transport failure")

#: Local refusals meaning no request was ever sent.
_LOCAL_REFUSAL_MARKERS = ("physical_request_cap_exhausted", "missing_credentials",
                          "missing_or_malformed_credentials", "writer_missing_credentials")

_RETRY_EXHAUSTED_RE = re.compile(r"retry_exhausted_http_(\d{3})\b")
_LING_HTTP_RE = re.compile(r"^writer_http_(\d{3})_")
_LING_NETWORK_RE = re.compile(r"^writer_network_\w+$")
_SK_TOKEN_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}")

PROBE_PROMPT = "Reply with exactly: SILENCE"
PROBE_MAX_TOKENS = 16
PROBE_TIMEOUT_SECONDS = 60.0
PROBE_MAX_LOGICAL_REQUESTS = 1
PROBE_MAX_PHYSICAL_ATTEMPTS = 1
PROBE_MAX_RETRIES = 0
JEV_PROBE_COST_CEILING_USD = 0.01
LING_PROBE_COST_CEILING_USD = 0.01

NOT_CLAIMED = ("key expiry", "model removal", "quota exhaustion")

#: The stopped replay-v4 artifacts this task must preserve byte-for-byte.
REPLAY_V4_PINS = {
    "journal": {"path": str(prv4.DEFAULT_JOURNAL_V4),
                "sha256": "5a870d5f643f3716c70b8350ab19ff256834f9079e6364931661630587b24b62",
                "rows": 2},
    "report": {"path": str(prv4.DEFAULT_REPORT_V4),
               "sha256": "71a7f2c401bb67d5db5d0758188531361ae42cd6aedd4de92d3100c727f3a8a2"},
    "registration": {"path": str(prv4.DEFAULT_OUTPUT_V4),
                     "sha256": "5ea64f8218ed1ddabb2cab5a081dea666e686683a2a67ea9a186a9409ea40ee2"},
    "rule": ("never opened for write by this module; replay-v4 is not resumed, rerun, "
             "appended to, pooled or reinterpreted"),
}

SOURCE_FILES = (
    "src/apart_incident_response/jev_provider_diagnostics.py",
    "src/apart_incident_response/jev_choice.py",
    "src/apart_incident_response/jev_choice_v2.py",
    "src/apart_incident_response/jev_ling_writer_v3.py",
    "src/apart_incident_response/jev_ling_writer_v5.py",
    "src/apart_incident_response/behavioral_discovery.py",
    "src/apart_incident_response/jev_coverage_manifest_preregistration_v7.py",
    "src/apart_incident_response/jev_replay_preregistration.py",
    "src/apart_incident_response/jev_replay_preregistration_v4.py",
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_files_hash(repo_root: Path) -> str:
    payload = {name: _sha256_file(Path(repo_root) / name) for name in SOURCE_FILES}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _content_hash(document: Mapping[str, Any]) -> str:
    payload = json.dumps({key: value for key, value in document.items()
                          if key != "preregistration_hash"}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _repo_root_default() -> Path:
    return Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------

def classify_probe_outcome(*, credential_ok: bool, http_status: int | None = None,
                           transport_error: str | None = None,
                           parse_error: str | None = None,
                           response_received: bool = False,
                           body_ok: bool = False) -> str:
    """Map a sanitized probe observation onto exactly one registered class."""

    if not credential_ok:
        return CLASS_CREDENTIAL_OR_CONFIGURATION
    if transport_error and any(marker in str(transport_error)
                               for marker in _LOCAL_REFUSAL_MARKERS):
        return CLASS_CREDENTIAL_OR_CONFIGURATION
    if http_status is not None:
        status = int(http_status)
        if not 200 <= status < 300:
            if status in (401, 403):
                return CLASS_AUTH_REJECTED
            if status == 429:
                return CLASS_RATE_LIMITED
            if status == 404:
                return CLASS_UNAVAILABLE
            if status == 408 or 500 <= status <= 599:
                return CLASS_CAPACITY
            return CLASS_CREDENTIAL_OR_CONFIGURATION
    if parse_error or (response_received and not body_ok):
        return CLASS_MALFORMED
    if response_received and body_ok:
        return CLASS_VALID
    return CLASS_NETWORK


def _jev_exception_fields(exc: BaseException) -> dict[str, Any]:
    """Extract only sanitized fields from a Jev transport exception."""

    if isinstance(exc, jc.JevCredentialError):
        return {"credential_ok": False, "http_status": None,
                "transport_error": str(exc), "parse_error": None}
    if isinstance(exc, jc.JevProviderRejection):
        return {"credential_ok": True, "http_status": int(exc.status),
                "transport_error": None, "parse_error": None}
    if isinstance(exc, jc.JevResponseError):
        return {"credential_ok": True, "http_status": None,
                "transport_error": None, "parse_error": str(exc)}
    if isinstance(exc, jc.JevTransportError):
        match = _RETRY_EXHAUSTED_RE.search(str(exc))
        if match:
            return {"credential_ok": True, "http_status": int(match.group(1)),
                    "transport_error": None, "parse_error": None}
        return {"credential_ok": True, "http_status": None,
                "transport_error": str(exc), "parse_error": None}
    return {"credential_ok": True, "http_status": None,
            "transport_error": type(exc).__name__, "parse_error": None}


def _ling_error_class_fields(error_class: str | None) -> dict[str, Any]:
    """Map the v5 writer error classes onto the same sanitized fields."""

    if not error_class:
        return {"credential_ok": True, "http_status": None, "transport_error": None,
                "parse_error": None}
    if any(marker in error_class for marker in _LOCAL_REFUSAL_MARKERS):
        return {"credential_ok": False, "http_status": None, "transport_error": error_class,
                "parse_error": None}
    match = _LING_HTTP_RE.match(error_class)
    if match:
        return {"credential_ok": True, "http_status": int(match.group(1)),
                "transport_error": None, "parse_error": None}
    if _LING_NETWORK_RE.match(error_class):
        return {"credential_ok": True, "http_status": None,
                "transport_error": error_class, "parse_error": None}
    if "cap_exhausted" in error_class:
        return {"credential_ok": False, "http_status": None,
                "transport_error": error_class, "parse_error": None}
    return {"credential_ok": True, "http_status": None,
            "transport_error": error_class, "parse_error": None}


# --------------------------------------------------------------------------
# redaction
# --------------------------------------------------------------------------

def _secrets() -> list[str | None]:
    return [jc.load_jev_credentials().api_key, bd._api_key()]


def redaction_violations(text: str, secrets: Sequence[str | None]) -> list[str]:
    """Return every secret-bearing or header-bearing pattern found in ``text``."""

    found: set[str] = set()
    for secret in secrets:
        if secret and len(secret) >= 8 and str(secret) in text:
            found.add("credential_value_present")
    if "Bearer " in text:
        found.add("bearer_token_present")
    if re.search(r'"authorization"\s*:', text, re.IGNORECASE):
        found.add("authorization_field_present")
    if _SK_TOKEN_RE.search(text):
        found.add("sk_token_present")
    return sorted(found)


def _assert_redacted(document: Mapping[str, Any]) -> None:
    text = json.dumps(document, sort_keys=True, allow_nan=False)
    violations = redaction_violations(text, _secrets())
    if violations:
        raise ValueError(f"refusing to retain redactable material: {violations}")


# --------------------------------------------------------------------------
# registration
# --------------------------------------------------------------------------

def build_registration(*, repo_root: Path) -> dict[str, Any]:
    """Build the locked diagnostics registration (offline, byte-reproducible)."""

    root = Path(repo_root)
    for pin in REPLAY_V4_PINS.values():
        if not isinstance(pin, Mapping):
            continue
        path = root / str(pin["path"])
        if not path.is_file():
            raise ValueError(f"pinned replay-v4 artifact missing: {pin['path']}")
        if _sha256_file(path) != pin["sha256"]:
            raise ValueError(f"replay-v4 artifact drift: {pin['path']}")
    document: dict[str, Any] = {
        "preregistration_version": DIAG_VERSION,
        "status": DIAG_STATUS,
        "issue": {"parent": 159, "task": 196,
                  "title": "Bounded provider diagnostics for the stopped replay-v4 transport failure"},
        "stage": "offline_provider_diagnostics",
        "purpose": ("separate credential, HTTP status, capacity, transport and payload failures "
                    "for the Jev and Ling routes behind the replay-v4 transport_error stop"),
        "approval_required": True,
        "live_collection_authorized": False,
        "probes_authorized": False,
        "lock_is_not_execution_authorization": True,
        "authorizes_replay": False,
        "availability_evidence_authorizes_replay": False,
        "taxonomy": {"classes": list(ERROR_CLASSES), "definitions": dict(CLASS_DEFINITIONS),
                     "classification_order": CLASS_ORDER, "exactly_one_class": True},
        "probes": {
            "jev": {
                "provider": "jev",
                "model": pr.JEV_REPLAY_MODEL,
                "endpoint": jc.JEV_SYSTEMONE_ENDPOINT,
                "transport": "apart_incident_response.jev_choice.JevChoiceClient",
                "transport_contract": ("identical endpoint, model and transport class as replay-v4; "
                                       "retries disabled and physical attempts capped at one"),
                "request_source": ("frozen pre-read ISO ChoiceState of the first registered replay "
                                   "event, rebuilt with jev_replay_preregistration_v4.pre_read_body; "
                                   "not any of the real/placebo/null replay branches"),
                "max_logical_requests": PROBE_MAX_LOGICAL_REQUESTS,
                "max_physical_attempts": PROBE_MAX_PHYSICAL_ATTEMPTS,
                "max_retries": PROBE_MAX_RETRIES,
                "timeout_seconds": PROBE_TIMEOUT_SECONDS,
                "cost_ceiling_usd": JEV_PROBE_COST_CEILING_USD,
                "output": str(DEFAULT_JEV_PROBE_OUTPUT),
            },
            "ling": {
                "provider": "openrouter",
                "model": prv7.PAID_LING_MODEL,
                "endpoint": pr.LING_ENDPOINT,
                "key_loader": "apart_incident_response.behavioral_discovery._api_key",
                "key_loader_matches_v7_runner": True,
                "transport": "apart_incident_response.jev_ling_writer_v5.LingWriterClientV5",
                "prompt_format": ("payload produced by LingWriterClientV5.write_outcome: model + "
                                  "messages[{role: user, content}] + max_tokens + temperature, the "
                                  "same request builder the v7 runner uses"),
                "prompt": PROBE_PROMPT,
                "max_tokens": PROBE_MAX_TOKENS,
                "max_logical_requests": PROBE_MAX_LOGICAL_REQUESTS,
                "max_physical_attempts": PROBE_MAX_PHYSICAL_ATTEMPTS,
                "max_retries": PROBE_MAX_RETRIES,
                "timeout_seconds": PROBE_TIMEOUT_SECONDS,
                "cost_ceiling_usd": LING_PROBE_COST_CEILING_USD,
                "output": str(DEFAULT_LING_PROBE_OUTPUT),
            },
        },
        "outputs": {"registration": str(DEFAULT_REGISTRATION),
                    "jev_probe": str(DEFAULT_JEV_PROBE_OUTPUT),
                    "ling_probe": str(DEFAULT_LING_PROBE_OUTPUT),
                    "fresh_paths_required": True, "overwrite_forbidden": True},
        "caps": {"logical_requests_per_probe": PROBE_MAX_LOGICAL_REQUESTS,
                 "physical_attempts_per_probe": PROBE_MAX_PHYSICAL_ATTEMPTS,
                 "max_retries_per_probe": PROBE_MAX_RETRIES,
                 "total_physical_attempts_if_both_run": 2,
                 "jev_cost_ceiling_usd": JEV_PROBE_COST_CEILING_USD,
                 "ling_cost_ceiling_usd": LING_PROBE_COST_CEILING_USD,
                 "arithmetic": "1 logical request x (1 + max_retries 0) = 1 physical attempt per probe"},
        "recording": {
            "fields": ["status", "http_status", "error_class", "model", "provider",
                       "attempt_count", "usage_present", "retry_metadata"],
            "retry_metadata": ["max_retries", "retries_performed", "retryable_statuses",
                               "physical_attempts", "cap", "retry_after_present",
                               "retry_after_valid", "delay_seconds"],
            "retention": ["no raw response body", "no response headers", "no keys",
                          "no authorization values", "no provider envelopes"],
            "raw_response_retained": False,
            "credentials_retained": False,
        },
        "preservation": {"replay_v4": REPLAY_V4_PINS,
                         "never_resume_or_rerun_replay_v4": True},
        "availability_evidence": [
            {"provider": "jev", "model": pr.JEV_REPLAY_MODEL,
             "observation": "separate Jev probe succeeded with jev-1.13.0",
             "credential_state": "present and currently accepted",
             "source": "task-provided evidence; no committed artifact exists in this repository",
             "scope": "availability only", "authorizes_replay": False},
            {"provider": "openrouter", "model": prv7.PAID_LING_MODEL,
             "observation": "separate OpenRouter probe succeeded with HTTP 200 and one valid completion",
             "credential_state": "present and currently accepted",
             "source": "task-provided evidence; no committed artifact exists in this repository",
             "scope": "availability only", "authorizes_replay": False},
        ],
        "not_claimed": list(NOT_CLAIMED),
        "claim_scope": ("transport and availability classification only; the recorded probe "
                        "successes are availability evidence and never authorize replay; no "
                        "causal, behavioral, coverage or uptake claim follows"),
        "pending": "separate review authorization for any replay-v4 re-attempt",
        "source_files": list(SOURCE_FILES),
        "source_files_hash": _source_files_hash(root),
    }
    document["preregistration_hash"] = _content_hash(document)
    return document


def write_registration(document: Mapping[str, Any], *, repo_root: Path) -> Path:
    """Persist the registration once; never overwrites."""

    target = Path(repo_root) / DEFAULT_REGISTRATION
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return target


def load_locked_registration(*, repo_root: Path, pinned_hash: str | None = None) -> dict[str, Any]:
    path = Path(repo_root) / DEFAULT_REGISTRATION
    if not path.is_file():
        raise ValueError("diagnostics registration missing")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("preregistration_version") != DIAG_VERSION:
        raise ValueError("wrong diagnostics registration version")
    if document.get("status") != DIAG_STATUS:
        raise ValueError("diagnostics registration is not locked")
    if document.get("live_collection_authorized") is not False:
        raise ValueError("live_collection_authorized must be false")
    if document.get("authorizes_replay") is not False:
        raise ValueError("diagnostics registration must not authorize replay")
    if pinned_hash is not None and document.get("preregistration_hash") != pinned_hash:
        raise ValueError("diagnostics registration hash drift")
    return document


def verify_registration(document: Mapping[str, Any], *, repo_root: Path,
                        approval: str | None = None, check_credentials: bool = True,
                        require_approval: bool = False) -> dict[str, Any]:
    """Repository-backed fail-closed preflight; makes no network request."""

    root = Path(repo_root)
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    check("approval_present", bool(approval) or not require_approval,
          None if approval else "approval required for --live")
    try:
        expected: dict[str, Any] = build_registration(repo_root=root)
        check("registration_rebuilds", True, [])
    except ValueError as exc:
        expected = {}
        check("registration_rebuilds", False, [str(exc)])
    if expected:
        check("registration_hash_matches",
              document.get("preregistration_hash") == expected.get("preregistration_hash"),
              document.get("preregistration_hash"))
        check("registration_content_matches",
              all(document.get(key) == expected.get(key)
                  for key in expected if key != "preregistration_hash"), None)
        check("source_files_hash_matches",
              document.get("source_files_hash") == expected.get("source_files_hash"),
              document.get("source_files_hash"))
        check("source_files_bound",
              sorted(document.get("source_files") or []) == sorted(SOURCE_FILES),
              len(document.get("source_files") or []))
    check("status_locked", document.get("status") == DIAG_STATUS, document.get("status"))
    check("live_collection_not_authorized",
          document.get("live_collection_authorized") is False
          and document.get("probes_authorized") is False
          and document.get("authorizes_replay") is False, None)
    check("taxonomy_is_eight_classes",
          list((document.get("taxonomy") or {}).get("classes") or []) == list(ERROR_CLASSES),
          (document.get("taxonomy") or {}).get("classes"))

    outputs = document.get("outputs") or {}
    for key in ("jev_probe", "ling_probe"):
        target = root / str(outputs.get(key, ""))
        check(f"{key}_path_fresh", not target.exists(), str(outputs.get(key)))

    probes = document.get("probes") or {}
    jev = probes.get("jev") or {}
    check("jev_model_matches_replay_v4", jev.get("model") == pr.JEV_REPLAY_MODEL,
          jev.get("model"))
    check("jev_endpoint_matches_replay_v4", jev.get("endpoint") == jc.JEV_SYSTEMONE_ENDPOINT,
          jev.get("endpoint"))
    check("jev_transport_matches_replay_v4",
          str(jev.get("transport", "")).endswith("jev_choice.JevChoiceClient"),
          jev.get("transport"))
    ling = probes.get("ling") or {}
    check("ling_model_is_paid_v7_route", ling.get("model") == prv7.PAID_LING_MODEL,
          ling.get("model"))
    check("ling_endpoint_matches_v7_runner", ling.get("endpoint") == pr.LING_ENDPOINT,
          ling.get("endpoint"))
    check("ling_key_loader_matches_v7_runner",
          ling.get("key_loader") == "apart_incident_response.behavioral_discovery._api_key"
          and ling.get("key_loader_matches_v7_runner") is True, ling.get("key_loader"))
    check("ling_transport_is_v5_writer",
          str(ling.get("transport", "")).endswith("jev_ling_writer_v5.LingWriterClientV5"),
          ling.get("transport"))

    caps = document.get("caps") or {}
    check("one_physical_attempt_per_probe",
          caps.get("physical_attempts_per_probe") == PROBE_MAX_PHYSICAL_ATTEMPTS
          and caps.get("max_retries_per_probe") == PROBE_MAX_RETRIES,
          {key: caps.get(key) for key in ("logical_requests_per_probe",
                                          "physical_attempts_per_probe",
                                          "max_retries_per_probe")})

    for name, pin in REPLAY_V4_PINS.items():
        if not isinstance(pin, Mapping):
            continue
        path = root / str(pin["path"])
        check(f"replay_v4_{name}_preserved",
              path.is_file() and _sha256_file(path) == pin["sha256"], pin["path"])
    check("diagnostics_paths_disjoint_from_replay_v4",
          not (set(OWNED_PATHS) & {str(pin["path"]) for pin in REPLAY_V4_PINS.values()
                                   if isinstance(pin, Mapping)}), None)
    check("availability_evidence_non_authorizing",
          all(entry.get("authorizes_replay") is False
              for entry in document.get("availability_evidence") or []), None)
    check("not_claimed_recorded",
          sorted(document.get("not_claimed") or []) == sorted(NOT_CLAIMED),
          document.get("not_claimed"))

    if check_credentials:
        credentials = jc.load_jev_credentials()
        check("jev_credentials_present",
              bool(credentials.present and credentials.shape_ok), credentials.redacted())
        ling_key = bd._api_key()
        check("ling_credentials_present", bool(ling_key) and len(str(ling_key)) >= 16,
              {"present": bool(ling_key)})

    failed = [entry["check"] for entry in checks if not entry["ok"]]
    return {"mode": f"{DIAG_VERSION}-preflight", "ok": not failed,
            "failed": failed, "checks": checks}


# --------------------------------------------------------------------------
# probes
# --------------------------------------------------------------------------

def _base_record(*, provider: str, model: str, output: str,
                 approval: str | None) -> dict[str, Any]:
    return {
        "diagnostics_version": DIAG_VERSION,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": provider,
        "model": model,
        "output": str(output),
        "approval": approval,
        "scope": "bounded_provider_diagnostics",
        "availability_only": True,
        "authorizes_replay": False,
        "max_logical_requests": PROBE_MAX_LOGICAL_REQUESTS,
        "max_physical_attempts": PROBE_MAX_PHYSICAL_ATTEMPTS,
        "max_retries": PROBE_MAX_RETRIES,
        "raw_response_retained": False,
        "credentials_retained": False,
        "headers_retained": False,
        "provider_calls": 0,
        "attempt_count": 0,
        "persist": False,
    }


def _no_call_record(record: dict[str, Any], *, transport_error: str) -> dict[str, Any]:
    """Local refusal path: no request was sent, so nothing is persisted for a run."""

    record.update({"status": "completed",
                   "error_class": CLASS_CREDENTIAL_OR_CONFIGURATION,
                   "http_status": None, "http_success": False,
                   "transport_error": transport_error, "parse_error": None,
                   "attempt_count": 0, "provider_calls": 0,
                   "usage_present": False, "usage": {},
                   "retry_metadata": {"max_retries": PROBE_MAX_RETRIES,
                                      "retries_performed": 0,
                                      "physical_attempts": 0,
                                      "cap": PROBE_MAX_PHYSICAL_ATTEMPTS},
                   "persist": True})
    _assert_redacted(record)
    return record


def _blocked(reason: str, *, provider: str, output: str,
             approval: str | None) -> dict[str, Any]:
    record = _base_record(provider=provider, model="", output=output, approval=approval)
    record.update({"status": "blocked", "stop_reason": reason, "persist": False,
                   "provider_calls": 0, "attempt_count": 0})
    return record


def _finish(record: dict[str, Any], *, classification: str, attempt_count: int,
            http_status: int | None, transport_error: str | None, parse_error: str | None,
            usage: Mapping[str, Any], retry_metadata: Mapping[str, Any],
            extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    record.update({
        "status": "completed",
        "error_class": classification,
        "http_status": http_status,
        "http_success": classification == CLASS_VALID,
        "transport_error": transport_error,
        "parse_error": parse_error,
        "attempt_count": int(attempt_count),
        "provider_calls": 1 if attempt_count else 0,
        "usage_present": bool(usage),
        "usage": {key: value for key, value in dict(usage).items()
                  if isinstance(value, int)},
        "retry_metadata": dict(retry_metadata),
        "persist": True,
    })
    if extra:
        record.update(dict(extra))
    _assert_redacted(record)
    return record


def _pre_read_iso_state(repo_root: Path) -> Any:
    """Rebuild the frozen pre-read ISO ChoiceState of the first replay event."""

    registration = json.loads(
        (Path(repo_root) / prv4.DEFAULT_OUTPUT_V4).read_text(encoding="utf-8"))
    events = registration.get("events") or []
    if not events:
        raise ValueError("replay-v4 registration has no events")
    instance = prv4._regenerate_instance(str(events[0]["instance_id"]))
    _, state = prv4.pre_read_body(instance, pr.JEV_REPLAY_MODEL)
    return state


def run_jev_probe(*, registration: Mapping[str, Any], repo_root: Path, approval: str | None,
                  client_factory: Callable[..., Any] | None = None,
                  state_builder: Callable[[], Any] | None = None) -> dict[str, Any]:
    """One logical Jev request, at most one physical attempt."""

    probe = registration.get("probes", {}).get("jev", {})
    output_rel = str(probe.get("output") or DEFAULT_JEV_PROBE_OUTPUT)
    output_abs = Path(repo_root) / output_rel
    record = _base_record(provider="jev", model=str(probe.get("model") or pr.JEV_REPLAY_MODEL),
                          output=output_rel, approval=approval)
    if not approval:
        return _blocked("missing_approval", provider="jev", output=output_rel,
                        approval=approval)
    if output_abs.exists():
        return _blocked("output_exists", provider="jev", output=output_rel, approval=approval)
    credentials = jc.load_jev_credentials()
    if not (credentials.present and credentials.shape_ok):
        return _no_call_record(record, transport_error="missing_or_malformed_credentials")

    factory = client_factory or jc.JevChoiceClient
    client = factory(model=pr.JEV_REPLAY_MODEL, endpoint=jc.JEV_SYSTEMONE_ENDPOINT,
                     max_retries=PROBE_MAX_RETRIES,
                     max_physical_requests=PROBE_MAX_PHYSICAL_ATTEMPTS,
                     timeout=PROBE_TIMEOUT_SECONDS)
    adapter = jc2.JevChoiceAdapterV2(client, model=pr.JEV_REPLAY_MODEL)
    builder = state_builder or (lambda: _pre_read_iso_state(repo_root))
    try:
        request = adapter.build_request(builder())
    except Exception as exc:
        return _no_call_record(
            record, transport_error=f"local_request_build_failed:{type(exc).__name__}")

    usage: dict[str, Any] = {}
    parse_error: str | None = None
    transport_error: str | None = None
    http_status: int | None = None
    credential_ok = True
    response_received = False
    body_ok = False
    try:
        raw = client.complete(request)
        response_received = True
        body_ok = isinstance(raw, Mapping)
        if body_ok:
            candidate = raw.get("usage")
            if isinstance(candidate, Mapping):
                usage = dict(candidate)
            if "answers" not in raw:
                parse_error, body_ok = "missing_answers_field", False
        else:
            parse_error = "body_not_a_mapping"
    except Exception as exc:
        fields = _jev_exception_fields(exc)
        credential_ok = bool(fields["credential_ok"])
        http_status = fields["http_status"]
        transport_error = fields["transport_error"]
        parse_error = fields["parse_error"]

    attempt_count = int(getattr(client, "physical_attempts", 0) or 0)
    classification = classify_probe_outcome(
        credential_ok=credential_ok, http_status=http_status,
        transport_error=transport_error, parse_error=parse_error,
        response_received=response_received, body_ok=body_ok)
    retry_metadata = {
        "max_retries": int(getattr(client, "max_retries", PROBE_MAX_RETRIES)),
        "retries_performed": 0,
        "retryable_statuses": sorted(jc.JEV_RETRYABLE_STATUSES),
        "physical_attempts": attempt_count,
        "cap": PROBE_MAX_PHYSICAL_ATTEMPTS,
    }
    return _finish(record, classification=classification, attempt_count=attempt_count,
                   http_status=http_status, transport_error=transport_error,
                   parse_error=parse_error, usage=usage, retry_metadata=retry_metadata,
                   extra={"endpoint": str(getattr(client, "endpoint",
                                                  jc.JEV_SYSTEMONE_ENDPOINT)),
                          "request_shape": "frozen_pre_read_iso_choice_state"})


def run_ling_probe(*, registration: Mapping[str, Any], repo_root: Path, approval: str | None,
                   writer_factory: Callable[..., Any] | None = None) -> dict[str, Any]:
    """One logical Ling request, at most one physical attempt."""

    probe = registration.get("probes", {}).get("ling", {})
    output_rel = str(probe.get("output") or DEFAULT_LING_PROBE_OUTPUT)
    output_abs = Path(repo_root) / output_rel
    record = _base_record(provider="openrouter",
                          model=str(probe.get("model") or prv7.PAID_LING_MODEL),
                          output=output_rel, approval=approval)
    if not approval:
        return _blocked("missing_approval", provider="openrouter", output=output_rel,
                        approval=approval)
    if output_abs.exists():
        return _blocked("output_exists", provider="openrouter", output=output_rel,
                        approval=approval)
    api_key = bd._api_key()
    if not api_key or len(api_key) < 16:
        return _no_call_record(record, transport_error="writer_missing_credentials")

    factory = writer_factory or writer_v5.LingWriterClientV5
    writer = factory(model=str(probe.get("model") or prv7.PAID_LING_MODEL),
                     endpoint=str(probe.get("endpoint") or pr.LING_ENDPOINT),
                     api_key=api_key, max_retries=PROBE_MAX_RETRIES,
                     max_physical_requests=PROBE_MAX_PHYSICAL_ATTEMPTS,
                     timeout=PROBE_TIMEOUT_SECONDS)

    outcome: dict[str, Any] | None = None
    parse_error: str | None = None
    transport_error: str | None = None
    http_status: int | None = None
    credential_ok = True
    response_received = False
    body_ok = False
    try:
        outcome = writer.write_outcome({
            "prompt": str(probe.get("prompt") or PROBE_PROMPT),
            "grammar": writer_v5.GRAMMAR_EXPLICIT_SILENCE,
            "private_clues": [], "candidate_labels": [],
            "max_tokens": int(probe.get("max_tokens") or PROBE_MAX_TOKENS),
        })
        fields = _ling_error_class_fields(outcome.get("error_class"))
        credential_ok = bool(fields["credential_ok"])
        http_status = fields["http_status"]
        transport_error = fields["transport_error"]
        response_received = http_status is None and transport_error is None
        body_ok = response_received
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        parse_error, response_received, body_ok = type(exc).__name__, True, False
    except Exception as exc:
        transport_error = type(exc).__name__

    attempt_count = int(getattr(writer, "physical_attempts", 0) or 0)
    classification = classify_probe_outcome(
        credential_ok=credential_ok, http_status=http_status,
        transport_error=transport_error, parse_error=parse_error,
        response_received=response_received, body_ok=body_ok)
    diagnostics = [dict(entry) for entry in
                   ((outcome or {}).get("diagnostics")
                    if outcome is not None else writer.rate_limit_diagnostics())
                   if isinstance(entry, Mapping)]
    retry_metadata = {
        "max_retries": int(getattr(writer, "max_retries", PROBE_MAX_RETRIES)),
        "retries_performed": max(0, attempt_count - 1),
        "retryable_statuses": list(writer_v5.LING_RETRYABLE_STATUSES),
        "physical_attempts": attempt_count,
        "cap": PROBE_MAX_PHYSICAL_ATTEMPTS,
        "per_attempt": diagnostics,
    }
    usage: dict[str, Any] = {}
    if outcome is not None:
        for key in ("input_tokens", "output_tokens", "completion_tokens"):
            if isinstance(outcome.get(key), int):
                usage[key] = outcome[key]
    return _finish(record, classification=classification, attempt_count=attempt_count,
                   http_status=http_status, transport_error=transport_error,
                   parse_error=parse_error, usage=usage, retry_metadata=retry_metadata,
                   extra={"endpoint": str(getattr(writer, "endpoint", pr.LING_ENDPOINT)),
                          "key_loader": "behavioral_discovery._api_key",
                          "prompt_format": "LingWriterClientV5.write_outcome payload",
                          "writer_outcome": (outcome or {}).get("outcome"),
                          "finish_reason": (outcome or {}).get("finish_reason")})


def execute_probes(registration: Mapping[str, Any], *, repo_root: Path, approval: str | None,
                   verification: Mapping[str, Any], provider: str = "both",
                   jev_runner: Callable[[], dict[str, Any]] | None = None,
                   ling_runner: Callable[[], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Gate, run and persist the selected probes. Zero calls unless every gate passes."""

    summary: dict[str, Any] = {
        "mode": DIAG_VERSION, "approval": approval, "provider": provider,
        "probes": {}, "provider_calls": 0,
        "raw_response_retained": False, "credentials_retained": False,
        "authorizes_replay": False, "availability_only": True,
    }
    if not approval:
        summary.update({"status": "blocked", "stop_reason": "missing_approval"})
        return summary
    if not verification.get("ok"):
        summary.update({"status": "blocked", "stop_reason": "preflight_failed",
                        "failed": list(verification.get("failed") or [])})
        return summary
    selected = ("jev", "ling") if provider == "both" else (provider,)
    outputs = registration.get("outputs") or {}
    for name in selected:
        key = f"{name}_probe"
        target = Path(repo_root) / str(outputs.get(key, ""))
        if target.exists():
            summary.update({"status": "blocked", "stop_reason": f"{key}_path_not_fresh",
                            "provider": name})
            return summary
    for name in selected:
        if name == "jev":
            runner = jev_runner or (
                lambda: run_jev_probe(registration=registration, repo_root=repo_root,
                                      approval=approval))
        else:
            runner = ling_runner or (
                lambda: run_ling_probe(registration=registration, repo_root=repo_root,
                                       approval=approval))
        record = runner()
        written = False
        if record.get("persist"):
            target = Path(repo_root) / str(record["output"])
            _assert_redacted(record)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n")
            written = True
        summary["probes"][name] = {key: record.get(key) for key in (
            "status", "error_class", "http_status", "attempt_count", "usage_present",
            "provider_calls", "stop_reason", "model", "provider", "output")}
        summary["probes"][name]["written"] = written
        summary["provider_calls"] += int(record.get("provider_calls") or 0)
    summary["status"] = "completed"
    summary["classifications"] = {name: entry.get("error_class")
                                  for name, entry in summary["probes"].items()}
    return summary


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="#196 bounded provider diagnostics (offline; live gated)")
    parser.add_argument("--live", action="store_true",
                        help="run the selected probes (requires --approval; never run offline)")
    parser.add_argument("--approval", help="reviewer runtime authorization reference")
    parser.add_argument("--provider", choices=("jev", "ling", "both"), default="both")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--lock", action="store_true",
                        help="build and persist the offline registration (never overwrites)")
    args = parser.parse_args(argv)
    root = Path(args.repo_root) if args.repo_root is not None else _repo_root_default()

    if args.lock:
        document = build_registration(repo_root=root)
        write_registration(document, repo_root=root)
        print(json.dumps({"mode": DIAG_VERSION, "status": "locked",
                          "path": str(DEFAULT_REGISTRATION),
                          "preregistration_hash": document["preregistration_hash"]},
                         indent=2, sort_keys=True))
        return 0

    try:
        registration = load_locked_registration(repo_root=root)
    except ValueError as exc:
        print(json.dumps({"mode": DIAG_VERSION, "status": "blocked",
                          "stop_reason": f"registration_load_failed: {exc}",
                          "provider_calls": 0}, indent=2, sort_keys=True))
        return 2
    verification = verify_registration(registration, repo_root=root, approval=args.approval,
                                       check_credentials=True, require_approval=bool(args.live))
    print(json.dumps(verification, indent=2, sort_keys=True, allow_nan=False))
    if not verification["ok"]:
        return 2
    if not args.live:
        print(json.dumps({"mode": DIAG_VERSION, "status": "offline",
                          "note": "preflight only; no provider call made",
                          "probes_authorized": False, "authorizes_replay": False,
                          "provider_calls": 0}, indent=2, sort_keys=True))
        return 0
    summary = execute_probes(registration, repo_root=root, approval=args.approval,
                             verification=verification, provider=args.provider)
    print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))
    if summary.get("status") == "blocked":
        return 2
    classes = list((summary.get("classifications") or {}).values())
    return 0 if classes and all(name == CLASS_VALID for name in classes) else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DIAG_VERSION", "DIAG_STATUS", "DEFAULT_REGISTRATION", "DEFAULT_JEV_PROBE_OUTPUT",
    "DEFAULT_LING_PROBE_OUTPUT", "OWNED_PATHS", "ERROR_CLASSES", "CLASS_DEFINITIONS",
    "CLASS_CREDENTIAL_OR_CONFIGURATION", "CLASS_AUTH_REJECTED", "CLASS_RATE_LIMITED",
    "CLASS_UNAVAILABLE", "CLASS_CAPACITY", "CLASS_NETWORK", "CLASS_MALFORMED", "CLASS_VALID",
    "NOT_CLAIMED", "SOURCE_FILES", "REPLAY_V4_PINS", "PROBE_MAX_LOGICAL_REQUESTS",
    "PROBE_MAX_PHYSICAL_ATTEMPTS", "PROBE_MAX_RETRIES",
    "classify_probe_outcome", "build_registration", "write_registration",
    "load_locked_registration", "verify_registration", "redaction_violations",
    "run_jev_probe", "run_ling_probe", "execute_probes", "main",
]
