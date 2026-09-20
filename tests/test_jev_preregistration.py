import hashlib
import json
import unittest
from pathlib import Path

from apart_incident_response import jev_preregistration as jp
from apart_incident_response.jev_choice import (
    JEV_CHOICE_CODEC_VERSION,
    JEV_CHOICE_INSTRUCTIONS,
    JEV_QUESTION_ID,
    is_jev_protocol_key,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def build(approved=False):
    return jp.build_jev_choice_capability_preregistration(repo_root=REPO_ROOT, approved=approved)


def verify(document, **overrides):
    params = {
        "instance_ids": document["jev_capability"]["instance_ids"],
        "model": document["provider_settings"]["model"],
        "endpoint": document["provider_settings"]["endpoint"],
        "codec_version": document["provider_settings"]["codec_version"],
        "question_id": document["provider_settings"]["question_id"],
        "instructions": document["provider_settings"]["instructions"],
        "planned_requests": document["jev_capability"]["planned_requests"],
    }
    params.update(overrides)
    return jp.verify_against_jev_choice_preregistration(document, **params)


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.doc = build()

    def test_default_is_draft_and_not_approved(self):
        self.assertEqual(self.doc["preregistration_version"], jp.JEV_CAPABILITY_VERSION)
        self.assertEqual(self.doc["status"], "draft_pending_review")
        self.assertTrue(self.doc["approval_required"])
        self.assertFalse(self.doc["approval"]["approved"])
        self.assertEqual(self.doc["jev_capability"]["status"], "proposed")

    def test_manifest_is_seventeen_held_out_instances(self):
        ids = self.doc["jev_capability"]["instance_ids"]
        self.assertEqual(len(ids), 17)
        expected = hashlib.sha256(json.dumps(ids, sort_keys=True).encode()).hexdigest()
        self.assertEqual(self.doc["jev_capability"]["manifest_hash"], expected)
        self.assertEqual(self.doc["jev_capability"]["seed_base"], 71000)
        self.assertTrue(self.doc["jev_capability"]["leak_audit"]["all_pass"])

    def test_disjoint_from_planning_low_manifest_and_smoke(self):
        planning_low = json.loads((REPO_ROOT / jp.JEV_PLANNING_LOW_MANIFEST).read_text(encoding="utf-8"))
        ids = set(self.doc["jev_capability"]["instance_ids"])
        self.assertFalse(ids & set(planning_low["instance_ids"]))
        held_out = self.doc["jev_capability"]["held_out"]
        self.assertFalse(ids & set(held_out["smoke_instance_ids"]))
        self.assertEqual(held_out["disjoint_from_planning_low_manifest_hash"], planning_low["manifest_hash"])

    def test_protocol_key_is_jev_and_bound(self):
        key = self.doc["provider_settings"]["expected_protocol_key"]
        self.assertTrue(is_jev_protocol_key(key))
        self.assertEqual(key, self.doc["protocol_boundary"]["jev_protocol_key"])
        self.assertEqual(self.doc["provider_settings"]["codec_version"], JEV_CHOICE_CODEC_VERSION)

    def test_instructions_are_condition_neutral(self):
        wording = self.doc["provider_settings"]["instructions"].lower()
        self.assertEqual(self.doc["provider_settings"]["instructions"], JEV_CHOICE_INSTRUCTIONS)
        self.assertEqual(self.doc["provider_settings"]["question_id"], JEV_QUESTION_ID)
        self.assertNotIn("exactly one", wording)
        self.assertNotIn("unique", wording)

    def test_caps_and_diagnostics_declared(self):
        caps = self.doc["caps"]
        self.assertEqual(caps["max_requests"], jp.JEV_CAPABILITY_REQUEST_CAP)
        self.assertEqual(caps["max_cost_usd"], 1.0)
        self.assertLessEqual(caps["estimated_cost_ceiling_usd"], caps["max_cost_usd"])
        self.assertLess(caps["estimated_cost_planned_usd"], caps["estimated_cost_ceiling_usd"])
        self.assertEqual(set(self.doc["jev_capability"]["conditions_run"]), {"ISO", "FULL"})
        for excluded in ("COMM", "Noul", "Score"):
            self.assertIn(excluded, self.doc["jev_capability"]["diagnostics_not_run"])
        self.assertIn("full_vector_validity", self.doc["capability_metrics"]["primary"])
        self.assertIn("reliability_bins", self.doc["calibration_diagnostics"]["primary"])

    def test_hash_is_reproducible_and_stable(self):
        self.assertEqual(build()["preregistration_hash"], self.doc["preregistration_hash"])

    def test_approved_registration_is_locked(self):
        locked = build(approved=True)
        self.assertEqual(locked["status"], "locked_for_jev_choice_capability")
        self.assertTrue(locked["approval"]["approved"])
        self.assertEqual(locked["jev_capability"]["status"], "locked")
        self.assertNotEqual(locked["preregistration_hash"], self.doc["preregistration_hash"])


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.doc = build(approved=True)

    def test_verify_ok_when_locked_and_matching(self):
        result = verify(self.doc)
        self.assertTrue(result["ok"], result["errors"])
        self.assertTrue(is_jev_protocol_key(result["expected_protocol_key"]))

    def test_verify_rejects_draft(self):
        result = verify(build(approved=False))
        self.assertFalse(result["ok"])
        self.assertTrue(any("not locked" in error for error in result["errors"]))

    def test_verify_rejects_setting_drift(self):
        self.assertFalse(verify(self.doc, model="jev-1.13.1")["ok"])
        self.assertFalse(verify(self.doc, endpoint="https://example.invalid")["ok"])
        self.assertFalse(verify(self.doc, codec_version="other")["ok"])
        self.assertFalse(verify(self.doc, question_id="other")["ok"])
        self.assertFalse(verify(self.doc, instructions="Different wording.")["ok"])

    def test_verify_rejects_manifest_and_cap_drift(self):
        self.assertFalse(verify(self.doc, instance_ids=["planning-00000000"])["ok"])
        self.assertFalse(verify(self.doc, planned_requests=jp.JEV_CAPABILITY_REQUEST_CAP + 1)["ok"])


if __name__ == "__main__":
    unittest.main()
