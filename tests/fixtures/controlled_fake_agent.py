"""Deterministic harness-check agent; never label its output as experiment data."""

from __future__ import annotations

import json
import os
from pathlib import Path


def call(operation: str, arguments: dict[str, object]) -> dict[str, object]:
    print(json.dumps({"type": "tool_execution_start", "toolName": operation, "id": operation}), flush=True)
    request = {
        "credential": Path(os.environ["APART_CONTROLLER_CREDENTIAL_FILE"]).read_text(encoding="utf-8").strip(),
        "operation": operation,
        "arguments": arguments,
    }
    with open(os.environ["APART_TOOL_REQUEST_FIFO"], "wb") as stream:
        stream.write((json.dumps(request) + "\n").encode("utf-8"))
    with open(os.environ["APART_TOOL_RESPONSE_FIFO"], "rb") as stream:
        response = json.loads(stream.readline())
    print(json.dumps({"type": "tool_execution_end", "toolName": operation, "id": operation}), flush=True)
    if not response.get("ok"):
        return {"error": response.get("error", {})}
    return response.get("result", {})


def main() -> int:
    seed = int(os.environ["APART_SEED"])
    condition = os.environ["APART_CONDITION"]
    agent_id = os.environ["APART_AGENT_ID"]
    role = int(agent_id.rsplit("-", 1)[-1])
    content = call("task_read", {"path": ["application.log", "deployment.txt", "metrics.txt"][(role + seed - 2) % 3]})
    token = "ORCHID-731"
    call("task_query", {"query": token})
    if condition != "C0":
        call("board_append", {"message": f"{agent_id} observed seeded evidence {token}"})
        call("board_read", {"limit": 50})
    diagnosis = "The ORCHID-731 configuration revision changed CACHE_MODE from local to shared, causing the cache-related outage."
    call("task_submit", {
        "diagnosis": diagnosis,
        "evidence": [{"path": Path(content.get("path", "application.log")).name, "excerpt": content.get("content", "").splitlines()[0]}],
    })
    print(json.dumps({
        "type": "message_end",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": diagnosis}],
            "usage": {"totalTokens": 10},
            "stopReason": "stop",
        },
    }), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
