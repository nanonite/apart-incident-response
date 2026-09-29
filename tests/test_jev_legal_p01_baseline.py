"""L01 (#219) focused validation: offline evidence index with zero network events.

Everything in this suite is recomputed from files on disk. A process-wide audit
hook records any ``socket.*`` / ``urllib.*`` / ``http.client.*`` /
``ftplib.*`` event and ``urllib.request.urlopen`` is replaced by a raising stub
for the build, so a provider call fails the suite instead of escaping it.
"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import jev_legal_p01_baseline as p01
from apart_incident_response import jev_ling_writer_v5 as writer_v5
from apart_incident_response import jev_p06_discovery_runner as p06
from apart_incident_response import behavioral_discovery as bd

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = REPO_ROOT / "runs" / "next-phase" / "legal" / "jev-legal-p01-evidence-v1.json"
DOC = REPO_ROOT / "docs" / "jev-legal-p01-baseline.md"
TERMINAL = REPO_ROOT / "docs" / "jev-hypothesis-low-terminal-decision.md"
PROTOCOL = REPO_ROOT / "docs" / "jev-discovery-confirmation-plan.md"
JOURNAL = REPO_ROOT / "runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection.jsonl"
REPORT = REPO_ROOT / "runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection-report.json"
REGISTRATION = REPO_ROOT / "runs/next-phase/jev-p04-discovery-registration-v1.json"
LOCK = REPO_ROOT / "runs/next-phase/jev-p05-discovery-lock-v1.json"
AUTH = REPO_ROOT / "runs/next-phase/jev-discovery-authorization-record-v1.json"
AUDIT_200 = REPO_ROOT / "runs/epic-126/replication/jev-replication-form-audit-v1.json"
WRITER_SOURCE = REPO_ROOT / "src/apart_incident_response/jev_ling_writer_v5.py"
RUNNER_SOURCE = REPO_ROOT / "src/apart_incident_response/jev_p06_discovery_runner.py"

#: sha256 recomputed from disk; the #219 prefixes pin these five inputs.
PINNED_SHA256 = {
    "docs/jev-hypothesis-low-terminal-decision.md":
        "89ef2aafb5e28f12d0db707499c583d89cdcc490d105c23c3c56b39e11818d0b",
    "runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection.jsonl":
        "4e8de096f2c30a6a36a94a0f79e5f450c2e196123e3eafe1c310a92c4f334c83",
    "runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection-report.json":
        "3086ceac558ff922bd083db3795f5f1aa5c7127813daba8bfd71ae1fbef09d3c",
    "runs/epic-126/replication/jev-replication-form-audit-v1.json":
        "cb529cd61e0e662bfa19fc4998e89fa59a0bf0d63e14f77498035466d6bce89d",
    "docs/jev-discovery-confirmation-plan.md":
        "501e21b6dea760371b0bf368046d8bacd203f6b92f0af754a7955d1f738677f7",
}

FROZEN_PATHS = sorted(set(PINNED_SHA256) | {
    "runs/next-phase/jev-p04-discovery-registration-v1.json",
    "runs/next-phase/jev-p05-discovery-lock-v1.json",
    "runs/next-phase/jev-discovery-authorization-record-v1.json",
    "src/apart_incident_response/jev_ling_writer_v5.py",
    "src/apart_incident_response/jev_p06_discovery_runner.py",
    "docs/jev-legal-task-sequence.md",
    "docs/jev-legal-p01-baseline.md",
    "runs/next-phase/legal/jev-legal-p01-evidence-v1.json",
})

REQUIRED_PHRASES = [
    "#219", "#218", "#159", "#215", "#220", "legal:low", "L01",
    "89ef2aafb5e28f12d0db707499c583d89cdcc490d105c23c3c56b39e11818d0b",
    "4e8de096f2c30a6a36a94a0f79e5f450c2e196123e3eafe1c310a92c4f334c83",
    "3086ceac558ff922bd083db3795f5f1aa5c7127813daba8bfd71ae1fbef09d3c",
    "cb529cd61e0e662bfa19fc4998e89fa59a0bf0d63e14f77498035466d6bce89d",
    "501e21b6dea760371b0bf368046d8bacd203f6b92f0af754a7955d1f738677f7",
    "zero network events", "audit hook", "not a new approval",
    "finish_reason", "rate limiting", "truncated_output",
    "writer_error:truncated_output", "not_attempted:truncated_output",
    "1024-token", "at least 1005",
    "$0.00039726", "534", "2029", "Handoff to L02",
    "Cannot be inferred", "Can be inferred",
    "A failed or stopped predecessor never authorizes its successor",
    "no provider call", "byte-identical", "OpenCode Go",
    "85000", "87511", "19/19",
]

BANNED_PHRASES = [
    "this task authorizes collection",
    "authorizes the live run",
    "locking authorizes execution",
    "proves the hypothesis",
    "population-representative",
    "generalizes to other families",
    "rate limiting caused",
    "legal:low collection is authorized",
]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _explode(*_args, **_kwargs):
    raise AssertionError("provider call attempted during an offline L01 check")


_NETWORK_EVENTS: list[str] = []


def _audit_hook(event, _args):
    if event.startswith(("socket.", "urllib.", "http.client.", "ftplib.")):
        _NETWORK_EVENTS.append(event)


sys.addaudithook(_audit_hook)


class L01TestCase(unittest.TestCase):
    """Every test proves the frozen inputs stayed byte-identical."""

    def setUp(self):
        self.before = {relative: sha256_of(REPO_ROOT / relative)
                       for relative in FROZEN_PATHS}
        self.legal_outputs_before = sorted(
            path.name for path in (REPO_ROOT / "runs" / "next-phase" / "legal").glob("*"))

    def tearDown(self):
        self.assertEqual({relative: sha256_of(REPO_ROOT / relative)
                          for relative in FROZEN_PATHS}, self.before,
                         "a frozen or L01 input changed during the test")
        self.assertEqual(sorted(path.name for path in
                                (REPO_ROOT / "runs" / "next-phase" / "legal").glob("*")),
                         self.legal_outputs_before,
                         "the L01 output directory changed state during the test")

    def build_offline(self):
        _NETWORK_EVENTS.clear()
        with patch("urllib.request.urlopen", _explode):
            document = p01.build_evidence(REPO_ROOT)
        self.assertEqual(_NETWORK_EVENTS, [], "network event during the offline build")
        return document


class HashIntegrityTests(L01TestCase):
    def test_pinned_input_hashes_match_the_task_prefixes(self):
        for relative, expected in PINNED_SHA256.items():
            with self.subTest(path=relative):
                self.assertEqual(sha256_of(REPO_ROOT / relative), expected)

    def test_terminal_report_cites_the_recomputed_bytes(self):
        text = TERMINAL.read_text(encoding="utf-8")
        for relative in ("runs/next-phase/hypothesis/jev-discovery-v1/"
                         "jev-discovery-collection.jsonl",
                         "runs/next-phase/hypothesis/jev-discovery-v1/"
                         "jev-discovery-collection-report.json",
                         "docs/jev-discovery-confirmation-plan.md"):
            with self.subTest(path=relative):
                self.assertIn(PINNED_SHA256[relative], text)

    def test_content_hashes_recompute_from_the_frozen_documents(self):
        registration = json.loads(REGISTRATION.read_text(encoding="utf-8"))
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        recomputed_registration = hashlib.sha256(json.dumps(
            {key: value for key, value in registration.items()
             if key != "registration_hash"}, sort_keys=True).encode()).hexdigest()
        recomputed_lock = hashlib.sha256(json.dumps(
            {key: value for key, value in lock.items() if key != "lock_hash"},
            sort_keys=True).encode()).hexdigest()
        self.assertEqual(recomputed_registration, p06.REGISTRATION_HASH)
        self.assertEqual(recomputed_lock, p06.LOCK_HASH)
        self.assertEqual(registration["registration_hash"], p06.REGISTRATION_HASH)
        self.assertEqual(lock["lock_hash"], p06.LOCK_HASH)
        auth = json.loads(AUTH.read_text(encoding="utf-8"))
        self.assertEqual(auth["scope_digest_sha256"], p06.SCOPE_DIGEST)
        report = json.loads(REPORT.read_text(encoding="utf-8"))
        self.assertEqual(report["registration_hash"], p06.REGISTRATION_HASH)
        self.assertEqual(report["lock_hash"], p06.LOCK_HASH)


class JournalRecomputationTests(L01TestCase):
    def setUp(self):
        super().setUp()
        self.rows = [json.loads(line) for line in
                     JOURNAL.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.report = json.loads(REPORT.read_text(encoding="utf-8"))
        self.registration = json.loads(REGISTRATION.read_text(encoding="utf-8"))

    def test_sixteen_row_stop_in_registered_manifest_order(self):
        manifest = self.registration["fixed_n"]["manifest"]
        self.assertEqual(len(self.rows), 16)
        self.assertEqual(len({row["instance_id"] for row in self.rows}), 16)
        self.assertEqual([row["sequence"] for row in self.rows], list(range(1, 17)))
        self.assertEqual([(row["instance_id"], row["seed"], row["prompt_form_id"])
                          for row in self.rows],
                         [(entry["instance_id"], entry["seed"], entry["prompt_form_id"])
                          for entry in manifest])
        self.assertTrue(all(85000 <= row["seed"] <= 85511 for row in self.rows))
        self.assertFalse(any(87000 <= row["seed"] <= 87511 for row in self.rows))

    def test_status_counts_and_failure_reasons(self):
        counts = {key: sum(1 for row in self.rows if row["status"] == key)
                  for key in ("failed", "not_attempted", "ok", "silence")}
        self.assertEqual(counts, {"failed": 1, "not_attempted": 15, "ok": 0, "silence": 0})
        failed = next(row for row in self.rows if row["status"] == "failed")
        self.assertEqual(failed["failure_reason"], "writer_error:truncated_output")
        self.assertEqual({row["failure_reason"] for row in self.rows
                          if row["status"] == "not_attempted"},
                         {"not_attempted:truncated_output"})
        self.assertEqual([(writer["agent"], writer["turn"], writer["outcome"])
                          for writer in failed["emission"]["writer_outcomes"]],
                         [("A", 0, "deliberate_silence"), ("B", 0, "deliberate_silence"),
                          ("A", 1, "truncated_output")])

    def test_three_ling_zero_jev_calls_and_token_totals(self):
        provider_calls = sum(row["provider_calls"] for row in self.rows)
        physical = {key: sum(row["physical_attempts"][key] for row in self.rows)
                    for key in ("ling", "jev", "combined")}
        tokens = {key: sum(row["token_usage"][key] for row in self.rows)
                  for key in ("ling_input_tokens", "ling_output_tokens",
                              "jev_input_tokens", "jev_output_tokens")}
        self.assertEqual(provider_calls, 3)
        self.assertEqual(physical, {"ling": 3, "jev": 0, "combined": 3})
        self.assertEqual(tokens, {"ling_input_tokens": 534, "ling_output_tokens": 2029,
                                  "jev_input_tokens": 0, "jev_output_tokens": 0})
        self.assertEqual(self.report["provider_calls"], 3)
        self.assertEqual(self.report["caps"]["physical_used"], {"jev": 0, "ling": 3})

    def test_cost_recomputes_from_the_registered_rates(self):
        cost_model = self.registration["budgets"]["cost_model"]
        self.assertEqual((cost_model["ling_prompt_usd_per_mtok"],
                          cost_model["ling_completion_usd_per_mtok"]), (0.06, 0.18))
        recomputed = (534 * 0.06 + 2029 * 0.18) / 1_000_000
        self.assertAlmostEqual(recomputed, 0.00039726, places=12)
        self.assertEqual(sum(row["cost"]["usd"] for row in self.rows), 0.00039726)
        self.assertEqual(self.report["caps"]["cost_usd"], 0.00039726)
        self.assertLessEqual(recomputed,
                             self.registration["budgets"]["discovery_collection"]["cost_ceiling_usd"])
        self.assertLessEqual(recomputed, self.registration["budgets"]["program"]["cost_ceiling_usd"])

    def test_report_cross_checks_the_journal(self):
        self.assertEqual(self.report["status"], "stopped")
        self.assertEqual(self.report["stop_reason"], "truncated_output")
        self.assertEqual(self.report["journaled_seeds"], 16)
        self.assertEqual(self.report["planned_seeds"], 16)
        self.assertEqual(self.report["counts"],
                         {"failed": 1, "not_attempted": 15, "ok": 0, "silence": 0})
        self.assertEqual(self.report["seeds"],
                         [row["instance_id"] for row in self.rows])
        self.assertEqual(self.report["credentials_retained"], False)


class TruncationDiagnosisTests(L01TestCase):
    def setUp(self):
        super().setUp()
        self.rows = [json.loads(line) for line in
                     JOURNAL.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.diagnostics = [record for row in self.rows
                            for writer in (row.get("emission") or {}).get("writer_outcomes") or ()
                            for record in writer["attempt_diagnostics"]]

    def test_all_attempts_are_http_200_without_rate_limit_signal(self):
        self.assertEqual(len(self.diagnostics), 3)
        self.assertEqual([record["status"] for record in self.diagnostics], [200, 200, 200])
        self.assertEqual([record["error_class"] for record in self.diagnostics],
                         [None, None, None])
        self.assertEqual([record["retry_ordinal"] for record in self.diagnostics], [0, 0, 0])
        self.assertFalse(any(record["retry_after_present"] for record in self.diagnostics))
        self.assertFalse(any(record["retry_after_ms_present"] for record in self.diagnostics))
        self.assertEqual([record["delay_source"] for record in self.diagnostics],
                         ["none", "none", "min_interval"])

    def test_a_rate_limit_would_have_been_recorded_distinctly(self):
        self.assertEqual(bd.classify_http_status(429), "rate_limited")
        self.assertEqual(f"writer_http_{429}_{bd.classify_http_status(429)}",
                         "writer_http_429_rate_limited")
        stops = json.loads(REGISTRATION.read_text(encoding="utf-8"))["stops"]
        self.assertTrue(any("rate-limited" in stop for stop in stops))

    def test_truncated_output_requires_finish_reason_length_on_non_empty_content(self):
        contents = ("", "   ", "SILENCE", "ANSWER: candidate-3", "MESSAGE: bit0=0",
                    "ANSWER: candidate-3\nMESSAGE: bit0=0")
        reasons = (None, "stop", "length", "content_filter")
        truncated = []
        for grammar in (writer_v5.GRAMMAR_EXPLICIT_SILENCE, writer_v5.GRAMMAR_ORIGINAL_LING):
            for reason in reasons:
                for content in contents:
                    result = writer_v5.classify_writer_completion(
                        content, reason, ["bit0=0"], grammar=grammar,
                        candidate_labels=["candidate-3"])
                    if result["outcome"] == writer_v5.OUTCOME_TRUNCATED_OUTPUT:
                        truncated.append((reason, result["content_length"]))
        self.assertTrue(truncated)
        self.assertTrue(all(reason == "length" and length > 0
                            for reason, length in truncated))
        for grammar in (writer_v5.GRAMMAR_EXPLICIT_SILENCE, writer_v5.GRAMMAR_ORIGINAL_LING):
            for content in contents:
                if not content.strip():
                    continue
                result = writer_v5.classify_writer_completion(
                    content, "length", ["bit0=0"], grammar=grammar,
                    candidate_labels=["candidate-3"])
                self.assertEqual(result["outcome"], writer_v5.OUTCOME_TRUNCATED_OUTPUT)

    def test_truncated_output_is_never_treated_as_silence(self):
        self.assertIn("truncated_output", p06.WRITER_TERMINAL_OUTCOMES)
        for grammar in (writer_v5.GRAMMAR_EXPLICIT_SILENCE, writer_v5.GRAMMAR_ORIGINAL_LING):
            blank = writer_v5.classify_writer_completion("", "length", [], grammar=grammar)
            self.assertEqual(blank["outcome"], writer_v5.OUTCOME_EMPTY_OUTPUT)
            self.assertNotEqual(blank["outcome"], writer_v5.OUTCOME_DELIBERATE_SILENCE)
        schema = writer_v5.writer_schema()
        self.assertIn("empty or truncated output is never silence", schema["silence_rule"])


class OutputCapTests(L01TestCase):
    def setUp(self):
        super().setUp()
        self.registration = json.loads(REGISTRATION.read_text(encoding="utf-8"))
        self.rows = [json.loads(line) for line in
                     JOURNAL.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_max_tokens_1024_is_pinned_by_registration_preflight_and_identity(self):
        self.assertEqual(self.registration["treatment"]["writer_prompt"]["max_tokens"], 1024)
        self.assertEqual(self.registration["budgets"]["cost_model"]["ling_output_token_ceiling"],
                         1024)
        runner_text = RUNNER_SOURCE.read_text(encoding="utf-8")
        self.assertIn('identity.get("max_tokens") != 1024', runner_text)
        self.assertIn('writer_contract.get("token_budget", -1)) == 1024', runner_text)
        self.assertIn('cost_model.get("ling_output_token_ceiling", 0)) == 1024', runner_text)
        writer_text = WRITER_SOURCE.read_text(encoding="utf-8")
        self.assertIn('elif reason == "length":', writer_text)
        for row in self.rows:
            for writer in (row.get("emission") or {}).get("writer_outcomes") or ():
                self.assertEqual(writer["request_identity"]["max_tokens"], 1024)

    def test_output_token_bound_is_derivable_but_exact_count_is_not(self):
        total = sum(row["token_usage"]["ling_output_tokens"] for row in self.rows)
        ceiling = self.registration["budgets"]["cost_model"]["ling_output_token_ceiling"]
        self.assertEqual(total, 2029)
        self.assertEqual(total - ceiling, 1005)
        self.assertEqual(ceiling, 1024)

    def test_finish_reason_is_not_persisted_in_the_journal_or_report(self):
        for row in self.rows:
            for writer in (row.get("emission") or {}).get("writer_outcomes") or ():
                self.assertNotIn("finish_reason", writer)
                self.assertFalse(any("finish_reason" in record
                                     for record in writer["attempt_diagnostics"]))
        self.assertNotIn("finish_reason", json.dumps(json.loads(REPORT.read_text())))


class EvidenceArtifactTests(L01TestCase):
    def test_committed_artifact_is_reproducible_under_audit(self):
        document = self.build_offline()
        self.assertEqual(json.loads(EVIDENCE.read_text(encoding="utf-8")), document)

    def test_every_named_check_passes_with_zero_network_events(self):
        document = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(len(document["checks"]), 19)
        self.assertEqual([entry["check"] for entry in document["checks"] if not entry["ok"]], [])
        self.assertTrue(all(entry["ok"] for entry in document["checks"]))
        self.assertEqual(document["network_audit"]["events"], 0)
        self.assertEqual(document["network_audit"]["event_names"], [])
        self.assertEqual(document["network_audit"]["provider_calls"], 0)

    def test_artifact_records_limitations_handoff_and_no_approval(self):
        document = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertTrue(document["limitations"])
        self.assertEqual(document["handoff"]["to"], "L02")
        self.assertEqual(document["handoff"]["issue"], 220)
        self.assertTrue(document["handoff"]["conditions"])
        facts = document["historical_facts"]
        self.assertFalse(facts["authorization_carried_into_legal_family"])
        self.assertFalse(facts["legal_family_route_status"]["authorized"])
        self.assertIn("not a new approval", facts["status"])
        self.assertEqual(facts["l4x_treatment"]["max_tokens"], 1024)
        self.assertIn("paid OpenRouter",
                      facts["route_used_by_stopped_hypothesis_run"]["ling"]["sku"])

    def test_cli_entry_point_writes_byte_identical_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence.json"
            _NETWORK_EVENTS.clear()
            with patch("urllib.request.urlopen", _explode):
                rc = p01.main(["--repo-root", str(REPO_ROOT), "--output", str(output)])
            self.assertEqual(_NETWORK_EVENTS, [])
            self.assertEqual(rc, 0)
            self.assertEqual(output.read_bytes(), EVIDENCE.read_bytes())


class BaselineDocumentTests(L01TestCase):
    def setUp(self):
        super().setUp()
        text = DOC.read_text(encoding="utf-8")
        self.normalized = " ".join(text.split())

    def test_required_statements_are_present(self):
        for phrase in REQUIRED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)

    def test_no_authorization_language_slips_in(self):
        lowered = self.normalized.lower()
        for phrase in BANNED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase.lower(), lowered)

    def test_document_pins_every_recomputed_input_digest(self):
        for relative, digest in PINNED_SHA256.items():
            with self.subTest(path=relative):
                self.assertIn(digest, self.normalized)


if __name__ == "__main__":
    unittest.main()
