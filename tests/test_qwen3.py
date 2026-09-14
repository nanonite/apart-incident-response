import importlib.util
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from apart_incident_response.qwen3_artifacts import (
    ARTIFACT_SCHEMA,
    Qwen3ArtifactError,
    entropy_from_rows,
    load_full_logits_artifact,
    replay_entropy,
    validate_metadata,
    write_full_logits_artifact,
)
from apart_incident_response.qwen3_runtime import Qwen3RuntimeConfig, Qwen3RuntimeError, resolve_device
from scripts.ollama_goal_inference import _per_token_entropy
from scripts.qwen3_full_logits import _render_prompt, main as full_logits_main


def metadata_fixture() -> dict[str, object]:
    digest = "0" * 64
    return {
        "run_id": "test-run",
        "model": {"id": "Qwen/Qwen3-8B", "revision": "revision-1"},
        "tokenizer": {"id": "Qwen/Qwen3-8B", "revision": "revision-1"},
        "prompt": {"sha256": digest},
        "generation": {
            "seed": 1,
            "max_new_tokens": 2,
            "temperature": 0.0,
            "think": False,
            "use_cache": True,
        },
        "tensor": {
            "name": "logits",
            "shape": [2, 4],
            "layout": "step_vocab_row_major",
            "pre_sampling": True,
        },
        "paths": {
            "logits": "full-logits/logits.safetensors",
            "metadata": "full-logits/metadata.json",
            "generated": "full-logits/generated.json",
            "entropy": "full-logits/entropy.json",
        },
        "checksums": {
            "logits_artifact_sha256": digest,
            "generated_token_ids_sha256": digest,
        },
        "provenance": {"logits_source": "transformers_generate_output_logits"},
    }


class Qwen3ArtifactTests(unittest.TestCase):
    def test_metadata_schema_requires_raw_pre_sampling_provenance(self):
        metadata = metadata_fixture()
        metadata["schema_version"] = 1
        metadata["artifact_schema"] = ARTIFACT_SCHEMA
        validate_metadata(metadata)
        metadata["tensor"] = {**metadata["tensor"], "pre_sampling": False}
        with self.assertRaises(Qwen3ArtifactError):
            validate_metadata(metadata)

    def test_entropy_uses_full_vocabulary_and_matches_sampled_logprob(self):
        result = entropy_from_rows([[0.0, 0.0, 0.0, 0.0]], [2])
        self.assertAlmostEqual(result["entropy_bits"][0], 2.0)
        self.assertAlmostEqual(result["sampled_token_logprobs"][0], -math.log(4.0))
        self.assertEqual(result["vocabulary_size"], 4)

    def test_entropy_rejects_nonfinite_logits_and_bad_token_ids(self):
        with self.assertRaises(Qwen3ArtifactError):
            entropy_from_rows([[0.0, float("nan")]], [0])
        with self.assertRaises(Qwen3ArtifactError):
            entropy_from_rows([[0.0, 0.0]], [2])
        with self.assertRaises(Qwen3ArtifactError):
            entropy_from_rows([[0.0, 0.0], [0.0]], [0, 0])

    def test_thinking_prompt_uses_the_pinned_chat_template_contract(self):
        class FixtureTokenizer:
            def apply_chat_template(self, messages, **kwargs):
                self.messages = messages
                self.kwargs = kwargs
                return "rendered prompt"

        tokenizer = FixtureTokenizer()
        self.assertEqual(_render_prompt(tokenizer, "fixture", think=False), "fixture")
        self.assertEqual(_render_prompt(tokenizer, "fixture", think=True), "rendered prompt")
        self.assertEqual(tokenizer.messages, [{"role": "user", "content": "fixture"}])
        self.assertTrue(tokenizer.kwargs["enable_thinking"])

    def test_ollama_top_k_entropy_is_distinct_from_full_vocabulary_entropy(self):
        top_k = _per_token_entropy(-math.log(4.0), [{"logprob": -math.log(4.0)}])
        full = entropy_from_rows([[0.0, 0.0, 0.0, 0.0]], [0])
        self.assertLess(top_k["top_k_entropy_bits"], full["entropy_bits"][0])
        self.assertAlmostEqual(top_k["sampled_logprob"], full["sampled_token_logprobs"][0])

    def test_full_logits_cli_records_unavailable_runtime_as_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with patch(
                "scripts.qwen3_full_logits._seed_torch",
                side_effect=Qwen3RuntimeError("fixture runtime unavailable"),
            ):
                status = full_logits_main(["--prompt", "fixture", "--output", str(output)])
            self.assertEqual(status, 2)
            failure = json.loads(next(output.rglob("failure.json")).read_text(encoding="utf-8"))
            self.assertEqual(failure["status"], "failed")
            self.assertEqual(failure["run_id"], "seed-1")
            self.assertIn("fixture runtime unavailable", failure["error"])

    def test_cpu_mode_is_explicit_and_four_bit_cpu_is_rejected(self):
        with self.assertRaises(Qwen3RuntimeError):
            Qwen3RuntimeConfig("Qwen/Qwen3-8B", "revision", "revision", device="cpu")
        config = Qwen3RuntimeConfig(
            "Qwen/Qwen3-8B", "revision", "revision", device="cpu", load_in_4bit=False
        )
        self.assertEqual(config.device, "cpu")
        self.assertEqual(resolve_device("cpu"), "cpu")

    @unittest.skipUnless(
        importlib.util.find_spec("torch") and importlib.util.find_spec("safetensors"),
        "binary artifact dependencies are optional in the lightweight test runtime",
    )
    def test_safetensors_round_trip_and_entropy_replay(self):
        import torch

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata = metadata_fixture()
            metadata["generation"] = {**metadata["generation"], "generated_token_count": 2}
            logits = torch.tensor([[0.0, 1.0, 2.0, 3.0], [3.0, 2.0, 1.0, 0.0]])
            token_ids = torch.tensor([3, 0])
            normalized = write_full_logits_artifact(
                root,
                logits,
                token_ids,
                metadata,
                generated_record={"response": "fixture", "generated_token_ids": [3, 0]},
            )
            self.assertEqual(normalized["tensor"]["shape"], [2, 4])
            loaded = load_full_logits_artifact(root)
            replayed = replay_entropy(root)
            self.assertEqual(tuple(loaded.logits.shape), (2, 4))
            self.assertEqual(replayed["token_count"], 2)
            self.assertEqual(
                json.loads((root / "full-logits" / "entropy.json").read_text())["token_count"],
                2,
            )


class Qwen3LiveSmokeTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("QWEN3_LIVE_SMOKE") == "1",
        "set QWEN3_LIVE_SMOKE=1 in the isolated model runtime to run the live smoke",
    )
    def test_live_logits_are_finite_replayable_and_seed_addressed(self):
        import torch

        output = Path(os.environ.get("QWEN3_LIVE_OUTPUT", "runs/qwen3-8b/live-smoke"))
        arguments = [
            "--prompt",
            "Return exactly OK.",
            "--output",
            str(output),
            "--run-id",
            "live-smoke-seed-17",
            "--seed",
            "17",
            "--max-new-tokens",
            "4",
            "--device",
            "cuda",
            "--local-files-only",
        ]
        self.assertEqual(full_logits_main(arguments), 0)
        loaded = load_full_logits_artifact(output)
        self.assertTrue(torch.isfinite(loaded.logits).all().item())
        self.assertEqual(loaded.logits.shape[0], loaded.generated_token_ids.shape[0])
        generated = json.loads(next(output.rglob("generated.json")).read_text(encoding="utf-8"))
        self.assertEqual(generated["generated_token_ids"], loaded.generated_token_ids.tolist())
        self.assertIsInstance(generated["completion_text"], str)
        replayed = replay_entropy(output)
        self.assertEqual(replayed["token_count"], loaded.logits.shape[0])

        if os.environ.get("QWEN3_LIVE_DETERMINISM") == "1":
            repeat = output.parent / f"{output.name}-repeat"
            repeat_arguments = [*arguments]
            repeat_arguments[repeat_arguments.index("--output") + 1] = str(repeat)
            repeat_arguments[repeat_arguments.index("--run-id") + 1] = "live-smoke-seed-17-repeat"
            self.assertEqual(full_logits_main(repeat_arguments), 0)
            repeated = load_full_logits_artifact(repeat)
            self.assertEqual(loaded.generated_token_ids.tolist(), repeated.generated_token_ids.tolist())


if __name__ == "__main__":
    unittest.main()
