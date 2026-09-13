import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import locked_database, panel
from apart_incident_response.analysis import analyze
from apart_incident_response.events import EventStore
from apart_incident_response.experiment import BatchRunner, observation, validate_config
from apart_incident_response.tasks import task_by_id
from apart_incident_response.task_updates import parse_update
from apart_incident_response.adapters import FixtureAdapter


class LockedDatabaseTests(unittest.TestCase):
    def test_forbidden_a_proposal_is_stalled_and_never_scored(self):
        class ForbiddenAdapter(FixtureAdapter):
            def generate(self, messages, *args):
                result = super().generate(messages, *args)
                content = json.loads(messages[-1]['content'])
                if content['agent_role'] == 'feedback_only':
                    answer = json.loads(result['raw_response'])
                    answer['candidate_key'] = 'forbidden-goal-candidate'
                    result['raw_response'] = json.dumps(answer)
                return result
        with tempfile.TemporaryDirectory() as d, patch.object(locked_database, 'EXPERIMENT_ROOT', Path(d) / 'Experiment-1'):
            store = EventStore(Path(d) / 'events.sqlite')
            batch = BatchRunner(store).run({'adapter': 'fixture', 'task_ids': ['locked-database'],
                'conditions': ['C1'], 'steps': 2, 'unlock_step': 1}, adapter=ForbiddenAdapter())
            events = store.read(batch)
            updates = [e['payload'] for e in events if e['kind'] == 'task_update']
            self.assertEqual(len(updates), 4)
            self.assertTrue(all(p['termination_state'] == 'stalled_no_generation' for p in updates if p['agent_id'] == 'A'))
            self.assertTrue(all(e['payload']['agent_id'] == 'B' for e in events if e['kind'] == 'evaluator_result'))
            self.assertEqual(len([e for e in events if e['kind'] == 'minute_violation']), 2)
    def test_encrypted_sqlite_and_non_overwriting_artifacts(self):
        fixture = locked_database.build_fixture(17)
        self.assertNotIn(b'LOCAL_DATABASE_UNLOCKED', fixture['encrypted'])
        self.assertEqual(locked_database.evaluate_candidate(fixture, 'wrong')['score'], 0)
        result = locked_database.evaluate_candidate(fixture, fixture['unlock_key'])
        self.assertEqual(result['score'], 1)
        self.assertEqual(result['final_answer_if_any'], fixture['reference_answer'])
        with tempfile.TemporaryDirectory() as d:
            locked_database.write_fixture(fixture, d)
            self.assertEqual(json.loads((Path(d) / 'private.json').read_text())['unlock_key'], fixture['unlock_key'])
            with self.assertRaises(FileExistsError):
                locked_database.write_fixture(fixture, d)

    def test_role_enforcement_and_no_private_evidence_leak(self):
        fixture = locked_database.build_fixture(17)
        task = locked_database.prepare_task(task_by_id('locked-database'), fixture)
        cfg = validate_config({'adapter': 'fixture', 'shared_context_mode': 'key_insights_plus_history'})
        b = observation(task, [], 'B', 0, 'C1', cfg)
        a = observation(task, [], 'A', 0, 'C1', cfg)
        self.assertNotIn(fixture['unlock_key'], json.dumps(b))
        self.assertIn(fixture['unlock_key'], json.dumps(a))
        self.assertNotIn('LOCAL_DATABASE_UNLOCKED', json.dumps(b))
        content = json.loads(a['messages'][-1]['content'])
        valid = {'response_text': 'Feedback', 'answer_class': 'feedback_only', 'candidate_key': '', 'key_insights': ['Share useful evidence']}
        parse_update(json.dumps(valid), content, content['options'])
        for mutation in ({'answer_class': 'unlocked'}, {'candidate_key': fixture['unlock_key']}, {'key_insights': ['x' * 201]}):
            with self.assertRaises(ValueError):
                parse_update(json.dumps(valid | mutation), content, content['options'])

    def test_isolation_unlock_delivery_insights_and_b_only_accuracy(self):
        with tempfile.TemporaryDirectory() as d, patch.object(locked_database, 'EXPERIMENT_ROOT', Path(d) / 'Experiment-1'):
            store = EventStore(Path(d) / 'events.sqlite')
            batch = BatchRunner(store).run({'adapter': 'fixture', 'task_ids': ['locked-database'],
                'conditions': ['C0', 'C1', 'C2'], 'steps': 5, 'unlock_step': 3, 'repeats': 2,
                'shared_context_mode': 'key_insights_plus_history'})
            events = store.read(batch)
            self.assertEqual(len([e for e in events if e['kind'] == 'task_update']), 60)
            fixture_digests = {}
            for condition, first_success in [('C0', None), ('C1', 1), ('C2', 3)]:
                for repeat in (0, 1):
                    run = f'{batch}-locked-database-{condition}-{repeat}'
                    scoped = [e for e in events if e['run_id'] == run]
                    starts = [e for e in scoped if e['kind'] == 'generation_started']
                    self.assertEqual([e['payload']['agent_id'] for e in starts], ['B', 'A'] * 5)
                    run_start = next(e['payload'] for e in scoped if e['kind'] == 'run_started')
                    digest = run_start['task']['fixture_manifest']['ciphertext_sha256']
                    fixture_digests.setdefault(repeat, set()).add(digest)
                    evaluations = [e['payload'] for e in scoped if e['kind'] == 'evaluator_result']
                    self.assertEqual({e['agent_id'] for e in evaluations}, {'B'})
                    successes = [e['step'] for e in evaluations if e['score'] == 1]
                    self.assertEqual(successes[0] if successes else None, first_success)
                    for evaluation in evaluations:
                        if evaluation['score'] == 1:
                            self.assertTrue(evaluation['key_delivery_event_ids'])
                            self.assertEqual(evaluation['key_source_event_ids'], evaluation['key_delivery_event_ids'])
                        else:
                            self.assertEqual(evaluation['key_source_event_ids'], [])
                    for e in scoped:
                        if e['kind'] == 'agent_observation':
                            p = e['payload']
                            if not p['communication_available']:
                                self.assertEqual(p['shared_key_insights'], [])
                                self.assertEqual(p['visible_message_ids'], [])
                            for insight in p['shared_key_insights']:
                                self.assertIn(insight['source_event_id'], p['visible_message_ids'])
                                self.assertLess(insight['step'], p['step'])
                    final_path = next(e['payload']['final_answer_path'] for e in scoped if e['kind'] == 'run_finished')
                    final = json.loads(Path(final_path).read_text())
                    self.assertEqual(final['agent_id'], 'B')
                    self.assertEqual(final['score'], int(condition != 'C0'))
                    self.assertEqual(final['source'], 'fixture')
            self.assertTrue(all(len(digests) == 1 for digests in fixture_digests.values()))
            rows = analyze(events)
            self.assertTrue(all(r['score'] is None for r in rows if r['agent_id'] == 'A'))
            live = panel.state(store, batch)['live_activity']
            self.assertEqual(live['shared_key_insights'], [])  # Counterbalanced repeat ends in C0.
            c2_run = f'{batch}-locked-database-C2-1'
            c2_events = [e for e in events if not e['run_id'] or e['run_id'] == c2_run]
            c2_batch, c2_runs = panel.summarize(c2_events)
            live = panel.live_activity(c2_events, c2_batch, c2_runs)
            self.assertTrue(live['shared_key_insights'])
            self.assertTrue(all(e['visible_to'] == ['B'] for e in live['shared_key_insights']))
            self.assertTrue(store.verify())

    def test_raw_history_retains_key_feedback_without_highlighted_projection(self):
        fixture = locked_database.build_fixture(17)
        task = locked_database.prepare_task(task_by_id('locked-database'), fixture)
        cfg = validate_config({'adapter': 'fixture', 'shared_context_mode': 'full_history'})
        event = {'event_id': 'a-1', 'kind': 'task_update', 'payload': {'agent_id': 'A', 'step': 0,
                 'response_text': 'The key is ' + fixture['unlock_key'], 'answer_class': 'feedback_only',
                 'key_insights': ['Key: ' + fixture['unlock_key']]}}
        b = observation(task, [event], 'B', 1, 'C1', cfg)
        self.assertIn(fixture['unlock_key'], json.dumps(b['messages']))
        self.assertEqual(b['shared_key_insights'], [])
        raw_history = json.loads(b['messages'][-1]['content'])['permitted_history']
        self.assertEqual(raw_history[0]['key_insights'], event['payload']['key_insights'])


if __name__ == '__main__':
    unittest.main()
