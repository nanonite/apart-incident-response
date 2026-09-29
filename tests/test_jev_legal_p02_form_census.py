"""L02 (#220) focused validation: offline legal form census with zero network events.

Everything in this suite is recomputed from files on disk. A process-wide audit
hook records any ``socket.*`` / ``urllib.*`` / ``http.client.*`` /
``ftplib.*`` event and ``urllib.request.urlopen`` is replaced by a raising stub
for the build, so a provider call fails the suite instead of escaping it. The
frozen #200/#207/#215 inputs, the L01 handoff and this chain's output directory
are asserted byte-identical before and after every test.
"""

import contextlib
import hashlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import jev_legal_form_census as census
from apart_incident_response import jev_replication_preregistration as rep

REPO_ROOT = Path(__file__).resolve().parents[1]
CENSUS_PATH = REPO_ROOT / census.CENSUS_PATH
DOC_PATH = REPO_ROOT / census.DOC_PATH
AUDIT_200 = REPO_ROOT / rep.AUDIT_PATH
MODULE_PATH = REPO_ROOT / "src/apart_incident_response/jev_legal_form_census.py"

#: Self-recorded content hash of the committed census.
CENSUS_CONTENT_HASH = "5fee9d0173dbdcc8ea3f5783f5ee578f1a0cf697742f8de7c4d71d0bcccfb6f2"

#: sha256 recomputed from disk; the frozen-input table of the census pins these.
PINNED_SHA256 = {
    "docs/jev-discovery-confirmation-plan.md":
        "501e21b6dea760371b0bf368046d8bacd203f6b92f0af754a7955d1f738677f7",
    "runs/epic-126/replication/jev-replication-form-audit-v1.json":
        "cb529cd61e0e662bfa19fc4998e89fa59a0bf0d63e14f77498035466d6bce89d",
    "runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection.jsonl":
        "4e8de096f2c30a6a36a94a0f79e5f450c2e196123e3eafe1c310a92c4f334c83",
    "runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection-report.json":
        "3086ceac558ff922bd083db3795f5f1aa5c7127813daba8bfd71ae1fbef09d3c",
    "docs/jev-hypothesis-low-terminal-decision.md":
        "89ef2aafb5e28f12d0db707499c583d89cdcc490d105c23c3c56b39e11818d0b",
    "runs/next-phase/legal/jev-legal-p01-evidence-v1.json":
        "b2d0726619f5a18ce1ed5a54c5197d51709b1e0473b58ee129c74592b7b707e3",
    "docs/jev-legal-p01-baseline.md":
        "8926f48d85338163fae0f9434f63c62b380f6402580bb57cd1d35b25d0471870",
    "docs/jev-legal-task-sequence.md":
        "884b0ed4329cc47888e797478f8f00b57f7f5c9d679998d154f5a789397d0394",
}

FROZEN_PATHS = sorted(set(PINNED_SHA256) | {
    str(census.CENSUS_PATH),
    str(census.DOC_PATH),
    "src/apart_incident_response/jev_legal_form_census.py",
})

#: Derived findings pinned after the offline build (recomputed, not trusted).
FORM_IDS = [
    "309706db278f790720bf76f19b248ff43e5eaf178d250cd60f9defccfb7b00c9",
    "3ca0223020c4113d4a8147d3b611c414248eb64369497f9a5f6a4a7f78a0df9f",
    "935f84146a383fa027fb55446dd011c55d81f32151477d56ca85d7e155b8c809",
    "bb6fcd3ffb95e480cd779f380549bfca873e86b8c313825d97d14c6ea7b6ca07",
]
HYPOTHESIS_FORM_IDS = [
    "57ee9880f18bff4971516f9db820fd96dfb9eb86dab29e166025625e88a7b0c9",
    "a0e4ffd0c0b442207bf171422592a1f0b8f58556e2d44d8845d74ec23853f03d",
    "a95806c84d3a722d0ae240c637277373526956b57051cf006e5430706bf6e94c",
    "fc05e96360fa58fd2398727a886654d27d87fe561b2160002bcc01511f322562",
]
TEMPLATE_HASH = "35b03db195dd6aed416005b5fa3f985e08572c66d058fed6572d9bff975ef6f6"
OPTION_SET_HASH = "04740042a5ee268940966b919c1fed29eb8a42503de2973bbc39178ae7b9bcb6"
PRIOR_INSTANCE_ID_COUNT = 535
PRIOR_INSTANCE_IDS_SHA256 = "aafdd077730bd057df6746978acbd05dafdc683aebcdf43b5f516fbffb0baf14"
PRIOR_SEED_UNION_COUNT = 3152
PRIOR_SEED_UNION_SHA256 = "c4c55096579e341add56ba75df56739c458d2e5e46aece1104334ec0e549f2d3"
FOUND_SEED_COUNT = 1965
FOUND_SEEDS_SHA256 = "1952e7113d4f065c39157f4ab811aa20fde9a4a78bed6ee39ca3bac54cda3d6d"

REQUIRED_PHRASES = [
    # task identity and offline scope
    "#220", "#218", "#159", "#219", "#221", "legal:low", "L02",
    "no provider call", "zero network events", "nothing here authorizes collection",
    # census identity and reproducibility
    "jev-legal-p02-form-census-v1",
    CENSUS_CONTENT_HASH,
    "byte-for-byte", "fail closed on drift",
    # inventory and exceptions
    "1074", "1069", "audit exceptions, never empty sets",
    "runs/container-isolation.json", "runs/opencode-go-container/",
    PRIOR_INSTANCE_IDS_SHA256, PRIOR_SEED_UNION_SHA256, FOUND_SEEDS_SHA256,
    "Stated exclusions", ".chainlink/issues.db",
    # windows
    "85000", "87511", "88000", "88511", "89000", "89511",
    "no seed may ever be selected", "chosen offline after the inventory",
    "No held-out/confirmation window is chosen here",
    # census and capacity
    "k = 4", "Per-form capacity", "distinct seeds never add form units",
    "[32, 4], [64, 4], [128, 4], [256, 4], [512, 4]",
    # closure
    "exhaustive enumeration", "finite form space", "(bit0, bit2)",
    "Residual unknowns", "proven, not merely observed",
    # hashes
    "pre_read_state_hash", "option_set_hash", "branch_request_hashes",
    "branch_state_hashes", "pre_read_request_body_hash",
    # structure
    "finalizer_needs_peer", "authoritative", "fictional_fact_1",
    "I_m = 1.0 bit", "I_m = 0.0 bit", "ExactInformationEvaluator",
    # dependence
    "hash-distinct but not independent", "assumption-dependent",
    "complete 2×2 factorial", "state.clues", TEMPLATE_HASH,
    # overlap
    "disjoint_from_all_accessible_prior_artifacts", "1024 unique",
    "inaccessible_locations_remaining",
    # consequence and handoff
    "0.125", "L03 (#221)", "no legal-family effect-size prior",
    "35/35", "provider_calls: 0", "Handoff to L03",
    "A predecessor closed as failed does not authorize successor execution",
    "L07 gate",
]

BANNED_PHRASES = [
    "this task authorizes collection",
    "authorizes the live run",
    "locking authorizes execution",
    "proves the hypothesis",
    "confirms the effect",
    "population-representative",
    "generalizes to other families",
    "the winning family",
    "closure is unknown",
    "closure unproven",
    "no prior manifests found",
    "the prior inventory is empty",
    "legal:low collection is authorized",
    "authorized by this census",
]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _explode(*_args, **_kwargs):
    raise AssertionError("provider call attempted during an offline L02 check")


_NETWORK_EVENTS: list[str] = []


def _audit_hook(event, _args):
    if event.startswith(("socket.", "urllib.", "http.client.", "ftplib.")):
        _NETWORK_EVENTS.append(event)


sys.addaudithook(_audit_hook)

_BUILT: dict | None = None


def build_offline() -> dict:
    """Build the census once per process, under a raising urlopen stub."""

    global _BUILT
    if _BUILT is None:
        _NETWORK_EVENTS.clear()
        with patch("urllib.request.urlopen", _explode):
            document = census.build_census(REPO_ROOT)
        assert _NETWORK_EVENTS == [], f"network event during the offline build: {_NETWORK_EVENTS}"
        _BUILT = document
    return _BUILT


class L02TestCase(unittest.TestCase):
    """Every test proves the frozen inputs stayed byte-identical."""

    def setUp(self):
        self.before = {relative: sha256_of(REPO_ROOT / relative)
                       for relative in FROZEN_PATHS}
        self.legal_outputs_before = sorted(
            path.name for path in (REPO_ROOT / "runs" / "next-phase" / "legal").glob("*"))

    def tearDown(self):
        self.assertEqual({relative: sha256_of(REPO_ROOT / relative)
                          for relative in FROZEN_PATHS}, self.before,
                         "a frozen, L01 or L02 input changed during the test")
        self.assertEqual(sorted(path.name for path in
                                (REPO_ROOT / "runs" / "next-phase" / "legal").glob("*")),
                         self.legal_outputs_before,
                         "the legal output directory changed state during the test")


class ContentHashTests(L02TestCase):
    def setUp(self):
        super().setUp()
        self.census = json.loads(CENSUS_PATH.read_text(encoding="utf-8"))
        self.text = DOC_PATH.read_text(encoding="utf-8")
        self.normalized = " ".join(self.text.split())

    def test_census_content_hash_recomputes_and_is_pinned_in_the_doc(self):
        recomputed = hashlib.sha256(
            json.dumps({key: value for key, value in self.census.items()
                        if key != "content_hash"}, sort_keys=True).encode()).hexdigest()
        self.assertEqual(recomputed, CENSUS_CONTENT_HASH)
        self.assertEqual(self.census["content_hash"], CENSUS_CONTENT_HASH)
        self.assertIn(CENSUS_CONTENT_HASH, self.normalized)

    def test_frozen_input_pins_recompute_from_disk(self):
        for relative, expected in PINNED_SHA256.items():
            with self.subTest(path=relative):
                self.assertEqual(sha256_of(REPO_ROOT / relative), expected)
        recorded = {entry["path"]: entry["sha256"]
                    for entry in self.census["frozen_input_evidence"]["inputs"]}
        self.assertEqual(recorded, PINNED_SHA256)
        self.assertTrue(all(entry["prefix_match"] is not False
                            for entry in self.census["frozen_input_evidence"]["inputs"]))

    def test_generator_sources_are_pinned_in_the_artifact(self):
        sources = {entry["path"]: entry["sha256"]
                   for entry in self.census["frozen_input_evidence"]["sources"]}
        self.assertIn("src/apart_incident_response/jev_legal_form_census.py", sources)
        self.assertIn("src/apart_incident_response/task_families.py", sources)
        for relative, digest in sources.items():
            with self.subTest(path=relative):
                self.assertEqual(sha256_of(REPO_ROOT / relative), digest)


class InventoryTests(L02TestCase):
    def setUp(self):
        super().setUp()
        self.inventory = json.loads(CENSUS_PATH.read_text(encoding="utf-8"))[
            "prior_manifest_inventory"]

    def test_inventory_coverage_and_scan_scope(self):
        self.assertEqual(self.inventory["manifest_files_discovered"], 1074)
        self.assertEqual(self.inventory["manifest_files_scanned"], 1069)
        self.assertEqual(self.inventory["scan_scope"]["root"], "runs")
        self.assertEqual(self.inventory["scan_scope"]["chain_output_prefixes_excluded"],
                         ["runs/next-phase/legal/"])
        excluded = {entry["path"] for entry in
                    self.inventory["scan_scope"]["excluded_sources"]}
        self.assertIn("runs/next-phase/legal/**", excluded)
        self.assertIn(".chainlink/issues.db", excluded)
        self.assertTrue(self.inventory["scan_scope"]["excluded_sources_are_stated_not_empty"])

    def test_inaccessible_manifests_are_audit_exceptions_not_empty_sets(self):
        files = [item["path"] for item in self.inventory["inaccessible_manifests"]]
        directories = [item["path"] for item in
                       self.inventory["inaccessible_directories"]]
        self.assertIn("runs/container-isolation.json", files)
        self.assertIn("runs/t1-container/matrix.json", files)
        self.assertEqual(len(files), 5)
        self.assertIn("runs/opencode-go-container/", directories)
        self.assertIn("runs/openrouter/pilot-container-3/", directories)
        self.assertEqual(len(directories), 15)
        self.assertTrue(self.inventory["exceptions_are_audit_exceptions_not_empty_sets"])
        self.assertIn("never as empty sets", self.inventory["statement"])

    def test_prior_ids_seeds_and_union_are_recorded(self):
        ids = self.inventory["instance_ids"]
        self.assertEqual(ids["count"], PRIOR_INSTANCE_ID_COUNT)
        self.assertEqual(ids["sha256"], PRIOR_INSTANCE_IDS_SHA256)
        self.assertEqual(ids["legal_family_instance_id_count"], 45)
        found = self.inventory["found_seeds"]
        self.assertEqual(found["count"], FOUND_SEED_COUNT)
        self.assertEqual(found["sha256"], FOUND_SEEDS_SHA256)
        self.assertEqual(found["max"], 87511)
        union = self.inventory["prior_seed_union"]
        self.assertEqual(union["count"], PRIOR_SEED_UNION_COUNT)
        self.assertEqual(union["sha256"], PRIOR_SEED_UNION_SHA256)
        self.assertEqual(union["max"], 87511)
        self.assertEqual(union["sources"], ["found in accessible run manifests",
                                            "documented prior seed ranges",
                                            "reserved hypothesis windows"])
        self.assertNotIn("_seeds", union)

    def test_reserved_hypothesis_windows_and_documented_ranges_are_listed(self):
        reserved = [(entry["low"], entry["high"])
                    for entry in self.inventory["reserved_hypothesis_windows"]]
        self.assertEqual(reserved, [(85000, 85511), (86000, 86511), (87000, 87511)])
        self.assertEqual(self.inventory["reserved_hypothesis_span"], [85000, 87511])
        self.assertIn([16000, 17104], self.inventory["documented_seed_ranges"])
        self.assertIn([75000, 75255], self.inventory["documented_seed_ranges"])

    def test_chain_own_namespace_is_excluded_and_l01_is_pinned(self):
        chain = self.inventory["chain_own_namespace_excluded"]
        self.assertEqual(chain["prefixes"], ["runs/next-phase/legal/"])
        self.assertEqual(chain["known_prior_files"],
                         ["runs/next-phase/legal/jev-legal-p01-evidence-v1.json"])


class WindowTests(L02TestCase):
    def setUp(self):
        super().setUp()
        document = json.loads(CENSUS_PATH.read_text(encoding="utf-8"))
        self.windows = document["windows"]
        self.overlap = document["seed_id_overlap"]

    def test_windows_are_the_fresh_discovery_and_closure_probe_pair(self):
        roles = {window["role"]: window for window in self.windows["windows"]}
        self.assertEqual(sorted(roles), ["closure_probe", "discovery"])
        self.assertEqual((roles["discovery"]["base"], roles["discovery"]["end"]),
                         (88000, 88511))
        self.assertEqual((roles["closure_probe"]["base"], roles["closure_probe"]["end"]),
                         (89000, 89511))
        for role in roles:
            with self.subTest(role=role):
                self.assertEqual(roles[role]["window"], 512)
                self.assertTrue(roles[role]["chosen_after_inventory"])
                self.assertEqual(roles[role]["candidates_skipped"], 0)
        self.assertIn("no seed may ever be selected",
                      roles["closure_probe"]["description"])

    def test_windows_are_derived_from_the_completed_inventory(self):
        self.assertTrue(self.windows["chosen_after_inventory"])
        self.assertTrue(self.windows["inventory_first"])
        self.assertEqual(self.windows["candidate_floor"], 88000)
        self.assertIn("max 87511", self.windows["floor_derivation"])
        self.assertTrue(self.windows["discovery_vs_closure_probe_disjoint"])
        self.assertFalse(self.windows["hypothesis_windows_reused"])
        self.assertEqual(self.windows["hypothesis_span_never_reused"], [85000, 87511])

    def test_hypothesis_span_is_never_touched(self):
        for window in self.windows["windows"]:
            with self.subTest(role=window["role"]):
                self.assertGreaterEqual(window["base"], 87512)
        self.assertEqual(self.overlap["reserved_hypothesis_window_overlaps"], [])
        self.assertEqual(self.overlap["documented_seed_range_overlaps"], [])

    def test_no_held_out_window_is_fixed_at_l02(self):
        held_out = self.windows["held_out_window"]
        self.assertFalse(held_out["fixed_by_l02"])
        self.assertIn("inventory-first rule", held_out["statement"])


class CapacityTests(L02TestCase):
    def setUp(self):
        super().setUp()
        document = json.loads(CENSUS_PATH.read_text(encoding="utf-8"))
        self.census = document["census"]
        self.capacity = document["form_capacity"]

    def test_k_is_four_with_the_derived_form_set(self):
        self.assertEqual(self.capacity["k"], 4)
        self.assertEqual(sorted(self.capacity["form_ids"]), FORM_IDS)
        self.assertEqual(self.capacity["form_set_hash"],
                         "ad2f6bee676229527b067912c4259f8fb7f9e4e0e989685d5afa8613f48e5633")
        self.assertTrue(self.capacity["distinct_seeds_are_not_form_units"])

    def test_every_window_reports_the_same_four_forms(self):
        for role in ("discovery", "closure_probe"):
            with self.subTest(role=role):
                self.assertEqual(self.census[role]["distinct_forms"], 4)
                self.assertEqual(sorted(self.census[role]["forms"]), FORM_IDS)
                self.assertEqual(self.census[role]["growth_checkpoints"],
                                 [[32, 4], [64, 4], [128, 4], [256, 4], [512, 4]])

    def test_per_form_capacity_sums_to_the_window_sizes(self):
        per_form = self.capacity["per_form_capacity"]
        self.assertEqual(sorted(per_form), FORM_IDS)
        self.assertEqual(sum(entry["discovery"] for entry in per_form.values()), 512)
        self.assertEqual(sum(entry["closure_probe"] for entry in per_form.values()), 512)
        self.assertEqual(sum(entry["total_seeds"] for entry in per_form.values()), 1024)
        self.assertEqual(min(entry["discovery"] for entry in per_form.values()), 121)
        self.assertEqual(min(entry["closure_probe"] for entry in per_form.values()), 105)
        self.assertEqual(self.capacity["min_seeds_per_form"], 105)
        self.assertGreaterEqual(self.capacity["min_seeds_per_form"],
                                self.capacity["instances_per_form_reference"])

    def test_window_seed_lists_are_recorded_for_later_selection(self):
        for role, base in (("discovery", 88000), ("closure_probe", 89000)):
            with self.subTest(role=role):
                seeds = [seed for form in FORM_IDS
                         for seed in self.census[role]["forms"][form]]
                self.assertEqual(len(seeds), 512)
                self.assertEqual(len(set(seeds)), 512)
                self.assertEqual(sorted(seeds), list(range(base, base + 512)))


class ClosureTests(L02TestCase):
    def setUp(self):
        super().setUp()
        self.closure = json.loads(CENSUS_PATH.read_text(encoding="utf-8"))["closure"]

    def test_closure_is_proven_not_merely_observed(self):
        self.assertEqual(self.closure["status"], "closed")
        self.assertTrue(self.closure["proven"])
        self.assertEqual(self.closure["basis"],
                         "generator-level exhaustive enumeration of the finite form space")
        argument = self.closure["generator_argument"]
        self.assertEqual(argument["upper_bound_distinct_forms"], 4)
        self.assertTrue(argument["form_is_function_of_bit0_bit2"])
        self.assertEqual(argument["distinct_forms_enumerated"], 4)
        self.assertEqual(argument["realized_forms"], 4)

    def test_enumeration_covers_all_eight_targets(self):
        rows = self.closure["generator_argument"]["exhaustive_enumeration"]
        self.assertEqual(sorted(row["target_number"] for row in rows), list(range(8)))
        self.assertEqual({row["target"] for row in rows},
                         {f"disposition-{number}" for number in range(8)})
        by_pair = {}
        for row in rows:
            by_pair.setdefault((row["bit0"], row["bit2"]), set()).add(row["form_id"])
        self.assertEqual(sorted(by_pair), [(0, 0), (0, 1), (1, 0), (1, 1)])
        for pair, forms in by_pair.items():
            with self.subTest(pair=pair):
                self.assertEqual(len(forms), 1)
        self.assertEqual(sorted(by_pair[(0, 0)]), ["309706db278f790720bf76f19b248ff43"
                                                  "e5eaf178d250cd60f9defccfb7b00c9"])

    def test_closure_probe_observed_saturation_corroborates(self):
        observed = self.closure["observed_saturation"]
        self.assertEqual(observed["closure_probe_distinct_forms"], 4)
        self.assertEqual(observed["closure_probe_new_forms"], 0)
        self.assertEqual(observed["all_windows_distinct_forms"], [4, 4])

    def test_residual_unknowns_are_stated(self):
        unknowns = self.closure["residual_unknowns"]
        self.assertIsInstance(unknowns, list)
        self.assertGreaterEqual(len(unknowns), 3)
        joined = " ".join(unknowns)
        self.assertIn("generator configuration", joined)
        self.assertIn("statistical independence", joined)
        self.assertIn("authorizes no collection", joined)


class FormRecordTests(L02TestCase):
    def setUp(self):
        super().setUp()
        document = json.loads(CENSUS_PATH.read_text(encoding="utf-8"))
        self.records = document["form_records"]["per_form"]
        self.pre_read = document["pre_read_hashes"]["per_form"]

    def test_records_cover_every_form_with_hashes(self):
        self.assertEqual(sorted(self.records), FORM_IDS)
        self.assertEqual(sorted(self.pre_read), FORM_IDS)
        for form, record in self.records.items():
            with self.subTest(form=form):
                self.assertEqual(record["pre_read_request_body_hash"], form)
                self.assertEqual(self.pre_read[form]["pre_read_state_hash"],
                                 record["pre_read_state_hash"])
                self.assertEqual(self.pre_read[form]["option_set_hash"], OPTION_SET_HASH)
                self.assertEqual(record["option_set_hash"], OPTION_SET_HASH)
                self.assertEqual(record["option_count"], 8)
                self.assertEqual(sorted(record["branch_request_hashes"]),
                                 ["null", "placebo", "real"])
                self.assertEqual(sorted(record["branch_state_hashes"]),
                                 ["null", "placebo", "real"])
                self.assertTrue(record["a_finalizer_peer_need"]["finalizer_needs_peer"])

    def test_hashes_recompute_from_the_generator(self):
        for form, record in self.records.items():
            with self.subTest(form=form):
                instance = rep.instance_for("legal", int(record["representative_seed"]))
                self.assertEqual(instance.instance_id, record["representative_instance"])
                self.assertEqual(rep.pre_read_form_id(instance), form)
                geometry = rep._instance_geometry(instance)
                hashes = rep.branch_hashes(instance, geometry["real_claim"],
                                            geometry["placebo_claim"])
                self.assertEqual(hashes["pre_read_request_body_hash"], form)
                self.assertEqual(hashes["pre_read_state_hash"],
                                 record["pre_read_state_hash"])
                self.assertEqual(hashes["branch_request_hashes"],
                                 record["branch_request_hashes"])
                self.assertEqual(hashes["branch_state_hashes"],
                                 record["branch_state_hashes"])

    def test_a_finalizer_peer_need_and_authoritative_b_claim(self):
        for form, record in self.records.items():
            with self.subTest(form=form):
                peer = record["a_finalizer_peer_need"]
                self.assertTrue(peer["finalizer_needs_peer"])
                self.assertGreater(peer["private_a_size"], peer["joint_size"])
                self.assertTrue(peer["channel_complete"])
                self.assertTrue(peer["both_agents_needed"])
                claim = record["authoritative_b_owned_informative_claim"]
                self.assertTrue(claim["owned_by_b"])
                self.assertEqual(claim["claim_owner"], "B")
                self.assertFalse(claim["held_by_a_before_message"])
                self.assertEqual(claim["information_status"], "accepted")
                self.assertEqual(claim["i_m_bits"], 1.0)
                self.assertEqual((claim["before_count"], claim["after_count"]), (2, 1))
                placebo = record["placebo_claim"]
                self.assertTrue(placebo["owned_by_a"])
                self.assertTrue(placebo["inert"])
                self.assertEqual(placebo["i_m_bits"], 0.0)

    def test_structural_preconditions_hold_in_both_windows(self):
        per_window = json.loads(CENSUS_PATH.read_text(encoding="utf-8"))[
            "structural_preconditions"]["per_window"]
        self.assertEqual(sorted(per_window), ["closure_probe", "discovery"])
        for role, entry in per_window.items():
            with self.subTest(role=role):
                self.assertTrue(entry["closed_finite_solution_set"])
                self.assertTrue(entry["finalizer_needs_peer"])
                self.assertTrue(entry["eligible"])
                self.assertEqual(entry["informative_b_owned_claims"], 512)
                self.assertEqual(entry["b_to_a_information_bits"], [1.0])
                self.assertEqual(entry["b_clues_per_instance"], 1)
                self.assertEqual(entry["a_clues_per_instance"], 2)


class DependenceTests(L02TestCase):
    def setUp(self):
        super().setUp()
        document = json.loads(CENSUS_PATH.read_text(encoding="utf-8"))
        self.dependence = document["dependence_assessment"]
        self.audit_200 = json.loads(AUDIT_200.read_text(encoding="utf-8"))

    def test_shared_template_identical_except_state_clues(self):
        self.assertTrue(self.dependence["shared_template"])
        self.assertEqual(self.dependence["template_hash"], TEMPLATE_HASH)
        self.assertEqual(self.dependence["identical_except"], ["state.clues"])
        template = self.dependence["template"]
        self.assertEqual(template["model"], "jev-1.13.0")
        self.assertEqual(template["option_ids"],
                         [f"disposition-{index}" for index in range(8)])
        self.assertEqual(sorted(template["state_keys_except_clues"]),
                         ["agent_id", "complexity", "family"])

    def test_form_cells_are_the_complete_factorial(self):
        cells = self.dependence["form_cells"]
        self.assertEqual(len(cells), 4)
        pairs = sorted((cell["bit0"], cell["bit2"]) for cell in cells.values())
        self.assertEqual(pairs, [(0, 0), (0, 1), (1, 0), (1, 1)])
        self.assertEqual(self.dependence["factorial_pairs"],
                         [[0, 0], [0, 1], [1, 0], [1, 1]])
        for form, cell in cells.items():
            with self.subTest(form=form):
                self.assertEqual(cell["clues"],
                                 [f"fictional_fact_0={cell['bit0']}",
                                  f"fictional_fact_2={cell['bit2']}"])

    def test_hash_distinct_not_independent_and_assumption_dependent(self):
        self.assertTrue(self.dependence["hash_distinct_not_independent"])
        consequence = self.dependence["consequence"]
        self.assertIn("assumption-dependent", consequence)
        self.assertIn("0.125", consequence)
        self.assertIn("L03's (#221)", consequence)

    def test_legal_forms_are_disjoint_from_the_frozen_hypothesis_forms(self):
        self.assertEqual(sorted(self.audit_200["form_capacity"]["form_ids"]),
                         HYPOTHESIS_FORM_IDS)
        self.assertTrue(set(FORM_IDS).isdisjoint(HYPOTHESIS_FORM_IDS))
        document = json.loads(CENSUS_PATH.read_text(encoding="utf-8"))
        check = next(entry for entry in document["checks"]
                     if entry["check"] == "legal_forms_disjoint_from_hypothesis_forms")
        self.assertTrue(check["ok"])


class OverlapTests(L02TestCase):
    def setUp(self):
        super().setUp()
        self.overlap = json.loads(CENSUS_PATH.read_text(encoding="utf-8"))["seed_id_overlap"]

    def test_every_overlap_list_is_empty_and_disjointness_is_qualified(self):
        for key in ("selected_ids_overlapping_prior",
                    "selected_seeds_overlapping_prior",
                    "selected_legal_instance_ids_overlapping_prior_legal_ids",
                    "discovery_vs_closure_probe_seed_overlap",
                    "discovery_vs_closure_probe_instance_id_overlap",
                    "reserved_hypothesis_window_overlaps",
                    "documented_seed_range_overlaps"):
            with self.subTest(key=key):
                self.assertEqual(self.overlap[key], [])
        self.assertTrue(self.overlap["disjoint_from_all_accessible_prior_artifacts"])
        self.assertEqual(self.overlap["inaccessible_locations_remaining"], 20)
        self.assertIn("never treated as empty sets", self.overlap["qualification"])

    def test_selected_ids_are_unique_and_pinned(self):
        selected = self.overlap["selected"]
        self.assertEqual(selected["instance_id_count"], 1024)
        self.assertEqual(selected["instance_ids_unique"], 1024)
        self.assertEqual(selected["seed_count"], 1024)
        self.assertEqual(selected["seeds_sha256"],
                         "3fd851f847af5be1b67aaee5e381c764133c20a7c772b97332ad22089c51379f")
        self.assertEqual(selected["per_window"]["discovery"]["first_instance_id"],
                         "legal-000157c0")
        self.assertEqual(selected["per_window"]["closure_probe"]["first_instance_id"],
                         "legal-00015ba8")

    def test_prior_set_digests_match_the_inventory(self):
        self.assertEqual(self.overlap["prior_instance_id_count"],
                         PRIOR_INSTANCE_ID_COUNT)
        self.assertEqual(self.overlap["prior_instance_ids_sha256"],
                         PRIOR_INSTANCE_IDS_SHA256)
        self.assertEqual(self.overlap["prior_seed_union_count"],
                         PRIOR_SEED_UNION_COUNT)
        self.assertEqual(self.overlap["prior_seed_union_sha256"],
                         PRIOR_SEED_UNION_SHA256)
        self.assertEqual(len(self.overlap["prior_legal_family_instance_ids"]), 45)


class DeterministicRebuildTests(L02TestCase):
    def test_census_rebuilds_byte_for_byte_under_audit(self):
        _NETWORK_EVENTS.clear()
        document = build_offline()
        self.assertEqual(_NETWORK_EVENTS, [])
        self.assertEqual(json.loads(CENSUS_PATH.read_text(encoding="utf-8")), document)
        self.assertEqual(census._render(document), CENSUS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(document["network_audit"]["events"], 0)
        self.assertEqual(document["network_audit"]["provider_calls"], 0)

    def test_every_named_check_passes(self):
        document = json.loads(CENSUS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(document["checks"]), 35)
        self.assertEqual([entry["check"] for entry in document["checks"] if not entry["ok"]],
                         [])
        self.assertTrue(all(entry["ok"] for entry in document["checks"]))
        self.assertEqual(document["provider_calls"], 0)
        self.assertTrue(document["offline_only"])
        self.assertIn("no provider call", document["authorizes"])

    def test_cli_verification_is_green_with_a_raising_urlopen(self):
        buffer = io.StringIO()
        calls = []

        def explode(*args, **kwargs):
            calls.append(1)
            raise AssertionError("provider call attempted offline")

        with patch("urllib.request.urlopen", explode):
            with contextlib.redirect_stdout(buffer):
                rc = census.main(["--repo-root", str(REPO_ROOT)])
        self.assertEqual(calls, [])
        self.assertEqual(rc, 0)
        verification = json.loads(buffer.getvalue())
        self.assertTrue(verification["ok"], verification["failed"])
        self.assertEqual(verification["failed"], [])
        self.assertGreaterEqual(len(verification["checks"]), 40)
        self.assertEqual(verification["provider_calls"], 0)
        self.assertEqual(verification["content_hash"], CENSUS_CONTENT_HASH)

    def test_build_refuses_to_overwrite_an_existing_census(self):
        with self.assertRaises(FileExistsError):
            census.write_census({"content_hash": "ignored"}, repo_root=REPO_ROOT)

    def test_output_path_is_fresh_and_not_a_hypothesis_path(self):
        self.assertEqual(str(census.CENSUS_PATH),
                         "runs/next-phase/legal/jev-legal-p02-form-census-v1.json")
        self.assertNotIn(str(census.CENSUS_PATH), census.HYPOTHESIS_OUTPUT_PATHS)
        for path in census.HYPOTHESIS_OUTPUT_PATHS:
            with self.subTest(path=path):
                self.assertTrue((REPO_ROOT / path).exists())


class HandoffTests(L02TestCase):
    def test_handoff_targets_l03_without_authorizing_anything(self):
        document = json.loads(CENSUS_PATH.read_text(encoding="utf-8"))
        handoff = document["handoff"]
        self.assertEqual(handoff["to"], "L03")
        self.assertEqual(handoff["issue"], 221)
        joined = " ".join(handoff["conditions"])
        self.assertIn("reviewer approval", joined)
        self.assertIn("L07", joined)
        self.assertIn("never authorizes its successor", joined)
        self.assertTrue(document["limitations"])
        self.assertIn("no provider call", " ".join(document["limitations"]))
        self.assertEqual(document["capacity_consequence_for_l03"]["classification_owned_by"],
                         "L03 (#221)")
        self.assertEqual(document["capacity_consequence_for_l03"][
            "attainable_two_sided_sign_flip_floor"], "0.125")
        self.assertTrue(document["capacity_consequence_for_l03"]["floor_above_0_05"])
        self.assertIn("no legal-family effect-size prior",
                      document["capacity_consequence_for_l03"]["no_legal_effect_size_prior"])


class DocContentTests(L02TestCase):
    def setUp(self):
        super().setUp()
        text = DOC_PATH.read_text(encoding="utf-8")
        self.normalized = " ".join(text.split())
        self.normalized_lower = self.normalized.lower()

    def test_required_statements_are_present(self):
        for phrase in REQUIRED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)

    def test_no_authorization_language_slips_in(self):
        for phrase in BANNED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase.lower(), self.normalized_lower)

    def test_doc_pins_every_frozen_input_digest(self):
        for digest in PINNED_SHA256.values():
            with self.subTest(digest=digest):
                self.assertIn(digest, self.normalized)

    def test_handoff_section_records_the_successor_conditions(self):
        handoff = " ".join(self.normalized.split("## 11. Handoff")[1].split())
        self.assertIn("L03 (#221)", handoff)
        self.assertIn("A predecessor closed as failed does not authorize successor "
                      "execution", handoff)
        self.assertIn("blocked until the plugin records #220 closed", handoff)


if __name__ == "__main__":
    unittest.main()
