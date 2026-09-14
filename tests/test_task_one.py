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
    task_one_bundle_for_agent,
    task_one_instance,
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

    def test_validator_rejects_negated_diagnosis(self):
        answer = TASK_ONE_DIAGNOSIS + " This revision did not cause the outage."
        result = validate_task_one_answer(answer)
        self.assertFalse(result.accepted)
        self.assertEqual(result.missing_terms, ("diagnosis negates the expected cause",))

    def test_validator_rejects_unrelated_diagnosis_with_matching_keywords(self):
        answers = (
            (
                "ORCHID-731 CACHE_MODE local shared outage keywords are present, but "
                "a DNS failure caused the outage.",
                "diagnosis does not state the expected cache-mode change",
            ),
            (
                "The ORCHID-731 configuration revision changed CACHE_MODE from local "
                "to shared, but a DNS failure caused the outage.",
                "diagnosis does not connect the revision to the outage",
            ),
        )
        for answer, reason in answers:
            with self.subTest(answer=answer):
                result = validate_task_one_answer(answer)
                self.assertFalse(result.accepted)
                self.assertEqual(result.missing_terms, (reason,))

    def test_validator_fails_closed_for_non_text_answers(self):
        result = validate_task_one_answer(None)  # type: ignore[arg-type]
        self.assertFalse(result.accepted)
        self.assertEqual(result.missing_terms, ("answer must be text",))


class TaskOneTwoAgentFixtureTests(unittest.TestCase):
    """agent_count=2 must be a genuine two-role fixture, not a rotated 2-of-3."""

    def test_two_role_instance_has_exactly_two_bundles(self):
        for seed in range(1, 21):
            with self.subTest(seed=seed):
                instance = task_one_instance(seed, agent_count=2)
                self.assertEqual(len(instance.bundles), 2)
                self.assertEqual(
                    [bundle.agent_id for bundle in instance.bundles], ["agent-1", "agent-2"]
                )

    def test_every_seed_covers_the_private_token_role_at_n_equals_2(self):
        # This is the exact failure mode fixed here: with the old rotated
        # 2-of-3 selection, roughly one in three seeds excluded the role
        # holding the private token from a 2-agent launch entirely.
        for seed in range(1, 21):
            with self.subTest(seed=seed):
                instance = task_one_instance(seed, agent_count=2)
                roles = {task_one_bundle_for_agent(instance, number).agent_id for number in (1, 2)}
                self.assertEqual(roles, {"agent-1", "agent-2"})
                owners = instance.manifest()["token_provenance"]["private_token_owner_roles"]
                self.assertEqual(owners, {instance.token: ["agent-2"]})

    def test_two_role_evidence_is_individually_insufficient_but_jointly_sufficient(self):
        instance = task_one_instance(1, agent_count=2)
        for bundle in instance.bundles:
            result = instance.validate_answer(bundle.content)
            self.assertFalse(result.accepted)
        result = instance.validate_answer(instance.diagnosis)
        self.assertTrue(result.accepted)

    def test_three_role_default_is_unaffected(self):
        instance = task_one_instance(1)
        self.assertEqual(len(instance.bundles), 3)
        self.assertEqual(
            [bundle.agent_id for bundle in instance.bundles], ["agent-1", "agent-2", "agent-3"]
        )


if __name__ == "__main__":
    unittest.main()
