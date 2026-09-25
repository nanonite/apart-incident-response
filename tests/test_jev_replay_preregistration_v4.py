import copy
import hashlib
import json
import math
import unittest
from pathlib import Path

from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_choice_v2 as jc2
from apart_incident_response import jev_replay as jr
from apart_incident_response import jev_replay_inference as ji
from apart_incident_response import jev_replay_preregistration as pr
from apart_incident_response import jev_replay_preregistration_v2 as prv2
from apart_incident_response import jev_replay_preregistration_v4 as reg


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = REPO_ROOT / "runs" / "epic-126" / "replay-v4" / "jev-choice-replay-preregistration-v4.json"
DECISION = json.loads(
    (REPO_ROOT / "runs" / "epic-126" / "decisions" / "jev-v7-coverage-decision.json")
    .read_text(encoding="utf-8"))


def load_locked() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def verify(document, **kwargs):
    kwargs.setdefault("repo_root", REPO_ROOT)
    kwargs.setdefault("journal_exists", False)
    kwargs.setdefault("report_exists", False)
    return reg.verify_against_jev_replay_preregistration_v4(document, **kwargs)


class PositiveReproductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_locked()

    def test_byte_reproducible_build(self):
        self.assertEqual(self.document,
                         reg.build_replay_preregistration_v4(approved=True,
                                                             repo_root=REPO_ROOT))

    def test_committed_artifact_verifies(self):
        result = verify(self.document)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["errors"], [])
        self.assertFalse(result["live_collection_authorized"])

    def test_locked_status_and_not_authorization(self):
        self.assertEqual(self.document["preregistration_version"],
                         reg.JEV_REPLAY_V4_PREREG_VERSION)
        self.assertEqual(self.document["status"], reg.JEV_REPLAY_V4_LOCKED_STATUS)
        self.assertFalse(self.document["approval_required"])
        self.assertTrue(self.document["approval"]["approved"])
        self.assertEqual(self.document["approval"]["scope"], "replay_v4_registration_lock_only")
        self.assertFalse(self.document["approval"]["live_collection_authorized"])
        self.assertFalse(self.document["live_collection_authorized"])
        self.assertTrue(self.document["lock_is_not_live_authorization"])
        pending = " ".join(self.document["pending_decisions"])
        self.assertIn("does NOT authorize #159 execution", pending)
        self.assertIn("separate review and explicit live authorization", pending)

    def test_provenance_pins_recompute(self):
        provenance = self.document["provenance"]
        self.assertEqual(provenance["event_source"]["sha256"], reg.DECISION_SHA256)
        actual = hashlib.sha256((REPO_ROOT / reg.DECISION_ARTIFACT).read_bytes()).hexdigest()
        self.assertEqual(actual, reg.DECISION_SHA256)
        self.assertEqual(provenance["event_source"]["baseline_commit"], "cad2c80")
        self.assertEqual(provenance["event_count"], 17)
        self.assertEqual(provenance["form_count"], 6)
        self.assertIn("NOT a completed fixed-N sample",
                      provenance["partial_run_note"])
        upstream = provenance["upstream_sha256"]
        self.assertEqual(upstream, DECISION["inputs"]["sha256"])
        for relative, expected in upstream.items():
            actual = hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()
            self.assertEqual(actual, expected, relative)
        self.assertEqual(provenance["upstream_registration_content_hash"],
                         "f7f7d5742ea3e6a710ed102e6c2a454992abede5c4f51591a9cc447781797565")

    def test_source_and_treatment_hashes(self):
        self.assertEqual(self.document["source_files"], list(reg.REPLAY_V4_SOURCE_FILES))
        digest = hashlib.sha256()
        for relative in reg.REPLAY_V4_SOURCE_FILES:
            data = (REPO_ROOT / relative).read_bytes()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(data)
        self.assertEqual(self.document["source_files_hash"], digest.hexdigest())
        self.assertEqual(self.document["message_wording_hash"], jr.message_wording_hash())
        self.assertEqual(self.document["treatment_hash"],
                         reg.treatment_hash_v4(
                             decision_sha256=reg.DECISION_SHA256,
                             wording_hash=jr.message_wording_hash(),
                             normalization_policy_hash=prv2.normalization_policy_hash()))


class EventSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_locked()
        cls.events = cls.document["events"]

    def test_seventeen_events_unique_and_ordered_like_decision(self):
        self.assertEqual(len(self.events), 17)
        ids = [event["event_id"] for event in self.events]
        self.assertEqual(len(set(ids)), 17)
        self.assertEqual(ids, [event["event_id"] for event in DECISION["events"]])

    def test_distribution_exactly_1_4_4_1_4_3(self):
        forms = self.document["forms"]
        self.assertEqual(tuple(forms["expected_distribution"]), (1, 4, 4, 1, 4, 3))
        self.assertEqual(tuple(forms["form_event_counts"][form]
                               for form in reg.FROZEN_FORM_IDS), (1, 4, 4, 1, 4, 3))
        self.assertEqual(set(forms["covered_form_ids"]), set(reg.FROZEN_FORM_IDS))
        self.assertEqual(forms["k"], 6)
        self.assertEqual(sum(forms["form_event_counts"].values()), 17)

    def test_event_bindings_authoritative(self):
        for event in self.events:
            with self.subTest(event=event["event_id"]):
                real = event["real"]
                self.assertEqual(real["writer_id"], "B")
                self.assertEqual(real["reader_id"], "A")
                self.assertTrue(real["ownership_verified"])
                self.assertTrue(real["informative_verified"])
                self.assertAlmostEqual(real["i_m_bits"], math.log2(3))
                self.assertTrue(real["exposure_ids"])
                instance = reg._regenerate_instance(event["instance_id"])
                info = instance.information("A", real["claim"], real["message_id"])
                self.assertEqual(info.status, "accepted")
                self.assertAlmostEqual(info.delta_i_bits, math.log2(3))
                self.assertTrue(instance.holds_claim("B", real["claim"]))

    def test_placebo_bindings_inert(self):
        for event in self.events:
            with self.subTest(event=event["event_id"]):
                placebo = event["placebo"]
                self.assertEqual(placebo["i_m_bits"], 0.0)
                self.assertTrue(placebo["synthetic"])
                self.assertTrue(placebo["receiver_known"])
                self.assertTrue(placebo["inert_verified"])
                self.assertEqual(placebo["construction"], jr.PLACEBO_CONSTRUCTION)
                self.assertEqual(placebo["envelope"], jr.MESSAGE_ENVELOPE_TEMPLATE)
                self.assertEqual(placebo["origin"], jr.PLACEBO_ORIGIN)
                instance = reg._regenerate_instance(event["instance_id"])
                self.assertIn(placebo["claim"],
                              [str(c) for c in instance.private_clues["A"]])
                info = instance.information("A", placebo_claim_of(placebo), "placebo")
                self.assertEqual(info.delta_i_bits, 0.0)

    def test_branch_hashes_recompute(self):
        for event in self.events:
            with self.subTest(event=event["event_id"]):
                instance = reg._regenerate_instance(event["instance_id"])
                body, state = reg.pre_read_body(instance, pr.JEV_REPLAY_MODEL)
                pre_read = event["pre_read"]
                self.assertEqual(pre_read["request_body_hash"],
                                 jr.prompt_form_id(body))
                self.assertEqual(pre_read["state_hash"],
                                 jr.canonical_hash(dict(state.state)))
                expected = {
                    "real": jr.prompt_form_id(jr.branch_request_body(
                        body, jr.serialize_message(event["real"]["claim"]))),
                    "placebo": jr.prompt_form_id(jr.branch_request_body(
                        body, jr.serialize_placebo_message(event["placebo"]["claim"]))),
                    "null": jr.prompt_form_id(jr.branch_request_body(body, None)),
                }
                self.assertEqual(pre_read["branch_request_hashes"], expected)
                self.assertEqual(pre_read["request_body_hash"], event["prompt_form_id"])


def placebo_claim_of(placebo):
    return placebo["claim"]


class DesignFreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_locked()

    def test_branch_design_freeze(self):
        design = self.document["branch_design"]
        self.assertEqual(design["branches"], ["real", "placebo", "null"])
        envelope = design["envelope"]
        self.assertEqual(envelope["template"], jr.MESSAGE_ENVELOPE_TEMPLATE)
        self.assertTrue(envelope["identical_for_real_and_placebo"])
        self.assertTrue(envelope["source_neutral"])
        self.assertEqual(envelope["wording_hash"], jr.message_wording_hash())
        self.assertFalse(design["sender_identity_model_visible"])
        self.assertFalse(design["synthetic_origin_model_visible"])
        self.assertEqual(design["only_difference_between_branches"],
                         "state.visible_messages")
        self.assertIn("I_m = 0", design["placebo"])
        self.assertIn("no Ling call", design["no_ling_calls"])

    def test_estimand_and_direction(self):
        estimand = self.document["estimand"]
        self.assertEqual(estimand, reg.ESTIMAND)
        self.assertEqual(estimand["experimental_unit"], "prompt form")
        self.assertEqual(estimand["k"], 6)
        self.assertEqual(estimand["events"], 17)
        self.assertFalse(estimand["events_are_independent_units"])
        self.assertEqual(estimand["event_contrast"], "d_i = H_real,i - H_placebo,i")
        self.assertIn("equal-weight mean", estimand["primary"])
        self.assertEqual(estimand["directional_prediction"], "Delta < 0")
        joined = " | ".join(estimand["unit_notes"])
        self.assertIn("not 17 independent states", joined)
        self.assertIn("no instance-level t-test", joined)
        self.assertEqual(estimand["null_branch"]["excluded_from"],
                         "the algebraically cancelling primary real-versus-placebo contrast")
        self.assertEqual(len(estimand["null_branch"]["retained_for"]), 2)

    def test_inference_rules(self):
        inference = self.document["inference"]
        self.assertEqual(inference, reg.INFERENCE)
        self.assertIn("exhaustive two-sided cluster sign-flip", inference["primary_test"])
        self.assertIn("df = 5", inference["interval"])
        self.assertEqual(inference["min_two_sided_p_k6"], 2 / 64)
        self.assertEqual(inference["min_two_sided_p_k5"], 2 / 32)
        self.assertIn("negative", inference["direction_requirement"])
        self.assertEqual(inference["prohibited_as_primary"][0], "instance-level t-test")
        # floors recomputed from the inference module
        self.assertEqual(ji.sign_flip_two_sided([-1.0] * 6)["min_p_value"], 2 / 64)
        self.assertEqual(ji.sign_flip_two_sided([-1.0] * 5)["min_p_value"], 2 / 32)

    def test_guards_never_filter(self):
        guards = self.document["guards"]
        self.assertEqual(guards, reg.GUARDS)
        self.assertEqual(guards["target_probability_delta"], 0.0)
        self.assertEqual(guards["feasible_set_mass_epsilon"], 0.01)
        self.assertIn("never used to filter", guards["reporting"])
        self.assertIn("never be labeled useful uptake", guards["useful_uptake_rule"])

    def test_missingness_and_fallbacks(self):
        missingness = self.document["missingness"]
        self.assertEqual(missingness, reg.MISSINGNESS)
        self.assertIn("real and placebo are both valid", missingness["complete_pair"])
        self.assertIn("by branch and by form", missingness["report"])
        self.assertIn("every one of the six", missingness["primary_requirement"])
        self.assertEqual(missingness["target"], "retain all 17 events")
        self.assertEqual(missingness["imputation"], "never impute missing pairs")
        self.assertIn("interval-only descriptive", missingness["five_form_fallback"])
        self.assertIn("0.05", missingness["five_form_fallback"])
        self.assertIn("no causal gate", missingness["five_form_fallback"])
        self.assertEqual(missingness["below_five_forms"], "replay-coverage failure")

    def test_sensitivity_plan(self):
        sensitivity = self.document["sensitivity"]
        self.assertEqual(sensitivity, reg.SENSITIVITY)
        self.assertEqual(sensitivity["normalization_thresholds"], [1e-6, 0.01, 0.03, 0.05])
        self.assertIn("maximum induced entropy change", " | ".join(sensitivity["report"]))
        self.assertIn("never overrides the primary result", sensitivity["rule"])
        self.assertEqual(sensitivity["secondary_analyses"],
                         ["form-cluster bootstrap", "sign test on form means",
                          "instance-weighted mean"])
        self.assertIn("Wilcoxon on form means", sensitivity["not_implemented"])

    def test_limitations(self):
        limitations = self.document["limitations"]
        self.assertEqual(limitations, reg.LIMITATIONS)
        self.assertEqual(limitations["mde_or_ci_bits"], 0.203)
        self.assertIn("closed form space", limitations["k_cap"])
        self.assertIn("cannot exclude", limitations["null_result"])
        conditional = " ".join(limitations["conditional_on"])
        self.assertIn("six frozen planning-low prompt forms", conditional)
        self.assertIn("paid Ling route that generated the messages", conditional)


class CapsAndProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_locked()

    def test_call_and_physical_arithmetic(self):
        caps = self.document["caps"]
        planned = caps["planned_calls"]
        self.assertEqual((planned["jev"], planned["ling"], planned["combined"]), (51, 0, 51))
        self.assertIn("17 events x 3 branches", planned["arithmetic"])
        self.assertEqual(caps["physical_requests"], 153)
        partition = caps["provider_partition"]
        self.assertEqual((partition["jev"], partition["ling"], partition["total"]), (153, 0, 153))
        self.assertEqual(partition["jev"], 51 * 3)
        self.assertEqual(caps["retry_reserve"]["physical"], 102)
        self.assertEqual(caps["retry_reserve"]["max_retries"], 2)
        ling = caps["ling_budget"]
        self.assertEqual(ling["planned_calls"], 0)
        self.assertEqual(ling["physical_cap"], 0)
        self.assertIn("no Ling call exists", ling["justification"])

    def test_cost_arithmetic(self):
        caps = self.document["caps"]
        self.assertEqual(caps["cost_cap_usd"], 1.0)
        self.assertLessEqual(1.0, 1.0)
        self.assertEqual(caps["input_token_ceiling"], 8192)
        self.assertEqual(caps["input_usd_per_mtok"], 0.042)
        self.assertEqual(caps["worst_case_call_cost_usd"], 0.000344064)
        self.assertEqual(caps["worst_case_cost_usd"], 0.052641792)
        self.assertEqual(round(153 * 8192 * 0.042 / 1e6, 9), 0.052641792)
        self.assertLessEqual(caps["worst_case_cost_usd"], caps["cost_cap_usd"])
        self.assertIn("0.052641792", caps["worst_case_arithmetic"])
        self.assertEqual(caps["status"], "locked; live_collection_authorized=false")

    def test_protocol_and_normalization(self):
        protocol = self.document["model_and_protocol"]
        self.assertEqual(protocol["model"], "jev-1.13.0")
        self.assertEqual(protocol["model"], pr.JEV_REPLAY_MODEL)
        self.assertEqual(protocol["endpoint"], pr.JEV_REPLAY_ENDPOINT)
        self.assertEqual(protocol["codec_version"], jc2.JEV_CHOICE_V2_CODEC_VERSION)
        self.assertEqual(protocol["protocol_key"], reg.prv6_protocol_key())
        self.assertTrue(jc2.is_jev_v2_protocol_key(protocol["protocol_key"]))
        self.assertFalse(jc.is_jev_protocol_key(protocol["protocol_key"]))
        self.assertEqual(protocol["max_retries"], 2)
        self.assertEqual(protocol["retryable_statuses"], sorted(jc.JEV_RETRYABLE_STATUSES))
        self.assertEqual(protocol["normalization_policy_hash"],
                         prv2.normalization_policy_hash())
        self.assertEqual(protocol["normalization_policy"], prv2.normalization_policy())
        self.assertIn("normalize-all-accepted-vectors", protocol["normalization_mode"])


class VerifierRejectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_locked()

    def _expect(self, mutate, expected, document=None):
        tampered = copy.deepcopy(document or self.document)
        mutate(tampered)
        result = verify(tampered)
        self.assertFalse(result["ok"])
        self.assertTrue(any(expected in error for error in result["errors"]),
                        result["errors"])

    def test_draft_and_authorization_status_rejected(self):
        draft = reg.build_replay_preregistration_v4(approved=False, repo_root=REPO_ROOT)
        result = verify(draft)
        self.assertFalse(result["ok"])
        self.assertTrue(any("not locked" in error for error in result["errors"]))
        self._expect(lambda d: d.__setitem__("preregistration_hash", "0" * 64),
                     "registration hash drift")
        self._expect(lambda d: d["approval"].__setitem__("live_collection_authorized", True),
                     "lock must not authorize live collection")
        self._expect(lambda d: d.__setitem__("live_collection_authorized", True),
                     "live_collection_authorized must be false")
        self._expect(lambda d: d["approval"].__setitem__("scope", "live_collection"),
                     "approval scope is not the v4 replay registration lock")
        self._expect(lambda d: d.__setitem__("lock_is_not_live_authorization", False),
                     "lock-is-not-live-authorization")

    def test_content_and_source_drift_rejected(self):
        self._expect(lambda d: d.__setitem__("purpose", "tampered"),
                     "registration content drift")
        self._expect(lambda d: d.__setitem__("source_files_hash", "0" * 64),
                     "source hash does not match")
        self._expect(lambda d: d.__setitem__("treatment_hash", "0" * 64),
                     "treatment hash drift")

    def test_decision_pin_and_upstream_drift_rejected(self):
        self._expect(lambda d: d["provenance"]["event_source"].__setitem__("sha256", "0" * 64),
                     "decision artifact pin drift")
        self._expect(lambda d: d["provenance"]["upstream_sha256"].__setitem__(
            "runs/epic-126/jev-coverage-manifest-v7.jsonl", "0" * 64),
            "upstream artifact drift")

    def test_event_id_mutations_rejected(self):
        self._expect(lambda d: d["events"].pop(0), "missing event ids")
        self._expect(lambda d: d["events"].append(copy.deepcopy(d["events"][0])),
                     "duplicate event ids")
        extra = copy.deepcopy(self.document["events"][0])
        extra["event_id"] = "planning-00000000:message-B-0"
        self._expect(lambda d: d["events"].append(copy.deepcopy(extra)), "extra event ids")
        self._expect(lambda d: d["events"].reverse(), "reordered")

    def test_distribution_and_membership_mutations_rejected(self):
        def move_event(document):
            # move the first event onto a different frozen form so the
            # distribution necessarily changes
            document["events"][0]["prompt_form_id"] = reg.FROZEN_FORM_IDS[0]
        self._expect(move_event, "bound event distribution")
        self._expect(lambda d: d["forms"].__setitem__("expected_distribution", [1, 1, 1, 1, 1, 1]),
                     "expected distribution is not 1/4/4/1/4/3")
        self._expect(lambda d: d["forms"]["covered_form_ids"].pop(),
                     "covered form set differs")
        self._expect(lambda d: d["forms"]["form_event_counts"].__setitem__(
            reg.FROZEN_FORM_IDS[0], 2), "per-form event counts differ")

    def test_non_b_to_a_and_non_informative_rejected(self):
        self._expect(lambda d: d["events"][0]["real"].__setitem__("writer_id", "A"),
                     "non-B->A real message")
        self._expect(lambda d: d["events"][0]["real"].__setitem__("claim", "not-a-claim"),
                     "real claim not informative")
        self._expect(lambda d: d["events"][0]["real"].__setitem__("i_m_bits", 1.0),
                     "frozen real I_m is not log2(3)")

    def test_non_inert_placebo_rejected(self):
        self._expect(lambda d: d["events"][0]["placebo"].__setitem__("claim", "precedes=x>y"),
                     "placebo claim is not receiver-known")
        self._expect(lambda d: d["events"][0]["placebo"].__setitem__("i_m_bits", 1.0),
                     "placebo claim is not inert")
        self._expect(lambda d: d["events"][0]["placebo"].__setitem__("synthetic", False),
                     "placebo claim is not inert")
        self._expect(lambda d: d["events"][0]["placebo"].__setitem__("envelope", "x: {claim}"),
                     "placebo claim is not inert")

    def test_branch_state_mutations_rejected(self):
        self._expect(lambda d: d["events"][0]["pre_read"]["branch_request_hashes"].__setitem__(
            "real", "0" * 64), "branch request hash mismatch")
        self._expect(lambda d: d["events"][0]["pre_read"].__setitem__("state_hash", "0" * 64),
                     "pre-read state hash mismatch")
        self._expect(lambda d: d["events"][0]["pre_read"].__setitem__(
            "request_body_hash", "0" * 64), "request body hash mismatch")
        self._expect(lambda d: d["events"][0]["pre_read"]["option_ids"].pop(),
                     "option drift")

    def test_estimand_weighting_independence_mutations_rejected(self):
        self._expect(lambda d: d["estimand"].__setitem__("experimental_unit", "instance"),
                     "experimental unit or k drift")
        self._expect(lambda d: d["estimand"].__setitem__("events_are_independent_units", True),
                     "must not treat the events as independent units")
        self._expect(lambda d: d["estimand"].__setitem__("event_contrast", "x"),
                     "estimand drift")
        self._expect(lambda d: d["estimand"].__setitem__("primary", "instance-weighted mean"),
                     "primary estimand is not the equal-form mean")
        self._expect(lambda d: d["estimand"].__setitem__("directional_prediction", "Delta > 0"),
                     "estimand drift")

    def test_inference_guard_missingness_mutations_rejected(self):
        self._expect(lambda d: d["inference"].__setitem__("primary_test", "instance t-test"),
                     "inference rule drift: primary_test")
        self._expect(lambda d: d["inference"].__setitem__("interval", "df = 16"),
                     "inference rule drift: interval")
        self._expect(lambda d: d["inference"].__setitem__("min_two_sided_p_k6", 0.001),
                     "inference rule drift: min_two_sided_p_k6")
        self._expect(lambda d: d["guards"].__setitem__("target_probability_delta", 0.05),
                     "guard thresholds drift")
        self._expect(lambda d: d["guards"].__setitem__("reporting", "filtered from primary"),
                     "guards must not filter")
        self._expect(lambda d: d["missingness"].__setitem__("imputation", "mean impute"),
                     "missingness imputation rule drift")
        self._expect(lambda d: d["missingness"].__setitem__("primary_requirement", "any form"),
                     "six-form complete-pair requirement missing")
        self._expect(lambda d: d["missingness"].__setitem__("five_form_fallback",
                                                            "run the sign-flip anyway"),
                     "five-form fallback rule drift")
        self._expect(lambda d: d["missingness"].__setitem__("below_five_forms", "proceed"),
                     "below-five rule drift")
        self._expect(lambda d: d["sensitivity"].__setitem__("normalization_thresholds",
                                                            [0.01]),
                     "sensitivity thresholds drift")
        self._expect(lambda d: d["sensitivity"].__setitem__(
            "rule", "secondary may override"), "secondary-analysis rule drift")
        self._expect(lambda d: d["limitations"].__setitem__("mde_or_ci_bits", 0.05),
                     "MDE limitation drift")

    def test_protocol_and_key_mutations_rejected(self):
        self._expect(lambda d: d["model_and_protocol"].__setitem__("model", "jev-0.0.0"),
                     "wrong Jev model")
        self._expect(lambda d: d["model_and_protocol"].__setitem__("endpoint", "https://x"),
                     "wrong Jev endpoint")
        self._expect(lambda d: d["model_and_protocol"].__setitem__("codec_version", "v1"),
                     "wrong codec version")
        self._expect(lambda d: d["model_and_protocol"].__setitem__("protocol_key",
                                                                   "jev-choice-wire-v1|dead"),
                     "v1 key")
        self._expect(lambda d: d.__setitem__("extra_protocol_key",
                                             "jev-choice-wire-v2|" + "a" * 64),
                     "mixed or non-Jev protocol keys")
        self._expect(lambda d: d["model_and_protocol"].__setitem__(
            "normalization_policy_hash", "0" * 64), "normalization policy drift")

    def test_caps_and_output_mutations_rejected(self):
        self._expect(lambda d: d["caps"].__setitem__("physical_requests", 154),
                     "physical request ceiling drift")
        self._expect(lambda d: d["caps"]["planned_calls"].__setitem__("jev", 52),
                     "planned call arithmetic drift")
        self._expect(lambda d: d["caps"]["provider_partition"].__setitem__("jev", 154),
                     "provider partition drift")
        self._expect(lambda d: d["caps"].__setitem__("worst_case_cost_usd", 0.5),
                     "worst-case cost drift")
        self._expect(lambda d: d["caps"]["ling_budget"].__setitem__("planned_calls", 1),
                     "must not carry a Ling budget")
        self._expect(lambda d: d.__setitem__("outputs", {**d["outputs"],
                                                        "journal": "runs/epic-126/jev-choice-pilot-v3.jsonl"}),
                     "old output path rejected")
        self._expect(lambda d: d.__setitem__("outputs", {**d["outputs"], "journal": "x.jsonl"}),
                     "output paths differ")

    def test_freshness_collisions_rejected(self):
        result = verify(self.document, journal_exists=True, report_exists=True)
        self.assertFalse(result["ok"])
        self.assertIn("future replay journal already exists", result["errors"])
        self.assertIn("future replay report already exists", result["errors"])

    def test_wrong_runtime_model_endpoint_key_rejected(self):
        result = verify(self.document, model="jev-0.0.0")
        self.assertFalse(result["ok"])
        self.assertTrue(any("differs from the registration" in error
                            or "wrong Jev model" in error for error in result["errors"]))
        result = verify(self.document, protocol_key="not-a-key")
        self.assertFalse(result["ok"])
        self.assertTrue(any("v2 Jev key" in error for error in result["errors"]))


class OfflineContractTests(unittest.TestCase):
    def test_builder_and_verifier_make_zero_provider_calls(self):
        source = Path(reg.__file__).read_text(encoding="utf-8")
        for forbidden in ("JevChoiceClient(", "LingWriterClient(", "urlopen",
                          "requests.", "http://", "https://"):
            self.assertNotIn(forbidden, source)
        document = reg.build_replay_preregistration_v4(approved=True, repo_root=REPO_ROOT)
        result = verify(document)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(document["provider_calls"] if "provider_calls" in document else 0, 0)

    def test_output_paths_are_fresh_v4_names(self):
        outputs = reg.output_paths()
        self.assertEqual(outputs["registration"],
                         "runs/epic-126/replay-v4/jev-choice-replay-preregistration-v4.json")
        self.assertEqual(outputs["journal"],
                         "runs/epic-126/replay-v4/jev-choice-replay-v4.jsonl")
        self.assertEqual(outputs["report"],
                         "runs/epic-126/replay-v4/jev-choice-replay-report-v4.json")
        for old in reg.OLD_OUTPUT_PATHS_V4:
            self.assertNotIn(old, str(outputs["journal"]))
            self.assertNotIn(old, str(outputs["report"]))


def _expect_error(test, mutate, expected, document):
    tampered = copy.deepcopy(document)
    mutate(tampered)
    result = verify(tampered)
    test.assertFalse(result["ok"])
    test.assertTrue(any(expected in error for error in result["errors"]), result["errors"])


class BranchScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_locked()
        cls.events = DECISION["events"]
        cls.schedule = cls.document["branch_schedule"]

    def test_schedule_reproduces_and_rebuilds_identically(self):
        built = reg.build_branch_schedule(self.events)
        self.assertEqual(built, self.schedule)
        self.assertEqual(reg.build_branch_schedule(self.events), built)

    def test_event_major_decision_order_and_valid_permutations(self):
        self.assertTrue(self.schedule["event_major"])
        self.assertIn("executed adjacently", self.schedule["execution_order"])
        expected_order = [event["event_id"] for event in self.events]
        self.assertEqual(self.schedule["event_order"], expected_order)
        self.assertEqual(list(self.schedule["schedule"]), expected_order)
        self.assertEqual(set(self.schedule["schedule"]), set(expected_order))
        self.assertEqual(self.schedule["allowed_branches"], ["real", "placebo", "null"])
        for event_id, branches in self.schedule["schedule"].items():
            with self.subTest(event=event_id):
                self.assertEqual(len(branches), 3)
                self.assertEqual(sorted(branches), ["null", "placebo", "real"])

    def test_all_six_permutations_represented(self):
        used = {tuple(branches) for branches in self.schedule["schedule"].values()}
        self.assertEqual(used, set(reg.BRANCH_PERMUTATIONS))
        self.assertEqual(len(self.schedule["permutations"]), 6)

    def test_position_balance_table(self):
        balance = self.schedule["position_balance"]
        self.assertEqual(balance["by_position"], {
            "1": {"null": 6, "placebo": 5, "real": 6},
            "2": {"null": 6, "placebo": 6, "real": 5},
            "3": {"null": 5, "placebo": 6, "real": 6},
        })
        self.assertEqual(balance["per_branch_totals"],
                         {"null": 17, "placebo": 17, "real": 17})
        self.assertEqual(balance["max_position_difference"], 1)
        self.assertEqual(self.schedule["expected_max_position_difference"], 1)
        for slot in balance["by_position"].values():
            self.assertEqual(sum(slot.values()), 17)
            self.assertLessEqual(max(slot.values()) - min(slot.values()), 1)

    def test_form_level_rotation(self):
        form_roles = self.schedule["form_roles"]
        self.assertEqual(set(form_roles), set(reg.FROZEN_FORM_IDS))
        counts = {"0a3349e16c9633b4d559dfbb808d1e50d0446d8f92160a0feddd1e37299796ee": 1,
                  "1c1d9f6b5c9271ad8e74de180c3e397e1369d326564c9a08ba0840eff0b148fc": 4,
                  "2954f5684bcd198ed8eea0956cf573f93cde628d6dfa7472fc57f556bd089b2c": 4,
                  "3196a8d69f844702db012816def7d7866e7416e9fadc9f28eaa7f12ac16a8569": 1,
                  "55968fe191b18f37d1951d71f777115f753e0b9a6da526015f3db5251a1383eb": 4,
                  "ce847ac53b6e344103bc775aede5212b2be6fbd568dc1d85fd24cbde8f585222": 3}
        for form, role in form_roles.items():
            events = role["events"]
            with self.subTest(form=form):
                self.assertEqual(len(events), counts[form])
                self.assertEqual(role["lexicographic_form_index"],
                                 sorted(reg.FROZEN_FORM_IDS).index(form))
                self.assertEqual(role["rotation_start"], role["lexicographic_form_index"])
                permutations = [tuple(entry["branches"]) for entry in events]
                self.assertEqual(len(set(permutations)), len(permutations))
                per_form_ids = [event["event_id"] for event in self.events
                                if event["prompt_form_id"] == form]
                self.assertEqual([entry["event_id"] for entry in events], per_form_ids)
                for index, entry in enumerate(events):
                    self.assertEqual(entry["permutation_index"],
                                     (role["rotation_start"] + index) % 6)

    def test_schedule_depends_only_on_frozen_identity(self):
        mutated = copy.deepcopy(self.events)
        for event in mutated:
            event["claim"] = "tampered"
            event["i_m_bits"] = 999.0
            event["exposure_ids"] = []
        self.assertEqual(reg.build_branch_schedule(mutated), self.schedule)

    def test_execution_order_and_permutation_drift_rejected(self):
        _expect_error(self, lambda d: d["branch_schedule"]["schedule"].__setitem__(
            d["branch_schedule"]["event_order"][0], ["real", "real", "null"]),
            "branch schedule drift", self.document)
        _expect_error(self, lambda d: d["branch_schedule"]["schedule"].pop(
            d["branch_schedule"]["event_order"][-1]),
            "branch schedule is missing or has extra events", self.document)
        _expect_error(self, lambda d: d["branch_schedule"].__setitem__(
            "event_order", list(reversed(d["branch_schedule"]["event_order"]))),
            "branch schedule event order differs", self.document)
        _expect_error(self, lambda d: d["branch_schedule"].__setitem__(
            "allowed_branches", ["real", "placebo"]),
            "branch schedule allows branches other than", self.document)

    def test_balance_and_rotation_drift_rejected(self):
        def skew_balance(document):
            schedule = document["branch_schedule"]["schedule"]
            first = document["branch_schedule"]["event_order"][0]
            schedule[first] = ["real", "placebo", "null"]
            second = document["branch_schedule"]["event_order"][1]
            schedule[second] = ["real", "placebo", "null"]
        _expect_error(self, skew_balance, "branch schedule drift", self.document)

        def duplicate_within_form(document):
            roles = document["branch_schedule"]["form_roles"]
            form = "1c1d9f6b5c9271ad8e74de180c3e397e1369d326564c9a08ba0840eff0b148fc"
            events = roles[form]["events"]
            events[1]["branches"] = list(events[0]["branches"])
            schedule = document["branch_schedule"]["schedule"]
            schedule[events[1]["event_id"]] = list(events[0]["branches"])
        _expect_error(self, duplicate_within_form, "branch schedule drift", self.document)

        def stale_balance(document):
            document["branch_schedule"]["position_balance"]["max_position_difference"] = 0
        _expect_error(self, stale_balance, "branch position balance drift", self.document)

        def wrong_totals(document):
            document["branch_schedule"]["position_balance"]["per_branch_totals"] = {
                "real": 18, "placebo": 17, "null": 16}
        _expect_error(self, wrong_totals, "branch totals are not 17/17/17", self.document)


class GuardEstimandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_locked()

    def test_guard_formulas_frozen_exactly(self):
        guards = self.document["guards"]
        self.assertEqual(guards, reg.GUARDS)
        formulas = guards["formulas"]
        self.assertEqual(formulas["delta_p_target_i"],
                         "p_target(real_i) - p_target(placebo_i)")
        self.assertEqual(formulas["delta_feasible_mass_i"],
                         "mass_SA(real_i) - mass_SA(placebo_i)")
        self.assertEqual(formulas["mass_SA"],
                         "sum of the normalized Choice probabilities over the frozen "
                         "authoritative pre-read feasible_set for receiver A")
        self.assertEqual(formulas["target_ok_i"], "delta_p_target_i >= 0.0")
        self.assertEqual(formulas["mass_ok_i"], "delta_feasible_mass_i >= -0.01")
        self.assertEqual(formulas["useful_uptake_i"],
                         "(H_real_i - H_placebo_i < 0) and target_ok_i and mass_ok_i")
        self.assertIn("accepted normalized vector", formulas["computation_rule"])
        self.assertIn("never remove an otherwise valid real/placebo pair",
                      formulas["reporting_rule"])
        self.assertIn("null remains excluded", formulas["reporting_rule"])
        self.assertEqual(guards["target_probability_delta"], 0.0)
        self.assertEqual(guards["feasible_set_mass_epsilon"], 0.01)
        self.assertIn("frozen authoritative pre-read feasible_set",
                      guards["reference_set"])

    def test_feasible_set_bindings_reconstruct(self):
        for event in self.document["events"]:
            with self.subTest(event=event["event_id"]):
                instance = reg._regenerate_instance(event["instance_id"])
                pre_read = event["pre_read"]
                authoritative = sorted(str(value)
                                       for value in instance.private_solutions["A"])
                clue_consistent = sorted(str(value) for value in
                                         instance.clue_consistent(instance.private_clues["A"]))
                self.assertEqual(authoritative, clue_consistent)
                self.assertEqual(pre_read["feasible_set"], authoritative)
                self.assertEqual(pre_read["feasible_set_hash"],
                                 jr.canonical_hash(authoritative))
                self.assertTrue(pre_read["feasible_set_verified"])
                self.assertEqual(pre_read["target_id"], instance.target)
                self.assertIn("clue-consistent", pre_read["feasible_set_source"])

    def test_feasible_set_drift_rejected(self):
        _expect_error(self, lambda d: d["events"][0]["pre_read"]["feasible_set"].pop(),
                      "feasible set drift", self.document)
        _expect_error(self, lambda d: d["events"][0]["pre_read"].__setitem__(
            "feasible_set_hash", "0" * 64), "feasible set hash drift", self.document)
        _expect_error(self, lambda d: d["events"][0]["pre_read"].__setitem__(
            "feasible_set_verified", False), "feasible set verification missing",
            self.document)
        _expect_error(self, lambda d: d["events"][0]["pre_read"].__setitem__(
            "target_id", "tampered-target"), "target id drift", self.document)

    def test_guard_formula_direction_and_threshold_drift_rejected(self):
        _expect_error(self, lambda d: d["guards"]["formulas"].__setitem__(
            "delta_p_target_i", "p_target(placebo_i) - p_target(real_i)"),
            "guard formula drift: delta_p_target_i", self.document)
        _expect_error(self, lambda d: d["guards"]["formulas"].__setitem__(
            "delta_feasible_mass_i", "mass_SA(placebo_i) - mass_SA(real_i)"),
            "guard formula drift: delta_feasible_mass_i", self.document)
        _expect_error(self, lambda d: d["guards"]["formulas"].__setitem__(
            "mass_SA", "sum over the receiver's own posterior"),
            "guard formula drift: mass_SA", self.document)
        _expect_error(self, lambda d: d["guards"]["formulas"].__setitem__(
            "target_ok_i", "delta_p_target_i <= 0.0"),
            "guard comparison drift: target_ok_i", self.document)
        _expect_error(self, lambda d: d["guards"]["formulas"].__setitem__(
            "mass_ok_i", "delta_feasible_mass_i >= 0.01"),
            "guard comparison drift: mass_ok_i", self.document)
        _expect_error(self, lambda d: d["guards"]["formulas"].__setitem__(
            "useful_uptake_i", "H_real_i < H_placebo_i"),
            "guard formula drift: useful_uptake_i", self.document)
        _expect_error(self, lambda d: d["guards"]["formulas"].__setitem__(
            "computation_rule", "compute from the raw vector"),
            "guard formula drift: computation_rule", self.document)
        _expect_error(self, lambda d: d["guards"].__setitem__(
            "reference_set", "the receiver's posterior"),
            "guard reference-set definition drift", self.document)
        _expect_error(self, lambda d: d["guards"].__setitem__(
            "feasible_set_mass_epsilon", 0.05), "guard thresholds drift", self.document)


class ExecutionPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_locked()
        cls.policy = cls.document["execution_policy"]

    def test_preflight_rules_frozen(self):
        items = " | ".join(self.policy["preflight"])
        for required in ("exact reviewed registration hash", "branch-order manifests",
                         "model, endpoint, codec, protocol key, retry and normalization",
                         "request, state, option and treatment hashes",
                         "credentials present but never printed or retained",
                         "registered journal/report paths absent",
                         "enforced request and cost caps",
                         "no provider call before every preflight check passes"):
            self.assertIn(required, items)

    def test_output_lifecycle_frozen(self):
        lifecycle = self.policy["output_lifecycle"]
        self.assertFalse(lifecycle["overwrite"])
        self.assertFalse(lifecycle["automatic_resume"])
        self.assertFalse(lifecycle["append_to_prior_replay_artifacts"])
        self.assertIn("new review and explicit authorization",
                      lifecycle["fresh_execution_after_partial_run"])
        self.assertFalse(lifecycle["raw_provider_envelopes_retained"])
        self.assertFalse(lifecycle["credentials_retained"])

    def test_journal_contract_frozen(self):
        journal = self.policy["journal"]
        self.assertEqual(journal["kind"], "append-only branch-attempt journal")
        self.assertEqual(journal["row_unit"],
                         "one durable row per logical (event_id, branch) execution")
        self.assertIn("fsync after every logical branch outcome", journal["durability"])
        self.assertEqual(journal["unique_key"], ["event_id", "branch"])
        self.assertEqual(journal["duplicate_key_policy"], "fail closed")
        fields = journal["row_fields"]
        for required in ("planned_branch_position", "actual_branch_position", "request_hash",
                         "state_hash", "protocol_key", "resolved_model", "physical_attempts",
                         "vector and normalization diagnostics", "validity", "usage",
                         "error_class", "cap counters"):
            self.assertIn(required, fields)
        self.assertIn("fail closed if actual", journal["branch_order_persistence"])
        self.assertIn("event-level real/placebo/null records", journal["report_grouping"])
        self.assertIn("remain observable", journal["partial_triplets"])

    def test_per_branch_rules_frozen(self):
        per_branch = self.policy["per_branch"]
        self.assertIn("maximum two", per_branch["retries"])
        self.assertTrue(per_branch["physical_attempts_include_retries"])
        self.assertEqual(per_branch["cost_reservation_usd"], 0.001032192)
        self.assertIn("0.001032192", per_branch["cost_reservation"])
        self.assertIn("does not cause the remaining branches",
                      per_branch["nonterminal_invalid"])
        self.assertIn("real and placebo are both valid", per_branch["complete_pair"])
        self.assertIn("not required for the primary", per_branch["null_validity"])
        self.assertEqual(per_branch["imputation"], "none")

    def test_terminal_and_provider_failure_rules_frozen(self):
        self.assertEqual(self.policy["immediate_terminal_stops"], [
            "request cap or cost cap before the next call",
            "model drift",
            "protocol-key drift",
            "request/state/option identity drift",
            "malformed or non-finite/negative/option-mismatched vectors",
            "hard normalization deviation above 0.05",
            "argmax shift after normalization",
            "output collision",
            "registration or source/treatment hash drift"])
        nonterminal = self.policy["nonterminal_invalidity"]
        self.assertIn("suspect sensitivity band", nonterminal["band"])
        self.assertIn("recorded invalid", nonterminal["policy"])
        self.assertIn("never", nonterminal["policy"])
        self.assertIn("continue unless", nonterminal["policy"])
        provider = self.policy["provider_failures"]
        self.assertIn("sanitized invalid branch row", provider["retry_exhaustion"])
        self.assertEqual(provider["consecutive_terminal_failure_stop"], 2)
        self.assertIn("successful valid response", provider["reset"])
        self.assertIn("never retain response bodies", provider["retention"])
        self.assertIn("planned/attempted/valid/invalid/unattempted",
                      self.policy["stopping_report"])
        self.assertIn("by branch, event, and form", self.policy["stopping_report"])

    def test_caps_reservation_and_unchanged_limits(self):
        caps = self.document["caps"]
        self.assertEqual(caps["planned_calls"]["jev"], 51)
        self.assertEqual(caps["planned_calls"]["ling"], 0)
        self.assertEqual(caps["physical_requests"], 153)
        self.assertEqual(caps["cost_cap_usd"], 1.0)
        self.assertEqual(caps["worst_case_cost_usd"], 0.052641792)
        self.assertEqual(caps["worst_case_next_call_cost_usd"], 0.001032192)
        self.assertEqual(round(caps["worst_case_call_cost_usd"] * 3, 12), 0.001032192)
        self.assertIn("0.001032192", caps["next_call_reservation_arithmetic"])

    def test_runner_policy_frozen(self):
        policy = self.document["runner_policy"]
        self.assertTrue(policy["required_before_live"])
        self.assertFalse(policy["runner_implemented"])
        self.assertEqual(policy["runner_source_files"], [])
        self.assertFalse(policy["adding_runner_authorizes_collection"])
        self.assertIn("source binding", policy["policy"])
        self.assertIn("re-locked", policy["policy"])
        self.assertIn("separate explicit authorization", policy["live_execution_rule"])

    def test_execution_policy_drift_rejected(self):
        cases = [
            (lambda d: d["execution_policy"]["output_lifecycle"].__setitem__("overwrite", True),
             "execution policy drift: output_lifecycle.overwrite"),
            (lambda d: d["execution_policy"]["output_lifecycle"].__setitem__(
                "automatic_resume", True), "execution policy drift: output_lifecycle.automatic_resume"),
            (lambda d: d["execution_policy"]["output_lifecycle"].__setitem__(
                "append_to_prior_replay_artifacts", True),
             "execution policy drift: output_lifecycle.append_to_prior_replay_artifacts"),
            (lambda d: d["execution_policy"]["journal"].__setitem__(
                "durability", "append and flush"),
             "execution policy drift: journal.durability"),
            (lambda d: d["execution_policy"]["journal"].__setitem__(
                "unique_key", ["event_id"]), "execution policy drift: journal.unique_key"),
            (lambda d: d["execution_policy"]["journal"].__setitem__(
                "duplicate_key_policy", "overwrite"),
             "execution policy drift: journal.duplicate_key_policy"),
            (lambda d: d["execution_policy"]["journal"]["row_fields"].remove(
                "planned_branch_position"),
             "execution policy drift: journal.row_fields.planned_branch_position"),
            (lambda d: d["execution_policy"]["journal"].__setitem__(
                "branch_order_persistence", "best effort"),
             "execution policy drift: journal.branch_order_persistence"),
            (lambda d: d["execution_policy"]["journal"].__setitem__(
                "partial_triplets", "dropped"),
             "execution policy drift: journal.partial_triplets"),
            (lambda d: d["execution_policy"]["per_branch"].__setitem__(
                "retries", "registered statuses, maximum five"),
             "execution policy drift: per_branch.retries"),
            (lambda d: d["execution_policy"]["per_branch"].__setitem__(
                "physical_attempts_include_retries", False),
             "execution policy drift: per_branch.physical_attempts_include_retries"),
            (lambda d: d["execution_policy"]["per_branch"].__setitem__(
                "cost_reservation_usd", 0.0001),
             "execution policy drift: per_branch.cost_reservation"),
            (lambda d: d["execution_policy"]["per_branch"].__setitem__(
                "nonterminal_invalid", "skip the rest of the event"),
             "execution policy drift: per_branch.nonterminal_invalid"),
            (lambda d: d["execution_policy"]["per_branch"].__setitem__(
                "complete_pair", "any one branch valid"),
             "execution policy drift: per_branch.complete_pair"),
            (lambda d: d["execution_policy"]["per_branch"].__setitem__(
                "null_validity", "required for the primary pair"),
             "execution policy drift: per_branch.null_validity"),
            (lambda d: d["execution_policy"]["per_branch"].__setitem__("imputation", "mean"),
             "execution policy drift: per_branch.imputation"),
            (lambda d: d["execution_policy"]["immediate_terminal_stops"].pop(),
             "terminal stop classes drift"),
            (lambda d: d["execution_policy"]["nonterminal_invalidity"].__setitem__(
                "policy", "reinterpreted as valid and the run continues"),
             "execution policy drift: nonterminal_invalidity.policy"),
            (lambda d: d["execution_policy"]["provider_failures"].__setitem__(
                "consecutive_terminal_failure_stop", 3),
             "execution policy drift: provider_failures.consecutive_terminal_failure_stop"),
            (lambda d: d["execution_policy"]["provider_failures"].__setitem__(
                "reset", "never"), "execution policy drift: provider_failures.reset"),
            (lambda d: d["execution_policy"]["provider_failures"].__setitem__(
                "retention", "retain response bodies"),
             "execution policy drift: provider_failures.retention"),
            (lambda d: d["execution_policy"].__setitem__("stopping_report", "counts by branch"),
             "execution policy drift: stopping_report"),
        ]
        for mutate, expected in cases:
            with self.subTest(expected=expected):
                _expect_error(self, mutate, expected, self.document)

    def test_runner_policy_drift_rejected(self):
        _expect_error(self, lambda d: d["runner_policy"].__setitem__(
            "runner_implemented", True),
            "runner must not be reported implemented before it exists", self.document)
        _expect_error(self, lambda d: d["runner_policy"].__setitem__(
            "runner_source_files", ["src/apart_incident_response/x.py"]),
            "runner source list must be empty until a runner exists", self.document)
        _expect_error(self, lambda d: d["runner_policy"].__setitem__(
            "adding_runner_authorizes_collection", True),
            "adding a runner must not authorize collection", self.document)
        _expect_error(self, lambda d: d["runner_policy"].__setitem__(
            "policy", "a runner may execute freely"),
            "runner policy must require source binding and a re-lock", self.document)
        _expect_error(self, lambda d: d["runner_policy"].__setitem__(
            "live_execution_rule", "live execution is forbidden until reviewed"),
            "runner live-execution rule drift", self.document)


class BranchJournalSchemaTests(unittest.TestCase):
    """The frozen future branch-journal contract and stop semantics."""

    def test_branch_row_fields_and_key_contract(self):
        journal = load_locked()["execution_policy"]["journal"]
        self.assertEqual(journal["unique_key"], ["event_id", "branch"])
        self.assertEqual(journal["duplicate_key_policy"], "fail closed")
        self.assertIn("planned_branch_position", journal["row_fields"])
        self.assertIn("actual_branch_position", journal["row_fields"])
        self.assertIn("both planned and actual branch order", journal["branch_order_persistence"])

    def test_nonterminal_invalid_continues_and_null_not_required(self):
        policy = load_locked()["execution_policy"]
        self.assertIn("does not cause the remaining branches",
                      policy["per_branch"]["nonterminal_invalid"])
        self.assertIn("real and placebo are both valid",
                      policy["per_branch"]["complete_pair"])
        self.assertIn("not required for the primary", policy["per_branch"]["null_validity"])
        self.assertEqual(policy["per_branch"]["imputation"], "none")

    def test_two_consecutive_provider_failure_rule(self):
        provider = load_locked()["execution_policy"]["provider_failures"]
        self.assertEqual(provider["consecutive_terminal_failure_stop"], 2)
        self.assertIn("successful valid response", provider["reset"])
        self.assertIn("sanitized invalid branch row", provider["retry_exhaustion"])

    def test_request_and_cost_cap_reservation_registered(self):
        caps = load_locked()["caps"]
        self.assertEqual(caps["physical_requests"], 153)
        self.assertEqual(caps["planned_calls"]["jev"], 51)
        self.assertEqual(caps["worst_case_next_call_cost_usd"],
                         round(caps["worst_case_call_cost_usd"] * 3, 12))

    def test_partial_triplet_missingness_semantics(self):
        policy = load_locked()["execution_policy"]
        self.assertIn("remain observable", policy["journal"]["partial_triplets"])
        report_rule = policy["stopping_report"]
        self.assertIn("planned/attempted/valid/invalid/unattempted", report_rule)
        self.assertIn("by branch, event, and form", report_rule)



if __name__ == "__main__":
    unittest.main()
