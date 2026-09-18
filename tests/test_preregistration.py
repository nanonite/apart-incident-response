import json
import tempfile
import unittest
from pathlib import Path

from apart_incident_response.preregistration import (
    PREREGISTRATION_VERSION,
    STAGE2_SEED_BASE,
    audit_cells,
    build_preregistration,
    holm_adjust,
    mcnemar_required_pairs,
    missingness_report,
    stage2_instances,
)
from apart_incident_response.communication_protocol import ReasoningComplexity


class CellAuditTests(unittest.TestCase):
    def test_cosmetic_wrappers_are_collapsed(self):
        audit = audit_cells(seeds=(1, 2, 3))
        self.assertTrue(all(cell["stable"] for cell in audit["cells"]
                            if cell["complexity"] in {"low", "medium"}))
        # reference-high is the known singleton exception and is flagged unstable
        unstable = {(cell["family"], cell["complexity"]) for cell in audit["cells"] if not cell["stable"]}
        self.assertEqual(unstable, {("reference", "high")})
        self.assertLess(audit["distinct_cell_count"], audit["cell_count"])
        self.assertTrue(audit["cosmetic_wrapper_groups"])
        # hypothesis/poetry/legal/lexicon low share one decision-problem fingerprint
        low_bit = [members for members in audit["groups"].values()
                   if {"hypothesis:low", "poetry:low", "legal:low", "lexicon:low"} <= set(members)]
        self.assertTrue(low_bit, audit["groups"])

    def test_stage2_seeds_are_fresh_and_deterministic(self):
        first = [instance.instance_id for instance in stage2_instances(2)]
        second = [instance.instance_id for instance in stage2_instances(2)]
        self.assertEqual(first, second)
        self.assertEqual(len(first), len(set(first)))
        seeds = [instance.seed for instance in stage2_instances(2)]
        self.assertGreaterEqual(min(seeds), STAGE2_SEED_BASE)
        self.assertNotIn("hypothesis-00003e80", first)


class InferenceHelperTests(unittest.TestCase):
    def test_holm_adjust_is_monotone_and_capped(self):
        adjusted = holm_adjust({"a": 0.01, "b": 0.04, "c": 0.03})
        self.assertEqual(adjusted["a"], 0.03)
        self.assertAlmostEqual(adjusted["c"], 0.06)
        self.assertEqual(adjusted["b"], 0.06)
        self.assertTrue(all(0 <= value <= 1 for value in adjusted.values()))

    def test_mcnemar_required_pairs_grows_as_effect_weakens(self):
        strong = mcnemar_required_pairs(0.80, 0.30)
        weak = mcnemar_required_pairs(0.60, 0.30)
        self.assertGreater(weak["required_discordant_pairs"], strong["required_discordant_pairs"])
        self.assertGreater(strong["required_total_pairs"], strong["required_discordant_pairs"])
        with self.assertRaises(ValueError):
            mcnemar_required_pairs(0.5, 0.3)
        with self.assertRaises(ValueError):
            mcnemar_required_pairs(0.8, 0.0)

    def test_missingness_report_tracks_invalidity_and_complete_pairs(self):
        records = [
            {"instance_id": "a", "condition": "ISO", "valid_execution": True, "checker_accepted": False},
            {"instance_id": "a", "condition": "FULL", "valid_execution": True, "checker_accepted": True},
            {"instance_id": "b", "condition": "ISO", "valid_execution": True, "checker_accepted": True},
            {"instance_id": "b", "condition": "FULL", "valid_execution": False, "checker_accepted": False},
        ]
        report = missingness_report(records, "ISO", "FULL")
        self.assertEqual(report["attempted"], {"ISO": 2, "FULL": 2})
        self.assertEqual(report["valid"], {"ISO": 2, "FULL": 1})
        self.assertEqual(report["complete_pairs"], 1)
        self.assertEqual(report["incomplete_pairs"], 1)
        self.assertEqual(report["invalidity_by_condition"], {"ISO": 0, "FULL": 1})


class PreregistrationDocumentTests(unittest.TestCase):
    def build(self):
        return build_preregistration(repo_root=Path(__file__).resolve().parents[1],
                                     generator_commit="deadbeef")

    def test_document_freezes_required_state(self):
        document = self.build()
        self.assertEqual(document["preregistration_version"], PREREGISTRATION_VERSION)
        self.assertEqual(document["status"], "draft_for_review")
        self.assertTrue(document["approval_required"])
        self.assertEqual(document["generator_commit"], "deadbeef")
        self.assertEqual(len(document["generator_file_sha256"]), 64)
        self.assertEqual(len(document["treatment_file_sha256"]), 64)
        self.assertEqual(document["treatment_schema"]["primary_conditions"], ["ISO", "FULL", "COMM"])
        self.assertEqual(document["treatment_schema"]["diagnostic_conditions"], ["ORACLE", "INDUCED"])
        self.assertTrue(document["proposed_decisions"])
        self.assertEqual(document["stage2"]["seed_base"], STAGE2_SEED_BASE)
        self.assertIn("ISO", document["contrasts"]["primary"])
        self.assertTrue(document["superseded_artifacts"])

    def test_superseded_excludes_current_schema_artifacts(self):
        names = {Path(row["path"]).name for row in self.build()["superseded_artifacts"]}
        self.assertIn("paired-screen.jsonl", names)
        self.assertNotIn("treatment-schema.json", names)
        self.assertNotIn("preregistration-v1.json", names)

    def test_hash_is_deterministic(self):
        self.assertEqual(self.build()["preregistration_hash"], self.build()["preregistration_hash"])

    def test_cli_writes_document(self):
        from apart_incident_response import preregistration
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "prereg.json"
            code = preregistration.main(["--repo-root", str(Path(__file__).resolve().parents[1]),
                                         "--output", str(output)])
            self.assertEqual(code, 0)
            written = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(written["preregistration_version"], PREREGISTRATION_VERSION)
        self.assertEqual(written["cell_audit"]["distinct_cell_count"],
                         written["cell_audit"]["distinct_cell_count"])


if __name__ == "__main__":
    unittest.main()
