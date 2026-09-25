import copy
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_replay as jr
from apart_incident_response import jev_replay_preregistration_v2 as prv2
from apart_incident_response import jev_replay_preregistration_v4 as prv4
from apart_incident_response import jev_replay_preregistration_v5 as prv5


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRATION_PATH = REPO_ROOT / prv5.DEFAULT_OUTPUT_V5
REGISTRATION = json.loads(REGISTRATION_PATH.read_text(encoding="utf-8"))
PIN = REGISTRATION["preregistration_hash"]
V4_PATHS = (REPO_ROOT / prv4.DEFAULT_OUTPUT_V4, REPO_ROOT / prv4.DEFAULT_JOURNAL_V4,
            REPO_ROOT / prv4.DEFAULT_REPORT_V4)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def v4_snapshot() -> dict:
    return {str(path.relative_to(REPO_ROOT)): sha256_of(path) for path in V4_PATHS}


def v4_pins_on_disk() -> dict:
    return {name: sha256_of(REPO_ROOT / pin["path"]) for name, pin in prv5.V4_PINS.items()}


def treatment_payload(*, runner_source_file: str, runner_source_delegate: str | None,
                      runner_version: str) -> dict:
    """The treatment payload documented by the builders, rebuilt here so the
    test proves which fields may differ between v4 and v5."""

    payload = {
        "decision_artifact_sha256": prv4.DECISION_SHA256,
        "message_wording_hash": jr.message_wording_hash(),
        "envelope": jr.MESSAGE_ENVELOPE_TEMPLATE,
        "placebo_construction": jr.PLACEBO_CONSTRUCTION,
        "placebo_origin": jr.PLACEBO_ORIGIN,
        "normalization_policy_hash": prv2.normalization_policy_hash(),
        "codec_version": jc2_codec(),
        "branch_modes": ["real", "placebo", "null"],
        "estimand": prv4.ESTIMAND["primary"],
        "directional_prediction": prv4.ESTIMAND["directional_prediction"],
        "runner_source_file": runner_source_file,
        "runner_version": runner_version,
    }
    if runner_source_delegate is not None:
        payload["runner_source_delegate"] = runner_source_delegate
    return payload


def jc2_codec() -> str:
    from apart_incident_response import jev_choice_v2 as jc2
    return jc2.JEV_CHOICE_V2_CODEC_VERSION


def build(**kwargs) -> dict:
    kwargs.setdefault("approved", True)
    kwargs.setdefault("repo_root", REPO_ROOT)
    return prv5.build_replay_preregistration_v5(**kwargs)


def verify(document=None, **kwargs) -> dict:
    kwargs.setdefault("repo_root", REPO_ROOT)
    kwargs.setdefault("check_credentials", False)
    return prv5.verify_against_jev_replay_preregistration_v5(
        document if document is not None else REGISTRATION, **kwargs)


def v5_sandbox(test_case: unittest.TestCase) -> Path:
    """Repo root with a materialised replay-v5 directory and no v5 outputs.

    Everything else (src/, replay-v4 pins, decision artifact, all other
    runs/epic-126 entries) is symlinked back to the real checkout so source,
    provenance and historical-pin hashes verify exactly as in production.
    """

    root = Path(tempfile.mkdtemp(prefix="replay-v5-locktime-"))
    test_case.addCleanup(shutil.rmtree, root, ignore_errors=True)
    (root / "src").symlink_to(REPO_ROOT / "src")
    runs = root / "runs"
    runs.mkdir()
    for entry in sorted(os.listdir(REPO_ROOT / "runs")):
        if entry != "epic-126":
            (runs / entry).symlink_to(REPO_ROOT / "runs" / entry)
    epic = runs / "epic-126"
    epic.mkdir()
    for entry in sorted(os.listdir(REPO_ROOT / "runs" / "epic-126")):
        if entry == "replay-v5":
            continue
        (epic / entry).symlink_to(REPO_ROOT / "runs" / "epic-126" / entry)
    (epic / "replay-v5").mkdir()
    shutil.copy2(REGISTRATION_PATH, epic / "replay-v5" / REGISTRATION_PATH.name)
    return root


class ArtifactIntegrityTestCase(unittest.TestCase):
    """Prove the superseded v4 evidence never moves during any test."""

    def setUp(self):
        self.v4 = v4_snapshot()
        self.pins = v4_pins_on_disk()
        self.assertFalse((REPO_ROOT / prv5.DEFAULT_JOURNAL_V5).exists(),
                         "v5 journal must not exist before the authorized run")
        self.assertFalse((REPO_ROOT / prv5.DEFAULT_REPORT_V5).exists(),
                         "v5 report must not exist before the authorized run")

    def tearDown(self):
        self.assertEqual(v4_snapshot(), self.v4, "a superseded v4 artifact changed")
        self.assertEqual(v4_pins_on_disk(), self.pins, "a v4 pin drifted")


class ReproducibilityTests(ArtifactIntegrityTestCase):
    def test_build_is_byte_reproducible(self):
        first, second = build(), build()
        self.assertEqual(first, second)
        self.assertEqual(first["preregistration_hash"], second["preregistration_hash"])
        payload = json.dumps({k: v for k, v in first.items()
                              if k != "preregistration_hash"}, sort_keys=True)
        self.assertEqual(hashlib.sha256(payload.encode()).hexdigest(), PIN)

    def test_locked_document_reproduces_from_disk(self):
        rebuilt = build()
        self.assertEqual({k: v for k, v in REGISTRATION.items() if k != "preregistration_hash"},
                         {k: v for k, v in rebuilt.items() if k != "preregistration_hash"})
        self.assertEqual(REGISTRATION["preregistration_hash"], rebuilt["preregistration_hash"])
        self.assertEqual(REGISTRATION["preregistration_hash"], PIN)

    def test_stale_registration_hash_rejected(self):
        tampered = copy.deepcopy(REGISTRATION)
        tampered["preregistration_hash"] = "0" * 64
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue([e for e in result["errors"]
                         if e.startswith("registration_hash_matches")])

    def test_content_drift_rejected(self):
        tampered = copy.deepcopy(REGISTRATION)
        tampered["purpose"] = tampered["purpose"] + " tampered"
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue([e for e in result["errors"]
                         if e.startswith("registration_content_matches")])

    def test_verify_passes_on_the_locked_document(self):
        result = verify()
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["live_collection_authorized"], False)
        names = {check["check"] for check in result["checks"]}
        for required in ("registration_version", "status_locked", "approval_lock_scope",
                         "live_collection_not_authorized", "superseded_v4_artifacts_pinned",
                         "superseded_v4_lock_pinned", "superseded_stopped_run_recorded",
                         "v4_baseline_rebuilds", "frozen_scientific_content_verified",
                         "scientific_blocks_identical_to_v4", "event_ids_exact_unique_ordered",
                         "branch_schedule_event_major", "branch_request_and_state_hashes",
                         "six_form_scope", "jev_model_matches", "jev_endpoint_matches",
                         "codec_version", "jev_protocol_key", "normalization_policy",
                         "bounded_pacing_registered", "no_mixed_protocol_keys",
                         "planned_calls_51_0", "physical_cap_retry_inclusive",
                         "retry_inclusive_cost_reservation", "outputs_are_v5",
                         "fresh_output_paths", "fresh_output_paths_report",
                         "no_stale_or_superseded_output_paths", "source_files_bound",
                         "source_files_hash_matches", "runner_policy_satisfied",
                         "runner_binding_does_not_authorize",
                         "operational_decisions_recorded", "no_resume_policy_registered",
                         "registration_content_matches", "registration_hash_matches"):
            self.assertIn(required, names)


class ScientificContentTests(ArtifactIntegrityTestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = REGISTRATION
        cls.baseline = prv4.build_replay_preregistration_v4(approved=True, repo_root=REPO_ROOT)

    def test_scientific_blocks_identical_to_v4(self):
        for key, value in self.baseline.items():
            if key in prv5.V5_OVERRIDE_KEYS:
                continue
            with self.subTest(key=key):
                self.assertEqual(self.doc.get(key), value,
                                 f"scientific block drifted from v4: {key}")
        self.assertEqual(set(self.doc) - set(self.baseline), set(prv5.V5_ONLY_KEYS))
        self.assertEqual(set(self.baseline) - set(self.doc), set(),
                         "no v4 key may be dropped by v5")
        self.assertTrue(set(prv5.V5_OVERRIDE_KEYS) <= set(self.baseline))

    def test_estimand_unchanged(self):
        estimand = self.doc["estimand"]
        self.assertEqual(estimand, self.baseline["estimand"])
        self.assertEqual(estimand["experimental_unit"], "prompt form")
        self.assertEqual(estimand["k"], 6)
        self.assertIn("equal-weight mean", estimand["primary"])
        self.assertEqual(estimand["event_contrast"], "d_i = H_real,i - H_placebo,i")
        self.assertIs(estimand["events_are_independent_units"], False)

    def test_inference_unchanged(self):
        inference = self.doc["inference"]
        self.assertEqual(inference, self.baseline["inference"])
        self.assertIn("sign-flip", inference["primary_test"])
        self.assertIn("t interval", inference["interval"])
        self.assertEqual(inference["min_two_sided_p_k6"], 0.03125)
        self.assertIn("instance-level t-test", inference["prohibited_as_primary"])

    def test_guards_missingness_and_five_form_fallback_unchanged(self):
        self.assertEqual(self.doc["guards"], self.baseline["guards"])
        missingness = self.doc["missingness"]
        self.assertEqual(missingness, self.baseline["missingness"])
        self.assertEqual(missingness["imputation"], "never impute missing pairs")
        self.assertIn("interval-only descriptive", missingness["five_form_fallback"])
        self.assertIn("no causal gate", missingness["five_form_fallback"])

    def test_manifest_schedule_and_branch_hashes_unchanged(self):
        self.assertEqual(self.doc["events"], self.baseline["events"])
        self.assertEqual(self.doc["branch_schedule"], self.baseline["branch_schedule"])
        self.assertEqual(self.doc["forms"], self.baseline["forms"])
        self.assertEqual(self.doc["branch_design"], self.baseline["branch_design"])
        self.assertEqual(len(self.doc["events"]), 17)
        ids = [event["event_id"] for event in self.doc["events"]]
        self.assertEqual(ids, [event["event_id"] for event in self.baseline["events"]])
        self.assertEqual(len(set(ids)), 17)
        for event in self.doc["events"]:
            with self.subTest(event=event["event_id"]):
                self.assertEqual(sorted(event["pre_read"]["branch_request_hashes"]),
                                 ["null", "placebo", "real"])
                self.assertEqual(len(event["pre_read"]["state_hash"]), 64)

    def test_caps_unchanged_and_retry_inclusive(self):
        caps = self.doc["caps"]
        self.assertEqual(caps, self.baseline["caps"])
        self.assertEqual((caps["planned_calls"]["jev"], caps["planned_calls"]["ling"],
                          caps["planned_calls"]["combined"]), (51, 0, 51))
        self.assertEqual(caps["physical_requests"], 153)
        self.assertEqual(51 * 3, caps["physical_requests"])
        self.assertEqual(caps["provider_partition"]["jev"], 153)
        self.assertEqual(caps["worst_case_next_call_cost_usd"], prv4.NEXT_CALL_RESERVE_USD)
        self.assertLessEqual(caps["worst_case_cost_usd"], caps["cost_cap_usd"])

    def test_protocol_pins_unchanged(self):
        base = self.baseline["model_and_protocol"]
        doc = self.doc["model_and_protocol"]
        self.assertEqual({k: v for k, v in doc.items() if k != "backoff"},
                         {k: v for k, v in base.items() if k != "backoff"})
        self.assertEqual(doc["backoff"], dict(prv5.BACKOFF_V5))
        self.assertEqual(doc["max_retries"], 2)
        self.assertEqual(doc["retryable_statuses"], sorted(jc.JEV_RETRYABLE_STATUSES))
        self.assertEqual(doc["normalization_policy_hash"],
                         prv2.normalization_policy_hash())

    def test_treatment_hash_differs_only_by_runner_binding(self):
        import hashlib as _hashlib

        v5_payload = treatment_payload(runner_source_file=prv5.RUNNER_SOURCE_REL_V5,
                                       runner_source_delegate=prv5.RUNNER_SOURCE_REL_V4,
                                       runner_version=prv5.REPLAY_RUNNER_VERSION_V5)
        v4_payload = treatment_payload(runner_source_file=prv4.RUNNER_SOURCE_REL,
                                       runner_source_delegate=None,
                                       runner_version="jev-choice-replay-runner-v4")
        digest = lambda payload: _hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        self.assertEqual(digest(v5_payload), self.doc["treatment_hash"])
        self.assertEqual(digest(v4_payload), self.baseline["treatment_hash"])
        self.assertNotEqual(self.doc["treatment_hash"], self.baseline["treatment_hash"])
        self.assertEqual(set(v5_payload) - set(v4_payload), {"runner_source_delegate"})
        self.assertEqual(set(v4_payload) - set(v5_payload), set())
        changed = {key for key in v4_payload if v4_payload[key] != v5_payload[key]}
        self.assertEqual(changed, {"runner_source_file", "runner_version"})
        for field in ("decision_artifact_sha256", "message_wording_hash", "envelope",
                      "placebo_construction", "placebo_origin", "normalization_policy_hash",
                      "codec_version", "branch_modes", "estimand",
                      "directional_prediction"):
            self.assertEqual(v4_payload[field], v5_payload[field], field)


class SupersessionTests(ArtifactIntegrityTestCase):
    def test_v4_pins_match_the_committed_artifacts(self):
        for name, pin in prv5.V4_PINS.items():
            with self.subTest(name=name):
                self.assertEqual(sha256_of(REPO_ROOT / pin["path"]), pin["sha256"])

    def test_supersession_block_records_v4(self):
        supersedes = REGISTRATION["supersedes"]
        self.assertEqual(supersedes["preregistration_hash"], prv5.V4_LOCKED_HASH)
        self.assertEqual(supersedes["registration"]["sha256"],
                         prv5.V4_PINS["registration"]["sha256"])
        self.assertEqual(supersedes["journal"]["sha256"], prv5.V4_PINS["journal"]["sha256"])
        self.assertEqual(supersedes["report"]["sha256"], prv5.V4_PINS["report"]["sha256"])
        stopped = supersedes["stopped_run"]
        self.assertEqual(stopped["status"], "stopped")
        self.assertEqual(stopped["stop_reason"], "provider_failure_limit")
        self.assertEqual(stopped["attempted_branches"], 2)
        self.assertEqual(stopped["approval"], prv5.V4_RUN_APPROVAL)
        self.assertIn("never resumed, appended, overwritten", supersedes["rule"])

    def test_successor_of_lists_v4(self):
        successor = REGISTRATION["successor_of"]
        self.assertEqual(successor["v4"]["preregistration_hash"], prv5.V4_LOCKED_HASH)
        self.assertEqual(successor["v4"]["status"], "stopped")
        self.assertIs(successor["immutable"], True)

    def test_v5_outputs_are_fresh_and_disjoint_from_v4(self):
        outputs = REGISTRATION["outputs"]
        self.assertEqual(outputs, prv5.output_paths())
        self.assertFalse((REPO_ROOT / outputs["journal"]).exists())
        self.assertFalse((REPO_ROOT / outputs["report"]).exists())
        for value in outputs.values():
            self.assertNotIn(str(value), prv5.OLD_OUTPUT_PATHS_V5)

    def test_build_fails_closed_on_v4_pin_drift(self):
        with tempfile.TemporaryDirectory(prefix="replay-v5-drift-") as directory:
            root = Path(directory)
            (root / "src").symlink_to(REPO_ROOT / "src")
            target = root / prv5.V4_PINS["journal"]["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("drifted", encoding="utf-8")
            with self.assertRaises(ValueError):
                prv5.build_replay_preregistration_v5(approved=True, repo_root=root)


class OperationalPolicyTests(ArtifactIntegrityTestCase):
    def test_all_seven_decisions_recorded(self):
        decisions = REGISTRATION["operational_policy"]["decisions"]
        self.assertEqual(sorted(decisions), sorted([
            "retry_policy", "terminal_failure_rule", "jev_token_budget",
            "bounded_pacing", "timeout", "output_lifecycle",
            "physical_request_and_cost_caps"]))
        for name, decision in decisions.items():
            with self.subTest(decision=name):
                self.assertIn("rationale", decision)

    def test_preserved_decisions(self):
        decisions = REGISTRATION["operational_policy"]["decisions"]
        self.assertEqual(decisions["retry_policy"]["decision"], "preserve")
        self.assertEqual(decisions["retry_policy"]["max_retries"], 2)
        self.assertEqual(decisions["terminal_failure_rule"]["decision"], "preserve")
        self.assertIn("two consecutive", decisions["terminal_failure_rule"]["rule"])
        self.assertEqual(decisions["jev_token_budget"]["decision"], "preserve")
        self.assertEqual(decisions["jev_token_budget"]["input_token_ceiling"], 8192)
        self.assertEqual(decisions["timeout"]["decision"], "preserve")
        self.assertEqual(decisions["physical_request_and_cost_caps"]["decision"], "preserve")

    def test_bounded_pacing_change_is_scoped(self):
        pacing = REGISTRATION["operational_policy"]["decisions"]["bounded_pacing"]
        self.assertEqual(pacing["decision"], "change_bounded")
        self.assertEqual(pacing["field"], "model_and_protocol.backoff")
        self.assertEqual(pacing["from"], dict(prv5.BACKOFF_V4))
        self.assertEqual(pacing["to"], dict(prv5.BACKOFF_V5))
        self.assertEqual(pacing["previous_window_seconds"], 1.5)
        self.assertEqual(pacing["registered_window_per_logical_call_seconds"], 6.0)
        self.assertIn("retry count", pacing["unchanged"])
        self.assertIn("all caps", pacing["unchanged"])

    def test_fresh_output_lifecycle_registered(self):
        lifecycle = REGISTRATION["operational_policy"]["decisions"]["output_lifecycle"]
        self.assertEqual(lifecycle["decision"], "fresh_paths_no_resume")
        for flag in ("no_resume", "no_append", "no_overwrite", "no_path_overrides"):
            self.assertIs(lifecycle[flag], True)


class SourceBindingTests(ArtifactIntegrityTestCase):
    def test_source_files_bound(self):
        self.assertEqual(REGISTRATION["source_files"], list(prv5.V5_SOURCE_FILES))
        for name in (prv5.RUNNER_SOURCE_REL_V5, prv5.RUNNER_SOURCE_REL_V4):
            self.assertIn(name, REGISTRATION["source_files"])

    def test_source_files_hash_reproduces(self):
        digest = hashlib.sha256()
        for relative in prv5.V5_SOURCE_FILES:
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update((REPO_ROOT / relative).read_bytes())
        self.assertEqual(REGISTRATION["source_files_hash"], digest.hexdigest())

    def test_runner_binding_does_not_authorize(self):
        policy = REGISTRATION["runner_policy"]
        self.assertIs(policy["adding_runner_authorizes_collection"], False)
        self.assertIn("does not authorize execution", policy["policy"])
        self.assertIn("separate explicit authorization", policy["live_execution_rule"])
        self.assertEqual(policy["runner_source_files"],
                         [prv5.RUNNER_SOURCE_REL_V5, prv5.RUNNER_SOURCE_REL_V4])
        self.assertEqual(policy["supersedes_v4_registration"]["preregistration_hash"],
                         prv5.V4_LOCKED_HASH)
        self.assertIs(REGISTRATION["live_collection_authorized"], False)
        self.assertIs(REGISTRATION["lock_is_not_live_authorization"], True)

    def test_lock_is_not_authorization_declared(self):
        self.assertIn("separate explicit live authorization",
                      " ".join(REGISTRATION["pending_decisions"]))


class OccupiedOutputTests(ArtifactIntegrityTestCase):
    def test_occupied_new_paths_fail_verification(self):
        root = v5_sandbox(self)
        journal = root / prv5.DEFAULT_JOURNAL_V5
        report = root / prv5.DEFAULT_REPORT_V5
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text("SENTINEL", encoding="utf-8")
        result = verify(repo_root=root)
        self.assertFalse(result["ok"])
        failed = [error.split(":")[0] for error in result["errors"]]
        self.assertIn("fresh_output_paths", failed)
        self.assertNotIn("fresh_output_paths_report", failed)
        self.assertEqual(journal.read_text(encoding="utf-8"), "SENTINEL")
        self.assertFalse(report.exists())

    def test_sandbox_verifies_clean(self):
        root = v5_sandbox(self)
        result = verify(repo_root=root)
        self.assertTrue(result["ok"], result["errors"])


if __name__ == "__main__":
    unittest.main()
