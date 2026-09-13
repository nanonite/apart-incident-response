#!/usr/bin/env python3
"""Run Pi 0.85.1 directly with the mounted incident-tools extension."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SOURCE_ROOT = Path(__file__).resolve().parents[1]
PI_ROOT = Path(os.environ.get("APART_PI_ROOT", "/home/framework/GitRepos/pi"))
PI_ENTRY = PI_ROOT / "packages" / "coding-agent" / "src" / "cli.ts"
PI_FIXTURE = SOURCE_ROOT / "tests" / "fixtures" / "pi-faux-provider.ts"
EXTENSION = SOURCE_ROOT / "pi-extension" / "incident-tools.ts"
FIXED_TIMESTAMP = "2026-09-12T00:00:00Z"

sys.path.insert(0, str(SOURCE_ROOT / "src"))

from apart_incident_response import (  # noqa: E402
    BoardStore,
    BoardToolService,
    ConstrainedToolService,
    TaskCatalog,
    TaskDefinition,
    TaskToolService,
    ToolServiceSocketServer,
)
from apart_incident_response.runtime import AgentIdentity, Condition  # noqa: E402


def _run_pi(root: Path, server: ToolServiceSocketServer, credential_file: Path) -> tuple[str, list[dict[str, Any]]]:
    environment = os.environ.copy()
    environment.update(
        {
            "APART_CONDITION": "C1",
            "APART_TOOL_REQUEST_FIFO": str(server.request_fifo),
            "APART_TOOL_RESPONSE_FIFO": str(server.response_fifo),
            "APART_CONTROLLER_CREDENTIAL_FILE": str(credential_file),
            "HOME": str(root / "home"),
            "PI_CODING_AGENT_DIR": str(root / "pi-agent"),
            "PI_OFFLINE": "1",
        }
    )
    command = ["bun", "run", os.fspath(PI_ENTRY), "--version"]
    version = subprocess.run(command, check=True, capture_output=True, text=True, env=environment).stdout.strip()
    if version != "0.85.1":
        raise RuntimeError(f"expected Pi 0.85.1, got {version!r}")

    command = [
        "bun",
        "--smol",
        "run",
        os.fspath(PI_ENTRY),
        "--mode",
        "json",
        "--no-session",
        "--offline",
        "--no-builtin-tools",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--no-themes",
        "--no-context-files",
        "--no-approve",
        "--extension",
        os.fspath(EXTENSION),
        "--extension",
        os.fspath(PI_FIXTURE),
        "--model",
        "fixture/smoke",
        "read,query,coordinate,submit",
    ]
    completed: subprocess.CompletedProcess[str] | None = None
    for attempt in range(3):
        completed = subprocess.run(
            command,
            cwd=SOURCE_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if not (
            completed.returncode == -4
            and "Bun has crashed" in completed.stderr
            and attempt < 2
        ):
            break
    assert completed is not None
    if completed.returncode != 0:
        raise RuntimeError(f"Pi failed with {completed.returncode}: {completed.stderr}\n{completed.stdout}")
    events: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return version, events


def capture_trace() -> dict[str, Any]:
    if shutil.which("bun") is None or not PI_ENTRY.is_file():
        raise RuntimeError(f"Pi 0.85.1 CLI not found at {PI_ENTRY}")
    with tempfile.TemporaryDirectory(prefix="apart-pi-smoke-") as temporary:
        root = Path(temporary)
        task_root = root / "task"
        task_root.mkdir()
        task_root.joinpath("evidence.txt").write_text("ORCHID-731 fixture\n", encoding="utf-8")
        credential_file = root / "controller" / "credential"
        credential_file.parent.mkdir(mode=0o700)
        store = BoardStore.initialize(root / "board.sqlite", clock=lambda: FIXED_TIMESTAMP)
        try:
            catalog = TaskCatalog({"task-1": TaskDefinition("task-1", task_root)})
            service = ConstrainedToolService(
                TaskToolService(catalog),
                BoardToolService(store),
                artifact_root=root / "artifacts",
                clock=lambda: FIXED_TIMESTAMP,
            )
            identity = AgentIdentity("pi-smoke-run", "pi-agent", Condition.C1, "task-1", 1)
            # The controller owns this accounting state; Pi cannot supply it
            # as part of the task_submit arguments.
            service.update_runtime_usage(identity, 420, 4)
            credential = service.issue_credential(identity)
            credential_file.write_text(credential, encoding="utf-8")
            credential_file.chmod(0o600)
            with ToolServiceSocketServer(service, root / ".apart-tool-service.sock", use_fifo=True) as server:
                version, events = _run_pi(root, server, credential_file)
            audit_path = root / "artifacts" / "pi-smoke-run" / "agents" / "pi-agent" / "artifacts" / "tool_calls.jsonl"
            audit = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
            tool_events = [
                {
                    "tool": event.get("toolName"),
                    "is_error": event.get("isError", False),
                }
                for event in events
                if event.get("type") == "tool_execution_end"
            ]
            if [event["tool"] for event in tool_events] != [
                "task_read",
                "task_query",
                "board_append",
                "board_read",
                "task_submit",
            ]:
                raise RuntimeError(f"unexpected Pi tool execution sequence: {tool_events}")
            if len(audit) != 5 or any(event["response"].get("ok") is not True for event in audit):
                raise RuntimeError(f"unexpected tool audit: {audit}")
            board_read = audit[3]["response"]["result"]
            if board_read["messages"][0]["message_body"] != "Pi agent: ORCHID-731":
                raise RuntimeError("Pi board_read did not observe the preceding board_append")
            if credential in json.dumps(audit):
                raise RuntimeError("controller credential appeared in the audit")
            submission_path = root / "artifacts" / "pi-smoke-run" / "agents" / "pi-agent" / "artifacts" / "task_submission.json"
            submission = json.loads(submission_path.read_text(encoding="utf-8"))
            if submission["token_usage"] != {
                "source": "controller_runtime_accounting",
                "total_tokens": 420,
                "tool_calls": 4,
            }:
                raise RuntimeError(f"unexpected trusted usage: {submission['token_usage']}")
            if credential in json.dumps(submission):
                raise RuntimeError("controller credential appeared in the submission")
            return {
                "pi_version": version,
                "extension": "pi-extension/incident-tools.ts",
                "fixture_provider": "tests/fixtures/pi-faux-provider.ts",
                "transport": "fixture-fifo",
                "credential_free": True,
                "built_in_tools": False,
                "extension_discovery": False,
                "tool_events": tool_events,
                "audit": audit,
                "submission": submission,
            }
        finally:
            store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write the JSON trace to this path")
    args = parser.parse_args()
    encoded = json.dumps(capture_trace(), indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(encoded)
    else:
        args.output.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        sys.stdout.write(f"wrote {args.output}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
