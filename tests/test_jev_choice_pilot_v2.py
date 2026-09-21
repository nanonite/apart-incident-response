import json
import tempfile
import unittest
from pathlib import Path

from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_choice_pilot as pilot_v1
from apart_incident_response import jev_choice_pilot_v2 as pilot
from apart_incident_response import jev_choice_v2 as jc2
from apart_incident_response import jev_replay_preregistration as pr
from apart_incident_response import jev_replay_preregistration_v2 as prv2


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = json.loads((REPO_ROOT / "runs" / "epic-126"
                           / "jev-choice-replay-preregistration-v2.json").read_text())
PIN = REGISTRATION["preregistration_hash"]


class FakeReceiverClient:
    provider = "jev"
    endpoint = jc.JEV_SYSTEMONE_ENDPOINT
    max_retries = pr.JEV_REPLAY_MAX_RETRIES

    def __init__(self, *, max_physical_requests=250, attempts=0, fail=False, total=1.0):
        self.max_physical_requests = max_physical_requests
        self.physical_attempts = attempts
        self.calls = 0
        self.fail = fail
        self.total = total

    def complete(self, request):
        if self.max_physical_requests is not None and self.physical_attempts >= self.max_physical_requests:
            raise RuntimeError("physical_request_cap_exhausted")
        self.physical_attempts += 1
        self.calls += 1
        if self.fail:
            raise OSError("network down")
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


class FakeWriter:
    provider = "openrouter"

    def __init__(self, *, model=pr.LING_MODEL, endpoint=pr.LING_ENDPOINT, silent=False,
                 max_physical_requests=50):
        self.model = model
        self.endpoint = endpoint
        self.silent = silent
        self.max_physical_requests = max_physical_requests
        self.physical_attempts = 0
        self.calls = 0

    def write(self, context):
        self.physical_attempts += 1
        self.calls += 1
        if self.silent:
            return {"message": None}
        clues = list(context.get("private_clues", ()))
        return {"message": clues[0] if clues else None}


def setup(*, total=1.0, silent=False, receiver_cap=250, writer_cap=50):
    instances = pilot.pilot_instances()
    client = FakeReceiverClient(max_physical_requests=receiver_cap, total=total)
    receiver = jc2.JevChoiceAdapterV2(client, model=pr.JEV_REPLAY_MODEL)
    plan = pilot.build_pilot_plan(instances, REGISTRATION, receiver)
    writer = FakeWriter(silent=silent, max_physical_requests=writer_cap)
    verification = pilot.verify_pilot_preflight(plan, REGISTRATION, receiver, repo_root=REPO_ROOT,
                                                pinned_hash=PIN, ling_key_present=True, writer=writer)
    return instances, receiver, plan, verification, writer


class PlanV2Tests(unittest.TestCase):
    def test_plan_is_seventeen_instances_and_six_forms(self):
        instances, _, plan, _, _ = setup()
        self.assertEqual(len(instances), 17)
        self.assertEqual(plan.planned_requests, 102)
        self.assertEqual(len({case.prompt_form_id for case in plan.cases}), 6)

    def test_preflight_ok_offline_and_zero_calls(self):
        _, receiver, _, verification, _ = setup()
        self.assertTrue(verification["ok"], verification["failed"])
        self.assertEqual(receiver.client.calls, 0)

    def test_preflight_registration_segregation(self):
        _, _, plan, verification, _ = setup()
        self.assertTrue(plan.protocol_key.startswith(jc2.JEV_V2_PROTOCOL_KEY_PREFIX))
        self.assertNotEqual(plan.protocol_key, jc.jev_choice_protocol_key())
        self.assertEqual(plan.registration_hash, PIN)
        self.assertIn("v2", plan.protocol_key)
        checks = {item["check"]: item for item in verification["checks"]}
        self.assertTrue(checks["registration_verifies"]["ok"])
        self.assertTrue(checks["protocol_key_is_v2"]["ok"])
        self.assertTrue(checks["protocol_key_not_v1"]["ok"])
        self.assertTrue(checks["normalization_policy_frozen"]["ok"])

    def test_partitions_must_be_enforced(self):
        _, _, _, verification, _ = setup(receiver_cap=300)
        self.assertIn("receiver_partition_enforced", verification["failed"])
        _, _, _, verification, _ = setup(writer_cap=300)
        self.assertIn("writer_partition_enforced", verification["failed"])


class GatingV2Tests(unittest.TestCase):
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


class ExecutionV2Tests(unittest.TestCase):
    def test_exact_run_reports_no_renormalization(self):
        instances, receiver, plan, verification, writer = setup()
        report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test",
                                     pinned_hash=PIN, sleep_fn=lambda _: None)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["by_tier"]["exact"], 68)
        self.assertEqual(report["by_tier"]["complete_renormalized"], 0)
        self.assertEqual(report["renormalized_rows"], 0)
        self.assertTrue(report["replay_ready"])
        row = next(row for row in report["cases"] if row["arm"] == "COMM")
        self.assertIn("probability_diagnostics", row)
        self.assertIsNotNone(row["probability_diagnostics"])
        self.assertEqual(row["normalization_tier"], "exact")

    def test_renormalized_run_is_valid_and_reported_separately(self):
        instances, receiver, plan, verification, writer = setup(total=1.01)
        report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test",
                                     pinned_hash=PIN, sleep_fn=lambda _: None)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["by_tier"]["complete_renormalized"], 68)
        self.assertEqual(report["by_tier"]["exact"], 0)
        self.assertEqual(report["renormalized_rows"], 68)
        row = next(row for row in report["cases"] if row["arm"] == "ISO")
        self.assertEqual(row["normalization_tier"], "complete_renormalized")
        self.assertTrue(row["renormalized"])
        self.assertEqual(row["status"], "complete")
        self.assertTrue(row["raw_probabilities"])
        self.assertAlmostEqual(sum(row["probabilities"].values()), 1.0, places=9)
        self.assertAlmostEqual(sum(row["raw_probabilities"].values()), 1.01, places=6)
        self.assertIsNotNone(row["metrics"])
        self.assertAlmostEqual(row["metrics"]["p_target"],
                               row["probabilities"][row["target_id"]], places=12)

    def test_hard_deviation_stops_and_is_durable(self):
        instances, receiver, plan, verification, writer = setup(total=1.10)
        report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test",
                                     pinned_hash=PIN, sleep_fn=lambda _: None)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "not_normalized_hard")
        row = report["cases"][0]
        self.assertEqual(row["normalization_tier"], "not_normalized_hard")
        self.assertTrue(row["raw_probabilities"])
        self.assertEqual(report["hard_rows"], 1)

    def test_journal_is_durable_and_refuses_overwrite(self):
        instances, receiver, plan, verification, writer = setup()
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "pilot-v2.jsonl"
            report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test",
                                         pinned_hash=PIN, journal_path=journal, sleep_fn=lambda _: None)
            self.assertEqual(report["status"], "completed")
            self.assertEqual(len(journal.read_text().splitlines()), 68)
            _, receiver2, plan2, verification2, writer2 = setup()
            blocked = pilot.execute_pilot(plan2, receiver2, writer2, verification2, instances,
                                          approval="test", pinned_hash=PIN, journal_path=journal)
            self.assertEqual(blocked["stop_reason"], "output_exists")
            self.assertEqual(receiver2.client.calls, 0)

    def test_v2_runner_does_not_reuse_v1_paths(self):
        self.assertNotEqual(pilot.DEFAULT_JOURNAL, pilot_v1.DEFAULT_JOURNAL)
        self.assertNotEqual(pilot.DEFAULT_REPORT, pilot_v1.DEFAULT_REPORT)
        self.assertEqual(pilot.DEFAULT_JOURNAL, prv2.DEFAULT_JOURNAL_V2)
        self.assertEqual(pilot.DEFAULT_REPORT, prv2.DEFAULT_REPORT_V2)


if __name__ == "__main__":
    unittest.main()
