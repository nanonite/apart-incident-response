import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from apart_incident_response.runtime import (
    AgentIdentity,
    AgentRun,
    Condition,
    IsolationPolicy,
    RuntimeConfig,
    SystemBudget,
    create_isolated_workspace,
)
from apart_incident_response.task_prompts import (
    TASK_ONE_PROMPT,
    TaskPromptCatalog,
)


class TaskPromptTests(unittest.TestCase):
    @staticmethod
    def config(**overrides):
        values = {
            "pi_version": "0.85.1",
            "model": "fixture",
        }
        values.update(overrides)
        return RuntimeConfig(**values)

    def test_task_one_prompt_requests_diagnosis_and_submission(self):
        prompt = TaskPromptCatalog().prompt_for("task-1", 7)
        self.assertEqual(prompt, TASK_ONE_PROMPT)
        self.assertIn("most likely root cause", prompt)
        self.assertIn("task_read", prompt)
        self.assertIn("task_query", prompt)
        self.assertIn("task_submit", prompt)
        for prohibited in ("collaborat", "delegat", "board"):
            self.assertNotIn(prohibited, prompt.casefold())

    def test_same_task_and_seed_prompt_is_identical_across_conditions(self):
        config = self.config()
        prompts = {
            condition: config.prompt_for("task-1", 17)
            for condition in (Condition.C0, Condition.C1, Condition.C2)
        }
        self.assertEqual(set(prompts.values()), {TASK_ONE_PROMPT})

    def test_prompt_is_configurable_without_condition_specific_selection(self):
        configured = "Inspect the assigned incident evidence and submit the likely cause."
        config = self.config(task_prompts={"task-1": configured})
        self.assertEqual(config.prompt_for("task-1", 1), configured)
        self.assertEqual(config.prompt_for("task-1", 1), config.prompt_for("task-1", 1))

    def test_agent_run_uses_configured_prompt_when_no_override_is_given(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_agent = root / "prompt_echo.py"
            fake_agent.write_text(
                textwrap.dedent(
                    """
                    import json, sys
                    prompt = sys.stdin.read().strip()
                    print(json.dumps({
                        "type": "message_end",
                        "usage": {"totalTokens": 1},
                        "text": prompt,
                    }), flush=True)
                    """
                ),
                encoding="utf-8",
            )
            config = self.config(
                launch_command=(sys.executable, str(fake_agent)),
                isolation=IsolationPolicy(sandbox="none", allow_unsafe_for_tests=True),
                per_agent_token_budget=2,
                per_agent_tool_call_budget=1,
                aggregate_token_budget=2,
                aggregate_tool_call_budget=1,
                timeout_seconds=2,
            )
            responses = []
            for condition in (Condition.C0, Condition.C1, Condition.C2):
                identity = AgentIdentity("prompt-run", condition.value, condition, "task-1", 7)
                workspace = create_isolated_workspace(root / "runs", identity)
                result = AgentRun(
                    config,
                    identity,
                    workspace,
                    SystemBudget(2, 1),
                ).run()
                self.assertEqual(result.status.value, "completed")
                responses.append(result.final_response)
                metadata = json.loads((workspace.artifact_dir / "metadata.json").read_text())
                self.assertEqual(metadata["prompt"], TASK_ONE_PROMPT)
            self.assertEqual(responses, [TASK_ONE_PROMPT] * 3)

    def test_unknown_task_and_malformed_seed_fail_closed(self):
        catalog = TaskPromptCatalog()
        with self.assertRaises(ValueError):
            catalog.prompt_for("task-2", 1)
        with self.assertRaises(ValueError):
            catalog.prompt_for("task-1", True)


if __name__ == "__main__":
    unittest.main()
