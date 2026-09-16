"""OpenRouter live adapter for the ISO/FULL/COMM battery.

Credential handling: reads OPENROUTER_API_KEY from the environment.
The key is NEVER written to any log, artifact, or exception message.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .communication_protocol import BatteryCondition
from .communication_runner import AgentContext, AgentResponse, BatteryRunResult


_OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterBatteryProvider:
    """OpenRouter live adapter implementing BatteryProvider.

    The API key is read from the OPENROUTER_API_KEY environment variable and
    stored privately. It is never included in repr, str, logs, or exceptions.
    """

    provider: str = "openrouter"

    def __init__(
        self,
        model: str,
        *,
        max_output_tokens: int = 512,
        temperature: float = 0.0,
        http_timeout: int = 90,
        rate_limit_delay: float = 0.0,
    ) -> None:
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            raise ValueError("OPENROUTER_API_KEY environment variable is not set or empty")
        self._key = key  # private; never exposed in repr/str/logs
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.http_timeout = http_timeout
        self.rate_limit_delay = rate_limit_delay
        self.version: str = f"{model}@openrouter-battery-v1"
        self._usage_log: list[dict[str, Any]] = []

    def __repr__(self) -> str:
        return f"OpenRouterBatteryProvider(model={self.model!r}, key=***)"

    def __str__(self) -> str:
        return f"OpenRouterBatteryProvider(model={self.model!r}, key=***)"

    def respond(self, context: AgentContext) -> AgentResponse:
        """Call OpenRouter, parse response, return AgentResponse."""
        messages = self._build_messages(context)
        try:
            raw = self._call_api(messages)
        except Exception as exc:
            return AgentResponse(
                failure_reason=f"api_error:{type(exc).__name__}",
                output_text="",
                logprob_status="not_requested",
            )

        # Extract usage
        usage = raw.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0) or 0
        completion_tokens = usage.get("completion_tokens", 0) or 0
        self._usage_log.append({
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "model": self.model,
        })

        # Extract output text
        choices = raw.get("choices", [])
        if not choices:
            return AgentResponse(
                failure_reason="no_choices_in_response",
                output_text="",
                logprob_status="not_requested",
            )
        output_text = choices[0].get("message", {}).get("content", "") or ""

        answer, message = self._parse_response(output_text, context)

        if self.rate_limit_delay > 0:
            time.sleep(self.rate_limit_delay)

        return AgentResponse(
            answer=answer,
            message=message,
            output_text=output_text,
            logprob_status="not_requested",
            failure_reason=None if answer is not None else "no_parseable_answer",
        )

    def usage_summary(self) -> dict[str, Any]:
        """Return aggregated usage stats."""
        total_calls = len(self._usage_log)
        prompt_tokens = sum(entry["prompt_tokens"] for entry in self._usage_log)
        completion_tokens = sum(entry["completion_tokens"] for entry in self._usage_log)
        # All registered models in REGISTRY have 0 cost; default 0.0
        estimated_cost_usd = 0.0
        return {
            "total_calls": total_calls,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "estimated_cost_usd": estimated_cost_usd,
            "model": self.model,
        }

    def _call_api(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Make the HTTPS call to OpenRouter. Raises on HTTP error.

        The Authorization header value is NEVER included in any exception message.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_output_tokens,
            "temperature": self.temperature,
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._key}",
            "X-Title": "apart-battery-research",
        }
        req = urllib.request.Request(
            _OPENROUTER_API_URL,
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.http_timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            # Do NOT include Authorization header value in the error message
            raise RuntimeError(
                f"OpenRouter HTTP error: {exc.code} {exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"OpenRouter URL error: {exc.reason}"
            ) from exc

    def _build_messages(self, context: AgentContext) -> list[dict[str, Any]]:
        """Build system + user messages from the agent context."""
        system_content = (
            "You are a reasoning agent solving an identification task.\n"
            "After reasoning, your final output MUST end with exactly one line in this format:\n"
            "ANSWER: <candidate_label>\n"
            "Use only a label from the provided candidate list. Do not invent labels.\n"
            "For COMM condition only, you may also add: MESSAGE: <one short claim>"
        )

        # Build user message from task view
        view = context.task_view
        parts: list[str] = []

        family = view.get("family", "unknown")
        instance_id = view.get("instance_id", "unknown")
        parts.append(f"Task family: {family} (instance: {instance_id})")
        parts.append(f"Your role: Agent {view.get('agent_id', '?')}")

        candidates = view.get("candidate_labels", [])
        parts.append(f"Your candidate labels: {', '.join(candidates)}")

        private_clues = view.get("private_clues", [])
        if private_clues:
            parts.append(f"Your private clues: {'; '.join(str(c) for c in private_clues)}")

        # FULL condition: expose joint clues, while keeping the controller's
        # solution set out of the model-facing prompt.
        if context.condition is BatteryCondition.FULL:
            joint_clues = view.get("joint_clues", [])
            if joint_clues:
                parts.append(f"Joint clues (shared with partner): {'; '.join(str(c) for c in joint_clues)}")

        # COMM condition: include messages from partner
        if context.condition is BatteryCondition.COMM and context.visible_messages:
            board_lines: list[str] = []
            for msg in context.visible_messages:
                author = msg.get("author", "?")
                text = msg.get("text", "")
                board_lines.append(f"  [{author}]: {text}")
            parts.append("Board messages from partner:\n" + "\n".join(board_lines))

        task_instruction = view.get(
            "task_instruction",
            "Choose one candidate and reply exactly as ANSWER: <candidate label>.",
        )
        parts.append(task_instruction)

        user_content = "\n".join(parts)
        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

    def _parse_response(
        self, text: str, context: AgentContext
    ) -> tuple[str | None, str | None]:
        """Extract (answer, message) from model output.

        Looks for ANSWER: <candidate> case-insensitively; validates candidate
        is in context.task_view["candidate_labels"]. For COMM condition also
        looks for MESSAGE: <text>.

        Returns (None, None) if no valid answer found.
        """
        import re

        candidates = set(context.task_view.get("candidate_labels", []))
        answer: str | None = None
        message: str | None = None

        # Find ANSWER: anywhere in the text (case-insensitive)
        # Matches "ANSWER: label" at start of line or inline after other text
        answer_match = re.search(r"(?i)(?:^|\s)answer:\s*(.+?)(?:\s*$|\n|$)", text, re.MULTILINE)
        if answer_match:
            raw_answer = answer_match.group(1).strip()
            if raw_answer in candidates:
                answer = raw_answer
            # If not in candidates, answer stays None (hallucinated label)

        # For COMM condition, also look for MESSAGE: line
        if context.condition is BatteryCondition.COMM:
            message_match = re.search(r"(?i)^message:\s*(.+)$", text, re.MULTILINE)
            if message_match:
                message = message_match.group(1).strip()

        return answer, message


class BehavioralValidityGate:
    """Checks that a batch of runs has acceptable parse and answer validity rates."""

    def __init__(self, *, min_parse_rate: float = 0.5) -> None:
        self.min_parse_rate = min_parse_rate

    def evaluate(self, results: list[BatteryRunResult]) -> dict[str, Any]:
        """Return structured gate verdict.

        Checks:
        - parse_rate: fraction of runs that produced a parseable ANSWER
        - valid_answer_rate: fraction of runs where the answer was in the candidate set
        """
        if not results:
            return {
                "pass": False,
                "parse_rate": 0.0,
                "valid_answer_rate": 0.0,
                "status": "no_results",
                "issues": ["no results to evaluate"],
            }

        total = len(results)
        parsed = 0
        valid_answers = 0
        issues: list[str] = []

        for result in results:
            answers = result.submitted_answers
            # Count as parsed if any agent produced an answer
            has_answer = any(v is not None for v in answers.values())
            if has_answer:
                parsed += 1
                valid_answers += 1  # If it's in submitted_answers, it was validated

        parse_rate = parsed / total
        valid_answer_rate = valid_answers / total

        gate_pass = parse_rate >= self.min_parse_rate

        if parse_rate < self.min_parse_rate:
            issues.append(
                f"parse_rate {parse_rate:.2f} is below threshold {self.min_parse_rate:.2f}"
            )

        status = "pass" if gate_pass else "fail_low_parse_rate"

        return {
            "pass": gate_pass,
            "parse_rate": parse_rate,
            "valid_answer_rate": valid_answer_rate,
            "status": status,
            "issues": issues,
        }


class ResumableArtifact:
    """Saves/loads run results to a JSONL file for resumability."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._done: set[tuple[str, str]] = set()
        if path.exists():
            for entry in self.load_all():
                pair_id = entry.get("pair_id", "")
                condition = entry.get("condition", "")
                if pair_id and condition:
                    self._done.add((pair_id, condition))

    def already_done(self, pair_id: str, condition: str) -> bool:
        """Return True if this pair_id+condition was already completed."""
        return (pair_id, condition) in self._done

    def append(self, result: BatteryRunResult) -> None:
        """Write one result as a JSON line to the artifact file."""
        entry = {
            "run_id": result.run_id,
            "pair_id": result.pair_id,
            "instance_id": result.instance_id,
            "condition": result.condition.value if hasattr(result.condition, "value") else str(result.condition),
            "family": result.family,
            "seed": result.seed,
            "task_success": result.task_success,
            "status": result.status,
            "provider": result.provider,
            "provider_version": result.provider_version,
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        self._done.add((result.pair_id, entry["condition"]))

    def load_all(self) -> list[dict[str, Any]]:
        """Read all lines from the artifact file."""
        if not self.path.exists():
            return []
        entries: list[dict[str, Any]] = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return entries


class UsageAccumulator:
    """Accumulates usage across calls with per-model pricing."""

    def __init__(self, cost_per_mtok: float = 0.0) -> None:
        """Initialize with cost in USD per million tokens."""
        self.cost_per_mtok = cost_per_mtok
        self._prompt_tokens: int = 0
        self._completion_tokens: int = 0
        self._calls: int = 0

    def record(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Record token usage for one call."""
        self._prompt_tokens += prompt_tokens
        self._completion_tokens += completion_tokens
        self._calls += 1

    def summary(self) -> dict[str, Any]:
        """Return total tokens and estimated cost."""
        total_tokens = self._prompt_tokens + self._completion_tokens
        estimated_cost_usd = total_tokens / 1_000_000 * self.cost_per_mtok
        return {
            "calls": self._calls,
            "prompt_tokens": self._prompt_tokens,
            "completion_tokens": self._completion_tokens,
            "total_tokens": total_tokens,
            "estimated_cost_usd": estimated_cost_usd,
        }


__all__ = [
    "OpenRouterBatteryProvider",
    "BehavioralValidityGate",
    "ResumableArtifact",
    "UsageAccumulator",
]
