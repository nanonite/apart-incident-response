"""J2 — offline Jev Choice receiver adapter (no live calls).

Maps a FamilyInstance's public option set to a fixed finite-decision Choice
schema, validates a full probability vector, and records reproducible, sanitized
provenance. A ``ChoiceClient`` transport is injected; tests use a fake client.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from .task_families import FamilyInstance


JEV_ADAPTER_VERSION = "jev-choice-receiver-v1"
MAX_CHOICE_OPTIONS = 255
NORMALIZATION_TOLERANCE = 1e-6

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
    "transport_error",
})


@dataclass(frozen=True)
class ChoiceOption:
    option_id: str
    label: str


@dataclass(frozen=True)
class ChoiceState:
    instance_id: str
    agent_id: str
    condition: str
    options: tuple[ChoiceOption, ...]
    clues: tuple[str, ...]
    visible_messages: tuple[Mapping[str, Any], ...]
    prompt: str
    prompt_hash: str


@dataclass(frozen=True)
class ChoiceResponse:
    status: str
    probabilities: Mapping[str, float]
    selected_option_id: str | None
    model: str
    version: str
    request_id: str | None
    prompt_hash: str
    usage: Mapping[str, Any]
    cost_usd: float
    error_class: str | None = None


class ChoiceClient(Protocol):
    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        ...


def _invalid(model: str, prompt_hash: str, error_class: str) -> ChoiceResponse:
    if error_class not in INVALID_RESPONSE_CLASSES:
        raise ValueError(f"unknown invalid-response class: {error_class}")
    return ChoiceResponse("invalid", {}, None, model, JEV_ADAPTER_VERSION, None, prompt_hash, {}, 0.0,
                          error_class)


class JevChoiceAdapter:
    provider = "jev"
    version = JEV_ADAPTER_VERSION

    def __init__(self, client: ChoiceClient, *, model: str = "jev-choice",
                 max_options: int = MAX_CHOICE_OPTIONS) -> None:
        if not 1 <= max_options <= MAX_CHOICE_OPTIONS:
            raise ValueError(f"max_options must be in 1..{MAX_CHOICE_OPTIONS}")
        self.client = client
        self.model = model
        self.max_options = max_options

    def build_state(self, instance: FamilyInstance, agent: str, condition: str,
                    visible_messages: Sequence[Mapping[str, Any]] = ()) -> ChoiceState:
        view_condition = "FULL" if condition == "FULL" else condition
        view = instance.agent_view(agent, view_condition)
        labels = list(view.get("candidate_labels", []))
        options = tuple(ChoiceOption(option_id=str(label), label=str(label)) for label in labels)
        clues = tuple(view.get("private_clues", [])) + tuple(view.get("joint_clues", []))
        visible = tuple(dict(message) for message in visible_messages)
        prompt = json.dumps({
            "instruction": "Return a probability for each option_id.",
            "family": instance.family,
            "condition": condition,
            "options": [option.option_id for option in options],
            "clues": list(clues),
            "visible_messages": list(visible),
        }, sort_keys=True)
        return ChoiceState(instance.instance_id, agent, condition, options, tuple(clues),
                           visible, prompt, hashlib.sha256(prompt.encode()).hexdigest())

    def build_request(self, state: ChoiceState) -> dict[str, Any]:
        return {
            "model": self.model,
            "options": [option.option_id for option in state.options],
            "prompt": state.prompt,
            "prompt_hash": state.prompt_hash,
        }

    def complete(self, state: ChoiceState) -> ChoiceResponse:
        if len(state.options) > self.max_options:
            return _invalid(self.model, state.prompt_hash, "oversized_option_set")
        ids = [option.option_id for option in state.options]
        if len(set(ids)) != len(ids):
            return _invalid(self.model, state.prompt_hash, "duplicate_option_ids")
        if not ids:
            return _invalid(self.model, state.prompt_hash, "empty_distribution")
        try:
            raw = self.client.complete(self.build_request(state))
        except Exception:
            return _invalid(self.model, state.prompt_hash, "transport_error")
        return self.parse(state, raw)

    def parse(self, state: ChoiceState, raw: Mapping[str, Any]) -> ChoiceResponse:
        if not isinstance(raw, Mapping):
            return _invalid(self.model, state.prompt_hash, "malformed_response")
        probabilities = raw.get("probabilities")
        if not isinstance(probabilities, Mapping) or not probabilities:
            return _invalid(self.model, state.prompt_hash, "missing_probabilities")
        expected = {option.option_id for option in state.options}
        if set(probabilities) != expected:
            return _invalid(self.model, state.prompt_hash, "mismatched_option_set")
        values: dict[str, float] = {}
        for option_id, value in probabilities.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                return _invalid(self.model, state.prompt_hash, "non_finite_probability")
            if value < 0:
                return _invalid(self.model, state.prompt_hash, "negative_probability")
            values[str(option_id)] = float(value)
        total = sum(values.values())
        if total <= 0:
            return _invalid(self.model, state.prompt_hash, "empty_distribution")
        if abs(total - 1.0) > NORMALIZATION_TOLERANCE:
            return _invalid(self.model, state.prompt_hash, "not_normalized")
        selected = raw.get("selected_option_id")
        if selected is None:
            selected = max(values, key=values.get)
        elif str(selected) not in expected:
            return _invalid(self.model, state.prompt_hash, "mismatched_option_set")
        usage = raw.get("usage") if isinstance(raw.get("usage"), Mapping) else {}
        cost = usage.get("cost")
        return ChoiceResponse(
            "complete", values, str(selected), str(raw.get("model") or self.model),
            str(raw.get("version") or self.version), raw.get("request_id"), state.prompt_hash,
            dict(usage), float(cost) if isinstance(cost, (int, float)) else 0.0)

    def map_submission(self, response: ChoiceResponse) -> str | None:
        return response.selected_option_id if response.status == "complete" else None

    def record(self, state: ChoiceState, response: ChoiceResponse) -> dict[str, Any]:
        return {
            "adapter_version": self.version,
            "instance_id": state.instance_id,
            "agent_id": state.agent_id,
            "condition": state.condition,
            "option_count": len(state.options),
            "prompt_hash": state.prompt_hash,
            "status": response.status,
            "error_class": response.error_class,
            "model": response.model,
            "version": response.version,
            "request_id": response.request_id,
            "selected_option_id": response.selected_option_id,
            "probabilities": dict(response.probabilities),
            "probability_sum": round(sum(response.probabilities.values()), 9),
            "usage": dict(response.usage),
            "cost_usd": response.cost_usd,
            "raw_response_retained": False,
        }


class _UniformFixtureClient:
    """Offline-only deterministic client for fixture artifacts; never a live provider."""

    def __init__(self, model: str = "jev-choice-fixture") -> None:
        self.model = model

    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        options = list(request["options"])
        return {
            "probabilities": {option: 1.0 / len(options) for option in options},
            "model": self.model,
            "version": "offline-fixture",
            "request_id": f"fixture-{str(request.get('prompt_hash'))[:8]}",
            "usage": {"cost": 0.0},
        }


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    from pathlib import Path

    from .jev_protocol import planning_low_instances

    parser = argparse.ArgumentParser(description="J2 offline Jev Choice adapter fixture")
    parser.add_argument("--condition", choices=["ISO", "FULL", "COMM"], default=None)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    instance = planning_low_instances(1)[0]
    adapter = JevChoiceAdapter(_UniformFixtureClient())
    conditions = [args.condition] if args.condition else ["ISO", "FULL", "COMM"]
    records = []
    for condition in conditions:
        state = adapter.build_state(instance, "A", condition)
        response = adapter.complete(state)
        records.append(adapter.record(state, response))
    document = {
        "adapter_version": JEV_ADAPTER_VERSION,
        "mode": "offline_fixture",
        "selected_cell": "planning:low",
        "records": records,
        "raw_response_retained": False,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
                               encoding="utf-8")
    print(json.dumps({"adapter_version": JEV_ADAPTER_VERSION,
                      "conditions": [record["condition"] for record in records],
                      "statuses": [record["status"] for record in records]},
                     indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "INVALID_RESPONSE_CLASSES", "JEV_ADAPTER_VERSION", "MAX_CHOICE_OPTIONS",
    "NORMALIZATION_TOLERANCE", "ChoiceClient", "ChoiceOption", "ChoiceResponse",
    "ChoiceState", "JevChoiceAdapter", "main",
]
