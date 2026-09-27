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
DOC = REPO_ROOT / "docs" / "jev-p05-discovery-lock.md"
LOCK = REPO_ROOT / "runs" / "next-phase" / "jev-p05-discovery-lock-v1.json"
REVIEW = REPO_ROOT / "runs" / "next-phase" / "jev-p05-discovery-lock-review-v1.json"
REGISTRATION = REPO_ROOT / "runs" / "next-phase" / "jev-p04-discovery-registration-v1.json"
AUDIT = REPO_ROOT / p04.AUDIT_PATH
REGISTRATION_200 = REPO_ROOT / p04.REGISTRATION_200_PATH

#: Self-recorded content hash of the frozen lock.
LOCK_HASH = "9de4a61f9d46c47b55bbe7b8da9903c677c6461bf4af353007277835ed6a18b3"
#: Self-recorded content hash of the locked P04 registration.
REGISTRATION_HASH = "6fa6149770b620cd3a026a6415f8e4d97e800e8af5237794de7b29fca6dacfac"

#: Expected offline check counts.
PREFLIGHT_CHECKS = 51
VERIFY_CHECKS = 44
REVIEW_CHECKS = 16

REQUIRED_PHRASES = [
    "#206",
    "#201",
    "#159",
    "hypothesis:low",
    LOCK_HASH,
    REGISTRATION_HASH,
    "locked_pending_separate_live_authorization",
    "pending_not_supplied",
    "This lock is not live authorization",
    "provider_calls: 0",
    "51/51",
    "44/44",
    "16/16",
    "k = 4",
    "0.125",
    "pilot",
    "byte-unchanged",
    "independently recomputed",
    "paid OpenRouter",
    "$0.20",
    "$0.10",
    "$0.30",
    "request caps",
    "cost caps",
    "#206 stays open",
    "#207 (P06, collection) stays blocked",
]

BANNED_PHRASES = [
    "establishes causality",
    "proves causality",
    "proves causation",
    "population-representative",
    "generalizes to",
    "the model is calibrated",
    "live run authorized",
    "live authorization granted",
    "authorization was granted",
    "approved for collection",
    "safe to collect",
    "the reference is implied",
    "the winning family",
    "confirmed effect",
    "statistically significant",
]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DiscoveryLockTestCase(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text(encoding="utf-8")
        self.normalized = " ".join(self.text.split())
        self.normalized_lower = self.normalized.lower()
        self.lock = json.loads(LOCK.read_text(encoding="utf-8"))
        self.review = json.loads(REVIEW.read_text(encoding="utf-8"))
        self.registration = json.loads(REGISTRATION.read_text(encoding="utf-8"))
        self.live_paths = [REPO_ROOT / path for path in p04.PATHS.values()
                           if path != str(p04.REGISTRATION_PATH)]
        self.live_before = [path.exists() for path in self.live_paths]

    def tearDown(self):
        self.assertEqual([path.exists() for path in self.live_paths],
                         self.live_before, "a live output path changed state")
        for path in self.live_paths:
            self.assertFalse(path.exists(),
                             "a discovery live output must never appear offline")


class ContentHashTests(DiscoveryLockTestCase):
    def test_lock_hash_recomputes(self):
        recomputed = hashlib.sha256(
            json.dumps({key: value for key, value in self.lock.items()
                        if key != "lock_hash"},
                       sort_keys=True).encode()).hexdigest()
        self.assertEqual(recomputed, LOCK_HASH)
        self.assertEqual(self.lock["lock_hash"], LOCK_HASH)
        self.assertIn(LOCK_HASH, self.normalized)

    def test_locked_registration_hash_matches_pin(self):
        locked = self.lock["locked_registration"]
        self.assertEqual(locked["registration_hash"], REGISTRATION_HASH)
        recomputed = hashlib.sha256(
            json.dumps({key: value for key, value in self.registration.items()
                        if key != "registration_hash"},
                       sort_keys=True).encode()).hexdigest()
        self.assertEqual(recomputed, REGISTRATION_HASH)
        self.assertEqual(locked["file_sha256"], sha256_of(REGISTRATION))
        self.assertEqual(locked["status_at_lock"], "draft_pending_review")

    def test_hash_helpers_distinguish_the_two_documents(self):
        self.assertNotEqual(p05._lock_hash(self.lock), p05._registration_hash(self.lock))
        self.assertEqual(p05._lock_hash(self.lock), LOCK_HASH)
        self.assertEqual(p05._registration_hash(self.registration), REGISTRATION_HASH)


class LockStructureTests(DiscoveryLockTestCase):
    def test_lock_identity(self):
        self.assertEqual(self.lock["lock_version"], "jev-discovery-lock-v1")
        self.assertEqual(self.lock["status"], "locked_pending_separate_live_authorization")
        self.assertEqual(self.lock["issue"], "#206")
        self.assertEqual(self.lock["parent_issue"], "#201")
        self.assertEqual(self.lock["root_issue"], "#159")
        self.assertEqual(self.lock["task"], "P05")

    def test_lock_authorizes_nothing_beyond_locking(self):
        self.assertTrue(self.lock["offline_only"])
        self.assertIn("no provider call", self.lock["authorizes"])
        self.assertIn("no collection", self.lock["authorizes"])
        self.assertIn("no live run", self.lock["authorizes"])

    def test_embedded_preflight_is_green_and_call_free(self):
        preflight = self.lock["offline_preflight"]
        self.assertTrue(preflight["ok"])
        self.assertEqual(preflight["failed"], [])
        self.assertEqual(preflight["checks_run"], PREFLIGHT_CHECKS)
        self.assertEqual(preflight["provider_calls"], 0)


class AuthorizationReferenceTests(DiscoveryLockTestCase):
    def test_reference_is_pending_and_absent(self):
        reference = self.lock["authorization_reference"]
        self.assertEqual(reference["state"], "pending_not_supplied")
        self.assertIsNone(reference["reference"])
        self.assertIsNone(reference["recorded_at"])

    def test_reference_must_cover_stage_route_and_caps(self):
        self.assertEqual(self.lock["authorization_reference"]["must_cover"],
                         ["stage", "route", "request_caps", "cost_caps"])

    def test_reference_may_not_be_inferred(self):
        inferred_from = self.lock["authorization_reference"]["may_not_be_inferred_from"]
        self.assertIn("this lock", inferred_from)
        self.assertIn("credentials present in the environment", inferred_from)
        self.assertIn("the task prompt or plan document", inferred_from)
        self.assertIn("the locked registration", inferred_from)

    def test_reference_blocks_successor(self):
        blocks = self.lock["authorization_reference"]["blocks"]
        self.assertIn("#207", blocks)
        self.assertIn("supplied and recorded", blocks)

    def test_lock_is_not_authorization(self):
        authorization = self.registration["authorization"]
        self.assertTrue(authorization["locking_is_not_authorization"])
        self.assertTrue(authorization["approval_may_not_be_inferred_from_locking"])
        self.assertTrue(authorization["separate_live_authorization_required_after_locking"])
        self.assertTrue(authorization["approval_must_be_a_supplied_reference"])
        self.assertEqual(len(authorization["pending_review"]), 4)


class PreservedDesignTests(DiscoveryLockTestCase):
    def test_k4_and_floor_preserved(self):
        preserved = self.lock["preserved"]
        self.assertEqual(preserved["k"], 4)
        self.assertEqual(preserved["attainable_two_sided_sign_flip_floor"], "0.125")
        self.assertTrue(preserved["descriptive_only"])

    def test_classification_is_pilot(self):
        self.assertEqual(self.lock["preserved"]["classification"], "pilot")
        self.assertIn("descriptive only",
                      self.lock["preserved"]["fresh_seed_replication"])

    def test_contract_preserved(self):
        preserved = self.lock["preserved"]
        self.assertEqual(preserved["estimand"],
                         "equal-weight form mean of real-minus-placebo entropy")
        self.assertEqual(preserved["h0"], "Delta = 0")
        self.assertEqual(preserved["h1"], "Delta < 0")
        self.assertTrue(preserved["guards_never_filter_the_estimate"])
        self.assertTrue(preserved["no_planning_low_effect_size_prior"])

    def test_preserved_matches_registration(self):
        self.assertEqual(self.lock["preserved"]["k"],
                         self.registration["design_classification"]["k"])
        self.assertEqual(self.lock["preserved"]["classification"],
                         self.registration["design_classification"]["classification"])


class FrozenArtifactTests(DiscoveryLockTestCase):
    def test_frozen_200_artifacts_byte_unchanged(self):
        self.assertEqual(sha256_of(AUDIT),
                         "cb529cd61e0e662bfa19fc4998e89fa59a0bf0d63e14f77498035466d6bce89d")
        self.assertEqual(sha256_of(REGISTRATION_200),
                         "bddf46ed5fd87ec4da99532d645580a65e250d64639de80477002ff73d278f3c")

    def test_frozen_artifacts_recorded_in_lock(self):
        frozen = {row["path"]: row["sha256"]
                  for row in self.lock["preserved"]["frozen_200_artifacts"]}
        self.assertEqual(frozen[str(p04.AUDIT_PATH)], sha256_of(AUDIT))
        self.assertEqual(frozen[str(p04.REGISTRATION_200_PATH)],
                         sha256_of(REGISTRATION_200))


class EvidencePathTests(DiscoveryLockTestCase):
    def test_all_evidence_paths_hash_match_disk(self):
        rows = self.lock["evidence_paths"]
        self.assertEqual(len(rows), 7)
        for row in rows:
            with self.subTest(path=row["path"]):
                self.assertEqual(sha256_of(REPO_ROOT / row["path"]), row["sha256"])

    def test_evidence_includes_frozen_200_and_protocol(self):
        paths = {row["path"] for row in self.lock["evidence_paths"]}
        self.assertIn(str(p04.AUDIT_PATH), paths)
        self.assertIn(str(p04.REGISTRATION_200_PATH), paths)
        self.assertIn("docs/jev-discovery-confirmation-plan.md", paths)


class AuthorizationScopeTests(DiscoveryLockTestCase):
    def test_scope_matches_registration_exactly(self):
        expected = p05.authorization_scope(self.registration)
        self.assertEqual(self.lock["authorization_scope"], expected)

    def test_stage_and_route_recorded(self):
        scope = self.lock["authorization_scope"]
        self.assertEqual(scope["stage"], self.registration["stage"])
        self.assertEqual(scope["route"], self.registration["route"])
        self.assertIn("paid OpenRouter SKU", scope["route"]["ling"]["route"])
        self.assertEqual(scope["route"]["jev"]["model"], "jev-1.13.0")
        self.assertEqual(scope["route"]["normalization"]["hard_ceiling"], 0.05)

    def test_request_caps_recorded(self):
        caps = self.lock["authorization_scope"]["request_caps"]
        self.assertEqual(caps["block_n"], 16)
        self.assertEqual(caps["discovery_collection_planned"],
                         {"combined": 80, "jev": 16, "ling": 64})
        self.assertEqual(caps["discovery_collection_physical"],
                         {"combined": 240, "jev": 48, "ling": 192})
        self.assertEqual(caps["exploratory_replay_events_max"], 16)
        self.assertEqual(caps["program_physical"],
                         {"combined": 384, "jev": 192, "ling": 192})
        self.assertIn("3 physical attempts", caps["retry_model"])

    def test_cost_caps_recorded(self):
        caps = self.lock["authorization_scope"]["cost_caps"]
        self.assertEqual(caps["discovery_collection_ceiling_usd"], 0.2)
        self.assertEqual(caps["exploratory_replay_ceiling_usd"], 0.1)
        self.assertEqual(caps["program_ceiling_usd"], 0.3)
        self.assertEqual(caps["program_worst_case_usd"], 0.195821568)
        self.assertLessEqual(caps["program_worst_case_usd"],
                             caps["program_ceiling_usd"])

    def test_stops_and_paths_recorded(self):
        scope = self.lock["authorization_scope"]
        self.assertEqual(scope["stops"], self.registration["stops"])
        self.assertEqual(scope["paths"], self.registration["paths"])
        self.assertFalse(scope["path_lifecycle"]["resume"])
        self.assertFalse(scope["path_lifecycle"]["append"])
        self.assertFalse(scope["path_lifecycle"]["overwrite"])


class ReviewRecordTests(DiscoveryLockTestCase):
    def test_review_record_exists_and_approves(self):
        self.assertEqual(self.review["review_version"], "jev-discovery-lock-review-v1")
        self.assertEqual(self.review["verdict"], "approved")
        self.assertEqual(self.review["blocking_findings"], [])
        self.assertEqual(self.review["provider_calls"], 0)

    def test_review_covers_this_lock_hash(self):
        self.assertEqual(self.review["reviewed_lock_hash"], self.lock["lock_hash"])
        self.assertEqual(self.review["reviewed_lock_hash"], LOCK_HASH)

    def test_reviewed_against_issue_and_protocol(self):
        self.assertEqual(self.review["reviewed_against"],
                         ["#206", "docs/jev-discovery-confirmation-plan.md"])
        self.assertEqual(self.review["lock_path"],
                         "runs/next-phase/jev-p05-discovery-lock-v1.json")

    def test_review_checks_all_pass(self):
        checks = self.review["checks"]
        self.assertEqual(len(checks), REVIEW_CHECKS)
        self.assertTrue(all(entry["ok"] for entry in checks),
                        [entry for entry in checks if not entry["ok"]])


class OfflineCliTests(DiscoveryLockTestCase):
    def run_cli(self, argv):
        buffer = io.StringIO()
        calls = []

        def explode(*args, **kwargs):
            calls.append(1)
            raise AssertionError("provider call attempted offline")

        with patch("urllib.request.urlopen", explode):
            with contextlib.redirect_stdout(buffer):
                rc = p05.main(argv)
        return rc, buffer.getvalue(), calls

    def test_preflight_is_call_free_and_green(self):
        rc, output, calls = self.run_cli(["--repo-root", str(REPO_ROOT), "--preflight"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        document = json.loads(output)
        self.assertTrue(document["ok"], document["failed"])
        self.assertEqual(document["failed"], [])
        self.assertEqual(len(document["checks"]), PREFLIGHT_CHECKS)
        self.assertEqual(document["provider_calls"], 0)
        self.assertEqual(document["status"], "offline")

    def test_verification_is_call_free_and_green(self):
        rc, output, calls = self.run_cli(["--repo-root", str(REPO_ROOT)])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        document = json.loads(output)
        self.assertTrue(document["ok"], document["failed"])
        self.assertEqual(document["failed"], [])
        self.assertEqual(len(document["checks"]), VERIFY_CHECKS)
        self.assertEqual(document["provider_calls"], 0)
        self.assertEqual(document["lock_hash"], LOCK_HASH)
        self.assertEqual(document["authorization_reference_state"],
                         "pending_not_supplied")

    def test_build_is_idempotent_and_never_overwrites(self):
        rebuilt = p05.build_lock(REPO_ROOT)
        self.assertEqual(rebuilt, json.loads(LOCK.read_text(encoding="utf-8")))
        self.assertEqual(rebuilt["lock_hash"], LOCK_HASH)
        with self.assertRaises(p05.DiscoveryLockError):
            p05.write_lock({**rebuilt, "status": "tampered"}, repo_root=REPO_ROOT)


class FailClosedTests(DiscoveryLockTestCase):
    def test_verification_fails_closed_without_review_record(self):
        review_path = REPO_ROOT / p05.REVIEW_PATH
        original = review_path.read_bytes()
        try:
            review_path.unlink()
            verification = p05.verify_lock(self.lock, repo_root=REPO_ROOT)
            self.assertFalse(verification["ok"])
            for name in ("review_record_exists", "review_record_approved",
                         "review_record_matches_lock_hash",
                         "review_record_no_blocking_findings",
                         "review_record_covers_required_scope"):
                self.assertIn(name, verification["failed"])
        finally:
            review_path.write_bytes(original)
        self.assertEqual(sha256_of(review_path), hashlib.sha256(original).hexdigest())

    def test_tampered_lock_hash_is_rejected(self):
        tampered = {**self.lock, "lock_hash": "0" * 64}
        verification = p05.verify_lock(tampered, repo_root=REPO_ROOT)
        self.assertFalse(verification["ok"])
        self.assertIn("lock_hash_recomputes", verification["failed"])

    def test_live_output_paths_still_absent(self):
        for path in self.live_paths:
            self.assertFalse(path.exists())


class DocContentTests(DiscoveryLockTestCase):
    def test_required_phrases_present(self):
        for phrase in REQUIRED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)

    def test_banned_overclaims_are_absent(self):
        for phrase in BANNED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase.lower(), self.normalized_lower)

    def test_checks_section_records_counts_and_call_free_result(self):
        checks = " ".join(self.text.split("## 6. Checks")[1].split("## 7.")[0].split())
        self.assertIn("51/51", checks)
        self.assertIn("44/44", checks)
        self.assertIn("16/16", checks)
        self.assertIn("provider_calls: 0", checks)

    def test_handoff_records_gate_and_no_successor_authorization(self):
        handoff = " ".join(self.text.split("## 7. Handoff")[1].split())
        self.assertIn("A predecessor closed as failed does not authorize successor execution",
                      handoff)
        self.assertIn("#206 stays open", handoff)
        self.assertIn("#207 (P06, collection) stays blocked", handoff)
        self.assertIn("not that reference", handoff)

    def test_review_section_records_verdict_and_hash(self):
        review = " ".join(self.text.split("## 5. Independent review")[1]
                          .split("## 6.")[0].split())
        self.assertIn("approved", review)
        self.assertIn(LOCK_HASH, review)
        self.assertIn("0 network events", review)


if __name__ == "__main__":
    unittest.main()
