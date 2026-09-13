#!/usr/bin/env python3
"""Run the credential-free single-agent Task 1 calibration."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any


SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT / "src"))

from apart_incident_response import (  # noqa: E402
    ConstrainedToolService,
    TaskCatalog,
    TaskDefinition,
    TaskToolService,
)
from apart_incident_response.runtime import (  # noqa: E402
    AgentIdentity,
    AgentRun,
    Condition,
    IsolationPolicy,
    RuntimeConfig,
    SystemBudget,
    create_isolated_workspace,
)
from apart_incident_response.task_one import (  # noqa: E402
    TASK_ONE_EVIDENCE_BUNDLES,
    TASK_ONE_ID,
    TASK_ONE_DIFFICULTIES,
    validate_task_one_answer,
    materialize_task_one_bundle,
    task_one_instance,
)
from apart_incident_response.task_prompts import TASK_ONE_PROMPT  # noqa: E402


FAKE_AGENT = """
import json
import os
from pathlib import Path

paths = {
    "agent-1": "application.log",
    "agent-2": "deployment.txt",
    "agent-3": "metrics.txt",
}

def call(operation, arguments):
    request = {
        "credential": Path(os.environ["APART_CONTROLLER_CREDENTIAL_FILE"]).read_text(),
        "operation": operation,
        "arguments": arguments,
    }
    with open(os.environ["APART_TOOL_REQUEST_FIFO"], "wb") as stream:
        stream.write((json.dumps(request) + "\\n").encode())
    with open(os.environ["APART_TOOL_RESPONSE_FIFO"], "rb") as stream:
        response = json.loads(stream.readline())
    if not response["ok"]:
        raise SystemExit(response["error"]["message"])
    return response["result"]

_ = __import__("sys").stdin.read()
evidence = call("task_read", {"path": paths[os.environ["APART_AGENT_ID"]]})
print(json.dumps({"type": "tool_call", "id": "calibration-read", "name": "task_read"}), flush=True)
print(json.dumps({
    "type": "message_end",
    "message": {
        "role": "assistant",
        "content": [{"type": "text", "text": evidence["content"]}],
        "usage": {"totalTokens": 1},
        "stopReason": "stop",
    },
}), flush=True)
"""


def _config(fake_agent: Path) -> RuntimeConfig:
    return RuntimeConfig(
        pi_version="calibration",
        model="credential-free-fixture",
        launch_command=(sys.executable, str(fake_agent)),
        agent_count=1,
        per_agent_token_budget=10,
        per_agent_tool_call_budget=4,
        aggregate_token_budget=10,
        aggregate_tool_call_budget=4,
        timeout_seconds=2,
        isolation=IsolationPolicy(sandbox="none", allow_unsafe_for_tests=True),
    )


def capture_calibration() -> dict[str, Any]:
    """Run one deterministic C0 agent per assigned evidence bundle."""

    with tempfile.TemporaryDirectory(prefix="a1c-") as temporary:
        root = Path(temporary)
        fake_agent = root / "fake_agent.py"
        fake_agent.write_text(FAKE_AGENT, encoding="utf-8")
        config = _config(fake_agent)
        records: list[dict[str, Any]] = []
        for bundle in TASK_ONE_EVIDENCE_BUNDLES:
            identity = AgentIdentity(
                f"cal-1-{bundle.agent_id}",
                bundle.agent_id,
                Condition.C0,
                TASK_ONE_ID,
                1,
            )
            workspace = create_isolated_workspace(root / "runs", identity)
            evidence_path = workspace.task_dir / Path(bundle.relative_path).name
            evidence_path.write_text(bundle.content, encoding="utf-8")
            catalog = TaskCatalog({
                TASK_ONE_ID: TaskDefinition(
                    TASK_ONE_ID,
                    workspace.task_dir,
                    allowed_paths=(evidence_path.name,),
                )
            })
            service = ConstrainedToolService(
                TaskToolService(catalog),
                artifact_root=workspace.workspace_root,
            )
            result = AgentRun(
                config,
                identity,
                workspace,
                SystemBudget(10, 4),
                service,
            ).run()
            validation = validate_task_one_answer(result.final_response or "")
            available_tools = service.available_tools(identity)
            records.append({
                "run_id": identity.run_id,
                "agent_id": identity.agent_id,
                "condition": identity.condition.value,
                "task_id": identity.task_id,
                "seed": identity.seed,
                "evidence_bundle": bundle.relative_path,
                "prompt": TASK_ONE_PROMPT,
                "available_tools": list(available_tools),
                "board_tools_available": "board_read" in available_tools or "board_append" in available_tools,
                "status": result.status.value,
                "turns": sum(event.get("type") == "message_end" for event in result.events),
                "tokens_used": result.tokens_used,
                "tool_calls_used": result.tool_calls_used,
                "response": result.final_response,
                "validator": {
                    "accepted": validation.accepted,
                    "missing_terms": list(validation.missing_terms),
                },
            })
        if any(record["board_tools_available"] for record in records):
            raise RuntimeError("Task 1 calibration unexpectedly exposed board tools")
        if any(record["validator"]["accepted"] for record in records):
            raise RuntimeError("an individual Task 1 bundle passed the complete validator")
        return {
            "schema_version": 1,
            "task_id": TASK_ONE_ID,
            "seed": 1,
            "condition": Condition.C0.value,
            "calibration": True,
            "credential_free": True,
            "model_request": False,
            "purpose": "diagnostic calibration before Task 2; not a fourth experiment condition",
            "records": records,
        }


def capture_difficulty_calibration() -> dict[str, Any]:
    """Run independent fake agents against every predeclared difficulty level."""

    with tempfile.TemporaryDirectory(prefix="a1d-") as temporary:
        root = Path(temporary)
        fake_agent = root / "fake_agent.py"
        fake_agent.write_text(FAKE_AGENT, encoding="utf-8")
        config = _config(fake_agent)
        records: list[dict[str, Any]] = []
        for difficulty in TASK_ONE_DIFFICULTIES:
            instance = task_one_instance(1, difficulty)
            for bundle in instance.bundles:
                identity = AgentIdentity(
                    f"cal-1-{difficulty}-{bundle.agent_id}",
                    bundle.agent_id,
                    Condition.C0,
                    TASK_ONE_ID,
                    1,
                )
                workspace = create_isolated_workspace(root / "runs", identity)
                evidence_path = materialize_task_one_bundle(workspace.task_dir, bundle.agent_id, instance)
                catalog = TaskCatalog({
                    TASK_ONE_ID: TaskDefinition(
                        TASK_ONE_ID,
                        workspace.task_dir,
                        allowed_paths=(evidence_path.name,),
                        answer_validator=instance.validate_answer,
                    )
                })
                service = ConstrainedToolService(
                    TaskToolService(catalog),
                    artifact_root=workspace.workspace_root,
                )
                result = AgentRun(
                    config,
                    identity,
                    workspace,
                    SystemBudget(10, 4),
                    service,
                ).run()
                validation = instance.validate_answer(result.final_response or "")
                records.append({
                    "difficulty": difficulty,
                    "seed": 1,
                    "agent_id": bundle.agent_id,
                    "evidence_role": bundle.agent_id,
                    "fixture_sha256": instance.manifest()["fixture_sha256"],
                    "status": result.status.value,
                    "tokens_used": result.tokens_used,
                    "tool_calls_used": result.tool_calls_used,
                    "validator": {"accepted": validation.accepted, "missing_terms": list(validation.missing_terms)},
                })
        if any(record["validator"]["accepted"] for record in records):
            raise RuntimeError("an independent difficulty calibration bundle passed the full validator")
        return {
            "schema_version": 1,
            "task_id": TASK_ONE_ID,
            "seed": 1,
            "calibration": True,
            "credential_free": True,
            "model_request": False,
            "purpose": "difficulty calibration; not experimental data",
            "difficulty_levels": list(TASK_ONE_DIFFICULTIES),
            "records": records,
        }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--difficulty-all", action="store_true")
    args = parser.parse_args()
    calibration = capture_difficulty_calibration() if args.difficulty_all else capture_calibration()
    encoded = json.dumps(calibration, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(encoded)
    else:
        args.output.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        sys.stdout.write(f"wrote {args.output}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
