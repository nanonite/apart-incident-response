import json
import tempfile
import unittest
from pathlib import Path

from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_choice_pilot as pilot
from apart_incident_response.jev_choice import JevChoiceAdapter


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = json.loads((REPO_ROOT / "runs" / "epic-126"
                           / "jev-choice-replay-preregistration.json").read_text())
PIN = REGISTRATION["preregistration_hash"]


class FakeReceiverClient:
    provider = "jev"
    endpoint = jc.JEV_SYSTEMONE_ENDPOINT
    max_retries = 2

    def __init__(self, *, max_physical_requests=300):
        self.max_physical_requests = max_physical_requests
        self.physical_attempts = 0
        self.calls = 0

    def complete(self, request):
        self.physical_attempts += 1
        self.calls += 1
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

    def __init__(self, *, silent=False, max_physical_requests=300):
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


def setup(*, silent=False, receiver_cap=300, writer_cap=300):
    instances = pilot.pilot_instances()
    receiver_client = FakeReceiverClient(max_physical_requests=receiver_cap)
    receiver = JevChoiceAdapter(receiver_client, model=pilot.pr.JEV_REPLAY_MODEL)
    plan = pilot.build_pilot_plan(instances, REGISTRATION, receiver)
    verification = pilot.verify_pilot_preflight(plan, REGISTRATION, receiver, repo_root=REPO_ROOT,
                                                 pinned_hash=PIN, ling_key_present=True)
    writer = FakeWriter(silent=silent, max_physical_requests=writer_cap)
    return instances, receiver, plan, verification, writer


class PlanTests(unittest.TestCase):
    def test_plan_is_seventeen_instances_and_six_forms(self):
        instances, _, plan, _, _ = setup()
        self.assertEqual(len(instances), 17)
        self.assertEqual(plan.planned_requests, 102)
        self.assertEqual(plan.request_cap, 300)
        self.assertEqual(len({case.prompt_form_id for case in plan.cases}), 6)
        self.assertEqual({case.arm for case in plan.cases}, set(pilot.ARMS))

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
        failing = {"ok": False, "failed": ["ling_credentials_present"]}
        report = pilot.execute_pilot(plan, receiver, writer, failing, instances, approval="test")
        self.assertEqual(report["stop_reason"], "preflight_failed")
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(writer.calls, 0)

    def test_preflight_fails_without_ling_credential(self):
        instances = pilot.pilot_instances()
        receiver = JevChoiceAdapter(FakeReceiverClient(), model=pilot.pr.JEV_REPLAY_MODEL)
        plan = pilot.build_pilot_plan(instances, REGISTRATION, receiver)
        verification = pilot.verify_pilot_preflight(plan, REGISTRATION, receiver, repo_root=REPO_ROOT,
                                                     pinned_hash=PIN, ling_key_present=False)
        self.assertFalse(verification["ok"])
        self.assertIn("ling_credentials_present", verification["failed"])

    def test_unenforced_caps_block(self):
        instances, receiver, plan, verification, writer = setup(receiver_cap=None, writer_cap=300)
        report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test")
        self.assertEqual(report["stop_reason"], "receiver_cap_not_enforced")
        instances, receiver, plan, verification, writer = setup(receiver_cap=300, writer_cap=None)
        report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test")
        self.assertEqual(report["stop_reason"], "writer_cap_not_enforced")


class ExecutionTests(unittest.TestCase):
    def test_happy_path_reports_verified_exposure(self):
        instances, receiver, plan, verification, writer = setup()
        report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test",
                                     pinned_hash=PIN, sleep_fn=lambda _: None)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["attempted_requests"], 68)
        self.assertEqual(report["physical_attempts"], 102)
        self.assertEqual(report["forms_with_eligible_exposure"], 6)
        self.assertEqual(report["forms_missing_exposure"], [])
        self.assertTrue(report["replay_ready"])
        self.assertFalse(report["replay_started"])
        self.assertEqual(report["by_arm"]["COMM"]["real_writes"], 17)
        self.assertEqual(report["by_arm"]["COMM_CONTROL"]["real_writes"], 0)
        self.assertEqual(report["by_arm"]["COMM_CONTROL"]["attempted"], 17)

    def test_silent_writer_is_inconclusive_not_substituted(self):
        instances, receiver, plan, verification, writer = setup(silent=True)
        report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test",
                                     pinned_hash=PIN, sleep_fn=lambda _: None)
        self.assertEqual(report["status"], "inconclusive")
        self.assertEqual(report["stop_reason"], "missing_verified_exposure")
        self.assertEqual(len(report["forms_missing_exposure"]), 6)
        self.assertFalse(report["replay_ready"])

    def test_journal_is_durable_and_refuses_overwrite(self):
        instances, receiver, plan, verification, writer = setup()
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "pilot.jsonl"
            report = pilot.execute_pilot(plan, receiver, writer, verification, instances, approval="test",
                                         pinned_hash=PIN, journal_path=journal, sleep_fn=lambda _: None)
            self.assertEqual(report["status"], "completed")
            self.assertEqual(len(journal.read_text().splitlines()), 68)
            instances2, receiver2, plan2, verification2, writer2 = setup()
            blocked = pilot.execute_pilot(plan2, receiver2, writer2, verification2, instances2,
                                          approval="test", pinned_hash=PIN, journal_path=journal)
            self.assertEqual(blocked["stop_reason"], "output_exists")
            self.assertEqual(receiver2.client.calls, 0)


if __name__ == "__main__":
    unittest.main()
