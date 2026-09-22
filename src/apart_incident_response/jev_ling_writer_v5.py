"""#187 Phase A (repaired) — writer observability v5 (offline).

Replaces the ambiguous ``message-or-None`` parse with mutually exclusive writer
outcomes and sanitized per-attempt observability. It keeps the v3 Ling pacing,
retry, cap and redaction contracts by inheriting
:class:`~apart_incident_response.jev_ling_writer_v3.LingWriterClientV3`'s
monotonic limiter, retry-header handling and physical-attempt accounting; only
the completion parser and the persisted outcome change.

An empty or truncated completion is never recorded as silence. Raw response
bodies, credentials, complete headers and provider envelopes are never retained.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Mapping

from . import behavioral_discovery as bd
from . import jev_replay_preregistration as pr
from .jev_choice_pilot import WriterError
from .jev_ling_writer_v3 import (
    LING_BACKOFF_INITIAL_SECONDS,
    LING_BACKOFF_MAX_SECONDS,
    LING_MAX_RETRIES,
    LING_MAX_SERVER_REQUESTED_DELAY_SECONDS,
    LING_MIN_ATTEMPT_INTERVAL_SECONDS,
    LING_MONOTONIC_CLOCK_NAME,
    LING_PACING_ALGORITHM,
    LING_PROVENANCE_FIELDS,
    LING_RETRYABLE_STATUSES,
    LING_SUPPORTED_RETRY_HEADERS,
    LING_TIMEOUT_SECONDS,
    LingWriterClientV3,
    _numeric_seconds,
)


WRITER_OUTCOMES_VERSION = "ling-writer-outcomes-v5"
WRITER_PARSER_VERSION = "ling-writer-parser-v5"
SILENCE_TOKEN = "SILENCE"
MESSAGE_PREFIX = "MESSAGE:"
GRAMMAR_EXPLICIT_SILENCE = "explicit_silence_v5"
GRAMMAR_ORIGINAL_LING = "original_ling_v5"

OUTCOME_DELIBERATE_SILENCE = "deliberate_silence"
OUTCOME_MESSAGE_CANDIDATE = "message_candidate"
OUTCOME_EMPTY_OUTPUT = "empty_output"
OUTCOME_TRUNCATED_OUTPUT = "truncated_output"
OUTCOME_UNPARSED_OUTPUT = "unparsed_output"
OUTCOME_NON_OWNED_CLAIM = "non_owned_claim"
OUTCOME_INVALID_ANSWER = "invalid_answer"
OUTCOME_WRITER_ERROR = "writer_error"

WRITER_OUTCOMES = (
    OUTCOME_DELIBERATE_SILENCE,
    OUTCOME_MESSAGE_CANDIDATE,
    OUTCOME_EMPTY_OUTPUT,
    OUTCOME_TRUNCATED_OUTPUT,
    OUTCOME_UNPARSED_OUTPUT,
    OUTCOME_NON_OWNED_CLAIM,
    OUTCOME_INVALID_ANSWER,
    OUTCOME_WRITER_ERROR,
)

_MESSAGE_RE = re.compile(r"MESSAGE\s*:\s*([^\n]+)", re.IGNORECASE)
_ANSWER_RE = re.compile(r"ANSWER\s*:\s*([^\n.]+)", re.IGNORECASE)


def writer_schema() -> dict[str, Any]:
    return {
        "writer_outcomes_version": WRITER_OUTCOMES_VERSION,
        "writer_parser_version": WRITER_PARSER_VERSION,
        "outcomes": list(WRITER_OUTCOMES),
        "silence_token": SILENCE_TOKEN,
        "message_prefix": MESSAGE_PREFIX,
        "grammars": {
            GRAMMAR_EXPLICIT_SILENCE: "exact SILENCE token, or MESSAGE: <claim>",
            GRAMMAR_ORIGINAL_LING: "ANSWER: <label> with optional MESSAGE: <claim>; no MESSAGE is silence",
        },
        "silence_rule": "deliberate_silence only for an exact registered SILENCE response (or, for the "
                        "original-grammar rung, a valid ANSWER with no MESSAGE); empty or truncated output "
                        "is never silence",
        "classification_order": ["empty_output", "truncated_output", "deliberate_silence",
                                 "message_candidate", "non_owned_claim", "invalid_answer",
                                 "unparsed_output", "writer_error"],
        "retains_content_length": True,
        "retains_raw_content": False,
        "raw_response_retained": False,
        "pacing": {
            "min_attempt_interval_seconds": LING_MIN_ATTEMPT_INTERVAL_SECONDS,
            "pacing_algorithm": LING_PACING_ALGORITHM,
            "monotonic_clock": LING_MONOTONIC_CLOCK_NAME,
            "supported_retry_headers": list(LING_SUPPORTED_RETRY_HEADERS),
            "max_server_requested_delay_seconds": LING_MAX_SERVER_REQUESTED_DELAY_SECONDS,
            "retryable_statuses": list(LING_RETRYABLE_STATUSES),
            "max_retries": LING_MAX_RETRIES,
            "backoff_initial_seconds": LING_BACKOFF_INITIAL_SECONDS,
            "backoff_max_seconds": LING_BACKOFF_MAX_SECONDS,
            "provenance_fields": list(LING_PROVENANCE_FIELDS),
        },
    }


def writer_schema_hash() -> str:
    import hashlib
    return hashlib.sha256(json.dumps(writer_schema(), sort_keys=True).encode("utf-8")).hexdigest()


def classify_writer_completion(content: Any, finish_reason: Any, private_clues: Any, *,
                               grammar: str = GRAMMAR_EXPLICIT_SILENCE,
                               candidate_labels: Any = None) -> dict[str, Any]:
    """Return the mutually exclusive writer outcome for one completion.

    Never treats empty or truncated output as silence. For the original grammar
    a parsed ``ANSWER:`` must be one of the public candidate labels; an unknown or
    missing answer is classified separately from deliberate silence.
    """

    text = content if isinstance(content, str) else ""
    reason = finish_reason if isinstance(finish_reason, str) else None
    clues = {str(clue) for clue in (private_clues or ())}
    candidates = {str(label) for label in (candidate_labels or ())}
    result: dict[str, Any] = {"outcome": None, "claim": None, "answer": None,
                              "finish_reason": reason, "content_length": len(text),
                              "grammar": grammar, "parser_classification": None}
    if text.strip() == "":
        result["outcome"] = OUTCOME_EMPTY_OUTPUT
    elif reason == "length":
        result["outcome"] = OUTCOME_TRUNCATED_OUTPUT
    elif grammar == GRAMMAR_ORIGINAL_LING:
        message = _MESSAGE_RE.search(text)
        answer = _ANSWER_RE.search(text)
        if message is not None:
            claim = message.group(1).strip()
            result["claim"] = claim
            result["outcome"] = (OUTCOME_MESSAGE_CANDIDATE if claim in clues
                                 else OUTCOME_NON_OWNED_CLAIM)
        elif answer is not None:
            parsed_answer = answer.group(1).strip()
            result["answer"] = parsed_answer
            if candidates and parsed_answer not in candidates:
                result["outcome"] = OUTCOME_INVALID_ANSWER
            else:
                result["outcome"] = OUTCOME_DELIBERATE_SILENCE
        else:
            result["outcome"] = OUTCOME_UNPARSED_OUTPUT
    elif text.strip() == SILENCE_TOKEN:
        result["outcome"] = OUTCOME_DELIBERATE_SILENCE
    else:
        message = _MESSAGE_RE.search(text)
        if message is None:
            result["outcome"] = OUTCOME_UNPARSED_OUTPUT
        else:
            claim = message.group(1).strip()
            result["claim"] = claim
            result["outcome"] = (OUTCOME_MESSAGE_CANDIDATE if claim in clues
                                 else OUTCOME_NON_OWNED_CLAIM)
    result["parser_classification"] = result["outcome"]
    return result


class LingWriterClientV5(LingWriterClientV3):
    """Ling writer with v3 pacing and mutually exclusive v4 outcomes."""

    transport_version = "ling-writer-openrouter-pacing-v3"
    writer_outcomes_version = WRITER_OUTCOMES_VERSION
    writer_parser_version = WRITER_PARSER_VERSION

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.last_call_outcome: dict[str, Any] | None = None

    def _make_outcome(self, *, outcome: str, claim: str | None, finish_reason: Any,
                      content_length: int | None, input_tokens: Any, output_tokens: Any,
                      completion_tokens: Any, error_class: str | None, grammar: str,
                      answer: str | None = None, max_tokens: int | None = None,
                      seed: int | None = None) -> dict[str, Any]:
        return {
            "writer_outcomes_version": WRITER_OUTCOMES_VERSION,
            "writer_parser_version": WRITER_PARSER_VERSION,
            "outcome": outcome,
            "parser_classification": outcome,
            "claim": claim,
            "answer": answer,
            "finish_reason": finish_reason if isinstance(finish_reason, str) else None,
            "content_length": content_length,
            "input_tokens": input_tokens if isinstance(input_tokens, int) else None,
            "output_tokens": output_tokens if isinstance(output_tokens, int) else None,
            "completion_tokens": completion_tokens if isinstance(completion_tokens, int) else None,
            "error_class": error_class,
            "grammar": grammar,
            "max_tokens": max_tokens,
            "seed_sent": seed,
            "physical_attempts": self.physical_attempts,
            "diagnostics": self.rate_limit_diagnostics(),
            "raw_response_retained": False,
        }

    def write_outcome(self, context: Mapping[str, Any]) -> dict[str, Any]:  # pragma: no cover - live only
        grammar = str(context.get("grammar") or GRAMMAR_EXPLICIT_SILENCE)
        private_clues = list(context.get("private_clues", ()))
        if not self.api_key:
            self.last_call_diagnostics = []
            outcome = self._make_outcome(outcome=OUTCOME_WRITER_ERROR, claim=None, finish_reason=None,
                                         content_length=None, input_tokens=None, output_tokens=None,
                                         completion_tokens=None,
                                         error_class="writer_missing_credentials", grammar=grammar)
            self.last_call_outcome = outcome
            return outcome
        self.logical_calls += 1
        logical_call_id = f"ling-call-{self.logical_calls}"
        prompt = str(context.get("prompt") or "")
        max_tokens = int(context.get("max_tokens") or pr.LING_MAX_TOKENS)
        payload: dict[str, Any] = {"model": self.model,
                                   "messages": [{"role": "user", "content": prompt}],
                                   "max_tokens": max_tokens,
                                   "temperature": pr.LING_TEMPERATURE}
        seed = context.get("seed")
        if isinstance(seed, int) and not isinstance(seed, bool):
            payload["seed"] = seed
        body = json.dumps(payload).encode()
        retry_ordinal = 0
        server_delay: float | None = None
        call_records: list[dict[str, Any]] = []
        while True:
            if self.max_physical_requests is not None and self.physical_attempts >= self.max_physical_requests:
                self.last_call_diagnostics = call_records
                outcome = self._make_outcome(outcome=OUTCOME_WRITER_ERROR, claim=None, finish_reason=None,
                                             content_length=None, input_tokens=None, output_tokens=None,
                                             completion_tokens=None,
                                             error_class="writer_physical_request_cap_exhausted",
                                             grammar=grammar)
                self.last_call_outcome = outcome
                return outcome
            delay, source, sources = self._delay(retry_ordinal, server_delay)
            if delay > 0.0:
                self._sleep(delay)
            self._last_attempt_start = self._clock()
            self.physical_attempts += 1
            record: dict[str, Any] = {
                "logical_call_id": logical_call_id,
                "physical_attempt": self.physical_attempts,
                "retry_ordinal": retry_ordinal,
                "status": None,
                "delay_seconds": round(delay, 9),
                "delay_source": source,
                "delay_sources": sources,
                "retry_after_present": False,
                "retry_after_valid": False,
                "retry_after_ms_present": False,
                "retry_after_ms_valid": False,
                "error_class": None,
            }
            call_records.append(record)
            self.rate_limit_records.append(record)
            server_delay = None
            request = urllib.request.Request(self.endpoint, data=body, method="POST",
                                             headers={"Authorization": f"Bearer {self.api_key}",
                                                      "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                choice = (payload.get("choices") or [{}])[0] if isinstance(payload, Mapping) else {}
                message = choice.get("message") or {}
                usage = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else {}
                classified = classify_writer_completion(
                    message.get("content"), choice.get("finish_reason"), private_clues, grammar=grammar,
                    candidate_labels=context.get("candidate_labels"))
                record["status"] = 200
                self.last_call_diagnostics = call_records
                outcome = self._make_outcome(
                    outcome=classified["outcome"], claim=classified["claim"],
                    finish_reason=classified["finish_reason"], content_length=classified["content_length"],
                    input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens"),
                    completion_tokens=usage.get("completion_tokens"), error_class=None, grammar=grammar,
                    answer=classified.get("answer"), max_tokens=max_tokens,
                    seed=seed if isinstance(seed, int) and not isinstance(seed, bool) else None)
                self.last_call_outcome = outcome
                return outcome
            except urllib.error.HTTPError as exc:
                status = int(exc.code)
                record["status"] = status
                headers = getattr(exc, "headers", None)
                after, after_present, after_valid = _numeric_seconds(headers, "retry-after")
                after_ms, ms_present, ms_valid = _numeric_seconds(headers, "retry-after-ms", scale=0.001)
                record["retry_after_present"] = after_present
                record["retry_after_valid"] = after_valid
                record["retry_after_ms_present"] = ms_present
                record["retry_after_ms_valid"] = ms_valid
                valid = [value for value in (after, after_ms) if value is not None]
                server_delay = max(valid) if valid else None
                error_class = f"writer_http_{status}_{bd.classify_http_status(status)}"
                record["error_class"] = error_class
                if status in LING_RETRYABLE_STATUSES and retry_ordinal < self.max_retries:
                    retry_ordinal += 1
                    continue
                self.last_call_diagnostics = call_records
                outcome = self._make_outcome(outcome=OUTCOME_WRITER_ERROR, claim=None, finish_reason=None,
                                             content_length=None, input_tokens=None, output_tokens=None,
                                             completion_tokens=None, error_class=error_class, grammar=grammar)
                self.last_call_outcome = outcome
                return outcome
            except OSError as exc:
                error_class = f"writer_network_{type(exc).__name__}"
                record["error_class"] = error_class
                if retry_ordinal < self.max_retries:
                    retry_ordinal += 1
                    continue
                self.last_call_diagnostics = call_records
                outcome = self._make_outcome(outcome=OUTCOME_WRITER_ERROR, claim=None, finish_reason=None,
                                             content_length=None, input_tokens=None, output_tokens=None,
                                             completion_tokens=None, error_class=error_class, grammar=grammar)
                self.last_call_outcome = outcome
                return outcome

    def write(self, context: Mapping[str, Any]) -> Mapping[str, Any]:
        outcome = self.write_outcome(context)
        kind = outcome["outcome"]
        if kind == OUTCOME_MESSAGE_CANDIDATE:
            return {"message": outcome["claim"]}
        if kind == OUTCOME_DELIBERATE_SILENCE:
            return {"message": None}
        raise WriterError(str(outcome.get("error_class") or kind))


__all__ = [
    "WRITER_OUTCOMES_VERSION", "WRITER_PARSER_VERSION", "SILENCE_TOKEN", "MESSAGE_PREFIX",
    "GRAMMAR_EXPLICIT_SILENCE", "GRAMMAR_ORIGINAL_LING", "OUTCOME_DELIBERATE_SILENCE",
    "OUTCOME_MESSAGE_CANDIDATE", "OUTCOME_EMPTY_OUTPUT", "OUTCOME_TRUNCATED_OUTPUT",
    "OUTCOME_UNPARSED_OUTPUT", "OUTCOME_NON_OWNED_CLAIM", "OUTCOME_WRITER_ERROR", "WRITER_OUTCOMES",
    "writer_schema", "writer_schema_hash", "classify_writer_completion", "LingWriterClientV5",
]
