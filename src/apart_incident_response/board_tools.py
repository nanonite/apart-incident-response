"""Credential-scoped board operations built on the private SQLite store."""

from __future__ import annotations

from dataclasses import asdict
import threading
from typing import Any, Mapping

from .board_storage import BoardMessage, BoardStorageError, BoardStore
from .runtime import AgentIdentity, Condition
from .tool_contract import (
    MAX_MESSAGE_BYTES,
    MAX_READ_BYTES,
    MAX_READ_MESSAGES,
    ToolServiceError,
    ToolUnavailableError,
    ToolValidationError,
    exact_keys,
    optional_positive_int,
    required_text,
)


class BoardToolService:
    """Apply trusted run identity, cursor bounds, and C0/C1/C2 visibility."""

    def __init__(self, store: BoardStore) -> None:
        self._store = store
        self._lock = threading.Lock()

    def append(self, identity: AgentIdentity, arguments: Mapping[str, Any]) -> dict[str, Any]:
        exact_keys(arguments, {"message"})
        self._require_board(identity)
        message = required_text(arguments, "message", MAX_MESSAGE_BYTES)
        try:
            with self._lock:
                record = self._store.append_message(identity.run_id, identity.agent_id, message)
        except BoardStorageError as exc:
            raise ToolServiceError("board append failed") from exc
        return asdict(record)

    def read(self, identity: AgentIdentity, arguments: Mapping[str, Any]) -> dict[str, Any]:
        exact_keys(arguments, {"after_sequence_id", "limit"})
        self._require_board(identity)
        cursor = arguments.get("after_sequence_id", 0)
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise ToolValidationError("after_sequence_id must be a non-negative integer")
        limit = optional_positive_int(arguments, "limit", 20, MAX_READ_MESSAGES)
        own_agent = identity.agent_id if identity.condition is Condition.C2 else None
        try:
            with self._lock:
                messages, has_more = self._store.read_messages(
                    identity.run_id,
                    cursor,
                    agent_id=own_agent,
                    limit=limit,
                    max_bytes=MAX_READ_BYTES,
                )
        except BoardStorageError as exc:
            raise ToolServiceError("board read failed") from exc
        next_cursor = messages[-1].sequence_id if messages else cursor
        return {
            "messages": [asdict(message) for message in messages],
            "next_cursor": next_cursor,
            "has_more": has_more,
        }

    @staticmethod
    def _require_board(identity: AgentIdentity) -> None:
        if identity.condition is Condition.C0:
            raise ToolUnavailableError("board tools are unavailable in C0")
