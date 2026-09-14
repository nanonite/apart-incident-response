import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node is required for the dashboard renderer regression')
class DashboardActivityTests(unittest.TestCase):
    def test_sidebar_navigation_and_live_download_handlers(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['node', 'tests/fixtures/dashboard_navigation_exports.cjs'], cwd=root,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_live_disclosures_survive_polling_and_insights_show_recipients(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['node', 'tests/fixtures/live_activity_toggle.cjs'], cwd=root,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
