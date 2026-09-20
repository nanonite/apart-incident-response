import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from apart_incident_response.jev_choice import (
    INVALID_RESPONSE_CLASSES,
    JEV_CHOICE_CODEC_VERSION,
    JEV_PROTOCOL_KEY_PREFIX,
    JEV_RETRYABLE_STATUSES,
    JEV_SYSTEMONE_ENDPOINT,
    ChoiceOption,
    ChoiceState,
    JevChoiceAdapter,
    JevChoiceClient,
    assert_single_jev_protocol_key,
    is_jev_protocol_key,
    jev_choice_protocol_key,
    load_jev_credentials,
)
from apart_incident_response.jev_protocol import planning_low_instances


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "jev_choice_wire_choice_one.json"


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class RawResponse:
    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else str(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class ScriptedChoiceClient:
    """Fake transport: returns a canned response or raises."""

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.last_request = None

    def complete(self, request):
        self.last_request = request
        if self.error is not None:
            raise self.error
        return self.response


class AccountedClient(ScriptedChoiceClient):
    """Fake transport that reports the effective endpoint/retry settings."""

    endpoint = "https://example.invalid/v1/systemone"
    max_retries = 0


def envelope(option_ids, *, choice=None, model="jev-1.13.0", question_id="candidate",
             probabilities=None, confidence=1.0, usage=None):
    probabilities = probabilities or {option_id: 1.0 / len(option_ids) for option_id in option_ids}
    return {
        "model": model,
        "answers": {question_id: {
            "type": "choice",
            "choice": choice or max(probabilities, key=probabilities.get),
            "probabilities": probabilities,
            "confidence": confidence,
        }},
        "usage": usage if usage is not None else {"input_tokens": 12, "output_tokens": 3},
    }


def equal_weights(labels):
    return {label: 1.0 / len(labels) for label in labels}


def http_error(status, headers=None):
    return urllib.error.HTTPError("https://api.typesafe.ai/v1/systemone", status, "err",
                                  headers or {}, None)


class WireStateTests(unittest.TestCase):
    def instance(self):
        return planning_low_instances(1)[0]

    def adapter(self, client=None):
        return JevChoiceAdapter(client or ScriptedChoiceClient({}))

    def test_iso_state_is_leak_free(self):
        instance = self.instance()
        state = self.adapter().build_state(instance, "A", "ISO")
        self.assertEqual(state.state["clues"], list(instance.private_clues["A"]))
        for peer_clue in instance.private_clues["B"]:
            self.assertNotIn(peer_clue, state.state["clues"])
        self.assertNotIn("joint_clues", state.state)
        self.assertNotIn("visible_messages", state.state)
        self.assertNotIn("condition", state.state)
        self.assertNotIn("joint_solutions", state.state)
        serialized = json.dumps(state.state)
        self.assertNotIn(instance.target, serialized)
        self.assertNotIn("joint_candidate_labels", serialized)

    def test_full_state_uses_pooled_clues_once(self):
        instance = self.instance()
        state = self.adapter().build_state(instance, "A", "FULL")
        expected = [claim.text for claim in instance.claims]
        self.assertEqual(state.state["clues"], expected)
        self.assertEqual(len(state.state["clues"]), len(set(state.state["clues"])))
        self.assertNotIn("condition", state.state)
        self.assertNotIn("joint_solutions", state.state)
        self.assertNotIn("joint_candidate_labels", json.dumps(state.state))

    def test_comm_state_includes_only_received_messages(self):
        instance = self.instance()
        message = {"message_id": "m1", "text": "precedes=deploy>inspect"}
        state = self.adapter().build_state(instance, "A", "COMM", visible_messages=[message])
        self.assertEqual(state.state["visible_messages"], [message])
        self.assertEqual(state.state["clues"], list(instance.private_clues["A"]))
        self.assertNotIn("joint_clues", state.state)
        self.assertNotIn("condition", state.state)

    def test_visible_messages_rejected_outside_comm(self):
        instance = self.instance()
        with self.assertRaises(ValueError):
            self.adapter().build_state(instance, "A", "ISO", visible_messages=[{"text": "x"}])

    def test_request_shape_and_stable_option_ids(self):
        instance = self.instance()
        state = self.adapter().build_state(instance, "A", "ISO")
        request = self.adapter().build_request(state)
        self.assertEqual(set(request), {"model", "state", "questions"})
        self.assertEqual(list(request["questions"]), ["candidate"])
        question = request["questions"]["candidate"]
        self.assertEqual(question["type"], "choice")
        self.assertEqual(set(question["criteria"]), set(sorted(instance.solutions)))
        self.assertTrue(all(value is None for value in question["criteria"].values()))
        self.assertLessEqual(len(question["criteria"]), 255)

    def test_instructions_are_condition_neutral(self):
        instance = self.instance()
        adapter = self.adapter()
        bodies = [adapter.build_request(adapter.build_state(instance, "A", condition))
                  for condition in ("ISO", "FULL", "COMM")]
        instructions = {body["questions"]["candidate"]["instructions"] for body in bodies}
        self.assertEqual(len(instructions), 1)
        wording = instructions.pop().lower()
        self.assertNotIn("exactly one", wording)
        self.assertNotIn("unique", wording)

    def test_request_hash_is_reproducible_and_instance_scoped(self):
        first, second = planning_low_instances(2)
        adapter = self.adapter()
        a1 = adapter.build_state(first, "A", "ISO")
        a2 = adapter.build_state(first, "A", "ISO")
        b1 = adapter.build_state(second, "A", "ISO")
        self.assertEqual(a1.request_hash, a2.request_hash)
        self.assertNotEqual(a1.request_hash, b1.request_hash)
        self.assertEqual(adapter.record(a1, adapter.complete(a1))["request_hash"], a1.request_hash)


class WireParseTests(unittest.TestCase):
    def instance(self):
        return planning_low_instances(1)[0]

    def state(self, adapter, condition="ISO"):
        return adapter.build_state(self.instance(), "A", condition)

    def error_class(self, raw, condition="ISO", **kwargs):
        adapter = JevChoiceAdapter(ScriptedChoiceClient({}), **kwargs)
        return adapter.parse(self.state(adapter, condition), raw).error_class

    def test_fixture_response_parses(self):
        fixture = json.loads(FIXTURE.read_text())
        option_ids = list(fixture["request"]["questions"]["route"]["criteria"])
        state = ChoiceState("fixture", "A", "ISO", "route",
                            tuple(ChoiceOption(option_id, option_id) for option_id in option_ids),
                            {}, "", "deadbeef")
        adapter = JevChoiceAdapter(ScriptedChoiceClient({}), model="jev-1.13.0")
        response = adapter.parse(state, fixture["response"])
        self.assertEqual(response.status, "complete")
        self.assertEqual(response.selected_option_id, "owner_0")
        self.assertEqual(response.model, "jev-1.13.0")
        self.assertEqual(dict(response.usage), {"input_tokens": 340, "output_tokens": 28})
        self.assertAlmostEqual(sum(response.probabilities.values()), 1.0)

    def test_complete_maps_submission_and_records(self):
        instance = self.instance()
        labels = sorted(instance.solutions)
        probabilities = {label: 0.1 for label in labels}
        probabilities[instance.target] = 1.0 - 0.1 * (len(labels) - 1)
        client = ScriptedChoiceClient(envelope(labels, choice=instance.target,
                                               probabilities=probabilities, confidence=0.9))
        adapter = JevChoiceAdapter(client)
        state = adapter.build_state(instance, "A", "ISO")
        response = adapter.complete(state)
        self.assertEqual(response.status, "complete")
        self.assertEqual(response.confidence, 0.9)
        submission = adapter.map_submission(response)
        self.assertTrue(instance.validate(submission)["accepted"])
        record = adapter.record(state, response)
        self.assertEqual(record["protocol_key"], jev_choice_protocol_key(model=adapter.model))
        self.assertEqual(record["codec_version"], JEV_CHOICE_CODEC_VERSION)
        self.assertFalse(record["raw_response_retained"])
        self.assertNotIn("prompt_hash", record)

    def test_ties_accept_any_argmax(self):
        labels = sorted(self.instance().solutions)
        tied = {label: 0.0 for label in labels}
        tied[labels[0]] = 0.5
        tied[labels[1]] = 0.5
        accepted = self.error_class(envelope(labels, choice=labels[1], probabilities=tied))
        self.assertIsNone(accepted)

    def test_malformed_taxonomy(self):
        labels = sorted(self.instance().solutions)
        self.assertEqual(self.error_class({"model": "jev-1.13.0", "usage": {}}),
                         "response_not_evaluated")
        self.assertEqual(self.error_class({"detail": "bad request"}), "provider_rejected")
        self.assertEqual(self.error_class({"model": "jev-1.13.0", "answers": {}, "usage": {}}),
                         "missing_answer")
        wrong_kind = envelope(labels)
        wrong_kind["answers"]["candidate"]["type"] = "noul"
        self.assertEqual(self.error_class(wrong_kind), "wrong_answer_kind")

    def test_option_and_probability_validation(self):
        labels = sorted(self.instance().solutions)
        extra = envelope(labels)
        extra["answers"]["other"] = extra["answers"]["candidate"]
        self.assertEqual(self.error_class(extra), "extra_answer")

        mismatched = dict(equal_weights(labels))
        mismatched.pop(labels[0])
        self.assertEqual(self.error_class(envelope(labels, probabilities=mismatched)), "mismatched_option_set")

        not_normalized = {label: 0.5 for label in labels}
        self.assertEqual(self.error_class(envelope(labels, probabilities=not_normalized)), "not_normalized")

        negative = dict(equal_weights(labels))
        negative[labels[0]] = -0.1
        self.assertEqual(self.error_class(envelope(labels, probabilities=negative)), "negative_probability")

    def test_selection_confidence_usage_and_model(self):
        labels = sorted(self.instance().solutions)
        spread = {label: 0.05 for label in labels}
        spread[labels[-1]] = 0.5
        spread[labels[0]] = 0.25
        spread[labels[0]] = round(1.0 - 0.5 - 0.05 * (len(labels) - 2), 9)
        non_argmax = envelope(labels, choice=labels[0], probabilities=spread)
        self.assertEqual(self.error_class(non_argmax), "unknown_selection")

        bad_confidence = envelope(labels, confidence=1.5)
        self.assertEqual(self.error_class(bad_confidence), "invalid_confidence")

        bad_usage = envelope(labels, usage={"input_tokens": 2})
        self.assertEqual(self.error_class(bad_usage), "malformed_usage")

        drift = envelope(labels, model="jev-1.13.1")
        self.assertEqual(self.error_class(drift), "model_drift")


class TransportTests(unittest.TestCase):
    KEY = "typesafe-test-key-0123456789abcdef"

    def adapter(self, client):
        return JevChoiceAdapter(client)

    def test_missing_credentials_reports_missing_credentials(self):
        adapter = JevChoiceAdapter(JevChoiceClient(api_key=""))
        state = adapter.build_state(planning_low_instances(1)[0], "A", "ISO")
        response = adapter.complete(state)
        self.assertEqual(response.status, "invalid")
        self.assertEqual(response.error_class, "missing_credentials")

    def test_request_is_credential_safe(self):
        instance = planning_low_instances(1)[0]
        labels = sorted(instance.solutions)
        client = JevChoiceClient(api_key=self.KEY, model="jev-1.13.0", sleep_fn=lambda _: None)
        adapter = JevChoiceAdapter(client)
        state = adapter.build_state(instance, "A", "ISO")
        with patch("apart_incident_response.jev_choice.urllib.request.urlopen",
                   return_value=FakeResponse(envelope(labels))) as opener:
            response = adapter.complete(state)
        self.assertEqual(response.status, "complete")
        request = opener.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), f"Bearer {self.KEY}")
        self.assertEqual(request.full_url, JEV_SYSTEMONE_ENDPOINT)
        self.assertNotIn(self.KEY, request.data.decode())
        self.assertNotIn(self.KEY, json.dumps(client.diagnostics()))

    def test_retryable_status_is_retried_then_succeeds(self):
        labels = sorted(planning_low_instances(1)[0].solutions)
        client = JevChoiceClient(api_key=self.KEY, model="jev-1.13.0", sleep_fn=lambda _: None)
        adapter = JevChoiceAdapter(client)
        state = adapter.build_state(planning_low_instances(1)[0], "A", "ISO")
        with patch("apart_incident_response.jev_choice.urllib.request.urlopen",
                   side_effect=[http_error(529), FakeResponse(envelope(labels))]):
            response = adapter.complete(state)
        self.assertEqual(response.status, "complete")
        self.assertEqual(client.physical_attempts, 2)

    def test_retry_exhaustion_is_transport_error(self):
        client = JevChoiceClient(api_key=self.KEY, max_retries=1, sleep_fn=lambda _: None)
        adapter = JevChoiceAdapter(client)
        state = adapter.build_state(planning_low_instances(1)[0], "A", "ISO")
        with patch("apart_incident_response.jev_choice.urllib.request.urlopen",
                   side_effect=[http_error(529), http_error(529)]):
            response = adapter.complete(state)
        self.assertEqual(response.error_class, "transport_error")
        self.assertEqual(client.physical_attempts, 2)

    def test_physical_request_cap_blocks_retries(self):
        client = JevChoiceClient(api_key=self.KEY, max_physical_requests=1, sleep_fn=lambda _: None)
        adapter = JevChoiceAdapter(client)
        state = adapter.build_state(planning_low_instances(1)[0], "A", "ISO")
        with patch("apart_incident_response.jev_choice.urllib.request.urlopen",
                   side_effect=http_error(529)):
            response = adapter.complete(state)
        self.assertEqual(response.error_class, "transport_error")
        self.assertEqual(client.physical_attempts, 1)

    def test_non_retryable_status_is_provider_rejection(self):
        labels = sorted(planning_low_instances(1)[0].solutions)
        client = JevChoiceClient(api_key=self.KEY, sleep_fn=lambda _: None)
        adapter = JevChoiceAdapter(client)
        state = adapter.build_state(planning_low_instances(1)[0], "A", "ISO")
        with patch("apart_incident_response.jev_choice.urllib.request.urlopen",
                   side_effect=[http_error(422), FakeResponse(envelope(labels))]):
            response = adapter.complete(state)
        self.assertEqual(response.error_class, "provider_rejected")
        self.assertEqual(client.physical_attempts, 1)

    def test_retry_after_ms_header(self):
        client = JevChoiceClient(api_key=self.KEY, sleep_fn=lambda _: None)
        slept = []
        client._sleep = lambda delay: slept.append(delay)
        with patch("apart_incident_response.jev_choice.urllib.request.urlopen",
                   side_effect=[http_error(529, {"retry-after-ms": "2500"}),
                                FakeResponse(envelope(sorted(planning_low_instances(1)[0].solutions)))]):
            client.complete({"model": "jev-1.13.0", "state": {}, "questions": {}})
        self.assertEqual(slept, [2.5])

    def test_malformed_200_body_is_not_retried(self):
        labels = sorted(planning_low_instances(1)[0].solutions)
        client = JevChoiceClient(api_key=self.KEY, max_retries=2, sleep_fn=lambda _: None)
        adapter = JevChoiceAdapter(client)
        state = adapter.build_state(planning_low_instances(1)[0], "A", "ISO")
        with patch("apart_incident_response.jev_choice.urllib.request.urlopen",
                   side_effect=[RawResponse(b"not-json"), FakeResponse(envelope(labels))]):
            response = adapter.complete(state)
        self.assertEqual(response.error_class, "malformed_response")
        self.assertEqual(client.physical_attempts, 1)

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


class ProtocolKeyTests(unittest.TestCase):
    def test_key_is_deterministic_and_static_scoped(self):
        key = jev_choice_protocol_key()
        self.assertEqual(key, jev_choice_protocol_key())
        self.assertTrue(key.startswith(JEV_PROTOCOL_KEY_PREFIX))
        self.assertNotEqual(key, jev_choice_protocol_key(model="jev-1.13.1"))
        self.assertNotEqual(key, jev_choice_protocol_key(endpoint="https://example.invalid"))
        self.assertNotEqual(key, jev_choice_protocol_key(max_retries=0))

    def test_single_key_accepts_and_refuses_mixed(self):
        key = jev_choice_protocol_key()
        self.assertEqual(assert_single_jev_protocol_key(
            [{"protocol_key": key}, {"protocol_key": key}]), key)
        with self.assertRaises(ValueError):
            assert_single_jev_protocol_key([{"protocol_key": "six-family|a|b|c|d|e"}])
        with self.assertRaises(ValueError):
            assert_single_jev_protocol_key(
                [{"protocol_key": key}, {"protocol_key": jev_choice_protocol_key(model="x")}])
        with self.assertRaises(ValueError):
            assert_single_jev_protocol_key([{"nope": key}])
        self.assertTrue(is_jev_protocol_key(key))
        self.assertFalse(is_jev_protocol_key("six-family|a|b|c|d|e"))

    def test_record_key_tracks_effective_settings(self):
        instance = planning_low_instances(1)[0]

        def key_for(adapter):
            state = adapter.build_state(instance, "A", "ISO")
            return adapter.record(state, adapter.complete(state))["protocol_key"]

        baseline = key_for(JevChoiceAdapter(ScriptedChoiceClient({})))
        self.assertEqual(baseline, jev_choice_protocol_key())
        self.assertNotEqual(key_for(JevChoiceAdapter(ScriptedChoiceClient({}), instructions="Different.")),
                            baseline)
        self.assertNotEqual(key_for(JevChoiceAdapter(ScriptedChoiceClient({}), question_id="other")),
                            baseline)
        self.assertNotEqual(key_for(JevChoiceAdapter(ScriptedChoiceClient({}), model="jev-1.13.1")),
                            baseline)
        self.assertNotEqual(key_for(JevChoiceAdapter(AccountedClient({}))), baseline)
        self.assertEqual(key_for(JevChoiceAdapter(AccountedClient({}))),
                         jev_choice_protocol_key(endpoint=AccountedClient.endpoint, max_retries=0))

    def test_records_share_key_per_codec_but_hash_per_instance(self):
        first, second = planning_low_instances(2)
        adapter = JevChoiceAdapter(ScriptedChoiceClient({}))
        records = []
        for instance in (first, second):
            state = adapter.build_state(instance, "A", "ISO")
            response = adapter.complete(state)
            records.append(adapter.record(state, response))
        self.assertEqual(len({record["protocol_key"] for record in records}), 1)
        self.assertEqual(len({record["request_hash"] for record in records}), 2)
        self.assertEqual(assert_single_jev_protocol_key(records), records[0]["protocol_key"])


class ContractConstantTests(unittest.TestCase):
    def test_retryable_statuses_include_529(self):
        self.assertIn(529, JEV_RETRYABLE_STATUSES)
        self.assertTrue(JEV_RETRYABLE_STATUSES >= {408, 429, 500, 502, 503, 504})

    def test_invalid_classes_cover_new_rejections(self):
        required = {"provider_rejected", "response_not_evaluated", "missing_answer", "extra_answer",
                    "wrong_answer_kind", "unknown_selection", "invalid_confidence", "malformed_usage",
                    "model_drift", "missing_credentials", "transport_error"}
        self.assertTrue(INVALID_RESPONSE_CLASSES >= required)


if __name__ == "__main__":
    unittest.main()
