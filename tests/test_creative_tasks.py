import tempfile
import unittest
from pathlib import Path

from apart_incident_response.events import EventStore
from apart_incident_response.experiment import BatchRunner
from apart_incident_response.task_updates import parse_update
from apart_incident_response.tasks import task_by_id


class CreativeTaskTests(unittest.TestCase):
    def test_catalog_has_bounded_poetry_and_historical_critical_tasks(self):
        poetry = task_by_id('poetry-duet')
        history = task_by_id('civic-law-1943')
        self.assertEqual(poetry['update_contract'], 'creative-collab-v1')
        self.assertEqual(poetry['max_words'], 5000)
        self.assertIn('original', poetry['question'].lower())
        self.assertIn('critical', history['design'].lower())
        self.assertIn('educational', history['safety_note'].lower())

    def test_fixture_creative_batch_is_complete_and_annotated(self):
        raw = {'task_ids': ['poetry-duet', 'civic-law-1943'], 'conditions': ['C0', 'C2'],
               'steps': 3, 'repeats': 1, 'adapter': 'fixture', 'unlock_step': 1,
               'deadline_seconds': 30, 'batch_timeout_seconds': 60}
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / 'events.sqlite')
            BatchRunner(store).run(raw)
            events = store.read()
        updates = [e for e in events if e['kind'] == 'task_update']
        evaluations = [e for e in events if e['kind'] == 'evaluator_result']
        self.assertEqual(len(updates), 24)
        self.assertEqual(len(evaluations), 24)
        self.assertTrue(all(e['payload']['max_words'] == 5000 for e in evaluations))
        self.assertTrue(all(e['payload']['within_word_limit'] for e in evaluations))
        self.assertTrue(any(e['kind'] == 'communication_unlocked' for e in events))

    def test_creative_contract_rejects_overlong_artifact(self):
        task = task_by_id('poetry-duet')
        content = {'update_contract': 'creative-collab-v1', 'agent_role': 'opening_poet',
                   'allowed_evidence_ids': ['P1'], 'visible_message_ids': [], 'max_words': 2}
        raw = '{"response_text":"one two three", "answer_class":"draft", "key_insights":[], "evidence_ids":["P1"], "referenced_message_ids":[], "message_type":"draft", "rejected_option":"", "request_peer_context":false}'
        with self.assertRaises(ValueError):
            parse_update(raw, content, task['choices'])


if __name__ == '__main__':
    unittest.main()
