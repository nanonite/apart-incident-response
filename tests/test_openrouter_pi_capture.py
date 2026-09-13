import json
from pathlib import Path
import unittest


FIXTURES = Path(__file__).parent / "fixtures"


class OpenRouterPiCaptureFixtureTests(unittest.TestCase):
    def load_events(self, name: str) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_text_stream_has_correlated_per_turn_probability_records(self):
        events = self.load_events("pi-openrouter-logprobs-stream.jsonl")
        message = events[-1]["message"]
        capture = message["probabilityCapture"]
        self.assertEqual(capture["status"], "complete")
        self.assertEqual(capture["request_id"], "chatcmpl-logprob-1")
        self.assertEqual(capture["session_id"], "session-7")
        self.assertEqual(len(capture["token_records"]), 2)

    def test_tool_call_stream_preserves_tool_call_and_records_unavailable(self):
        events = self.load_events("pi-openrouter-tool-call-stream.jsonl")
        message = events[-1]["message"]
        self.assertEqual(message["content"][0]["type"], "toolCall")
        self.assertEqual(message["content"][0]["name"], "lookup")
        capture = message["probabilityCapture"]
        self.assertEqual(capture["status"], "unavailable")
        self.assertEqual(capture["token_records"], [])
        self.assertIn("omitted logprobs", capture["missing_data_reason"])

    def test_capture_fixtures_contain_no_credentials(self):
        for path in FIXTURES.glob("pi-openrouter-*-stream.jsonl"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("OPENROUTER_API_KEY", text)
            self.assertNotIn("sk-or-", text)


if __name__ == "__main__":
    unittest.main()
