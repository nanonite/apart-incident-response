"""J3b — Jev Choice wire codec (offline, no live calls).

Implements the TypeSafe System One Choice contract accepted in
``docs/jev-choice-wire-contract.md``:

- request: ``{model, state, questions:{candidate:{type,instructions,criteria}}}``
- response: ``{model, answers:{candidate:{type,choice,probabilities,confidence}}, usage}``

The transport is injected; tests use a fake client and an attributed fixture
copied from the pinned jev-dsl capture. The credential travels only in the
``Authorization`` header and never in the body, diagnostics or artifacts.
Wire conformance is *assumed* until #178 captures a real Jev response.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
import time
import urllib.error
import urllib.request
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .behavioral_discovery import classify_http_status, sanitize_provider_message
from .reasoning_baseline import OPENROUTER_ENV_FILE, PROJECT_ENV_FILE
from .task_families import FamilyInstance


#: Codec version for the real Choice wire shape. The offline scaffold's
#: ``JEV_ADAPTER_VERSION`` is preserved for the frozen v1 fixture only.
JEV_CHOICE_CODEC_VERSION = "jev-choice-wire-v1"
JEV_ADAPTER_VERSION = "jev-choice-receiver-v1"  # deprecated scaffold label

MAX_CHOICE_OPTIONS = 255
NORMALIZATION_TOLERANCE = 1e-6

JEV_SYSTEMONE_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
JEV_DEFAULT_MODEL = "jev-1.13.0"
JEV_QUESTION_ID = "candidate"
JEV_CHOICE_INSTRUCTIONS = (
    "Using the clues in `state`, assess how well each candidate in `criteria` "
    "fits those clues. Return a probability for every candidate in `criteria`."
)
JEV_CHOICE_STATE_SCHEMA = "jev-choice-state-v1"
JEV_CHOICE_CRITERIA_POLICY = "criteria_keys=exact_sorted_public_candidate_labels;values=null"
JEV_CHOICE_OPTION_ID_POLICY = "option_ids=exact_sorted_public_candidate_labels"
JEV_CHOICE_RESOLVED_MODEL_POLICY = "require_resolved_model"

JEV_RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504, 529})
JEV_MAX_RETRIES = 2
JEV_BACKOFF_INITIAL = 0.5
JEV_BACKOFF_MAX = 5.0
JEV_BACKOFF_JITTER = 0.25
JEV_TIMEOUT_DEFAULT = 30.0

JEV_PROTOCOL_KEY_PREFIX = "jev-choice-wire-v1|"

JEV_CREDENTIAL_ENV_NAMES = frozenset({
    "TYPESAFE", "TYPESAFE_API_KEY", "JEV_API_KEY", "JEV_CHOICE_API_KEY",
})

INVALID_RESPONSE_CLASSES = frozenset({
    "malformed_response",
    "missing_probabilities",
    "mismatched_option_set",
    "empty_distribution",
    "not_normalized",
    "negative_probability",
    "non_finite_probability",
    "oversized_option_set",
    "duplicate_option_ids",
    "missing_credentials",
    "transport_error",
    "provider_rejected",
    "response_not_evaluated",
    "missing_answer",
    "extra_answer",
    "wrong_answer_kind",
    "unknown_selection",
    "invalid_confidence",
    "malformed_usage",
    "model_drift",
})


class JevCredentialError(Exception):
    """Raised when the Jev credential is missing or malformed; never carries the key."""


class JevTransportError(Exception):
    """Sanitized transport failure (no bodies, no credentials)."""


class JevResponseError(Exception):
    """A successful HTTP response whose body is not valid JSON (never retried)."""


class JevProviderRejection(Exception):
    """A non-retryable provider HTTP rejection with a sanitized classification."""

    def __init__(self, status: int, classification: str, detail: str = "") -> None:
        self.status = int(status)
        self.classification = str(classification)
        self.detail = str(detail or "")
        super().__init__(f"http_{self.status}_{self.classification}")


def _secret_from_env_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        normalized = name.strip().removeprefix("export ").upper().replace("-", "_")
        if separator and normalized in JEV_CREDENTIAL_ENV_NAMES and value.strip():
            return value.strip().strip('"').strip("'")
    return None


@dataclass(frozen=True)
class JevCredentials:
    api_key: str | None = field(default=None, repr=False)
    source: str | None = None

    @property
    def present(self) -> bool:
        return bool(self.api_key)

    @property
    def shape_ok(self) -> bool:
        key = self.api_key or ""
        return len(key) >= 16 and not any(character.isspace() for character in key)

    @property
    def fingerprint(self) -> str | None:
        return hashlib.sha256(self.api_key.encode()).hexdigest()[:12] if self.api_key else None

    def redacted(self) -> dict[str, Any]:
        return {"present": self.present, "shape_ok": self.shape_ok, "source": self.source,
                "fingerprint": self.fingerprint}


def load_jev_credentials() -> JevCredentials:
    """Load the Jev/TypeSafe credential without exposing it."""

    for name in sorted(JEV_CREDENTIAL_ENV_NAMES):
        value = os.environ.get(name, "").strip()
        if value:
            return JevCredentials(value, f"env:{name}")
    configured = os.environ.get("APART_JEV_ENV_FILE", "").strip()
    for path in ([Path(configured)] if configured else []) + [PROJECT_ENV_FILE, OPENROUTER_ENV_FILE]:
        value = _secret_from_env_file(path)
        if value:
            return JevCredentials(value, f"file:{path.name}")
    return JevCredentials(None, None)


class JevChoiceClient:
    """Strict System One HTTP transport with Jev retries and physical-request accounting."""

    provider = "jev"

    def __init__(self, *, api_key: str | None = None, endpoint: str = JEV_SYSTEMONE_ENDPOINT,
                 model: str = JEV_DEFAULT_MODEL, timeout: float = JEV_TIMEOUT_DEFAULT,
                 max_retries: int = JEV_MAX_RETRIES, max_physical_requests: int | None = None,
                 sleep_fn: Any = time.sleep, backoff_initial: float = JEV_BACKOFF_INITIAL,
                 backoff_max: float = JEV_BACKOFF_MAX, backoff_jitter: float = JEV_BACKOFF_JITTER) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if max_physical_requests is not None and max_physical_requests < 1:
            raise ValueError("max_physical_requests must be positive when set")
        self.credentials = load_jev_credentials() if api_key is None else JevCredentials(api_key, "explicit")
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_physical_requests = max_physical_requests
        self.physical_attempts = 0
        self._sleep = sleep_fn
        self._backoff_initial = backoff_initial
        self._backoff_max = backoff_max
        self._backoff_jitter = backoff_jitter

    def build_request(self, request: Mapping[str, Any]) -> urllib.request.Request:
        payload = dict(request)
        payload["model"] = payload.get("model") or self.model
        key = self.credentials.api_key or ""
        return urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, sort_keys=True).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "endpoint": self.endpoint,
            "model": self.model,
            "credentials": self.credentials.redacted(),
            "max_retries": self.max_retries,
            "retryable_statuses": sorted(JEV_RETRYABLE_STATUSES),
            "max_physical_requests": self.max_physical_requests,
            "physical_attempts": self.physical_attempts,
            "raw_response_retained": False,
        }

    def _retry_after(self, exc: urllib.error.HTTPError) -> float | None:
        headers = getattr(exc, "headers", None)
        if headers is None:
            return None
        milliseconds = headers.get("retry-after-ms")
        if milliseconds is not None:
            try:
                return max(0.0, float(milliseconds) / 1000.0)
            except (TypeError, ValueError):
                pass
        seconds = headers.get("retry-after")
        if seconds is not None:
            try:
                return max(0.0, float(seconds))
            except (TypeError, ValueError):
                return None
        return None

    def _error_detail(self, exc: urllib.error.HTTPError) -> str:
        try:
            raw = exc.read().decode("utf-8", "replace")
        except Exception:
            return ""
        return sanitize_provider_message(raw, self.credentials.api_key)

    def _sleep_backoff(self, attempt: int, retry_after: float | None) -> None:
        delay = min(self._backoff_initial * (2 ** attempt), self._backoff_max)
        delay *= 1.0 - self._backoff_jitter
        if retry_after is not None:
            delay = max(delay, retry_after)
        self._sleep(max(delay, 0.0))

    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self.credentials.present or not self.credentials.shape_ok:
            raise JevCredentialError("missing_or_malformed_credentials")
        http_request = self.build_request(request)
        attempt = 0
        while True:
            if self.max_physical_requests is not None and self.physical_attempts >= self.max_physical_requests:
                raise JevTransportError("physical_request_cap_exhausted")
            self.physical_attempts += 1
            try:
                with urllib.request.urlopen(http_request, timeout=self.timeout) as response:
                    raw_body = response.read()
            except urllib.error.HTTPError as exc:
                status = int(exc.code)
                if status in JEV_RETRYABLE_STATUSES and attempt < self.max_retries:
                    self._sleep_backoff(attempt, self._retry_after(exc))
                    attempt += 1
                    continue
                if status in JEV_RETRYABLE_STATUSES:
                    raise JevTransportError(f"retry_exhausted_http_{status}")
                raise JevProviderRejection(status, classify_http_status(status), self._error_detail(exc))
            except (OSError, TypeError, KeyError) as exc:
                if attempt < self.max_retries:
                    self._sleep_backoff(attempt, None)
                    attempt += 1
                    continue
                raise JevTransportError(type(exc).__name__)
            # HTTP success: decode and parse once. A malformed body is an
            # invalid response, not a retryable transport failure.
            try:
                return json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise JevResponseError("malformed_json_body") from exc


@dataclass(frozen=True)
class ChoiceOption:
    option_id: str
    label: str


@dataclass(frozen=True)
class ChoiceState:
    instance_id: str
    agent_id: str
    condition: str
    question_id: str
    options: tuple[ChoiceOption, ...]
    state: Mapping[str, Any]
    instructions: str
    request_hash: str


@dataclass(frozen=True)
class ChoiceResponse:
    status: str
    probabilities: Mapping[str, float]
    selected_option_id: str | None
    confidence: float | None
    model: str
    version: str
    usage: Mapping[str, Any]
    request_hash: str
    error_class: str | None = None


class ChoiceClient(Protocol):
    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        ...


def _invalid(model: str, request_hash: str, error_class: str) -> ChoiceResponse:
    if error_class not in INVALID_RESPONSE_CLASSES:
        raise ValueError(f"unknown invalid-response class: {error_class}")
    return ChoiceResponse("invalid", {}, None, None, model, JEV_CHOICE_CODEC_VERSION, {}, request_hash,
                          error_class)


def jev_choice_protocol_key(*, model: str = JEV_DEFAULT_MODEL, endpoint: str = JEV_SYSTEMONE_ENDPOINT,
                            max_retries: int = JEV_MAX_RETRIES,
                            instructions: str = JEV_CHOICE_INSTRUCTIONS,
                            question_id: str = JEV_QUESTION_ID) -> str:
    """Return the additive Jev protocol key.

    Binds only static, instance-independent inputs that the adapter actually
    uses; per-instance clue values live in each row's ``request_hash`` instead.
    """

    components = {
        "codec_version": JEV_CHOICE_CODEC_VERSION,
        "endpoint": endpoint,
        "requested_model": model,
        "resolved_model_policy": JEV_CHOICE_RESOLVED_MODEL_POLICY,
        "state_schema": JEV_CHOICE_STATE_SCHEMA,
        "instructions": instructions,
        "criteria_policy": JEV_CHOICE_CRITERIA_POLICY,
        "question_id": question_id,
        "option_id_policy": JEV_CHOICE_OPTION_ID_POLICY,
        "normalization_tolerance": NORMALIZATION_TOLERANCE,
        "max_retries": max_retries,
        "retryable_statuses": sorted(JEV_RETRYABLE_STATUSES),
    }
    digest = hashlib.sha256(json.dumps(components, sort_keys=True).encode("utf-8")).hexdigest()
    return JEV_PROTOCOL_KEY_PREFIX + digest


def is_jev_protocol_key(key: Any) -> bool:
    return isinstance(key, str) and key.startswith(JEV_PROTOCOL_KEY_PREFIX)


def assert_single_jev_protocol_key(records: Iterable[Mapping[str, Any]]) -> str:
    """Refuse mixed/non-Jev protocol keys so Jev artifacts cannot be pooled."""

    keys = [record.get("protocol_key") for record in records]
    if not keys:
        raise ValueError("no records supplied")
    if any(key is None for key in keys):
        raise ValueError("record missing protocol_key")
    unique = sorted({str(key) for key in keys})
    if len(unique) != 1:
        raise ValueError(f"multiple protocol keys present: {unique}")
    key = unique[0]
    if not is_jev_protocol_key(key):
        raise ValueError(f"refusing non-Jev (mixed) protocol key: {key}")
    return key


class JevChoiceAdapter:
    provider = "jev"
    version = JEV_CHOICE_CODEC_VERSION

    def __init__(self, client: ChoiceClient, *, model: str = JEV_DEFAULT_MODEL,
                 instructions: str = JEV_CHOICE_INSTRUCTIONS, question_id: str = JEV_QUESTION_ID,
                 max_options: int = MAX_CHOICE_OPTIONS) -> None:
        if not 1 <= max_options <= MAX_CHOICE_OPTIONS:
            raise ValueError(f"max_options must be in 1..{MAX_CHOICE_OPTIONS}")
        self.client = client
        self.model = model
        self.instructions = instructions
        self.question_id = question_id
        self.max_options = max_options

    def _state_body(self, instance: FamilyInstance, agent: str, condition: str,
                    visible_messages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        view_condition = "FULL" if condition == "FULL" else condition
        view = instance.agent_view(agent, view_condition)
        if condition == "FULL":
            # Pooled clues once: joint_clues already contains the union of both
            # agents' private clues, so A's own private clues must not be
            # re-prepended (that would add repetition, not information).
            clues = list(view.get("joint_clues", []))
        else:
            clues = list(view.get("private_clues", []))
        state: dict[str, Any] = {
            "family": instance.family,
            "complexity": instance.complexity.value,
            "agent_id": agent,
            "clues": clues,
        }
        if condition == "COMM":
            state["visible_messages"] = [dict(message) for message in visible_messages]
        return state

    def _request_body(self, state: Mapping[str, Any], options: Sequence[ChoiceOption]) -> dict[str, Any]:
        return {
            "model": self.model,
            "state": dict(state),
            "questions": {
                self.question_id: {
                    "type": "choice",
                    "instructions": self.instructions,
                    "criteria": {option.option_id: None for option in options},
                }
            },
        }

    def build_state(self, instance: FamilyInstance, agent: str, condition: str,
                    visible_messages: Sequence[Mapping[str, Any]] = ()) -> ChoiceState:
        if condition not in {"ISO", "FULL", "COMM"}:
            raise ValueError("condition must be ISO, FULL or COMM")
        if condition != "COMM" and visible_messages:
            raise ValueError("visible_messages are only valid for COMM")
        labels = sorted(str(label) for label in instance.solutions)
        options = tuple(ChoiceOption(option_id=label, label=label) for label in labels)
        state = self._state_body(instance, agent, condition, visible_messages)
        body = self._request_body(state, options)
        request_hash = hashlib.sha256(
            json.dumps(body, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()
        return ChoiceState(instance.instance_id, agent, condition, self.question_id, options, state,
                           self.instructions, request_hash)

    def build_request(self, state: ChoiceState) -> dict[str, Any]:
        return self._request_body(state.state, state.options)

    def complete(self, state: ChoiceState) -> ChoiceResponse:
        if len(state.options) > self.max_options:
            return _invalid(self.model, state.request_hash, "oversized_option_set")
        ids = [option.option_id for option in state.options]
        if len(set(ids)) != len(ids):
            return _invalid(self.model, state.request_hash, "duplicate_option_ids")
        if not ids:
            return _invalid(self.model, state.request_hash, "empty_distribution")
        try:
            raw = self.client.complete(self.build_request(state))
        except JevCredentialError:
            return _invalid(self.model, state.request_hash, "missing_credentials")
        except JevProviderRejection:
            return _invalid(self.model, state.request_hash, "provider_rejected")
        except JevResponseError:
            return _invalid(self.model, state.request_hash, "malformed_response")
        except JevTransportError:
            return _invalid(self.model, state.request_hash, "transport_error")
        except Exception:
            return _invalid(self.model, state.request_hash, "transport_error")
        return self.parse(state, raw)

    def parse(self, state: ChoiceState, raw: Mapping[str, Any]) -> ChoiceResponse:
        if not isinstance(raw, Mapping):
            return _invalid(self.model, state.request_hash, "malformed_response")
        if "answers" not in raw:
            if "detail" in raw or "error_type" in raw:
                return _invalid(self.model, state.request_hash, "provider_rejected")
            return _invalid(self.model, state.request_hash, "response_not_evaluated")
        answers = raw.get("answers")
        if not isinstance(answers, Mapping):
            return _invalid(self.model, state.request_hash, "malformed_response")
        if state.question_id not in answers:
            return _invalid(self.model, state.request_hash, "missing_answer")
        if set(answers) != {state.question_id}:
            return _invalid(self.model, state.request_hash, "extra_answer")
        answer = answers[state.question_id]
        if not isinstance(answer, Mapping):
            return _invalid(self.model, state.request_hash, "malformed_response")
        if answer.get("type") != "choice":
            return _invalid(self.model, state.request_hash, "wrong_answer_kind")
        expected = {option.option_id for option in state.options}
        probabilities = answer.get("probabilities")
        if not isinstance(probabilities, Mapping) or not probabilities:
            return _invalid(self.model, state.request_hash, "missing_probabilities")
        if set(probabilities) != expected:
            return _invalid(self.model, state.request_hash, "mismatched_option_set")
        values: dict[str, float] = {}
        for option_id, value in probabilities.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                return _invalid(self.model, state.request_hash, "non_finite_probability")
            if value < 0:
                return _invalid(self.model, state.request_hash, "negative_probability")
            values[str(option_id)] = float(value)
        total = sum(values.values())
        if total <= 0:
            return _invalid(self.model, state.request_hash, "empty_distribution")
        if abs(total - 1.0) > NORMALIZATION_TOLERANCE:
            return _invalid(self.model, state.request_hash, "not_normalized")
        peak = max(values.values())
        argmax = {option_id for option_id, value in values.items() if value == peak}
        selected = answer.get("choice")
        if not isinstance(selected, str) or selected not in expected or selected not in argmax:
            return _invalid(self.model, state.request_hash, "unknown_selection")
        confidence = answer.get("confidence")
        if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                or not math.isfinite(confidence) or confidence < 0 or confidence > 1):
            return _invalid(self.model, state.request_hash, "invalid_confidence")
        usage = raw.get("usage")
        if not isinstance(usage, Mapping) or not all(
                isinstance(usage.get(name), int) and not isinstance(usage.get(name), bool)
                for name in ("input_tokens", "output_tokens")):
            return _invalid(self.model, state.request_hash, "malformed_usage")
        resolved_model = raw.get("model")
        if not isinstance(resolved_model, str) or resolved_model != self.model:
            return _invalid(self.model, state.request_hash, "model_drift")
        return ChoiceResponse("complete", values, selected, float(confidence), resolved_model,
                              self.version, dict(usage), state.request_hash)

    def map_submission(self, response: ChoiceResponse) -> str | None:
        return response.selected_option_id if response.status == "complete" else None

    def record(self, state: ChoiceState, response: ChoiceResponse) -> dict[str, Any]:
        protocol_key = jev_choice_protocol_key(
            model=self.model,
            endpoint=getattr(self.client, "endpoint", JEV_SYSTEMONE_ENDPOINT),
            max_retries=getattr(self.client, "max_retries", JEV_MAX_RETRIES),
            instructions=self.instructions,
            question_id=self.question_id,
        )
        return {
            "codec_version": self.version,
            "protocol_key": protocol_key,
            "instance_id": state.instance_id,
            "agent_id": state.agent_id,
            "condition": state.condition,
            "question_id": state.question_id,
            "option_count": len(state.options),
            "request_hash": state.request_hash,
            "status": response.status,
            "error_class": response.error_class,
            "resolved_model": response.model,
            "selected_option_id": response.selected_option_id,
            "probabilities": dict(response.probabilities),
            "probability_sum": round(sum(response.probabilities.values()), 9),
            "confidence": response.confidence,
            "usage": dict(response.usage),
            "physical_attempts": getattr(self.client, "physical_attempts", None),
            "endpoint": getattr(self.client, "endpoint", None),
            "raw_response_retained": False,
        }


class _OfflineFixtureClient:
    """Offline-only deterministic client for fixture artifacts; never a live provider."""

    def __init__(self, model: str = JEV_DEFAULT_MODEL) -> None:
        self.model = model

    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        questions = request["questions"]
        question_id = next(iter(questions))
        option_ids = list(questions[question_id]["criteria"])
        probability = 1.0 / len(option_ids)
        return {
            "model": self.model,
            "answers": {question_id: {
                "type": "choice",
                "choice": option_ids[0],
                "probabilities": {option_id: probability for option_id in option_ids},
                "confidence": probability,
            }},
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    from pathlib import Path

    from .jev_protocol import planning_low_instances

    parser = argparse.ArgumentParser(description="J3b offline Jev Choice wire codec fixture")
    parser.add_argument("--condition", choices=["ISO", "FULL", "COMM"], default=None)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    instance = planning_low_instances(1)[0]
    adapter = JevChoiceAdapter(_OfflineFixtureClient())
    conditions = [args.condition] if args.condition else ["ISO", "FULL", "COMM"]
    records = []
    for condition in conditions:
        state = adapter.build_state(instance, "A", condition)
        response = adapter.complete(state)
        records.append(adapter.record(state, response))
    document = {
        "codec_version": JEV_CHOICE_CODEC_VERSION,
        "mode": "offline_fixture",
        "assumed_wire_schema": True,
        "selected_cell": "planning:low",
        "records": records,
        "raw_response_retained": False,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
                               encoding="utf-8")
    print(json.dumps({"codec_version": JEV_CHOICE_CODEC_VERSION,
                      "conditions": [record["condition"] for record in records],
                      "statuses": [record["status"] for record in records]},
                     indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "INVALID_RESPONSE_CLASSES", "JEV_ADAPTER_VERSION", "JEV_CHOICE_CODEC_VERSION",
    "MAX_CHOICE_OPTIONS", "NORMALIZATION_TOLERANCE", "JEV_SYSTEMONE_ENDPOINT",
    "JEV_DEFAULT_MODEL", "JEV_QUESTION_ID", "JEV_CHOICE_INSTRUCTIONS",
    "JEV_CHOICE_STATE_SCHEMA", "JEV_CHOICE_CRITERIA_POLICY", "JEV_CHOICE_OPTION_ID_POLICY",
    "JEV_CHOICE_RESOLVED_MODEL_POLICY", "JEV_RETRYABLE_STATUSES", "JEV_MAX_RETRIES",
    "JEV_PROTOCOL_KEY_PREFIX", "JEV_CREDENTIAL_ENV_NAMES",
    "ChoiceClient", "ChoiceOption", "ChoiceResponse", "ChoiceState", "JevChoiceAdapter",
    "JevChoiceClient", "JevCredentialError", "JevCredentials", "JevProviderRejection",
    "JevResponseError", "JevTransportError", "assert_single_jev_protocol_key", "is_jev_protocol_key",
    "jev_choice_protocol_key", "load_jev_credentials", "main",
]
