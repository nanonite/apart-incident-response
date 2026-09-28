import contextlib
import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import jev_p04_design_classification as p04
from apart_incident_response import jev_p05_discovery_lock as p05
from apart_incident_response import jev_p06_discovery_runner as p06


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = REPO_ROOT / "runs" / "next-phase" / "jev-p04-discovery-registration-v1.json"
LOCK = REPO_ROOT / "runs" / "next-phase" / "jev-p05-discovery-lock-v1.json"
AUTH = REPO_ROOT / "runs" / "next-phase" / "jev-discovery-authorization-record-v1.json"

# A reference that binds the scope digest (the digest is embedded in the reference).
def _digest_binding_reference():
    return f"AUTHREF-JEV-0001:{p06.SCOPE_DIGEST}"


class FakeTransport(p06.DiscoveryTransport):
    """Mocked provider transport; records every call it receives."""

    is_configured = True

    def __init__(self, behavior=None):
        self.behavior = behavior or {}
        self.calls = []
        self.receiver_calls = []

    def writer_completion(self, *, request):
        from apart_incident_response import task_families as tf
        from apart_incident_response.communication_protocol import DependenceRegime, ReasoningComplexity
        instance_id = request["instance_id"]
        agent = request.get("agent", "A")
        turn = request.get("turn", 0)
        self.calls.append((instance_id, agent, turn))
        key = (instance_id, agent, turn)
        outcome = self.behavior.get(key, self.behavior.get(instance_id, "default"))
        if isinstance(outcome, Exception):
            raise outcome
        if outcome == "silence":
            return {"attempts": 1, "cost_usd": 0.00067584, "outcome": "deliberate_silence",
                    "input_tokens": 100, "output_tokens": 10}
        if isinstance(outcome, dict):
            return outcome
        # Return a claim the agent actually owns for this seed.
        seed = request.get("seed", 0)
        instance = tf.generate_instance("hypothesis", int(seed), DependenceRegime.N,
                                        ReasoningComplexity.LOW)
        claim = instance.private_clues.get(agent, ("bit0=0",))[0]
        return {"attempts": 1, "cost_usd": 0.00067584, "outcome": "message_candidate",
                "claim": claim, "input_tokens": 100, "output_tokens": 10}

    def receiver_choice(self, *, request):
        instance_id = request["instance_id"]
        self.receiver_calls.append(instance_id)
        key = (instance_id, "receiver")
        outcome = self.behavior.get(key, "default")
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, dict):
            return outcome
        return {"attempts": 1, "cost_usd": 0.000344064, "status": "complete",
                "model": "jev-1.13.0", "selected_option_id": "candidate-0",
                "confidence": 0.5,
                "probabilities": {"candidate-0": 0.5, "candidate-1": 0.3,
                                  "candidate-2": 0.2},
                "raw_probabilities": {"candidate-0": 0.5, "candidate-1": 0.3,
                                      "candidate-2": 0.2},
                "usage": {"input_tokens": 200, "output_tokens": 5},
                "normalization_tier": "exact", "renormalized": True,
                "request_hash": request.get("request_hash", "h")}


def authorized_copy(record, reference=None):
    if reference is None:
        reference = _digest_binding_reference()
    updated = json.loads(json.dumps(record))
    updated.update({
        "state": p06.AUTH_STATE_AUTHORIZED,
        "authorized": True,
        "reference": reference,
        "supplied_by": "test-authorizer@example",
        "supplied_at": "2026-09-28T00:00:00Z",
        "decision": "approve the registered discovery block at the recorded scope",
    })
    return updated


class P06TestCase(unittest.TestCase):
    def setUp(self):
        self.registration = json.loads(REGISTRATION.read_text(encoding="utf-8"))
        self.lock = json.loads(LOCK.read_text(encoding="utf-8"))
        self.auth = json.loads(AUTH.read_text(encoding="utf-8"))
        self.preflight = p06.run_preflight(REPO_ROOT)
        self.manifest = self.registration["fixed_n"]["manifest"]
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.journal_path = Path(self.tmp.name) / "collection.jsonl"
        self.report_path = Path(self.tmp.name) / "collection-report.json"
        self.live_paths = [REPO_ROOT / path for path in p04.PATHS.values()
                           if path != str(p04.REGISTRATION_PATH)]
        self.live_before = [path.exists() for path in self.live_paths]

    def tearDown(self):
        self.assertEqual([path.exists() for path in self.live_paths],
                         self.live_before, "a live output path changed state")
        for path in self.live_paths:
            self.assertFalse(path.exists(),
                             "a discovery live output must never appear offline")

    _UNSET = object()

    def run_with_transport(self, *, auth=None, approval=_UNSET,
                            behavior=None, registration=None, transport_factory="default",
                            preflight=None):
        created = {}

        def factory():
            created["transport"] = FakeTransport(behavior)
            return created["transport"]

        if transport_factory == "default":
            transport_factory = factory
        if approval is self._UNSET:
            approval = _digest_binding_reference()
        report = p06.execute_discovery_run(
            registration or self.registration, self.lock,
            auth if auth is not None else authorized_copy(self.auth),
            repo_root=REPO_ROOT, approval=approval,
            preflight=preflight if preflight is not None else self.preflight,
            transport_factory=transport_factory,
            journal_path=self.journal_path, report_path=self.report_path)
        return report, created.get("transport")


class PreflightTests(P06TestCase):
    def test_preflight_is_green_with_zero_network_events(self):
        events = []

        def hook(event, args):
            if event.startswith("socket.") or event.startswith("urllib."):
                events.append(event)

        def explode(*args, **kwargs):
            raise AssertionError("provider call attempted offline")

        with patch("urllib.request.urlopen", explode):
            import sys as _sys
            _sys.addaudithook(hook)
            with contextlib.redirect_stdout(io.StringIO()):
                rc = p06.main(["--repo-root", str(REPO_ROOT)])
            result = p06.run_preflight(REPO_ROOT)
        self.assertEqual(rc, 0)
        self.assertEqual(events, [])
        self.assertTrue(result["ok"], result["failed"])
        self.assertEqual(result["failed"], [])
        self.assertGreaterEqual(result["checks_run"], 24)
        self.assertEqual(result["provider_calls"], 0)
        self.assertEqual(result["status"], "offline")
        self.assertEqual(result["planned_seeds"], 16)

    def test_preflight_pins_the_registered_hashes_and_digest(self):
        self.assertEqual(self.preflight["registration_hash"], p06.REGISTRATION_HASH)
        self.assertEqual(self.preflight["lock_hash"], p06.LOCK_HASH)
        self.assertEqual(self.preflight["scope_digest_sha256"], p06.SCOPE_DIGEST)

    def test_preflight_reports_pending_state_without_failing(self):
        self.assertEqual(self.preflight["authorization_state"], p06.AUTH_STATE_PENDING)
        self.assertIs(self.preflight["authorized"], False)
        self.assertEqual(self.preflight["authorization_stop_reason"],
                         "authorization_pending")
        self.assertTrue(self.preflight["ok"])

    def test_cli_live_without_authorization_refuses(self):
        with contextlib.redirect_stdout(io.StringIO()) as buffer:
            rc = p06.main(["--repo-root", str(REPO_ROOT), "--live",
                           "--approval", "ANY-REFERENCE"])
        self.assertEqual(rc, 3)
        output = buffer.getvalue()
        self.assertIn("authorization_pending", output)
        self.assertIn('"provider_calls": 0', output)


class AuthorizationRefusalTests(P06TestCase):
    def assert_refused(self, report, transport, reason):
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["stop_reason"], reason)
        self.assertEqual(report["provider_calls"], 0)
        self.assertEqual(report["planned_seeds"], 16)
        self.assertFalse(self.journal_path.exists(), "a refused run must not journal")
        if transport is not None:
            self.assertEqual(transport.calls, [])

    def test_refusal_while_record_is_pending(self):
        def forbidden_factory():
            raise AssertionError("transport must not be constructed while pending")

        report = p06.execute_discovery_run(
            self.registration, self.lock, self.auth, repo_root=REPO_ROOT,
            approval="anything", preflight=self.preflight,
            transport_factory=forbidden_factory,
            journal_path=self.journal_path, report_path=self.report_path)
        self.assert_refused(report, None, "authorization_pending")

    def test_refusal_when_approval_not_supplied(self):
        report, transport = self.run_with_transport(approval=None)
        self.assert_refused(report, transport, "approval_reference_not_supplied")

    def test_refusal_when_approval_does_not_match_reference(self):
        report, transport = self.run_with_transport(approval="SOME-OTHER-REFERENCE")
        self.assert_refused(report, transport, "approval_reference_mismatch")

    def test_refusal_when_approval_does_not_bind_digest(self):
        """The reference itself must bind the scope digest."""
        drifted = authorized_copy(self.auth)
        drifted["reference"] = "AUTHREF-JEV-0001-WITHOUT-DIGEST"
        report, transport = self.run_with_transport(
            auth=drifted, approval="AUTHREF-JEV-0001-WITHOUT-DIGEST")
        self.assert_refused(report, transport, "approval_reference_does_not_bind_scope_digest")

    def test_refusal_when_scope_digest_drifts(self):
        drifted = authorized_copy(self.auth)
        drifted["scope_digest_sha256"] = "0" * 64
        report, transport = self.run_with_transport(auth=drifted)
        self.assert_refused(report, transport, "scope_digest_mismatch")

    def test_refusal_when_reference_not_echoed_in_reference_state(self):
        drifted = authorized_copy(self.auth)
        drifted["what_a_reference_must_state"]["scope_digest_sha256"] = "1" * 64
        report, transport = self.run_with_transport(auth=drifted)
        self.assert_refused(report, transport, "scope_digest_not_echoed_in_reference")

    def test_refusal_when_scope_differs_from_lock(self):
        drifted = authorized_copy(self.auth)
        drifted["scope"]["cost_caps"]["program_ceiling_usd"] = 999.0
        report, transport = self.run_with_transport(auth=drifted)
        self.assert_refused(report, transport, "authorization_scope_drift_from_lock")

    def test_refusal_when_transport_not_configured(self):
        report, _ = self.run_with_transport(transport_factory=None)
        self.assert_refused(report, None, "transport_not_configured")

    def test_refusal_when_transport_is_an_unwired_stub(self):
        """An authorized run against a stub must not consume the fresh paths."""
        report, _ = self.run_with_transport(
            transport_factory=lambda: p06.DiscoveryTransport())
        self.assert_refused(report, None, "transport_not_configured")
        self.assertFalse(self.journal_path.exists())
        self.assertFalse(self.report_path.exists())

    def test_refusal_when_preflight_not_ok(self):
        broken = dict(self.preflight, ok=False, failed=["x"])
        report, transport = self.run_with_transport(preflight=broken)
        self.assert_refused(report, transport, "preflight_failed")

    def test_refusal_leaves_authorization_record_untouched(self):
        self.run_with_transport(approval="wrong")
        after = json.loads(AUTH.read_text(encoding="utf-8"))
        self.assertEqual(after, self.auth)
        self.assertEqual(after["state"], p06.AUTH_STATE_PENDING)
        self.assertIsNone(after["reference"])


class OutputCollisionTests(P06TestCase):
    def test_existing_journal_refuses_without_calls(self):
        self.journal_path.write_text('{"instance_id":"pre-existing"}\n', encoding="utf-8")
        report, transport = self.run_with_transport()
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["stop_reason"], "output_collision:journal_exists")
        self.assertEqual(report["provider_calls"], 0)
        self.assertIsNone(transport, "the transport must not even be constructed")
        self.assertEqual(self.journal_path.read_text(encoding="utf-8"),
                         '{"instance_id":"pre-existing"}\n',
                         "an existing journal must never be appended to or overwritten")

    def test_existing_report_refuses_without_calls(self):
        self.report_path.write_text('{"pre":"existing"}\n', encoding="utf-8")
        report, transport = self.run_with_transport()
        self.assertEqual(report["stop_reason"], "output_collision:report_exists")
        self.assertIsNone(transport, "the transport must not even be constructed")
        self.assertFalse(self.journal_path.exists())

    def test_journal_open_mode_refuses_overwrite(self):
        self.journal_path.write_text("", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            p06.DiscoveryJournal(self.journal_path)

    def test_journal_refuses_duplicate_instance_ids(self):
        journal = p06.DiscoveryJournal(self.journal_path)
        try:
            journal.write({"instance_id": "hypothesis-00014c0b"})
            with self.assertRaises(p06.DiscoveryRunError):
                journal.write({"instance_id": "hypothesis-00014c0b"})
        finally:
            journal.close()


class JournalCompletenessTests(P06TestCase):
    def test_every_planned_seed_is_journaled(self):
        report, transport = self.run_with_transport()
        self.assertEqual(report["status"], "completed")
        self.assertIsNone(report["stop_reason"])
        rows = p06.DiscoveryJournal.read_rows(self.journal_path)
        self.assertEqual(len(rows), 16)
        self.assertEqual(report["journaled_seeds"], 16)
        self.assertEqual([row["instance_id"] for row in rows],
                         [entry["instance_id"] for entry in self.manifest])
        self.assertEqual([row["sequence"] for row in rows], list(range(1, 17)))

    def test_seeds_and_form_ids_match_manifest_exactly(self):
        self.run_with_transport()
        rows = p06.DiscoveryJournal.read_rows(self.journal_path)
        for row, entry in zip(rows, self.manifest):
            with self.subTest(instance=row["instance_id"]):
                self.assertEqual(row["seed"], entry["seed"])
                self.assertEqual(row["prompt_form_id"], entry["prompt_form_id"])
        self.assertEqual(len({row["seed"] for row in rows}), 16)

    def test_l4x_sequence_four_ling_calls_per_seed(self):
        """Each seed must make exactly 4 Ling writer calls: A and B on 2 turns."""
        report, transport = self.run_with_transport()
        self.assertEqual(report["status"], "completed")
        # 16 seeds x 4 calls = 64 Ling calls
        self.assertEqual(len(transport.calls), 64)
        # 16 seeds x 1 call = 16 Jev calls
        self.assertEqual(len(transport.receiver_calls), 16)
        # Verify the exact sequence: for each seed, A@0, B@0, A@1, B@1
        expected_calls = []
        for entry in self.manifest:
            for turn in range(2):
                for agent in ("A", "B"):
                    expected_calls.append((entry["instance_id"], agent, turn))
        self.assertEqual(transport.calls, expected_calls)

    def test_silence_and_failures_are_journaled(self):
        silence_id = self.manifest[1]["instance_id"]
        failure_id = self.manifest[2]["instance_id"]
        behavior = {}
        # All 4 writer calls for the silence seed return silence.
        for turn in range(2):
            for agent in ("A", "B"):
                behavior[(silence_id, agent, turn)] = "silence"
        # The failure seed raises on its first writer call.
        behavior[(failure_id, "A", 0)] = RuntimeError("writer_error")
        report, _ = self.run_with_transport(behavior=behavior)
        rows = p06.DiscoveryJournal.read_rows(self.journal_path)
        self.assertEqual(len(rows), 16)
        by_id = {row["instance_id"]: row for row in rows}
        silence = by_id[silence_id]
        self.assertEqual(silence["status"], "silence")
        self.assertTrue(silence["emission"]["silence"])
        failure = by_id[failure_id]
        self.assertEqual(failure["status"], "failed")
        self.assertIn("writer_error", failure["failure_reason"])
        self.assertEqual(report["counts"]["silence"], 1)
        self.assertEqual(report["counts"]["failed"], 1)
        self.assertEqual(report["counts"]["ok"], 14)

    def test_rows_carry_structural_need_form_identity_and_evidence(self):
        self.run_with_transport()
        row = p06.DiscoveryJournal.read_rows(self.journal_path)[0]
        self.assertTrue(row["structural_need"]["finalizer_needs_peer"])
        self.assertTrue(row["structural_need"]["channel_complete"])
        self.assertTrue(row["form_identity"]["prompt_form_id"])
        self.assertTrue(row["form_identity"]["pre_read_request_hash"])
        self.assertTrue(row["form_identity"]["pre_read_state_hash"])
        self.assertTrue(row["ownership"]["b_to_a_ownership_verified"])
        self.assertGreater(row["ownership"]["accepted_b_to_a_writes"], 0)
        self.assertTrue(row["exposure"]["read_after_write_verified"])
        self.assertGreater(row["exposure"]["verified_read_exposures"], 0)
        self.assertGreater(row["information"]["i_m_bits"], 0)

    def test_rows_carry_receiver_vectors_and_hashes(self):
        self.run_with_transport()
        row = p06.DiscoveryJournal.read_rows(self.journal_path)[0]
        receiver = row["receiver"]
        self.assertEqual(receiver["status"], "complete")
        self.assertEqual(receiver["resolved_model"], "jev-1.13.0")
        self.assertEqual(receiver["normalization_tier"], "exact")
        self.assertTrue(receiver["renormalized"])
        self.assertTrue(receiver["probabilities"])
        self.assertTrue(receiver["raw_probabilities"])
        self.assertEqual(sum(receiver["probabilities"].values()), 1.0)
        self.assertTrue(receiver["request_hash"])
        self.assertTrue(receiver["usage"])

    def test_rows_carry_request_identity_and_cost(self):
        self.run_with_transport()
        row = p06.DiscoveryJournal.read_rows(self.journal_path)[0]
        self.assertEqual(row["request"]["ling_model"], p06.LING_MODEL)
        self.assertEqual(row["request"]["ling_endpoint"], p06.LING_ENDPOINT)
        self.assertEqual(row["request"]["jev_model"], p06.JEV_MODEL)
        self.assertEqual(row["request"]["jev_endpoint"], p06.JEV_ENDPOINT)
        self.assertEqual(row["request"]["jev_codec_version"], p06.JEV_CODEC_VERSION)
        self.assertEqual(row["request"]["jev_protocol_key"], p06.PROTOCOL_KEY)
        self.assertEqual(row["request"]["ling_planned_calls"], 4)
        self.assertEqual(row["request"]["jev_planned_calls"], 1)
        self.assertEqual(row["request"]["ling_attempts"], 4)
        self.assertEqual(row["request"]["jev_attempts"], 1)
        self.assertGreater(row["cost"]["usd"], 0)
        self.assertGreaterEqual(row["cost"]["cumulative_usd"], row["cost"]["usd"])
        self.assertEqual(row["stage"], p06.STAGE)

    def test_rows_carry_physical_attempts_and_token_usage(self):
        self.run_with_transport()
        row = p06.DiscoveryJournal.read_rows(self.journal_path)[0]
        self.assertEqual(row["physical_attempts"]["ling"], 4)
        self.assertEqual(row["physical_attempts"]["jev"], 1)
        self.assertEqual(row["physical_attempts"]["combined"], 5)
        self.assertGreater(row["token_usage"]["ling_input_tokens"], 0)
        self.assertGreater(row["token_usage"]["ling_output_tokens"], 0)
        self.assertGreater(row["token_usage"]["jev_input_tokens"], 0)
        self.assertEqual(row["provider_calls"], 5)

    def test_transport_received_every_planned_seed_in_order(self):
        _, transport = self.run_with_transport()
        self.assertEqual(
            transport.receiver_calls,
            [entry["instance_id"] for entry in self.manifest])

    def test_report_records_scope_and_pins(self):
        report, _ = self.run_with_transport()
        self.assertEqual(report["scope_digest_sha256"], p06.SCOPE_DIGEST)
        self.assertEqual(report["registration_hash"], p06.REGISTRATION_HASH)
        self.assertEqual(report["lock_hash"], p06.LOCK_HASH)
        self.assertEqual(report["seeds"], [e["instance_id"] for e in self.manifest])
        self.assertEqual(report["planned_seeds"], 16)

    def test_report_caps_snapshot(self):
        report, _ = self.run_with_transport()
        caps = report["caps"]
        self.assertEqual(caps["planned_used"]["ling"], 64)
        self.assertEqual(caps["planned_used"]["jev"], 16)
        self.assertEqual(caps["physical_used"]["ling"], 64)
        self.assertEqual(caps["physical_used"]["jev"], 16)
        self.assertTrue(caps["within_ceiling"])
        self.assertTrue(caps["within_program_physical_ceiling"])
        self.assertTrue(caps["within_program_cost_ceiling"])


class CapAndStopEnforcementTests(P06TestCase):
    def run_with_budgets(self, mutate, behavior=None):
        registration = copy.deepcopy(self.registration)
        mutate(registration["budgets"])
        return self.run_with_transport(registration=registration, behavior=behavior)

    def test_cost_cap_stops_before_the_next_call(self):
        def mutate(budgets):
            budgets["discovery_collection"]["cost_ceiling_usd"] = 0.001
            budgets["discovery_collection"]["next_call_reservation_usd"]["ling"] = 0.00067584

        report, transport = self.run_with_budgets(mutate)
        self.assertEqual(report["status"], "stopped")
        self.assertTrue(report["stop_reason"].startswith("cost_cap_before_next_call"),
                        report["stop_reason"])
        self.assertLess(report["caps"]["cost_usd"], 0.001)
        self.assertTrue(report["caps"]["within_ceiling"])
        rows = p06.DiscoveryJournal.read_rows(self.journal_path)
        self.assertEqual(len(rows), 16, "every planned seed must still be journaled")
        attempted = [row for row in rows if row["attempted"]]
        self.assertLess(len(attempted), 16)
        for row in rows[len(attempted):]:
            self.assertEqual(row["status"], "not_attempted")
            self.assertIn("not_attempted:cost_cap_before_next_call", row["failure_reason"])
        self.assertEqual(len(transport.calls) + len(transport.receiver_calls),
                         sum(r["provider_calls"] for r in attempted))
        self.assertEqual(report["counts"]["not_attempted"], 16 - len(attempted))

    def test_planned_request_cap_stops_the_run(self):
        def mutate(budgets):
            budgets["discovery_collection"]["planned"]["ling"] = 5

        report, transport = self.run_with_budgets(mutate)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "request_cap_planned:ling")
        rows = p06.DiscoveryJournal.read_rows(self.journal_path)
        self.assertEqual(len(rows), 16)
        self.assertEqual(len(transport.calls), 5)
        # 5 calls = 1 full seed (4 calls) + 1 call into the second seed.
        # The second seed is attempted but incomplete; 14 seeds are not_attempted.
        self.assertEqual(report["counts"]["not_attempted"], 14)

    def test_physical_request_cap_accounts_for_retries(self):
        def mutate(budgets):
            budgets["discovery_collection"]["physical"]["ling"] = 4
            budgets["discovery_collection"]["next_call_reservation_usd"]["ling"] = 0.0

        behavior = {(entry["instance_id"], "A", 0): {"attempts": 3, "cost_usd": 0.0001,
                                                       "outcome": "message_candidate",
                                                       "claim": "bit0=0",
                                                       "input_tokens": 10,
                                                       "output_tokens": 5}
                    for entry in self.manifest}
        report, transport = self.run_with_budgets(mutate, behavior)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "request_cap_physical:ling")
        self.assertEqual(report["caps"]["physical_used"]["ling"], 3)
        self.assertEqual(len(transport.calls), 1)
        rows = p06.DiscoveryJournal.read_rows(self.journal_path)
        self.assertEqual(len(rows), 16)
        self.assertEqual(report["counts"]["not_attempted"], 15)

    def test_unknown_provider_is_refused(self):
        tracker = p06.CapTracker(self.registration["budgets"])
        self.assertEqual(tracker.reason_before_call("paid-free-fallback"),
                         "unknown_provider:paid-free-fallback")

    def test_registered_stops_and_paths_are_bound(self):
        stops = self.registration["stops"]
        self.assertTrue(any("output collision" in s for s in stops))
        self.assertTrue(any("cost cap" in s for s in stops))
        self.assertTrue(any("seed substitution" in s or "hash drift" in s for s in stops))
        lifecycle = self.registration["path_lifecycle"]
        self.assertFalse(lifecycle["resume"])
        self.assertFalse(lifecycle["append"])
        self.assertFalse(lifecycle["overwrite"])
        self.assertFalse(lifecycle["path_overrides"])

    def test_writer_terminal_error_stops_run(self):
        """A writer terminal error (empty_output, etc.) must fail closed."""
        behavior = {(self.manifest[0]["instance_id"], "A", 0): {
            "attempts": 1, "cost_usd": 0.0, "outcome": "empty_output",
            "error_class": "empty_output"}}
        report, transport = self.run_with_transport(behavior=behavior)
        self.assertEqual(report["status"], "stopped")
        self.assertIn("empty_output", report["stop_reason"])
        rows = p06.DiscoveryJournal.read_rows(self.journal_path)
        self.assertEqual(len(rows), 16)
        self.assertEqual(rows[0]["status"], "failed")
        self.assertIn("empty_output", rows[0]["failure_reason"])
        self.assertEqual(report["counts"]["not_attempted"], 15)

    def test_two_consecutive_terminal_failures_stop_run(self):
        """Two consecutive terminal provider failures must stop the run."""
        behavior = {
            (self.manifest[0]["instance_id"], "A", 0): RuntimeError("boom1"),
            (self.manifest[1]["instance_id"], "A", 0): RuntimeError("boom2"),
        }
        report, transport = self.run_with_transport(behavior=behavior)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "two_consecutive_terminal_provider_failures")
        rows = p06.DiscoveryJournal.read_rows(self.journal_path)
        self.assertEqual(len(rows), 16)
        self.assertEqual(report["counts"]["not_attempted"], 14)

    def test_receiver_invalid_stops_run(self):
        """An invalid receiver response must fail closed."""
        behavior = {(entry["instance_id"], "receiver"): {
            "attempts": 1, "cost_usd": 0.0, "status": "invalid",
            "error_class": "malformed_response"} for entry in self.manifest}
        report, transport = self.run_with_transport(behavior=behavior)
        self.assertEqual(report["status"], "stopped")
        self.assertIn("malformed_response", report["stop_reason"])
        rows = p06.DiscoveryJournal.read_rows(self.journal_path)
        self.assertEqual(len(rows), 16)

    def test_normalization_hard_ceiling_stops_run(self):
        """Normalization deviation above 0.05 must fail closed."""
        behavior = {(entry["instance_id"], "receiver"): {
            "attempts": 1, "cost_usd": 0.0, "status": "invalid",
            "error_class": "not_normalized_hard"} for entry in self.manifest}
        report, transport = self.run_with_transport(behavior=behavior)
        self.assertEqual(report["status"], "stopped")
        self.assertIn("not_normalized_hard", report["stop_reason"])


class NoSubstitutionTests(P06TestCase):
    def test_refused_run_never_touches_the_record_or_manifest(self):
        before = json.dumps(self.manifest, sort_keys=True)
        self.run_with_transport(approval=None)
        self.assertEqual(json.dumps(self.manifest, sort_keys=True), before)
        self.assertEqual(json.loads(REGISTRATION.read_text(encoding="utf-8")),
                         self.registration)

    def test_completed_run_uses_exactly_the_registered_manifest(self):
        report, _ = self.run_with_transport()
        rows = p06.DiscoveryJournal.read_rows(self.journal_path)
        self.assertEqual(len(rows), 16)
        self.assertEqual(sorted(row["seed"] for row in rows),
                         sorted(entry["seed"] for entry in self.manifest))
        self.assertEqual(report["journaled_seeds"], 16)
        self.assertEqual(report["counts"]["not_attempted"], 0)

    def test_hash_pins_unchanged(self):
        self.assertEqual(hashlib.sha256(REGISTRATION.read_bytes()).hexdigest(),
                         "78f7cd03c3afc12c94c3ba09839e4ac6ba667a3f68b96871571b274ae7d3ab11")
        self.assertEqual(p05._lock_hash(self.lock), p06.LOCK_HASH)
        self.assertEqual(json.loads(REGISTRATION.read_text(encoding="utf-8"))
                         ["registration_hash"], p06.REGISTRATION_HASH)


class L4XEvidenceTests(P06TestCase):
    def test_board_evidence_verified_from_events(self):
        """B-to-A ownership and A read-after-write exposure use real event evidence."""
        self.run_with_transport()
        rows = p06.DiscoveryJournal.read_rows(self.journal_path)
        for row in rows:
            with self.subTest(instance=row["instance_id"]):
                self.assertTrue(row["ownership"]["b_to_a_ownership_verified"])
                self.assertGreater(row["ownership"]["accepted_b_to_a_writes"], 0)
                self.assertTrue(row["exposure"]["read_after_write_verified"])
                self.assertGreater(row["exposure"]["verified_read_exposures"], 0)
                for read in row["exposure"]["reads"]:
                    self.assertEqual(read["writer_agent"], "B")
                    self.assertEqual(read["reader_agent"], "A")
                    self.assertEqual(read["exposure_id"], p06.JEV_FINALIZER_EXPOSURE_ID)
                    self.assertGreater(read["read_sequence"], read["write_sequence"])

    def test_rejected_claims_are_journaled(self):
        """Non-owned claims must be rejected and journaled, never accepted."""
        # Make B's turn-0 claim non-owned by using a claim B doesn't hold
        behavior = {}
        for entry in self.manifest:
            # A's claims are fine (A owns them), B's claims are not owned
            behavior[(entry["instance_id"], "B", 0)] = {
                "attempts": 1, "cost_usd": 0.0, "outcome": "non_owned_claim",
                "claim": "bit0=0", "error_class": None}
        report, _ = self.run_with_transport(behavior=behavior)
        rows = p06.DiscoveryJournal.read_rows(self.journal_path)
        for row in rows:
            self.assertGreater(len(row["ownership"]["rejected_claims"]), 0)
            for rejected in row["ownership"]["rejected_claims"]:
                self.assertEqual(rejected["agent"], "B")

    def test_jev_request_identity_matches_registered_route(self):
        """The Jev request must carry the exact registered model/endpoint/protocol."""
        self.run_with_transport()
        rows = p06.DiscoveryJournal.read_rows(self.journal_path)
        for row in rows:
            self.assertEqual(row["request"]["jev_model"], p06.JEV_MODEL)
            self.assertEqual(row["request"]["jev_endpoint"], p06.JEV_ENDPOINT)
            self.assertEqual(row["request"]["jev_codec_version"], p06.JEV_CODEC_VERSION)
            self.assertEqual(row["request"]["jev_protocol_key"], p06.PROTOCOL_KEY)
            self.assertEqual(row["request"]["jev_planned_calls"], 1)


class StructuralNeedAndFormIdentityTests(P06TestCase):
    def test_structural_need_derived_from_deterministic_instance(self):
        """Structural need must come from the deterministic instance, not transport."""
        self.run_with_transport()
        rows = p06.DiscoveryJournal.read_rows(self.journal_path)
        for row in rows:
            need = row["structural_need"]
            self.assertIn("finalizer_needs_peer", need)
            self.assertIn("channel_complete", need)
            self.assertIn("both_agents_needed", need)
            self.assertIn("pooled_equals_joint", need)

    def test_form_identity_derived_from_pre_read_request(self):
        """Form identity must come from the pre-read request hash."""
        self.run_with_transport()
        rows = p06.DiscoveryJournal.read_rows(self.journal_path)
        for row in rows:
            identity = row["form_identity"]
            self.assertTrue(identity["prompt_form_id"])
            self.assertTrue(identity["pre_read_request_hash"])
            self.assertTrue(identity["pre_read_state_hash"])
            self.assertTrue(identity["option_ids"])
            self.assertTrue(identity["target_id"])


class NoNetworkOfflineTests(P06TestCase):
    def test_execute_run_makes_zero_provider_calls(self):
        """The offline preflight makes zero provider calls."""
        self.assertEqual(self.preflight["provider_calls"], 0)

    def test_authorized_run_with_unwired_transport_makes_zero_calls(self):
        """An authorized run with no wired transport must make zero calls."""
        report, _ = self.run_with_transport(transport_factory=None)
        self.assertEqual(report["provider_calls"], 0)
        self.assertEqual(report["status"], "blocked")

    def test_cli_live_with_pending_record_makes_zero_calls(self):
        with contextlib.redirect_stdout(io.StringIO()) as buffer:
            rc = p06.main(["--repo-root", str(REPO_ROOT), "--live",
                           "--approval", _digest_binding_reference()])
        self.assertEqual(rc, 3)
        output = buffer.getvalue()
        self.assertIn('"provider_calls": 0', output)
        self.assertIn("authorization_pending", output)


if __name__ == "__main__":
    unittest.main()
