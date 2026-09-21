import tempfile
import unittest
from pathlib import Path

from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_choice_v2 as jc2
from apart_incident_response import jev_normalization_probe_v2 as probe_mod
from apart_incident_response import jev_replay_preregistration as pr
from apart_incident_response import jev_replay_preregistration_v2 as prv2


REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeProbeClient:
    provider = "jev"
    endpoint = pr.JEV_REPLAY_ENDPOINT
    max_retries = prv2.PROBE_MAX_RETRIES

    def __init__(self, *, total=1.0, max_physical_requests=prv2.PROBE_REQUEST_CAP):
        self.total = total
        self.max_physical_requests = max_physical_requests
        self.physical_attempts = 0
        self.calls = 0

    def complete(self, request):
        if self.max_physical_requests is not None and self.physical_attempts >= self.max_physical_requests:
            raise RuntimeError("physical_request_cap_exhausted")
        self.physical_attempts += 1
        self.calls += 1
        question_id = next(iter(request["questions"]))
        option_ids = list(request["questions"][question_id]["criteria"])
        rest = (self.total - 0.5) / (len(option_ids) - 1)
        probabilities = {option_id: (0.5 if index == 0 else rest)
                         for index, option_id in enumerate(option_ids)}
        return {"model": jc.JEV_DEFAULT_MODEL,
                "answers": {question_id: {"type": "choice", "choice": option_ids[0],
                                          "probabilities": probabilities,
                                          "confidence": 0.5}},
                "usage": {"input_tokens": 10, "output_tokens": 2}}


def setup(*, total=1.0, cap=prv2.PROBE_REQUEST_CAP):
    probe = prv2.build_probe_preregistration()
    adapter = jc2.JevChoiceAdapterV2(FakeProbeClient(total=total, max_physical_requests=cap),
                                     model=pr.JEV_REPLAY_MODEL)
    verification = probe_mod.verify_probe_preflight(adapter, probe=probe, repo_root=REPO_ROOT)
    return probe, adapter, verification


class ProbePreflightTests(unittest.TestCase):
    def test_request_hash_is_the_frozen_control_request(self):
        _, adapter, _ = setup()
        self.assertEqual(probe_mod.probe_state(adapter).request_hash, prv2.PROBE_REQUEST_HASH_FULL)

    def test_preflight_ok_and_zero_calls(self):
        _, adapter, verification = setup()
        self.assertTrue(verification["ok"], verification["failed"])
        self.assertEqual(adapter.client.calls, 0)

    def test_cap_mismatch_fails_closed(self):
        _, _, verification = setup(cap=10)
        self.assertIn("receiver_partition_enforced", verification["failed"])


class ProbeExecutionTests(unittest.TestCase):
    def test_absent_approval_makes_zero_calls(self):
        _, adapter, verification = setup()
        report = probe_mod.execute_probe(adapter, verification, approval=None, k=12)
        self.assertEqual(report["stop_reason"], "missing_approval")
        self.assertEqual(adapter.client.calls, 0)

    def test_failed_preflight_makes_zero_calls(self):
        _, adapter, _ = setup()
        report = probe_mod.execute_probe(adapter, {"ok": False}, approval="test", k=12)
        self.assertEqual(report["stop_reason"], "preflight_failed")
        self.assertEqual(adapter.client.calls, 0)

    def test_records_every_raw_vector_and_rejection_rates(self):
        _, adapter, verification = setup()
        report = probe_mod.execute_probe(adapter, verification, approval="test", k=12)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["attempted"], 12)
        self.assertEqual(len(report["records"]), 12)
        for record in report["records"]:
            self.assertTrue(record["raw_probabilities"])
            self.assertIsNotNone(record["probability_diagnostics"])
        self.assertEqual(set(report["rejection_rates"]), {"1e-06", "0.01", "0.03"})
        self.assertEqual(report["rejection_rates"]["1e-06"], 0.0)
        self.assertFalse(report["independent_prompt_forms"])

    def test_hard_deviation_stops_immediately(self):
        _, adapter, verification = setup(total=1.10)
        report = probe_mod.execute_probe(adapter, verification, approval="test", k=12)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "not_normalized_hard")
        self.assertEqual(report["attempted"], 1)
        self.assertEqual(report["rejection_rates"]["0.03"], 1.0)

    def test_journal_is_durable(self):
        _, adapter, verification = setup()
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "probe.jsonl"
            report = probe_mod.execute_probe(adapter, verification, approval="test", k=12,
                                             journal_path=journal)
            self.assertEqual(report["status"], "completed")
            self.assertEqual(len(journal.read_text().splitlines()), 12)


if __name__ == "__main__":
    unittest.main()
