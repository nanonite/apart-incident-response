import unittest

from apart_incident_response.behavioral_discovery import build_screen_instances
from apart_incident_response.jev_selection import audit_confirmatory, planning_high_invalid_trace


def record(instance_id, condition, *, valid, success, message_count=0, transmitted_bits=0.0,
           post_read_correlation=0, rejected=0, output_tokens=100, provider_failures=()):
    if valid and success:
        classification = "success"
    elif valid:
        classification = "valid_wrong_answer"
    else:
        classification = "invalid_output_empty"
    return {
        "instance_id": instance_id, "condition": condition,
        "valid_execution": valid, "task_success": success, "classification": classification,
        "event_summary": {
            "message_count": message_count, "transmitted_bits": transmitted_bits,
            "post_read_correlation_count": post_read_correlation, "rejected_write_count": rejected,
            "output_tokens": output_tokens, "input_tokens": 10, "event_count": 1,
            "provider_failure_types": list(provider_failures),
        },
    }


class JevSelectionTests(unittest.TestCase):
    def instances(self):
        return build_screen_instances(scheme="stage2-confirmatory", seeds_per_cell=1)

    def by_cell(self, instances):
        return {(instance.family, instance.complexity.value): instance.instance_id for instance in instances}

    def test_cell_audit_counts_matched_outcomes_and_comm(self):
        instances = self.instances()
        planning_low = self.by_cell(instances)[("planning", "low")]
        records = [
            record(planning_low, "ISO", valid=True, success=False),
            record(planning_low, "FULL", valid=True, success=True),
            record(planning_low, "COMM", valid=True, success=True, message_count=2,
                   transmitted_bits=3.0, post_read_correlation=1),
        ]
        audit = audit_confirmatory(instances, records)
        cell = next(c for c in audit["cells"]
                    if (c["family"], c["complexity"]) == ("planning", "low"))
        self.assertEqual(cell["valid_by_condition"], {"ISO": 1, "FULL": 1, "COMM": 1})
        self.assertEqual(cell["iso_to_full"]["difference"], 1.0)
        self.assertEqual(cell["comm"]["used_board"], 1)
        self.assertEqual(cell["comm"]["post_read_correlation_count"], 1)
        self.assertTrue(audit["notes"]["post_read_correlation_is_not_causal"])
        self.assertTrue(audit["notes"]["comm_confounds_board_use_with_extra_finalizer_turn"])

    def test_planning_high_trace_detects_token_cap_and_provider_failure(self):
        instances = self.instances()
        planning_high = self.by_cell(instances)[("planning", "high")]
        records = [
            record(planning_high, "ISO", valid=False, success=False, output_tokens=1024),
            record(planning_high, "COMM", valid=False, success=False, output_tokens=3600,
                   provider_failures=("http_400_client_error",)),
        ]
        trace = planning_high_invalid_trace(instances, records)
        self.assertEqual(trace["invalid_total"], 2)
        self.assertEqual(trace["iso_invalid_total"], 1)
        self.assertEqual(trace["iso_invalid_at_cap"], 1)
        self.assertEqual(trace["provider_failures_present"], ["http_400_client_error"])
        self.assertTrue(trace["safe_next_diagnostics"])

    def test_audit_uses_preregistered_holm_scope(self):
        audit = audit_confirmatory(self.instances(), [])
        self.assertEqual(audit["holm_scope"], "five cell-specific C_need claims")
        self.assertEqual(audit["cell_count"], 5)
        self.assertEqual(audit["record_count"], 0)
        self.assertTrue(audit["notes"]["p_value_is_not_an_entropy_gate"])


if __name__ == "__main__":
    unittest.main()
