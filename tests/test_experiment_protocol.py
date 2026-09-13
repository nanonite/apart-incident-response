import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from apart_incident_response.events import EventStore
from apart_incident_response.experiment import BatchRunner, validate_config


class SlowAdapter:
    source = 'fixture'
    model = 'slow-test'
    def metadata(self):
        return {'source': self.source, 'model': self.model}
    def generate(self, *args, **kwargs):
        time.sleep(0.05)
        raise AssertionError('should have timed out')


class ExperimentProtocolTests(unittest.TestCase):
    def test_minute_defaults(self):
        cfg = validate_config({'adapter': 'fixture'})
        self.assertEqual((cfg['steps'], cfg['unlock_step'], cfg['schedule']), (5, 3, 'minute_checkpoints'))
        self.assertEqual((cfg['minute_seconds'], cfg['deadline_seconds']), (60, 300))

    def test_nonfinite_budgets_are_rejected(self):
        for value in (float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                validate_config({'deadline_seconds': value})

    def test_run_budget_limits_pending_generation_and_preserves_missingness(self):
        with tempfile.TemporaryDirectory() as d:
            store = EventStore(Path(d) / 'events.sqlite')
            clock = [0.0]
            def expired_generation(*args):
                self.assertEqual(args[-1], 0.02)
                clock[0] = 0.02
                return None, 20.0, TimeoutError('generation deadline exceeded')
            with patch('apart_incident_response.experiment.time.monotonic', side_effect=lambda: clock[0]), \
                 patch('apart_incident_response.experiment.timed_generate', side_effect=expired_generation):
                BatchRunner(store).run({'adapter': 'fixture', 'task_ids': ['inventory'],
                    'conditions': ['C0'], 'steps': 5, 'unlock_step': 3,
                    'deadline_seconds': 0.02, 'minute_seconds': 60}, adapter=SlowAdapter())
            events = store.read()
            requests = [e for e in events if e['kind'] == 'generation_started']
            self.assertEqual(len(requests), 1)
            self.assertLessEqual(requests[0]['payload']['request_deadline_seconds'], 0.02)
            updates = [e for e in events if e['kind'] == 'task_update']
            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0]['payload']['termination_state'], 'stalled_no_generation')
            self.assertIn('run_elapsed_seconds', updates[0]['payload'])
            finished = next(e for e in events if e['kind'] == 'run_finished')
            self.assertEqual(finished['payload']['status'], 'over_deadline')
            self.assertEqual(events[-1]['payload']['status'], 'completed_with_errors')

    def test_engagement_mode_is_explicit_in_observation_and_update(self):
        with tempfile.TemporaryDirectory() as d:
            store = EventStore(Path(d) / 'events.sqlite')
            batch = BatchRunner(store).run({'adapter': 'fixture', 'task_ids': ['database-insider'],
                'conditions': ['C1'], 'steps': 2, 'unlock_step': 1, 'engagement_mode': 'peer_review'})
            events = [e for e in store.read() if e['batch_id'] == batch]
            self.assertTrue(all(e['payload']['engagement_mode'] == 'peer_review' for e in events
                                if e['kind'] in ('agent_observation', 'task_update')))

    def test_c2_unlock_and_difficulty_are_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            store = EventStore(Path(d) / 'events.sqlite')
            batch = BatchRunner(store).run({'adapter': 'fixture', 'task_ids': ['inventory'],
                'conditions': ['C2'], 'steps': 4, 'unlock_step': 3})
            events = [e for e in store.read() if e['batch_id'] == batch]
            obs = [e for e in events if e['kind'] == 'agent_observation' and e['payload']['agent_id'] == 'A']
            self.assertFalse(obs[0]['payload']['communication_available'])
            self.assertTrue(obs[3]['payload']['communication_available'])
            self.assertEqual({e['payload']['difficulty'] for e in events if e['kind'] == 'task_update'}, {1})
            peer = [e for e in events if e['kind'] == 'task_update' and e['payload']['agent_id'] == 'B' and e['payload']['step'] == 0][0]
            self.assertIn(peer['event_id'], obs[3]['payload']['visible_event_ids'])

    def test_logprobs_config_wiring(self):
        self.assertFalse(validate_config({'adapter': 'fixture'})['logprobs'])
        self.assertTrue(validate_config({'adapter': 'fixture', 'logprobs': True})['logprobs'])
        with self.assertRaises(ValueError):
            validate_config({'adapter': 'fixture', 'logprobs': 'yes'})
        with tempfile.TemporaryDirectory() as d:
            store = EventStore(Path(d) / 'events.sqlite')
            batch = BatchRunner(store).run({'adapter': 'fixture', 'task_ids': ['inventory'],
                'conditions': ['C0'], 'steps': 2, 'unlock_step': 1, 'logprobs': True})
            updates = [e for e in store.read() if e['batch_id'] == batch and e['kind'] == 'task_update']
            self.assertTrue(updates)
            self.assertTrue(all(e['payload']['logprobs_available'] is False for e in updates))
            self.assertTrue(all(e['payload']['logprob_token_count'] == 0 for e in updates))

    def test_timeout_keeps_agent_minute_grid_with_stalled_update(self):
        with tempfile.TemporaryDirectory() as d:
            store = EventStore(Path(d) / 'events.sqlite')
            batch = BatchRunner(store).run({'adapter': 'fixture', 'task_ids': ['inventory'],
                'conditions': ['C0'], 'steps': 2, 'unlock_step': 1, 'timeout_seconds': 0.001,
                'minute_seconds': 0.001}, adapter=SlowAdapter())
            events = [e for e in store.read() if e['batch_id'] == batch]
            self.assertTrue(any(e['kind'] == 'minute_violation' for e in events))
            updates = [e for e in events if e['kind'] == 'task_update']
            self.assertTrue(updates)
            self.assertTrue(all(e['payload']['submitted'] for e in updates))
            self.assertTrue(any(e['payload']['termination_state'] == 'stalled_no_generation' for e in updates))


if __name__ == '__main__':
    unittest.main()
