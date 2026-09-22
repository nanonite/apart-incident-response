import json
import unittest
import urllib.error
from unittest.mock import patch

from apart_incident_response import jev_ling_writer_v3 as writer_v3
from apart_incident_response import jev_ling_writer_v4 as w4


KEY = "openrouter-test-key-0123456789"
CLUES = ["precedes=deploy>inspect", "budget=valid"]


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.t = start
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, delay: float) -> None:
        self.sleeps.append(round(delay, 9))
        self.t += delay


class FakeResponse:
    def __init__(self, content, finish_reason=None, usage=None):
        body = {"choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
                "usage": usage if usage is not None else {"prompt_tokens": 11, "completion_tokens": 4}}
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


def http_error(status, headers=None):
    return urllib.error.HTTPError("https://openrouter.ai/api/v1/chat/completions", status, "e",
                                  headers or {}, None)


def make_client(clock, **kwargs):
    return w4.LingWriterClientV4(api_key=KEY, clock=clock.now, sleep_fn=clock.sleep, **kwargs)


def context(prompt="p", grammar=w4.GRAMMAR_EXPLICIT_SILENCE, clues=CLUES):
    return {"prompt": prompt, "grammar": grammar, "private_clues": list(clues)}


class ClassifierTests(unittest.TestCase):
    def classify(self, content, finish_reason=None, grammar=w4.GRAMMAR_EXPLICIT_SILENCE, clues=CLUES):
        return w4.classify_writer_completion(content, finish_reason, clues, grammar=grammar)

    def test_exact_silence(self):
        self.assertEqual(self.classify("SILENCE")["outcome"], w4.OUTCOME_DELIBERATE_SILENCE)
        self.assertEqual(self.classify("  SILENCE  ")["outcome"], w4.OUTCOME_DELIBERATE_SILENCE)

    def test_valid_message_and_non_owned(self):
        owned = self.classify("MESSAGE: budget=valid")
        self.assertEqual(owned["outcome"], w4.OUTCOME_MESSAGE_CANDIDATE)
        self.assertEqual(owned["claim"], "budget=valid")
        foreign = self.classify("MESSAGE: invented-clue")
        self.assertEqual(foreign["outcome"], w4.OUTCOME_NON_OWNED_CLAIM)
        self.assertEqual(foreign["claim"], "invented-clue")

    def test_empty_is_never_silence(self):
        self.assertEqual(self.classify("")["outcome"], w4.OUTCOME_EMPTY_OUTPUT)
        self.assertEqual(self.classify("   ")["outcome"], w4.OUTCOME_EMPTY_OUTPUT)

    def test_truncated_is_never_silence(self):
        result = self.classify("MESSAGE: budget=valid", finish_reason="length")
        self.assertEqual(result["outcome"], w4.OUTCOME_TRUNCATED_OUTPUT)
        self.assertIsNone(result["claim"])

    def test_malformed_nonempty(self):
        self.assertEqual(self.classify("random words here")["outcome"], w4.OUTCOME_UNPARSED_OUTPUT)

    def test_original_grammar(self):
        grammar = w4.GRAMMAR_ORIGINAL_LING
        self.assertEqual(self.classify("ANSWER: x MESSAGE: budget=valid", grammar=grammar)["outcome"],
                         w4.OUTCOME_MESSAGE_CANDIDATE)
        self.assertEqual(self.classify("ANSWER: x", grammar=grammar)["outcome"],
                         w4.OUTCOME_DELIBERATE_SILENCE)
        self.assertEqual(self.classify("no grammar at all", grammar=grammar)["outcome"],
                         w4.OUTCOME_UNPARSED_OUTPUT)

    def test_outcomes_are_mutually_exclusive(self):
        self.assertEqual(len(set(w4.WRITER_OUTCOMES)), len(w4.WRITER_OUTCOMES))


class TransportOutcomeTests(unittest.TestCase):
    def test_success_outcome_and_diagnostics(self):
        clock = FakeClock()
        client = make_client(clock)
        with patch.object(w4.urllib.request, "urlopen", return_value=FakeResponse("MESSAGE: budget=valid")):
            outcome = client.write_outcome(context())
        self.assertEqual(outcome["outcome"], w4.OUTCOME_MESSAGE_CANDIDATE)
        self.assertEqual(outcome["claim"], "budget=valid")
        self.assertEqual(outcome["input_tokens"], 11)
        self.assertEqual(outcome["completion_tokens"], 4)
        self.assertEqual(outcome["content_length"], len("MESSAGE: budget=valid"))
        self.assertFalse(outcome["raw_response_retained"])

    def test_empty_and_truncated_via_transport(self):
        clock = FakeClock()
        with patch.object(w4.urllib.request, "urlopen", return_value=FakeResponse("")):
            self.assertEqual(make_client(clock).write_outcome(context())["outcome"], w4.OUTCOME_EMPTY_OUTPUT)
        with patch.object(w4.urllib.request, "urlopen",
                          return_value=FakeResponse("MESSAGE: budget=valid", finish_reason="length")):
            outcome = make_client(FakeClock()).write_outcome(context())
        self.assertEqual(outcome["outcome"], w4.OUTCOME_TRUNCATED_OUTPUT)
        self.assertEqual(outcome["finish_reason"], "length")

    def test_terminal_429_is_durable_writer_error(self):
        clock = FakeClock()
        client = make_client(clock)
        with patch.object(w4.urllib.request, "urlopen",
                          side_effect=[http_error(429), http_error(429), http_error(429)]):
            outcome = client.write_outcome(context())
        self.assertEqual(outcome["outcome"], w4.OUTCOME_WRITER_ERROR)
        self.assertEqual(outcome["error_class"], "writer_http_429_rate_limited")
        self.assertEqual(client.physical_attempts, 3)
        self.assertEqual(len(outcome["diagnostics"]), 3)

    def test_cap_enforcement(self):
        clock = FakeClock()
        client = make_client(clock, max_physical_requests=1)
        with patch.object(w4.urllib.request, "urlopen", side_effect=[http_error(429)]):
            outcome = client.write_outcome(context())
        self.assertEqual(outcome["outcome"], w4.OUTCOME_WRITER_ERROR)
        self.assertEqual(outcome["error_class"], "writer_physical_request_cap_exhausted")
        self.assertEqual(client.physical_attempts, 1)

    def test_pacing_inherited_between_calls(self):
        clock = FakeClock()
        client = make_client(clock)
        with patch.object(w4.urllib.request, "urlopen", return_value=FakeResponse("SILENCE")):
            client.write_outcome(context())
            client.write_outcome(context())
        self.assertEqual(clock.sleeps, [writer_v3.LING_MIN_ATTEMPT_INTERVAL_SECONDS])

    def test_no_credentials_or_raw_bodies_retained(self):
        clock = FakeClock()
        client = make_client(clock)
        marker = "SECRET-HEADER-xyz"
        with patch.object(w4.urllib.request, "urlopen",
                          side_effect=[http_error(429, {"X-Provider": marker, "Retry-After": "4.0"}),
                                       FakeResponse("MESSAGE: budget=valid")]):
            outcome = client.write_outcome(context())
        serialized = json.dumps(outcome, allow_nan=False)
        self.assertNotIn(KEY, serialized)
        self.assertNotIn(marker, serialized)
        self.assertNotIn("authorization", serialized.lower())
        self.assertFalse(outcome["raw_response_retained"])

    def test_write_compatibility_shim(self):
        clock = FakeClock()
        with patch.object(w4.urllib.request, "urlopen", return_value=FakeResponse("MESSAGE: budget=valid")):
            self.assertEqual(make_client(clock).write(context()), {"message": "budget=valid"})
        with patch.object(w4.urllib.request, "urlopen", return_value=FakeResponse("SILENCE")):
            self.assertEqual(make_client(FakeClock()).write(context()), {"message": None})

    def test_schema_hash_stable(self):
        self.assertEqual(w4.writer_schema_hash(), w4.writer_schema_hash())
        self.assertEqual(w4.writer_schema()["writer_outcomes_version"], w4.WRITER_OUTCOMES_VERSION)


if __name__ == "__main__":
    unittest.main()
