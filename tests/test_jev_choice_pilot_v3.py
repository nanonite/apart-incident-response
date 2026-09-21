import json
import tempfile
import unittest
from pathlib import Path

from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_choice_pilot as pilot_v1
from apart_incident_response import jev_choice_pilot_v2 as pilot_v2
from apart_incident_response import jev_choice_pilot_v3 as pilot
from apart_incident_response import jev_choice_v2 as jc2
from apart_incident_response import jev_ling_writer_v3 as writer_v3
from apart_incident_response import jev_replay_preregistration as pr
from apart_incident_response import jev_replay_preregistration_v3 as prv3
from apart_incident_response.jev_choice_pilot import WriterError


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = json.loads((REPO_ROOT / "runs" / "epic-126"
                           / "jev-choice-replay-preregistration-v3.json").read_text())
PIN = REGISTRATION["preregistration_hash"]


class FakeReceiverClient:
    provider = "jev"
    endpoint = jc.JEV_SYSTEMONE_ENDPOINT
    max_retries = pr.JEV_REPLAY_MAX_RETRIES

    def __init__(self, *, max_physical_requests=250, fail=False):
        self.max_physical_requests = max_physical_requests
        self.physical_attempts = 0
        self.calls = 0
        self.fail = fail

    def complete(self, request):
        self.physical_attempts += 1
        self.calls += 1
        if self.fail:
            raise OSError("network down")
        question_id = next(iter(request["questions"]))
        option_ids = list(request["questions"][question_id]["criteria"])
        rest = (1.0 - 0.5) / (len(option_ids) - 1)
        probabilities = {option_id: (0.5 if index == 0 else rest)
                         for index, option_id in enumerate(option_ids)}
        return {"model": jc.JEV_DEFAULT_MODEL,
                "answers": {question_id: {"type": "choice", "choice": option_ids[0],
                                          "probabilities": probabilities,
                                          "confidence": 0.5}},
                "usage": {"input_tokens": 10, "output_tokens": 2}}


class FakePacingWriter:
    provider = "openrouter"
    transport_version = writer_v3.LING_WRITER_TRANSPORT_VERSION
    min_attempt_interval_seconds = writer_v3.LING_MIN_ATTEMPT_INTERVAL_SECONDS
    pacing_algorithm = writer_v3.LING_PACING_ALGORITHM
    clock_name = writer_v3.LING_MONOTONIC_CLOCK_NAME
    supported_retry_headers = tuple(writer_v3.LING_SUPPORTED_RETRY_HEADERS)
    max_server_requested_delay_seconds = writer_v3.LING_MAX_SERVER_REQUESTED_DELAY_SECONDS
    backoff_initial_seconds = writer_v3.LING_BACKOFF_INITIAL_SECONDS
    backoff_max_seconds = writer_v3.LING_BACKOFF_MAX_SECONDS

    def __init__(self, *, model=pr.LING_MODEL, endpoint=pr.LING_ENDPOINT,
                 max_retries=pr.LING_MAX_RETRIES, max_physical_requests=50, fail_class=None):
        self.model = model
        self.endpoint = endpoint
        self.max_retries = max_retries
        self.max_physical_requests = max_physical_requests
        self.fail_class = fail_class
        self.physical_attempts = 0
        self.logical_calls = 0
        self.calls = 0
        self.last_call_diagnostics = []
        self.rate_limit_records = []

    def write(self, context):
        self.logical_calls += 1
        self.calls += 1
        self.physical_attempts += 1
        record = {
            "logical_call_id": f"ling-call-{self.logical_calls}",
            "physical_attempt": self.physical_attempts,
            "retry_ordinal": 0,
            "status": 429 if self.fail_class else 200,
            "delay_seconds": 0.0,
            "delay_source": "none",
            "delay_sources": [],
            "retry_after_present": bool(self.fail_class),
            "retry_after_valid": False,
            "retry_after_ms_present": False,
            "retry_after_ms_valid": False,
            "error_class": self.fail_class,
        }
        self.last_call_diagnostics = [record]
        self.rate_limit_records.append(record)
        if self.fail_class is not None:
            raise WriterError(self.fail_class)
        clues = list(context.get("private_clues", ()))
        return {"message": clues[0] if clues else None}


def setup(*, receiver_cap=250, writer_cap=50, writer_model=pr.LING_MODEL, writer_fail_class=None,
          receiver_fail=False):
    instances = pilot.pilot_instances()
    receiver = jc2.JevChoiceAdapterV2(FakeReceiverClient(max_physical_requests=receiver_cap,
                                                         fail=receiver_fail),
                                      model=pr.JEV_REPLAY_MODEL)
    plan = pilot.build_pilot_plan(instances, REGISTRATION, receiver)
    writer = FakePacingWriter(model=writer_model, max_physical_requests=writer_cap,
                              fail_class=writer_fail_class)
    verification = pilot.verify_pilot_preflight(plan, REGISTRATION, receiver, repo_root=REPO_ROOT,
                                                pinned_hash=PIN, ling_key_present=True, writer=writer)
    return instances, receiver, plan, verification, writer


class PlanV3Tests(unittest.TestCase):
    def test_plan_is_seventeen_instances_and_six_forms(self):
        instances, _, plan, _, _ = setup()
        self.assertEqual(len(instances), 17)
        self.assertEqual(plan.planned_requests, 102)
        self.assertEqual(len({case.prompt_form_id for case in plan.cases}), 6)

    def test_preflight_ok_offline_and_zero_calls(self):
        _, receiver, _, verification, writer = setup()
        self.assertTrue(verification["ok"], verification["failed"])
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(writer.calls, 0)

    def test_preflight_inspects_writer_pacing(self):
        _, _, _, verification, _ = setup()
        checks = {item["check"]: item for item in verification["checks"]}
        for name in ("writer_transport_version_matches", "writer_min_interval_matches",
                     "writer_pacing_algorithm_matches", "writer_clock_is_monotonic",
                     "writer_retry_policy_matches", "writer_retry_headers_match",
                     "writer_max_server_delay_matches", "writer_partition_enforced",
                     "writer_model_matches", "writer_endpoint_matches",
                     "registration_verifies", "protocol_key_is_v2"):
            self.assertIn(name, checks)
            self.assertTrue(checks[name]["ok"], name)

    def test_preflight_rejects_wrong_interval_and_pacing(self):
        instances = pilot.pilot_instances()
        receiver = jc2.JevChoiceAdapterV2(FakeReceiverClient(), model=pr.JEV_REPLAY_MODEL)
        plan = pilot.build_pilot_plan(instances, REGISTRATION, receiver)
        writer = FakePacingWriter(max_physical_requests=plan.ling_request_cap)
        writer.min_attempt_interval_seconds = 0.25
        verification = pilot.verify_pilot_preflight(plan, REGISTRATION, receiver, repo_root=REPO_ROOT,
                                                    pinned_hash=PIN, ling_key_present=True, writer=writer)
        self.assertIn("writer_min_interval_matches", verification["failed"])
        writer = FakePacingWriter(max_physical_requests=plan.ling_request_cap)
        writer.transport_version = "ling-writer-v2"
        verification = pilot.verify_pilot_preflight(plan, REGISTRATION, receiver, repo_root=REPO_ROOT,
                                                    pinned_hash=PIN, ling_key_present=True, writer=writer)
        self.assertIn("writer_transport_version_matches", verification["failed"])

    def test_preflight_rejects_wrong_ling_model(self):
        _, _, _, verification, _ = setup(writer_model="some/other-model")
        self.assertIn("writer_model_matches", verification["failed"])

    def test_preflight_rejects_wrong_registration(self):
        import copy
        tampered = copy.deepcopy(REGISTRATION)
        tampered["writer_transport"]["min_attempt_interval_seconds"] = 0.25
        instances = pilot.pilot_instances()
        receiver = jc2.JevChoiceAdapterV2(FakeReceiverClient(), model=pr.JEV_REPLAY_MODEL)
        plan = pilot.build_pilot_plan(instances, tampered, receiver)
        writer = FakePacingWriter(max_physical_requests=plan.ling_request_cap)
        verification = pilot.verify_pilot_preflight(plan, tampered, receiver, repo_root=REPO_ROOT,
                                                    pinned_hash=tampered["preregistration_hash"],
                                                    ling_key_present=True, writer=writer)
        self.assertFalse(verification["ok"])
        self.assertIn("registration_verifies", verification["failed"])


class GatingV3Tests(unittest.TestCase):
    def test_absent_approval_makes_zero_calls(self):
        instances, receiver, plan, verification, writer = setup()
        report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval=None)
        self.assertEqual(report["stop_reason"], "missing_approval")
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(writer.calls, 0)

    def test_failed_preflight_makes_zero_calls(self):
        instances, receiver, plan, _, writer = setup()
        report = pilot.execute_pilot(plan, receiver, writer, {"ok": False}, instances, approval="test")
        self.assertEqual(report["stop_reason"], "preflight_failed")
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(writer.calls, 0)


class ExecutionV3Tests(unittest.TestCase):
    def test_happy_path_reports_pacing_and_diagnostics(self):
        instances, receiver, plan, verification, writer = setup()
        report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test",
                                     pinned_hash=PIN, sleep_fn=lambda _: None)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["attempted_requests"], 68)
        self.assertEqual(report["by_tier"]["exact"], 68)
        self.assertEqual(report["writer_transport_version"], writer_v3.LING_WRITER_TRANSPORT_VERSION)
        self.assertEqual(report["writer_min_interval_seconds"], 3.25)
        self.assertEqual(report["writer_rate_limit"]["transport_version"],
                         writer_v3.LING_WRITER_TRANSPORT_VERSION)
        comm = next(row for row in report["cases"] if row["arm"] == "COMM")
        self.assertTrue(comm["writer_diagnostics"])
        self.assertEqual(set(comm["writer_diagnostics"][0]) <= set(writer_v3.LING_PROVENANCE_FIELDS), True)
        self.assertTrue(report["replay_ready"])

    def test_terminal_429_is_durable_and_counts_arm(self):
        instances, receiver, plan, verification, writer = setup(
            writer_fail_class="writer_http_429_rate_limited")
        report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test",
                                     pinned_hash=PIN, sleep_fn=lambda _: None)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "writer_http_429_rate_limited")
        row = next(row for row in report["cases"] if row.get("error_class") == "writer_http_429_rate_limited")
        self.assertEqual(row["arm"], "COMM")
        self.assertEqual(row["write_status"], "writer_error")
        self.assertTrue(row["writer_diagnostics"])
        self.assertEqual(report["by_arm"]["COMM"]["attempted"], 1)
        self.assertEqual(report["by_arm"]["COMM"]["invalid"], 1)

    def test_partitions_and_journal(self):
        instances, receiver, plan, verification, writer = setup(receiver_cap=300)
        self.assertIn("receiver_partition_enforced", verification["failed"])
        instances, receiver, plan, verification, writer = setup(writer_cap=300)
        self.assertIn("writer_partition_enforced", verification["failed"])

    def test_journal_is_durable_and_refuses_overwrite(self):
        instances, receiver, plan, verification, writer = setup()
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "pilot-v3.jsonl"
            report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test",
                                         pinned_hash=PIN, journal_path=journal, sleep_fn=lambda _: None)
            self.assertEqual(report["status"], "completed")
            self.assertEqual(len(journal.read_text().splitlines()), 68)
            _, receiver2, plan2, verification2, writer2 = setup()
            blocked = pilot.execute_pilot(plan2, receiver2, writer2, verification2, instances,
                                          approval="test", pinned_hash=PIN, journal_path=journal)
            self.assertEqual(blocked["stop_reason"], "output_exists")
            self.assertEqual(receiver2.client.calls, 0)

    def test_report_is_fail_closed_before_any_call(self):
        instances, receiver, plan, verification, writer = setup()
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "pilot-v3.jsonl"
            report_path = Path(directory) / "pilot-v3-report.json"
            report_path.write_text('{"existing": true}\n', encoding="utf-8")
            blocked = pilot.execute_pilot(plan, receiver, writer, verification, instances,
                                          approval="test", pinned_hash=PIN, journal_path=journal,
                                          report_path=report_path, sleep_fn=lambda _: None)
            self.assertEqual(blocked["stop_reason"], "report_exists")
            self.assertEqual(receiver.client.calls, 0)
            self.assertEqual(writer.calls, 0)
            self.assertFalse(journal.exists())
            self.assertEqual(report_path.read_text(encoding="utf-8"), '{"existing": true}\n')

    def test_fresh_paths_do_not_collide_with_v1_or_v2(self):
        self.assertNotEqual(pilot.DEFAULT_JOURNAL, pilot_v1.DEFAULT_JOURNAL)
        self.assertNotEqual(pilot.DEFAULT_REPORT, pilot_v1.DEFAULT_REPORT)
        self.assertNotEqual(pilot.DEFAULT_JOURNAL, pilot_v2.DEFAULT_JOURNAL)
        self.assertNotEqual(pilot.DEFAULT_REPORT, pilot_v2.DEFAULT_REPORT)
        self.assertEqual(pilot.DEFAULT_JOURNAL, prv3.DEFAULT_JOURNAL_V3)
        self.assertEqual(pilot.DEFAULT_REPORT, prv3.DEFAULT_REPORT_V3)


if __name__ == "__main__":
    unittest.main()
