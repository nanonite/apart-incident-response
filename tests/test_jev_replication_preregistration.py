import contextlib
import copy
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import jev_replication_preregistration as rep


REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = REPO_ROOT / rep.AUDIT_PATH
REGISTRATION_PATH = REPO_ROOT / rep.REGISTRATION_PATH
AUDIT = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
REGISTRATION = json.loads(REGISTRATION_PATH.read_text(encoding="utf-8"))


def render(document) -> str:
    return json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n"


def parse_docs(output: str) -> list:
    decoder = json.JSONDecoder()
    index, docs = 0, []
    while index < len(output):
        while index < len(output) and output[index] in " \n\t\r":
            index += 1
        if index >= len(output):
            break
        document, index = decoder.raw_decode(output, index)
        docs.append(document)
    return docs


class FrozenInputsTestCase(unittest.TestCase):
    def setUp(self):
        self.audit_sha = hashlib.sha256(AUDIT_PATH.read_bytes()).hexdigest()
        self.registration_sha = hashlib.sha256(REGISTRATION_PATH.read_bytes()).hexdigest()
        self.live_paths = [REPO_ROOT / path for path in
                           (rep.COLLECTION_JOURNAL, rep.COLLECTION_REPORT,
                            rep.REPLAY_JOURNAL, rep.REPLAY_REPORT)]
        self.live_before = [path.exists() for path in self.live_paths]

    def tearDown(self):
        self.assertEqual(hashlib.sha256(AUDIT_PATH.read_bytes()).hexdigest(),
                         self.audit_sha, "the audit artifact changed")
        self.assertEqual(hashlib.sha256(REGISTRATION_PATH.read_bytes()).hexdigest(),
                         self.registration_sha, "the registration artifact changed")
        self.assertEqual([path.exists() for path in self.live_paths], self.live_before,
                         "a live output path changed state")
        for path in self.live_paths:
            self.assertFalse(path.exists(),
                             "a replication live output must never appear offline")


class SelectionTests(FrozenInputsTestCase):
    def test_selection_is_reproducible(self):
        first = rep.select_family()
        second = rep.select_family()
        self.assertEqual(first, second)
        self.assertEqual(first["selected_family"], "hypothesis")

    def test_rule_is_alphabetical_over_non_planning_families(self):
        selection = rep.select_family()
        self.assertNotIn("planning", selection["candidates_in_rule_order"])
        self.assertEqual(selection["candidates_in_rule_order"],
                         sorted(rep.NON_PLANNING_FAMILIES))
        self.assertEqual(selection["candidates_in_rule_order"][0], "hypothesis")
        self.assertIn("planning", selection["excluded_families"])

    def test_selection_is_outcome_blind_and_not_a_prior(self):
        selection = rep.select_family()
        self.assertIs(selection["outcome_blind"], True)
        self.assertEqual(selection["consulted_prior_live_outcomes"], [])
        statement = selection["anti_prior_statement"]
        self.assertIn("planning-low estimate and p-value are not used as a prior", statement)
        self.assertIn("effect-size guarantee", statement)

    def test_structural_preconditions_hold_for_the_selected_family(self):
        evaluation = rep.structural_preconditions(
            "hypothesis", base=rep.SEED_SCAN_BASE, window=64)
        self.assertTrue(evaluation["eligible"])
        self.assertTrue(evaluation["closed_finite_solution_set"])
        self.assertTrue(evaluation["finalizer_needs_peer"])
        self.assertGreater(evaluation["informative_b_owned_claims"], 0)
        self.assertEqual(evaluation["b_clues_per_instance"], 1)

    def test_planning_is_not_a_candidate(self):
        self.assertNotIn("planning", rep.NON_PLANNING_FAMILIES)
        self.assertIn("planning", rep.EXCLUDED_FAMILIES)


class FormCapacityTests(FrozenInputsTestCase):
    def test_audit_form_ids_are_reproducible(self):
        rebuilt = rep.build_form_audit(REPO_ROOT)
        self.assertEqual(rebuilt["form_capacity"]["form_ids"],
                         AUDIT["form_capacity"]["form_ids"])
        self.assertEqual(rebuilt["form_capacity"]["form_set_hash"],
                         AUDIT["form_capacity"]["form_set_hash"])
        self.assertEqual(rebuilt["audit_content_hash"], AUDIT["audit_content_hash"])

    def test_audit_file_is_byte_reproducible(self):
        self.assertEqual(AUDIT_PATH.read_text(encoding="utf-8"),
                         render(rep.build_form_audit(REPO_ROOT)))

    def test_form_space_is_closed(self):
        capacity = AUDIT["form_capacity"]
        self.assertEqual(capacity["space"], "closed")
        self.assertIs(capacity["closed"], True)
        self.assertEqual(capacity["primary_distinct_forms"], 4)
        self.assertEqual(capacity["k_max"], 4)
        self.assertEqual(capacity["new_forms_in_closure_probe"], 0)
        self.assertEqual(capacity["primary_growth_checkpoints"],
                         [[32, 4], [64, 4], [128, 4], [256, 4], [512, 4]])

    def test_form_space_status_closed_and_open_branches(self):
        forms = AUDIT["form_capacity"]["form_ids"]
        self.assertEqual(rep.form_space_status(forms, forms), "closed")
        self.assertEqual(rep.form_space_status(forms, forms[:2]), "closed")
        self.assertEqual(rep.form_space_status(forms, forms + ["0" * 64]), "open")
        self.assertEqual(rep.form_space_status([], ["0" * 64]), "open")

    def test_closure_probe_is_a_separate_disjoint_window(self):
        windows = AUDIT["windows"]
        self.assertEqual(windows["primary"]["base"], rep.SEED_SCAN_BASE)
        self.assertEqual(windows["closure_probe"]["base"], rep.CLOSURE_PROBE_BASE)
        self.assertEqual(windows["confirmation"]["base"], rep.CONFIRMATION_SCAN_BASE)
        self.assertNotEqual(windows["primary"]["base"], windows["closure_probe"]["base"])
        self.assertIn("no seed may be selected", windows["closure_probe"]["role"])

    def test_prompt_form_id_derives_from_structure_only(self):
        instance = rep.instance_for("hypothesis", rep.SEED_SCAN_BASE)
        form = rep.pre_read_form_id(instance)
        self.assertEqual(len(form), 64)
        self.assertIn(form, AUDIT["form_capacity"]["form_ids"])
        self.assertEqual(rep.pre_read_form_id(instance), form, "form id must be stable")
        self.assertEqual(rep._instance_id("hypothesis", rep.SEED_SCAN_BASE),
                         instance.instance_id)


class DisjointnessTests(FrozenInputsTestCase):
    def test_selected_seeds_never_overlap_a_documented_prior_range(self):
        prior = set()
        for low, high in rep.PRIOR_SEED_RANGES:
            prior.update(range(low, high + 1))
        for seed in AUDIT["disjointness"]["selected_seeds"]:
            self.assertNotIn(seed, prior)
        for window in ("primary", "closure_probe", "confirmation"):
            base = AUDIT["windows"][window]["base"]
            end = AUDIT["windows"][window]["end"]
            for low, high in rep.PRIOR_SEED_RANGES:
                self.assertTrue(end < low or high < base,
                                f"{window} overlaps prior range ({low}, {high})")

    def test_selected_ids_are_disjoint_from_prior_artifacts(self):
        disjoint = AUDIT["disjointness"]
        self.assertEqual(disjoint["selected_ids_overlapping_prior"], [])
        self.assertEqual(disjoint["primary_vs_confirmation_overlap"], [])
        self.assertIs(disjoint["disjoint_from_all_prior_artifacts"], True)
        self.assertGreater(disjoint["prior_instance_id_count"], 0)
        self.assertEqual(len(disjoint["prior_instance_ids_sha256"]), 64)
        self.assertGreater(len(disjoint["prior_sources"]), 0)

    def test_blocks_are_disjoint_from_each_other(self):
        primary = {entry["instance_id"] for entry in AUDIT["blocks"]["primary"]["manifest"]}
        confirmation = {entry["instance_id"]
                        for entry in AUDIT["blocks"]["confirmation"]["manifest"]}
        self.assertEqual(len(primary), rep.BLOCK_N)
        self.assertEqual(len(confirmation), rep.BLOCK_N)
        self.assertEqual(primary & confirmation, set())

    def test_fixed_n_selection_uses_no_outcome_based_stopping(self):
        self.assertIn("no outcome-based stopping", AUDIT["blocks"]["selection_rule"])
        for block in ("primary", "confirmation"):
            membership = AUDIT["blocks"][block]["form_membership"]
            self.assertEqual(len(membership), 4)
            for form, ids in membership.items():
                self.assertEqual(len(ids), rep.INSTANCES_PER_FORM, form)
            self.assertEqual(sum(len(v) for v in membership.values()), rep.BLOCK_N)


class ManifestHashTests(FrozenInputsTestCase):
    def test_manifest_hashes_are_stable(self):
        rebuilt = rep.build_form_audit(REPO_ROOT)
        for block in rep.BLOCKS:
            with self.subTest(block=block):
                self.assertEqual(rebuilt["blocks"][block]["manifest_hash"],
                                 AUDIT["blocks"][block]["manifest_hash"])
                self.assertEqual(rebuilt["blocks"][block]["manifest"],
                                 AUDIT["blocks"][block]["manifest"])

    def test_registration_reproduces_byte_for_byte(self):
        rebuilt = rep.build_registration(REPO_ROOT, audit=AUDIT)
        self.assertEqual(REGISTRATION_PATH.read_text(encoding="utf-8"), render(rebuilt))
        self.assertEqual(REGISTRATION["preregistration_hash"],
                         rebuilt["preregistration_hash"])
        payload = json.dumps({k: v for k, v in REGISTRATION.items()
                              if k != "preregistration_hash"}, sort_keys=True)
        self.assertEqual(hashlib.sha256(payload.encode()).hexdigest(),
                         REGISTRATION["preregistration_hash"])

    def test_treatment_and_geometry_hashes_reproduce(self):
        self.assertEqual(REGISTRATION["information_geometry_hash"],
                         AUDIT["instance_geometry"]["information_geometry_hash"])
        self.assertEqual(REGISTRATION["manifest_treatment_hash"],
                         rep.manifest_treatment_hash(AUDIT))
        self.assertEqual(REGISTRATION["treatment_hash"],
                         rep.replication_treatment_hash(
                             manifest_treatment=REGISTRATION["manifest_treatment_hash"],
                             geometry=REGISTRATION["information_geometry_hash"],
                             prompt_hash=REGISTRATION["treatment"]["writer_prompt"]["prompt_hash"]))
        self.assertEqual(REGISTRATION["audit_binding"]["audit_content_hash"],
                         AUDIT["audit_content_hash"])

    def test_branch_hashes_recompute_exactly(self):
        geometry_rows = AUDIT["instance_geometry"]["rows"]
        self.assertGreater(len(geometry_rows), 0)
        family = REGISTRATION["family"]
        for row in geometry_rows[:3]:
            instance = rep.instance_for(family, row["seed"])
            hashes = rep.branch_hashes(instance, row["real_claim"], row["placebo_claim"])
            self.assertEqual(len(hashes["pre_read_request_body_hash"]), 64)
            self.assertEqual(len(hashes["pre_read_state_hash"]), 64)
            self.assertEqual(set(hashes["branch_request_hashes"]), {"real", "placebo", "null"})
            self.assertEqual(set(hashes["branch_state_hashes"]), {"real", "placebo", "null"})
            for value in list(hashes["branch_request_hashes"].values()) \
                    + list(hashes["branch_state_hashes"].values()):
                self.assertEqual(len(value), 64)


class MultiplicityTests(FrozenInputsTestCase):
    def test_holm_rule_and_frozen_family_set(self):
        multiplicity = REGISTRATION["multiplicity"]
        self.assertIn("Holm", multiplicity["family_level_control"])
        self.assertIs(multiplicity["family_set_frozen_before_outcomes"], True)
        self.assertEqual(multiplicity["registered_family_set"], ["hypothesis"])
        self.assertEqual(multiplicity["registered_family_count"], 1)
        self.assertIn("Holm-adjusted p equals the raw p",
                      multiplicity["single_family_reduction"])

    def test_no_post_hoc_sweep_or_winner(self):
        forbidden = " ".join(REGISTRATION["multiplicity"]["forbidden"])
        self.assertIn("sweeping families and selecting a winner post hoc", forbidden)
        self.assertIn("adding a family after outcomes are visible", forbidden)
        self.assertIn("removing a registered family after outcomes are visible", forbidden)

    def test_fresh_seed_confirmation_is_required(self):
        confirmation = REGISTRATION["multiplicity"]["confirmation"]
        self.assertIs(confirmation["required_before_any_claim"], True)
        self.assertEqual(confirmation["block"], "confirmation")
        self.assertEqual(confirmation["n"], rep.BLOCK_N)
        self.assertIs(confirmation["may_not_pool_with_primary_for_primary_estimate"], True)
        self.assertEqual(confirmation["seed_window"]["base"], rep.CONFIRMATION_SCAN_BASE)

    def test_minimum_form_rule_and_five_form_fallback(self):
        plan = REGISTRATION["inference_plan"]
        self.assertEqual(plan["minimum_forms_for_confirmatory"], 5)
        self.assertIn("interval-only", plan["five_form_fallback"])
        self.assertIn("0.05 is forbidden", plan["five_form_fallback"])
        self.assertIn("replay-coverage failure", plan["missingness"]["below_five_forms"])
        self.assertEqual(plan["attainable_two_sided_floor_by_k"],
                         {"4": "0.125", "5": "0.0625", "6": "0.03125"})

    def test_k4_finding_is_recorded_honestly(self):
        plan = REGISTRATION["inference_plan"]
        self.assertEqual(plan["k_max_from_audit"], 4)
        self.assertIn("closed at k = 4", plan["audit_finding"])
        self.assertIn("no dichotomous rejection", plan["audit_finding"])
        self.assertIn("estimation and descriptive study", plan["consequence"])

    def test_mde_is_illustrative_and_not_a_prior(self):
        mde = REGISTRATION["inference_plan"]["mde"]
        self.assertAlmostEqual(mde["illustrative_sd_bits"], 0.1933, places=4)
        self.assertIn("illustrative sensitivity only", mde["illustrative_sd_source"])
        self.assertIn("not used as a prior", mde["not_a_prior"])
        self.assertIsNotNone(mde["illustrative_mde_bits"])

    def test_non_claims_include_every_prohibited_claim(self):
        text = " ".join(REGISTRATION["non_claims"])
        for phrase in ("no population-level claim", "no cross-family claim",
                       "no calibration claim", "no instance-level claim",
                       "no unique-information claim",
                       "no use of the planning-low estimate or p-value as a prior",
                       "no post-hoc family sweep or winner selection"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)


class DesignFreezeTests(FrozenInputsTestCase):
    def test_treatment_is_the_original_l4x_communication_treatment(self):
        treatment = REGISTRATION["treatment"]
        self.assertEqual(treatment["family"], "hypothesis")
        self.assertEqual(treatment["complexity"], "low")
        self.assertEqual(treatment["regime"], "N")
        self.assertEqual(treatment["agents"], ["A", "B"])
        self.assertEqual(treatment["turns"], 2)
        self.assertEqual(treatment["primary_direction"], "one-way B->A")
        prompt = treatment["writer_prompt"]
        self.assertEqual(prompt["prompt_schema_version"], "treatment-prompt-v2")
        self.assertEqual(prompt["seed_behavior"]["algorithm"], "sha256-truncated-signed31-v1")
        self.assertEqual(prompt["max_tokens"], 1024)
        self.assertEqual(prompt["temperature"], 0.0)
        writer = treatment["writer_transport"]
        self.assertEqual(writer["model"], "inclusionai/ling-3.0-flash-vl")
        self.assertEqual(writer["min_attempt_interval_seconds"], 3.25)
        self.assertEqual(writer["max_retries"], 2)

    def test_branches_and_authoritative_checks_frozen(self):
        branches = REGISTRATION["branches"]
        self.assertEqual(branches["modes"], ["real", "placebo", "null"])
        self.assertEqual(branches["envelope"], "peer_clue: {claim}")
        self.assertEqual(branches["placebo_origin"], "controller")
        block = REGISTRATION["authoritative_checks"]
        checks = " ".join(list(block)
                          + [str(value) for value in block.values()])
        for phrase in ("holds_claim", "board_write", "peer_read_exposure",
                       "delta_i_bits", "receiver_known", "deduplication"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, checks)

    def test_estimand_and_inference_freeze(self):
        estimand = REGISTRATION["estimand"]
        self.assertEqual(estimand["experimental_unit"], "prompt form")
        self.assertIn("equal-weight mean", estimand["primary"])
        self.assertEqual(estimand["directional_prediction"], "Delta < 0")
        self.assertIs(estimand["events_are_independent_units"], False)
        plan = REGISTRATION["inference_plan"]
        self.assertIn("sign-flip", plan["primary_test"])
        self.assertIn("form-mean t interval", plan["interval"])
        self.assertEqual(plan["imputation"], "never impute missing pairs")
        self.assertEqual(plan["guards"]["target_probability_delta"], 0.0)
        self.assertEqual(plan["guards"]["feasible_set_mass_epsilon"], 0.01)
        self.assertIn("never used to filter", plan["guards"]["reporting"])

    def test_operational_settings_frozen(self):
        operations = REGISTRATION["operational_settings"]
        jev = operations["jev"]
        self.assertEqual(jev["model"], "jev-1.13.0")
        self.assertEqual(jev["endpoint"], "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(jev["codec_version"], "jev-choice-wire-v2")
        self.assertEqual(jev["max_retries"], 2)
        self.assertEqual(jev["retryable_statuses"], [408, 429, 500, 502, 503, 504, 529])
        ling = operations["ling"]
        self.assertEqual(ling["model"], "inclusionai/ling-3.0-flash-vl")
        self.assertEqual(ling["endpoint"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(ling["key_loader"], "behavioral_discovery._api_key")
        self.assertEqual(operations["normalization"]["policy_hash"],
                         "292ac217f1cf54083252e6363a16a48596daab72a8ca06d4569c20f861b7e1e9")
        lifecycle = operations["output_lifecycle"]
        self.assertIs(lifecycle["fresh_paths"], True)
        for flag in ("resume", "append", "overwrite", "path_overrides"):
            self.assertIs(lifecycle[flag], False)

    def test_partitions_retries_and_caps(self):
        caps = REGISTRATION["operational_settings"]["caps"]
        collection, replay, program = caps["collection"], caps["replay"], caps["program"]
        self.assertEqual(collection["planned"]["ling"], 128)
        self.assertEqual(collection["physical"]["ling"], 384)
        self.assertEqual(collection["planned"]["jev"], 32)
        self.assertEqual(collection["physical"]["jev"], 96)
        self.assertEqual(replay["planned"]["jev"], 96)
        self.assertEqual(replay["physical"]["jev"], 288)
        self.assertEqual(replay["planned"]["ling"], 0)
        self.assertEqual(program["physical"]["combined"], 768)
        self.assertLessEqual(collection["worst_case_cost_usd"], collection["cost_ceiling_usd"])
        self.assertLessEqual(replay["worst_case_cost_usd"], replay["cost_ceiling_usd"])
        self.assertLessEqual(program["worst_case_cost_usd"], program["cost_ceiling_usd"])
        self.assertAlmostEqual(caps["cost_model"]["ling_worst_physical_call_usd"],
                               0.00067584, places=12)
        self.assertAlmostEqual(caps["cost_model"]["jev_worst_physical_call_usd"],
                               0.000344064, places=12)

    def test_terminal_stops_registered(self):
        stops = " ".join(REGISTRATION["operational_settings"]["terminal_stops"])
        for phrase in ("cost cap", "model drift", "protocol-key drift", "option-mismatched",
                       "hard normalization", "argmax shift", "output collision",
                       "hash drift", "two consecutive terminal provider failures"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, stops)

    def test_outputs_are_fresh_and_reserved(self):
        outputs = REGISTRATION["outputs"]
        self.assertEqual(outputs["collection_journal"], str(rep.COLLECTION_JOURNAL))
        self.assertEqual(outputs["replay_journal"], str(rep.REPLAY_JOURNAL))
        for key in ("collection_journal", "collection_report",
                    "replay_journal", "replay_report"):
            self.assertFalse((REPO_ROOT / outputs[key]).exists(), key)
            self.assertIn(outputs[key], rep.OWNED_PATHS)


class AuthorizationTests(FrozenInputsTestCase):
    def test_registration_is_draft_and_not_authorizing(self):
        self.assertEqual(REGISTRATION["status"], "draft_pending_review")
        self.assertIs(REGISTRATION["approval_required"], True)
        self.assertIs(REGISTRATION["approval"]["approved"], False)
        self.assertIs(REGISTRATION["lock_does_not_imply_approval"], True)
        self.assertIs(REGISTRATION["live_collection_authorized"], False)
        self.assertIs(REGISTRATION["lock_is_not_live_authorization"], True)
        authorization = REGISTRATION["operational_settings"]["authorization"]
        self.assertIs(authorization["separate_live_authorization_required_after_locking"], True)
        self.assertIs(authorization["approval_may_not_be_inferred_from_locking"], True)
        self.assertIn("separate explicit live authorization",
                      " ".join(REGISTRATION["pending_review"]))

    def test_verification_flags_approval_must_be_supplied(self):
        result = rep.verify_registration(REGISTRATION, repo_root=REPO_ROOT,
                                         audit_document=AUDIT, check_credentials=False)
        self.assertTrue(result["ok"], result["errors"])
        names = {check["check"] for check in result["checks"]}
        self.assertIn("approval_not_inferred_from_locking", names)
        self.assertIn("status_is_draft", names)
        self.assertFalse(result["live_collection_authorized"])


class TamperTests(FrozenInputsTestCase):
    def _verify(self, document):
        return rep.verify_registration(document, repo_root=REPO_ROOT,
                                       audit_document=AUDIT, check_credentials=False)

    def test_lock_flag_flip_rejected(self):
        tampered = copy.deepcopy(REGISTRATION)
        tampered["live_collection_authorized"] = True
        result = self._verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("approval_not_inferred_from_locking", result["failed"])

    def test_approval_flip_rejected(self):
        tampered = copy.deepcopy(REGISTRATION)
        tampered["approval"]["approved"] = True
        tampered["approval"]["approved_by"] = "someone"
        result = self._verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("approval_not_inferred_from_locking", result["failed"])

    def test_status_flip_to_locked_rejected(self):
        tampered = copy.deepcopy(REGISTRATION)
        tampered["status"] = rep.LOCKED_STATUS
        result = self._verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("status_is_draft", result["failed"])

    def test_stale_registration_hash_rejected(self):
        tampered = copy.deepcopy(REGISTRATION)
        tampered["preregistration_hash"] = "0" * 64
        result = self._verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue([e for e in result["errors"]
                         if e.startswith("registration_hash_matches")])

    def test_family_swap_rejected(self):
        tampered = copy.deepcopy(REGISTRATION)
        tampered["family"] = "poetry"
        result = self._verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("family_matches_selection_rule", result["failed"])

    def test_cap_tamper_rejected(self):
        tampered = copy.deepcopy(REGISTRATION)
        tampered["operational_settings"]["caps"]["program"]["cost_ceiling_usd"] = 100.0
        result = self._verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue([e for e in result["errors"]
                         if e.startswith("registration_content_matches")])

    def test_manifest_hash_tamper_rejected(self):
        tampered = copy.deepcopy(REGISTRATION)
        tampered["manifests"]["primary"]["manifest_hash"] = "0" * 64
        result = self._verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("manifest_hashes_match_audit", result["failed"])

    def test_audit_binding_tamper_rejected(self):
        tampered = copy.deepcopy(REGISTRATION)
        tampered["audit_binding"]["form_set_hash"] = "0" * 64
        result = self._verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("audit_form_set_hash_matches", result["failed"])

    def test_mixed_protocol_key_rejected(self):
        tampered = copy.deepcopy(REGISTRATION)
        tampered["operational_settings"]["jev"]["protocol_key"] = "jev-choice-wire-v1|deadbeef"
        result = self._verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("no_mixed_protocol_keys", result["failed"])
        self.assertIn("jev_pins", result["failed"])

    def test_minimum_form_rule_tamper_rejected(self):
        tampered = copy.deepcopy(REGISTRATION)
        tampered["inference_plan"]["minimum_forms_for_confirmatory"] = 1
        result = self._verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("minimum_form_rule_and_five_form_fallback", result["failed"])


class OfflineCliTests(FrozenInputsTestCase):
    def run_cli(self, argv):
        buffer = io.StringIO()
        calls = []

        def explode(*args, **kwargs):
            calls.append(1)
            raise AssertionError("provider call attempted offline")

        with patch("urllib.request.urlopen", explode):
            with contextlib.redirect_stdout(buffer):
                rc = rep.main(argv)
        return rc, buffer.getvalue(), calls

    def test_offline_verification_is_call_free(self):
        rc, output, calls = self.run_cli(["--repo-root", str(REPO_ROOT)])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        docs = parse_docs(output)
        self.assertTrue(docs[0]["ok"], docs[0]["failed"])
        self.assertEqual(docs[0]["failed"], [])
        self.assertIn("no provider call made", docs[1]["note"])
        self.assertIs(docs[1]["lock_does_not_imply_approval"], True)

    def test_live_without_approval_makes_zero_calls(self):
        rc, output, calls = self.run_cli(["--repo-root", str(REPO_ROOT), "--live"])
        self.assertEqual(rc, 2)
        self.assertEqual(calls, [])
        blocked = parse_docs(output)[0]
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["stop_reason"], "missing_approval")
        self.assertEqual(blocked["provider_calls"], 0)

    def test_live_with_approval_is_still_refused_while_draft(self):
        rc, output, calls = self.run_cli(["--repo-root", str(REPO_ROOT), "--live",
                                          "--approval", "some-reference"])
        self.assertEqual(rc, 2)
        self.assertEqual(calls, [])
        blocked = parse_docs(output)[-1]
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["stop_reason"],
                         "draft_registration_requires_reviewer_lock_and_a_separate_live_"
                         "authorization_reference")
        self.assertEqual(blocked["provider_calls"], 0)
        self.assertIs(blocked["live_collection_authorized"], False)

    def test_failed_preflight_makes_zero_calls_and_writes_nothing(self):
        with tempfile.TemporaryDirectory(prefix="replication-preflight-") as directory:
            root = Path(directory)
            target = root / rep.REGISTRATION_PATH
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REGISTRATION_PATH, target)
            rc, output, calls = self.run_cli(["--repo-root", str(root), "--live",
                                              "--approval", "some-reference"])
            self.assertEqual(rc, 2)
            self.assertEqual(calls, [])
            verification = parse_docs(output)[0]
            self.assertFalse(verification["ok"])
            self.assertTrue(verification["failed"])
            written = [path for path in root.rglob("*") if path.is_file() and path != target]
            self.assertEqual(written, [])

    def test_write_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="replication-lock-") as directory:
            root = Path(directory)
            rep.write_audit(AUDIT, repo_root=root)
            with self.assertRaises(FileExistsError):
                rep.write_audit(AUDIT, repo_root=root)
            rep.write_registration(REGISTRATION, repo_root=root)
            with self.assertRaises(FileExistsError):
                rep.write_registration(REGISTRATION, repo_root=root)
            self.assertEqual((root / rep.AUDIT_PATH).read_text(encoding="utf-8"),
                             render(AUDIT))


if __name__ == "__main__":
    unittest.main()
