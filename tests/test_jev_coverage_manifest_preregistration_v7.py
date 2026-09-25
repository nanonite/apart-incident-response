import copy
import hashlib
import json
import unittest
from pathlib import Path

from apart_incident_response import jev_coverage_manifest_preregistration_v7 as reg
from apart_incident_response import jev_coverage_manifest_preregistration_v6 as regv6


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = REPO_ROOT / "runs" / "epic-126" / "jev-coverage-manifest-preregistration-v7.json"


def load_locked() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def verify(document, **kwargs):
    kwargs.setdefault("repo_root", REPO_ROOT)
    kwargs.setdefault("journal_exists", False)
    kwargs.setdefault("report_exists", False)
    return reg.verify_against_coverage_manifest_preregistration_v7(document, **kwargs)


class ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_locked()

    def test_byte_reproducible_build(self):
        self.assertEqual(self.document,
                         reg.build_coverage_manifest_preregistration_v7(approved=True,
                                                                        repo_root=REPO_ROOT))

    def test_locked_status_and_live_authorization_false(self):
        self.assertEqual(self.document["preregistration_version"], reg.COVERAGE_PREREG_VERSION)
        self.assertEqual(self.document["status"], reg.COVERAGE_LOCKED_STATUS)
        self.assertFalse(self.document["approval_required"])
        self.assertTrue(self.document["approval"]["approved"])
        self.assertEqual(self.document["approval"]["scope"], "v7_registration_lock_only")
        self.assertFalse(self.document["approval"]["live_collection_authorized"])
        self.assertFalse(self.document["live_collection_authorized"])
        self.assertTrue(self.document["lock_is_not_live_authorization"])

    def test_committed_artifact_verifies_with_freshness_overrides(self):
        result = verify(self.document)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["errors"], [])
        self.assertFalse(result["live_collection_authorized"])

    def test_manifest_reused_unchanged_from_v6_with_justification(self):
        v6 = json.loads(
            (REPO_ROOT / "runs/epic-126/jev-coverage-manifest-preregistration-v6.json")
            .read_text(encoding="utf-8"))
        manifest = self.document["manifest"]
        self.assertEqual(manifest["manifest_hash"],
                         "c4221e7db05fbdcba7b441099cb59d84147fa00d25569000ae2f416ca7233ad1")
        self.assertEqual(manifest["manifest_hash"], v6["manifest"]["manifest_hash"])
        self.assertEqual(manifest["instance_ids"], v6["manifest"]["instance_ids"])
        self.assertEqual(manifest["form_membership"], v6["manifest"]["form_membership"])
        self.assertEqual(len(manifest["instance_ids"]), 36)
        self.assertEqual(len(set(manifest["instance_ids"])), 36)
        self.assertTrue(all(count == 6 for count in manifest["form_counts"].values()))
        self.assertEqual(manifest["reused_from"], reg.V6_PREREGISTRATION_PATH)
        self.assertIn("no outcome-based selection", manifest["manifest_reuse_justification"])

    def test_disjointness_evidence_stable_and_excludes_owned_paths(self):
        evidence = self.document["manifest"]["disjointness"]
        self.assertTrue(evidence["ok"])
        self.assertEqual(evidence["overlap"], [])
        live = reg.prior_instance_ids_v7(REPO_ROOT)
        self.assertEqual(evidence["prior_instance_ids"], live)
        for path in (*regv6.V6_OWNED_PATHS, *reg.V7_OWNED_PATHS):
            self.assertIn(path, live["excluded"])

    def test_paid_sku_and_pricing_frozen(self):
        protocol = self.document["model_and_protocol"]
        self.assertEqual(protocol["ling_model"], reg.PAID_LING_MODEL)
        self.assertEqual(protocol["ling_previous_model"], reg.PREVIOUS_LING_MODEL)
        self.assertIn("HTTP 404", protocol["ling_model_change_note"])
        cost = self.document["caps"]["cost_model"]
        self.assertEqual(cost, reg.cost_model())
        self.assertEqual(cost["ling_prompt_usd_per_mtok"], 0.06)
        self.assertEqual(cost["ling_completion_usd_per_mtok"], 0.18)
        # conservative enforced-free ceiling: the retired 4096 assumption must stay dead
        self.assertEqual(cost["ling_input_token_ceiling"], 8192)
        self.assertNotEqual(cost["ling_input_token_ceiling"], 4096)
        self.assertEqual(cost["ling_output_token_ceiling"], 1024)
        self.assertEqual(cost["ling_worst_call_usd"], 0.00067584)
        self.assertEqual(cost["ling_next_call_reserve_usd"], 0.00202752)
        self.assertEqual(cost["ling_worst_total_usd"], 0.29196288)
        self.assertEqual(cost["jev_worst_total_usd"], 0.037158912)
        self.assertEqual(cost["worst_case_total_usd"], 0.329121792)
        self.assertEqual(self.document["caps"]["worst_case_cost_usd"], 0.329121792)
        self.assertEqual(self.document["caps"]["cost_cap_usd"], 1.0)
        self.assertLessEqual(self.document["caps"]["worst_case_cost_usd"],
                             self.document["caps"]["cost_cap_usd"])

    def test_planned_calls_and_partitions_unchanged(self):
        caps = self.document["caps"]
        self.assertEqual(caps["planned_calls"]["ling"], 144)
        self.assertEqual(caps["planned_calls"]["jev"], 36)
        self.assertEqual(caps["planned_calls"]["combined"], 180)
        self.assertEqual(caps["provider_partition"]["ling"], 432)
        self.assertEqual(caps["provider_partition"]["jev"], 108)
        self.assertEqual(caps["provider_partition"]["total"], 540)

    def test_probe_binding_and_artifact_pin(self):
        binding = self.document["transport_probe"]
        self.assertEqual(binding["sha256"], reg.EXPECTED_PROBE_SHA256)
        self.assertTrue(binding["routing_success"])
        self.assertTrue(binding["transport_success"])
        self.assertFalse(binding["writer_output_validated"])
        self.assertIn("routing, credentials, HTTP success, and usage/pricing only",
                      binding["probe_scope"])
        self.assertIn("derived from a reviewer recommendation", binding["approval_basis"])
        self.assertIn("does not authorize v7 collection", binding["approval_basis"])
        self.assertEqual(binding["original_outcome"]["outcome"], "empty_output")
        self.assertEqual(binding["original_outcome"]["finish_reason"], "length")
        self.assertEqual(binding["model"], reg.PAID_LING_MODEL)
        self.assertEqual(binding["attempts"], {"physical": 1, "cap": 1})
        self.assertEqual(binding["pricing_usd_per_mtok"], {"prompt": 0.06, "completion": 0.18})
        self.assertTrue(binding["required_before_live"])
        self.assertNotIn("success", binding)
        probe_path = REPO_ROOT / reg.PROBE_PATH
        self.assertEqual(hashlib.sha256(probe_path.read_bytes()).hexdigest(),
                         reg.EXPECTED_PROBE_SHA256)

    def test_catalog_gate_and_routing_repair_recorded(self):
        gate = self.document["catalog_gate"]
        self.assertTrue(gate["required_before_live"])
        self.assertTrue(gate["live_recheck_required"])
        self.assertTrue(gate["recorded_from_probe"]["target_present"])
        self.assertFalse(gate["recorded_from_probe"]["free_sku_present"])
        repair = self.document["model_routing_repair"]
        self.assertIn("absent from", repair["root_cause"])
        self.assertIn("same base OpenRouter model identifier", repair["treatment_drift"])
        self.assertIn("provider routing or serving configuration may differ",
                      repair["treatment_drift"])
        self.assertIn("must not automatically be pooled with free-route behavioral rates",
                      repair["treatment_drift"])
        self.assertNotIn("same underlying model", repair["treatment_drift"])
        self.assertIn("same base OpenRouter model identifier", repair["resolution"])
        self.assertIn("different vendor/model", repair["rejected_alternatives"])
        note = self.document["model_and_protocol"]["ling_model_change_note"]
        self.assertIn("must not automatically be pooled with free-route behavioral rates", note)
        self.assertNotIn("is the same underlying model", note)

    def test_runner_policy_bound_with_probe_and_catalog_requirements(self):
        policy = self.document["runner_policy"]
        self.assertTrue(policy["runner_implemented"])
        self.assertEqual(policy["runner_source_files"], [reg.RUNNER_SOURCE_REL])
        self.assertTrue(policy["runner_source_bound"])
        self.assertIn(reg.RUNNER_SOURCE_REL, reg.V7_SOURCE_FILES)
        self.assertEqual(len(reg.V7_SOURCE_FILES), 27)
        self.assertIn(reg.RUNNER_SOURCE_REL,
                      self.document["generator"]["source_files"])
        self.assertEqual(self.document["generator"]["source_files_hash"],
                         reg._source_files_hash(REPO_ROOT))
        self.assertFalse(policy["adding_runner_authorizes_collection"])
        self.assertEqual(policy["probe_required"]["sha256"], reg.EXPECTED_PROBE_SHA256)
        self.assertTrue(policy["catalog_gate_required"])
        self.assertIn("live execution is forbidden", policy["live_execution_rule"])
        self.assertEqual(policy["predecessor_lock"]["preregistration_hash"],
                         reg.V6_PREREGISTRATION_HASH)

    def test_preserved_inputs_pin_and_recompute(self):
        preserved = self.document["preserved_inputs"]
        self.assertEqual(preserved, reg.PRESERVED_INPUT_SHA256)
        for relative, expected in preserved.items():
            actual = hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()
            self.assertEqual(actual, expected, relative)
        self.assertEqual(preserved[reg.V6_JOURNAL_PATH], reg.V6_JOURNAL_SHA256)
        self.assertEqual(preserved[reg.V6_REPORT_PATH], reg.V6_REPORT_SHA256)
        self.assertEqual(preserved[reg.V6_PREREGISTRATION_PATH],
                         reg.V6_PREREGISTRATION_SHA256)

    def test_successor_references_and_fresh_outputs(self):
        successor = self.document["successor_of"]
        self.assertTrue(successor["immutable"])
        self.assertEqual(successor["v6_registration"]["preregistration_hash"],
                         reg.V6_PREREGISTRATION_HASH)
        outputs6 = successor["v6_frozen_outputs"]
        self.assertEqual(outputs6["journal"]["sha256"], reg.V6_JOURNAL_SHA256)
        self.assertEqual(outputs6["report"]["sha256"], reg.V6_REPORT_SHA256)
        self.assertIn("preserved byte-identical", outputs6["result"])
        outputs = self.document["outputs"]
        self.assertEqual(outputs, reg.output_paths())
        for old in (*regv6.OLD_OUTPUT_PATHS_V6, reg.V6_PREREGISTRATION_PATH,
                    reg.V6_JOURNAL_PATH, reg.V6_REPORT_PATH):
            for value in outputs.values():
                self.assertNotIn(old, str(value))


class ConservativeCostBoundTests(unittest.TestCase):
    """Frozen paid-route arithmetic (review finding 2)."""

    def test_exact_recomputed_bound(self):
        self.assertEqual(reg.LING_INPUT_TOKEN_CEILING, 8192)
        self.assertEqual(reg.LING_WORST_CALL_USD, 0.00067584)
        self.assertEqual(round((8192 * 0.06 + 1024 * 0.18) / 1_000_000, 12),
                         reg.LING_WORST_CALL_USD)
        self.assertEqual(reg.LING_NEXT_CALL_RESERVE_USD, 0.00202752)
        self.assertEqual(round(reg.LING_WORST_CALL_USD * 3, 12),
                         reg.LING_NEXT_CALL_RESERVE_USD)
        self.assertEqual(reg.LING_WORST_TOTAL_USD, 0.29196288)
        self.assertEqual(round(0.00067584 * 432, 9), reg.LING_WORST_TOTAL_USD)
        self.assertEqual(reg.JEV_WORST_TOTAL_USD, 0.037158912)
        self.assertEqual(reg.WORST_CASE_TOTAL_USD, 0.329121792)
        self.assertEqual(round(reg.LING_WORST_TOTAL_USD + reg.JEV_WORST_TOTAL_USD, 9),
                         reg.WORST_CASE_TOTAL_USD)
        self.assertLessEqual(reg.WORST_CASE_TOTAL_USD, reg.COST_CAP_USD)
        self.assertEqual(reg.COST_CAP_USD, 1.0)

    def test_legacy_4096_and_wrong_totals_rejected(self):
        legacy = copy.deepcopy(load_locked())
        legacy["caps"]["cost_model"]["ling_input_token_ceiling"] = 4096
        result = verify(legacy)
        self.assertFalse(result["ok"])
        self.assertTrue(any("cost model drift" in error for error in result["errors"]))

        wrong = copy.deepcopy(load_locked())
        wrong["caps"]["cost_model"]["ling_worst_total_usd"] = 0.18579456
        result = verify(wrong)
        self.assertFalse(result["ok"])
        self.assertTrue(any("cost model drift" in error for error in result["errors"]))

        wrong_reserve = copy.deepcopy(load_locked())
        wrong_reserve["caps"]["cost_model"]["ling_next_call_reserve_usd"] = 0.00043008
        result = verify(wrong_reserve)
        self.assertFalse(result["ok"])
        self.assertTrue(any("cost model drift" in error for error in result["errors"]))

    def test_combined_worst_above_frozen_or_ceiling_rejected(self):
        above_frozen = copy.deepcopy(load_locked())
        above_frozen["caps"]["worst_case_cost_usd"] = 0.4
        result = verify(above_frozen)
        self.assertFalse(result["ok"])
        self.assertTrue(any("worst-case cost drift" in error for error in result["errors"]))

        above_ceiling = copy.deepcopy(load_locked())
        above_ceiling["caps"]["worst_case_cost_usd"] = 1.5
        result = verify(above_ceiling)
        self.assertFalse(result["ok"])
        self.assertTrue(any("worst-case cost exceeds the cost ceiling" in error
                            for error in result["errors"]))

        below_worst = copy.deepcopy(load_locked())
        below_worst["caps"]["cost_cap_usd"] = 0.3
        result = verify(below_worst)
        self.assertFalse(result["ok"])
        self.assertTrue(any("worst-case cost exceeds the cost ceiling" in error
                            for error in result["errors"]))

    def test_runner_guard_reserves_retry_inclusive_next_call_once(self):
        cost = reg.cost_model()
        self.assertEqual(cost["ling_next_call_reserve_usd"],
                         cost["ling_worst_call_usd"] * 3)
        # runner source: single reserve per logical call, physical 1+retries
        source = (REPO_ROOT / "src/apart_incident_response/jev_coverage_bridge_v7.py")
        text = source.read_text(encoding="utf-8")
        self.assertIn("reserve = ling_reserve if ling else jev_reserve", text)
        self.assertIn(
            'report["estimated_cost_usd"] + reserve <= report["cost_cap_usd"]', text)
        self.assertIn("1 + pr.JEV_REPLAY_MAX_RETRIES", text)


class VerifierRejectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_locked()

    def test_stale_hash_rejected(self):
        tampered = copy.deepcopy(self.document)
        tampered["preregistration_hash"] = "0" * 64
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("registration hash drift from the repository state", result["errors"])

    def test_draft_status_rejected(self):
        draft = reg.build_coverage_manifest_preregistration_v7(approved=False,
                                                               repo_root=REPO_ROOT)
        result = verify(draft)
        self.assertFalse(result["ok"])
        self.assertTrue(any("not locked" in error for error in result["errors"]))

    def test_free_sku_model_rejected(self):
        tampered = copy.deepcopy(self.document)
        tampered["model_and_protocol"]["ling_model"] = reg.PREVIOUS_LING_MODEL
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("paid inclusionai/ling-3.0-flash-vl" in error
                            for error in result["errors"]), result["errors"])

    def test_pricing_and_cost_drift_rejected(self):
        tampered = copy.deepcopy(self.document)
        tampered["caps"]["cost_model"]["ling_prompt_usd_per_mtok"] = 0.05
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("cost model drift" in error for error in result["errors"]))
        tampered = copy.deepcopy(self.document)
        tampered["caps"]["worst_case_cost_usd"] = 2.0
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("worst-case cost" in error for error in result["errors"]))

    def test_v6_output_paths_rejected_as_outputs(self):
        tampered = copy.deepcopy(self.document)
        tampered["outputs"]["journal"] = reg.V6_JOURNAL_PATH
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("old v1-v6 output path rejected" in error
                            for error in result["errors"]))

    def test_manifest_tamper_rejected(self):
        tampered = copy.deepcopy(self.document)
        tampered["manifest"]["manifest_hash"] = "0" * 64
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("manifest hash differs from the frozen v6 manifest hash",
                      result["errors"])
        tampered = copy.deepcopy(self.document)
        tampered["manifest"]["manifest_reuse_justification"] = ""
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("manifest reuse justification missing", result["errors"])

    def test_probe_binding_tamper_rejected(self):
        tampered = copy.deepcopy(self.document)
        tampered["transport_probe"]["sha256"] = "0" * 64
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("probe binding sha256 drift" in error
                            for error in result["errors"]))
        tampered = copy.deepcopy(self.document)
        tampered["transport_probe"]["routing_success"] = False
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("routing_success true" in error for error in result["errors"]))
        tampered = copy.deepcopy(self.document)
        tampered["transport_probe"]["writer_output_validated"] = True
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("must not claim validated writer output" in error
                            for error in result["errors"]))
        tampered = copy.deepcopy(self.document)
        tampered["transport_probe"]["probe_scope"] = "behavioral capability"
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("probe scope drift" in error for error in result["errors"]))
        tampered = copy.deepcopy(self.document)
        tampered["transport_probe"]["approval_basis"] = "formal approval string"
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("probe approval basis drift" in error
                            for error in result["errors"]))

    def test_preserved_input_drift_rejected(self):
        tampered = copy.deepcopy(self.document)
        tampered["preserved_inputs"][reg.V6_JOURNAL_PATH] = "0" * 64
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("preserved input pin list drift" in error
                            or "preserved input unchanged check failed" in error
                            for error in result["errors"]), result["errors"])

    def test_runner_policy_tamper_rejected(self):
        tampered = copy.deepcopy(self.document)
        tampered["runner_policy"]["adding_runner_authorizes_collection"] = True
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("adding the runner must not authorize collection", result["errors"])
        tampered = copy.deepcopy(self.document)
        tampered["runner_policy"]["predecessor_lock"]["preregistration_hash"] = "0" * 64
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("predecessor v6 lock hash missing or drifted", result["errors"])

    def test_live_authorization_attempt_rejected(self):
        tampered = copy.deepcopy(self.document)
        tampered["approval"]["live_collection_authorized"] = True
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("lock must not authorize live collection", result["errors"])

    def test_freshness_params_report_collisions(self):
        result = verify(self.document, journal_exists=True, report_exists=True)
        self.assertFalse(result["ok"])
        self.assertIn("future coverage journal already exists", result["errors"])
        self.assertIn("future coverage report already exists", result["errors"])

    def test_missing_probe_fails_rebuild_closed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory)
            result = verify(self.document, repo_root=empty)
            self.assertFalse(result["ok"])
            self.assertTrue(any("rebuild_failed" in error or "probe artifact missing" in error
                                or "preserved input unchanged check failed" in error
                                for error in result["errors"]), result["errors"])

    def test_live_catalog_gate_and_pricing_check(self):
        good = {"catalog_version": "openrouter-catalog-gate-v1",
                "catalog_url": "https://openrouter.ai/api/v1/models",
                "model_count": 460,
                "entries": {reg.PAID_LING_MODEL: {
                    "present": True, "prompt_usd_per_tok": "0.00000006",
                    "completion_usd_per_tok": "0.00000018", "context_length": 262144},
                    reg.PREVIOUS_LING_MODEL: {"present": False}}}
        result = verify(self.document, check_catalog=True, catalog_document=good)
        self.assertTrue(result["ok"], result["errors"])
        drifted = copy.deepcopy(good)
        drifted["entries"][reg.PAID_LING_MODEL]["prompt_usd_per_tok"] = "0.00000007"
        result = verify(self.document, check_catalog=True, catalog_document=drifted)
        self.assertFalse(result["ok"])
        self.assertIn("live catalog pricing drift from the frozen cost model", result["errors"])
        missing = copy.deepcopy(good)
        missing["entries"][reg.PAID_LING_MODEL] = {"present": False}
        result = verify(self.document, check_catalog=True, catalog_document=missing)
        self.assertFalse(result["ok"])
        self.assertTrue(any("live catalog gate failed" in error
                            for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
