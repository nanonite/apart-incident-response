import json
from pathlib import Path
import unittest


FIXTURES = Path(__file__).parent / "fixtures"


class OpenRouterContractTests(unittest.TestCase):
    def load(self, name: str) -> dict[str, object]:
        payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        self.assertIsInstance(payload, dict)
        return payload

    def test_verified_fixture_contains_sampled_logprob_and_top_alternatives(self):
        payload = self.load("openrouter-chat-completion-logprobs.json")
        self.assertEqual(payload["model"], "openai/gpt-4o-mini")
        choices = payload["choices"]
        self.assertIsInstance(choices, list)
        logprobs = choices[0]["logprobs"]["content"]
        self.assertEqual(len(logprobs), 2)
        for token_record in logprobs:
            alternatives = token_record["top_logprobs"]
            self.assertGreaterEqual(len(alternatives), 1)
            self.assertEqual(token_record["token"], alternatives[0]["token"])
            self.assertIsInstance(token_record["logprob"], float)

    def test_request_fixture_requires_probability_support_and_is_one_shot(self):
        payload = self.load("openrouter-chat-completion-request.json")
        self.assertEqual(payload["model"], "openai/gpt-4o-mini")
        self.assertFalse(payload["stream"])
        self.assertTrue(payload["logprobs"])
        self.assertEqual(payload["top_logprobs"], 5)
        self.assertEqual(payload["provider"]["require_parameters"], True)

    def test_missing_logprobs_fixture_is_explicitly_unavailable(self):
        payload = self.load("openrouter-chat-completion-missing-logprobs.json")
        self.assertIsNone(payload["choices"][0]["logprobs"])

    def test_fixtures_contain_no_credential_fields_or_values(self):
        for path in FIXTURES.glob("openrouter-chat-completion-*.json"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("OPENROUTER_API_KEY", text)
            self.assertNotIn("sk-or-", text)


if __name__ == "__main__":
    unittest.main()
