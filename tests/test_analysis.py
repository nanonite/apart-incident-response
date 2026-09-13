import unittest

from apart_incident_response.analysis import analyze, entropy, checkpoint_grid, intervention_changes


class AnalysisTests(unittest.TestCase):
    def test_intervention_contrast_preserves_negative_sign_missingness_and_sources(self):
        metrics = [dict(task_id='x', agent_id='B', condition_id=c, step=s, entropy_bits=h,
                        sample_count=2, source_event_ids=[c+str(s)])
                   for c, s, h in [('C2', 2, 1.0), ('C2', 3, 0.0), ('C0', 2, 0.0), ('C0', 3, 0.5)]]
        row = intervention_changes(metrics, 3)[0]
        self.assertEqual(row['delta_bits'], -1.0)
        self.assertEqual(row['difference_in_deltas_bits'], -1.5)
        self.assertEqual(len(row['source_event_ids']), 4)
        self.assertFalse(row['causal_claim'])
        metrics[0]['entropy_bits'] = None
        self.assertIsNone(intervention_changes(metrics, 3)[0]['delta_bits'])
    def test_grid_exports_unstarted_scenarios_as_missing_without_agent_outputs(self):
        events = [{'kind': 'batch_started', 'event_id': 's', 'batch_id': 'batch', 'run_id': None,
                   'timestamp': '2026-09-13T00:00:00Z', 'payload': {'config': {
                       'task_ids': ['inventory'], 'conditions': ['C0', 'C2'], 'repeats': 2, 'steps': 5, 'unlock_step': 3}}}]
        rows = checkpoint_grid(events)
        self.assertEqual(len(rows), 40)
        self.assertTrue(all(row['submission_status'] == 'missing' for row in rows))
        self.assertTrue(all(row['response_text'] is None and not row['source_event_ids'] for row in rows))
        self.assertTrue(all(row['planned_unlock_step'] == 3 for row in rows if row['condition_id'] == 'C2'))
        self.assertEqual(len(events), 1)
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
