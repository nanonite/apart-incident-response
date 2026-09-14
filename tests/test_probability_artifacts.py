import math
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from apart_incident_response.probability_artifacts import (
    ProbabilityArtifactError,
    build_probability_artifact,
    is_complete_probability_artifact,
    normalize_token_probability,
    replay_partial_entropy,
)
from scripts.ollama_goal_inference import main as ollama_goal_main


def log_probability(probability: float) -> float:
    return math.log(probability)


class PartialProbabilityArtifactTests(unittest.TestCase):
    provenance = {
        "provider": "openrouter",
        "model": "openai/gpt-4o-mini",
        "parameters": {"logprobs": True, "top_logprobs": 2},
    }

    def record(self, **overrides):
        record = {
            "token": "A",
            "logprob": log_probability(0.6),
            "top_logprobs": [
                {"token": "A", "logprob": log_probability(0.6)},
                {"token": "B", "logprob": log_probability(0.3)},
                {"token": "B", "logprob": log_probability(0.3)},
            ],
        }
        record.update(overrides)
        return record

    def test_sampled_token_is_counted_once_and_alternatives_are_deduplicated(self):
        normalized = normalize_token_probability(self.record())
        self.assertEqual([item["token"] for item in normalized["top_alternatives"]], ["B"])
        self.assertAlmostEqual(normalized["covered_mass"], 0.9)
        self.assertAlmostEqual(normalized["residual_mass"], 0.1)
        self.assertAlmostEqual(
            normalized["entropy"]["partial_entropy_bits"],
            -(2 / 3 * math.log2(2 / 3) + 1 / 3 * math.log2(1 / 3)),
        )
        self.assertAlmostEqual(
            normalized["entropy"]["sampled_surprise_bits"], -math.log2(0.6)
        )

    def test_empty_alternatives_are_a_valid_partial_distribution(self):
        normalized = normalize_token_probability(
            self.record(top_logprobs=[], logprob=log_probability(0.7))
        )
        self.assertEqual(normalized["top_alternatives"], [])
        self.assertAlmostEqual(normalized["covered_mass"], 0.7)
        self.assertAlmostEqual(normalized["residual_mass"], 0.3)
        self.assertEqual(normalized["entropy"]["partial_entropy_bits"], 0.0)

    def test_nonfinite_and_overfull_values_fail_closed(self):
        with self.assertRaises(ProbabilityArtifactError):
            normalize_token_probability(self.record(logprob=math.nan))
        with self.assertRaises(ProbabilityArtifactError):
            normalize_token_probability(
                self.record(top_logprobs=[{"token": "B", "logprob": math.inf}])
            )
        with self.assertRaises(ProbabilityArtifactError):
            normalize_token_probability(
                self.record(
                    logprob=log_probability(0.8),
                    top_logprobs=[{"token": "B", "logprob": log_probability(0.5)}],
                )
            )

    def test_unavailable_artifact_has_explicit_reason_and_is_not_full_vocabulary(self):
        artifact = build_probability_artifact(
            None,
            provenance=self.provenance,
            missing_data_reason="provider omitted logprobs",
        )
        self.assertEqual(artifact["status"], "unavailable")
        self.assertEqual(artifact["missing_data_reason"], "provider omitted logprobs")
        self.assertFalse(artifact["full_vocabulary_compatible"])
        self.assertEqual(replay_partial_entropy(artifact), {"status": "unavailable", "token_count": 0})

    def test_artifact_replay_recomputes_the_partial_entropy(self):
        artifact = build_probability_artifact(
            [self.record()], provenance=self.provenance
        )
        replayed = replay_partial_entropy(artifact)
        self.assertEqual(replayed["status"], "complete")
        self.assertEqual(replayed["token_count"], 1)
        self.assertAlmostEqual(
            replayed["tokens"][0]["partial_entropy_bits"],
            artifact["tokens"][0]["entropy"]["partial_entropy_bits"],
        )
        self.assertEqual(artifact["coverage"]["alternative_count"], 1)

    def test_entropy_gate_requires_every_turn_to_be_complete(self):
        artifact = build_probability_artifact([self.record()], provenance=self.provenance)
        turn_artifact = {
            "artifact_schema": "agent-turn-probability-v1",
            "coverage": {"turns": 1, "complete": 1, "partial": 0, "unavailable": 0},
            "turns": [{
                "status": "complete",
                "probability_artifact": artifact,
            }],
        }
        self.assertTrue(is_complete_probability_artifact(turn_artifact))
        turn_artifact["coverage"]["partial"] = 1
        self.assertFalse(is_complete_probability_artifact(turn_artifact))

    def test_ollama_goal_artifact_uses_shared_normalization(self):
        fixture_path = Path(__file__).parent / "fixtures" / "openrouter-chat-completion-logprobs.json"
        response = json.loads(fixture_path.read_text(encoding="utf-8"))
        response["response"] = "Paris."
        response["logprobs"] = response["choices"][0]["logprobs"]["content"]
        with tempfile.TemporaryDirectory() as temp:
            with patch(
                "scripts.ollama_goal_inference._post_generate",
                return_value=response,
            ):
                self.assertEqual(
                    ollama_goal_main(
                        ["--prompt", "capital", "--output", str(Path(temp) / "ollama")]
                    ),
                    0,
                )
            artifact = json.loads(
                next((Path(temp) / "ollama").rglob("goal_inference.json")).read_text(encoding="utf-8")
            )
            probability = artifact["probability_artifact"]
            self.assertEqual(probability["artifact_schema"], "partial-token-probability-v1")
            self.assertEqual(probability["coverage"]["alternative_count"], 2)
            self.assertEqual(
                [item["token"] for item in probability["tokens"][0]["top_alternatives"]],
                ["London"],
            )


if __name__ == "__main__":
    unittest.main()
