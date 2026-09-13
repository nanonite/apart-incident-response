import json
from pathlib import Path
import tempfile
import unittest

from apart_incident_response.run_artifacts import build_agent_timeline


ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


class AgentProbabilityArtifactTests(unittest.TestCase):
    def test_timeline_persists_replayable_text_and_unavailable_tool_turns(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "run-C1"
            artifact_dir = root / "agents" / "agent-1" / "artifacts"
            artifact_dir.mkdir(parents=True)
            (root / "manifest.json").write_text(json.dumps({
                "run_id": "run-C1",
                "triplet_id": "run",
                "condition": "C1",
                "seed": 1,
                "run_class": "harness_check",
                "prompt": "capital?",
                "assignment": [{"agent_id": "agent-1"}],
            }), encoding="utf-8")
            (artifact_dir / "metadata.json").write_text(json.dumps({
                "prompt": "capital?",
                "started_at": "2026-09-13T00:00:00Z",
            }), encoding="utf-8")
            events = []
            for filename in ("pi-openrouter-logprobs-stream.jsonl", "pi-openrouter-tool-call-stream.jsonl"):
                events.extend(
                    json.loads(line)
                    for line in (FIXTURES / filename).read_text(encoding="utf-8").splitlines()
                )
            secret = "controller-secret-for-probability-test"
            events[-1]["message"]["content"][0]["arguments"]["city"] = secret
            (artifact_dir / "events.json").write_text(json.dumps(events), encoding="utf-8")
            (artifact_dir / "tool_calls.jsonl").write_text("", encoding="utf-8")
            (artifact_dir / "result.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
            (artifact_dir / "agent_telemetry.json").write_text(json.dumps({"status": "completed", "turn_count": 2}), encoding="utf-8")

            timeline = build_agent_timeline(root, "agent-1", secrets=(secret,), persist=True)
            probability = json.loads(
                (artifact_dir / "probability_artifacts.json").read_text(encoding="utf-8")
            )
            encoded = json.dumps({"timeline": timeline, "probability": probability}, sort_keys=True)
            self.assertNotIn(secret, encoded)
            self.assertEqual(probability["coverage"]["turns"], 2)
            self.assertEqual(probability["coverage"]["complete"], 1)
            self.assertEqual(probability["coverage"]["unavailable"], 1)
            self.assertEqual(probability["coverage"]["by_kind"]["text"]["tokens"], 2)
            self.assertEqual(probability["turns"][0]["replay"]["status"], "complete")
            self.assertEqual(probability["turns"][1]["replay"]["status"], "unavailable")
            self.assertTrue(timeline["probability_artifacts"]["present"])
            self.assertTrue(timeline["artifacts"]["probability_artifacts.json"]["present"])


if __name__ == "__main__":
    unittest.main()
