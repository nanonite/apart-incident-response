import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apart_incident_response.reasoning_baseline import (
    DEFAULT_FREE_MODEL, BaselineResponse, BaselineRunner, OpenRouterFreeProvider,
    default_cases, main,
)


class FakeProvider:
    model = DEFAULT_FREE_MODEL

    def __init__(self, responses):
        self.responses = responses

    def complete(self, prompt, *, max_tokens, seed):
        return self.responses[seed]


class ReasoningBaselineTests(unittest.TestCase):
    def test_default_cases_cover_a_useful_reasoning_floor(self):
        cases = default_cases()
        self.assertEqual([case.level for case in cases], ["low", "medium", "high"])
        report = BaselineRunner(FakeProvider([
            BaselineResponse("ANSWER: 27", DEFAULT_FREE_MODEL),
            BaselineResponse("ANSWER: 11:00", DEFAULT_FREE_MODEL),
            BaselineResponse("ANSWER: approve", DEFAULT_FREE_MODEL),
        ])).run(cases)
        self.assertEqual(report["valid_runs"], 3)
        self.assertEqual(report["accuracy"], 1.0)
        self.assertFalse(report["scientific_battery_evidence"])

    def test_invalid_and_missing_logprob_rows_are_retained(self):
        report = BaselineRunner(FakeProvider([
            BaselineResponse("", DEFAULT_FREE_MODEL, status="unavailable", error="missing"),
            BaselineResponse("nonsense", DEFAULT_FREE_MODEL),
            BaselineResponse("ANSWER: approve", DEFAULT_FREE_MODEL, logprobs=({"token": "x", "logprob": 0.0,
                                                                                  "top_logprobs": [{"token": "x", "logprob": 0.0}]},), usage={"completion_tokens": 4}),
        ])).run()
        self.assertEqual(report["requests_made"], 3)
        self.assertEqual(report["invalid_runs"], 1)
        self.assertIsNone(report["rows"][0]["correct"])
        self.assertEqual(report["rows"][2]["logprob_token_count"], 1)
        self.assertEqual(report["rows"][2]["logprob_status"], "records_present_visible_coverage_unknown")
        self.assertEqual(report["rows"][2]["topk_mass_coverage"], 1.0)
        self.assertFalse(report["raw_responses_retained"])

    def test_provider_requires_free_slug_and_missing_key_is_explicit(self):
        with self.assertRaises(ValueError):
            OpenRouterFreeProvider("openai/gpt-4o-mini")
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "", "OPEN_ROUTER_API_KEY": ""}, clear=False):
            response = OpenRouterFreeProvider(api_key="").complete("test", max_tokens=8, seed=0)
        self.assertEqual(response.status, "unavailable")

    def test_cli_without_live_is_zero_cost_plan_only(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "baseline.json"
            self.assertEqual(main(["--output", str(output)]), 0)
            report = json.loads(output.read_text())
            self.assertEqual(report["status"], "not_run")
            self.assertEqual(report["estimated_cost_usd"], 0.0)


if __name__ == "__main__":
    unittest.main()
