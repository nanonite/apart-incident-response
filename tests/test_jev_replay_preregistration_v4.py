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


if __name__ == "__main__":
    unittest.main()
