import json
import unittest
from pathlib import Path

from apart_incident_response import jev_replay_preregistration as pr


REPO_ROOT = Path(__file__).resolve().parents[1]
JOURNAL = REPO_ROOT / "runs" / "epic-126" / "jev-choice-capability.jsonl"


def j3_hashes():
    rows = [json.loads(line) for line in JOURNAL.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {str(row["request_hash"]) for row in rows}


class CapacityTests(unittest.TestCase):
    def test_capacity_is_six_paired_forms(self):
        audit = pr.audit_form_capacity(j3_hashes=j3_hashes())
        self.assertEqual(audit["capacity_paired_forms"], 6)
        self.assertEqual(audit["union_distinct_request_forms"], 12)
        self.assertEqual(audit["blocks"]["72000"]["new_forms_vs_j3"], 0)
        self.assertEqual(audit["blocks"]["74000"]["new_forms_vs_j3"], 0)
        self.assertIn("generator redesign", audit["recommendation"])

    def test_between_form_sd_is_illustrative(self):
        rows = [json.loads(line) for line in JOURNAL.read_text(encoding="utf-8").splitlines() if line.strip()]
        sd = pr.between_form_sd(rows)
        self.assertAlmostEqual(sd, 0.193, places=2)

    def test_illustrative_required_forms_is_monotone(self):
        self.assertIsNotNone(pr.illustrative_required_forms(0.2, 0.193))
        self.assertGreater(pr.illustrative_required_forms(0.1, 0.193),
                           pr.illustrative_required_forms(0.2, 0.193))
        self.assertIsNone(pr.illustrative_required_forms(0.0, 0.193))


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.doc = pr.build_replay_preregistration(journal_path=JOURNAL)

    def test_draft_is_not_locked_or_authorized(self):
        self.assertEqual(self.doc["status"], "draft_pending_review")
        self.assertTrue(self.doc["approval_required"])
        self.assertFalse(self.doc["approval"]["approved"])
        self.assertFalse(self.doc["approval"]["live_collection_authorized"])

    def test_estimand_and_guards_frozen(self):
        self.assertEqual(self.doc["estimand"]["event_difference"], "H_real - H_placebo")
        self.assertEqual(self.doc["estimand"]["directional_prediction"], "delta < 0")
        self.assertIn("equal-weight mean", self.doc["estimand"]["estimand"])
        self.assertIn("pre-read clue-consistent set", self.doc["guards"]["feasible_set_mass"]["reference_set"])
        self.assertEqual(self.doc["claim_scope"]["forms"], 6)
        self.assertEqual(self.doc["claim_scope"]["type"], "form-conditioned")

    def test_pending_decisions_and_caps(self):
        self.assertTrue(self.doc["pending_decisions"])
        self.assertEqual(self.doc["caps"]["physical_requests"], pr.DRAFT_REQUEST_CAP)
        self.assertEqual(self.doc["caps"]["status"], "draft; not authorized")
        self.assertIn("not authorized", json.dumps(self.doc["caps"]))

    def test_hash_is_reproducible(self):
        self.assertEqual(pr.build_replay_preregistration(journal_path=JOURNAL)["preregistration_hash"],
                         self.doc["preregistration_hash"])


if __name__ == "__main__":
    unittest.main()
