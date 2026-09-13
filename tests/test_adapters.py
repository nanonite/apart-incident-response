import unittest

from apart_incident_response.adapters import FixtureAdapter, OllamaAdapter


class AdapterTests(unittest.TestCase):
    def test_fixture_shape(self):
        result = FixtureAdapter().generate([{'role': 'user', 'content': '{}'}], 1, 100, {'yes': 'yes'})
        self.assertIn('raw_response', result)
        self.assertEqual(result['model'], FixtureAdapter.model)

    def test_ollama_endpoint_validation(self):
        with self.assertRaises(ValueError):
            OllamaAdapter('model', endpoint='file:///tmp/nope')


if __name__ == '__main__':
    unittest.main()
