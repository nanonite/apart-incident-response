import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apart_incident_response.behavioral_discovery import (
    BehavioralArtifactStore,
    BehavioralProviderConfig,
    OpenRouterBehavioralProvider,
    audit_retained_pilot,
)
from apart_incident_response.communication_protocol import BatteryCondition
from apart_incident_response.communication_runner import AgentContext


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class BehavioralDiscoveryTests(unittest.TestCase):
    def context(self):
        return AgentContext("run", "instance", "A", BatteryCondition.COMM, 0,
                            {"family": "hypothesis", "task_instruction": "answer", "candidate_labels": ["candidate-0"]},
                            (), "prompt-v1", 96)

    def test_behavioral_payload_omits_logprob_parameters(self):
        provider = OpenRouterBehavioralProvider(
            BehavioralProviderConfig(max_requests=1, min_interval_seconds=0), api_key="secret"
        )
        with patch("apart_incident_response.behavioral_discovery.urllib.request.urlopen",
                   return_value=FakeResponse({"model": "fixture", "choices": [{"message": {"content": "ANSWER: candidate-0"}, "finish_reason": "stop"}], "usage": {"cost": 0}})) as opener:
            response = provider.respond(self.context())
        payload = json.loads(opener.call_args.args[0].data.decode())
        self.assertNotIn("logprobs", payload)
        self.assertNotIn("top_logprobs", payload)
        self.assertNotIn("secret", opener.call_args.args[0].data.decode())
        self.assertEqual(response.answer, "candidate-0")

    def test_request_cap_and_sanitized_resume_artifact(self):
        provider = OpenRouterBehavioralProvider(
            BehavioralProviderConfig(max_requests=1, min_interval_seconds=0), api_key="secret"
        )
        with patch("apart_incident_response.behavioral_discovery.urllib.request.urlopen",
                   return_value=FakeResponse({"model": "fixture", "choices": [{"message": {"content": "ANSWER: x"}}], "usage": {}})):
            provider.complete("answer", seed=1)
        with self.assertRaises(RuntimeError):
            provider.complete("answer", seed=2)
        with tempfile.TemporaryDirectory() as directory:
            store = BehavioralArtifactStore(Path(directory) / "runs.jsonl")
            self.assertTrue(store.path.parent.stat().st_mode & 0o700)

    def test_retained_failed_pilot_is_not_salvaged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "pilot" / "s0001" / "C1"
            (root / "artifacts").mkdir(parents=True)
            (root / "index.json").write_text(json.dumps({"status": "failed", "agents": {"agent-1": {"status": "budget_exhausted"}}}))
            (root / "artifacts" / "metrics.json").write_text(json.dumps({"submitted_agents": 0, "validator_outcomes": []}))
            (root / "artifacts" / "board_events.jsonl").write_text('{"kind":"board_write"}\n')
            report = audit_retained_pilot(Path(directory) / "pilot")
            self.assertEqual(report["run_count"], 1)
            self.assertEqual(report["behavioral_valid_count"], 0)
            self.assertEqual(report["salvage_decision"], "no_salvage_behavioral_execution_invalid")
            self.assertFalse(report["raw_evidence_rewritten"])


if __name__ == "__main__":
    unittest.main()
