import sqlite3
import tempfile
import unittest
from pathlib import Path

from apart_incident_response.board_storage import BoardStorageError, BoardStore


class BoardStorageTests(unittest.TestCase):
    def test_schema_creation_has_required_columns_and_append_only_triggers(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "service" / "board.sqlite3"
            with BoardStore.initialize(database) as store:
                columns = {
                    row[1]: row[2]
                    for row in store._connection.execute("PRAGMA table_info(messages)")
                }
                self.assertEqual(
                    columns,
                    {
                        "sequence_id": "INTEGER",
                        "run_id": "TEXT",
                        "agent_id": "TEXT",
                        "server_timestamp": "TEXT",
                        "message_body": "TEXT",
                        "message_size": "INTEGER",
                    },
                )
                triggers = {
                    row[0]
                    for row in store._connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                    )
                }
                self.assertEqual(
                    triggers,
                    {"messages_reject_update", "messages_reject_delete"},
                )
            self.assertEqual(database.stat().st_mode & 0o777, 0o600)
            self.assertEqual(database.parent.stat().st_mode & 0o777, 0o700)

    def test_required_fields_and_message_size_are_validated(self):
        with tempfile.TemporaryDirectory() as temp:
            with BoardStore.initialize(Path(temp) / "board.sqlite3") as store:
                for args in (
                    ("", "agent-1", "message"),
                    ("run-1", "", "message"),
                    ("run-1", "agent-1", ""),
                ):
                    with self.subTest(args=args), self.assertRaises(BoardStorageError):
                        store.append_message(*args)

                message = store.append_message("run-1", "agent-1", "café 🚀")
                self.assertEqual(message.message_size, len("café 🚀".encode("utf-8")))
                row = store._connection.execute(
                    "SELECT message_size, length(CAST(message_body AS BLOB)) FROM messages"
                ).fetchone()
                self.assertEqual(row[0], row[1])

    def test_sequence_ids_are_monotonic_and_iteration_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temp:
            with BoardStore.initialize(Path(temp) / "board.sqlite3", clock=lambda: "2026-01-01T00:00:00Z") as store:
                first = store.append_message("run-1", "agent-1", "first")
                second = store.append_message("run-1", "agent-2", "second")
                third = store.append_message("run-2", "agent-1", "third")
                self.assertEqual(
                    [message.sequence_id for message in store.iter_messages()],
                    [first.sequence_id, second.sequence_id, third.sequence_id],
                )
                self.assertEqual([first.sequence_id, second.sequence_id, third.sequence_id], [1, 2, 3])
                self.assertEqual(first.server_timestamp, "2026-01-01T00:00:00Z")

    def test_direct_sql_update_and_delete_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "board.sqlite3"
            with BoardStore.initialize(database) as store:
                message = store.append_message("run-1", "agent-1", "immutable")
                direct = sqlite3.connect(database)
                try:
                    with self.assertRaises(sqlite3.IntegrityError):
                        direct.execute(
                            "UPDATE messages SET message_body = 'changed' WHERE sequence_id = ?",
                            (message.sequence_id,),
                        )
                    with self.assertRaises(sqlite3.IntegrityError):
                        direct.execute(
                            "DELETE FROM messages WHERE sequence_id = ?",
                            (message.sequence_id,),
                        )
                    direct.rollback()
                finally:
                    direct.close()
                self.assertEqual(list(store.iter_messages())[0].message_body, "immutable")

    def test_schema_rejects_missing_or_inconsistent_required_values(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "board.sqlite3"
            with BoardStore.initialize(database):
                direct = sqlite3.connect(database)
                try:
                    invalid_rows = (
                        ("", "agent-1", "timestamp", "body", 4),
                        ("run-1", "   ", "timestamp", "body", 4),
                        ("run-1", "agent-1", " ", "body", 4),
                        ("run-1", "agent-1", "timestamp", "", 0),
                        ("run-1", "agent-1", "timestamp", "é", 1),
                    )
                    for row in invalid_rows:
                        with self.subTest(row=row), self.assertRaises(sqlite3.IntegrityError):
                            direct.execute(
                                """
                                INSERT INTO messages
                                    (run_id, agent_id, server_timestamp, message_body, message_size)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                row,
                            )
                    direct.rollback()
                finally:
                    direct.close()

    def test_database_path_inside_agent_workspace_is_rejected_even_through_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "agent"
            workspace.mkdir()
            outside = root / "service"
            outside.mkdir()
            link = workspace / "service-link"
            link.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(BoardStorageError):
                BoardStore.initialize(
                    link / "board.sqlite3",
                    agent_workspace_roots=(workspace,),
                )
