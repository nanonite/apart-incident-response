import json
import tempfile
import unittest
import urllib.error
import dataclasses
import io
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from apart_incident_response.behavioral_discovery import (
    ANALYSIS_PAIRS,
    ENDPOINT,
    ORACLE_CONDITION,
    PROMPT_SCHEMA_VERSION,
    PROTOCOL_OUTPUT_STEM,
    TREATMENT_PROMPT_FIELDS,
    BehavioralArtifactStore,
    BehavioralProviderConfig,
    DiagnosticCondition,
    OpenRouterBehavioralProvider,
    audit_retained_pilot,
    build_screen_instances,
    channel_audit_manifest,
    classify_http_status,
    current_protocol_key,
    extended_paired_instances,
    frozen_full_gate_instances,
    is_retryable_status,
    mcnemar_exact_p,
    mcnemar_midp,
    matched_replay_uptake,
    pair_attempt_state,
    paired_contrast,
    paired_contrasts_by_protocol,
    provider_seed,
    request_budget,
    resolve_condition_turns,
    run_behavioral_screen,
    run_full_gate,
    run_oracle_probe,
    run_paired_screen,
    run_settings_hash,
    sanitize_provider_message,
    select_frozen_instances,
    treatment_prompt,
    treatment_prompt_hash,
    treatment_schema,
    wilson_interval,
)
from apart_incident_response.communication_protocol import (
    BatteryCondition,
    DependenceRegime,
    ReasoningComplexity,
    assign_dependence,
    directional_d_idx,
)
from apart_incident_response.communication_runner import AgentContext, AgentResponse
from apart_incident_response.reasoning_baseline import DEFAULT_FREE_MODEL
from apart_incident_response.task_families import (
    GENERATOR_VERSION,
    audit_channel_invariants,
    generate_instance,
    preregistered_manifest,
)


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

    def test_provider_records_finish_reason(self):
        provider = self.provider()
        body = {"id": "req-len", "model": "served", "choices": [
            {"message": {"content": ""}, "finish_reason": "length"}], "usage": {}}
        with patch("apart_incident_response.behavioral_discovery.urllib.request.urlopen",
                   return_value=FakeResponse(body)):
            response = provider.complete("prompt", seed=1)
        self.assertEqual(response.finish_reason, "length")

    def test_empty_output_with_length_finish_reason_is_invalid_output_empty(self):
        instances = frozen_full_gate_instances()[:2]

        class LengthProvider(FakeGateProvider):
            def respond(self, context):
                self.request_count += 1
                return AgentResponse(output_text="", answer=None, finish_reason="length")

        config = BehavioralProviderConfig(max_requests=8, min_interval_seconds=0, max_cost_usd=20.0)
        provider = LengthProvider(config)
        with tempfile.TemporaryDirectory() as directory:
            store = BehavioralArtifactStore(Path(directory) / "gate.jsonl")
            report = run_full_gate(instances, provider, store)
            records = store.records()
        self.assertEqual(report["classification_counts"], {"invalid_output_empty": 2})
        self.assertEqual(len(records), 2)
        for record in records:
            summary = record["event_summary"]
            self.assertEqual(summary["finish_reason_counts"].get("length"), 1)
            self.assertEqual(summary["truncated_output_count"], 1)
            self.assertEqual(summary["outputs"][0]["finish_reason"], "length")

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
        self.assertEqual(report["requests_made"], 2)
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
        self.assertEqual(report["attempted_runs"], 3)
        self.assertEqual(report["requests_made"], 3)

    def test_full_gate_stops_at_cost_cap(self):
        config = BehavioralProviderConfig(max_requests=16, min_interval_seconds=0, max_cost_usd=0.5)
        provider = FakeGateProvider(config, cost_per_call=0.6)
        with tempfile.TemporaryDirectory() as directory:
            report = run_full_gate(frozen_full_gate_instances(), provider,
                                   BehavioralArtifactStore(Path(directory) / "gate.jsonl"))
        self.assertEqual(report["stop_reason"], "cost_cap")
        self.assertEqual(report["attempted_runs"], 1)

    def test_full_prompt_is_leak_free_invariant(self):
        body = {"model": "served", "choices": [{"message": {"content": "ANSWER: candidate-0"}}], "usage": {}}
        # A hostile task_view still carrying the answer key must not leak through.
        task_view = {"family": "hypothesis", "task_instruction": "answer",
                     "candidate_labels": ["candidate-0"], "joint_clues": ["bit0=0"],
                     "joint_candidate_labels": ["candidate-0"]}
        context = AgentContext("run", "instance", "A", BatteryCondition.FULL, 0, task_view, (), "prompt-v1", 96)
        with patch("apart_incident_response.behavioral_discovery.urllib.request.urlopen",
                   return_value=FakeResponse(body)) as opener:
            response = OpenRouterBehavioralProvider(
                BehavioralProviderConfig(max_requests=1, min_interval_seconds=0),
                api_key="secret").respond(context)
        content = json.loads(json.loads(opener.call_args.args[0].data.decode())["messages"][0]["content"])
        self.assertEqual(set(content), set(TREATMENT_PROMPT_FIELDS))
        self.assertNotIn("joint_candidate_labels", content)
        self.assertIn("joint_clues", content)
        self.assertEqual(response.prompt_schema_version, PROMPT_SCHEMA_VERSION)
        self.assertEqual(response.prompt_hash, treatment_prompt_hash(context))

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
        self.assertEqual(report["requests_per_instance"], 2)
        self.assertEqual(report["requests_made"], 4)
        self.assertTrue(report["all_condition_denominators_present"])
        for cell in report["cells"]:
            self.assertNotIn("COMM", cell["p_success"])

    def test_paired_screen_stops_at_request_cap(self):
        instances = frozen_full_gate_instances()[:4]
        config = BehavioralProviderConfig(max_requests=12, min_interval_seconds=0, max_cost_usd=20.0)
        provider = PairedFakeProvider(config, {})
        with tempfile.TemporaryDirectory() as directory:
            report = run_paired_screen(instances, provider, BehavioralArtifactStore(Path(directory) / "screen.jsonl"))
        # default frozen schedule: ISO 1 + FULL 1 + COMM (2 turns x 2 agents) = 6 per instance
        self.assertEqual(report["condition_turns"], {"ISO": 1, "FULL": 1, "COMM": 2})
        self.assertEqual(report["requests_per_instance"], 6)
        self.assertEqual(report["stop_reason"], "request_cap")
        self.assertEqual(report["attempted_instances"], 2)
        self.assertEqual(report["requests_made"], 12)
        self.assertFalse(report["all_condition_denominators_present"])

    def test_condition_turns_resolution_and_key_binding(self):
        conditions = (BatteryCondition.ISO, BatteryCondition.FULL, BatteryCondition.COMM)
        self.assertEqual(resolve_condition_turns(conditions), {"ISO": 1, "FULL": 1, "COMM": 2})
        self.assertEqual(resolve_condition_turns(conditions, turns=2), {"ISO": 2, "FULL": 2, "COMM": 2})
        self.assertEqual(resolve_condition_turns(conditions, condition_turns={"COMM": 3}),
                         {"ISO": 1, "FULL": 1, "COMM": 3})
        with self.assertRaises(ValueError):
            resolve_condition_turns(conditions, condition_turns={"COMM": 0})
        self.assertNotEqual(current_protocol_key("m", "v1", turns={"ISO": 1, "FULL": 1, "COMM": 2}),
                            current_protocol_key("m", "v1", turns=2))

    def test_comm_recovery_undefined_below_minimum_c_need(self):
        frozen = frozen_full_gate_instances()
        instances = [frozen[0]]
        responses = {(instance.instance_id, condition.value, "A"): AgentResponse(
            answer=instance.target, output_text=f"ANSWER: {instance.target}")
            for instance in instances for condition in BatteryCondition}
        config = BehavioralProviderConfig(max_requests=16, min_interval_seconds=0, max_cost_usd=20.0)
        provider = PairedFakeProvider(config, responses)
        with tempfile.TemporaryDirectory() as directory:
            report = run_paired_screen(instances, provider, BehavioralArtifactStore(Path(directory) / "screen.jsonl"))
        # ISO == FULL == 1.0 here, so C_need is zero and eta_comm must be undefined
        self.assertEqual(report["minimum_effective_c_need"], 0.10)
        self.assertIsNone(report["comm_recovery_eta"])


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
                    self.assertTrue(analysis["channel_complete"], (family, complexity.value, seed, analysis))
                    self.assertTrue(analysis["both_agents_needed"], (family, complexity.value, seed, analysis))
                    self.assertTrue(analysis["finalizer_needs_peer"], (family, complexity.value, seed, analysis))

    def test_missing_decisive_clue_is_rejected_by_unique_target_invariant(self):
        base = generate_instance("hypothesis", 16000, DependenceRegime.N, ReasoningComplexity.LOW)
        # Dropping B's decisive clue leaves two candidates; an N task requires a
        # unique clue-consistent target, so construction must reject it.
        with self.assertRaises(ValueError):
            dataclasses.replace(base, private_clues={"A": base.private_clues["A"], "B": ()})
        audit = audit_channel_invariants([base])
        self.assertEqual(audit["channel_incomplete_ids"], [])
        self.assertEqual(audit["channel_complete_count"], 1)

    def test_audit_reports_high_complexity_singleton_honestly(self):
        instances = channel_audit_manifest(seeds_per_cell=3, families=("reference",))
        audit = audit_channel_invariants(instances)
        self.assertEqual(audit["channel_incomplete_ids"], [])
        self.assertEqual(audit["unpartitioned_claims_ids"], [])
        high_rows = [row for row in audit["rows"] if row["complexity"] == "high"]
        self.assertTrue(high_rows)
        # reference-high can leave one agent with a singleton, so peer necessity is not universal
        singleton_high = [row for row in high_rows
                          if row["private_a_size"] <= 1 or row["private_b_size"] <= 1]
        self.assertTrue(singleton_high, "reference-high should expose at least one singleton-agent case")
        for row in singleton_high:
            self.assertFalse(row["both_agents_needed"], row)
        self.assertEqual(audit["no_live_screen"], True)

    def test_audit_reports_declared_sets_now_match_clue_consistent_sets(self):
        instances = channel_audit_manifest(seeds_per_cell=1, families=("hypothesis",))
        audit = audit_channel_invariants(instances)
        # After #166 the clue-consistent sets are authoritative, so the declared
        # private_solutions must equal the clue-consistent feasible set.
        self.assertEqual(audit["declared_mismatch_count"], 0)
        for row in audit["rows"]:
            self.assertTrue(row["declared_matches_clue_consistent_a"])
            self.assertTrue(row["declared_matches_clue_consistent_b"])

    def test_hypothesis_low_seed_16000_counts_and_assignment(self):
        instance = generate_instance("hypothesis", 16000, DependenceRegime.N, ReasoningComplexity.LOW)
        self.assertEqual(len(instance.solutions), 8)
        self.assertEqual(len(instance.private_solutions["A"]), 2)
        self.assertEqual(len(instance.private_solutions["B"]), 4)
        self.assertEqual(len(instance.joint_solutions), 1)
        self.assertEqual(instance.joint_solutions,
                         instance.clue_consistent(instance.pooled_private_clues()))
        self.assertEqual(instance.assignment.regime, DependenceRegime.N)
        self.assertEqual(instance.checker_id, "hypothesis-oracle-v2")
        self.assertTrue(instance.validate(instance.target)["accepted"])
        self.assertFalse(instance.validate("candidate-99")["accepted"])
        self.assertEqual(instance.validate(instance.target)["generator_version"], GENERATOR_VERSION)

    def test_public_options_are_distinct_from_private_feasible(self):
        instance = generate_instance("planning", 16400, DependenceRegime.N, ReasoningComplexity.LOW)
        view = instance.agent_view("A", "ISO")
        self.assertEqual(set(view["candidate_labels"]), set(instance.solutions))
        self.assertEqual(view["candidate_count"], len(instance.solutions))
        self.assertNotIn("private_feasible_labels", view)
        self.assertLess(len(instance.private_solutions["A"]), len(instance.solutions))

    def test_redundant_and_useful_peer_claims(self):
        instance = generate_instance("planning", 16400, DependenceRegime.N, ReasoningComplexity.LOW)
        redundant = instance.information("A", "budget=valid", "m1")
        self.assertEqual(redundant.delta_i_bits, 0.0)
        peer = next(claim for claim in instance.claims if claim.text.startswith("precedes")
                    and claim.text not in instance.private_clues["A"])
        useful = instance.information("A", peer.text, "m2")
        self.assertIsNotNone(useful.delta_i_bits)
        self.assertGreater(useful.delta_i_bits, 0.0)

    def test_reference_high_counterexample_finalizer_may_not_need_peer(self):
        instance = generate_instance("reference", 16401, DependenceRegime.N, ReasoningComplexity.HIGH)
        analysis = instance.channel_analysis()
        self.assertTrue(analysis["channel_complete"])
        self.assertFalse(analysis["both_agents_needed"])
        self.assertFalse(analysis["finalizer_needs_peer"])
        self.assertLessEqual(analysis["private_a_size"], 1)

    def test_unsupported_regimes_are_rejected(self):
        for regime in (DependenceRegime.R, DependenceRegime.H):
            with self.assertRaises(ValueError):
                generate_instance("hypothesis", 16000, regime)

    def test_claims_are_held_by_exactly_one_writer(self):
        for family in ("hypothesis", "reference", "planning", "poetry", "legal", "lexicon"):
            instance = generate_instance(family, 16000, DependenceRegime.N, ReasoningComplexity.LOW)
            analysis = instance.channel_analysis()
            self.assertTrue(analysis["claims_partitioned"], family)
            held = set(instance.private_clues["A"]) | set(instance.private_clues["B"])
            self.assertEqual(held, {claim.text for claim in instance.claims})

    def test_zero_and_undefined_denominators(self):
        self.assertEqual(directional_d_idx(1, 1), 0.0)
        self.assertIsNone(directional_d_idx(0, 1))
        self.assertIsNone(directional_d_idx(2, 0))
        self.assertEqual(assign_dependence(0.0), DependenceRegime.R)
        self.assertIsNone(assign_dependence(None))

    def test_preregistered_manifest_is_deterministic_and_leak_safe(self):
        instances = [generate_instance("hypothesis", 16000, DependenceRegime.N, ReasoningComplexity.LOW)]
        first = preregistered_manifest(instances)
        second = preregistered_manifest(instances)
        self.assertEqual(first["manifest_hash"], second["manifest_hash"])
        self.assertEqual(first["generator_version"], GENERATOR_VERSION)
        self.assertEqual(first["regime"], "N")
        blob = json.dumps(first)
        self.assertNotIn("candidate-4", blob)
        self.assertNotIn("bit0", blob)
        self.assertNotIn(instances[0].target, blob)

    def test_oracle_probe_reports_channel_ceiling(self):
        frozen = frozen_full_gate_instances()
        instances = [frozen[0], frozen[2]]
        responses = {(instance.instance_id, ORACLE_CONDITION, "A"): AgentResponse(
            answer=instance.target, output_text=f"ANSWER: {instance.target}") for instance in instances}
        config = BehavioralProviderConfig(max_requests=8, min_interval_seconds=0, max_cost_usd=20.0)
        provider = PairedFakeProvider(config, responses)
        with tempfile.TemporaryDirectory() as directory:
            store = BehavioralArtifactStore(Path(directory) / "oracle.jsonl")
            report = run_oracle_probe(instances, provider, store)
            records = store.records()
            completed = store.oracle_completed_instance_ids()
        self.assertEqual(report["attempted_instances"], 2)
        self.assertEqual(report["valid_runs"], 2)
        self.assertEqual(report["successes"], 2)
        self.assertEqual(report["oracle_success_rate"], 1.0)
        self.assertEqual(report["stop_reason"], "completed_planned_runs")
        self.assertEqual(report["condition"], ORACLE_CONDITION)
        self.assertEqual(report["requests_per_instance"], 1)
        # ORACLE has its own labeled, append-only artifact identity
        self.assertEqual(len(records), 2)
        self.assertTrue(all(record["condition"] == ORACLE_CONDITION for record in records))
        self.assertTrue(all(record["schema_version"] == "behavioral-oracle-v1" for record in records))
        self.assertEqual(completed, {instance.instance_id for instance in instances})


class TreatmentSchemaTests(unittest.TestCase):
    def context(self, condition, view, *, turn=0, agent="A"):
        full_view = {**view, "is_finalizer": True, "finalizing_agent": "A"}
        return AgentContext("r", "instance", agent, condition, turn, full_view, (), PROMPT_SCHEMA_VERSION, 96)

    def test_agent_view_full_has_no_answer_key(self):
        instance = generate_instance("hypothesis", 16000, DependenceRegime.N, ReasoningComplexity.LOW)
        view = instance.agent_view("A", "FULL")
        self.assertNotIn("joint_candidate_labels", view)
        self.assertIn("joint_clues", view)
        self.assertEqual(set(view["candidate_labels"]), set(instance.solutions))

    def test_prompt_schema_fields_and_board_absence(self):
        instance = generate_instance("hypothesis", 16000, DependenceRegime.N, ReasoningComplexity.LOW)
        cases = ((BatteryCondition.ISO, "ISO"), (BatteryCondition.FULL, "FULL"),
                 (DiagnosticCondition.ORACLE, "FULL"))
        for condition, view_condition in cases:
            view = instance.agent_view("A", view_condition)
            prompt = treatment_prompt(self.context(condition, view))
            self.assertEqual(set(prompt), set(TREATMENT_PROMPT_FIELDS))
            self.assertEqual(prompt["condition"], condition.value)
            self.assertEqual(prompt["visible_messages"], [])
            self.assertNotIn("joint_candidate_labels", prompt)

    def test_oracle_prompt_matches_full_schema_except_label(self):
        instance = generate_instance("hypothesis", 16000, DependenceRegime.N, ReasoningComplexity.LOW)
        view = instance.agent_view("A", "FULL")
        full = treatment_prompt(self.context(BatteryCondition.FULL, view))
        oracle = treatment_prompt(self.context(DiagnosticCondition.ORACLE, view))
        self.assertEqual(set(full), set(oracle))
        self.assertEqual({k: v for k, v in full.items() if k != "condition"},
                         {k: v for k, v in oracle.items() if k != "condition"})
        self.assertEqual(full["condition"], "FULL")
        self.assertEqual(oracle["condition"], "ORACLE")

    def test_oracle_is_outside_primary_conditions(self):
        self.assertEqual(DiagnosticCondition.ORACLE.value, ORACLE_CONDITION)
        self.assertNotIn(DiagnosticCondition.ORACLE, list(BatteryCondition))
        self.assertEqual([condition.value for condition in BatteryCondition], ["ISO", "FULL", "COMM"])

    def test_request_budget_is_frozen_and_comparable(self):
        self.assertEqual(request_budget("ISO", 2), 2)
        self.assertEqual(request_budget("FULL", 2), 2)
        self.assertEqual(request_budget(ORACLE_CONDITION, 2), 2)
        self.assertEqual(request_budget("COMM", 2), 4)
        self.assertEqual(request_budget("ISO", 1), 1)
        with self.assertRaises(ValueError):
            request_budget("ISO", 0)

    def test_treatment_schema_locks_fields_budget_and_policy(self):
        schema = treatment_schema()
        self.assertEqual(schema["prompt_schema_version"], PROMPT_SCHEMA_VERSION)
        self.assertEqual(schema["prompt_fields"], list(TREATMENT_PROMPT_FIELDS))
        self.assertEqual(schema["primary_conditions"], ["ISO", "FULL", "COMM"])
        self.assertEqual(schema["diagnostic_conditions"], ["ORACLE", "INDUCED"])
        self.assertEqual(schema["forbidden_model_visible_fields"], ["joint_candidate_labels"])
        self.assertEqual(schema["condition_turns"], {"ISO": 1, "FULL": 1, "COMM": 2, "ORACLE": 1})
        self.assertEqual(schema["minimum_effective_c_need"], 0.10)
        self.assertEqual(schema["request_budget"], {"ISO": 1, "FULL": 1, "ORACLE": 1, "COMM": 4})
        self.assertEqual(schema["finalizer_policy"], "one_way_A_finalizer")
        self.assertIn("claim_not_owned_by_writer", schema["comm_grammar"]["rejected_writes"])
        self.assertIn("correlation", schema["comm_grammar"]["post_read_evidence"])
        self.assertEqual(schema["cue_estimands"], {"c_need": "p_FULL - p_ISO", "oracle_gap": "p_ORACLE - p_FULL"})

    def test_provider_seed_is_reproducible_and_condition_specific(self):
        seed = provider_seed("hypothesis-1", "FULL", 0, "A")
        self.assertEqual(seed, provider_seed("hypothesis-1", "FULL", 0, "A"))
        self.assertNotEqual(seed, provider_seed("hypothesis-1", "ISO", 0, "A"))
        self.assertNotEqual(seed, provider_seed("hypothesis-1", "FULL", 1, "A"))
        self.assertNotEqual(seed, provider_seed("hypothesis-1", "FULL", 0, "B"))

    def test_provider_seed_is_bounded_to_signed_31_bits(self):
        from apart_incident_response.behavioral_discovery import (
            PROVIDER_SEED_ALGORITHM, PROVIDER_SEED_MAX,
        )
        self.assertEqual(PROVIDER_SEED_MAX, 2 ** 31 - 1)
        self.assertEqual(PROVIDER_SEED_ALGORITHM, "sha256-truncated-signed31-v1")
        seeds = [provider_seed(f"inst-{index}", condition, turn, agent)
                 for index in range(50)
                 for condition in ("ISO", "FULL", "COMM")
                 for turn in range(2)
                 for agent in ("A", "B")]
        self.assertTrue(all(0 <= seed <= PROVIDER_SEED_MAX for seed in seeds))
        # a known failing unsigned value would have exceeded the signed maximum
        self.assertGreater(3705292798, PROVIDER_SEED_MAX)

    def test_protocol_key_binds_seed_algorithm(self):
        baseline = run_settings_hash(turns=1, max_tokens=1024)
        with patch("apart_incident_response.behavioral_discovery.PROVIDER_SEED_ALGORITHM",
                   "sha256-truncated-unsigned32-v0"):
            mutated = run_settings_hash(turns=1, max_tokens=1024)
        self.assertNotEqual(baseline, mutated)

    def test_paired_screen_requests_match_frozen_budget(self):
        frozen = frozen_full_gate_instances()
        instances = [frozen[0], frozen[2]]
        responses = {}
        for instance in instances:
            for condition in BatteryCondition:
                responses[(instance.instance_id, condition.value, "A")] = AgentResponse(
                    answer=instance.target, output_text=f"ANSWER: {instance.target}")
            responses[(instance.instance_id, BatteryCondition.COMM.value, "B")] = AgentResponse(
                answer=instance.target, output_text=f"ANSWER: {instance.target}")
        config = BehavioralProviderConfig(max_requests=64, min_interval_seconds=0, max_cost_usd=20.0)
        provider = PairedFakeProvider(config, responses)
        with tempfile.TemporaryDirectory() as directory:
            report = run_paired_screen(instances, provider,
                                       BehavioralArtifactStore(Path(directory) / "screen.jsonl"), turns=2)
        expected = sum(request_budget(condition.value, 2) for condition in BatteryCondition) * len(instances)
        self.assertEqual(report["requests_per_instance"],
                         sum(request_budget(condition.value, 2) for condition in BatteryCondition))
        self.assertEqual(report["requests_made"], expected)


class ProtocolBoundaryTests(unittest.TestCase):
    def test_protocol_key_is_deterministic_and_config_scoped(self):
        key = current_protocol_key("model-a", "provider-v1")
        self.assertEqual(key, current_protocol_key("model-a", "provider-v1"))
        self.assertNotEqual(key, current_protocol_key("model-b", "provider-v1"))
        self.assertNotEqual(key, current_protocol_key("model-a", "provider-v2"))
        # generator | prompt schema | treatment-schema hash | run-settings hash | model | provider
        self.assertEqual(len(key.split("|")), 6)

    def test_protocol_key_binds_run_settings(self):
        base = dict(turns=2, max_tokens=1024, finalizing_agent="A")
        key = current_protocol_key("model-a", "provider-v1", **base)
        self.assertEqual(key, current_protocol_key("model-a", "provider-v1", **base))
        self.assertNotEqual(key, current_protocol_key("model-a", "provider-v1", turns=1, max_tokens=1024,
                                                      finalizing_agent="A"))
        self.assertNotEqual(key, current_protocol_key("model-a", "provider-v1", turns=2, max_tokens=512,
                                                      finalizing_agent="A"))
        self.assertNotEqual(key, current_protocol_key("model-a", "provider-v1", turns=2, max_tokens=1024,
                                                      finalizing_agent="B"))
        self.assertNotEqual(run_settings_hash(turns=2, max_tokens=1024),
                            run_settings_hash(turns=2, max_tokens=512))

    def test_paired_contrast_rejects_ambiguous_duplicates(self):
        records = [
            {"instance_id": "x", "condition": "ISO", "valid_execution": True, "checker_accepted": True},
            {"instance_id": "x", "condition": "ISO", "valid_execution": True, "checker_accepted": False},
            {"instance_id": "x", "condition": "FULL", "valid_execution": True, "checker_accepted": True},
        ]
        with self.assertRaises(ValueError):
            paired_contrast(records, "ISO", "FULL")
        grouped = paired_contrasts_by_protocol(records)
        entry = grouped["legacy_unknown_protocol"]["paired_contrasts"]["ISO->FULL"]
        self.assertTrue(entry["ambiguous"])
        self.assertIn("duplicate", entry["error"])

    def test_full_resume_requires_matching_condition(self):
        with tempfile.TemporaryDirectory() as directory:
            store = BehavioralArtifactStore(Path(directory) / "shared.jsonl")
            key = current_protocol_key("model-a", "provider-v1", turns=1, max_tokens=96, finalizing_agent="A")
            store.path.write_text(json.dumps({
                "schema_version": "behavioral-run-v1", "valid_execution": True,
                "instance_id": "i1", "condition": "ISO", "protocol_key": key}) + "\n", encoding="utf-8")
            self.assertEqual(store.completed_instance_ids(protocol_key=key, condition="FULL"), set())
            self.assertEqual(store.completed_instance_ids(protocol_key=key, condition="ISO"), {"i1"})

    def test_protocol_output_stem_is_versioned(self):
        self.assertEqual(PROTOCOL_OUTPUT_STEM, GENERATOR_VERSION)
        self.assertNotIn(".jsonl", PROTOCOL_OUTPUT_STEM)
        self.assertNotEqual(PROTOCOL_OUTPUT_STEM, "")

    def test_paired_contrasts_segregate_by_protocol(self):
        key_a = current_protocol_key("model-a", "v1")
        key_b = current_protocol_key("model-b", "v1")
        records = [
            {"instance_id": "x", "condition": "ISO", "valid_execution": True,
             "checker_accepted": False, "protocol_key": key_a},
            {"instance_id": "x", "condition": "FULL", "valid_execution": True,
             "checker_accepted": True, "protocol_key": key_a},
            {"instance_id": "x", "condition": "ISO", "valid_execution": True,
             "checker_accepted": True, "protocol_key": key_b},
            {"instance_id": "x", "condition": "FULL", "valid_execution": True,
             "checker_accepted": False, "protocol_key": key_b},
        ]
        grouped = paired_contrasts_by_protocol(records)
        self.assertEqual(set(grouped), {key_a, key_b})
        self.assertEqual(grouped[key_a]["record_count"], 2)
        self.assertEqual(grouped[key_a]["paired_contrasts"]["ISO->FULL"]["difference"], 1.0)
        self.assertEqual(grouped[key_b]["paired_contrasts"]["ISO->FULL"]["difference"], -1.0)

    def test_resume_ignores_records_from_other_protocols(self):
        with tempfile.TemporaryDirectory() as directory:
            store = BehavioralArtifactStore(Path(directory) / "mixed.jsonl")
            store.append_oracle({"instance_id": "i1", "valid_execution": True,
                                 "checker_accepted": True, "protocol_key": "other-protocol"})
            self.assertEqual(store.oracle_completed_instance_ids(protocol_key="other-protocol"), {"i1"})
            self.assertEqual(store.oracle_completed_instance_ids(protocol_key="current-protocol"), set())
            self.assertEqual(store.completed_instance_ids(protocol_key="current-protocol"), set())

    def test_oracle_provider_exception_records_invalid_artifact(self):
        class ExplodingProvider(PairedFakeProvider):
            def respond(self, context):
                self.request_count += 1
                raise RuntimeError("boom")

        instances = frozen_full_gate_instances()[:2]
        config = BehavioralProviderConfig(max_requests=8, min_interval_seconds=0,
                                          max_cost_usd=20.0, max_consecutive_failures=5)
        provider = ExplodingProvider(config, {})
        with tempfile.TemporaryDirectory() as directory:
            store = BehavioralArtifactStore(Path(directory) / "oracle.jsonl")
            report = run_oracle_probe(instances, provider, store)
            records = store.records()
        self.assertEqual(report["attempted_instances"], 2)
        self.assertEqual(report["valid_runs"], 0)
        self.assertEqual(report["invalid_runs"], 2)
        self.assertEqual(len(records), 2)
        self.assertTrue(all(record["classification"] == "provider_execution_failure" for record in records))
        self.assertTrue(all(record["valid_execution"] is False for record in records))
        self.assertTrue(all(record["protocol_key"] for record in records))


class CommunicationGrammarTests(unittest.TestCase):
    def test_matched_replay_separates_causal_uptake_from_correlation(self):
        instance = generate_instance("hypothesis", 16000, DependenceRegime.N, ReasoningComplexity.LOW)

        class MessageDependent:
            provider = "fixture"
            version = "replay-dependent"
            model = "fixture"

            def __init__(self):
                self.config = BehavioralProviderConfig(max_requests=8, min_interval_seconds=0)
                self.request_count = 0

            def respond(self, context):
                self.request_count += 1
                seen = any(row.get("text") == "bit1=0" for row in context.visible_messages)
                return AgentResponse(answer=instance.target if seen else "candidate-99")

        dependent = matched_replay_uptake(instance, MessageDependent(), real_message="bit1=0",
                                          placebo_message=None)
        self.assertTrue(dependent["real_accepted"])
        self.assertFalse(dependent["placebo_accepted"])
        self.assertTrue(dependent["causal_uptake"])
        self.assertEqual(dependent["evidence_class"], "matched_replay_counterfactual")

        class AlwaysCorrect:
            provider = "fixture"
            version = "replay-null"
            model = "fixture"

            def __init__(self):
                self.config = BehavioralProviderConfig(max_requests=8, min_interval_seconds=0)
                self.request_count = 0

            def respond(self, context):
                return AgentResponse(answer=instance.target)

        null = matched_replay_uptake(instance, AlwaysCorrect(), real_message="bit1=0",
                                     placebo_message=None)
        self.assertTrue(null["real_accepted"])
        self.assertTrue(null["placebo_accepted"])
        self.assertFalse(null["causal_uptake"])

    def test_paired_screen_reports_structural_and_voluntary_separately(self):
        frozen = frozen_full_gate_instances()
        instances = [frozen[0], frozen[2]]
        responses = {}
        for instance in instances:
            for condition in BatteryCondition:
                responses[(instance.instance_id, condition.value, "A")] = AgentResponse(
                    answer=instance.target, output_text=f"ANSWER: {instance.target}")
            owned = instance.private_clues["B"][0]
            responses[(instance.instance_id, BatteryCondition.COMM.value, "B")] = AgentResponse(
                answer=instance.target,
                message=owned,
                output_text=f"ANSWER: {instance.target}\nMESSAGE: {owned}")
        config = BehavioralProviderConfig(max_requests=64, min_interval_seconds=0, max_cost_usd=20.0)
        provider = PairedFakeProvider(config, responses)
        with tempfile.TemporaryDirectory() as directory:
            report = run_paired_screen(instances, provider,
                                       BehavioralArtifactStore(Path(directory) / "screen.jsonl"), turns=2)
        self.assertEqual(report["induced_arm"]["status"], "not_run")
        self.assertEqual(report["structural_necessity"]["instances"], 2)
        self.assertEqual(report["structural_necessity"]["finalizer_needs_peer_count"], 2)
        self.assertEqual(report["voluntary_comm"]["used_board_count"], 2)
        self.assertEqual(report["voluntary_comm"]["rejected_write_count"], 0)
        self.assertIn("comm_recovery_eta", report)
        self.assertIn("correlation", report["voluntary_comm"]["causal_claim"].lower())

    def test_induced_condition_is_separate_from_primary_battery(self):
        self.assertEqual(DiagnosticCondition.INDUCED.value, "INDUCED")
        self.assertNotIn(DiagnosticCondition.INDUCED, list(BatteryCondition))
        self.assertNotIn("INDUCED", [left for left, _ in ANALYSIS_PAIRS] + [right for _, right in ANALYSIS_PAIRS])

    def test_live_screen_consumes_frozen_stage2_manifest(self):
        from apart_incident_response.preregistration import mechanics_smoke_instances
        instances = build_screen_instances(scheme="stage2", seeds_per_cell=2)
        self.assertEqual([instance.instance_id for instance in instances],
                         [instance.instance_id for instance in mechanics_smoke_instances()])
        self.assertEqual(len({instance.instance_id for instance in instances}), len(instances))
        self.assertGreaterEqual(min(instance.seed for instance in instances), 19000)

    def test_planning_high_v4_scheme_matches_registered_manifest(self):
        from apart_incident_response.preregistration import build_planning_high_preregistration
        document = build_planning_high_preregistration(repo_root=Path(__file__).resolve().parents[1],
                                                       generator_commit="deadbeef")
        instances = build_screen_instances(scheme="planning-high-v4", seeds_per_cell=17)
        self.assertEqual([instance.instance_id for instance in instances],
                         document["planning_high"]["instance_ids"])
        self.assertEqual(len(instances), 17)
        self.assertEqual(len({instance.instance_id for instance in instances}), 17)


class ProviderDiagnosticsTests(unittest.TestCase):
    def test_sanitize_provider_message_redacts_credentials_and_tokens(self):
        key = "sk-secret-abcdefghijklmnopqrstuvwxyz0123456789"
        raw = ('{"error":{"message":"bad request for ' + key +
               ' user_3CAdTGDNDbieDntM5WOeHKMxiXH token '
               'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMN0123456789"}}')
        clean = sanitize_provider_message(raw, key)
        self.assertNotIn(key, clean)
        self.assertIn("<redacted-key>", clean)
        self.assertIn("<redacted-user>", clean)
        self.assertNotIn("user_3CAdTGDNDbieDntM5WOeHKMxiXH", clean)
        self.assertLessEqual(len(clean), 300)

    def test_provider_captures_sanitized_http_error_message(self):
        key = "sk-secret-abcdefghijklmnopqrstuvwxyz0123456789"
        body = b'{"error":{"message":"invalid request: upstream rejected","code":400}}'
        error = urllib.error.HTTPError("https://example.invalid", 400, "bad", {}, io.BytesIO(body))
        provider = OpenRouterBehavioralProvider(
            BehavioralProviderConfig(max_requests=2, min_interval_seconds=0, retries=0), api_key=key)
        with patch("apart_incident_response.behavioral_discovery.urllib.request.urlopen",
                   side_effect=error):
            response = provider.complete("prompt", seed=1)
        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid request", response.error_message)
        self.assertNotIn(key, response.error_message or "")
        self.assertEqual(provider.diagnostics()["last_error_message"], response.error_message)


class RecoveryTests(unittest.TestCase):
    def test_pair_attempt_state_reports_missing_and_invalid(self):
        instance = frozen_full_gate_instances()[0]
        records = [
            {"instance_id": instance.instance_id, "condition": "ISO",
             "valid_execution": True, "checker_accepted": True},
            {"instance_id": instance.instance_id, "condition": "FULL",
             "valid_execution": False, "checker_accepted": False},
        ]
        state = pair_attempt_state(records, [instance], condition_requests={"ISO": 1, "FULL": 1, "COMM": 4})
        self.assertEqual(state["valid_pairs"], 1)
        self.assertEqual(state["invalid_pairs"], 1)
        self.assertEqual(state["missing_pairs"], 1)
        self.assertEqual(state["incomplete_instances"], 1)
        self.assertEqual(state["resume_pairs"],
                         [(instance.instance_id, "FULL"), (instance.instance_id, "COMM")])
        self.assertEqual(state["resume_requests"], 5)

    def test_resume_skips_valid_pairs_without_duplicates(self):
        instance = frozen_full_gate_instances()[0]
        responses = {}
        for condition in (BatteryCondition.FULL, BatteryCondition.COMM):
            responses[(instance.instance_id, condition.value, "A")] = AgentResponse(
                answer=instance.target, output_text=f"ANSWER: {instance.target}")
        responses[(instance.instance_id, BatteryCondition.COMM.value, "B")] = AgentResponse(
            answer=instance.target, output_text=f"ANSWER: {instance.target}")
        config = BehavioralProviderConfig(max_requests=8, min_interval_seconds=0, max_cost_usd=20.0)
        provider = PairedFakeProvider(config, responses)
        resume = [{"instance_id": instance.instance_id, "condition": "ISO", "valid_execution": True}]
        with tempfile.TemporaryDirectory() as directory:
            store = BehavioralArtifactStore(Path(directory) / "resume.jsonl")
            report = run_paired_screen([instance], provider, store,
                                       condition_turns={"ISO": 1, "FULL": 1, "COMM": 2},
                                       resume_records=resume)
            records = store.records()
        self.assertEqual(report["resumed_runs"], 1)
        self.assertEqual(report["attempted_runs"], 2)
        self.assertEqual(report["requests_made"], 5)  # FULL 1 + COMM 4
        self.assertEqual(sorted(record["condition"] for record in records), ["COMM", "FULL"])
        self.assertEqual(len(records), 2)


if __name__ == "__main__":
    unittest.main()