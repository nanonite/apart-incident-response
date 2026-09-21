"""#186 — Ling/OpenRouter pacing writer transport v3 (offline).

Successor to the v1 Ling writer used by the stopped v2 optional-board pilot
(commit ``c555597``), which terminated on ``writer_http_429_rate_limited`` after
29 physical OpenRouter attempts for 25 logical writer turns. The 429 came from
the Ling/OpenRouter path, not Jev.

This transport adds a Ling-only monotonic rate limiter that spaces **every
physical OpenRouter attempt** (separate logical calls and retries alike) by at
least :data:`LING_MIN_ATTEMPT_INTERVAL_SECONDS` seconds, targeting the
documented 20 requests-per-minute free-model ceiling. Jev is never subject to
this limiter.

Retry handling reads only numeric ``Retry-After`` seconds and numeric
``retry-after-ms``; it never parses HTTP dates, never reads an error body, and
retains only bounded, sanitized per-attempt provenance. Provider response
bodies, complete headers, credentials and authorization values are never kept or
logged.

Pacing can relieve the documented per-minute ceiling but cannot guarantee relief
from a daily quota or an upstream-provider capacity limit.
"""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping

from . import behavioral_discovery as bd
from . import jev_replay_preregistration as pr
from .jev_choice_pilot import WriterError


LING_WRITER_TRANSPORT_VERSION = "ling-writer-openrouter-pacing-v3"
LING_MIN_ATTEMPT_INTERVAL_SECONDS = 3.25
LING_MAX_SERVER_REQUESTED_DELAY_SECONDS = 10.0
LING_PACING_ALGORITHM = "monotonic_min_interval_between_physical_attempt_starts"
LING_SUPPORTED_RETRY_HEADERS = ("retry-after", "retry-after-ms")
LING_RETRY_HEADER_PARSING = "numeric_only; no HTTP-date parsing; malformed/negative/non-finite/excessive ignored"
LING_RETRYABLE_STATUSES = tuple(sorted(pr.JEV_REPLAY_RETRYABLE))
LING_MAX_RETRIES = pr.LING_MAX_RETRIES
LING_BACKOFF_INITIAL_SECONDS = pr.LING_BACKOFF_INITIAL
LING_BACKOFF_MAX_SECONDS = pr.LING_BACKOFF_MAX
LING_TIMEOUT_SECONDS = 120.0
LING_MONOTONIC_CLOCK_NAME = "time.monotonic"

#: Sanitized provenance schema: exactly these keys, never provider bytes.
LING_PROVENANCE_FIELDS = (
    "logical_call_id", "physical_attempt", "retry_ordinal", "status",
    "delay_seconds", "delay_source", "delay_sources",
    "retry_after_present", "retry_after_valid",
    "retry_after_ms_present", "retry_after_ms_valid",
    "error_class",
)


def writer_transport_spec() -> dict[str, Any]:
    """The frozen, hash-bindable writer transport contract."""

    return {
        "writer_transport_version": LING_WRITER_TRANSPORT_VERSION,
        "provider": "openrouter",
        "min_attempt_interval_seconds": LING_MIN_ATTEMPT_INTERVAL_SECONDS,
        "pacing_algorithm": LING_PACING_ALGORITHM,
        "pacing_scope": "every physical attempt, across logical calls and retries; Ling only",
        "monotonic_clock": LING_MONOTONIC_CLOCK_NAME,
        "retryable_statuses": list(LING_RETRYABLE_STATUSES),
        "max_retries": LING_MAX_RETRIES,
        "backoff_initial_seconds": LING_BACKOFF_INITIAL_SECONDS,
        "backoff_max_seconds": LING_BACKOFF_MAX_SECONDS,
        "backoff_formula": "min(initial * 2**retry_ordinal, backoff_max)",
        "supported_retry_headers": list(LING_SUPPORTED_RETRY_HEADERS),
        "retry_header_parsing": LING_RETRY_HEADER_PARSING,
        "max_server_requested_delay_seconds": LING_MAX_SERVER_REQUESTED_DELAY_SECONDS,
        "delay_rule": "max(remaining_min_interval, exponential_backoff, valid_server_requested_delay)",
        "provenance_fields": list(LING_PROVENANCE_FIELDS),
        "retains_response_bodies": False,
        "retains_credentials": False,
    }


def _numeric_seconds(headers: Any, name: str, *, scale: float = 1.0) -> tuple[float | None, bool, bool]:
    """Return ``(seconds, present, valid)`` for a numeric retry header.

    HTTP-date values are intentionally rejected (no date parsing). Negative,
    non-finite, malformed, or above-cap values are present-but-invalid and are
    ignored. Values are never retained.
    """

    if headers is None or not hasattr(headers, "get"):
        return None, False, False
    raw = headers.get(name)
    if raw is None:
        # Plain mappings are case-sensitive; HTTPMessage is not. Fall back to a
        # case-insensitive scan without retaining any header value.
        try:
            for key, value in headers.items():
                if str(key).lower() == name.lower():
                    raw = value
                    break
        except (AttributeError, TypeError):
            raw = None
    if raw is None:
        return None, False, False
    try:
        value = float(str(raw).strip()) * scale
    except (TypeError, ValueError):
        return None, True, False
    if not math.isfinite(value) or value < 0.0 or value > LING_MAX_SERVER_REQUESTED_DELAY_SECONDS:
        return None, True, False
    return value, True, True


class LingWriterClientV3:
    """OpenRouter chat writer with monotonic per-attempt pacing and safe retries."""

    provider = "openrouter"
    transport_version = LING_WRITER_TRANSPORT_VERSION

    def __init__(self, *, model: str = pr.LING_MODEL, endpoint: str = pr.LING_ENDPOINT,
                 api_key: str | None = None, timeout: float = LING_TIMEOUT_SECONDS,
                 max_retries: int = LING_MAX_RETRIES, max_physical_requests: int | None = None,
                 min_attempt_interval_seconds: float = LING_MIN_ATTEMPT_INTERVAL_SECONDS,
                 clock: Callable[[], float] = time.monotonic,
                 sleep_fn: Callable[[float], None] = time.sleep) -> None:
        self.model = model
        self.endpoint = endpoint
        self.api_key = api_key if api_key is not None else bd._api_key()
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_physical_requests = max_physical_requests
        self.min_attempt_interval_seconds = float(min_attempt_interval_seconds)
        self.pacing_algorithm = LING_PACING_ALGORITHM
        self.supported_retry_headers = tuple(LING_SUPPORTED_RETRY_HEADERS)
        self.max_server_requested_delay_seconds = LING_MAX_SERVER_REQUESTED_DELAY_SECONDS
        self.backoff_initial_seconds = LING_BACKOFF_INITIAL_SECONDS
        self.backoff_max_seconds = LING_BACKOFF_MAX_SECONDS
        self.clock_name = LING_MONOTONIC_CLOCK_NAME
        self.physical_attempts = 0
        self.logical_calls = 0
        self.last_call_diagnostics: list[dict[str, Any]] = []
        self.rate_limit_records: list[dict[str, Any]] = []
        self._clock = clock
        self._sleep = sleep_fn
        self._last_attempt_start: float | None = None

    def _backoff(self, retry_ordinal: int) -> float:
        return min(self.backoff_initial_seconds * (2 ** retry_ordinal), self.backoff_max_seconds)

    def _remaining_min_interval(self) -> float:
        if self._last_attempt_start is None:
            return 0.0
        elapsed = self._clock() - self._last_attempt_start
        return max(0.0, self.min_attempt_interval_seconds - elapsed)

    def _delay(self, retry_ordinal: int, server_delay: float | None) -> tuple[float, str, list[str]]:
        candidates = {
            "min_interval": self._remaining_min_interval(),
            "backoff": self._backoff(retry_ordinal) if retry_ordinal > 0 else 0.0,
            "server_requested": server_delay or 0.0,
        }
        sources = sorted(name for name, value in candidates.items() if value > 0.0)
        if not sources:
            return 0.0, "none", []
        source = max(sources, key=lambda name: candidates[name])
        return candidates[source], source, sources

    def rate_limit_diagnostics(self) -> list[dict[str, Any]]:
        return [dict(record) for record in self.rate_limit_records]

    def write(self, context: Mapping[str, Any]) -> Mapping[str, Any]:  # pragma: no cover - live only
        if not self.api_key:
            self.last_call_diagnostics = []
            raise WriterError("writer_missing_credentials")
        self.logical_calls += 1
        logical_call_id = f"ling-call-{self.logical_calls}"
        clues = list(context.get("private_clues", ()))
        prompt = pr.LING_PROMPT_TEMPLATE.format(clues=clues)
        body = json.dumps({"model": self.model, "messages": [{"role": "user", "content": prompt}],
                           "max_tokens": pr.LING_MAX_TOKENS,
                           "temperature": pr.LING_TEMPERATURE}).encode()
        retry_ordinal = 0
        server_delay: float | None = None
        call_records: list[dict[str, Any]] = []
        while True:
            if self.max_physical_requests is not None and self.physical_attempts >= self.max_physical_requests:
                self.last_call_diagnostics = call_records
                raise WriterError("writer_physical_request_cap_exhausted")
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
                record["status"] = 200
                self.last_call_diagnostics = call_records
                break
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
                raise WriterError(error_class)
            except OSError as exc:
                error_class = f"writer_network_{type(exc).__name__}"
                record["error_class"] = error_class
                if retry_ordinal < self.max_retries:
                    retry_ordinal += 1
                    continue
                self.last_call_diagnostics = call_records
                raise WriterError(error_class)
        text = str(payload["choices"][0]["message"]["content"])
        if "MESSAGE:" in text:
            return {"message": text.split("MESSAGE:", 1)[1].strip()}
        return {"message": None}


__all__ = [
    "LING_WRITER_TRANSPORT_VERSION", "LING_MIN_ATTEMPT_INTERVAL_SECONDS",
    "LING_MAX_SERVER_REQUESTED_DELAY_SECONDS", "LING_PACING_ALGORITHM",
    "LING_SUPPORTED_RETRY_HEADERS", "LING_RETRY_HEADER_PARSING", "LING_RETRYABLE_STATUSES",
    "LING_MAX_RETRIES", "LING_BACKOFF_INITIAL_SECONDS", "LING_BACKOFF_MAX_SECONDS",
    "LING_TIMEOUT_SECONDS", "LING_MONOTONIC_CLOCK_NAME", "LING_PROVENANCE_FIELDS",
    "writer_transport_spec", "LingWriterClientV3",
]
