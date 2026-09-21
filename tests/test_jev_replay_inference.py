import json
import unittest
from pathlib import Path

from apart_incident_response import jev_replay as jr
from apart_incident_response import jev_replay_inference as ji
from apart_incident_response import jev_preregistration as jp
from apart_incident_response.jev_choice import JEV_CHOICE_INSTRUCTIONS, JEV_DEFAULT_MODEL, jev_choice_protocol_key


REPO_ROOT = Path(__file__).resolve().parents[1]
JOURNAL = REPO_ROOT / "runs" / "epic-126" / "jev-choice-capability.jsonl"
PROTOCOL_KEY = jev_choice_protocol_key()


def spread(options, target_id, p=0.5):
    others = [option for option in options if option != target_id]
    remainder = (1.0 - p) / len(others) if others else 0.0
    probabilities = {option: remainder for option in options}
    probabilities[target_id] = p
    return probabilities


def one_hot(options, target_id):
    return {option: (1.0 if option == target_id else 0.0) for option in options}


def build_event(instance, *, real_probs=None, placebo_probs=None, event_id=None, placebo_status="complete"):
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
    info = instance.information(agent, real_claim, "m-real")
    placebo_claim = str(instance.private_clues[agent][0])
    real_probs = real_probs or one_hot(options, target)
    placebo_probs = placebo_probs or spread(options, target, 0.5)

    def branch(name, probabilities, message_text, status="complete"):
        return jr.make_branch(name, status=status, probabilities=probabilities if status == "complete" else None,
                              option_ids=options, target_id=target, feasible_set=feasible,
                              state_hash=state_hash, protocol_key=PROTOCOL_KEY,
                              resolved_model=JEV_DEFAULT_MODEL, usage={"input_tokens": 10, "output_tokens": 2},
                              request_hash=jr.prompt_form_id(jr.branch_request_body(body, message_text)))

    branches = {
        "real": branch("real", real_probs, jr.serialize_message(writer, real_claim)),
        "placebo": branch("placebo", placebo_probs, jr.serialize_placebo_message(placebo_claim),
                          status=placebo_status),
        "null": branch("null", spread(options, target, 0.5), None),
    }
    return jr.build_event(
        event_id=event_id or f"ev-{instance.instance_id}", instance_id=instance.instance_id,
        condition="COMM", model=JEV_DEFAULT_MODEL,
        task={"family": instance.family, "seed": instance.seed,
              "regime": instance.assignment.regime.value, "complexity": instance.complexity.value,
              "agent": agent},
        prompt_form_id_value=form, pre_read_state=state, request_body=body, option_ids=options,
        target_id=target, feasible_set=feasible, i_m_bits=float(info.delta_i_bits),
        real_message={"writer_id": writer, "reader_id": agent, "exposure_id": "x", "message_id": "m-real",
                      "claim": real_claim,
                      "board_event": {"message_id": "m-real", "writer": writer, "reader": agent,
                                      "normalized_claim": real_claim}},
        placebo={"claim": placebo_claim, "synthetic": True, "construction": jr.PLACEBO_CONSTRUCTION,
                 "envelope": jr.MESSAGE_ENVELOPE_TEMPLATE, "i_m_bits": 0},
        branches=branches)


def _iso_form(instance):
    state = {"family": instance.family, "complexity": instance.complexity.value, "agent_id": "A",
             "clues": list(instance.private_clues.get("A", ()))}
    body = jr.pre_read_request_body(state=state, question_id="candidate",
                                    instructions=JEV_CHOICE_INSTRUCTIONS,
                                    option_ids=sorted(instance.solutions), model=JEV_DEFAULT_MODEL)
    return jr.prompt_form_id(body)


def form_events(count=6):
    """One event per distinct ISO prompt form (first instances repeat forms)."""

    seen: set[str] = set()
    events = []
    for instance in jp.jev_capability_instances():
        form = _iso_form(instance)
        if form in seen:
            continue
        seen.add(form)
        events.append(build_event(instance))
        if len(events) == count:
            break
    return events


class TDfTests(unittest.TestCase):
    def test_t_critical_lookup(self):
        self.assertAlmostEqual(ji.t_critical_975(5), 2.571)
        self.assertAlmostEqual(ji.t_critical_975(100), 1.960)


class SignFlipTests(unittest.TestCase):
    def test_all_same_sign_hits_minimum_p(self):
        result = ji.sign_flip_two_sided([-0.2, -0.1, -0.3, -0.15, -0.25, -0.05])
        self.assertAlmostEqual(result["p_value"], 2 / 64)

    def test_balanced_signs_not_significant(self):
        self.assertGreater(ji.sign_flip_two_sided([-0.2, 0.2, -0.1, 0.1, -0.3, 0.3])["p_value"], 0.5)


class ContrastTests(unittest.TestCase):
    def test_equal_form_contrast(self):
        events = form_events(6)
        contrast = ji.paired_continuous_contrast(events)
        self.assertEqual(contrast["k_forms"], 6)
        self.assertLess(contrast["form_mean"], 0.0)
        self.assertIsNotNone(contrast["t_interval_975"])
        self.assertAlmostEqual(contrast["sign_flip"]["p_value"], 2 / 64)
        self.assertEqual(contrast["missingness"]["usable_pairs"], 6)
        self.assertEqual(contrast["sensitivities"]["label"], "secondary; not the primary inference")

    def test_incomplete_pair_reported(self):
        events = [build_event(jp.jev_capability_instances()[0]),
                  build_event(jp.jev_capability_instances()[1], placebo_status="invalid")]
        contrast = ji.paired_continuous_contrast(events)
        self.assertEqual(contrast["missingness"]["usable_pairs"], 1)
        self.assertEqual(contrast["missingness"]["incomplete_pairs"], 1)

    def test_required_forms_exact_membership(self):
        events = form_events(6)
        ids = [event["prompt_form_id"] for event in events]
        self.assertTrue(ji.paired_continuous_contrast(events, required_forms=ids)["complete_forms"])
        subset = ji.paired_continuous_contrast(events, required_forms=ids[:5])
        self.assertFalse(subset["complete_forms"])
        self.assertTrue(subset["extra_forms"])
        missing = ji.paired_continuous_contrast(events, required_forms=ids + ["deadbeef"])
        self.assertTrue(missing["missing_forms"])

    def test_duplicate_and_mixed_protocol_rejected(self):
        event = build_event(jp.jev_capability_instances()[0])
        with self.assertRaises(ValueError):
            ji.paired_continuous_contrast([event, json.loads(json.dumps(event))])
        mixed = build_event(jp.jev_capability_instances()[1])
        mixed["branches"]["real"]["protocol_key"] = "six-family-clue-consistent-v2|a|b|c|d|e"
        with self.assertRaises(ValueError):
            ji.paired_continuous_contrast([event, mixed])

    def test_fail_on_invalid_raises_and_relaxed_reports(self):
        event = build_event(jp.jev_capability_instances()[0])
        event["branches"]["real"]["entropy_bits"] += 0.5
        with self.assertRaises(ValueError):
            ji.paired_continuous_contrast([event])
        relaxed = ji.paired_continuous_contrast([event], fail_on_invalid=False)
        self.assertEqual(relaxed["missingness"]["invalid_events"], 1)


class GuardTests(unittest.TestCase):
    def test_guard_violation_does_not_filter_primary(self):
        instance = jp.jev_capability_instances()[0]
        options = sorted(instance.solutions)
        real = {option: 0.1 for option in options}
        real[instance.target] = 0.1
        real[options[1]] = 0.5
        placebo = {option: 1 / 6 for option in options}
        event = build_event(instance, real_probs=real, placebo_probs=placebo)
        guards = ji.guard_evaluation([event])
        row = guards["events"][0]
        self.assertLess(row["entropy_diff"], 0.0)
        self.assertFalse(row["target_guard_ok"])
        self.assertFalse(row["useful_info"])
        self.assertEqual(guards["filtering"], "never used to filter the primary estimate")
        contrast = ji.paired_continuous_contrast([event])
        self.assertEqual(contrast["missingness"]["usable_pairs"], 1)

    def test_useful_info_requires_target_and_mass(self):
        event = build_event(jp.jev_capability_instances()[0])
        guards = ji.guard_evaluation([event])
        self.assertTrue(guards["events"][0]["useful_info"])


class J3RegressionTests(unittest.TestCase):
    def test_j3_iso_full_form_regression(self):
        journal = [json.loads(line) for line in JOURNAL.read_text(encoding="utf-8").splitlines() if line.strip()]
        result = ji.j3_iso_full_regression(journal)
        self.assertEqual(result["k_forms"], 6)
        self.assertGreater(result["form_mean"], 0.0)
        self.assertIn("not causal", result["label"])


if __name__ == "__main__":
    unittest.main()
