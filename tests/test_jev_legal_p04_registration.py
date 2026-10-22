"""L04 (#222) focused validation: offline legal discovery registration.

Everything in this suite is recomputed from files on disk. A process-wide
audit hook records any ``socket.*`` / ``urllib.*`` / ``http.client.*`` /
``ftplib.*`` event and ``urllib.request.urlopen`` is replaced by a raising
stub for the build, so a provider call fails the suite instead of escaping
it. The frozen #200/#207/#215 inputs, the L01/L02/L03 handoffs, the stopped
hypothesis non-reuse controls and this chain's outputs are asserted
byte-identical before and after every test.
"""

import contextlib
import hashlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import jev_legal_p04_registration as reg
from apart_incident_response import jev_replication_preregistration as rep

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = REPO_ROOT / reg.REGISTRATION_PATH
DOC_PATH = REPO_ROOT / reg.DOC_PATH
MODULE_PATH = REPO_ROOT / "src/apart_incident_response/jev_legal_p04_registration.py"

#: Registered status: draft pending review; nothing is authorized.
STATUS = "draft_pending_review"

#: Self-recorded registration content hash of the committed artifact.
REGISTRATION_CONTENT_HASH = (
    "5f31630bae7fe414f054f78e1c4bb5ebf3b525d083cd3f91b81e1f89b427bde1")

#: sha256 recomputed from disk; the artifact's frozen-input table pins these.
PINNED_SHA256 = {
    "docs/jev-discovery-confirmation-plan.md":
        "501e21b6dea760371b0bf368046d8bacd203f6b92f0af754a7955d1f738677f7",
    "docs/jev-legal-task-sequence.md":
        "884b0ed4329cc47888e797478f8f00b57f7f5c9d679998d154f5a789397d0394",
    "docs/jev-cross-family-entropy-program-v1.md":
        "d9acace24a0cdbfc9a41e331b1fd422f07f22e3fc01480e6408af78d9de4be05",
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
    "runs/next-phase/legal/jev-legal-p02-form-census-v1.json":
        "4bffa5cda2433a81efb41025f42fdd82c585c41798ff2c55e9d853aa45681d24",
    "docs/jev-legal-p02-capacity.md":
        "25fac868d502b05ede479fa7e68161f8f4fd4db33267a0f01d710f2d0adec2fa",
    "runs/next-phase/legal/jev-legal-p03-design-v1.json":
        "688bc7875ff7b81bb70d60076e137b0274559b484d597f6f643ae2fb48c827ab",
    "docs/jev-legal-p03-design.md":
        "24bd6d7e8cec205bf5b5cee96f98f09afad17c85a1e825c012b536e3a2716f79",
    "research/jev/cross-family/jev-cross-family-capacity-v1.json":
        "13c526761c1f10e71382a5c5d142e47585539bad66238d3a6bfd49646b17271e",
    "docs/jev-cross-family-capacity-audit-v1.md":
        "ca8a3fefac6221b862245ed2a8bac9b43b5411dc9447e00016375192ca16c75f",
    "runs/next-phase/jev-p04-discovery-registration-v1.json":
        "78f7cd03c3afc12c94c3ba09839e4ac6ba667a3f68b96871571b274ae7d3ab11",
    "runs/next-phase/jev-discovery-authorization-record-v1.json":
        "77962311dc723b7bf0eab0bda042078ec5d8a903120dd37b023c7b93d2e6d8eb",
}

FROZEN_PATHS = sorted(set(PINNED_SHA256) | {
    str(reg.REGISTRATION_PATH),
    str(reg.DOC_PATH),
    "src/apart_incident_response/jev_legal_p04_registration.py",
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
L03_SCREEN_MANIFEST_HASH = (
    "1eeda0eacc2d891e8117e2816c7a7bf2c65c3962c8e1fa102acdc4766deefb26")

REQUIRED_PHRASES = [
    # task identity and offline scope
    "#222", "#218", "#159", "#223", "#227", "#225", "legal:low", "L04",
    "no provider call", "zero network events", "L07", "#225",
    # artifact identity and reproducibility
    reg.REGISTRATION_VERSION, "5f31630bae7fe414f054f78e1c4bb5ebf3b525d083cd3f91b81e1f89b427bde1",
    "byte-for-byte", "fail closed on drift", STATUS, "pending",
    # derivation carried from L03
    "2/2^4 = 2/16 = 1/8 = 0.125", "k = 4", "descriptive discovery",
    # manifest, windows, treatment
    "88000-88511", "89000-89511", "fixed N = 16", "outcome-blind",
    "no held-out or confirmation window is registered",
    "87000-87511", "never selectable",
    L03_SCREEN_MANIFEST_HASH, "1eeda0eacc",
    "exact-original-comm-bridge", "temperature 0.0", "1024",
    "finish_reason: length", "http_200_writer_output_cap",
    "truncated_output", "no automatic budget escalation", "ANSWER: <label>",
    # route and normalization
    "paid OpenRouter Ling SKU", "open(\"x\")",
    "tiers `exact` / `complete_renormalized`",
    # budgets, caps and ceilings
    "$0.20", "$0.10", "$0.30", "0.146276352", "0.049545216", "0.195821568",
    "384 requests", "retry", "unused budgets authorize no carry-over",
    # stops, paths, coverage, ownership
    "no-resume / no-append / no-overwrite / no-path-override",
    "frozen_before_collection", "no imputation",
    "no replenishment from spare capacity", "peer_read_exposure",
    "one deduplicated informative claim per state",
    # stopped predecessor and audit consumption
    "non-reuse controls", "never inherited", "88000-88511",
    "prospective program context",
    # authorization
    "draft_pending_review", "halts before #225",
]

BANNED_PHRASES = [
    "this registration authorizes collection",
    "authorizes the live run",
    "locking authorizes any call",
    "legal:low is authorized",
    "legal:low is confirmatory",
    "status: authorized",
    "seeds increase k",
    "population-representative",
    "the winning family",
    "we ran a probe",
    "a live request was made",
    "a live journal was written",
]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _explode(*_args, **_kwargs):
    raise AssertionError("provider call attempted during an offline L04 check")


_NETWORK_EVENTS: list[str] = []


def _audit_hook(event, _args):
    if event.startswith(reg.NETWORK_EVENT_PREFIXES):
        _NETWORK_EVENTS.append(event)


sys.addaudithook(_audit_hook)

_BUILT: dict | None = None


def build_offline() -> dict:
    """Build the registration once per process, under a raising stub."""

    global _BUILT
    if _BUILT is None:
        _NETWORK_EVENTS.clear()
        with patch("urllib.request.urlopen", _explode):
            document = reg.build_registration(REPO_ROOT)
        assert _NETWORK_EVENTS == [], (
            f"network event during the offline build: {_NETWORK_EVENTS}")
        _BUILT = document
    return _BUILT


class L04TestCase(unittest.TestCase):
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

    def test_committed_artifact_matches_build_and_status(self):
        self.assertEqual(self.artifact, self.document)
        self.assertEqual(self.document["status"], STATUS)
        self.assertEqual(self.document["registration_hash"],
                         REGISTRATION_CONTENT_HASH)
        self.assertEqual(
            self.document["registration_hash"],
            reg._content_hash(self.document, hash_key="registration_hash"))

    def test_pinned_input_hashes_recompute_from_disk(self):
        for relative, expected in PINNED_SHA256.items():
            with self.subTest(path=relative):
                self.assertEqual(sha256_of(REPO_ROOT / relative), expected)

    def test_stopped_predecessor_is_a_non_reuse_control_only(self):
        stopped = self.document["stopped_predecessor_non_reuse"]
        controls = {row["role"]: row for row in stopped["pinned_controls"]}
        self.assertEqual(
            controls["stopped hypothesis registration"]["content_hash"],
            reg.STOPPED_REGISTRATION_HASH)
        self.assertEqual(
            controls["stopped hypothesis authorization record"]
            ["scope_digest_sha256"], reg.STOPPED_SCOPE_DIGEST)
        self.assertIn("88000-88511", str(stopped["not_reused"]))
        registered_window = self.document["fixed_n"]["window"]
        self.assertEqual([registered_window["base"], registered_window["end"]],
                         [88000, 88511])
        for entry in self.document["fixed_n"]["manifest"]:
            for low, high in reg.RESERVED_HYPOTHESIS_SPANS:
                with self.subTest(seed=entry["seed"], span=(low, high)):
                    self.assertFalse(low <= entry["seed"] <= high)

    def test_classification_carries_l03_and_never_promotes(self):
        classification = self.document["design_classification"]
        self.assertEqual(classification["decision_from_l03"],
                         "descriptive_discovery")
        self.assertEqual(classification["classification"],
                         "pilot (descriptive/estimation only)")
        self.assertEqual(classification["k"], 4)
        self.assertEqual(classification["attainable_two_sided_sign_flip_floor"],
                         "0.125")
        self.assertTrue(classification["floor_above_0_05"])
        self.assertEqual(classification["confirmatory_minimum_k"], 6)
        self.assertTrue(classification["no_cross_family_promotion"])
        audit = self.document["cross_family_audit_consumption"]
        self.assertEqual(audit["issue"], 227)
        self.assertIn("promote legal:low k = 4", str(audit["does_not"]))

    def test_manifest_is_the_l03_screen_seed_for_seed(self):
        fixed = self.document["fixed_n"]
        self.assertEqual(fixed["block_n"], 16)
        self.assertEqual(fixed["instances_per_form"], 4)
        self.assertEqual(fixed["form_count"], 4)
        self.assertEqual(sorted(fixed["form_membership"]), sorted(FORM_IDS))
        self.assertTrue(all(len(ids) == 4 for ids in fixed["form_membership"].values()))
        self.assertEqual([entry["seed"] for entry in fixed["manifest"]],
                         EXPECTED_SEEDS)
        self.assertEqual(fixed["l03_screen_manifest_hash"],
                         L03_SCREEN_MANIFEST_HASH)
        self.assertEqual(fixed["manifest_hash"], L03_SCREEN_MANIFEST_HASH)
        self.assertTrue(fixed["outcome_blind"])
        self.assertEqual(fixed["consulted_outcomes"], [])
        self.assertFalse(fixed["held_out_window"]["registered_here"])

    def test_manifest_rebuilds_from_the_generator(self):
        for entry in self.document["fixed_n"]["manifest"]:
            instance = rep.instance_for("legal", entry["seed"])
            with self.subTest(seed=entry["seed"]):
                self.assertEqual(entry["instance_id"], instance.instance_id)
                self.assertEqual(entry["prompt_form_id"],
                                 rep.pre_read_form_id(instance))
                self.assertGreaterEqual(entry["seed"], 88000)
                self.assertLessEqual(entry["seed"], 88511)

    def test_treatment_bytes_and_hashes_recompute(self):
        treatment = self.document["treatment"]
        self.assertEqual(treatment["mode"], "exact-original-comm-bridge")
        self.assertEqual(treatment["rung"], "L4X")
        self.assertEqual(treatment["turns"], 2)
        self.assertEqual(treatment["agents"], ["A", "B"])
        self.assertEqual(treatment["writer_transport"]["token_budget"], 1024)
        self.assertEqual(treatment["writer_transport"]["temperature"], 0.0)
        geometry = reg.information_geometry_hash(
            json.loads((REPO_ROOT / reg.L02_CENSUS_PATH)
                       .read_text(encoding="utf-8")))
        self.assertEqual(treatment["information_geometry_hash"], geometry)
        self.assertEqual(
            treatment["manifest_treatment_hash"],
            reg.legal_manifest_treatment_hash(self.document["fixed_n"]["manifest"]))
        self.assertEqual(
            treatment["treatment_hash"],
            reg.legal_treatment_hash(treatment,
                                     treatment["manifest_treatment_hash"],
                                     treatment["information_geometry_hash"]))

    def test_writer_output_policy_is_justified_by_l01(self):
        policy = self.document["writer_output_policy"]
        self.assertEqual(policy["max_tokens"], 1024)
        self.assertEqual(policy["max_tokens"], rep.LING_OUTPUT_TOKEN_CEILING)
        justification = policy["justification_from_l01"]
        self.assertEqual(justification["diagnosis_stop_kind"],
                         "http_200_writer_output_cap")
        self.assertEqual(justification["recorded_stop_reason"],
                         "truncated_output")
        self.assertEqual(justification["max_tokens_sent_per_hypothesis_request"],
                         1024)
        self.assertEqual(justification["hypothesis_attempted_seeds"], 1)
        self.assertIn("no counterfactual exists",
                      str(justification["no_counterfactual"]))
        self.assertTrue(any("truncated_output" in item
                            for item in policy["truncation_classification"]))
        self.assertTrue(any("429" in item
                            for item in policy["truncation_classification"]))
        self.assertTrue(policy["truncation_policy"]
                        ["truncated_output_is_a_registered_terminal_writer_error"])
        self.assertTrue(policy["truncation_policy"]["no_automatic_budget_escalation"])
        self.assertTrue(policy["truncation_policy"]["no_mid_run_repair"])

    def test_route_is_first_registration_with_authorization_pending(self):
        route = self.document["route"]
        self.assertEqual(route["registered_by"], reg.REGISTRATION_VERSION)
        self.assertIn("no prior registered or authorized route",
                      route["registered_here_for_family"])
        self.assertTrue(route["authorization"].startswith("pending"))
        self.assertTrue(route["carries_nothing_forward"])
        self.assertTrue(route["independently_chosen_and_costed"])
        self.assertEqual(route["ling"]["max_tokens"], 1024)
        self.assertEqual(route["normalization"]["hard_ceiling"], 0.05)
        self.assertEqual(route["normalization"]["tiers"],
                         ["exact", "complete_renormalized"])

    def test_budget_arithmetic_recomputes_from_the_rate_card(self):
        budgets = self.document["budgets"]
        ling = (8192 * 0.06 + 1024 * 0.18) / 1_000_000
        jev = 8192 * 0.042 / 1_000_000
        collection = 16 * 4 * 3 * ling + 16 * 1 * 3 * jev
        replay = 16 * 3 * 3 * jev
        self.assertAlmostEqual(
            budgets["discovery_collection"]["worst_case_cost_usd"],
            round(collection, 12), places=12)
        self.assertAlmostEqual(budgets["exploratory_replay"]["worst_case_cost_usd"],
                               round(replay, 12), places=12)
        self.assertAlmostEqual(budgets["program"]["worst_case_cost_usd"],
                               round(collection + replay, 12), places=12)
        self.assertEqual(budgets["discovery_collection"]["hard_cost_ceiling_usd"], 0.20)
        self.assertEqual(budgets["exploratory_replay"]["hard_cost_ceiling_usd"], 0.10)
        self.assertEqual(budgets["program"]["hard_cost_ceiling_usd"], 0.30)
        self.assertTrue(budgets["discovery_collection"]["within_hard_ceiling"])
        self.assertTrue(budgets["exploratory_replay"]["within_hard_ceiling"])
        self.assertTrue(budgets["program"]["within_hard_ceiling"])

    def test_request_caps_are_retry_inclusive_and_paced(self):
        caps = self.document["request_caps"]
        self.assertEqual(caps["discovery_collection"]["physical_combined_max"], 240)
        self.assertEqual(caps["exploratory_replay"]["physical_jev_max"], 144)
        self.assertEqual(caps["program"]["physical_combined_max"], 384)
        self.assertEqual(caps["max_retries"], {"ling": 2, "jev": 2})
        self.assertTrue(caps["reservation_rule"].startswith(
            "stop before the next call"))
        self.assertIn("carry-over", str(caps["no_credit_from_unused_budgets"]))

    def test_stops_coverage_retention_and_ownership_are_frozen(self):
        stops = self.document["stops"]
        self.assertEqual(len(stops), 11)
        self.assertTrue(all(isinstance(stop, str) for stop in stops))
        self.assertTrue(any("truncated_output" in stop for stop in stops))
        self.assertTrue(any("two consecutive terminal provider failures" in stop
                            for stop in self.document["stops"]))
        self.assertTrue(any("output collision" in stop
                            for stop in self.document["stops"]))
        coverage = self.document["coverage_rules"]
        self.assertTrue(coverage["frozen_before_collection"])
        self.assertTrue(coverage["no_imputation"])
        self.assertTrue(coverage["no_seed_replacement"])
        self.assertTrue(coverage["no_form_removal_after_outcomes"])
        self.assertTrue(coverage["no_replenishment_from_spare_capacity"])
        self.assertEqual(coverage["min_complete_per_form"], 1)
        retention = self.document["silence_and_failure_retention"]
        self.assertTrue(retention["retain_silences"])
        self.assertTrue(retention["retain_failures"])
        self.assertTrue(retention["retain_not_attempted_rows"])
        self.assertIn("immutable journal", str(retention["stop_semantics"]))
        ownership = self.document["ownership_and_exposure_checks"]
        self.assertTrue(ownership["ownership_check"]["rejection_journaled"])
        self.assertIn("strictly greater than",
                      ownership["read_after_write"]["required"])

    def test_multiplicity_information_and_inference_are_frozen(self):
        multiplicity = self.document["multiplicity"]
        self.assertEqual(multiplicity["registered_family_set"], ["legal"])
        self.assertEqual(multiplicity["registered_family_count"], 1)
        self.assertTrue(multiplicity["family_set_frozen_before_outcomes"])
        information = self.document["information_rules"]
        self.assertEqual(information["real_claim_information_bits"], [1.0])
        self.assertEqual(information["placebo_information_bits"], 0.0)
        self.assertTrue(information["placebo_inert_for_every_form"])
        inference = self.document["inference_plan"]
        self.assertEqual(inference["alpha"], 0.05)
        self.assertEqual(inference["minimum_forms_for_confirmatory"], 6)
        self.assertEqual(inference["k_from_l03"], 4)
        self.assertTrue(inference["prohibited_as_primary"])

    def test_paths_are_fresh_unique_absent_and_lifecycle_bound(self):
        self.assertEqual(self.document["path_lifecycle"]["resume"], False)
        self.assertEqual(self.document["path_lifecycle"]["append"], False)
        self.assertEqual(self.document["path_lifecycle"]["overwrite"], False)
        self.assertEqual(self.document["path_lifecycle"]["path_overrides"], False)
        registered = self.document["path_lifecycle"]["all_registered_paths"]
        self.assertEqual(len(registered), len(set(registered)))
        for name in ("discovery_journal", "discovery_report",
                     "exploratory_replay_journal", "exploratory_replay_report"):
            path = REPO_ROOT / self.document["paths"][name]
            with self.subTest(path=name):
                self.assertFalse(path.exists(),
                                 "a live output path exists before authorization")
                self.assertTrue(str(self.document["paths"][name])
                                .startswith("runs/next-phase/legal/"))

    def test_write_refuses_to_overwrite_the_registration_path(self):
        with self.assertRaises(FileExistsError):
            reg.write_registration(self.document, repo_root=REPO_ROOT)

    def test_authorization_is_pending_with_separate_l07_gate(self):
        authorization = self.document["authorization"]
        self.assertEqual(authorization["authorization_status"], "pending")
        self.assertTrue(
            authorization["separate_live_authorization_required_after_locking"])
        self.assertTrue(authorization["locking_is_not_authorization"])
        self.assertFalse(authorization["route_authorized"])
        self.assertFalse(authorization["route_registered"])
        self.assertEqual(authorization["l07_gate"]["issue"], "#225")
        self.assertEqual(authorization["l07_gate"]["loop_halts_before"], "#225")
        self.assertIn("no probe, dry call, schema call",
                      authorization["no_provider_call_of_any_kind"])
        self.assertEqual(self.document["provider_calls"], 0)
        self.assertTrue(self.document["offline_only"])
        self.assertTrue(self.document["non_claims"])
        self.assertTrue(self.document["handoff_to_l05"]["runnable_registration"])
        self.assertEqual(self.document["handoff_to_l05"]["issue"], 223)

    def test_zero_network_events_recorded(self):
        self.assertEqual(_NETWORK_EVENTS, [], _NETWORK_EVENTS)
        self.assertEqual(self.document["network_audit"]["events"], 0)
        self.assertEqual(self.document["network_audit"]["event_names"], [])
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
        haystack = (self.doc_text + json.dumps(self.document, sort_keys=True)
                    ).lower()
        for phrase in BANNED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase.lower(), haystack)


class DeterministicRebuildTests(L04TestCase):
    def test_registration_verification_is_green(self):
        with patch("urllib.request.urlopen", _explode):
            verification = reg.verify_registration(self.artifact,
                                                   repo_root=REPO_ROOT)
        self.assertTrue(verification["ok"], verification["errors"])
        self.assertEqual(verification["failed"], [])
        self.assertEqual(verification["registration_hash"],
                         REGISTRATION_CONTENT_HASH)
        self.assertEqual(verification["status"], STATUS)
        self.assertEqual(verification["provider_calls"], 0)

    def test_cli_verification_is_green(self):
        buffer = io.StringIO()

        def explode(*args, **kwargs):
            raise AssertionError("provider call attempted offline")

        with patch("urllib.request.urlopen", explode), \
                contextlib.redirect_stdout(buffer):
            code = reg.main(["--repo-root", str(REPO_ROOT)])
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["ok"], payload["errors"])
        self.assertEqual(payload["provider_calls"], 0)
        self.assertEqual(payload["registration_hash"], REGISTRATION_CONTENT_HASH)
        self.assertEqual(payload["status"], STATUS)

    def test_verification_fails_closed_on_hash_drift(self):
        tampered = dict(self.document)
        tampered["registration_hash"] = "0" * 64
        verification = reg.verify_registration(tampered, repo_root=REPO_ROOT)
        self.assertFalse(verification["ok"])
        self.assertIn("registration_hash_matches", verification["failed"])

    def test_verification_fails_closed_on_status_drift(self):
        tampered = dict(self.document)
        tampered["status"] = "authorized"
        verification = reg.verify_registration(tampered, repo_root=REPO_ROOT)
        self.assertFalse(verification["ok"])
        self.assertIn("status_is_draft_pending_review", verification["failed"])

    def test_module_sources_recompute(self):
        self.assertTrue(MODULE_PATH.is_file())
        self.assertIn("jev_legal_p04_registration", MODULE_PATH.read_text(
            encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
