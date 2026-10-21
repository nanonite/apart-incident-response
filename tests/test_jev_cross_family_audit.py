"""Offline checks for #227's source-bound capacity decision."""

import hashlib
import json
from pathlib import Path
import unittest

from apart_incident_response import jev_cross_family_audit as audit
from apart_incident_response import task_families as tasks
from apart_incident_response.communication_protocol import DependenceRegime, ReasoningComplexity


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / audit.ARTIFACT_PATH


class CrossFamilyAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.published_bytes = ARTIFACT.read_bytes()
        cls.published = json.loads(cls.published_bytes)
        cls.rebuilt = audit.build(ROOT)

    def test_rebuild_is_byte_identical_and_offline(self):
        self.assertEqual(self.published_bytes, audit._render(self.rebuilt))
        self.assertEqual(self.rebuilt["provider_calls"], 0)
        self.assertEqual(self.rebuilt["network_audit_events"], [])
        self.assertEqual(self.rebuilt["content_hash"], audit._content_hash(self.rebuilt))

    def test_inputs_are_real_file_pins(self):
        for path, digest in self.rebuilt["inputs_sha256"].items():
            with self.subTest(path=path):
                self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), digest)
                self.assertEqual(digest, audit.INPUT_PINS[path])

    def test_fresh_windows_and_inventory_exceptions(self):
        windows = self.rebuilt["windows"]["selected"]
        self.assertEqual([(w["base"], w["end"]) for w in windows],
                         [(90000, 90511), (91000, 91511)])
        self.assertEqual(sum(w["window"] for w in windows), 1024)
        self.assertTrue(self.rebuilt["inventory"]["overlap_qualified_by_audit_exceptions"])
        self.assertTrue(self.rebuilt["inventory"]["inaccessible_manifests"])
        self.assertTrue(self.rebuilt["inventory"]["inaccessible_directories"])

    def test_every_supported_remaining_cell_reported(self):
        cells = self.rebuilt["cells"]
        self.assertEqual({(c["family"], c["complexity"], c["regime"]) for c in cells},
                         {(family, complexity.value, DependenceRegime.N.value)
                          for family in audit.FAMILIES for complexity in ReasoningComplexity})
        for cell in cells:
            with self.subTest(cell=(cell["family"], cell["complexity"])):
                self.assertEqual(cell["k"], 4)
                self.assertEqual(cell["two_sided_sign_flip_floor"], 0.125)
                self.assertEqual(sum(cell["discovery_per_form_capacity"].values()), 512)
                self.assertEqual(sum(cell["closure_probe_per_form_capacity"].values()), 512)
                self.assertEqual(set(cell["discovery_per_form_capacity"]),
                                 set(cell["closure_probe_per_form_capacity"]))
                self.assertEqual(len(cell["state_semantics"]["shared_template_hashes"]), 1)
                self.assertFalse(cell["unadjusted_alpha_0_05_best_case_attainable"])
                self.assertFalse(cell["holm_7_or_8_first_step_best_case_attainable"])

    def test_reference_high_no_go_is_real_generator_defect(self):
        cell = next(c for c in self.rebuilt["cells"]
                    if c["family"] == "reference" and c["complexity"] == "high")
        self.assertEqual(cell["classification"], "no_go_structural_or_semantic")
        self.assertEqual(cell["structural"]["finalizer_needs_peer"], 516)
        self.assertEqual(cell["structural"]["authoritative_b_owned_informative"], 516)
        self.assertEqual(len(cell["state_semantics"]["forms_with_multiple_authoritative_a_sets"]), 4)
        witnesses = {}
        for seed in range(90000, 90512):
            instance = tasks.generate_instance("reference", seed, DependenceRegime.N,
                                               ReasoningComplexity.HIGH)
            key = tuple(instance.private_clues["A"])
            value = tuple(sorted(instance.private_solutions["A"]))
            earlier = witnesses.get(key)
            if earlier is not None and earlier != value:
                break
            witnesses[key] = value
        else:
            self.fail("no witnessed same-visible-clue / different-authoritative-set collision")

    def test_holm_best_case_is_arithmetic_not_claim(self):
        self.assertEqual({row["hypotheses"]: row["minimum_k_for_best_case_first_step"]
                          for row in self.rebuilt["holm_best_case_attainability"]},
                         {1: 6, 2: 7, 7: 9, 8: 9})
        self.assertEqual(self.rebuilt["breadth"]["existing_generator_families"], 6)
        self.assertEqual(self.rebuilt["breadth"]["proposed_additional_families"], 2)
        self.assertEqual(self.rebuilt["queue"]["historical_frozen"],
                         list(audit.HISTORICAL_QUEUE))
        self.assertTrue(all(p["status"] == "proposal_only_not_audited_or_runnable"
                            for p in self.rebuilt["proposals"]))
        for proposal in self.rebuilt["proposals"]:
            self.assertEqual(len(set(proposal["fixed_choice_options"])), 4)
            self.assertTrue(proposal["offline_validation_needs"])


if __name__ == "__main__":
    unittest.main()
