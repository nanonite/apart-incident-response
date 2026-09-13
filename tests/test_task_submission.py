import json
import shutil
import tempfile
import unittest
from pathlib import Path

from apart_incident_response import (
    ConstrainedToolService,
    TaskCatalog,
    TaskDefinition,
    TaskToolService,
)
from apart_incident_response.runtime import AgentIdentity, Condition
from apart_incident_response.task_one import TASK_ONE_DIAGNOSIS
from apart_incident_response.tool_contract import (
    MAX_DIAGNOSIS_BYTES,
    MAX_EVIDENCE_EXCERPT_BYTES,
    MAX_EVIDENCE_REFERENCES,
)


class TaskSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="apart-task-submit-"))
        self.addCleanup(shutil.rmtree, self.temp)
        task_root = self.temp / "task"
        task_root.mkdir(mode=0o700)
        (task_root / "evidence.txt").write_text(
            "Revision ORCHID-731 changed CACHE_MODE.\n"
            "CACHE_MODE changed from local to shared, causing HTTP 503 outage.\n",
            encoding="utf-8",
        )
        (task_root / "other.txt").write_text("unpermitted evidence\n", encoding="utf-8")
        catalog = TaskCatalog({
            "task-1": TaskDefinition("task-1", task_root, ("evidence.txt",)),
        })
        self.service = ConstrainedToolService(
            TaskToolService(catalog),
            artifact_root=self.temp / "artifacts",
            clock=lambda: "2026-09-12T00:00:00Z",
        )
        self.identity = AgentIdentity("run-1", "agent-1", Condition.C1, "task-1", 7)
        self.credential = self.service.issue_credential(self.identity)

    def submit(self, arguments=None):
        return self.service.invoke(
            self.credential,
            "task_submit",
            arguments if arguments is not None else self.arguments(),
        )

    @staticmethod
    def arguments():
        return {
            "diagnosis": TASK_ONE_DIAGNOSIS,
            "evidence": [{
                "path": "evidence.txt",
                "line_start": 2,
                "line_end": 2,
                "excerpt": "CACHE_MODE changed from local to shared",
            }],
        }

    def artifact_path(self) -> Path:
        return self.temp / "artifacts" / "run-1" / "agents" / "agent-1" / "artifacts" / "task_submission.json"

    def audit_path(self) -> Path:
        return self.artifact_path().with_name("tool_calls.jsonl")

    def test_valid_submission_persists_evaluator_ready_artifact(self):
        self.service.update_runtime_usage(self.identity, 42, 3)
        response = self.submit()
        self.assertTrue(response["ok"])
        artifact = json.loads(self.artifact_path().read_text(encoding="utf-8"))
        self.assertEqual(artifact["run_id"], "run-1")
        self.assertEqual(artifact["agent_id"], "agent-1")
        self.assertEqual(artifact["task_id"], "task-1")
        self.assertEqual(artifact["timestamp"], "2026-09-12T00:00:00Z")
        self.assertEqual(artifact["diagnosis"], self.arguments()["diagnosis"])
        self.assertEqual(artifact["evidence"][0]["path"], "evidence.txt")
        self.assertEqual(artifact["evidence"][0]["line_start"], 2)
        self.assertEqual(artifact["token_usage"], {
            "source": "controller_runtime_accounting",
            "status": "provisional",
            "total_tokens": 42,
            "tool_calls": 3,
        })
        self.assertEqual(artifact["submission_id"], f"sha256:{artifact['submission_sha256']}")
        for path in (
            self.temp / "artifacts",
            self.temp / "artifacts" / "run-1",
            self.temp / "artifacts" / "run-1" / "agents",
            self.temp / "artifacts" / "run-1" / "agents" / "agent-1",
            self.artifact_path().parent,
        ):
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.artifact_path().stat().st_mode & 0o777, 0o600)

    def test_retry_is_idempotent_and_does_not_rewrite_artifact(self):
        self.service.update_runtime_usage(self.identity, 42, 3)
        first = self.submit()
        before = self.artifact_path().read_bytes()
        self.service.update_runtime_usage(self.identity, 99, 8)
        second = self.submit()
        self.assertEqual(first, second)
        self.assertEqual(before, self.artifact_path().read_bytes())

    def test_finalization_replaces_provisional_usage_with_drained_runtime_totals(self):
        self.service.update_runtime_usage(self.identity, 42, 3)
        self.assertTrue(self.submit()["ok"])
        provisional = json.loads(self.artifact_path().read_text(encoding="utf-8"))
        self.assertEqual(provisional["token_usage"]["status"], "provisional")
        self.service.update_runtime_usage(self.identity, 55, 4)
        self.service.finalize_runtime_usage(self.identity)
        final = json.loads(self.artifact_path().read_text(encoding="utf-8"))
        self.assertEqual(final["token_usage"], {
            "source": "controller_runtime_accounting",
            "status": "final",
            "total_tokens": 55,
            "tool_calls": 4,
        })
        self.assertEqual(final["submission_sha256"], provisional["submission_sha256"])

    def test_rejected_diagnosis_reports_missing_terms(self):
        self.service.update_runtime_usage(self.identity, 42, 3)
        arguments = self.arguments()
        arguments["diagnosis"] = "The configuration change broke the cache."
        response = self.submit(arguments)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "invalid_arguments")
        for term in ("orchid-731", "cache_mode", "local", "shared", "outage"):
            self.assertIn(term, response["error"]["message"])

    def test_conflicting_second_submission_is_rejected(self):
        self.service.update_runtime_usage(self.identity, 42, 3)
        self.assertTrue(self.submit()["ok"])
        conflicting = self.arguments()
        conflicting["diagnosis"] = (
            "The ORCHID-731 configuration revision changed CACHE_MODE from local to "
            "shared, triggering the cache-related outage."
        )
        response = self.submit(conflicting)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "invalid_arguments")

    def test_evidence_must_be_in_fixture_and_permission_set(self):
        self.service.update_runtime_usage(self.identity, 42, 3)
        invalid_cases = (
            {"path": "../evidence.txt", "excerpt": "ORCHID-731"},
            {"path": "/etc/hosts", "excerpt": "localhost"},
            {"path": "other.txt", "excerpt": "unpermitted"},
            {"path": "evidence.txt", "excerpt": "fabricated"},
            {"path": "evidence.txt", "line_start": 0, "line_end": 1},
            {"path": "evidence.txt", "line_start": 2, "line_end": 99},
        )
        for reference in invalid_cases:
            with self.subTest(reference=reference):
                response = self.submit({"diagnosis": "diagnosis", "evidence": [reference]})
                self.assertFalse(response["ok"])
                self.assertIn(response["error"]["code"], {"invalid_arguments", "permission_denied"})

    def test_malformed_oversized_and_fabricated_usage_inputs_are_rejected(self):
        self.service.update_runtime_usage(self.identity, 42, 3)
        cases = (
            {"diagnosis": "diagnosis", "evidence": "evidence.txt"},
            {"diagnosis": "diagnosis", "evidence": []},
            {"diagnosis": "diagnosis", "evidence": [{"path": "evidence.txt"}]},
            {"diagnosis": "diagnosis", "evidence": [{"path": "evidence.txt", "excerpt": None}]},
            {"diagnosis": "diagnosis", "evidence": [{"path": "evidence.txt", "line_start": 1}]},
            {"diagnosis": "diagnosis", "evidence": [{"path": "evidence.txt", "extra": 1, "excerpt": "ORCHID-731"}]},
            {"diagnosis": "a" * (MAX_DIAGNOSIS_BYTES + 1), "evidence": [{"path": "evidence.txt", "excerpt": "ORCHID-731"}]},
            {"diagnosis": "diagnosis", "evidence": [{"path": "evidence.txt", "excerpt": "x" * (MAX_EVIDENCE_EXCERPT_BYTES + 1)}]},
            {"diagnosis": "diagnosis", "evidence": [{"path": "evidence.txt", "excerpt": "ORCHID-731"}] * (MAX_EVIDENCE_REFERENCES + 1)},
            {"diagnosis": "diagnosis", "evidence": [{"path": "evidence.txt", "excerpt": "ORCHID-731"}], "usage": {"total_tokens": 1}},
        )
        for arguments in cases:
            with self.subTest(arguments=list(arguments)[:2]):
                response = self.submit(arguments)
                self.assertFalse(response["ok"])
                self.assertEqual(response["error"]["code"], "invalid_arguments")
        for usage in ((-1, 3), (42, -1), (True, 3), (42, False)):
            with self.subTest(usage=usage):
                with self.assertRaises(ValueError):
                    self.service.update_runtime_usage(self.identity, *usage)
        self.service.update_runtime_usage(self.identity, 50, 4)
        with self.assertRaises(ValueError):
            self.service.update_runtime_usage(self.identity, 49, 4)

    def test_identity_and_artifact_storage_fail_closed(self):
        other_identity = AgentIdentity("run-1", "agent-2", Condition.C1, "task-2", 7)
        other_credential = self.service.issue_credential(other_identity)
        response = self.service.invoke(other_credential, "task_submit", self.arguments())
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "permission_denied")
        self.assertFalse((self.temp / "artifacts" / "run-1" / "agents" / "agent-2" / "artifacts" / "task_submission.json").exists())

        task_service = TaskToolService(TaskCatalog({"task-1": TaskDefinition("task-1", self.temp / "task")}))
        without_storage = ConstrainedToolService(task_service)
        credential = without_storage.issue_credential(self.identity)
        without_storage.update_runtime_usage(self.identity, 1, 1)
        response = without_storage.invoke(credential, "task_submit", self.arguments())
        self.assertEqual(response["error"]["code"], "invalid_arguments")

    def test_credentials_are_redacted_from_submission_and_audit(self):
        self.service.update_runtime_usage(self.identity, 42, 3)
        provider_secret = "opencode-secret-for-audit-test"
        self.service.add_redaction_secret(provider_secret)
        arguments = self.arguments()
        arguments["diagnosis"] = (
            f"{TASK_ONE_DIAGNOSIS} Credential {self.credential} "
            f"Provider {provider_secret} was redacted."
        )
        response = self.submit(arguments)
        self.assertTrue(response["ok"])
        artifact_text = self.artifact_path().read_text(encoding="utf-8")
        audit_text = self.audit_path().read_text(encoding="utf-8")
        self.assertNotIn(self.credential, artifact_text)
        self.assertNotIn(self.credential, audit_text)
        self.assertNotIn(provider_secret, artifact_text)
        self.assertNotIn(provider_secret, audit_text)
        self.assertIn("<redacted-credential>", artifact_text)
        self.assertIn("<redacted-credential>", audit_text)
        self.assertIn("<redacted-provider-secret>", artifact_text)
        self.assertIn("<redacted-provider-secret>", audit_text)


if __name__ == "__main__":
    unittest.main()
