import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.openrouter_goal_inference import (
    DEFAULT_MODEL,
    _post_chat_completion,
    _request_payload,
    main,
)


FIXTURES = Path(__file__).parent / "fixtures"


class OpenRouterGoalInferenceTests(unittest.TestCase):
    def load(self, name: str) -> dict[str, object]:
        payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        self.assertIsInstance(payload, dict)
        return payload

    def test_request_payload_is_one_shot_and_requires_probability_support(self):
        payload = _request_payload(
            "openrouter/openai/gpt-4o-mini",
            "capital?",
            top_logprobs=5,
            max_tokens=16,
            temperature=0.0,
            seed=23,
        )
        self.assertEqual(payload["model"], "openai/gpt-4o-mini")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "capital?"}])
        self.assertFalse(payload["stream"])
        self.assertTrue(payload["logprobs"])
        self.assertEqual(payload["top_logprobs"], 5)
        self.assertEqual(payload["max_tokens"], 16)
        self.assertEqual(payload["seed"], 23)
        self.assertEqual(
            payload["provider"],
            {"require_parameters": True},
        )

    def test_default_model_is_the_exact_ling_openrouter_id(self):
        self.assertEqual(DEFAULT_MODEL, "inclusionai/ling-3.0-flash-vl:free")
        payload = _request_payload(
            "openrouter/inclusionai/ling-3.0-flash-vl:free",
            "incident",
            top_logprobs=5,
            max_tokens=128,
            temperature=0.0,
            seed=1,
        )
        self.assertEqual(payload["model"], "inclusionai/ling-3.0-flash-vl:free")
        self.assertEqual(payload["provider"], {"require_parameters": True})

    def test_api_key_is_sent_only_as_an_authorization_header(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"id":"response-1"}'

        secret = "sk-or-header-only"
        with patch("scripts.openrouter_goal_inference.urllib.request.urlopen", return_value=FakeResponse()) as opener:
            response = _post_chat_completion(
                "https://openrouter.ai/api/v1/chat/completions",
                secret,
                _request_payload(
                    "openai/gpt-4o-mini",
                    "capital?",
                    top_logprobs=5,
                    max_tokens=16,
                    temperature=0.0,
                    seed=None,
                ),
            )
        self.assertEqual(response["id"], "response-1")
        request = opener.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), f"Bearer {secret}")
        self.assertNotIn(secret, request.data.decode("utf-8"))

    def test_success_saves_normalized_probability_and_sanitized_response(self):
        response = self.load("openrouter-chat-completion-logprobs.json")
        secret = "sk-or-test-secret"
        response["diagnostic"] = secret
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": secret}, clear=False):
                with patch(
                    "scripts.openrouter_goal_inference._post_chat_completion",
                    return_value=response,
                ) as post:
                    result = main([
                        "--prompt", "capital of France",
                        "--model", "openrouter/openai/gpt-4o-mini",
                        "--seed", "7",
                        "--max-tokens", "32",
                        "--output", str(Path(temp) / "success"),
                        "--run-id", "openrouter-test-1",
                    ])
            self.assertEqual(result, 0)
            payload = post.call_args.args[2]
            self.assertEqual(payload["model"], "openai/gpt-4o-mini")
            self.assertFalse(payload["stream"])
            self.assertTrue(payload["logprobs"])
            self.assertEqual(payload["provider"]["require_parameters"], True)
            artifact_path = next((Path(temp) / "success").rglob("goal_inference.json"))
            artifact_text = artifact_path.read_text(encoding="utf-8")
            self.assertNotIn(secret, artifact_text)
            artifact = json.loads(artifact_text)
            self.assertEqual(artifact["status"], "complete")
            self.assertEqual(artifact["response"]["id"], "gen-openrouter-fixture-001")
            self.assertEqual(artifact["response"]["model"], "openai/gpt-4o-mini")
            self.assertEqual(artifact["route"]["openrouter_route"], "openrouter.ai:443")
            probability = artifact["probability_artifact"]
            self.assertEqual(probability["artifact_schema"], "partial-token-probability-v1")
            self.assertEqual(probability["coverage"]["token_count"], 2)
            self.assertEqual(
                [item["token"] for item in probability["tokens"][0]["top_alternatives"]],
                ["London"],
            )
            self.assertEqual(artifact["raw_response"]["diagnostic"], "[REDACTED]")

    def test_omitted_logprobs_writes_explicit_failure_without_the_key(self):
        response = self.load("openrouter-chat-completion-missing-logprobs.json")
        secret = "sk-or-missing-logprobs"
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": secret}, clear=False):
                with patch(
                    "scripts.openrouter_goal_inference._post_chat_completion",
                    return_value=response,
                ):
                    result = main([
                        "--prompt", "capital of France",
                        "--output", str(Path(temp) / "missing"),
                        "--run-id", "openrouter-test-missing",
                    ])
            self.assertEqual(result, 2)
            artifact_path = next((Path(temp) / "missing").rglob("failure.json"))
            artifact_text = artifact_path.read_text(encoding="utf-8")
            self.assertNotIn(secret, artifact_text)
            artifact = json.loads(artifact_text)
            self.assertEqual(artifact["status"], "failed")
            self.assertIn("omitted", artifact["error"])
            self.assertEqual(artifact["probability_artifact"]["status"], "unavailable")
            self.assertFalse(artifact["probability_artifact"]["full_vocabulary_compatible"])

    def test_missing_controller_key_writes_failure_without_attempting_request(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {}, clear=True):
                with patch("scripts.openrouter_goal_inference._post_chat_completion") as post:
                    result = main([
                        "--prompt", "capital of France",
                        "--output", str(Path(temp) / "no-key"),
                    ])
            self.assertEqual(result, 2)
            post.assert_not_called()
            failure = json.loads(next((Path(temp) / "no-key").rglob("failure.json")).read_text(encoding="utf-8"))
            self.assertEqual(failure["error"], "OPENROUTER_API_KEY is required")

    def test_repeated_successes_create_one_canonical_artifact_per_invocation(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "repeated"
            response = self.load("openrouter-chat-completion-logprobs.json")
            arguments = [
                "--prompt", "capital of France",
                "--model", "openai/gpt-4o-mini",
                "--output", str(output),
            ]
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-repeat"}, clear=False):
                with patch(
                    "scripts.openrouter_goal_inference._post_chat_completion",
                    return_value=response,
                ):
                    self.assertEqual(main(arguments), 0)
                    self.assertEqual(main(arguments), 0)
            canonical = output / "openrouter" / "openai%2Fgpt-4o-mini"
            canonical_artifacts = sorted(canonical.glob("*/goal_inference.json"))
            self.assertEqual(len(canonical_artifacts), 2)
            canonical_uuids = [
                json.loads(path.read_text(encoding="utf-8"))["run_uuid"]
                for path in canonical_artifacts
            ]
            self.assertEqual(len(set(canonical_uuids)), 2)
            self.assertFalse((output / "goal_inference.json").exists())

    def test_invalid_token_array_writes_failure_artifact(self):
        response = self.load("openrouter-chat-completion-logprobs.json")
        response["choices"][0]["logprobs"]["content"][1]["logprob"] = float("nan")
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-invalid"}, clear=False):
                with patch(
                    "scripts.openrouter_goal_inference._post_chat_completion",
                    return_value=response,
                ):
                    result = main([
                        "--prompt", "capital of France",
                        "--output", str(Path(temp) / "invalid"),
                    ])
            self.assertEqual(result, 2)
            failure = json.loads(next((Path(temp) / "invalid").rglob("failure.json")).read_text(encoding="utf-8"))
            self.assertEqual(failure["error_type"], "ProbabilityArtifactError")
            self.assertIn("finite", failure["error"])


if __name__ == "__main__":
    unittest.main()
