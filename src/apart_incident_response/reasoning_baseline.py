"""A small, opt-in bottom-of-reasoning baseline for free OpenRouter models.

This is a capability smoke test, not evidence for the communication battery.
It uses independent closed-world questions, an exact checker, and a strict
request cap.  Results retain invalid and unavailable cases without storing raw
model responses or credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping, Protocol, Sequence


OPENROUTER_CHAT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_FREE_MODEL = "inclusionai/ling-3.0-flash-vl:free"
OPENROUTER_ENV_FILE = Path.home() / ".config" / "apart-incident-response" / "openrouter.env"
PROJECT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
FREE_MODEL_CANDIDATES = (
    "inclusionai/ling-3.0-flash-vl:free",
    "nex-agi/nex-n2.5-mini:free",
    "nex-agi/nex-n2.5-pro:free",
    "inclusionai/ling-3.0-flash-sante:free",
    "inclusionai/ling-3.0-flash-fin:free",
    "liquid/lfm-2.5-2.6b:free",
)
BASELINE_VERSION = "reasoning-floor-v1"


@dataclass(frozen=True)
class ReasoningCase:
    case_id: str
    level: str
    prompt: str
    expected: str
    checker: Callable[[str, str], bool]


@dataclass(frozen=True)
class BaselineResponse:
    text: str
    model: str
    logprobs: tuple[Mapping[str, Any], ...] = ()
    usage: Mapping[str, Any] = None
    status: str = "complete"
    error: str | None = None

    @property
    def logprob_coverage(self) -> float | None:
        """Visible-token coverage, only when the provider supplies its denominator."""

        visible_tokens = (self.usage or {}).get("visible_completion_tokens")
        if isinstance(visible_tokens, int) and visible_tokens > 0 and self.logprobs:
            return min(1.0, len(self.logprobs) / visible_tokens)
        return None

    @property
    def topk_mass_coverage(self) -> float | None:
        """Mean probability mass represented by returned top-k alternatives."""

        if not self.logprobs:
            return None
        masses: list[float] = []
        for record in self.logprobs:
            values: dict[str, float] = {}
            for alternative in record.get("top_logprobs") or []:
                if not isinstance(alternative, Mapping) or not isinstance(alternative.get("token"), str):
                    continue
                logprob = alternative.get("logprob")
                if isinstance(logprob, (int, float)) and math.isfinite(logprob):
                    values.setdefault(alternative["token"], math.exp(logprob))
            token, logprob = record.get("token"), record.get("logprob")
            if isinstance(token, str) and isinstance(logprob, (int, float)) and math.isfinite(logprob):
                values.setdefault(token, math.exp(logprob))
            if values:
                masses.append(min(1.0, sum(values.values())))
        return sum(masses) / len(masses) if masses else None


class BaselineProvider(Protocol):
    model: str

    def complete(self, prompt: str, *, max_tokens: int, seed: int) -> BaselineResponse:
        ...


def _load_openrouter_key() -> str | None:
    for name in ("OPENROUTER_API_KEY", "OPEN_ROUTER_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    configured_file = os.environ.get("APART_OPENROUTER_ENV_FILE", "").strip()
    env_files = ([Path(configured_file)] if configured_file else []) + [PROJECT_ENV_FILE, OPENROUTER_ENV_FILE]
    for env_file in env_files:
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            name = name.strip().removeprefix("export ")
            normalized_name = name.upper().replace("-", "_")
            if separator and normalized_name in {"OPENROUTER_API_KEY", "OPEN_ROUTER_API_KEY"} and value.strip():
                return value.strip().strip('"').strip("'")
    return None


def _answer_checker(response: str, expected: str) -> bool:
    match = re.search(r"answer\s*:\s*([^\n.]+)", response, flags=re.IGNORECASE)
    return bool(match and match.group(1).strip().casefold() == expected.casefold())


def default_cases() -> tuple[ReasoningCase, ...]:
    return (
        ReasoningCase(
            "floor-arithmetic", "low",
            "A lab has 24 kits, receives 18, and issues 15. Reply exactly as ANSWER: <number>.",
            "27", _answer_checker,
        ),
        ReasoningCase(
            "floor-conjunction", "medium",
            "Alpha is available at 09:00 or 11:00 but not 10:00. Beta is available at 10:00 or 11:00 but not 09:00. Reply exactly as ANSWER: <time> with the earliest shared time.",
            "11:00", _answer_checker,
        ),
        ReasoningCase(
            "floor-rule-chain", "high",
            "Fictional rules: a request is approved only if verified and within budget. The request is verified and within budget. Reply exactly as ANSWER: approve or ANSWER: reject.",
            "approve", _answer_checker,
        ),
    )


class OpenRouterFreeProvider:
    """OpenRouter-compatible provider restricted to an explicit ``:free`` slug."""

    def __init__(self, model: str = DEFAULT_FREE_MODEL, *, endpoint: str = OPENROUTER_CHAT_ENDPOINT,
                 api_key: str | None = None, top_logprobs: int = 5, timeout: float = 120.0) -> None:
        if not model.endswith(":free"):
            raise ValueError("reasoning baseline only permits models with a :free suffix")
        if not model or model.startswith("/") or model.count("/") != 1:
            raise ValueError("model must be an OpenRouter author/model slug")
        if not 0 <= top_logprobs <= 20:
            raise ValueError("top_logprobs must be between 0 and 20")
        self.model = model
        self.endpoint = endpoint
        self.api_key = _load_openrouter_key() if api_key is None else api_key
        self.top_logprobs = top_logprobs
        self.timeout = timeout
        self.provider = "openrouter"
        self.version = "openrouter-free-v1"

    def respond(self, context: Any) -> Any:
        """Adapt a battery context without retaining the raw provider response."""

        from .communication_runner import AgentResponse

        prompt = json.dumps({
            "instruction": context.task_view.get("task_instruction"),
            "family": context.task_view.get("family"),
            "condition": context.condition.value,
            "candidate_labels": context.task_view.get("candidate_labels", []),
            "joint_candidate_labels": context.task_view.get("joint_candidate_labels"),
            "private_clues": context.task_view.get("private_clues", []),
            "visible_messages": list(context.visible_messages),
        }, sort_keys=True)
        response = self.complete(prompt, max_tokens=min(context.token_budget, 96), seed=context.turn)
        answer_match = re.search(r"answer\s*:\s*([^\n.]+)", response.text, flags=re.IGNORECASE)
        answer = answer_match.group(1).strip() if answer_match else None
        return AgentResponse(
            answer=answer,
            output_text=response.text,
            logprob_coverage=response.logprob_coverage,
            logprob_mass_coverage=response.topk_mass_coverage,
            logprob_status="records_present" if response.logprobs else "unavailable",
            failure_reason=(response.error or "logprobs unavailable") if not response.logprobs else response.error,
        )

    def complete(self, prompt: str, *, max_tokens: int, seed: int) -> BaselineResponse:
        if not self.api_key:
            return BaselineResponse("", self.model, status="unavailable", error="OPENROUTER_API_KEY is required")
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "seed": seed,
            "logprobs": True,
            "top_logprobs": self.top_logprobs,
            "provider": {"require_parameters": True},
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            choice = (body.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content = choice.get("logprobs") or {}
            records = content.get("content") or []
            return BaselineResponse(
                str(message.get("content") or ""), str(body.get("model") or self.model),
                tuple(record for record in records if isinstance(record, Mapping)),
                body.get("usage") if isinstance(body.get("usage"), Mapping) else {},
                "complete", None,
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            return BaselineResponse("", self.model, status="unavailable", error=type(exc).__name__ + ": " + str(exc))


class BaselineRunner:
    def __init__(self, provider: BaselineProvider, *, max_requests: int = 3, max_tokens: int = 96) -> None:
        if not 1 <= max_requests <= 3:
            raise ValueError("bottom-of-reasoning baseline is capped at three requests")
        if not 1 <= max_tokens <= 256:
            raise ValueError("max_tokens must be between 1 and 256")
        self.provider = provider
        self.max_requests = max_requests
        self.max_tokens = max_tokens

    def run(self, cases: Sequence[ReasoningCase] | None = None) -> dict[str, Any]:
        selected = tuple(cases or default_cases())[: self.max_requests]
        rows: list[dict[str, Any]] = []
        for index, case in enumerate(selected):
            started = time.monotonic()
            response = self.provider.complete(case.prompt, max_tokens=self.max_tokens, seed=index)
            valid = response.status == "complete" and bool(response.text)
            correct = case.checker(response.text, case.expected) if valid else False
            coverage = response.logprob_coverage
            logprob_status = "unavailable" if not response.logprobs else (
                "complete" if coverage is not None and coverage >= 1.0 else
                "partial_token_coverage" if coverage is not None else
                "records_present_visible_coverage_unknown"
            )
            rows.append({
                "case_id": case.case_id, "level": case.level, "model": response.model,
                "status": "valid" if valid else response.status,
                "correct": correct if valid else None,
                "response_sha256": hashlib.sha256(response.text.encode()).hexdigest() if response.text else None,
                "response_chars": len(response.text),
                "latency_seconds": time.monotonic() - started,
                "logprob_status": logprob_status,
                "logprob_token_count": len(response.logprobs),
                "logprob_coverage": coverage,
                "topk_mass_coverage": response.topk_mass_coverage,
                "reasoning_tokens": ((response.usage or {}).get("completion_tokens_details") or {}).get("reasoning_tokens"),
                "error_type": response.error.split(":", 1)[0] if response.error else None,
            })
        valid_rows = [row for row in rows if row["status"] == "valid"]
        return {
            "baseline_version": BASELINE_VERSION,
            "provider": "openrouter",
            "model": getattr(self.provider, "model", "unknown"),
            "mode": "bottom_of_reasoning_capability_smoke",
            "request_cap": self.max_requests,
            "requests_made": len(rows),
            "estimated_cost_usd": 0.0 if str(getattr(self.provider, "model", "")).endswith(":free") else None,
            "valid_runs": len(valid_rows),
            "invalid_runs": len(rows) - len(valid_rows),
            "accuracy": sum(bool(row["correct"]) for row in valid_rows) / len(valid_rows) if valid_rows else None,
            "rows": rows,
            "raw_responses_retained": False,
            "credentials_retained": False,
            "scientific_battery_evidence": False,
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_FREE_MODEL, choices=FREE_MODEL_CANDIDATES)
    parser.add_argument("--live", action="store_true", help="make at most three free-provider requests")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.live:
        report = BaselineRunner(OpenRouterFreeProvider(args.model)).run()
    else:
        report = {"baseline_version": BASELINE_VERSION, "status": "not_run", "model": args.model,
                  "next_step": "re-run with --live after provider capability approval", "estimated_cost_usd": 0.0}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BASELINE_VERSION", "DEFAULT_FREE_MODEL", "FREE_MODEL_CANDIDATES", "BaselineResponse",
    "BaselineRunner", "OpenRouterFreeProvider", "ReasoningCase", "default_cases", "main",
]
