import json
import unittest

from apart_incident_response import jev_replay as jr
from apart_incident_response import jev_preregistration as jp
from apart_incident_response.communication_events import CommunicationEventLog
from apart_incident_response.jev_choice import JEV_CHOICE_INSTRUCTIONS, JEV_DEFAULT_MODEL, jev_choice_protocol_key


PROTOCOL_KEY = jev_choice_protocol_key()
EXPOSURE_ID = "x1"


def spread(options, target_id, p=0.5):
    others = [option for option in options if option != target_id]
    remainder = (1.0 - p) / len(others) if others else 0.0
    probabilities = {option: remainder for option in options}
    probabilities[target_id] = p
    return probabilities


def one_hot(options, target_id):
    return {option: (1.0 if option == target_id else 0.0) for option in options}


def board_log_for(instance, *, writer, reader, claim, message_id, exposure_id=EXPOSURE_ID, rejected=False):
    """Build a log fixture with the actual CommunicationEventLog schema."""

    log = CommunicationEventLog("run-1", clock=lambda: 1)
    info = instance.information(reader, claim, message_id)
    if rejected:
        log.record("board_write_rejected", writer, status="rejected",
                   payload={"reason": "claim_not_owned_by_writer", "raw_text": claim, "claim_owner": None})
    else:
        log.board_write(writer, info, message_tokens=2, receiver_id=reader)
    log.peer_read(reader, info, exposure_id=exposure_id)
    return [event.to_dict() for event in log.events]


def valid_event(instance=None, *, board_log=None, exposure_id=EXPOSURE_ID):
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
    log = board_log if board_log is not None else board_log_for(
        instance, writer=writer, reader=agent, claim=real_claim, message_id="m-real", exposure_id=exposure_id)

    def branch(name, probabilities, message_text):
        return jr.make_branch(name, status="complete", probabilities=probabilities, option_ids=options,
                              target_id=target, feasible_set=feasible, state_hash=state_hash,
                              protocol_key=PROTOCOL_KEY, resolved_model=JEV_DEFAULT_MODEL,
                              usage={"input_tokens": 10, "output_tokens": 2},
                              request_hash=jr.prompt_form_id(jr.branch_request_body(body, message_text)))

    branches = {
        "real": branch("real", one_hot(options, target), jr.serialize_message(real_claim)),
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
        real_message={"writer_id": writer, "reader_id": agent, "exposure_id": exposure_id,
                      "message_id": "m-real", "claim": real_claim},
        placebo={"claim": placebo_claim, "synthetic": True, "construction": jr.PLACEBO_CONSTRUCTION,
                 "envelope": jr.MESSAGE_ENVELOPE_TEMPLATE, "i_m_bits": 0},
        branches=branches, board_log=log)


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

    def test_envelope_is_source_neutral_in_both_arms(self):
        self.assertEqual(jr.serialize_message("the clue"), "peer_clue: the clue")
        self.assertEqual(jr.serialize_placebo_message("the clue"), "peer_clue: the clue")
        self.assertNotIn("from", jr.MESSAGE_ENVELOPE_TEMPLATE)
        self.assertEqual(len(jr.message_wording_hash()), 64)

    def test_branch_request_body_differs_only_by_message(self):
        body = jr.pre_read_request_body(state={"clues": ["a"]}, question_id="candidate",
                                        instructions=JEV_CHOICE_INSTRUCTIONS, option_ids=["x"], model="m")
        real = jr.branch_request_body(body, jr.serialize_message("a"))
        null = jr.branch_request_body(body, None)
        self.assertEqual(real["state"]["visible_messages"], [{"role": "peer", "text": "peer_clue: a"}])
        self.assertEqual(null["state"]["visible_messages"], [])


class ValidationTests(unittest.TestCase):
    def test_valid_event_passes(self):
        self.assertEqual(jr.validate_event(valid_event()), [])

    def test_placebo_must_be_receiver_already_known(self):
        instance = jp.jev_capability_instances()[0]
        event = valid_event(instance)
        event["placebo"]["claim"] = str(instance.private_clues["B"][0])
        self.assertIn("placebo_not_inert", jr.validate_event(event))

    def test_real_ownership_and_i_m_are_authoritative(self):
        event = valid_event()
        event["real_message"]["writer_id"] = "A"
        problems = jr.validate_event(event)
        self.assertTrue({"ineligible_real_message", "unverified_real_evidence"} & set(problems))
        event = valid_event()
        event["i_m_bits"] = float(event["i_m_bits"]) + 1.0
        self.assertIn("unverified_real_evidence", jr.validate_event(event))
        event = valid_event()
        event["real_message"]["message_id"] = "other"
        self.assertIn("unverified_real_evidence", jr.validate_event(event))

    def test_board_log_link_is_required_and_rejected_write_fails(self):
        instance = jp.jev_capability_instances()[0]
        claim = str(instance.private_clues["B"][0])
        rejected = board_log_for(instance, writer="B", reader="A", claim=claim, message_id="m-real",
                                 rejected=True)
        event = valid_event(instance, board_log=rejected)
        problems = jr.validate_event(event)
        self.assertIn("unverified_real_evidence", problems)
        event = valid_event(instance, board_log=[])
        self.assertIn("unverified_real_evidence", jr.validate_event(event))
        # write present but no read
        log = CommunicationEventLog("run-2", clock=lambda: 1)
        info = instance.information("A", claim, "m-real")
        log.board_write("B", info, message_tokens=2, receiver_id="A")
        event = valid_event(instance, board_log=[e.to_dict() for e in log.events])
        self.assertIn("unverified_real_evidence", jr.validate_event(event))

    def test_invented_exposure_id_fails(self):
        instance = jp.jev_capability_instances()[0]
        claim = str(instance.private_clues["B"][0])
        log = board_log_for(instance, writer="B", reader="A", claim=claim, message_id="m-real",
                            exposure_id="invented")
        event = valid_event(instance, board_log=log, exposure_id="x1")
        self.assertIn("unverified_real_evidence", jr.validate_event(event))

    def test_branch_request_hash_is_recomputed(self):
        event = valid_event()
        event["branches"]["real"]["request_hash"] = "deadbeef"
        self.assertIn("branch_request_mismatch", jr.validate_event(event))

    def test_instance_task_is_authoritative(self):
        event = valid_event()
        event["task"]["seed"] = 999999
        self.assertIn("instance_mismatch", jr.validate_event(event))

    def test_malformed_records_return_problems_not_exceptions(self):
        mutations = (
            lambda e: e["branches"]["real"].__setitem__("probabilities", {o: "bad" for o in e["option_ids"]}),
            lambda e: e.pop("request_body", None),
            lambda e: e.__setitem__("branches", None),
            lambda e: e["branches"]["real"].pop("usage", None),
            lambda e: e["branches"]["real"].pop("entropy_bits", None),
            lambda e: e["branches"]["real"].__setitem__("resolved_model", "other"),
            lambda e: e.pop("board_log", None),
        )
        for mutate in mutations:
            event = valid_event()
            mutate(event)
            self.assertTrue(jr.validate_event(event))  # must not raise
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
        self.assertEqual(summary["forms"], 1)
        self.assertEqual(next(iter(summary["by_form"].values()))["complete_pairs"], 2)

    def test_incomplete_pair_reported_not_counted(self):
        event = valid_event()
        event["branches"]["placebo"]["status"] = "invalid"
        row = next(iter(jr.summarize_events([event])["by_form"].values()))
        self.assertEqual(row["complete_pairs"], 0)
        self.assertEqual(row["incomplete_pairs"], 1)


if __name__ == "__main__":
    unittest.main()
