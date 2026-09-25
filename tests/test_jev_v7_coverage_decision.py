import copy
import hashlib
import json
import unittest
from pathlib import Path

from apart_incident_response import jev_six_form_coverage_audit as audit
from apart_incident_response import jev_v7_coverage_decision as dec


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = REPO_ROOT / "runs" / "epic-126" / "decisions" / "jev-v7-coverage-decision.json"


def load_artifact() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def load_rows() -> list:
    return [json.loads(line) for line in
            (REPO_ROOT / dec.DEFAULT_JOURNAL).read_text(encoding="utf-8").splitlines()
            if line.strip()]


class InputVerificationTests(unittest.TestCase):
    def test_all_pinned_inputs_verify_on_committed_state(self):
        result = dec.verify_inputs(REPO_ROOT)
        self.assertTrue(result["ok"])
        self.assertEqual(result["failed"], [])
        self.assertEqual(len(result["checks"]), 19)

    def test_pin_values_match_real_files(self):
        for relative, expected in dec.EXPECTED_SHA256.items():
            actual = hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()
            self.assertEqual(actual, expected, relative)
        for relative, expected in dec.HISTORICAL_SHA256.items():
            actual = hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()
            self.assertEqual(actual, expected, relative)

    def test_verify_inputs_fails_closed_on_missing_or_altered_tree(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                dec.verify_inputs(Path(directory))

    def test_report_summary_tamper_detected(self):
        report = {"status": "stopped", "stop_reason": "empty_output",
                  "planned_cases": 36, "attempted_cases": 32,
                  "receiver_valid_cases": 31, "receiver_invalid_cases": 0,
                  "receiver_unattempted_cases": 1}
        self.assertEqual(dec.verify_report_summary(report), [])
        for field, value in (("status", "completed"), ("stop_reason", "cost_cap"),
                             ("planned_cases", 35), ("attempted_cases", 36),
                             ("receiver_valid_cases", 30), ("receiver_invalid_cases", 1),
                             ("receiver_unattempted_cases", 0)):
            tampered = dict(report)
            tampered[field] = value
            errors = dec.verify_report_summary(tampered)
            with self.subTest(field=field):
                self.assertTrue(errors)
                self.assertIn(field, errors[0])

    def test_registration_tamper_detected(self):
        registration = json.loads(
            (REPO_ROOT / dec.DEFAULT_REGISTRATION).read_text(encoding="utf-8"))
        self.assertEqual(dec.verify_registration(registration), [])
        for mutate, expected in (
                (lambda d: d.__setitem__("preregistration_hash", "0" * 64),
                 "content hash"),
                (lambda d: d.__setitem__("status", "draft"),
                 "locked v7"),
                (lambda d: d.__setitem__("live_collection_authorized", True),
                 "not authorize"),
                (lambda d: d["manifest"].__setitem__("manifest_hash", "0" * 64),
                 "manifest hash"),
                (lambda d: d["manifest"].__setitem__("n", 35), "36 instances"),
                (lambda d: d["model_and_protocol"].__setitem__("ling_model",
                                                               "inclusionai/ling-3.0-flash-vl:free"),
                 "ling model")):
            tampered = copy.deepcopy(registration)
            mutate(tampered)
            errors = dec.verify_registration(tampered)
            with self.subTest(expected=expected):
                self.assertTrue(any(expected in error for error in errors), errors)


class ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_artifact()

    def test_byte_reproducible(self):
        self.assertEqual(self.document, dec.build_decision(REPO_ROOT))

    def test_artifact_inputs_are_hash_bound(self):
        recorded = self.document["inputs"]["sha256"]
        self.assertEqual(recorded, dec.EXPECTED_SHA256)
        self.assertEqual(self.document["inputs"]["historical_sha256"],
                         dec.HISTORICAL_SHA256)
        self.assertEqual(self.document["inputs"]["registration_content_hash"],
                         dec.EXPECTED_REGISTRATION_CONTENT_HASH)
        self.assertTrue(self.document["inputs"]["input_verification"]["ok"])
        for relative, expected in recorded.items():
            actual = hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()
            self.assertEqual(actual, expected, relative)

    def test_zero_provider_calls_and_offline_mode(self):
        self.assertEqual(self.document["mode"], "offline-analysis-only")
        self.assertEqual(self.document["provider_calls"], 0)
        source = Path(dec.__file__).read_text(encoding="utf-8")
        for forbidden in ("JevChoiceClient(", "LingWriterClientV5(", "urlopen",
                          "requests.", "http://", "https://"):
            self.assertNotIn(forbidden, source)


class DenominatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_artifact()
        cls.den = cls.document["denominators"]

    def test_core_denominators(self):
        self.assertEqual(self.den["planned_instances"], 36)
        self.assertEqual(self.den["attempted_instances"], 32)
        self.assertEqual(self.den["unattempted_instances"], 4)
        self.assertEqual(sorted(self.den["unattempted_instance_ids"]),
                         ["planning-0001251e", "planning-00012522",
                          "planning-00012524", "planning-00012530"])
        self.assertEqual(self.den["receiver_valid"], 31)
        self.assertEqual(self.den["receiver_invalid"], 0)
        self.assertEqual(self.den["receiver_unattempted"], 1)

    def test_writer_valid_vs_invalid_denominators(self):
        self.assertEqual(self.den["writer_valid_calls"], 124)
        self.assertEqual(self.den["writer_invalid_calls"], 1)
        self.assertEqual(self.den["writer_valid_calls"] + self.den["writer_invalid_calls"], 125)

    def test_eligible_event_denominators(self):
        self.assertEqual(self.den["eligible_replay_events"], 17)
        self.assertEqual(self.den["eligible_claims"], 17)
        self.assertEqual(self.den["distinct_covered_forms"], 6)
        self.assertEqual(self.den["rows_with_accepted_b_message_but_no_eligible_event"], 0)
        self.assertEqual(self.den["recomputed_eligible_rows"], 17)


class WriterValidityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_artifact()
        cls.writer = cls.document["writer_validity"]

    def test_definitions_separate_classifiability_from_correctness(self):
        self.assertIn("NOT correctness", self.writer["definition"]["writer_valid"])
        self.assertIn("deliberate_silence", self.writer["definition"]["writer_valid"])
        self.assertIn("explicitly rejected", self.writer["definition"]["writer_valid"])
        for name in ("empty_output", "truncated_output", "unparsed_output",
                     "invalid_answer", "writer_error"):
            self.assertIn(name, self.writer["definition"]["writer_invalid"])

    def test_counts_and_silence_separation(self):
        self.assertEqual(self.writer["writer_calls_total"], 125)
        self.assertEqual(self.writer["writer_valid_calls"], 124)
        self.assertEqual(self.writer["writer_invalid_calls"], 1)
        self.assertTrue(self.writer["invalid_not_counted_as_silence"])
        totals = self.writer["outcome_totals"]
        self.assertEqual(totals["empty_output"], 1)
        self.assertEqual(totals["deliberate_silence"], 100)
        self.assertEqual(totals["message_candidate"], 24)
        # the invalid row must never be inside the silence count
        self.assertEqual(sum(totals.get(name, 0) for name in dec.INVALID_WRITER_OUTCOMES), 1)
        self.assertEqual(sum(totals.get(name, 0) for name in dec.VALID_WRITER_OUTCOMES), 124)

    def test_terminal_failure_interpretation(self):
        terminal = self.writer["terminal_failure"]
        self.assertEqual(terminal["instance_id"], "planning-0001251d")
        self.assertEqual(terminal["outcome"], "empty_output")
        self.assertEqual(terminal["visible_content"], "empty")
        self.assertEqual(terminal["finish_reason"], "length")
        self.assertEqual(terminal["output_tokens"], 1024)
        self.assertIsNone(terminal["error_class"])
        self.assertTrue(terminal["receiver_unattempted"])
        self.assertEqual(terminal["classification"],
                         "writer-invalid missing data caused by output-budget exhaustion")
        self.assertIn("deliberate silence", terminal["explicitly_not"])
        self.assertIn("an API-key failure", terminal["explicitly_not"])
        self.assertIn("an OpenRouter transport failure", terminal["explicitly_not"])
        self.assertIn("lack of communication", terminal["explicitly_not"])


class EventSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_artifact()
        cls.events = cls.document["events"]
        cls.rows = load_rows()
        cls.registration = json.loads(
            (REPO_ROOT / dec.DEFAULT_REGISTRATION).read_text(encoding="utf-8"))
        cls.instances = dec.regenerate_instances(cls.registration)

    def test_seventeen_events_with_unique_ids(self):
        self.assertEqual(len(self.events), 17)
        ids = [event["event_id"] for event in self.events]
        self.assertEqual(len(set(ids)), 17)
        for event in self.events:
            self.assertIn(":", event["event_id"])
            self.assertEqual(event["selected_claims_in_pre_read_state"], 1)

    def test_every_event_has_full_authoritative_provenance(self):
        protocol = self.registration["model_and_protocol"]["protocol_key"]
        for event in self.events:
            with self.subTest(event=event["event_id"]):
                self.assertEqual(event["writer_id"], "B")
                self.assertEqual(event["reader_id"], "A")
                self.assertEqual(event["i_m_bits"], audit.LOG2_3)
                self.assertGreater(event["i_m_bits"], 0.0)
                self.assertTrue(event["exposure_ids"])
                self.assertTrue(all(str(v).strip() for v in event["exposure_ids"]))
                self.assertTrue(event["receiver_valid"])
                self.assertEqual(event["protocol_key"], protocol)
                self.assertEqual(len(event["request_hash"]), 64)
                self.assertEqual(len(event["state_hash"]), 64)
                self.assertEqual(event["resolved_model"], "jev-1.13.0")
                self.assertIn(event["prompt_form_id"], set(prv6_ids()))

    def test_recompute_reproduces_artifact_events(self):
        recomputation = dec.recompute_event_set(self.rows, self.instances,
                                                self.registration)
        self.assertEqual(recomputation["events"], self.events)
        self.assertEqual(recomputation["present_without_event"], 0)

    def test_per_form_eligible_counts(self):
        counts = self.document["decisions"]["coverage_replay_readiness"]["form_event_counts"]
        self.assertEqual(counts, {
            "0a3349e16c9633b4d559dfbb808d1e50d0446d8f92160a0feddd1e37299796ee": 1,
            "1c1d9f6b5c9271ad8e74de180c3e397e1369d326564c9a08ba0840eff0b148fc": 4,
            "2954f5684bcd198ed8eea0956cf573f93cde628d6dfa7472fc57f556bd089b2c": 4,
            "3196a8d69f844702db012816def7d7866e7416e9fadc9f28eaa7f12ac16a8569": 1,
            "55968fe191b18f37d1951d71f777115f753e0b9a6da526015f3db5251a1383eb": 4,
            "ce847ac53b6e344103bc775aede5212b2be6fbd568dc1d85fd24cbde8f585222": 3,
        })
        self.assertEqual(sum(counts.values()), 17)


def prv6_ids():
    from apart_incident_response import jev_coverage_manifest_preregistration_v6 as prv6
    return prv6.FROZEN_FORM_IDS


class MissingnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_artifact()
        cls.missing = cls.document["missingness_by_form"]

    def test_missingness_by_form_exact(self):
        expected = {
            "0a3349e16c9633b4d559dfbb808d1e50d0446d8f92160a0feddd1e37299796ee":
                (6, 6, [], 6, 0, 1),
            "1c1d9f6b5c9271ad8e74de180c3e397e1369d326564c9a08ba0840eff0b148fc":
                (6, 6, [], 6, 0, 4),
            "2954f5684bcd198ed8eea0956cf573f93cde628d6dfa7472fc57f556bd089b2c":
                (6, 6, [], 5, 1, 4),
            "3196a8d69f844702db012816def7d7866e7416e9fadc9f28eaa7f12ac16a8569":
                (6, 4, ["planning-00012522", "planning-00012524"], 4, 0, 1),
            "55968fe191b18f37d1951d71f777115f753e0b9a6da526015f3db5251a1383eb":
                (6, 6, [], 6, 0, 4),
            "ce847ac53b6e344103bc775aede5212b2be6fbd568dc1d85fd24cbde8f585222":
                (6, 4, ["planning-0001251e", "planning-00012530"], 4, 0, 3),
        }
        self.assertEqual(set(self.missing), set(expected))
        for form, (planned, attempted, not_attempted, valid, unattempted, eligible) \
                in expected.items():
            block = self.missing[form]
            with self.subTest(form=form):
                self.assertEqual(block["planned_instances"], planned)
                self.assertEqual(block["attempted_instances"], attempted)
                self.assertEqual(block["not_attempted_instances"], not_attempted)
                self.assertEqual(block["receiver_valid_instances"], valid)
                self.assertEqual(block["receiver_unattempted_instances"], unattempted)
                self.assertEqual(block["eligible_events"], eligible)
        total_unattempted = sum(len(block["not_attempted_instances"])
                                for block in self.missing.values())
        self.assertEqual(total_unattempted, 4)
        writer_invalid = [iid for block in self.missing.values()
                          for iid in block["writer_invalid_instances"]]
        self.assertEqual(writer_invalid, ["planning-0001251d"])


class AdversarialProvenanceTests(unittest.TestCase):
    """Mutated rows must lose eligibility or fail closed, never silently pass."""

    @classmethod
    def setUpClass(cls):
        cls.rows = load_rows()
        cls.registration = json.loads(
            (REPO_ROOT / dec.DEFAULT_REGISTRATION).read_text(encoding="utf-8"))
        cls.instances = dec.regenerate_instances(cls.registration)
        cls.by_id = {instance.instance_id: instance for instance in cls.instances}
        cls.eligible_row = next(row for row in cls.rows if row["replay_eligible"])

    def _select(self, row):
        return audit.select_replay_claims(row, self.by_id[row["instance_id"]])

    def test_missing_board_write_rejected(self):
        row = copy.deepcopy(self.eligible_row)
        row["board_log"] = [event for event in row["board_log"]
                            if event["kind"] != "board_write"]
        selection = self._select(row)
        self.assertFalse(selection["eligible"])
        reasons = [entry["reason"] for entry in selection["rejected"]]
        self.assertIn("missing_verified_board_write", reasons)

    def test_read_before_write_rejected(self):
        row = copy.deepcopy(self.eligible_row)
        write_seq = next(event["sequence"] for event in row["board_log"]
                         if event["kind"] == "board_write")
        read_event = next(event for event in row["board_log"]
                          if event["kind"] == "peer_read_exposure")
        read_event["sequence"] = write_seq
        selection = self._select(row)
        self.assertFalse(selection["eligible"])
        reasons = [entry["reason"] for entry in selection["rejected"]]
        self.assertIn("read_before_write", reasons)

    def test_blank_exposure_id_rejected(self):
        row = copy.deepcopy(self.eligible_row)
        read_event = next(event for event in row["board_log"]
                          if event["kind"] == "peer_read_exposure")
        read_event["payload"]["exposure_id"] = ""
        selection = self._select(row)
        self.assertFalse(selection["eligible"])
        reasons = [entry["reason"] for entry in selection["rejected"]]
        self.assertIn("missing_exposure_id", reasons)

    def test_rejection_evidence_rejected(self):
        row = copy.deepcopy(self.eligible_row)
        message_id = row["replay_selection"]["selected"][0]["message_id"]
        row["board_log"].append({
            "kind": "board_write_rejected", "message_id": message_id,
            "agent_id": "B", "sequence": 999, "status": "rejected",
            "payload": {"reason": "claim_not_owned_by_writer", "raw_text": "x"}})
        selection = self._select(row)
        self.assertFalse(selection["eligible"])
        reasons = [entry["reason"] for entry in selection["rejected"]]
        self.assertIn("rejected_write_evidence", reasons)

    def test_stored_flag_disagreement_fails_closed(self):
        tampered = copy.deepcopy(self.rows)
        row = next(r for r in tampered if r["replay_eligible"])
        row["replay_eligible"] = False
        with self.assertRaises(ValueError) as caught:
            dec.recompute_event_set(tampered, self.instances, self.registration)
        self.assertIn("disagrees with recomputation", str(caught.exception))

    def test_consistent_receiver_flip_reclassifies_row(self):
        tampered = copy.deepcopy(self.rows)
        row = next(r for r in tampered if r["replay_eligible"]
                   and r["accepted_b_message_present"])
        row["receiver_valid"] = False
        row["replay_eligible"] = False
        row["eligible_exposure"] = False
        result = dec.recompute_event_set(tampered, self.instances, self.registration)
        self.assertEqual(len(result["events"]), 16)
        self.assertEqual(result["present_without_event"], 1)

    def test_stored_selection_drift_fails_closed(self):
        tampered = copy.deepcopy(self.rows)
        row = next(r for r in tampered if r["replay_eligible"])
        row["replay_selection"] = {"eligible": False, "selected": [], "rejected": []}
        with self.assertRaises(ValueError) as caught:
            dec.recompute_event_set(tampered, self.instances, self.registration)
        self.assertIn("stored replay_selection differs", str(caught.exception))


class DecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_artifact()
        cls.decisions = cls.document["decisions"]

    def test_collection_completeness_failed(self):
        collection = self.decisions["collection_completeness"]
        self.assertEqual(collection["result"], "failed")
        self.assertEqual(collection["planned"], 36)
        self.assertEqual(collection["attempted"], 32)
        self.assertIn("registered partial run", collection["statement"])
        self.assertIn("cannot be described as a completed fixed-N sample",
                      collection["statement"])

    def test_six_form_coverage_observed_and_gate_released(self):
        coverage = self.decisions["coverage_replay_readiness"]
        self.assertEqual(coverage["result"], "six_form_coverage_observed")
        self.assertEqual(coverage["covered_forms"], 6)
        self.assertEqual(coverage["k"], 6)
        self.assertEqual(coverage["missing_forms"], [])
        self.assertTrue(coverage["conditional_replay_gate_released"])
        self.assertEqual(coverage["statement"],
                         "Six-form replay coverage passed within a registered partial run; "
                         "fixed-N collection completeness failed.")
        self.assertIn("coverage dimension only", coverage["gate_scope"])
        self.assertIn("#193", coverage["gate_scope"])

    def test_five_form_branch_is_interval_only(self):
        events = _synthetic_events(5)
        coverage = dec.make_decisions([], {}, events, {})["coverage_replay_readiness"]
        self.assertEqual(coverage["result"], "five_form_coverage_interval_only")
        self.assertFalse(coverage["conditional_replay_gate_released"])
        self.assertIn("interval-only descriptive", coverage["statement"])
        self.assertIn("below 0.05 is explicitly forbidden", coverage["statement"])

    def test_fewer_than_five_forms_fails(self):
        events = _synthetic_events(3)
        coverage = dec.make_decisions([], {}, events, {})["coverage_replay_readiness"]
        self.assertEqual(coverage["result"], "inducement_coverage_failure")
        self.assertFalse(coverage["conditional_replay_gate_released"])
        self.assertIn("inducement/coverage failure", coverage["statement"])


def _synthetic_events(count):
    forms = sorted(prv6_ids())
    events = []
    for index in range(count):
        events.append({"prompt_form_id": forms[index % 6],
                       "instance_id": f"synthetic-{index}",
                       "i_m_bits": audit.LOG2_3})
    return events


class InformationAccountingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.accounting = load_artifact()["information_accounting"]

    def test_gross_and_eligible_totals(self):
        self.assertEqual(self.accounting["gross_transmitted_all_messages"]["records"], 24)
        self.assertAlmostEqual(self.accounting["gross_transmitted_all_messages"]["i_m_bits"],
                               38.039100017307724)
        self.assertEqual(self.accounting["gross_b_to_a"]["records"], 19)
        self.assertAlmostEqual(self.accounting["gross_b_to_a"]["i_m_bits"], 19 * audit.LOG2_3)
        self.assertEqual(self.accounting["gross_a_to_b"]["records"], 5)
        self.assertAlmostEqual(self.accounting["gross_a_to_b"]["i_m_bits"], 5 * audit.LOG2_3)
        eligible = self.accounting["replay_eligible_event_claims"]
        self.assertEqual((eligible["events"], eligible["claims"]), (17, 17))
        self.assertAlmostEqual(eligible["i_m_bits"], 17 * audit.LOG2_3)
        distinct = self.accounting["distinct_form_claim_treatments"]
        self.assertEqual(distinct["count"], 6)
        self.assertAlmostEqual(distinct["i_m_bits"], 6 * audit.LOG2_3)

    def test_gross_never_labeled_unique_and_only_b_to_a(self):
        self.assertIn("never unique information delivered",
                      self.accounting["label_rule"])
        self.assertIn("must never be described as unique information delivered",
                      self.accounting["gross_is_not_unique_note"])
        self.assertEqual(self.accounting["primary_replay_set_direction"], "B->A only")
        self.assertTrue(self.accounting["primary_replay_set_direction_verified"])


class ExperimentalUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.unit = load_artifact()["experimental_unit"]

    def test_unit_and_k(self):
        self.assertEqual(self.unit["unit"], "prompt form")
        self.assertEqual(self.unit["k"], 6)
        self.assertEqual(self.unit["events"], 17)
        self.assertIn("replicates", self.unit["note"])
        self.assertIn("not 17 independent states", self.unit["note"])

    def test_prohibited_analyses_not_performed(self):
        prohibited = " | ".join(self.unit["prohibited_and_not_performed"])
        for item in ("instance-level t-test", "instance-level Wilcoxon",
                     "independence-assuming", "real/placebo/null replay inference",
                     "causal uptake effect"):
            self.assertIn(item, prohibited)

    def test_claim_scope_limits(self):
        document = load_artifact()
        scope = " | ".join(document["claim_scope"])
        self.assertIn("registered partial run", scope)
        self.assertIn("must not be pooled with free-route behavioral rates", scope)
        self.assertIn("never unique information delivered", scope)
        self.assertIn("no causal", scope)


class SelectionPolicyTests(unittest.TestCase):
    def test_policy_shape(self):
        policy = dec.selection_policy()
        self.assertEqual(policy["policy_version"],
                         "jev-six-form-coverage-audit-v1::select_replay_claims")
        self.assertEqual(policy["selector_source_sha256"],
                         dec.EXPECTED_SHA256[dec.SELECTOR_MODULE])
        self.assertEqual(len(policy["eligibility_conditions"]), 17)
        self.assertEqual(policy["direction"], "one-way B->A")
        self.assertEqual(policy["valid_writer_outcomes"],
                         sorted(dec.VALID_WRITER_OUTCOMES))
        self.assertEqual(policy["invalid_writer_outcomes"],
                         sorted(dec.INVALID_WRITER_OUTCOMES))
        self.assertEqual(set(policy["invalid_writer_outcomes"]),
                         {"empty_output", "truncated_output", "unparsed_output",
                          "invalid_answer", "writer_error"})

    def test_writer_outcome_sets_mirror_runner_stop_rules(self):
        from apart_incident_response import jev_writer_exact_bridge_v5 as bridge
        self.assertEqual(set(dec.INVALID_WRITER_OUTCOMES),
                         set(bridge.STOP_WRITER_OUTCOMES))


if __name__ == "__main__":
    unittest.main()
