import dataclasses
import json
import unittest
from pathlib import Path

from apart_incident_response import jev_capability as cap
from apart_incident_response import jev_preregistration as jp
from apart_incident_response.jev_choice import JEV_SYSTEMONE_ENDPOINT, JevChoiceAdapter, JevCredentials


REPO_ROOT = Path(__file__).resolve().parents[1]
KEY = "typesafe-test-key-0123456789abcdef"


class FakeClient:
    provider = "jev"
    endpoint = JEV_SYSTEMONE_ENDPOINT
    max_retries = jp.JEV_CAPABILITY_MAX_RETRIES

    def __init__(self, responses, *, max_physical_requests=jp.JEV_CAPABILITY_REQUEST_CAP):
        self.max_physical_requests = max_physical_requests
        self.physical_attempts = 0
        self.calls = []
        self._responses = list(responses)

    def complete(self, request):
        self.calls.append(request)
        self.physical_attempts += 1
        if not self._responses:
            raise AssertionError("unexpected provider call")
        return self._responses.pop(0)


class ExtraAttemptClient(FakeClient):
    """Simulates one retried attempt so physical attempts exceed case count."""

    def complete(self, request):
        if self.physical_attempts == 0:
            self.physical_attempts += 1
        return super().complete(request)


def spread_envelope(options, choice, probability=0.6, model="jev-1.13.0"):
    others = [option for option in options if option != choice]
    remainder = (1.0 - probability) / len(others) if others else 0.0
    probabilities = {option: remainder for option in options}
    probabilities[choice] = probability
    return {
        "model": model,
        "answers": {"candidate": {"type": "choice", "choice": choice,
                                  "probabilities": probabilities, "confidence": probability}},
        "usage": {"input_tokens": 100, "output_tokens": 5},
    }


def responses_for(plan, instances, *, full_wrong=0, full_invalid=0, iso_invalid=0, model="jev-1.13.0"):
    by_id = {instance.instance_id: instance for instance in instances}
    responses = []
    wrong_left, invalid_left, iso_invalid_left = full_wrong, full_invalid, iso_invalid
    for case in plan.cases:
        instance = by_id[case.instance_id]
        options = list(case.option_ids)
        if case.condition == "FULL" and invalid_left > 0:
            invalid_left -= 1
            responses.append({"model": model, "answers": {}, "usage": {"input_tokens": 10, "output_tokens": 1}})
            continue
        if case.condition == "ISO" and iso_invalid_left > 0:
            iso_invalid_left -= 1
            responses.append({"model": model, "answers": {}, "usage": {"input_tokens": 10, "output_tokens": 1}})
            continue
        choice = instance.target if case.condition == "FULL" else options[0]
        if case.condition == "FULL" and wrong_left > 0:
            wrong_left -= 1
            choice = next(option for option in options if option != instance.target)
        responses.append(spread_envelope(options, choice, model=model))
    return responses


def setup(responses=None, *, instances=None, registration=None, client=None):
    instances = instances or jp.jev_capability_instances()
    registration = registration or cap.load_registration()
    client = client or FakeClient(responses if responses is not None else responses_for(
        cap.build_capability_plan(instances, registration,
                                  JevChoiceAdapter(FakeClient([]), model=jp.JEV_CAPABILITY_MODEL)),
        instances))
    adapter = JevChoiceAdapter(client, model=jp.JEV_CAPABILITY_MODEL)
    plan = cap.build_capability_plan(instances, registration, adapter)
    verification = cap.verify_capability_preflight(plan, registration, adapter, JevCredentials(KEY, "test"),
                                                   repo_root=REPO_ROOT)
    return instances, registration, adapter, plan, verification


class PreflightTests(unittest.TestCase):
    def test_preflight_ok_offline(self):
        _, _, adapter, plan, verification = setup()
        self.assertTrue(verification["ok"], verification["failed"])
        self.assertEqual(len(plan.cases), 34)
        self.assertEqual(plan.request_cap, 68)
        self.assertEqual(plan.registration_hash, cap.JEV_CAPABILITY_REGISTRATION_HASH)
        self.assertEqual(adapter.client.physical_attempts, 0)

    def test_fail_closed_without_approval(self):
        instances, _, adapter, plan, verification = setup()
        report = cap.execute_capability_probe(plan, adapter, verification, instances, approval=None)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["stop_reason"], "missing_approval")
        self.assertEqual(adapter.client.calls, [])

    def test_fail_closed_on_pinned_hash_mismatch(self):
        instances, _, adapter, plan, verification = setup()
        report = cap.execute_capability_probe(plan, adapter, verification, instances,
                                              approval="test", pinned_hash="0" * 64)
        self.assertEqual(report["stop_reason"], "registration_hash_mismatch")
        self.assertEqual(adapter.client.calls, [])

    def test_fail_closed_when_transport_cap_not_enforced(self):
        instances, _, adapter, plan, verification = setup(client=FakeClient([], max_physical_requests=None))
        report = cap.execute_capability_probe(plan, adapter, verification, instances, approval="test")
        self.assertEqual(report["stop_reason"], "transport_cap_not_enforced")
        self.assertEqual(adapter.client.calls, [])

    def test_preflight_rejects_duplicate_case_records(self):
        instances, registration, adapter, plan, verification = setup()
        duplicated = dataclasses.replace(plan, cases=plan.cases[:1] + plan.cases[:1] + plan.cases[2:])
        result = cap.verify_capability_preflight(duplicated, registration, adapter, JevCredentials(KEY, "test"),
                                                 repo_root=REPO_ROOT)
        self.assertFalse(result["ok"])
        self.assertIn("case_records_unique", result["failed"])

    def test_preflight_rejects_non_jev_protocol_key(self):
        instances, registration, adapter, plan, verification = setup()
        mixed = dataclasses.replace(plan, protocol_key="six-family-clue-consistent-v2|a|b|c|d|e")
        result = cap.verify_capability_preflight(mixed, registration, adapter, JevCredentials(KEY, "test"),
                                                 repo_root=REPO_ROOT)
        self.assertFalse(result["ok"])
        self.assertIn("single_jev_protocol_key", result["failed"])


class ExecutionTests(unittest.TestCase):
    def test_successful_completion_and_metrics(self):
        instances, _, adapter, plan, verification = setup()
        report = cap.execute_capability_probe(plan, adapter, verification, instances, approval="test")
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["decision"], "continue")
        self.assertEqual(report["valid_cases"], 34)
        self.assertEqual(report["physical_attempts"], 34)
        self.assertEqual(report["full_vector_validity"], 1.0)
        self.assertEqual(report["task_validity_full"], 1.0)
        self.assertEqual(report["task_validity_full_denominator"], 17)
        self.assertIsNotNone(report["p_correct_full_wilson"])
        self.assertIsNotNone(report["brier"])
        self.assertIsNotNone(report["log_loss"])
        self.assertTrue(report["reliability_bins"])
        self.assertIsNotNone(report["iso_mass_on_consistent_set"])
        self.assertEqual(report["by_condition"]["FULL"]["successes"], 17)
        self.assertEqual(report["go_no_go"]["reasons"], [])

    def test_retry_and_cap_accounting(self):
        instances, registration, _, _, _ = setup()
        client = ExtraAttemptClient(responses_for(
            cap.build_capability_plan(instances, registration,
                                      JevChoiceAdapter(FakeClient([]), model=jp.JEV_CAPABILITY_MODEL)), instances))
        adapter = JevChoiceAdapter(client, model=jp.JEV_CAPABILITY_MODEL)
        plan = cap.build_capability_plan(instances, registration, adapter)
        verification = cap.verify_capability_preflight(plan, registration, adapter, JevCredentials(KEY, "test"),
                                                       repo_root=REPO_ROOT)
        report = cap.execute_capability_probe(plan, adapter, verification, instances, approval="test")
        self.assertEqual(report["attempted_cases"], 34)
        self.assertEqual(report["physical_attempts"], 35)
        self.assertGreaterEqual(report["physical_attempts"], report["attempted_cases"])
        self.assertLessEqual(report["physical_attempts"], report["max_physical_requests"])

    def test_contract_and_model_drift_stops_with_partial_preserved(self):
        instances, registration, _, _, _ = setup()
        responses = responses_for(
            cap.build_capability_plan(instances, registration,
                                      JevChoiceAdapter(FakeClient([]), model=jp.JEV_CAPABILITY_MODEL)),
            instances)
        responses[2] = spread_envelope(list(instances[1].solutions), list(instances[1].solutions)[0],
                                       model="jev-1.13.1")
        client = FakeClient(responses)
        adapter = JevChoiceAdapter(client, model=jp.JEV_CAPABILITY_MODEL)
        plan = cap.build_capability_plan(instances, registration, adapter)
        verification = cap.verify_capability_preflight(plan, registration, adapter, JevCredentials(KEY, "test"),
                                                       repo_root=REPO_ROOT)
        report = cap.execute_capability_probe(plan, adapter, verification, instances, approval="test")
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "model_drift")
        self.assertEqual(report["decision"], "stop")
        self.assertEqual(report["attempted_cases"], 3)
        self.assertEqual(len(report["cases"]), 3)
        self.assertEqual(report["invalid_classes"], {"model_drift": 1})

    def test_invalid_full_counts_as_failure_over_17(self):
        instances, registration, _, _, _ = setup()
        responses = responses_for(
            cap.build_capability_plan(instances, registration,
                                      JevChoiceAdapter(FakeClient([]), model=jp.JEV_CAPABILITY_MODEL)),
            instances, full_invalid=1)
        client = FakeClient(responses)
        adapter = JevChoiceAdapter(client, model=jp.JEV_CAPABILITY_MODEL)
        plan = cap.build_capability_plan(instances, registration, adapter)
        verification = cap.verify_capability_preflight(plan, registration, adapter, JevCredentials(KEY, "test"),
                                                       repo_root=REPO_ROOT)
        report = cap.execute_capability_probe(plan, adapter, verification, instances, approval="test")
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["task_validity_full"], 0.0)
        self.assertEqual(report["task_validity_full_denominator"], 17)

    def test_go_no_go_threshold_is_exact(self):
        for full_wrong, expected in ((1, "continue"), (2, "stop")):
            instances, registration, _, _, _ = setup()
            responses = responses_for(
                cap.build_capability_plan(instances, registration,
                                          JevChoiceAdapter(FakeClient([]), model=jp.JEV_CAPABILITY_MODEL)),
                instances, full_wrong=full_wrong)
            client = FakeClient(responses)
            adapter = JevChoiceAdapter(client, model=jp.JEV_CAPABILITY_MODEL)
            plan = cap.build_capability_plan(instances, registration, adapter)
            verification = cap.verify_capability_preflight(plan, registration, adapter,
                                                           JevCredentials(KEY, "test"), repo_root=REPO_ROOT)
            report = cap.execute_capability_probe(plan, adapter, verification, instances, approval="test")
            self.assertAlmostEqual(report["task_validity_full"], (17 - full_wrong) / 17, places=6)
            self.assertEqual(report["decision"], expected, (full_wrong, report["go_no_go"]))


class StatsTests(unittest.TestCase):
    def test_reliability_bins_and_brier(self):
        bins = cap.reliability_bins([(0.9, True), (0.9, True), (0.1, False)])
        self.assertEqual(sum(row["count"] for row in bins), 3)
        brier, logloss = cap._brier_and_logloss([(0.9, True), (0.1, False)])
        self.assertAlmostEqual(brier, 0.01)
        self.assertGreater(logloss, 0.0)


if __name__ == "__main__":
    unittest.main()
