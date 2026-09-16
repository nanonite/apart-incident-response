import unittest

from apart_incident_response.communication_events import CommunicationEventLog


class TestCommunicationSummaryContract(unittest.TestCase):
    def test_summary_emits_canonical_post_read_bits_field(self):
        summary = CommunicationEventLog("run-test").summary()
        self.assertEqual(summary["post_read_correlated_bits"], 0.0)
        self.assertEqual(summary["verified_useful_bits"], 0.0)
        self.assertEqual(summary["post_read_success_count"], 0)


if __name__ == "__main__":
    unittest.main()
