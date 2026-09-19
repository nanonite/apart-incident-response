import unittest

from apart_incident_response.jev_protocol import (
    JEV_PLANNING_LOW_SEED_BASE,
    audit_invariants,
    build_manifest,
    planning_low_instances,
)


class JevProtocolTests(unittest.TestCase):
    def test_planning_low_instances_are_fresh_unique_and_in_range(self):
        instances = planning_low_instances(17)
        ids = [instance.instance_id for instance in instances]
        self.assertEqual(len(ids), 17)
        self.assertEqual(len(set(ids)), 17)
        self.assertTrue(all(instance.seed >= JEV_PLANNING_LOW_SEED_BASE for instance in instances))
        self.assertTrue(all(instance.family == "planning" for instance in instances))
        self.assertTrue(all(instance.complexity.value == "low" for instance in instances))

    def test_invariants_all_pass_without_answer_key_exposure(self):
        audit = audit_invariants(planning_low_instances(5))
        self.assertEqual(audit["instance_count"], 5)
        self.assertEqual(audit["passing"], 5)
        self.assertEqual(audit["failing_ids"], [])
        for row in audit["rows"]:
            self.assertTrue(row["checks"]["pooled_equals_joint"])
            self.assertTrue(row["checks"]["claims_partitioned"])
            self.assertTrue(row["checks"]["both_agents_needed"])
            self.assertTrue(row["checks"]["finalizer_needs_peer"])
            self.assertTrue(row["checks"]["no_answer_key_exposed"])
            self.assertTrue(row["checks"]["joint_size_one"])

    def test_manifest_is_deterministic_and_bounded(self):
        first = build_manifest(3)
        second = build_manifest(3)
        self.assertEqual(first["manifest_hash"], second["manifest_hash"])
        self.assertEqual(first["instance_ids"], second["instance_ids"])
        self.assertEqual(first["selected_cell"], "planning:low")
        self.assertTrue(first["communication_invariants"]["board_optional_primary"])
        self.assertTrue(first["superseded_artifacts_excluded"])
        self.assertTrue(first["analysis_boundary"]["require_protocol_key"])

    def test_seed_count_must_be_positive(self):
        with self.assertRaises(ValueError):
            planning_low_instances(0)


if __name__ == "__main__":
    unittest.main()
