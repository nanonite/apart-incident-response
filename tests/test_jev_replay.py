import json
import unittest

from apart_incident_response import jev_replay as jr
from apart_incident_response import jev_preregistration as jp
from apart_incident_response.jev_choice import JEV_CHOICE_INSTRUCTIONS, JEV_DEFAULT_MODEL, jev_choice_protocol_key


PROTOCOL_KEY = jev_choice_protocol_key()


def one_hot(options, target_id):
    return {option: (1.0 if option == target_id else 0.0) for option in options}


def spread(options, target_id, p=0.5):
    others = [option for option in options if option != target_id]
    remainder = (1.0 - p) / len(others) if others else 0.0
    probabilities = {option: remainder for option in options}
    probabilities[target_id] = p
    return probabilities


def sample_event():
    instance = jp.jev_capability_instances()[0]
    options = sorted(instance.solutions)
    target = instance.target
    feasible = sorted(instance.private_solutions["A"])
    state = {"family": instance.family, "complexity": instance.complexity.value, "agent_id": "A",
             "clues": list(instance.private_clues.get("A", ()))}
    body = jr.pre_read_request_body(state=state, question_id="candidate",
                                    instructions=JEV_CHOICE_INSTRUCTIONS, option_ids=options,
                                    model=JEV_DEFAULT_MODEL)
    form = jr.prompt_form_id(body)
    state_hash = jr.canonical_hash(state)
    branches = {
        "real": jr.make_branch("real", status="complete", probabilities=spread(options, target, 0.8),
                              option_ids=options, target_id=target, feasible_set=feasible,
                              state_hash=state_hash, protocol_key=PROTOCOL_KEY,
                              resolved_model=JEV_DEFAULT_MODEL, usage={"input_tokens": 10, "output_tokens": 2},
                              request_hash="r"),
        "placebo": jr.make_branch("placebo", status="complete", probabilities=spread(options, target, 0.4),
                                  option_ids=options, target_id=target, feasible_set=feasible,
                                  state_hash=state_hash, protocol_key=PROTOCOL_KEY,
                                  resolved_model=JEV_DEFAULT_MODEL, usage={"input_tokens": 10, "output_tokens": 2},
                                  request_hash="p"),
        "null": jr.make_branch("null", status="complete", probabilities=spread(options, target, 0.4),
                               option_ids=options, target_id=target, feasible_set=feasible,
                               state_hash=state_hash, protocol_key=PROTOCOL_KEY,
                               resolved_model=JEV_DEFAULT_MODEL, usage={"input_tokens": 10, "output_tokens": 2},
                               request_hash="n"),
    }
    return jr.build_event(event_id="ev-1", instance_id=instance.instance_id, condition="COMM",
                          prompt_form_id_value=form, pre_read_state=state, option_ids=options,
                          target_id=target, feasible_set=feasible, i_m_bits=1.0,
                          message={"writer_id": "B", "reader_id": "A", "exposure_id": "x1",
                                   "owner_exact": True, "i_m_bits": 1.0},
                          branches=branches)


class IdentityTests(unittest.TestCase):
    def test_prompt_form_id_is_stable_and_sensitive(self):
        state = {"clues": ["a", "b"], "agent_id": "A"}
        body = jr.pre_read_request_body(state=state, question_id="candidate",
                                        instructions=JEV_CHOICE_INSTRUCTIONS,
                                        option_ids=["x", "y"], model=JEV_DEFAULT_MODEL)
        first = jr.prompt_form_id(body)
        self.assertEqual(first, jr.prompt_form_id(body))
        other = json.loads(json.dumps(body))
        other["questions"]["candidate"]["instructions"] = "different wording"
        self.assertNotEqual(first, jr.prompt_form_id(other))
        other2 = json.loads(json.dumps(body))
        other2["state"]["clues"] = ["a", "c"]
        self.assertNotEqual(first, jr.prompt_form_id(other2))

    def test_entropy_and_guards(self):
        self.assertEqual(jr.entropy_bits({"a": 1.0}), 0.0)
        event = sample_event()
        real = event["branches"]["real"]
        self.assertGreater(real["entropy_bits"], 0.0)
        self.assertAlmostEqual(real["p_target"], 0.8)
        self.assertAlmostEqual(real["feasible_mass"], sum(real["probabilities"][o] for o in event["feasible_set"]))


class ValidationTests(unittest.TestCase):
    def test_valid_event(self):
        self.assertEqual(jr.validate_event(sample_event()), [])

    def test_missing_and_unknown_branch(self):
        event = sample_event()
        del event["branches"]["null"]
        self.assertIn("missing_branch", jr.validate_event(event))
        event = sample_event()
        event["branches"]["extra"] = event["branches"]["null"]
        self.assertIn("unknown_branch", jr.validate_event(event))

    def test_unmatched_state_across_branches(self):
        event = sample_event()
        event["branches"]["placebo"]["state_hash"] = "different"
        self.assertIn("unmatched_state", jr.validate_event(event))

    def test_mixed_protocol(self):
        event = sample_event()
        event["branches"]["real"]["protocol_key"] = "six-family-clue-consistent-v2|a|b|c|d|e"
        problems = jr.validate_event(event)
        self.assertIn("mixed_protocol", problems)
        self.assertIn("non_jev_protocol_key", problems)
        with self.assertRaises(ValueError):
            jr.assert_single_protocol([event])

    def test_malformed_vector(self):
        event = sample_event()
        event["branches"]["real"]["probabilities"] = {"only": 1.0}
        self.assertIn("option_identity_mismatch", jr.validate_event(event))
        event = sample_event()
        event["branches"]["placebo"]["probabilities"] = {o: 0.1 for o in event["option_ids"]}
        self.assertIn("not_normalized", jr.validate_event(event))

    def test_answer_key_leakage(self):
        event = sample_event()
        event["pre_read_state"]["clues"] = [event["target_id"]]
        self.assertIn("answer_key_leakage", jr.validate_event(event))

    def test_missing_provenance(self):
        event = sample_event()
        event["message"] = {"writer_id": "B"}
        self.assertIn("missing_provenance", jr.validate_event(event))

    def test_duplicates_raise(self):
        event = sample_event()
        with self.assertRaises(ValueError):
            jr.assert_no_duplicate_events([event, sample_event()])


class SummaryTests(unittest.TestCase):
    def test_summary_counts_complete_pairs_by_form(self):
        event = sample_event()
        second = json.loads(json.dumps(event))
        second["event_id"] = "ev-2"
        summary = jr.summarize_events([event, second])
        self.assertEqual(summary["events"], 2)
        self.assertEqual(summary["forms"], 1)
        row = next(iter(summary["by_form"].values()))
        self.assertEqual(row["complete_pairs"], 2)
        self.assertEqual(row["valid"], 2)

    def test_incomplete_pair_is_reported_not_counted(self):
        event = sample_event()
        event["branches"]["placebo"]["status"] = "invalid"
        summary = jr.summarize_events([event])
        row = next(iter(summary["by_form"].values()))
        self.assertEqual(row["complete_pairs"], 0)
        self.assertEqual(row["incomplete_pairs"], 1)
        self.assertEqual(row["attempted"], 1)
        self.assertEqual(summary["invalid"], [])


if __name__ == "__main__":
    unittest.main()
