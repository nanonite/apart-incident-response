"""#191 repair item 5 — separately capped, nonexperimental transport probe (v7).

Confirms OpenRouter routing/transport for the paid
``inclusionai/ling-3.0-flash-vl`` SKU (the same base model identifier as the
unrouteable ``:free`` SKU, though provider routing or serving configuration
may differ) before any v7 experimental collection is authorized.

Scope is strictly routing, credentials, HTTP success, and usage/pricing —
never behavioral or writer-output capability. The committed artifact's
outcome fields are immutable; :func:`interpret_probe_artifact` derives the
``routing_success`` / ``writer_output_validated`` split for bindings.

Hard caps: exactly one physical completion attempt
(``PROBE_MAX_REQUESTS``), ``PROBE_MAX_TOKENS`` output tokens, its own cost
ceiling, and a read-only catalog fetch first. The probe never touches the
experimental journal/report paths, never uses experimental seeds or task
content, and retains no raw response or credential. Refusals (missing
approval, existing output, unreachable/gated catalog, missing credentials)
make zero completion calls and write nothing; once a completion is attempted
the sanitized result is always recorded as evidence.

Approval source: #191 review repair instruction — "Run one separately capped,
nonexperimental transport probe before authorizing the full block."
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import behavioral_discovery as bd
from . import jev_ling_writer_v5 as writer_v5
from . import jev_openrouter_catalog as catalog
from . import jev_replay_preregistration as pr


PROBE_VERSION = "ling-transport-probe-v7"
DEFAULT_PROBE_OUTPUT = Path("runs/epic-126/jev-ling-transport-probe-v7.json")

PROBE_MODEL = catalog.PAID_LING_MODEL
PROBE_ENDPOINT = pr.LING_ENDPOINT
PROBE_MAX_REQUESTS = 1
PROBE_MAX_TOKENS = 16
PROBE_TIMEOUT_SECONDS = 60.0
PROBE_COST_CEILING_USD = 0.01
PROBE_PROMPT = "Reply with exactly: SILENCE"

#: Strict interpretation scope for the probe evidence.
PROBE_SCOPE = ("routing, credentials, HTTP success, and usage/pricing only; "
               "not behavioral or writer-output capability")

#: Accurate approval provenance for the committed probe.
APPROVAL_BASIS = (
    "the probe reference was derived from a reviewer recommendation rather than a "
    "separately supplied formal approval string; accepted only as nonexperimental route "
    "evidence; not retrospective experimental authorization; does not authorize v7 "
    "collection")

#: Writer outcomes that would count as usable writer output (none were produced
#: by the committed probe: finish_reason=length, empty_output).
VALID_WRITER_OUTCOMES = frozenset({
    "deliberate_silence", "message_candidate", "non_owned_claim"})


def interpret_probe_artifact(document: Mapping[str, Any]) -> dict[str, Any]:
    """Schema-tolerant split between routing success and writer-output validity.

    The committed probe artifact is immutable historical evidence (possibly
    carrying an earlier generic ``success`` flag); this helper derives the
    semantics the registration must bind: HTTP 200 + one attempt + no writer
    error proves routing only, while ``writer_output_validated`` requires a
    usable parsed writer outcome. Never raises on malformed content.
    """

    try:
        attempts = document.get("attempts") if isinstance(document, Mapping) else {}
        attempts = attempts if isinstance(attempts, Mapping) else {}
        outcome = document.get("outcome") if isinstance(document, Mapping) else {}
        outcome = outcome if isinstance(outcome, Mapping) else {}
        diagnostics = document.get("diagnostics") if isinstance(document, Mapping) else []
        diagnostics = diagnostics if isinstance(diagnostics, list) else []
        outcome_name = outcome.get("outcome")
        error_class = outcome.get("error_class")
        http_200 = any(isinstance(entry, Mapping) and entry.get("status") == 200
                       for entry in diagnostics)
        physical = attempts.get("physical")
        routing_success = bool(
            isinstance(physical, int) and not isinstance(physical, bool) and physical >= 1
            and error_class is None
            and outcome_name != "writer_error"
            and http_200)
        writer_output_validated = outcome_name in VALID_WRITER_OUTCOMES
        finish_reason = outcome.get("finish_reason")
    except Exception:
        return {"routing_success": False, "writer_output_validated": False,
                "outcome": None, "finish_reason": None, "http_200_seen": False}
    return {"routing_success": routing_success,
            "writer_output_validated": writer_output_validated,
            "outcome": outcome_name, "finish_reason": finish_reason,
            "http_200_seen": http_200}

#: Registered paid-route pricing (USD per million tokens), frozen from the
#: OpenRouter catalog snapshot captured by this probe; re-verified against a
#: fresh catalog fetch by the v7 live preflight.
LING_PROMPT_USD_PER_MTOK = 0.06
LING_COMPLETION_USD_PER_MTOK = 0.18


def estimate_probe_cost_usd(input_tokens: int, output_tokens: int,
                            *, prompt_usd_per_mtok: float = LING_PROMPT_USD_PER_MTOK,
                            completion_usd_per_mtok: float = LING_COMPLETION_USD_PER_MTOK
                            ) -> float:
    return round((max(0, int(input_tokens)) * prompt_usd_per_mtok
                  + max(0, int(output_tokens)) * completion_usd_per_mtok) / 1_000_000, 12)


def _blocked(reason: str, approval: str | None) -> dict[str, Any]:
    return {"probe_version": PROBE_VERSION, "scope": "nonexperimental_transport_probe",
            "status": "blocked", "stop_reason": reason, "approval": approval,
            "provider_calls": 0, "raw_response_retained": False,
            "credentials_retained": False}


def run_probe(approval: str | None, *, output: Path | None = None,
              timeout: float = PROBE_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Run the one-shot probe; returns the report (also written on attempt)."""

    output = output if output is not None else DEFAULT_PROBE_OUTPUT
    if not approval:
        return _blocked("missing_approval", approval)
    if output.exists():
        return _blocked("output_exists", approval)
    try:
        fetched = catalog.fetch_model_catalog(timeout=timeout)
    except Exception as exc:
        return _blocked(f"catalog_unreachable: {type(exc).__name__}", approval)
    gate = catalog.catalog_availability_gate(PROBE_MODEL, catalog=fetched)
    if not gate["ok"]:
        return _blocked("catalog_gate_failed", approval)
    api_key = bd._api_key()
    if not api_key:
        return _blocked("missing_ling_credentials", approval)

    writer = writer_v5.LingWriterClientV5(
        model=PROBE_MODEL, endpoint=PROBE_ENDPOINT, api_key=api_key,
        max_physical_requests=PROBE_MAX_REQUESTS, timeout=timeout)
    started = time.monotonic()
    outcome = writer.write_outcome({
        "prompt": PROBE_PROMPT,
        "grammar": writer_v5.GRAMMAR_EXPLICIT_SILENCE,
        "private_clues": [], "candidate_labels": [],
        "max_tokens": PROBE_MAX_TOKENS})
    elapsed = round(time.monotonic() - started, 3)
    interpretation = interpret_probe_artifact(
        {"attempts": {"physical": writer.physical_attempts}, "outcome": outcome,
         "diagnostics": writer.rate_limit_diagnostics()})
    input_tokens = int(outcome.get("input_tokens") or 0)
    output_tokens = int(outcome.get("output_tokens") or 0)
    entry = (fetched.get("entries") or {}).get(PROBE_MODEL) or {}
    prompt_rate = float(entry.get("prompt_usd_per_tok") or 0.0) * 1_000_000
    completion_rate = float(entry.get("completion_usd_per_tok") or 0.0) * 1_000_000
    estimated = estimate_probe_cost_usd(input_tokens, output_tokens,
                                        prompt_usd_per_mtok=prompt_rate,
                                        completion_usd_per_mtok=completion_rate)
    report = {
        "probe_version": PROBE_VERSION,
        "scope": "nonexperimental_transport_probe",
        "purpose": ("confirm OpenRouter routing and pricing for the paid ling SKU before "
                    "any v7 experimental collection is authorized"),
        "source_instruction": ("#191 review repair item 5: run one separately capped, "
                               "nonexperimental transport probe before authorizing the "
                               "full block"),
        "approval": approval,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": PROBE_MODEL,
        "endpoint": PROBE_ENDPOINT,
        "previous_failed_sku": catalog.FREE_LING_MODEL,
        "caps": {"max_requests": PROBE_MAX_REQUESTS, "max_tokens": PROBE_MAX_TOKENS,
                 "timeout_seconds": timeout, "cost_ceiling_usd": PROBE_COST_CEILING_USD},
        "catalog": catalog.record_gate(fetched, gate),
        "pricing_frozen_usd_per_mtok": {"prompt": prompt_rate, "completion": completion_rate},
        "attempts": {"physical": writer.physical_attempts, "cap": PROBE_MAX_REQUESTS},
        "elapsed_seconds": elapsed,
        "outcome": {key: outcome.get(key) for key in (
            "outcome", "error_class", "parser_classification", "finish_reason",
            "content_length", "answer", "claim", "input_tokens", "output_tokens",
            "completion_tokens", "seed_sent", "max_tokens", "physical_attempts")},
        "diagnostics": writer.rate_limit_diagnostics(),
        "cost": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                 "estimated_cost_usd": estimated,
                 "cost_ceiling_usd": PROBE_COST_CEILING_USD},
        "routing_success": interpretation["routing_success"],
        "writer_output_validated": interpretation["writer_output_validated"],
        "probe_scope": PROBE_SCOPE,
        "approval_basis": APPROVAL_BASIS,
        "experimental_writer_budget_note": ("the experimental writer still uses the separately "
                                            "registered 1,024-token budget"),
        "result_note": ("one probe completion only; not experimental data; routing success "
                        "does not imply usable writer output and does not authorize "
                        "collection — a separate review and live authorization are still "
                        "required"),
        "raw_response_retained": False,
        "credentials_retained": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                      encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="#191 repair: capped ling transport probe v7")
    parser.add_argument("--approval", help="reviewer instruction reference for this probe")
    parser.add_argument("--output", type=Path, default=DEFAULT_PROBE_OUTPUT)
    parser.add_argument("--timeout", type=float, default=PROBE_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    report = run_probe(args.approval, output=args.output, timeout=args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    if report.get("status") == "blocked":
        return 2
    return 0 if report.get("routing_success") else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PROBE_VERSION", "DEFAULT_PROBE_OUTPUT", "PROBE_MODEL", "PROBE_ENDPOINT",
    "PROBE_MAX_REQUESTS", "PROBE_MAX_TOKENS", "PROBE_TIMEOUT_SECONDS",
    "PROBE_COST_CEILING_USD", "PROBE_PROMPT", "PROBE_SCOPE", "APPROVAL_BASIS",
    "VALID_WRITER_OUTCOMES", "LING_PROMPT_USD_PER_MTOK",
    "LING_COMPLETION_USD_PER_MTOK", "estimate_probe_cost_usd",
    "interpret_probe_artifact", "run_probe", "main",
]
