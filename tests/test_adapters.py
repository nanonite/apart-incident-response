import unittest
import json

from apart_incident_response.adapters import FixtureAdapter, OllamaAdapter


class AdapterTests(unittest.TestCase):
    def test_ollama_feedback_schema_has_no_goal_choice(self):
        class RecordingAdapter(OllamaAdapter):
            def request(self, route, payload=None, timeout=180):
                self.payload = payload
                return {'message': {'content': '{}'}, 'done_reason': 'stop'}
        adapter = RecordingAdapter()
        content = {'update_contract': 'locked-database-v1', 'agent_role': 'feedback_only'}
        adapter.generate([{'role': 'user', 'content': json.dumps(content)}], 17, 220,
                         {'feedback_only': 'Feedback only'})
        schema = adapter.payload['format']
        self.assertEqual(schema['properties']['answer_class']['enum'], ['feedback_only'])
        self.assertEqual(schema['properties']['candidate_key']['enum'], [''])
        self.assertEqual(set(schema['required']), {'response_text', 'answer_class', 'key_insights', 'candidate_key'})
        self.assertFalse(adapter.payload['stream'])
    def test_fixture_shape(self):
        result = FixtureAdapter().generate([{'role': 'user', 'content': '{}'}], 1, 100, {'yes': 'yes'})
        self.assertIn('raw_response', result)
        self.assertEqual(result['model'], FixtureAdapter.model)

    def test_ollama_endpoint_validation(self):
        with self.assertRaises(ValueError):
            OllamaAdapter('model', endpoint='file:///tmp/nope')


if __name__ == '__main__':
    unittest.main()
