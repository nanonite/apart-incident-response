import json
import math
import shutil
import tempfile
import unittest
from pathlib import Path

from apart_incident_response import jev_replay_inference as ji
from apart_incident_response import jev_replay_preregistration as pr
from apart_incident_response import jev_six_form_coverage_audit as audit
from apart_incident_response.communication_events import CommunicationEventLog
from apart_incident_response.jev_choice_pilot import pilot_instances


REPO_ROOT = Path(__file__).resolve().parents[1]
JOURNAL = REPO_ROOT / "runs" / "epic-126" / "jev-writer-exact-bridge-v5.jsonl"
ARTIFACT = REPO_ROOT / "runs" / "epic-126" / "jev-six-form-coverage-audit-v1.json"

FROZEN_FORM_IDS = {
    "0a3349e16c9633b4d559dfbb808d1e50d0446d8f92160a0feddd1e37299796ee",
    "1c1d9f6b5c9271ad8e74de180c3e397e1369d326564c9a08ba0840eff0b148fc",
    "2954f5684bcd198ed8eea0956cf573f93cde628d6dfa7472fc57f556bd089b2c",
    "3196a8d69f844702db012816def7d7866e7416e9fadc9f28eaa7f12ac16a8569",
    "55968fe191b18f37d1951d71f777115f753e0b9a6da526015f3db5251a1383eb",
    "ce847ac53b6e344103bc775aede5212b2be6fbd568dc1d85fd24cbde8f585222",
}

UNCOVERED_FORM_ID = "55968fe191b18f37d1951d71f777115f753e0b9a6da526015f3db5251a1383eb"

EXPECTED_FORM_TABLE = {
    "0a3349e16c9633b4d559dfbb808d1e50d0446d8f92160a0feddd1e37299796ee": {
        "b_clue": "precedes=inspect>deploy", "instances": 4, "b_opportunities": 8,
        "accepted_b": 4, "accepted_a": 0, "eligible": 3,
        "instance_ids": ["planning-00011944", "planning-00011948", "planning-0001194c",
                         "planning-0001194f"],
    },
    "1c1d9f6b5c9271ad8e74de180c3e397e1369d326564c9a08ba0840eff0b148fc": {
        "b_clue": "precedes=stage>deploy", "instances": 3, "b_opportunities": 6,
        "accepted_b": 2, "accepted_a": 0, "eligible": 2,
        "instance_ids": ["planning-00011947", "planning-0001194b", "planning-0001194d"],
    },
    "2954f5684bcd198ed8eea0956cf573f93cde628d6dfa7472fc57f556bd089b2c": {
        "b_clue": "precedes=stage>inspect", "instances": 1, "b_opportunities": 2,
        "accepted_b": 2, "accepted_a": 0, "eligible": 1,
        "instance_ids": ["planning-00011950"],
    },
    "3196a8d69f844702db012816def7d7866e7416e9fadc9f28eaa7f12ac16a8569": {
        "b_clue": "precedes=deploy>stage", "instances": 3, "b_opportunities": 6,
        "accepted_b": 1, "accepted_a": 1, "eligible": 1,
        "instance_ids": ["planning-00011940", "planning-00011942", "planning-00011946"],
    },
    "55968fe191b18f37d1951d71f777115f753e0b9a6da526015f3db5251a1383eb": {
        "b_clue": "precedes=inspect>stage", "instances": 3, "b_opportunities": 6,
        "accepted_b": 0, "accepted_a": 1, "eligible": 0,
        "instance_ids": ["planning-00011949", "planning-0001194a", "planning-0001194e"],
    },
    "ce847ac53b6e344103bc775aede5212b2be6fbd568dc1d85fd24cbde8f585222": {
        "b_clue": "precedes=deploy>inspect", "instances": 3, "b_opportunities": 6,
        "accepted_b": 3, "accepted_a": 0, "eligible": 2,
        "instance_ids": ["planning-00011941", "planning-00011943", "planning-00011945"],
    },
}


def journal_cases():
    return audit.load_journal(JOURNAL)


def instances_by_id():
    return {instance.instance_id: instance for instance in pilot_instances()}


def case_map():
    return {str(case["instance_id"]): case for case in journal_cases()}


def build_selections():
    cases = journal_cases()
    by_id = instances_by_id()
    return {str(case["instance_id"]): audit.select_replay_claims(case, by_id[str(case["instance_id"])])
            for case in cases}


def craft_case(messages, *, instance):
    """Build a synthetic journal case with board rows and provenance events."""

    log = CommunicationEventLog("craft-run", clock=lambda: 1)
    board = []
    for index, message in enumerate(messages):
        message_id = message.get("message_id", f"message-craft-{index}")
        info = instance.information(message.get("reader", "A"), message["text"], message_id)
        if message.get("write", True):
            log.board_write(message["author"], info, message_tokens=1,
                            receiver_id=message.get("reader", "A"))
        if message.get("expose"):
            reader = message.get("reader", "A")
            log.peer_read(reader, info, exposure_id=message.get("exposure_id", "craft-exposure"))
        board.append({
            "message_id": message_id, "author": message["author"],
            "receiver": message.get("row_receiver", message.get("reader", "A")),
            "text": message["text"], "status": message.get("status", "accepted"),
            "delta_i_bits": info.delta_i_bits, "message_tokens": 1,
        })
    return {
        "instance_id": instance.instance_id, "board": board,
        "board_log": [event.to_dict() for event in log.events],
        "writer_outcomes": [], "receiver_valid": True, "receiver_attempted": True,
    }


class _StubInfo:
    def __init__(self, message_id, status, delta, raw_text):
        self.message_id = message_id
        self.status = status
        self.delta_i_bits = delta
        self.raw_text = raw_text
        self.normalized_claim = raw_text
        self.before_count = 3
        self.after_count = 1 if delta else 3
        self.reason = None

    @property
    def useful(self):
        return self.status == "accepted" and bool(self.delta_i_bits)


class _StubInstance:
    """Duck-typed instance for ownership / I_m=0 / multi-claim rule tests."""

    def __init__(self, *, instance_id="stub-1", receiver_clues=("known-claim",),
                 owned=("owned-claim", "owned-claim-2"),
                 info_map=None):
        self.instance_id = instance_id
        self.private_clues = {"A": tuple(receiver_clues), "B": tuple(owned)}
        self._owned = set(owned)
        self._info_map = info_map or {}

    def holds_claim(self, agent, raw_text):
        return agent == "B" and raw_text in self._owned

    def information(self, agent, raw_text, message_id):
        status, delta = self._info_map.get(raw_text, ("accepted", audit.LOG2_3))
        return _StubInfo(message_id, status, delta, raw_text)


def stub_case(texts, *, reader="A", write=True, expose=True, author="B"):
    log = CommunicationEventLog("stub-run", clock=lambda: 1)
    board = []
    for index, text in enumerate(texts):
        message_id = f"message-stub-{index}"
        info = _StubInfo(message_id, "accepted", audit.LOG2_3, text)
        if write:
            log.board_write(author, info, message_tokens=1, receiver_id=reader)
        if expose:
            log.peer_read(reader, info, exposure_id="stub-exposure")
        board.append({"message_id": message_id, "author": author, "receiver": reader,
                      "text": text, "status": "accepted",
                      "delta_i_bits": info.delta_i_bits, "message_tokens": 1})
    return {"instance_id": "stub-1", "board": board,
            "board_log": [event.to_dict() for event in log.events],
            "writer_outcomes": [], "receiver_valid": True, "receiver_attempted": True}


class InputIntegrityTests(unittest.TestCase):
    def test_pinned_inputs_verify(self):
        result = audit.verify_pinned_inputs(REPO_ROOT)
        self.assertTrue(result["ok"])
        self.assertFalse(result["inputs_modified_by_audit"])
        self.assertTrue(all(row["ok"] for row in result["inputs"]))

    def test_pinned_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / audit.DEFAULT_JOURNAL_REL).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(JOURNAL, root / audit.DEFAULT_JOURNAL_REL)
            report = REPO_ROOT / audit.DEFAULT_REPORT_REL
            shutil.copy(report, root / audit.DEFAULT_REPORT_REL)
            tampered = root / audit.DEFAULT_JOURNAL_REL
            tampered.write_text(tampered.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                audit.verify_pinned_inputs(root)

    def test_build_audit_crosscheck_and_reproducibility(self):
        first = audit.build_audit(REPO_ROOT)
        second = audit.build_audit(REPO_ROOT)
        self.assertEqual(first, second)
        self.assertTrue(first["report_crosscheck"]["ok"])
        self.assertEqual(first["report_crosscheck"]["failed"], [])
        self.assertEqual(first["provider_calls"], 0)
        self.assertEqual(first["inputs"]["journal"]["write_attempts_by_audit"], 0)
        self.assertEqual(first["inputs"]["report"]["write_attempts_by_audit"], 0)
        self.assertEqual(first["prior_artifacts_modified"], [])
        committed = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        self.assertEqual(committed, first)


class CoverageFactsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = audit.build_audit(REPO_ROOT)
        cls.facts = cls.audit["coverage_facts"]

    def test_receiver_validity_17_of_17(self):
        self.assertEqual(self.facts["cases_total"], 17)
        self.assertEqual(self.facts["receiver_valid_cases"], 17)
        self.assertEqual(self.facts["receiver_invalid_cases"], 0)
        self.assertEqual(self.facts["receiver_unattempted_cases"], 0)
        self.assertTrue(self.facts["all_receiver_cases_valid"])

    def test_accepted_messages_a2_b12(self):
        self.assertEqual(self.facts["accepted_messages"]["total"], 14)
        self.assertEqual(self.facts["accepted_messages"]["by_author"], {"A": 2, "B": 12})

    def test_authoritative_records_and_read_exposures(self):
        self.assertEqual(self.facts["authoritative_information_records"], 14)
        self.assertEqual(self.facts["verified_read_exposures"], 14)

    def test_eligible_cases_9_of_17(self):
        self.assertEqual(self.facts["eligible_b_to_a_cases"], 9)
        self.assertAlmostEqual(self.facts["eligible_b_to_a_rate"], 9 / 17)

    def test_six_forms_five_covered_uncovered_identified(self):
        self.assertEqual(self.facts["distinct_pre_read_prompt_forms"], 6)
        self.assertEqual(self.facts["forms_with_eligible_exposure"], 5)
        self.assertTrue(self.facts["exactly_five_of_six_forms_covered"])
        self.assertEqual(self.facts["uncovered_form_id"], UNCOVERED_FORM_ID)

    def test_no_forbidden_writer_output_affected_result(self):
        self.assertEqual(self.facts["forbidden_writer_outcomes"], [])
        self.assertFalse(self.facts["invalid_writer_output_affected_result"])
        census = self.audit["writer_outcome_census"]
        self.assertEqual(census["forbidden_outcome_count"], 0)
        self.assertEqual(set(census["totals_by_outcome"]),
                         {"deliberate_silence", "message_candidate", "non_owned_claim"})

    def test_writer_outcome_census_flags_forbidden_outcomes(self):
        cases = [{"writer_outcomes": [{"agent": "B", "turn": 0, "outcome": "empty_output"}]}]
        census = audit.writer_outcome_census(cases)
        self.assertEqual(census["forbidden_outcomes_present"], ["empty_output"])
        self.assertTrue(census["forbidden_writer_output_affected_result"])


class FormAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = audit.build_audit(REPO_ROOT)
        cls.forms = {row["prompt_form_id"]: row for row in cls.audit["forms"]}

    def test_exact_six_form_membership(self):
        self.assertEqual(set(self.forms), FROZEN_FORM_IDS)
        self.assertEqual(set(self.forms), set(pr.frozen_forms()["iso_form_ids"]))
        for form_id, expected in EXPECTED_FORM_TABLE.items():
            self.assertEqual(self.forms[form_id]["instance_ids"], expected["instance_ids"])

    def test_per_form_counts(self):
        for form_id, expected in EXPECTED_FORM_TABLE.items():
            row = self.forms[form_id]
            with self.subTest(form=form_id):
                self.assertEqual(row["b_owned_clue"], expected["b_clue"])
                self.assertEqual(row["instance_count"], expected["instances"])
                self.assertEqual(row["b_writer_opportunities"], expected["b_opportunities"])
                self.assertEqual(row["accepted_b_messages"], expected["accepted_b"])
                self.assertEqual(row["accepted_a_messages"], expected["accepted_a"])
                self.assertEqual(row["eligible_b_to_a_exposures"], expected["eligible"])
                self.assertEqual(row["covered"], expected["eligible"] > 0)

    def test_form_totals_match_coverage_facts(self):
        self.assertEqual(sum(row["instance_count"] for row in self.forms.values()), 17)
        self.assertEqual(sum(row["b_writer_opportunities"] for row in self.forms.values()), 34)
        self.assertEqual(sum(row["accepted_b_messages"] for row in self.forms.values()), 12)
        self.assertEqual(sum(row["accepted_a_messages"] for row in self.forms.values()), 2)
        self.assertEqual(sum(row["eligible_b_to_a_exposures"] for row in self.forms.values()), 9)

    def test_uncovered_form_record(self):
        uncovered = self.audit["uncovered_form"]
        self.assertEqual(uncovered["prompt_form_id"], UNCOVERED_FORM_ID)
        self.assertEqual(uncovered["b_owned_clue"], "precedes=inspect>stage")
        self.assertEqual(uncovered["accepted_b_messages"], 0)
        self.assertEqual(uncovered["eligible_b_to_a_exposures"], 0)
        self.assertEqual(uncovered["b_writer_opportunities"], 6)
        self.assertTrue(uncovered["geometry_equivalent_to_covered_forms"])
        self.assertIn("writer/seed coverage event", uncovered["classification"])
        self.assertIn("does not prove", uncovered["not_proven"])

    def test_form_clue_bijection_and_log2_3_bits(self):
        geometry = self.audit["information_geometry"]
        self.assertTrue(geometry["form_to_b_clue_bijective"])
        self.assertEqual(geometry["distinct_forms"], 6)
        self.assertEqual(geometry["distinct_b_clues"], 6)
        self.assertTrue(geometry["each_b_clue_carries_log2_3_bits"])
        self.assertAlmostEqual(geometry["expected_bits"], math.log2(3))
        self.assertTrue(geometry["geometry_equivalent_across_forms"])
        for row in self.forms.values():
            info = row["authoritative_information"]
            self.assertAlmostEqual(info["i_m_bits"], math.log2(3))
            self.assertEqual(info["status"], "accepted")
            self.assertEqual(info["receiver_feasible_before"], 3)
            self.assertEqual(info["receiver_feasible_after"], 1)


class SelectionRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.by_id = instances_by_id()
        cls.cases = case_map()

    def test_real_eligible_case_selects_single_b_claim(self):
        case = self.cases["planning-00011940"]
        selection = audit.select_replay_claims(case, self.by_id["planning-00011940"])
        self.assertTrue(selection["eligible"])
        self.assertEqual(len(selection["selected"]), 1)
        chosen = selection["selected"][0]
        self.assertEqual(chosen["claim"], "precedes=deploy>stage")
        self.assertEqual(chosen["writer_id"], "B")
        self.assertAlmostEqual(chosen["i_m_bits"], math.log2(3))
        self.assertTrue(chosen["exposure_ids"])

    def test_b_to_a_only_filtering_rejects_a_to_b(self):
        case = self.cases["planning-00011942"]
        selection = audit.select_replay_claims(case, self.by_id["planning-00011942"])
        self.assertFalse(selection["eligible"])
        self.assertEqual(selection["selected"], [])
        self.assertEqual([row["reason"] for row in selection["rejected"]],
                         ["direction_not_b_to_a"])
        self.assertEqual(selection["rejected"][0]["claim"], "precedes=inspect>deploy")

    def test_receiver_known_and_zero_i_m_claim_rejected(self):
        instance = self.by_id["planning-00011940"]
        receiver_known = list(instance.private_clues["A"])[0]
        case = craft_case([{"author": "B", "text": receiver_known, "expose": True}],
                          instance=instance)
        selection = audit.select_replay_claims(case, instance)
        self.assertFalse(selection["eligible"])
        self.assertEqual(selection["rejected"][0]["reason"], "receiver_known_claim")

        stub = _StubInstance(info_map={"zero-claim": ("accepted", 0.0)})
        zero_case = stub_case(["zero-claim"])
        zero_selection = audit.select_replay_claims(zero_case, stub)
        self.assertFalse(zero_selection["eligible"])
        self.assertEqual(zero_selection["rejected"][0]["reason"], "zero_or_uninformative_claim")

    def test_unowned_informative_claim_rejected(self):
        stub = _StubInstance(owned=("owned-claim",), info_map={})
        case = stub_case(["not-owned-claim"])
        selection = audit.select_replay_claims(case, stub)
        self.assertFalse(selection["eligible"])
        self.assertEqual(selection["rejected"][0]["reason"], "claim_not_owned_by_writer")

    def test_deduplication_and_one_event_selection_rule(self):
        case = self.cases["planning-00011943"]
        selection = audit.select_replay_claims(case, self.by_id["planning-00011943"])
        self.assertEqual(len(selection["selected"]), 1)
        duplicates = [row for row in selection["rejected"]
                      if row["reason"] == "duplicate_claim_within_event"]
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]["claim"], selection["selected"][0]["claim"])

        stub = _StubInstance(owned=("owned-claim", "owned-claim-2"))
        two_claim_case = stub_case(["owned-claim", "owned-claim-2"])
        two_selection = audit.select_replay_claims(two_claim_case, stub)
        self.assertEqual(len(two_selection["selected"]), 1)
        self.assertEqual(two_selection["selected"][0]["claim"], "owned-claim")
        self.assertEqual([row["reason"] for row in two_selection["rejected"]],
                         ["second_claim_same_pre_read_state"])

    def test_verified_write_and_read_provenance_required(self):
        instance = self.by_id["planning-00011940"]
        b_clue = list(instance.private_clues["B"])[0]
        missing_read = craft_case([{"author": "B", "text": b_clue, "expose": False}],
                                  instance=instance)
        selection = audit.select_replay_claims(missing_read, instance)
        self.assertFalse(selection["eligible"])
        self.assertEqual(selection["rejected"][0]["reason"], "missing_verified_read_exposure")

        missing_write = craft_case([{"author": "B", "text": b_clue, "write": False,
                                     "expose": True}], instance=instance)
        selection = audit.select_replay_claims(missing_write, instance)
        self.assertFalse(selection["eligible"])
        self.assertEqual(selection["rejected"][0]["reason"], "missing_verified_board_write")

        not_accepted = craft_case([{"author": "B", "text": b_clue, "status": "rejected",
                                    "expose": True}], instance=instance)
        selection = audit.select_replay_claims(not_accepted, instance)
        self.assertFalse(selection["eligible"])
        self.assertEqual(selection["rejected"][0]["reason"], "write_not_accepted")

    def test_selections_recompute_to_frozen_eligibility(self):
        selections = build_selections()
        cases = journal_cases()
        recomputed = sum(1 for case in cases
                         if audit._case_is_eligible(case, selections[str(case["instance_id"])]))
        journal_flag = sum(1 for case in cases if case.get("eligible_exposure"))
        self.assertEqual(recomputed, 9)
        self.assertEqual(recomputed, journal_flag)


class InformationAccountingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = audit.build_audit(REPO_ROOT)
        cls.accounting = cls.audit["information_accounting"]

    def test_gross_report_is_not_unique_information(self):
        gross = self.accounting["gross_reported"]
        self.assertEqual(gross["authoritative_records"], 14)
        self.assertEqual(gross["i_m_bits"], 22.18947501)
        self.assertIn("NOT unique information", gross["warning"])

    def test_a_to_b_writes_excluded_and_b_to_a_gross(self):
        by_direction = self.accounting["by_direction"]
        self.assertEqual(by_direction["b_to_a"]["messages"], 12)
        self.assertAlmostEqual(by_direction["b_to_a"]["i_m_bits"], 12 * math.log2(3))
        self.assertEqual(by_direction["a_to_b_excluded"]["messages"], 2)
        self.assertAlmostEqual(by_direction["a_to_b_excluded"]["i_m_bits"], 2 * math.log2(3))
        self.assertEqual(self.accounting["primary_replay_direction"], "one-way B->A")

    def test_replay_eligible_after_dedup_and_one_claim_rule(self):
        eligible = self.accounting["replay_eligible"]
        self.assertEqual(eligible["events"], 9)
        self.assertEqual(eligible["claims"], 9)
        self.assertAlmostEqual(eligible["i_m_bits"], 9 * math.log2(3))
        self.assertEqual(eligible["distinct_form_claims"], 5)
        self.assertAlmostEqual(eligible["distinct_form_claim_i_m_bits"], 5 * math.log2(3))
        self.assertEqual(self.accounting["b_to_a_duplicates_removed"]["messages"], 3)
        self.assertAlmostEqual(self.accounting["b_to_a_duplicates_removed"]["i_m_bits"],
                               3 * math.log2(3))

    def test_no_agent_symmetry_claim(self):
        self.assertIn("no symmetry across agents", self.accounting["rules"][-1])
        self.assertIn("not mirrored", self.accounting["rules"][-1])
        self.assertIn("mirrors the B->A estimand", self.accounting["no_agent_symmetry_claim"])


class EstimandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.estimand = audit.build_audit(REPO_ROOT)["estimand"]

    def test_experimental_unit_is_prompt_form_not_instance(self):
        self.assertIn("prompt form", self.estimand["experimental_unit"])
        self.assertIn("not the instance ID", self.estimand["experimental_unit"])

    def test_branch_definitions_and_contrasts(self):
        self.assertEqual(self.estimand["branches"]["H_real"], "H(Y | C, M_real)")
        self.assertEqual(self.estimand["branches"]["H_placebo"], "H(Y | C, M_placebo)")
        self.assertEqual(self.estimand["branches"]["H_null"], "H(Y | C)")
        self.assertIn("d_i = H_real - H_placebo", self.estimand["event_contrast"])
        self.assertIn("mean(d_i)", self.estimand["form_contrast"])
        self.assertEqual(self.estimand["primary_estimand"],
                         "equal-weight mean of d_f across the six forms")

    def test_null_branch_retained_and_guards_do_not_filter(self):
        self.assertIn("manipulation checks", self.estimand["null_branch"])
        self.assertIn("cancels", self.estimand["null_branch"])
        self.assertIn("must not filter", self.estimand["guards"])

    def test_missingness_and_claim_limits(self):
        self.assertIn("not imputed", self.estimand["missingness"])
        self.assertIn("by form", self.estimand["missingness"])
        self.assertIn("instance-weighted analyses are secondary only",
                      self.estimand["claim_limits"])
        self.assertIn("no instance-level t-test or Wilcoxon as primary",
                      self.estimand["claim_limits"])


class InferenceLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.limits = audit.build_audit(REPO_ROOT)["inference_limits"]

    def test_k6_sign_flip_floor(self):
        floor = self.limits["sign_flip_floor"]["k_6"]
        self.assertEqual(floor["permutations"], 64)
        self.assertEqual(floor["expression"], "2/64")
        self.assertEqual(floor["min_two_sided_p"], 0.03125)
        self.assertEqual(floor["exact_min_p"], 2 / 64)
        direct = ji.sign_flip_two_sided([-1.0] * 6)
        self.assertAlmostEqual(direct["min_p_value"], 2 / 64)

    def test_k5_sign_flip_floor_blocks_alpha_0_05(self):
        floor = self.limits["sign_flip_floor"]["k_5"]
        self.assertEqual(floor["permutations"], 32)
        self.assertEqual(floor["expression"], "2/32")
        self.assertEqual(floor["min_two_sided_p"], 0.0625)
        self.assertEqual(floor["exact_min_p"], 2 / 32)
        self.assertGreater(floor["min_two_sided_p"], 0.05)
        five_form_rule = self.limits["sign_flip_floor"]["five_form_rule"]
        self.assertIn("interval-only and descriptive", five_form_rule)
        self.assertIn("2/32 = 0.0625", five_form_rule)
        direct = ji.sign_flip_two_sided([-1.0] * 5)
        self.assertAlmostEqual(direct["min_p_value"], 2 / 32)

    def test_primary_interval_test_and_secondary_rules(self):
        self.assertEqual(self.limits["primary_test"],
                         "exact two-sided cluster sign-flip test on form means")
        self.assertEqual(self.limits["interval"], "form-mean t interval with df = k - 1")
        self.assertEqual(self.limits["secondary_only"], ["instance-weighted analyses"])
        self.assertIn("instance-level t-test", self.limits["not_primary"])
        self.assertIn("instance-level Wilcoxon", self.limits["not_primary"])
        self.assertIn("not imputed", self.limits["missingness_rule"])
        self.assertIn("never filter", self.limits["guards_rule"])
        self.assertIn("cannot increase k", self.limits["form_space_limit"])


class SensitivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sensitivity = audit.build_audit(REPO_ROOT)["sensitivity"]

    def test_reproduces_approximately_0_203_bit_half_width(self):
        expected = ji.t_critical_975(5) * 0.1933 / math.sqrt(6)
        self.assertEqual(self.sensitivity["t_critical_975"], 2.571)
        self.assertEqual(self.sensitivity["expression"], "t(0.975,5) * 0.1933 / sqrt(6)")
        self.assertAlmostEqual(self.sensitivity["half_width_bits"], expected, places=12)
        self.assertEqual(self.sensitivity["half_width_rounded_bits"], 0.203)
        self.assertAlmostEqual(self.sensitivity["half_width_bits"], 0.203, delta=0.001)

    def test_illustrative_sd_recomputed_and_interpretation_frozen(self):
        self.assertEqual(self.sensitivity["illustrative_between_form_sd_bits"], 0.1933)
        self.assertAlmostEqual(self.sensitivity["illustrative_sd_recomputed_bits"], 0.1933,
                               delta=0.0005)
        self.assertIn("planning/sensitivity context",
                      self.sensitivity["interpretation"])
        self.assertIn("cannot rule out effects smaller than roughly 0.2 bits",
                      self.sensitivity["interpretation"])
        self.assertIn("cannot increase k", self.sensitivity["form_space_note"])


class FreshCoverageSizingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.handoff = audit.build_audit(REPO_ROOT)["fresh_coverage_handoff"]

    def test_observed_rate_and_n36_target(self):
        rate = self.handoff["observed_eligible_instance_rate"]
        self.assertEqual(rate["numerator"], 9)
        self.assertEqual(rate["denominator"], 17)
        self.assertAlmostEqual(rate["value"], 9 / 17)
        self.assertEqual(rate["rounded"], 0.529)
        self.assertEqual(self.handoff["target"], {"fresh_instances_per_form": 6, "forms": 6,
                                                  "N": 36})

    def test_per_form_and_all_forms_probabilities(self):
        rate = 9 / 17
        expected_per_form = 1 - (1 - rate) ** 6
        expected_all = expected_per_form ** 6
        per_form = self.handoff["probability_one_form_has_at_least_one"]
        all_forms = self.handoff["probability_all_forms_have_at_least_one"]
        self.assertEqual(per_form["expression"], "1 - (1 - 9/17)^6")
        self.assertAlmostEqual(per_form["value"], expected_per_form, places=12)
        self.assertEqual(all_forms["expression"], "[1 - (1 - 9/17)^6]^6")
        self.assertAlmostEqual(all_forms["value"], expected_all, places=12)
        self.assertEqual(all_forms["rounded"], 0.937)
        self.assertAlmostEqual(all_forms["value"], 0.937, delta=0.001)

    def test_assumption_and_requirements_documented_not_implemented(self):
        self.assertIn("not evidence", self.handoff["assumption"])
        self.assertEqual(self.handoff["handoff_to"], "#190")
        self.assertIn("does not implement #190", self.handoff["status"])
        joined = " ".join(self.handoff["requirements"])
        self.assertIn("new registration and manifest", joined)
        self.assertIn("do not append to the frozen 17-instance artifact", joined)
        self.assertIn("form identity is deterministic", joined)
        self.assertIn("fixed N with no stopping after the first message", joined)


if __name__ == "__main__":
    unittest.main()
