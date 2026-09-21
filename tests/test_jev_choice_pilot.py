import json
import tempfile
import unittest
from pathlib import Path

from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_choice_pilot as pilot
from apart_incident_response import jev_replay_preregistration as pr
from apart_incident_response.jev_choice import JevChoiceAdapter


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = json.loads((REPO_ROOT / "runs" / "epic-126"
                           / "jev-choice-replay-preregistration.json").read_text())
PIN = REGISTRATION["preregistration_hash"]


class FakeReceiverClient:
    provider = "jev"
    endpoint = jc.JEV_SYSTEMONE_ENDPOINT
    max_retries = 2

    def __init__(self, *, max_physical_requests=250, attempts=0, fail=False):
        self.max_physical_requests = max_physical_requests
        self.physical_attempts = attempts
        self.calls = 0
        self.fail = fail

    def complete(self, request):
        if self.max_physical_requests is not None and self.physical_attempts >= self.max_physical_requests:
            raise RuntimeError("physical_request_cap_exhausted")
        self.physical_attempts += 1
        self.calls += 1
        if self.fail:
            raise OSError("network down")
        question_id = next(iter(request["questions"]))
        option_ids = list(request["questions"][question_id]["criteria"])
        probability = 1.0 / len(option_ids)
        return {"model": jc.JEV_DEFAULT_MODEL,
                "answers": {question_id: {"type": "choice", "choice": option_ids[0],
                                          "probabilities": {o: probability for o in option_ids},
                                          "confidence": probability}},
                "usage": {"input_tokens": 10, "output_tokens": 2}}


class FakeWriter:
    provider = "openrouter"

    def __init__(self, *, model=pr.LING_MODEL, endpoint=pr.LING_ENDPOINT, silent=False, error=None,
                 error_class=None, max_physical_requests=50):
        self.model = model
        self.endpoint = endpoint
        self.silent = silent
        self.error = error
        self.error_class = error_class
        self.max_physical_requests = max_physical_requests
        self.physical_attempts = 0
        self.calls = 0

    def write(self, context):
        if self.max_physical_requests is not None and self.physical_attempts >= self.max_physical_requests:
            raise pilot.WriterError("writer_physical_request_cap_exhausted")
        self.physical_attempts += 1
        self.calls += 1
        if self.error_class is not None:
            raise pilot.WriterError(self.error_class)
        if self.error is not None:
            raise RuntimeError(self.error)
        if self.silent:
            return {"message": None}
        clues = list(context.get("private_clues", ()))
        return {"message": clues[0] if clues else None}


def setup(*, silent=False, writer_error=None, writer_error_class=None, receiver_cap=250, writer_cap=50,
          receiver_attempts=0, writer_model=pr.LING_MODEL, receiver_fail=False):
    instances = pilot.pilot_instances()
    client = FakeReceiverClient(max_physical_requests=receiver_cap, attempts=receiver_attempts,
                                fail=receiver_fail)
    receiver = JevChoiceAdapter(client, model=pr.JEV_REPLAY_MODEL)
    plan = pilot.build_pilot_plan(instances, REGISTRATION, receiver)
    writer = FakeWriter(silent=silent, error=writer_error, error_class=writer_error_class,
                        max_physical_requests=writer_cap, model=writer_model)
    verification = pilot.verify_pilot_preflight(plan, REGISTRATION, receiver, repo_root=REPO_ROOT,
                                                 pinned_hash=PIN, ling_key_present=True, writer=writer)
    return instances, receiver, plan, verification, writer


class PlanTests(unittest.TestCase):
    def test_plan_is_seventeen_instances_and_six_forms(self):
        instances, _, plan, _, _ = setup()
        self.assertEqual(len(instances), 17)
        self.assertEqual(plan.planned_requests, 102)
        self.assertEqual(plan.jev_request_cap + plan.ling_request_cap, plan.request_cap)
        self.assertEqual(len({case.prompt_form_id for case in plan.cases}), 6)

    def test_preflight_ok_offline(self):
        _, receiver, _, verification, _ = setup()
        self.assertTrue(verification["ok"], verification["failed"])
        self.assertEqual(receiver.client.calls, 0)


class GatingTests(unittest.TestCase):
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

    def test_partitions_must_be_enforced(self):
        _, _, _, verification, _ = setup(receiver_cap=300)
        self.assertFalse(verification["ok"])
        self.assertIn("receiver_partition_enforced", verification["failed"])
        _, _, _, verification, _ = setup(writer_cap=300)
        self.assertFalse(verification["ok"])
        self.assertIn("writer_partition_enforced", verification["failed"])

    def test_preflight_rejects_wrong_ling_model(self):
        instances, receiver, plan, verification, writer = setup(writer_model="some/other-model")
        self.assertFalse(verification["ok"])
        self.assertIn("writer_model_matches", verification["failed"])


class ExecutionTests(unittest.TestCase):
    def test_happy_path_executes_registered_turns_and_reports_exposure(self):
        instances, receiver, plan, verification, writer = setup()
        report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test",
                                     pinned_hash=PIN, sleep_fn=lambda _: None)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["attempted_requests"], 68)
        self.assertEqual(report["provider_attempts"]["combined"], 102)
        self.assertLessEqual(report["provider_attempts"]["jev"], plan.jev_request_cap)
        self.assertLessEqual(report["provider_attempts"]["ling"], plan.ling_request_cap)
        self.assertEqual(report["forms_with_eligible_exposure"], 6)
        self.assertTrue(report["replay_ready"])
        turns = {(row["arm"], row["turns_executed"]) for row in report["cases"]}
        self.assertEqual(turns, {("ISO", 1), ("FULL", 1), ("COMM", 2), ("COMM_CONTROL", 2)})

    def test_rows_retain_replay_ready_evidence(self):
        instances, receiver, plan, verification, writer = setup()
        report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test",
                                     pinned_hash=PIN, sleep_fn=lambda _: None)
        comm = [row for row in report["cases"] if row["arm"] == "COMM"]
        first = comm[0]
        self.assertTrue(first["claim"])
        self.assertTrue(first["message_id"])
        self.assertGreater(first["i_m_bits"], 0.0)
        self.assertEqual(first["protocol_key"], plan.protocol_key)
        self.assertEqual(first["resolved_model"], jc.JEV_DEFAULT_MODEL)
        kinds = [event["kind"] for event in first["board_log"]]
        self.assertIn("board_write", kinds)
        self.assertIn("peer_read_exposure", kinds)
        iso = next(row for row in report["cases"] if row["arm"] == "ISO")
        self.assertEqual(iso["board_log"], [])
        self.assertIsNone(iso["claim"])

    def test_silent_writer_is_inconclusive(self):
        instances, receiver, plan, verification, writer = setup(silent=True)
        report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test",
                                     pinned_hash=PIN, sleep_fn=lambda _: None)
        self.assertEqual(report["status"], "inconclusive")
        self.assertEqual(len(report["forms_missing_exposure"]), 6)

    def test_writer_error_is_durable(self):
        instances, receiver, plan, verification, writer = setup(writer_error="boom")
        report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test",
                                     pinned_hash=PIN, sleep_fn=lambda _: None)
        self.assertEqual(report["stop_reason"], "writer_RuntimeError")
        row = next(row for row in report["cases"] if row.get("error_class") == "writer_RuntimeError")
        self.assertEqual(row["arm"], "COMM")
        self.assertEqual(row["turns_registered"], 2)
        self.assertIn("turns_executed", row)
        self.assertEqual(row["protocol_key"], plan.protocol_key)
        self.assertIn("provider_attempts", row)
        self.assertEqual(row["task"]["family"], "planning")
        self.assertTrue(row["option_ids"])
        self.assertEqual(report["by_arm"]["COMM"]["attempted"], 1)
        self.assertEqual(report["by_arm"]["COMM"]["invalid"], 1)

    def test_jev_exception_is_durable_and_counted(self):
        class RaisingAdapter(JevChoiceAdapter):
            def complete_with_raw(self, state):
                raise RuntimeError("provider blew up")

        instances = pilot.pilot_instances()
        receiver = RaisingAdapter(FakeReceiverClient(), model=pr.JEV_REPLAY_MODEL)
        plan = pilot.build_pilot_plan(instances, REGISTRATION, receiver)
        writer = FakeWriter()
        verification = pilot.verify_pilot_preflight(plan, REGISTRATION, receiver, repo_root=REPO_ROOT,
                                                     pinned_hash=PIN, ling_key_present=True, writer=writer)
        report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test",
                                     pinned_hash=PIN, sleep_fn=lambda _: None)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "jev_RuntimeError")
        row = next(row for row in report["cases"] if row.get("error_class") == "jev_RuntimeError")
        self.assertEqual(row["arm"], "ISO")
        self.assertEqual(row["protocol_key"], plan.protocol_key)
        self.assertIn("provider_attempts", row)
        self.assertEqual(report["by_arm"]["ISO"]["attempted"], 1)
        self.assertEqual(report["by_arm"]["ISO"]["invalid"], 1)

    def test_writer_sanitized_error_class_preserved(self):
        instances, receiver, plan, verification, writer = setup(
            writer_error_class="writer_http_429_rate_limited")
        report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test",
                                     pinned_hash=PIN, sleep_fn=lambda _: None)
        self.assertEqual(report["stop_reason"], "writer_http_429_rate_limited")
        self.assertTrue(any(row.get("error_class") == "writer_http_429_rate_limited"
                            for row in report["cases"]))

    def test_jev_transport_failure_is_durable_and_partial(self):
        instances, receiver, plan, verification, writer = setup(receiver_fail=True)
        report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test",
                                     pinned_hash=PIN, sleep_fn=lambda _: None)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "transport_error")
        self.assertTrue(any(row.get("error_class") == "transport_error" for row in report["cases"]))

    def test_partition_cap_stops_without_crossing(self):
        instances, receiver, plan, verification, writer = setup(receiver_attempts=250)
        report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test",
                                     pinned_hash=PIN, sleep_fn=lambda _: None)
        self.assertEqual(report["status"], "stopped")
        self.assertLessEqual(report["provider_attempts"]["jev"], plan.jev_request_cap)
        self.assertLessEqual(report["provider_attempts"]["combined"], plan.request_cap)

    def test_journal_is_durable_and_refuses_overwrite(self):
        instances, receiver, plan, verification, writer = setup()
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "pilot.jsonl"
            report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test",
                                         pinned_hash=PIN, journal_path=journal, sleep_fn=lambda _: None)
            self.assertEqual(report["status"], "completed")
            self.assertEqual(len(journal.read_text().splitlines()), 68)
            _, receiver2, plan2, verification2, writer2 = setup()
            blocked = pilot.execute_pilot(plan2, receiver2, writer2, verification2, instances,
                                          approval="test", pinned_hash=PIN, journal_path=journal)
            self.assertEqual(blocked["stop_reason"], "output_exists")
            self.assertEqual(receiver2.client.calls, 0)


if __name__ == "__main__":
    unittest.main()
