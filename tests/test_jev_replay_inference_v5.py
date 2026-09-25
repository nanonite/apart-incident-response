import copy
import hashlib
import itertools
import json
import math
import tempfile
import unittest
from pathlib import Path

from apart_incident_response import jev_replay_inference as ji
from apart_incident_response import jev_replay_inference_v5 as inf


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = REPO_ROOT / inf.DEFAULT_OUTPUT
REGISTRATION_PATH = REPO_ROOT / inf.DEFAULT_REGISTRATION
INPUTS = inf.load_inputs(REPO_ROOT)
JOURNAL = INPUTS["journal_rows"]
REPORT = INPUTS["report"]
REGISTRATION = INPUTS["registration"]
FORMS = tuple(inf.REQUIRED_FORMS)


def artifact() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def structure(rows=None, report=None, registration=None) -> dict:
    return inf.verify_structure(
        rows if rows is not None else JOURNAL,
        report if report is not None else REPORT,
        registration if registration is not None else REGISTRATION)


def failed(result: dict) -> list:
    return [entry["check"] for entry in result["checks"] if not entry["ok"]]


class InputsTestCase(unittest.TestCase):
    """Every test proves the frozen run inputs and prior artifacts stay put."""

    def setUp(self):
        self.input_hashes = dict(INPUTS["sha256"])
        self.artifact_sha = hashlib.sha256(ARTIFACT.read_bytes()).hexdigest()

    def tearDown(self):
        current = {name: inf.sha256_file(REPO_ROOT / relative)
                   for name, relative in INPUTS["paths"].items()}
        self.assertEqual(current, self.input_hashes, "a frozen input changed")
        self.assertEqual(hashlib.sha256(ARTIFACT.read_bytes()).hexdigest(),
                         self.artifact_sha, "the analysis artifact changed")


class HashIntegrityTests(InputsTestCase):
    def test_pinned_hashes_match(self):
        result = inf.verify_hashes(INPUTS)
        self.assertTrue(result["ok"], result["errors"])

    def test_journal_hash_drift_fails_closed(self):
        pins = dict(inf.PINNED)
        pins["journal_sha256"] = "0" * 64
        result = inf.verify_hashes(INPUTS, pins=pins)
        self.assertFalse(result["ok"])
        self.assertIn("journal_hash_matches_pinned", failed(result))

    def test_report_hash_drift_fails_closed(self):
        pins = dict(inf.PINNED)
        pins["report_sha256"] = "0" * 64
        self.assertFalse(inf.verify_hashes(INPUTS, pins=pins)["ok"])

    def test_registration_hash_drift_fails_closed(self):
        pins = dict(inf.PINNED)
        pins["registration_hash"] = "0" * 64
        result = inf.verify_hashes(INPUTS, pins=pins)
        self.assertFalse(result["ok"])
        self.assertIn("registration_content_hash_matches_pinned", failed(result))

    def test_tampered_registration_content_fails_closed(self):
        tampered = copy.deepcopy(INPUTS)
        tampered["registration"]["purpose"] = "tampered"
        result = inf.verify_hashes(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("registration_content_hash_matches_pinned", failed(result))

    def test_compute_fails_closed_on_artifact_drift(self):
        with tempfile.TemporaryDirectory(prefix="inference-drift-") as directory:
            root = Path(directory)
            for name, relative in INPUTS["paths"].items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((REPO_ROOT / relative).read_bytes())
            journal = root / INPUTS["paths"]["journal"]
            journal.write_text(journal.read_text(encoding="utf-8") + "\n",
                               encoding="utf-8")
            with self.assertRaises(inf.AnalysisError):
                inf.compute(root)


class StructuralIntegrityTests(InputsTestCase):
    def test_real_inputs_pass_every_check(self):
        result = structure()
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["errors"], [])

    def test_duplicate_records_fail_closed(self):
        rows = list(JOURNAL) + [dict(JOURNAL[0])]
        self.assertIn("no_duplicate_event_branch_records", failed(structure(rows=rows)))

    def test_duplicate_report_events_fail_closed(self):
        report = copy.deepcopy(REPORT)
        report["events"].append(copy.deepcopy(report["events"][0]))
        self.assertIn("no_duplicate_report_events", failed(structure(report=report)))

    def test_missing_branch_fails_closed_without_imputation(self):
        rows = [dict(row) for row in JOURNAL if not (
            row["event_id"] == JOURNAL[0]["event_id"] and row["branch"] == "null")]
        result = structure(rows=rows)
        names = failed(result)
        self.assertIn("journal_row_count_matches_report", names)
        self.assertIn("all_three_branches_present_per_event", names)

    def test_mixed_protocols_fail_closed(self):
        rows = [dict(row) for row in JOURNAL]
        rows[0]["protocol_key"] = "jev-choice-wire-v1|deadbeef"
        names = failed(structure(rows=rows))
        self.assertIn("single_protocol_key_in_journal", names)
        self.assertIn("journal_protocol_matches_registration", names)

    def test_single_model_enforced(self):
        rows = [dict(row) for row in JOURNAL]
        rows[0]["resolved_model"] = "jev-9.9.9"
        names = failed(structure(rows=rows))
        self.assertIn("single_model_in_journal", names)
        self.assertIn("journal_model_matches_registration", names)

    def test_branch_request_hash_drift_fails_closed(self):
        rows = [dict(row) for row in JOURNAL]
        rows[0]["request_hash"] = "0" * 64
        self.assertIn("branch_request_hashes_match_registration", failed(structure(rows=rows)))

    def test_branch_state_hash_drift_fails_closed(self):
        rows = [dict(row) for row in JOURNAL]
        rows[0]["state_hash"] = "0" * 64
        self.assertIn("branch_state_hashes_match_registration", failed(structure(rows=rows)))

    def test_malformed_vector_fails_closed(self):
        rows = [dict(row) for row in JOURNAL]
        rows[0]["probabilities"] = {"only": 2.0}
        self.assertIn("malformed_vectors_rejected", failed(structure(rows=rows)))

    def test_non_finite_metric_fails_closed(self):
        rows = [dict(row) for row in JOURNAL]
        rows[0]["entropy_bits"] = float("nan")
        names = failed(structure(rows=rows))
        self.assertIn("metrics_present_and_finite", names)
        self.assertIn("no_imputation_required", names)

    def test_six_required_forms_enforced(self):
        rows = [dict(row) for row in JOURNAL]
        rows[0]["prompt_form_id"] = "not-a-frozen-form"
        names = failed(structure(rows=rows))
        self.assertIn("six_required_forms_present", names)
        self.assertIn("form_event_distribution_matches", names)

    def test_stale_registration_hash_fails_closed(self):
        report = copy.deepcopy(REPORT)
        report["registration_hash"] = "0" * 64
        self.assertIn("report_registration_hash_matches", failed(structure(report=report)))

    def test_incomplete_run_status_fails_closed(self):
        report = copy.deepcopy(REPORT)
        report["status"] = "stopped"
        self.assertIn("report_status_completed", failed(structure(report=report)))


class SignFlipTests(unittest.TestCase):
    def test_exact_enumeration_matches_independent_bruteforce(self):
        values = [-1.036554951204699, -0.8642350835480621, -0.6436499821287791,
                  -0.8404057620820807, -0.10495083234600536, -1.1752544651287469]
        observed = sum(values) / len(values)
        count = 0
        total = 0
        for signs in itertools.product((1, -1), repeat=len(values)):
            total += 1
            signed = sum(sign * value for sign, value in zip(signs, values)) / len(values)
            if abs(signed) >= abs(observed) - 1e-12:
                count += 1
        result = ji.sign_flip_two_sided(values)
        self.assertEqual(result["permutations"], 64)
        self.assertEqual(total, 64)
        self.assertEqual(result["p_value"], count / 64)

    def test_all_negative_forms_hit_the_k6_floor(self):
        result = ji.sign_flip_two_sided([-0.1] * 6)
        self.assertEqual(result["p_value"], 2 / 64)
        self.assertEqual(result["p_value"], 0.03125)
        self.assertEqual(result["min_p_value"], 0.03125)

    def test_mixed_signs_raise_the_p_value(self):
        result = ji.sign_flip_two_sided([-1.0, -1.0, -1.0, -1.0, 1.0, 1.0])
        self.assertGreater(result["p_value"], 0.03125)

    def test_artifact_p_value_is_the_floor(self):
        primary = artifact()["primary"]
        self.assertEqual(primary["sign_flip"]["p_value"], 0.03125)
        self.assertEqual(primary["sign_flip"]["min_p_value"], 0.03125)
        self.assertEqual(primary["p_value_floor_k6"], 0.03125)
        self.assertEqual(primary["k"], 6)


class EstimandTests(InputsTestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = artifact()

    def test_form_aggregation_recomputed(self):
        d_by_form: dict[str, list[float]] = {}
        for event in self.doc["per_event"]:
            d_by_form.setdefault(event["prompt_form_id"], []).append(event["d_i"])
        for row in self.doc["form_table"]:
            values = d_by_form[row["form"]]
            self.assertEqual(row["n_pairs"], len(values))
            self.assertAlmostEqual(row["d_f"], sum(values) / len(values), places=12)

    def test_primary_is_equal_weight_mean_of_form_means(self):
        primary = self.doc["primary"]
        form_means = [row["d_f"] for row in self.doc["form_table"]]
        self.assertAlmostEqual(primary["estimate"], sum(form_means) / len(form_means),
                               places=12)
        instance_weighted = (sum(event["d_i"] for event in self.doc["per_event"])
                             / len(self.doc["per_event"]))
        self.assertNotAlmostEqual(primary["estimate"], instance_weighted, places=6,
                                  msg="the primary must be form-weighted, not instance-weighted")

    def test_t_interval_df5(self):
        primary = self.doc["primary"]
        form_means = [row["d_f"] for row in self.doc["form_table"]]
        mean = sum(form_means) / len(form_means)
        sd = math.sqrt(sum((value - mean) ** 2 for value in form_means)
                       / (len(form_means) - 1))
        half = ji.t_critical_975(5) * (sd / math.sqrt(6))
        self.assertEqual(primary["df"], 5)
        self.assertAlmostEqual(primary["t_interval_975"][0], mean - half, places=12)
        self.assertAlmostEqual(primary["t_interval_975"][1], mean + half, places=12)

    def test_direction_requirement(self):
        primary = self.doc["primary"]
        self.assertEqual(primary["direction_required"], "negative")
        self.assertTrue(primary["direction_met"])
        self.assertTrue(primary["interval_excludes_zero"])

    def test_positive_estimate_fails_the_direction_requirement(self):
        flipped = inf._primary([-value for value in
                                [row["d_f"] for row in self.doc["form_table"]]])
        self.assertFalse(flipped["direction_met"])
        self.assertFalse(flipped["criterion_met"])

    def test_primary_criterion_requires_all_six_forms(self):
        five = inf._primary([-0.1] * 5)
        self.assertFalse(five["criterion_met"])
        self.assertEqual(five["k"], 5)

    def test_no_instance_level_inference_is_primary(self):
        primary = self.doc["primary"]
        self.assertEqual(primary["unit"], "prompt form")
        self.assertIn("sign-flip", primary["test"])
        self.assertEqual(self.doc["estimand"]["events_are_independent_units"], False)


class MissingnessTests(InputsTestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = artifact()

    def test_no_imputation_and_full_completeness(self):
        missingness = self.doc["missingness"]
        self.assertEqual(missingness["imputation"], "none")
        self.assertEqual(missingness["complete_pairs"], 17)
        self.assertEqual(missingness["incomplete_pairs"], 0)
        self.assertEqual(missingness["partial_triplets"], 0)
        self.assertTrue(missingness["primary_requirement_met"])
        for branch in ("real", "placebo", "null"):
            counts = missingness["by_branch"][branch]
            self.assertEqual(counts["planned"], 17)
            self.assertEqual(counts["attempted"], 17)
            self.assertEqual(counts["valid"], 17)
            self.assertEqual(counts["invalid"], 0)
            self.assertEqual(counts["unattempted"], 0)
        self.assertEqual(sum(missingness["complete_pairs_by_form"].values()), 17)
        self.assertEqual(len(missingness["complete_pairs_by_form"]), 6)

    def test_complete_pairs_by_form_match_the_registered_distribution(self):
        expected = {"0a3349e16c9633b4d559dfbb808d1e50d0446d8f92160a0feddd1e37299796ee": 1,
                    "1c1d9f6b5c9271ad8e74de180c3e397e1369d326564c9a08ba0840eff0b148fc": 4,
                    "2954f5684bcd198ed8eea0956cf573f93cde628d6dfa7472fc57f556bd089b2c": 4,
                    "3196a8d69f844702db012816def7d7866e7416e9fadc9f28eaa7f12ac16a8569": 1,
                    "55968fe191b18f37d1951d71f777115f753e0b9a6da526015f3db5251a1383eb": 4,
                    "ce847ac53b6e344103bc775aede5212b2be6fbd568dc1d85fd24cbde8f585222": 3}
        self.assertEqual(self.doc["missingness"]["complete_pairs_by_form"], expected)
        self.assertEqual(self.doc["form_table"][0]["n_pairs"], 1)


class GuardTests(InputsTestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = artifact()

    def test_guards_never_filter_the_primary_estimate(self):
        guards = self.doc["guards"]
        self.assertIs(guards["filtered_primary_estimate"], False)
        self.assertEqual(guards["excluded_from_primary"], 0)
        self.assertEqual(guards["filtering"],
                         "never used to filter the primary estimate")
        self.assertEqual(len(guards["events"]), 17)
        self.assertEqual(len(self.doc["per_event"]), 17)

    def test_guard_failing_events_still_enter_the_estimate(self):
        failing = [event for event in self.doc["per_event"]
                   if not event["guards"]["mass_ok_i"]]
        self.assertEqual(len(failing), 2)
        by_form = {row["form"]: row for row in self.doc["form_table"]}
        for event in failing:
            self.assertIn(event["prompt_form_id"], by_form)
        # the form holding the two guard failures still carries all four pairs
        form_with_failures = {event["prompt_form_id"] for event in failing}.pop()
        self.assertEqual(by_form[form_with_failures]["n_pairs"], 4)
        self.assertEqual(self.doc["guards"]["per_form"][form_with_failures]["mass_ok"], 2)

    def test_guard_counts(self):
        guards = self.doc["guards"]
        self.assertEqual(guards["target_ok_events"], 17)
        self.assertEqual(guards["mass_ok_events"], 15)
        self.assertEqual(guards["useful_uptake_events"], 15)
        self.assertEqual(guards["target_violations"], 0)
        self.assertEqual(guards["mass_violations"], 2)
        self.assertEqual(guards["delta"], 0.0)
        self.assertEqual(guards["epsilon"], 0.01)

    def test_guard_failures_are_not_exclusions(self):
        primary_with_all = inf._primary([row["d_f"] for row in self.doc["form_table"]])
        passing = [event for event in self.doc["per_event"]
                   if event["guards"]["useful_uptake_i"]]
        d_by_form: dict[str, list[float]] = {}
        for event in passing:
            d_by_form.setdefault(event["prompt_form_id"], []).append(event["d_i"])
        primary_passing_only = inf._primary(
            [sum(values) / len(values) for _, values in sorted(d_by_form.items())])
        self.assertNotAlmostEqual(primary_with_all["estimate"],
                                  primary_passing_only["estimate"], places=9)
        self.assertAlmostEqual(self.doc["primary"]["estimate"],
                               primary_with_all["estimate"], places=12)


class NormalizationSensitivityTests(InputsTestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = artifact()

    def test_tiers_reported(self):
        normalization = self.doc["normalization"]
        self.assertEqual(normalization["tiers"], {"exact": 50,
                                                  "complete_renormalized": 1})
        self.assertEqual(normalization["exact_rows"], 50)
        self.assertEqual(normalization["complete_renormalized_rows"], 1)
        self.assertEqual(normalization["other_rows"], 0)
        self.assertEqual(normalization["thresholds"], [1e-6, 0.01, 0.03, 0.05])

    def test_sensitivity_grid_covers_every_threshold(self):
        grid = self.doc["normalization"]["sensitivity"]["grid"]
        self.assertEqual([row["threshold"] for row in grid],
                         [1e-6, 0.01, 0.03, 0.05])
        self.assertIn("conclusion_changed", self.doc["normalization"]["sensitivity"]
                      ["conclusion_definition"])

    def test_conclusions_do_not_change_across_the_grid(self):
        grid = self.doc["normalization"]["sensitivity"]["grid"]
        for row in grid:
            with self.subTest(threshold=row["threshold"]):
                self.assertFalse(row["conclusion_changed"])
                self.assertFalse(row["criterion_changed"])
                self.assertFalse(row["k_changed"])
                self.assertTrue(row["criterion_met"])
                self.assertEqual(row["k"], 6)
                self.assertEqual(row["sign_flip_p_value"], 0.03125)

    def test_tightest_threshold_moves_only_the_estimate(self):
        grid = self.doc["normalization"]["sensitivity"]["grid"]
        tightest = grid[0]
        self.assertEqual(tightest["threshold"], 1e-6)
        self.assertEqual(tightest["excluded_event_count"], 1)
        self.assertEqual(tightest["accepted_pairs"], 16)
        self.assertTrue(tightest["estimate_changed"])
        self.assertNotAlmostEqual(tightest["estimate"],
                                  self.doc["primary"]["estimate"], places=9)
        self.assertIn("point estimate moved", tightest["conclusion_note"])

    def test_registered_threshold_reproduces_the_primary_result(self):
        grid = self.doc["normalization"]["sensitivity"]["grid"]
        registered = next(row for row in grid if row["threshold"] == 0.01)
        self.assertEqual(registered["accepted_pairs"], 17)
        self.assertAlmostEqual(registered["estimate"], self.doc["primary"]["estimate"],
                               places=12)
        self.assertEqual(registered["conclusion_note"],
                         "no change: same k, same point estimate and same registered decision")


class ArtifactTests(InputsTestCase):
    def test_artifact_reproduces_byte_for_byte(self):
        rebuilt = inf.compute(REPO_ROOT)
        rendered = json.dumps(rebuilt, indent=2, sort_keys=True, allow_nan=False) + "\n"
        self.assertEqual(rendered, ARTIFACT.read_text(encoding="utf-8"))

    def test_artifact_records_inputs_and_registration(self):
        doc = artifact()
        self.assertEqual(doc["analysis_version"], "jev-replay-inference-v5-v1")
        self.assertEqual(doc["registration_hash"], inf.PINNED["registration_hash"])
        self.assertEqual(doc["inputs"]["journal"]["sha256"], inf.PINNED["journal_sha256"])
        self.assertEqual(doc["inputs"]["report"]["sha256"], inf.PINNED["report_sha256"])
        self.assertEqual(doc["inputs"]["registration"]["sha256"],
                         inf.PINNED["registration_file_sha256"])
        self.assertEqual(doc["inputs"]["run_commit"], inf.PINNED["run_commit"])
        self.assertTrue(doc["verification"]["ok"])

    def test_run_refuses_to_overwrite(self):
        result = inf.run(REPO_ROOT)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stop_reason"], "output_exists")
        self.assertFalse(result["written"])

    def test_written_output_is_outside_the_live_paths(self):
        self.assertEqual(str(inf.DEFAULT_OUTPUT),
                         "runs/epic-126/replay-v5/jev-choice-replay-inference-v5.json")
        self.assertNotEqual(inf.DEFAULT_OUTPUT, inf.DEFAULT_JOURNAL)
        self.assertNotEqual(inf.DEFAULT_OUTPUT, inf.DEFAULT_REPORT)

    def test_analysis_is_deterministic_and_call_free(self):
        doc = artifact()
        self.assertNotIn("written_at", json.dumps(doc))
        self.assertIn("byte-identical for identical inputs", doc["determinism"])


class ClaimScopeTests(InputsTestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = artifact()

    def test_registered_causal_uptake_is_scoped(self):
        uptake = self.doc["registered_causal_uptake"]
        self.assertIs(uptake["criterion_met"], True)
        self.assertIs(uptake["guards_filtered_primary"], False)
        self.assertIn("registered conditional scope only", uptake["scope"])

    def test_non_claims_are_explicit(self):
        non_claims = " ".join(self.doc["non_claims"])
        for phrase in ("no calibration claim", "no population-level", "no generalization",
                       "no instance-level inference",
                       "never reported as unique delivered information"):
            self.assertIn(phrase, non_claims)

    def test_mde_limitation_and_conditional_scope(self):
        limitations = self.doc["limitations"]
        self.assertEqual(limitations["mde_or_ci_bits"], 0.203)
        self.assertIn("the six frozen planning-low prompt forms",
                      limitations["conditional_on"])
        self.assertIn("six frozen", self.doc["claim_scope"]["statement"])

    def test_information_accounting_distinguishes_gross_from_unique(self):
        block = self.doc["information_accounting"]
        self.assertFalse(block["gross_equals_unique"])
        self.assertAlmostEqual(block["gross_replay_eligible_bits"], 26.9443625123, places=6)
        self.assertAlmostEqual(block["unique_delivered_bits_over_distinct_treatments"],
                               9.5097750043, places=6)
        self.assertEqual(block["distinct_form_claim_treatments"], 6)
        self.assertIn("never unique information delivered", block["definitions"]["gross"])
        self.assertIn("not information delivered", block["definitions"]["entropy_change"])

    def test_null_manipulation_checks_present(self):
        checks = self.doc["null_manipulation_checks"]
        self.assertEqual(checks["events_with_real_minus_null"], 17)
        self.assertEqual(checks["real_below_null_events"], 17)
        self.assertIn("null is excluded from the primary", checks["scope"])


if __name__ == "__main__":
    unittest.main()
