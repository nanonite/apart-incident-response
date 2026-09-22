import copy
import json
import unittest
from pathlib import Path

from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_ling_writer_v3 as writer_v3
from apart_incident_response import jev_ling_writer_v5 as writer_v5
from apart_incident_response import jev_replay_preregistration as pr
from apart_incident_response import jev_replay_preregistration_v2 as prv2
from apart_incident_response import jev_replay_preregistration_v3 as prv3
from apart_incident_response import jev_writer_ladder_v5 as ladder
from apart_incident_response import jev_writer_ladder_preregistration_v4 as prv4
from apart_incident_response import jev_writer_ladder_preregistration_v5 as prv5


REPO_ROOT = Path(__file__).resolve().parents[1]


def locked():
    return prv5.build_writer_ladder_preregistration_v5(approved=True, repo_root=REPO_ROOT)


def verify(document, **overrides):
    params = {
        "instance_ids": document["manifest"]["instance_ids"],
        "model": document["model_and_protocol"]["model"],
        "endpoint": document["model_and_protocol"]["endpoint"],
        "protocol_key": document["model_and_protocol"]["protocol_key"],
        "planned_requests": document["caps"]["planned_requests"],
        "repo_root": REPO_ROOT,
    }
    params.update(overrides)
    return prv5.verify_against_writer_ladder_preregistration_v5(document, **params)


class DraftAndLockV4Tests(unittest.TestCase):
    def setUp(self):
        self.draft = prv5.build_writer_ladder_preregistration_v5(repo_root=REPO_ROOT)
        self.doc = locked()

    def test_draft_not_locked_or_authorized(self):
        self.assertEqual(self.draft["status"], prv5.WRITER_LADDER_DRAFT_STATUS)
        self.assertFalse(self.draft["approval"]["approved"])
        self.assertFalse(self.draft["approval"]["live_collection_authorized"])

    def test_locked_not_live_authorized(self):
        self.assertEqual(self.doc["status"], prv5.WRITER_LADDER_LOCKED_STATUS)
        self.assertTrue(self.doc["approval"]["approved"])
        self.assertFalse(self.doc["approval"]["live_collection_authorized"])
        self.assertFalse(self.doc["live_collection_authorized"])

    def test_ladder_and_writer_schema_frozen(self):
        self.assertEqual(self.doc["writer_ladder"], ladder.ladder_schema())
        self.assertEqual(self.doc["writer_observability"], writer_v5.writer_schema())
        self.assertEqual(self.doc["writer_transport"], writer_v3.writer_transport_spec())
        self.assertEqual(self.doc["interpretation_rules"], ladder.INTERPRETATION_RULES)

    def test_caps_and_planned(self):
        caps = self.doc["caps"]
        self.assertEqual(caps["planned_requests"], 493)
        self.assertEqual(caps["planned_ladder_requests"], 408)
        self.assertEqual(caps["planned_bridge_requests"], 85)
        self.assertEqual(caps["physical_requests"], 550)
        self.assertEqual(caps["provider_partition"]["jev"], 250)
        self.assertEqual(caps["provider_partition"]["ling"], 300)
        self.assertEqual(caps["ladder_partition"]["jev"], 216)
        self.assertEqual(caps["ladder_partition"]["ling"], 220)
        self.assertEqual(caps["ladder_partition"]["total"], 436)
        self.assertEqual(caps["bridge_partition"]["jev"], 34)
        self.assertEqual(caps["bridge_partition"]["ling"], 80)
        self.assertEqual(caps["bridge_partition"]["total"], 114)
        # non-overlapping sub-partitions sum exactly to the combined ceiling
        self.assertEqual(caps["ladder_partition"]["jev"] + caps["bridge_partition"]["jev"],
                         caps["provider_partition"]["jev"])
        self.assertEqual(caps["ladder_partition"]["ling"] + caps["bridge_partition"]["ling"],
                         caps["provider_partition"]["ling"])
        self.assertLessEqual(caps["planned_by_provider"]["jev"], caps["provider_partition"]["jev"])
        self.assertLessEqual(caps["planned_by_provider"]["ling"], caps["provider_partition"]["ling"])
        self.assertEqual(caps["cost_cap_usd"],
                         caps["ladder_partition"]["cost_cap_usd"] + caps["bridge_partition"]["cost_cap_usd"])
        self.assertEqual(caps["cost_cap_usd"], 1.0)
        self.assertLessEqual(caps["worst_case_cost_usd"], caps["cost_cap_usd"])

    def test_exact_bridge_and_l5_gate_frozen(self):
        self.assertEqual(self.doc["exact_bridge"]["token_budget"], 1024)
        self.assertEqual(self.doc["exact_bridge"]["turns"], 2)
        self.assertEqual(self.doc["exact_bridge"]["agents"], ["A", "B"])
        self.assertEqual(self.doc["writer_ladder"]["l5_required_owned_fraction"], 1.0)
        self.assertIn("invalid_answer", self.doc["stop_rules"])

    def test_manifest_forms(self):
        self.assertEqual(self.doc["manifest"]["paired_forms"], 6)
        self.assertEqual(len(self.doc["manifest"]["instance_ids"]), 17)

    def test_fresh_paths(self):
        outputs = self.doc["outputs"]
        self.assertEqual(outputs, prv5.output_paths())
        for old in prv5.OLD_OUTPUT_PATHS_V5:
            self.assertNotIn(old, outputs.values())

    def test_locked_hash_reproduces(self):
        self.assertEqual(locked()["preregistration_hash"], self.doc["preregistration_hash"])

    def test_committed_artifact_verifies(self):
        document = json.loads((REPO_ROOT / "runs" / "epic-126"
                               / "jev-writer-ladder-preregistration-v5.json").read_text())
        self.assertTrue(verify(document)["ok"])
        self.assertFalse(document["approval"]["live_collection_authorized"])


class VerifierV4Tests(unittest.TestCase):
    def setUp(self):
        self.doc = locked()

    def test_verify_ok(self):
        self.assertTrue(verify(self.doc)["ok"])

    def test_rejects_draft_and_v1_key(self):
        draft = prv5.build_writer_ladder_preregistration_v5(repo_root=REPO_ROOT)
        self.assertFalse(verify(draft)["ok"])
        self.assertFalse(verify(self.doc, protocol_key=jc.jev_choice_protocol_key())["ok"])

    def test_rejects_old_output_paths(self):
        tampered = copy.deepcopy(self.doc)
        tampered["outputs"]["journal"] = "runs/epic-126/jev-writer-ladder-v4.jsonl"
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("old v1/v2/v3/v4 output path" in error for error in result["errors"]))

    def test_rejects_overlapping_or_drifted_partitions(self):
        for mutate in (
            lambda d: d["caps"]["bridge_partition"].__setitem__("jev", 60),
            lambda d: d["caps"]["ladder_partition"].__setitem__("ling", 300),
            lambda d: d["caps"]["provider_partition"].__setitem__("jev", 999),
            lambda d: d["exact_bridge"].__setitem__("jev_partition", 60),
            lambda d: d["exact_bridge"].__setitem__("token_budget", 96),
            lambda d: d["exact_bridge"].__setitem__("seed_algorithm", "none"),
        ):
            tampered = copy.deepcopy(self.doc)
            mutate(tampered)
            self.assertFalse(verify(tampered)["ok"])

    def test_rejects_ladder_and_timing_drift(self):
        for mutate in (
            lambda d: d["writer_ladder"]["rungs"][0].__setitem__("visible_fields", []),
            lambda d: d["writer_transport"].__setitem__("min_attempt_interval_seconds", 0.25),
            lambda d: d["writer_transport"].__setitem__("max_retries", 9),
            lambda d: d["writer_transport"].__setitem__("supported_retry_headers", ["retry-after"]),
            lambda d: d["interpretation_rules"].__setitem__("no_post_hoc", "pick a winner"),
            lambda d: d["writer_observability"]["outcomes"].append("mystery"),
        ):
            tampered = copy.deepcopy(self.doc)
            mutate(tampered)
            self.assertFalse(verify(tampered)["ok"])

    def test_rejects_source_manifest_cap_and_budget_drift(self):
        tampered = copy.deepcopy(self.doc)
        tampered["generator"]["source_files_hash"] = "0" * 64
        self.assertFalse(verify(tampered)["ok"])
        tampered = copy.deepcopy(self.doc)
        tampered["caps"]["physical_requests"] = 9999
        self.assertFalse(verify(tampered)["ok"])
        self.assertFalse(verify(self.doc, instance_ids=["planning-00000000"])["ok"])
        self.assertFalse(verify(self.doc, planned_requests=600)["ok"])


class ImmutabilityTests(unittest.TestCase):
    def test_v3_v2_v1_artifacts_still_verify(self):
        v3 = json.loads((REPO_ROOT / "runs" / "epic-126"
                         / "jev-choice-replay-preregistration-v3.json").read_text())
        self.assertTrue(prv3.verify_against_jev_replay_preregistration_v3(
            v3, instance_ids=v3["frozen_forms"]["instance_ids"],
            model=v3["model_and_protocol"]["model"], endpoint=v3["model_and_protocol"]["endpoint"],
            protocol_key=v3["model_and_protocol"]["protocol_key"],
            planned_requests=v3["caps"]["planned_physical_requests"], repo_root=REPO_ROOT)["ok"])
        v2 = json.loads((REPO_ROOT / "runs" / "epic-126"
                         / "jev-choice-replay-preregistration-v2.json").read_text())
        self.assertTrue(prv2.verify_against_jev_replay_preregistration_v2(
            v2, instance_ids=v2["frozen_forms"]["instance_ids"],
            model=v2["model_and_protocol"]["model"], endpoint=v2["model_and_protocol"]["endpoint"],
            protocol_key=v2["model_and_protocol"]["protocol_key"],
            planned_requests=v2["caps"]["planned_physical_requests"], repo_root=REPO_ROOT)["ok"])
        v4 = json.loads((REPO_ROOT / "runs" / "epic-126"
                         / "jev-writer-ladder-preregistration-v4.json").read_text())
        self.assertTrue(prv4.verify_against_writer_ladder_preregistration_v4(
            v4, instance_ids=v4["manifest"]["instance_ids"],
            model=v4["model_and_protocol"]["model"], endpoint=v4["model_and_protocol"]["endpoint"],
            protocol_key=v4["model_and_protocol"]["protocol_key"],
            planned_requests=v4["caps"]["planned_requests"], repo_root=REPO_ROOT)["ok"])
        v1 = json.loads((REPO_ROOT / "runs" / "epic-126"
                         / "jev-choice-replay-preregistration.json").read_text())
        self.assertTrue(pr.verify_against_jev_replay_preregistration(
            v1, instance_ids=v1["frozen_forms"]["instance_ids"],
            model=v1["model_and_protocol"]["model"], endpoint=v1["model_and_protocol"]["endpoint"],
            protocol_key=v1["model_and_protocol"]["protocol_key"],
            planned_requests=v1["caps"]["planned_physical_requests"], repo_root=REPO_ROOT)["ok"])

    def test_stopped_v3_artifacts_unchanged(self):
        report = json.loads((REPO_ROOT / "runs" / "epic-126"
                             / "jev-choice-pilot-report-v3.json").read_text())
        self.assertEqual(report["stop_reason"], "missing_verified_exposure")
        journal = (REPO_ROOT / "runs" / "epic-126" / "jev-choice-pilot-v3.jsonl").read_text()
        self.assertEqual(len(journal.splitlines()), 68)


if __name__ == "__main__":
    unittest.main()
