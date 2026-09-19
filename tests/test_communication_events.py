import unittest

from apart_incident_response.communication_events import CommunicationEventLog


class TestCommunicationSummaryContract(unittest.TestCase):
    def test_summary_emits_canonical_post_read_bits_field(self):
        summary = CommunicationEventLog("run-test").summary()
        self.assertEqual(summary["post_read_correlated_bits"], 0.0)
        self.assertEqual(summary["transmitted_bits"], 0.0)
        self.assertEqual(summary["post_read_correlation_count"], 0)
        self.assertNotIn("verified_useful_bits", summary)
        self.assertNotIn("post_read_correlated_use_count", summary)


if __name__ == "__main__":
    unittest.main()
