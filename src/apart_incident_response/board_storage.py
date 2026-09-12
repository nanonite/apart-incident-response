"""Controller-owned SQLite storage for the append-only message board.

This module deliberately contains storage primitives only.  It does not expose
an agent tool, condition policy, credential-derived identity, or a database
connection to Pi.  The controller/board service owns the :class:`BoardStore`
instance and passes message records to later board APIs.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Iterator


class BoardStorageError(ValueError):
    """Raised when a board database cannot satisfy the service boundary."""


@dataclass(frozen=True)
class BoardMessage:
    """One immutable row returned by the controller-owned board store."""

    sequence_id: int
    run_id: str
    agent_id: str
    server_timestamp: str
    message_body: str
    message_size: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _path_is_within(path: Path, root: Path) -> bool:
    """Return whether *path* is equal to or below *root*."""

    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _lexical_path(path: Path) -> Path:
    """Return an absolute path without following symlinks."""

    return Path(os.path.abspath(os.fspath(path)))


def _resolve_database_path(
    database_path: str | os.PathLike[str],
    agent_workspace_roots: Iterable[str | os.PathLike[str]],
) -> Path:
    """Resolve and boundary-check a service database path.

    Both lexical and resolved paths are checked.  Checking both matters: a
    symlink located in an agent workspace must not provide an alternate path
    into or out of that workspace for the service database.
    """

    candidate = Path(database_path).expanduser()
    if not candidate.name or candidate.name in {".", ".."}:
        raise BoardStorageError("board database path must name a database file")

    lexical = _lexical_path(candidate)
    resolved = candidate.resolve(strict=False)
    roots = []
    for raw_root in agent_workspace_roots:
        root = Path(raw_root).expanduser()
        roots.append((_lexical_path(root), root.resolve(strict=False)))

    for lexical_root, resolved_root in roots:
        if _path_is_within(lexical, lexical_root) or _path_is_within(resolved, resolved_root):
            raise BoardStorageError(
                "board database must be outside every agent workspace; "
                f"refusing {candidate}"
            )

    return resolved


def _validate_message_field(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BoardStorageError(f"{field_name} must be a non-empty string")
    return value


def _initialize_schema(connection: sqlite3.Connection) -> None:
    """Create the board schema and immutable-row triggers idempotently."""

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS messages (
            sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL
                CHECK (typeof(run_id) = 'text' AND length(trim(run_id)) > 0),
            agent_id TEXT NOT NULL
                CHECK (typeof(agent_id) = 'text' AND length(trim(agent_id)) > 0),
            server_timestamp TEXT NOT NULL
                CHECK (
                    typeof(server_timestamp) = 'text'
                    AND length(trim(server_timestamp)) > 0
                ),
            message_body TEXT NOT NULL
                CHECK (
                    typeof(message_body) = 'text'
                    AND length(trim(message_body)) > 0
                ),
            message_size INTEGER NOT NULL
                CHECK (
                    typeof(message_size) = 'integer'
                    AND message_size = length(CAST(message_body AS BLOB))
                    AND message_size > 0
                )
        );

        CREATE TRIGGER IF NOT EXISTS messages_reject_update
        BEFORE UPDATE ON messages
        BEGIN
            SELECT RAISE(ABORT, 'messages are append-only: UPDATE is forbidden');
        END;

        CREATE TRIGGER IF NOT EXISTS messages_reject_delete
        BEFORE DELETE ON messages
        BEGIN
            SELECT RAISE(ABORT, 'messages are append-only: DELETE is forbidden');
        END;
        """
    )
    connection.commit()


class BoardStore:
    """Private SQLite message storage owned by the board service.

    ``initialize`` is the intended entry point for the controller.  The
    caller must provide the current agent workspace roots so this class can
    reject database paths inside them, including symlinked paths.  The store
    creates the database parent only when absent, keeps it private, and never
    gives its path or connection to an agent process.

    ``append_message`` is the only write operation.  ``iter_messages`` is a
    deterministic low-level read primitive for the future ``board_read`` API;
    cursor semantics, condition visibility, and tool argument validation are
    intentionally left to #17--#19.
    """

    def __init__(
        self,
        database_path: str | os.PathLike[str],
        *,
        agent_workspace_roots: Iterable[str | os.PathLike[str]] = (),
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self._database_path = _resolve_database_path(database_path, agent_workspace_roots)
        self._clock = clock
        parent = self._database_path.parent
        if parent.exists():
            if not parent.is_dir():
                raise BoardStorageError(f"board database parent is not a directory: {parent}")
            if parent.stat().st_uid != os.getuid() or parent.stat().st_mode & 0o077:
                raise BoardStorageError(
                    "board database parent must be controller-owned and mode 0700 or stricter"
                )
        else:
            parent.mkdir(parents=True, mode=0o700)
            parent.chmod(0o700)

        existing = self._database_path.exists()
        if existing and not self._database_path.is_file():
            raise BoardStorageError(f"board database path is not a regular file: {self._database_path}")
        if existing:
            database_stat = self._database_path.stat()
            if database_stat.st_uid != os.getuid() or database_stat.st_mode & 0o077:
                raise BoardStorageError(
                    "board database must be controller-owned and mode 0600 or stricter"
                )

        self._connection = sqlite3.connect(self._database_path, timeout=5.0)
        try:
            self._connection.execute("PRAGMA foreign_keys = ON")
            _initialize_schema(self._connection)
            if not existing:
                self._database_path.chmod(0o600)
        except Exception:
            self._connection.close()
            raise

    @classmethod
    def initialize(
        cls,
        database_path: str | os.PathLike[str],
        *,
        agent_workspace_roots: Iterable[str | os.PathLike[str]] = (),
        clock: Callable[[], str] = _utc_now,
    ) -> "BoardStore":
        """Initialize/open a private service database for later board APIs."""

        return cls(
            database_path,
            agent_workspace_roots=agent_workspace_roots,
            clock=clock,
        )

    @property
    def database_path(self) -> Path:
        """Return the controller-side path; never pass it to an agent."""

        return self._database_path

    def append_message(self, run_id: str, agent_id: str, message_body: str) -> BoardMessage:
        """Append one server-timestamped message and return its assigned row."""

        run_id = _validate_message_field(run_id, "run_id")
        agent_id = _validate_message_field(agent_id, "agent_id")
        message_body = _validate_message_field(message_body, "message_body")
        server_timestamp = _validate_message_field(self._clock(), "server timestamp")
        message_size = len(message_body.encode("utf-8"))

        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO messages
                    (run_id, agent_id, server_timestamp, message_body, message_size)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, agent_id, server_timestamp, message_body, message_size),
            )
            sequence_id = int(cursor.lastrowid)

        return BoardMessage(
            sequence_id=sequence_id,
            run_id=run_id,
            agent_id=agent_id,
            server_timestamp=server_timestamp,
            message_body=message_body,
            message_size=message_size,
        )

    def iter_messages(self) -> Iterator[BoardMessage]:
        """Yield rows in ascending sequence order for a future board reader."""

        rows = self._connection.execute(
            """
            SELECT sequence_id, run_id, agent_id, server_timestamp, message_body, message_size
            FROM messages
            ORDER BY sequence_id ASC
            """
        )
        for row in rows:
            yield BoardMessage(
                sequence_id=int(row[0]),
                run_id=str(row[1]),
                agent_id=str(row[2]),
                server_timestamp=str(row[3]),
                message_body=str(row[4]),
                message_size=int(row[5]),
            )

    def close(self) -> None:
        """Close the controller's database connection."""

        self._connection.close()

    def __enter__(self) -> "BoardStore":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()
