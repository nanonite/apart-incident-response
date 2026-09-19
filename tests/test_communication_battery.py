import unittest

from apart_incident_response.communication_analysis import PairedOutcome, fit_communication_propensity, paired_metrics, paired_contrasts, wilson_interval
from apart_incident_response.communication_calibration import calibration_report, selected_fixture_instances
from apart_incident_response.communication_entropy import assign_entropy_gate, coverage_gate, first_post_read_outputs, matched_placebo
from apart_incident_response.communication_events import CommunicationEventLog
from apart_incident_response.communication_protocol import (
    BatteryCondition, BatteryProtocol, DependenceRegime, directional_d_idx,
)
from apart_incident_response.communication_runner import AgentResponse, ScriptedProvider, TwoAgentBatteryRunner
from apart_incident_response.finite_information import ExactInformationEvaluator, FeasibleSet, MessageInterpretation
from apart_incident_response.live_gate import LiveGate, evaluate_capability_smoke
from apart_incident_response.communication_report import report_from_rows
from apart_incident_response.task_families import generate_grid, generate_instance, validate_family_grid


class CommunicationBatteryTests(unittest.TestCase):
    def test_protocol_is_distinct_from_legacy_conditions(self):
        document = BatteryProtocol().to_dict()
        self.assertEqual(document["protocol_version"], "two-agent-iso-full-comm-v1")
        self.assertEqual(document["conditions"], ["ISO", "FULL", "COMM"])
        self.assertNotIn("C0", document["conditions"])

    def test_exact_message_information_and_unknown_state(self):
        feasible = FeasibleSet.from_values(range(8))
        evaluator = ExactInformationEvaluator()
        interpretation = MessageInterpretation.accepted(lambda value: value < 2, "value<2")
        result = evaluator.evaluate(feasible, "value<2", interpretation, "m1")
        self.assertEqual(result.before_count, 8)
        self.assertEqual(result.after_count, 2)
        self.assertEqual(result.delta_i_bits, 2.0)
        unknown = evaluator.evaluate(feasible, "maybe", MessageInterpretation.unknown("ambiguous"), "m2")
        self.assertIsNone(unknown.delta_i_bits)
        duplicate = evaluator.evaluate(FeasibleSet.from_values(range(2)), "value<2",
                                       MessageInterpretation.accepted(lambda value: True, "duplicate"), "m3")
        self.assertEqual(duplicate.delta_i_bits, 0.0)

    def test_dependence_is_measured_not_hint(self):
        self.assertAlmostEqual(directional_d_idx(8, 2), 2 / 3)
        for family in ("hypothesis", "reference", "planning", "poetry", "legal", "lexicon"):
            report = validate_family_grid(family)
            self.assertTrue(report["all_finite"], family)
            self.assertTrue(report["all_valid"], family)
            self.assertEqual(report["supported_regimes"], ["N"])
            self.assertEqual(len(report["cells"]), 3)
            self.assertEqual({cell["regime"] for cell in report["cells"]}, {"N"})
        # redundant/helpful hints are unsupported by the clue-consistent generator
        for regime in (DependenceRegime.R, DependenceRegime.H):
            with self.assertRaises(ValueError):
                generate_instance("hypothesis", 1, regime)

    def test_hypothesis_trajectory_is_auditable(self):
        instance = generate_instance("hypothesis", 4, DependenceRegime.N)
        self.assertEqual(len(instance.private_solutions["A"]), 2)
        trajectory = instance.trajectory("A", tuple(claim.text for claim in instance.claims[:3]))
        self.assertEqual([(row.before_count, row.after_count, row.delta_i_bits) for row in trajectory],
                         [(2, 2, 0.0), (2, 1, 1.0), (1, 1, 0.0)])

    def test_board_write_reports_receiver_information(self):
        instance = generate_instance("hypothesis", 16000, DependenceRegime.N)
        # B holds bit1=0; A does not. The same claim carries 0 bits for the
        # writer B and 1 bit for the receiver A.
        self.assertEqual(instance.information("B", "bit1=0", "m").delta_i_bits, 0.0)
        self.assertEqual(instance.information("A", "bit1=0", "m").delta_i_bits, 1.0)

        class Provider:
            provider = "fixture"
            version = "receiver-info-test"

            def respond(self, context):
                if context.agent_id == "B" and context.turn == 0:
                    return AgentResponse(answer=instance.target, message="bit1=0")
                return AgentResponse(answer=instance.target)

        result = TwoAgentBatteryRunner(turns=2).run_condition(
            instance, BatteryCondition.COMM, Provider())
        self.assertEqual(result.event_summary["message_count"], 1)
        self.assertEqual(result.event_summary["transmitted_bits"], 1.0)
        join = next(row for row in result.event_summary["joins"])
        self.assertEqual(join["delta_i_bits"], 1.0)
        self.assertEqual(join["reader_agent"], "A")

    def test_provenance_distinguishes_read_output_and_post_read_correlation(self):
        log = CommunicationEventLog("run")
        message = generate_instance("hypothesis", 1).information("A", "bit0=0", "m1")
        log.board_write("A", message, message_tokens=1)
        log.peer_read("B", message)
        log.peer_read("B", message)
        log.model_output("B", "o1", exposed_message_ids=("m1",), logprob_entropy_bits=1.2,
                         logprob_coverage=1.0, logprob_status="complete")
        log.post_read_correlation("B", message, "o1", checker_evidence={"evidence_class": "post_read_correlation"})
        self.assertEqual(len([event for event in log.events if event.kind == "peer_read_exposure"]), 1)
        self.assertEqual([row["status"] for row in log.replay_joins()], ["joined"])

    def test_runner_triplet_has_paired_ids_and_isolation(self):
        instance = generate_instance("hypothesis", 5)

        class Provider:
            provider = "fixture"
            version = "test-provider"

            def respond(self, context):
                self.last = context
                return AgentResponse(answer=instance.target)

        results = TwoAgentBatteryRunner(turns=1).run_triplet(instance, Provider())
        self.assertEqual([result.condition for result in results], list(BatteryCondition))
        self.assertEqual({result.pair_id for result in results}, {f"pair-{instance.instance_id}"})
        self.assertEqual({result.instance_id for result in results}, {instance.instance_id})
        self.assertEqual(results[0].event_summary["message_count"], 0)

    def test_comm_writer_ownership_positive_null_and_wrong_owner(self):
        instance = generate_instance("hypothesis", 16000, DependenceRegime.N)
        self.assertTrue(instance.holds_claim("B", "bit1=0"))
        self.assertFalse(instance.holds_claim("B", "bit0=1"))
        self.assertEqual(instance.claim_owner("bit0=1"), "A")

        def run(message):
            class Provider:
                provider = "fixture"
                version = "ownership-test"

                def respond(self, context):
                    if context.agent_id == "B" and context.turn == 0 and message is not None:
                        return AgentResponse(answer=instance.target, message=message)
                    return AgentResponse(answer=instance.target)
            return TwoAgentBatteryRunner(turns=2).run_condition(
                instance, BatteryCondition.COMM, Provider())

        owned = run("bit1=0")
        self.assertEqual(owned.event_summary["message_count"], 1)
        self.assertEqual(owned.event_summary["rejected_write_count"], 0)
        self.assertEqual(owned.artifact["rejected_writes"], [])

        wrong_owner = run("bit0=1")
        self.assertEqual(wrong_owner.event_summary["message_count"], 0)
        self.assertEqual(wrong_owner.event_summary["rejected_write_count"], 1)
        self.assertEqual(wrong_owner.artifact["rejected_writes"][0]["claim_owner"], "A")
        self.assertEqual(wrong_owner.artifact["rejected_writes"][0]["reason"], "claim_not_owned_by_writer")

        silent = run(None)
        self.assertEqual(silent.status, "completed")
        self.assertEqual(silent.event_summary["message_count"], 0)
        self.assertEqual(silent.event_summary["rejected_write_count"], 0)

    def test_post_read_evidence_is_labelled_correlation(self):
        instance = generate_instance("hypothesis", 51, DependenceRegime.N)

        class UptakeProvider:
            provider = "fixture"
            version = "correlation-label-test"

            def respond(self, context):
                if context.agent_id == "B" and context.turn == 0:
                    return AgentResponse(answer=None, message=instance.claims[1].text)
                if context.agent_id == "A" and context.turn == 1 and context.visible_messages:
                    return AgentResponse(answer=instance.target)
                return AgentResponse(answer=None)

        result = TwoAgentBatteryRunner(turns=2, finalizing_agent="A").run_condition(
            instance, BatteryCondition.COMM, UptakeProvider())
        self.assertGreaterEqual(result.event_summary["post_read_correlation_count"], 1)
        self.assertNotIn("post_read_success_count", result.event_summary)
        self.assertNotIn("first_post_read_success_latency_seconds", result.event_summary)
        # the correlation event carries explicit non-causal evidence labelling
        import json as _json
        blob = _json.dumps(result.artifact)
        self.assertIn("post_read_correlation", blob)

    def test_comm_optional_message_is_read_and_machine_verified(self):
        instance = generate_instance("hypothesis", 51, DependenceRegime.N)
        class UptakeProvider:
            provider = "fixture"
            version = "uptake-test-v1"
            model = "fixture-model"
            def respond(self, context):
                if context.agent_id == "B" and context.turn == 0:
                    return AgentResponse(answer=None, message=instance.claims[1].text)
                if context.agent_id == "A" and context.turn == 1 and context.visible_messages:
                    return AgentResponse(answer=instance.target)
                return AgentResponse(answer=None)
        result = TwoAgentBatteryRunner(turns=2, finalizing_agent="A").run_condition(
            instance, BatteryCondition.COMM, UptakeProvider(),
        )
        self.assertEqual(result.status, "completed")
        self.assertGreaterEqual(result.event_summary["message_count"], 1)
        self.assertGreaterEqual(result.event_summary["post_read_correlation_count"], 1)
        self.assertEqual(result.artifact["model_id"], "fixture-model")

    def test_informative_message_does_not_pass_when_finalizer_already_knew_answer(self):
        instance = generate_instance("hypothesis", 54, DependenceRegime.N)
        class AlreadyKnowsProvider:
            provider = "fixture"
            version = "no-uptake-test-v1"
            model = "fixture-model"
            def respond(self, context):
                if context.agent_id == "B" and context.turn == 0:
                    return AgentResponse(answer=instance.target, message=instance.claims[1].text)
                return AgentResponse(answer=instance.target)
        result = TwoAgentBatteryRunner(turns=2, finalizing_agent="A").run_condition(
            instance, BatteryCondition.COMM, AlreadyKnowsProvider(),
        )
        self.assertTrue(result.task_success)
        self.assertEqual(result.event_summary["post_read_correlation_count"], 0)

    def test_self_reported_use_without_information_or_checker_does_not_pass(self):
        instance = generate_instance("hypothesis", 52, DependenceRegime.N)
        answers = {(instance.instance_id, condition, agent): instance.target
                   for condition in BatteryCondition for agent in ("A", "B")}
        messages = {(instance.instance_id, BatteryCondition.COMM, "A", 0): "ambiguous self report"}
        provider = ScriptedProvider(answers, messages)
        result = TwoAgentBatteryRunner(turns=2, finalizing_agent="A").run_condition(instance, BatteryCondition.COMM, provider)
        self.assertEqual(result.event_summary["post_read_correlation_count"], 0)

    def test_finalizer_only_scoring_rejects_other_agent_answer(self):
        instance = generate_instance("hypothesis", 53, DependenceRegime.N)
        class Provider:
            provider = "fixture"
            version = "finalizer-test-v1"
            model = "fixture-model"
            def respond(self, context):
                return AgentResponse(answer=instance.target if context.agent_id == "B" else "not-the-answer")
        result = TwoAgentBatteryRunner(turns=1, finalizing_agent="A").run_condition(instance, BatteryCondition.ISO, Provider())
        self.assertFalse(result.task_success)
        self.assertEqual(result.artifact["model_id"], "fixture-model")

    def test_analysis_retains_invalid_denominators_and_does_not_use_volume_for_phi(self):
        rows = [
            PairedOutcome("p", "hypothesis", "fixture", "ISO", False, communication_tokens=9),
            PairedOutcome("p", "hypothesis", "fixture", "FULL", True, communication_tokens=1),
            PairedOutcome("p", "hypothesis", "fixture", "COMM", True,
                          transmitted_bits=1, post_read_correlated_bits=1, communication_tokens=99),
        ]
        metrics = paired_metrics(rows)[0]
        self.assertEqual(metrics["c_need"], 1.0)
        fit = fit_communication_propensity(rows)
        self.assertTrue(fit["message_volume_is_not_a_predictor"])
        self.assertNotIn("communication_tokens", fit["features"])

    def test_entropy_alignment_and_coverage_gate(self):
        log = CommunicationEventLog("run")
        message = generate_instance("hypothesis", 2).information("A", "bit0=0", "m1")
        log.board_write("A", message, message_tokens=1)
        log.peer_read("B", message)
        log.model_output("B", "o1", exposed_message_ids=("m1",), logprob_entropy_bits=2.0,
                         logprob_coverage=1.0, logprob_status="complete")
        rows = first_post_read_outputs(log.events)
        self.assertEqual(rows[0]["event_alignment"], "first_model_output_after_peer_read")
        self.assertEqual(coverage_gate(rows)["status"], "pass")
        self.assertEqual(coverage_gate([{**rows[0], "entropy_bits": None}])["status"], "incomplete_logprob_coverage")

    def test_full_battery_requires_explicit_gate(self):
        decision = LiveGate(max_runs=54, max_cost=1.0).authorize(
            estimated_runs=6480, estimated_cost=10.0, power_decision=None,
            provider_capability=True, stage="full_battery")
        self.assertFalse(decision["authorized"])
        self.assertTrue(decision["reasons"])

    def test_uncertainty_and_paired_contrasts_keep_independent_units(self):
        self.assertEqual(wilson_interval(1, 1)[0] >= 0.0, True)
        rows = [
            PairedOutcome("p1", "hypothesis", "fixture", "ISO", False),
            PairedOutcome("p1", "hypothesis", "fixture", "FULL", True),
            PairedOutcome("p1", "hypothesis", "fixture", "COMM", True),
        ]
        self.assertEqual(paired_contrasts(rows)["FULL-ISO"]["n_pairs"], 1)

    def test_entropy_placebo_and_turn8_gate_are_separate_labels(self):
        assignment = assign_entropy_gate("pair-1", turn8=True)
        self.assertEqual((assignment.arm, assignment.gate_step), ("turn8_exogenous_gate", 8))
        placebo = matched_placebo([{"message_id": "m", "message_tokens": 3}],
                                 [{"message_id": "p", "message_tokens": 3}])
        self.assertEqual(placebo[0]["matching_status"], "yoked")

    def test_capability_smoke_distinguishes_partial_logprob_coverage(self):
        report = {"provider": "openrouter", "model": "free", "rows": [
            {"status": "valid", "logprob_token_count": 2, "logprob_status": "partial"},
        ]}
        gate = evaluate_capability_smoke(report)
        self.assertEqual(gate["status"], "capability_pass")
        self.assertFalse(gate["entropy_coverage_pass"])

    def test_calibration_and_report_are_fixture_only_and_privacy_safe(self):
        report = calibration_report(["hypothesis", "reference"])
        self.assertEqual(report["cell_count"], 6)
        self.assertTrue(report["generator_hints_not_used_for_assignment"])
        self.assertEqual(report["live_pilot"]["status"], "not_run")
        self.assertEqual(len(selected_fixture_instances(["hypothesis"])), 1)
        aggregate = report_from_rows([{"pair_id": "p", "family": "hypothesis", "condition": "ISO",
                                       "success": True, "model": "fixture"}])
        self.assertFalse(aggregate["privacy"]["raw_messages_included"])


if __name__ == "__main__":
    unittest.main()
