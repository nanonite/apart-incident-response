import copy
import hashlib
import io
import json
import math
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_choice_v2 as jc2
from apart_incident_response import jev_replay as jr
from apart_incident_response import jev_replay_preregistration as pr
from apart_incident_response import jev_replay_preregistration_v4 as prv4
from apart_incident_response import jev_replay_runner_v4 as runner


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = json.loads(
    (REPO_ROOT / "runs/epic-126/replay-v4/jev-choice-replay-preregistration-v4.json")
    .read_text(encoding="utf-8"))
PIN = REGISTRATION["preregistration_hash"]
FRESH = {"journal_exists": False, "report_exists": False}

#: The committed stopped replay-v4 run. These are pinned project state: never
#: moved, deleted, rewritten or reinterpreted by any test.
REPLAY_REGISTRATION = REPO_ROOT / "runs/epic-126/replay-v4/jev-choice-replay-preregistration-v4.json"
REPLAY_JOURNAL = REPO_ROOT / "runs/epic-126/replay-v4/jev-choice-replay-v4.jsonl"
REPLAY_REPORT = REPO_ROOT / "runs/epic-126/replay-v4/jev-choice-replay-report-v4.json"
REPLAY_ARTIFACTS = (REPLAY_REGISTRATION, REPLAY_JOURNAL, REPLAY_REPORT)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_snapshot() -> dict[Path, str]:
    return {path: sha256_of(path) for path in REPLAY_ARTIFACTS}


def lock_time_sandbox(test_case: unittest.TestCase) -> Path:
    """Repo root presenting the checkout as it was at registration lock time.

    The stopped replay journal/report already exist in the real checkout, so a
    CLI invocation against ``REPO_ROOT`` legitimately fails its freshness
    checks. This sandbox isolates those outputs without touching them: it
    materialises ``runs/epic-126/replay-v4`` as a real directory holding only a
    byte-identical copy of the registration, and symlinks every other path back
    to the real checkout so source hashes, the pinned decision artifact and all
    upstream pins verify exactly as they do in production.
    """

    root = Path(tempfile.mkdtemp(prefix="replay-v4-locktime-"))
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
        if entry == "replay-v4":
            continue
        (epic / entry).symlink_to(REPO_ROOT / "runs" / "epic-126" / entry)
    (epic / "replay-v4").mkdir()
    shutil.copy2(REPLAY_REGISTRATION,
                 epic / "replay-v4" / REPLAY_REGISTRATION.name)
    return root


class FakeReceiverClient:
    provider = "jev"
    endpoint = jc.JEV_SYSTEMONE_ENDPOINT
    max_retries = pr.JEV_REPLAY_MAX_RETRIES

    def __init__(self, *, max_physical_requests=153, scale=None, fail_calls=()):
        self.max_physical_requests = max_physical_requests
        self.physical_attempts = 0
        self.calls = 0
        self.scale = scale
        self.fail_calls = set(fail_calls)

    def complete(self, request):
        if self.calls in self.fail_calls:
            self.calls += 1
            raise OSError("simulated transport failure")
        self.physical_attempts += 1
        self.calls += 1
        question_id = next(iter(request["questions"]))
        option_ids = list(request["questions"][question_id]["criteria"])
        rest = 0.5 / (len(option_ids) - 1)
        probabilities = {option_id: (0.5 if index == 0 else rest)
                         for index, option_id in enumerate(option_ids)}
        if self.scale is not None:
            probabilities = {key: value * self.scale
                             for key, value in probabilities.items()}
        return {"model": jc.JEV_DEFAULT_MODEL,
                "answers": {question_id: {"type": "choice", "choice": option_ids[0],
                                          "probabilities": probabilities,
                                          "confidence": 0.5}},
                "usage": {"input_tokens": 10, "output_tokens": 2}}


def make_preflight(registration=None, *, receiver=None, approval="test",
                   check_credentials=False, **kwargs):
    registration = registration or REGISTRATION
    if receiver is None:
        receiver = jc2.JevChoiceAdapterV2(FakeReceiverClient(),
                                          model=pr.JEV_REPLAY_MODEL)
    return runner.verify_replay_runner_preflight(
        registration, receiver, repo_root=REPO_ROOT, approval=approval,
        check_credentials=check_credentials, pinned_hash=registration.get(
            "preregistration_hash"), **(kwargs or FRESH))


def execute(registration=None, *, receiver=None, approval="test", verification=None,
            journal_path=None, report_path=None, registration_pinned=True):
    registration = registration or REGISTRATION
    if receiver is None:
        receiver = jc2.JevChoiceAdapterV2(FakeReceiverClient(), model=pr.JEV_REPLAY_MODEL)
    used_verification = verification if verification is not None else make_preflight(
        registration, receiver=receiver, approval=approval)
    directory = tempfile.mkdtemp(prefix="replay-v4-")
    journal = journal_path if journal_path is not None else Path(directory) / "j.jsonl"
    report = report_path if report_path is not None else Path(directory) / "r.json"
    result = runner.execute_replay_runner(
        registration, receiver, verification=used_verification, approval=approval,
        pinned_hash=registration.get("preregistration_hash") if registration_pinned else None,
        journal_path=journal, report_path=report, sleep_fn=lambda _: None)
    rows = []
    if journal.exists():
        for line in journal.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return result, receiver, journal, rows


OK_VERIFICATION = {"ok": True, "checks": [], "failed": []}


class PreflightTests(unittest.TestCase):
    def test_preflight_ok_named_checks(self):
        result = make_preflight()
        self.assertTrue(result["ok"], result["failed"])
        names = {check["check"] for check in result["checks"]}
        for required in ("approval_present", "registration_verifies",
                         "registration_hash_matches", "status_locked",
                         "live_collection_not_authorized", "runner_policy_satisfied",
                         "runner_not_live_authorization", "source_treatment_hashes_wellformed",
                         "event_manifest_and_schedule_verified",
                         "event_ids_exact_unique_ordered", "branch_schedule_event_major",
                         "feasible_set_hashes_verified", "jev_model_matches",
                         "jev_endpoint_matches", "jev_retry_policy", "jev_protocol_key",
                         "codec_version", "normalization_policy",
                         "request_state_option_treatment_hashes", "journal_path_fresh",
                         "report_path_fresh", "jev_physical_cap_enforced",
                         "planned_calls_51_0", "cost_caps_and_reserve",
                         "upstream_192_hashes_verified"):
            self.assertIn(required, names)

    def test_credential_check_only_when_requested(self):
        present = type("C", (), {"present": True, "shape_ok": True,
                                 "redacted": lambda self: {}})()
        absent = type("C", (), {"present": False, "shape_ok": False,
                                "redacted": lambda self: {}})()
        with patch.object(jc, "load_jev_credentials", return_value=present):
            result = make_preflight(check_credentials=True)
            self.assertTrue(result["ok"], result["failed"])
        with patch.object(jc, "load_jev_credentials", return_value=absent):
            result = make_preflight(check_credentials=True)
            self.assertFalse(result["ok"])
            self.assertIn("jev_credentials_present", result["failed"])
        result = make_preflight(check_credentials=True, approval=None)
        self.assertIn("approval_present", result["failed"])

    def test_runner_policy_and_source_binding_verified(self):
        result = make_preflight()
        runner_check = next(check for check in result["checks"]
                            if check["check"] == "runner_policy_satisfied")
        self.assertTrue(runner_check["ok"])
        self.assertEqual(REGISTRATION["runner_policy"]["runner_source_files"],
                         [runner.RUNNER_SOURCE_REL])
        self.assertIn(runner.RUNNER_SOURCE_REL, REGISTRATION["source_files"])
        self.assertEqual(REGISTRATION["source_files_hash"],
                         prv4._source_files_hash(REPO_ROOT))
        self.assertEqual(REGISTRATION["treatment_hash"],
                         prv4.treatment_hash_v4(
                             decision_sha256=prv4.DECISION_SHA256,
                             wording_hash=REGISTRATION["message_wording_hash"],
                             normalization_policy_hash=prv4.prv2.normalization_policy_hash()))
        self.assertEqual(PIN, REGISTRATION["preregistration_hash"])
        self.assertNotEqual(PIN, prv4.SUPERSEDED_OFFLINE_LOCK_HASH)
        self.assertEqual(REGISTRATION["runner_policy"]["superseded_offline_lock"]
                         ["preregistration_hash"], prv4.SUPERSEDED_OFFLINE_LOCK_HASH)

    def test_registration_drift_rejected_by_preflight(self):
        tampered = copy.deepcopy(REGISTRATION)
        tampered["preregistration_hash"] = "0" * 64
        result = make_preflight(registration=tampered)
        self.assertFalse(result["ok"])
        self.assertIn("registration_verifies", result["failed"])

    def test_missing_approval_and_failed_preflight_zero_calls(self):
        report, receiver, _, _ = execute(approval=None)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["stop_reason"], "missing_approval")
        self.assertEqual(receiver.client.calls, 0)
        report, receiver, _, _ = execute(verification={"ok": False, "failed": ["x"],
                                                        "checks": []})
        self.assertEqual(report["stop_reason"], "preflight_failed")
        self.assertEqual(receiver.client.calls, 0)


class BranchJournalTests(unittest.TestCase):
    def test_duplicate_key_rejected_and_fsync_per_row(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "j.jsonl"
            journal = runner.BranchJournal(path)
            journal.write({"event_id": "e1", "branch": "real", "x": 1})
            journal.write({"event_id": "e1", "branch": "placebo", "x": 2})
            self.assertEqual(journal.rows, 2)
            self.assertEqual(journal.fsync_count, 2)
            with self.assertRaises(runner.BranchJournalError):
                journal.write({"event_id": "e1", "branch": "real", "x": 3})
            self.assertTrue(journal.handle.closed)
            rows = journal.read_rows()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["branch"], "real")

    def test_overwrite_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "j.jsonl"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                runner.BranchJournal(path)
            self.assertEqual(path.read_text(encoding="utf-8"), "{}")

    def test_fsync_called_once_per_row_during_run(self):
        real_fsync = os.fsync
        calls = []

        def spy(fd):
            calls.append(fd)
            return real_fsync(fd)

        with patch.object(runner.os, "fsync", side_effect=spy):
            report, receiver, journal, rows = execute()
        self.assertEqual(report["status"], "completed")
        self.assertEqual(len(rows), 51)
        self.assertEqual(len(calls), 51)


class ScheduleExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report, cls.receiver, cls.journal, cls.rows = execute()

    def test_fake_run_completes_zero_network(self):
        # the fake receiver stands in for the transport; no urlopen anywhere
        self.assertEqual(self.report["status"], "completed")
        self.assertIsNone(self.report["stop_reason"])
        self.assertEqual(self.report["attempted_branches"], 51)
        self.assertEqual(self.report["valid_branches"], 51)
        self.assertEqual(self.report["invalid_branches"], 0)
        self.assertEqual(self.report["unattempted_branches"], 0)
        self.assertEqual(len(self.rows), 51)
        self.assertEqual(self.report["physical_attempts"]["jev"], 51)
        self.assertEqual(self.report["physical_attempts"]["cap"], 153)
        self.assertLessEqual(self.report["estimated_cost_usd"], 1.0)

    def test_exact_schedule_execution(self):
        schedule = REGISTRATION["branch_schedule"]
        self.assertTrue(self.report["schedule_adherence"]["planned_equals_actual"])
        self.assertEqual([event["event_id"] for event in self.report["events"]],
                         schedule["event_order"])
        for event in self.report["events"]:
            with self.subTest(event=event["event_id"]):
                self.assertEqual(event["branch_order_planned"],
                                 schedule["schedule"][event["event_id"]])
                self.assertEqual(event["branch_order_actual"],
                                 event["branch_order_planned"])
                self.assertEqual(sorted(event["branches"]), ["null", "placebo", "real"])
        branch_totals = {branch: sum(1 for row in self.rows if row["branch"] == branch)
                         for branch in ("real", "placebo", "null")}
        self.assertEqual(branch_totals, {"real": 17, "placebo": 17, "null": 17})
        for row in self.rows:
            self.assertEqual(row["planned_branch_position"],
                             row["actual_branch_position"])

    def test_schedule_drift_rejected(self):
        tampered = copy.deepcopy(REGISTRATION)
        first = tampered["branch_schedule"]["event_order"][0]
        tampered["branch_schedule"]["schedule"][first] = ["real", "real", "null"]
        report, receiver, _, _ = execute(registration=tampered,
                                         verification=OK_VERIFICATION)
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(report["stop_reason"].startswith("plan_drift"))
        self.assertEqual(receiver.client.calls, 0)

    def test_request_and_state_hash_drift_stop_before_call(self):
        tampered = copy.deepcopy(REGISTRATION)
        tampered["events"][0]["pre_read"]["state_hash"] = "0" * 64
        report, receiver, journal, rows = execute(registration=tampered,
                                                  verification=OK_VERIFICATION)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "pre_read_hash_mismatch")
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(rows, [])

        tampered = copy.deepcopy(REGISTRATION)
        tampered["events"][0]["pre_read"]["branch_request_hashes"]["real"] = "0" * 64
        report, receiver, journal, rows = execute(registration=tampered,
                                                  verification=OK_VERIFICATION)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "branch_request_hash_mismatch")
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(rows, [])

    def test_output_collision_and_resume_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "j.jsonl"
            journal.write_text("SENTINEL", encoding="utf-8")
            report, receiver, journal_path, rows = execute(journal_path=journal,
                                                           verification=OK_VERIFICATION)
            self.assertEqual(report["stop_reason"], "output_exists")
            self.assertEqual(journal.read_text(encoding="utf-8"), "SENTINEL")
            self.assertEqual(receiver.client.calls, 0)
            self.assertEqual(rows, [])

    def test_partition_and_cost_caps_stop(self):
        report, receiver, _, _ = execute(
            receiver=jc2.JevChoiceAdapterV2(
                FakeReceiverClient(max_physical_requests=152),
                model=pr.JEV_REPLAY_MODEL),
            verification=OK_VERIFICATION)
        self.assertEqual(report["stop_reason"], "partition_not_enforced")
        self.assertEqual(receiver.client.calls, 0)

        tampered = copy.deepcopy(REGISTRATION)
        tampered["caps"]["cost_cap_usd"] = 0.00001
        report, receiver, _, rows = execute(registration=tampered,
                                            verification=OK_VERIFICATION)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "cost_cap")
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(rows, [])


class NormalizationBehaviorTests(unittest.TestCase):
    def test_suspect_band_recorded_invalid_and_siblings_run(self):
        report, receiver, journal, rows = execute(
            receiver=jc2.JevChoiceAdapterV2(
                FakeReceiverClient(scale=1.03), model=pr.JEV_REPLAY_MODEL))
        # nonterminal suspect band: run reaches the end of the schedule
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["attempted_branches"], 51)
        self.assertEqual(report["valid_branches"], 0)
        self.assertEqual(report["invalid_branches"], 51)
        suspect_rows = [row for row in rows
                        if row["error_class"] == "not_normalized_suspect"]
        self.assertEqual(len(suspect_rows), 51)
        for row in suspect_rows:
            self.assertFalse(row["valid"])
            self.assertIsNotNone(row["probability_diagnostics"])
        first_event = report["events"][0]
        self.assertEqual(sorted(first_event["branches"]), ["null", "placebo", "real"])

    def test_hard_normalization_stops_immediately(self):
        report, receiver, journal, rows = execute(
            receiver=jc2.JevChoiceAdapterV2(
                FakeReceiverClient(scale=1.1), model=pr.JEV_REPLAY_MODEL))
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "not_normalized_hard")
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["valid"])
        self.assertEqual(rows[0]["error_class"], "not_normalized_hard")

    def test_incomplete_triplet_observable_in_missingness(self):
        report, receiver, journal, rows = execute(
            receiver=jc2.JevChoiceAdapterV2(
                FakeReceiverClient(scale=1.1), model=pr.JEV_REPLAY_MODEL))
        first_event_id = REGISTRATION["branch_schedule"]["event_order"][0]
        entry = report["missingness"]["by_event"][first_event_id]
        self.assertEqual(entry["planned"], 3)
        self.assertEqual(entry["attempted"], 1)
        self.assertEqual(entry["unattempted"], 2)
        self.assertTrue(entry["partial_triplet"])
        self.assertIn("partial triplets remain observable", report["partial_report_note"])


class ProviderFailureTests(unittest.TestCase):
    def test_two_consecutive_failures_stop_with_sanitized_rows(self):
        report, receiver, journal, rows = execute(
            receiver=jc2.JevChoiceAdapterV2(
                FakeReceiverClient(fail_calls=(0, 1)), model=pr.JEV_REPLAY_MODEL))
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "provider_failure_limit")
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertFalse(row["valid"])
            self.assertEqual(row["error_class"], "transport_error")
            self.assertNotIn("simulated", json.dumps(row))
        first_event_id = REGISTRATION["branch_schedule"]["event_order"][0]
        entry = report["missingness"]["by_event"][first_event_id]
        self.assertEqual((entry["attempted"], entry["unattempted"]), (2, 1))
        self.assertTrue(entry["partial_triplet"])

    def test_consecutive_counter_resets_after_valid_response(self):
        report, receiver, journal, rows = execute(
            receiver=jc2.JevChoiceAdapterV2(
                FakeReceiverClient(fail_calls=(0,)), model=pr.JEV_REPLAY_MODEL))
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["attempted_branches"], 51)
        self.assertEqual(report["invalid_branches"], 1)
        self.assertEqual(report["valid_branches"], 50)


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report, *_rest = execute()

    def test_real_placebo_null_grouping(self):
        events = self.report["events"]
        self.assertEqual(len(events), 17)
        for event in events:
            with self.subTest(event=event["event_id"]):
                self.assertEqual(sorted(event["branches"]), ["null", "placebo", "real"])
                self.assertEqual(event["branch_order_actual"],
                                 event["branch_order_planned"])
        real_row = events[0]["branches"]["real"]
        self.assertIn("entropy_bits", real_row)
        self.assertIn("p_target", real_row)
        self.assertIn("feasible_mass", real_row)

    def test_complete_pair_and_primary_reporting(self):
        analysis = self.report["analysis"]
        self.assertEqual(analysis["unit"], "prompt form")
        self.assertEqual(analysis["events"], 17)
        self.assertEqual(analysis["complete_pairs"], 17)
        self.assertEqual(analysis["missingness"]["planned_pairs"], 17)
        self.assertEqual(analysis["missingness"]["imputation"], "none")
        inference = analysis["inference"]
        self.assertEqual(inference["result"], "six_form_primary_inference")
        self.assertEqual(inference["k"], 6)
        self.assertEqual(inference["interval"]["df"], 5)
        self.assertEqual(inference["sign_flip"]["min_p_value"], 2 / 64)
        # degenerate fake: every branch gets the same vector, so d_i = 0 and
        # the negative-direction requirement is (correctly) not met
        self.assertFalse(inference["direction_met"])
        self.assertEqual(inference["primary_delta"], 0.0)
        self.assertIn("sign-flip", inference["statement"])

    def test_guards_reported_never_filter(self):
        analysis = self.report["analysis"]
        guards = analysis["guards"]
        self.assertFalse(guards["filtered_primary_estimate"])
        self.assertEqual(guards["delta"], 0.0)
        self.assertEqual(guards["epsilon"], 0.01)
        self.assertEqual(guards["formulas"], prv4.GUARD_FORMULAS)
        for form, entry in guards["per_form"].items():
            self.assertEqual(entry["complete_pairs"],
                             analysis["missingness"]["complete_pairs_by_form"][form])
        self.assertIn("never remove a valid real/placebo pair", guards["statement"])
        self.assertIn("never useful uptake", guards["statement"])

    def test_null_manipulation_checks_separate(self):
        checks = self.report["analysis"]["null_manipulation_checks"]
        self.assertIn("null excluded from the primary", checks["scope"])
        self.assertEqual(checks["events_with_real_minus_null"], 17)
        self.assertEqual(checks["mean_real_minus_null"], 0.0)


def synthetic_records(forms_metrics):
    """Build event records for analyze_replay: [(form, d, real, placebo, null metrics)]."""
    records = []
    for index, (form, real, placebo, null) in enumerate(forms_metrics):
        records.append({
            "event_id": f"synthetic-{index}", "prompt_form_id": form,
            "branches": {
                "real": {"valid": real is not None, **(real or {})},
                "placebo": {"valid": placebo is not None, **(placebo or {})},
                "null": {"valid": null is not None, **(null or {})},
            }})
    return records


def metrics(entropy, p_target=0.5, mass=1.0):
    return {"entropy_bits": entropy, "p_target": p_target, "feasible_mass": mass}


class FallbackBranchTests(unittest.TestCase):
    FORMS = sorted(prv4.FROZEN_FORM_IDS)

    def test_five_form_interval_only_fallback(self):
        records = synthetic_records([
            (form, metrics(0.0), metrics(0.1), metrics(0.1)) for form in self.FORMS[:5]])
        analysis = runner.analyze_replay(records)
        inference = analysis["inference"]
        self.assertEqual(inference["result"], "five_form_interval_only")
        self.assertEqual(inference["k"], 5)
        self.assertEqual(inference["interval"]["df"], 4)
        self.assertFalse(inference["sign_flip"]["reported"])
        self.assertTrue(inference["sign_flip"]["forbidden_two_sided_below_0_05"])
        self.assertFalse(inference["causal_gate_released"])
        self.assertIn("interval-only descriptive", inference["statement"])

    def test_below_five_forms_is_coverage_failure(self):
        records = synthetic_records([
            (form, metrics(0.0), metrics(0.1), metrics(0.1)) for form in self.FORMS[:3]])
        analysis = runner.analyze_replay(records)
        self.assertEqual(analysis["inference"]["result"], "replay_coverage_failure")
        self.assertFalse(analysis["inference"]["causal_gate_released"])
        self.assertIn("replay-coverage failure", analysis["inference"]["statement"])

    def test_guard_values_computed_from_branch_metrics(self):
        form = self.FORMS[0]
        records = synthetic_records([
            (form, metrics(0.0, p_target=0.9, mass=1.0),
             metrics(0.4, p_target=0.4, mass=1.0), metrics(0.4))])
        analysis = runner.analyze_replay(records)
        event = analysis["per_event"][0]
        self.assertTrue(event["complete_pair"])
        self.assertAlmostEqual(event["d_i"], -0.4)
        guard = event["guards"]
        self.assertAlmostEqual(guard["delta_p_target_i"], 0.5)
        self.assertAlmostEqual(guard["delta_feasible_mass_i"], 0.0)
        self.assertTrue(guard["target_ok_i"])
        self.assertTrue(guard["mass_ok_i"])
        self.assertTrue(guard["useful_uptake_i"])
        form_guard = analysis["guards"]["per_form"][form]
        self.assertEqual(form_guard["target_ok"], 1)
        self.assertEqual(form_guard["useful_uptake"], 1)

    def test_failed_target_guard_still_included_in_primary(self):
        form = self.FORMS[0]
        records = synthetic_records([
            (form, metrics(0.3, p_target=0.2, mass=1.0),
             metrics(0.4, p_target=0.7, mass=1.0), metrics(0.4))])
        analysis = runner.analyze_replay(records)
        event = analysis["per_event"][0]
        self.assertTrue(event["complete_pair"])
        self.assertIsNotNone(event["d_i"])
        self.assertFalse(event["guards"]["target_ok_i"])
        self.assertFalse(event["guards"]["useful_uptake_i"])
        self.assertEqual(analysis["complete_pairs"], 1)
        self.assertEqual(analysis["missingness"]["complete_pairs_by_form"][form], 1)
        self.assertFalse(analysis["guards"]["filtered_primary_estimate"])

    def test_mass_guard_direction(self):
        form = self.FORMS[0]
        records = synthetic_records([
            (form, metrics(0.0, mass=0.5), metrics(0.4, mass=1.0), metrics(0.4))])
        guard = runner.analyze_replay(records)["per_event"][0]["guards"]
        self.assertAlmostEqual(guard["delta_feasible_mass_i"], -0.5)
        self.assertFalse(guard["mass_ok_i"])
        self.assertFalse(guard["useful_uptake_i"])


class OfflineCliTests(unittest.TestCase):
    """Offline CLI behaviour, isolated in a lock-time sandbox.

    The committed stopped replay journal/report occupy the registered output
    paths, so production freshness checks must fail against ``REPO_ROOT``. Each
    test therefore runs against :func:`lock_time_sandbox`, while ``setUp``/
    ``tearDown`` prove the real replay artifacts stayed byte-identical.
    """

    def setUp(self):
        self.assertTrue(REPLAY_JOURNAL.is_file(),
                        "stopped replay journal must exist for this suite")
        self.assertTrue(REPLAY_REPORT.is_file(),
                        "stopped replay report must exist for this suite")
        self.artifacts = artifact_snapshot()
        self.replay_dir_listing = sorted(
            os.listdir(REPO_ROOT / "runs/epic-126/replay-v4"))
        self.sandbox_root = lock_time_sandbox(self)

    def tearDown(self):
        self.assertEqual(artifact_snapshot(), self.artifacts,
                         "a replay-v4 artifact changed during the test")
        self.assertEqual(
            sorted(os.listdir(REPO_ROOT / "runs/epic-126/replay-v4")),
            self.replay_dir_listing,
            "the replay-v4 output directory gained or lost a file")

    def run_cli(self, argv, *, explode_message="provider call"):
        """Run the offline CLI against the lock-time sandbox."""

        import contextlib
        buffer = io.StringIO()
        with patch.object(jc.JevChoiceClient, "complete",
                          side_effect=AssertionError(explode_message)), \
                patch("urllib.request.urlopen",
                      side_effect=AssertionError(explode_message)), \
                contextlib.redirect_stdout(buffer):
            rc = runner.main(argv)
        return rc, buffer.getvalue()

    def test_sandbox_isolates_the_stopped_replay_outputs(self):
        sandbox_journal = (self.sandbox_root / REPLAY_JOURNAL.relative_to(REPO_ROOT))
        sandbox_report = (self.sandbox_root / REPLAY_REPORT.relative_to(REPO_ROOT))
        sandbox_registration = (
            self.sandbox_root / REPLAY_REGISTRATION.relative_to(REPO_ROOT))
        self.assertFalse(sandbox_journal.exists())
        self.assertFalse(sandbox_report.exists())
        self.assertTrue(sandbox_registration.is_file())
        self.assertEqual(sandbox_registration.read_bytes(),
                         REPLAY_REGISTRATION.read_bytes())
        self.assertTrue(REPLAY_JOURNAL.is_file())
        self.assertTrue(REPLAY_REPORT.is_file())

    def test_offline_cli_zero_provider_calls(self):
        rc, output = self.run_cli(["--repo-root", str(self.sandbox_root)],
                                  explode_message="provider call during offline CLI")
        self.assertEqual(rc, 0)
        self.assertIn("preflight only", output)
        self.assertIn('"provider_calls": 0', output)
        self.assertFalse(
            (self.sandbox_root / REPLAY_JOURNAL.relative_to(REPO_ROOT)).exists())
        self.assertFalse(
            (self.sandbox_root / REPLAY_REPORT.relative_to(REPO_ROOT)).exists())

    def test_live_without_approval_zero_provider_calls(self):
        rc, output = self.run_cli(["--repo-root", str(self.sandbox_root), "--live"],
                                  explode_message="provider call")
        self.assertEqual(rc, 2)
        verification = json.loads(output)
        self.assertFalse(verification["ok"])
        self.assertIn("approval_present", verification["failed"])
        self.assertFalse(
            (self.sandbox_root / REPLAY_JOURNAL.relative_to(REPO_ROOT)).exists())
        self.assertFalse(
            (self.sandbox_root / REPLAY_REPORT.relative_to(REPO_ROOT)).exists())

    def test_production_preflight_rejects_occupied_registered_paths(self):
        """The real checkout keeps its freshness gate: occupied paths fail closed."""

        import contextlib
        buffer = io.StringIO()
        with patch.object(jc.JevChoiceClient, "complete",
                          side_effect=AssertionError("provider call")), \
                patch("urllib.request.urlopen",
                      side_effect=AssertionError("provider call")), \
                contextlib.redirect_stdout(buffer):
            rc = runner.main(["--repo-root", str(REPO_ROOT)])
        self.assertEqual(rc, 2)
        verification = json.loads(buffer.getvalue())
        self.assertFalse(verification["ok"])
        self.assertIn("journal_path_fresh", verification["failed"])
        self.assertIn("report_path_fresh", verification["failed"])
        self.assertIn("registration_verifies", verification["failed"])
        # failed preflight must not write anything
        self.assertEqual(artifact_snapshot(), self.artifacts)
        self.assertFalse(
            (self.sandbox_root / REPLAY_JOURNAL.relative_to(REPO_ROOT)).exists())

    def test_replay_artifacts_byte_identical_after_cli(self):
        before = artifact_snapshot()
        self.run_cli(["--repo-root", str(self.sandbox_root)])
        self.run_cli(["--repo-root", str(REPO_ROOT)])
        self.assertEqual(artifact_snapshot(), before)

    def test_cli_has_no_output_overrides(self):
        import contextlib
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stdout(io.StringIO()):
                runner.main(["--repo-root", str(REPO_ROOT), "--journal", "/tmp/x.jsonl"])


if __name__ == "__main__":
    unittest.main()
