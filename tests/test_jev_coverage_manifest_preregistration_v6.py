import copy
import hashlib
import inspect
import json
import math
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from apart_incident_response import behavioral_discovery as bd
from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_choice_v2 as jc2
from apart_incident_response import jev_coverage_manifest_preregistration_v6 as reg
from apart_incident_response import jev_ling_writer_v3 as writer_v3
from apart_incident_response import jev_replay_preregistration as pr
from apart_incident_response import jev_six_form_coverage_audit as audit
from apart_incident_response import task_families as tf
from apart_incident_response.communication_protocol import DependenceRegime, ReasoningComplexity


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = REPO_ROOT / "runs" / "epic-126" / "jev-coverage-manifest-preregistration-v6.json"


def load_locked() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def verify(document, **kwargs):
    return reg.verify_against_coverage_manifest_preregistration_v6(document, **kwargs)


class ManifestSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_locked()
        cls.manifest = cls.document["manifest"]

    def test_deterministic_manifest_reproduction(self):
        first_meta, first_instances = reg.select_form_balanced_manifest()
        second_meta, second_instances = reg.select_form_balanced_manifest()
        self.assertEqual(first_meta, second_meta)
        self.assertEqual([i.instance_id for i in first_instances],
                         [i.instance_id for i in second_instances])
        self.assertEqual(reg.build_coverage_manifest_preregistration_v6(approved=True),
                         reg.build_coverage_manifest_preregistration_v6(approved=True))

    def test_exactly_36_unique_ids(self):
        ids = self.manifest["instance_ids"]
        self.assertEqual(len(ids), 36)
        self.assertEqual(len(set(ids)), 36)
        self.assertEqual(self.manifest["n"], 36)
        self.assertTrue(all(instance_id.startswith("planning-") for instance_id in ids))
        seeds = self.manifest["instance_seeds"]
        self.assertEqual(seeds, sorted(seeds))
        self.assertTrue(all(reg.SEED_SCAN_BASE <= seed <= reg.SEED_SCAN_END for seed in seeds))

    def test_six_ids_in_each_exact_frozen_form(self):
        membership = self.manifest["form_membership"]
        self.assertEqual(set(membership), set(reg.FROZEN_FORM_IDS))
        self.assertEqual(len(reg.FROZEN_FORM_IDS), 6)
        self.assertEqual(set(self.manifest["iso_form_ids"]), set(reg.FROZEN_FORM_IDS))
        self.assertEqual(sorted(pr.frozen_forms()["iso_form_ids"]), sorted(reg.FROZEN_FORM_IDS))
        audit_document = json.loads(
            (REPO_ROOT / reg.DEFAULT_AUDIT_V1).read_text(encoding="utf-8"))
        audit_forms = sorted(row["prompt_form_id"] for row in audit_document["forms"])
        self.assertEqual(audit_forms, sorted(reg.FROZEN_FORM_IDS))
        for form, ids in membership.items():
            with self.subTest(form=form):
                self.assertEqual(len(ids), 6)
                self.assertEqual(self.manifest["form_counts"][form], 6)
        seen = set()
        for form, ids in membership.items():
            for instance_id in ids:
                self.assertNotIn(instance_id, seen)
                seen.add(instance_id)
                seed = int(instance_id.split("-")[1], 16)
                instance = tf.generate_instance("planning", seed, DependenceRegime.N,
                                                ReasoningComplexity.LOW)
                self.assertEqual(instance.instance_id, instance_id)
                recomputed = audit.pre_read_form_ids([instance])[instance_id]
                self.assertEqual(recomputed, form)
        self.assertEqual(seen, set(self.manifest["instance_ids"]))

    def test_disjoint_from_all_prior_manifests(self):
        ids = set(self.manifest["instance_ids"])
        prior = set(reg._prior_id_set(REPO_ROOT))
        self.assertEqual(ids & prior, set())
        disjointness = self.manifest["disjointness"]
        self.assertTrue(disjointness["ok"])
        self.assertEqual(disjointness["overlap"], [])
        evidence = disjointness["prior_instance_ids"]
        self.assertEqual(evidence["instance_id_count"], len(prior))
        self.assertEqual(evidence["instance_ids_sha256"], hashlib.sha256(
            json.dumps(sorted(prior), sort_keys=True).encode()).hexdigest())
        # frozen 17-instance L4X block, planning-low manifest, J3, smoke/pilot blocks
        frozen17 = {f"planning-{seed:08x}" for seed in range(72000, 72017)}
        manifest70k = {f"planning-{seed:08x}" for seed in range(70000, 70017)}
        capability71k = {f"planning-{seed:08x}" for seed in range(71000, 71017)}
        self.assertFalse(ids & frozen17)
        self.assertFalse(ids & manifest70k)
        self.assertFalse(ids & capability71k)
        self.assertTrue(frozen17 <= prior and manifest70k <= prior and capability71k <= prior)

    def test_selection_inputs_are_offline_form_identity_only(self):
        self.assertEqual(len(inspect.signature(reg.select_form_balanced_manifest).parameters), 0)
        source = (inspect.getsource(reg.scan_window)
                  + inspect.getsource(reg.select_form_balanced_manifest))
        for forbidden in ("runs/", ".jsonl", "probabilities", "eligible_exposure",
                          "bridge-v5", "report"):
            self.assertNotIn(forbidden, source)
        meta, _ = reg.select_form_balanced_manifest()
        self.assertIn("form identity only", meta["scan"]["inputs"])
        self.assertIn("no model outcomes", meta["scan"]["inputs"])

    def test_manifest_hash_stability(self):
        ids = self.manifest["instance_ids"]
        expected = hashlib.sha256(json.dumps(ids, sort_keys=True).encode()).hexdigest()
        self.assertEqual(self.manifest["manifest_hash"], expected)
        self.assertEqual(self.manifest["form_manifest_hash"], hashlib.sha256(
            json.dumps(sorted(reg.FROZEN_FORM_IDS), sort_keys=True).encode()).hexdigest())
        self.assertEqual(reg.build_coverage_manifest_preregistration_v6(approved=True)
                         ["manifest"]["manifest_hash"], expected)


class TreatmentBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_locked()
        cls.generator = cls.document["generator"]
        cls.selection, cls.instances = reg.select_form_balanced_manifest()

    def test_source_treatment_geometry_binding_recomputes(self):
        self.assertEqual(self.generator["source_files_hash"],
                         reg._source_files_hash(REPO_ROOT))
        self.assertEqual(self.generator["source_files"], list(reg.COVERAGE_SOURCE_FILES))
        form_of = {instance_id: form
                   for form, ids in self.document["manifest"]["form_membership"].items()
                   for instance_id in ids}
        instances = {instance.instance_id: instance for instance in self.instances}
        ordered = [instances[instance_id]
                   for instance_id in self.document["manifest"]["instance_ids"]]
        self.assertEqual(self.generator["manifest_treatment_hash"],
                         reg.manifest_treatment_hash(ordered, form_of))
        self.assertEqual(self.generator["information_geometry_hash"],
                         audit.information_geometry_hash(ordered))
        self.assertEqual(self.generator["treatment_hash"],
                         reg.treatment_hash_v6(
                             manifest_treatment=self.generator["manifest_treatment_hash"],
                             information_geometry=self.generator["information_geometry_hash"],
                             prompt_hash=self.document["treatment"]["writer_prompt"]["prompt_hash"]))
        self.assertEqual(len(self.generator["source_files_hash"]), 64)
        self.assertEqual(len(self.generator["manifest_treatment_hash"]), 64)
        self.assertEqual(len(self.generator["information_geometry_hash"]), 64)

    def test_geometry_matches_frozen_log2_3_for_every_instance(self):
        for instance in self.instances:
            for clue in instance.private_clues.get("B", ()):
                info = instance.information("A", clue, "m-test")
                with self.subTest(instance=instance.instance_id):
                    self.assertEqual(info.status, "accepted")
                    self.assertAlmostEqual(info.delta_i_bits, math.log2(3))
                    self.assertEqual((info.before_count, info.after_count), (3, 1))

    def test_treatment_binds_original_comm_bridge(self):
        treatment = self.document["treatment"]
        self.assertEqual(treatment["mode"], "exact-original-comm-bridge-v5")
        self.assertEqual(treatment["family"], "planning")
        self.assertEqual(treatment["complexity"], "low")
        self.assertEqual(treatment["regime"], "N")
        self.assertEqual(treatment["agents"], ["A", "B"])
        self.assertEqual(treatment["turns"], 2)
        self.assertEqual(treatment["token_budget"], 1024)
        self.assertEqual(treatment["seed_algorithm"], bd.PROVIDER_SEED_ALGORITHM)
        self.assertEqual(treatment["primary_direction"], "one-way B->A")
        self.assertEqual(treatment["final_receiver"], "A via Jev Choice wire v2")
        self.assertEqual(treatment["exposure_id"], "jev-finalizer")
        prompt = treatment["writer_prompt"]
        self.assertEqual(prompt["prompt_schema_version"], bd.PROMPT_SCHEMA_VERSION)
        self.assertEqual(prompt["prompt_fields"], list(bd.TREATMENT_PROMPT_FIELDS))
        self.assertIn("treatment_prompt", prompt["path"])
        self.assertIn("ANSWER:", prompt["output_grammar"])
        self.assertEqual(prompt["temperature"], 0.0)
        self.assertEqual(prompt["max_tokens"], 1024)
        self.assertEqual(prompt["seed_behavior"]["algorithm"], bd.PROVIDER_SEED_ALGORITHM)
        self.assertEqual(treatment["writer_transport"], writer_v3.writer_transport_spec())
        self.assertEqual(treatment["writer_transport"]["min_attempt_interval_seconds"], 3.25)
        self.assertEqual(treatment["writer_transport"]["max_retries"], pr.LING_MAX_RETRIES)
        self.assertIn("peer-only", treatment["visibility"])
        self.assertIn("holds_claim", treatment["ownership"])

    def test_protocol_bindings(self):
        protocol = self.document["model_and_protocol"]
        self.assertEqual(protocol["model"], pr.JEV_REPLAY_MODEL)
        self.assertEqual(protocol["endpoint"], pr.JEV_REPLAY_ENDPOINT)
        self.assertEqual(protocol["codec_version"], jc2.JEV_CHOICE_V2_CODEC_VERSION)
        self.assertEqual(protocol["protocol_key"], reg.protocol_key_v6())
        self.assertTrue(jc2.is_jev_v2_protocol_key(protocol["protocol_key"]))
        self.assertFalse(jc.is_jev_protocol_key(protocol["protocol_key"]))
        self.assertEqual(protocol["retryable_statuses"], sorted(jc.JEV_RETRYABLE_STATUSES))
        self.assertEqual(protocol["ling_model"], pr.LING_MODEL)
        self.assertEqual(protocol["ling_endpoint"], pr.LING_ENDPOINT)


class DesignContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_locked()

    def test_fixed_n_and_no_outcome_stopping(self):
        design = self.document["coverage_design"]
        self.assertTrue(design["fixed_n"])
        self.assertEqual(design["n"], 36)
        self.assertEqual(design["instances_per_form"], 6)
        self.assertEqual(design["forms"], 6)
        self.assertTrue(design["no_stopping_after_first_message"])
        self.assertTrue(design["no_stopping_after_form_exposure"])
        self.assertIn("no seed replacement", design["no_seed_replacement"])
        self.assertIn("never pooled", design["no_pooling_with_frozen_block"])
        self.assertEqual(design["prior_data_role"], "historical sizing context only")
        self.assertEqual(design["k"], 6)
        self.assertEqual(design["experimental_unit"], "prompt form")
        self.assertIn("cannot increase k", design["k_limit_note"])

    def test_sizing_rationale_assumption_labeled(self):
        sizing = self.document["sizing_rationale"]
        rate = sizing["historical_eligible_rate"]
        self.assertEqual((rate["numerator"], rate["denominator"]), (9, 17))
        self.assertAlmostEqual(rate["value"], 9 / 17)
        self.assertEqual(rate["rounded"], 0.529)
        one = sizing["p_one_form_ge_one"]
        all_six = sizing["p_all_six_ge_one"]
        self.assertEqual(one["expression"], "1 - (1 - 9/17)^6")
        self.assertAlmostEqual(one["value"], 1 - (1 - 9 / 17) ** 6, places=12)
        self.assertEqual(one["rounded"], 0.989)
        self.assertEqual(all_six["expression"], "[1 - (1 - 9/17)^6]^6")
        self.assertAlmostEqual(all_six["value"], (1 - (1 - 9 / 17) ** 6) ** 6, places=12)
        self.assertEqual(all_six["rounded"], 0.937)
        self.assertIn("not evidence that eligibility is independent", sizing["assumption"])
        self.assertIn("historical sizing context only", sizing["source"])

    def test_coverage_outcomes_and_eligibility_rule_frozen(self):
        outcomes = self.document["coverage_outcomes"]
        self.assertIn("release the coverage gate for #192/#193 review",
                      outcomes["six_forms_covered"])
        self.assertIn("interval-only descriptive fallback", outcomes["five_forms_covered"])
        self.assertIn("no alpha=0.05 two-sided sign-flip claim",
                      outcomes["five_forms_covered"])
        self.assertIn("fewer than five", outcomes["fewer_than_five_or_gate_failure"])
        self.assertIn("stop and report", outcomes["fewer_than_five_or_gate_failure"])
        self.assertIn("must not start #159", outcomes["collection_starts_no_159"])
        self.assertIn("#192", outcomes["decision_owner"])
        rule = self.document["eligibility_rule"]
        self.assertEqual(len(rule), 9)
        self.assertIn("receiver valid", rule)
        self.assertIn("A->B messages excluded from primary replay eligibility", rule)

    def test_evidence_requirements_cover_receiver_and_provenance(self):
        evidence = " | ".join(self.document["evidence_requirements"])
        for item in ("writer outcomes by agent and turn", "accepted/rejected board writes",
                     "authoritative I_m from A's perspective", "exposure ID",
                     "normalized and raw probability vectors", "request/state hashes",
                     "prompt_form_id", "raw_response_retained=false",
                     "credentials_retained=false"):
            self.assertIn(item, evidence)

    def test_claim_scope_rejects_k_increase(self):
        scope = self.document["claim_scope"]
        self.assertEqual(scope["forms"], 6)
        self.assertEqual(scope["n"], 36)
        self.assertIn("do not increase k beyond six", scope["statement"])
        self.assertIn("must not start #159", scope["statement"])


class CapsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_locked()
        cls.caps = cls.document["caps"]

    def test_planned_call_arithmetic_144_36_180(self):
        self.assertEqual(reg.PLANNED_LING_PER_INSTANCE, 4)
        self.assertEqual(reg.PLANNED_JEV_PER_INSTANCE, 1)
        self.assertEqual((reg.PLANNED_LING, reg.PLANNED_JEV, reg.PLANNED_REQUESTS),
                         (144, 36, 180))
        planned = self.caps["planned_calls"]
        self.assertEqual(planned["ling"], 144)
        self.assertEqual(planned["jev"], 36)
        self.assertEqual(planned["combined"], 180)
        self.assertIn("36 instances x 4 writer calls", planned["arithmetic"])
        self.assertIn("144", planned["arithmetic"])

    def test_retry_inclusive_partitions(self):
        self.assertEqual(reg.RETRY_RESERVE_FACTOR, 1 + pr.JEV_REPLAY_MAX_RETRIES)
        self.assertEqual((reg.LING_REQUEST_CAP, reg.JEV_REQUEST_CAP, reg.COMBINED_REQUEST_CAP),
                         (432, 108, 540))
        partition = self.caps["provider_partition"]
        self.assertEqual(partition["ling"], 432)
        self.assertEqual(partition["jev"], 108)
        self.assertEqual(partition["total"], 540)
        self.assertEqual(partition["jev"] + partition["ling"], partition["total"])
        self.assertEqual(self.caps["physical_requests"], 540)
        reserve = self.caps["retry_reserve"]
        self.assertEqual(reserve["per_call_max_physical_attempts"], 3)
        self.assertEqual(reserve["combined_reserve"], 360)
        self.assertLessEqual(reg.PLANNED_LING, reg.LING_REQUEST_CAP)
        self.assertLessEqual(reg.PLANNED_JEV, reg.JEV_REQUEST_CAP)
        self.assertLessEqual(reg.PLANNED_REQUESTS, reg.COMBINED_REQUEST_CAP)

    def test_cap_and_cost_consistency(self):
        self.assertEqual(self.caps["cost_cap_usd"], 1.0)
        self.assertEqual(self.caps["input_token_ceiling"], 8192)
        self.assertEqual(self.caps["input_usd_per_mtok"], 0.042)
        expected_call = round(8192 * 0.042 / 1_000_000, 12)
        self.assertEqual(self.caps["worst_case_call_cost_usd"], expected_call)
        expected_total = round(540 * expected_call, 9)
        self.assertEqual(self.caps["worst_case_cost_usd"], expected_total)
        self.assertLessEqual(expected_total, self.caps["cost_cap_usd"])
        self.assertIn("0.18579456", self.caps["worst_case_arithmetic"])
        self.assertEqual(self.caps["pacing"]["min_attempt_interval_seconds"],
                         writer_v3.LING_MIN_ATTEMPT_INTERVAL_SECONDS)
        self.assertEqual(self.caps["status"], "locked; live_collection_authorized=false")


class ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_locked()

    def test_committed_artifact_byte_reproducible(self):
        self.assertEqual(self.document,
                         reg.build_coverage_manifest_preregistration_v6(approved=True))

    def test_locked_status_and_live_authorization_false(self):
        self.assertEqual(self.document["status"], reg.COVERAGE_LOCKED_STATUS)
        self.assertEqual(self.document["preregistration_version"], reg.COVERAGE_PREREG_VERSION)
        self.assertFalse(self.document["approval_required"])
        self.assertTrue(self.document["approval"]["approved"])
        self.assertEqual(self.document["approval"]["scope"], "v6_registration_lock_only")
        self.assertFalse(self.document["approval"]["live_collection_authorized"])
        self.assertFalse(self.document["live_collection_authorized"])
        self.assertTrue(self.document["lock_is_not_live_authorization"])

    def test_output_paths_fresh_and_outputs_absent(self):
        outputs = self.document["outputs"]
        self.assertEqual(outputs, reg.output_paths())
        for old in reg.OLD_OUTPUT_PATHS_V6:
            for value in outputs.values():
                self.assertNotIn(old, str(value))
        self.assertFalse((REPO_ROOT / reg.DEFAULT_JOURNAL_V6).exists())
        self.assertFalse((REPO_ROOT / reg.DEFAULT_REPORT_V6).exists())

    def test_successor_references_and_immutable_note(self):
        successor = self.document["successor_of"]
        self.assertTrue(successor["immutable"])
        self.assertIn("jev-writer-ladder-preregistration-v5.json", successor["v5"])
        self.assertIn("never modified, resumed, appended to, pooled with",
                      successor["note"])


class VerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_locked()

    def test_committed_artifact_verifies(self):
        result = verify(self.document)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["errors"], [])
        self.assertFalse(result["live_collection_authorized"])
        self.assertEqual(result["planned_requests"], 180)
        self.assertEqual(result["request_cap"], 540)

    def test_draft_status_rejected(self):
        draft = reg.build_coverage_manifest_preregistration_v6(approved=False)
        result = verify(draft)
        self.assertFalse(result["ok"])
        self.assertTrue(any("not locked" in error for error in result["errors"]))
        self.assertTrue(any("lock approval is missing" in error for error in result["errors"]))

    def test_hash_and_content_drift_rejected(self):
        tampered = copy.deepcopy(self.document)
        tampered["preregistration_hash"] = "0" * 64
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("registration hash drift from the repository state", result["errors"])
        tampered = copy.deepcopy(self.document)
        tampered["treatment"]["token_budget"] = 512
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("registration content drift from the repository state", result["errors"])
        self.assertIn("token budget drift", result["errors"])

    def test_source_treatment_geometry_drift_rejected(self):
        for key, expected_error in (
                ("source_files_hash", "source hash"),
                ("manifest_treatment_hash", "manifest treatment hash drift"),
                ("information_geometry_hash", "information geometry hash drift")):
            tampered = copy.deepcopy(self.document)
            tampered["generator"][key] = "0" * 64
            result = verify(tampered)
            with self.subTest(key=key):
                self.assertFalse(result["ok"])
                self.assertTrue(any(expected_error in error for error in result["errors"]),
                                result["errors"])

    def test_wrong_form_set_and_count_rejected(self):
        tampered = copy.deepcopy(self.document)
        tampered["manifest"]["iso_form_ids"][0] = "deadbeef"
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("frozen six-form set" in error for error in result["errors"]),
                        result["errors"])
        tampered = copy.deepcopy(self.document)
        form = reg.FROZEN_FORM_IDS[0]
        tampered["manifest"]["form_counts"][form] = 5
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("exactly six instances" in error for error in result["errors"]),
                        result["errors"])

    def test_manifest_id_swap_and_overlap_rejected(self):
        tampered = copy.deepcopy(self.document)
        tampered["manifest"]["instance_ids"][0] = "planning-00011940"  # frozen 17 block
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("overlaps prior instance ids" in error for error in result["errors"]),
                        result["errors"])
        self.assertTrue(any("manifest hash mismatch" in error for error in result["errors"]),
                        result["errors"])
        tampered = copy.deepcopy(self.document)
        tampered["manifest"]["instance_ids"][1] = tampered["manifest"]["instance_ids"][0]
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("manifest contains duplicate instance ids", result["errors"])

    def test_wrong_model_endpoint_codec_transport_pacing_rejected(self):
        mutations = [
            ("model_and_protocol", "model", "jev-0.0.0", "wrong Jev model"),
            ("model_and_protocol", "endpoint", "https://example.invalid", "wrong Jev endpoint"),
            ("model_and_protocol", "codec_version", "jev-choice-wire-v1", "codec version drift"),
            ("treatment", "writer_transport", {"writer_transport_version": "x"},
             "writer transport/pacing/retry drift"),
            ("treatment", "turns", 1, "turns/agents drift"),
            ("treatment", "token_budget", 96, "token budget drift"),
            ("treatment", "seed_algorithm", "unseeded", "seed algorithm drift"),
            ("treatment", "writer_prompt", {"path": "hand-built"}, "prompt path/schema"),
        ]
        for section, field, value, expected in mutations:
            tampered = copy.deepcopy(self.document)
            tampered[section][field] = value
            result = verify(tampered)
            with self.subTest(field=field):
                self.assertFalse(result["ok"])
                self.assertTrue(any(expected in error for error in result["errors"]),
                                result["errors"])
        tampered = copy.deepcopy(self.document)
        tampered["caps"]["pacing"]["min_attempt_interval_seconds"] = 0.25
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("Ling pacing drift", result["errors"])
        tampered = copy.deepcopy(self.document)
        tampered["treatment"]["writer_transport"]["min_attempt_interval_seconds"] = 0.25
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("writer transport/pacing/retry drift", result["errors"])

    def test_caps_drift_and_insufficient_cap_rejected(self):
        tampered = copy.deepcopy(self.document)
        tampered["caps"]["physical_requests"] = 179
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("cap" in error for error in result["errors"]), result["errors"])
        tampered = copy.deepcopy(self.document)
        tampered["caps"]["planned_calls"]["combined"] = 181
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("planned call arithmetic drift (expected 144/36/180)", result["errors"])
        tampered = copy.deepcopy(self.document)
        tampered["caps"]["provider_partition"]["jev"] = 107
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("provider partitions do not sum to the combined cap", result["errors"])
        tampered = copy.deepcopy(self.document)
        tampered["caps"]["worst_case_cost_usd"] = 2.0
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("worst-case cost" in error for error in result["errors"]))

    def test_old_path_rejected(self):
        tampered = copy.deepcopy(self.document)
        tampered["outputs"]["journal"] = "runs/epic-126/jev-writer-ladder-v5.jsonl"
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("old v1-v5 output path rejected" in error
                            for error in result["errors"]), result["errors"])
        tampered = copy.deepcopy(self.document)
        tampered["outputs"]["report"] = "runs/epic-126/jev-writer-exact-bridge-report-v5.json"
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("old v1-v5 output path rejected" in error
                            for error in result["errors"]), result["errors"])

    def test_output_collision_rejected(self):
        result = verify(self.document, journal_exists=True, report_exists=True)
        self.assertFalse(result["ok"])
        self.assertIn("future coverage journal already exists", result["errors"])
        self.assertIn("future coverage report already exists", result["errors"])
        clean = verify(self.document, journal_exists=False, report_exists=False)
        self.assertTrue(clean["ok"], clean["errors"])

    def test_protocol_key_v1_and_mixed_rejected(self):
        tampered = copy.deepcopy(self.document)
        tampered["model_and_protocol"]["protocol_key"] = "jev-choice-wire-v1|deadbeef"
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("v1 key" in error for error in result["errors"]),
                        result["errors"])
        tampered = copy.deepcopy(self.document)
        tampered["extra_protocol_key"] = "jev-choice-wire-v2|" + "a" * 64
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("mixed or non-Jev protocol keys present", result["errors"])
        result = verify(self.document, protocol_key="not-a-jev-key")
        self.assertFalse(result["ok"])
        self.assertTrue(any("not a v2 Jev key" in error for error in result["errors"]),
                        result["errors"])
        result = verify(self.document, model="jev-9.9.9")
        self.assertFalse(result["ok"])
        self.assertTrue(any("runtime model differs" in error for error in result["errors"]),
                        result["errors"])

    def test_live_authorization_attempt_rejected(self):
        tampered = copy.deepcopy(self.document)
        tampered["approval"]["live_collection_authorized"] = True
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("lock must not authorize live collection", result["errors"])
        tampered = copy.deepcopy(self.document)
        tampered["approval"]["scope"] = "live_collection"
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("approval scope is not the v6 registration lock", result["errors"])
        tampered = copy.deepcopy(self.document)
        tampered["live_collection_authorized"] = True
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("live_collection_authorized must be false", result["errors"])

    def test_credential_checks_only_when_requested(self):
        offline = verify(self.document, check_credentials=False)
        self.assertTrue(offline["ok"], offline["errors"])
        present = SimpleNamespace(present=True, shape_ok=True, redacted=lambda: {})
        with mock.patch.object(jc, "load_jev_credentials", return_value=present):
            result = verify(self.document, check_credentials=True, ling_key_present=True)
            self.assertTrue(result["ok"], result["errors"])
        absent = SimpleNamespace(present=False, shape_ok=False, redacted=lambda: {})
        with mock.patch.object(jc, "load_jev_credentials", return_value=absent):
            result = verify(self.document, check_credentials=True, ling_key_present=False)
            self.assertFalse(result["ok"])
            self.assertIn("jev credentials missing for the proposed live preflight",
                          result["errors"])
            self.assertIn("ling credentials missing for the proposed live preflight",
                          result["errors"])

    def test_builder_and_verifier_make_zero_provider_calls(self):
        source = (inspect.getsource(reg.build_coverage_manifest_preregistration_v6)
                  + inspect.getsource(reg.verify_against_coverage_manifest_preregistration_v6)
                  + inspect.getsource(reg.main) + inspect.getsource(reg.select_form_balanced_manifest))
        for forbidden in ("JevChoiceClient(", "LingWriterClientV5(", "urlopen",
                          ".complete(", "requests.", "http"):
            self.assertNotIn(forbidden, source)
        document = reg.build_coverage_manifest_preregistration_v6(approved=True)
        result = verify(document, check_credentials=False)
        self.assertTrue(result["ok"], result["errors"])


class LifecycleTests(unittest.TestCase):
    """Review #190 findings: self-scan exclusion, self source-binding, runner policy."""

    @classmethod
    def setUpClass(cls):
        cls.document = load_locked()

    def test_v6_outputs_excluded_and_only_collision_fails(self):
        evidence_before = reg.prior_instance_ids(REPO_ROOT)
        ids_before = reg._prior_id_set(REPO_ROOT)
        self.assertEqual(sorted(evidence_before["excluded"]), sorted(reg.V6_OWNED_PATHS))
        self.assertEqual(len(reg.V6_OWNED_FILE_NAMES), 3)
        journal = REPO_ROOT / reg.DEFAULT_JOURNAL_V6
        report = REPO_ROOT / reg.DEFAULT_REPORT_V6
        self.assertFalse(journal.exists())
        self.assertFalse(report.exists())
        manifest_ids = self.document["manifest"]["instance_ids"]
        # representative future outputs embedding the 36 manifest ids
        journal.write_text("\n".join(json.dumps({"instance_id": instance_id,
                                                 "status": "complete"})
                                     for instance_id in manifest_ids) + "\n",
                           encoding="utf-8")
        report.write_text(json.dumps({"status": "completed",
                                      "cases": [{"instance_id": instance_id}
                                                for instance_id in manifest_ids]}),
                          encoding="utf-8")
        try:
            evidence_during = reg.prior_instance_ids(REPO_ROOT)
            ids_during = reg._prior_id_set(REPO_ROOT)
            self.assertEqual(ids_during, ids_before)
            self.assertEqual(evidence_during, evidence_before)
            self.assertEqual(
                reg.build_coverage_manifest_preregistration_v6(approved=True), self.document)
            result = verify(self.document)
            self.assertFalse(result["ok"])
            self.assertEqual(result["errors"], ["future coverage journal already exists",
                                               "future coverage report already exists"])
        finally:
            journal.unlink(missing_ok=True)
            report.unlink(missing_ok=True)
        self.assertFalse(journal.exists())
        self.assertFalse(report.exists())
        clean = verify(self.document)
        self.assertTrue(clean["ok"], clean["errors"])

    def test_registration_module_is_source_bound(self):
        module_path = "src/apart_incident_response/jev_coverage_manifest_preregistration_v6.py"
        self.assertIn(module_path, reg.COVERAGE_SOURCE_FILES)
        self.assertIn(reg.RUNNER_SOURCE_REL, reg.COVERAGE_SOURCE_FILES)
        self.assertEqual(len(reg.COVERAGE_SOURCE_FILES), 23)
        self.assertIn(module_path, self.document["generator"]["source_files"])
        self.assertIn(reg.RUNNER_SOURCE_REL, self.document["generator"]["source_files"])
        self.assertEqual(self.document["generator"]["source_files_hash"],
                         reg._source_files_hash(REPO_ROOT))

    def test_runner_policy_frozen_for_191(self):
        policy = self.document["runner_policy"]
        self.assertTrue(policy["required_before_live"])
        self.assertTrue(policy["runner_implemented"])
        self.assertEqual(policy["runner_source_files"], [reg.RUNNER_SOURCE_REL])
        self.assertTrue(policy["runner_source_bound"])
        self.assertFalse(policy["adding_runner_authorizes_collection"])
        self.assertIn(reg.RUNNER_SOURCE_REL, policy["policy"])
        self.assertIn("COVERAGE_SOURCE_FILES", policy["policy"])
        self.assertIn("does not authorize collection", policy["policy"])
        self.assertIn("live execution is forbidden", policy["live_execution_rule"])
        self.assertIn("reviewed and separately live-authorized", policy["live_execution_rule"])
        self.assertIn("not live authorization", policy["live_execution_rule"])
        superseded = policy["superseded_offline_lock"]
        self.assertEqual(superseded["preregistration_hash"], reg.SUPERSEDED_OFFLINE_LOCK_HASH)
        self.assertEqual(superseded["preregistration_hash"],
                         "41c14acebba674180bf7878e519b53422513ae2612133cee03e94e3ca608ce5c")

    def test_superseded_offline_lock_hash_rejected(self):
        tampered = copy.deepcopy(self.document)
        tampered["preregistration_hash"] = reg.SUPERSEDED_OFFLINE_LOCK_HASH
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("registration hash drift from the repository state", result["errors"])

    def test_runner_policy_tamper_rejected(self):
        tampered = copy.deepcopy(self.document)
        tampered["runner_policy"]["adding_runner_authorizes_collection"] = True
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("adding the runner must not authorize collection", result["errors"])
        tampered = copy.deepcopy(self.document)
        tampered["runner_policy"]["runner_implemented"] = False
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("runner must be implemented and source-bound in this lock",
                      result["errors"])
        tampered = copy.deepcopy(self.document)
        tampered["runner_policy"]["runner_source_files"] = ["src/apart_incident_response/x.py"]
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("runner source file mismatch", result["errors"])
        tampered = copy.deepcopy(self.document)
        tampered["runner_policy"]["superseded_offline_lock"]["preregistration_hash"] = "0" * 64
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertIn("superseded offline lock hash missing or drifted", result["errors"])
        tampered = copy.deepcopy(self.document)
        del tampered["runner_policy"]
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any("runner policy missing" in error for error in result["errors"]),
                        result["errors"])


if __name__ == "__main__":
    unittest.main()
