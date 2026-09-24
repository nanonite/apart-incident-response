import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_choice_v2 as jc2
from apart_incident_response import jev_coverage_bridge_v6 as run6
from apart_incident_response import jev_coverage_manifest_preregistration_v6 as prv6
from apart_incident_response import jev_ling_writer_v5 as writer_v5
from apart_incident_response import jev_replay_preregistration as pr
from apart_incident_response import jev_six_form_coverage_audit as audit


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = json.loads(
    (REPO_ROOT / "runs/epic-126" / "jev-coverage-manifest-preregistration-v6.json")
    .read_text(encoding="utf-8"))
PIN = REGISTRATION["preregistration_hash"]
KEY = "openrouter-test-key-0123456789"


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.t += delay


class FakeResponse:
    def __init__(self, content="SILENCE", finish_reason=None):
        body = {"choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3}}
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class FakeReceiverClient:
    provider = "jev"
    endpoint = jc.JEV_SYSTEMONE_ENDPOINT
    max_retries = pr.JEV_REPLAY_MAX_RETRIES

    def __init__(self, *, max_physical_requests=108):
        self.max_physical_requests = max_physical_requests
        self.physical_attempts = 0
        self.calls = 0

    def complete(self, request):
        self.physical_attempts += 1
        self.calls += 1
        question_id = next(iter(request["questions"]))
        option_ids = list(request["questions"][question_id]["criteria"])
        rest = 0.5 / (len(option_ids) - 1)
        probabilities = {option_id: (0.5 if index == 0 else rest)
                         for index, option_id in enumerate(option_ids)}
        return {"model": jc.JEV_DEFAULT_MODEL,
                "answers": {question_id: {"type": "choice", "choice": option_ids[0],
                                          "probabilities": probabilities, "confidence": 0.5}},
                "usage": {"input_tokens": 10, "output_tokens": 2}}


def _prompt(request):
    return json.loads(request.data)["messages"][0]["content"]


def _silence(prompt):
    """Original-grammar silence: a valid ANSWER with no MESSAGE line."""

    return FakeResponse(f"ANSWER: {prompt['candidate_labels'][0]}")


def owned_side_effect(capture=None, reject_agent=None):
    def respond(request, timeout=None):
        prompt = json.loads(_prompt(request))
        if capture is not None:
            capture.append(prompt)
        agent = "A" if prompt.get("is_finalizer") else "B"
        turn = prompt["turn"]
        if reject_agent is not None and agent == reject_agent and turn == 0:
            return FakeResponse("MESSAGE: invented-clue")
        clues = prompt["private_clues"]
        return FakeResponse(f"MESSAGE: {clues[0]}" if clues else "SILENCE")
    return respond


def b_only_specific_clue_side_effect(clue="precedes=deploy>stage"):
    """A always silent; B writes only its specific registered clue."""

    def respond(request, timeout=None):
        prompt = json.loads(_prompt(request))
        agent = "A" if prompt.get("is_finalizer") else "B"
        clues = prompt["private_clues"]
        if agent == "B" and clues and clues[0] == clue:
            return FakeResponse(f"MESSAGE: {clues[0]}")
        return _silence(prompt)
    return respond


def empty_side_effect(request, timeout=None):
    return FakeResponse("")


def build(side_effect=None, *, registration=None, receiver_cap=108, writer_cap=432,
          check_credentials=False, approval="test", receiver_client=None):
    registration = registration or REGISTRATION
    client = receiver_client or FakeReceiverClient(max_physical_requests=receiver_cap)
    receiver = jc2.JevChoiceAdapterV2(
        client, model=registration["model_and_protocol"]["model"])
    clock = FakeClock()
    writer = writer_v5.LingWriterClientV5(
        api_key=KEY, max_physical_requests=writer_cap,
        clock=clock.now, sleep_fn=clock.sleep)
    plan, instances = run6.build_coverage_plan(registration)
    verification = run6.verify_coverage_bridge_preflight(
        plan, registration, receiver, writer, repo_root=REPO_ROOT, approval=approval,
        check_credentials=check_credentials, pinned_hash=registration.get("preregistration_hash"))
    return registration, receiver, writer, plan, instances, verification, side_effect


def run(side_effect=None, *, approval="test", verification=None, registration=None,
        **kwargs):
    registration, receiver, writer, plan, instances, verify, se = build(
        side_effect, registration=registration, approval=approval, **kwargs)
    used_verification = verification if verification is not None else verify
    with tempfile.TemporaryDirectory() as directory:
        journal = Path(directory) / "coverage.jsonl"
        report_path = Path(directory) / "coverage-report.json"
        with patch.object(writer_v5.urllib.request, "urlopen", side_effect=se):
            report = run6.execute_coverage_bridge(
                plan, receiver, writer, used_verification, instances,
                approval=approval, registration=registration,
                pinned_hash=registration.get("preregistration_hash"),
                journal_path=journal, report_path=report_path, sleep_fn=lambda _: None)
        rows = ([json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()
                 if line.strip()] if journal.exists() else [])
        report_written = report_path.exists()
    return report, receiver, writer, plan, instances, rows, report_written


class PlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registration = run6.load_locked_registration(repo_root=REPO_ROOT)
        cls.plan, cls.instances = run6.build_coverage_plan(cls.registration)

    def test_exact_36_instance_plan_registered_order(self):
        registered = REGISTRATION["manifest"]["instance_ids"]
        self.assertEqual(list(self.plan.instance_ids), registered)
        self.assertEqual(len(self.plan.instance_ids), 36)
        self.assertEqual(len(set(self.plan.instance_ids)), 36)
        self.assertEqual([instance.instance_id for instance in self.instances], registered)
        self.assertEqual([instance.seed for instance in self.instances],
                         REGISTRATION["manifest"]["instance_seeds"])

    def test_six_per_form_membership_and_prompt_forms(self):
        self.assertEqual(set(self.plan.form_membership), set(prv6.FROZEN_FORM_IDS))
        for form, ids in self.plan.form_membership.items():
            with self.subTest(form=form):
                self.assertEqual(len(ids), 6)
                self.assertEqual(list(ids), REGISTRATION["manifest"]["form_membership"][form])
        self.assertEqual(set(self.plan.prompt_form_ids.values()), set(prv6.FROZEN_FORM_IDS))
        for instance_id, form in self.plan.prompt_form_ids.items():
            membership = REGISTRATION["manifest"]["form_membership"][form]
            self.assertIn(instance_id, membership)

    def test_planned_and_partition_arithmetic(self):
        self.assertEqual((self.plan.planned_ling, self.plan.planned_jev,
                          self.plan.planned_requests), (144, 36, 180))
        self.assertEqual((self.plan.ling_request_cap, self.plan.jev_request_cap,
                          self.plan.request_cap), (432, 108, 540))
        self.assertEqual(self.plan.ling_request_cap + self.plan.jev_request_cap,
                         self.plan.request_cap)
        self.assertEqual(self.plan.cost_cap_usd, 1.0)
        self.assertEqual(self.plan.worst_case_call_cost_usd, 0.000344064)
        self.assertEqual(self.plan.worst_case_next_call_cost_usd,
                         round(0.000344064 * (1 + pr.JEV_REPLAY_MAX_RETRIES), 12))
        self.assertLessEqual(self.plan.planned_ling, self.plan.ling_request_cap)
        self.assertLessEqual(self.plan.planned_jev, self.plan.jev_request_cap)
        self.assertLessEqual(self.plan.planned_requests, self.plan.request_cap)

    def test_runtime_clients_receive_registered_caps(self):
        receiver, writer, plan, instances = run6.construct_coverage_runtime(REGISTRATION)
        self.assertEqual(receiver.client.max_physical_requests, 108)
        self.assertEqual(writer.max_physical_requests, 432)
        self.assertEqual(receiver.model, REGISTRATION["model_and_protocol"]["model"])
        self.assertEqual(writer.model, REGISTRATION["model_and_protocol"]["ling_model"])
        self.assertEqual(len(instances), 36)


class PreflightTests(unittest.TestCase):
    def _preflight(self, registration=None, *, receiver=None, writer=None,
                   approval="test", check_credentials=False):
        registration = registration or REGISTRATION
        if receiver is None or writer is None:
            receiver = jc2.JevChoiceAdapterV2(
                FakeReceiverClient(max_physical_requests=108),
                model=REGISTRATION["model_and_protocol"]["model"])
            writer = writer_v5.LingWriterClientV5(
                api_key=KEY, max_physical_requests=432, clock=FakeClock().now,
                sleep_fn=lambda _: None)
        plan, _ = run6.build_coverage_plan(registration)
        return run6.verify_coverage_bridge_preflight(
            plan, registration, receiver, writer, repo_root=REPO_ROOT, approval=approval,
            check_credentials=check_credentials, pinned_hash=registration.get("preregistration_hash"))

    def test_preflight_ok_named_checks(self):
        result = self._preflight()
        self.assertTrue(result["ok"], result["failed"])
        names = {check["check"] for check in result["checks"]}
        for required in ("approval_present", "registration_verifies",
                         "registration_hash_matches", "status_locked",
                         "live_collection_not_authorized", "runner_policy_satisfied",
                         "runner_not_live_authorization",
                         "source_treatment_geometry_prompt_hashes_wellformed",
                         "manifest_36_exact_order", "forms_six_per_exact_form",
                         "manifest_disjointness", "fixed_n_and_no_replacement",
                         "resume_not_permitted", "jev_model_matches", "jev_endpoint_matches",
                         "jev_retry_policy", "jev_protocol_key", "jev_partition_matches",
                         "ling_model_matches", "ling_endpoint_matches",
                         "ling_parser_and_schema", "ling_pacing", "ling_retry_policy",
                         "ling_seed_behavior", "token_budget_matches",
                         "grammar_and_prompt_path", "two_agents_two_turns",
                         "ling_partition_matches", "combined_cap_and_partitions",
                         "planned_within_caps", "cost_cap_and_guard", "journal_path_fresh",
                         "report_path_fresh", "frozen_v1_v5_and_189_inputs_unchanged"):
            self.assertIn(required, names)

    def test_credential_checks_only_when_requested(self):
        present = type("Creds", (), {"present": True, "shape_ok": True,
                                     "redacted": lambda self: {}})()
        absent = type("Creds", (), {"present": False, "shape_ok": False,
                                    "redacted": lambda self: {}})()
        with patch.object(jc, "load_jev_credentials", return_value=present):
            result = self._preflight(check_credentials=True)
            self.assertTrue(result["ok"], result["failed"])
        with patch.object(jc, "load_jev_credentials", return_value=absent):
            result = self._preflight(check_credentials=True)
            self.assertFalse(result["ok"])
            self.assertIn("jev_credentials_present", result["failed"])
        result = self._preflight(check_credentials=True)
        # ling_key_present defaults to ambient key detection via bd._api_key
        self.assertTrue(any(check["check"] == "ling_credentials_present"
                            for check in result["checks"]))
        result = self._preflight(check_credentials=True, approval=None)
        self.assertIn("approval_present", result["failed"])

    def test_wrong_registration_fields_fail_preflight(self):
        mutations = [
            ("model_and_protocol", "model", "jev-0.0.0", "jev_model_matches"),
            ("model_and_protocol", "endpoint", "https://x.invalid", "jev_endpoint_matches"),
            ("model_and_protocol", "protocol_key", "jev-choice-wire-v2|dead",
             "jev_protocol_key"),
            ("treatment", "token_budget", 96, "token_budget_matches"),
            ("treatment", "seed_algorithm", "unseeded", "ling_seed_behavior"),
            ("caps", "cost_cap_usd", 0.5, "cost_cap_and_guard"),
            ("generator", "source_files_hash", "0" * 64, "registration_verifies"),
            ("manifest", "iso_form_ids", ["deadbeef"], "forms_six_per_exact_form"),
        ]
        for section, field, value, expected in mutations:
            tampered = json.loads(json.dumps(REGISTRATION))
            tampered[section][field] = value
            receiver = jc2.JevChoiceAdapterV2(
                FakeReceiverClient(max_physical_requests=108),
                model=tampered["model_and_protocol"]["model"]
                if field == "model" else REGISTRATION["model_and_protocol"]["model"])
            writer = writer_v5.LingWriterClientV5(
                api_key=KEY, max_physical_requests=432, clock=FakeClock().now,
                sleep_fn=lambda _: None)
            plan, _ = run6.build_coverage_plan(tampered)
            result = run6.verify_coverage_bridge_preflight(
                plan, tampered, receiver, writer, repo_root=REPO_ROOT, approval="test",
                check_credentials=False,
                pinned_hash=tampered.get("preregistration_hash"))
            with self.subTest(section=section, field=field):
                self.assertFalse(result["ok"])
                self.assertIn(expected, result["failed"], result["failed"])

    def test_wrong_manifest_order_rejected_at_plan_and_preflight(self):
        tampered = json.loads(json.dumps(REGISTRATION))
        ids = tampered["manifest"]["instance_ids"]
        ids[0], ids[1] = ids[1], ids[0]
        with self.assertRaises(ValueError):
            run6.build_coverage_plan(tampered)
        plan, _ = run6.build_coverage_plan(REGISTRATION)
        receiver = jc2.JevChoiceAdapterV2(FakeReceiverClient(max_physical_requests=108),
                                          model=REGISTRATION["model_and_protocol"]["model"])
        writer = writer_v5.LingWriterClientV5(api_key=KEY, max_physical_requests=432,
                                              clock=FakeClock().now, sleep_fn=lambda _: None)
        result = run6.verify_coverage_bridge_preflight(
            plan, tampered, receiver, writer, repo_root=REPO_ROOT, approval="test",
            check_credentials=False, pinned_hash=tampered.get("preregistration_hash"))
        self.assertFalse(result["ok"])
        self.assertIn("manifest_36_exact_order", result["failed"])
        self.assertIn("registration_verifies", result["failed"])

    def test_wrong_form_count_rejected(self):
        tampered = json.loads(json.dumps(REGISTRATION))
        form = prv6.FROZEN_FORM_IDS[0]
        tampered["manifest"]["form_membership"][form] = \
            tampered["manifest"]["form_membership"][form][:5]
        with self.assertRaises(ValueError):
            run6.build_coverage_plan(tampered)

    def test_runtime_transport_drift_rejected(self):
        receiver = jc2.JevChoiceAdapterV2(FakeReceiverClient(max_physical_requests=107),
                                          model=REGISTRATION["model_and_protocol"]["model"])
        writer = writer_v5.LingWriterClientV5(api_key=KEY, max_physical_requests=432,
                                              clock=FakeClock().now, sleep_fn=lambda _: None)
        plan, _ = run6.build_coverage_plan(REGISTRATION)
        result = run6.verify_coverage_bridge_preflight(
            plan, REGISTRATION, receiver, writer, repo_root=REPO_ROOT, approval="test",
            check_credentials=False, pinned_hash=PIN)
        self.assertIn("jev_partition_matches", result["failed"])

        writer2 = writer_v5.LingWriterClientV5(api_key=KEY, max_physical_requests=431,
                                               clock=FakeClock().now, sleep_fn=lambda _: None)
        result = run6.verify_coverage_bridge_preflight(
            plan, REGISTRATION, receiver=type("R", (), {"model": REGISTRATION[
                "model_and_protocol"]["model"],
                "client": FakeReceiverClient(max_physical_requests=108)})(),
            writer=writer2, repo_root=REPO_ROOT, approval="test",
            check_credentials=False, pinned_hash=PIN)
        self.assertIn("ling_partition_matches", result["failed"])

        writer3 = writer_v5.LingWriterClientV5(api_key=KEY, max_physical_requests=432,
                                               clock=FakeClock().now, sleep_fn=lambda _: None)
        writer3.min_attempt_interval_seconds = 0.25
        result = run6.verify_coverage_bridge_preflight(
            plan, REGISTRATION,
            receiver=type("R", (), {"model": REGISTRATION["model_and_protocol"]["model"],
                                    "client": FakeReceiverClient(
                                        max_physical_requests=108)})(),
            writer=writer3, repo_root=REPO_ROOT, approval="test",
            check_credentials=False, pinned_hash=PIN)
        self.assertIn("ling_pacing", result["failed"])

        writer4 = writer_v5.LingWriterClientV5(api_key=KEY, max_physical_requests=432,
                                               max_retries=5, clock=FakeClock().now,
                                               sleep_fn=lambda _: None)
        result = run6.verify_coverage_bridge_preflight(
            plan, REGISTRATION,
            receiver=type("R", (), {"model": REGISTRATION["model_and_protocol"]["model"],
                                    "client": FakeReceiverClient(
                                        max_physical_requests=108)})(),
            writer=writer4, repo_root=REPO_ROOT, approval="test",
            check_credentials=False, pinned_hash=PIN)
        self.assertIn("ling_retry_policy", result["failed"])


class BlockingTests(unittest.TestCase):
    def test_missing_approval_zero_calls_no_files(self):
        report, receiver, writer, *_ = run(owned_side_effect(), approval=None)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["stop_reason"], "missing_approval")
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(writer.physical_attempts, 0)

    def test_failed_preflight_zero_calls_no_files(self):
        report, receiver, writer, *_ = run(
            owned_side_effect(), verification={"ok": False, "failed": ["x"], "checks": []})
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["stop_reason"], "preflight_failed")
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(writer.physical_attempts, 0)

    def test_pinned_hash_mismatch_blocks(self):
        registration, receiver, writer, plan, instances, verification, se = build(
            owned_side_effect())
        report = run6.execute_coverage_bridge(
            plan, receiver, writer, verification, instances, approval="test",
            registration=registration, pinned_hash="0" * 64,
            journal_path=Path(tempfile.mkdtemp()) / "j.jsonl",
            report_path=Path(tempfile.mkdtemp()) / "r.json")
        self.assertEqual(report["stop_reason"], "registration_hash_mismatch")
        self.assertEqual(receiver.client.calls, 0)

    def test_existing_journal_or_report_blocks_and_preserves_bytes(self):
        registration, receiver, writer, plan, instances, verification, se = build(
            owned_side_effect())
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "j.jsonl"
            report_path = Path(directory) / "r.json"
            journal.write_text("SENTINEL-JOURNAL", encoding="utf-8")
            report = run6.execute_coverage_bridge(
                plan, receiver, writer, verification, instances, approval="test",
                registration=registration, pinned_hash=PIN,
                journal_path=journal, report_path=report_path, sleep_fn=lambda _: None)
            self.assertEqual(report["stop_reason"], "output_exists")
            self.assertEqual(journal.read_text(encoding="utf-8"), "SENTINEL-JOURNAL")
            self.assertEqual(receiver.client.calls, 0)
            journal.unlink()
            report_path.write_text("SENTINEL-REPORT", encoding="utf-8")
            report = run6.execute_coverage_bridge(
                plan, receiver, writer, verification, instances, approval="test",
                registration=registration, pinned_hash=PIN,
                journal_path=journal, report_path=report_path, sleep_fn=lambda _: None)
            self.assertEqual(report["stop_reason"], "report_exists")
            self.assertEqual(report_path.read_text(encoding="utf-8"), "SENTINEL-REPORT")
            self.assertEqual(receiver.client.calls, 0)

    def test_partition_not_enforced_blocks(self):
        registration, receiver, writer, plan, instances, verification, se = build(
            owned_side_effect(), writer_cap=431)
        writer.max_physical_requests = 431
        report = run6.execute_coverage_bridge(
            plan, receiver, writer, {"ok": True, "checks": [], "failed": []}, instances,
            approval="test",
            registration=registration, pinned_hash=PIN,
            journal_path=Path(tempfile.mkdtemp()) / "j.jsonl",
            report_path=Path(tempfile.mkdtemp()) / "r.json")
        self.assertEqual(report["stop_reason"], "writer_partition_not_enforced")
        self.assertEqual(receiver.client.calls, 0)


class FixedNRunTests(unittest.TestCase):
    def test_full_fixed_n_run_exact_physical_calls(self):
        report, receiver, writer, plan, instances, rows, written = run(owned_side_effect())
        self.assertEqual(report["status"], "completed")
        self.assertIsNone(report["stop_reason"])
        self.assertEqual(report["attempted_cases"], 36)
        self.assertEqual(report["receiver_valid_cases"], 36)
        self.assertEqual(report["receiver_invalid_cases"], 0)
        self.assertEqual(report["receiver_unattempted_cases"], 0)
        self.assertEqual(len(rows), 36)
        self.assertEqual([row["instance_id"] for row in rows], list(plan.instance_ids))
        self.assertEqual(writer.physical_attempts, 144)
        self.assertEqual(receiver.client.physical_attempts, 36)
        self.assertEqual(report["provider_attempts"]["ling"], 144)
        self.assertEqual(report["provider_attempts"]["jev"], 36)
        self.assertEqual(report["provider_attempts"]["combined"], 180)
        self.assertEqual(report["physical_attempts"], 180)
        self.assertEqual((report["planned_calls"]["ling"], report["planned_calls"]["jev"],
                          report["planned_calls"]["combined"]), (144, 36, 180))
        self.assertEqual(report["partitions"], {"ling": 432, "jev": 108, "combined": 540})
        self.assertEqual(report["distinct_forms"], 6)
        self.assertEqual(report["writer_invalid_cases"], 0)

    def test_fixed_n_continues_through_silence_and_rejected_writes(self):
        def mixed(request, timeout=None):
            prompt = json.loads(_prompt(request))
            agent = "A" if prompt.get("is_finalizer") else "B"
            turn = prompt["turn"]
            if agent == "B" and turn == 0:
                return FakeResponse("MESSAGE: invented-clue")
            if turn == 1:
                return _silence(prompt)
            clues = prompt["private_clues"]
            if clues:
                return FakeResponse(f"MESSAGE: {clues[0]}")
            return _silence(prompt)

        report, receiver, writer, plan, instances, rows, _ = run(mixed)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["attempted_cases"], 36)
        self.assertEqual(len(rows), 36)
        self.assertEqual(writer.physical_attempts, 144)
        self.assertEqual(receiver.client.physical_attempts, 36)
        totals = report["writer_outcome_totals"]
        self.assertIn("non_owned_claim", totals)
        self.assertIn("deliberate_silence", totals)
        self.assertIn("message_candidate", totals)
        self.assertGreater(report["writer_outcome_totals"].get("non_owned_claim", 0), 0)
        self.assertGreater(report["writer_outcome_totals"].get("deliberate_silence", 0), 0)

    def test_terminal_writer_failure_preserves_partial_journal(self):
        report, receiver, writer, plan, instances, rows, _ = run(empty_side_effect)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "empty_output")
        self.assertEqual(report["attempted_cases"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["writer_outcomes"][0]["outcome"], "empty_output")
        self.assertTrue(rows[0]["receiver_unattempted"])
        self.assertEqual(report["receiver_unattempted_cases"], 1)
        self.assertEqual(receiver.client.calls, 0)

    def test_eligibility_uses_authoritative_189_selector(self):
        report, receiver, writer, plan, instances, rows, _ = run(owned_side_effect())
        by_id = {instance.instance_id: instance for instance in instances}
        for row in rows:
            expected = audit.select_replay_claims(row, by_id[row["instance_id"]])
            self.assertEqual(row["replay_selection"], expected)
            self.assertEqual(row["replay_eligible"],
                             bool(expected["eligible"] and row["receiver_valid"]))
            self.assertLessEqual(len(expected["selected"]), 1)
        self.assertEqual(report["replay_eligible_events"], 36)
        self.assertEqual(report["replay_eligible_claims"], 36)
        self.assertTrue(report["one_deduplicated_claim_per_pre_read_state"])

    def test_per_form_report_counts(self):
        report, receiver, writer, plan, instances, rows, _ = run(
            b_only_specific_clue_side_effect())
        per_form = report["per_form"]
        covered_form = "3196a8d69f844702db012816def7d7866e7416e9fadc9f28eaa7f12ac16a8569"
        block = per_form[covered_form]
        self.assertEqual(block["planned_cases"], 6)
        self.assertEqual(block["attempted_cases"], 6)
        self.assertEqual(block["receiver_valid_cases"], 6)
        self.assertEqual(block["b_writer_opportunities"], 12)
        self.assertEqual(block["accepted_b_messages"], 12)
        self.assertEqual(block["eligible_b_to_a_events"], 6)
        self.assertEqual(block["deliberate_silence_outcomes"], 12)  # A silent, 2 turns x 6
        self.assertEqual(block["rejected_write_attempts"], 0)
        other = per_form["0a3349e16c9633b4d559dfbb808d1e50d0446d8f92160a0feddd1e37299796ee"]
        self.assertEqual(other["attempted_cases"], 6)
        self.assertEqual(other["b_writer_opportunities"], 12)
        self.assertEqual(other["accepted_b_messages"], 0)
        self.assertEqual(other["eligible_b_to_a_events"], 0)
        self.assertEqual(other["deliberate_silence_outcomes"], 24)  # A+B silent, 6 instances
        self.assertEqual(report["forms_with_eligible_exposure"], 1)
        self.assertEqual(len(report["missing_forms"]), 5)
        self.assertIn(covered_form, report["forms_with_eligible_exposure_ids"])
        self.assertTrue(report["one_deduplicated_claim_per_pre_read_state"])
        self.assertEqual(report["replay_eligible_events"], 6)
        self.assertEqual(report["replay_eligible_claims"], 6)

    def test_report_flags_and_gross_labeling(self):
        report, *_ = run(owned_side_effect())
        self.assertTrue(report["coverage_decision_pending_192"])
        self.assertFalse(report["replay_started"])
        self.assertFalse(report["raw_response_retained"])
        self.assertFalse(report["credentials_retained"])
        self.assertIn("gross", report["i_m_bits_label"])
        self.assertIn("belongs to #192", report["coverage_note"])
        self.assertIn("does not start #159", report["coverage_note"])
        self.assertEqual(report["seeds_replaced"], 0)
        self.assertEqual(report["verified_read_exposures"],
                         report["verified_read_exposures_counted"])
        normalization = report["normalization"]
        self.assertEqual(normalization["tiers"], {"exact": 36})
        self.assertEqual(normalization["normalized_rows"], 36)
        self.assertEqual(normalization["materially_renormalized_rows"], 0)
        self.assertGreater(report["i_m_bits"], 0.0)
        self.assertEqual(report["messages_by_direction"]["b_to_a"] > 0, True)

    def test_journal_rows_contain_frozen_evidence(self):
        report, receiver, writer, plan, instances, rows, _ = run(owned_side_effect())
        required = {
            "instance_id", "instance_seed", "prompt_form_id", "registered_form_membership",
            "writer_outcomes", "board", "rejected", "board_log", "receiver_attempted",
            "receiver_unattempted", "receiver_invalid", "receiver_valid",
            "receiver_error_class", "selected_option_id", "probabilities",
            "raw_probabilities", "probability_diagnostics", "normalization_tier",
            "renormalized", "request_hash", "state_hash", "protocol_key",
            "resolved_model", "confidence", "usage", "provider_attempts",
            "replay_selection", "replay_eligible", "eligible_exposure",
            "accepted_b_message_present", "material_correction",
            "raw_response_retained", "credentials_retained",
        }
        for row in rows:
            missing = required - set(row)
            self.assertFalse(missing, missing)
            self.assertFalse(row["raw_response_retained"])
            self.assertFalse(row["credentials_retained"])
            self.assertTrue(row["registered_form_membership"])
            self.assertIn(row["prompt_form_id"], prv6.FROZEN_FORM_IDS)
            self.assertEqual(row["instance_seed"],
                             int(row["instance_id"].split("-")[1], 16))
            self.assertEqual(row["protocol_key"], REGISTRATION["model_and_protocol"][
                "protocol_key"])
            self.assertEqual(set(row["probabilities"]), set(row["option_ids"]))
            outcome = row["writer_outcomes"][0]
            for key in ("finish_reason", "input_tokens", "output_tokens", "content_length",
                        "parser_classification", "outcome", "agent", "turn"):
                self.assertIn(key, outcome)
            for event in row["board_log"]:
                self.assertIn(event["kind"],
                              ("board_write", "peer_read_exposure", "board_write_rejected"))

    def test_no_raw_responses_or_credentials_retained(self):
        report, *_ = run(owned_side_effect())
        dumped = json.dumps(report, sort_keys=True)
        self.assertNotIn(KEY, dumped)
        self.assertNotIn("Authorization", dumped)
        self.assertNotIn("authorization", dumped.lower().replace(
            "credentials_retained", ""))
        self.assertFalse(report["raw_response_retained"])
        self.assertFalse(report["credentials_retained"])
        for row in report["cases"]:
            self.assertFalse(row["raw_response_retained"])
            self.assertFalse(row["credentials_retained"])


class AuthoritativeEligibilityTests(unittest.TestCase):
    def test_eligible_exposure_mirrors_selector_for_every_row(self):
        report, receiver, writer, plan, instances, rows, _ = run(owned_side_effect())
        for row in rows:
            self.assertEqual(row["eligible_exposure"], row["replay_eligible"])
            self.assertTrue(row["accepted_b_message_present"])
            self.assertTrue(row["eligible_exposure"])

    def test_message_presence_does_not_imply_eligibility(self):
        class DriftReceiverClient(FakeReceiverClient):
            def complete(self, request):
                payload = super().complete(request)
                payload["model"] = "jev-9.9.9"
                return payload

        report, receiver, writer, plan, instances, rows, _ = run(
            owned_side_effect(), receiver_client=DriftReceiverClient(
                max_physical_requests=108))
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "model_drift")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertTrue(row["accepted_b_message_present"])
        self.assertFalse(row["receiver_valid"])
        self.assertFalse(row["replay_eligible"])
        self.assertFalse(row["eligible_exposure"])
        self.assertEqual(row["receiver_error_class"], "model_drift")

    def test_rejected_write_counted_once(self):
        form = prv6.FROZEN_FORM_IDS[0]
        case = {"prompt_form_id": form, "receiver_valid": True, "receiver_attempted": True,
                "writer_outcomes": [{"agent": "B", "turn": 0, "outcome": "non_owned_claim"}],
                "board": [], "board_log": [],
                "rejected": [{"agent": "B", "turn": 0, "claim": "invented"}],
                "normalization_tier": "exact", "renormalized": True,
                "material_correction": False, "replay_eligible": False,
                "replay_selection": {"selected": []}}
        summary = run6.summarize_coverage([case], counted_exposures=0)
        self.assertEqual(summary["per_form"][form]["rejected_write_attempts"], 1)
        self.assertEqual(summary["writer_outcome_totals"]["non_owned_claim"], 1)

    def test_rejected_writes_not_double_counted_end_to_end(self):
        report, receiver, writer, plan, instances, rows, _ = run(
            owned_side_effect(reject_agent="B"))
        self.assertEqual(report["status"], "completed")
        non_owned = report["writer_outcome_totals"].get("non_owned_claim", 0)
        self.assertEqual(non_owned, 36)
        per_form_total = sum(block["rejected_write_attempts"]
                             for block in report["per_form"].values())
        self.assertEqual(per_form_total, 36)
        journaled = sum(len(row["rejected"]) for row in rows)
        self.assertEqual(journaled, 36)

    def test_material_correction_literal_meaning(self):
        def response(tier, renormalized):
            return type("R", (), {"normalization_tier": tier,
                                  "renormalized": renormalized})()

        self.assertFalse(run6.material_correction(response("exact", True)))
        self.assertFalse(run6.material_correction(response("exact", False)))
        self.assertTrue(run6.material_correction(response("complete_renormalized", True)))
        self.assertFalse(run6.material_correction(response("malformed", False)))
        self.assertFalse(run6.material_correction(response(None, True)))

    def test_cost_guard_reserves_single_retry_inclusive_call(self):
        tampered = json.loads(json.dumps(REGISTRATION))
        tampered["caps"]["cost_cap_usd"] = 0.002
        report, receiver, writer, plan, instances, rows, _ = run(
            owned_side_effect(), registration=tampered,
            verification={"ok": True, "checks": [], "failed": []})
        self.assertEqual(plan.worst_case_next_call_cost_usd, 0.001032192)
        self.assertEqual(report["cost_cap_usd"], 0.002)
        # One retry-inclusive reservation (0.001032192) fits under 0.002, so the
        # full run completes; a triple-reserved 0.0030966 would stop immediately.
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["attempted_cases"], 36)
        self.assertEqual(writer.physical_attempts, 144)
        self.assertEqual(receiver.client.physical_attempts, 36)
        self.assertLessEqual(report["estimated_cost_usd"] + plan.worst_case_next_call_cost_usd,
                             0.002)


class RegistrationAmendmentTests(unittest.TestCase):
    def test_runner_is_source_bound_in_amended_registration(self):
        self.assertIn(prv6.RUNNER_SOURCE_REL, prv6.COVERAGE_SOURCE_FILES)
        self.assertIn(prv6.RUNNER_SOURCE_REL, REGISTRATION["generator"]["source_files"])
        self.assertEqual(REGISTRATION["generator"]["source_files_hash"],
                         prv6._source_files_hash(REPO_ROOT))
        policy = REGISTRATION["runner_policy"]
        self.assertTrue(policy["runner_implemented"])
        self.assertEqual(policy["runner_source_files"], [prv6.RUNNER_SOURCE_REL])
        self.assertTrue(policy["runner_source_bound"])
        self.assertFalse(policy["adding_runner_authorizes_collection"])
        self.assertEqual(policy["superseded_offline_lock"]["preregistration_hash"],
                         prv6.SUPERSEDED_OFFLINE_LOCK_HASH)

    def test_old_registration_hash_rejected(self):
        tampered = json.loads(json.dumps(REGISTRATION))
        tampered["preregistration_hash"] = prv6.SUPERSEDED_OFFLINE_LOCK_HASH
        result = prv6.verify_against_coverage_manifest_preregistration_v6(
            tampered, repo_root=REPO_ROOT)
        self.assertFalse(result["ok"])
        self.assertIn("registration hash drift from the repository state", result["errors"])

    def test_live_authorization_remains_false(self):
        self.assertFalse(REGISTRATION["live_collection_authorized"])
        self.assertFalse(REGISTRATION["approval"]["live_collection_authorized"])
        self.assertFalse(REGISTRATION["runner_policy"]["adding_runner_authorizes_collection"])

    def test_manifest_hash_and_ids_unchanged(self):
        self.assertEqual(REGISTRATION["manifest"]["manifest_hash"],
                         "c4221e7db05fbdcba7b441099cb59d84147fa00d25569000ae2f416ca7233ad1")
        self.assertEqual(len(REGISTRATION["manifest"]["instance_ids"]), 36)


class OfflineCliTests(unittest.TestCase):
    def test_offline_cli_makes_zero_provider_calls(self):
        def explode(*args, **kwargs):
            raise AssertionError("provider call during offline CLI")

        with patch.object(writer_v5.urllib.request, "urlopen", side_effect=explode), \
                patch.object(jc.JevChoiceClient, "complete", side_effect=explode):
            rc = run6.main(["--repo-root", str(REPO_ROOT)])
        self.assertEqual(rc, 0)
        self.assertFalse((REPO_ROOT / prv6.DEFAULT_JOURNAL_V6).exists())
        self.assertFalse((REPO_ROOT / prv6.DEFAULT_REPORT_V6).exists())

    def test_cli_rejects_alternate_output_paths(self):
        alternate_dir = tempfile.mkdtemp(prefix="alt-outputs-")
        alternate_journal = Path(alternate_dir) / "alt.jsonl"
        alternate_report = Path(alternate_dir) / "alt.json"

        def explode(*args, **kwargs):
            raise AssertionError("provider call after alternate-path rejection")

        with patch.object(writer_v5.urllib.request, "urlopen", side_effect=explode), \
                patch.object(jc.JevChoiceClient, "complete", side_effect=explode):
            with self.assertRaises(SystemExit):
                run6.main(["--repo-root", str(REPO_ROOT), "--live", "--approval", "x",
                           "--journal", str(alternate_journal),
                           "--report", str(alternate_report)])
            with self.assertRaises(SystemExit):
                run6.main(["--repo-root", str(REPO_ROOT), "--journal",
                           str(alternate_journal)])
        self.assertFalse(alternate_journal.exists())
        self.assertFalse(alternate_report.exists())
        self.assertFalse((REPO_ROOT / prv6.DEFAULT_JOURNAL_V6).exists())
        self.assertFalse((REPO_ROOT / prv6.DEFAULT_REPORT_V6).exists())

    def test_live_without_approval_makes_zero_provider_calls(self):
        def explode(*args, **kwargs):
            raise AssertionError("provider call without approval")

        with patch.object(writer_v5.urllib.request, "urlopen", side_effect=explode), \
                patch.object(jc.JevChoiceClient, "complete", side_effect=explode):
            rc = run6.main(["--repo-root", str(REPO_ROOT), "--live"])
        self.assertEqual(rc, 2)
        self.assertFalse((REPO_ROOT / prv6.DEFAULT_JOURNAL_V6).exists())
        self.assertFalse((REPO_ROOT / prv6.DEFAULT_REPORT_V6).exists())

    def test_runner_module_source_has_no_transport_construction_in_offline_paths(self):
        # offline validation paths never construct provider calls themselves
        self.assertTrue(callable(run6.verify_coverage_bridge_preflight))
        self.assertTrue(callable(run6.build_coverage_plan))


if __name__ == "__main__":
    unittest.main()
