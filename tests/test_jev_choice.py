import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from apart_incident_response.jev_choice import (
    INVALID_RESPONSE_CLASSES,
    JevChoiceAdapter,
    JevChoiceClient,
    load_jev_credentials,
)
from apart_incident_response.jev_protocol import planning_low_instances


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class ScriptedChoiceClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.last_request = None

    def complete(self, request):
        self.last_request = request
        if self.error is not None:
            raise self.error
        return self.response


def equal_weights(labels):
    return {label: 1.0 / len(labels) for label in labels}


class JevChoiceAdapterTests(unittest.TestCase):
    def instance(self):
        return planning_low_instances(1)[0]

    def test_iso_state_excludes_joint_and_peer_clues(self):
        instance = self.instance()
        adapter = JevChoiceAdapter(ScriptedChoiceClient({}))
        iso = adapter.build_state(instance, "A", "ISO")
        full = adapter.build_state(instance, "A", "FULL")
        self.assertEqual(set(iso.clues), set(instance.private_clues["A"]))
        for peer_clue in instance.private_clues["B"]:
            self.assertNotIn(peer_clue, iso.clues)
        self.assertEqual(set(full.clues), {claim.text for claim in instance.claims})
        self.assertNotIn("joint_candidate_labels", iso.prompt)
        self.assertEqual(iso.options[0].option_id, sorted(instance.solutions)[0])

    def test_complete_normalizes_and_maps_submission(self):
        instance = self.instance()
        labels = sorted(instance.solutions)
        probabilities = {label: 0.1 for label in labels}
        probabilities[instance.target] = 1.0 - 0.1 * (len(labels) - 1)
        client = ScriptedChoiceClient({"probabilities": probabilities, "model": "jev-choice-1",
                                       "request_id": "req-1", "usage": {"cost": 0.0}})
        adapter = JevChoiceAdapter(client)
        state = adapter.build_state(instance, "A", "ISO")
        response = adapter.complete(state)
        self.assertEqual(response.status, "complete")
        self.assertAlmostEqual(sum(response.probabilities.values()), 1.0)
        submission = adapter.map_submission(response)
        self.assertEqual(submission, instance.target)
        self.assertTrue(instance.validate(submission)["accepted"])
        record = adapter.record(state, response)
        self.assertFalse(record["raw_response_retained"])
        self.assertAlmostEqual(record["probability_sum"], 1.0)
        self.assertEqual(client.last_request["options"], labels)

    def test_rejects_mismatched_not_normalized_and_negative(self):
        instance = self.instance()
        adapter = JevChoiceAdapter(ScriptedChoiceClient({}))
        state = adapter.build_state(instance, "A", "ISO")
        labels = [option.option_id for option in state.options]

        mismatched = dict(equal_weights(labels))
        mismatched.pop(labels[0])
        self.assertEqual(adapter.parse(state, {"probabilities": mismatched}).error_class,
                         "mismatched_option_set")

        not_normalized = {label: 0.5 for label in labels}
        self.assertEqual(adapter.parse(state, {"probabilities": not_normalized}).error_class,
                         "not_normalized")

        negative = dict(equal_weights(labels))
        negative[labels[0]] = -0.1
        self.assertEqual(adapter.parse(state, {"probabilities": negative}).error_class,
                         "negative_probability")

    def test_rejects_oversized_option_set(self):
        instance = self.instance()
        adapter = JevChoiceAdapter(ScriptedChoiceClient({}), max_options=2)
        state = adapter.build_state(instance, "A", "ISO")
        response = adapter.complete(state)
        self.assertEqual(response.status, "invalid")
        self.assertEqual(response.error_class, "oversized_option_set")

    def test_transport_and_malformed_taxonomy(self):
        instance = self.instance()
        state = JevChoiceAdapter(ScriptedChoiceClient({})).build_state(instance, "A", "ISO")
        transport = JevChoiceAdapter(ScriptedChoiceClient(error=RuntimeError("boom"))).complete(state)
        self.assertEqual(transport.error_class, "transport_error")
        malformed = JevChoiceAdapter(ScriptedChoiceClient({})).complete(state)
        self.assertEqual(malformed.error_class, "missing_probabilities")
        self.assertTrue(set(INVALID_RESPONSE_CLASSES) >= {transport.error_class, malformed.error_class})

    def test_record_prompt_hash_is_reproducible(self):
        instance = self.instance()
        client = ScriptedChoiceClient({"probabilities": equal_weights(sorted(instance.solutions))})
        adapter = JevChoiceAdapter(client)
        state = adapter.build_state(instance, "A", "COMM", visible_messages=[{"text": "precedes=a>b"}])
        again = adapter.build_state(instance, "A", "COMM", visible_messages=[{"text": "precedes=a>b"}])
        self.assertEqual(state.prompt_hash, again.prompt_hash)
        response = adapter.complete(state)
        self.assertEqual(response.status, "complete")
        self.assertEqual(response.prompt_hash, state.prompt_hash)


class JevCredentialTests(unittest.TestCase):
    KEY = "typesafe-test-key-0123456789abcdef"

    def instance(self):
        return planning_low_instances(1)[0]

    def test_credentials_load_from_file_without_leaking(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "jev.env"
            env_file.write_text(f"typesafe={self.KEY}\n", encoding="utf-8")
            with patch.dict(os.environ, {"APART_JEV_ENV_FILE": str(env_file)}, clear=True):
                credentials = load_jev_credentials()
        self.assertTrue(credentials.present)
        self.assertTrue(credentials.shape_ok)
        self.assertNotIn(self.KEY, repr(credentials))
        self.assertNotIn(self.KEY, json.dumps(credentials.redacted()))
        self.assertEqual(len(credentials.fingerprint), 12)
        client = JevChoiceClient(api_key=self.KEY)
        self.assertNotIn(self.KEY, json.dumps(client.diagnostics()))

    def test_missing_credentials_reports_missing_credentials(self):
        adapter = JevChoiceAdapter(JevChoiceClient(api_key=""))
        state = adapter.build_state(self.instance(), "A", "ISO")
        response = adapter.complete(state)
        self.assertEqual(response.status, "invalid")
        self.assertEqual(response.error_class, "missing_credentials")
        self.assertIn("missing_credentials", INVALID_RESPONSE_CLASSES)

    def test_request_is_credential_safe_and_parses(self):
        instance = self.instance()
        client = JevChoiceClient(api_key=self.KEY, endpoint="https://example.invalid/jev/v1/choice",
                                 model="jev-choice-1")
        adapter = JevChoiceAdapter(client)
        state = adapter.build_state(instance, "A", "ISO")
        labels = [option.option_id for option in state.options]
        body = {"probabilities": {label: 1.0 / len(labels) for label in labels},
                "model": "jev-choice-1", "request_id": "req-1", "usage": {"cost": 0.0}}
        with patch("apart_incident_response.jev_choice.urllib.request.urlopen",
                   return_value=FakeResponse(body)) as opener:
            response = adapter.complete(state)
        self.assertEqual(response.status, "complete")
        request = opener.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), f"Bearer {self.KEY}")
        self.assertNotIn(self.KEY, request.data.decode())
        self.assertEqual(request.full_url, "https://example.invalid/jev/v1/choice")

    def test_http_error_is_transport_error(self):
        adapter = JevChoiceAdapter(JevChoiceClient(api_key=self.KEY))
        state = adapter.build_state(self.instance(), "A", "ISO")
        error = urllib.error.HTTPError("https://example.invalid", 429, "rate", {}, None)
        with patch("apart_incident_response.jev_choice.urllib.request.urlopen", side_effect=error):
            response = adapter.complete(state)
        self.assertEqual(response.error_class, "transport_error")


if __name__ == "__main__":
    unittest.main()
