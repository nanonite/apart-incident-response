import contextlib
import copy
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_choice_v2 as jc2
from apart_incident_response import jev_replay_preregistration as pr
from apart_incident_response import jev_replay_preregistration_v4 as prv4
from apart_incident_response import jev_replay_preregistration_v5 as prv5
from apart_incident_response import jev_replay_runner_v4 as _v4
from apart_incident_response import jev_replay_runner_v5 as runner


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRATION_PATH = REPO_ROOT / prv5.DEFAULT_OUTPUT_V5
REGISTRATION = json.loads(REGISTRATION_PATH.read_text(encoding="utf-8"))
PIN = REGISTRATION["preregistration_hash"]
V4_PATHS = (REPO_ROOT / prv4.DEFAULT_OUTPUT_V4, REPO_ROOT / prv4.DEFAULT_JOURNAL_V4,
            REPO_ROOT / prv4.DEFAULT_REPORT_V4)
OK_VERIFICATION = {"ok": True, "checks": [], "failed": []}


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_docs(output: str) -> list:
    """Decode every concatenated JSON document the CLI printed."""

    decoder = json.JSONDecoder()
    index, docs = 0, []
    while index < len(output):
        while index < len(output) and output[index] in " \n\t\r":
            index += 1
        if index >= len(output):
            break
        document, index = decoder.raw_decode(output, index)
        docs.append(document)
    return docs


def v4_snapshot() -> dict:
    return {str(path.relative_to(REPO_ROOT)): sha256_of(path) for path in V4_PATHS}


class FakeReceiverClient:
    provider = "jev"
    endpoint = jc.JEV_SYSTEMONE_ENDPOINT
    max_retries = pr.JEV_REPLAY_MAX_RETRIES

    def __init__(self, *, max_physical_requests=153, fail_calls=()):
        self.max_physical_requests = max_physical_requests
        self.physical_attempts = 0
        self.calls = 0
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
        return {"model": jc.JEV_DEFAULT_MODEL,
                "answers": {question_id: {"type": "choice", "choice": option_ids[0],
                                          "probabilities": probabilities,
                                          "confidence": 0.5}},
                "usage": {"input_tokens": 10, "output_tokens": 2}}


def v5_sandbox(test_case: unittest.TestCase) -> Path:
    """Repo root with a materialised replay-v5 directory and no v5 outputs."""

    root = Path(tempfile.mkdtemp(prefix="replay-v5-cli-"))
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


def execute(registration=None, *, receiver=None, approval="test",
            verification=None, repo_root=None):
    registration = registration if registration is not None else REGISTRATION
    if receiver is None:
        receiver = jc2.JevChoiceAdapterV2(FakeReceiverClient(), model=pr.JEV_REPLAY_MODEL)
    used_verification = verification if verification is not None else OK_VERIFICATION
    root = repo_root if repo_root is not None else Path(
        tempfile.mkdtemp(prefix="replay-v5-exec-"))
    report = runner.execute(registration, receiver, verification=used_verification,
                            approval=approval, repo_root=root,
                            pinned_hash=registration.get("preregistration_hash"),
                            sleep_fn=lambda _: None)
    journal = root / registration["outputs"]["journal"]
    rows = []
    if journal.exists():
        for line in journal.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return report, receiver, journal, rows


class V5TestCase(unittest.TestCase):
    """Every test proves the superseded v4 evidence and v5 outputs stay put."""

    def setUp(self):
        self.v4 = v4_snapshot()
        self.assertFalse((REPO_ROOT / prv5.DEFAULT_JOURNAL_V5).exists(),
                         "v5 journal must be absent until an authorized run")
        self.assertFalse((REPO_ROOT / prv5.DEFAULT_REPORT_V5).exists(),
                         "v5 report must be absent until an authorized run")

    def tearDown(self):
        self.assertEqual(v4_snapshot(), self.v4, "a superseded v4 artifact changed")
        self.assertFalse((REPO_ROOT / prv5.DEFAULT_JOURNAL_V5).exists())
        self.assertFalse((REPO_ROOT / prv5.DEFAULT_REPORT_V5).exists())

    def run_cli(self, argv, *, explode_message="provider call"):
        buffer = io.StringIO()
        with patch.object(jc.JevChoiceClient, "complete",
                          side_effect=AssertionError(explode_message)), \
                patch("urllib.request.urlopen",
                      side_effect=AssertionError(explode_message)), \
                contextlib.redirect_stdout(buffer):
            rc = runner.main(argv)
        return rc, buffer.getvalue()


class PreflightTests(V5TestCase):
    def test_offline_preflight_passes_with_named_checks(self):
        rc, output = self.run_cli(["--repo-root", str(REPO_ROOT)])
        self.assertEqual(rc, 0)
        self.assertIn("preflight only", output)
        self.assertIn('"provider_calls": 0', output)
        verification = parse_docs(output)[0]
        self.assertTrue(verification["ok"], verification["failed"])
        names = {check["check"] for check in verification["checks"]}
        for required in ("runtime_approval_present", "registration_verifies",
                         "registration_hash_matches", "status_locked",
                         "live_collection_not_authorized", "registration_version",
                         "approval_lock_scope", "superseded_v4_artifacts_pinned",
                         "frozen_scientific_content_verified",
                         "scientific_blocks_identical_to_v4",
                         "event_ids_exact_unique_ordered", "branch_schedule_event_major",
                         "branch_request_and_state_hashes", "jev_model_matches",
                         "jev_endpoint_matches", "jev_retry_policy",
                         "jev_bounded_pacing_enforced", "jev_protocol_key",
                         "codec_version", "jev_physical_cap_enforced",
                         "planned_calls_51_0", "cost_caps_and_reserve",
                         "fresh_output_paths", "fresh_output_paths_report",
                         "source_files_hash_matches", "no_mixed_protocol_keys",
                         "registration_content_matches", "registration_hash_matches"):
            self.assertIn(required, names)

    def test_live_without_approval_zero_provider_calls(self):
        rc, output = self.run_cli(["--repo-root", str(REPO_ROOT), "--live"])
        self.assertEqual(rc, 2)
        verification = parse_docs(output)[0]
        self.assertFalse(verification["ok"])
        self.assertIn("runtime_approval_present", verification["failed"])
        self.assertFalse((REPO_ROOT / prv5.DEFAULT_JOURNAL_V5).exists())
        self.assertFalse((REPO_ROOT / prv5.DEFAULT_REPORT_V5).exists())

    def test_occupied_new_paths_block_execution(self):
        root = v5_sandbox(self)
        journal = root / prv5.DEFAULT_JOURNAL_V5
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text("SENTINEL", encoding="utf-8")
        rc, output = self.run_cli(["--repo-root", str(root), "--live",
                                   "--approval", "ref"])
        self.assertEqual(rc, 2)
        verification = parse_docs(output)[0]
        self.assertFalse(verification["ok"])
        self.assertIn("fresh_output_paths", verification["failed"])
        self.assertEqual(journal.read_text(encoding="utf-8"), "SENTINEL")
        self.assertFalse((root / prv5.DEFAULT_REPORT_V5).exists())

    def test_failed_preflight_zero_provider_calls_and_no_files(self):
        with tempfile.TemporaryDirectory(prefix="replay-v5-broken-") as directory:
            root = Path(directory)
            target = root / prv5.DEFAULT_OUTPUT_V5
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REGISTRATION_PATH, target)
            rc, _ = self.run_cli(["--repo-root", str(root), "--live", "--approval", "ref"])
            self.assertEqual(rc, 2)
            self.assertEqual(list(root.rglob("*.jsonl")), [])
            self.assertEqual([p for p in root.rglob("*.json") if p != target], [])

    def test_production_rejects_v4_paths_as_v5_outputs(self):
        tampered = copy.deepcopy(REGISTRATION)
        tampered["outputs"]["journal"] = str(prv4.DEFAULT_JOURNAL_V4)
        result = prv5.verify_against_jev_replay_preregistration_v5(
            tampered, repo_root=REPO_ROOT, check_credentials=False)
        self.assertFalse(result["ok"])
        failed = [error.split(":")[0] for error in result["errors"]]
        self.assertIn("outputs_are_v5", failed)
        self.assertIn("no_stale_or_superseded_output_paths", failed)

    def test_cli_has_no_output_overrides(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                runner.main(["--repo-root", str(REPO_ROOT), "--journal", "/tmp/x.jsonl"])


class TransportContractTests(V5TestCase):
    def test_bounded_pacing_applied_to_client(self):
        receiver = runner.build_receiver(REGISTRATION)
        client = receiver.client
        self.assertEqual(client._backoff_initial, prv5.BACKOFF_V5["initial_seconds"])
        self.assertEqual(client._backoff_max, prv5.BACKOFF_V5["max_seconds"])
        self.assertEqual(client._backoff_jitter, prv5.BACKOFF_V5["jitter"])
        self.assertEqual(client.max_retries, 2)
        self.assertEqual(client.max_physical_requests, 153)
        self.assertEqual(client.endpoint, pr.JEV_REPLAY_ENDPOINT)
        self.assertEqual(client.model, pr.JEV_REPLAY_MODEL)

    def test_bounded_pacing_rejected_when_not_registered(self):
        tampered = copy.deepcopy(REGISTRATION)
        tampered["model_and_protocol"]["backoff"] = dict(prv5.BACKOFF_V4)
        with self.assertRaises(ValueError):
            runner.build_receiver(tampered)

    def test_registration_backoff_matches_operational_policy(self):
        pacing = REGISTRATION["operational_policy"]["decisions"]["bounded_pacing"]
        self.assertEqual(REGISTRATION["model_and_protocol"]["backoff"], pacing["to"])
        self.assertEqual(pacing["from"], dict(prv5.BACKOFF_V4))


class ExecutionTests(V5TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report, cls.receiver, cls.journal, cls.rows = execute()

    def test_fake_run_completes_and_is_stamped_v5(self):
        self.assertEqual(self.report["status"], "completed")
        self.assertEqual(self.report["attempted_branches"], 51)
        self.assertEqual(self.report["valid_branches"], 51)
        self.assertEqual(len(self.rows), 51)
        self.assertEqual(self.report["mode"], "jev-choice-replay-runner-v5")
        self.assertEqual(self.report["registration_version"],
                         prv5.JEV_REPLAY_V5_PREREG_VERSION)
        self.assertEqual(self.report["registration_hash"], PIN)
        runner_info = self.report["runner"]
        self.assertEqual(runner_info["entrypoint"], prv5.RUNNER_SOURCE_REL_V5)
        self.assertEqual(runner_info["executes_schedule_via"], prv5.RUNNER_SOURCE_REL_V4)
        self.assertEqual(runner_info["bounded_pacing"], dict(prv5.BACKOFF_V5))

    def test_registered_schedule_and_analysis_intact(self):
        schedule = REGISTRATION["branch_schedule"]
        self.assertTrue(self.report["schedule_adherence"]["planned_equals_actual"])
        self.assertEqual([event["event_id"] for event in self.report["events"]],
                         schedule["event_order"])
        analysis = self.report["analysis"]
        self.assertEqual(len(analysis["per_event"]), 17)
        self.assertIn("missingness", self.report)
        branch_totals = {branch: sum(1 for row in self.rows if row["branch"] == branch)
                         for branch in ("real", "placebo", "null")}
        self.assertEqual(branch_totals, {"real": 17, "placebo": 17, "null": 17})

    def test_journal_written_under_registered_v5_path(self):
        self.assertTrue(str(self.journal).endswith(str(prv5.DEFAULT_JOURNAL_V5)),
                        self.journal)
        self.assertEqual(len(self.rows), 51)
        for row in self.rows:
            self.assertFalse(row["raw_response_retained"])
            self.assertFalse(row["credentials_retained"])

    def test_fsync_once_per_row(self):
        real_fsync = os.fsync
        calls = []

        def spy(fd):
            calls.append(fd)
            return real_fsync(fd)

        with patch("os.fsync", side_effect=spy):
            report, _receiver, _journal, rows = execute()
        self.assertEqual(report["status"], "completed")
        self.assertEqual(len(rows), 51)
        self.assertEqual(len(calls), 51)

    def test_partial_failure_journaled_durably(self):
        report, _receiver, journal, rows = execute(
            receiver=jc2.JevChoiceAdapterV2(FakeReceiverClient(fail_calls=(0, 1)),
                                            model=pr.JEV_REPLAY_MODEL))
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "provider_failure_limit")
        self.assertEqual(len(rows), 2)
        self.assertTrue(journal.exists())
        for row in rows:
            self.assertFalse(row["valid"])
            self.assertEqual(row["error_class"], "transport_error")
            self.assertNotIn("simulated", json.dumps(row))
        first_event = REGISTRATION["branch_schedule"]["event_order"][0]
        entry = report["missingness"]["by_event"][first_event]
        self.assertEqual((entry["attempted"], entry["unattempted"]), (2, 1))
        self.assertTrue(entry["partial_triplet"])
        reread = [json.loads(line) for line in
                  journal.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(reread, rows)

    def test_no_resume_append_or_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="replay-v5-resume-") as directory:
            root = Path(directory)
            journal = root / prv5.DEFAULT_JOURNAL_V5
            journal.parent.mkdir(parents=True, exist_ok=True)
            journal.write_text("SENTINEL", encoding="utf-8")
            report, receiver, path, rows = execute(repo_root=root)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["stop_reason"], "output_exists")
            self.assertEqual(journal.read_text(encoding="utf-8"), "SENTINEL")
            self.assertEqual(receiver.client.calls, 0)
            self.assertEqual(rows, [])

            # BranchJournal refuses to open an existing file: no append, no overwrite
            with self.assertRaises(FileExistsError):
                _v4.BranchJournal(journal)
            self.assertEqual(journal.read_text(encoding="utf-8"), "SENTINEL")

    def test_duplicate_branch_key_rejected(self):
        with tempfile.TemporaryDirectory(prefix="replay-v5-dup-") as directory:
            path = Path(directory) / "j.jsonl"
            journal = runner.BranchJournal(path)
            journal.write({"event_id": "e1", "branch": "real"})
            journal.write({"event_id": "e1", "branch": "placebo"})
            self.assertEqual(journal.fsync_count, 2)
            with self.assertRaises(runner.BranchJournalError):
                journal.write({"event_id": "e1", "branch": "real"})
            self.assertTrue(journal.handle.closed)
            self.assertEqual(len(journal.read_rows()), 2)

    def test_schedule_and_hash_drift_stop_before_any_call(self):
        tampered = copy.deepcopy(REGISTRATION)
        first = tampered["branch_schedule"]["event_order"][0]
        tampered["branch_schedule"]["schedule"][first] = ["real", "real", "null"]
        report, receiver, _journal, rows = execute(registration=tampered)
        self.assertTrue(report["stop_reason"].startswith("plan_drift"),
                        report["stop_reason"])
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(rows, [])

        tampered = copy.deepcopy(REGISTRATION)
        tampered["events"][0]["pre_read"]["branch_request_hashes"]["real"] = "0" * 64
        report, receiver, _journal, rows = execute(registration=tampered)
        self.assertEqual(report["stop_reason"], "branch_request_hash_mismatch")
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(rows, [])

    def test_credentials_never_written(self):
        for row in self.rows:
            text = json.dumps(row)
            self.assertNotIn("Bearer ", text)
            self.assertNotIn('"authorization"', text.lower())


class DelegationTests(V5TestCase):
    def test_schedule_executor_is_the_reviewed_v4_module(self):
        self.assertIs(runner.BranchJournal, _v4.BranchJournal)
        self.assertIs(runner.build_replay_plan, _v4.build_replay_plan)
        self.assertIs(runner.analyze_replay, _v4.analyze_replay)
        self.assertIs(runner.PROVIDER_FAILURE_CLASSES, _v4.PROVIDER_FAILURE_CLASSES)

    def test_runner_binding_is_source_bound_and_non_authorizing(self):
        policy = REGISTRATION["runner_policy"]
        self.assertEqual(policy["runner_source_files"],
                         [prv5.RUNNER_SOURCE_REL_V5, prv5.RUNNER_SOURCE_REL_V4])
        self.assertTrue(policy["runner_source_bound"])
        self.assertIs(policy["adding_runner_authorizes_collection"], False)
        for name in policy["runner_source_files"]:
            self.assertIn(name, REGISTRATION["source_files"])
        self.assertIs(REGISTRATION["live_collection_authorized"], False)


if __name__ == "__main__":
    unittest.main()
