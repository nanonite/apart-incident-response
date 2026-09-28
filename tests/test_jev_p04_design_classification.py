import contextlib
import hashlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import jev_p04_design_classification as p04
from apart_incident_response import jev_replication_preregistration as rep


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "jev-p04-design-classification.md"
REGISTRATION = REPO_ROOT / "runs" / "next-phase" / "jev-p04-discovery-registration-v1.json"
AUDIT = REPO_ROOT / rep.AUDIT_PATH
REGISTRATION_200 = REPO_ROOT / rep.REGISTRATION_PATH

#: Self-recorded content hash of the frozen registration.
REGISTRATION_HASH = "6fa6149770b620cd3a026a6415f8e4d97e800e8af5237794de7b29fca6dacfac"

#: Frozen pins carried from the #200 artifacts and the P02/P03 records.
AUDIT_CONTENT_HASH = "5242e9cfa35e3a77c54045475428dd617cf93cb16d464b55ad679adc35f80a83"
PREREGISTRATION_HASH = "ff186a066e6af093ecc383e668d948bdca7c1ef8f84b5752b88db47960a6ec6d"
SCOPE_CONTENT_HASH = "4cf5556c8e9c0811653e4b4d726a7b437d43bd63134cad0f80b84eb9148ec59b"
CENSUS_CONTENT_HASH = "ee0ba3a1714828b3e39834280a0a2eb7850f1cc0526463eb59d3bc4b7026fe14"

FORM_IDS = [
    "57ee9880f18bff4971516f9db820fd96dfb9eb86dab29e166025625e88a7b0c9",
    "a0e4ffd0c0b442207bf171422592a1f0b8f58556e2d44d8845d74ec23853f03d",
    "a95806c84d3a722d0ae240c637277373526956b57051cf006e5430706bf6e94c",
    "fc05e96360fa58fd2398727a886654d27d87fe561b2160002bcc01511f322562",
]

REQUIRED_PHRASES = [
    # task identity and offline scope
    "#205",
    "#201",
    "#159",
    "hypothesis:low",
    "no provider call",
    "nothing here authorizes collection",
    # artifact and hash
    "jev-p04-discovery-registration-v1",
    "6fa6149770b620cd3a026a6415f8e4d97e800e8af5237794de7b29fca6dacfac",
    "5242e9cfa35e3a77c54045475428dd617cf93cb16d464b55ad679adc35f80a83",
    "ff186a066e6af093ecc383e668d948bdca7c1ef8f84b5752b88db47960a6ec6d",
    "4cf5556c8e9c0811653e4b4d726a7b437d43bd63134cad0f80b84eb9148ec59b",
    "ee0ba3a1714828b3e39834280a0a2eb7850f1cc0526463eb59d3bc4b7026fe14",
    # k and floor
    "k = 4",
    "0.125",
    "2/2",
    "no dichotomous rejection",
    # pilot vs potentially confirmatory
    "pilot",
    "potentially confirmatory",
    "k ≥ 6",
    "descriptive",
    "fresh-seed replication",
    # fixed N
    "fixed N = 16",
    "4 per form",
    "85000–85511",
    "no outcome-based stopping",
    # treatment and route
    "L4X communication treatment",
    "inclusionai/ling-3.0-flash-vl",
    "jev-1.13.0",
    "jev-choice-wire-v2",
    "ling-writer-openrouter-pacing-v3",
    # budgets
    "0.00067584",
    "0.000344064",
    "$0.20",
    "$0.10",
    "$0.30",
    "0.146276352",
    "0.049545216",
    "0.195821568",
    # stops and paths
    "terminal stops",
    "no resume, no append, no overwrite",
    "runs/next-phase/hypothesis/jev-discovery-v1",
    "prior-instance-id pin",
    # coverage rules
    "Permissible within-form missingness",
    "complete-case scope",
    "No imputation",
    "no seed replacement",
    "no form removal after outcomes",
    "selection risk",
    # exploratory replay
    "exploratory",
    "never confirmatory",
    # new-version resolutions
    "six-form",
    "interval half-width",
    "not a power-based MDE",
    # checks and handoff
    "41/41",
    "provider_calls: 0",
    "byte-for-byte",
    "P05 (#206)",
    "A predecessor closed as failed does not authorize successor execution",
]

BANNED_PHRASES = [
    "proves the hypothesis",
    "confirms the effect for every family",
    "population-representative",
    "generalizes to other families",
    "the winning family",
    "this task authorizes collection",
    "authorizes the live run",
    "locking authorizes execution",
    "instance-level significance",
    "we selected the best family",
    "five-form minimum",
]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DesignClassificationTestCase(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text(encoding="utf-8")
        self.normalized = " ".join(self.text.split())
        self.normalized_lower = self.normalized.lower()
        self.registration = json.loads(REGISTRATION.read_text(encoding="utf-8"))
        self.audit = json.loads(AUDIT.read_text(encoding="utf-8"))
        self.registration_200 = json.loads(REGISTRATION_200.read_text(encoding="utf-8"))
        self.live_paths = [REPO_ROOT / path for path in p04.PATHS.values()
                           if path != str(p04.REGISTRATION_PATH)]
        self.live_before = [path.exists() for path in self.live_paths]

    def tearDown(self):
        self.assertEqual([path.exists() for path in self.live_paths],
                         self.live_before, "a live output path changed state")


class ContentHashTests(DesignClassificationTestCase):
    def test_registration_hash_recomputes(self):
        recomputed = hashlib.sha256(
            json.dumps({key: value for key, value in self.registration.items()
                        if key != "registration_hash"},
                       sort_keys=True).encode()).hexdigest()
        self.assertEqual(recomputed, REGISTRATION_HASH)
        self.assertEqual(self.registration["registration_hash"], REGISTRATION_HASH)
        self.assertIn(REGISTRATION_HASH, self.normalized)

    def test_frozen_input_pins_still_match(self):
        self.assertEqual(self.audit["audit_content_hash"], AUDIT_CONTENT_HASH)
        self.assertEqual(self.registration_200["preregistration_hash"], PREREGISTRATION_HASH)
        evidence = self.registration["input_evidence"]
        self.assertEqual(evidence["audit_200"]["audit_content_hash"], AUDIT_CONTENT_HASH)
        self.assertEqual(evidence["registration_200"]["preregistration_hash"],
                         PREREGISTRATION_HASH)
        self.assertEqual(evidence["scope_freeze_p02"]["content_hash"], SCOPE_CONTENT_HASH)
        self.assertEqual(evidence["census_p03"]["content_hash"], CENSUS_CONTENT_HASH)
        self.assertEqual(sha256_of(AUDIT), evidence["audit_200"]["file_sha256"])
        self.assertEqual(sha256_of(REGISTRATION_200),
                         evidence["registration_200"]["file_sha256"])
        for pin in (AUDIT_CONTENT_HASH, PREREGISTRATION_HASH, SCOPE_CONTENT_HASH,
                     CENSUS_CONTENT_HASH):
            with self.subTest(pin=pin):
                self.assertIn(pin, self.normalized)


class RegistrationStructureTests(DesignClassificationTestCase):
    def test_registration_version_and_identity(self):
        self.assertEqual(self.registration["preregistration_version"],
                         "jev-discovery-registration-v1")
        self.assertEqual(self.registration["issue"], "#205")
        self.assertEqual(self.registration["parent_issue"], "#201")
        self.assertEqual(self.registration["root_issue"], "#159")
        self.assertEqual(self.registration["family"], "hypothesis")
        self.assertIs(self.registration["offline_only"], True)
        self.assertIn("no collection", self.registration["authorizes"])
        self.assertEqual(self.registration["status"], "draft_pending_review")

    def test_approval_not_inferred_from_locking(self):
        authorization = self.registration["authorization"]
        self.assertIs(authorization["locking_is_not_authorization"], True)
        self.assertIs(authorization["approval_may_not_be_inferred_from_locking"], True)
        self.assertIs(authorization["separate_live_authorization_required_after_locking"],
                      True)
        self.assertTrue(any("separate explicit live authorization" in item
                            for item in authorization["pending_review"]))


class DesignClassificationTests(DesignClassificationTestCase):
    def test_k4_and_floor(self):
        classification = self.registration["design_classification"]
        self.assertEqual(classification["k"], 4)
        self.assertEqual(classification["attainable_two_sided_sign_flip_floor"], "0.125")
        self.assertIs(classification["floor_above_0_05"], True)

    def test_classification_is_pilot(self):
        classification = self.registration["design_classification"]
        self.assertEqual(classification["classification"], "pilot")
        pilot_vs = classification["pilot_vs_potentially_confirmatory"]
        self.assertIn("pilot", pilot_vs)
        self.assertIn("not potentially confirmatory", pilot_vs)
        self.assertIn("k = 4 < 6", pilot_vs)

    def test_k_bands_recorded(self):
        bands = self.registration["design_classification"]["k_bands"]
        self.assertEqual([band["k"] for band in bands], [4, 5, 6, 7])
        self.assertEqual(bands[0]["floor"], "0.125")
        self.assertEqual(bands[1]["floor"], "0.0625")
        self.assertEqual(bands[2]["floor"], "0.03125")
        self.assertEqual(bands[3]["floor"], "0.015625")
        self.assertIn("potentially confirmatory", bands[2]["classification"])
        self.assertIn("potentially confirmatory", bands[3]["classification"])

    def test_fresh_seed_replication_descriptive(self):
        classification = self.registration["design_classification"]
        self.assertIn("descriptive only", classification["fresh_seed_replication"])
        self.assertIn("k = 4", self.normalized)
        self.assertIn("0.125", self.normalized)
        self.assertIn("descriptive", self.normalized)

    def test_contract_phrases_are_present(self):
        classification = self.registration["design_classification"]
        self.assertEqual(classification["h0"], "Delta = 0")
        self.assertEqual(classification["h1"], "Delta < 0")
        self.assertEqual(classification["estimand"],
                         "equal-weight form mean of real-minus-placebo entropy")
        self.assertIs(classification["guards_never_filter_the_estimate"], True)
        self.assertIs(classification["no_planning_low_effect_size_prior"], True)
        self.assertIs(classification["distinct_seed_ids_are_not_independent_forms"], True)
        for phrase in ("H0: Delta = 0", "H1: Delta < 0",
                       "equal-weight form mean of real-minus-placebo entropy",
                       "Guards never filter the estimate",
                       "No planning-low effect-size prior"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)


class FixedNTests(DesignClassificationTestCase):
    def test_fixed_n_block_n_16(self):
        fixed_n = self.registration["fixed_n"]
        self.assertEqual(fixed_n["block_n"], 16)
        self.assertEqual(fixed_n["instances_per_form"], 4)
        self.assertEqual(fixed_n["form_count"], 4)
        self.assertEqual(fixed_n["block"], "discovery")

    def test_fixed_n_window(self):
        window = self.registration["fixed_n"]["window"]
        self.assertEqual(window["base"], 85000)
        self.assertEqual(window["end"], 85511)
        self.assertEqual(window["window"], 512)

    def test_manifest_has_16_instances_4_per_form(self):
        manifest = self.registration["fixed_n"]["manifest"]
        self.assertEqual(len(manifest), 16)
        counts = {}
        for entry in manifest:
            counts[entry["prompt_form_id"]] = counts.get(entry["prompt_form_id"], 0) + 1
        self.assertEqual(len(counts), 4)
        self.assertTrue(all(count == 4 for count in counts.values()))

    def test_manifest_matches_200_audit_primary_block(self):
        manifest = self.registration["fixed_n"]["manifest"]
        audit_primary = self.audit["blocks"]["primary"]["manifest"]
        self.assertEqual(manifest, audit_primary)
        self.assertIs(self.registration["fixed_n"]["matches_200_audit_primary_block"], True)

    def test_manifest_form_ids_match(self):
        manifest = self.registration["fixed_n"]["manifest"]
        self.assertEqual(sorted({entry["prompt_form_id"] for entry in manifest}), FORM_IDS)

    def test_selection_rule_fixed_no_stopping(self):
        rule = self.registration["fixed_n"]["selection_rule"]
        self.assertIn("fixed N", rule)
        self.assertIn("no outcome-based stopping", rule)
        self.assertIn("no outcome-based stopping", self.normalized)


class TreatmentRouteTests(DesignClassificationTestCase):
    def test_treatment_original_l4x(self):
        treatment = self.registration["treatment"]
        self.assertEqual(treatment["mode"], "exact-original-comm-bridge")
        self.assertEqual(treatment["family"], "hypothesis")
        self.assertEqual(treatment["complexity"], "low")
        self.assertEqual(treatment["regime"], "N")
        self.assertEqual(treatment["agents"], ["A", "B"])
        self.assertEqual(treatment["turns"], 2)
        self.assertEqual(treatment["primary_direction"], "one-way B->A")
        self.assertIn("writer_prompt", treatment)
        self.assertIn("writer_transport", treatment)

    def test_ling_route_paid_openrouter(self):
        ling = self.registration["route"]["ling"]
        self.assertEqual(ling["model"], "inclusionai/ling-3.0-flash-vl")
        self.assertEqual(ling["route"], "paid OpenRouter SKU (the free SKU is not routable)")
        self.assertIn("ling-writer-openrouter-pacing-v3", ling["pacing"])

    def test_jev_receiver_pins(self):
        jev = self.registration["route"]["jev"]
        self.assertEqual(jev["model"], "jev-1.13.0")
        self.assertEqual(jev["codec_version"], "jev-choice-wire-v2")
        self.assertTrue(jev["protocol_key"].startswith("jev-choice-wire-v2|"))
        self.assertEqual(jev["max_retries"], 2)

    def test_normalization_policy(self):
        normalization = self.registration["route"]["normalization"]
        self.assertEqual(normalization["policy_hash"],
                         "292ac217f1cf54083252e6363a16a48596daab72a8ca06d4569c20f861b7e1e9")
        self.assertEqual(normalization["hard_ceiling"], 0.05)
        self.assertIn("normalize every accepted vector", normalization["rule"])


class BudgetTests(DesignClassificationTestCase):
    def test_budget_arithmetic(self):
        budgets = self.registration["budgets"]
        collection = budgets["discovery_collection"]
        replay = budgets["exploratory_replay"]
        program = budgets["program"]
        self.assertEqual(collection["planned"]["ling"], 64)
        self.assertEqual(collection["planned"]["jev"], 16)
        self.assertEqual(collection["physical"]["ling"], 192)
        self.assertEqual(collection["physical"]["jev"], 48)
        self.assertEqual(replay["planned"]["jev"], 48)
        self.assertEqual(replay["physical"]["jev"], 144)
        self.assertEqual(program["planned"]["ling"], 64)
        self.assertEqual(program["planned"]["jev"], 64)
        self.assertEqual(program["physical"]["ling"], 192)
        self.assertEqual(program["physical"]["jev"], 192)

    def test_cost_model_matches_registered_rates(self):
        cost = self.registration["budgets"]["cost_model"]
        self.assertEqual(cost["ling_worst_physical_call_usd"], 0.00067584)
        self.assertEqual(cost["jev_worst_physical_call_usd"], 0.000344064)

    def test_worst_case_costs_within_ceilings(self):
        budgets = self.registration["budgets"]
        self.assertLessEqual(budgets["discovery_collection"]["worst_case_cost_usd"],
                             budgets["discovery_collection"]["cost_ceiling_usd"])
        self.assertLessEqual(budgets["exploratory_replay"]["worst_case_cost_usd"],
                             budgets["exploratory_replay"]["cost_ceiling_usd"])
        self.assertLessEqual(budgets["program"]["worst_case_cost_usd"],
                             budgets["program"]["cost_ceiling_usd"])
        self.assertEqual(budgets["discovery_collection"]["worst_case_cost_usd"],
                         0.146276352)
        self.assertEqual(budgets["exploratory_replay"]["worst_case_cost_usd"],
                         0.049545216)
        self.assertEqual(budgets["program"]["worst_case_cost_usd"], 0.195821568)

    def test_budget_figures_in_doc(self):
        for figure in ("0.146276352", "0.049545216", "0.195821568"):
            with self.subTest(figure=figure):
                self.assertIn(figure, self.normalized)


class StopsPathsTests(DesignClassificationTestCase):
    def test_terminal_stops_registered(self):
        stops = self.registration["stops"]
        joined = " ".join(stops)
        self.assertIn("output collision", joined)
        self.assertIn("hash drift", joined)
        self.assertIn("cost cap", joined)
        self.assertIn("model drift", joined)
        self.assertIn("normalization deviation", joined)

    def test_paths_registered_and_freshness_matches_current_state(self):
        paths = self.registration["paths"]
        for key in ("registration", "discovery_journal", "discovery_report",
                     "exploratory_replay_journal", "exploratory_replay_report"):
            with self.subTest(key=key):
                self.assertIn(key, paths)
        expected_fresh = not any(self.live_before)
        verification = p04.verify_registration(self.registration, repo_root=REPO_ROOT)
        freshness = next(check for check in verification["checks"]
                         if check["check"] == "paths_are_fresh")
        self.assertEqual(freshness["ok"], expected_fresh, freshness["detail"])

    def test_paths_outside_epic_126(self):
        for key, path in self.registration["paths"].items():
            with self.subTest(key=key):
                self.assertFalse(path.startswith("runs/epic-126/"))

    def test_path_lifecycle_no_resume_append_overwrite(self):
        lifecycle = self.registration["path_lifecycle"]
        self.assertIs(lifecycle["fresh_paths"], True)
        self.assertIs(lifecycle["resume"], False)
        self.assertIs(lifecycle["append"], False)
        self.assertIs(lifecycle["overwrite"], False)
        self.assertIs(lifecycle["path_overrides"], False)

    def test_path_location_note_records_scan_reason(self):
        note = self.registration["path_lifecycle"]["location_note"]
        self.assertIn("prior-instance-id pin", note)
        self.assertIn("runs/epic-126/", note)
        self.assertIn("P02/P03", note)


class CoverageRulesTests(DesignClassificationTestCase):
    def test_permissible_within_form_missingness(self):
        coverage = self.registration["coverage_rules"]
        self.assertIn("up to 3 of 4 seeds per form", coverage["permissible_within_form_missingness"])
        self.assertEqual(coverage["min_complete_per_form"], 1)

    def test_complete_case_scope_and_selection_risk(self):
        coverage = self.registration["coverage_rules"]
        self.assertIn("all required fields", coverage["complete_case_scope"])
        self.assertIn("reported by stage, form, and branch with reasons",
                      coverage["complete_case_scope"])
        self.assertIn("not random", coverage["selection_risk"])
        self.assertIn("biased", coverage["selection_risk"])
        self.assertIn("complete-case scope and selection risk",
                      coverage["selection_risk"])

    def test_no_imputation_no_replacement_no_removal(self):
        coverage = self.registration["coverage_rules"]
        self.assertIs(coverage["no_imputation"], True)
        self.assertIs(coverage["no_seed_replacement"], True)
        self.assertIs(coverage["no_form_removal_after_outcomes"], True)

    def test_missing_entire_form_rule(self):
        coverage = self.registration["coverage_rules"]
        self.assertIn("blocks confirmation", coverage["missing_entire_form"])
        self.assertIn("descriptive", coverage["missing_entire_form"])

    def test_discovery_screen_requirements(self):
        requirements = self.registration["coverage_rules"]["discovery_screen_requirements"]
        joined = " ".join(requirements)
        self.assertIn("structural need", joined)
        self.assertIn("voluntary emission", joined)
        self.assertIn("ownership", joined)
        self.assertIn("board write", joined)


class ExploratoryReplayTests(DesignClassificationTestCase):
    def test_exploratory_replay_labeled_exploratory(self):
        exploratory = self.registration["exploratory_replay"]
        self.assertIn("exploratory", exploratory["label"])
        self.assertIn("never confirmatory", exploratory["label"])
        self.assertIn("separately covered by P05 authorization", exploratory["status"])

    def test_exploratory_replay_descriptive_only(self):
        exploratory = self.registration["exploratory_replay"]
        self.assertIn("descriptive only", exploratory["inference"])
        self.assertIn("0.125", exploratory["inference"])
        self.assertIs(exploratory["may_not_pool_with_held_out"], True)

    def test_exploratory_replay_branches(self):
        exploratory = self.registration["exploratory_replay"]
        self.assertEqual(exploratory["branches"], ["real", "placebo", "null"])
        self.assertIn("state.visible_messages", exploratory["only_difference"])


class NewVersionResolutionTests(DesignClassificationTestCase):
    def test_six_form_minimum(self):
        inference = self.registration["inference_plan"]
        self.assertEqual(inference["minimum_forms_for_confirmatory"], 6)
        self.assertIn("six", inference["minimum_form_rule"])
        self.assertIn("six-form", self.normalized)

    def test_interval_half_width_labeled_not_mde(self):
        half_width = self.registration["inference_plan"]["interval_half_width"]
        self.assertIn("not a power-based MDE", half_width["label"])
        self.assertIs(half_width["not_a_prior"], True)
        self.assertIn("interval half-width", self.normalized)
        self.assertIn("not a power-based MDE", self.normalized)

    def test_no_five_form_minimum_wording(self):
        inference = self.registration["inference_plan"]
        self.assertNotIn(5, [inference["minimum_forms_for_confirmatory"]])
        self.assertNotIn("five-form minimum", self.normalized_lower)


class InferencePlanTests(DesignClassificationTestCase):
    def test_sign_flip_and_t_interval_primary(self):
        inference = self.registration["inference_plan"]
        self.assertIn("sign-flip", inference["primary_test"])
        self.assertIn("form-mean t interval", inference["interval"])
        self.assertEqual(inference["direction_requirement"],
                         "the observed equal-form mean must be negative")

    def test_no_instance_level_primary(self):
        inference = self.registration["inference_plan"]
        self.assertIn("instance-level t-test", inference["prohibited_as_primary"])
        self.assertIn("instance-level Wilcoxon test", inference["prohibited_as_primary"])

    def test_guards_never_filter_registered(self):
        guards = self.registration["inference_plan"]["guards"]
        self.assertEqual(guards["target_probability_delta"], 0.0)
        self.assertEqual(guards["feasible_set_mass_epsilon"], 0.01)
        self.assertIn("never used to filter", guards["reporting"])

    def test_missingness_rules(self):
        missingness = self.registration["inference_plan"]["missingness"]
        self.assertIn("at least one complete pair in every registered form",
                      missingness["primary_requirement"])
        self.assertIn("descriptive", missingness["below_six_forms"])
        self.assertIn("blocks confirmation", missingness["missing_entire_form"])


class MultiplicityTests(DesignClassificationTestCase):
    def test_holm_rule_frozen_family_set(self):
        multiplicity = self.registration["multiplicity"]
        self.assertIn("Holm", multiplicity["family_level_control"])
        self.assertEqual(multiplicity["registered_family_set"], ["hypothesis"])
        self.assertIs(multiplicity["family_set_frozen_before_outcomes"], True)

    def test_post_hoc_family_selection_forbidden(self):
        forbidden = self.registration["multiplicity"]["forbidden"]
        self.assertIn("sweeping families and selecting a winner post hoc", forbidden)


class DeterministicRebuildTests(DesignClassificationTestCase):
    def test_registration_rebuilds_byte_for_byte(self):
        rebuilt = p04.build_registration(REPO_ROOT)
        self.assertEqual(rebuilt, self.registration)
        self.assertEqual(p04._render(rebuilt), REGISTRATION.read_text(encoding="utf-8"))

    def test_registration_cli_verification_is_green(self):
        buffer = io.StringIO()
        calls = []

        def explode(*args, **kwargs):
            calls.append(1)
            raise AssertionError("provider call attempted offline")

        with patch("urllib.request.urlopen", explode):
            with contextlib.redirect_stdout(buffer):
                rc = p04.main(["--repo-root", str(REPO_ROOT)])
        self.assertEqual(calls, [])
        verification = json.loads(buffer.getvalue())
        expected_fresh = not any(self.live_before)
        self.assertEqual(rc, 0 if expected_fresh else 2)
        self.assertEqual(verification["ok"], expected_fresh, verification["failed"])
        if expected_fresh:
            self.assertEqual(verification["failed"], [])
        else:
            self.assertIn("paths_are_fresh", verification["failed"])
        self.assertGreaterEqual(len(verification["checks"]), 41)
        self.assertEqual(verification["provider_calls"], 0)


class FrozenArtifactTests(DesignClassificationTestCase):
    def test_frozen_artifacts_are_byte_unchanged(self):
        self.assertEqual(sha256_of(AUDIT),
                         "cb529cd61e0e662bfa19fc4998e89fa59a0bf0d63e14f77498035466d6bce89d")
        self.assertEqual(sha256_of(REGISTRATION_200),
                         "bddf46ed5fd87ec4da99532d645580a65e250d64639de80477002ff73d278f3c")


class DocContentTests(DesignClassificationTestCase):
    def test_required_phrases_present(self):
        for phrase in REQUIRED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)

    def test_banned_overclaims_are_absent(self):
        for phrase in BANNED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase.lower(), self.normalized_lower)

    def test_handoff_records_next_step_and_no_successor_authorization(self):
        handoff = " ".join(self.text.split("## 5. Handoff")[1].split())
        self.assertIn("P05 (#206)", handoff)
        self.assertIn("lock discovery design and record live authorization", handoff)
        self.assertIn("A predecessor closed as failed does not authorize successor execution",
                      handoff)
        self.assertIn("blocked by this task", handoff)

    def test_checks_section_records_the_offline_verification(self):
        checks = " ".join(self.text.split("## 4. Checks")[1].split("## 5.")[0].split())
        self.assertIn("provider_calls: 0", checks)
        self.assertIn("byte-for-byte", checks)
        self.assertIn("fail closed on drift", checks)
        self.assertIn("41/41", checks)


if __name__ == "__main__":
    unittest.main()
