"""Offline tests for the legal L05 discovery preflight and fail-closed runner.

Every fixture is offline: no transport fixture ever contacts a provider, all
provider interaction is mocked in-process, and live output paths of the
registered legal discovery stay untouched.
"""

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

from apart_incident_response import jev_legal_p04_registration as lp04
from apart_incident_response import jev_legal_p05_runner as l05

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = REPO_ROOT / "runs" / "next-phase" / "legal" / \
    "jev-legal-p04-discovery-registration-v1.json"
CENSUS = REPO_ROOT / "runs" / "next-phase" / "legal" / "jev-legal-p02-form-census-v1.json"
LIVE_PATHS = [
    REPO_ROOT / rel for rel in (
        "runs/next-phase/legal/jev-discovery-v1/jev-discovery-collection.jsonl",
        "runs/next-phase/legal/jev-discovery-v1/jev-discovery-collection-report.json",
        "runs/next-phase/legal/jev-discovery-v1/jev-exploratory-replay.jsonl",
        "runs/next-phase/legal/jev-discovery-v1/jev-exploratory-replay-report.json",
    )
]


def registered_lock():
    registration = json.loads(REGISTRATION.read_text(encoding="utf-8"))
    document = {
        "preregistration_version": l05.REGISTRATION_VERSION,
        "registration_hash": l05.REGISTRATION_HASH,
        "status": "locked_pending_separate_live_authorization",
        "authorization_scope": l05.authorization_scope_for_registration(registration),
        "review": {"required": True, "independent": True,
                   "record_path": l05.LOCK_REVIEW_PATH},
    }
    document["lock_hash"] = l05.lock_hash(document)
    return document


def approved_lock_review(lock):
    return {"verdict": "approved", "reviewed_lock_hash": lock["lock_hash"],
            "blocking_findings": []}


def scope_digest_of(lock):
    return l05.scope_digest(lock["authorization_scope"])


def authorized_record(lock, *, reference=None):
    digest = scope_digest_of(lock)
    reference = reference or f"AUTHREF-LEGAL-0001:{digest}"
    return {
        "state": l05.AUTH_STATE_AUTHORIZED,
        "authorized": True,
        "reference": reference,
        "supplied_by": "test-authorizer@example",
        "supplied_at": "2026-10-22T00:00:00Z",
        "decision": "authorize the registered legal discovery block at the exact scope",
        "scope": dict(lock["authorization_scope"]),
        "scope_digest_sha256": digest,
        "must_cover": list(l05.MUST_COVER),
        "locking_is_not_authorization": True,
    }


def pending_record(lock):
    return {
        "state": l05.AUTH_STATE_PENDING,
        "authorized": False,
        "reference": None,
        "supplied_by": None,
        "supplied_at": None,
        "decision": None,
        "scope": dict(lock["authorization_scope"]),
        "scope_digest_sha256": scope_digest_of(lock),
        "must_cover": list(l05.MUST_COVER),
        "locking_is_not_authorization": True,
    }


class FakeTransport(l05.DiscoveryTransport):
    """In-process transport: records every call, never touches a provider."""

    is_configured = True

    def __init__(self, behavior=None):
        from apart_incident_response import task_families as tf
        from apart_incident_response.communication_protocol import (
            DependenceRegime, ReasoningComplexity,
        )
        self.behavior = behavior or {}
        self.calls = []
        self.receiver_calls = []
        self._tf = tf
        self._regime = DependenceRegime.N
        self._complexity = ReasoningComplexity.LOW

    def _instance(self, seed):
        return self._tf.generate_instance("legal", int(seed), self._regime,
                                          self._complexity)

    def writer_completion(self, *, request):
        instance_id = request["instance_id"]
        agent = request.get("agent", "A")
        turn = request.get("turn", 0)
        self.calls.append((instance_id, agent, turn))
        key = (instance_id, agent, turn)
        outcome = self.behavior.get(key, self.behavior.get(instance_id, "default"))
        if isinstance(outcome, Exception):
            raise outcome
        if outcome == "silence":
            return {"attempts": 1, "cost_usd": 0.00067584,
                    "outcome": "deliberate_silence",
                    "input_tokens": 100, "output_tokens": 10}
        if isinstance(outcome, dict):
            result = dict(outcome)
            if "request_identity" not in result:
                result["request_identity"] = {
                    "model": l05.LING_MODEL, "endpoint": l05.LING_ENDPOINT,
                    "temperature": 0.0, "max_tokens": int(request["max_tokens"]),
                    "provider_seed": int(request["provider_seed"]),
                    "prompt_sha256": hashlib.sha256(
                        str(request["prompt"]).encode()).hexdigest()}
            return result
        claim = self._instance(request["seed"]).private_clues.get(agent, ("",))[0]
        return {"attempts": 1, "cost_usd": 0.00067584,
                "outcome": "message_candidate", "claim": claim,
                "input_tokens": 100, "output_tokens": 10,
                "request_identity": {
                    "model": l05.LING_MODEL, "endpoint": l05.LING_ENDPOINT,
                    "temperature": 0.0, "max_tokens": int(request["max_tokens"]),
                    "provider_seed": int(request["provider_seed"]),
                    "prompt_sha256": hashlib.sha256(
                        str(request["prompt"]).encode()).hexdigest()}}

    def receiver_choice(self, *, request):
        instance_id = request["instance_id"]
        self.receiver_calls.append(instance_id)
        outcome = self.behavior.get((instance_id, "receiver"), "default")
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, dict):
            return outcome
        state = request["state"]
        option_ids = [option.option_id for option in state.options]
        probability = 1.0 / len(option_ids)
        probabilities = {option_id: probability for option_id in option_ids}
        selected = max(probabilities, key=probabilities.get)
        return {"attempts": 1, "cost_usd": 0.000344064, "status": "complete",
                "model": l05.JEV_MODEL, "error_class": None,
                "codec_version": l05.JEV_CODEC_VERSION,
                "normalization_tier": "exact", "renormalized": True,
                "selected_option_id": selected, "confidence": 0.5,
                "probabilities": probabilities,
                "raw_probabilities": dict(probabilities),
                "normalization_diagnostics":
                    {"absolute_normalization_deviation": 0.0},
                "usage": {"input_tokens": 200, "output_tokens": 5},
                "request_hash": state.request_hash}


class LegalPreflightFixture(unittest.TestCase):
    """Shared fixtures: isolated journal/report paths and registered objects."""

    def setUp(self):
        self.registration = json.loads(REGISTRATION.read_text(encoding="utf-8"))
        self.lock = registered_lock()
        self.lock_review = approved_lock_review(self.lock)
        self.auth = authorized_record(self.lock)
        self.preflight = {"ok": True, "failed": [], "provider_calls": 0}
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.journal_path = Path(tmp.name) / "jev-discovery-collection.jsonl"
        self.report_path = Path(tmp.name) / "jev-discovery-collection-report.json"
        self.live_before = [path.exists() for path in LIVE_PATHS]

    def tearDown(self):
        self.assertEqual([path.exists() for path in LIVE_PATHS], self.live_before,
                         "a registered live output path changed state")

    _UNSET = object()

    def run_with_transport(self, *, lock="UNSET", auth="UNSET",
                           lock_review="UNSET", approval=_UNSET,
                            behavior=None, registration=None, transport_factory="default",
                            preflight=None, journal_path=None, report_path=None):
        created = {}

        def factory():
            created["transport"] = FakeTransport(behavior)
            return created["transport"]

        if transport_factory == "default":
            transport_factory = factory
        if approval is self._UNSET:
            approval = authorized_record(self.lock)["reference"]
        report = l05.execute_legal_discovery_run(
            registration or self.registration,
            self.lock if lock == "UNSET" else lock,
            self.auth if auth == "UNSET" else auth,
            lock_review=self.lock_review if lock_review == "UNSET" else lock_review,
            repo_root=REPO_ROOT, approval=approval,
            preflight=preflight if preflight is not None else self.preflight,
            transport_factory=transport_factory,
            journal_path=journal_path or self.journal_path,
            report_path=report_path or self.report_path)
        return report, created.get("transport")


class PreflightTests(LegalPreflightFixture):
    def test_preflight_is_green_with_zero_network_events(self):
        events = []

        def hook(event, args):
            if event.startswith("socket.") or event.startswith("urllib.") \
                    or event.startswith("http.client."):
                events.append(event)

        def explode(*args, **kwargs):
            raise AssertionError("provider call attempted offline")

        with patch("urllib.request.urlopen", explode):
            sys.addaudithook(hook)
            result = l05.run_preflight(REPO_ROOT)
        self.assertEqual(events, [])
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["failed"], [])
        self.assertGreaterEqual(result["checks_run"], 20)
        self.assertEqual(result["provider_calls"], 0)
        self.assertEqual(result["network_audit"]["events"], 0)
        self.assertEqual(result["status"], "offline")
        self.assertEqual(result["planned_seeds"], 16)
        self.assertEqual(result["release_gate_stop_reason"], "lock_pending_l06")
        self.assertFalse(result["authorized"])

    def test_preflight_pins_the_registered_hashes_and_paths(self):
        result = l05.run_preflight(REPO_ROOT)
        self.assertEqual(result["registration_hash"], l05.REGISTRATION_HASH)
        self.assertEqual(result["registration_version"], l05.REGISTRATION_VERSION)
        self.assertEqual(result["lock_path"], l05.LOCK_PATH)
        self.assertEqual(result["authorization_record_path"], l05.AUTH_PATH)

    def test_preflight_records_release_gate_state(self):
        result = l05.run_preflight(REPO_ROOT)
        self.assertEqual(result["lock_state"], l05.LOCK_STATE_ABSENT)
        self.assertEqual(result["authorization_state"], l05.AUTH_STATE_NO_RECORD)
        scope = result["expected_authorization_scope"]
        self.assertTrue(l05.scope_matches_registration(scope, self.registration))
        self.assertEqual(
            result["expected_authorization_scope_digest"],
            l05.scope_digest(scope))

    def test_registered_fields_validate_on_disk(self):
        census = json.loads(CENSUS.read_text(encoding="utf-8"))
        snapshot = json.loads(json.dumps(self.registration, sort_keys=True))
        snapshot["_validation_census_document"] = census
        self.assertEqual(l05.validate_registration_fields(snapshot), [])

    def test_restart_does_not_rewrite_an_identical_report(self):
        report_path = REPO_ROOT / l05.PREFLIGHT_REPORT_PATH
        before = report_path.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            rc = l05.main(["--repo-root", str(REPO_ROOT)])
        self.assertEqual(rc, 0)
        self.assertEqual(report_path.read_bytes(), before)

    def test_registration_hash_content_pin_matches_recomputed_bytes(self):
        self.assertEqual(lp04.verify_registration(self.registration,
                                                  repo_root=REPO_ROOT).get("ok"),
                         True)


class FieldDriftTests(LegalPreflightFixture):
    def mutated(self, mutate):
        snapshot = json.loads(json.dumps(self.registration, sort_keys=True))
        census = json.loads(CENSUS.read_text(encoding="utf-8"))
        snapshot["_validation_census_document"] = census
        mutate(snapshot)
        return l05.validate_registration_fields(snapshot)

    def test_manifest_seed_drift_fails_generator_recompute(self):
        def mutate(document):
            document["fixed_n"]["manifest"][0]["seed"] = 88099

        self.assertIn("manifest_ids_recompute_from_the_generator",
                      self.mutated(mutate))

    def test_manifest_hash_drift_fails(self):
        def mutate(document):
            document["fixed_n"]["manifest_hash"] = "0" * 64

        failures = self.mutated(mutate)
        self.assertIn("manifest_hash_matches_registered_pin", failures)

    def test_ling_model_drift_fails(self):
        def mutate(document):
            document["route"]["ling"]["model"] = "openai/gpt-x"

        self.assertIn("route_ling_registered_pins_match", self.mutated(mutate))

    def test_treatment_hash_drift_fails(self):
        def mutate(document):
            document["treatment"]["treatment_hash"] = "0" * 64

        self.assertIn("treatment_hash_matches_registered_pin", self.mutated(mutate))

    def test_token_budget_drift_fails(self):
        def mutate(document):
            document["treatment"]["writer_prompt"]["max_tokens"] = 2048

        self.assertIn("writer_output_policy_max_tokens_1024", self.mutated(mutate))

    def test_ceilings_drift_fail(self):
        def mutate(document):
            document["budgets"]["program"]["hard_cost_ceiling_usd"] = 3.0

        self.assertIn("hard_cost_ceilings_match_registered", self.mutated(mutate))

    def test_reservation_drift_fails(self):
        def mutate(document):
            document["budgets"]["discovery_collection"]["next_call_reservation_usd"] = {
                "jev": 0.0, "ling": 0.0}

        self.assertIn("next_call_retry_reservations_match_registered",
                      self.mutated(mutate))

    def test_authorization_block_drift_fails(self):
        def mutate(document):
            document["authorization"]["route_authorized"] = True

        failures = self.mutated(mutate)
        self.assertIn("authorization_block_is_fully_pending", failures)

    def test_path_lifecycle_drift_fails(self):
        def mutate(document):
            document["path_lifecycle"]["resume"] = True

        self.assertIn("path_lifecycle_forbids_resume_append_overwrite",
                      self.mutated(mutate))

    def test_live_path_key_drift_fails_even_with_four_paths(self):
        def mutate(document):
            document["paths"]["wrong_report"] = document["paths"].pop(
                "discovery_report")

        self.assertIn("registered_live_output_paths_present", self.mutated(mutate))

    def test_missing_census_prevents_geometry_recompute(self):
        snapshot = json.loads(json.dumps(self.registration, sort_keys=True))
        snapshot["_validation_census_document"] = {}
        failures = l05.validate_registration_fields(snapshot)
        self.assertIn("census_document_supplied_for_geometry_recompute", failures)


class ReleaseGateTests(LegalPreflightFixture):
    def evaluate(self, *, lock="UNSET", auth="UNSET", lock_review="UNSET",
                 approval="REF"):
        return l05.evaluate_release_gates(
            self.lock if lock == "UNSET" else lock,
            self.auth if auth == "UNSET" else auth,
            approval, self.registration,
            self.lock_review if lock_review == "UNSET" else lock_review)

    def test_green_gates_authorize_this_exact_scope(self):
        stop, lock_state, auth_state = self.evaluate(approval=self.auth["reference"])
        self.assertIsNone(stop)
        self.assertEqual(lock_state, l05.LOCK_STATE_PRESENT)
        self.assertEqual(auth_state, l05.AUTH_STATE_AUTHORIZED)

    def test_missing_lock_blocks_before_any_call(self):
        self.assertEqual(self.evaluate(lock=None)[0], "lock_pending_l06")

    def test_lock_registration_hash_drift(self):
        drifted = dict(self.lock, registration_hash="0" * 64)
        self.assertEqual(self.evaluate(lock=drifted)[0], "lock_registration_hash_drift")

    def test_lock_version_drift(self):
        drifted = dict(self.lock, preregistration_version="older-version")
        self.assertEqual(self.evaluate(lock=drifted)[0],
                         "lock_registration_version_drift")

    def test_lock_status_not_reviewed(self):
        drifted = dict(self.lock, status="draft")
        self.assertEqual(self.evaluate(lock=drifted)[0], "lock_status_not_reviewed")

    def test_lock_hash_mismatch(self):
        drifted = dict(self.lock, lock_hash="0" * 64)
        self.assertEqual(self.evaluate(lock=drifted)[0], "lock_hash_mismatch")

    def test_lock_review_missing(self):
        self.assertEqual(self.evaluate(lock_review=None)[0], "lock_review_pending_l06")

    def test_lock_review_must_name_exact_hash(self):
        drifted = dict(self.lock_review, reviewed_lock_hash="0" * 64)
        self.assertEqual(self.evaluate(lock_review=drifted)[0],
                         "lock_review_not_approved_for_hash")

    def test_lock_scope_missing(self):
        drifted = dict(self.lock)
        drifted.pop("authorization_scope")
        drifted["lock_hash"] = l05.lock_hash(drifted)
        self.assertEqual(self.evaluate(lock=drifted)[0],
                         "lock_authorization_scope_missing")

    def test_missing_authorization_record(self):
        self.assertEqual(self.evaluate(auth=None, approval=None)[0],
                         "authorization_pending")

    def test_pending_authorization_record(self):
        self.assertEqual(self.evaluate(auth=pending_record(self.lock), approval=None)[0],
                         "authorization_pending")

    def test_authorized_flag_not_set(self):
        record = pending_record(self.lock)
        record["state"] = l05.AUTH_STATE_AUTHORIZED
        self.assertEqual(self.evaluate(auth=record)[0], "authorization_flag_not_set")

    def test_scope_drift_from_lock(self):
        record = authorized_record(self.lock)
        record["scope"] = dict(record["scope"], stage="something else")
        self.assertEqual(self.evaluate(auth=record)[0],
                         "authorization_scope_drift_from_lock")

    def test_scope_out_of_registered_scope(self):
        drifted_lock = copy.deepcopy(self.lock)
        drifted_lock["authorization_scope"]["stage"] = "some wider scope"
        drifted_lock["lock_hash"] = l05.lock_hash(drifted_lock)
        self.assertEqual(
            self.evaluate(lock=drifted_lock, auth=authorized_record(drifted_lock))[0],
            "lock_authorization_scope_drift")

    def test_scope_digest_mismatch(self):
        record = authorized_record(self.lock)
        record["scope_digest_sha256"] = "0" * 64
        self.assertEqual(self.evaluate(auth=record)[0], "scope_digest_mismatch")

    def test_must_cover_drift(self):
        record = authorized_record(self.lock)
        record["must_cover"] = ["stage", "route"]
        self.assertEqual(self.evaluate(auth=record)[0],
                         "authorization_must_cover_drift")

    def test_locking_is_not_authorization_flag_required(self):
        record = authorized_record(self.lock)
        record["locking_is_not_authorization"] = False
        self.assertEqual(self.evaluate(auth=record)[0],
                         "authorization_non_inference_flags_missing")

    def test_approval_not_supplied(self):
        self.assertEqual(self.evaluate(approval=None)[0],
                         "approval_reference_not_supplied")

    def test_approval_reference_mismatch(self):
        self.assertEqual(self.evaluate(approval="AUTHREF-OTHER")[0],
                         "approval_reference_mismatch")

    def test_approval_must_bind_scope_digest(self):
        record = authorized_record(self.lock)
        record["reference"] = "AUTHREF-LEGAL-0001-UNBOUND"
        stop = self.evaluate(auth=record, approval=record["reference"])[0]
        self.assertEqual(stop, "approval_reference_does_not_bind_scope_digest")

    def test_scope_digest_is_stable_across_calls(self):
        self.assertEqual(scope_digest_of(self.lock), scope_digest_of(registered_lock()))


class RefusalTests(LegalPreflightFixture):
    def assert_refused(self, report, transport, reason):
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["stop_reason"], reason)
        self.assertEqual(report["provider_calls"], 0)
        self.assertEqual(report["planned_seeds"], 16)
        if transport is not None:
            self.assertEqual(transport.calls, [])
            self.assertEqual(transport.receiver_calls, [])
        if "output_collision" not in reason:
            self.assertFalse(self.journal_path.exists(),
                             "a refused run must not journal")
            self.assertFalse(self.report_path.exists())

    def test_refusal_while_lock_is_absent(self):
        def forbidden_factory():
            raise AssertionError("transport must not be constructed without the lock")

        report, _ = self.run_with_transport(lock=None,
                                            transport_factory=forbidden_factory)
        self.assert_refused(report, None, "lock_pending_l06")

    def test_refusal_while_authorization_is_pending(self):
        def forbidden_factory():
            raise AssertionError("transport must not be constructed while pending")

        report, _ = self.run_with_transport(auth=pending_record(self.lock),
                                            transport_factory=forbidden_factory)
        self.assert_refused(report, None, "authorization_pending")

    def test_refusal_without_approval(self):
        report, transport = self.run_with_transport(approval=None)
        self.assert_refused(report, transport, "approval_reference_not_supplied")

    def test_refusal_with_mismatched_approval(self):
        report, transport = self.run_with_transport(approval="AUTHREF-OTHER")
        self.assert_refused(report, transport, "approval_reference_mismatch")

    def test_refusal_when_approval_does_not_bind_scope_digest(self):
        record = authorized_record(self.lock)
        record["reference"] = "AUTHREF-LEGAL-0001-UNBOUND"
        report, transport = self.run_with_transport(
            auth=record, approval=record["reference"])
        self.assert_refused(report, transport,
                            "approval_reference_does_not_bind_scope_digest")

    def test_refusal_on_failed_preflight(self):
        report, transport = self.run_with_transport(
            preflight={"ok": False, "failed": ["registered_fields_validate"],
                       "provider_calls": 0})
        self.assert_refused(report, transport, "preflight_failed")
        self.assertEqual(report["failed"], ["registered_fields_validate"])

    def test_refusal_on_journal_collision(self):
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        self.journal_path.write_text("{}\n", encoding="utf-8")
        report, transport = self.run_with_transport()
        self.assert_refused(report, transport, "output_collision:journal_exists")

    def test_refusal_on_report_collision(self):
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text("{}\n", encoding="utf-8")
        report, transport = self.run_with_transport()
        self.assert_refused(report, transport, "output_collision:report_exists")

    def test_refusal_on_unconfigured_transport(self):
        def unconfigured_factory():
            transport = FakeTransport()
            transport.is_configured = False
            return transport

        report, _ = self.run_with_transport(transport_factory=unconfigured_factory)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["stop_reason"], "transport_not_configured")
        self.assertEqual(report["provider_calls"], 0)
        self.assertFalse(self.journal_path.exists())

    def test_refusal_on_manifest_drift(self):
        drifted = json.loads(json.dumps(self.registration))
        drifted["fixed_n"]["manifest"] = drifted["fixed_n"]["manifest"][:1]
        report, transport = self.run_with_transport(registration=drifted)
        self.assert_refused(report, transport, "manifest_drift")

    def test_refusal_on_same_length_registration_drift(self):
        drifted = copy.deepcopy(self.registration)
        drifted["stops"][0] = "silently weakened stop"
        report, transport = self.run_with_transport(registration=drifted)
        self.assert_refused(report, transport, "registration_drift")


class RunLifecycleTests(LegalPreflightFixture):
    def test_full_block_journals_every_planned_instance_exactly_once(self):
        report, transport = self.run_with_transport()
        self.assertEqual(report["status"], "completed")
        self.assertIsNone(report["stop_reason"])
        self.assertEqual(report["planned_seeds"], 16)
        self.assertEqual(report["journaled_seeds"], 16)
        self.assertTrue(report["journal_complete_at_registered_n"])
        rows = [json.loads(line) for line in
                self.journal_path.read_text(encoding="utf-8").splitlines()]
        manifest = self.registration["fixed_n"]["manifest"]
        self.assertEqual([row["instance_id"] for row in rows],
                         [entry["instance_id"] for entry in manifest])
        self.assertEqual([row["sequence"] for row in rows], list(range(1, 17)))
        counts = report["counts"]
        self.assertEqual(sum(counts.values()), 16)
        self.assertEqual(counts["ok"] + counts["silence"] + counts["failed"]
                         + counts["not_attempted"], 16)
        self.assertEqual(len(transport.calls), 64)
        self.assertEqual(len(transport.receiver_calls), 16)
        self.assertGreater(report["caps"]["combined_planned_used"], 0)
        self.assertTrue(report["caps"]["within_ceiling"])
        self.assertTrue(report["caps"]["within_program_cost_ceiling"])
        for row in rows:
            self.assertTrue(row["structural_need"]["finalizer_needs_peer"])
            self.assertTrue(row["ownership"]["b_to_a_ownership_verified"])
            self.assertTrue(row["exposure"]["read_after_write_verified"])
            self.assertEqual(row["request"]["ling_planned_calls"], 4)
            self.assertEqual(row["request"]["jev_planned_calls"], 1)
            self.assertIn(row["status"], {"ok", "silence", "failed", "not_attempted"})

    def test_unaccounted_writer_exception_stops_and_journals_the_whole_manifest(self):
        seed_rows = self.registration["fixed_n"]["manifest"]
        behavior = {seed_rows[0]["instance_id"]: RuntimeError("offline-fake outage"),
                    seed_rows[1]["instance_id"]: RuntimeError("offline-fake outage")}
        report, transport = self.run_with_transport(behavior=behavior)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"],
                         "unaccounted_transport_or_audit_exception")
        self.assertEqual(report["planned_seeds"], 16)
        self.assertEqual(report["journaled_seeds"], 16)
        rows = [json.loads(line) for line in
                self.journal_path.read_text(encoding="utf-8").splitlines()]
        statuses = [row["status"] for row in rows]
        self.assertEqual(len(rows), 16)
        self.assertEqual(statuses[0], "failed")
        self.assertTrue(all(row["status"] == "not_attempted" for row in rows[1:]))
        self.assertTrue(all(row["failure_reason"] ==
                            "not_attempted:unaccounted_transport_or_audit_exception"
                            for row in rows[1:]))
        self.assertEqual(rows[0]["physical_attempts"]["ling"], 3)

    def test_writer_attempt_count_overage_is_a_stop_and_journal_stays_complete(self):
        manifest = self.registration["fixed_n"]["manifest"]
        first = manifest[0]["instance_id"]
        overage = {"attempts": 9, "cost_usd": 0.0, "outcome": "message_candidate",
                   "claim": "bit0=0", "input_tokens": 1, "output_tokens": 1}
        behavior = {first: dict(overage)}
        report, _ = self.run_with_transport(behavior=behavior)
        self.assertEqual(report["journaled_seeds"], 16)
        self.assertTrue(report["journal_complete_at_registered_n"])
        rows = [json.loads(line) for line in
                self.journal_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows[0]["status"], "failed")

    def test_cost_cap_stops_before_the_next_call_and_journals_all_rows(self):
        manifest = self.registration["fixed_n"]["manifest"]
        first = manifest[0]["instance_id"]
        expensive = {"attempts": 1,
                     "cost_usd": 0.15,
                     "outcome": "message_candidate", "claim": "bit0=0",
                     "input_tokens": 10, "output_tokens": 10}
        behavior = {first: copy.deepcopy(expensive)}
        report, _ = self.run_with_transport(behavior=behavior)
        self.assertEqual(report["status"], "stopped")
        self.assertIn(report["stop_reason"],
                      {"cost_cap_exceeded_after_call", "cost_cap_before_next_call:ling"})
        self.assertEqual(report["journaled_seeds"], 16)
        rows = [json.loads(line) for line in
                self.journal_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 16)
        self.assertEqual(report["caps"]["within_ceiling"], False)
        self.assertTrue(all(row["status"] == "not_attempted" for row in rows[1:]))

    def test_request_identity_drift_is_a_stop(self):
        manifest = self.registration["fixed_n"]["manifest"]
        first = manifest[0]["instance_id"]
        drifted = {"attempts": 1, "cost_usd": 0.00067584,
                   "outcome": "message_candidate", "claim": "bit0=0",
                   "input_tokens": 10, "output_tokens": 10,
                   "request_identity": {"model": "wrong-model"}}
        behavior = {first: copy.deepcopy(drifted)}
        report, _ = self.run_with_transport(behavior=behavior)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "writer_request_identity_drift")
        rows = [json.loads(line) for line in
                self.journal_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows[0]["failure_reason"], "writer_error:writer_request_identity_drift")
        self.assertTrue(all(row["status"] == "not_attempted" for row in rows[1:]))

    def test_receiver_invalid_vector_stops_the_run_and_journals_all_rows(self):
        manifest = self.registration["fixed_n"]["manifest"]
        first = manifest[0]["instance_id"]
        behavior = {(first, "receiver"): {
            "attempts": 1, "cost_usd": 0.000344064, "status": "complete",
            "model": l05.JEV_MODEL, "codec_version": l05.JEV_CODEC_VERSION,
            "normalization_tier": "invalid", "renormalized": False,
            "probabilities": {}, "raw_probabilities": {},
            "usage": {"input_tokens": 1, "output_tokens": 1}}}
        report, _ = self.run_with_transport(behavior=behavior)
        # A malformed receiver vector is a registered terminal stop; the run
        # keeps the whole fixed manifest as an immutable journal.
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "request_hash_drift")
        self.assertEqual(report["journaled_seeds"], 16)
        rows = [json.loads(line) for line in
                self.journal_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows[0]["status"], "failed")
        self.assertTrue(all(row["status"] == "not_attempted" for row in rows[1:]))

    def test_malformed_normalization_diagnostics_stop_before_next_seed(self):
        class MalformedReceiver(FakeTransport):
            def receiver_choice(self, *, request):
                result = dict(super().receiver_choice(request=request))
                result["normalization_diagnostics"] = {
                    "absolute_normalization_deviation": "invalid"}
                return result

        report = l05.execute_legal_discovery_run(
            self.registration, self.lock, self.auth, repo_root=REPO_ROOT,
            lock_review=self.lock_review,
            approval=self.auth["reference"], preflight=self.preflight,
            transport_factory=MalformedReceiver,
            journal_path=self.journal_path, report_path=self.report_path)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "normalization_diagnostics_invalid")
        rows = [json.loads(line) for line in
                self.journal_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 16)
        self.assertEqual(rows[0]["status"], "failed")
        self.assertTrue(all(row["status"] == "not_attempted" for row in rows[1:]))


class CliTests(LegalPreflightFixture):
    def test_cli_live_without_the_lock_refuses_after_a_green_preflight(self):
        with contextlib.redirect_stdout(io.StringIO()) as buffer:
            rc = l05.main(["--repo-root", str(REPO_ROOT), "--live", "--no-report"])
        self.assertEqual(rc, 3)
        output = buffer.getvalue()
        self.assertIn("lock_pending_l06", output)
        self.assertIn('"provider_calls": 0', output)

    def test_cli_preflight_only_reports_zero_provider_calls(self):
        with contextlib.redirect_stdout(io.StringIO()) as buffer:
            rc = l05.main(["--repo-root", str(REPO_ROOT), "--no-report"])
        self.assertEqual(rc, 0)
        output = buffer.getvalue()
        self.assertIn('"authorized": false', output)
        self.assertIn('"network_events": 0', output)
        self.assertIn('"provider_calls": 0', output)


if __name__ == "__main__":
    unittest.main()
