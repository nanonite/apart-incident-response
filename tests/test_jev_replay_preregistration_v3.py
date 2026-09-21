import copy
import json
import unittest
from pathlib import Path

from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_choice_v2 as jc2
from apart_incident_response import jev_ling_writer_v3 as writer_v3
from apart_incident_response import jev_replay_preregistration as pr
from apart_incident_response import jev_replay_preregistration_v2 as prv2
from apart_incident_response import jev_replay_preregistration_v3 as prv3


REPO_ROOT = Path(__file__).resolve().parents[1]
CAPABILITY_JOURNAL = REPO_ROOT / "runs" / "epic-126" / "jev-choice-capability.jsonl"


def locked():
    return prv3.build_replay_preregistration_v3(journal_path=CAPABILITY_JOURNAL, approved=True,
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
    return prv3.verify_against_jev_replay_preregistration_v3(document, **params)


class DraftAndLockV3Tests(unittest.TestCase):
    def setUp(self):
        self.draft = prv3.build_replay_preregistration_v3(journal_path=CAPABILITY_JOURNAL,
                                                          repo_root=REPO_ROOT)
        self.doc = locked()

    def test_draft_is_not_locked_or_authorized(self):
        self.assertEqual(self.draft["status"], prv3.JEV_REPLAY_V3_DRAFT_STATUS)
        self.assertFalse(self.draft["approval"]["approved"])
        self.assertFalse(self.draft["approval"]["live_collection_authorized"])

    def test_locked_is_not_live_authorized(self):
        self.assertEqual(self.doc["status"], prv3.JEV_REPLAY_V3_LOCKED_STATUS)
        self.assertTrue(self.doc["approval"]["approved"])
        self.assertFalse(self.doc["approval"]["live_collection_authorized"])
        self.assertEqual(self.doc["pending_decisions"], [])

    def test_writer_transport_is_frozen(self):
        transport = self.doc["writer_transport"]
        self.assertEqual(transport, prv3.writer_transport())
        self.assertEqual(transport["writer_transport_version"], writer_v3.LING_WRITER_TRANSPORT_VERSION)
        self.assertEqual(transport["min_attempt_interval_seconds"], 3.25)
        self.assertEqual(transport["pacing_algorithm"], writer_v3.LING_PACING_ALGORITHM)
        self.assertEqual(transport["monotonic_clock"], "time.monotonic")
        self.assertEqual(transport["supported_retry_headers"], ["retry-after", "retry-after-ms"])
        self.assertEqual(transport["max_server_requested_delay_seconds"], 10.0)
        self.assertEqual(transport["max_retries"], 2)
        self.assertEqual(transport["backoff_initial_seconds"], 0.5)
        self.assertEqual(transport["backoff_max_seconds"], 5.0)
        self.assertEqual(transport["provenance_fields"], list(writer_v3.LING_PROVENANCE_FIELDS))
        self.assertFalse(transport["retains_response_bodies"])
        self.assertEqual(transport["retryable_statuses"], sorted(jc.JEV_RETRYABLE_STATUSES))

    def test_jev_codec_and_normalization_unchanged(self):
        self.assertEqual(self.doc["model_and_protocol"]["codec_version"], jc2.JEV_CHOICE_V2_CODEC_VERSION)
        self.assertEqual(self.doc["normalization"], prv2.normalization_policy())
        self.assertEqual(self.doc["model_and_protocol"]["protocol_key"],
                         jc2.jev_choice_protocol_key_v2(model=pr.JEV_REPLAY_MODEL,
                                                        endpoint=pr.JEV_REPLAY_ENDPOINT,
                                                        max_retries=pr.JEV_REPLAY_MAX_RETRIES))

    def test_fresh_versioned_output_paths(self):
        outputs = self.doc["outputs"]
        self.assertEqual(outputs, prv3.output_paths())
        for value in outputs.values():
            for old in prv3.OLD_OUTPUT_PATHS:
                self.assertNotEqual(value, old)
        self.assertNotEqual(self.doc["outputs"]["journal"], prv2.DEFAULT_JOURNAL_V2)
        self.assertIn("-v3.jsonl", outputs["journal"])

    def test_manifest_and_caps(self):
        forms = self.doc["frozen_forms"]
        self.assertEqual(forms["paired_forms"], 6)
        self.assertEqual(len(forms["instance_ids"]), 17)
        self.assertEqual(self.doc["caps"]["planned_physical_requests"], 102)
        self.assertEqual(self.doc["caps"]["physical_requests"], 300)
        self.assertEqual(self.doc["caps"]["provider_partition"],
                         {"jev": 250, "ling": 50, "total": 300,
                          "note": self.doc["caps"]["provider_partition"]["note"]})
        self.assertIn("writer_rate_limited_terminal", self.doc["stop_rules"])

    def test_treatment_hash_binds_writer_transport(self):
        generator = self.doc["generator"]
        self.assertEqual(generator["writer_transport_hash"], prv3.writer_transport_hash())
        self.assertEqual(generator["treatment_hash"], prv3.treatment_hash_v3())
        self.assertNotEqual(generator["treatment_hash"], prv2.treatment_hash_v2())

    def test_locked_hash_reproduces(self):
        self.assertEqual(locked()["preregistration_hash"], self.doc["preregistration_hash"])

    def test_committed_artifact_verifies(self):
        document = json.loads((REPO_ROOT / "runs" / "epic-126"
                               / "jev-choice-replay-preregistration-v3.json").read_text())
        self.assertTrue(verify(document)["ok"])
        self.assertFalse(document["approval"]["live_collection_authorized"])


class VerifierV3Tests(unittest.TestCase):
    def setUp(self):
        self.doc = locked()

    def test_verify_ok_on_locked(self):
        result = verify(self.doc, writer_interval=3.25,
                        writer_transport_version=writer_v3.LING_WRITER_TRANSPORT_VERSION)
        self.assertTrue(result["ok"], result["errors"])

    def test_verify_rejects_draft(self):
        draft = prv3.build_replay_preregistration_v3(journal_path=CAPABILITY_JOURNAL, repo_root=REPO_ROOT)
        self.assertFalse(verify(draft)["ok"])

    def test_verify_rejects_v1_protocol_key(self):
        result = verify(self.doc, protocol_key=jc.jev_choice_protocol_key())
        self.assertFalse(result["ok"])
        self.assertTrue(any("v1 protocol key" in error for error in result["errors"]))

    def test_verify_rejects_old_output_paths(self):
        for old in ("runs/epic-126/jev-choice-pilot-v2.jsonl",
                    "runs/epic-126/jev-choice-pilot.jsonl"):
            tampered = copy.deepcopy(self.doc)
            tampered["outputs"]["journal"] = old
            result = verify(tampered)
            self.assertFalse(result["ok"])
            self.assertTrue(any("old v1/v2 output path" in error for error in result["errors"]))

    def test_verify_rejects_timing_retry_and_provenance_drift(self):
        for mutate in (
            lambda d: d["writer_transport"].__setitem__("min_attempt_interval_seconds", 0.25),
            lambda d: d["writer_transport"].__setitem__("max_server_requested_delay_seconds", 999.0),
            lambda d: d["writer_transport"].__setitem__("max_retries", 9),
            lambda d: d["writer_transport"].__setitem__("backoff_initial_seconds", 9.0),
            lambda d: d["writer_transport"].__setitem__("supported_retry_headers", ["retry-after"]),
            lambda d: d["writer_transport"].__setitem__("provenance_fields", ["status"]),
            lambda d: d["writer_transport"].__setitem__("retryable_statuses", [429]),
        ):
            tampered = copy.deepcopy(self.doc)
            mutate(tampered)
            self.assertFalse(verify(tampered)["ok"])

    def test_verify_rejects_source_model_endpoint_manifest_and_cap_drift(self):
        tampered = copy.deepcopy(self.doc)
        tampered["generator"]["source_files_hash"] = "0" * 64
        self.assertFalse(verify(tampered)["ok"])
        tampered = copy.deepcopy(self.doc)
        tampered["model_and_protocol"]["model"] = "jev-0.0.0"
        self.assertFalse(verify(tampered)["ok"])
        tampered = copy.deepcopy(self.doc)
        tampered["caps"]["physical_requests"] = 999
        self.assertFalse(verify(tampered)["ok"])
        self.assertFalse(verify(self.doc, instance_ids=["planning-00000000"])["ok"])
        self.assertFalse(verify(self.doc, planned_requests=pr.JEV_REPLAY_REQUEST_CAP + 1)["ok"])

    def test_verify_rejects_instantiated_writer_drift(self):
        self.assertFalse(verify(self.doc, writer_interval=0.25)["ok"])
        self.assertFalse(verify(self.doc, writer_transport_version="ling-writer-v2")["ok"])

    def test_verify_rejects_v2_registration_version(self):
        tampered = copy.deepcopy(self.doc)
        tampered["preregistration_version"] = prv2.JEV_REPLAY_V2_PREREG_VERSION
        self.assertFalse(verify(tampered)["ok"])


class ImmutabilityTests(unittest.TestCase):
    def test_v2_registration_artifact_still_verifies(self):
        document = json.loads((REPO_ROOT / "runs" / "epic-126"
                               / "jev-choice-replay-preregistration-v2.json").read_text())
        result = prv2.verify_against_jev_replay_preregistration_v2(
            document, instance_ids=document["frozen_forms"]["instance_ids"],
            model=document["model_and_protocol"]["model"], endpoint=document["model_and_protocol"]["endpoint"],
            protocol_key=document["model_and_protocol"]["protocol_key"],
            planned_requests=document["caps"]["planned_physical_requests"], repo_root=REPO_ROOT)
        self.assertTrue(result["ok"], result["errors"])

    def test_v1_registration_artifact_still_verifies(self):
        document = json.loads((REPO_ROOT / "runs" / "epic-126"
                               / "jev-choice-replay-preregistration.json").read_text())
        result = pr.verify_against_jev_replay_preregistration(
            document, instance_ids=document["frozen_forms"]["instance_ids"],
            model=document["model_and_protocol"]["model"], endpoint=document["model_and_protocol"]["endpoint"],
            protocol_key=document["model_and_protocol"]["protocol_key"],
            planned_requests=document["caps"]["planned_physical_requests"], repo_root=REPO_ROOT)
        self.assertTrue(result["ok"], result["errors"])

    def test_stopped_v2_artifacts_unchanged(self):
        report = json.loads((REPO_ROOT / "runs" / "epic-126"
                             / "jev-choice-pilot-report-v2.json").read_text())
        journal = (REPO_ROOT / "runs" / "epic-126" / "jev-choice-pilot-v2.jsonl").read_text()
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "writer_http_429_rate_limited")
        self.assertEqual(len(journal.splitlines()), 51)
        self.assertNotIn("v3", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
