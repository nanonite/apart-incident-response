import tempfile
import unittest
from pathlib import Path

from apart_incident_response.task_one import (
    TASK_ONE_DIAGNOSIS,
    TASK_ONE_EVIDENCE_BUNDLES,
    TASK_ONE_REQUIRED_CLUES,
    TASK_ONE_TOKEN,
    materialize_task_one,
    materialize_task_one_bundle,
    validate_task_one_answer,
)


class TaskOneTests(unittest.TestCase):
    def test_three_bundles_are_individually_insufficient(self):
        self.assertEqual([bundle.agent_id for bundle in TASK_ONE_EVIDENCE_BUNDLES], [
            "agent-1",
            "agent-2",
            "agent-3",
        ])
        self.assertTrue(all(TASK_ONE_TOKEN in bundle.content for bundle in TASK_ONE_EVIDENCE_BUNDLES[:2]))
        combined_clues = frozenset().union(*(bundle.diagnostic_clues for bundle in TASK_ONE_EVIDENCE_BUNDLES))
        self.assertEqual(combined_clues, TASK_ONE_REQUIRED_CLUES)
        for bundle in TASK_ONE_EVIDENCE_BUNDLES:
            self.assertNotEqual(bundle.diagnostic_clues, TASK_ONE_REQUIRED_CLUES)
            self.assertNotIn(TASK_ONE_DIAGNOSIS, bundle.content)

    def test_materialize_task_one_writes_controller_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = materialize_task_one(Path(temporary))
            self.assertEqual([path.relative_to(temporary).as_posix() for path in paths], [
                bundle.relative_path for bundle in TASK_ONE_EVIDENCE_BUNDLES
            ])
            for path, bundle in zip(paths, TASK_ONE_EVIDENCE_BUNDLES):
                self.assertEqual(path.read_text(encoding="utf-8"), bundle.content)

    def test_each_bundle_can_be_materialized_in_isolation(self):
        with tempfile.TemporaryDirectory() as temporary:
            for bundle in TASK_ONE_EVIDENCE_BUNDLES:
                root = Path(temporary) / bundle.agent_id
                path = materialize_task_one_bundle(root, bundle.agent_id)
                self.assertEqual(path.read_text(encoding="utf-8"), bundle.content)
                self.assertEqual([item.name for item in root.iterdir()], [path.name])

    def test_only_combined_diagnosis_passes_validator(self):
        for bundle in TASK_ONE_EVIDENCE_BUNDLES:
            result = validate_task_one_answer(bundle.content)
            self.assertFalse(result.accepted)
            self.assertTrue(result.missing_terms)
        result = validate_task_one_answer(TASK_ONE_DIAGNOSIS)
        self.assertTrue(result.accepted)
        self.assertEqual(result.missing_terms, ())

    def test_validator_fails_closed_for_non_text_answers(self):
        result = validate_task_one_answer(None)  # type: ignore[arg-type]
        self.assertFalse(result.accepted)
        self.assertEqual(result.missing_terms, ("answer must be text",))


if __name__ == "__main__":
    unittest.main()
