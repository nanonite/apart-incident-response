import json
import unittest
from pathlib import Path

from apart_incident_response import jev_replay as jr
from apart_incident_response import jev_replay_inference as ji
from apart_incident_response.jev_choice import JEV_CHOICE_INSTRUCTIONS, JEV_DEFAULT_MODEL, jev_choice_protocol_key


REPO_ROOT = Path(__file__).resolve().parents[1]
JOURNAL = REPO_ROOT / "runs" / "epic-126" / "jev-choice-capability.jsonl"
PROTOCOL_KEY = jev_choice_protocol_key()
OPTIONS = [f"c{i}" for i in range(6)]
TARGET = "c0"
FEASIBLE = ["c0", "c1", "c2"]


def one_hot(target=TARGET):
    return {option: (1.0 if option == target else 0.0) for option in OPTIONS}


def spread(target=TARGET, p=0.5):
    others = [option for option in OPTIONS if option != target]
    remainder = (1.0 - p) / len(others)
    probabilities = {option: remainder for option in OPTIONS}
    probabilities[target] = p
    return probabilities


def make_event(form_index, p_placebo, *, event_id=None, protocol_key=PROTOCOL_KEY, placebo_status="complete",
               real_probabilities=None, placebo_probabilities=None):
    state = {"family": "planning", "agent_id": "A", "clues": [f"clue-{form_index}"]}
    body = jr.pre_read_request_body(state=state, question_id="candidate",
                                    instructions=JEV_CHOICE_INSTRUCTIONS, option_ids=OPTIONS,
                                    model=JEV_DEFAULT_MODEL)
    form = jr.prompt_form_id(body)
    state_hash = jr.canonical_hash(state)
    real_probs = real_probabilities if real_probabilities is not None else one_hot()
    placebo_probs = placebo_probabilities if placebo_probabilities is not None else spread(p=p_placebo)
    branches = {
        "real": jr.make_branch("real", status="complete", probabilities=real_probs, option_ids=OPTIONS,
                              target_id=TARGET, feasible_set=FEASIBLE, state_hash=state_hash,
                              protocol_key=protocol_key, resolved_model=JEV_DEFAULT_MODEL,
                              usage={"input_tokens": 5, "output_tokens": 1}, request_hash="r"),
        "placebo": jr.make_branch("placebo", status=placebo_status,
                                  probabilities=placebo_probs if placebo_status == "complete" else None,
                                  option_ids=OPTIONS, target_id=TARGET, feasible_set=FEASIBLE,
                                  state_hash=state_hash, protocol_key=protocol_key,
                                  resolved_model=JEV_DEFAULT_MODEL, usage={"input_tokens": 5, "output_tokens": 1},
                                  request_hash="p"),
        "null": jr.make_branch("null", status="complete", probabilities=spread(p=p_placebo),
                               option_ids=OPTIONS, target_id=TARGET, feasible_set=FEASIBLE,
                               state_hash=state_hash, protocol_key=protocol_key,
                               resolved_model=JEV_DEFAULT_MODEL, usage={"input_tokens": 5, "output_tokens": 1},
                               request_hash="n"),
    }
    return jr.build_event(event_id=event_id or f"ev-{form_index}", instance_id=f"inst-{form_index}",
                          condition="COMM", model=JEV_DEFAULT_MODEL, prompt_form_id_value=form,
                          pre_read_state=state, option_ids=OPTIONS, target_id=TARGET,
                          feasible_set=FEASIBLE, i_m_bits=1.0,
                          message={"writer_id": "B", "reader_id": "A", "exposure_id": "x",
                                   "owner_exact": True, "i_m_bits": 1.0},
                          placebo={"construction": jr.PLACEBO_CONSTRUCTION, "wording": jr.PLACEBO_WORDING_TEMPLATE,
                                   "synthetic": True, "i_m_bits": 0, "claim": "clue"},
                          branches=branches, request_body=body)


class TDfTests(unittest.TestCase):
    def test_t_critical_lookup(self):
        self.assertAlmostEqual(ji.t_critical_975(5), 2.571)
        self.assertAlmostEqual(ji.t_critical_975(1), 12.706)
        self.assertAlmostEqual(ji.t_critical_975(100), 1.960)


class SignFlipTests(unittest.TestCase):
    def test_all_same_sign_hits_minimum_p(self):
        result = ji.sign_flip_two_sided([-0.2, -0.1, -0.3, -0.15, -0.25, -0.05])
        self.assertEqual(result["k"], 6)
        self.assertAlmostEqual(result["p_value"], 2 / 64)
        self.assertAlmostEqual(result["min_p_value"], 2 / 64)

    def test_balanced_signs_are_not_significant(self):
        result = ji.sign_flip_two_sided([-0.2, 0.2, -0.1, 0.1, -0.3, 0.3])
        self.assertGreater(result["p_value"], 0.5)


class ContrastTests(unittest.TestCase):
    def test_equal_form_contrast(self):
        placebos = [0.5, 0.6, 0.4, 0.7, 0.3, 0.55]
        events = [make_event(index, p) for index, p in enumerate(placebos)]
        contrast = ji.paired_continuous_contrast(events)
        self.assertEqual(contrast["k_forms"], 6)
        self.assertLess(contrast["form_mean"], 0.0)
        self.assertIsNotNone(contrast["t_interval_975"])
        self.assertAlmostEqual(contrast["sign_flip"]["p_value"], 2 / 64)
        self.assertEqual(contrast["missingness"]["usable_pairs"], 6)
        self.assertEqual(contrast["sensitivities"]["label"],
                         "secondary; not the primary inference")
        self.assertIsNotNone(contrast["sensitivities"]["form_cluster_bootstrap_ci"])
        self.assertIsNotNone(contrast["sensitivities"]["instance_weighted_mean"])

    def test_incomplete_pair_reported(self):
        events = [make_event(0, 0.5), make_event(1, 0.6, placebo_status="invalid")]
        contrast = ji.paired_continuous_contrast(events)
        self.assertEqual(contrast["missingness"]["usable_pairs"], 1)
        self.assertEqual(contrast["missingness"]["incomplete_pairs"], 1)
        self.assertEqual(contrast["k_forms"], 1)

    def test_min_pairs_per_form_drops_form(self):
        events = [make_event(0, 0.5), make_event(1, 0.6)]
        contrast = ji.paired_continuous_contrast(events, min_pairs_per_form=2)
        self.assertEqual(contrast["k_forms"], 0)
        self.assertEqual(contrast["missingness"]["forms_below_min_pairs"], 2)

    def test_duplicate_events_rejected(self):
        event = make_event(0, 0.5)
        duplicate = json.loads(json.dumps(event))
        with self.assertRaises(ValueError):
            ji.paired_continuous_contrast([event, duplicate])

    def test_mixed_protocol_rejected(self):
        first = make_event(0, 0.5)
        second = make_event(1, 0.6, protocol_key="six-family-clue-consistent-v2|a|b|c|d|e")
        with self.assertRaises(ValueError):
            ji.paired_continuous_contrast([first, second])

    def test_required_forms_and_two_sided_decision(self):
        events = [make_event(index, 0.5 + 0.02 * index) for index in range(6)]
        contrast = ji.paired_continuous_contrast(events, required_forms=6)
        self.assertTrue(contrast["complete_forms"])
        self.assertTrue(contrast["two_sided_only"])
        self.assertTrue(contrast["negative_effect"])
        self.assertAlmostEqual(contrast["minimum_two_sided_p"], 2 / 64)
        five = ji.paired_continuous_contrast(events[:5], required_forms=6)
        self.assertFalse(five["complete_forms"])
        self.assertAlmostEqual(five["minimum_two_sided_p"], 2 / 32)

    def test_required_forms_exact_membership(self):
        events = [make_event(index, 0.5 + 0.02 * index) for index in range(6)]
        ids = [event["prompt_form_id"] for event in events]
        exact = ji.paired_continuous_contrast(events, required_forms=ids)
        self.assertTrue(exact["complete_forms"])
        subset = ji.paired_continuous_contrast(events, required_forms=ids[:5])
        self.assertFalse(subset["complete_forms"])
        self.assertTrue(subset["extra_forms"])
        missing = ji.paired_continuous_contrast(events, required_forms=ids + ["deadbeef"])
        self.assertFalse(missing["complete_forms"])
        self.assertTrue(missing["missing_forms"])

    def test_fail_on_invalid_raises(self):
        event = make_event(0, 0.5)
        event["branches"]["real"]["entropy_bits"] += 0.5
        with self.assertRaises(ValueError):
            ji.paired_continuous_contrast([event])
        relaxed = ji.paired_continuous_contrast([event], fail_on_invalid=False)
        self.assertEqual(relaxed["missingness"]["invalid_events"], 1)
        self.assertEqual(relaxed["missingness"]["usable_pairs"], 0)


class GuardTests(unittest.TestCase):
    def test_guard_violation_does_not_filter_primary(self):
        real = {option: 0.1 for option in OPTIONS}
        real[TARGET] = 0.1
        real["c1"] = 0.5
        placebo = {option: 1 / 6 for option in OPTIONS}
        violation = make_event(1, 0.5, real_probabilities=real, placebo_probabilities=placebo)
        guards = ji.guard_evaluation([violation])
        row = guards["events"][0]
        self.assertLess(row["entropy_diff"], 0.0)
        self.assertFalse(row["target_guard_ok"])
        self.assertFalse(row["useful_info"])
        self.assertEqual(guards["filtering"], "never used to filter the primary estimate")
        contrast = ji.paired_continuous_contrast([violation])
        self.assertEqual(contrast["missingness"]["usable_pairs"], 1)

    def test_useful_info_requires_target_and_mass(self):
        useful = make_event(0, 0.5)
        guards = ji.guard_evaluation([useful])
        self.assertTrue(guards["events"][0]["useful_info"])
        self.assertEqual(guards["useful_info_events"], 1)


class J3RegressionTests(unittest.TestCase):
    def test_j3_iso_full_form_regression(self):
        journal = [json.loads(line) for line in JOURNAL.read_text(encoding="utf-8").splitlines() if line.strip()]
        result = ji.j3_iso_full_regression(journal)
        self.assertEqual(result["k_forms"], 6)
        self.assertGreater(result["form_mean"], 0.0)
        self.assertAlmostEqual(result["form_mean"], 1.3058, places=2)
        self.assertIsNotNone(result["t_interval_975"])
        self.assertIn("not causal", result["label"])


if __name__ == "__main__":
    unittest.main()
