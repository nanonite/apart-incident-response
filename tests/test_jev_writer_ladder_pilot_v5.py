import json
import re
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_choice_pilot as pilot_v1
from apart_incident_response import jev_choice_v2 as jc2
from apart_incident_response import jev_ling_writer_v5 as writer_v5
from apart_incident_response import jev_writer_ladder_v5 as ladder
from apart_incident_response import jev_writer_ladder_pilot_v5 as pilot
from apart_incident_response import jev_writer_ladder_preregistration_v5 as prv5
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


def _prompt(request):
    return json.loads(request.data)["messages"][0]["content"]


def owned_side_effect(request, timeout=None):
    match = re.search(r"([a-z]+=[A-Za-z0-9_>]+)", _prompt(request))
    return FakeResponse(f"MESSAGE: {match.group(1)}" if match else "SILENCE")


def silence_side_effect(request, timeout=None):
    prompt = _prompt(request)
    if "is_finalizer" in prompt:
        labels = json.loads(prompt)["candidate_labels"]
        return FakeResponse(f"ANSWER: {labels[0]}")
    return FakeResponse("SILENCE")


def empty_side_effect(request, timeout=None):
    return FakeResponse("")


def invalid_answer_side_effect(request, timeout=None):
    prompt = _prompt(request)
    if "is_finalizer" in prompt:
        return FakeResponse("ANSWER: invented-candidate")
    return FakeResponse("SILENCE")


def error_side_effect(request, timeout=None):
    raise urllib.error.HTTPError("https://openrouter.ai/api/v1/chat/completions", 429, "e", {}, None)


def setup(side_effect, *, receiver_cap=216, writer_cap=220):
    instances = pilot.ladder_instances()
    receiver = jc2.JevChoiceAdapterV2(FakeReceiverClient(max_physical_requests=receiver_cap),
                                      model=pr.JEV_REPLAY_MODEL)
    plan = pilot.build_ladder_plan(instances, REGISTRATION, receiver)
    clock = FakeClock()
    writer = writer_v5.LingWriterClientV5(api_key=KEY, max_physical_requests=writer_cap,
                                          clock=clock.now, sleep_fn=clock.sleep)
    verification = pilot.verify_ladder_preflight(plan, REGISTRATION, receiver, writer,
                                                 repo_root=REPO_ROOT, pinned_hash=PIN,
                                                 ling_key_present=True)
    return instances, receiver, plan, verification, writer, side_effect, clock


def run(side_effect, *, approval="test", **kwargs):
    instances, receiver, plan, verification, writer, se, clock = setup(side_effect, **kwargs)
    with patch.object(writer_v5.urllib.request, "urlopen", side_effect=se):
        report = pilot.execute_ladder(plan, receiver, writer, verification, instances,
                                      approval=approval, pinned_hash=PIN, sleep_fn=lambda _: None)
    return report, receiver, writer, clock


class PlanTests(unittest.TestCase):
    def test_plan_separates_cases_and_provider_calls(self):
        instances = pilot.ladder_instances()
        receiver = jc2.JevChoiceAdapterV2(FakeReceiverClient(), model=pr.JEV_REPLAY_MODEL)
        plan = pilot.build_ladder_plan(instances, REGISTRATION, receiver)
        self.assertEqual(len(plan.cases), 204)
        self.assertEqual(plan.planned_cases, 204)
        self.assertEqual(plan.planned_provider_calls, 408)
        self.assertEqual(len({case.rung_id for case in plan.cases}), 6)  # L4X is the bridge, not here
        self.assertEqual(len({case.prompt_form_id for case in plan.cases}), 6)

    def test_preflight_ok_and_zero_calls(self):
        instances, receiver, plan, verification, writer, se, clock = setup(owned_side_effect)
        self.assertTrue(verification["ok"], verification["failed"])
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(writer.physical_attempts, 0)

    def test_frozen_planned_counts_not_incremented(self):
        report, *_ = run(owned_side_effect)
        for rid in ("L0", "L1", "L2", "L3", "L4", "L5"):
            self.assertEqual(report["by_rung"][rid]["planned_cases"], 34)
            self.assertEqual(report["by_rung"][rid]["planned_provider_calls"], 68)


class GatingTests(unittest.TestCase):
    def test_absent_approval_zero_calls(self):
        report, receiver, writer, clock = run(owned_side_effect, approval=None)
        self.assertEqual(report["stop_reason"], "missing_approval")
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(writer.physical_attempts, 0)

    def test_failed_preflight_zero_calls(self):
        instances, receiver, plan, _, writer, se, clock = setup(owned_side_effect)
        report = pilot.execute_ladder(plan, receiver, writer, {"ok": False}, instances, approval="test")
        self.assertEqual(report["stop_reason"], "preflight_failed")
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(writer.physical_attempts, 0)

    def test_overwrite_refused_for_journal_and_report(self):
        for name in ("journal", "report"):
            instances, receiver, plan, verification, writer, se, clock = setup(owned_side_effect)
            with tempfile.TemporaryDirectory() as directory:
                journal = Path(directory) / "ladder.jsonl"
                report_path = Path(directory) / "report.json"
                (journal if name == "journal" else report_path).write_text("{}")
                blocked = pilot.execute_ladder(plan, receiver, writer, verification, instances,
                                               approval="test", pinned_hash=PIN, journal_path=journal,
                                               report_path=report_path)
                self.assertEqual(blocked["stop_reason"],
                                 "output_exists" if name == "journal" else "report_exists")
                self.assertEqual(receiver.client.calls, 0)


class WriterInvalidTests(unittest.TestCase):
    def test_empty_output_stops_before_jev_and_is_not_valid(self):
        report, receiver, writer, clock = run(empty_side_effect)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "empty_output")
        self.assertEqual(receiver.client.calls, 0)  # Jev never called for the invalid case
        row = report["cases"][0]
        self.assertEqual(row["writer_outcome"], "empty_output")
        self.assertFalse(row["receiver_attempted"])
        self.assertIsNone(row["receiver_status"])
        l0 = report["by_rung"]["L0"]
        self.assertEqual(l0["attempted_cases"], 1)
        self.assertEqual(l0["writer_invalid"], 1)
        self.assertEqual(l0["receiver_valid"], 0)
        self.assertEqual(l0["receiver_unattempted"], 1)
        self.assertEqual(l0["joint_valid"], 0)

    def test_invalid_answer_stops_before_jev(self):
        report, receiver, writer, clock = run(invalid_answer_side_effect)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "invalid_answer")
        row = report["cases"][-1]
        self.assertEqual(row["rung_id"], "L4")
        self.assertFalse(row["receiver_attempted"])

    def test_terminal_429_stops_before_jev(self):
        report, receiver, writer, clock = run(error_side_effect)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "writer_http_429_rate_limited")
        self.assertEqual(report["by_rung"]["L0"]["writer_outcomes"]["COMM"]["writer_error"], 1)
        self.assertFalse(report["cases"][0]["receiver_attempted"])


class ExecutionTests(unittest.TestCase):
    def test_owned_run_passes_l5_gate_and_control_never_writes(self):
        report, receiver, writer, clock = run(owned_side_effect)
        self.assertEqual(report["status"], "completed")
        self.assertTrue(report["l5_gate_passed"])
        self.assertTrue(report["voluntary_interpretation_emitted"])
        for rid in ("L0", "L1", "L2", "L3", "L4", "L5"):
            row = report["by_rung"][rid]
            self.assertEqual(row["writer_valid"], 34)
            self.assertEqual(row["writer_invalid"], 0)
            self.assertEqual(row["receiver_valid"], 34)
            self.assertEqual(row["joint_valid"], 34)
            self.assertEqual(row["distinct_forms"], 6)
            self.assertEqual(row["writer_outcomes"]["COMM"]["message_candidate"], 17)
        control = [row for row in report["cases"] if row["arm"] == "COMM_CONTROL"]
        self.assertTrue(all(row["write_status"] == "control_no_write" for row in control))
        self.assertTrue(all(row["board_log"] == [] for row in control))
        self.assertTrue(all(not row["eligible_exposure"] for row in control))

    def test_all_silence_fails_l5_gate_and_is_inconclusive(self):
        report, receiver, writer, clock = run(silence_side_effect)
        self.assertEqual(report["status"], "inconclusive")
        self.assertEqual(report["stop_reason"], "l5_gate_failed")
        self.assertFalse(report["l5_gate_passed"])
        self.assertFalse(report["voluntary_interpretation_emitted"])
        for rid in ("L0", "L1", "L2", "L3", "L4"):
            self.assertEqual(report["by_rung"][rid]["writer_outcomes"]["COMM"]["deliberate_silence"], 17)

    def test_l5_gate_enforced_when_l5_silent_but_others_write(self):
        # Owned everywhere except L5, which returns ANSWER/silence -> gate fails.
        def side_effect(request, timeout=None):
            prompt = _prompt(request)
            if "INDUCED" in prompt:
                return FakeResponse("SILENCE")
            return owned_side_effect(request, timeout)
        report, receiver, writer, clock = run(side_effect)
        self.assertEqual(report["status"], "inconclusive")
        self.assertEqual(report["stop_reason"], "l5_gate_failed")
        self.assertEqual(report["by_rung"]["L5"]["writer_outcomes"]["COMM"]["deliberate_silence"], 17)

    def test_denominators_and_tokens_separated(self):
        report, receiver, writer, clock = run(owned_side_effect)
        self.assertEqual(report["attempted_cases"], 204)
        self.assertEqual(report["physical_attempts"], receiver.client.physical_attempts + writer.physical_attempts)
        self.assertLessEqual(report["provider_attempts"]["jev"], plan_cap(report, "jev"))
        self.assertLessEqual(report["provider_attempts"]["ling"], plan_cap(report, "ling"))
        l0 = report["by_rung"]["L0"]
        self.assertGreater(l0["ling_input_tokens"], 0)
        self.assertGreater(l0["jev_input_tokens"], 0)
        self.assertGreater(l0["estimated_cost_usd"], 0.0)

    def test_no_credentials_or_raw_bodies(self):
        report, receiver, writer, clock = run(owned_side_effect)
        serialized = json.dumps(report, allow_nan=False)
        self.assertNotIn(KEY, serialized)
        self.assertFalse(report["raw_response_retained"])
        self.assertFalse(report["credentials_retained"])

    def test_journal_durable(self):
        instances, receiver, plan, verification, writer, se, clock = setup(owned_side_effect)
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "ladder.jsonl"
            with patch.object(writer_v5.urllib.request, "urlopen", side_effect=se):
                report = pilot.execute_ladder(plan, receiver, writer, verification, instances,
                                              approval="test", pinned_hash=PIN, journal_path=journal,
                                              sleep_fn=lambda _: None)
            self.assertEqual(report["status"], "completed")
            self.assertEqual(len(journal.read_text().splitlines()), 204)


def plan_cap(report, provider):
    return report["provider_attempts"][f"{provider}_partition"]


if __name__ == "__main__":
    unittest.main()
