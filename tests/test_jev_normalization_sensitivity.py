import json
import unittest

from apart_incident_response import jev_choice_v2 as v2
from apart_incident_response import jev_normalization_sensitivity as sens


LABELS = ["a", "b", "c", "d", "e", "f"]


def spread(total, first=0.5):
    rest = (total - first) / (len(LABELS) - 1)
    return {label: (first if index == 0 else rest) for index, label in enumerate(LABELS)}


class SensitivityTests(unittest.TestCase):
    def test_grid_is_registered(self):
        self.assertEqual(tuple(sens.SENSITIVITY_GRID), (1e-6, 0.01, 0.03, 0.05))

    def test_counts_and_adjustments_across_grid(self):
        report = sens.normalization_sensitivity(
            [spread(1.0), spread(1.01, first=0.51), spread(1.02, first=0.52), spread(1.10, first=0.6)],
            option_ids=LABELS)
        zero = report["per_tolerance"]["1e-06"]
        self.assertEqual(zero["accepted"], 1)
        self.assertEqual(zero["rejected"], 3)
        one = report["per_tolerance"]["0.01"]
        self.assertEqual(one["accepted"], 2)
        three = report["per_tolerance"]["0.03"]
        self.assertEqual(three["accepted"], 3)
        five = report["per_tolerance"]["0.05"]
        self.assertEqual(five["accepted"], 3)
        self.assertGreater(report["max_normalization_adjustment"], 0.0)
        self.assertGreater(report["max_induced_entropy_difference"], 0.0)

    def test_conclusion_stability_is_labelled(self):
        report = sens.normalization_sensitivity(
            [spread(1.0), spread(1.02, first=0.52)], option_ids=LABELS)
        self.assertTrue(report["unstable"])
        self.assertFalse(report["conclusion_stable"])

        stable = sens.normalization_sensitivity([spread(1.0)], option_ids=LABELS)
        self.assertFalse(stable["unstable"])
        self.assertTrue(stable["conclusion_stable"])

    def test_malformed_vectors_are_rejected_at_every_tolerance(self):
        report = sens.normalization_sensitivity(
            [{"a": -0.5, "b": 1.5}, {"a": float("nan"), "b": 0.0}], option_ids=["a", "b"])
        for row in report["per_tolerance"].values():
            self.assertEqual(row["accepted"], 0)
            self.assertGreater(row["rejected_by_shape"], 0)

    def test_explicit_conclusion_function_marks_instability(self):
        def conclude(accepted):
            return {"n": len(accepted)}

        report = sens.normalization_sensitivity(
            [spread(1.0), spread(1.02, first=0.52)], option_ids=LABELS, conclusion_fn=conclude)
        self.assertTrue(report["unstable"])
        self.assertEqual(report["per_tolerance"]["1e-06"]["conclusion"], {"n": 1})
        self.assertEqual(report["per_tolerance"]["0.03"]["conclusion"], {"n": 2})

    def test_journal_vectors_extracts_raw_then_used(self):
        rows = [
            {"raw_probabilities": {"a": 1.0}},
            {"probabilities": {"b": 1.0}},
            {"status": "invalid"},
        ]
        self.assertEqual(sens.journal_vectors(rows), [{"a": 1.0}, {"b": 1.0}])

    def test_default_conclusion_is_json_safe(self):
        report = sens.normalization_sensitivity([spread(0.99)], option_ids=LABELS)
        json.dumps(report, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
