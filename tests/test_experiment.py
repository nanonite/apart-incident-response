import json
import sys
import tempfile
import unittest
from pathlib import Path

from apart_incident_response.capabilities import get_capability_profile
from apart_incident_response.controller import ExperimentController, ExperimentProtocol
from apart_incident_response.runtime import AgentIdentity, Condition, IsolationPolicy, RuntimeConfig
from apart_incident_response.task_one import TASK_ONE_TOKEN, task_one_instance
from apart_incident_response.tool_service import ConstrainedToolService


ROOT = Path(__file__).parents[1]
FAKE_AGENT = ROOT / "tests" / "fixtures" / "controlled_fake_agent.py"
EXTENSION = ROOT / "pi-extension" / "incident-tools.ts"


def fixture_config() -> RuntimeConfig:
    return RuntimeConfig(
        pi_version="fixture",
        model="fixture/controlled-agent",
        launch_command=(sys.executable, str(FAKE_AGENT)),
        agent_count=3,
        per_agent_token_budget=40,
        per_agent_tool_call_budget=10,
        aggregate_token_budget=120,
        aggregate_tool_call_budget=30,
        timeout_seconds=10,
        isolation=IsolationPolicy(sandbox="none", allow_unsafe_for_tests=True),
    )


class ControlledExperimentTests(unittest.TestCase):
    def test_protocol_is_versioned_and_declares_matched_triplets(self):
        protocol = ExperimentProtocol()
        document = protocol.to_dict()
        self.assertEqual(document["protocol_version"], "controlled-n-agent-c0-c1-c2-v1")
        self.assertEqual(document["conditions"], ["C0", "C1", "C2"])
        self.assertEqual(document["primary_contrast"], "C1 versus C2")
        self.assertEqual(set(document["factor_levels"]), {
            "agent_count", "capability_profile", "difficulty", "transformation_cadence", "model"
        })
        self.assertIn("aggregate token/tool-call ceilings", document["matched_within_triplet"])

    def test_seeded_instances_change_fixture_hash_but_keep_incomplete_roles(self):
        first = task_one_instance(1)
        second = task_one_instance(2)
        self.assertEqual(first.token, TASK_ONE_TOKEN)
        self.assertNotEqual(first.manifest()["fixture_sha256"], second.manifest()["fixture_sha256"])
        self.assertNotEqual(first.diagnosis, second.diagnosis)
        for instance in (first, second):
            self.assertTrue(all(not instance.validate_answer(bundle.content).accepted for bundle in instance.bundles))
            self.assertTrue(instance.validate_answer(instance.diagnosis).accepted)

    def test_capability_profile_cannot_change_board_condition(self):
        profile = get_capability_profile("task-read-submit-v1")
        self.assertNotIn("task_query", profile.task_tools)
        identity = AgentIdentity("run", "agent-1", Condition.C1, "task-1", 1, "task-read-submit-v1")
        service = object.__new__(ConstrainedToolService)
        service._board_service = object()
        self.assertEqual(service.available_tools(identity), ("task_read", "task_submit", "board_read", "board_append"))
        c0 = AgentIdentity("run", "agent-1", Condition.C0, "task-1", 1, "task-read-submit-v1")
        self.assertEqual(service.available_tools(c0), ("task_read", "task_submit"))

    def test_fake_provider_triplet_records_provenance_and_containment_as_harness_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            controller = ExperimentController(
                fixture_config(),
                Path(temporary),
                extension=EXTENSION,
                run_class="harness_check",
            )
            runs = controller.run_triplet(seed=1, triplet_id="test-triplet")
            self.assertEqual([run.condition for run in runs], [Condition.C0, Condition.C1, Condition.C2])
            self.assertFalse(any(json.loads((run.artifact_root / "manifest.json").read_text())["run_class"] == "experimental" for run in runs))
            self.assertEqual(runs[0].metrics["U"], 0.0)
            self.assertGreater(runs[1].metrics["U"], 0.0)
            self.assertEqual(runs[2].metrics["U"], 0.0)
            # Concurrent agents may observe different prefixes of the append-only
            # board; raw events preserve the exact schedule for replay.
            self.assertGreater(runs[1].metrics["cross_agent_messages_X"], 0)
            self.assertLessEqual(runs[1].metrics["cross_agent_messages_X"], 6)
            self.assertEqual(runs[2].metrics["cross_agent_messages_X"], 0)
            for run in runs:
                self.assertTrue(run.metrics["task_success"])
                self.assertLessEqual(run.metrics["total_tokens"], 120)
                self.assertLessEqual(run.metrics["total_tool_calls"], 30)
                artifact_dir = run.artifact_root / "artifacts"
                for name in ("board_events.jsonl", "metrics.json", "uptake.json", "replay.json"):
                    self.assertTrue((artifact_dir / name).exists(), name)
                agent_artifact = run.artifact_root / "agents" / "agent-1" / "artifacts"
                for name in ("events.json", "response.json", "final_response.txt", "agent_telemetry.json", "result.json", "tool_calls.jsonl", "task_submission.json"):
                    self.assertTrue((agent_artifact / name).exists(), name)
            self.assertEqual(runs[1].metrics["uptake"][0]["provenance"], "board_sequence_to_later_recipient_event")

    def test_n_two_and_n_three_use_one_shared_budget_and_isolated_assignments(self):
        with tempfile.TemporaryDirectory() as temporary:
            controller = ExperimentController(fixture_config(), Path(temporary), extension=EXTENSION, run_class="harness_check")
            two = controller.run_condition(Condition.C1, seed=1, run_id="n-two", triplet_id="n-two", agent_count=2)
            three = controller.run_condition(Condition.C2, seed=1, run_id="n-three", triplet_id="n-three", agent_count=3)
            for run, count in ((two, 2), (three, 3)):
                manifest = json.loads((run.artifact_root / "manifest.json").read_text())
                self.assertEqual(manifest["factor_assignment"]["agent_count"], count)
                self.assertEqual(len(manifest["assignment"]), count)
                budget = json.loads((run.artifact_root / "budget.json").read_text())
                self.assertLessEqual(budget["tokens_used"], 120)
                self.assertEqual(len(list((run.artifact_root / "agents").iterdir())), count)


if __name__ == "__main__":
    unittest.main()
