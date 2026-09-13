#!/usr/bin/env python3
"""Capture a credential-free two-agent board visibility trace."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
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


FIXED_TIMESTAMP = "2026-09-12T00:00:00Z"


def _invoke(
    server: ToolServiceSocketServer,
    service: ConstrainedToolService,
    identity: AgentIdentity,
    operation: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    credential = service.issue_credential(identity)
    response = server.request_from_controller(
        {
            "credential": credential,
            "operation": operation,
            "arguments": arguments,
        }
    )
    if not response.get("ok"):
        raise RuntimeError(f"smoke operation failed: {operation}")
    return {
        "operation": operation,
        "arguments": arguments,
        "response": response,
    }


def capture_trace() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="apart-board-smoke-") as temporary:
        root = Path(temporary)
        task_root = root / "task"
        task_root.mkdir()
        task_root.joinpath("evidence.txt").write_text("fixture\n", encoding="utf-8")
        store = BoardStore.initialize(
            root / "board.sqlite",
            clock=lambda: FIXED_TIMESTAMP,
        )
        try:
            catalog = TaskCatalog({"task-1": TaskDefinition("task-1", task_root)})
            service = ConstrainedToolService(
                TaskToolService(catalog),
                BoardToolService(store),
            )
            with ToolServiceSocketServer(service, root / ".board-service.sock", use_fifo=True) as server:
                c1_agent_1 = AgentIdentity("run-c1", "agent-1", Condition.C1, "task-1", 1)
                c1_agent_2 = AgentIdentity("run-c1", "agent-2", Condition.C1, "task-1", 2)
                c2_agent_1 = AgentIdentity("run-c2", "agent-1", Condition.C2, "task-1", 1)
                c2_agent_2 = AgentIdentity("run-c2", "agent-2", Condition.C2, "task-1", 2)
                c1_append = _invoke(
                    server,
                    service,
                    c1_agent_1,
                    "board_append",
                    {"message": "Agent 1: ORCHID-731"},
                )
                c1_read = _invoke(server, service, c1_agent_2, "board_read", {"limit": 10})
                c2_append = _invoke(
                    server,
                    service,
                    c2_agent_1,
                    "board_append",
                    {"message": "Agent 1: C2-private"},
                )
                c2_read = _invoke(server, service, c2_agent_2, "board_read", {"limit": 10})
            c1_messages = c1_read["response"]["result"]["messages"]  # type: ignore[index]
            c2_messages = c2_read["response"]["result"]["messages"]  # type: ignore[index]
            return {
                "trace_version": 1,
                "credential_free": True,
                "transport": "fixture-fifo",
                "c1": {
                    "agent_1_append": c1_append,
                    "agent_2_read": c1_read,
                    "agent_2_saw_agent_1": bool(c1_messages),
                },
                "c2": {
                    "agent_1_append": c2_append,
                    "agent_2_read": c2_read,
                    "agent_2_saw_agent_1": bool(c2_messages),
                },
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
