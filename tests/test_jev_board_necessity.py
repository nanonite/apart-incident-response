import json
import math
import unittest
from pathlib import Path

from apart_incident_response import jev_board_necessity as bn
from apart_incident_response import jev_preregistration as jp
from apart_incident_response import task_families as tf
from apart_incident_response.communication_protocol import DependenceRegime, ReasoningComplexity
from apart_incident_response.jev_protocol import audit_instance


REPO_ROOT = Path(__file__).resolve().parents[1]
JOURNAL = REPO_ROOT / "runs" / "epic-126" / "jev-choice-capability.jsonl"
SELECTION = REPO_ROOT / "runs" / "epic-126" / "jev-cell-selection-v1.json"


class EntropyTests(unittest.TestCase):
    def test_entropy_bits(self):
        self.assertEqual(bn.entropy_bits({"a": 1.0}), 0.0)
        self.assertAlmostEqual(bn.entropy_bits({"a": 0.5, "b": 0.5}), 1.0)
        self.assertAlmostEqual(bn.entropy_bits({"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}), 2.0)

    def test_validate_vector(self):
        good = {"status": "complete", "option_ids": ["a", "b"],
                "probabilities": {"a": 0.5, "b": 0.5}}
        self.assertEqual(bn.validate_vector(good), [])
        bad_identity = {"status": "complete", "option_ids": ["a", "b"], "probabilities": {"a": 1.0}}
        self.assertIn("option_identity_mismatch", bn.validate_vector(bad_identity))
        not_normalized = {"status": "complete", "option_ids": ["a", "b"],
                          "probabilities": {"a": 0.5, "b": 0.4}}
        self.assertIn("not_normalized", bn.validate_vector(not_normalized))
        self.assertEqual(bn.validate_vector({"status": "invalid"}), ["status=invalid"])


class SummarizeTests(unittest.TestCase):
    def setUp(self):
        self.instances = jp.jev_capability_instances()
        self.journal = bn.load_journal(JOURNAL)

    def test_summarize_matches_committed_journal(self):
        summary = bn.summarize_jev(self.journal, self.instances)
        self.assertEqual(summary["journal_rows"], 34)
        self.assertEqual(summary["valid_rows"], 34)
        self.assertEqual(summary["invalid_rows"], [])
        self.assertEqual(summary["distinct_request_hashes"], 12)
        self.assertEqual(summary["distinct_prompt_forms"], 6)
        self.assertTrue(summary["option_identity_ok"])
        self.assertTrue(summary["normalization_ok"])
        self.assertGreater(summary["by_condition"]["ISO"]["mean_entropy_bits"], 1.0)
        self.assertLess(summary["by_condition"]["FULL"]["mean_entropy_bits"], 0.1)
        self.assertGreater(summary["mean_delta_entropy_bits"], 1.0)
        self.assertGreater(summary["iso_consistent_mass"], 0.9)
        self.assertEqual(summary["by_condition"]["FULL"]["accepted"], 17)

    def test_structural_need(self):
        need = bn.structural_need(self.instances)
        self.assertEqual(need["instances"], 17)
        self.assertTrue(need["all_pass"])
        self.assertEqual(need["finalizer_needs_peer_count"], 17)
        self.assertEqual(need["channel_complete_count"], 17)


class LingEvidenceTests(unittest.TestCase):
    def test_ling_planning_low_cell(self):
        cell = bn.load_ling_cell(SELECTION)
        self.assertEqual(cell["cell"], "planning:low")
        self.assertAlmostEqual(cell["holm_adjusted_p"], 0.009765625)
        self.assertTrue(cell["significant_fwer_0_05"])
        self.assertEqual(cell["comm"]["used_board"], 14)
        self.assertEqual(cell["comm"]["post_read_correlation_count"], 2)


class CriterionTests(unittest.TestCase):
    def _summary(self, *, iso_h, full_h, delta, mass):
        return {"by_condition": {"ISO": {"mean_entropy_bits": iso_h},
                                 "FULL": {"mean_entropy_bits": full_h}},
                "mean_delta_entropy_bits": delta, "iso_consistent_mass": mass}

    def setUp(self):
        self.need = {"instances": 17, "finalizer_needs_peer_count": 17}
        self.ling = {"holm_adjusted_p": 0.0098}

    def test_advances_on_real_like_values(self):
        result = bn.ceiling_assessment(self._summary(iso_h=1.28, full_h=0.005, delta=1.28, mass=0.98),
                                       self.need, self.ling)
        self.assertEqual(result["decision"], "advance")
        self.assertFalse(result["criterion"]["note"].startswith("preregistered"))

    def test_redesigns_when_iso_entropy_is_at_floor(self):
        result = bn.ceiling_assessment(self._summary(iso_h=0.0, full_h=0.005, delta=0.0, mass=0.98),
                                       self.need, self.ling)
        self.assertEqual(result["decision"], "redesign")
        failed = {item["check"] for item in result["checks"] if not item["ok"]}
        self.assertIn("iso_entropy_above_floor", failed)

    def test_redesigns_when_iso_mass_not_on_consistent_set(self):
        result = bn.ceiling_assessment(self._summary(iso_h=1.28, full_h=0.005, delta=1.28, mass=0.5),
                                       self.need, self.ling)
        self.assertEqual(result["decision"], "redesign")


class ManifestAndReportTests(unittest.TestCase):
    def test_proposed_j5_block_is_disjoint_and_leak_clean(self):
        proposed = bn.proposed_j5_manifest()
        ids = set(proposed["instance_ids"])
        self.assertEqual(proposed["seed_base"], 72000)
        self.assertEqual(len(ids), 17)
        j3 = {instance.instance_id for instance in jp.jev_capability_instances()}
        planning_low = set(json.loads((REPO_ROOT / "runs" / "epic-126"
                                       / "jev-planning-low-manifest.json").read_text())["instance_ids"])
        self.assertFalse(ids & j3)
        self.assertFalse(ids & planning_low)
        instances = [tf.generate_instance("planning", 72000 + r, DependenceRegime.N, ReasoningComplexity.LOW)
                     for r in range(17)]
        self.assertTrue(all(audit_instance(instance)["all_pass"] for instance in instances))

    def test_build_report_decisions(self):
        report = bn.build_report(journal_path=JOURNAL, selection_path=SELECTION)
        self.assertEqual(report["version"], bn.BOARD_NECESSITY_VERSION)
        decisions = {row["cell"]: row["decision"] for row in report["candidate_decisions"]}
        self.assertEqual(decisions["planning:low"], "advance")
        for held in ("hypothesis:low", "hypothesis:medium", "planning:high", "reference:low"):
            self.assertEqual(decisions[held], "hold")
        self.assertEqual(report["ceiling_assessment"]["decision"], "advance")
        self.assertTrue(report["notes"]["p_value_is_not_an_entropy_gate"])
        self.assertTrue(report["notes"]["repeated_query_not_independent"])
        self.assertEqual(report["proposed_j5_manifest"]["status"], "draft_pending_review")


if __name__ == "__main__":
    unittest.main()
