import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_choice_v2 as jc2
from apart_incident_response import jev_coverage_bridge_v7 as run7
from apart_incident_response import jev_coverage_manifest_preregistration_v7 as prv7
from apart_incident_response import jev_ling_writer_v5 as writer_v5
from apart_incident_response import jev_replay_preregistration as pr
from apart_incident_response import jev_six_form_coverage_audit as audit


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = json.loads(
    (REPO_ROOT / "runs/epic-126" / "jev-coverage-manifest-preregistration-v7.json")
    .read_text(encoding="utf-8"))
PIN = REGISTRATION["preregistration_hash"]
KEY = "openrouter-test-key-0123456789"

# Freshness-sensitive calls pass these so committed prior outputs never matter.
FRESH = {"journal_exists": False, "report_exists": False}


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
    return FakeResponse(f"ANSWER: {prompt['candidate_labels'][0]}")


def owned_side_effect(reject_agent=None):
    def respond(request, timeout=None):
        prompt = json.loads(_prompt(request))
        agent = "A" if prompt.get("is_finalizer") else "B"
        turn = prompt["turn"]
        if reject_agent is not None and agent == reject_agent and turn == 0:
            return FakeResponse("MESSAGE: invented-clue")
        clues = prompt["private_clues"]
        if clues:
            return FakeResponse(f"MESSAGE: {clues[0]}")
        return _silence(prompt)
    return respond


def b_only_specific_clue_side_effect(clue="precedes=deploy>stage"):
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
          receiver_client=None, check_credentials=False, approval="test"):
    registration = registration or REGISTRATION
    client = receiver_client or FakeReceiverClient(max_physical_requests=receiver_cap)
    receiver = jc2.JevChoiceAdapterV2(
        client, model=registration["model_and_protocol"]["model"])
    clock = FakeClock()
    writer = writer_v5.LingWriterClientV5(
        api_key=KEY, model=registration["model_and_protocol"]["ling_model"],
        max_physical_requests=writer_cap, clock=clock.now, sleep_fn=clock.sleep)
    plan, instances = run7.build_coverage_plan(registration)
    verification = run7.verify_coverage_bridge_preflight(
        plan, registration, receiver, writer, repo_root=REPO_ROOT, approval=approval,
        check_credentials=check_credentials, pinned_hash=registration.get("preregistration_hash"),
        **FRESH)
    return registration, receiver, writer, plan, instances, verification, side_effect


def run(side_effect=None, *, approval="test", verification=None, registration=None, **kwargs):
    registration, receiver, writer, plan, instances, verify, se = build(
        side_effect, registration=registration, approval=approval, **kwargs)
    used_verification = verification if verification is not None else verify
    with tempfile.TemporaryDirectory() as directory:
        journal = Path(directory) / "coverage.jsonl"
        report_path = Path(directory) / "coverage-report.json"
        with patch.object(writer_v5.urllib.request, "urlopen", side_effect=se):
            report = run7.execute_coverage_bridge(
                plan, receiver, writer, used_verification, instances,
                approval=approval, registration=registration,
                pinned_hash=registration.get("preregistration_hash"),
                journal_path=journal, report_path=report_path, sleep_fn=lambda _: None)
        rows = ([json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()
                 if line.strip()] if journal.exists() else [])
    return report, receiver, writer, plan, instances, rows


class PlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registration = run7.load_locked_registration(repo_root=REPO_ROOT)
        cls.plan, cls.instances = run7.build_coverage_plan(cls.registration)

    def test_exact_36_instance_plan_registered_order(self):
        registered = REGISTRATION["manifest"]["instance_ids"]
        self.assertEqual(list(self.plan.instance_ids), registered)
        self.assertEqual(len(set(self.plan.instance_ids)), 36)

    def test_six_per_form_membership(self):
        from apart_incident_response import jev_coverage_manifest_preregistration_v6 as prv6
        self.assertEqual(set(self.plan.form_membership), set(prv6.FROZEN_FORM_IDS))
        for ids in self.plan.form_membership.values():
            self.assertEqual(len(ids), 6)

    def test_planned_and_partition_arithmetic(self):
        self.assertEqual((self.plan.planned_ling, self.plan.planned_jev,
                          self.plan.planned_requests), (144, 36, 180))
        self.assertEqual((self.plan.ling_request_cap, self.plan.jev_request_cap,
                          self.plan.request_cap), (432, 108, 540))
        self.assertEqual(self.plan.cost_cap_usd, 1.0)

    def test_runtime_clients_use_paid_sku_and_registered_caps(self):
        receiver, writer, plan, instances = run7.construct_coverage_runtime(REGISTRATION)
        self.assertEqual(writer.model, prv7.PAID_LING_MODEL)
        self.assertNotEqual(writer.model, prv7.PREVIOUS_LING_MODEL)
        self.assertEqual(writer.max_physical_requests, 432)
        self.assertEqual(receiver.client.max_physical_requests, 108)
        self.assertEqual(len(instances), 36)

    def test_cost_accounting_math(self):
        tokens = {"ling_input_tokens": 1008, "ling_output_tokens": 432,
                  "jev_input_tokens": 360, "jev_output_tokens": 72}
        expected = (1008 * 0.06 + 432 * 0.18 + 360 * 0.042) / 1_000_000
        self.assertEqual(run7.estimate_run_cost_usd(tokens, prv7.cost_model()),
                         round(expected, 12))
        self.assertEqual(run7.estimate_run_cost_usd({}, prv7.cost_model()), 0.0)
        # free-route (v1-v6) assumptions are not reused: paid completion tokens cost
        paid_only = run7.estimate_run_cost_usd(
            {"ling_input_tokens": 0, "ling_output_tokens": 1_000_000}, prv7.cost_model())
        self.assertEqual(paid_only, 0.18)


class PreflightTests(unittest.TestCase):
    def _preflight(self, registration=None, *, receiver=None, writer=None,
                   approval="test", check_credentials=False, **kwargs):
        registration = registration or REGISTRATION
        if receiver is None or writer is None:
            receiver = jc2.JevChoiceAdapterV2(
                FakeReceiverClient(max_physical_requests=108),
                model=REGISTRATION["model_and_protocol"]["model"])
            writer = writer_v5.LingWriterClientV5(
                api_key=KEY, model=prv7.PAID_LING_MODEL, max_physical_requests=432,
                clock=FakeClock().now, sleep_fn=lambda _: None)
        plan, _ = run7.build_coverage_plan(registration)
        return run7.verify_coverage_bridge_preflight(
            plan, registration, receiver, writer, repo_root=REPO_ROOT, approval=approval,
            check_credentials=check_credentials, pinned_hash=registration.get("preregistration_hash"),
            **FRESH, **kwargs)

    def test_preflight_ok_named_checks(self):
        result = self._preflight()
        self.assertTrue(result["ok"], result["failed"])
        names = {check["check"] for check in result["checks"]}
        for required in ("approval_present", "registration_verifies", "status_locked",
                         "live_collection_not_authorized", "runner_policy_satisfied",
                         "runner_not_live_authorization",
                         "source_treatment_geometry_prompt_hashes_wellformed",
                         "manifest_36_exact_order", "forms_six_per_exact_form",
                         "manifest_disjointness", "manifest_reuse_justified",
                         "fixed_n_and_no_replacement", "resume_not_permitted",
                         "jev_model_matches", "jev_endpoint_matches", "jev_retry_policy",
                         "jev_protocol_key", "jev_partition_matches",
                         "ling_model_is_paid_sku", "ling_endpoint_matches",
                         "ling_parser_and_schema", "ling_pacing", "ling_retry_policy",
                         "ling_seed_behavior", "token_budget_matches",
                         "grammar_and_prompt_path", "two_agents_two_turns",
                         "ling_partition_matches", "cost_model_frozen_paid_route",
                         "cost_model_recomputes_within_ceiling",
                         "combined_cap_and_partitions", "planned_within_caps",
                         "transport_probe_routing_succeeded_and_capped",
                         "probe_writer_output_not_claimed", "catalog_gate_recorded",
                         "journal_path_fresh", "report_path_fresh",
                         "frozen_v1_v7_inputs_unchanged"):
            self.assertIn(required, names)

    def test_credential_checks_only_when_requested(self):
        present = type("C", (), {"present": True, "shape_ok": True,
                                 "redacted": lambda self: {}})()
        absent = type("C", (), {"present": False, "shape_ok": False,
                                "redacted": lambda self: {}})()
        with patch.object(jc, "load_jev_credentials", return_value=present):
            result = self._preflight(check_credentials=True)
            self.assertTrue(result["ok"], result["failed"])
        with patch.object(jc, "load_jev_credentials", return_value=absent):
            result = self._preflight(check_credentials=True)
            self.assertFalse(result["ok"])
            self.assertIn("jev_credentials_present", result["failed"])
        result = self._preflight(check_credentials=True, approval=None)
        self.assertIn("approval_present", result["failed"])

    def _malformed_catalogs(self):
        return [
            {"model_count": "460", "entries": {}},
            {"model_count": 460, "entries": []},
            {"model_count": 460, "entries": {prv7.PAID_LING_MODEL: {"present": True,
                                                                   "prompt_usd_per_tok": 0.06,
                                                                   "completion_usd_per_tok": "0.18"}}},
            {"model_count": 460, "entries": {prv7.PAID_LING_MODEL: {
                "present": True, "prompt_usd_per_tok": "NaN",
                "completion_usd_per_tok": "0.00000018"}}},
            {"model_count": 460, "entries": {prv7.PAID_LING_MODEL: {
                "present": True, "prompt_usd_per_tok": "0.00000006",
                "completion_usd_per_tok": "-0.1"}}},
        ]

    def test_malformed_catalog_never_raises_and_fails_named_checks(self):
        for payload in self._malformed_catalogs():
            with self.subTest(payload=payload):
                result = self._preflight(check_catalog=True, catalog_document=payload)
                self.assertFalse(result["ok"])
                self.assertIn("live_catalog_gate", result["failed"])

    def test_live_cli_makes_zero_provider_calls_when_catalog_gate_fails(self):
        stdout = io.StringIO()

        def explode(*args, **kwargs):
            raise AssertionError("provider call despite failed catalog gate")

        present = type("C", (), {"present": True, "shape_ok": True,
                                 "redacted": lambda self: {}})()
        with patch.object(run7.catalog, "fetch_model_catalog",
                          return_value=self._malformed_catalogs()[2]), \
                patch.object(jc, "load_jev_credentials", return_value=present), \
                patch.object(run7.bd, "_api_key", return_value="key"), \
                patch.object(writer_v5.urllib.request, "urlopen", side_effect=explode), \
                patch.object(jc.JevChoiceClient, "complete", side_effect=explode), \
                contextlib.redirect_stdout(stdout):
            rc = run7.main(["--repo-root", str(REPO_ROOT), "--live",
                            "--approval", "reviewer-test"])
        self.assertEqual(rc, 2)
        output = stdout.getvalue()
        self.assertIn('"live_catalog_gate"', output)
        self.assertIn('"ok": false', output)

    def test_live_catalog_gate_checks(self):
        good = {"catalog_version": "openrouter-catalog-gate-v1",
                "catalog_url": "https://openrouter.ai/api/v1/models",
                "model_count": 460,
                "entries": {prv7.PAID_LING_MODEL: {"present": True,
                                                   "prompt_usd_per_tok": "0.00000006",
                                                   "completion_usd_per_tok": "0.00000018",
                                                   "context_length": 262144},
                            prv7.PREVIOUS_LING_MODEL: {"present": False}}}
        result = self._preflight(check_catalog=True, catalog_document=good)
        self.assertTrue(result["ok"], result["failed"])
        names = {check["check"] for check in result["checks"]}
        self.assertIn("live_catalog_gate", names)
        self.assertIn("live_catalog_pricing_matches_frozen", names)
        bad = copy.deepcopy(good)
        bad["entries"][prv7.PAID_LING_MODEL] = {"present": False}
        result = self._preflight(check_catalog=True, catalog_document=bad)
        self.assertFalse(result["ok"])
        self.assertIn("live_catalog_gate", result["failed"])
        drifted = copy.deepcopy(good)
        drifted["entries"][prv7.PAID_LING_MODEL]["completion_usd_per_tok"] = "0.00000009"
        result = self._preflight(check_catalog=True, catalog_document=drifted)
        self.assertFalse(result["ok"])
        self.assertIn("live_catalog_pricing_matches_frozen", result["failed"])

    def test_registration_drift_rejected_by_preflight(self):
        mutations = [
            ("model_and_protocol", "ling_model", prv7.PREVIOUS_LING_MODEL,
             "ling_model_is_paid_sku"),
            ("model_and_protocol", "model", "jev-0.0.0", "jev_model_matches"),
            ("model_and_protocol", "protocol_key", "jev-choice-wire-v2|dead",
             "jev_protocol_key"),
            ("treatment", "token_budget", 96, "token_budget_matches"),
            ("treatment", "seed_algorithm", "unseeded", "ling_seed_behavior"),
        ]
        for section, field, value, expected in mutations:
            tampered = copy.deepcopy(REGISTRATION)
            tampered[section][field] = value
            result = self._preflight(registration=tampered)
            with self.subTest(field=field):
                self.assertFalse(result["ok"])
                self.assertIn(expected, result["failed"], result["failed"])

        tampered = copy.deepcopy(REGISTRATION)
        tampered["caps"]["cost_model"]["ling_completion_usd_per_mtok"] = 0.10
        result = self._preflight(registration=tampered)
        self.assertFalse(result["ok"])
        self.assertIn("cost_model_frozen_paid_route", result["failed"])

    def test_runtime_transport_drift_rejected(self):
        receiver = jc2.JevChoiceAdapterV2(FakeReceiverClient(max_physical_requests=107),
                                          model=REGISTRATION["model_and_protocol"]["model"])
        plan, _ = run7.build_coverage_plan(REGISTRATION)
        writer = writer_v5.LingWriterClientV5(api_key=KEY, model=prv7.PAID_LING_MODEL,
                                              max_physical_requests=432,
                                              clock=FakeClock().now, sleep_fn=lambda _: None)
        result = run7.verify_coverage_bridge_preflight(
            plan, REGISTRATION, receiver, writer, repo_root=REPO_ROOT, approval="test",
            check_credentials=False, pinned_hash=PIN, **FRESH)
        self.assertIn("jev_partition_matches", result["failed"])

        writer2 = writer_v5.LingWriterClientV5(api_key=KEY, model=prv7.PAID_LING_MODEL,
                                               max_physical_requests=431,
                                               clock=FakeClock().now, sleep_fn=lambda _: None)
        receiver2 = jc2.JevChoiceAdapterV2(FakeReceiverClient(max_physical_requests=108),
                                           model=REGISTRATION["model_and_protocol"]["model"])
        result = run7.verify_coverage_bridge_preflight(
            plan, REGISTRATION, receiver2, writer2, repo_root=REPO_ROOT, approval="test",
            check_credentials=False, pinned_hash=PIN, **FRESH)
        self.assertIn("ling_partition_matches", result["failed"])

    def test_wrong_manifest_order_and_form_rejected(self):
        tampered = copy.deepcopy(REGISTRATION)
        ids = tampered["manifest"]["instance_ids"]
        ids[0], ids[1] = ids[1], ids[0]
        with self.assertRaises(ValueError):
            run7.build_coverage_plan(tampered)
        plan, _ = run7.build_coverage_plan(REGISTRATION)
        receiver = jc2.JevChoiceAdapterV2(FakeReceiverClient(max_physical_requests=108),
                                          model=REGISTRATION["model_and_protocol"]["model"])
        writer = writer_v5.LingWriterClientV5(api_key=KEY, model=prv7.PAID_LING_MODEL,
                                              max_physical_requests=432,
                                              clock=FakeClock().now, sleep_fn=lambda _: None)
        result = run7.verify_coverage_bridge_preflight(
            plan, tampered, receiver, writer, repo_root=REPO_ROOT, approval="test",
            check_credentials=False, pinned_hash=tampered.get("preregistration_hash"), **FRESH)
        self.assertFalse(result["ok"])
        self.assertIn("manifest_36_exact_order", result["failed"])

        tampered = copy.deepcopy(REGISTRATION)
        form = "0a3349e16c9633b4d559dfbb808d1e50d0446d8f92160a0feddd1e37299796ee"
        tampered["manifest"]["form_membership"][form] = \
            tampered["manifest"]["form_membership"][form][:5]
        with self.assertRaises(ValueError):
            run7.build_coverage_plan(tampered)


class BlockingTests(unittest.TestCase):
    def test_missing_approval_zero_calls_no_files(self):
        report, receiver, writer, *_ = run(owned_side_effect(), approval=None)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["stop_reason"], "missing_approval")
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(writer.physical_attempts, 0)

    def test_failed_preflight_zero_calls(self):
        report, receiver, writer, *_ = run(
            owned_side_effect(), verification={"ok": False, "failed": ["x"], "checks": []})
        self.assertEqual(report["stop_reason"], "preflight_failed")
        self.assertEqual(receiver.client.calls, 0)

    def test_existing_journal_or_report_blocks_and_preserves_bytes(self):
        registration, receiver, writer, plan, instances, verification, se = build(
            owned_side_effect())
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "j.jsonl"
            report_path = Path(directory) / "r.json"
            journal.write_text("SENTINEL-JOURNAL", encoding="utf-8")
            report = run7.execute_coverage_bridge(
                plan, receiver, writer, verification, instances, approval="test",
                registration=registration, pinned_hash=PIN,
                journal_path=journal, report_path=report_path, sleep_fn=lambda _: None)
            self.assertEqual(report["stop_reason"], "output_exists")
            self.assertEqual(journal.read_text(encoding="utf-8"), "SENTINEL-JOURNAL")
            self.assertEqual(receiver.client.calls, 0)
            journal.unlink()
            report_path.write_text("SENTINEL-REPORT", encoding="utf-8")
            report = run7.execute_coverage_bridge(
                plan, receiver, writer, verification, instances, approval="test",
                registration=registration, pinned_hash=PIN,
                journal_path=journal, report_path=report_path, sleep_fn=lambda _: None)
            self.assertEqual(report["stop_reason"], "report_exists")
            self.assertEqual(report_path.read_text(encoding="utf-8"), "SENTINEL-REPORT")

    def test_pinned_hash_and_partition_mismatch_block(self):
        registration, receiver, writer, plan, instances, verification, se = build(
            owned_side_effect())
        report = run7.execute_coverage_bridge(
            plan, receiver, writer, verification, instances, approval="test",
            registration=registration, pinned_hash="0" * 64,
            journal_path=Path(tempfile.mkdtemp()) / "j.jsonl",
            report_path=Path(tempfile.mkdtemp()) / "r.json")
        self.assertEqual(report["stop_reason"], "registration_hash_mismatch")
        writer.max_physical_requests = 431
        report = run7.execute_coverage_bridge(
            plan, receiver, writer, verification, instances, approval="test",
            registration=registration, pinned_hash=PIN,
            journal_path=Path(tempfile.mkdtemp()) / "j.jsonl",
            report_path=Path(tempfile.mkdtemp()) / "r.json")
        self.assertEqual(report["stop_reason"], "writer_partition_not_enforced")
        self.assertEqual(receiver.client.calls, 0)

    def test_cost_model_drift_blocks(self):
        registration, receiver, writer, plan, instances, verification, se = build(
            owned_side_effect())
        tampered = copy.deepcopy(registration)
        tampered["caps"]["cost_model"]["ling_prompt_usd_per_mtok"] = 0.05
        report = run7.execute_coverage_bridge(
            plan, receiver, writer, verification, instances, approval="test",
            registration=tampered, pinned_hash=PIN,
            journal_path=Path(tempfile.mkdtemp()) / "j.jsonl",
            report_path=Path(tempfile.mkdtemp()) / "r.json")
        self.assertEqual(report["stop_reason"], "cost_model_drift")
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(writer.physical_attempts, 0)


class FixedNRunTests(unittest.TestCase):
    def test_full_fixed_n_run_exact_physical_calls_and_tokens(self):
        report, receiver, writer, plan, instances, rows = run(owned_side_effect())
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["attempted_cases"], 36)
        self.assertEqual(report["receiver_valid_cases"], 36)
        self.assertEqual(len(rows), 36)
        self.assertEqual(writer.physical_attempts, 144)
        self.assertEqual(receiver.client.physical_attempts, 36)
        self.assertEqual(report["provider_attempts"]["combined"], 180)
        self.assertEqual(report["tokens_by_provider"],
                         {"ling_input_tokens": 1008, "ling_output_tokens": 432,
                          "jev_input_tokens": 360, "jev_output_tokens": 72})
        self.assertEqual(report["input_tokens"], 1368)
        self.assertEqual(report["estimated_cost_usd"],
                         round((1008 * 0.06 + 432 * 0.18 + 360 * 0.042) / 1_000_000, 12))
        self.assertEqual(report["ling_model"], prv7.PAID_LING_MODEL)
        self.assertEqual(report["cost_model"], prv7.cost_model())

    def test_rows_always_carry_material_correction(self):
        # step 6 regression: writer-failure rows must include it explicitly false
        report, receiver, writer, plan, instances, rows = run(empty_side_effect)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIn("material_correction", row)
        self.assertIs(row["material_correction"], False)
        self.assertIs(row["accepted_b_message_present"], False)
        report2, _, _, _, _, rows2 = run(owned_side_effect())
        for row in rows2:
            self.assertIn("material_correction", row)
            self.assertIs(row["material_correction"], False)

    def test_fixed_n_continues_through_silence_and_rejections(self):
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

        report, receiver, writer, plan, instances, rows = run(mixed)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["attempted_cases"], 36)
        self.assertEqual(writer.physical_attempts, 144)
        self.assertIn("non_owned_claim", report["writer_outcome_totals"])
        self.assertIn("deliberate_silence", report["writer_outcome_totals"])

    def test_eligibility_uses_authoritative_189_selector(self):
        report, receiver, writer, plan, instances, rows = run(owned_side_effect())
        by_id = {instance.instance_id: instance for instance in instances}
        for row in rows:
            expected = audit.select_replay_claims(row, by_id[row["instance_id"]])
            self.assertEqual(row["replay_selection"], expected)
            self.assertEqual(row["eligible_exposure"], row["replay_eligible"])
        self.assertEqual(report["replay_eligible_events"], 36)
        self.assertTrue(report["one_deduplicated_claim_per_pre_read_state"])

    def test_per_form_report_counts(self):
        report, receiver, writer, plan, instances, rows = run(
            b_only_specific_clue_side_effect())
        covered = "3196a8d69f844702db012816def7d7866e7416e9fadc9f28eaa7f12ac16a8569"
        block = report["per_form"][covered]
        self.assertEqual(block["attempted_cases"], 6)
        self.assertEqual(block["receiver_valid_cases"], 6)
        self.assertEqual(block["b_writer_opportunities"], 12)
        self.assertEqual(block["accepted_b_messages"], 12)
        self.assertEqual(block["eligible_b_to_a_events"], 6)
        self.assertEqual(report["forms_with_eligible_exposure"], 1)
        self.assertEqual(len(report["missing_forms"]), 5)

    def test_report_flags_and_no_retention(self):
        report, *_ = run(owned_side_effect())
        self.assertTrue(report["coverage_decision_pending_192"])
        self.assertFalse(report["replay_started"])
        self.assertFalse(report["raw_response_retained"])
        self.assertFalse(report["credentials_retained"])
        self.assertIn("gross", report["i_m_bits_label"])
        dumped = json.dumps(report, sort_keys=True)
        self.assertNotIn(KEY, dumped)
        for row in report["cases"]:
            self.assertFalse(row["raw_response_retained"])
            self.assertFalse(row["credentials_retained"])

    def test_cost_guard_reserves_single_next_call(self):
        tampered = copy.deepcopy(REGISTRATION)
        tampered["caps"]["cost_cap_usd"] = 0.005
        report, receiver, writer, plan, instances, rows = run(
            owned_side_effect(), registration=tampered,
            verification={"ok": True, "checks": [], "failed": []})
        # conservative reserve is 0.00202752 (retry-inclusive, once per logical
        # call): fits under 0.005, while a tripled 0.00608256 would not
        self.assertEqual(prv7.LING_NEXT_CALL_RESERVE_USD, 0.00202752)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["attempted_cases"], 36)
        self.assertEqual(writer.physical_attempts, 144)


class OfflineCliTests(unittest.TestCase):
    def test_offline_cli_makes_zero_provider_calls(self):
        outputs_present = ((REPO_ROOT / prv7.DEFAULT_JOURNAL_V7).exists()
                           or (REPO_ROOT / prv7.DEFAULT_REPORT_V7).exists())
        stdout = io.StringIO()

        def explode(*args, **kwargs):
            raise AssertionError("provider call during offline CLI")

        with patch.object(writer_v5.urllib.request, "urlopen", side_effect=explode), \
                patch.object(jc.JevChoiceClient, "complete", side_effect=explode), \
                contextlib.redirect_stdout(stdout):
            rc = run7.main(["--repo-root", str(REPO_ROOT)])
        if outputs_present:
            self.assertEqual(rc, 2)
        else:
            self.assertEqual(rc, 0)
        self.assertIn('"provider_calls": 0', stdout.getvalue())

    def test_live_without_approval_makes_zero_provider_calls(self):
        stdout = io.StringIO()

        def explode(*args, **kwargs):
            raise AssertionError("provider call without approval")

        with patch.object(writer_v5.urllib.request, "urlopen", side_effect=explode), \
                patch.object(jc.JevChoiceClient, "complete", side_effect=explode), \
                contextlib.redirect_stdout(stdout):
            rc = run7.main(["--repo-root", str(REPO_ROOT), "--live"])
        self.assertEqual(rc, 2)

    def test_cli_has_no_output_path_overrides(self):
        alternate = Path(tempfile.mkdtemp()) / "alt.jsonl"

        def explode(*args, **kwargs):
            raise AssertionError("provider call after alternate-path rejection")

        with patch.object(writer_v5.urllib.request, "urlopen", side_effect=explode), \
                patch.object(jc.JevChoiceClient, "complete", side_effect=explode):
            with self.assertRaises(SystemExit):
                run7.main(["--repo-root", str(REPO_ROOT), "--journal", str(alternate)])
        self.assertFalse(alternate.exists())


if __name__ == "__main__":
    unittest.main()
