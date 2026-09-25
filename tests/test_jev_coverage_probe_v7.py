import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import jev_coverage_manifest_preregistration_v7 as prv7
from apart_incident_response import jev_coverage_probe_v7 as probe
from apart_incident_response import jev_openrouter_catalog as catalog


REPO_ROOT = Path(__file__).resolve().parents[1]
COMMITTED = REPO_ROOT / "runs" / "epic-126" / "jev-ling-transport-probe-v7.json"

APPROVAL = "reviewer-repair-191-transport-probe-2026-09-24"


def good_catalog():
    return {"catalog_version": catalog.CATALOG_VERSION, "catalog_url": catalog.CATALOG_URL,
            "model_count": 460,
            "entries": {catalog.PAID_LING_MODEL: {"present": True,
                                                  "prompt_usd_per_tok": "0.00000006",
                                                  "completion_usd_per_tok": "0.00000018",
                                                  "context_length": 262144},
                        catalog.FREE_LING_MODEL: {"present": False}},
            "requested_slugs": [catalog.PAID_LING_MODEL, catalog.FREE_LING_MODEL]}


class ProbeCapsAndContractTests(unittest.TestCase):
    def test_caps_are_separately_tiny(self):
        self.assertEqual(probe.PROBE_MAX_REQUESTS, 1)
        self.assertEqual(probe.PROBE_MAX_TOKENS, 16)
        self.assertEqual(probe.PROBE_COST_CEILING_USD, 0.01)
        self.assertEqual(probe.PROBE_MODEL, "inclusionai/ling-3.0-flash-vl")

    def test_scope_and_approval_basis_are_accurate(self):
        self.assertIn("routing, credentials, HTTP success, and usage/pricing only",
                      probe.PROBE_SCOPE)
        self.assertIn("not behavioral or writer-output capability", probe.PROBE_SCOPE)
        self.assertIn("derived from a reviewer recommendation", probe.APPROVAL_BASIS)
        self.assertIn("rather than a separately supplied formal approval string",
                      probe.APPROVAL_BASIS)
        self.assertIn("not retrospective experimental authorization",
                      probe.APPROVAL_BASIS)
        self.assertIn("does not authorize v7 collection", probe.APPROVAL_BASIS)

    def test_interpret_probe_artifact_routing_vs_writer_output(self):
        base = {"attempts": {"physical": 1, "cap": 1},
                "diagnostics": [{"status": 200}]}
        routing_only = dict(base, outcome={"outcome": "empty_output",
                                           "finish_reason": "length",
                                           "error_class": None})
        reading = probe.interpret_probe_artifact(routing_only)
        self.assertTrue(reading["routing_success"])
        self.assertFalse(reading["writer_output_validated"])

        usable = dict(base, outcome={"outcome": "deliberate_silence",
                                     "finish_reason": None, "error_class": None})
        reading = probe.interpret_probe_artifact(usable)
        self.assertTrue(reading["routing_success"])
        self.assertTrue(reading["writer_output_validated"])

        failed = dict(base, outcome={"outcome": "writer_error",
                                     "error_class": "writer_http_404_...",
                                     "finish_reason": None})
        reading = probe.interpret_probe_artifact(failed)
        self.assertFalse(reading["routing_success"])
        self.assertFalse(reading["writer_output_validated"])

        # malformed payloads never raise
        for weird in (None, {}, {"attempts": "x"}, {"attempts": {"physical": True},
                                                    "outcome": []},
                      {"diagnostics": "nope", "outcome": None}):
            reading = probe.interpret_probe_artifact(weird)
            self.assertIn("routing_success", reading)

    def test_pricing_constants_match_frozen_cost_model(self):
        self.assertEqual(probe.LING_PROMPT_USD_PER_MTOK,
                         prv7.LING_PROMPT_USD_PER_MTOK)
        self.assertEqual(probe.LING_COMPLETION_USD_PER_MTOK,
                         prv7.LING_COMPLETION_USD_PER_MTOK)
        self.assertEqual(prv7.LING_PROMPT_USD_PER_MTOK, 0.06)
        self.assertEqual(prv7.LING_COMPLETION_USD_PER_MTOK, 0.18)

    def test_probe_cost_estimator(self):
        self.assertEqual(probe.estimate_probe_cost_usd(0, 0), 0.0)
        self.assertEqual(probe.estimate_probe_cost_usd(1_000_000, 1_000_000), 0.24)
        self.assertLessEqual(probe.estimate_probe_cost_usd(8192, 16),
                             probe.PROBE_COST_CEILING_USD)
        # retired legacy Ling input ceiling must not resurface in probe math docs
        self.assertEqual(prv7.LING_INPUT_TOKEN_CEILING, 8192)

    def test_refuses_without_approval_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "probe.json"
            def explode(*args, **kwargs):
                raise AssertionError("provider call without approval")
            with patch("urllib.request.urlopen", side_effect=explode):
                report = probe.run_probe(None, output=output)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["stop_reason"], "missing_approval")
            self.assertEqual(report["provider_calls"], 0)
            self.assertFalse(output.exists())

    def test_refuses_existing_output_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "probe.json"
            output.write_text("SENTINEL", encoding="utf-8")
            def explode(*args, **kwargs):
                raise AssertionError("provider call with existing output")
            with patch("urllib.request.urlopen", side_effect=explode):
                report = probe.run_probe(APPROVAL, output=output)
            self.assertEqual(report["stop_reason"], "output_exists")
            self.assertEqual(output.read_text(encoding="utf-8"), "SENTINEL")

    def test_unreachable_catalog_blocks_before_any_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "probe.json"
            with patch.object(catalog, "fetch_model_catalog",
                              side_effect=RuntimeError("no network")), \
                    patch("urllib.request.urlopen", side_effect=AssertionError(
                        "completion attempted")):
                report = probe.run_probe(APPROVAL, output=output)
            self.assertEqual(report["stop_reason"],
                             "catalog_unreachable: RuntimeError")
            self.assertFalse(output.exists())

    def test_catalog_gate_failure_blocks_before_any_completion(self):
        gated = good_catalog()
        gated["entries"][catalog.PAID_LING_MODEL] = {"present": False}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "probe.json"
            with patch.object(catalog, "fetch_model_catalog", return_value=gated), \
                    patch("urllib.request.urlopen",
                          side_effect=AssertionError("completion attempted")):
                report = probe.run_probe(APPROVAL, output=output)
            self.assertEqual(report["stop_reason"], "catalog_gate_failed")
            self.assertFalse(output.exists())

    def test_missing_credentials_blocks_before_any_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "probe.json"
            with patch.object(catalog, "fetch_model_catalog", return_value=good_catalog()), \
                    patch.object(probe.bd, "_api_key", return_value=None), \
                    patch("urllib.request.urlopen",
                          side_effect=AssertionError("completion attempted")):
                report = probe.run_probe(APPROVAL, output=output)
            self.assertEqual(report["stop_reason"], "missing_ling_credentials")
            self.assertFalse(output.exists())

    def test_cli_requires_approval_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "probe.json"
            def explode(*args, **kwargs):
                raise AssertionError("provider call from CLI without approval")
            with patch("urllib.request.urlopen", side_effect=explode):
                rc = probe.main(["--output", str(output)])
            self.assertEqual(rc, 2)
            self.assertFalse(output.exists())


class CommittedProbeArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(COMMITTED.read_text(encoding="utf-8"))

    def test_committed_probe_matches_pin_and_contract(self):
        import hashlib
        actual = hashlib.sha256(COMMITTED.read_bytes()).hexdigest()
        self.assertEqual(actual, probe.__dict__.get("EXPECTED_PROBE_SHA256",
                                                    prv7.EXPECTED_PROBE_SHA256))
        self.assertEqual(actual, prv7.EXPECTED_PROBE_SHA256)
        self.assertEqual(self.document["probe_version"], probe.PROBE_VERSION)
        self.assertEqual(self.document["scope"], "nonexperimental_transport_probe")
        interpretation = probe.interpret_probe_artifact(self.document)
        self.assertTrue(interpretation["routing_success"])
        self.assertFalse(interpretation["writer_output_validated"])
        self.assertTrue(interpretation["http_200_seen"])
        self.assertEqual(interpretation["outcome"], "empty_output")
        self.assertEqual(interpretation["finish_reason"], "length")
        # original historical outcome fields retained verbatim (artifact immutable)
        self.assertEqual(self.document["outcome"]["outcome"], "empty_output")
        self.assertEqual(self.document["outcome"]["finish_reason"], "length")
        self.assertIsNone(self.document["outcome"]["answer"])
        self.assertEqual(self.document["model"], probe.PROBE_MODEL)
        self.assertEqual(self.document["attempts"], {"physical": 1, "cap": 1})
        self.assertEqual(self.document["approval"], APPROVAL)
        entries = self.document["catalog"]["entries"]
        self.assertTrue(entries[catalog.PAID_LING_MODEL]["present"])
        self.assertFalse(entries[catalog.FREE_LING_MODEL]["present"])
        self.assertEqual(self.document["pricing_frozen_usd_per_mtok"],
                         {"prompt": 0.06, "completion": 0.18})
        self.assertLessEqual(self.document["cost"]["estimated_cost_usd"],
                             probe.PROBE_COST_CEILING_USD)
        self.assertFalse(self.document["raw_response_retained"])
        self.assertFalse(self.document["credentials_retained"])
        dumped = json.dumps(self.document).lower()
        for marker in ('"bearer ', '"api_key"', '"authorization":', "sk-or-v1"):
            self.assertNotIn(marker, dumped)


if __name__ == "__main__":
    unittest.main()
