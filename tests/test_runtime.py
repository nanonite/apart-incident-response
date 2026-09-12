import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from apart_incident_response.runtime import (
    AgentIdentity,
    AgentRun,
    Condition,
    IsolationPolicy,
    RuntimeConfig,
    RuntimeConfigError,
    SystemBudget,
    build_pi_command,
    create_isolated_workspace,
    load_identity,
)


class RuntimeContractTests(unittest.TestCase):
    def config(self, **overrides):
        values = {
            "pi_version": "0.83.0",
            "model": "openai-codex/gpt-5.6-luna",
            "pi_root_env": None,
            "isolation": IsolationPolicy(sandbox="none", allow_unsafe_for_tests=True),
        }
        values.update(overrides)
        return RuntimeConfig(**values)

    def identity(self, agent_id="agent-1", condition=Condition.C0):
        return AgentIdentity("run-001", agent_id, condition, "task-1", 17)

    def test_config_keeps_same_aggregate_budget_for_all_conditions(self):
        config = self.config()
        self.assertEqual(config.conditions, (Condition.C0, Condition.C1, Condition.C2))
        self.assertEqual(config.aggregate_token_budget, 12_000)
        self.assertEqual(config.aggregate_tool_call_budget, 96)

    def test_config_rejects_side_channels(self):
        with self.assertRaises(RuntimeConfigError):
            self.config(isolation=IsolationPolicy(network=True, sandbox="none", allow_unsafe_for_tests=True))

    def test_config_rejects_shell_operators(self):
        with self.assertRaises(RuntimeConfigError):
            self.config(launch_command=("pi", "--", "x; touch leaked"))

    def test_identity_is_stable_and_unique(self):
        first = self.identity("agent-1")
        second = self.identity("agent-2")
        self.assertEqual(first.credential_id, first.credential_id)
        self.assertNotEqual(first.credential_id, second.credential_id)
        self.assertNotEqual(first.credential_id, self.identity("agent-1", Condition.C1).credential_id)
        self.assertNotEqual(first.credential_id, AgentIdentity("run-001", "agent-1", Condition.C0, "task-1", 18).credential_id)
        self.assertEqual(first.to_dict()["condition"], "C0")

    def test_identity_round_trip_rejects_tampering(self):
        identity = self.identity()
        self.assertEqual(load_identity(identity.to_dict()), identity)
        tampered = identity.to_dict()
        tampered["credential_id"] = "not-the-controller-binding"
        with self.assertRaises(RuntimeConfigError):
            load_identity(tampered)
        missing = identity.to_dict()
        del missing["task_id"]
        with self.assertRaises(RuntimeConfigError):
            load_identity(missing)

    def test_workspace_is_agent_specific_and_private(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = create_isolated_workspace(root, self.identity("agent-1"))
            second = create_isolated_workspace(root, self.identity("agent-2"))
            self.assertNotEqual(first.root, second.root)
            self.assertNotEqual(first.task_dir, second.task_dir)
            self.assertEqual(first.root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(first.task_dir.stat().st_mode & 0o777, 0o700)
            with self.assertRaises(RuntimeConfigError):
                create_isolated_workspace(root, self.identity("agent-1"))

    def test_pi_command_is_minimal_and_disables_session_persistence(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = create_isolated_workspace(Path(temp), self.identity())
            command = build_pi_command(self.config(), self.identity(), workspace)
            self.assertIn("--no-tools", command)
            self.assertIn("--no-skills", command)
            self.assertIn("--no-extensions", command)
            self.assertIn("--no-context-files", command)
            self.assertIn("--no-session", command)
            self.assertIn("--mode", command)
            self.assertNotIn("bash", command)

    def test_local_pi_checkout_is_resolved_from_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            pi_root = Path(temp) / "pi"
            (pi_root / "packages/coding-agent/src").mkdir(parents=True)
            (pi_root / "packages/coding-agent/package.json").write_text(
                json.dumps({"version": "0.83.0"}), encoding="utf-8"
            )
            config = self.config(
                pi_root_env="TEST_APART_PI_ROOT",
                launch_command=("bun", "run", "{pi_root}/packages/coding-agent/src/cli.ts"),
            )
            workspace = create_isolated_workspace(Path(temp) / "runs", self.identity())
            with patch.dict(os.environ, {"TEST_APART_PI_ROOT": str(pi_root)}):
                command = build_pi_command(config, self.identity(), workspace)
            self.assertTrue(any(str(pi_root) in part for part in command))

    def test_system_budget_is_atomic(self):
        budget = SystemBudget(10, 2)
        self.assertTrue(budget.reserve(tokens=7, tool_calls=1))
        self.assertFalse(budget.reserve(tokens=4, tool_calls=0))
        self.assertEqual(budget.tokens_used, 7)
        self.assertEqual(budget.tool_calls_used, 1)
        self.assertTrue(budget.reserve(tokens=3, tool_calls=1))
        self.assertFalse(budget.reserve(tokens=0, tool_calls=1))

    def test_agent_lifecycle_writes_complete_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake_agent = root / "fake_agent.py"
            fake_agent.write_text(
                textwrap.dedent(
                    """
                    import json
                    import sys
                    prompt = sys.stdin.read()
                    print(json.dumps({"type": "tool_call", "name": "task_read"}), flush=True)
                    print(json.dumps({"type": "message_end", "usage": {"total_tokens": 7}, "text": prompt.strip()}), flush=True)
                    """
                ),
                encoding="utf-8",
            )
            identity = self.identity()
            workspace = create_isolated_workspace(root / "runs", identity)
            config = self.config(
                launch_command=(sys.executable, str(fake_agent)),
                per_agent_token_budget=10,
                per_agent_tool_call_budget=2,
                aggregate_token_budget=10,
                aggregate_tool_call_budget=2,
                timeout_seconds=2,
            )
            result = AgentRun(config, identity, workspace, SystemBudget(10, 2)).run("diagnose this")
            self.assertEqual(result.status.value, "completed")
            self.assertEqual(result.final_response, "diagnose this")
            self.assertEqual(result.tokens_used, 7)
            self.assertEqual(result.tool_calls_used, 1)
            self.assertTrue((workspace.artifact_dir / "metadata.json").exists())
            self.assertTrue((workspace.artifact_dir / "events.json").exists())
            saved = json.loads((workspace.artifact_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "completed")

    def test_agent_timeout_produces_failure_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake_agent = root / "slow_agent.py"
            fake_agent.write_text(
                "import time; time.sleep(2)\n",
                encoding="utf-8",
            )
            identity = self.identity()
            workspace = create_isolated_workspace(root / "runs", identity)
            config = self.config(
                launch_command=(sys.executable, str(fake_agent)),
                timeout_seconds=0.05,
            )
            result = AgentRun(config, identity, workspace, SystemBudget(10, 2)).run("wait")
            self.assertEqual(result.status.value, "timed_out")
            self.assertEqual(json.loads((workspace.artifact_dir / "result.json").read_text(encoding="utf-8"))["status"], "timed_out")

    def test_json_config_round_trips(self):
        config = RuntimeConfig.from_json(Path("config/runtime.json"))
        self.assertEqual(config.pi_version, "0.85.1")
        self.assertEqual(config.model, "openai-codex/gpt-5.6-luna")
        encoded = json.dumps(config.to_dict())
        self.assertIn('"C2"', encoded)


if __name__ == "__main__":
    unittest.main()
