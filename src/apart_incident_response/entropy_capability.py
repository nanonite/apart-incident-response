"""Pinned output-kind logprob capability matrix and eligibility gate."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import time
import urllib.request
from typing import Any, Mapping, Sequence

from .behavioral_discovery import ENDPOINT, _api_key


CAPABILITY_VERSION = "entropy-capability-matrix-v1"
OUTPUT_KINDS = ("ordinary_text", "tool_call_arguments", "reasoning_bearing_text")


@dataclass(frozen=True)
class CapabilityProbeConfig:
    model: str
    endpoint: str = ENDPOINT
    max_requests: int = 3
    max_cost_usd: float = 20.0
    min_interval_seconds: float = 0.25
    top_logprobs: int = 5
    max_tokens: int = 96


def _topk_mass(records: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    masses: list[float] = []
    for record in records:
        values: dict[str, float] = {}
        for alternative in record.get("top_logprobs") or []:
            if isinstance(alternative, Mapping) and isinstance(alternative.get("token"), str):
                logprob = alternative.get("logprob")
                if isinstance(logprob, (int, float)) and math.isfinite(logprob):
                    values.setdefault(alternative["token"], math.exp(logprob))
        token, logprob = record.get("token"), record.get("logprob")
        if isinstance(token, str) and isinstance(logprob, (int, float)) and math.isfinite(logprob):
            values.setdefault(token, math.exp(logprob))
        if values:
            masses.append(min(1.0, sum(values.values())))
    return {
        "mean": sum(masses) / len(masses) if masses else None,
        "minimum": min(masses) if masses else None,
        "token_count": len(masses),
    }


def evaluate_probability_capture(
    *, output_kind: str, visible_text: str | None, records: Sequence[Mapping[str, Any]],
    response: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply independent record/alignment/mass/full-logit gates."""

    message = response.get("choices", [{}])[0].get("message", {}) if isinstance(response.get("choices", [{}])[0], Mapping) else {}
    reconstructed = "".join(str(record.get("token", "")) for record in records)
    if visible_text is None or not reconstructed:
        alignment = "unknown"
    elif reconstructed == visible_text:
        alignment = "aligned"
    else:
        alignment = "mismatch"
    mass = _topk_mass(records)
    full_logits = bool(response.get("full_logits") or response.get("logits"))
    return {
        "output_kind": output_kind,
        "provider_model": response.get("model"),
        "provider": response.get("provider"),
        "status": "records_present" if records else "records_missing",
        "token_record_count": len(records),
        "visible_text_sha256": hashlib.sha256(visible_text.encode()).hexdigest() if visible_text is not None else None,
        "visible_text_chars": len(visible_text) if visible_text is not None else None,
        "visible_span_alignment": alignment,
        "top_k_mass": mass,
        "full_vocabulary_logits_present": full_logits,
        "exact_entropy_eligible": full_logits and alignment == "aligned",
        "observed_token_partial_entropy_eligible": bool(records),
        "tool_call_present": bool(message.get("tool_calls")) if isinstance(message, Mapping) else False,
        "raw_response_retained": False,
    }


class OpenRouterCapabilityProbe:
    def __init__(self, config: CapabilityProbeConfig, *, api_key: str | None = None) -> None:
        if not config.model.endswith(":free"):
            raise ValueError("probe requires a free model unless an explicit paid budget policy is added")
        self.config = config
        self.api_key = _api_key() if api_key is None else api_key
        self.requests = 0
        self.cost_usd = 0.0
        self._last_request = 0.0

    def _payload(self, output_kind: str, seed: int) -> dict[str, Any]:
        if output_kind == "tool_call_arguments":
            return {
                "model": self.config.model,
                "messages": [{"role": "user", "content": "Call the tool with city=Paris and country=France."}],
                "tools": [{"type": "function", "function": {"name": "record", "parameters": {
                    "type": "object", "properties": {"city": {"type": "string"}, "country": {"type": "string"}}, "required": ["city", "country"]
                }}}],
                "tool_choice": {"type": "function", "function": {"name": "record"}},
                "logprobs": True, "top_logprobs": self.config.top_logprobs, "provider": {"require_parameters": True},
                "stream": False, "max_tokens": self.config.max_tokens, "seed": seed,
            }
        prompt = "Reply in one short sentence with ANSWER: Paris." if output_kind == "ordinary_text" else \
            "Give a concise reasoning-bearing answer, then end with ANSWER: Paris."
        return {
            "model": self.config.model, "messages": [{"role": "user", "content": prompt}],
            "logprobs": True, "top_logprobs": self.config.top_logprobs,
            "provider": {"require_parameters": True}, "stream": False,
            "max_tokens": self.config.max_tokens, "temperature": 0.0, "seed": seed,
        }

    def probe(self, output_kind: str, *, seed: int) -> dict[str, Any]:
        if output_kind not in OUTPUT_KINDS:
            raise ValueError(f"unknown output kind: {output_kind}")
        if self.requests >= self.config.max_requests:
            return {"output_kind": output_kind, "status": "not_run_request_cap", "raw_response_retained": False}
        if not self.api_key:
            return {"output_kind": output_kind, "status": "unavailable_credentials", "raw_response_retained": False}
        delay = self.config.min_interval_seconds - (time.monotonic() - self._last_request)
        if delay > 0:
            time.sleep(delay)
        self._last_request = time.monotonic()
        self.requests += 1
        request = urllib.request.Request(self.config.endpoint, data=json.dumps(self._payload(output_kind, seed)).encode(),
                                         headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                body = json.loads(response.read().decode())
            choices = body.get("choices") or [{}]
            choice = choices[0] if isinstance(choices[0], Mapping) else {}
            message = choice.get("message") if isinstance(choice.get("message"), Mapping) else {}
            logprobs = choice.get("logprobs") if isinstance(choice.get("logprobs"), Mapping) else {}
            records = tuple(record for record in (logprobs.get("content") or []) if isinstance(record, Mapping))
            visible = message.get("content") if isinstance(message.get("content"), str) else None
            usage = body.get("usage") if isinstance(body.get("usage"), Mapping) else {}
            cost = usage.get("cost") if isinstance(usage.get("cost"), (int, float)) else 0.0
            self.cost_usd += float(cost)
            result = evaluate_probability_capture(output_kind=output_kind, visible_text=visible, records=records, response=body)
            result.update({"finish_reason": choice.get("finish_reason"), "usage": {
                key: value for key, value in usage.items() if isinstance(value, (str, int, float, bool, type(None)))
            }, "cost_usd": float(cost)})
            return result
        except Exception as exc:
            return {"output_kind": output_kind, "status": "request_failed", "error_type": type(exc).__name__, "raw_response_retained": False}

    def run(self) -> dict[str, Any]:
        results = [self.probe(kind, seed=index + 7000) for index, kind in enumerate(OUTPUT_KINDS)]
        return {"capability_version": CAPABILITY_VERSION, "model": self.config.model,
                "endpoint": self.config.endpoint, "request_cap": self.config.max_requests,
                "requests": self.requests, "cost_usd": self.cost_usd, "results": results,
                "raw_responses_retained": False}


__all__ = ["CAPABILITY_VERSION", "CapabilityProbeConfig", "OpenRouterCapabilityProbe", "OUTPUT_KINDS", "evaluate_probability_capture"]
