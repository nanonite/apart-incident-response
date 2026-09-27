import contextlib
import hashlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import jev_form_census as census
from apart_incident_response import jev_replication_preregistration as rep


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "jev-p03-form-capacity-audit.md"
CENSUS = REPO_ROOT / "runs" / "next-phase" / "jev-form-census-v1.json"
AUDIT = REPO_ROOT / rep.AUDIT_PATH
REGISTRATION = REPO_ROOT / rep.REGISTRATION_PATH
SCOPE = REPO_ROOT / census.SCOPE_PATH

#: Self-recorded content hash of the frozen census.
CENSUS_CONTENT_HASH = "ee0ba3a1714828b3e39834280a0a2eb7850f1cc0526463eb59d3bc4b7026fe14"

#: Frozen pins carried from the #200 artifacts and the P02 scope freeze.
AUDIT_CONTENT_HASH = "5242e9cfa35e3a77c54045475428dd617cf93cb16d464b55ad679adc35f80a83"
PREREGISTRATION_HASH = "ff186a066e6af093ecc383e668d948bdca7c1ef8f84b5752b88db47960a6ec6d"
SCOPE_CONTENT_HASH = "4cf5556c8e9c0811653e4b4d726a7b437d43bd63134cad0f80b84eb9148ec59b"
PRIOR_INSTANCE_ID_COUNT = 8945
PRIOR_INSTANCE_IDS_SHA256 = "429e8c54720d1a472d9e191fedc0510ade291680514f2dae4dff8c2a747607f9"

FORM_IDS = [
    "57ee9880f18bff4971516f9db820fd96dfb9eb86dab29e166025625e88a7b0c9",
    "a0e4ffd0c0b442207bf171422592a1f0b8f58556e2d44d8845d74ec23853f03d",
    "a95806c84d3a722d0ae240c637277373526956b57051cf006e5430706bf6e94c",
    "fc05e96360fa58fd2398727a886654d27d87fe561b2160002bcc01511f322562",
]
TEMPLATE_HASH = "951f7efa7b38b33c8fe6c6d90bf071e968ec4d86bfa2cb4f404a20aaa62a237a"

REQUIRED_PHRASES = [
    # task identity and offline scope
    "#204",
    "#201",
    "#159",
    "hypothesis:low",
    "no provider call",
    "nothing here authorizes collection",
    # census and closure
    "jev-form-census-v1",
    "ee0ba3a1714828b3e39834280a0a2eb7850f1cc0526463eb59d3bc4b7026fe14",
    "closed",
    "exhaustive enumeration",
    "finite generator state space",
    "(bit0, bit2)",
    "Residual unknowns",
    # pre-read hashes
    "pre_read_request_body_hash",
    "pre_read_state_hash",
    "branch_request_hashes",
    "branch_state_hashes",
    # dependence
    "Shared-template",
    "state.clues",
    "hash-distinct but not independent",
    "assumption-dependent",
    # capacity and overlap
    "Per-form capacity",
    "Seed/ID overlap report",
    "disjoint_from_all_prior_artifacts",
    "429e8c54720d1a472d9e191fedc0510ade291680514f2dae4dff8c2a747607f9",
    "current manifest coverage",
    "No new manifest",
    # design consequence
    "k = 4",
    "0.125",
    "descriptive/estimation only",
    "Guards never filter the estimate",
    "No planning-low effect-size prior",
    # checks and handoff
    "deterministic",
    "byte-for-byte",
    "P04 (#205)",
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
    "closure is unknown",
    "closure unproven",
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


class FormCensusTestCase(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text(encoding="utf-8")
        self.normalized = " ".join(self.text.split())
        self.normalized_lower = self.normalized.lower()
        self.census = json.loads(CENSUS.read_text(encoding="utf-8"))
        self.audit = json.loads(AUDIT.read_text(encoding="utf-8"))
        self.registration = json.loads(REGISTRATION.read_text(encoding="utf-8"))
        self.scope = json.loads(SCOPE.read_text(encoding="utf-8"))
        self.live_paths = [REPO_ROOT / path for path in
                           (rep.COLLECTION_JOURNAL, rep.COLLECTION_REPORT,
                            rep.REPLAY_JOURNAL, rep.REPLAY_REPORT)]
        self.live_before = [path.exists() for path in self.live_paths]

    def tearDown(self):
        self.assertEqual([path.exists() for path in self.live_paths],
                         self.live_before, "a live output path changed state")
        for path in self.live_paths:
            self.assertFalse(path.exists(),
                             "a replication live output must never appear offline")


class ContentHashTests(FormCensusTestCase):
    def test_census_content_hash_recomputes(self):
        recomputed = hashlib.sha256(
            json.dumps({key: value for key, value in self.census.items()
                        if key != "content_hash"},
                       sort_keys=True).encode()).hexdigest()
        self.assertEqual(recomputed, CENSUS_CONTENT_HASH)
        self.assertEqual(self.census["content_hash"], CENSUS_CONTENT_HASH)
        self.assertIn(CENSUS_CONTENT_HASH, self.normalized)

    def test_frozen_input_pins_still_match(self):
        self.assertEqual(self.audit["audit_content_hash"], AUDIT_CONTENT_HASH)
        self.assertEqual(self.registration["preregistration_hash"], PREREGISTRATION_HASH)
        self.assertEqual(self.scope["content_hash"], SCOPE_CONTENT_HASH)
        evidence = self.census["input_evidence"]
        self.assertEqual(evidence["audit_200"]["audit_content_hash"], AUDIT_CONTENT_HASH)
        self.assertEqual(evidence["registration_200"]["preregistration_hash"],
                         PREREGISTRATION_HASH)
        self.assertEqual(evidence["scope_freeze_p02"]["content_hash"], SCOPE_CONTENT_HASH)
        self.assertEqual(sha256_of(AUDIT), evidence["audit_200"]["file_sha256"])
        self.assertEqual(sha256_of(REGISTRATION), evidence["registration_200"]["file_sha256"])
        self.assertEqual(sha256_of(SCOPE), evidence["scope_freeze_p02"]["file_sha256"])
        for pin in (AUDIT_CONTENT_HASH, PREREGISTRATION_HASH, SCOPE_CONTENT_HASH):
            with self.subTest(pin=pin):
                self.assertIn(pin, self.normalized)


class FrozenArtifactTests(FormCensusTestCase):
    def test_frozen_artifacts_are_byte_unchanged(self):
        self.assertEqual(sha256_of(AUDIT),
                         "cb529cd61e0e662bfa19fc4998e89fa59a0bf0d63e14f77498035466d6bce89d")
        self.assertEqual(sha256_of(REGISTRATION),
                         "bddf46ed5fd87ec4da99532d645580a65e250d64639de80477002ff73d278f3c")

    def test_200_audit_still_rebuilds_byte_for_byte(self):
        rebuilt = rep.build_form_audit(REPO_ROOT)
        self.assertEqual(rep._render(rebuilt), AUDIT.read_text(encoding="utf-8"))
        self.assertEqual(rebuilt["audit_content_hash"], AUDIT_CONTENT_HASH)


class CensusStructureTests(FormCensusTestCase):
    def test_census_version_and_identity(self):
        self.assertEqual(self.census["census_version"], "jev-form-census-v1")
        self.assertEqual(self.census["issue"], "#204")
        self.assertEqual(self.census["parent_issue"], "#201")
        self.assertEqual(self.census["root_issue"], "#159")
        self.assertEqual(self.census["family"], "hypothesis")
        self.assertIs(self.census["offline_only"], True)
        self.assertIn("no collection", self.census["authorizes"])

    def test_form_capacity_k4_and_form_ids(self):
        capacity = self.census["form_capacity"]
        self.assertEqual(capacity["k"], 4)
        self.assertEqual(sorted(capacity["form_ids"]), FORM_IDS)
        self.assertEqual(capacity["form_set_hash"],
                         self.audit["form_capacity"]["form_set_hash"])
        self.assertEqual(capacity["instances_per_form"], 4)
        self.assertEqual(capacity["block_n"], 16)
        self.assertIn("per_form_capacity", capacity)
        for form in FORM_IDS:
            with self.subTest(form=form):
                self.assertIn(form, capacity["per_form_capacity"])
                entry = capacity["per_form_capacity"][form]
                self.assertEqual(entry["primary"]
                                 + entry["closure_probe"] + entry["confirmation"],
                                 entry["total_seeds"])

    def test_per_form_capacity_sums_to_window_sizes(self):
        capacity = self.census["form_capacity"]["per_form_capacity"]
        for name in ("primary", "closure_probe", "confirmation"):
            with self.subTest(window=name):
                self.assertEqual(sum(entry[name] for entry in capacity.values()), 512)

    def test_census_windows_match_the_200_audit(self):
        windows = self.census["windows"]
        self.assertEqual(windows["primary"]["base"], 85000)
        self.assertEqual(windows["primary"]["end"], 85511)
        self.assertEqual(windows["closure_probe"]["base"], 86000)
        self.assertEqual(windows["closure_probe"]["end"], 86511)
        self.assertEqual(windows["confirmation"]["base"], 87000)
        self.assertEqual(windows["confirmation"]["end"], 87511)
        for name in ("primary", "closure_probe", "confirmation"):
            with self.subTest(window=name):
                self.assertEqual(self.census["census"][name]["distinct_forms"], 4)
                self.assertEqual(sorted(self.census["census"][name]["forms"]), FORM_IDS)


class ClosureTests(FormCensusTestCase):
    def test_closure_status_closed_with_proof(self):
        closure = self.census["closure"]
        self.assertEqual(closure["status"], "closed")
        self.assertEqual(closure["basis"],
                         "generator-level exhaustive enumeration of the finite form space")
        self.assertIn("exhaustive enumeration", self.normalized)
        self.assertIn("finite generator state space", self.normalized)

    def test_observed_saturation_recorded(self):
        saturation = self.census["closure"]["observed_saturation"]
        self.assertEqual(saturation["primary_growth_checkpoints"],
                         [[32, 4], [64, 4], [128, 4], [256, 4], [512, 4]])
        self.assertEqual(saturation["closure_probe_distinct_forms"], 4)
        self.assertEqual(saturation["closure_probe_new_forms"], 0)
        self.assertEqual(saturation["all_windows_distinct_forms"], [4, 4, 4])

    def test_exhaustive_enumeration_covers_all_eight_targets(self):
        rows = self.census["closure"]["generator_argument"]["exhaustive_enumeration"]
        self.assertEqual(sorted(row["target_number"] for row in rows), list(range(8)))
        self.assertEqual(len(rows), 8)

    def test_exhaustive_enumeration_realizes_exactly_four_forms(self):
        argument = self.census["closure"]["generator_argument"]
        self.assertEqual(argument["distinct_forms_enumerated"], 4)
        self.assertEqual(argument["realized_forms"], 4)
        self.assertIs(argument["form_is_function_of_bit0_bit2"], True)
        self.assertEqual(argument["upper_bound_distinct_forms"], 4)
        self.assertEqual(sorted(argument["form_to_targets"]), FORM_IDS)

    def test_form_is_function_of_bit0_bit2(self):
        rows = self.census["closure"]["generator_argument"]["exhaustive_enumeration"]
        by_pair = {}
        for row in rows:
            by_pair.setdefault((row["bit0"], row["bit2"]), set()).add(row["form_id"])
        self.assertEqual(len(by_pair), 4)
        for pair, forms in by_pair.items():
            with self.subTest(pair=pair):
                self.assertEqual(len(forms), 1)

    def test_closure_residual_unknowns_stated(self):
        unknowns = self.census["closure"]["residual_unknowns"]
        self.assertIsInstance(unknowns, list)
        self.assertGreaterEqual(len(unknowns), 3)
        joined = " ".join(unknowns)
        self.assertIn("generator configuration", joined)
        self.assertIn("statistical independence", joined)
        self.assertIn("authorizes no collection", joined)
        self.assertIn("Residual unknowns", self.normalized)


class PreReadHashTests(FormCensusTestCase):
    def test_pre_read_hashes_cover_all_forms(self):
        per_form = self.census["pre_read_hashes"]["per_form"]
        self.assertEqual(sorted(per_form), FORM_IDS)

    def test_pre_read_body_hash_equals_form_id(self):
        for form, record in self.census["pre_read_hashes"]["per_form"].items():
            with self.subTest(form=form):
                self.assertEqual(record["pre_read_request_body_hash"], form)
                self.assertTrue(record["pre_read_state_hash"])
                self.assertEqual(set(record["branch_request_hashes"]),
                                 {"real", "placebo", "null"})
                self.assertEqual(set(record["branch_state_hashes"]),
                                 {"real", "placebo", "null"})
                self.assertTrue(record["representative_instance"])
                self.assertIn("real_claim", record)
                self.assertIn("placebo_claim", record)

    def test_pre_read_hashes_recompute_from_the_generator(self):
        for form, record in self.census["pre_read_hashes"]["per_form"].items():
            with self.subTest(form=form):
                instance = rep.instance_for("hypothesis", int(record["seed"]))
                self.assertEqual(instance.instance_id, record["representative_instance"])
                geometry = rep._instance_geometry(instance)
                hashes = rep.branch_hashes(instance, geometry["real_claim"],
                                           geometry["placebo_claim"])
                self.assertEqual(hashes["pre_read_request_body_hash"], form)
                self.assertEqual(hashes["pre_read_state_hash"], record["pre_read_state_hash"])
                self.assertEqual(hashes["branch_request_hashes"],
                                 record["branch_request_hashes"])
                self.assertEqual(hashes["branch_state_hashes"],
                                 record["branch_state_hashes"])


class DependenceTests(FormCensusTestCase):
    def test_shared_template_identical_except_state_clues(self):
        dependence = self.census["dependence_assessment"]
        self.assertIs(dependence["shared_template"], True)
        self.assertEqual(dependence["template_hash"], TEMPLATE_HASH)
        self.assertEqual(dependence["identical_except"], ["state.clues"])
        self.assertIn("state.clues", self.normalized)

    def test_form_cells_are_the_2x2_factorial(self):
        cells = self.census["dependence_assessment"]["form_cells"]
        self.assertEqual(len(cells), 4)
        pairs = sorted((cell["bit0"], cell["bit2"]) for cell in cells.values())
        self.assertEqual(pairs, [(0, 0), (0, 1), (1, 0), (1, 1)])

    def test_hash_distinct_not_independent_and_sign_flips_assumption_dependent(self):
        dependence = self.census["dependence_assessment"]
        self.assertIs(dependence["hash_distinct_not_independent"], True)
        consequence = dependence["consequence"]
        self.assertIn("assumption-dependent", consequence)
        self.assertIn("0.125", consequence)
        self.assertIn("descriptive/estimation only", consequence)
        self.assertIn("hash-distinct but not independent", self.normalized)


class OverlapTests(FormCensusTestCase):
    def test_no_overlap_with_prior_ids(self):
        overlap = self.census["seed_id_overlap"]
        self.assertEqual(overlap["selected_ids_overlapping_prior"], [])
        self.assertEqual(overlap["primary_vs_confirmation_overlap"], [])
        self.assertEqual(overlap["documented_seed_range_overlaps"], [])
        self.assertIs(overlap["disjoint_from_all_prior_artifacts"], True)

    def test_prior_id_set_reproduces_the_200_pin(self):
        prior = rep._prior_instance_ids(REPO_ROOT)
        self.assertEqual(prior["instance_id_count"], PRIOR_INSTANCE_ID_COUNT)
        self.assertEqual(prior["instance_ids_sha256"], PRIOR_INSTANCE_IDS_SHA256)
        overlap = self.census["seed_id_overlap"]
        self.assertEqual(overlap["prior_instance_id_count"], PRIOR_INSTANCE_ID_COUNT)
        self.assertEqual(overlap["prior_instance_ids_sha256"], PRIOR_INSTANCE_IDS_SHA256)
        self.assertIn(PRIOR_INSTANCE_IDS_SHA256, self.normalized)

    def test_selected_ids_match_the_200_audit_blocks(self):
        overlap = self.census["seed_id_overlap"]
        primary = [e["instance_id"] for e in self.audit["blocks"]["primary"]["manifest"]]
        confirmation = [e["instance_id"]
                        for e in self.audit["blocks"]["confirmation"]["manifest"]]
        self.assertEqual(overlap["selected_ids"]["primary"], primary)
        self.assertEqual(overlap["selected_ids"]["confirmation"], confirmation)
        self.assertEqual(len(primary), 16)
        self.assertEqual(len(confirmation), 16)


class ManifestCoverageTests(FormCensusTestCase):
    def test_current_manifest_coverage_rechecked_and_unchanged(self):
        coverage = self.census["current_manifest_coverage"]
        self.assertIs(coverage["rechecked_against_current_disk"], True)
        self.assertIs(coverage["prior_id_set_matches_200_pin"], True)
        self.assertEqual(coverage["new_manifests_since_200_audit"], [])
        self.assertEqual(coverage["missing_manifests_since_200_audit"], [])
        self.assertEqual(coverage["current_scan_source_count"], 119)
        self.assertEqual(coverage["audit_200_scan_source_count"], 119)
        self.assertIn("runs/container-isolation.json", coverage["inaccessible_manifests"])
        self.assertIn("No new manifest", self.normalized)

    def test_artifacts_outside_scan_scope_recorded(self):
        coverage = self.census["current_manifest_coverage"]
        outside = coverage["artifacts_outside_200_scan_scope"]
        self.assertIn("runs/next-phase/jev-p02-scope-freeze.json", outside)
        self.assertIn("docs/jev-p01-evidence-index.md", outside)


class DesignConsequenceTests(FormCensusTestCase):
    def test_k4_descriptive_only_is_recorded(self):
        consequence = self.census["design_consequence"]
        self.assertEqual(consequence["k"], 4)
        self.assertEqual(consequence["attainable_two_sided_sign_flip_floor"], "0.125")
        self.assertIs(consequence["floor_above_0_05"], True)
        self.assertEqual(consequence["classification"], "descriptive/estimation only")
        self.assertIn("descriptive only", consequence["fresh_seed_replication"])
        self.assertIn("k = 4", self.normalized)
        self.assertIn("0.125", self.normalized)

    def test_contract_phrases_are_present(self):
        for phrase in ("H0: Delta = 0", "H1: Delta < 0",
                       "equal-weight form mean of real-minus-placebo entropy",
                       "Guards never filter the estimate",
                       "No planning-low effect-size prior"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)


class DeterministicRebuildTests(FormCensusTestCase):
    def test_census_rebuilds_byte_for_byte(self):
        rebuilt = census.build_census(REPO_ROOT)
        self.assertEqual(rebuilt, self.census)
        self.assertEqual(census._render(rebuilt), CENSUS.read_text(encoding="utf-8"))

    def test_census_cli_verification_is_green(self):
        buffer = io.StringIO()
        calls = []

        def explode(*args, **kwargs):
            calls.append(1)
            raise AssertionError("provider call attempted offline")

        with patch("urllib.request.urlopen", explode):
            with contextlib.redirect_stdout(buffer):
                rc = census.main(["--repo-root", str(REPO_ROOT)])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        verification = json.loads(buffer.getvalue())
        self.assertTrue(verification["ok"], verification["failed"])
        self.assertEqual(verification["failed"], [])
        self.assertGreaterEqual(len(verification["checks"]), 30)
        self.assertEqual(verification["provider_calls"], 0)


class DocContentTests(FormCensusTestCase):
    def test_required_phrases_present(self):
        for phrase in REQUIRED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)

    def test_banned_overclaims_are_absent(self):
        for phrase in BANNED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase.lower(), self.normalized_lower)

    def test_handoff_records_next_step_and_no_successor_authorization(self):
        handoff = " ".join(self.text.split("## 8. Handoff")[1].split())
        self.assertIn("P04 (#205)", handoff)
        self.assertIn("classify design and plan discovery", handoff)
        self.assertIn("A predecessor closed as failed does not authorize successor execution",
                      handoff)
        self.assertIn("blocked by this task", handoff)

    def test_checks_section_records_the_offline_verification(self):
        checks = " ".join(self.text.split("## 7. Checks")[1].split("## 8.")[0].split())
        self.assertIn("provider_calls: 0", checks)
        self.assertIn("byte-for-byte", checks)
        self.assertIn("fail closed on drift", checks)
        self.assertIn("49/49", checks)


if __name__ == "__main__":
    unittest.main()
