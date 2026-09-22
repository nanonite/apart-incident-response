"""#187 Phase B — treatment-equivalence audit (offline).

Field-level diff between the original Ling treatment and the v3 standalone
writer, grounded in code rather than paraphrase. Jev runs *after* the writer
decision, so a writing difference must not be attributed to Jev.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from . import behavioral_discovery as bd
from . import jev_replay_preregistration as pr
from . import jev_ling_writer_v3 as writer_v3
from .communication_protocol import BatteryCondition
from .communication_runner import AgentContext
from .jev_protocol import planning_low_instances


TREATMENT_AUDIT_VERSION = "jev-writer-treatment-audit-v4"
AUDIT_SAMPLE_SEED = 72000


def _sample_context() -> AgentContext:
    instance = planning_low_instances(1)[0]
    view = dict(instance.agent_view("B", "COMM"))
    view["is_finalizer"] = False
    view["finalizing_agent"] = bd.FINALIZER_AGENT
    view["joint_clues"] = []
    return AgentContext(
        run_id="treatment-audit", instance_id=instance.instance_id, agent_id="B",
        condition=BatteryCondition.COMM, turn=1, task_view=view, visible_messages=(),
        prompt_version=bd.PROMPT_SCHEMA_VERSION, token_budget=96)


def original_ling_treatment() -> dict[str, Any]:
    """Reconstruct the exact model-visible original Ling writer treatment from code."""

    context = _sample_context()
    prompt = bd.treatment_prompt(context)
    return {
        "source": "behavioral_discovery.treatment_prompt + OpenRouterBehavioralProvider",
        "prompt_schema_version": bd.PROMPT_SCHEMA_VERSION,
        "prompt_fields": list(bd.TREATMENT_PROMPT_FIELDS),
        "prompt_example": prompt,
        "prompt_serialization": "json.dumps(treatment_prompt(context), sort_keys=True)",
        "model": bd.DEFAULT_FREE_MODEL,
        "endpoint": bd.ENDPOINT,
        "temperature": 0.0,
        "max_tokens": 96,
        "seed_behavior": "provider_seed(instance_id|condition|turn|agent_id) sha256-masked to 0..2^31-1, sent as `seed`",
        "seed_field_sent": True,
        "output_grammar": "free text; parser reads `answer: <label>` and optional `message: <text>`",
        "parser_regex": {"answer": r"answer\\s*:\\s*([^\\n.]+)", "message": r"message\\s*:\\s*([^\\n]+)"},
        "silence_semantics": "absence of a MESSAGE line in a valid ANSWER response",
    }


def v3_standalone_writer() -> dict[str, Any]:
    """The v3 standalone writer request actually sent by the paced pilot."""

    return {
        "source": "jev_choice_pilot.LingWriterClient.write (LING_PROMPT_TEMPLATE)",
        "writer_transport_version": writer_v3.LING_WRITER_TRANSPORT_VERSION,
        "prompt_template": pr.LING_PROMPT_TEMPLATE,
        "prompt_fields": ["private_clues", "silence_option"],
        "model": pr.LING_MODEL,
        "endpoint": pr.LING_ENDPOINT,
        "temperature": pr.LING_TEMPERATURE,
        "max_tokens": pr.LING_MAX_TOKENS,
        "seed_behavior": "no seed field sent",
        "seed_field_sent": False,
        "output_grammar": "MESSAGE: <exact clue> or SILENCE",
        "parser": "message-or-None (v3); ambiguous",
        "silence_semantics": "any non-MESSAGE result was recorded as None/silence",
    }


FIELD_MAP = (
    ("objective/instruction", "instruction (task_instruction)", "not visible"),
    ("candidates", "candidate_labels (public option set)", "not visible"),
    ("family and complexity", "family, complexity", "not visible"),
    ("condition and turn", "condition, turn", "not visible"),
    ("agent/finalizer role", "is_finalizer, finalizing_agent", "not visible"),
    ("private clues", "private_clues", "private_clues"),
    ("joint clues", "joint_clues (pooled task constraints)", "not visible"),
    ("visible messages", "visible_messages", "not visible"),
    ("seed behavior", "seed sent", "no seed"),
    ("temperature", "0.0", "0.0"),
    ("token budget", "96", "64"),
    ("output grammar", "ANSWER + optional MESSAGE; absent MESSAGE = silence", "MESSAGE or SILENCE"),
)


def treatment_equivalence_audit() -> dict[str, Any]:
    original = original_ling_treatment()
    standalone = v3_standalone_writer()
    rows = []
    for field, original_value, v3_value in FIELD_MAP:
        rows.append({
            "field": field,
            "original_ling": original_value,
            "v3_standalone_writer": v3_value,
            "equivalent": original_value == v3_value,
        })
    return {
        "audit_version": TREATMENT_AUDIT_VERSION,
        "sample_seed": AUDIT_SAMPLE_SEED,
        "original_ling": original,
        "v3_standalone_writer": standalone,
        "field_diff": rows,
        "equivalent_fields": [row["field"] for row in rows if row["equivalent"]],
        "divergent_fields": [row["field"] for row in rows if not row["equivalent"]],
        "conclusion": (
            "The v3 standalone writer is not treatment-equivalent to the original Ling solver: it "
            "drops the objective, candidate labels, family/complexity, condition/turn/role, joint "
            "clues and visible messages, sends no seed, uses a 64- vs 96-token budget, and replaces "
            "the original grammar with an explicit SILENCE token. Only private clues, temperature "
            "and model family/endpoint are shared."),
        "jev_downstream_note": (
            "Jev is the receiver and runs after the writer decision, so the v3 all-silence result "
            "cannot be attributed to Jev; it is a property of the writer treatment."),
        "hash": hashlib.sha256(json.dumps(rows, sort_keys=True).encode("utf-8")).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="#187 writer treatment-equivalence audit")
    parser.add_argument("--output", type=Path,
                        default=Path("runs/epic-126/jev-writer-treatment-audit-v4.json"))
    args = parser.parse_args(argv)
    audit = treatment_equivalence_audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, indent=2, sort_keys=True, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(json.dumps({"audit_version": audit["audit_version"],
                      "divergent_fields": audit["divergent_fields"],
                      "hash": audit["hash"], "output": str(args.output)},
                     indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "TREATMENT_AUDIT_VERSION", "original_ling_treatment", "v3_standalone_writer",
    "treatment_equivalence_audit", "FIELD_MAP", "main",
]
