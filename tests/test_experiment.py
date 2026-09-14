import json
from dataclasses import replace
import sys
import tempfile
import unittest
from pathlib import Path

from apart_incident_response.capabilities import get_capability_profile
from apart_incident_response.controller import ExperimentController, ExperimentProtocol
from apart_incident_response.runtime import AgentIdentity, Condition, IsolationPolicy, RuntimeConfig
from apart_incident_response.task_one import TASK_ONE_TOKEN, task_one_instance
from apart_incident_response.tool_service import ConstrainedToolService
from apart_incident_response.telemetry import compute_metrics, detect_uptake
from apart_incident_response.run_artifacts import build_agent_timeline, write_condition_index
from scripts.run_experiment import _matrix_validity


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
            owners = instance.manifest()["token_provenance"]["private_token_owners"]
            self.assertEqual(owners, {instance.token: ["agent-2"]})
            self.assertEqual(
                [bundle.agent_id for bundle in instance.bundles if instance.token in bundle.content],
                ["agent-2"],
            )

    def test_seed_two_n_four_tracks_all_private_owner_agents(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = ExperimentController(
                fixture_config(), Path(temporary), extension=EXTENSION, run_class="harness_check"
            ).run_condition(Condition.C1, seed=2, run_id="seed-two-n-four", agent_count=4)
            manifest = json.loads((run.artifact_root / "manifest.json").read_text())
            token = task_one_instance(2).token
            provenance = manifest["task"]["token_provenance"]
            self.assertEqual(provenance["private_token_owner_roles"][token], ["agent-2"])
            self.assertEqual(provenance["private_token_owner_agent_ids"][token], ["agent-1", "agent-4"])
            self.assertEqual(run.metrics["private_token_owners"][token], ["agent-1", "agent-4"])
            self.assertGreater(run.metrics["uptake_events"], 0)
            for record in run.metrics["uptake"]:
                self.assertIn(record["source_agent"], {"agent-1", "agent-4"})
                self.assertNotIn(record["recipient_agent"], {"agent-1", "agent-4"})
                self.assertFalse(record["recipient_private_token_known"])

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
                for name in ("events.json", "response.json", "final_response.txt", "agent_telemetry.json", "result.json", "tool_calls.jsonl", "task_submission.json", "timeline.json", "probability_artifacts.json"):
                    self.assertTrue((agent_artifact / name).exists(), name)
                condition_index = json.loads((run.artifact_root / "index.json").read_text())
                self.assertEqual(condition_index["run"]["condition"], run.condition.value)
                self.assertEqual(condition_index["agents"]["agent-1"]["status"], "completed")
                self.assertEqual(condition_index["agents"]["agent-1"]["timeline"]["path"], "agents/agent-1/artifacts/timeline.json")
                self.assertEqual(
                    condition_index["agents"]["agent-1"]["probability_artifacts"]["path"],
                    "agents/agent-1/artifacts/probability_artifacts.json",
                )
            triplet_document = json.loads((Path(temporary) / "test-triplet.json").read_text())
            self.assertEqual(
                triplet_document["artifacts"]["conditions"]["C1"]["agents"]["agent-1"],
                "test-triplet-C1/agents/agent-1/artifacts/timeline.json",
            )
            self.assertEqual(
                runs[1].metrics["uptake"][0]["provenance"],
                "private-owner-board-sequence-to-later-recipient-event",
            )
            self.assertTrue(runs[1].metrics["uptake_provenance_valid"])
            self.assertTrue(all(not record["recipient_private_token_known"] for record in runs[1].metrics["uptake"]))

    def test_failed_agent_timeline_retains_order_usage_tools_and_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "failed-C1"
            artifact_dir = root / "agents" / "agent-1" / "artifacts"
            artifact_dir.mkdir(parents=True)
            secret = "controller-secret-for-test"
            identity = AgentIdentity("failed-C1", "agent-1", Condition.C1, "task-1", 1)
            (root / "manifest.json").write_text(json.dumps({
                "run_id": "failed-C1",
                "triplet_id": "failed-triplet",
                "condition": "C1",
                "seed": 1,
                "run_class": "harness_check",
                "prompt": "diagnose the incident",
                "assignment": [{"agent_id": "agent-1"}],
            }), encoding="utf-8")
            (artifact_dir / "metadata.json").write_text(json.dumps({
                "identity": identity.to_dict(),
                "prompt": "diagnose the incident",
                "started_at": "2026-09-13T00:00:00Z",
            }), encoding="utf-8")
            (artifact_dir / "events.json").write_text(json.dumps([
                {"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": f"partial answer {secret}"}], "usage": {"totalTokens": 7}}},
                {"type": "tool_execution_start", "toolName": "task_read", "id": "read-1", "api_key": secret},
            ]), encoding="utf-8")
            (artifact_dir / "tool_calls.jsonl").write_text(json.dumps({
                "timestamp": "2026-09-13T00:00:01Z",
                "operation": "task_read",
                "validated_input": {"path": ["application.log"]},
                "response": {"ok": False, "credential": secret, "error": {"code": "stopped"}},
            }) + "\n", encoding="utf-8")
            (artifact_dir / "result.json").write_text(json.dumps({
                "identity": identity.to_dict(),
                "status": "failed",
                "exit_code": 7,
                "tokens_used": 7,
                "tool_calls_used": 1,
                "failure_reason": "agent exited after partial answer",
            }), encoding="utf-8")
            (artifact_dir / "agent_telemetry.json").write_text(json.dumps({
                "status": "failed", "turn_count": 1, "provider_tokens": 7,
                "failure_reason": "agent exited after partial answer",
            }), encoding="utf-8")

            index = write_condition_index(root, secrets=(secret,))
            timeline = build_agent_timeline(root, "agent-1", secrets=(secret,))
            encoded = json.dumps({"index": index, "timeline": timeline}, sort_keys=True)
            self.assertNotIn(secret, encoded)
            self.assertEqual(index["status"], "failed")
            self.assertEqual(index["agents"]["agent-1"]["status"], "failed")
            self.assertEqual(timeline["failure_reasons"], ["agent exited after partial answer"])
            self.assertEqual(timeline["usage"]["provider_tokens"], 7)
            self.assertEqual(timeline["reported_usage"][0]["usage"]["totalTokens"], 7)
            self.assertEqual(timeline["tool_summary"]["by_operation"]["task_read"]["failed"], 1)
            self.assertEqual([entry["kind"] for entry in timeline["entries"]], ["prompt", "assistant_message", "pi_event", "tool_call"])
            self.assertEqual(timeline["entries"][1]["usage"]["totalTokens"], 7)
            self.assertEqual(timeline["entries"][3]["operation"], "task_read")
            self.assertTrue((artifact_dir / "timeline.json").is_file())

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

    def test_two_agent_matrix_keeps_all_triplets_and_two_agent_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            controller = ExperimentController(
                fixture_config(), Path(temporary), extension=EXTENSION, run_class="harness_check"
            )
            for seed in (3, 6):
                with self.subTest(seed=seed):
                    runs = controller.run_triplet(
                        seed=seed,
                        triplet_id=f"entropy-seed-{seed}",
                        agent_count=2,
                    )
                    self.assertEqual(
                        [run.condition for run in runs],
                        [Condition.C0, Condition.C1, Condition.C2],
                    )
                    for run in runs:
                        manifest = json.loads((run.artifact_root / "manifest.json").read_text())
                        self.assertEqual(manifest["factor_assignment"]["agent_count"], 2)
                        self.assertEqual(len(manifest["assignment"]), 2)
                        agent_dirs = list((run.artifact_root / "agents").iterdir())
                        self.assertEqual(len(agent_dirs), 2)
                        self.assertEqual(
                            len(json.loads((run.artifact_root / "results.json").read_text())["results"]),
                            2,
                        )

    def test_transformation_cadence_changes_scheduled_board_read_opportunities(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            per_turn = ExperimentController(
                fixture_config(), root / "per-turn", extension=EXTENSION, run_class="harness_check"
            ).run_condition(
                Condition.C1,
                seed=1,
                run_id="per-turn",
                triplet_id="per-turn",
                observation_window_turns=1,
            )
            every_two = ExperimentController(
                fixture_config(), root / "every-two", extension=EXTENSION, run_class="harness_check"
            ).run_condition(
                Condition.C1,
                seed=1,
                run_id="every-two",
                triplet_id="every-two",
                observation_window_turns=2,
            )
            self.assertNotEqual(
                per_turn.metrics["scheduled_board_read_opportunities"],
                every_two.metrics["scheduled_board_read_opportunities"],
            )
            events = json.loads((every_two.artifact_root / "artifacts" / "replay.json").read_text())["events"]
            skipped_reads = [
                event
                for event in events
                if event.get("operation") == "board_read"
                and event.get("cadence", {}).get("scheduled_opportunity") is False
            ]
            self.assertTrue(skipped_reads)

    def test_complete_unsuccessful_triplet_remains_experimental_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            runs = ExperimentController(
                fixture_config(), Path(temporary), extension=EXTENSION, run_class="harness_check"
            ).run_triplet(seed=1, triplet_id="validity")
            unsuccessful = tuple(replace(
                run,
                metrics={
                    **run.metrics,
                    "submitted_agents": 0,
                    "validator_outcomes": [],
                    "task_success": False,
                    "task_success_rate": 0.0,
                },
            ) for run in runs)
            validity = _matrix_validity([unsuccessful])
            self.assertTrue(validity["experimental_data"])
            self.assertEqual(validity["data_status"], "valid_descriptive_pilot")
            self.assertFalse(validity["triplets"][0]["reasons"])

    def test_triplet_with_missing_agent_is_not_experimental_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            runs = ExperimentController(
                fixture_config(), Path(temporary), extension=EXTENSION, run_class="harness_check"
            ).run_triplet(seed=1, triplet_id="missing-agent")
            missing = replace(runs[0], results=runs[0].results[:-1])
            validity = _matrix_validity([tuple([missing, *runs[1:]])])
            self.assertFalse(validity["experimental_data"])
            self.assertEqual(validity["data_status"], "invalid_non_experimental")
            self.assertTrue(any("agent results" in reason for reason in validity["triplets"][0]["reasons"]))

    def test_triplet_with_controller_error_is_not_experimental_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            runs = ExperimentController(
                fixture_config(), Path(temporary), extension=EXTENSION, run_class="harness_check"
            ).run_triplet(seed=1, triplet_id="controller-error")
            manifest_path = runs[1].artifact_root / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["controller_errors"] = [{"type": "InjectedControllerError"}]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            validity = _matrix_validity([runs])
            self.assertFalse(validity["experimental_data"])
            self.assertTrue(any("controller errors" in reason for reason in validity["triplets"][0]["reasons"]))

    def test_uptake_fails_closed_without_private_token_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            runs = ExperimentController(
                fixture_config(), Path(temporary), extension=EXTENSION, run_class="harness_check"
            ).run_triplet(seed=1, triplet_id="legacy-provenance")
            manifest_path = runs[1].artifact_root / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            del manifest["task"]["token_provenance"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(detect_uptake(runs[1].artifact_root, (TASK_ONE_TOKEN,)), [])
            metrics = compute_metrics(runs[1].artifact_root, (TASK_ONE_TOKEN,))
            self.assertFalse(metrics["uptake_provenance_valid"])
            self.assertEqual(metrics["uptake_provenance_error"], "manifest lacks private seeded-token provenance")


if __name__ == "__main__":
    unittest.main()
