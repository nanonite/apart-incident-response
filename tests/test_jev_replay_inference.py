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


def make_event(form_index, p_placebo, *, event_id=None, protocol_key=PROTOCOL_KEY, placebo_status="complete"):
    state = {"family": "planning", "agent_id": "A", "clues": [f"clue-{form_index}"]}
    body = jr.pre_read_request_body(state=state, question_id="candidate",
                                    instructions=JEV_CHOICE_INSTRUCTIONS, option_ids=OPTIONS,
                                    model=JEV_DEFAULT_MODEL)
    form = jr.prompt_form_id(body)
    state_hash = jr.canonical_hash(state)
    branches = {
        "real": jr.make_branch("real", status="complete", probabilities=one_hot(), option_ids=OPTIONS,
                              target_id=TARGET, feasible_set=FEASIBLE, state_hash=state_hash,
                              protocol_key=protocol_key, resolved_model=JEV_DEFAULT_MODEL,
                              usage={"input_tokens": 5, "output_tokens": 1}, request_hash="r"),
        "placebo": jr.make_branch("placebo", status=placebo_status,
                                  probabilities=spread(p=p_placebo) if placebo_status == "complete" else None,
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
                          condition="COMM", prompt_form_id_value=form, pre_read_state=state,
                          option_ids=OPTIONS, target_id=TARGET, feasible_set=FEASIBLE, i_m_bits=1.0,
                          message={"writer_id": "B", "reader_id": "A", "exposure_id": "x"},
                          branches=branches)


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
