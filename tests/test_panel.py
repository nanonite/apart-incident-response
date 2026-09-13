import json
import tempfile
import unittest
import io
import zipfile
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
    def test_open_log_is_unverified_and_export_audit_does_not_reset_agent_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / 'events.sqlite')
            event = store.append('orphan', 'batch_started', {'config': {}})
            panel.audit_action(store, 'orphan', 'export_bundle')
            data = panel.App(store).snapshot()
            self.assertEqual(data['execution']['state'], 'unverified')
            self.assertFalse(data['can_stop'])
            self.assertEqual(data['live_activity']['last_event_at'], event['timestamp'])
            self.assertEqual(data['batch']['status'], 'running')
            self.assertEqual(len(store.read()), 2)

    def test_live_request_is_generating_and_queued_without_invented_answers(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / 'events.sqlite')
            store.append('live', 'batch_started', {'config': {}})
            store.append('live', 'run_started', {'task_id': 'inventory', 'condition_id': 'C0', 'repeat': 0}, 'run')
            for agent in ('A', 'B'):
                store.append('live', 'agent_observation', {'agent_id': agent, 'step': 0, 'messages': [],
                    'visible_message_ids': [], 'communication_available': False}, 'run')
            started = store.append('live', 'generation_started', {'agent_id': 'A', 'step': 0}, 'run')
            live = panel.state(store)['live_activity']
            self.assertEqual(live['agents']['A']['state'], 'generating')
            self.assertEqual(live['agents']['A']['last_event_id'], started['event_id'])
            self.assertEqual(live['agents']['B']['state'], 'queued')
            self.assertEqual(live['agents']['A']['updates'], [])
            self.assertFalse(live['exports']['ready'])
            self.assertTrue(live['exports']['available'])
            self.assertTrue(live['exports']['partial'])
            self.assertEqual(live['shared_history'], [])
            store.append('live', 'run_finished', {'status': 'stopped'}, 'run')
            store.append('live', 'batch_finished', {'status': 'stopped'})
            live = panel.state(store)['live_activity']
            self.assertEqual(live['agents']['A']['state'], 'interrupted')
            self.assertEqual(live['agents']['B']['state'], 'interrupted')
            self.assertTrue(live['exports']['ready'])
            self.assertFalse(live['exports']['partial'])
            self.assertEqual(live['exports']['bundle_url'], '/api/export?batch=live')

    def test_live_shared_history_contains_only_delivered_peer_responses(self):
        temp, store, _ = batch_store()
        self.addCleanup(temp.cleanup)
        data = panel.state(store)
        for condition in ('C0', 'C1', 'C2'):
            run = next(r for r in data['runs'] if r['condition_id'] == condition)
            scoped = run_events(data, run)
            live = panel.live_activity(scoped, data['batch'], [run])
            self.assertEqual(live['run']['id'], run['id'])
            if condition == 'C0':
                self.assertEqual(live['shared_history'], [])
            else:
                self.assertEqual(len(live['shared_history']), 2)
                self.assertTrue(all(message['step'] == 0 for message in live['shared_history']))
                self.assertTrue(all('evaluator' not in message and 'private_evidence' not in message for message in live['shared_history']))
                self.assertEqual(live['shared_history'][0]['visible_to'], ['B'])
                self.assertEqual(live['shared_history'][1]['visible_to'], ['A'])
            self.assertEqual(len(live['agents']['A']['updates']), 2)
            self.assertIn('evaluator', live['agents']['A']['updates'][0])

    def test_finished_batch_exports_include_events_responses_and_metrics(self):
        temp, store, _ = batch_store()
        self.addCleanup(temp.cleanup)
        data = panel.state(store)
        self.assertTrue(data['live_activity']['exports']['ready'])
        data['session_key'] = 'must-not-export'
        with zipfile.ZipFile(io.BytesIO(panel.bundle(data))) as archive:
            self.assertTrue({'events.jsonl', 'responses.jsonl', 'metrics.jsonl', 'manifest.json', 'report.md'} <= set(archive.namelist()))
            manifest = json.loads(archive.read('manifest.json'))
            self.assertNotIn('session_key', manifest)
            self.assertEqual(manifest['export_metadata']['kind'], 'completed')
            self.assertIn('| Condition |', archive.read('report.md').decode())
            self.assertEqual(len(archive.read('responses.jsonl').splitlines()), 12)
            grid = [json.loads(line) for line in archive.read('checkpoint-grid.jsonl').splitlines()]
            self.assertEqual(len(grid), 12)
            self.assertTrue(all(row['submission_status'] == 'valid' for row in grid))
            self.assertTrue(all(row['context_hash'] for row in grid))
            self.assertTrue(all(row['task_version'] and row['pair_id'] and row['seed'] == 17 for row in grid))

    def test_active_export_marks_partial_cutoff_and_does_not_invent_responses(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / 'events.sqlite')
            last = store.append('live', 'batch_started', {'source': 'local_model', 'config': {}})
            data = panel.state(store)
            with zipfile.ZipFile(io.BytesIO(panel.bundle(data))) as archive:
                manifest = json.loads(archive.read('manifest.json'))
                meta = manifest['export_metadata']
                self.assertEqual(meta['kind'], 'partial')
                self.assertEqual(meta['batch_status'], 'running')
                self.assertEqual(meta['event_log_cutoff']['event_id'], last['event_id'])
                self.assertEqual(meta['event_log_cutoff']['hash'], last['hash'])
                self.assertEqual(meta['response_count'], 0)
                self.assertEqual(archive.read('responses.jsonl'), b'')
                self.assertIn('**partial**', archive.read('report.md').decode())
            self.assertEqual(len(store.read()), 1)

    def test_panel_launch_accepts_ui_engagement_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / 'events.sqlite')
            app = panel.App(store)
            batch_id = app.launch(dict(CONFIG, task_ids=['database-insider'], engagement_mode='peer_review',
                                       study_id='asymmetric_evidence_v1'))
            app.thread.join(timeout=10)
            self.assertFalse(app.thread.is_alive())
            data = panel.state(store, batch_id)
            self.assertEqual(data['server']['api_version'], panel.PANEL_API_VERSION)
            self.assertEqual(data['batch']['status'], 'completed')
            self.assertEqual(data['batch']['config']['engagement_mode'], 'peer_review')
            self.assertEqual(len([e for e in data['events'] if e['kind'] == 'task_update']), 12)

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
