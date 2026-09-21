import json
import unittest
import urllib.error
from unittest.mock import patch

from apart_incident_response import jev_ling_writer_v3 as w
from apart_incident_response.jev_choice_pilot import WriterError


KEY = "openrouter-test-key-0123456789"


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.t = start
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, delay: float) -> None:
        self.sleeps.append(round(delay, 9))
        self.t += delay

    def advance(self, seconds: float) -> None:
        self.t += seconds


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


def success():
    return FakeResponse({"choices": [{"message": {"content": "MESSAGE: precedes=x"}}]})


def http_error(status, headers=None):
    return urllib.error.HTTPError("https://openrouter.ai/api/v1/chat/completions", status, "e",
                                  headers or {}, None)


def writer(clock, **kwargs):
    return w.LingWriterClientV3(api_key=KEY, clock=clock.now, sleep_fn=clock.sleep, **kwargs)


class PacingTests(unittest.TestCase):
    def test_successive_logical_calls_are_spaced(self):
        clock = FakeClock()
        client = writer(clock)
        with patch.object(w.urllib.request, "urlopen", return_value=success()):
            client.write({"private_clues": ["a"]})
            self.assertEqual(clock.sleeps, [])
            client.write({"private_clues": ["b"]})
        self.assertEqual(clock.sleeps, [w.LING_MIN_ATTEMPT_INTERVAL_SECONDS])

    def test_no_sleep_when_enough_time_has_elapsed(self):
        clock = FakeClock()
        client = writer(clock)
        with patch.object(w.urllib.request, "urlopen", return_value=success()):
            client.write({"private_clues": ["a"]})
            clock.advance(w.LING_MIN_ATTEMPT_INTERVAL_SECONDS + 0.5)
            client.write({"private_clues": ["b"]})
        self.assertEqual(clock.sleeps, [])

    def test_retries_are_spaced(self):
        clock = FakeClock()
        client = writer(clock)
        with patch.object(w.urllib.request, "urlopen", side_effect=[http_error(429), success()]):
            client.write({"private_clues": ["a"]})
        self.assertEqual(clock.sleeps, [w.LING_MIN_ATTEMPT_INTERVAL_SECONDS])
        self.assertEqual(client.physical_attempts, 2)

    def test_remaining_wait_uses_previous_attempt_start(self):
        clock = FakeClock()
        client = writer(clock)
        with patch.object(w.urllib.request, "urlopen", return_value=success()):
            client.write({"private_clues": ["a"]})
            clock.advance(2.0)
            client.write({"private_clues": ["b"]})
        self.assertAlmostEqual(clock.sleeps[0], w.LING_MIN_ATTEMPT_INTERVAL_SECONDS - 2.0, places=9)


class RetryHeaderTests(unittest.TestCase):
    def run_retry(self, headers):
        clock = FakeClock()
        client = writer(clock)
        with patch.object(w.urllib.request, "urlopen", side_effect=[http_error(429, headers), success()]):
            client.write({"private_clues": ["a"]})
        return clock, client

    def test_numeric_retry_after_dominates(self):
        clock, client = self.run_retry({"Retry-After": "5.0"})
        self.assertEqual(clock.sleeps, [5.0])
        record = client.rate_limit_diagnostics()[0]
        self.assertTrue(record["retry_after_present"])
        self.assertTrue(record["retry_after_valid"])
        self.assertEqual(record["status"], 429)

    def test_numeric_retry_after_ms_dominates_when_larger_than_interval(self):
        clock, _ = self.run_retry({"retry-after-ms": "4000"})
        self.assertEqual(clock.sleeps, [4.0])

    def test_small_retry_after_ms_falls_back_to_interval(self):
        clock, client = self.run_retry({"retry-after-ms": "2500"})
        self.assertEqual(clock.sleeps, [w.LING_MIN_ATTEMPT_INTERVAL_SECONDS])
        record = client.rate_limit_diagnostics()[0]
        self.assertTrue(record["retry_after_ms_present"])
        self.assertTrue(record["retry_after_ms_valid"])

    def test_header_lookup_is_case_insensitive(self):
        clock, _ = self.run_retry({"retry-after": "4.0"})
        self.assertEqual(clock.sleeps, [4.0])

    def test_malformed_negative_nonfinite_and_excessive_are_ignored(self):
        for headers in ({"Retry-After": "not-a-date"}, {"Retry-After": "-5"}, {"Retry-After": "inf"},
                        {"Retry-After": "nan"}, {"Retry-After": "9999"}, {}):
            with self.subTest(headers=headers):
                clock, client = self.run_retry(headers)
                self.assertEqual(clock.sleeps, [w.LING_MIN_ATTEMPT_INTERVAL_SECONDS])
                record = client.rate_limit_diagnostics()[0]
                if headers:
                    self.assertTrue(record["retry_after_present"])
                    self.assertFalse(record["retry_after_valid"])

    def test_max_of_interval_backoff_and_server_delay(self):
        clock = FakeClock()
        client = writer(clock, min_attempt_interval_seconds=1.0)
        client._last_attempt_start = clock.now()
        delay, source, sources = client._delay(1, None)  # backoff 1.0, interval 1.0 -> tie resolved
        self.assertEqual(delay, 1.0)
        delay, source, sources = client._delay(2, None)  # backoff 2.0 beats interval 1.0
        self.assertEqual((delay, source), (2.0, "backoff"))
        delay, source, sources = client._delay(1, 5.0)   # server delay beats interval and backoff
        self.assertEqual((delay, source), (5.0, "server_requested"))
        self.assertEqual(sorted(sources), ["backoff", "min_interval", "server_requested"])

    def test_server_delay_above_bound_is_ignored(self):
        clock, client = self.run_retry({"Retry-After": str(w.LING_MAX_SERVER_REQUESTED_DELAY_SECONDS + 1)})
        self.assertEqual(clock.sleeps, [w.LING_MIN_ATTEMPT_INTERVAL_SECONDS])
        self.assertFalse(client.rate_limit_diagnostics()[0]["retry_after_valid"])


class FailureTests(unittest.TestCase):
    def test_terminal_429_is_durable_and_stops(self):
        clock = FakeClock()
        client = writer(clock)
        with patch.object(w.urllib.request, "urlopen",
                          side_effect=[http_error(429), http_error(429), http_error(429)]):
            with self.assertRaises(WriterError) as caught:
                client.write({"private_clues": ["a"]})
        self.assertEqual(caught.exception.error_class, "writer_http_429_rate_limited")
        self.assertEqual(client.physical_attempts, 3)
        self.assertEqual(len(client.rate_limit_diagnostics()), 3)
        self.assertEqual([record["retry_ordinal"] for record in client.rate_limit_diagnostics()], [0, 1, 2])
        self.assertEqual(client.last_call_diagnostics[-1]["error_class"], "writer_http_429_rate_limited")

    def test_physical_attempt_cap_exhaustion(self):
        clock = FakeClock()
        client = writer(clock, max_physical_requests=1)
        with patch.object(w.urllib.request, "urlopen", side_effect=[http_error(429), success()]):
            with self.assertRaises(WriterError) as caught:
                client.write({"private_clues": ["a"]})
        self.assertEqual(caught.exception.error_class, "writer_physical_request_cap_exhausted")
        self.assertEqual(client.physical_attempts, 1)

    def test_missing_credentials(self):
        clock = FakeClock()
        client = w.LingWriterClientV3(api_key="", clock=clock.now, sleep_fn=clock.sleep)
        with self.assertRaises(WriterError) as caught:
            client.write({"private_clues": ["a"]})
        self.assertEqual(caught.exception.error_class, "writer_missing_credentials")
        self.assertEqual(client.physical_attempts, 0)


class ProvenanceTests(unittest.TestCase):
    def test_provenance_is_sanitized_and_json_safe(self):
        clock = FakeClock()
        client = writer(clock)
        with patch.object(w.urllib.request, "urlopen", side_effect=[http_error(429, {"Retry-After": "5.0"}),
                                                                    success()]):
            client.write({"private_clues": ["a"]})
        diagnostics = client.rate_limit_diagnostics()
        for record in diagnostics:
            self.assertTrue(set(record) <= set(w.LING_PROVENANCE_FIELDS), set(record))
        json.dumps(diagnostics, allow_nan=False)

    def test_no_credentials_headers_or_bodies_retained(self):
        clock = FakeClock()
        client = writer(clock)
        marker = "SECRET-HEADER-VALUE-xyz"
        with patch.object(w.urllib.request, "urlopen",
                          side_effect=[http_error(429, {"X-Provider-Trace": marker, "Retry-After": "4.0"}),
                                       success()]):
            client.write({"private_clues": ["a"]})
        serialized = json.dumps(client.rate_limit_diagnostics(), allow_nan=False)
        self.assertNotIn(KEY, serialized)
        self.assertNotIn(marker, serialized)
        self.assertNotIn("authorization", serialized.lower())
        self.assertNotIn("messages", serialized)

    def test_transport_spec_is_frozen_and_hashable(self):
        spec = w.writer_transport_spec()
        self.assertEqual(spec["writer_transport_version"], w.LING_WRITER_TRANSPORT_VERSION)
        self.assertEqual(spec["min_attempt_interval_seconds"], 3.25)
        self.assertEqual(spec["max_server_requested_delay_seconds"], 10.0)
        self.assertEqual(spec["supported_retry_headers"], ["retry-after", "retry-after-ms"])
        self.assertEqual(spec["max_retries"], 2)
        self.assertFalse(spec["retains_response_bodies"])
        json.dumps(spec, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
