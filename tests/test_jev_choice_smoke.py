import json
import tempfile
import unittest
from pathlib import Path

from apart_incident_response import jev_choice_smoke as smoke
from apart_incident_response.jev_choice import JEV_SYSTEMONE_ENDPOINT, JevChoiceAdapter, JevCredentials
from apart_incident_response.jev_protocol import planning_low_instances


MANIFEST_PATH = Path(__file__).resolve().parents[1] / "runs" / "epic-126" / "jev-planning-low-manifest.json"
KEY = "typesafe-test-key-0123456789abcdef"


def manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


class RecordingClient:
    provider = "jev"

    def __init__(self, *, endpoint=JEV_SYSTEMONE_ENDPOINT, max_retries=smoke.JEV_SMOKE_MAX_RETRIES,
                 max_physical_requests=smoke.JEV_SMOKE_MAX_PHYSICAL_REQUESTS, responder=None):
        self.endpoint = endpoint
        self.max_retries = max_retries
        self.max_physical_requests = max_physical_requests
        self.physical_attempts = 0
        self.calls = []
        self.responder = responder

    def complete(self, request):
        self.calls.append(request)
        self.physical_attempts += 1
        if self.responder is not None:
            return self.responder(request)
        return _uniform_envelope(request)


def _uniform_envelope(request):
    question_id = next(iter(request["questions"]))
    option_ids = sorted(request["questions"][question_id]["criteria"])
    probability = 1.0 / len(option_ids)
    return {
        "model": "jev-1.13.0",
        "answers": {question_id: {
            "type": "choice",
            "choice": option_ids[0],
            "probabilities": {option_id: probability for option_id in option_ids},
            "confidence": probability,
        }},
        "usage": {"input_tokens": 100, "output_tokens": 3},
    }


def adapter_with(client):
    return JevChoiceAdapter(client, model=smoke.JEV_SMOKE_MODEL)


def plan_for(instances, client, *, max_physical_requests=smoke.JEV_SMOKE_MAX_PHYSICAL_REQUESTS):
    return smoke.build_smoke_plan(instances, manifest(), adapter_with(client),
                                  max_physical_requests=max_physical_requests)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.instances = planning_low_instances(smoke.JEV_SMOKE_INSTANCE_COUNT)
        self.client = RecordingClient()
        self.adapter = adapter_with(self.client)
        self.plan = plan_for(self.instances, self.client)

    def test_plan_is_two_instances_by_iso_full(self):
        self.assertEqual(len(self.plan.cases), 4)
        self.assertEqual({case.condition for case in self.plan.cases}, {"ISO", "FULL"})
        self.assertEqual({case.instance_id for case in self.plan.cases},
                         {instance.instance_id for instance in self.instances})
        self.assertEqual(self.plan.planned_physical_requests, 4)
        self.assertEqual(self.plan.protocol_key,
                         smoke.jev_choice_protocol_key(model=smoke.JEV_SMOKE_MODEL,
                                                       endpoint=JEV_SYSTEMONE_ENDPOINT,
                                                       max_retries=smoke.JEV_SMOKE_MAX_RETRIES))

    def test_plan_dict_reports_reserve_and_cost_ceiling(self):
        payload = self.plan.to_dict()
        self.assertEqual(payload["retry_reserve"], 2)
        self.assertLessEqual(payload["estimated_cost_ceiling_usd"], smoke.JEV_SMOKE_COST_CAP_USD)

    def test_verification_ok_offline(self):
        verification = smoke.verify_smoke_plan(self.plan, self.adapter, JevCredentials(KEY, "test"),
                                               self.instances)
        self.assertTrue(verification["ok"], verification["failed"])
        self.assertEqual(verification["credentials"]["fingerprint"],
                         JevCredentials(KEY, "test").fingerprint)
        self.assertEqual(self.client.physical_attempts, 0)

    def test_missing_credentials_fail(self):
        verification = smoke.verify_smoke_plan(self.plan, self.adapter, JevCredentials(None, None),
                                               self.instances)
        self.assertFalse(verification["ok"])
        self.assertIn("credentials_present", verification["failed"])

    def test_instance_outside_manifest_fails(self):
        empty = {**manifest(), "instance_ids": []}
        plan = smoke.build_smoke_plan(self.instances, empty, self.adapter)
        verification = smoke.verify_smoke_plan(plan, self.adapter, JevCredentials(KEY, "test"),
                                               self.instances)
        self.assertFalse(verification["ok"])
        self.assertTrue(any(item.startswith("instance_in_manifest:") for item in verification["failed"]))

    def test_cap_exceeded_fails_and_blocks_calls(self):
        plan = plan_for(self.instances, self.client, max_physical_requests=3)
        verification = smoke.verify_smoke_plan(plan, self.adapter, JevCredentials(KEY, "test"),
                                               self.instances)
        self.assertFalse(verification["ok"])
        self.assertIn("planned_within_cap", verification["failed"])
        report = smoke.execute_smoke(plan, self.adapter, verification, self.instances,
                                     approval="test-approval")
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["stop_reason"], "preflight_failed")
        self.assertEqual(self.client.calls, [])


class ExecuteSmokeTests(unittest.TestCase):
    def setUp(self):
        self.instances = planning_low_instances(smoke.JEV_SMOKE_INSTANCE_COUNT)
        self.client = RecordingClient()
        self.adapter = adapter_with(self.client)
        self.plan = plan_for(self.instances, self.client)
        self.verification = smoke.verify_smoke_plan(self.plan, self.adapter, JevCredentials(KEY, "test"),
                                                     self.instances)

    def test_requires_approval(self):
        report = smoke.execute_smoke(self.plan, self.adapter, self.verification, self.instances,
                                     approval=None)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["stop_reason"], "missing_approval")
        self.assertEqual(self.client.calls, [])

    def test_transport_cap_must_be_enforced(self):
        client = RecordingClient(max_physical_requests=None)
        report = smoke.execute_smoke(self.plan, adapter_with(client), self.verification, self.instances,
                                     approval="test-approval")
        self.assertEqual(report["stop_reason"], "transport_cap_not_enforced")
        self.assertEqual(client.calls, [])

    def test_happy_path_records_and_curates_golden(self):
        with tempfile.TemporaryDirectory() as directory:
            golden_path = Path(directory) / "golden.json"
            report = smoke.execute_smoke(self.plan, self.adapter, self.verification, self.instances,
                                         approval="test-approval", golden_path=golden_path)
            golden = json.loads(golden_path.read_text())
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["valid_cases"], 4)
        self.assertEqual(report["decision"], "continue")
        self.assertEqual(report["resolved_models"], ["jev-1.13.0"])
        self.assertEqual(self.client.physical_attempts, 4)
        self.assertEqual(report["estimated_cost_usd"], smoke.estimate_cost_usd(400))
        self.assertEqual(set(golden), {"_source", "probe", "status", "request", "response"})
        self.assertNotIn("authorization", {key.lower() for key in golden["request"]})
        self.assertNotIn(KEY, json.dumps(golden))
        self.assertEqual(golden["response"]["model"], "jev-1.13.0")

    def test_stops_on_first_contract_mismatch(self):
        def responder(request):
            return {"model": "jev-1.13.0", "answers": {}, "usage": {"input_tokens": 1, "output_tokens": 1}}

        client = RecordingClient(responder=responder)
        report = smoke.execute_smoke(self.plan, adapter_with(client), self.verification, self.instances,
                                     approval="test-approval")
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "missing_answer")
        self.assertEqual(report["attempted_cases"], 1)
        self.assertEqual(report["valid_cases"], 0)
        self.assertEqual(client.physical_attempts, 1)

    def test_golden_curation_drops_credential_fields(self):
        golden = smoke.curate_golden_fixture(
            request_body={"model": "jev-1.13.0", "Authorization": KEY, "state": {}},
            response_body={"model": "jev-1.13.0"}, plan=self.plan, probe="p")
        self.assertNotIn("Authorization", golden["request"])
        self.assertNotIn(KEY, json.dumps(golden))


class CostTests(unittest.TestCase):
    def test_estimate_cost_usd_matches_price(self):
        self.assertEqual(smoke.estimate_cost_usd(0), 0.0)
        self.assertAlmostEqual(smoke.estimate_cost_usd(1_000_000), 0.042)
        self.assertAlmostEqual(smoke.estimate_cost_usd(400), 0.0000168)


if __name__ == "__main__":
    unittest.main()
