import json
import tempfile
import unittest
from pathlib import Path

from apart_incident_response.preregistration import (
    APPROVED_CUMULATIVE_CAP,
    CONFIRMATORY_COST_CAP_USD,
    CONFIRMATORY_INSTANCES,
    CONFIRMATORY_PER_CELL,
    CONFIRMATORY_PLANNED_REQUESTS,
    CONFIRMATORY_REQUEST_CAP,
    CONFIRMATORY_RETRY_RESERVE,
    CONFIRMATORY_VERSION,
    CONSUMED_REQUESTS,
    COST_CAP_USD,
    MINIMUM_EFFECTIVE_C_NEED,
    NEW_REQUEST_ALLOWANCE,
    ORIGINAL_SMOKE_CAP,
    PLANNED_SMOKE_REQUESTS,
    PREREGISTRATION_VERSION,
    PROPOSED_REPRESENTATIVE_CELLS,
    RETRY_PREFLIGHT_RESERVE,
    SEED_BASIS_DESCRIPTION,
    SMOKE_CONDITION_TURNS,
    SMOKE_MAX_COST_USD,
    SMOKE_MAX_PHYSICAL_REQUESTS,
    SMOKE_MAX_TOKENS,
    SMOKE_MODEL,
    STAGE2_CONFIRMATORY_SEED_BASE,
    STAGE2_MAX_SEEDS_PER_CELL,
    STAGE2_SEED_BASE,
    SUCCESSOR_VERSION,
    assert_unique_instance_ids,
    audit_cells,
    build_confirmatory_preregistration,
    build_preregistration,
    build_successor_preregistration,
    holm_adjust,
    mechanics_smoke_instances,
    mcnemar_required_pairs,
    missingness_report,
    stage2_instances,
    verify_against_confirmatory_preregistration,
    verify_against_preregistration,
)
from apart_incident_response.communication_protocol import ReasoningComplexity


class CellAuditTests(unittest.TestCase):
    def test_cosmetic_wrappers_are_collapsed(self):
        audit = audit_cells(seeds=(1, 2, 3))
        self.assertTrue(all(cell["stable"] for cell in audit["cells"]
                            if cell["complexity"] in {"low", "medium"}))
        self.assertEqual(audit["unstable_cells"], ["reference:high"])
        self.assertLess(audit["distinct_cell_count"], audit["cell_count"])
        self.assertTrue(audit["cosmetic_wrapper_groups"])
        low_bit = [members for members in audit["groups"].values()
                   if {"hypothesis:low", "poetry:low", "legal:low", "lexicon:low"} <= set(members)]
        self.assertTrue(low_bit, audit["groups"])


class Stage2ManifestTests(unittest.TestCase):
    def test_stage2_seeds_are_fresh_collision_free_and_deterministic(self):
        first = assert_unique_instance_ids(stage2_instances(2))
        second = assert_unique_instance_ids(stage2_instances(2))
        self.assertEqual(first, second)
        seeds = [instance.seed for instance in stage2_instances(2)]
        self.assertGreaterEqual(min(seeds), STAGE2_SEED_BASE)
        self.assertNotIn("hypothesis-00003e80", first)
        # the previous 100-seed complexity spacing collided at 110 seeds; the
        # frozen layout must stay unique for large per-cell counts
        large = assert_unique_instance_ids(stage2_instances(110))
        self.assertEqual(len(large), len(set(large)))
        self.assertEqual(len(large), len(PROPOSED_REPRESENTATIVE_CELLS) * 110)

    def test_stage2_manifest_is_frozen_to_requested_seed_count(self):
        one = build_preregistration(repo_root=Path(__file__).resolve().parents[1],
                                    generator_commit="deadbeef", seeds_per_cell=1)
        three = build_preregistration(repo_root=Path(__file__).resolve().parents[1],
                                      generator_commit="deadbeef", seeds_per_cell=3)
        one_ids = one["stage2"]["mechanics_smoke"]["instance_ids"]
        three_ids = three["stage2"]["mechanics_smoke"]["instance_ids"]
        self.assertEqual(len(one_ids), len(PROPOSED_REPRESENTATIVE_CELLS))
        self.assertEqual(len(three_ids), len(PROPOSED_REPRESENTATIVE_CELLS) * 3)
        self.assertNotEqual(one["stage2"]["mechanics_smoke"]["manifest_hash"],
                            three["stage2"]["mechanics_smoke"]["manifest_hash"])
        self.assertNotEqual(one["preregistration_hash"], three["preregistration_hash"])

    def test_frozen_smoke_is_two_seeds_per_group(self):
        self.assertEqual(len(mechanics_smoke_instances()), 2 * len(PROPOSED_REPRESENTATIVE_CELLS))

    def test_seed_count_above_layout_is_rejected(self):
        with self.assertRaises(ValueError):
            stage2_instances(STAGE2_MAX_SEEDS_PER_CELL + 1)


class InferenceHelperTests(unittest.TestCase):
    def test_holm_adjust_is_monotone_and_capped(self):
        adjusted = holm_adjust({"a": 0.01, "b": 0.04, "c": 0.03})
        self.assertEqual(adjusted["a"], 0.03)
        self.assertAlmostEqual(adjusted["c"], 0.06)
        self.assertEqual(adjusted["b"], 0.06)
        self.assertTrue(all(0 <= value <= 1 for value in adjusted.values()))

    def test_mcnemar_required_pairs_grows_as_effect_weakens(self):
        strong = mcnemar_required_pairs(0.80, 0.30)
        weak = mcnemar_required_pairs(0.60, 0.30)
        self.assertGreater(weak["required_discordant_pairs"], strong["required_discordant_pairs"])
        self.assertGreater(strong["required_total_pairs"], strong["required_discordant_pairs"])
        with self.assertRaises(ValueError):
            mcnemar_required_pairs(0.5, 0.3)
        with self.assertRaises(ValueError):
            mcnemar_required_pairs(0.8, 0.0)

    def test_missingness_counts_unpaired_attempts_and_bounds(self):
        # two ISO attempts, one FULL attempt (the reviewer's counterexample)
        records = [
            {"instance_id": "a", "condition": "ISO", "valid_execution": True, "checker_accepted": True},
            {"instance_id": "b", "condition": "ISO", "valid_execution": True, "checker_accepted": False},
            {"instance_id": "a", "condition": "FULL", "valid_execution": False, "checker_accepted": False},
        ]
        report = missingness_report(records, "ISO", "FULL")
        self.assertEqual(report["attempted"], {"ISO": 2, "FULL": 1})
        self.assertEqual(report["valid"], {"ISO": 2, "FULL": 0})
        self.assertEqual(report["attempted_pairs"], 2)
        self.assertEqual(report["complete_pairs"], 0)
        self.assertEqual(report["incomplete_pairs"], 2)
        self.assertEqual(report["invalidity_by_condition"], {"ISO": 0, "FULL": 1})
        low, high = report["difference_bounds_extreme_imputation"]
        self.assertLessEqual(low, high)
        self.assertLessEqual(low, 0.0)
        self.assertGreaterEqual(high, 0.0)

    def test_missingness_complete_pair_difference(self):
        records = [
            {"instance_id": "a", "condition": "ISO", "valid_execution": True, "checker_accepted": False},
            {"instance_id": "a", "condition": "FULL", "valid_execution": True, "checker_accepted": True},
        ]
        report = missingness_report(records, "ISO", "FULL")
        self.assertEqual(report["complete_pairs"], 1)
        self.assertEqual(report["incomplete_pairs"], 0)
        self.assertEqual(report["complete_case_difference"], 1.0)
        self.assertEqual(report["difference_bounds_extreme_imputation"], [1.0, 1.0])


class PreregistrationDocumentTests(unittest.TestCase):
    def build(self):
        return build_preregistration(repo_root=Path(__file__).resolve().parents[1],
                                     generator_commit="deadbeef")

    def test_document_freezes_required_state(self):
        document = self.build()
        self.assertEqual(document["preregistration_version"], PREREGISTRATION_VERSION)
        self.assertEqual(document["status"], "draft_for_review")
        self.assertTrue(document["approval_required"])
        self.assertEqual(document["generator_commit"], "deadbeef")
        self.assertEqual(len(document["generator_file_sha256"]), 64)
        self.assertEqual(len(document["treatment_file_sha256"]), 64)
        self.assertEqual(document["treatment_schema"]["primary_conditions"], ["ISO", "FULL", "COMM"])
        self.assertEqual(document["treatment_schema"]["diagnostic_conditions"], ["ORACLE", "INDUCED"])
        self.assertTrue(document["proposed_decisions"])
        self.assertEqual(document["inference"]["minimum_effective_c_need"], MINIMUM_EFFECTIVE_C_NEED)
        self.assertEqual(document["provider_settings"]["condition_turns"],
                         {"ISO": 1, "FULL": 1, "COMM": 2})
        self.assertEqual(document["provider_settings"]["diagnostics_not_run"], ["ORACLE", "INDUCED"])
        self.assertTrue(document["stage2"]["layout"]["collision_free"])
        self.assertEqual(document["declared_distinct_cells"]["excluded_unstable"], ["reference:high"])
        smoke_ids = document["stage2"]["mechanics_smoke"]["instance_ids"]
        self.assertEqual(len(smoke_ids), 2 * len(PROPOSED_REPRESENTATIVE_CELLS))
        self.assertEqual(len(smoke_ids), len(set(smoke_ids)))
        self.assertIn("ISO", document["contrasts"]["primary"])
        self.assertTrue(document["superseded_artifacts"])

    def test_superseded_excludes_current_schema_artifacts(self):
        names = {Path(row["path"]).name for row in self.build()["superseded_artifacts"]}
        self.assertIn("paired-screen.jsonl", names)
        self.assertNotIn("treatment-schema.json", names)
        self.assertNotIn("preregistration-v1.json", names)

    def test_hash_is_deterministic(self):
        self.assertEqual(self.build()["preregistration_hash"], self.build()["preregistration_hash"])

    def test_approved_lock_records_caps_and_decisions(self):
        document = build_preregistration(repo_root=Path(__file__).resolve().parents[1],
                                         generator_commit="deadbeef", approved=True)
        self.assertEqual(document["status"], "locked_for_mechanics_smoke")
        self.assertFalse(document["approval_required"])
        self.assertTrue(document["approval"]["approved"])
        self.assertEqual(document["caps"]["smoke"]["max_physical_requests"], SMOKE_MAX_PHYSICAL_REQUESTS)
        self.assertEqual(document["caps"]["smoke"]["max_cost_usd"], SMOKE_MAX_COST_USD)
        self.assertTrue(document["caps"]["smoke"]["counts_retries"])
        self.assertTrue(document["caps"]["smoke"]["counts_preflight"])
        self.assertEqual(document["declared_distinct_cells"]["status"], "approved")
        self.assertEqual(document["provider_settings"]["condition_turns"], SMOKE_CONDITION_TURNS)
        self.assertEqual(document["provider_settings"]["max_tokens"], SMOKE_MAX_TOKENS)
        self.assertEqual(document["provider_settings"]["conditions_run"], ["ISO", "FULL", "COMM"])
        self.assertEqual(document["provider_settings"]["diagnostics_not_run"], ["ORACLE", "INDUCED"])
        self.assertEqual(document["provider_settings"]["model"], "inclusionai/ling-3.0-flash-vl:free")
        self.assertTrue(document["provider_settings"]["expected_protocol_key"])
        self.assertTrue(document["approved_decisions"])
        self.assertEqual(document["contrasts"]["run_in_smoke"], ["ISO", "FULL", "COMM"])
        self.assertEqual(document["stage2"]["confirmatory"]["status"], "proposed_pending_smoke")
        self.assertTrue(document["pending_decisions"])

    def test_verify_against_preregistration_accepts_locked_and_rejects_drift(self):
        document = build_preregistration(repo_root=Path(__file__).resolve().parents[1],
                                         generator_commit="deadbeef", approved=True)
        instance_ids = document["stage2"]["mechanics_smoke"]["instance_ids"]
        model = document["provider_settings"]["model"]
        good = verify_against_preregistration(document, instance_ids=instance_ids, model=model,
                                              provider_version="behavioral-discovery-v1",
                                              condition_turns=SMOKE_CONDITION_TURNS,
                                              max_tokens=SMOKE_MAX_TOKENS)
        self.assertTrue(good["ok"], good["errors"])
        drift = verify_against_preregistration(document, instance_ids=instance_ids[:-1], model=model,
                                               provider_version="behavioral-discovery-v1",
                                               condition_turns={"ISO": 1, "FULL": 1, "COMM": 3},
                                               max_tokens=SMOKE_MAX_TOKENS)
        self.assertFalse(drift["ok"])
        wrong_model = verify_against_preregistration(document, instance_ids=instance_ids,
                                                     model="deepseek/deepseek-v4.1-flash",
                                                     provider_version="behavioral-discovery-v1",
                                                     condition_turns=SMOKE_CONDITION_TURNS,
                                                     max_tokens=SMOKE_MAX_TOKENS)
        self.assertFalse(wrong_model["ok"])

    def test_cli_writes_document(self):
        from apart_incident_response import preregistration
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "prereg.json"
            code = preregistration.main(["--repo-root", str(Path(__file__).resolve().parents[1]),
                                         "--output", str(output)])
            self.assertEqual(code, 0)
            written = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(written["preregistration_version"], PREREGISTRATION_VERSION)
        self.assertEqual(len(written["stage2"]["mechanics_smoke"]["instance_ids"]),
                         2 * len(PROPOSED_REPRESENTATIVE_CELLS))


    def test_successor_registration_is_locked_with_87_17_70_accounting(self):
        root = Path(__file__).resolve().parents[1]
        v1_path = root / "runs" / "epic-126" / "preregistration-v1.json"
        v1 = json.loads(v1_path.read_text(encoding="utf-8"))
        v1_hash_before = v1["preregistration_hash"]
        document = build_successor_preregistration(repo_root=root, generator_commit="deadbeef")
        self.assertEqual(document["preregistration_version"], SUCCESSOR_VERSION)
        self.assertEqual(document["status"], "locked_for_mechanics_smoke")
        self.assertFalse(document["approval_required"])
        self.assertTrue(document["approval"]["approved"])
        self.assertEqual(document["approval"]["cumulative_cap"], APPROVED_CUMULATIVE_CAP)
        self.assertEqual(document["supersedes"]["version"], "stage2-preregistration-v1")
        self.assertEqual(document["supersedes"]["hash"], v1_hash_before)
        self.assertEqual(document["amendment"]["provider_seed_algorithm"],
                         "sha256-truncated-signed31-v1")
        self.assertEqual(document["amendment"]["provider_seed_max"], 2 ** 31 - 1)
        # seed_basis must describe the signed-31-bit mask
        self.assertEqual(document["provider_settings"]["seed_basis"], SEED_BASIS_DESCRIPTION)
        self.assertIn("31-bit", document["provider_settings"]["seed_basis"])
        self.assertIn("2^31", document["provider_settings"]["seed_basis"])
        accounting = document["request_cap_accounting"]
        self.assertEqual(accounting["reviewer_approved_cumulative_cap"], 87)
        self.assertEqual(accounting["consumed"]["total"], 17)
        self.assertEqual(sum(CONSUMED_REQUESTS.values()), 17)
        self.assertEqual(accounting["new_request_allowance"], 70)
        self.assertEqual(accounting["planned_smoke_requests"], 60)
        self.assertEqual(accounting["retry_preflight_reserve"], 10)
        self.assertEqual(accounting["clean_restart_cap"], 70)
        self.assertEqual(accounting["historical"]["original_smoke_cap"], ORIGINAL_SMOKE_CAP)
        self.assertIn("not the current cap", accounting["historical"]["note"])
        self.assertNotIn("remaining_under_original_cap", accounting)
        self.assertEqual(APPROVED_CUMULATIVE_CAP - sum(CONSUMED_REQUESTS.values()), NEW_REQUEST_ALLOWANCE)
        self.assertTrue(document["clean_restart_plan"])
        # the locked v1 file must be preserved byte-for-byte at the hash level
        self.assertEqual(json.loads(v1_path.read_text(encoding="utf-8"))["preregistration_hash"],
                         v1_hash_before)
        # the new key must differ from the locked v1 key so runs cannot be pooled
        self.assertNotEqual(document["provider_settings"]["expected_protocol_key"],
                            v1["provider_settings"]["expected_protocol_key"])

    def test_successor_registration_hash_is_reproducible(self):
        root = Path(__file__).resolve().parents[1]
        first = build_successor_preregistration(repo_root=root, generator_commit="deadbeef")
        second = build_successor_preregistration(repo_root=root, generator_commit="deadbeef")
        self.assertEqual(first["preregistration_hash"], second["preregistration_hash"])

    def test_preflight_rejects_draft_and_over_budget(self):
        root = Path(__file__).resolve().parents[1]
        ids = mechanics_smoke_instances()
        ids = [instance.instance_id for instance in ids]
        model = SMOKE_MODEL
        kwargs = dict(instance_ids=ids, model=model, provider_version="behavioral-discovery-v1",
                      condition_turns=SMOKE_CONDITION_TURNS, max_tokens=SMOKE_MAX_TOKENS)
        locked = build_successor_preregistration(repo_root=root, generator_commit="deadbeef")
        within = verify_against_preregistration(locked, planned_requests=60, **kwargs)
        self.assertTrue(within["ok"], within["errors"])
        self.assertEqual(within["new_request_allowance"], 70)
        over = verify_against_preregistration(locked, planned_requests=71, **kwargs)
        self.assertFalse(over["ok"])
        self.assertTrue(any("exceed" in error for error in over["errors"]))
        draft = build_successor_preregistration(repo_root=root, generator_commit="deadbeef",
                                                approved=False)
        rejected = verify_against_preregistration(draft, planned_requests=60, **kwargs)
        self.assertFalse(rejected["ok"])
        self.assertTrue(any("not locked" in error for error in rejected["errors"]))

    def test_successor_cli_writes_document(self):
        from apart_incident_response import preregistration
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "prereg-v2.json"
            code = preregistration.main(["--repo-root", str(Path(__file__).resolve().parents[1]),
                                         "--successor", "--output", str(output)])
            self.assertEqual(code, 0)
            written = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(written["preregistration_version"], SUCCESSOR_VERSION)
        self.assertEqual(written["status"], "locked_for_mechanics_smoke")
        self.assertEqual(written["request_cap_accounting"]["new_request_allowance"], 70)
        self.assertTrue(written["amendment"])


    def test_confirmatory_draft_discordant_pair_sizing(self):
        root = Path(__file__).resolve().parents[1]
        v2 = json.loads((root / "runs" / "epic-126" / "preregistration-v2.json").read_text(encoding="utf-8"))
        document = build_confirmatory_preregistration(repo_root=root, generator_commit="deadbeef")
        self.assertEqual(document["preregistration_version"], CONFIRMATORY_VERSION)
        self.assertEqual(document["stage"], "confirmatory")
        self.assertEqual(document["status"], "draft_pending_review")
        self.assertTrue(document["approval_required"])
        self.assertEqual(document["supersedes"]["hash"], v2["preregistration_hash"])
        confirmatory = document["confirmatory"]
        self.assertEqual(confirmatory["per_cell_instances"], CONFIRMATORY_PER_CELL)
        self.assertEqual(confirmatory["total_instances"], CONFIRMATORY_INSTANCES)
        self.assertEqual(confirmatory["target_iso_full_pairs"], 83)
        self.assertEqual(confirmatory["required_discordant_pairs"], 33)
        self.assertEqual(confirmatory["expected_discordant_pairs"], 34.0)
        self.assertEqual(confirmatory["planned_requests"], CONFIRMATORY_PLANNED_REQUESTS)
        self.assertEqual(confirmatory["retry_preflight_reserve"], CONFIRMATORY_RETRY_RESERVE)
        self.assertEqual(confirmatory["request_cap"], CONFIRMATORY_REQUEST_CAP)
        self.assertEqual(confirmatory["cost_cap_usd"], CONFIRMATORY_COST_CAP_USD)
        self.assertEqual(len(confirmatory["instance_ids"]), 85)
        self.assertEqual(len(set(confirmatory["instance_ids"])), 85)
        self.assertEqual(confirmatory["conditions_run"], ["ISO", "FULL", "COMM"])
        self.assertEqual(confirmatory["diagnostics_not_run"], ["ORACLE", "INDUCED"])
        self.assertEqual([cell["instances"] for cell in confirmatory["cells"]], [17] * 5)
        # confirmatory reuses the same treatment protocol as locked v2
        self.assertEqual(document["provider_settings"]["expected_protocol_key"],
                         v2["provider_settings"]["expected_protocol_key"])

    def test_confirmatory_manifest_matches_fresh_reserved_seed_block(self):
        root = Path(__file__).resolve().parents[1]
        document = build_confirmatory_preregistration(repo_root=root, generator_commit="deadbeef")
        instances = stage2_instances(CONFIRMATORY_PER_CELL, seed_base=STAGE2_CONFIRMATORY_SEED_BASE)
        self.assertEqual(sorted(instance.instance_id for instance in instances),
                         sorted(document["confirmatory"]["instance_ids"]))
        self.assertGreaterEqual(min(instance.seed for instance in instances), STAGE2_CONFIRMATORY_SEED_BASE)

    def test_confirmatory_registration_hash_is_reproducible(self):
        root = Path(__file__).resolve().parents[1]
        first = build_confirmatory_preregistration(repo_root=root, generator_commit="deadbeef")
        second = build_confirmatory_preregistration(repo_root=root, generator_commit="deadbeef")
        self.assertEqual(first["preregistration_hash"], second["preregistration_hash"])

    def test_confirmatory_scheme_generates_fresh_85_ids(self):
        from apart_incident_response.behavioral_discovery import build_screen_instances
        confirmatory = build_screen_instances(scheme="stage2-confirmatory", seeds_per_cell=17)
        smoke_ids = {instance.instance_id for instance in mechanics_smoke_instances()}
        ids = [instance.instance_id for instance in confirmatory]
        self.assertEqual(len(ids), 85)
        self.assertEqual(len(set(ids)), 85)
        self.assertEqual(set(ids) & smoke_ids, set())
        self.assertGreaterEqual(min(instance.seed for instance in confirmatory),
                                STAGE2_CONFIRMATORY_SEED_BASE)

    def test_confirmatory_preflight_accepts_locked_rejects_draft_and_over_budget(self):
        root = Path(__file__).resolve().parents[1]
        document = json.loads((root / "runs" / "epic-126" / "preregistration-v3.json").read_text(encoding="utf-8"))
        instance_ids = document["confirmatory"]["instance_ids"]
        kwargs = dict(instance_ids=instance_ids, model=SMOKE_MODEL,
                      provider_version="behavioral-discovery-v1",
                      condition_turns=SMOKE_CONDITION_TURNS, max_tokens=SMOKE_MAX_TOKENS)
        good = verify_against_confirmatory_preregistration(document, planned_requests=600, **kwargs)
        self.assertTrue(good["ok"], good["errors"])
        over = verify_against_confirmatory_preregistration(document, planned_requests=601, **kwargs)
        self.assertFalse(over["ok"])
        self.assertTrue(any("exceed" in error for error in over["errors"]))
        draft = build_confirmatory_preregistration(repo_root=root, generator_commit="deadbeef",
                                                   approved=False)
        rejected = verify_against_confirmatory_preregistration(draft, planned_requests=600, **kwargs)
        self.assertFalse(rejected["ok"])
        self.assertTrue(any("not locked" in error for error in rejected["errors"]))

    def test_confirmatory_cli_writes_draft(self):
        from apart_incident_response import preregistration
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "prereg-v3.json"
            code = preregistration.main(["--repo-root", str(Path(__file__).resolve().parents[1]),
                                         "--confirmatory", "--output", str(output)])
            self.assertEqual(code, 0)
            written = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(written["preregistration_version"], CONFIRMATORY_VERSION)
        self.assertEqual(written["status"], "draft_pending_review")
        self.assertEqual(written["confirmatory"]["request_cap"], CONFIRMATORY_REQUEST_CAP)


if __name__ == "__main__":
    unittest.main()
