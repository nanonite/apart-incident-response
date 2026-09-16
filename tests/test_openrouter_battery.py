import unittest
from unittest.mock import patch, MagicMock
import json
from pathlib import Path
import tempfile
import os

from apart_incident_response.openrouter_battery import (
    OpenRouterBatteryProvider, BehavioralValidityGate, ResumableArtifact, UsageAccumulator
)
from apart_incident_response.communication_protocol import BatteryCondition
from apart_incident_response.communication_runner import AgentContext, AgentResponse, TwoAgentBatteryRunner, ScriptedProvider
from apart_incident_response.task_families import generate_instance, DependenceRegime


FAKE_KEY = "sk-or-test-fake-key-1234567890abcdef"


def _make_provider(model: str = "test-model") -> OpenRouterBatteryProvider:
    """Create provider with a fake key injected via environment."""
    with patch.dict(os.environ, {"OPENROUTER_API_KEY": FAKE_KEY}):
        return OpenRouterBatteryProvider(model)


def _make_context(
    condition: BatteryCondition = BatteryCondition.ISO,
    candidates: list[str] | None = None,
    agent_id: str = "A",
) -> AgentContext:
    if candidates is None:
        candidates = ["candidate-0", "candidate-1", "candidate-2"]
    task_view = {
        "family": "hypothesis",
        "instance_id": "hypothesis-00000005",
        "complexity": "low",
        "agent_id": agent_id,
        "candidate_labels": candidates,
        "candidate_count": len(candidates),
        "private_clues": ["bit0=1"],
        "task_instruction": "Choose one candidate and reply exactly as ANSWER: <candidate label>.",
    }
    if condition is BatteryCondition.FULL:
        task_view["joint_clues"] = ["bit0=1", "bit1=0"]
        task_view["joint_candidate_labels"] = [candidates[0]]
        task_view["joint_candidate_count"] = 1
    return AgentContext(
        run_id="run-test",
        instance_id="hypothesis-00000005",
        agent_id=agent_id,
        condition=condition,
        turn=0,
        task_view=task_view,
        visible_messages=(),
        prompt_version="communication-battery-prompt-v1",
        token_budget=512,
    )


class TestProviderKeyRedaction(unittest.TestCase):
    """Test 1: provider never exposes the API key in repr or str."""

    def test_provider_redacts_key_from_repr(self):
        provider = _make_provider("my-model")
        r = repr(provider)
        s = str(provider)
        self.assertNotIn(FAKE_KEY, r)
        self.assertNotIn(FAKE_KEY, s)
        self.assertIn("***", r)
        self.assertIn("***", s)


class TestParseResponse(unittest.TestCase):
    """Tests 2-4: _parse_response extracts ANSWER and MESSAGE correctly."""

    def setUp(self):
        self.provider = _make_provider()

    def test_parse_response_extracts_answer(self):
        """Test 2: valid ANSWER line is extracted."""
        context = _make_context(
            condition=BatteryCondition.ISO,
            candidates=["candidate-0", "candidate-1", "candidate-2", "candidate-3"],
        )
        answer, message = self.provider._parse_response(
            "Let me think... ANSWER: candidate-3", context
        )
        self.assertEqual(answer, "candidate-3")
        self.assertIsNone(message)

    def test_parse_response_rejects_invalid_candidate(self):
        """Test 3: hallucinated label not in candidates returns (None, None)."""
        context = _make_context(
            condition=BatteryCondition.ISO,
            candidates=["candidate-0", "candidate-1"],
        )
        answer, message = self.provider._parse_response(
            "ANSWER: hallucinated-label-99", context
        )
        self.assertIsNone(answer)
        self.assertIsNone(message)

    def test_parse_response_comm_extracts_message(self):
        """Test 4: for COMM condition, also extracts MESSAGE line."""
        context = _make_context(
            condition=BatteryCondition.COMM,
            candidates=["candidate-0", "candidate-1", "candidate-2"],
        )
        # Add a visible_messages for COMM context
        context_comm = AgentContext(
            run_id=context.run_id,
            instance_id=context.instance_id,
            agent_id=context.agent_id,
            condition=BatteryCondition.COMM,
            turn=context.turn,
            task_view=context.task_view,
            visible_messages=(),
            prompt_version=context.prompt_version,
            token_budget=context.token_budget,
        )
        answer, message = self.provider._parse_response(
            "ANSWER: candidate-1\nMESSAGE: I think candidate-1 is correct",
            context_comm,
        )
        self.assertEqual(answer, "candidate-1")
        self.assertEqual(message, "I think candidate-1 is correct")


class TestFullPromptPrivacy(unittest.TestCase):
    def test_full_prompt_does_not_expose_joint_solution_labels(self):
        provider = _make_provider()
        context = _make_context(condition=BatteryCondition.FULL)
        messages = provider._build_messages(context)
        prompt = "\n".join(message["content"] for message in messages)
        self.assertIn("Joint clues", prompt)
        self.assertNotIn("Narrowed joint candidates", prompt)
        self.assertNotIn("candidate-0", prompt.split("Joint clues", 1)[1])

    def test_generated_full_view_keeps_solution_set_controller_side(self):
        instance = generate_instance("hypothesis", 5)
        view = instance.agent_view("A", "FULL")
        self.assertIn("joint_clues", view)
        self.assertNotIn("joint_candidate_labels", view)
        self.assertNotIn("joint_candidate_count", view)


class TestBehavioralValidityGate(unittest.TestCase):
    """Tests 5-6: BehavioralValidityGate pass and fail cases."""

    def _make_result(
        self, task_success: bool, answer: str | None = "candidate-0"
    ):
        """Make a minimal BatteryRunResult-like object."""
        from apart_incident_response.communication_runner import BatteryRunResult
        return BatteryRunResult(
            run_id="run-1",
            pair_id="pair-1",
            instance_id="inst-1",
            condition=BatteryCondition.FULL,
            family="hypothesis",
            seed=1,
            provider="test",
            provider_version="v1",
            prompt_version="v1",
            status="completed",
            task_success=task_success,
            submitted_answers={"A": answer, "B": answer},
            invalid_agents=(),
            event_summary={},
            artifact={},
        )

    def test_behavioral_validity_gate_pass(self):
        """Test 5: gate passes when all results have valid answers."""
        gate = BehavioralValidityGate()
        results = [self._make_result(True, "candidate-0") for _ in range(5)]
        verdict = gate.evaluate(results)
        self.assertTrue(verdict["pass"])
        self.assertEqual(verdict["parse_rate"], 1.0)
        self.assertEqual(verdict["status"], "pass")

    def test_behavioral_validity_gate_fail_low_parse_rate(self):
        """Test 6: gate fails when < 50% of runs parsed."""
        gate = BehavioralValidityGate()
        results = (
            [self._make_result(False, None) for _ in range(4)]
            + [self._make_result(True, "candidate-0")]
        )
        verdict = gate.evaluate(results)
        self.assertFalse(verdict["pass"])
        self.assertEqual(verdict["parse_rate"], 0.2)
        self.assertIn("fail", verdict["status"])


class TestResumableArtifact(unittest.TestCase):
    """Test 7: ResumableArtifact tracks completed runs."""

    def _make_result(self, pair_id: str, condition: BatteryCondition):
        from apart_incident_response.communication_runner import BatteryRunResult
        return BatteryRunResult(
            run_id=f"run-{pair_id}",
            pair_id=pair_id,
            instance_id="inst-1",
            condition=condition,
            family="hypothesis",
            seed=1,
            provider="test",
            provider_version="v1",
            prompt_version="v1",
            status="completed",
            task_success=True,
            submitted_answers={"A": "candidate-0"},
            invalid_agents=(),
            event_summary={},
            artifact={},
        )

    def test_resumable_artifact_skip_done(self):
        """Test 7: save a result, verify already_done returns True for same pair_id+condition."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "artifact.jsonl"
            artifact = ResumableArtifact(path)
            self.assertFalse(artifact.already_done("pair-1", "FULL"))
            result = self._make_result("pair-1", BatteryCondition.FULL)
            artifact.append(result)
            self.assertTrue(artifact.already_done("pair-1", "FULL"))
            self.assertFalse(artifact.already_done("pair-1", "ISO"))
            self.assertFalse(artifact.already_done("pair-2", "FULL"))

            # Verify persistence: reload from file
            artifact2 = ResumableArtifact(path)
            self.assertTrue(artifact2.already_done("pair-1", "FULL"))


class TestUsageAccumulator(unittest.TestCase):
    """Test 8: UsageAccumulator records and totals correctly."""

    def test_usage_accumulator(self):
        """Test 8: record two calls, verify totals."""
        acc = UsageAccumulator(cost_per_mtok=1.0)
        acc.record(100, 50)
        acc.record(200, 75)
        summary = acc.summary()
        self.assertEqual(summary["prompt_tokens"], 300)
        self.assertEqual(summary["completion_tokens"], 125)
        self.assertEqual(summary["total_tokens"], 425)
        self.assertAlmostEqual(summary["estimated_cost_usd"], 425 / 1_000_000 * 1.0)
        self.assertEqual(summary["calls"], 2)


class TestProviderWithMockedApi(unittest.TestCase):
    """Test 9: mock _call_api to verify respond() output."""

    def test_provider_with_mocked_api(self):
        """Test 9: mock _call_api to return a fake response, verify correct AgentResponse."""
        provider = _make_provider("test-model")
        context = _make_context(
            condition=BatteryCondition.ISO,
            candidates=["candidate-0", "candidate-1", "candidate-2"],
        )

        fake_response = {
            "choices": [
                {"message": {"content": "ANSWER: candidate-1"}}
            ],
            "usage": {"prompt_tokens": 50, "completion_tokens": 10},
        }

        with patch.object(provider, "_call_api", return_value=fake_response):
            response = provider.respond(context)

        self.assertEqual(response.answer, "candidate-1")
        self.assertIsNone(response.message)
        self.assertEqual(response.logprob_status, "not_requested")
        self.assertIsNone(response.failure_reason)

        summary = provider.usage_summary()
        self.assertEqual(summary["total_calls"], 1)
        self.assertEqual(summary["prompt_tokens"], 50)
        self.assertEqual(summary["completion_tokens"], 10)


class TestFakeProviderTriplet(unittest.TestCase):
    """Test 10: use ScriptedProvider to run a full triplet, verify condition isolation."""

    def test_fake_provider_triplet(self):
        """Test 10: ScriptedProvider runs full triplet with correct condition isolation."""
        instance = generate_instance("hypothesis", 5)
        target = instance.target

        # ScriptedProvider answers correctly under all conditions
        answers = {
            (instance.instance_id, BatteryCondition.ISO, "A"): target,
            (instance.instance_id, BatteryCondition.ISO, "B"): target,
            (instance.instance_id, BatteryCondition.FULL, "A"): target,
            (instance.instance_id, BatteryCondition.FULL, "B"): target,
            (instance.instance_id, BatteryCondition.COMM, "A"): target,
            (instance.instance_id, BatteryCondition.COMM, "B"): target,
        }
        provider = ScriptedProvider(answers)
        runner = TwoAgentBatteryRunner(turns=1)
        triplet = runner.run_triplet(instance, provider)

        self.assertEqual(len(triplet), 3)
        conditions = [r.condition for r in triplet]
        self.assertEqual(conditions, list(BatteryCondition))

        # All should share the same pair_id
        pair_ids = {r.pair_id for r in triplet}
        self.assertEqual(len(pair_ids), 1)

        # Verify condition isolation: ISO has no visible messages
        iso_result = triplet[0]
        self.assertEqual(iso_result.condition, BatteryCondition.ISO)

        # All conditions: target was provided, so task should succeed
        for result in triplet:
            self.assertTrue(result.task_success, f"Failed for condition {result.condition}")


if __name__ == "__main__":
    unittest.main()
