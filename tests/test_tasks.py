import unittest

from apart_incident_response.tasks import TASKS, task_by_id, validate_task_pool


class TaskPoolTests(unittest.TestCase):
    def test_pool_is_valid_and_difficulties_are_bounded(self):
        self.assertTrue(validate_task_pool())
        self.assertEqual(sorted({task_by_id(t['id'])['difficulty'] for t in TASKS}), [1, 2, 3, 4, 5])

    def test_task_lookup_returns_a_copy(self):
        task = task_by_id('inventory')
        task['difficulty'] = 5
        self.assertEqual(task_by_id('inventory')['difficulty'], 1)


if __name__ == '__main__':
    unittest.main()
