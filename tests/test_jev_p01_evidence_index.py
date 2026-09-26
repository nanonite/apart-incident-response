import contextlib
import hashlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import jev_replay_inference_v5 as inf
from apart_incident_response import jev_replication_preregistration as rep


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "jev-p01-evidence-index.md"
INFERENCE = REPO_ROOT / inf.DEFAULT_OUTPUT
AUDIT = REPO_ROOT / rep.AUDIT_PATH
REGISTRATION = REPO_ROOT / rep.REGISTRATION_PATH
MEMO = REPO_ROOT / "docs" / "jev-planning-low-replay-decision-memo.md"

#: sha256 of every frozen input listed in section 1 of the evidence index.
INPUT_SHA256 = {
    "runs/epic-126/replay-v5/jev-choice-replay-inference-v5.json":
        "b892a8d514623aca17b83f17a59e9e699d773b48f059b7b954b6239ff7d6f2ce",
    "runs/epic-126/replay-v5/jev-choice-replay-v5.jsonl":
        "5e9f7322bdb29baf16b18f9b4f4181e9a88ad454e0394ea379e4cdea29b1fede",
    "runs/epic-126/replay-v5/jev-choice-replay-report-v5.json":
        "0ec84446d697bca91c25e155b3cd61f43b4e7706e6df185ea08c3685a8f88310",
    "runs/epic-126/replay-v5/jev-choice-replay-preregistration-v5.json":
        "3c02f8bb44c11d6edd050daf32950e3cf8365f79638e92d46181df764945ddd7",
    "docs/jev-planning-low-replay-decision-memo.md":
        "93215d4cafc20114d7ece32d0e3b1d9c6d28a8ced4236c577fe24ac90775c018",
    "runs/epic-126/jev-board-necessity-selection.json":
        "78dba91926c0134c772c85020ab1a503c8785ddbb34031528a0231297641627a",
    "runs/epic-126/replication/jev-replication-form-audit-v1.json":
        "cb529cd61e0e662bfa19fc4998e89fa59a0bf0d63e14f77498035466d6bce89d",
    "runs/epic-126/replication/jev-replication-preregistration-v1.json":
        "bddf46ed5fd87ec4da99532d645580a65e250d64639de80477002ff73d278f3c",
    "docs/jev-replication-preregistration.md":
        "fec0831bbec1cbb32dd7599a7cb1ac6bf19dacee02effbc319a0e608bc41169d",
    "src/apart_incident_response/jev_replication_preregistration.py":
        "d91c0e3ad13fc3049240ab76f13214997872681485ef24b60627763f7ec06133",
    "tests/test_jev_replication_preregistration.py":
        "ce9363676d87c891d7dab8edd020f32a6c3203940f48753c557212f946a3b9ca",
    "docs/jev-discovery-confirmation-plan.md":
        "501e21b6dea760371b0bf368046d8bacd203f6b92f0af754a7955d1f738677f7",
}

#: Content pins recorded inside the frozen artifacts.
AUDIT_CONTENT_HASH = "5242e9cfa35e3a77c54045475428dd617cf93cb16d464b55ad679adc35f80a83"
PREREGISTRATION_HASH = "ff186a066e6af093ecc383e668d948bdca7c1ef8f84b5752b88db47960a6ec6d"
V5_REGISTRATION_HASH = "0a81e400f598d16742301d7c07cbaf5398fa861b4fa1701c15405391ab4f6d15"

#: The four frozen hypothesis prompt-form ids from the #200 audit.
HYPOTHESIS_FORM_IDS = [
    "57ee9880f18bff4971516f9db820fd96dfb9eb86dab29e166025625e88a7b0c9",
    "a0e4ffd0c0b442207bf171422592a1f0b8f58556e2d44d8845d74ec23853f03d",
    "a95806c84d3a722d0ae240c637277373526956b57051cf006e5430706bf6e94c",
    "fc05e96360fa58fd2398727a886654d27d87fe561b2160002bcc01511f322562",
]

REQUIRED_PHRASES = [
    # task identity and offline scope
    "#202",
    "#201",
    "#159",
    "hypothesis:low",
    "no provider call",
    "nothing here authorizes collection",
    # planning-low conditional result, preserved
    "-0.7775085127397289",
    "0.03125",
    "-1.1722041593435226",
    "-0.38281286613593507",
    "17/17",
    "1/4/4/1/4/3",
    "15/17",
    "filtered_primary_estimate: false",
    "excluded_from_primary: 0",
    "six frozen planning-low prompt forms",
    "paid Ling route",
    "not used as a prior",
    # guard failures preserved
    "planning-000124f9:message-B-0",
    "planning-00012511:message-B-0",
    "55968fe191b18f37d1951d71f777115f753e0b9a6da526015f3db5251a1383eb",
    "target_ok: true",
    "mass_ok: false",
    "useful_uptake: false",
    # contract reconciliation
    "H0: Delta = 0; H1: Delta < 0",
    "equal-weight mean of the within-form means of `H_real - H_placebo`",
    "never used to filter",
    "never impute missing pairs",
    "events_are_independent_units: false",
    "0.125",
    "estimation and descriptive study",
    # pilot identification
    "outcome-blind",
    "closed at **k = 4**",
    "85000",
    "87000",
    "estimation and descriptive study",
    "draft_pending_review",
    "live_collection_authorized: false",
    "lock_does_not_imply_approval: true",
    "may never be pooled with the primary block",
    # new-version log
    "minimum_forms_for_confirmatory: 5",
    "five_form_fallback",
    "below_five_forms: replay-coverage failure",
    "t(0.975, k−1) × SD_between / √k",
    "0.30754",
    "interval half-width",
    "not a power-based MDE",
    "six-form confirmatory minimum",
    "not by modifying the frozen draft",
    # checks and handoff
    "49/49",
    "provider_calls: 0",
    "P02 (#203)",
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
]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


class EvidenceIndexTestCase(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text(encoding="utf-8")
        # phrases are matched against whitespace-normalized text so that
        # markdown line wrapping cannot hide a required statement
        self.normalized = " ".join(self.text.split())
        self.normalized_lower = self.normalized.lower()
        self.inference = json.loads(INFERENCE.read_text(encoding="utf-8"))
        self.audit = json.loads(AUDIT.read_text(encoding="utf-8"))
        self.registration = json.loads(REGISTRATION.read_text(encoding="utf-8"))
        self.before = {relative: sha256_of(REPO_ROOT / relative)
                       for relative in INPUT_SHA256}
        self.live_paths = [REPO_ROOT / path for path in
                           (rep.COLLECTION_JOURNAL, rep.COLLECTION_REPORT,
                            rep.REPLAY_JOURNAL, rep.REPLAY_REPORT)]
        self.live_before = [path.exists() for path in self.live_paths]

    def tearDown(self):
        self.assertEqual({relative: sha256_of(REPO_ROOT / relative)
                          for relative in INPUT_SHA256}, self.before,
                         "a frozen evidence input changed during the test")
        self.assertEqual([path.exists() for path in self.live_paths],
                         self.live_before, "a live output path changed state")
        for path in self.live_paths:
            self.assertFalse(path.exists(),
                             "a replication live output must never appear offline")


class HashIntegrityTests(EvidenceIndexTestCase):
    def test_recomputed_hashes_match_the_index(self):
        for relative, expected in INPUT_SHA256.items():
            with self.subTest(path=relative):
                self.assertEqual(sha256_of(REPO_ROOT / relative), expected)
                self.assertIn(expected, self.normalized)

    def test_memo_pins_still_match_recomputed_hashes(self):
        self.assertEqual(sha256_of(REPO_ROOT / inf.DEFAULT_JOURNAL),
                         inf.PINNED["journal_sha256"])
        self.assertEqual(sha256_of(REPO_ROOT / inf.DEFAULT_REPORT),
                         inf.PINNED["report_sha256"])
        self.assertEqual(sha256_of(REPO_ROOT / inf.DEFAULT_REGISTRATION),
                         inf.PINNED["registration_file_sha256"])
        self.assertEqual(sha256_of(INFERENCE),
                         "b892a8d514623aca17b83f17a59e9e699d773b48f059b7b954b6239ff7d6f2ce")

    def test_v5_registration_content_hash_recomputes(self):
        document = json.loads(inf.DEFAULT_REGISTRATION.read_text(encoding="utf-8"))
        recomputed = hashlib.sha256(
            json.dumps({key: value for key, value in document.items()
                        if key != "preregistration_hash"},
                       sort_keys=True).encode()).hexdigest()
        self.assertEqual(recomputed, V5_REGISTRATION_HASH)
        self.assertEqual(document["preregistration_hash"], V5_REGISTRATION_HASH)
        self.assertEqual(self.inference["registration_hash"], V5_REGISTRATION_HASH)
        self.assertIn(V5_REGISTRATION_HASH, self.normalized)

    def test_200_content_pins_match_the_frozen_artifacts(self):
        self.assertEqual(self.audit["audit_content_hash"], AUDIT_CONTENT_HASH)
        self.assertEqual(self.registration["preregistration_hash"],
                         PREREGISTRATION_HASH)
        self.assertEqual(self.registration["audit_binding"]["audit_content_hash"],
                         AUDIT_CONTENT_HASH)
        recomputed = hashlib.sha256(
            json.dumps({key: value for key, value in self.registration.items()
                        if key != "preregistration_hash"},
                       sort_keys=True).encode()).hexdigest()
        self.assertEqual(recomputed, PREREGISTRATION_HASH)
        for pin in (AUDIT_CONTENT_HASH, PREREGISTRATION_HASH):
            with self.subTest(pin=pin):
                self.assertIn(pin, self.normalized)


class PlanningLowPreservationTests(EvidenceIndexTestCase):
    def test_primary_result_numbers_match_the_inference_artifact(self):
        primary = self.inference["primary"]
        self.assertIn(repr(primary["estimate"]), self.normalized)
        self.assertIn(repr(primary["sign_flip"]["p_value"]), self.normalized)
        for bound in primary["t_interval_975"]:
            self.assertIn(repr(bound), self.normalized)
        self.assertEqual(primary["k"], 6)
        self.assertTrue(primary["criterion_met"])
        self.assertTrue(primary["direction_met"])
        self.assertEqual(primary["sign_flip"]["permutations"], 64)
        self.assertEqual(self.inference["missingness"]["complete_pairs"], 17)
        self.assertEqual(
            self.inference["missingness"]["complete_pairs_by_form"],
            {"0a3349e16c9633b4d559dfbb808d1e50d0446d8f92160a0feddd1e37299796ee": 1,
             "1c1d9f6b5c9271ad8e74de180c3e397e1369d326564c9a08ba0840eff0b148fc": 4,
             "2954f5684bcd198ed8eea0956cf573f93cde628d6dfa7472fc57f556bd089b2c": 4,
             "3196a8d69f844702db012816def7d7866e7416e9fadc9f28eaa7f12ac16a8569": 1,
             "55968fe191b18f37d1951d71f777115f753e0b9a6da526015f3db5251a1383eb": 4,
             "ce847ac53b6e344103bc775aede5212b2be6fbd568dc1d85fd24cbde8f585222": 3})

    def test_guard_failures_match_the_inference_artifact(self):
        events = self.inference["guards"]["events"]
        self.assertEqual(len(events), 17)
        failures = [event for event in events
                    if not event["mass_ok"] or not event["useful_uptake"]]
        self.assertEqual(len(failures), 2)
        self.assertEqual({event["event_id"] for event in failures},
                         {"planning-000124f9:message-B-0",
                          "planning-00012511:message-B-0"})
        for event in failures:
            self.assertTrue(event["target_ok"])
            self.assertFalse(event["mass_ok"])
            self.assertFalse(event["useful_uptake"])
            self.assertEqual(event["form"],
                             "55968fe191b18f37d1951d71f777115f753e0b9a6da526015f3db5251a1383eb")
        uptake = self.inference["registered_causal_uptake"]
        self.assertTrue(uptake["criterion_met"])
        self.assertFalse(uptake["guards_filtered_primary"])
        self.assertTrue(uptake["guards_reported_separately"])

    def test_sensitivity_and_null_checks_are_preserved(self):
        grid = self.inference["normalization"]["sensitivity"]["grid"]
        self.assertEqual([entry["threshold"] for entry in grid],
                         [1e-06, 0.01, 0.03, 0.05])
        for entry in grid:
            with self.subTest(threshold=entry["threshold"]):
                self.assertFalse(entry["conclusion_changed"])
                self.assertTrue(entry["criterion_met"])
        for threshold in ("1e-6", "0.01", "0.03", "0.05"):
            with self.subTest(threshold=threshold):
                self.assertIn(threshold, self.normalized)
        null_checks = self.inference["null_manipulation_checks"]
        self.assertEqual(null_checks["real_below_null_events"], 17)
        self.assertEqual(null_checks["placebo_below_null_events"], 6)
        self.assertIn(repr(round(null_checks["mean_real_minus_null"], 6)),
                      self.normalized)
        self.assertIn(repr(round(null_checks["mean_placebo_minus_null"], 6)),
                      self.normalized)

    def test_scope_wording_is_conditional(self):
        scope = " ".join(self.text.split("## 2. Planning-low conditional result")[1]
                         .split("## 3.")[0].split())
        self.assertIn("conditional on the six frozen planning-low prompt forms", scope)
        self.assertIn("paid Ling route that generated the messages", scope)
        self.assertIn("historical evidence outside any new confirmation set", scope)
        self.assertIn("not used as a prior, power assumption or effect-size guarantee", scope)


class ContractReconciliationTests(EvidenceIndexTestCase):
    def test_required_contract_phrases_present(self):
        for phrase in REQUIRED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)

    def test_hypothesis_and_estimand_match_the_frozen_registration(self):
        self.assertEqual(self.registration["family"], "hypothesis")
        self.assertEqual(self.registration["treatment"]["complexity"], "low")
        self.assertEqual(self.registration["estimand"]["directional_prediction"],
                         "Delta < 0")
        self.assertIn("equal-weight mean", self.registration["estimand"]["primary"])
        self.assertIs(self.registration["estimand"]["events_are_independent_units"],
                      False)
        self.assertEqual(self.registration["inference_plan"]["imputation"],
                         "never impute missing pairs")
        self.assertIn("never used to filter",
                      self.registration["inference_plan"]["guards"]["reporting"])
        self.assertIn("Delta < 0", self.normalized)
        self.assertIn("never impute missing pairs", self.normalized)

    def test_no_planning_low_prior_is_registered(self):
        selection = self.registration["family_selection"]
        self.assertIs(selection["outcome_blind"], True)
        self.assertEqual(selection["consulted_prior_live_outcomes"], [])
        self.assertIn("planning-low estimate and p-value are not used as a prior",
                      selection["anti_prior_statement"])
        self.assertIn("not used as a prior",
                      self.registration["inference_plan"]["mde"]["not_a_prior"])


class PilotIdentificationTests(EvidenceIndexTestCase):
    def test_pilot_facts_match_the_frozen_audit(self):
        capacity = self.audit["form_capacity"]
        self.assertEqual(capacity["k_max"], 4)
        self.assertEqual(capacity["space"], "closed")
        self.assertEqual(capacity["primary_distinct_forms"], 4)
        self.assertEqual(capacity["new_forms_in_closure_probe"], 0)
        self.assertEqual(capacity["form_ids"], HYPOTHESIS_FORM_IDS)
        self.assertEqual(capacity["primary_growth_checkpoints"],
                         [[32, 4], [64, 4], [128, 4], [256, 4], [512, 4]])
        for form in HYPOTHESIS_FORM_IDS:
            with self.subTest(form=form):
                self.assertIn(form, self.normalized)

    def test_block_windows_and_sizes_match_the_frozen_audit(self):
        windows = self.audit["windows"]
        self.assertEqual(windows["primary"]["base"], 85000)
        self.assertEqual(windows["confirmation"]["base"], 87000)
        for block in ("primary", "confirmation"):
            manifest = self.audit["blocks"][block]["manifest"]
            self.assertEqual(len(manifest), 16)
            counts = {}
            for entry in manifest:
                counts[entry["prompt_form_id"]] = \
                    counts.get(entry["prompt_form_id"], 0) + 1
            self.assertEqual(counts, {form: 4 for form in HYPOTHESIS_FORM_IDS})
        self.assertIs(self.audit["disjointness"]["disjoint_from_all_prior_artifacts"],
                      True)
        self.assertEqual(self.audit["disjointness"]["selected_ids_overlapping_prior"], [])
        self.assertEqual(self.audit["disjointness"]["primary_vs_confirmation_overlap"], [])

    def test_descriptive_only_status_is_recorded(self):
        plan = self.registration["inference_plan"]
        self.assertEqual(plan["attainable_two_sided_floor_by_k"]["4"], "0.125")
        self.assertEqual(plan["k_max_from_audit"], 4)
        self.assertIn("no dichotomous rejection", plan["audit_finding"])
        self.assertIn("estimation and descriptive study", plan["consequence"])
        self.assertIn("0.125", self.normalized)
        self.assertIn("no significance-style claim", self.normalized)

    def test_draft_gate_state_is_recorded(self):
        self.assertEqual(self.registration["status"], "draft_pending_review")
        self.assertIs(self.registration["live_collection_authorized"], False)
        self.assertIs(self.registration["lock_does_not_imply_approval"], True)
        self.assertIs(self.registration["approval"]["approved"], False)
        self.assertIn("draft_pending_review", self.normalized)
        self.assertIn("this task authorizes no live run", self.normalized)


class NewVersionLogTests(EvidenceIndexTestCase):
    def test_five_form_wording_is_logged(self):
        log = " ".join(self.text.split("## 5. Log for a new registration version")[1]
                       .split("## 6.")[0].split())
        self.assertIn("minimum_forms_for_confirmatory: 5", log)
        self.assertIn("five_form_fallback", log)
        self.assertIn("below_five_forms: replay-coverage failure", log)
        self.assertIn("six-form confirmatory minimum", log)
        self.assertIn("k = 6 floor", log)
        self.assertIn("0.03125", log)

    def test_half_width_mde_mismatch_is_logged(self):
        log = " ".join(self.text.split("## 5. Log for a new registration version")[1]
                       .split("## 6.")[0].split())
        self.assertIn("t(0.975, k−1) × SD_between / √k", log)
        self.assertIn("0.30754", log)
        self.assertIn("interval half-width", log)
        self.assertIn("not a power-based MDE", log)
        self.assertIn("80%", log)
        self.assertIn("unattainable", log)

    def test_frozen_json_is_not_edited(self):
        self.assertIn("not by modifying the frozen draft", self.normalized)
        self.assertIn("The frozen #200 JSON is **not** edited", self.normalized)


class ChecksAndHandoffTests(EvidenceIndexTestCase):
    def test_checks_section_records_the_offline_preflight(self):
        checks = " ".join(self.text.split("## 6. Checks")[1].split("## 7.")[0].split())
        self.assertIn("49/49", checks)
        self.assertIn("provider_calls: 0", checks)
        self.assertIn("fail closed on drift", checks)
        self.assertIn("byte-for-byte", checks)

    def test_handoff_section_records_next_step_and_no_successor_authorization(self):
        handoff = " ".join(self.text.split("## 7. Handoff")[1].split())
        self.assertIn("P02 (#203)", handoff)
        self.assertIn("freeze next-family scope and artifact inventory", handoff)
        self.assertIn("no live outcome used to choose forms or seeds", handoff)
        self.assertIn("A predecessor closed as failed does not authorize successor execution",
                      handoff)
        self.assertIn("blocked by this task", handoff)

    def test_banned_overclaims_are_absent(self):
        for phrase in BANNED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase.lower(), self.normalized_lower)


class OfflineVerificationTests(EvidenceIndexTestCase):
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

    def test_offline_preflight_is_call_free_and_green(self):
        rc, output, calls = self.run_cli(["--repo-root", str(REPO_ROOT)])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        docs = parse_docs(output)
        self.assertTrue(docs[0]["ok"], docs[0]["failed"])
        self.assertEqual(docs[0]["failed"], [])
        self.assertEqual(len(docs[0]["checks"]), 49)
        self.assertFalse(docs[0]["live_collection_authorized"])
        self.assertEqual(docs[1]["provider_calls"], 0)
        self.assertEqual(docs[1]["status"], "offline")

    def test_live_path_is_refused_while_draft_with_zero_calls(self):
        rc, output, calls = self.run_cli(["--repo-root", str(REPO_ROOT), "--live",
                                          "--approval", "some-reference"])
        self.assertEqual(rc, 2)
        self.assertEqual(calls, [])
        blocked = parse_docs(output)[-1]
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["provider_calls"], 0)
        self.assertFalse(blocked["live_collection_authorized"])


if __name__ == "__main__":
    unittest.main()
