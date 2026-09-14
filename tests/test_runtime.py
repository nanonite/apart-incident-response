import fcntl
import hashlib
import json
import os
import sys
import tempfile
import threading
import textwrap
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from apart_incident_response.task_tools import TaskCatalog, TaskToolService
from apart_incident_response.tool_credentials import ControllerCredentialAuthority
from apart_incident_response.tool_service import ConstrainedToolService
from apart_incident_response.runtime import (
    AgentIdentity,
    AgentRun,
    Condition,
    IsolationPolicy,
    RuntimeConfig,
    RuntimeConfigError,
    SystemBudget,
    _ModelEgressProxy,
    _bubblewrap_failure_reason,
    _model_request_metadata,
    _opencode_session_id,
    _prepare_auth_file,
    _prepare_model_limits,
    _resolve_provider_api_key,
    _resolve_auth_store,
    _resolve_auth_file,
    build_pi_command,
    create_isolated_workspace,
    load_identity,
    probe_ollama,
)


class RuntimeContractTests(unittest.TestCase):
    def config(self, **overrides):
        values = {
            "pi_version": "0.83.0",
            "model": "openai-codex/gpt-5.6-luna",
            "pi_root_env": None,
            "isolation": IsolationPolicy(sandbox="none", allow_unsafe_for_tests=True),
        }
        values.update(overrides)
        return RuntimeConfig(**values)

    def identity(self, agent_id="agent-1", condition=Condition.C0):
        return AgentIdentity("run-001", agent_id, condition, "task-1", 17)

    def test_config_keeps_same_aggregate_budget_for_all_conditions(self):
        config = self.config()
        self.assertEqual(config.conditions, (Condition.C0, Condition.C1, Condition.C2))
        self.assertEqual(config.aggregate_token_budget, 12_000)
        self.assertEqual(config.aggregate_tool_call_budget, 96)

    def test_config_rejects_side_channels(self):
        with self.assertRaises(RuntimeConfigError):
            self.config(isolation=IsolationPolicy(network=True, sandbox="none", allow_unsafe_for_tests=True))

    def test_config_rejects_shell_operators(self):
        with self.assertRaises(RuntimeConfigError):
            self.config(launch_command=("pi", "--", "x; touch leaked"))

    def test_identity_is_stable_and_unique(self):
        first = self.identity("agent-1")
        second = self.identity("agent-2")
        self.assertEqual(first.credential_id, first.credential_id)
        self.assertNotEqual(first.credential_id, second.credential_id)
        self.assertNotEqual(first.credential_id, self.identity("agent-1", Condition.C1).credential_id)
        self.assertNotEqual(first.credential_id, AgentIdentity("run-001", "agent-1", Condition.C0, "task-1", 18).credential_id)
        self.assertEqual(first.to_dict()["condition"], "C0")

    def test_identity_round_trip_rejects_tampering(self):
        identity = self.identity()
        self.assertEqual(load_identity(identity.to_dict()), identity)
        tampered = identity.to_dict()
        tampered["credential_id"] = "not-the-controller-binding"
        with self.assertRaises(RuntimeConfigError):
            load_identity(tampered)
        altered_fields = identity.to_dict()
        altered_fields["agent_id"] = "agent-2"
        with self.assertRaises(RuntimeConfigError):
            load_identity(altered_fields)
        recomputed_unkeyed = altered_fields.copy()
        material = "\0".join(
            [
                recomputed_unkeyed["run_id"],
                recomputed_unkeyed["agent_id"],
                recomputed_unkeyed["condition"],
                recomputed_unkeyed["task_id"],
                str(recomputed_unkeyed["seed"]),
            ]
        )
        recomputed_unkeyed["credential_id"] = hashlib.sha256(material.encode()).hexdigest()
        with self.assertRaises(RuntimeConfigError):
            load_identity(recomputed_unkeyed)
        missing_credential = identity.to_dict()
        del missing_credential["credential_id"]
        with self.assertRaises(RuntimeConfigError):
            load_identity(missing_credential)
        missing = identity.to_dict()
        del missing["task_id"]
        with self.assertRaises(RuntimeConfigError):
            load_identity(missing)

    def test_workspace_is_agent_specific_and_private(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = create_isolated_workspace(root, self.identity("agent-1"))
            second = create_isolated_workspace(root, self.identity("agent-2"))
            self.assertNotEqual(first.root, second.root)
            self.assertNotEqual(first.task_dir, second.task_dir)
            self.assertEqual(first.root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(first.task_dir.stat().st_mode & 0o777, 0o700)
            with self.assertRaises(RuntimeConfigError):
                create_isolated_workspace(root, self.identity("agent-1"))

    def test_pi_command_is_minimal_and_disables_session_persistence(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = create_isolated_workspace(Path(temp), self.identity())
            command = build_pi_command(self.config(), self.identity(), workspace)
            self.assertIn("--no-tools", command)
            self.assertIn("--no-skills", command)
            self.assertIn("--no-extensions", command)
            self.assertIn("--no-context-files", command)
            self.assertIn("--no-session", command)
        self.assertIn("--mode", command)
        self.assertNotIn("bash", command)

    def test_bubblewrap_preserves_identity_and_model_network(self):
        with tempfile.TemporaryDirectory() as temp:
            pi_root = Path(temp) / "pi"
            (pi_root / "packages/coding-agent").mkdir(parents=True)
            (pi_root / "packages/coding-agent/package.json").write_text(
                json.dumps({"version": "0.83.0"}), encoding="utf-8"
            )
            config = self.config(
                pi_root_env="TEST_APART_PI_ROOT",
                isolation=IsolationPolicy(model_network=True),
                launch_command=("bun", "run", "{pi_root}/packages/coding-agent/src/cli.ts"),
            )
            workspace = create_isolated_workspace(Path(temp) / "runs", self.identity())
            with patch.dict(os.environ, {"TEST_APART_PI_ROOT": str(pi_root)}):
                command = build_pi_command(config, self.identity(), workspace)
            self.assertIn("--unshare-net", command)
            self.assertIn("network_bridge", " ".join(command))
            self.assertIn("--setenv", command)
            identity_index = command.index("APART_RUN_ID")
            self.assertEqual(command[identity_index + 1], "run-001")
            if Path("/usr").is_dir():
                self.assertIn("/usr", command)
            if Path("/lib").exists():
                self.assertIn("/lib", command)

    def test_bubblewrap_namespace_failure_is_explicit_and_fail_closed(self):
        reason = _bubblewrap_failure_reason(
            ["bwrap: loopback: Failed to create NETLINK_ROUTE socket: Operation not permitted\n"]
        )
        self.assertEqual(
            reason,
            "Bubblewrap isolation failed: bwrap: loopback: Failed to create NETLINK_ROUTE socket: Operation not permitted",
        )
        self.assertEqual(
            _bubblewrap_failure_reason(
                ["bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted\n"]
            ),
            "Bubblewrap isolation failed: bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted",
        )
        self.assertIsNone(_bubblewrap_failure_reason(["agent failed\n"]))

    def test_model_relay_allows_model_and_oauth_hosts_only_over_https(self):
        relay = _ModelEgressProxy(Path("/tmp/unused-relay.sock"), ("chatgpt.com", "auth.openai.com"))
        self.assertTrue(relay._allowed("chatgpt.com", 443))
        self.assertTrue(relay._allowed("auth.openai.com", 443))
        self.assertFalse(relay._allowed("example.com", 443))
        self.assertFalse(relay._allowed("chatgpt.com", 80))
        self.assertEqual(relay._parse_connect_target("chatgpt.com:443"), ("chatgpt.com", 443))
        self.assertEqual(relay._parse_connect_target("auth.openai.com:443"), ("auth.openai.com", 443))
        for target in ("example.com:443", "chatgpt.com:80", "chatgpt.com", "https://chatgpt.com:443", "chatgpt.com:443:extra"):
            self.assertIsNone(relay._parse_connect_target(target))

    def test_opencode_selection_is_provider_specific_and_session_is_stable(self):
        config = self.config().for_model("opencode-go/kimi-k2.6")
        self.assertEqual(config.model, "opencode-go/kimi-k2.6")
        self.assertEqual(config.isolation.model_hosts, ("opencode.ai",))
        self.assertEqual(config.isolation.oauth_hosts, ())
        self.assertIsNone(config.pi_auth_store_env)
        codex = config.for_model("openai-codex/gpt-5.6-luna")
        self.assertEqual(codex.pi_auth_store_env, self.config().pi_auth_store_env)
        self.assertEqual(codex.isolation.model_hosts, ("chatgpt.com",))
        self.assertEqual(codex.isolation.oauth_hosts, ("auth.openai.com",))
        self.assertEqual(_opencode_session_id(self.identity()), _opencode_session_id(self.identity()))
        self.assertNotEqual(
            _opencode_session_id(self.identity("agent-1")),
            _opencode_session_id(self.identity("agent-2")),
        )

    def test_opencode_does_not_require_codex_auth_file(self):
        config = self.config().for_model("opencode-go/kimi-k2.6")
        with patch.dict(os.environ, {"TEST_PI_AUTH": "/missing/codex-auth.json"}):
            self.assertIsNone(_resolve_auth_file(config))

    def test_openrouter_selection_uses_only_provider_egress_and_preserves_model_slug(self):
        config = self.config().for_model("openrouter/openai/gpt-4o-mini")
        self.assertEqual(config.model, "openrouter/openai/gpt-4o-mini")
        self.assertEqual(config.isolation.model_hosts, ("openrouter.ai",))
        self.assertEqual(config.isolation.oauth_hosts, ())
        metadata = _model_request_metadata(config)
        self.assertEqual(metadata["openrouter_base_url"], "https://openrouter.ai/api/v1")
        self.assertEqual(metadata["openrouter_model"], "openai/gpt-4o-mini")
        self.assertEqual(metadata["openrouter_route"], "openrouter.ai:443")

    def test_openrouter_switch_restores_codex_egress(self):
        config = self.config().for_model("openrouter/openai/gpt-4o-mini")
        codex = config.for_model("openai-codex/gpt-5.6-luna")
        self.assertEqual(codex.isolation.model_hosts, ("chatgpt.com",))
        self.assertEqual(codex.isolation.oauth_hosts, ("auth.openai.com",))

    def test_openrouter_rejects_model_without_author_and_slug(self):
        with self.assertRaises(RuntimeConfigError):
            self.config().for_model("openrouter/gpt-4o-mini")

    def test_openrouter_relay_allows_only_openrouter_https(self):
        relay = _ModelEgressProxy(Path("/tmp/unused-openrouter-relay.sock"), ("openrouter.ai",))
        self.assertTrue(relay._allowed("openrouter.ai", 443))
        self.assertTrue(relay._allowed("OPENROUTER.AI.", 443))
        self.assertFalse(relay._allowed("openrouter.ai", 80))
        self.assertFalse(relay._allowed("chatgpt.com", 443))
        self.assertEqual(relay._parse_connect_target("openrouter.ai:443"), ("openrouter.ai", 443))

    def test_openrouter_model_limits_use_the_configured_agent_envelope(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = create_isolated_workspace(Path(temp), self.identity())
            config = self.config(per_agent_token_budget=17).for_model(
                "openrouter/openai/gpt-4o-mini"
            )
            path = _prepare_model_limits(workspace, config)
            payload = json.loads(path.read_text(encoding="utf-8"))
            provider = payload["providers"]["openrouter"]
            self.assertEqual(
                provider["modelOverrides"]["openai/gpt-4o-mini"]["maxTokens"],
                17,
            )

    def test_openrouter_key_is_controller_only_and_staged_for_pi(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            secret = "openrouter-secret-for-test"
            key_file = root / "openrouter-key"
            key_file.write_text(
                json.dumps({"openrouter": {"type": "api_key", "key": secret}}) + "\n",
                encoding="utf-8",
            )
            key_file.chmod(0o600)
            config = self.config().for_model("openrouter/openai/gpt-4o-mini")
            with patch.dict(
                os.environ,
                {
                    "APART_OPENROUTER_API_KEY_FILE": str(key_file),
                    "OPENROUTER_API_KEY": "ambient-value-must-not-win",
                },
                clear=True,
            ):
                self.assertEqual(_resolve_provider_api_key(config), secret)
            workspace = create_isolated_workspace(root / "runs", self.identity())
            stage = _prepare_auth_file(None, workspace, config, api_key=secret)
            self.assertIsNotNone(stage)
            self.assertEqual(
                json.loads(stage.target.read_text(encoding="utf-8"))["openrouter"]["key"],
                secret,
            )
            self.assertIsNone(_resolve_auth_store(config, None, workspace))

    def test_openrouter_key_is_required_when_no_controller_input_exists(self):
        config = self.config().for_model("openrouter/openai/gpt-4o-mini")
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeConfigError, "OpenRouter API key is unavailable"):
                _resolve_provider_api_key(config)

    def test_ollama_selection_uses_loopback_endpoint_and_disables_oauth(self):
        config = self.config().for_model("ollama/qwen3:8b")
        self.assertEqual(config.model, "ollama/qwen3:8b")
        self.assertEqual(config.isolation.model_hosts, ("127.0.0.1",))
        self.assertEqual(config.isolation.oauth_hosts, ())
        self.assertEqual(config.thinking_level, "off")

    def test_codex_selection_restores_egress_after_ollama(self):
        config = self.config().for_model("ollama/qwen3:8b").for_model("openai-codex/gpt-5.6-luna")
        self.assertEqual(config.isolation.model_hosts, ("chatgpt.com",))
        self.assertEqual(config.isolation.oauth_hosts, ("auth.openai.com",))

    def test_ollama_model_limits_stage_openai_compatibility_config(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = create_isolated_workspace(Path(temp), self.identity())
            config = self.config(per_agent_token_budget=17).for_model("ollama/qwen3:8b")
            path = _prepare_model_limits(workspace, config)
            payload = json.loads(path.read_text(encoding="utf-8"))
            provider = payload["providers"]["ollama"]
            self.assertEqual(provider["baseUrl"], "http://127.0.0.1:11434/v1")
            self.assertEqual(provider["api"], "openai-completions")
            self.assertEqual(provider["models"], [{"id": "qwen3:8b", "name": "Qwen3 8B 4-bit"}])
            self.assertEqual(provider["modelOverrides"]["qwen3:8b"]["maxTokens"], 17)
            self.assertFalse(provider["modelOverrides"]["qwen3:8b"]["samplingParams"]["think"])

    def test_ollama_relay_allows_only_controller_selected_local_target(self):
        relay = _ModelEgressProxy(
            Path("/tmp/unused-ollama-relay.sock"),
            (),
            local_target=("127.0.0.1", 11434),
        )
        self.assertTrue(relay._allowed("127.0.0.1", 11434))
        self.assertFalse(relay._allowed("127.0.0.1", 443))
        self.assertFalse(relay._allowed("localhost", 11434))
        self.assertFalse(relay._allowed("chatgpt.com", 443))
        self.assertFalse(relay._allowed("opencode.ai", 443))
        self.assertTrue(relay._parse_local_request(
            b"POST /v1/chat/completions HTTP/1.1\r\n"
            b"Host: 127.0.0.1:11434\r\n"
            b"Content-Length: 2\r\n\r\n"
        ))
        self.assertTrue(relay._parse_local_request(
            b"POST http://127.0.0.1:11434/v1/chat/completions HTTP/1.1\r\n"
            b"Host: 127.0.0.1:11434\r\n\r\n"
        ))
        self.assertFalse(relay._parse_local_request(
            b"GET /v1/models HTTP/1.1\r\nHost: 127.0.0.1:11434\r\n\r\n"
        ))
        self.assertFalse(relay._parse_local_request(
            b"POST /v1/chat/completions HTTP/1.1\r\nHost: chatgpt.com:443\r\n\r\n"
        ))

    def test_unknown_ollama_tag_is_rejected(self):
        with self.assertRaises(RuntimeConfigError):
            self.config().for_model("ollama/qwen3:14b")

    def test_ollama_probe_records_digest_and_checkpoint_pin(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({
            "models": [{"name": "qwen3:8b", "digest": "sha256:test-digest"}],
        }).encode("utf-8")
        config = self.config().for_model("ollama/qwen3:8b")
        with patch("apart_incident_response.runtime.urllib.request.urlopen", return_value=response):
            probe = probe_ollama(config)
        self.assertEqual(probe["ollama_host"], "http://127.0.0.1:11434")
        self.assertEqual(probe["ollama_model"], "qwen3:8b")
        self.assertEqual(probe["digest"], "sha256:test-digest")
        self.assertEqual(probe["checkpoint"]["revision"], "47719a242beab8f9aecc40ce3928b034dd5dd559")

    def test_opencode_does_not_use_configured_codex_oauth_store(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = create_isolated_workspace(Path(temp) / "runs", self.identity())
            config = self.config(pi_auth_store_env="TEST_AUTH_STORE").for_model("opencode-go/kimi-k2.6")
            with patch.dict(os.environ, {}, clear=True):
                self.assertIsNone(_resolve_auth_store(config, None, workspace))
            self.assertEqual(config.pi_auth_store_env, "TEST_AUTH_STORE")

    def test_opencode_relay_allows_only_opencode_ai_https(self):
        relay = _ModelEgressProxy(Path("/tmp/unused-opencode-relay.sock"), ("opencode.ai",))
        self.assertTrue(relay._allowed("opencode.ai", 443))
        self.assertFalse(relay._allowed("auth.openai.com", 443))
        self.assertFalse(relay._allowed("example.com", 443))
        self.assertFalse(relay._allowed("opencode.ai", 80))

    def test_model_relay_denies_malformed_proxy_request(self):
        relay = _ModelEgressProxy(Path("/tmp/unused-relay.sock"), ("chatgpt.com", "auth.openai.com"))
        client = MagicMock()
        client.recv.return_value = b"GET https://example.com/ HTTP/1.1\r\n\r\n"
        relay._handle_client(client)
        self.assertTrue(any(b"403 Forbidden" in call.args[0] for call in client.sendall.call_args_list))
        client.close.assert_called_once()

    def test_extension_is_mounted_and_enabled_explicitly(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            extension = root / "tools" / "experiment.ts"
            extension.parent.mkdir()
            extension.write_text("export default {};", encoding="utf-8")
            workspace = create_isolated_workspace(root / "runs", self.identity())
            config = self.config(isolation=IsolationPolicy(sandbox="none", allow_unsafe_for_tests=True))
            command = build_pi_command(config, self.identity(), workspace, extension)
            self.assertIn("--no-builtin-tools", command)
            self.assertIn("--extension", command)
            self.assertEqual(command[command.index("--extension") + 1], str(extension))

    def test_bubblewrap_mounts_extension_and_auth_without_host_paths_in_pi_argv(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pi_root = root / "pi"
            (pi_root / "packages/coding-agent").mkdir(parents=True)
            (pi_root / "node_modules").mkdir()
            (pi_root / "packages/coding-agent/package.json").write_text(
                json.dumps({"version": "0.83.0"}), encoding="utf-8"
            )
            extension = root / "tools" / "experiment.ts"
            extension.parent.mkdir()
            extension.write_text("export default {};", encoding="utf-8")
            auth_file = root / "auth.json"
            auth_file.write_text("{}\n", encoding="utf-8")
            config = self.config(
                pi_root_env="TEST_APART_PI_ROOT",
                pi_auth_file_env="TEST_APART_PI_AUTH",
                isolation=IsolationPolicy(model_network=True),
                launch_command=("bun", "run", "{pi_root}/packages/coding-agent/src/cli.ts"),
            )
            workspace = create_isolated_workspace(root / "runs", self.identity())
            with patch.dict(
                os.environ,
                {"TEST_APART_PI_ROOT": str(pi_root), "TEST_APART_PI_AUTH": str(auth_file)},
            ):
                command = build_pi_command(config, self.identity(), workspace, extension)
            self.assertNotIn(str(auth_file), command)
            self.assertIn(str(extension.parent), command)
            self.assertIn("/experiment/node_modules", command)
            self.assertEqual(command[command.index("--extension") + 1], "/experiment/extensions/experiment.ts")
            self.assertIn("--no-builtin-tools", command)

    def test_opencode_requires_pinned_pi_native_support(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pi_root = root / "pi"
            (pi_root / "packages/coding-agent/src").mkdir(parents=True)
            (pi_root / "packages/coding-agent/package.json").write_text(
                json.dumps({"version": "0.83.0"}), encoding="utf-8"
            )
            config = self.config(
                pi_root_env="TEST_APART_PI_ROOT",
                launch_command=("bun", "run", "{pi_root}/packages/coding-agent/src/cli.ts"),
            ).for_model("opencode-go/kimi-k2.6")
            workspace = create_isolated_workspace(root / "runs", self.identity())
            with patch.dict(os.environ, {"TEST_APART_PI_ROOT": str(pi_root)}):
                with self.assertRaisesRegex(RuntimeConfigError, "built-in OpenCode Go support"):
                    build_pi_command(config, self.identity(), workspace)

    def test_local_pi_checkout_is_resolved_from_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            pi_root = Path(temp) / "pi"
            (pi_root / "packages/coding-agent/src").mkdir(parents=True)
            (pi_root / "packages/coding-agent/package.json").write_text(
                json.dumps({"version": "0.83.0"}), encoding="utf-8"
            )
            config = self.config(
                pi_root_env="TEST_APART_PI_ROOT",
                launch_command=("bun", "run", "{pi_root}/packages/coding-agent/src/cli.ts"),
            )
            workspace = create_isolated_workspace(Path(temp) / "runs", self.identity())
            with patch.dict(os.environ, {"TEST_APART_PI_ROOT": str(pi_root)}):
                command = build_pi_command(config, self.identity(), workspace)
            self.assertTrue(any(str(pi_root) in part for part in command))

    def test_system_budget_is_atomic(self):
        budget = SystemBudget(10, 2)
        self.assertTrue(budget.reserve(tokens=7, tool_calls=1))
        self.assertFalse(budget.reserve(tokens=4, tool_calls=0))
        self.assertEqual(budget.tokens_used, 7)
        self.assertEqual(budget.tool_calls_used, 1)
        self.assertTrue(budget.reserve(tokens=3, tool_calls=1))
        self.assertFalse(budget.reserve(tokens=0, tool_calls=1))

    def test_system_budget_claim_is_reserved_before_launch(self):
        budget = SystemBudget(10, 2)
        claim = budget.claim(10, 2)
        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertEqual((claim.token_limit, claim.tool_call_limit), (10, 2))
        self.assertIsNone(budget.claim(1, 1))
        self.assertEqual(budget.snapshot()["tokens_reserved"], 10)
        self.assertTrue(budget.settle(claim, 3, 1))
        self.assertEqual(budget.tokens_used, 3)
        self.assertEqual(budget.tool_calls_used, 1)
        self.assertEqual(budget.snapshot()["tokens_reserved"], 0)

    def test_system_budget_settlement_bounds_actual_over_claim(self):
        budget = SystemBudget(10, 2)
        claim = budget.claim(10, 2)
        assert claim is not None
        settlement = budget.settle(claim, tokens=15, tool_calls=3)
        self.assertFalse(settlement)
        self.assertEqual(settlement.token_overage, 5)
        self.assertEqual(settlement.tool_call_overage, 1)
        snapshot = budget.snapshot()
        self.assertEqual(snapshot["tokens_used"], 10)
        self.assertEqual(snapshot["tool_calls_used"], 2)
        self.assertLessEqual(snapshot["tokens_used"] + snapshot["tokens_reserved"], snapshot["token_limit"])
        self.assertLessEqual(snapshot["tool_calls_used"] + snapshot["tool_calls_reserved"], snapshot["tool_call_limit"])
        with self.assertRaises(RuntimeConfigError):
            budget.settle(claim, 0, 0)

    def test_system_budget_concurrent_claims_are_atomic(self):
        budget = SystemBudget(10, 4)
        barrier = threading.Barrier(8)
        claims = []
        violations = []
        lock = threading.Lock()

        def claim_once():
            barrier.wait()
            claim = budget.claim(4, 1)
            snapshot = budget.snapshot()
            if snapshot["tokens_used"] + snapshot["tokens_reserved"] > snapshot["token_limit"]:
                with lock:
                    violations.append("tokens")
            if snapshot["tool_calls_used"] + snapshot["tool_calls_reserved"] > snapshot["tool_call_limit"]:
                with lock:
                    violations.append("tool_calls")
            if claim is not None:
                with lock:
                    claims.append(claim)

        threads = [threading.Thread(target=claim_once) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(violations, [])
        self.assertEqual(len(claims), 2)
        for claim in claims:
            self.assertTrue(budget.settle(claim, 4, 1))
        snapshot = budget.snapshot()
        self.assertLessEqual(snapshot["tokens_used"] + snapshot["tokens_reserved"], snapshot["token_limit"])
        self.assertLessEqual(snapshot["tool_calls_used"] + snapshot["tool_calls_reserved"], snapshot["tool_call_limit"])

    def test_pi_provider_max_output_override_is_staged(self):
        with tempfile.TemporaryDirectory() as temp:
            identity = self.identity()
            workspace = create_isolated_workspace(Path(temp), identity)
            config = self.config(per_agent_token_budget=17)
            path = _prepare_model_limits(workspace, config)
            self.assertIsNotNone(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["providers"]["openai-codex"]["modelOverrides"]["gpt-5.6-luna"]["maxTokens"],
                17,
            )

    def test_agent_lifecycle_writes_complete_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake_agent = root / "fake_agent.py"
            fake_agent.write_text(
                textwrap.dedent(
                    """
                    import json
                    import sys
                    prompt = sys.stdin.read()
                    print(json.dumps({"type": "tool_call", "name": "task_read"}), flush=True)
                    print(json.dumps({"type": "message_end", "usage": {"total_tokens": 7}, "text": prompt.strip()}), flush=True)
                    """
                ),
                encoding="utf-8",
            )
            identity = self.identity()
            workspace = create_isolated_workspace(root / "runs", identity)
            config = self.config(
                launch_command=(sys.executable, str(fake_agent)),
                per_agent_token_budget=10,
                per_agent_tool_call_budget=2,
                aggregate_token_budget=10,
                aggregate_tool_call_budget=2,
                timeout_seconds=2,
            )
            result = AgentRun(config, identity, workspace, SystemBudget(10, 2)).run("diagnose this")
            self.assertEqual(result.status.value, "completed")
            self.assertEqual(result.final_response, "diagnose this")
            self.assertEqual(result.tokens_used, 7)
            self.assertEqual(result.tool_calls_used, 1)
            self.assertTrue((workspace.artifact_dir / "metadata.json").exists())
            self.assertTrue((workspace.artifact_dir / "events.json").exists())
            saved = json.loads((workspace.artifact_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "completed")

    def test_controller_credential_is_redacted_from_agent_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            secret = "controller-secret-for-runtime"
            fake_agent = root / "credential_echo_agent.py"
            fake_agent.write_text(
                textwrap.dedent(
                    """
                    import json
                    import os
                    from pathlib import Path

                    credential = Path(os.environ["APART_CONTROLLER_CREDENTIAL_FILE"]).read_text().strip()
                    print(json.dumps({
                        "type": "message_end",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": credential}],
                            "usage": {"totalTokens": 1},
                        },
                    }), flush=True)
                    """
                ),
                encoding="utf-8",
            )

            class FixedAuthority(ControllerCredentialAuthority):
                def issue(self, identity):
                    return secret

            identity = self.identity(condition=Condition.C1)
            workspace = create_isolated_workspace(root / "runs", identity)
            service = ConstrainedToolService(
                TaskToolService(TaskCatalog({})),
                credentials=FixedAuthority(),
                artifact_root=root / "runs",
            )
            config = self.config(
                launch_command=(sys.executable, str(fake_agent)),
                per_agent_token_budget=10,
                per_agent_tool_call_budget=2,
                aggregate_token_budget=10,
                aggregate_tool_call_budget=2,
                timeout_seconds=2,
            )
            result = AgentRun(config, identity, workspace, SystemBudget(10, 2), service).run("diagnose")
            self.assertEqual(result.status.value, "completed")
            for artifact_path in workspace.artifact_dir.iterdir():
                self.assertNotIn(secret.encode("utf-8"), artifact_path.read_bytes(), artifact_path.name)

    def test_opencode_key_is_staged_only_transiently_and_redacted_from_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            secret = "opencode-secret-for-test"
            key_file = root / "opencode-key"
            key_file.write_text(
                json.dumps({"opencode-go": {"type": "api_key", "key": secret}}) + "\n",
                encoding="utf-8",
            )
            key_file.chmod(0o600)
            fake_agent = root / "opencode_fake_agent.py"
            fake_agent.write_text(
                textwrap.dedent(
                    """
                    import json
                    import os
                    import sys
                    from pathlib import Path

                    auth_path = Path(os.environ["HOME"]) / ".pi" / "agent" / "auth.json"
                    staged = json.loads(auth_path.read_text())
                    secret = staged["opencode-go"]["key"]
                    child_env = os.environ.get("OPENCODE_API_KEY")
                    print(json.dumps({
                        "type": "message_end",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": secret + "|" + repr(child_env)}],
                            "usage": {"totalTokens": 3},
                            "stopReason": "stop",
                        },
                    }), flush=True)
                    sys.stdin.read()
                    """
                ),
                encoding="utf-8",
            )
            identity = self.identity()
            workspace = create_isolated_workspace(root / "runs", identity)
            config = self.config(
                launch_command=(sys.executable, str(fake_agent)),
                api_key_file_env="TEST_OPENCODE_KEY_FILE",
                api_key_env="TEST_OPENCODE_KEY_ENV",
                pi_auth_file_env=None,
                pi_auth_store_env=None,
                per_agent_token_budget=10,
                per_agent_tool_call_budget=2,
                aggregate_token_budget=10,
                aggregate_tool_call_budget=2,
                timeout_seconds=2,
            ).for_model("opencode-go/kimi-k2.6")
            with patch.dict(
                os.environ,
                {
                    "TEST_OPENCODE_KEY_FILE": str(key_file),
                    "TEST_OPENCODE_KEY_ENV": "should-not-be-forwarded",
                    "OPENCODE_API_KEY": "ambient-value",
                },
            ):
                result = AgentRun(
                    config, identity, workspace, SystemBudget(10, 2)
                ).run("diagnose this")
            self.assertEqual(result.status.value, "completed")
            self.assertEqual(result.final_response, "[REDACTED]|None")
            self.assertNotIn(secret, json.dumps(result.to_dict()))
            for artifact in workspace.artifact_dir.rglob("*"):
                if artifact.is_file():
                    self.assertNotIn(secret, artifact.read_text(encoding="utf-8"))
            self.assertFalse((workspace.root / "home" / ".pi" / "agent" / "auth.json").exists())
            self.assertFalse((workspace.root / "home" / ".pi" / "agent" / "models.json").exists())

    def test_pi_json_stream_replay_uses_authoritative_usage_and_message(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake_agent = root / "pi_json_replay.py"
            events = [
                {
                    "type": "message_start",
                    "message": {"role": "assistant", "content": [], "timestamp": 1},
                },
                {"type": "message_update", "usage": {"totalTokens": 120}},
                {
                    "type": "message_end",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "toolCall", "id": "call-1", "name": "task_read", "arguments": {}}],
                        "usage": {"totalTokens": 120},
                        "stopReason": "toolUse",
                        "timestamp": 1,
                    },
                },
                {"type": "tool_execution_start", "toolCallId": "call-1", "toolName": "task_read"},
                {"type": "tool_execution_end", "toolCallId": "call-1", "toolName": "task_read", "result": {}, "isError": False},
                {
                    "type": "message_start",
                    "message": {"role": "assistant", "content": [], "timestamp": 2},
                },
                {"type": "message_update", "usage": {"totalTokens": 100}},
                {
                    "type": "message_end",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "final"}],
                        "usage": {"totalTokens": 100},
                        "stopReason": "stop",
                        "responseId": "response-2",
                        "timestamp": 2,
                    },
                },
            ]
            fake_agent.write_text(
                "import json, sys\n" + "events = " + repr(events) + "\n" +
                "for event in events: print(json.dumps(event), flush=True)\n",
                encoding="utf-8",
            )
            identity = self.identity()
            workspace = create_isolated_workspace(root / "runs", identity)
            config = self.config(
                launch_command=(sys.executable, str(fake_agent)),
                per_agent_token_budget=300,
                per_agent_tool_call_budget=2,
                aggregate_token_budget=300,
                aggregate_tool_call_budget=2,
                timeout_seconds=2,
            )
            result = AgentRun(config, identity, workspace, SystemBudget(300, 2)).run("diagnose this")
            self.assertEqual(result.status.value, "completed")
            self.assertEqual(result.tokens_used, 220)
            self.assertEqual(result.tool_calls_used, 1)
            self.assertEqual(result.final_response, "final")

    def test_pi_provider_error_is_not_reported_as_completed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake_agent = root / "pi_error.py"
            fake_agent.write_text(
                "import json\n"
                "print(json.dumps({'type': 'message_end', 'message': {"
                "'role': 'assistant', 'content': [], 'stopReason': 'error', "
                "'errorMessage': 'provider unavailable', 'usage': {'totalTokens': 0}}}), flush=True)\n",
                encoding="utf-8",
            )
            identity = self.identity()
            workspace = create_isolated_workspace(root / "runs", identity)
            config = self.config(
                launch_command=(sys.executable, str(fake_agent)),
                per_agent_token_budget=10,
                per_agent_tool_call_budget=2,
                aggregate_token_budget=10,
                aggregate_tool_call_budget=2,
            )
            result = AgentRun(config, identity, workspace, SystemBudget(10, 2)).run("ping")
            self.assertEqual(result.status.value, "failed")
            self.assertIn("provider unavailable", result.failure_reason or "")

    def test_agent_actual_usage_over_claim_is_explicit_budget_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake_agent = root / "over_budget.py"
            fake_agent.write_text(
                "import json\n"
                "print(json.dumps({'type': 'message_end', 'message': {"
                "'role': 'assistant', 'content': [{'type': 'text', 'text': 'too much'}], "
                "'usage': {'totalTokens': 15}, 'stopReason': 'stop'}}), flush=True)\n",
                encoding="utf-8",
            )
            identity = self.identity()
            workspace = create_isolated_workspace(root / "runs", identity)
            config = self.config(
                launch_command=(sys.executable, str(fake_agent)),
                per_agent_token_budget=10,
                per_agent_tool_call_budget=2,
                aggregate_token_budget=10,
                aggregate_tool_call_budget=2,
            )
            budget = SystemBudget(10, 2)
            result = AgentRun(config, identity, workspace, budget).run("ping")
            self.assertEqual(result.status.value, "budget_exhausted")
            self.assertIn("provider usage exceeded", result.failure_reason or "")
            snapshot = budget.snapshot()
            self.assertEqual(snapshot["tokens_used"], 10)
            self.assertEqual(snapshot["tokens_over_budget"], 5)
            self.assertEqual(snapshot["tokens_reserved"], 0)
            self.assertLessEqual(snapshot["tokens_used"] + snapshot["tokens_reserved"], snapshot["token_limit"])

    def test_budget_claim_blocks_process_before_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            identity = self.identity()
            workspace = create_isolated_workspace(root / "runs", identity)
            config = self.config(
                per_agent_token_budget=10,
                per_agent_tool_call_budget=2,
                aggregate_token_budget=10,
                aggregate_tool_call_budget=2,
            )
            with patch("apart_incident_response.runtime.subprocess.Popen") as popen:
                result = AgentRun(config, identity, workspace, SystemBudget(9, 2)).run("ping")
            popen.assert_not_called()
            self.assertEqual(result.status.value, "budget_exhausted")
            self.assertIn("before provider launch", result.failure_reason or "")

    def test_auth_cleanup_runs_when_prompt_write_breaks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            auth_file = root / "auth.json"
            auth_file.write_text("{}\n", encoding="utf-8")
            identity = self.identity()
            workspace = create_isolated_workspace(root / "runs", identity)
            config = self.config(
                launch_command=(sys.executable, "-c", "pass"),
                pi_auth_file_env="TEST_APART_PI_AUTH",
                pi_auth_store_env="TEST_APART_PI_AUTH_STORE",
                per_agent_token_budget=10,
                per_agent_tool_call_budget=2,
                aggregate_token_budget=10,
                aggregate_tool_call_budget=2,
            )
            private_agent_home = workspace.root / "home" / ".pi" / "agent"
            private_agent_home.mkdir(parents=True)
            (private_agent_home / "auth.json.lock").mkdir()
            fake_process = MagicMock()
            fake_process.stdin.write.side_effect = BrokenPipeError("child exited")
            fake_process.poll.return_value = 0
            fake_process.wait.return_value = 0
            store = root / "controller-state" / "codex-auth.json"
            with patch.dict(
                os.environ,
                {
                    "TEST_APART_PI_AUTH": str(auth_file),
                    "TEST_APART_PI_AUTH_STORE": str(store),
                },
            ), patch(
                "apart_incident_response.runtime.subprocess.Popen", return_value=fake_process
            ):
                result = AgentRun(config, identity, workspace, SystemBudget(10, 2)).run("ping")
            self.assertEqual(result.status.value, "failed")
            self.assertFalse((workspace.root / "home" / ".pi" / "agent" / "auth.json").exists())
            self.assertFalse((workspace.root / "home" / ".pi" / "agent" / "auth.json.lock").exists())
            self.assertFalse((workspace.root / "home" / ".pi" / "agent" / "models.json").exists())
            self.assertTrue(store.exists())

    def test_cleanup_error_does_not_skip_proxy_shutdown_or_mask_result(self):
        with tempfile.TemporaryDirectory() as temp:
            identity = self.identity()
            workspace = create_isolated_workspace(Path(temp), identity)
            config = self.config(
                isolation=IsolationPolicy(model_network=True),
                per_agent_token_budget=10,
                per_agent_tool_call_budget=2,
                aggregate_token_budget=10,
                aggregate_tool_call_budget=2,
            )
            fake_process = MagicMock()
            fake_process.stdin.write.side_effect = BrokenPipeError("child exited")
            fake_process.poll.return_value = 0
            fake_process.wait.return_value = 0
            fake_proxy = MagicMock()
            with patch("apart_incident_response.runtime._ModelEgressProxy", return_value=fake_proxy), patch(
                "apart_incident_response.runtime.build_pi_command", return_value=["fake-agent"]
            ), patch("apart_incident_response.runtime.subprocess.Popen", return_value=fake_process), patch.object(
                AgentRun, "_cleanup_staged_auth", side_effect=OSError("cleanup failed")
            ):
                result = AgentRun(config, identity, workspace, SystemBudget(10, 2)).run("ping")
            self.assertEqual(result.status.value, "failed")
            fake_proxy.stop.assert_called_once()

    def test_submission_finalization_failure_preserves_completed_result(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake_agent = root / "complete_agent.py"
            fake_agent.write_text(
                textwrap.dedent(
                    """
                    import json
                    print(json.dumps({"type": "message_end", "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "completed"}],
                        "usage": {"totalTokens": 1},
                        "stopReason": "stop",
                    }}), flush=True)
                    """
                ),
                encoding="utf-8",
            )

            class FinalizationFailureService:
                def update_runtime_usage(self, identity, total_tokens, tool_calls):
                    return None

                def issue_credential(self, identity):
                    return "opaque-credential"

                def finalize_runtime_usage(self, identity):
                    raise ValueError("invalid task_submission artifact path")

            identity = self.identity()
            workspace = create_isolated_workspace(root / "runs", identity)
            config = self.config(
                launch_command=(sys.executable, str(fake_agent)),
                isolation=IsolationPolicy(sandbox="none", allow_unsafe_for_tests=True),
                per_agent_token_budget=10,
                per_agent_tool_call_budget=1,
                aggregate_token_budget=10,
                aggregate_tool_call_budget=1,
                timeout_seconds=2,
            )
            result = AgentRun(
                config,
                identity,
                workspace,
                SystemBudget(10, 1),
                FinalizationFailureService(),
            ).run("complete")

            self.assertEqual(result.status.value, "completed")
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(
                result.persistence_failure,
                "Task submission finalization failed (ValueError)",
            )
            saved = json.loads((workspace.artifact_dir / "result.json").read_text())
            self.assertEqual(saved["status"], "completed")
            self.assertEqual(saved["exit_code"], 0)
            self.assertEqual(
                saved["persistence_failure"],
                "Task submission finalization failed (ValueError)",
            )

    def test_auth_cleanup_handles_lock_file_symlink_and_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            identity = self.identity()
            workspace = create_isolated_workspace(Path(temp), identity)
            run = AgentRun(self.config(), identity, workspace, SystemBudget(10, 2))
            agent_home = workspace.root / "home" / ".pi" / "agent"
            agent_home.mkdir(parents=True)
            outside = Path(temp) / "outside-lock-target"
            outside.write_text("keep", encoding="utf-8")
            for shape in ("file", "symlink", "directory"):
                (agent_home / "auth.json").write_text("{}\n", encoding="utf-8")
                lock = agent_home / "auth.json.lock"
                if shape == "file":
                    lock.write_text("lock", encoding="utf-8")
                elif shape == "symlink":
                    lock.symlink_to(outside)
                else:
                    lock.mkdir()
                    (lock / "owner").write_text("lock", encoding="utf-8")
                run._cleanup_staged_auth()
                self.assertFalse((agent_home / "auth.json").exists())
                self.assertFalse(lock.exists() or lock.is_symlink())
            self.assertEqual(outside.read_text(encoding="utf-8"), "keep")

    def test_agent_timeout_produces_failure_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake_agent = root / "slow_agent.py"
            fake_agent.write_text(
                "import time; time.sleep(2)\n",
                encoding="utf-8",
            )
            identity = self.identity()
            workspace = create_isolated_workspace(root / "runs", identity)
            config = self.config(
                launch_command=(sys.executable, str(fake_agent)),
                per_agent_token_budget=10,
                per_agent_tool_call_budget=2,
                aggregate_token_budget=10,
                aggregate_tool_call_budget=2,
                timeout_seconds=0.05,
            )
            result = AgentRun(config, identity, workspace, SystemBudget(10, 2)).run("wait")
            self.assertEqual(result.status.value, "timed_out")
            self.assertEqual(json.loads((workspace.artifact_dir / "result.json").read_text(encoding="utf-8"))["status"], "timed_out")

    def test_json_config_round_trips(self):
        config = RuntimeConfig.from_json(Path("config/runtime.json"))
        self.assertEqual(config.pi_version, "0.85.1")
        self.assertEqual(config.model, "openai-codex/gpt-5.6-luna")
        self.assertEqual(config.pi_auth_file_env, "APART_PI_AUTH_FILE")
        self.assertEqual(config.pi_auth_store_env, "APART_PI_AUTH_STORE")
        self.assertEqual(config.per_agent_token_budget, 16_000)
        self.assertEqual(config.aggregate_token_budget, 48_000)
        self.assertTrue(config.isolation.model_network)
        self.assertEqual(config.isolation.model_hosts, ("chatgpt.com",))
        self.assertEqual(config.isolation.oauth_hosts, ("auth.openai.com",))
        encoded = json.dumps(config.to_dict())
        self.assertIn('"C2"', encoded)

    def test_oauth_refresh_persists_across_runs_without_mutating_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "codex-source.json"
            source_payload = {
                "tokens": {
                    "access_token": "access-0",
                    "refresh_token": "refresh-0",
                }
            }
            source.write_text(json.dumps(source_payload) + "\n", encoding="utf-8")
            source_bytes = source.read_bytes()
            store = root / "controller-state" / "codex-auth.json"
            fake_agent = root / "rotating_agent.py"
            fake_agent.write_text(
                textwrap.dedent(
                    """
                    import json
                    import os
                    import sys
                    from pathlib import Path

                    auth_path = Path(os.environ["HOME"]) / ".pi" / "agent" / "auth.json"
                    auth = json.loads(auth_path.read_text())
                    credentials = auth["openai-codex"]
                    refresh = credentials["refresh"]
                    if refresh == "refresh-0":
                        next_refresh = "refresh-1"
                    elif refresh == "refresh-1":
                        next_refresh = "refresh-2"
                    else:
                        print("unexpected refresh token", file=sys.stderr)
                        raise SystemExit(2)
                    credentials["access"] = "access-" + next_refresh[-1]
                    credentials["refresh"] = next_refresh
                    auth_path.write_text(json.dumps(auth) + "\\n")
                    print(json.dumps({"type": "message_end", "message": {
                        "role": "assistant", "content": [{"type": "text", "text": "rotated"}],
                        "usage": {"totalTokens": 1}, "stopReason": "stop"}}), flush=True)
                    """
                ),
                encoding="utf-8",
            )
            config = self.config(
                launch_command=(sys.executable, str(fake_agent)),
                pi_auth_file_env="TEST_AUTH_SOURCE",
                pi_auth_store_env="TEST_AUTH_STORE",
                per_agent_token_budget=10,
                per_agent_tool_call_budget=2,
                aggregate_token_budget=20,
                aggregate_tool_call_budget=4,
            )
            with patch.dict(
                os.environ,
                {"TEST_AUTH_SOURCE": str(source), "TEST_AUTH_STORE": str(store)},
            ):
                first_identity = self.identity("agent-1")
                first_workspace = create_isolated_workspace(root / "runs", first_identity)
                first = AgentRun(
                    config, first_identity, first_workspace, SystemBudget(20, 4)
                ).run("refresh")
                second_identity = self.identity("agent-2")
                second_workspace = create_isolated_workspace(root / "runs", second_identity)
                second = AgentRun(
                    config, second_identity, second_workspace, SystemBudget(20, 4)
                ).run("refresh")

            self.assertEqual(first.status.value, "completed")
            self.assertEqual(second.status.value, "completed")
            stored = json.loads(store.read_text(encoding="utf-8"))
            self.assertEqual(stored["auth"]["openai-codex"]["refresh"], "refresh-2")
            self.assertEqual(source.read_bytes(), source_bytes)
            self.assertEqual(store.stat().st_mode & 0o777, 0o600)
            self.assertEqual(store.parent.stat().st_mode & 0o777, 0o700)
            self.assertTrue(Path(f"{store}.lock").exists())
            for workspace in (first_workspace, second_workspace):
                agent_home = workspace.root / "home" / ".pi" / "agent"
                self.assertFalse((agent_home / "auth.json").exists())
                self.assertFalse((agent_home / "auth.json.lock").exists())
                self.assertFalse((agent_home / "models.json").exists())
                for artifact in workspace.artifact_dir.iterdir():
                    self.assertNotIn(b"refresh-", artifact.read_bytes())

    def test_concurrent_oauth_runs_overlap_and_preserve_atomic_refresh_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "codex-source.json"
            source.write_text(
                json.dumps(
                    {"tokens": {"access_token": "access-0", "refresh_token": "refresh-0"}}
                )
                + "\n",
                encoding="utf-8",
            )
            store = root / "controller-state" / "codex-auth.json"
            fake_agent = root / "rotating_agent.py"
            fake_agent.write_text(
                textwrap.dedent(
                    """
                    import json
                    import os
                    import time
                    from pathlib import Path

                    time.sleep(0.05)
                    auth_path = Path(os.environ["HOME"]) / ".pi" / "agent" / "auth.json"
                    auth = json.loads(auth_path.read_text())
                    credentials = auth["openai-codex"]
                    agent_id = os.environ["APART_AGENT_ID"]
                    refresh = credentials["refresh"]
                    if refresh != "refresh-0":
                        print("unexpected refresh token", file=sys.stderr)
                        raise SystemExit(2)
                    next_refresh = {"agent-1": "refresh-1", "agent-2": "refresh-2"}[agent_id]
                    credentials["access"] = "access-" + next_refresh[-1]
                    credentials["refresh"] = next_refresh
                    auth_path.write_text(json.dumps(auth) + "\\n")
                    print(json.dumps({"type": "message_end", "message": {
                        "role": "assistant", "content": [{"type": "text", "text": "rotated"}],
                        "usage": {"totalTokens": 1}, "stopReason": "stop"}}), flush=True)
                    """
                ),
                encoding="utf-8",
            )
            config = self.config(
                launch_command=(sys.executable, str(fake_agent)),
                pi_auth_file_env="TEST_AUTH_SOURCE",
                pi_auth_store_env="TEST_AUTH_STORE",
                per_agent_token_budget=10,
                per_agent_tool_call_budget=2,
                aggregate_token_budget=20,
                aggregate_tool_call_budget=4,
            )
            identities = [self.identity("agent-1"), self.identity("agent-2")]
            workspaces = [
                create_isolated_workspace(root / "runs", identity) for identity in identities
            ]
            results = []
            result_lock = threading.Lock()

            def run_agent(index):
                result = AgentRun(
                    config, identities[index], workspaces[index], SystemBudget(10, 2)
                ).run("refresh")
                with result_lock:
                    results.append(result)

            with patch.dict(
                os.environ,
                {"TEST_AUTH_SOURCE": str(source), "TEST_AUTH_STORE": str(store)},
            ):
                threads = [threading.Thread(target=run_agent, args=(index,)) for index in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

            self.assertEqual(len(results), 2)
            self.assertTrue(all(result.status.value == "completed" for result in results))
            started = [
                datetime.fromisoformat(result.provider_started_at.replace("Z", "+00:00"))
                for result in results
                if result.provider_started_at is not None
            ]
            ended = [datetime.fromisoformat(result.ended_at.replace("Z", "+00:00")) for result in results]
            self.assertEqual(len(started), 2)
            self.assertLess(max(started), min(ended), "authenticated AgentRun instances must overlap")
            stored = json.loads(store.read_text(encoding="utf-8"))
            stored_credentials = stored["auth"]["openai-codex"]
            valid_access_by_refresh = {"refresh-1": "access-1", "refresh-2": "access-2"}
            self.assertIn(stored_credentials["refresh"], valid_access_by_refresh)
            self.assertEqual(
                stored_credentials["access"],
                valid_access_by_refresh[stored_credentials["refresh"]],
                "controller store must contain one coherent winning OAuth credential",
            )
            self.assertEqual(stored_credentials["type"], "oauth")
            self.assertGreaterEqual(stored["revision"], 2)

    def test_auth_store_rejects_repository_workspace_and_insecure_parent_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.json"
            source.write_text("{}\n", encoding="utf-8")
            identity = self.identity()
            workspace = create_isolated_workspace(root / "runs", identity)
            config = self.config(
                pi_auth_file_env="TEST_AUTH_SOURCE",
                pi_auth_store_env="TEST_AUTH_STORE",
            )
            environment = {"TEST_AUTH_SOURCE": str(source)}

            with patch.dict(
                os.environ,
                {**environment, "TEST_AUTH_STORE": str(Path.cwd() / ".review-store.json")},
            ), self.assertRaisesRegex(RuntimeConfigError, "outside the repository"):
                _prepare_auth_file(source, workspace, config, hold_lock=True)

            workspace_alias = root / "workspace-alias"
            workspace_alias.symlink_to(workspace.workspace_root, target_is_directory=True)
            with patch.dict(
                os.environ,
                {**environment, "TEST_AUTH_STORE": str(workspace_alias / "store.json")},
            ), self.assertRaisesRegex(RuntimeConfigError, "outside the repository"):
                _prepare_auth_file(source, workspace, config, hold_lock=True)

            with patch.dict(
                os.environ,
                {**environment, "TEST_AUTH_STORE": str(source)},
            ), self.assertRaisesRegex(RuntimeConfigError, "must not overwrite"):
                _prepare_auth_file(source, workspace, config, hold_lock=True)

            insecure_parent = root / "existing-0755"
            insecure_parent.mkdir(mode=0o755)
            insecure_parent.chmod(0o755)
            before_mode = insecure_parent.stat().st_mode & 0o777
            with patch.dict(
                os.environ,
                {**environment, "TEST_AUTH_STORE": str(insecure_parent / "store.json")},
            ), self.assertRaisesRegex(RuntimeConfigError, "dedicated private directory"):
                _prepare_auth_file(source, workspace, config, hold_lock=True)
            self.assertEqual(insecure_parent.stat().st_mode & 0o777, before_mode)
            self.assertFalse((insecure_parent / "store.json").exists())

    def test_oauth_persistence_failure_is_visible_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state_dir = root / "controller-state"
            state_dir.mkdir(mode=0o700)
            state_dir.chmod(0o700)
            store = state_dir / "codex-auth.json"
            store.write_text(
                json.dumps(
                    {
                        "format": 1,
                        "revision": 1,
                        "auth": {
                            "openai-codex": {
                                "type": "oauth",
                                "access": "access-0",
                                "refresh": "refresh-0",
                                "expires": 0,
                            }
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            store.chmod(0o600)
            fake_agent = root / "rotating_agent.py"
            fake_agent.write_text(
                textwrap.dedent(
                    """
                    import json
                    import os
                    import sys
                    from pathlib import Path

                    failed = sys.stdin.read().strip() == "agent-failure"
                    auth_path = Path(os.environ["HOME"]) / ".pi" / "agent" / "auth.json"
                    auth = json.loads(auth_path.read_text())
                    auth["openai-codex"]["access"] = "rotated-" + "access-" + "value"
                    auth["openai-codex"]["refresh"] = "rotated-" + "refresh-" + "value"
                    auth_path.write_text(json.dumps(auth) + "\\n")
                    message = {"type": "message_end", "message": {
                        "role": "assistant", "content": [{"type": "text", "text": "completed"}],
                        "usage": {"totalTokens": 1},
                        "stopReason": "error" if failed else "stop",
                    }}
                    if failed:
                        message["message"]["errorMessage"] = "agent failed"
                    print(json.dumps(message), flush=True)
                    if failed:
                        raise SystemExit(7)
                    """
                ),
                encoding="utf-8",
            )
            identity = self.identity()
            workspace = create_isolated_workspace(root / "runs", identity)
            agent_home = workspace.root / "home" / ".pi" / "agent"
            agent_home.mkdir(parents=True)
            (agent_home / "auth.json.lock").mkdir()
            config = self.config(
                launch_command=(sys.executable, str(fake_agent)),
                pi_auth_file_env="TEST_MISSING_SOURCE",
                pi_auth_store_env="TEST_AUTH_STORE",
                per_agent_token_budget=10,
                per_agent_tool_call_budget=2,
                aggregate_token_budget=10,
                aggregate_tool_call_budget=2,
            )
            with patch.dict(
                os.environ,
                {"TEST_MISSING_SOURCE": "", "TEST_AUTH_STORE": str(store)},
            ), patch(
                "apart_incident_response.runtime._write_auth_store",
                side_effect=OSError("simulated store write failure"),
            ):
                result = AgentRun(config, identity, workspace, SystemBudget(10, 2)).run("refresh")

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.status.value, "failed")
            self.assertEqual(
                result.persistence_failure,
                "OAuth credential persistence failed (OSError)",
            )
            self.assertIn("OAuth credential persistence failed (OSError)", result.failure_reason or "")
            artifact = json.loads((workspace.artifact_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(artifact["status"], "failed")
            self.assertEqual(artifact["persistence_failure"], "OAuth credential persistence failed (OSError)")
            for artifact_path in workspace.artifact_dir.iterdir():
                self.assertNotIn(b"rotated-access-value", artifact_path.read_bytes())
                self.assertNotIn(b"rotated-refresh-value", artifact_path.read_bytes())
            self.assertFalse((agent_home / "auth.json").exists())
            self.assertFalse((agent_home / "auth.json.lock").exists())
            self.assertFalse((agent_home / "models.json").exists())
            stored = json.loads(store.read_text(encoding="utf-8"))
            self.assertEqual(stored["auth"]["openai-codex"]["refresh"], "refresh-0")

            failed_identity = self.identity("agent-2")
            failed_workspace = create_isolated_workspace(root / "runs", failed_identity)
            failed_agent_home = failed_workspace.root / "home" / ".pi" / "agent"
            failed_agent_home.mkdir(parents=True)
            (failed_agent_home / "auth.json.lock").mkdir()
            with patch.dict(
                os.environ,
                {"TEST_MISSING_SOURCE": "", "TEST_AUTH_STORE": str(store)},
            ), patch(
                "apart_incident_response.runtime._write_auth_store",
                side_effect=OSError("simulated store write failure"),
            ):
                failed_result = AgentRun(
                    config,
                    failed_identity,
                    failed_workspace,
                    SystemBudget(10, 2),
                ).run("agent-failure")
            self.assertEqual(failed_result.exit_code, 7)
            self.assertEqual(failed_result.status.value, "failed")
            self.assertIn("agent failed", failed_result.failure_reason or "")
            self.assertIn(
                "OAuth credential persistence failed (OSError)",
                failed_result.failure_reason or "",
            )
            self.assertEqual(
                failed_result.persistence_failure,
                "OAuth credential persistence failed (OSError)",
            )
            failed_artifact = json.loads(
                (failed_workspace.artifact_dir / "result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(failed_artifact["status"], "failed")
            self.assertIn("agent failed", failed_artifact["failure_reason"])
            self.assertFalse((failed_agent_home / "auth.json").exists())
            self.assertFalse((failed_agent_home / "auth.json.lock").exists())

            lock_path = Path(f"{store}.lock")
            with lock_path.open("r+") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


if __name__ == "__main__":
    unittest.main()
