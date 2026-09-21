import copy
import json
import unittest
from pathlib import Path

from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_choice_v2 as jc2
from apart_incident_response import jev_replay_preregistration as pr
from apart_incident_response import jev_replay_preregistration_v2 as prv2


REPO_ROOT = Path(__file__).resolve().parents[1]
CAPABILITY_JOURNAL = REPO_ROOT / "runs" / "epic-126" / "jev-choice-capability.jsonl"


def locked():
    return prv2.build_replay_preregistration_v2(journal_path=CAPABILITY_JOURNAL, approved=True,
                                                repo_root=REPO_ROOT)


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
    return prv2.verify_against_jev_replay_preregistration_v2(document, **params)


class DraftAndLockV2Tests(unittest.TestCase):
    def setUp(self):
        self.draft = prv2.build_replay_preregistration_v2(journal_path=CAPABILITY_JOURNAL,
                                                          repo_root=REPO_ROOT)
        self.doc = locked()

    def test_draft_is_not_locked_or_authorized(self):
        self.assertEqual(self.draft["status"], prv2.JEV_REPLAY_V2_DRAFT_STATUS)
        self.assertFalse(self.draft["approval"]["approved"])
        self.assertFalse(self.draft["approval"]["live_collection_authorized"])

    def test_locked_is_not_live_authorized(self):
        self.assertEqual(self.doc["status"], prv2.JEV_REPLAY_V2_LOCKED_STATUS)
        self.assertTrue(self.doc["approval"]["approved"])
        self.assertFalse(self.doc["approval"]["live_collection_authorized"])
        self.assertEqual(self.doc["pending_decisions"], [])

    def test_v2_codec_and_protocol_key(self):
        protocol = self.doc["model_and_protocol"]
        self.assertEqual(protocol["codec_version"], jc2.JEV_CHOICE_V2_CODEC_VERSION)
        self.assertTrue(protocol["protocol_key"].startswith(jc2.JEV_V2_PROTOCOL_KEY_PREFIX))
        self.assertEqual(protocol["protocol_key"],
                         jc2.jev_choice_protocol_key_v2(model=protocol["model"],
                                                        endpoint=protocol["endpoint"],
                                                        max_retries=pr.JEV_REPLAY_MAX_RETRIES))
        self.assertEqual(prv2.JEV_REPLAY_V2_PROTOCOL_PREFIX, jc2.JEV_V2_PROTOCOL_KEY_PREFIX)

    def test_normalization_policy_is_frozen(self):
        normalization = self.doc["normalization"]
        self.assertEqual(normalization, prv2.normalization_policy())
        tiers = normalization["tiers"]
        self.assertEqual(tiers["exact"]["max_absolute_deviation"], 1e-6)
        self.assertEqual(tiers["complete_renormalized"]["max_absolute_deviation"], 1e-2)
        self.assertTrue(tiers["complete_renormalized"]["boundary_inclusive_with_machine_epsilon"])
        self.assertEqual(tiers["not_normalized_suspect"]["max_absolute_deviation"], 0.05)
        self.assertEqual(tiers["not_normalized_hard"]["min_absolute_deviation_exclusive"], 0.05)
        self.assertEqual(normalization["sensitivity_grid"], [1e-6, 0.01, 0.03, 0.05])
        self.assertEqual(normalization["quantization_bound"], 0.03)
        self.assertEqual(normalization["hard_ceiling"], 0.05)
        self.assertIn("raw_probability_sum",
                      normalization["raw_vs_normalized_metrics"]["raw_retained_separately"])
        self.assertIn("brier_score",
                      normalization["raw_vs_normalized_metrics"]["normalized_vector_used_for"])
        for field in ("option_count", "signed_normalization_deviation", "minimum_probability",
                      "maximum_probability", "zero_count", "all_finite", "all_nonnegative",
                      "raw_argmax_set", "normalization_tier", "argmax_preserved"):
            self.assertIn(field, normalization["diagnostics_fields"])

    def test_determinism_is_recorded_as_stochastic(self):
        determinism = self.doc["determinism"]
        self.assertFalse(determinism["seed_supported"])
        self.assertFalse(determinism["temperature_supported"])
        self.assertEqual(determinism["classification"], "stochastic")
        self.assertEqual(determinism["request_fields_sent"], ["model", "state", "questions"])

    def test_changed_source_and_treatment_hashes(self):
        generator = self.doc["generator"]
        self.assertNotEqual(generator["source_files_hash"], pr._source_files_hash(REPO_ROOT))
        self.assertNotEqual(generator["treatment_hash"], pr.treatment_hash())
        self.assertEqual(generator["manifest_treatment_hash"], pr.treatment_hash())
        self.assertEqual(len(generator["source_files_hash"]), 64)
        self.assertEqual(len(generator["treatment_hash"]), 64)

    def test_fresh_versioned_output_paths(self):
        outputs = self.doc["outputs"]
        self.assertEqual(outputs, prv2.output_paths())
        for value in outputs.values():
            for old in prv2.OLD_OUTPUT_PATHS:
                self.assertNotEqual(value, old)
        self.assertIn("-v2.json", outputs["registration"])
        self.assertIn("-v2.jsonl", outputs["journal"])

    def test_frozen_manifest_and_caps(self):
        forms = self.doc["frozen_forms"]
        self.assertEqual(forms["paired_forms"], 6)
        self.assertEqual(len(forms["instance_ids"]), 17)
        self.assertEqual(self.doc["caps"]["planned_physical_requests"], 102)
        self.assertEqual(self.doc["caps"]["physical_requests"], 300)
        self.assertIn("not_normalized_hard", self.doc["stop_rules"])

    def test_locked_hash_reproduces(self):
        self.assertEqual(locked()["preregistration_hash"], self.doc["preregistration_hash"])


class VerifierV2Tests(unittest.TestCase):
    def setUp(self):
        self.doc = locked()

    def test_verify_ok_on_locked(self):
        result = verify(self.doc)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["expected_protocol_key"], self.doc["model_and_protocol"]["protocol_key"])

    def test_verify_rejects_draft(self):
        draft = prv2.build_replay_preregistration_v2(journal_path=CAPABILITY_JOURNAL, repo_root=REPO_ROOT)
        self.assertFalse(verify(draft)["ok"])

    def test_verify_rejects_v1_protocol_key(self):
        result = verify(self.doc, protocol_key=jc.jev_choice_protocol_key())
        self.assertFalse(result["ok"])
        self.assertTrue(any("v1 protocol key" in error for error in result["errors"]))

    def test_verify_rejects_old_output_path(self):
        tampered = copy.deepcopy(self.doc)
        tampered["outputs"]["journal"] = "runs/epic-126/jev-choice-pilot.jsonl"
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("old v1 output path" in error for error in result["errors"]))

    def test_verify_rejects_tolerance_drift(self):
        tampered = copy.deepcopy(self.doc)
        tampered["normalization"]["tiers"]["complete_renormalized"]["max_absolute_deviation"] = 0.5
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("tolerance drift" in error for error in result["errors"]))

    def test_verify_rejects_hash_and_setting_drift(self):
        tampered = copy.deepcopy(self.doc)
        tampered["caps"]["physical_requests"] = 999
        self.assertFalse(verify(tampered)["ok"])
        tampered = copy.deepcopy(self.doc)
        tampered["normalization"]["sensitivity_grid"] = [1e-6, 0.05]
        self.assertFalse(verify(tampered)["ok"])

    def test_verify_rejects_wrong_manifest_and_overbudget(self):
        self.assertFalse(verify(self.doc, instance_ids=["planning-00000000"])["ok"])
        self.assertFalse(verify(self.doc, planned_requests=pr.JEV_REPLAY_REQUEST_CAP + 1)["ok"])


class ProbeRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.probe = prv2.build_probe_preregistration()

    def test_probe_is_gated_and_not_authorized(self):
        self.assertFalse(self.probe["execution_authorized"])
        self.assertFalse(self.probe["live_collection_authorized"])
        self.assertIn("separate future live approval", self.probe["approval_requirement"])

    def test_probe_targets_identical_request(self):
        source = self.probe["source"]
        self.assertEqual(source["request_hash_prefix"], "2ba516131bdb")
        self.assertTrue(source["request_hash_full"].startswith("2ba516131bdb"))

    def test_probe_k_and_caps(self):
        design = self.probe["design"]
        self.assertEqual(design["k_range"], [12, 20])
        self.assertTrue(12 <= design["frozen_k"] <= 20)
        self.assertEqual(design["frozen_k"], 16)
        self.assertEqual(design["rejection_rates_at"], [1e-6, 0.01, 0.03])
        self.assertEqual(design["stop_if_absolute_deviation_above"], 0.05)
        self.assertFalse(design["independent_prompt_forms"])
        caps = self.probe["caps"]
        self.assertEqual(caps["physical_requests"], prv2.PROBE_REQUEST_CAP)
        self.assertEqual(caps["cost_cap_usd"], prv2.PROBE_COST_CAP_USD)
        self.assertLessEqual(caps["worst_case_cost_usd"], caps["cost_cap_usd"])

    def test_probe_hash_reproduces_and_is_linked_from_registration(self):
        self.assertEqual(prv2.build_probe_preregistration()["probe_hash"], self.probe["probe_hash"])
        document = locked()
        self.assertEqual(document["diagnostic_probe"]["probe_hash"], self.probe["probe_hash"])
        self.assertFalse(document["diagnostic_probe"]["execution_authorized"])
        self.assertEqual(document["diagnostic_probe"]["frozen_k"], 16)


if __name__ == "__main__":
    unittest.main()
