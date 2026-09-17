import json
import tempfile
import unittest
import urllib.error
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from apart_incident_response.behavioral_discovery import (
    ENDPOINT,
    BehavioralArtifactStore,
    BehavioralProviderConfig,
    OpenRouterBehavioralProvider,
    audit_retained_pilot,
    classify_http_status,
    extended_paired_instances,
    frozen_full_gate_instances,
    is_retryable_status,
    mcnemar_exact_p,
    mcnemar_midp,
    paired_contrast,
    run_behavioral_screen,
    run_full_gate,
    run_oracle_probe,
    run_paired_screen,
    select_frozen_instances,
    wilson_interval,
)
from apart_incident_response.communication_protocol import BatteryCondition, DependenceRegime, ReasoningComplexity
from apart_incident_response.communication_runner import AgentContext, AgentResponse
from apart_incident_response.reasoning_baseline import DEFAULT_FREE_MODEL
from apart_incident_response.task_families import generate_instance


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class BehavioralDiscoveryTests(unittest.TestCase):
    def context(self):
        return AgentContext("run", "instance", "A", BatteryCondition.COMM, 0,
                            {"family": "hypothesis", "task_instruction": "answer", "candidate_labels": ["candidate-0"]},
                            (), "prompt-v1", 96)

    def test_behavioral_payload_omits_logprob_parameters(self):
        provider = OpenRouterBehavioralProvider(
            BehavioralProviderConfig(max_requests=1, min_interval_seconds=0), api_key="secret"
        )
        with patch("apart_incident_response.behavioral_discovery.urllib.request.urlopen",
                   return_value=FakeResponse({"model": "fixture", "choices": [{"message": {"content": "ANSWER: candidate-0"}, "finish_reason": "stop"}], "usage": {"cost": 0}})) as opener:
            response = provider.respond(self.context())
        payload = json.loads(opener.call_args.args[0].data.decode())
        self.assertNotIn("logprobs", payload)
        self.assertNotIn("top_logprobs", payload)
        self.assertNotIn("secret", opener.call_args.args[0].data.decode())
        self.assertEqual(response.answer, "candidate-0")

    def test_request_cap_and_sanitized_resume_artifact(self):
        provider = OpenRouterBehavioralProvider(
            BehavioralProviderConfig(max_requests=1, min_interval_seconds=0), api_key="secret"
        )
        with patch("apart_incident_response.behavioral_discovery.urllib.request.urlopen",
                   return_value=FakeResponse({"model": "fixture", "choices": [{"message": {"content": "ANSWER: x"}}], "usage": {}})):
            provider.complete("answer", seed=1)
        with self.assertRaises(RuntimeError):
            provider.complete("answer", seed=2)
        with tempfile.TemporaryDirectory() as directory:
            store = BehavioralArtifactStore(Path(directory) / "runs.jsonl")
            self.assertTrue(store.path.parent.stat().st_mode & 0o700)

    def test_retry_attempts_count_against_hard_cap(self):
        provider = OpenRouterBehavioralProvider(
            BehavioralProviderConfig(max_requests=2, min_interval_seconds=0, retries=1), api_key="secret"
        )
        rate_limit = urllib.error.HTTPError("https://example.invalid", 429, "rate limited", {}, None)
        response = FakeResponse({"model": "fixture", "choices": [{"message": {"content": "ANSWER: x"}}]})
        with patch("apart_incident_response.behavioral_discovery.urllib.request.urlopen",
                   side_effect=[rate_limit, response]) as opener, patch(
                       "apart_incident_response.behavioral_discovery.time.sleep"):
            self.assertEqual(provider.complete("answer", seed=1).status, "complete")
        self.assertEqual(provider.request_count, 2)
        self.assertEqual(opener.call_count, 2)

        exhausted = OpenRouterBehavioralProvider(
            BehavioralProviderConfig(max_requests=1, min_interval_seconds=0, retries=1), api_key="secret"
        )
        with patch("apart_incident_response.behavioral_discovery.urllib.request.urlopen",
                   side_effect=rate_limit) as opener, patch(
                       "apart_incident_response.behavioral_discovery.time.sleep"):
            self.assertEqual(exhausted.complete("answer", seed=1).error_type, "request_cap_exhausted")
        self.assertEqual(exhausted.request_count, 1)
        self.assertEqual(opener.call_count, 1)

    def test_screen_stops_at_triplet_boundary(self):
        class FakeProvider(OpenRouterBehavioralProvider):
            def respond(self, context):
                self._reserve()
                return AgentResponse()

        provider = FakeProvider(BehavioralProviderConfig(max_requests=12, min_interval_seconds=0), api_key="secret")
        instances = [generate_instance("hypothesis", seed, DependenceRegime.N) for seed in (51, 52)]
        with tempfile.TemporaryDirectory() as directory:
            report = run_behavioral_screen(instances, provider, BehavioralArtifactStore(Path(directory) / "runs.jsonl"))
        self.assertEqual(report["attempted_instances"], 1)
        self.assertEqual(report["run_count"], 3)
        self.assertEqual(report["provider_requests"], 12)
        self.assertTrue(report["stopped_before_instance_for_request_cap"])

    def test_retained_failed_pilot_is_not_salvaged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "pilot" / "s0001" / "C1"
            (root / "artifacts").mkdir(parents=True)
            (root / "index.json").write_text(json.dumps({"status": "failed", "agents": {"agent-1": {"status": "budget_exhausted"}}}))
            (root / "artifacts" / "metrics.json").write_text(json.dumps({"submitted_agents": 0, "validator_outcomes": []}))
            (root / "artifacts" / "board_events.jsonl").write_text('{"kind":"board_write"}\n')
            report = audit_retained_pilot(Path(directory) / "pilot")
            self.assertEqual(report["run_count"], 1)
            self.assertEqual(report["behavioral_valid_count"], 0)
            self.assertEqual(report["salvage_decision"], "no_salvage_behavioral_execution_invalid")
            self.assertFalse(report["raw_evidence_rewritten"])


class FakeGateProvider:
    """Deterministic non-HTTP provider for FULL-gate classification tests."""

    provider = "fixture"
    version = "fixture-gate-v1"

    def __init__(self, config, responses=None, cost_per_call=0.0):
        self.config = config
        self.model = config.model
        self.responses = responses or {}
        self.cost_per_call = cost_per_call
        self.request_count = 0
        self.cost_usd = 0.0

    def respond(self, context):
        self.request_count += 1
        self.cost_usd += self.cost_per_call
        return self.responses.get((context.instance_id, context.agent_id), AgentResponse())


class FullGateProviderTests(unittest.TestCase):
    def provider(self, *, retries=1, max_requests=8, cost_cap=20.0, failures=2):
        return OpenRouterBehavioralProvider(
            BehavioralProviderConfig(max_requests=max_requests, min_interval_seconds=0, retries=retries,
                                     max_cost_usd=cost_cap, max_consecutive_failures=failures),
            api_key="secret-key",
        )

    def test_request_is_credential_safe_and_logprob_free(self):
        provider = self.provider()
        body = {"id": "req-1", "model": "served-model", "choices": [{"message": {"content": "ANSWER: candidate-0"}}],
                "usage": {}}
        with patch("apart_incident_response.behavioral_discovery.urllib.request.urlopen",
                   return_value=FakeResponse(body)) as opener:
            response = provider.respond(self.context())
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, ENDPOINT)
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-key")
        self.assertEqual(request.method, "POST")
        decoded = request.data.decode()
        self.assertNotIn("secret-key", decoded)
        self.assertNotIn("logprobs", decoded)
        self.assertNotIn("top_logprobs", decoded)
        payload = json.loads(decoded)
        self.assertEqual(payload["model"], DEFAULT_FREE_MODEL)
        self.assertEqual(payload["provider"], {"require_parameters": True})
        self.assertFalse(payload["stream"])
        self.assertEqual(response.logprob_status, "not_requested")
        self.assertIsNone(response.output_logprob_entropy_bits)

    def test_http_status_classification_table(self):
        expected = {400: "client_error", 401: "auth_error", 402: "payment_required", 403: "auth_error",
                    404: "endpoint_or_model_unavailable", 405: "client_error", 408: "request_timeout",
                    418: "client_error", 422: "client_error", 429: "rate_limited", 500: "server_error",
                    502: "server_error", 503: "server_error", 504: "server_error"}
        for code, error_class in expected.items():
            self.assertEqual(classify_http_status(code), error_class)
            self.assertEqual(is_retryable_status(code), code in {408, 429, 500, 502, 503, 504})
            provider = self.provider(retries=0)
            error = urllib.error.HTTPError("https://example.invalid", code, "error", {}, None)
            with patch("apart_incident_response.behavioral_discovery.urllib.request.urlopen",
                       side_effect=error), patch("apart_incident_response.behavioral_discovery.time.sleep"):
                response = provider.complete("prompt", seed=1)
            self.assertEqual(response.status, "unavailable")
            self.assertEqual(response.error_class, error_class)
            self.assertEqual(response.status_code, code)
            self.assertNotIn("secret-key", response.error_type or "")

    def test_retry_only_for_retryable_statuses(self):
        success = FakeResponse({"model": "served", "choices": [{"message": {"content": "ANSWER: x"}}], "usage": {}})
        for code in (408, 429, 500, 502, 503, 504):
            provider = self.provider(retries=1)
            error = urllib.error.HTTPError("https://example.invalid", code, "error", {}, None)
            with patch("apart_incident_response.behavioral_discovery.urllib.request.urlopen",
                       side_effect=[error, success]) as opener, patch(
                           "apart_incident_response.behavioral_discovery.time.sleep"):
                response = provider.complete("prompt", seed=1)
            self.assertEqual(response.status, "complete", code)
            self.assertEqual(opener.call_count, 2, code)
        for code in (400, 401, 403, 404, 422):
            provider = self.provider(retries=1)
            error = urllib.error.HTTPError("https://example.invalid", code, "error", {}, None)
            with patch("apart_incident_response.behavioral_discovery.urllib.request.urlopen",
                       side_effect=error) as opener, patch(
                           "apart_incident_response.behavioral_discovery.time.sleep"):
                response = provider.complete("prompt", seed=1)
            self.assertEqual(response.status, "unavailable", code)
            self.assertEqual(opener.call_count, 1, code)

    def test_usage_cost_and_provenance_accumulate(self):
        provider = self.provider()
        body = {"id": "req-42", "model": "served/ling-x", "choices": [{"message": {"content": "ANSWER: candidate-0"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 5, "cost": 0.0}}
        with patch("apart_incident_response.behavioral_discovery.urllib.request.urlopen",
                   return_value=FakeResponse(body)):
            response = provider.complete("prompt", seed=1)
        self.assertEqual(response.request_id, "req-42")
        self.assertEqual(response.model, "served/ling-x")
        self.assertEqual(provider.input_tokens, 11)
        self.assertEqual(provider.output_tokens, 5)
        self.assertEqual(provider.cost_usd, 0.0)
        self.assertEqual(provider.last_model, "served/ling-x")
        diagnostics = provider.diagnostics()
        self.assertEqual(diagnostics["requests"], 1)
        self.assertEqual(diagnostics["model"], DEFAULT_FREE_MODEL)
        self.assertEqual(diagnostics["last_served_model"], "served/ling-x")
        self.assertEqual(diagnostics["input_tokens"], 11)
        self.assertEqual(diagnostics["output_tokens"], 5)
        self.assertFalse(diagnostics["logprobs_requested"])

    def test_rate_floor_is_enforced_between_requests(self):
        provider = self.provider(max_requests=4)
        provider.config = BehavioralProviderConfig(max_requests=4, min_interval_seconds=0.25)
        clock = [100.0]
        sleeps = []

        def fake_monotonic():
            return clock[0]

        def fake_sleep(seconds):
            sleeps.append(seconds)
            clock[0] += seconds

        with patch("apart_incident_response.behavioral_discovery.time.monotonic", side_effect=fake_monotonic), patch(
                "apart_incident_response.behavioral_discovery.time.sleep", side_effect=fake_sleep):
            provider._reserve()
            clock[0] += 0.10
            provider._reserve()
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 0.15, places=9)
        self.assertEqual(provider.request_count, 2)

    def test_full_gate_classifies_invalid_output_versus_wrong_answer(self):
        instances = frozen_full_gate_instances()[:3]
        correct, wrong, empty = instances
        responses = {
            (correct.instance_id, "A"): AgentResponse(answer=correct.target,
                                                     output_text=f"ANSWER: {correct.target}"),
            (wrong.instance_id, "A"): AgentResponse(answer="candidate-99", output_text="ANSWER: candidate-99"),
            (empty.instance_id, "A"): AgentResponse(answer=None, output_text=""),
        }
        config = BehavioralProviderConfig(max_requests=8, min_interval_seconds=0, max_cost_usd=20.0)
        provider = FakeGateProvider(config, responses)
        with tempfile.TemporaryDirectory() as directory:
            report = run_full_gate(instances, provider, BehavioralArtifactStore(Path(directory) / "gate.jsonl"))
        self.assertEqual(report["classification_counts"],
                         {"success": 1, "valid_wrong_answer": 1, "invalid_output_empty": 1})
        self.assertEqual(report["valid_denominator"], 2)
        self.assertEqual(report["successes"], 1)
        self.assertEqual(report["valid_success_rate"], 0.5)
        self.assertTrue(report["paired_screen_ready"])
        self.assertEqual(report["stop_reason"], "completed_planned_runs")

    def test_full_gate_resumes_completed_instances(self):
        instances = frozen_full_gate_instances()[:3]
        correct = instances[0]
        responses = {(correct.instance_id, "A"): AgentResponse(answer=correct.target,
                                                              output_text=f"ANSWER: {correct.target}")}
        config = BehavioralProviderConfig(max_requests=8, min_interval_seconds=0, max_cost_usd=20.0)
        with tempfile.TemporaryDirectory() as directory:
            store = BehavioralArtifactStore(Path(directory) / "gate.jsonl")
            first = run_full_gate(instances, FakeGateProvider(config, responses), store)
            self.assertEqual(first["attempted_runs"], 3)
            second = run_full_gate(instances, FakeGateProvider(config, responses), store)
            self.assertEqual(second["resumed_runs"], 1)
            self.assertEqual(second["attempted_runs"], 2)

    def test_full_gate_stops_on_repeated_http_failure(self):
        class FailingProvider(FakeGateProvider):
            def respond(self, context):
                self.request_count += 1
                return AgentResponse(output_text="", failure_reason="http_401_auth_error")

        config = BehavioralProviderConfig(max_requests=16, min_interval_seconds=0, max_cost_usd=20.0,
                                          max_consecutive_failures=2)
        provider = FailingProvider(config)
        with tempfile.TemporaryDirectory() as directory:
            report = run_full_gate(frozen_full_gate_instances(), provider,
                                   BehavioralArtifactStore(Path(directory) / "gate.jsonl"))
        self.assertEqual(report["stop_reason"], "repeated_http_failure")
        self.assertEqual(report["attempted_runs"], 2)
        self.assertEqual(report["valid_denominator"], 0)
        self.assertEqual(report["requests_made"], 4)
        self.assertEqual(report["classification_counts"], {"provider_execution_failure": 2})
        self.assertFalse(report["paired_screen_ready"])
        self.assertEqual(report["solvability_conclusion"], "not_available")

    def test_full_gate_stops_at_request_cap(self):
        config = BehavioralProviderConfig(max_requests=3, min_interval_seconds=0, max_cost_usd=20.0)
        provider = FakeGateProvider(config)
        with tempfile.TemporaryDirectory() as directory:
            report = run_full_gate(frozen_full_gate_instances(), provider,
                                   BehavioralArtifactStore(Path(directory) / "gate.jsonl"))
        self.assertEqual(report["stop_reason"], "request_cap")
        self.assertEqual(report["attempted_runs"], 1)
        self.assertEqual(report["requests_made"], 2)

    def test_full_gate_stops_at_cost_cap(self):
        config = BehavioralProviderConfig(max_requests=16, min_interval_seconds=0, max_cost_usd=0.5)
        provider = FakeGateProvider(config, cost_per_call=0.3)
        with tempfile.TemporaryDirectory() as directory:
            report = run_full_gate(frozen_full_gate_instances(), provider,
                                   BehavioralArtifactStore(Path(directory) / "gate.jsonl"))
        self.assertEqual(report["stop_reason"], "cost_cap")
        self.assertEqual(report["attempted_runs"], 1)

    def test_full_view_defaults_to_leak_free(self):
        body = {"model": "served", "choices": [{"message": {"content": "ANSWER: candidate-0"}}], "usage": {}}
        task_view = {"family": "hypothesis", "task_instruction": "answer", "candidate_labels": ["candidate-0"],
                     "joint_clues": ["bit0=0"], "joint_candidate_labels": ["candidate-0"]}
        context = AgentContext("run", "instance", "A", BatteryCondition.FULL, 0, task_view, (), "prompt-v1", 96)
        with patch("apart_incident_response.behavioral_discovery.urllib.request.urlopen",
                   return_value=FakeResponse(body)) as opener:
            OpenRouterBehavioralProvider(BehavioralProviderConfig(max_requests=1, min_interval_seconds=0),
                                         api_key="secret").respond(context)
        default_content = json.loads(json.loads(opener.call_args.args[0].data.decode())["messages"][0]["content"])
        self.assertNotIn("joint_candidate_labels", default_content)
        self.assertIn("joint_clues", default_content)
        with patch("apart_incident_response.behavioral_discovery.urllib.request.urlopen",
                   return_value=FakeResponse(body)) as leaky_opener:
            OpenRouterBehavioralProvider(
                BehavioralProviderConfig(max_requests=1, min_interval_seconds=0,
                                         include_joint_candidate_labels=True),
                api_key="secret").respond(context)
        leaky_content = json.loads(json.loads(leaky_opener.call_args.args[0].data.decode())["messages"][0]["content"])
        self.assertIn("joint_candidate_labels", leaky_content)

    def test_frozen_manifest_ids_match_committed_gate_instances(self):
        instance_ids = [instance.instance_id for instance in frozen_full_gate_instances()]
        self.assertEqual(instance_ids, [
            "hypothesis-00003a98", "hypothesis-00003a99", "hypothesis-00003a9a", "hypothesis-00003a9b",
            "reference-00003a9c", "reference-00003a9d", "reference-00003a9e", "reference-00003a9f",
        ])

    def test_select_frozen_instances_filters_family_and_complexity(self):
        selected = select_frozen_instances(families="hypothesis", complexities="medium")
        self.assertEqual([instance.instance_id for instance in selected],
                         ["hypothesis-00003a9a", "hypothesis-00003a9b"])
        self.assertEqual([instance.complexity.value for instance in selected], ["medium", "medium"])

    def test_extended_paired_instances_have_equal_n_per_cell(self):
        instances = extended_paired_instances(5)
        self.assertEqual(len(instances), 4 * 5)
        self.assertEqual(len({instance.instance_id for instance in instances}), len(instances))
        counts = Counter((instance.family, instance.complexity.value) for instance in instances)
        self.assertEqual(set(counts.values()), {5})
        self.assertEqual(set(counts), {("hypothesis", "low"), ("hypothesis", "medium"),
                                       ("reference", "low"), ("reference", "medium")})

    def test_extended_paired_instances_can_select_other_families(self):
        instances = extended_paired_instances(3, families=("planning", "lexicon"))
        self.assertEqual(len(instances), 2 * 2 * 3)
        self.assertEqual({instance.family for instance in instances}, {"planning", "lexicon"})
        self.assertEqual(len({instance.instance_id for instance in instances}), len(instances))
        self.assertNotIn(instances[0].instance_id, {i.instance_id for i in extended_paired_instances(3)})

    def context(self):
        return AgentContext("run", "instance", "A", BatteryCondition.FULL, 0,
                            {"family": "hypothesis", "task_instruction": "answer", "candidate_labels": ["candidate-0"]},
                            (), "prompt-v1", 96)


class PairedFakeProvider:
    provider = "fixture"
    version = "paired-fixture-v1"

    def __init__(self, config, responses):
        self.config = config
        self.model = config.model
        self.responses = responses
        self.request_count = 0
        self.cost_usd = 0.0

    def respond(self, context):
        self.request_count += 1
        return self.responses.get((context.instance_id, context.condition.value, context.agent_id),
                                  AgentResponse(output_text="", answer=None))


class PairedScreenTests(unittest.TestCase):
    def test_paired_screen_reports_denominators_and_c_need(self):
        frozen = frozen_full_gate_instances()
        instances = [frozen[0], frozen[2]]
        responses = {}
        for instance in instances:
            responses[(instance.instance_id, BatteryCondition.ISO.value, "A")] = AgentResponse(
                answer="candidate-99", output_text="ANSWER: candidate-99")
            responses[(instance.instance_id, BatteryCondition.FULL.value, "A")] = AgentResponse(
                answer=instance.target, output_text=f"ANSWER: {instance.target}")
            responses[(instance.instance_id, BatteryCondition.COMM.value, "A")] = AgentResponse(
                answer=instance.target, output_text=f"ANSWER: {instance.target}")
        config = BehavioralProviderConfig(max_requests=24, min_interval_seconds=0, max_cost_usd=20.0)
        provider = PairedFakeProvider(config, responses)
        with tempfile.TemporaryDirectory() as directory:
            report = run_paired_screen(instances, provider, BehavioralArtifactStore(Path(directory) / "screen.jsonl"))
        self.assertEqual(report["by_condition"]["ISO"]["valid"], 2)
        self.assertEqual(report["by_condition"]["ISO"]["successes"], 0)
        self.assertEqual(report["by_condition"]["FULL"]["successes"], 2)
        self.assertEqual(report["by_condition"]["COMM"]["successes"], 2)
        self.assertTrue(report["all_condition_denominators_present"])
        self.assertTrue(report["paired_screen_ready"])
        self.assertIn("ISO->FULL", report["paired_contrasts"])
        self.assertEqual(report["paired_contrasts"]["ISO->FULL"]["right_only"], 2)
        self.assertEqual(len(report["cells"]), 2)
        for cell in report["cells"]:
            self.assertEqual(cell["valid_denominators"], {"ISO": 1, "FULL": 1, "COMM": 1})
            self.assertEqual(cell["c_need_unclipped"], 1.0)
            self.assertIn("ISO->FULL", cell["paired_contrasts"])

    def test_paired_screen_can_run_iso_and_full_only(self):
        frozen = frozen_full_gate_instances()
        instances = [frozen[0], frozen[2]]
        responses = {}
        for instance in instances:
            responses[(instance.instance_id, BatteryCondition.ISO.value, "A")] = AgentResponse(
                answer="candidate-99", output_text="ANSWER: candidate-99")
            responses[(instance.instance_id, BatteryCondition.FULL.value, "A")] = AgentResponse(
                answer=instance.target, output_text=f"ANSWER: {instance.target}")
        config = BehavioralProviderConfig(max_requests=16, min_interval_seconds=0, max_cost_usd=20.0)
        provider = PairedFakeProvider(config, responses)
        with tempfile.TemporaryDirectory() as directory:
            report = run_paired_screen(instances, provider, BehavioralArtifactStore(Path(directory) / "screen.jsonl"),
                                       turns=1, conditions=(BatteryCondition.ISO, BatteryCondition.FULL))
        self.assertEqual(set(report["by_condition"]), {"ISO", "FULL"})
        self.assertEqual(report["requests_per_instance"], 4)
        self.assertEqual(report["requests_made"], 8)
        self.assertTrue(report["all_condition_denominators_present"])
        for cell in report["cells"]:
            self.assertNotIn("COMM", cell["p_success"])

    def test_paired_screen_stops_at_request_cap(self):
        instances = frozen_full_gate_instances()[:2]
        config = BehavioralProviderConfig(max_requests=12, min_interval_seconds=0, max_cost_usd=20.0)
        provider = PairedFakeProvider(config, {})
        with tempfile.TemporaryDirectory() as directory:
            report = run_paired_screen(instances, provider, BehavioralArtifactStore(Path(directory) / "screen.jsonl"))
        self.assertEqual(report["stop_reason"], "request_cap")
        self.assertEqual(report["attempted_instances"], 1)
        self.assertEqual(report["requests_made"], 12)
        self.assertFalse(report["all_condition_denominators_present"])


class PairedInferenceTests(unittest.TestCase):
    def test_wilson_interval_bounds(self):
        low, high = wilson_interval(0, 20)
        self.assertEqual(low, 0.0)
        self.assertLess(high, 0.2)
        low, high = wilson_interval(20, 20)
        self.assertEqual(high, 1.0)
        self.assertLess(low, 1.0)
        self.assertIsNone(wilson_interval(0, 0))

    def test_mcnemar_exact_and_midp(self):
        self.assertEqual(mcnemar_exact_p(0, 0), 1.0)
        self.assertAlmostEqual(mcnemar_exact_p(2, 13), 0.00739, places=4)
        self.assertLess(mcnemar_midp(2, 13), mcnemar_exact_p(2, 13))
        self.assertEqual(mcnemar_exact_p(5, 5), 1.0)

    def test_paired_contrast_counts_and_newcombe_interval(self):
        records = []
        for index in range(3):
            records.append({"instance_id": f"i{index}", "condition": "ISO", "valid_execution": True, "task_success": True})
            records.append({"instance_id": f"i{index}", "condition": "FULL", "valid_execution": True, "task_success": True})
        for index in range(3, 8):
            records.append({"instance_id": f"i{index}", "condition": "ISO", "valid_execution": True, "task_success": False})
            records.append({"instance_id": f"i{index}", "condition": "FULL", "valid_execution": True, "task_success": True})
        records.append({"instance_id": "i8", "condition": "ISO", "valid_execution": True, "task_success": False})
        records.append({"instance_id": "i8", "condition": "FULL", "valid_execution": True, "task_success": False})
        records.append({"instance_id": "i9", "condition": "ISO", "valid_execution": True, "task_success": True})
        records.append({"instance_id": "i9", "condition": "FULL", "valid_execution": True, "task_success": False})
        contrast = paired_contrast(records, "ISO", "FULL")
        self.assertEqual((contrast["both_success"], contrast["left_only"], contrast["right_only"],
                          contrast["both_fail"]), (3, 1, 5, 1))
        self.assertEqual(contrast["n_pairs"], 10)
        self.assertAlmostEqual(contrast["difference"], 0.4)
        low, high = contrast["newcombe_ci"]
        self.assertLessEqual(low, contrast["difference"])
        self.assertGreaterEqual(high, contrast["difference"])
        self.assertLess(contrast["mcnemar_exact_p"], 0.3)

    def test_paired_contrast_skips_invalid_and_unpaired(self):
        records = [
            {"instance_id": "a", "condition": "ISO", "valid_execution": True, "task_success": True},
            {"instance_id": "a", "condition": "FULL", "valid_execution": True, "task_success": True},
            {"instance_id": "b", "condition": "ISO", "valid_execution": False, "task_success": False},
            {"instance_id": "b", "condition": "FULL", "valid_execution": True, "task_success": True},
            {"instance_id": "c", "condition": "ISO", "valid_execution": True, "task_success": False},
        ]
        contrast = paired_contrast(records, "ISO", "FULL")
        self.assertEqual(contrast["n_pairs"], 1)
        self.assertEqual(contrast["both_success"], 1)


class ChannelCoverageTests(unittest.TestCase):
    def test_private_clues_cover_the_joint_information(self):
        for family in ("hypothesis", "reference", "planning", "poetry", "legal", "lexicon"):
            for complexity in (ReasoningComplexity.LOW, ReasoningComplexity.MEDIUM):
                for seed in (16000, 16003, 16401):
                    instance = generate_instance(family, seed, DependenceRegime.N, complexity)
                    analysis = instance.channel_analysis()
                    self.assertTrue(analysis["covers_joint"], (family, complexity.value, seed, analysis))
                    self.assertTrue(analysis["both_agents_needed"], (family, complexity.value, seed, analysis))

    def test_oracle_probe_reports_channel_ceiling(self):
        frozen = frozen_full_gate_instances()
        instances = [frozen[0], frozen[2]]
        responses = {(instance.instance_id, BatteryCondition.FULL.value, "A"): AgentResponse(
            answer=instance.target, output_text=f"ANSWER: {instance.target}") for instance in instances}
        config = BehavioralProviderConfig(max_requests=8, min_interval_seconds=0, max_cost_usd=20.0)
        provider = PairedFakeProvider(config, responses)
        with tempfile.TemporaryDirectory() as directory:
            report = run_oracle_probe(instances, provider, BehavioralArtifactStore(Path(directory) / "oracle.jsonl"))
        self.assertEqual(report["attempted_instances"], 2)
        self.assertEqual(report["valid_runs"], 2)
        self.assertEqual(report["successes"], 2)
        self.assertEqual(report["oracle_success_rate"], 1.0)
        self.assertEqual(report["stop_reason"], "completed_planned_runs")


if __name__ == "__main__":
    unittest.main()
