import contextlib
import hashlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import jev_p04_design_classification as p04
from apart_incident_response import jev_p05_discovery_lock as p05


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "jev-discovery-authorization-gate.md"
LOCK = REPO_ROOT / "runs" / "next-phase" / "jev-p05-discovery-lock-v1.json"
LOCK_REVIEW = REPO_ROOT / "runs" / "next-phase" / "jev-p05-discovery-lock-review-v1.json"
REGISTRATION = REPO_ROOT / "runs" / "next-phase" / "jev-p04-discovery-registration-v1.json"
REG_REVIEW = REPO_ROOT / "runs" / "next-phase" / "jev-p04-discovery-registration-review-v1.json"
AUTH_RECORD = REPO_ROOT / "runs" / "next-phase" / "jev-discovery-authorization-record-v1.json"

LOCK_HASH = "9de4a61f9d46c47b55bbe7b8da9903c677c6461bf4af353007277835ed6a18b3"
REGISTRATION_HASH = "6fa6149770b620cd3a026a6415f8e4d97e800e8af5237794de7b29fca6dacfac"
REGISTRATION_FILE_SHA = "78f7cd03c3afc12c94c3ba09839e4ac6ba667a3f68b96871571b274ae7d3ab11"
SCOPE_DIGEST = "938da9116805967253417c53709cd85d56d1913ac0142032d0d4732f50c04061"

P04_REVIEW_CHECKS = 24

REQUIRED_PHRASES = [
    "#206",
    "#207",
    LOCK_HASH,
    REGISTRATION_HASH,
    SCOPE_DIGEST,
    "awaiting_explicit_reference",
    "authorized: false",
    "grants no authority of any kind",
    "grants no authority",
    "paid OpenRouter SKU",
    "hypothesis:low discovery screen and optional exploratory replay",
    "$0.20",
    "$0.10",
    "$0.30",
    "zero provider calls",
    "Zero provider calls",
    "stays open",
    "stays blocked",
    "Not authorization",
    "does not exist",
    "requires a **new version",
]

BANNED_PHRASES = [
    "authorization is granted",
    "authorization granted",
    "you are authorized",
    "live run authorized",
    "approved for collection",
    "safe to collect",
    "begin collection",
    "start collection",
    "proves causality",
    "population-representative",
    "the winning family",
    "statistically significant",
]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AuthorizationGateTestCase(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text(encoding="utf-8")
        self.normalized = " ".join(self.text.split())
        self.normalized_lower = self.normalized.lower()
        self.record = json.loads(AUTH_RECORD.read_text(encoding="utf-8"))
        self.lock = json.loads(LOCK.read_text(encoding="utf-8"))
        self.lock_review = json.loads(LOCK_REVIEW.read_text(encoding="utf-8"))
        self.registration = json.loads(REGISTRATION.read_text(encoding="utf-8"))
        self.reg_review = json.loads(REG_REVIEW.read_text(encoding="utf-8"))
        self.live_paths = [REPO_ROOT / path for path in p04.PATHS.values()
                           if path != str(p04.REGISTRATION_PATH)]
        self.live_before = [path.exists() for path in self.live_paths]

    def tearDown(self):
        self.assertEqual([path.exists() for path in self.live_paths],
                         self.live_before, "a live output path changed state")
        for path in self.live_paths:
            self.assertFalse(path.exists(),
                             "a discovery live output must never appear offline")


class AuthorizationRecordTests(AuthorizationGateTestCase):
    def test_record_is_not_authorization(self):
        self.assertEqual(self.record["state"], "awaiting_explicit_reference")
        self.assertIs(self.record["authorized"], False)
        self.assertIsNone(self.record["reference"])
        self.assertIsNone(self.record["supplied_by"])
        self.assertIsNone(self.record["supplied_at"])
        self.assertIsNone(self.record["decision"])
        self.assertEqual(self.record["provider_calls"], 0)

    def test_record_covers_exactly_the_four_must_cover_fields(self):
        self.assertEqual(self.record["must_cover"],
                         ["stage", "route", "request_caps", "cost_caps"])
        self.assertEqual(sorted(self.record["scope"].keys()),
                         sorted(["stage", "family", "route", "request_caps",
                                 "cost_caps", "stops", "paths", "path_lifecycle"]))

    def test_scope_is_copied_verbatim_from_the_p05_lock(self):
        self.assertEqual(self.record["scope"], self.lock["authorization_scope"])
        self.assertEqual(self.record["scope"], p05.authorization_scope(self.registration))

    def test_scope_digest_recomputes(self):
        digest = hashlib.sha256(
            json.dumps(self.record["scope"], sort_keys=True).encode()).hexdigest()
        self.assertEqual(digest, SCOPE_DIGEST)
        self.assertEqual(self.record["scope_digest_sha256"], SCOPE_DIGEST)
        self.assertEqual(
            self.record["what_a_reference_must_state"]["scope_digest_sha256"], SCOPE_DIGEST)

    def test_stage_route_and_caps_present(self):
        scope = self.record["scope"]
        self.assertEqual(scope["stage"],
                         "hypothesis:low discovery screen and optional exploratory replay")
        self.assertIn("paid OpenRouter SKU", scope["route"]["ling"]["route"])
        self.assertEqual(scope["route"]["ling"]["model"], "inclusionai/ling-3.0-flash-vl")
        self.assertEqual(scope["route"]["jev"]["model"], "jev-1.13.0")
        self.assertEqual(scope["route"]["normalization"]["hard_ceiling"], 0.05)
        caps = scope["request_caps"]
        self.assertEqual(caps["discovery_collection_physical"],
                         {"combined": 240, "jev": 48, "ling": 192})
        self.assertEqual(caps["program_physical"],
                         {"combined": 384, "jev": 192, "ling": 192})
        self.assertIn("3 physical attempts", caps["retry_model"])
        cost = scope["cost_caps"]
        self.assertEqual(cost["discovery_collection_ceiling_usd"], 0.2)
        self.assertEqual(cost["exploratory_replay_ceiling_usd"], 0.1)
        self.assertEqual(cost["program_ceiling_usd"], 0.3)

    def test_derived_from_pins_match_the_lock(self):
        derived = self.record["derived_from"]
        self.assertEqual(derived["p05_lock_hash"], LOCK_HASH)
        self.assertEqual(derived["p05_lock_hash"], self.lock["lock_hash"])
        self.assertEqual(derived["locked_registration_hash"], REGISTRATION_HASH)
        self.assertEqual(derived["locked_registration_file_sha256"],
                         sha256_of(REGISTRATION))
        self.assertEqual(derived["p05_lock_commit"], "615cec6")

    def test_may_not_be_inferred_from(self):
        inferred_from = self.record["may_not_be_inferred_from"]
        for item in ("this record", "the P05 lock", "the locked registration",
                     "the P05 lock review verdict",
                     "the P04 registration review verdict",
                     "credentials present in the environment",
                     "the task prompt or the protocol document"):
            with self.subTest(item=item):
                self.assertIn(item, inferred_from)

    def test_prerequisite_reviews_recorded_but_not_authorization(self):
        self.assertTrue(self.record["prerequisite_reviews_are_not_authorization"])
        verdicts = {entry["name"]: entry["verdict"]
                    for entry in self.record["prerequisite_reviews"]}
        self.assertEqual(verdicts["P05 discovery lock review"], "approved")
        self.assertEqual(verdicts["P04 discovery registration review"], "approved")

    def test_effect_while_reference_absent(self):
        effect = self.record["effect_while_reference_absent"]
        self.assertEqual(effect["provider_calls"], 0)
        self.assertEqual(effect["issue_206"], "stays open")
        self.assertEqual(effect["issue_207"], "stays blocked by #206")
        self.assertEqual(effect["live_output_paths"], "must remain absent")


class P04RegistrationReviewTests(AuthorizationGateTestCase):
    def test_review_approved_without_new_version(self):
        self.assertEqual(self.reg_review["verdict"], "approved")
        self.assertIs(self.reg_review["requires_new_version"], False)
        self.assertEqual(self.reg_review["blocking_findings"], [])
        self.assertEqual(self.reg_review["provider_calls"], 0)

    def test_all_four_pending_review_items_decided(self):
        decisions = self.reg_review["item_decisions"]
        self.assertEqual(self.reg_review["reviewed_items_count"], 4)
        self.assertEqual([entry["item"] for entry in decisions], [1, 2, 3, 4])
        for entry in decisions:
            with self.subTest(item=entry["item"]):
                self.assertEqual(entry["verdict"], "approved")
                self.assertTrue(entry["detail"])

    def test_item_four_recorded_as_standing_requirement_not_granted(self):
        item4 = self.reg_review["item_decisions"][3]
        self.assertEqual(item4["item"], 4)
        self.assertIn("not granted", item4["detail"])
        self.assertIn("supplies NO live authorization",
                      self.reg_review["resolution_note"])

    def test_review_checks_all_pass(self):
        checks = self.reg_review["checks"]
        self.assertEqual(len(checks), P04_REVIEW_CHECKS)
        self.assertTrue(all(entry["ok"] for entry in checks),
                        [entry for entry in checks if not entry["ok"]])

    def test_registration_bytes_unchanged_by_the_review(self):
        self.assertTrue(self.reg_review["registration_bytes_unchanged"])
        self.assertEqual(self.reg_review["registration_status_field_unchanged"],
                         "draft_pending_review")
        self.assertEqual(sha256_of(REGISTRATION), REGISTRATION_FILE_SHA)
        self.assertEqual(self.registration["registration_hash"], REGISTRATION_HASH)
        self.assertEqual(self.registration["status"], "draft_pending_review")


class CrossConsistencyTests(AuthorizationGateTestCase):
    def run_verify(self):
        buffer = io.StringIO()
        calls = []

        def explode(*args, **kwargs):
            calls.append(1)
            raise AssertionError("provider call attempted offline")

        with patch("urllib.request.urlopen", explode):
            with contextlib.redirect_stdout(buffer):
                rc = p05.main(["--repo-root", str(REPO_ROOT)])
        return rc, json.loads(buffer.getvalue()), calls

    def test_p05_lock_still_verifies_green_after_the_review(self):
        rc, verification, calls = self.run_verify()
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        self.assertTrue(verification["ok"], verification["failed"])
        self.assertEqual(verification["checks_run"], 44)
        self.assertEqual(verification["provider_calls"], 0)
        self.assertEqual(verification["lock_hash"], LOCK_HASH)
        self.assertEqual(verification["authorization_reference_state"],
                         "pending_not_supplied")

    def test_lock_review_still_approved_for_this_hash(self):
        self.assertEqual(self.lock_review["verdict"], "approved")
        self.assertEqual(self.lock_review["reviewed_lock_hash"], LOCK_HASH)
        self.assertEqual(self.lock_review["blocking_findings"], [])

    def test_no_live_output_path_exists(self):
        for path in self.live_paths:
            self.assertFalse(path.exists())


class DocContentTests(AuthorizationGateTestCase):
    def test_required_phrases_present(self):
        for phrase in REQUIRED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)

    def test_banned_overclaims_are_absent(self):
        for phrase in BANNED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase.lower(), self.normalized_lower)

    def test_doc_states_gate_status(self):
        status = " ".join(self.text.split("## 5. Current gate status")[1].split())
        self.assertIn("#206 open", status)
        self.assertIn("#207", status)
        self.assertIn("Zero provider calls", status)
        self.assertIn("do not exist", status)

    def test_doc_names_the_four_must_cover_fields(self):
        section = " ".join(self.text.split("## 2. What you are being asked to decide")[1]
                           .split("## 3.")[0].split())
        for field in ("Stage", "Route", "Request caps", "Cost caps"):
            with self.subTest(field=field):
                self.assertIn(field, section)


if __name__ == "__main__":
    unittest.main()
