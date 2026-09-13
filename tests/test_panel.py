import json
import tempfile
import unittest
from pathlib import Path

from apart_incident_response import panel
from apart_incident_response.events import EventStore
from apart_incident_response.experiment import BatchRunner

CONFIG = {'adapter': 'fixture', 'conditions': ['C0', 'C1', 'C2'], 'task_ids': ['inventory'],
          'steps': 2, 'unlock_step': 1, 'repeats': 1}


def batch_store():
    temp = tempfile.TemporaryDirectory()
    store = EventStore(Path(temp.name) / 'obs.sqlite')
    batch = BatchRunner(store).run(CONFIG)
    return temp, store, batch


def run_events(data, run):
    return [e for e in data['events'] if e.get('run_id') == run['id'] or not e.get('run_id')]


class PanelStateTests(unittest.TestCase):
    def test_state_is_json_serializable_and_carries_audit_and_metrics(self):
        temp, store, _ = batch_store()
        self.addCleanup(temp.cleanup)
        data = panel.state(store)
        json.dumps(data, allow_nan=False)
        self.assertEqual(data['audit'], [])
        self.assertTrue(data['metrics'])
        self.assertTrue(data['batches'])

    def test_audit_trail_records_researcher_actions_in_order(self):
        temp, store, batch = batch_store()
        self.addCleanup(temp.cleanup)
        panel.audit_action(store, batch, 'export_bundle')
        panel.audit_action(store, batch, 'snapshot_written', path='demo.json')
        audit = panel.state(store)['audit']
        self.assertEqual([a['action'] for a in audit], ['export_bundle', 'snapshot_written'])
        self.assertEqual(audit[1]['path'], 'demo.json')
        self.assertTrue(audit[0]['timestamp'])

    def test_projection_isolated_agent_never_sees_peer_history(self):
        temp, store, _ = batch_store()
        self.addCleanup(temp.cleanup)
        data = panel.state(store)
        run = next(r for r in data['runs'] if r['condition_id'] == 'C0')
        events = run_events(data, run)
        proj = panel.projection_step(events, 1)
        peer_b = {e['event_id'] for e in events if e['kind'] == 'task_update'
                  and e['payload'].get('agent_id') == 'B' and e['payload'].get('step') == 0}
        self.assertFalse(set(proj['agents']['A']['visible_event_ids']) & peer_b)
        self.assertIs(proj['communication_available']['A'], False)

    def test_projection_global_contains_truth_agents_cannot_see(self):
        temp, store, _ = batch_store()
        self.addCleanup(temp.cleanup)
        data = panel.state(store)
        run = next(r for r in data['runs'] if r['condition_id'] == 'C0')
        events = run_events(data, run)
        proj = panel.projection_step(events, 0)
        self.assertTrue(any(e['kind'] == 'evaluator_result' for e in proj['global']))
        for agent in ('A', 'B'):
            visible = set(proj['agents'][agent]['visible_event_ids'])
            self.assertFalse(any(e['event_id'] in visible and e['kind'] == 'evaluator_result'
                                 for e in proj['global']))
        self.assertTrue(proj['global'] and proj['note'])

    def test_projection_C2_unlock_retrospectively_reveals_peer_history(self):
        temp, store, _ = batch_store()
        self.addCleanup(temp.cleanup)
        data = panel.state(store)
        run = next(r for r in data['runs'] if r['condition_id'] == 'C2')
        events = run_events(data, run)
        before = panel.projection_step(events, 0)
        after = panel.projection_step(events, 1)
        self.assertIs(before['communication_available']['A'], False)
        self.assertIs(after['communication_available']['A'], True)
        visible_after = set(after['agents']['A']['visible_event_ids'])
        self.assertTrue(any(e['event_id'] in visible_after for e in events
                            if e['kind'] == 'task_update' and e['payload'].get('agent_id') == 'B'))

    def test_fixture_batch_preserves_complete_agent_by_step_grid(self):
        temp, store, _ = batch_store()
        self.addCleanup(temp.cleanup)
        data = panel.state(store)
        updates = {}
        for e in data['events']:
            if e['kind'] == 'task_update':
                updates.setdefault(e['run_id'], []).append(e)
        self.assertTrue(updates)
        for us in updates.values():
            steps = sorted({e['payload']['step'] for e in us})
            self.assertEqual(len(steps), 2)
            for s in steps:
                self.assertEqual(sorted(e['payload']['agent_id'] for e in us if e['payload']['step'] == s),
                                 ['A', 'B'])


if __name__ == '__main__':
    unittest.main()