import json
import unittest

from apart_incident_response import jev_replay as jr
from apart_incident_response import jev_preregistration as jp
from apart_incident_response.jev_choice import JEV_CHOICE_INSTRUCTIONS, JEV_DEFAULT_MODEL, jev_choice_protocol_key


PROTOCOL_KEY = jev_choice_protocol_key()


def spread(options, target_id, p=0.5):
    others = [option for option in options if option != target_id]
    remainder = (1.0 - p) / len(others) if others else 0.0
    probabilities = {option: remainder for option in options}
    probabilities[target_id] = p
    return probabilities


def one_hot(options, target_id):
    return {option: (1.0 if option == target_id else 0.0) for option in options}


def valid_event(instance=None):
    instance = instance or jp.jev_capability_instances()[0]
    agent, writer = "A", "B"
    options = sorted(instance.solutions)
    target = instance.target
    feasible = sorted(instance.private_solutions[agent])
    state = {"family": instance.family, "complexity": instance.complexity.value, "agent_id": agent,
             "clues": list(instance.private_clues.get(agent, ()))}
    body = jr.pre_read_request_body(state=state, question_id="candidate",
                                    instructions=JEV_CHOICE_INSTRUCTIONS, option_ids=options,
                                    model=JEV_DEFAULT_MODEL)
    form = jr.prompt_form_id(body)
    state_hash = jr.canonical_hash(state)
    real_claim = str(instance.private_clues[writer][0])
    real_info = instance.information(agent, real_claim, "m-real")
    placebo_claim = str(instance.private_clues[agent][0])

    def branch(name, probabilities, message_text):
        return jr.make_branch(name, status="complete", probabilities=probabilities, option_ids=options,
                              target_id=target, feasible_set=feasible, state_hash=state_hash,
                              protocol_key=PROTOCOL_KEY, resolved_model=JEV_DEFAULT_MODEL,
                              usage={"input_tokens": 10, "output_tokens": 2},
                              request_hash=jr.prompt_form_id(jr.branch_request_body(body, message_text)))

    branches = {
        "real": branch("real", one_hot(options, target), jr.serialize_message(writer, real_claim)),
        "placebo": branch("placebo", spread(options, target, 0.4), jr.serialize_placebo_message(placebo_claim)),
        "null": branch("null", spread(options, target, 0.4), None),
    }
    return jr.build_event(
        event_id="ev-1", instance_id=instance.instance_id, condition="COMM", model=JEV_DEFAULT_MODEL,
        task={"family": instance.family, "seed": instance.seed,
              "regime": instance.assignment.regime.value, "complexity": instance.complexity.value,
              "agent": agent},
        prompt_form_id_value=form, pre_read_state=state, request_body=body, option_ids=options,
        target_id=target, feasible_set=feasible, i_m_bits=float(real_info.delta_i_bits),
        real_message={"writer_id": writer, "reader_id": agent, "exposure_id": "x1", "message_id": "m-real",
                      "claim": real_claim,
                      "board_event": {"message_id": "m-real", "writer": writer, "reader": agent,
                                      "normalized_claim": real_claim}},
        placebo={"claim": placebo_claim, "synthetic": True, "construction": jr.PLACEBO_CONSTRUCTION,
                 "envelope": jr.MESSAGE_ENVELOPE_TEMPLATE, "i_m_bits": 0},
        branches=branches)


class IdentityTests(unittest.TestCase):
    def test_prompt_form_id_is_stable_and_sensitive(self):
        state = {"clues": ["a", "b"], "agent_id": "A"}
        body = jr.pre_read_request_body(state=state, question_id="candidate",
                                        instructions=JEV_CHOICE_INSTRUCTIONS, option_ids=["x", "y"],
                                        model=JEV_DEFAULT_MODEL)
        first = jr.prompt_form_id(body)
        self.assertEqual(first, jr.prompt_form_id(body))
        other = json.loads(json.dumps(body))
        other["questions"]["candidate"]["instructions"] = "different wording"
        self.assertNotEqual(first, jr.prompt_form_id(other))

    def test_envelope_and_placebo_serializer_are_frozen(self):
        self.assertEqual(jr.serialize_message("B", "c"), "peer_message from B: c")
        self.assertEqual(jr.serialize_placebo_message("c"), "peer_message from peer: c")
        self.assertEqual(jr.message_wording_hash(), jr.message_wording_hash())
        self.assertEqual(len(jr.message_wording_hash()), 64)

    def test_branch_request_body_differs_only_by_message(self):
        body = jr.pre_read_request_body(state={"clues": ["a"]}, question_id="candidate",
                                        instructions=JEV_CHOICE_INSTRUCTIONS, option_ids=["x"], model="m")
        real = jr.branch_request_body(body, "peer_message from B: a")
        null = jr.branch_request_body(body, None)
        self.assertEqual(real["state"]["visible_messages"], [{"role": "peer", "text": "peer_message from B: a"}])
        self.assertEqual(null["state"]["visible_messages"], [])
        self.assertEqual({k: v for k, v in real.items() if k != "state"},
                         {k: v for k, v in null.items() if k != "state"})


class ValidationTests(unittest.TestCase):
    def test_valid_event_passes(self):
        self.assertEqual(jr.validate_event(valid_event()), [])

    def test_placebo_must_be_receiver_already_known(self):
        instance = jp.jev_capability_instances()[0]
        event = valid_event(instance)
        event["placebo"]["claim"] = str(instance.private_clues["B"][0])
        problems = jr.validate_event(event)
        self.assertIn("placebo_not_inert", problems)

    def test_real_ownership_and_i_m_are_authoritative(self):
        event = valid_event()
        event["real_message"]["writer_id"] = "A"
        event["real_message"]["board_event"]["writer"] = "A"
        event["real_message"]["board_event"]["normalized_claim"] = "nonexistent"
        problems = jr.validate_event(event)
        self.assertTrue({"ineligible_real_message", "unverified_real_evidence"} & set(problems))
        event = valid_event()
        event["i_m_bits"] = float(event["i_m_bits"]) + 1.0
        self.assertIn("unverified_real_evidence", jr.validate_event(event))
        event = valid_event()
        event["real_message"]["board_event"] = {}
        self.assertTrue({"unverified_real_evidence", "missing_provenance"}
                        & set(jr.validate_event(event)))

    def test_branch_request_hash_is_recomputed(self):
        event = valid_event()
        event["branches"]["real"]["request_hash"] = "deadbeef"
        self.assertIn("branch_request_mismatch", jr.validate_event(event))
        event = valid_event()
        event["branches"]["placebo"]["request_hash"] = ""
        self.assertIn("branch_request_mismatch", jr.validate_event(event))

    def test_instance_task_is_authoritative(self):
        event = valid_event()
        event["task"]["seed"] = 999999
        self.assertIn("instance_mismatch", jr.validate_event(event))

    def test_malformed_records_return_problems_not_exceptions(self):
        for mutate in (
            lambda e: e["branches"]["real"].__setitem__("probabilities", {o: "bad" for o in e["option_ids"]}),
            lambda e: e.pop("request_body", None),
            lambda e: e.__setitem__("branches", None),
            lambda e: e["branches"]["real"].pop("usage", None),
            lambda e: e["branches"]["real"].pop("entropy_bits", None),
            lambda e: e["branches"]["real"].__setitem__("resolved_model", "other"),
        ):
            event = valid_event()
            mutate(event)
            problems = jr.validate_event(event)  # must not raise
            self.assertTrue(problems)
        self.assertEqual(jr.validate_event(None), ["malformed_event"])

    def test_mixed_protocol_and_duplicates_raise(self):
        event = valid_event()
        event["branches"]["real"]["protocol_key"] = "six-family-clue-consistent-v2|a|b|c|d|e"
        with self.assertRaises(ValueError):
            jr.assert_single_protocol([event])
        with self.assertRaises(ValueError):
            jr.assert_no_duplicate_events([valid_event(), valid_event()])


class SummaryTests(unittest.TestCase):
    def test_summary_counts_complete_pairs_by_form(self):
        second = json.loads(json.dumps(valid_event()))
        second["event_id"] = "ev-2"
        summary = jr.summarize_events([valid_event(), second])
        self.assertEqual(summary["events"], 2)
        self.assertEqual(summary["forms"], 1)
        row = next(iter(summary["by_form"].values()))
        self.assertEqual(row["complete_pairs"], 2)

    def test_incomplete_pair_reported_not_counted(self):
        event = valid_event()
        event["branches"]["placebo"]["status"] = "invalid"
        summary = jr.summarize_events([event])
        row = next(iter(summary["by_form"].values()))
        self.assertEqual(row["complete_pairs"], 0)
        self.assertEqual(row["incomplete_pairs"], 1)


if __name__ == "__main__":
    unittest.main()
