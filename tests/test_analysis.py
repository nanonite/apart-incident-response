import unittest

from apart_incident_response.analysis import analyze, entropy


class AnalysisTests(unittest.TestCase):
    def test_entropy_requires_a_distribution(self):
        self.assertAlmostEqual(entropy([0.5, 0.5]), 1.0)
        with self.assertRaises(ValueError):
            entropy([1, 1])

    def test_difficulty_is_preserved_in_metric_rows(self):
        events = [
            {'kind': 'task_update', 'event_id': 'a', 'payload': {'task_id': 'x', 'difficulty': 4, 'condition_id': 'C0', 'step': 0, 'agent_id': 'A', 'answer_class': 'one', 'source': 'fixture'}},
            {'kind': 'task_update', 'event_id': 'b', 'payload': {'task_id': 'x', 'difficulty': 4, 'condition_id': 'C0', 'step': 0, 'agent_id': 'A', 'answer_class': 'two', 'source': 'fixture'}},
        ]
        rows = analyze(events)
        self.assertEqual(rows[0]['difficulty'], 4)
        self.assertEqual(rows[0]['entropy_bits'], 1.0)


if __name__ == '__main__':
    unittest.main()
