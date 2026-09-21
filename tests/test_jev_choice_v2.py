import json
import unittest

from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_choice_v2 as v2
from apart_incident_response.jev_protocol import planning_low_instances


class ScriptedChoiceClient:
    endpoint = jc.JEV_SYSTEMONE_ENDPOINT
    max_retries = 2

    def __init__(self, response=None):
        self.response = response
        self.physical_attempts = 0
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        self.physical_attempts += 1
        return self.response


def envelope(option_ids, probabilities, *, choice=None, model=jc.JEV_DEFAULT_MODEL,
             confidence=0.5, question_id="candidate", usage=None):
    peak = max(probabilities, key=probabilities.get) if probabilities else None
    return {
        "model": model,
        "answers": {question_id: {
            "type": "choice",
            "choice": choice or peak,
            "probabilities": probabilities,
            "confidence": confidence,
        }},
        "usage": usage if usage is not None else {"input_tokens": 12, "output_tokens": 3},
    }


def spread(labels, total, first=0.5):
    """A 6-option vector with the given total, peaking on ``labels[0]``."""

    rest = (total - first) / (len(labels) - 1)
    return {label: (first if index == 0 else rest) for index, label in enumerate(labels)}


class CodecV2Tests(unittest.TestCase):
    def setUp(self):
        self.instance = planning_low_instances(1)[0]
        self.labels = sorted(self.instance.solutions)

    def parse(self, probabilities, **kwargs):
        adapter = v2.JevChoiceAdapterV2(ScriptedChoiceClient(envelope(self.labels, probabilities, **kwargs)))
        state = adapter.build_state(self.instance, "A", "ISO")
        return adapter, adapter.parse(state, envelope(self.labels, probabilities, **kwargs))

    def test_sum_exactly_one_is_exact_and_valid(self):
        probs = spread(self.labels, 1.0, first=0.5)
        _, response = self.parse(probs)
        self.assertEqual(response.status, "complete")
        self.assertEqual(response.normalization_tier, "exact")
        self.assertTrue(response.renormalized)
        self.assertAlmostEqual(sum(response.probabilities.values()), 1.0, places=9)
        self.assertAlmostEqual(sum(response.raw_probabilities.values()), 1.0, places=9)

    def test_exact_tier_is_also_rescaled_by_its_raw_sum(self):
        probs = spread(self.labels, 1.0 - 5e-7, first=0.5)  # |dev| = 5e-7 <= 1e-6 -> exact
        _, response = self.parse(probs)
        self.assertEqual(response.status, "complete")
        self.assertEqual(response.normalization_tier, "exact")
        self.assertTrue(response.renormalized)
        raw_total = sum(response.raw_probabilities.values())
        self.assertAlmostEqual(sum(response.probabilities.values()), 1.0, places=12)
        for option_id, value in response.raw_probabilities.items():
            self.assertAlmostEqual(response.probabilities[option_id], value / raw_total, places=12)
        self.assertNotEqual(dict(response.probabilities), dict(response.raw_probabilities))

    def test_boundary_sums_are_complete_renormalized(self):
        for total in (0.99, 1.01):
            _, response = self.parse(spread(self.labels, total))
            self.assertEqual(response.status, "complete", total)
            self.assertEqual(response.normalization_tier, "complete_renormalized")
            self.assertTrue(response.renormalized)
            self.assertAlmostEqual(sum(response.probabilities.values()), 1.0, places=9)
            self.assertAlmostEqual(sum(response.raw_probabilities.values()), total, places=6)

    def test_just_inside_and_outside_boundaries(self):
        _, inside_high = self.parse(spread(self.labels, 1.00999, first=0.51))
        self.assertEqual(inside_high.normalization_tier, "complete_renormalized")
        _, outside_high = self.parse(spread(self.labels, 1.0101, first=0.51))
        self.assertEqual(outside_high.normalization_tier, "not_normalized_suspect")
        _, inside_low = self.parse(spread(self.labels, 0.99001))
        self.assertEqual(inside_low.normalization_tier, "complete_renormalized")
        _, outside_low = self.parse(spread(self.labels, 0.9899))
        self.assertEqual(outside_low.normalization_tier, "not_normalized_suspect")

    def test_suspect_through_hard_ceiling_and_hard_above(self):
        _, at_ceiling = self.parse(spread(self.labels, 1.049, first=0.55))
        self.assertEqual(at_ceiling.normalization_tier, "not_normalized_suspect")
        self.assertEqual(at_ceiling.status, "invalid")
        self.assertEqual(at_ceiling.error_class, "not_normalized_suspect")
        _, hard = self.parse(spread(self.labels, 1.06, first=0.6))
        self.assertEqual(hard.normalization_tier, "not_normalized_hard")
        self.assertEqual(hard.status, "invalid")
        self.assertEqual(hard.error_class, "not_normalized_hard")

    def test_invalid_shapes_are_never_repaired(self):
        _, negative = self.parse({self.labels[0]: 1.1, self.labels[1]: -0.1,
                                  **{label: 0.0 for label in self.labels[2:]}})
        self.assertEqual(negative.status, "invalid")
        self.assertEqual(negative.error_class, "negative_probability")
        self.assertEqual(negative.probabilities, {})

        _, non_finite = self.parse({self.labels[0]: float("inf"),
                                    **{label: 0.0 for label in self.labels[1:]}})
        self.assertEqual(non_finite.error_class, "non_finite_probability")
        self.assertEqual(non_finite.probabilities, {})

        _, empty = self.parse({})
        self.assertEqual(empty.error_class, "missing_probabilities")

        mismatched = {label: 0.1 for label in self.labels[:-1]}
        _, mismatch = self.parse(mismatched)
        self.assertEqual(mismatch.error_class, "mismatched_option_set")

    def test_raw_vector_is_retained_on_invalid_normalization(self):
        probs = spread(self.labels, 1.06, first=0.6)
        adapter, response = self.parse(probs)
        self.assertEqual(response.status, "invalid")
        self.assertEqual(response.normalization_tier, "not_normalized_hard")
        self.assertEqual(set(response.raw_probabilities), set(self.labels))
        self.assertAlmostEqual(response.diagnostics.raw_probability_sum, sum(probs.values()), places=9)
        state = adapter.build_state(self.instance, "A", "ISO")
        record = adapter.record(state, response)
        self.assertEqual(record["raw_probabilities"], response.raw_probabilities)
        self.assertFalse(record["raw_response_retained"])
        self.assertIsNotNone(record["probability_diagnostics"])

    def test_normalized_metrics_and_argmax_preservation(self):
        probs = spread(self.labels, 0.99)
        _, response = self.parse(probs)
        self.assertTrue(response.renormalized)
        self.assertTrue(response.diagnostics.argmax_preserved)
        self.assertEqual(set(response.diagnostics.raw_argmax_set),
                         {max(response.probabilities, key=response.probabilities.get)})
        feasible = sorted(self.instance.private_solutions["A"])
        metrics = v2.distribution_metrics(response.probabilities, target_id=self.instance.target,
                                          feasible_set=feasible)
        raw_metrics = v2.distribution_metrics(response.raw_probabilities, target_id=self.instance.target,
                                              feasible_set=feasible)
        self.assertNotAlmostEqual(metrics["p_target"], raw_metrics["p_target"], places=9)
        self.assertAlmostEqual(metrics["entropy_bits"], v2.entropy_bits(response.probabilities), places=9)
        self.assertAlmostEqual(metrics["brier_score"],
                               v2.brier_score(response.probabilities, self.instance.target), places=9)
        self.assertEqual(metrics["log_loss"], v2.log_loss(response.probabilities, self.instance.target))

    def test_selection_is_validated_against_the_normalized_argmax(self):
        probs = spread(self.labels, 0.99)
        adapter = v2.JevChoiceAdapterV2(ScriptedChoiceClient(envelope(self.labels, probs)))
        state = adapter.build_state(self.instance, "A", "ISO")
        real_normalized = v2.normalized_metric_vector

        def swapped(probabilities, diagnostics, problems):
            used = real_normalized(probabilities, diagnostics, problems)
            if not used:
                return used
            peak = max(used, key=used.get)
            runner_up = sorted(used, key=used.get)[-2]
            used = dict(used)
            used[peak], used[runner_up] = used[runner_up], used[peak]
            return used

        v2.normalized_metric_vector = swapped
        try:
            response = adapter.parse(state, envelope(self.labels, probs))
        finally:
            v2.normalized_metric_vector = real_normalized
        self.assertEqual(response.status, "invalid")
        self.assertEqual(response.error_class, "argmax_shifted_on_renormalization")

    def test_argmax_shift_fails_closed(self):
        probs = spread(self.labels, 0.99)
        adapter = v2.JevChoiceAdapterV2(ScriptedChoiceClient(envelope(self.labels, probs)))
        state = adapter.build_state(self.instance, "A", "ISO")
        real_check = v2._argmax_preserved
        v2._argmax_preserved = lambda raw_argmax_set, normalized: False
        try:
            response = adapter.parse(state, envelope(self.labels, probs))
        finally:
            v2._argmax_preserved = real_check
        self.assertEqual(response.status, "invalid")
        self.assertEqual(response.error_class, "argmax_shifted_on_renormalization")


class V1CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.instance = planning_low_instances(1)[0]
        self.labels = sorted(self.instance.solutions)

    def test_v1_remains_strict(self):
        probs = spread(self.labels, 1.01)
        v1_adapter = jc.JevChoiceAdapter(ScriptedChoiceClient(envelope(self.labels, probs)))
        v1_state = v1_adapter.build_state(self.instance, "A", "ISO")
        v1_response = v1_adapter.parse(v1_state, envelope(self.labels, probs))
        self.assertEqual(v1_response.status, "invalid")
        self.assertEqual(v1_response.error_class, "not_normalized")
        v2_adapter = v2.JevChoiceAdapterV2(ScriptedChoiceClient(envelope(self.labels, probs)))
        v2_response = v2_adapter.parse(v2_adapter.build_state(self.instance, "A", "ISO"),
                                       envelope(self.labels, probs))
        self.assertEqual(v2_response.status, "complete")
        self.assertEqual(v2_response.normalization_tier, "complete_renormalized")

    def test_protocol_key_separation(self):
        v1_key = jc.jev_choice_protocol_key()
        v2_key = v2.jev_choice_protocol_key_v2()
        self.assertNotEqual(v1_key, v2_key)
        self.assertTrue(v1_key.startswith(jc.JEV_PROTOCOL_KEY_PREFIX))
        self.assertTrue(v2_key.startswith(v2.JEV_V2_PROTOCOL_KEY_PREFIX))
        self.assertFalse(v2.is_jev_v2_protocol_key(v1_key))
        self.assertFalse(jc.is_jev_protocol_key(v2_key))
        self.assertTrue(v2.is_any_jev_protocol_key(v1_key))
        self.assertTrue(v2.is_any_jev_protocol_key(v2_key))

    def test_v2_key_reproducible_and_settings_scoped(self):
        self.assertEqual(v2.jev_choice_protocol_key_v2(), v2.jev_choice_protocol_key_v2())
        self.assertNotEqual(v2.jev_choice_protocol_key_v2(model="jev-1.13.1"),
                            v2.jev_choice_protocol_key_v2())
        self.assertNotEqual(v2.jev_choice_protocol_key_v2(max_retries=0),
                            v2.jev_choice_protocol_key_v2())

    def test_mixed_key_assertion(self):
        v2_key = v2.jev_choice_protocol_key_v2()
        self.assertEqual(v2.assert_single_jev_v2_protocol_key(
            [{"protocol_key": v2_key}, {"protocol_key": v2_key}]), v2_key)
        with self.assertRaises(ValueError):
            v2.assert_single_jev_v2_protocol_key([{"protocol_key": jc.jev_choice_protocol_key()}])


class ClassificationUnitTests(unittest.TestCase):
    def test_tier_boundaries(self):
        self.assertEqual(v2.classify_normalization(0.0), "exact")
        self.assertEqual(v2.classify_normalization(1e-6), "exact")
        self.assertEqual(v2.classify_normalization(1e-6 + 1e-9), "complete_renormalized")
        self.assertEqual(v2.classify_normalization(1e-2), "complete_renormalized")
        self.assertEqual(v2.classify_normalization(1e-2 + 1e-3), "not_normalized_suspect")
        self.assertEqual(v2.classify_normalization(0.05), "not_normalized_suspect")
        self.assertEqual(v2.classify_normalization(0.05 + 1e-6), "not_normalized_hard")

    def test_non_finite_values_are_json_safe(self):
        raw, diagnostics, problems = v2.diagnose_probability_vector(
            {"a": float("nan"), "b": float("inf")}, ["a", "b"])
        self.assertEqual(problems, ["non_finite_probability"])
        self.assertEqual(raw["a"], "nan")
        self.assertEqual(raw["b"], "inf")
        self.assertFalse(diagnostics.all_finite)
        self.assertIsNone(diagnostics.raw_probability_sum)
        json.dumps(raw, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
