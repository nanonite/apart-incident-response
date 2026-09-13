#!/usr/bin/env python3
"""Inspect one sanitized per-agent experiment timeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT / "src"))

from apart_incident_response.run_artifacts import build_agent_timeline  # noqa: E402


def _entry_text(entry: dict[str, object]) -> str:
    if isinstance(entry.get("text"), str):
        return entry["text"]
    messages = entry.get("assistant_messages")
    if isinstance(messages, list):
        parts = []
        for message in messages:
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    parts.append(content)
                elif isinstance(content, list):
                    parts.extend(
                        part.get("text", "")
                        for part in content
                        if isinstance(part, dict) and isinstance(part.get("text"), str)
                    )
        return "".join(parts)
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    timeline = build_agent_timeline(args.run_root, args.agent_id, persist=True)
    if args.as_json:
        print(json.dumps(timeline, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    identity = timeline.get("identity", {})
    print(f"run={identity.get('run_id', '?')} agent={identity.get('agent_id', args.agent_id)} status={timeline.get('status', 'missing')}")
    for entry in timeline.get("entries", []):
        if not isinstance(entry, dict):
            continue
        sequence = entry.get("sequence", "?")
        timestamp = entry.get("timestamp") or "-"
        kind = entry.get("kind", "event")
        operation = entry.get("operation")
        label = f"{kind}:{operation}" if operation else str(kind)
        text = " ".join(_entry_text(entry).split())
        if len(text) > 240:
            text = text[:237] + "..."
        print(f"{sequence:>4} {timestamp} {label} {text}".rstrip())
    for reason in timeline.get("failure_reasons", []):
        print(f"failure: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
