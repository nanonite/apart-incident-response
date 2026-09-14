import unittest

from apart_incident_response.entropy_capability import evaluate_probability_capture


class EntropyCapabilityTests(unittest.TestCase):
    def test_mass_does_not_certify_visible_alignment(self):
        response = {"model": "fixture", "provider": "fixture", "choices": [{"message": {"content": "Paris"}}]}
        records = ({"token": "Paris", "logprob": 0.0, "top_logprobs": [{"token": "Paris", "logprob": 0.0}]},)
        result = evaluate_probability_capture(output_kind="ordinary_text", visible_text="Paris", records=records, response=response)
        self.assertEqual(result["visible_span_alignment"], "aligned")
        self.assertTrue(result["observed_token_partial_entropy_eligible"])
        self.assertFalse(result["exact_entropy_eligible"])
        self.assertGreaterEqual(result["top_k_mass"]["mean"], 0.95)

    def test_missing_tool_records_are_not_eligible(self):
        result = evaluate_probability_capture(output_kind="tool_call_arguments", visible_text=None, records=(), response={"model": "fixture"})
        self.assertEqual(result["status"], "records_missing")
        self.assertFalse(result["observed_token_partial_entropy_eligible"])
        self.assertFalse(result["exact_entropy_eligible"])


if __name__ == "__main__":
    unittest.main()
