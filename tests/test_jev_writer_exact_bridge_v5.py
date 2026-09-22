import json
import re
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_choice_v2 as jc2
from apart_incident_response import jev_ling_writer_v5 as writer_v5
from apart_incident_response import jev_writer_exact_bridge_v5 as bridge
from apart_incident_response import jev_writer_ladder_v5 as ladder
from apart_incident_response import jev_replay_preregistration as pr


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = json.loads((REPO_ROOT / "runs" / "epic-126"
                           / "jev-writer-ladder-preregistration-v5.json").read_text())
PIN = REGISTRATION["preregistration_hash"]
KEY = "openrouter-test-key-0123456789"


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.t += delay


class FakeResponse:
    def __init__(self, content="SILENCE", finish_reason=None):
        body = {"choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3}}
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class FakeReceiverClient:
    provider = "jev"
    endpoint = jc.JEV_SYSTEMONE_ENDPOINT
    max_retries = pr.JEV_REPLAY_MAX_RETRIES

    def __init__(self, *, max_physical_requests=250):
        self.max_physical_requests = max_physical_requests
        self.physical_attempts = 0
        self.calls = 0

    def complete(self, request):
        self.physical_attempts += 1
        self.calls += 1
        question_id = next(iter(request["questions"]))
        option_ids = list(request["questions"][question_id]["criteria"])
        rest = 0.5 / (len(option_ids) - 1)
        probabilities = {option_id: (0.5 if index == 0 else rest)
                         for index, option_id in enumerate(option_ids)}
        return {"model": jc.JEV_DEFAULT_MODEL,
                "answers": {question_id: {"type": "choice", "choice": option_ids[0],
                                          "probabilities": probabilities, "confidence": 0.5}},
                "usage": {"input_tokens": 10, "output_tokens": 2}}


def owned_side_effect(seen=None):
    def respond(request, timeout=None):
        payload = json.loads(request.data)
        if seen is not None:
            seen.append(payload)
        match = re.search(r"([a-z]+=[A-Za-z0-9_>]+)", payload["messages"][0]["content"])
        return FakeResponse(f"MESSAGE: {match.group(1)}" if match else "SILENCE")
    return respond


def empty_side_effect(request, timeout=None):
    return FakeResponse("")


def setup(side_effect):
    instances = bridge.bridge_instances()
    receiver = jc2.JevChoiceAdapterV2(FakeReceiverClient(), model=pr.JEV_REPLAY_MODEL)
    plan = bridge.build_bridge_plan(instances, REGISTRATION)
    clock = FakeClock()
    writer = writer_v5.LingWriterClientV5(api_key=KEY, max_physical_requests=120,
                                          clock=clock.now, sleep_fn=clock.sleep)
    return instances, receiver, plan, writer, side_effect, clock


def run(side_effect, *, approval="test", seen=None, **kwargs):
    instances, receiver, plan, writer, se, clock = setup(side_effect)
    with patch.object(writer_v5.urllib.request, "urlopen", side_effect=se):
        report = bridge.execute_bridge(plan, receiver, writer, instances, approval=approval,
                                       pinned_hash=PIN, **kwargs)
    return report, receiver, writer, clock


class BridgePlanTests(unittest.TestCase):
    def test_plan(self):
        instances, receiver, plan, writer, se, clock = setup(owned_side_effect())
        self.assertEqual(plan.planned_requests, 85)
        self.assertEqual(plan.request_cap, 180)
        self.assertEqual(plan.jev_request_cap, 60)
        self.assertEqual(plan.ling_request_cap, 120)
        self.assertEqual(ladder.EXACT_BRIDGE_TOKEN_BUDGET, 1024)

    def test_absent_approval_zero_calls(self):
        report, receiver, writer, clock = run(owned_side_effect(), approval=None)
        self.assertEqual(report["stop_reason"], "missing_approval")
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(writer.physical_attempts, 0)

    def test_overwrite_refused(self):
        instances, receiver, plan, writer, se, clock = setup(owned_side_effect())
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "report.json"
            report_path.write_text("{}")
            blocked = bridge.execute_bridge(plan, receiver, writer, instances, approval="test",
                                            pinned_hash=PIN, report_path=report_path)
            self.assertEqual(blocked["stop_reason"], "report_exists")
            self.assertEqual(receiver.client.calls, 0)


class BridgeExecutionTests(unittest.TestCase):
    def test_two_agents_two_turns_and_seed_and_budget(self):
        seen = []
        report, receiver, writer, clock = run(owned_side_effect(seen), seen=seen)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["attempted_cases"], 17)
        self.assertGreater(report["writes_by_agent"]["A"], 0)
        self.assertGreater(report["writes_by_agent"]["B"], 0)
        self.assertEqual(report["board_messages"], report["writes_by_agent"]["A"] + report["writes_by_agent"]["B"])
        self.assertEqual(report["token_budget"], 1024)
        # every bridge request carried a deterministic seed and the 1024 budget
        self.assertTrue(seen)
        self.assertTrue(all("seed" in payload for payload in seen))
        self.assertTrue(all(payload["max_tokens"] == 1024 for payload in seen))
        self.assertGreater(report["verified_read_exposures"], 0)
        self.assertGreater(report["i_m_bits"], 0.0)
        self.assertEqual(report["distinct_forms"], 6)

    def test_empty_output_stops_before_receiver(self):
        report, receiver, writer, clock = run(empty_side_effect)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "empty_output")
        self.assertEqual(receiver.client.calls, 0)

    def test_seed_matches_provider_seed(self):
        import hashlib
        instance = bridge.bridge_instances()[0]
        expected = int(hashlib.sha256(f"{instance.instance_id}|COMM|0|A".encode()).hexdigest()[:8], 16) \
            & ((2 ** 31) - 1)
        seen = []
        run(owned_side_effect(seen), seen=seen)
        self.assertEqual(seen[0]["seed"], expected)

    def test_no_credentials_or_raw_bodies(self):
        report, receiver, writer, clock = run(owned_side_effect())
        serialized = json.dumps(report, allow_nan=False)
        self.assertNotIn(KEY, serialized)
        self.assertFalse(report["raw_response_retained"])
        self.assertFalse(report["credentials_retained"])


if __name__ == "__main__":
    unittest.main()
