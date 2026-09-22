"""#187 Phase B — frozen planning-low writer prompt ladder (offline).

L0–L5 change only the writer-visible context, holding the downstream Jev
receiver, option set, instances, ownership rule, pacing and exposure
instrumentation fixed. L4 reproduces the original Ling treatment schema/grammar;
L5 is a required exact-owned-claim positive control labelled INDUCED and
excluded from voluntary-COMM inference.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import behavioral_discovery as bd
from . import jev_replay_preregistration as pr
from . import jev_ling_writer_v4 as writer_v4


LADDER_VERSION = "planning-low-writer-ladder-v4"
SILENCE_TOKEN = writer_v4.SILENCE_TOKEN

#: Exact prompt templates, frozen and hashed.
L0_TEMPLATE = pr.LING_PROMPT_TEMPLATE
L1_TEMPLATE = "Task: {instruction}\n" + L0_TEMPLATE
L2_TEMPLATE = L1_TEMPLATE + "\nCandidates: {candidate_labels}"
L3_TEMPLATE = L2_TEMPLATE + "\nCondition: {condition}; turn: {turn}; role: {role}"
L4_FIELDS = ("instruction", "family", "complexity", "condition", "turn", "is_finalizer",
             "finalizing_agent", "candidate_labels", "joint_clues", "private_clues", "visible_messages")
L5_TEMPLATE = ("INDUCED positive control. You must send exactly one message using "
               "MESSAGE: <exact clue>. Choose one of your private clues verbatim. "
               "Private clues: {clues}. Reply with MESSAGE: <exact clue>.")


@dataclass(frozen=True)
class LadderRung:
    rung_id: str
    name: str
    visible_fields: tuple[str, ...]
    grammar: str
    induced: bool
    voluntary: bool

    def to_dict(self) -> dict[str, Any]:
        return {"rung_id": self.rung_id, "name": self.name, "visible_fields": list(self.visible_fields),
                "grammar": self.grammar, "induced": self.induced, "voluntary": self.voluntary}


LADDER_RUNGS: tuple[LadderRung, ...] = (
    LadderRung("L0", "current private-clues-only writer", ("private_clues",),
               writer_v4.GRAMMAR_EXPLICIT_SILENCE, False, True),
    LadderRung("L1", "L0 plus task instruction", ("private_clues", "instruction"),
               writer_v4.GRAMMAR_EXPLICIT_SILENCE, False, True),
    LadderRung("L2", "L1 plus candidate labels",
               ("private_clues", "instruction", "candidate_labels"),
               writer_v4.GRAMMAR_EXPLICIT_SILENCE, False, True),
    LadderRung("L3", "L2 plus condition, turn and role",
               ("private_clues", "instruction", "candidate_labels", "condition", "turn", "role"),
               writer_v4.GRAMMAR_EXPLICIT_SILENCE, False, True),
    LadderRung("L4", "exact original Ling treatment schema and turn semantics", L4_FIELDS,
               writer_v4.GRAMMAR_ORIGINAL_LING, False, True),
    LadderRung("L5", "required exact-owned-claim positive control (INDUCED)",
               ("private_clues",), writer_v4.GRAMMAR_EXPLICIT_SILENCE, True, False),
)

RUNG_INDEX = {rung.rung_id: rung for rung in LADDER_RUNGS}

INTERPRETATION_RULES = {
    "emission_prompt_dependent": (
        "If L4 or L5 writes while L0 remains silent, emission is prompt/role dependent; the "
        "reproducing rung must be registered as part of the communication treatment before replay."),
    "demote_planning_low": (
        "If all voluntary rungs return deliberate_silence, demote planning-low and propose a "
        "separately preregistered six-family Jev-in-loop discovery screen."),
    "repair_instrumentation": (
        "Any empty_output, truncated_output or unparsed_output outcomes mean instrumentation or "
        "token budget must be repaired before scientific interpretation."),
    "l5_transport_validation": (
        "If L5 fails to produce an exact-owned accepted write, the transport/parser is not validated "
        "and the ladder is not interpretable."),
    "no_post_hoc": "Do not select a successful rung post hoc and call it confirmatory.",
    "separate_concepts": (
        "Emission, exposure, post-read correlation and causal uptake remain separate; emission is "
        "not causal uptake and requires matched real/placebo/null replay."),
    "three_gates": (
        "Three distinct gates remain required: structural necessity, inducement through an owned "
        "informative message, and causal uptake through matched real/placebo/null replay."),
}


def ladder_context(instance: Any, *, condition: str, turn: int, agent: str, role: str,
                   visible_messages: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    view = dict(instance.agent_view(agent, "FULL" if condition == "FULL" else condition))
    if condition == "FULL":
        clues = list(instance.agent_view(agent, "FULL").get("joint_clues", []))
    else:
        clues = list(instance.private_clues.get(agent, ()))
    return {
        "instance_id": instance.instance_id,
        "instruction": view.get("task_instruction"),
        "family": instance.family,
        "complexity": instance.complexity.value,
        "condition": condition,
        "turn": turn,
        "agent_id": agent,
        "role": role,
        "is_finalizer": False,
        "finalizing_agent": bd.FINALIZER_AGENT,
        "candidate_labels": sorted(instance.solutions),
        "joint_clues": list(view.get("joint_clues", [])),
        "private_clues": clues,
        "visible_messages": [dict(message) for message in visible_messages],
    }


def ladder_prompt(rung_id: str, context: Mapping[str, Any]) -> dict[str, Any]:
    rung = RUNG_INDEX[rung_id]
    clues = list(context.get("private_clues", ()))
    candidates = ", ".join(str(label) for label in context.get("candidate_labels", ()))
    if rung_id == "L0":
        prompt = L0_TEMPLATE.format(clues=clues)
    elif rung_id == "L1":
        prompt = L1_TEMPLATE.format(instruction=context.get("instruction"), clues=clues)
    elif rung_id == "L2":
        prompt = L2_TEMPLATE.format(instruction=context.get("instruction"), clues=clues,
                                    candidate_labels=candidates)
    elif rung_id == "L3":
        prompt = L3_TEMPLATE.format(instruction=context.get("instruction"), clues=clues,
                                    candidate_labels=candidates, condition=context.get("condition"),
                                    turn=context.get("turn"), role=context.get("role"))
    elif rung_id == "L4":
        fields = {
            "instruction": context.get("instruction"),
            "family": context.get("family"),
            "complexity": context.get("complexity"),
            "condition": context.get("condition"),
            "turn": context.get("turn"),
            "is_finalizer": context.get("is_finalizer", False),
            "finalizing_agent": context.get("finalizing_agent"),
            "candidate_labels": list(context.get("candidate_labels", ())),
            "joint_clues": list(context.get("joint_clues", ())),
            "private_clues": clues,
            "visible_messages": list(context.get("visible_messages", ())),
        }
        prompt = json.dumps(fields, sort_keys=True)
    elif rung_id == "L5":
        prompt = L5_TEMPLATE.format(clues=clues)
    else:
        raise ValueError(f"unknown ladder rung: {rung_id}")
    return {"rung_id": rung_id, "prompt": prompt, "grammar": rung.grammar, "induced": rung.induced,
            "visible_fields": list(rung.visible_fields)}


def ladder_schema() -> dict[str, Any]:
    return {
        "ladder_version": LADDER_VERSION,
        "rungs": [rung.to_dict() for rung in LADDER_RUNGS],
        "templates": {
            "L0": L0_TEMPLATE, "L1": L1_TEMPLATE, "L2": L2_TEMPLATE, "L3": L3_TEMPLATE,
            "L4": "json.dumps({instruction,family,complexity,condition,turn,is_finalizer,"
                  "finalizing_agent,candidate_labels,joint_clues,private_clues,visible_messages})",
            "L5": L5_TEMPLATE,
        },
        "interpretation_rules": dict(INTERPRETATION_RULES),
        "induced_rungs": ["L5"],
        "voluntary_rungs": [rung.rung_id for rung in LADDER_RUNGS if rung.voluntary],
        "writer_schema_hash": writer_v4.writer_schema_hash(),
    }


def ladder_hash() -> str:
    return hashlib.sha256(json.dumps(ladder_schema(), sort_keys=True).encode("utf-8")).hexdigest()


def declared_writer_outcomes() -> list[str]:
    return list(writer_v4.WRITER_OUTCOMES)


__all__ = [
    "LADDER_VERSION", "LadderRung", "LADDER_RUNGS", "RUNG_INDEX", "INTERPRETATION_RULES",
    "ladder_context", "ladder_prompt", "ladder_schema", "ladder_hash", "declared_writer_outcomes",
    "L0_TEMPLATE", "L1_TEMPLATE", "L2_TEMPLATE", "L3_TEMPLATE", "L4_FIELDS", "L5_TEMPLATE",
]
