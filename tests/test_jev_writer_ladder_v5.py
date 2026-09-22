import json
import unittest

from apart_incident_response import jev_writer_ladder_v5 as ladder
from apart_incident_response import jev_ling_writer_v5 as writer_v5
from apart_incident_response.jev_choice_pilot import pilot_instances


class LadderDefinitionTests(unittest.TestCase):
    def setUp(self):
        self.instance = pilot_instances()[0]
        self.context = ladder.ladder_context(self.instance, condition="COMM", turn=1, agent="B",
                                             role="writer")

    def test_seven_rungs_with_bridge(self):
        self.assertEqual([rung.rung_id for rung in ladder.LADDER_RUNGS],
                         ["L0", "L1", "L2", "L3", "L4", "L5", "L4X"])
        self.assertEqual([rung.rung_id for rung in ladder.LADDER_RUNGS if not rung.bridge],
                         ["L0", "L1", "L2", "L3", "L4", "L5"])
        self.assertTrue(ladder.RUNG_INDEX["L4X"].bridge)
        self.assertEqual(ladder.ladder_schema()["bridge_rungs"], ["L4X"])

    def test_l4_renamed_and_l4x_exact_bridge(self):
        self.assertIn("approximate", ladder.RUNG_INDEX["L4"].name)
        self.assertEqual(ladder.EXACT_BRIDGE_TURNS, 2)
        self.assertEqual(list(ladder.EXACT_BRIDGE_AGENTS), ["A", "B"])
        self.assertEqual(ladder.EXACT_BRIDGE_TOKEN_BUDGET, 1024)
        self.assertEqual(ladder.L5_REQUIRED_OWNED_FRACTION, 1.0)
        self.assertIn("l5_gate", ladder.INTERPRETATION_RULES)

    def test_l5_is_induced_and_excluded(self):
        rung = ladder.RUNG_INDEX["L5"]
        self.assertTrue(rung.induced)
        self.assertFalse(rung.voluntary)
        self.assertTrue(all(r.voluntary for r in ladder.LADDER_RUNGS
                            if r.rung_id not in ("L5", "L4X")))
        self.assertEqual(ladder.ladder_schema()["induced_rungs"], ["L5"])

    def test_prompt_field_differences(self):
        l0 = ladder.ladder_prompt("L0", self.context)["prompt"]
        l1 = ladder.ladder_prompt("L1", self.context)["prompt"]
        l2 = ladder.ladder_prompt("L2", self.context)["prompt"]
        l3 = ladder.ladder_prompt("L3", self.context)["prompt"]
        l4 = ladder.ladder_prompt("L4", self.context)["prompt"]
        l5 = ladder.ladder_prompt("L5", self.context)["prompt"]
        self.assertEqual(l0, ladder.L0_TEMPLATE.format(clues=list(self.instance.private_clues["B"])))
        self.assertNotIn("Task:", l0)
        self.assertIn("Task:", l1)
        self.assertNotIn("Candidates:", l1)
        self.assertIn("Candidates:", l2)
        self.assertNotIn("Condition:", l2)
        self.assertIn("Condition:", l3)
        parsed = json.loads(l4)
        self.assertEqual(set(parsed), set(ladder.L4_FIELDS))
        self.assertIn("INDUCED", l5)
        self.assertIn("MESSAGE:", l5)
        grammars = {r: ladder.ladder_prompt(r, self.context)["grammar"] for r in ("L0", "L1", "L2", "L3", "L4", "L5")}
        self.assertEqual(grammars["L4"], writer_v5.GRAMMAR_ORIGINAL_LING)
        self.assertTrue(all(grammars[r] == writer_v5.GRAMMAR_EXPLICIT_SILENCE
                            for r in ("L0", "L1", "L2", "L3", "L5")))

    def test_l4_matches_original_schema_fields(self):
        parsed = json.loads(ladder.ladder_prompt("L4", self.context)["prompt"])
        for field in ladder.L4_FIELDS:
            self.assertIn(field, parsed)

    def test_l4_uses_pooled_joint_clues_for_full(self):
        full = ladder.ladder_context(self.instance, condition="FULL", turn=1, agent="B", role="writer")
        parsed = json.loads(ladder.ladder_prompt("L4", full)["prompt"])
        self.assertEqual(parsed["joint_clues"], [claim.text for claim in self.instance.claims])

    def test_decision_rules_frozen(self):
        for key in ("emission_prompt_dependent", "demote_planning_low", "repair_instrumentation",
                    "l5_transport_validation", "no_post_hoc", "separate_concepts", "three_gates"):
            self.assertIn(key, ladder.INTERPRETATION_RULES)
        self.assertIn("post hoc", ladder.INTERPRETATION_RULES["no_post_hoc"])

    def test_ladder_hash_stable_and_schema(self):
        self.assertEqual(ladder.ladder_hash(), ladder.ladder_hash())
        schema = ladder.ladder_schema()
        self.assertEqual(schema["ladder_version"], ladder.LADDER_VERSION)
        self.assertEqual(schema["voluntary_rungs"], ["L0", "L1", "L2", "L3", "L4"])
        self.assertFalse(ladder.RUNG_INDEX["L4X"].voluntary)

    def test_l5_explicit_grammar_classifies_silence(self):
        result = writer_v5.classify_writer_completion("SILENCE", None, [],
                                                      grammar=ladder.RUNG_INDEX["L5"].grammar)
        self.assertEqual(result["outcome"], writer_v5.OUTCOME_DELIBERATE_SILENCE)


if __name__ == "__main__":
    unittest.main()
