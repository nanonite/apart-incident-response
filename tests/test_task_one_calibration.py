import unittest

from scripts.task_one_calibration import capture_calibration, capture_difficulty_calibration


class TaskOneCalibrationTests(unittest.TestCase):
    def test_each_bundle_is_calibrated_without_board_or_complete_answer(self):
        trace = capture_calibration()
        self.assertTrue(trace["calibration"])
        self.assertTrue(trace["credential_free"])
        self.assertFalse(trace["model_request"])
        self.assertEqual(trace["condition"], "C0")
        self.assertEqual(len(trace["records"]), 3)
        self.assertTrue(all(record["status"] == "completed" for record in trace["records"]))
        self.assertTrue(all(record["turns"] == 1 for record in trace["records"]))
        self.assertTrue(all(record["tokens_used"] == 1 for record in trace["records"]))
        self.assertTrue(all(record["tool_calls_used"] == 1 for record in trace["records"]))
        self.assertTrue(all(not record["board_tools_available"] for record in trace["records"]))
        self.assertTrue(all(not record["validator"]["accepted"] for record in trace["records"]))

    def test_each_predeclared_difficulty_is_independently_calibrated(self):
        trace = capture_difficulty_calibration()
        self.assertEqual(trace["difficulty_levels"], ["easy", "anchor", "hard"])
        self.assertEqual(len(trace["records"]), 9)
        self.assertTrue(all(record["status"] == "completed" for record in trace["records"]))
        self.assertTrue(all(not record["validator"]["accepted"] for record in trace["records"]))
        for difficulty in trace["difficulty_levels"]:
            hashes = {record["fixture_sha256"] for record in trace["records"] if record["difficulty"] == difficulty}
            self.assertEqual(len(hashes), 1)


if __name__ == "__main__":
    unittest.main()
