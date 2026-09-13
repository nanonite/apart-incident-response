import errno
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace

from apart_incident_response import (
    BOARD_TOOL_NAMES,
    CORE_TOOL_NAMES,
    BoardToolService,
    BoardStore,
    ConstrainedToolService,
    TaskCatalog,
    TaskDefinition,
    TaskToolService,
    ToolServiceSocketServer,
)
from apart_incident_response.runtime import (
    AgentIdentity,
    AgentRun,
    build_pi_command,
    Condition,
    IsolationPolicy,
    RuntimeConfig,
    SystemBudget,
    _build_cli_tool_service,
    create_isolated_workspace,
)
from apart_incident_response.tool_service import MAX_READ_MESSAGES
from apart_incident_response.task_one import TASK_ONE_DIAGNOSIS


class ToolServiceTests(unittest.TestCase):
    def identity(self, agent_id: str, condition: Condition = Condition.C1, task_id: str = "task-1") -> AgentIdentity:
        return AgentIdentity("run-1", agent_id, condition, task_id, 1)

    def service(
        self,
        root: Path,
        *,
        clock=lambda: "2026-01-01T00:00:00Z",
        artifact_root: Path | None = None,
    ):
        task_root = root / "task-fixtures"
        task_root.mkdir()
        (task_root / "evidence.txt").write_text(
            "The service returned HTTP 503.\nToken: ORCHID-731\n", encoding="utf-8"
        )
        (task_root / "trace.log").write_text("worker timeout after 30 seconds\n", encoding="utf-8")
        store = BoardStore.initialize(root / "board-service" / "board.sqlite3", clock=clock)
        catalog = TaskCatalog({"task-1": TaskDefinition("task-1", task_root)})
        service = ConstrainedToolService(
            TaskToolService(catalog),
            BoardToolService(store),
            artifact_root=artifact_root or root / "artifacts",
            clock=clock,
        )
        return service, store

    def invoke(self, service, identity, operation, arguments):
        return service.invoke(service.issue_credential(identity), operation, arguments)

    @staticmethod
    def submission_arguments():
        return {
            "diagnosis": TASK_ONE_DIAGNOSIS,
            "evidence": [{"path": "evidence.txt", "excerpt": "Token: ORCHID-731", "line_start": 2, "line_end": 2}],
        }

    def test_available_tools_omit_board_in_c0(self):
        with tempfile.TemporaryDirectory() as temp:
            service, store = self.service(Path(temp))
            try:
                self.assertEqual(service.available_tools(self.identity("agent-1", Condition.C0)), CORE_TOOL_NAMES)
                self.assertEqual(
                    service.available_tools(self.identity("agent-1")),
                    CORE_TOOL_NAMES + BOARD_TOOL_NAMES,
                )
            finally:
                store.close()

    def test_task_read_query_and_idempotent_submit_are_audited(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            service, store = self.service(root)
            try:
                identity = self.identity("agent-1")
                credential = service.issue_credential(identity)
                service.update_runtime_usage(identity, 12, 2)
                read = service.invoke(credential, "task_read", {"path": "evidence.txt"})
                query = service.invoke(credential, "task_query", {"query": "orchid"})
                first = service.invoke(credential, "task_submit", self.submission_arguments())
                second = service.invoke(credential, "task_submit", self.submission_arguments())
                self.assertTrue(read["ok"])
                self.assertEqual(read["result"]["content"].splitlines()[1], "Token: ORCHID-731")
                self.assertEqual(query["result"]["matches"][0]["path"], "evidence.txt")
                self.assertEqual(first, second)
                audit_path = root / "artifacts" / "run-1" / "agents" / "agent-1" / "artifacts" / "tool_calls.jsonl"
                events = [json.loads(line) for line in audit_path.read_text().splitlines()]
                self.assertEqual([event["operation"] for event in events], ["task_read", "task_query", "task_submit", "task_submit"])
                self.assertTrue(all(event["run_id"] == "run-1" and event["agent_id"] == "agent-1" for event in events))
                self.assertNotIn(credential, audit_path.read_text())
                self.assertEqual(audit_path.stat().st_mode & 0o777, 0o600)
            finally:
                store.close()

    def test_task_scope_and_argument_validation_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            service, store = self.service(Path(temp))
            try:
                credential = service.issue_credential(self.identity("agent-1"))
                for arguments in (
                    {"path": "../outside"},
                    {"path": "/etc/hosts"},
                    {"path": "evidence.txt", "operation": "write"},
                ):
                    with self.subTest(arguments=arguments):
                        response = service.invoke(credential, "task_read", arguments)
                        self.assertFalse(response["ok"])
                        self.assertEqual(response["error"]["code"], "invalid_arguments")
                unknown_task = service.issue_credential(self.identity("agent-1", task_id="other-task"))
                response = service.invoke(unknown_task, "task_read", {"path": "evidence.txt"})
                self.assertEqual(response["error"]["code"], "permission_denied")
                response = service.invoke(credential, "shell", {})
                self.assertEqual(response["error"]["code"], "invalid_arguments")
                response = service.invoke("forged", "task_read", {"path": "evidence.txt"})
                self.assertEqual(response["error"]["code"], "invalid_credential")
                audit_path = Path(temp) / "artifacts" / "run-1" / "agents" / "agent-1" / "artifacts" / "tool_calls.jsonl"
                events = [json.loads(line) for line in audit_path.read_text().splitlines()]
                self.assertEqual(len(events), 5)
                self.assertTrue(all(event["timestamp"] for event in events))
                self.assertEqual(events[0]["validated_input"], {"path": "../outside"})
                self.assertEqual(events[3]["validated_input"], {"path": "evidence.txt"})
                self.assertEqual(events[4]["validated_input"], {})
            finally:
                store.close()

    def test_extension_has_only_explicit_conditioned_tool_registrations(self):
        extension = Path(__file__).parents[1] / "pi-extension" / "incident-tools.ts"
        source = extension.read_text(encoding="utf-8")
        for name in CORE_TOOL_NAMES + BOARD_TOOL_NAMES:
            self.assertIn(f'name: "{name}"', source)
        self.assertIn('if (condition === "C0") return;', source)
        self.assertLess(source.index('if (condition === "C0") return;'), source.index('name: "board_read"'))

    def test_c1_ordering_pagination_and_cross_run_containment(self):
        with tempfile.TemporaryDirectory() as temp:
            service, store = self.service(Path(temp))
            try:
                agent_one = self.identity("agent-1")
                agent_two = self.identity("agent-2")
                first = self.invoke(service, agent_one, "board_append", {"message": "one"})
                hidden_run = AgentIdentity("run-2", "agent-3", Condition.C1, "task-1", 1)
                self.invoke(service, hidden_run, "board_append", {"message": "other run"})
                second = self.invoke(service, agent_two, "board_append", {"message": "two"})
                credential = service.issue_credential(agent_two)
                page = service.invoke(credential, "board_read", {"after_sequence_id": 0, "limit": 1})
                next_page = service.invoke(
                    credential, "board_read", {"after_sequence_id": page["result"]["next_cursor"], "limit": 1}
                )
                self.assertEqual(page["result"]["messages"][0]["message_body"], "one")
                self.assertTrue(page["result"]["has_more"])
                self.assertEqual(next_page["result"]["messages"][0]["message_body"], "two")
                self.assertEqual(next_page["result"]["messages"][0]["run_id"], "run-1")
                self.assertEqual(first["result"]["agent_id"], "agent-1")
                self.assertEqual(second["result"]["agent_id"], "agent-2")
            finally:
                store.close()

    def test_c2_returns_only_callers_messages_and_c0_has_no_board(self):
        with tempfile.TemporaryDirectory() as temp:
            service, store = self.service(Path(temp))
            try:
                agent_one = self.identity("agent-1", Condition.C2)
                agent_two = self.identity("agent-2", Condition.C2)
                self.invoke(service, agent_one, "board_append", {"message": "private one"})
                self.invoke(service, agent_two, "board_append", {"message": "private two"})
                agent_two_read = self.invoke(service, agent_two, "board_read", {})
                agent_one_read = self.invoke(service, agent_one, "board_read", {})
                c0 = self.identity("agent-0", Condition.C0)
                c0_response = self.invoke(service, c0, "board_append", {"message": "blocked"})
                self.assertEqual(agent_two_read["result"]["messages"][0]["agent_id"], "agent-2")
                self.assertEqual(agent_one_read["result"]["messages"][0]["agent_id"], "agent-1")
                self.assertEqual(c0_response["error"]["code"], "tool_unavailable")
            finally:
                store.close()

    def test_cursor_size_and_identity_spoofing_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            service, store = self.service(Path(temp))
            try:
                identity = self.identity("agent-1")
                credential = service.issue_credential(identity)
                for arguments in (
                    {"after_sequence_id": True},
                    {"after_sequence_id": -1},
                    {"limit": 0},
                    {"limit": MAX_READ_MESSAGES + 1},
                    {"cursor": 0},
                ):
                    with self.subTest(arguments=arguments):
                        response = service.invoke(credential, "board_read", arguments)
                        self.assertEqual(response["error"]["code"], "invalid_arguments")
                spoofed = service.invoke(
                    credential, "board_append", {"message": "x", "agent_id": "agent-9"}
                )
                oversized = service.invoke(
                    credential, "board_append", {"message": "x" * (8 * 1024 + 1)}
                )
                self.assertEqual(spoofed["error"]["code"], "invalid_arguments")
                self.assertEqual(oversized["error"]["code"], "invalid_arguments")
            finally:
                store.close()

    def test_ipc_board_round_trip_does_not_expose_credential(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for use_fifo in (True, False):
                with self.subTest(transport="fifo" if use_fifo else "unix"):
                    transport_root = root / ("fifo" if use_fifo else "unix")
                    transport_root.mkdir()
                    service, store = self.service(transport_root)
                    identity = self.identity("agent-1")
                    second_identity = self.identity("agent-2")
                    socket_path = transport_root / "service.sock"
                    try:
                        try:
                            with ToolServiceSocketServer(service, socket_path, use_fifo=use_fifo) as server:
                                first_credential = service.issue_credential(identity)
                                append = server.request_from_controller({
                                    "credential": first_credential,
                                    "operation": "board_append",
                                    "arguments": {"message": "through IPC"},
                                })
                                second_credential = service.issue_credential(second_identity)
                                read = server.request_from_controller({
                                    "credential": second_credential,
                                    "operation": "board_read",
                                    "arguments": {"limit": 1},
                                })
                        except OSError as exc:
                            if use_fifo or exc.errno != errno.EPERM:
                                raise
                            continue
                        self.assertTrue(append["ok"])
                        self.assertEqual(append["result"]["run_id"], "run-1")
                        self.assertEqual(append["result"]["agent_id"], "agent-1")
                        self.assertEqual(read["result"]["messages"][0]["message_body"], "through IPC")
                        audit = (transport_root / "artifacts" / "run-1" / "agents" / "agent-1" / "artifacts" / "tool_calls.jsonl").read_text()
                        self.assertNotIn(first_credential, audit)
                        self.assertNotIn(second_credential, audit)
                    finally:
                        store.close()

    def test_cli_extension_run_wires_controller_tool_service(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task_root = root / "task-fixtures"
            task_root.mkdir()
            fake_agent = root / "fake_agent.py"
            fake_agent.write_text(
                textwrap.dedent(
                    """
                    import json, os

                    def call(name, arguments):
                        with open(os.environ["APART_TOOL_REQUEST_FIFO"], "wb") as request:
                            request.write((json.dumps({
                                "credential": open(os.environ["APART_CONTROLLER_CREDENTIAL_FILE"]).read(),
                                "operation": name,
                                "arguments": arguments,
                            }) + "\\n").encode())
                        with open(os.environ["APART_TOOL_RESPONSE_FIFO"], "rb") as response_stream:
                            response = json.loads(response_stream.readline())
                        if not response["ok"]:
                            raise SystemExit(response["error"]["message"])
                        print(json.dumps({"type": "tool_call", "id": name, "name": name}), flush=True)
                        return response["result"]

                    call("board_append", {"message": "from cli"})
                    call("board_read", {"limit": 1})
                    print(json.dumps({"type": "message_end", "message": {
                        "role": "assistant", "content": [{"type": "text", "text": "cli done"}],
                        "usage": {"totalTokens": 2}, "stopReason": "stop"
                    }}), flush=True)
                    """
                ),
                encoding="utf-8",
            )
            config_path = root / "runtime.json"
            config_path.write_text(json.dumps({
                "pi": {
                    "version": "test",
                    "model": "fixture",
                    "launch_command": [sys.executable, str(fake_agent)],
                    "thinking_level": "medium",
                },
                "limits": {
                    "agent_count": 1,
                    "per_agent_token_budget": 10,
                    "per_agent_tool_call_budget": 3,
                    "aggregate_token_budget": 10,
                    "aggregate_tool_call_budget": 3,
                    "timeout_seconds": 2,
                },
                "isolation": {
                    "sandbox": "none",
                    "model_network": False,
                    "network": False,
                    "shared_filesystem": False,
                    "shell": False,
                    "subprocess": False,
                    "mcp": False,
                    "subagents": False,
                    "allow_unsafe_for_tests": True,
                },
                "conditions": ["C0", "C1", "C2"],
            }), encoding="utf-8")
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "apart_incident_response.runtime",
                    "run",
                    str(config_path),
                    "--run-id",
                    "run-cli",
                    "--agent-id",
                    "agent-1",
                    "--condition",
                    "C1",
                    "--task-id",
                    "task-1",
                    "--seed",
                    "1",
                    "--workspace-root",
                    str(root / "runs"),
                    "--task-root",
                    str(task_root),
                    "--extension",
                    str(Path(__file__).parents[1] / "pi-extension" / "incident-tools.ts"),
                    "--prompt",
                    "use the constrained board",
                ],
                cwd=Path(__file__).parents[1],
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            result = json.loads(completed.stdout)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["tool_calls_used"], 2)
            audit_path = root / "runs" / "run-cli" / "agents" / "agent-1" / "artifacts" / "tool_calls.jsonl"
            self.assertEqual(len(audit_path.read_text().splitlines()), 2)

    def test_cli_task_one_materializes_authenticated_bundle_and_validates_submission(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            identity = self.identity("agent-2")
            workspace = create_isolated_workspace(root / "runs", identity)
            args = SimpleNamespace(task_root=None, board_database=None)
            service, store = _build_cli_tool_service(args, identity, workspace)
            try:
                credential = service.issue_credential(identity)
                service.update_runtime_usage(identity, 20, 1)
                read = service.invoke(credential, "task_read", {"path": "deployment.txt"})
                self.assertTrue(read["ok"])
                self.assertIn("CACHE_MODE changed from local to shared", read["result"]["content"])
                valid = service.invoke(credential, "task_submit", {
                    "diagnosis": TASK_ONE_DIAGNOSIS,
                    "evidence": [{
                        "path": "deployment.txt",
                        "line_start": 2,
                        "line_end": 2,
                        "excerpt": "CACHE_MODE changed from local to shared",
                    }],
                })
                self.assertTrue(valid["ok"])
                invalid = service.invoke(credential, "task_submit", {
                    "diagnosis": "ORCHID-731 CACHE_MODE local shared outage keywords are present, but DNS caused the outage.",
                    "evidence": [{"path": "deployment.txt", "excerpt": "CACHE_MODE changed from local to shared"}],
                })
                self.assertEqual(invalid["error"]["code"], "invalid_arguments")
                self.assertTrue((workspace.task_dir / "deployment.txt").is_file())
            finally:
                store.close()

    def test_runtime_mounts_service_and_records_tool_flow(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            service, store = self.service(root, artifact_root=root / "runs")
            fake_agent = root / "fake_agent.py"
            fake_agent.write_text(
                textwrap.dedent(
                    """
                    import json, os, sys

                    def call(name, arguments):
                        with open(os.environ["APART_TOOL_REQUEST_FIFO"], "wb") as request:
                            request.write((json.dumps({
                                "credential": open(os.environ["APART_CONTROLLER_CREDENTIAL_FILE"]).read(),
                                "operation": name,
                                "arguments": arguments,
                            }) + "\\n").encode())
                        with open(os.environ["APART_TOOL_RESPONSE_FIFO"], "rb") as response_stream:
                            response = json.loads(response_stream.readline())
                        if not response["ok"]:
                            raise SystemExit(response["error"]["message"])
                        print(json.dumps({"type": "tool_call", "id": name, "name": name}), flush=True)
                        return response["result"]

                    call("task_read", {"path": "evidence.txt"})
                    call("task_query", {"query": "ORCHID-731"})
                    call("task_submit", {"diagnosis": "The ORCHID-731 configuration revision changed CACHE_MODE from local to shared, causing the cache-related outage.", "evidence": [{"path": "evidence.txt", "excerpt": "Token: ORCHID-731"}]})
                    print(json.dumps({"type": "message_end", "message": {
                        "role": "assistant", "content": [{"type": "text", "text": "done"}],
                        "usage": {"totalTokens": 3}, "stopReason": "stop"
                    }}), flush=True)
                    """
                ),
                encoding="utf-8",
            )
            identity = self.identity("agent-1")
            workspace = create_isolated_workspace(root / "runs", identity)
            config = RuntimeConfig(
                pi_version="test",
                model="fixture",
                launch_command=(sys.executable, str(fake_agent)),
                agent_count=1,
                per_agent_token_budget=10,
                per_agent_tool_call_budget=4,
                aggregate_token_budget=10,
                aggregate_tool_call_budget=4,
                timeout_seconds=2,
                isolation=IsolationPolicy(sandbox="none", allow_unsafe_for_tests=True),
            )
            try:
                result = AgentRun(
                    config,
                    identity,
                    workspace,
                    SystemBudget(10, 4),
                    service,
                ).run("complete the fixture", Path("pi-extension/incident-tools.ts"))
                self.assertEqual(result.status.value, "completed")
                self.assertEqual(result.tool_calls_used, 3)
                self.assertEqual(result.final_response, "done")
                audit_path = workspace.artifact_dir / "tool_calls.jsonl"
                self.assertEqual(len(audit_path.read_text().splitlines()), 3)
                self.assertNotIn("APART_CONTROLLER_CREDENTIAL", audit_path.read_text())
                submission = json.loads((workspace.artifact_dir / "task_submission.json").read_text())
                self.assertEqual(submission["token_usage"]["source"], "controller_runtime_accounting")
                self.assertGreaterEqual(submission["token_usage"]["tool_calls"], 0)
                self.assertLessEqual(submission["token_usage"]["tool_calls"], result.tool_calls_used)
                self.assertLessEqual(submission["token_usage"]["total_tokens"], result.tokens_used)
                metadata = json.loads((workspace.artifact_dir / "metadata.json").read_text())
                self.assertNotIn("controller-credential", json.dumps(metadata["command"]))
                self.assertFalse((workspace.root / ".apart-tool-service.sock").exists())
            finally:
                store.close()

    def test_bubblewrap_service_mount_keeps_credential_out_of_argv(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            service, store = self.service(root)
            identity = self.identity("agent-1")
            workspace = create_isolated_workspace(root / "runs", identity)
            credential_file = root / "controller" / "credential"
            credential_file.parent.mkdir(mode=0o700)
            credential_file.write_text("opaque-test-credential", encoding="utf-8")
            credential_file.chmod(0o600)
            config = RuntimeConfig(
                pi_version="test",
                model="fixture",
                launch_command=("true",),
                agent_count=1,
                per_agent_token_budget=10,
                per_agent_tool_call_budget=1,
                aggregate_token_budget=10,
                aggregate_tool_call_budget=1,
                timeout_seconds=1,
                isolation=IsolationPolicy(sandbox="bubblewrap"),
            )
            try:
                command = build_pi_command(
                    config,
                    identity,
                    workspace,
                    Path("pi-extension/incident-tools.ts"),
                    tool_socket=workspace.root / ".apart-tool-service.sock",
                    extra_env={"APART_CONTROLLER_CREDENTIAL_FILE": str(credential_file)},
                )
                self.assertIn("--unshare-net", command)
                self.assertIn("--bind", command)
                self.assertIn("/controller/credential", command)
                self.assertIn("APART_CONTROLLER_CREDENTIAL_FILE", command)
                self.assertNotIn("opaque-test-credential", command)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
