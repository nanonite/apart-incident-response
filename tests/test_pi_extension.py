import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


SOURCE_ROOT = Path(__file__).parents[1]
PI_ROOT = Path(os.environ.get("APART_PI_ROOT", "/home/framework/GitRepos/pi"))
PI_ENTRY = PI_ROOT / "packages" / "coding-agent" / "src" / "cli.ts"


@unittest.skipUnless(
    shutil.which("bun") is not None and PI_ENTRY.is_file(),
    "Pi 0.85.1 fixture is not installed",
)
class DirectPiExtensionTests(unittest.TestCase):
    def test_real_pi_executes_constrained_tools_through_controller_ipc(self):
        completed = subprocess.run(
            [sys.executable, str(SOURCE_ROOT / "scripts" / "pi_extension_smoke.py")],
            cwd=SOURCE_ROOT,
            env={**os.environ, "PYTHONPATH": str(SOURCE_ROOT / "src")},
            capture_output=True,
            text=True,
            timeout=45,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        trace = json.loads(completed.stdout)
        self.assertEqual(trace["pi_version"], "0.85.1")
        self.assertEqual(trace["extension"], "pi-extension/incident-tools.ts")
        self.assertFalse(trace["built_in_tools"])
        self.assertFalse(trace["extension_discovery"])
        self.assertEqual(
            [event["tool"] for event in trace["tool_events"]],
            ["task_read", "task_query", "board_append", "board_read", "task_submit"],
        )
        self.assertEqual([event["operation"] for event in trace["audit"]], [
            "task_read", "task_query", "board_append", "board_read", "task_submit"
        ])
        self.assertTrue(all(event["response"]["ok"] for event in trace["audit"]))


if __name__ == "__main__":
    unittest.main()
