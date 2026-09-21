import copy
import json
import unittest
from pathlib import Path

from apart_incident_response import jev_replay_preregistration as pr
from apart_incident_response.jev_choice import JEV_CHOICE_CODEC_VERSION, jev_choice_protocol_key


REPO_ROOT = Path(__file__).resolve().parents[1]
JOURNAL = REPO_ROOT / "runs" / "epic-126" / "jev-choice-capability.jsonl"


def locked():
    return pr.build_replay_preregistration(journal_path=JOURNAL, approved=True, repo_root=REPO_ROOT)


def verify(document, **overrides):
    params = {
        "instance_ids": document["frozen_forms"]["instance_ids"],
        "model": document["model_and_protocol"]["model"],
        "endpoint": document["model_and_protocol"]["endpoint"],
        "protocol_key": document["model_and_protocol"]["protocol_key"],
        "planned_requests": document["caps"]["planned_physical_requests"],
        "repo_root": REPO_ROOT,
    }
    params.update(overrides)
    return pr.verify_against_jev_replay_preregistration(document, **params)


class DraftAndLockTests(unittest.TestCase):
    def setUp(self):
        self.draft = pr.build_replay_preregistration(journal_path=JOURNAL, repo_root=REPO_ROOT)
        self.doc = locked()

    def test_draft_is_not_locked_or_authorized(self):
        self.assertEqual(self.draft["status"], pr.JEV_REPLAY_DRAFT_STATUS)
        self.assertFalse(self.draft["approval"]["approved"])
        self.assertFalse(self.draft["approval"]["live_collection_authorized"])

    def test_locked_is_not_live_authorized(self):
        self.assertEqual(self.doc["status"], pr.JEV_REPLAY_LOCKED_STATUS)
        self.assertTrue(self.doc["approval"]["approved"])
        self.assertFalse(self.doc["approval"]["live_collection_authorized"])
        self.assertEqual(self.doc["pending_decisions"], [])

    def test_frozen_manifest_and_forms(self):
        forms = self.doc["frozen_forms"]
        self.assertEqual(forms["paired_forms"], 6)
        self.assertEqual(len(forms["instance_ids"]), 17)
        self.assertEqual(len(forms["manifest_hash"]), 64)
        self.assertEqual(self.doc["manifest"]["manifest_hash"], forms["manifest_hash"])

    def test_caps_and_worst_case_accounting(self):
        caps = self.doc["caps"]
        self.assertEqual(caps["planned_physical_requests"], 102)
        self.assertEqual(caps["physical_requests"], 300)
        self.assertEqual(caps["retry_reserve"], 198)
        self.assertLessEqual(caps["worst_case_cost_usd"], caps["cost_cap_usd"])
        partition = caps["provider_partition"]
        self.assertEqual(partition["jev"] + partition["ling"], partition["total"])
        self.assertEqual(partition["total"], pr.JEV_REPLAY_REQUEST_CAP)
        self.assertEqual(caps["planned_by_provider"], {"jev": 68, "ling": 34})
        self.assertIn("locked", caps["status"])

    def test_conditions_include_turn_matched_control(self):
        conditions = self.doc["conditions"]
        self.assertEqual(conditions["condition_turns"], {"ISO": 1, "FULL": 1, "COMM": 2})
        self.assertIn("turn_matched_control", conditions)
        self.assertIn("no real board write", conditions["turn_matched_control"]["description"])
        self.assertTrue(conditions["optional_silence"])
        self.assertEqual(len(conditions["arms"]), 4)

    def test_generator_hashes_and_invalidity_classes(self):
        generator = self.doc["generator"]
        self.assertEqual(len(generator["source_files_hash"]), 64)
        self.assertEqual(len(generator["treatment_hash"]), 64)
        self.assertTrue(self.doc["invalidity_classes"])
        self.assertIn("unverified_real_evidence", self.doc["invalidity_classes"])

    def test_locked_hash_reproduces(self):
        self.assertEqual(locked()["preregistration_hash"], self.doc["preregistration_hash"])

    def test_ling_contract_is_frozen(self):
        ling = self.doc["ling_contract"]
        self.assertTrue(ling["model"])
        self.assertEqual(ling["endpoint"], pr.LING_ENDPOINT)
        self.assertEqual(ling["max_tokens"], 64)
        self.assertEqual(ling["temperature"], 0.0)
        self.assertEqual(ling["backoff_initial_seconds"], 0.5)
        self.assertEqual(ling["backoff_max_seconds"], 5.0)
        self.assertEqual(len(ling["contract_hash"]), 64)


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.doc = locked()

    def test_verify_ok_on_locked(self):
        result = verify(self.doc)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["expected_protocol_key"], self.doc["model_and_protocol"]["protocol_key"])

    def test_verify_rejects_draft(self):
        draft = pr.build_replay_preregistration(journal_path=JOURNAL, repo_root=REPO_ROOT)
        self.assertFalse(verify(draft)["ok"])

    def test_verify_rejects_hash_or_setting_drift(self):
        tampered = copy.deepcopy(self.doc)
        tampered["caps"]["physical_requests"] = 999
        self.assertFalse(verify(tampered)["ok"])
        tampered = copy.deepcopy(self.doc)
        tampered["guards"]["feasible_set_mass"]["epsilon"] = 0.5
        self.assertFalse(verify(tampered)["ok"])

    def test_verify_rejects_wrong_manifest(self):
        self.assertFalse(verify(self.doc, instance_ids=["planning-00000000"])["ok"])

    def test_verify_rejects_mixed_protocol_and_overbudget(self):
        self.assertFalse(verify(self.doc, protocol_key="six-family-clue-consistent-v2|a|b|c|d|e")["ok"])
        self.assertFalse(verify(self.doc, planned_requests=pr.JEV_REPLAY_REQUEST_CAP + 1)["ok"])

    def test_protocol_key_matches_codec(self):
        self.assertEqual(self.doc["model_and_protocol"]["protocol_key"],
                         jev_choice_protocol_key(model=self.doc["model_and_protocol"]["model"],
                                                 endpoint=self.doc["model_and_protocol"]["endpoint"],
                                                 max_retries=pr.JEV_REPLAY_MAX_RETRIES,
                                                 instructions=__import__(
                                                     "apart_incident_response.jev_choice",
                                                     fromlist=["JEV_CHOICE_INSTRUCTIONS"]).JEV_CHOICE_INSTRUCTIONS,
                                                 question_id="candidate"))
        self.assertEqual(self.doc["model_and_protocol"]["codec_version"], JEV_CHOICE_CODEC_VERSION)


if __name__ == "__main__":
    unittest.main()
