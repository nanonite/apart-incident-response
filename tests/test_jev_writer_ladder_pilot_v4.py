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
from apart_incident_response import jev_ling_writer_v4 as writer_v4
from apart_incident_response import jev_writer_ladder_v4 as ladder
from apart_incident_response import jev_writer_ladder_pilot_v4 as pilot
from apart_incident_response import jev_writer_ladder_preregistration_v4 as prv4
from apart_incident_response import jev_replay_preregistration as pr


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = prv4.build_writer_ladder_preregistration_v4(approved=True, repo_root=REPO_ROOT)
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


def owned_side_effect(marker=None):
    def respond(request, timeout=None):
        body = json.loads(request.data)
        prompt = body["messages"][0]["content"]
        match = re.search(r"([a-z]+=[A-Za-z0-9_>]+)", prompt)
        content = f"MESSAGE: {match.group(1)}" if match else "SILENCE"
        response = FakeResponse(content)
        if marker:
            response.headers = {"X-Provider": marker}
        return response
    return respond


def silence_side_effect(request, timeout=None):
    body = json.loads(request.data)
    prompt = body["messages"][0]["content"]
    # The original-grammar rung (L4) expresses silence as a valid answer with no
    # MESSAGE line; the explicit-grammar rungs use the SILENCE token.
    if "is_finalizer" in prompt:
        return FakeResponse("ANSWER: stage>inspect>deploy")
    return FakeResponse("SILENCE")


def error_side_effect(request, timeout=None):
    raise urllib.error.HTTPError("https://openrouter.ai/api/v1/chat/completions", 429, "e", {}, None)


def setup(side_effect, *, receiver_cap=250, writer_cap=250, writer=None):
    instances = pilot.ladder_instances()
    receiver = jc2.JevChoiceAdapterV2(FakeReceiverClient(max_physical_requests=receiver_cap),
                                      model=pr.JEV_REPLAY_MODEL)
    plan = pilot.build_ladder_plan(instances, REGISTRATION, receiver)
    clock = FakeClock()
    used_writer = writer or writer_v4.LingWriterClientV4(api_key=KEY, max_physical_requests=writer_cap,
                                                         clock=clock.now, sleep_fn=clock.sleep)
    verification = pilot.verify_ladder_preflight(plan, REGISTRATION, receiver, used_writer,
                                                 repo_root=REPO_ROOT, pinned_hash=PIN,
                                                 ling_key_present=True)
    return instances, receiver, plan, verification, used_writer, side_effect, clock


def run(side_effect, *, approval="test", **kwargs):
    instances, receiver, plan, verification, writer, se, clock = setup(side_effect, **kwargs)
    with patch.object(writer_v4.urllib.request, "urlopen", side_effect=se):
        report = pilot.execute_ladder(plan, receiver, writer, verification, instances,
                                      approval=approval, pinned_hash=PIN, sleep_fn=lambda _: None)
    return report, receiver, writer, clock, plan, verification


class PlanTests(unittest.TestCase):
    def test_plan_counts(self):
        instances = pilot.ladder_instances()
        receiver = jc2.JevChoiceAdapterV2(FakeReceiverClient(), model=pr.JEV_REPLAY_MODEL)
        plan = pilot.build_ladder_plan(instances, REGISTRATION, receiver)
        self.assertEqual(len(plan.cases), 204)
        self.assertEqual(plan.planned_requests, 408)
        self.assertEqual(len({case.prompt_form_id for case in plan.cases}), 6)
        self.assertEqual(len({case.rung_id for case in plan.cases}), 6)

    def test_preflight_ok_zero_calls(self):
        instances, receiver, plan, verification, writer, se, clock = setup(owned_side_effect())
        self.assertTrue(verification["ok"], verification["failed"])
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(writer.physical_attempts, 0)
        checks = {c["check"]: c for c in verification["checks"]}
        for name in ("writer_transport_version_matches", "writer_min_interval_matches",
                     "writer_outcomes_version", "ladder_hash_matches", "writer_partition_enforced"):
            self.assertTrue(checks[name]["ok"], name)

    def test_partition_mismatch_fails(self):
        instances, receiver, plan, verification, writer, se, clock = setup(owned_side_effect(),
                                                                           writer_cap=10)
        self.assertIn("writer_partition_enforced", verification["failed"])


class GatingTests(unittest.TestCase):
    def test_absent_approval_zero_calls(self):
        report, receiver, writer, clock, plan, verification = run(owned_side_effect(), approval=None)
        self.assertEqual(report["stop_reason"], "missing_approval")
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(writer.physical_attempts, 0)

    def test_failed_preflight_zero_calls(self):
        instances, receiver, plan, _, writer, se, clock = setup(owned_side_effect())
        report = pilot.execute_ladder(plan, receiver, writer, {"ok": False}, instances, approval="test")
        self.assertEqual(report["stop_reason"], "preflight_failed")
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(writer.physical_attempts, 0)

    def test_journal_and_report_overwrite_refused(self):
        instances, receiver, plan, verification, writer, se, clock = setup(owned_side_effect())
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "ladder.jsonl"
            report_path = Path(directory) / "ladder-report.json"
            journal.write_text("{}\n")
            blocked = pilot.execute_ladder(plan, receiver, writer, verification, instances, approval="test",
                                           pinned_hash=PIN, journal_path=journal, report_path=report_path)
            self.assertEqual(blocked["stop_reason"], "output_exists")
        instances, receiver, plan, verification, writer, se, clock = setup(owned_side_effect())
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "ladder.jsonl"
            report_path = Path(directory) / "ladder-report.json"
            report_path.write_text('{"existing": true}\n')
            blocked = pilot.execute_ladder(plan, receiver, writer, verification, instances, approval="test",
                                           pinned_hash=PIN, journal_path=journal, report_path=report_path)
            self.assertEqual(blocked["stop_reason"], "report_exists")
            self.assertFalse(journal.exists())


class ExecutionTests(unittest.TestCase):
    def test_happy_path_owned_claims_and_control_never_writes(self):
        report, receiver, writer, clock, plan, verification = run(owned_side_effect())
        self.assertEqual(report["status"], "completed")
        for rung_id in ("L0", "L1", "L2", "L3", "L4", "L5"):
            row = report["by_rung"][rung_id]
            self.assertEqual(row["planned"], 34)
            self.assertEqual(row["attempted"], 34)
            self.assertEqual(row["exact_owned_accepted_writes"], 17)
            self.assertEqual(row["writer_outcomes"]["message_candidate"], 34)
            self.assertEqual(row["distinct_forms"], 6)
        control = [row for row in report["cases"] if row["arm"] == "COMM_CONTROL"]
        self.assertTrue(control)
        self.assertTrue(all(row["write_status"] == "control_no_write" for row in control))
        self.assertTrue(all(row["board_log"] == [] for row in control))
        self.assertTrue(all(not row["eligible_exposure"] for row in control))
        l5 = [row for row in report["cases"] if row["rung_id"] == "L5"]
        self.assertTrue(all(row["induced"] and not row["voluntary"] for row in l5))
        self.assertFalse(report["replay_ready"])

    def test_all_silence_is_observable_and_not_error(self):
        report, receiver, writer, clock, plan, verification = run(silence_side_effect)
        self.assertEqual(report["status"], "completed")
        for rung_id in ("L0", "L1", "L2", "L3", "L4", "L5"):
            self.assertEqual(report["by_rung"][rung_id]["writer_outcomes"]["deliberate_silence"], 34)
            self.assertEqual(report["by_rung"][rung_id]["exact_owned_accepted_writes"], 0)

    def test_terminal_429_is_durable_and_stops(self):
        report, receiver, writer, clock, plan, verification = run(error_side_effect)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "writer_http_429_rate_limited")
        self.assertEqual(report["by_rung"]["L0"]["attempted"], 1)
        self.assertEqual(report["by_rung"]["L0"]["invalid"], 1)
        self.assertEqual(report["by_rung"]["L0"]["writer_outcomes"]["writer_error"], 1)
        row = report["cases"][0]
        self.assertEqual(row["writer_outcome"], "writer_error")
        self.assertTrue(row["writer_outcome_diagnostics"]["delay_diagnostics"])

    def test_pacing_and_cap_accounting(self):
        report, receiver, writer, clock, plan, verification = run(owned_side_effect())
        self.assertLessEqual(report["provider_attempts"]["jev"], plan.jev_request_cap)
        self.assertLessEqual(report["provider_attempts"]["ling"], plan.ling_request_cap)
        self.assertLessEqual(report["physical_attempts"], plan.request_cap)
        self.assertGreater(report["estimated_cost_usd"], 0.0)

    def test_no_credentials_or_raw_bodies_in_rows(self):
        marker = "SECRET-PROVIDER-MARKER"
        report, receiver, writer, clock, plan, verification = run(owned_side_effect(marker=marker))
        serialized = json.dumps(report, allow_nan=False)
        self.assertNotIn(KEY, serialized)
        self.assertNotIn(marker, serialized)
        self.assertFalse(report["raw_response_retained"])
        self.assertFalse(report["credentials_retained"])

    def test_journal_is_durable(self):
        instances, receiver, plan, verification, writer, se, clock = setup(owned_side_effect())
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "ladder.jsonl"
            with patch.object(writer_v4.urllib.request, "urlopen", side_effect=se):
                report = pilot.execute_ladder(plan, receiver, writer, verification, instances,
                                              approval="test", pinned_hash=PIN, journal_path=journal,
                                              sleep_fn=lambda _: None)
            self.assertEqual(report["status"], "completed")
            self.assertEqual(len(journal.read_text().splitlines()), 204)


if __name__ == "__main__":
    unittest.main()
