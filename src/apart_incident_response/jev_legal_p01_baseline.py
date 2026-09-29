"""L01 (#219): offline legal baseline reconciliation and P06 truncation diagnosis.

Everything here is derived from files already on disk: the closed
hypothesis:low family's terminal report (#215), the stopped P06 journal and
report (#207), the frozen #200 form-capacity audit, the protocol, and the pinned
writer/runner sources that produced the recorded stop. The module makes no
provider call, records no approval, and never writes to a frozen artifact.

A process-wide audit hook records every network event raised while the evidence
index is assembled and the build fails closed if one occurs, so
``network_audit.events`` in the emitted artifact is an observed zero rather
than an assumption.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from apart_incident_response import jev_ling_writer_v5 as writer_v5
from apart_incident_response import jev_p05_discovery_lock as p05
from apart_incident_response import jev_p06_discovery_runner as p06

EVIDENCE_REL = "runs/next-phase/legal/jev-legal-p01-evidence-v1.json"
DOC_REL = "docs/jev-legal-p01-baseline.md"
PROTOCOL_REL = "docs/jev-discovery-confirmation-plan.md"
NETWORK_EVENT_PREFIXES = ("socket.", "urllib.", "http.client.", "ftplib.")

#: Inputs pinned by sha256 prefix in the Chainlink #219 task text. Digests are
#: always recomputed from disk; the issue text is never trusted as a hash.
PINNED_INPUTS: tuple[dict[str, Any], ...] = (
    {"path": "docs/jev-hypothesis-low-terminal-decision.md",
     "role": "#215 terminal family report (P14)",
     "expected_sha256_prefix": "89ef2aaf",
     "pin_source": "Chainlink #219 task text"},
    {"path": "runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection.jsonl",
     "role": "#207 P06 discovery journal (16 rows)",
     "expected_sha256_prefix": "4e8de096",
     "pin_source": "Chainlink #219 task text; scope table of #215 terminal report"},
    {"path": "runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection-report.json",
     "role": "#207 P06 collection report",
     "expected_sha256_prefix": "3086ceac",
     "pin_source": "Chainlink #219 task text; scope table of #215 terminal report"},
    {"path": "runs/epic-126/replication/jev-replication-form-audit-v1.json",
     "role": "#200 frozen form-capacity audit",
     "expected_sha256_prefix": "cb529cd6",
     "pin_source": "Chainlink #219 task text; docs/jev-p01-evidence-index.md section 1"},
    {"path": PROTOCOL_REL,
     "role": "research protocol for the discovery/confirmation chain",
     "expected_sha256_prefix": "501e21b6",
     "pin_source": "Chainlink #219 task text; scope table of #215 terminal report"},
)

#: Corroborating frozen inputs recorded so the diagnosis is reproducible.
SUPPORTING_INPUTS: tuple[dict[str, Any], ...] = (
    {"path": "runs/next-phase/jev-p04-discovery-registration-v1.json",
     "role": "#207 registered design (manifest, treatment, route, budgets)",
     "expected_sha256_prefix": "78f7cd03",
     "pin_source": "scope table of #215 terminal report"},
    {"path": "runs/next-phase/jev-p05-discovery-lock-v1.json",
     "role": "#207 discovery lock",
     "expected_sha256_prefix": "75d12f7b",
     "pin_source": "scope table of #215 terminal report"},
    {"path": "runs/next-phase/jev-discovery-authorization-record-v1.json",
     "role": "hypothesis:low authorization record (historical, not carried forward)",
     "expected_sha256_prefix": "77962311",
     "pin_source": "scope table of #215 terminal report"},
    {"path": "src/apart_incident_response/jev_ling_writer_v5.py",
     "role": "writer-v5 finish_reason / output-cap classification source",
     "expected_sha256_prefix": None,
     "pin_source": "recomputed and pinned by L01"},
    {"path": "src/apart_incident_response/jev_p06_discovery_runner.py",
     "role": "P06 runner: request identity, token ceilings, terminal stops",
     "expected_sha256_prefix": None,
     "pin_source": "recomputed and pinned by L01"},
    {"path": DOC_REL,
     "role": "L01 baseline narrative (this task's second deliverable)",
     "expected_sha256_prefix": None,
     "pin_source": "recomputed and pinned by L01"},
)

EXPECTED = {
    "registration_content_hash": p06.REGISTRATION_HASH,
    "lock_content_hash": p06.LOCK_HASH,
    "scope_digest_sha256": p06.SCOPE_DIGEST,
    "recorded_stop_reason": "truncated_output",
    "recorded_cost_usd": 0.00039726,
    "recorded_ling_input_tokens": 534,
    "recorded_ling_output_tokens": 2029,
    "recorded_provider_calls": 3,
    "planned_rows": 16,
    "max_tokens_sent": 1024,
}


class EvidenceBuildError(RuntimeError):
    """Raised when the offline build cannot fail closed on its own."""


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
# local reads
# --------------------------------------------------------------------------

def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_journal(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def hash_inputs(root: Path, specs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    entries = []
    for spec in specs:
        path = root / str(spec["path"])
        digest = sha256_of(path)
        prefix = spec.get("expected_sha256_prefix")
        entries.append({
            "path": spec["path"],
            "role": spec["role"],
            "expected_sha256_prefix": prefix,
            "sha256": digest,
            "prefix_match": None if prefix is None else digest.startswith(prefix),
            "pin_source": spec["pin_source"],
        })
    return entries


# --------------------------------------------------------------------------
# journal / report recomputation
# --------------------------------------------------------------------------

def _cost_from_tokens(tokens: Mapping[str, int], cost_model: Mapping[str, Any]) -> float:
    """Registered rates applied to the journaled token totals (0 jev calls)."""
    ling = (tokens["ling_input_tokens"] * float(cost_model["ling_prompt_usd_per_mtok"])
            + tokens["ling_output_tokens"] * float(cost_model["ling_completion_usd_per_mtok"]))
    jev = tokens["jev_input_tokens"] * float(cost_model.get("jev_input_usd_per_mtok", 0.0))
    return (ling + jev) / 1_000_000


def _attempt_diagnostics(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for row in rows:
        emission = row.get("emission") or {}
        for writer in emission.get("writer_outcomes") or ():
            records.extend(writer.get("attempt_diagnostics") or ())
    return records


def summarize_journal(rows: Sequence[Mapping[str, Any]],
                      manifest: Sequence[Mapping[str, Any]],
                      cost_model: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute every recorded number of the stopped P06 collection."""
    status_counts = Counter(str(row["status"]) for row in rows)
    physical = Counter()
    tokens: Counter[str] = Counter()
    provider_calls = 0
    for row in rows:
        for provider, value in (row.get("physical_attempts") or {}).items():
            physical[provider] += int(value)
        tokens.update({key: int(value) for key, value in (row.get("token_usage") or {}).items()})
        provider_calls += int(row.get("provider_calls") or 0)
    recorded_cost = round(sum(float((row.get("cost") or {}).get("usd") or 0.0) for row in rows), 12)
    recomputed_cost = round(_cost_from_tokens(tokens, cost_model), 12)
    diagnostics = _attempt_diagnostics(rows)
    outcomes = [{"agent": writer["agent"], "turn": writer["turn"], "outcome": writer["outcome"]}
                for row in rows if row.get("emission")
                for writer in row["emission"].get("writer_outcomes") or ()]
    ceiling = int(cost_model["ling_output_token_ceiling"])
    summary = {
        "rows": len(rows),
        "instance_ids_unique": len({row["instance_id"] for row in rows}),
        "sequence": [row["sequence"] for row in rows],
        "matches_registered_manifest": [
            (row["instance_id"], row["seed"], row["prompt_form_id"]) for row in rows] == [
            (entry["instance_id"], entry["seed"], entry["prompt_form_id"]) for entry in manifest],
        "seeds": [row["seed"] for row in rows],
        "status_counts": {key: int(status_counts.get(key, 0))
                          for key in ("failed", "not_attempted", "ok", "silence")},
        "provider_calls": provider_calls,
        "physical_attempts": {"ling": int(physical["ling"]), "jev": int(physical["jev"]),
                              "combined": int(physical["combined"])},
        "token_totals": {key: int(tokens[key]) for key in
                         ("ling_input_tokens", "ling_output_tokens",
                          "jev_input_tokens", "jev_output_tokens")},
        "recorded_cost_usd": recorded_cost,
        "recomputed_cost_usd": recomputed_cost,
        "cost_matches_registered_rates": math.isclose(recorded_cost, recomputed_cost,
                                                      rel_tol=0.0, abs_tol=1e-12),
        "failure_reasons": {
            "failed_row": next((row["failure_reason"] for row in rows if row["status"] == "failed"), None),
            "not_attempted_rows": sorted({row["failure_reason"] for row in rows
                                          if row["status"] == "not_attempted"}),
        },
        "writer_outcomes": outcomes,
        "attempt_diagnostics": {
            "records": len(diagnostics),
            "statuses": [record.get("status") for record in diagnostics],
            "error_classes": [record.get("error_class") for record in diagnostics],
            "retry_ordinals": [record.get("retry_ordinal") for record in diagnostics],
            "retry_after_present_any": any(record.get("retry_after_present") for record in diagnostics),
            "retry_after_ms_present_any": any(record.get("retry_after_ms_present")
                                              for record in diagnostics),
            "delay_sources": sorted({source for record in diagnostics
                                     for source in record.get("delay_sources") or ()}),
            "delay_source_values": [record.get("delay_source") for record in diagnostics],
        },
        "output_token_bound": {
            "registered_output_token_ceiling": ceiling,
            "truncated_call_output_tokens_upper_bound": ceiling,
            "silence_calls_output_tokens_lower_bound":
                max(int(tokens["ling_output_tokens"]) - ceiling, 0),
        },
    }
    return summary


def cross_check_report(report: Mapping[str, Any],
                       summary: Mapping[str, Any],
                       rows: Sequence[Mapping[str, Any]]) -> dict[str, bool]:
    counts = report.get("counts") or {}
    caps = report.get("caps") or {}
    return {
        "journaled_seeds": report.get("journaled_seeds") == summary["rows"],
        "planned_seeds": report.get("planned_seeds") == summary["rows"],
        "seed_order": list(report.get("seeds") or []) == [row["instance_id"] for row in rows],
        "status_counts": all(int(counts.get(key, -1)) == value
                             for key, value in summary["status_counts"].items()),
        "provider_calls": report.get("provider_calls") == summary["provider_calls"],
        "physical_used": (caps.get("physical_used") or {}).get("ling")
            == summary["physical_attempts"]["ling"]
            and (caps.get("physical_used") or {}).get("jev")
            == summary["physical_attempts"]["jev"],
        "cost": math.isclose(float((caps.get("cost_usd") or 0.0)), summary["recorded_cost_usd"],
                             rel_tol=0.0, abs_tol=1e-12),
        "stop": report.get("status") == "stopped"
            and report.get("stop_reason") == EXPECTED["recorded_stop_reason"],
        "registration_hash": report.get("registration_hash") == p06.REGISTRATION_HASH,
        "lock_hash": report.get("lock_hash") == p06.LOCK_HASH,
        "scope_digest": report.get("scope_digest_sha256") == p06.SCOPE_DIGEST,
    }


# --------------------------------------------------------------------------
# writer-v5 finish_reason / output-cap trace (offline)
# --------------------------------------------------------------------------

_PROBE_CONTENTS = ("", "   ", "SILENCE", "ANSWER: candidate-3", "MESSAGE: bit0=0",
                   "ANSWER: candidate-3\nMESSAGE: bit0=0", "bit0=0 is my answer")
_PROBE_REASONS = (None, "stop", "length", "content_filter")
_PROBE_GRAMMARS = (writer_v5.GRAMMAR_EXPLICIT_SILENCE, writer_v5.GRAMMAR_ORIGINAL_LING)


def trace_finish_reason_handling() -> dict[str, Any]:
    """Probe writer-v5 classification offline: what ``finish_reason`` entails.

    No provider is contacted; synthetic completions are classified only.
    """
    outcomes_by_reason: dict[str, set[str]] = {}
    truncated = []
    for grammar in _PROBE_GRAMMARS:
        for reason in _PROBE_REASONS:
            for content in _PROBE_CONTENTS:
                result = writer_v5.classify_writer_completion(
                    content, reason, ["bit0=0"], grammar=grammar,
                    candidate_labels=["candidate-3"])
                outcomes_by_reason.setdefault(str(reason), set()).add(result["outcome"])
                if result["outcome"] == writer_v5.OUTCOME_TRUNCATED_OUTPUT:
                    truncated.append({"grammar": grammar, "finish_reason": reason,
                                      "content_length": result["content_length"]})
    probes = len(_PROBE_GRAMMARS) * len(_PROBE_REASONS) * len(_PROBE_CONTENTS)
    length_always_truncated = all(
        writer_v5.classify_writer_completion(content, "length", ["bit0=0"], grammar=grammar,
                                             candidate_labels=["candidate-3"])["outcome"]
        == writer_v5.OUTCOME_TRUNCATED_OUTPUT
        for grammar in _PROBE_GRAMMARS for content in _PROBE_CONTENTS if content.strip())
    return {
        "writer_outcomes_version": writer_v5.WRITER_OUTCOMES_VERSION,
        "writer_parser_version": writer_v5.WRITER_PARSER_VERSION,
        "classification_order": list(writer_v5.writer_schema()["classification_order"]),
        "probes": probes,
        "outcomes_by_finish_reason": {key: sorted(value)
                                      for key, value in outcomes_by_reason.items()},
        "truncated_output_requires_finish_reason_length": bool(truncated) and all(
            probe["finish_reason"] == "length" for probe in truncated),
        "truncated_output_requires_non_empty_content": bool(truncated) and all(
            probe["content_length"] > 0 for probe in truncated),
        "length_with_non_empty_content_is_always_truncated": length_always_truncated,
        "truncated_probes": len(truncated),
    }


# --------------------------------------------------------------------------
# diagnosis, historical facts, limitations
# --------------------------------------------------------------------------

def diagnose_truncation(summary: Mapping[str, Any], registration: Mapping[str, Any],
                        trace: Mapping[str, Any]) -> dict[str, Any]:
    """Separate the HTTP 200 ``truncated_output`` stop from rate limiting."""
    diagnostics = summary["attempt_diagnostics"]
    error_classes = [str(item) for item in diagnostics["error_classes"]]
    cost_model = registration["budgets"]["cost_model"]
    return {
        "stop_kind": "http_200_writer_output_cap",
        "recorded_stop_reason": EXPECTED["recorded_stop_reason"],
        "rate_limit_distinction": {
            "statuses": diagnostics["statuses"],
            "retry_ordinals": diagnostics["retry_ordinals"],
            "retry_after_present_any": diagnostics["retry_after_present_any"],
            "retry_after_ms_present_any": diagnostics["retry_after_ms_present_any"],
            "error_classes": diagnostics["error_classes"],
            "delay_sources": diagnostics["delay_sources"],
            "rate_limited_error_class_seen": any("rate_limited" in item for item in error_classes),
            "conclusion": ("The stop is an HTTP 200 writer output-cap classification, not rate limiting: "
                           "all recorded attempts returned 200 with no error class, no retry-after header, "
                           "retry_ordinal 0 and only client-side min_interval pacing."),
            "counterfactual_signal": ("A rate-limit stop under this writer would be journaled as HTTP 429 with "
                                      "error_class writer_http_429_rate_limited, retry_after_present true and "
                                      "retry_ordinal > 0; 429 is a registered retryable status and "
                                      "'rate-limited' is a registered writer terminal stop."),
            "scope": ("Distinctions hold for the three recorded attempts only; absence of a rate-limit signal "
                      "is not proof that no provider-side throttling existed."),
        },
        "output_cap_budget": {
            "max_tokens_sent_per_request": EXPECTED["max_tokens_sent"],
            "registered_output_token_ceiling": int(cost_model["ling_output_token_ceiling"]),
            "recorded_token_totals": summary["token_totals"],
            "bound": summary["output_token_bound"],
        },
        "can_infer": [
            ("Every recorded Ling request was sent with max_tokens 1024: the runner rejects any request "
             "identity whose max_tokens differs from 1024 (writer_request_identity_drift stops the run), "
             "the offline preflight requires writer_contract token_budget == 1024 and cost model "
             "ling_output_token_ceiling == 1024, and the journal records max_tokens 1024 on all attempts."),
            ("The third attempt returned HTTP 200 with non-empty content and finish_reason 'length': the "
             "writer-v5 classifier assigns truncated_output only when finish_reason == 'length' on non-empty "
             "content, so the recorded outcome entails that provider field."),
            ("finish_reason 'length' means generation stopped at the output cap instead of a natural end, so "
             "the registered 1024-token output budget was the binding constraint on that call."),
            ("truncated_output is a registered writer terminal outcome: the run stopped with stop_reason "
             "truncated_output, the failed row carries writer_error:truncated_output and the 15 unattempted "
             "rows carry not_attempted:truncated_output."),
            ("The truncated call cannot have exceeded the 1024 output-token ceiling, because an over-ceiling "
             "usage is rewritten to writer_error/writer_token_budget_exceeded; with 2029 recorded output "
             "tokens over three calls, the two deliberate_silence calls together produced at least 1005 "
             "output tokens."),
        ],
        "cannot_infer": [
            ("finish_reason, content_length and per-call completion_tokens are not persisted in the journal or "
             "report: the 'length' field is a code-level inference from the pinned writer-v5 source, not an "
             "observed value in the artifact."),
            ("The exact number of tokens the truncated call emitted is unknown; only row-level totals "
             "(534 input / 2029 output) exist, so only the bound above is derivable."),
            ("Raw response bodies are never retained (raw_response_retained false), so the truncated text "
             "cannot be re-examined or re-classified offline."),
            ("Nothing here shows what a larger budget would have produced: no counterfactual completion "
             "exists, and one truncated call from one attempted seed cannot show that 1024 tokens is "
             "systematically too small."),
            ("No scientific interpretation follows: the registered ladder rule treats truncated_output as an "
             "instrumentation/token-budget repair item before interpretation, and the run completed zero "
             "instances."),
            ("The diagnosis cannot be generalized to the legal:low family, whose route, budget and stop rules "
             "are not yet registered."),
        ],
        "classification_trace": dict(trace),
    }


def historical_facts(registration: Mapping[str, Any]) -> dict[str, Any]:
    """Record the original L4X treatment and the observed route as history."""
    treatment = registration["treatment"]
    route = registration["route"]
    writer_prompt = treatment["writer_prompt"]
    return {
        "status": "historical fact recorded for L01 reconciliation; not a new approval",
        "authorization_carried_into_legal_family": False,
        "l4x_treatment": {
            "rung": "L4X",
            "description": ("exact original COMM bridge: two agents x two turns, provider_seed, "
                            "1024 max tokens, evolving visible-message state, original "
                            "ANSWER/optional-MESSAGE grammar"),
            "mode": treatment["mode"],
            "agents": list(treatment["agents"]),
            "turns": int(treatment["turns"]),
            "grammar": writer_prompt["output_grammar"],
            "max_tokens": int(writer_prompt["max_tokens"]),
            "temperature": float(writer_prompt["temperature"]),
            "seed_behavior": writer_prompt["seed_behavior"],
            "registered_calls": {"ling_per_seed": p06.L4X_LING_CALLS_PER_SEED,
                                 "jev_per_seed": p06.L4X_JEV_CALLS_PER_SEED,
                                 "ling_total": p06.L4X_TOTAL_LING_CALLS,
                                 "jev_total": p06.L4X_TOTAL_JEV_CALLS},
        },
        "route_used_by_stopped_hypothesis_run": {
            "ling": {"endpoint": route["ling"]["endpoint"], "model": route["ling"]["model"],
                     "sku": route["ling"]["route"], "temperature": float(route["ling"]["temperature"]),
                     "pacing": route["ling"]["pacing"]},
            "jev": {"endpoint": route["jev"]["endpoint"], "model": route["jev"]["model"],
                    "codec_version": route["jev"]["codec_version"]},
            "registration": registration["paths"]["registration"],
        },
        "legal_family_route_status": {
            "registered": False,
            "authorized": False,
            "statement": ("legal:low has no registered or authorized route; L04 must register one and L07 "
                          "must supply a separate scope-bound user authorization before any provider call"),
            "opencode_go_note": ("OpenCode Go has no interchangeable Ling route in the current registration "
                                 "(docs/jev-legal-task-sequence.md)"),
            "rate_limit_note": ("the hypothesis run's paid OpenRouter route and its observed 200 responses "
                                "carry no authorization and no rate-limit claim into legal:low"),
        },
    }


def limitations() -> list[str]:
    return [
        "Offline only: no provider call, probe, live journal or network event was made or authorized.",
        "Frozen #200 and terminal #207/#215 files are read-only inputs here and were preserved byte-identically.",
        "The #215 terminal report digest is pinned by an 8-character prefix in the #219 task text; the full "
        "digest recomputed here is recorded and cross-checked against the task prefix only.",
        "finish_reason, content_length and per-call token usage are not persisted by the P06 journal, so the "
        "output-cap diagnosis rests on the pinned writer-v5 source plus the recorded outcome.",
        "One attempted seed out of sixteen; the truncation diagnosis has n = 1 and no counterfactual retry.",
        "A failed or stopped predecessor never authorizes a successor: nothing here approves legal:low "
        "collection, a route, a budget or any provider call.",
    ]


def _check(name: str, ok: bool, detail: Any) -> dict[str, Any]:
    return {"check": name, "ok": bool(ok), "detail": detail}


def _finish_reason_persisted(rows: Sequence[Mapping[str, Any]]) -> bool:
    """True only if the journal would let a reader observe finish_reason itself."""
    for row in rows:
        for writer in (row.get("emission") or {}).get("writer_outcomes") or ():
            if "finish_reason" in writer:
                return True
            if any("finish_reason" in record for record in writer.get("attempt_diagnostics") or ()):
                return True
    return False


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def _source_pins(root: Path) -> dict[str, Any]:
    writer_source = (root / "src/apart_incident_response/jev_ling_writer_v5.py").read_text(encoding="utf-8")
    runner_source = (root / "src/apart_incident_response/jev_p06_discovery_runner.py").read_text(encoding="utf-8")
    return {
        "classification_branch_present": 'elif reason == "length":' in writer_source
            and "result[\"outcome\"] = OUTCOME_TRUNCATED_OUTPUT" in writer_source,
        "request_identity_max_tokens_gate": 'identity.get("max_tokens") != 1024' in runner_source,
        "preflight_token_budget_gate": 'writer_contract.get("token_budget", -1)) == 1024' in runner_source,
        "output_ceiling_gate": 'cost_model.get("ling_output_token_ceiling", 0)) == 1024' in runner_source,
    }


def build_evidence(repo_root: Path | str) -> dict[str, Any]:
    """Recompute the L01 evidence index from disk. Fails closed on any drift."""
    root = Path(repo_root)
    _install_network_audit_hook()
    _NETWORK_EVENTS.clear()

    inputs = hash_inputs(root, PINNED_INPUTS)
    supporting = hash_inputs(root, SUPPORTING_INPUTS)
    hashes_before = {entry["path"]: entry["sha256"] for entry in inputs + supporting}

    registration = load_json(root / "runs/next-phase/jev-p04-discovery-registration-v1.json")
    lock = load_json(root / "runs/next-phase/jev-p05-discovery-lock-v1.json")
    auth = load_json(root / "runs/next-phase/jev-discovery-authorization-record-v1.json")
    report = load_json(root / "runs/next-phase/hypothesis/jev-discovery-v1/"
                               "jev-discovery-collection-report.json")
    rows = load_journal(root / "runs/next-phase/hypothesis/jev-discovery-v1/"
                               "jev-discovery-collection.jsonl")
    terminal_text = (root / "docs/jev-hypothesis-low-terminal-decision.md").read_text(encoding="utf-8")

    summary = summarize_journal(rows, registration["fixed_n"]["manifest"],
                                registration["budgets"]["cost_model"])
    report_checks = cross_check_report(report, summary, rows)
    trace = trace_finish_reason_handling()
    source_pins = _source_pins(root)
    diagnosis = diagnose_truncation(summary, registration, trace)
    history = historical_facts(registration)

    registration_hash = p05._registration_hash(registration)
    lock_hash = p05._lock_hash(lock)
    pinned_digests = {entry["path"]: entry["sha256"] for entry in inputs}
    terminal_pins_match = all(
        pinned_digests[path] in terminal_text
        for path in ("runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection.jsonl",
                     "runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection-report.json",
                     PROTOCOL_REL))
    document_text = (root / DOC_REL).read_text(encoding="utf-8") if (root / DOC_REL).exists() else ""
    hashes_after = {entry["path"]: sha256_of(root / entry["path"])
                    for entry in inputs + supporting}
    events = network_events()

    cost_model = registration["budgets"]["cost_model"]
    checks = [
        _check("pinned_input_sha256_prefixes_match", all(entry["prefix_match"] for entry in inputs),
               {entry["path"]: entry["sha256"] for entry in inputs}),
        _check("supporting_input_hashes_recomputed",
               all(entry["prefix_match"] is not False for entry in supporting),
               {entry["path"]: entry["sha256"] for entry in supporting}),
        _check("terminal_report_pins_match_recomputed_bytes", terminal_pins_match,
               "the #215 scope table cites the recomputed journal, report and protocol digests"),
        _check("registration_and_lock_content_hashes_recompute",
               registration_hash == EXPECTED["registration_content_hash"]
               and lock_hash == EXPECTED["lock_content_hash"],
               {"registration_hash": registration_hash, "lock_hash": lock_hash}),
        _check("authorization_scope_digest_matches",
               auth.get("scope_digest_sha256") == EXPECTED["scope_digest_sha256"]
               and report.get("scope_digest_sha256") == EXPECTED["scope_digest_sha256"],
               EXPECTED["scope_digest_sha256"]),
        _check("journal_matches_registered_manifest",
               summary["rows"] == EXPECTED["planned_rows"]
               and summary["instance_ids_unique"] == EXPECTED["planned_rows"]
               and summary["sequence"] == list(range(1, EXPECTED["planned_rows"] + 1))
               and summary["matches_registered_manifest"],
               {"rows": summary["rows"], "unique_ids": summary["instance_ids_unique"],
                "manifest_order": summary["matches_registered_manifest"]}),
        _check("journal_status_counts", summary["status_counts"] == {
            "failed": 1, "not_attempted": 15, "ok": 0, "silence": 0}, summary["status_counts"]),
        _check("provider_call_accounting",
               summary["provider_calls"] == EXPECTED["recorded_provider_calls"]
               and summary["physical_attempts"] == {"ling": 3, "jev": 0, "combined": 3},
               {"provider_calls": summary["provider_calls"],
                "physical_attempts": summary["physical_attempts"]}),
        _check("cost_recomputes_from_registered_rates",
               summary["cost_matches_registered_rates"]
               and math.isclose(summary["recorded_cost_usd"], EXPECTED["recorded_cost_usd"],
                                rel_tol=0.0, abs_tol=1e-12)
               and summary["recorded_cost_usd"] <= float(registration["budgets"]["discovery_collection"]["cost_ceiling_usd"]),
               {"recorded": summary["recorded_cost_usd"],
                "recomputed": summary["recomputed_cost_usd"],
                "tokens": summary["token_totals"],
                "rates": {"ling_prompt_usd_per_mtok": cost_model["ling_prompt_usd_per_mtok"],
                          "ling_completion_usd_per_mtok": cost_model["ling_completion_usd_per_mtok"]}}),
        _check("report_cross_checks_journal", all(report_checks.values()), report_checks),
        _check("no_rate_limit_signal_on_any_attempt",
               all(status == 200 for status in diagnosis["rate_limit_distinction"]["statuses"])
               and not diagnosis["rate_limit_distinction"]["rate_limited_error_class_seen"]
               and not diagnosis["rate_limit_distinction"]["retry_after_present_any"]
               and not diagnosis["rate_limit_distinction"]["retry_after_ms_present_any"]
               and max(diagnosis["rate_limit_distinction"]["retry_ordinals"] or [0]) == 0,
               diagnosis["rate_limit_distinction"]["conclusion"]),
        _check("truncated_output_requires_finish_reason_length",
               trace["truncated_output_requires_finish_reason_length"]
               and trace["truncated_output_requires_non_empty_content"]
               and trace["length_with_non_empty_content_is_always_truncated"],
               {key: trace[key] for key in ("probes", "truncated_probes",
                                            "outcomes_by_finish_reason")}),
        _check("truncated_output_is_a_registered_terminal_outcome",
               "truncated_output" in p06.WRITER_TERMINAL_OUTCOMES
               and summary["failure_reasons"]["failed_row"] == "writer_error:truncated_output"
               and summary["failure_reasons"]["not_attempted_rows"] == ["not_attempted:truncated_output"],
               summary["failure_reasons"]),
        _check("max_tokens_1024_pinned_by_gates_and_request_identity",
               int(registration["treatment"]["writer_prompt"]["max_tokens"]) == EXPECTED["max_tokens_sent"]
               and int(cost_model["ling_output_token_ceiling"]) == EXPECTED["max_tokens_sent"]
               and all(source_pins.values()),
               source_pins),
        _check("finish_reason_not_persisted_recorded_as_limitation",
               not _finish_reason_persisted(rows),
               "diagnosis is a code-level inference from the pinned writer-v5 source"),
        _check("frozen_inputs_byte_identical_after_build", hashes_before == hashes_after,
               "every input digest recomputed at the end of the build equals the digest read at the start"),
        _check("zero_network_events_under_audit_hook", not events,
               {"events": list(events), "provider_calls": 0}),
        _check("baseline_doc_pins_the_recomputed_hashes",
               bool(document_text) and all(digest in document_text
                                           for digest in pinned_digests.values()),
               DOC_REL),
        _check("no_approval_recorded_for_legal_family",
               history["legal_family_route_status"]["authorized"] is False
               and history["authorization_carried_into_legal_family"] is False,
               history["status"]),
    ]

    network_audit = {"hook": "sys.addaudithook(" + ", ".join(NETWORK_EVENT_PREFIXES) + ")",
                     "events": len(events), "event_names": list(events), "provider_calls": 0}
    document = {
        "artifact": "jev-legal-p01-evidence-v1",
        "chain": {"task": 219, "title": "L01 — Reconcile legal baseline and diagnose P06 truncation",
                  "parent_issue": 218, "root_issue": 159, "family": "legal:low",
                  "milestone": "L01", "predecessor_issue": 215, "successor_issue": 220,
                  "protocol": PROTOCOL_REL, "baseline_doc": DOC_REL},
        "scope": ("offline evidence reconciliation and truncation diagnosis only; no provider call, no probe, "
                  "no live journal, no authorization inference and no modification of frozen hypothesis "
                  "artifacts"),
        "inputs": inputs,
        "supporting_inputs": supporting,
        "recomputation": {"journal": summary, "report_cross_checks": report_checks,
                          "registration_hash": registration_hash, "lock_hash": lock_hash,
                          "scope_digest_sha256": EXPECTED["scope_digest_sha256"]},
        "truncation_diagnosis": diagnosis,
        "historical_facts": history,
        "limitations": limitations(),
        "checks": checks,
        "network_audit": network_audit,
        "handoff": {
            "to": "L02", "issue": 220,
            "deliverable": "runs/next-phase/legal/jev-legal-p02-form-census-v1.json",
            "conditions": [
                "#219 must be closed by the plugin after reviewer approval before L02 runs",
                "legal form count, independence, closure and fresh seed windows are findings to derive, "
                "not assumptions inherited from the hypothesis family audit",
                "the hypothesis 85000-87511 windows, instance ids and output paths must not be reused",
                "no provider call is authorized by this artifact; L07 supplies a separate scope-bound "
                "user authorization",
                "a failed or stopped predecessor never authorizes its successor",
            ],
        },
    }
    if events:
        raise EvidenceBuildError(f"network events during offline build: {events}")
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=EVIDENCE_REL)
    args = parser.parse_args(argv)
    document = build_evidence(args.repo_root)
    output = Path(args.repo_root) / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    failed = [entry["check"] for entry in document["checks"] if not entry["ok"]]
    print(json.dumps({"output": str(output), "checks_run": len(document["checks"]),
                      "failed": failed,
                      "network_events": document["network_audit"]["events"]}, indent=2))
    return 0 if not failed else 1


__all__ = ["EVIDENCE_REL", "DOC_REL", "PROTOCOL_REL", "PINNED_INPUTS", "SUPPORTING_INPUTS",
           "EXPECTED", "EvidenceBuildError", "sha256_of", "load_json", "load_journal",
           "hash_inputs", "summarize_journal", "cross_check_report",
           "trace_finish_reason_handling", "diagnose_truncation", "historical_facts",
           "limitations", "network_events", "build_evidence", "main"]


if __name__ == "__main__":  # pragma: no cover - manual offline entry point
    raise SystemExit(main())
