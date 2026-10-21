"""L03 (#221) focused validation: offline legal design decision, zero network.

Everything in this suite is recomputed from files on disk. A process-wide audit
hook records any ``socket.*`` / ``urllib.*`` / ``http.client.*`` /
``ftplib.*`` event and ``urllib.request.urlopen`` is replaced by a raising stub
for the build, so a provider call fails the suite instead of escaping it. The
frozen #200/#207/#215 inputs, the L01/L02 handoffs and this chain's outputs
are asserted byte-identical before and after every test.
"""

import contextlib
import hashlib
import io
import json
import sys
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import jev_legal_p03_design as design
from apart_incident_response import jev_replication_preregistration as rep

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = REPO_ROOT / design.DESIGN_PATH
DOC_PATH = REPO_ROOT / design.DOC_PATH
MODULE_PATH = REPO_ROOT / "src/apart_incident_response/jev_legal_p03_design.py"

#: Self-recorded content hash of the committed design artifact.
DESIGN_CONTENT_HASH = "adf52cb7b7d62e532acc0b8f26c000582e4a291767f737558f016fdf9eafed06"

#: sha256 recomputed from disk; the frozen-input table pins these.
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
    "docs/jev-cross-family-entropy-program-v1.md":
        "d9acace24a0cdbfc9a41e331b1fd422f07f22e3fc01480e6408af78d9de4be05",
    "runs/next-phase/legal/jev-legal-p02-form-census-v1.json":
        "4bffa5cda2433a81efb41025f42fdd82c585c41798ff2c55e9d853aa45681d24",
    "docs/jev-legal-p02-capacity.md":
        "25fac868d502b05ede479fa7e68161f8f4fd4db33267a0f01d710f2d0adec2fa",
}

FROZEN_PATHS = sorted(set(PINNED_SHA256) | {
    str(design.DESIGN_PATH),
    str(design.DOC_PATH),
    "src/apart_incident_response/jev_legal_p03_design.py",
})

#: Derived findings pinned after the offline build (recomputed, not trusted).
FORM_IDS = [
    "309706db278f790720bf76f19b248ff43e5eaf178d250cd60f9defccfb7b00c9",
    "3ca0223020c4113d4a8147d3b611c414248eb64369497f9a5f6a4a7f78a0df9f",
    "935f84146a383fa027fb55446dd011c55d81f32151477d56ca85d7e155b8c809",
    "bb6fcd3ffb95e480cd779f380549bfca873e86b8c313825d97d14c6ea7b6ca07",
]
EXPECTED_SEEDS = [88008, 88020, 88026, 88031, 88006, 88009, 88011, 88017,
                  88004, 88005, 88010, 88013, 88000, 88001, 88002, 88003]
MIN_K_BY_FAMILY_COUNT = {1: 6, 2: 7, 7: 9, 8: 9}

REQUIRED_PHRASES = [
    # task identity and offline scope
    "#221", "#218", "#159", "#220", "#222", "#227", "legal:low", "L03",
    "no provider call", "zero network events", "L07", "A failed or stopped predecessor",
    # artifact identity and reproducibility
    "jev-legal-p03-design-v1", DESIGN_CONTENT_HASH,
    "byte-for-byte", "fail closed on drift",
    # derivation
    "2/2^k = 2/2^4 = 2/16 = 1/8 = 0.125", "k = 4", "attainable",
    "1/140", "1/160", "no legal-family effect-size prior",
    # classification
    "descriptive discovery", "not no-go", "no dichotomous rejection",
    "potentially confirmatory", "registered legal estimand is preserved",
    "H0 `Delta = 0`", "H1 `Delta < 0`", "two-sided",
    # exchangeability
    "template-identical", "assumption-dependent", "state.clues",
    "35b03db195dd6aed416005b5fa3f985e08572c66d058fed6572d9bff975ef6f6",
    "2×2 factorial", "not a sample from a",
    # screen and capacity
    "88000–88511", "89000–89511", "fixed N = 16", "first `s*` seeds per form",
    "INSTANCES_PER_FORM = 4", "legal-000157c8", "consulted_outcomes: []",
    "never selectable", "no held-out/confirmation window is chosen here",
    # scenarios, stops and coverage
    "0.00067584", "0.000344064", "$0.20", "$0.30", "0.146276352",
    "0.195821568", "0.292552704", "0.391643136", "retry-inclusive",
    "truncated_output", "fixed manifest as an immutable journal",
    "at least 1 complete instance per form", "No imputation",
    "no replenishment from spare capacity",
    # frozen artifacts and handoff
    "byte-identically", "frozen historical queue", "not Jev entropy evidence",
    "Handoff to L04", "follows #227", "microbenchmarks", "explicit no-go",
]

BANNED_PHRASES = [
    "this task authorizes collection",
    "authorizes the live run",
    "locking authorizes execution",
    "legal:low collection is authorized",
    "confirmatory support for legal",
    "legal:low is confirmatory",
    "k = 6 for legal",
    "seeds increase k",
    "population-representative",
    "the winning family",
    "no prior manifests found",
    "closure unproven",
    "we ran a probe",
    "a live request was made",
]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _explode(*_args, **_kwargs):
    raise AssertionError("provider call attempted during an offline L03 check")


_NETWORK_EVENTS: list[str] = []


def _audit_hook(event, _args):
    if event.startswith(design.NETWORK_EVENT_PREFIXES):
        _NETWORK_EVENTS.append(event)


sys.addaudithook(_audit_hook)

_BUILT: dict | None = None


def build_offline() -> dict:
    """Build the design artifact once per process, under a raising stub."""

    global _BUILT
    if _BUILT is None:
        _NETWORK_EVENTS.clear()
        with patch("urllib.request.urlopen", _explode):
            document = design.build_design(REPO_ROOT)
        assert _NETWORK_EVENTS == [], f"network event during the offline build: {_NETWORK_EVENTS}"
        _BUILT = document
    return _BUILT


class L03TestCase(unittest.TestCase):
    """Every test proves the frozen inputs stayed byte-identical."""

    def setUp(self):
        self.before = {relative: sha256_of(REPO_ROOT / relative)
                       for relative in FROZEN_PATHS}
        self.document = build_offline()
        self.artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        self.doc_text = DOC_PATH.read_text(encoding="utf-8")

    def tearDown(self):
        after = {relative: sha256_of(REPO_ROOT / relative)
                 for relative in FROZEN_PATHS}
        self.assertEqual(self.before, after, "a frozen input changed byte-for-byte")

    def test_committed_artifact_matches_build(self):
        self.assertEqual(self.artifact, self.document)
        self.assertEqual(self.artifact["content_hash"], DESIGN_CONTENT_HASH)

    def test_pinned_input_hashes_recompute_from_disk(self):
        for relative, expected in PINNED_SHA256.items():
            with self.subTest(path=relative):
                self.assertEqual(sha256_of(REPO_ROOT / relative), expected)

    def test_floor_is_derived_from_k_not_copied(self):
        floor = self.document["derivation"]["sign_flip_floor"]
        exact = Fraction(2, 2 ** 4)
        self.assertEqual(floor["k"], 4)
        self.assertEqual(floor["numerator"], 2)
        self.assertEqual(floor["denominator"], 16)
        self.assertEqual(floor["exact_fraction"], "2/16")
        self.assertEqual(floor["reduced_fraction"], "1/8")
        self.assertEqual(floor["value"], str(float(exact)))
        self.assertEqual(Fraction(floor["value"]), exact)

    def test_multiplicity_grid_minima(self):
        grid = self.document["derivation"]["declared_multiplicity"]["grid"]
        self.assertEqual({row["registered_family_count"]:
                          row["min_k_for_attainable_floor"] for row in grid},
                         MIN_K_BY_FAMILY_COUNT)
        for row in grid:
            with self.subTest(m=row["registered_family_count"]):
                threshold = Fraction(1, 20) / row["registered_family_count"]
                self.assertLessEqual(Fraction(2, 2 ** row["min_k_for_attainable_floor"]),
                                     threshold)
                self.assertGreater(Fraction(2, 2 ** (row["min_k_for_attainable_floor"] - 1)),
                                   threshold)
                self.assertFalse(row["k4_floor_eligible"])

    def test_classification_is_descriptive_discovery(self):
        classification = self.document["classification"]
        self.assertEqual(classification["decision"], "descriptive_discovery")
        trace = classification["decision_trace"]
        self.assertEqual([entry["result"] for entry in trace],
                         ["structural gate passed -> continue",
                          "capacity gate passed -> continue",
                          "floor 0.125 > 0.05 -> descriptive_discovery",
                          "not reached"])

    def test_gates_pass_independently_of_the_decision(self):
        checks = {entry["check"]: entry["ok"] for entry in self.document["checks"]}
        self.assertTrue(checks["structural_gate_passes"])
        self.assertTrue(checks["capacity_gate_passes"])
        self.assertTrue(checks["confirmatory_minimum_is_six_forms"])
        self.assertTrue(checks["multiplicity_only_demands_more_forms"])

    def test_manifest_is_the_first_four_seeds_per_form(self):
        screen = self.document["discovery_screen"]
        self.assertEqual(screen["fixed_n"], 16)
        self.assertEqual(screen["instances_per_form"], 4)
        self.assertEqual([entry["seed"] for entry in screen["manifest"]], EXPECTED_SEEDS)
        self.assertEqual(sorted(screen["form_membership"]), sorted(FORM_IDS))
        self.assertTrue(all(len(ids) == 4 for ids in screen["form_membership"].values()))
        self.assertEqual(screen["outcome_blind"], True)
        self.assertEqual(screen["consulted_outcomes"], [])

    def test_manifest_rebuilds_from_the_generator(self):
        for entry in self.document["discovery_screen"]["manifest"]:
            instance = rep.instance_for("legal", entry["seed"])
            with self.subTest(seed=entry["seed"]):
                self.assertEqual(entry["instance_id"], instance.instance_id)
                self.assertEqual(entry["prompt_form_id"],
                                 rep.pre_read_form_id(instance))
                self.assertGreaterEqual(entry["seed"], 88000)
                self.assertLessEqual(entry["seed"], 88511)

    def test_scenario_arithmetic_recomputes_from_the_rate_card(self):
        ling = (8192 * 0.06 + 1024 * 0.18) / 1_000_000
        jev = 8192 * 0.042 / 1_000_000
        for scenario in self.document["request_cost_scenarios"]["scenarios"]:
            n = 4 * scenario["seeds_per_form"]
            collection = n * 4 * 3 * ling + n * 1 * 3 * jev
            replay = n * 3 * 3 * jev
            with self.subTest(seeds_per_form=scenario["seeds_per_form"]):
                self.assertAlmostEqual(scenario["collection"]["worst_case_cost_usd"],
                                       round(collection, 12), places=12)
                self.assertAlmostEqual(scenario["exploratory_replay"]["worst_case_cost_usd"],
                                       round(replay, 12), places=12)
                self.assertAlmostEqual(scenario["program"]["worst_case_cost_usd"],
                                       round(collection + replay, 12), places=12)
        scenarios = self.document["request_cost_scenarios"]["scenarios"]
        self.assertEqual([s["seeds_per_form"] for s in scenarios if s["feasible"]], [4])
        self.assertEqual(self.document["request_cost_scenarios"]["selected_seeds_per_form"], 4)
        self.assertFalse(scenarios[0]["feasible"])   # below the selection quantum
        self.assertFalse(scenarios[2]["feasible"])   # exceeds the planning ceilings

    def test_coverage_rule_and_stops_are_frozen(self):
        coverage = self.document["coverage_rule"]
        self.assertTrue(coverage["prospective"])
        self.assertTrue(coverage["frozen_before_collection"])
        self.assertEqual(coverage["min_complete_per_form"], 1)
        self.assertTrue(coverage["no_imputation"])
        self.assertTrue(coverage["no_seed_replacement"])
        self.assertTrue(coverage["no_form_removal_after_outcomes"])
        self.assertTrue(coverage["no_replenishment_from_spare_capacity"])
        stops = self.document["stop_conditions"]["stops"]
        self.assertTrue(any("cost cap" in stop for stop in stops))
        self.assertTrue(any("fixed schedule" in stop for stop in stops))
        self.assertTrue(any("truncated_output" in stop for stop in stops))

    def test_handoff_records_the_227_predecessor_and_l07_gate(self):
        handoff = self.document["handoff"]
        self.assertEqual(handoff["to"], "L04")
        self.assertEqual(handoff["issue"], 222)
        self.assertTrue(any("#227" in condition for condition in handoff["conditions"]))
        self.assertTrue(any("L07" in condition for condition in handoff["conditions"]))
        self.assertFalse(handoff["handoff_to_227"]["grants_authorization"])

    def test_estimand_and_prior_prohibitions_are_recorded(self):
        estimand = self.document["derivation"]["estimand"]
        self.assertEqual(estimand["h0"], "Delta = 0")
        self.assertEqual(estimand["h1"], "Delta < 0")
        self.assertEqual(estimand["estimand"],
                         "equal-weight form mean of real-minus-placebo entropy")
        self.assertTrue(estimand["guards_never_filter_the_estimate"])
        priors = self.document["derivation"]["priors"]
        self.assertFalse(priors["planning_low_effect_size_prior_used"])
        self.assertFalse(priors["hypothesis_low_effect_size_prior_used"])

    def test_no_live_path_exists(self):
        for relative in design.PROPOSED_PATHS.values():
            with self.subTest(path=relative):
                self.assertFalse((REPO_ROOT / relative).exists(),
                                 "a proposed live path exists before any authorization")

    def test_zero_network_events_recorded(self):
        self.assertEqual(_NETWORK_EVENTS, [], _NETWORK_EVENTS)
        self.assertEqual(self.document["network_audit"]["events"], 0)
        self.assertEqual(self.document["network_audit"]["provider_calls"], 0)
        self.assertEqual(self.document["provider_calls"], 0)

    def test_required_phrases_present_in_doc(self):
        # Search whitespace-normalized, case-folded text so that markdown line
        # wrapping and sentence-initial capitalization do not create false
        # failures; every phrase must still appear verbatim otherwise.
        haystack = " ".join(self.doc_text.split()).lower()
        for phrase in REQUIRED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), haystack)

    def test_banned_phrases_absent(self):
        haystack = (self.doc_text + json.dumps(self.document, sort_keys=True)).lower()
        for phrase in BANNED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase.lower(), haystack)


class DeterministicRebuildTests(L03TestCase):
    def test_design_rebuilds_byte_for_byte(self):
        with patch("urllib.request.urlopen", _explode):
            rebuilt = design.build_design(REPO_ROOT)
        self.assertEqual(rebuilt, self.document)
        self.assertEqual(design._render(rebuilt), ARTIFACT.read_text(encoding="utf-8"))

    def test_cli_verification_is_green(self):
        buffer = io.StringIO()

        def explode(*args, **kwargs):
            raise AssertionError("provider call attempted offline")

        with patch("urllib.request.urlopen", explode), \
                contextlib.redirect_stdout(buffer):
            code = design.main(["--repo-root", str(REPO_ROOT)])
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["ok"], payload["errors"])
        self.assertEqual(payload["provider_calls"], 0)
        self.assertEqual(payload["content_hash"], DESIGN_CONTENT_HASH)

    def test_rebuild_fails_closed_on_content_hash_drift(self):
        tampered = dict(self.document)
        tampered["content_hash"] = "0" * 64
        self.assertNotEqual(design._content_hash(tampered), tampered["content_hash"])


if __name__ == "__main__":
    unittest.main()
