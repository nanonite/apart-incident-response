import os
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.run_experiment import _execution_context


ROOT = Path(__file__).parents[1]


class ContainerLaunchContractTests(unittest.TestCase):
    def test_runtime_image_contains_controller_and_constrained_extension(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        runtime_section = dockerfile.split("FROM runtime AS pi-smoke", 1)[0]
        for path in (
            "pi-extension ./pi-extension",
            "scripts/container_isolation_check.py",
            "scripts/container_matrix_entrypoint.sh",
            "scripts/run_experiment.py",
            "tests/fixtures/controlled_fake_agent.py",
        ):
            self.assertIn(path, runtime_section)

    def test_compose_matrix_service_has_no_docker_socket_and_persists_runs(self):
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        matrix = compose.split("  matrix:\n", 1)[1].split("  # Local model", 1)[0]
        self.assertIn("target: /app/runs", matrix)
        self.assertIn("target: /controller-state", matrix)
        self.assertNotIn("docker.sock", matrix)
        self.assertIn("APART_PI_ROOT: /opt/pi", matrix)
        self.assertIn("APART_PI_AUTH_STORE: /controller-state/codex-auth.json", matrix)

    def test_matrix_entrypoint_refuses_socket_and_marks_controller_boundary(self):
        entrypoint = (ROOT / "scripts/container_matrix_entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn("/run/docker.sock", entrypoint)
        self.assertIn("/var/run/docker.sock", entrypoint)
        self.assertIn("refusing matrix runtime", entrypoint)
        self.assertIn("chmod 0700 /controller-state", entrypoint)
        self.assertIn("APART_OPENCODE_API_KEY_FILE", entrypoint)

    def test_container_context_is_explicit_and_secret_free(self):
        with patch.dict(os.environ, {"APART_CONTAINERIZED": "1"}, clear=False):
            context = _execution_context()
        self.assertEqual(context["controller"], "docker-compose-matrix-service")
        self.assertTrue(context["containerized"])
        self.assertEqual(context["docker_access_scope"], "outer-controller-only")
        self.assertFalse(context["credentials_in_matrix_argv"])


if __name__ == "__main__":
    unittest.main()
