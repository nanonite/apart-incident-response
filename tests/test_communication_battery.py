import unittest

from apart_incident_response.communication_analysis import PairedOutcome, fit_communication_propensity, paired_metrics
from apart_incident_response.communication_calibration import calibration_report, selected_fixture_instances
from apart_incident_response.communication_entropy import coverage_gate, first_post_read_outputs
from apart_incident_response.communication_events import CommunicationEventLog
from apart_incident_response.communication_protocol import (
    BatteryCondition, BatteryProtocol, DependenceRegime, directional_d_idx,
)
from apart_incident_response.communication_runner import AgentResponse, TwoAgentBatteryRunner
from apart_incident_response.finite_information import ExactInformationEvaluator, FeasibleSet, MessageInterpretation
from apart_incident_response.live_gate import LiveGate
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
            self.assertEqual(len(report["cells"]), 9)
            self.assertEqual({cell["regime"] for cell in report["cells"]}, {"R", "H", "N"})

    def test_hypothesis_trajectory_is_auditable(self):
        instance = generate_instance("hypothesis", 4, DependenceRegime.N)
        trajectory = instance.trajectory("A", tuple(claim.text for claim in instance.claims[:3]))
        self.assertEqual([(row.before_count, row.after_count, row.delta_i_bits) for row in trajectory],
                         [(8, 4, 1.0), (4, 2, 1.0), (2, 1, 1.0)])

    def test_provenance_distinguishes_read_output_and_verified_use(self):
        log = CommunicationEventLog("run")
        message = generate_instance("hypothesis", 1).information("A", "bit0=0", "m1")
        log.board_write("A", message, message_tokens=1)
        log.peer_read("B", message)
        log.peer_read("B", message)
        log.model_output("B", "o1", exposed_message_ids=("m1",), logprob_entropy_bits=1.2,
                         logprob_coverage=1.0, logprob_status="complete")
        log.verified_use("B", message, "o1", checker_evidence={"verified": True})
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

    def test_analysis_retains_invalid_denominators_and_does_not_use_volume_for_phi(self):
        rows = [
            PairedOutcome("p", "hypothesis", "fixture", "ISO", False, communication_tokens=9),
            PairedOutcome("p", "hypothesis", "fixture", "FULL", True, communication_tokens=1),
            PairedOutcome("p", "hypothesis", "fixture", "COMM", True, useful_bits=1, communication_tokens=99),
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

    def test_calibration_and_report_are_fixture_only_and_privacy_safe(self):
        report = calibration_report(["hypothesis", "reference"])
        self.assertEqual(report["cell_count"], 18)
        self.assertTrue(report["generator_hints_not_used_for_assignment"])
        self.assertEqual(report["live_pilot"]["status"], "not_run")
        self.assertEqual(len(selected_fixture_instances(["hypothesis"])), 2)
        aggregate = report_from_rows([{"pair_id": "p", "family": "hypothesis", "condition": "ISO",
                                       "success": True, "model": "fixture"}])
        self.assertFalse(aggregate["privacy"]["raw_messages_included"])


if __name__ == "__main__":
    unittest.main()
