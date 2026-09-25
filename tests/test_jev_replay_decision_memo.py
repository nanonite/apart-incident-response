import hashlib
import json
import unittest
from pathlib import Path

from apart_incident_response import jev_replay_inference_v5 as inf


REPO_ROOT = Path(__file__).resolve().parents[1]
MEMO = REPO_ROOT / "docs" / "jev-planning-low-replay-decision-memo.md"
ARTIFACT = REPO_ROOT / inf.DEFAULT_OUTPUT

INPUT_PATHS = {
    "journal": REPO_ROOT / inf.DEFAULT_JOURNAL,
    "report": REPO_ROOT / inf.DEFAULT_REPORT,
    "registration": REPO_ROOT / inf.DEFAULT_REGISTRATION,
    "inference": ARTIFACT,
}

#: Headings the memo must carry so the five levels stay distinguishable.
LEVEL_HEADINGS = [
    "### Level 1 — Structural communication need",
    "### Level 2 — Message emission",
    "### Level 3 — Verified exposure",
    "### Level 4 — Entropy reduction",
    "### Level 5 — Causal uptake under the registered real/placebo contrast",
]

REQUIRED_PHRASES = [
    # section structure
    "## 3. What is supported",
    "## 4. What is NOT supported",
    "## 7. Recommended next scientific phase",
    "## 8. Chainlink reconciliation",
    # registered result
    "-0.7775085127397289",
    "0.03125",
    "-1.1722041593435226",
    "-0.38281286613593507",
    "17/17",
    "1/4/4/1/4/3",
    # scope wording
    "six frozen planning-low prompt forms",
    "the paid Ling route",
    "experimental unit is the prompt form",
    "k = 6",
    "0.203-bit MDE",
    # prohibition of overclaiming
    "No population-level claim",
    "No cross-family claim",
    "No calibration claim",
    "No instance-level claim",
    "No unique-information claim",
    "No generalization beyond these six frozen forms",
    "never 17 independent units",
    "No family sweep, no post-hoc winner",
    "gross totals are never described as unique delivered information",
    "not a fresh confirmation",
    "post-read correlation is never treated as uptake",
    # guards and sensitivity
    "filtered_primary_estimate: false",
    "conclusion_changed` | false at every threshold",
    # next phase
    "new form-capacity audit",
    "Fresh seeds",
    "Family-level multiplicity control",
    "A new registration",
    "Do not sweep families and select a winner post hoc",
    "Seed disjointness alone is never sufficient",
    # reconciliation
    "#159 — remains **open**",
    "left **draft/offline**",
    "**not reopened**",
]

#: Affirmative overclaims that must never appear anywhere in the memo.
BANNED_PHRASES = [
    "establishes causality",
    "proves causality",
    "proves causation",
    "demonstrates causation",
    "population-representative",
    "generalizes to",
    "generalises to",
    "calibration was verified",
    "the model is calibrated",
    "instance-level p-value",
    "instance-level significance",
    "significant at the instance level",
    "significant at an instance level",
    "bits were delivered to the receiver",
    "unique delivered information of",
    "unique delivered information is",
    "all six families",
    "the winning family",
    "selected the winning family",
    "confirms the effect for every family",
    "holds outside planning-low",
    "replicates across families",
]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MemoTestCase(unittest.TestCase):
    def setUp(self):
        self.text = MEMO.read_text(encoding="utf-8")
        # phrases are matched against whitespace-normalized text so that
        # markdown line wrapping cannot hide a required statement
        self.normalized = " ".join(self.text.split())
        self.normalized_lower = self.normalized.lower()
        self.artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        self.before = {name: sha256_of(path) for name, path in INPUT_PATHS.items()}

    def tearDown(self):
        self.assertEqual({name: sha256_of(path)
                          for name, path in INPUT_PATHS.items()}, self.before,
                         "a frozen replay-v5 input changed during the test")


class HashIntegrityTests(MemoTestCase):
    def test_recomputed_hashes_match_the_pins(self):
        self.assertEqual(sha256_of(INPUT_PATHS["journal"]), inf.PINNED["journal_sha256"])
        self.assertEqual(sha256_of(INPUT_PATHS["report"]), inf.PINNED["report_sha256"])
        self.assertEqual(sha256_of(INPUT_PATHS["registration"]),
                         inf.PINNED["registration_file_sha256"])
        self.assertEqual(sha256_of(INPUT_PATHS["inference"]),
                         "b892a8d514623aca17b83f17a59e9e699d773b48f059b7b954b6239ff7d6f2ce")

    def test_memo_quotes_every_pinned_hash(self):
        for value in (inf.PINNED["journal_sha256"], inf.PINNED["report_sha256"],
                      inf.PINNED["registration_file_sha256"],
                      inf.PINNED["registration_hash"],
                      "b892a8d514623aca17b83f17a59e9e699d773b48f059b7b954b6239ff7d6f2ce"):
            with self.subTest(hash=value):
                self.assertIn(value, self.normalized)

    def test_registration_content_hash_recomputes(self):
        document = json.loads(INPUT_PATHS["registration"].read_text(encoding="utf-8"))
        recomputed = hashlib.sha256(
            json.dumps({key: value for key, value in document.items()
                        if key != "preregistration_hash"}, sort_keys=True).encode()).hexdigest()
        self.assertEqual(recomputed, inf.PINNED["registration_hash"])
        self.assertEqual(document["preregistration_hash"], inf.PINNED["registration_hash"])
        self.assertEqual(self.artifact["registration_hash"], inf.PINNED["registration_hash"])

    def test_artifact_records_the_same_input_hashes(self):
        inputs = self.artifact["inputs"]
        self.assertEqual(inputs["journal"]["sha256"], inf.PINNED["journal_sha256"])
        self.assertEqual(inputs["report"]["sha256"], inf.PINNED["report_sha256"])
        self.assertEqual(inputs["registration"]["sha256"],
                         inf.PINNED["registration_file_sha256"])

    def test_memo_numbers_match_the_analysis_artifact(self):
        primary = self.artifact["primary"]
        self.assertIn(repr(primary["estimate"]), self.text)
        self.assertIn(repr(primary["estimate"]), self.text)
        self.assertIn(f"{primary['sign_flip']['p_value']}", self.text)
        for bound in primary["t_interval_975"]:
            self.assertIn(repr(bound), self.text)
        self.assertEqual(primary["k"], 6)
        self.assertTrue(primary["criterion_met"])


class FiveLevelTests(MemoTestCase):
    def test_all_five_levels_present_and_distinct(self):
        for heading in LEVEL_HEADINGS:
            with self.subTest(heading=heading):
                self.assertIn(heading, self.text)

    def test_each_level_carries_a_determination(self):
        for level in range(1, 6):
            start = self.text.index(f"### Level {level} ")
            end = self.text.find("### Level ", start + 1)
            section = self.text[start:end if end != -1 else None]
            with self.subTest(level=level):
                self.assertIn("**Status:", section)

    def test_supported_and_not_supported_sections(self):
        supported = " ".join(
            self.text.split("## 3. What is supported")[1].split("## 4.")[0].split())
        not_supported = " ".join(
            self.text.split("## 4. What is NOT supported")[1].split("## 5.")[0].split())
        self.assertIn("-0.7775085127397289", supported)
        self.assertIn("17/17", supported)
        self.assertIn("No population-level claim", not_supported)
        self.assertIn("No cross-family claim", not_supported)
        self.assertIn("No calibration claim", not_supported)
        self.assertIn("No instance-level claim", not_supported)
        self.assertIn("No unique-information claim", not_supported)


class ScopeWordingTests(MemoTestCase):
    def test_required_scope_phrases_present(self):
        for phrase in REQUIRED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)

    def test_scope_section_states_both_conditions(self):
        scope = " ".join(self.text.split("## 6. Claim scope")[1].split("## 7.")[0].split())
        self.assertIn("conditional on the six frozen planning-low prompt forms", scope)
        self.assertIn("paid Ling route", scope)
        self.assertIn("No population-level, cross-family, calibration, instance-level "
                      "or unique-information claim is made or implied", scope)

    def test_conditional_conclusion_wording(self):
        self.assertIn("conditional on the six frozen planning-low prompt forms",
                      self.normalized)
        self.assertIn("paid Ling route that generated the messages", self.normalized)


class OverclaimProhibitionTests(MemoTestCase):
    def test_banned_overclaims_are_absent(self):
        lowered = self.normalized_lower
        for phrase in BANNED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase.lower(), lowered)

    def test_gross_and_unique_information_are_distinguished(self):
        self.assertIn("26.9443625123", self.normalized)
        self.assertIn("9.5097750043", self.normalized)
        self.assertIn("6 treatments", self.normalized)
        self.assertIn("not bits delivered", self.normalized)

    def test_no_post_hoc_family_selection(self):
        self.assertIn("Do not sweep families and select a winner post hoc", self.normalized)
        self.assertIn("no family, form, rung or seed may be selected post hoc",
                      self.normalized)

    def test_next_phase_requires_audit_fresh_seeds_and_multiplicity(self):
        phase = " ".join(self.text.split("## 7. Recommended next scientific phase")[1].split())
        self.assertIn("Form-capacity audit first", phase)
        self.assertIn("Fresh seeds", phase)
        self.assertIn("Family-level multiplicity control", phase)
        self.assertIn("A new registration", phase)
        self.assertIn("0a81e400", phase)


class ReconciliationTests(MemoTestCase):
    def test_reconciliation_section_records_the_statuses(self):
        section = self.text.split("## 8. Chainlink reconciliation")[1]
        self.assertIn("#197", section)
        self.assertIn("#188", section)
        self.assertIn("#198", section)
        self.assertIn("#159 — remains **open**", section)
        self.assertIn("left **draft/offline**", section)
        self.assertIn("**not reopened**", section)

    def test_memo_makes_no_execution_authorization_claim(self):
        self.assertIn("nothing here authorizes further collection", self.normalized)
        self.assertIn("no provider call", self.normalized_lower)


if __name__ == "__main__":
    unittest.main()
