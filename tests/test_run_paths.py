import json
from pathlib import Path
import tempfile
import unittest

from apart_incident_response.controller import ExperimentController
from apart_incident_response.run_paths import (
    RunPathError,
    copy_file_if_absent,
    create_run_directory,
    decode_model_slug,
    find_run_by_uuid,
    split_model_id,
)
from scripts.run_experiment import run_harness_check
from tests.test_experiment import EXTENSION, fixture_config


class RunPathContractTests(unittest.TestCase):
    def test_model_mapping_is_reversible_and_rejects_path_traversal(self):
        provider, model, slug = split_model_id("openrouter/openai/gpt-4o-mini")
        self.assertEqual(provider, "openrouter")
        self.assertEqual(model, "openrouter/openai/gpt-4o-mini")
        self.assertEqual(decode_model_slug(slug), model)
        _, unprefixed_model, unprefixed_slug = split_model_id(
            "openai/gpt-4o-mini", provider="openrouter"
        )
        _, prefixed_model, prefixed_slug = split_model_id(
            "openrouter/openai/gpt-4o-mini", provider="openrouter"
        )
        self.assertNotEqual(unprefixed_slug, prefixed_slug)
        self.assertEqual(decode_model_slug(unprefixed_slug), unprefixed_model)
        self.assertEqual(decode_model_slug(prefixed_slug), prefixed_model)
        for invalid in ("", "../escape", "/absolute", r"C:\\absolute", "provider//model", "provider/./model"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(RunPathError):
                    split_model_id(invalid)

    def test_uuid_directories_are_unique_and_exclusive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = create_run_directory(root, "fixture/controlled-agent", run_id="repeatable-label")
            second = create_run_directory(root, "fixture/controlled-agent", run_id="repeatable-label")
            self.assertNotEqual(first.run_uuid, second.run_uuid)
            self.assertNotEqual(first.path, second.path)
            self.assertEqual(find_run_by_uuid(root, first.run_uuid).path, first.path)
            with self.assertRaises(RunPathError):
                create_run_directory(root, first.model, run_uuid=first.run_uuid)

    def test_compatibility_copy_never_replaces_an_existing_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            destination = root / "legacy" / "failure.json"
            source.write_text("first", encoding="utf-8")
            self.assertTrue(copy_file_if_absent(source, destination))
            source.write_text("second", encoding="utf-8")
            self.assertFalse(copy_file_if_absent(source, destination))
            self.assertEqual(destination.read_text(encoding="utf-8"), "first")

    def test_harness_matrix_has_one_uuid_and_resolvable_condition_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = run_harness_check(Path(temporary), run_id="matrix-label")
            invocation = Path(result["artifact_root"])
            self.assertRegex(result["run_uuid"], r"^[0-9a-f-]{36}$")
            self.assertEqual(result["run_uuid"], json.loads((invocation / "run.json").read_text())["run_uuid"])
            triplet = result["triplets"][0]
            self.assertEqual(set(triplet["conditions"]), {"C0", "C1", "C2"})
            for condition in triplet["conditions"]:
                condition_root = invocation / "s0001" / condition
                manifest = json.loads((condition_root / "manifest.json").read_text())
                self.assertEqual(manifest["run_uuid"], result["run_uuid"])
                link = triplet["artifacts"]["conditions"][condition]["agents"]["agent-1"]
                self.assertTrue((invocation / link).is_file(), link)

    def test_model_factor_uses_separate_model_scoped_invocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            invocation = create_run_directory(root, "fixture/controlled-agent-tier-1")
            controller = ExperimentController(
                fixture_config().for_model("fixture/controlled-agent-tier-1"),
                invocation.path,
                invocation=invocation,
                extension=EXTENSION,
                run_class="harness_check",
            )
            triplets = controller.run_factor_pilot(
                "model",
                ("configured", "fixture/controlled-agent-tier-2"),
                seeds=(1,),
            )
            models = set()
            roots = set()
            for triplet in triplets:
                for run in triplet:
                    manifest = json.loads((run.artifact_root / "manifest.json").read_text())
                    models.add(manifest["factor_assignment"]["model"])
                    roots.add(run.artifact_root.parents[2])
            self.assertEqual(models, {"fixture/controlled-agent-tier-1", "fixture/controlled-agent-tier-2"})
            self.assertEqual(len(roots), 2)


if __name__ == "__main__":
    unittest.main()
