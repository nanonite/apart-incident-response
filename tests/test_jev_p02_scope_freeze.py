import contextlib
import hashlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import jev_replication_preregistration as rep


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "jev-p02-scope-freeze.md"
SCOPE = REPO_ROOT / "runs" / "next-phase" / "jev-p02-scope-freeze.json"
AUDIT = REPO_ROOT / rep.AUDIT_PATH
REGISTRATION = REPO_ROOT / rep.REGISTRATION_PATH

#: Self-recorded content hash of the frozen scope record.
SCOPE_CONTENT_HASH = "4cf5556c8e9c0811653e4b4d726a7b437d43bd63134cad0f80b84eb9148ec59b"

#: Frozen pins carried from the #200 artifacts.
AUDIT_CONTENT_HASH = "5242e9cfa35e3a77c54045475428dd617cf93cb16d464b55ad679adc35f80a83"
PREREGISTRATION_HASH = "ff186a066e6af093ecc383e668d948bdca7c1ef8f84b5752b88db47960a6ec6d"
PRIOR_INSTANCE_ID_COUNT = 8945
PRIOR_INSTANCE_IDS_SHA256 = "429e8c54720d1a472d9e191fedc0510ade291680514f2dae4dff8c2a747607f9"

CANDIDATE_ORDER = ["hypothesis", "legal", "lexicon", "poetry", "reference"]
WINDOWS = {
    "discovery": (85000, 85511),
    "closure_probe": (86000, 86511),
    "held_out": (87000, 87511),
}

REQUIRED_PHRASES = [
    # task identity and offline scope
    "#203",
    "#201",
    "#159",
    "hypothesis:low",
    "no provider call",
    "nothing here authorizes collection",
    # candidate order and structural rule
    "alphabetically first (bytewise ascending) non-planning family",
    "closed finite solution set",
    "A-finalizer structurally needs the peer clue",
    "at least one B-owned claim that is informative for A",
    "legal",
    "lexicon",
    "poetry",
    "reference",
    "No outcome-based reordering",
    # prior-manifest inventory
    "131 files, 74 with instance ids",
    "429e8c54720d1a472d9e191fedc0510ade291680514f2dae4dff8c2a747607f9",
    "8802 documented seed-range ids",
    "runs/container-isolation.json",
    "permission-denied",
    "never as empty sets",
    "runs/discovery-145/",
    "one-turn protocol artifacts",
    # windows and stage labels
    "85000–85511",
    "86000–86511",
    "87000–87511",
    "discovery",
    "closure_probe",
    "held_out",
    "no seed may be selected from it",
    "fresh-seed held-out block",
    "No live outcome is used to choose forms or seeds",
    # design consequence
    "k_max = 4",
    "0.125",
    "estimation and descriptive study",
    "Guards never filter the estimate",
    "No planning-low effect-size prior",
    # checks and handoff
    "49/49",
    "provider_calls: 0",
    "P03 (#204)",
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


class ScopeFreezeTestCase(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text(encoding="utf-8")
        # phrases are matched against whitespace-normalized text so that
        # markdown line wrapping cannot hide a required statement
        self.normalized = " ".join(self.text.split())
        self.normalized_lower = self.normalized.lower()
        self.scope = json.loads(SCOPE.read_text(encoding="utf-8"))
        self.audit = json.loads(AUDIT.read_text(encoding="utf-8"))
        self.registration = json.loads(REGISTRATION.read_text(encoding="utf-8"))
        self.inventory = self.scope["prior_manifest_inventory"]["files"]
        self.before = {entry["path"]: (REPO_ROOT / entry["path"]).exists()
                       for entry in self.inventory}
        self.live_paths = [REPO_ROOT / path for path in
                           (rep.COLLECTION_JOURNAL, rep.COLLECTION_REPORT,
                            rep.REPLAY_JOURNAL, rep.REPLAY_REPORT)]
        self.live_before = [path.exists() for path in self.live_paths]

    def tearDown(self):
        for entry in self.inventory:
            path = REPO_ROOT / entry["path"]
            self.assertEqual(path.exists(), self.before[entry["path"]],
                             f"an inventory file changed state: {entry['path']}")
        self.assertEqual([path.exists() for path in self.live_paths],
                         self.live_before, "a live output path changed state")
        for path in self.live_paths:
            self.assertFalse(path.exists(),
                             "a replication live output must never appear offline")


class ContentHashTests(ScopeFreezeTestCase):
    def test_scope_content_hash_recomputes(self):
        recomputed = hashlib.sha256(
            json.dumps({key: value for key, value in self.scope.items()
                        if key != "content_hash"},
                       sort_keys=True).encode()).hexdigest()
        self.assertEqual(recomputed, SCOPE_CONTENT_HASH)
        self.assertEqual(self.scope["content_hash"], SCOPE_CONTENT_HASH)
        self.assertIn(SCOPE_CONTENT_HASH, self.normalized)

    def test_frozen_input_pins_still_match(self):
        self.assertEqual(self.audit["audit_content_hash"], AUDIT_CONTENT_HASH)
        self.assertEqual(self.registration["preregistration_hash"],
                         PREREGISTRATION_HASH)
        self.assertEqual(self.registration["audit_binding"]["audit_content_hash"],
                         AUDIT_CONTENT_HASH)
        for pin in (AUDIT_CONTENT_HASH, PREREGISTRATION_HASH):
            with self.subTest(pin=pin):
                self.assertIn(pin, self.normalized)


class InventoryHashTests(ScopeFreezeTestCase):
    def test_every_inventory_hash_matches_disk(self):
        checked = 0
        for entry in self.inventory:
            if not entry["accessible"]:
                continue
            with self.subTest(path=entry["path"]):
                self.assertEqual(sha256_of(REPO_ROOT / entry["path"]),
                                 entry["sha256"])
            checked += 1
        self.assertEqual(checked, len(self.inventory) - 1,
                         "exactly one inventory file is inaccessible")

    def test_inaccessible_manifest_is_recorded_not_empty(self):
        inaccessible = [entry for entry in self.inventory if not entry["accessible"]]
        self.assertEqual([entry["path"] for entry in inaccessible],
                         ["runs/container-isolation.json"])
        record = self.scope["prior_manifest_inventory"]["inaccessible_manifests"]
        self.assertEqual(record[0]["path"], "runs/container-isolation.json")
        self.assertIn("permission-denied", record[0]["reason"])
        self.assertIn("never as an empty set", record[0]["handling"])
        unaccounted = self.scope["prior_manifest_inventory"]["unaccounted_manifest_directories"]
        self.assertGreaterEqual(len(unaccounted), 10)
        for entry in unaccounted:
            with self.subTest(path=entry["path"]):
                self.assertIn("permission-denied", entry["reason"])
                self.assertFalse(_is_fully_readable(REPO_ROOT / entry["path"]),
                                 "an unaccounted directory became fully readable")

    def test_inventory_counts_are_self_consistent(self):
        inventory = self.scope["prior_manifest_inventory"]
        self.assertEqual(inventory["file_count"], len(self.inventory))
        self.assertEqual(
            inventory["files_with_instance_ids"],
            sum(1 for entry in self.inventory if entry["instance_id_count"]))
        self.assertEqual(inventory["file_count"], 131)
        self.assertEqual(inventory["files_with_instance_ids"], 74)
        self.assertEqual(inventory["prior_instance_id_count"],
                         PRIOR_INSTANCE_ID_COUNT)
        self.assertEqual(inventory["prior_instance_ids_sha256"],
                         PRIOR_INSTANCE_IDS_SHA256)

    def test_200_prior_sources_all_present_and_hashed(self):
        baseline = set(self.audit["disjointness"]["prior_sources"])
        self.assertEqual(len(baseline), 119)
        inventoried = {entry["path"] for entry in self.inventory
                       if entry["in_200_prior_sources"]}
        self.assertEqual(inventoried, baseline)
        for rel in baseline:
            with self.subTest(path=rel):
                entry = next(e for e in self.inventory if e["path"] == rel)
                if entry["accessible"]:
                    self.assertEqual(sha256_of(REPO_ROOT / rel), entry["sha256"])


class PriorInstanceIdTests(ScopeFreezeTestCase):
    def test_prior_instance_id_set_reproduces_the_200_pin(self):
        prior = rep._prior_instance_ids(REPO_ROOT)
        self.assertEqual(prior["instance_id_count"], PRIOR_INSTANCE_ID_COUNT)
        self.assertEqual(prior["instance_ids_sha256"], PRIOR_INSTANCE_IDS_SHA256)
        self.assertEqual(prior["instance_ids_sha256"],
                         self.audit["disjointness"]["prior_instance_ids_sha256"])
        self.assertEqual(prior["instance_id_count"],
                         self.audit["disjointness"]["prior_instance_id_count"])
        self.assertEqual(prior["documented_seed_id_count"], 8802)
        self.assertIn(PRIOR_INSTANCE_IDS_SHA256, self.normalized)
        self.assertIn("8802 documented seed-range ids", self.normalized)


class CandidateOrderTests(ScopeFreezeTestCase):
    def test_candidate_order_matches_the_200_audit(self):
        selection = self.audit["family_selection"]
        self.assertEqual(selection["candidates_in_rule_order"], CANDIDATE_ORDER)
        self.assertEqual(self.scope["candidate_order"]["candidates_in_rule_order"],
                         CANDIDATE_ORDER)
        self.assertEqual(selection["selected_family"], "hypothesis")
        self.assertEqual(selection["excluded_families"], ["planning"])
        self.assertIs(selection["outcome_blind"], True)
        self.assertEqual(selection["consulted_prior_live_outcomes"], [])
        self.assertEqual(selection["preconditions"],
                         self.scope["candidate_order"]["preconditions"])
        self.assertIs(self.scope["candidate_order"]["outcome_blind"], True)
        self.assertIs(self.scope["candidate_order"]["no_outcome_based_reordering"],
                      True)
        self.assertIs(self.scope["candidate_order"]["no_post_hoc_winner_selection"],
                      True)
        for family in CANDIDATE_ORDER:
            with self.subTest(family=family):
                self.assertIn(family, self.normalized)


class WindowAndStageTests(ScopeFreezeTestCase):
    def test_windows_match_the_200_audit(self):
        windows = self.audit["windows"]
        self.assertEqual(self.scope["proposed_windows"]["discovery"]["base"],
                         windows["primary"]["base"])
        self.assertEqual(self.scope["proposed_windows"]["discovery"]["end"],
                         windows["primary"]["end"])
        self.assertEqual(self.scope["proposed_windows"]["closure_probe"]["base"],
                         windows["closure_probe"]["base"])
        self.assertEqual(self.scope["proposed_windows"]["held_out"]["base"],
                         windows["confirmation"]["base"])
        self.assertEqual(self.scope["proposed_windows"]["held_out"]["end"],
                         windows["confirmation"]["end"])

    def test_windows_are_disjoint_from_documented_ranges_and_each_other(self):
        documented = self.scope["prior_manifest_inventory"]["documented_seed_ranges"]
        self.assertEqual(len(documented), 10)
        for name, (low, high) in WINDOWS.items():
            for entry in documented:
                with self.subTest(window=name, range=f"{entry['low']}–{entry['high']}"):
                    self.assertTrue(high < entry["low"] or low > entry["high"])
        names = list(WINDOWS)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = WINDOWS[names[i]], WINDOWS[names[j]]
                with self.subTest(pair=f"{names[i]}/{names[j]}"):
                    self.assertTrue(a[1] < b[0] or b[1] < a[0])
        self.assertIs(
            self.scope["proposed_windows"]["disjoint_from_documented_prior_ranges"],
            True)
        self.assertIs(self.scope["proposed_windows"]["pairwise_disjoint"], True)

    def test_stage_labels_are_explicit(self):
        labels = self.scope["stage_labels"]
        for name in ("discovery", "closure_probe", "held_out"):
            with self.subTest(label=name):
                self.assertIn(name, labels)
                self.assertIn(name, self.normalized)
        self.assertIn("P05", labels["discovery"])
        self.assertIn("P06", labels["discovery"])
        self.assertIn("P07", labels["discovery"])
        self.assertIn("P08", labels["held_out"])
        self.assertIn("P11", labels["held_out"])
        self.assertIn("P13", labels["held_out"])
        self.assertIn("not a live stage", labels["closure_probe"])
        self.assertEqual(
            self.scope["proposed_windows"]["discovery"]["maps_to_200_block"],
            "primary")
        self.assertEqual(
            self.scope["proposed_windows"]["held_out"]["maps_to_200_block"],
            "confirmation")

    def test_selection_rule_is_frozen(self):
        rule = self.scope["selection_rule"]
        self.assertIn("INSTANCES_PER_FORM = 4", rule)
        self.assertIn("ascending seed order", rule)
        self.assertIn("no outcome-based stopping", rule)
        self.assertIn("No live outcome is used to choose forms or seeds",
                      self.normalized)
        self.assertIn("Distinct seed ids are not independent forms", self.normalized)


class DesignConsequenceTests(ScopeFreezeTestCase):
    def test_k4_descriptive_only_is_recorded(self):
        self.assertEqual(self.scope["k_max"], 4)
        self.assertIn("0.125", self.scope["design_consequence"])
        self.assertIn("descriptive/estimation only", self.scope["design_consequence"])
        self.assertIn("k_max = 4", self.normalized)
        self.assertIn("0.125", self.normalized)
        self.assertIn("estimation and descriptive study", self.normalized)
        self.assertIn("fresh-seed replication", self.normalized)

    def test_contract_phrases_are_present(self):
        for phrase in ("H0: Delta = 0", "H1: Delta < 0",
                       "equal-weight form mean of real-minus-placebo entropy",
                       "Guards never filter the estimate",
                       "without imputation",
                       "No planning-low effect-size prior"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)


class DocContentTests(ScopeFreezeTestCase):
    def test_required_phrases_present(self):
        for phrase in REQUIRED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)

    def test_banned_overclaims_are_absent(self):
        for phrase in BANNED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase.lower(), self.normalized_lower)

    def test_handoff_records_next_step_and_no_successor_authorization(self):
        handoff = " ".join(self.text.split("## 6. Handoff")[1].split())
        self.assertIn("P03 (#204)", handoff)
        self.assertIn("audit form capacity and independence", handoff)
        self.assertIn("rechecking current manifest coverage", handoff)
        self.assertIn("A predecessor closed as failed does not authorize successor execution",
                      handoff)
        self.assertIn("blocked by this task", handoff)

    def test_checks_section_records_the_offline_preflight(self):
        checks = " ".join(self.text.split("## 5. Checks")[1].split("## 6.")[0].split())
        self.assertIn("49/49", checks)
        self.assertIn("provider_calls: 0", checks)
        self.assertIn("fail closed on drift", checks)
        self.assertIn("byte-for-byte", checks)


class OfflineVerificationTests(ScopeFreezeTestCase):
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


def _is_fully_readable(path: Path) -> bool:
    """True only when every file and directory under path can be read.

    Uses os.access because pathlib's rglob silently skips unreadable
    directories, which would make an unaccounted tree look clean.
    """
    import os
    if not path.exists():
        return False
    if path.is_file():
        return os.access(path, os.R_OK)
    if not os.access(path, os.R_OK | os.X_OK):
        return False
    for root, dirs, files in os.walk(path):
        for name in dirs + files:
            if not os.access(os.path.join(root, name), os.R_OK):
                return False
    return True


if __name__ == "__main__":
    unittest.main()
