import json
from pathlib import Path
import tempfile
import unittest
import uuid

from apart_incident_response.controlled_entropy_analysis import (
    AnalysisValidationError,
    benjamini_hochberg,
    call_rows,
    endpoint_analysis,
    event_aligned_profile,
    coupling_proxy,
    entropy_bits,
    functional_form_comparison,
    load_matrix,
    paired_condition_contrasts,
    replay_validation,
    require_replay_valid,
    robustness_summary,
    sign_test_pvalue,
    wilcoxon_signed_rank_pvalue,
)
from apart_incident_response.probability_artifacts import build_probability_artifact


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _probability_artifact(agent: int, condition: str, seed: int, *, partial: bool = False) -> dict:
    records = []
    for token in (f"a{agent}{condition}{seed}", f"b{agent}{condition}{seed}"):
        records.append({
            "token": token,
            "logprob": -0.7,
            "top_logprobs": [{"token": token, "logprob": -0.7}, {"token": "other", "logprob": -1.5}],
        })
    probability = build_probability_artifact(
        records,
        provenance={"provider": "openrouter", "model": "fixture/model", "parameters": {"top_logprobs": 2}},
    )
    turns = [
        {
            "source_sequence": index,
            "kind": "text",
            "status": "complete",
            "probability_artifact": probability,
        }
        for index in (1, 2)
    ]
    if partial:
        turns[1]["status"] = "partial"
    return {
        "artifact_schema": "agent-turn-probability-v1",
        "coverage": {
            "turns": 2,
            "complete": 1 if partial else 2,
            "partial": 1 if partial else 0,
            "unavailable": 0,
        },
        "turns": turns,
    }


def _matrix(root: Path, *, agent_count: int = 2, partial: bool = False) -> Path:
    invocation_uuid = str(uuid.uuid4())
    model = "openrouter/inclusionai/ling-3.0-flash-vl:free"
    triplet_links = {"conditions": {}}
    for condition in ("C0", "C1", "C2"):
        condition_root = root / "s0001" / condition
        assignments = [
            {"agent_id": f"agent-{number}", "agent_number": number}
            for number in range(1, agent_count + 1)
        ]
        manifest = {
            "run_class": "experimental",
            "run_uuid": invocation_uuid,
            "model": model,
            "condition": condition,
            "seed": 1,
            "triplet_id": "s0001",
            "task": {"task_id": "task-1"},
            "factor_assignment": {"agent_count": agent_count, "model": model},
            "assignment": assignments,
        }
        _write(condition_root / "manifest.json", manifest)
        results = [
            {"identity": {"agent_id": f"agent-{number}"}, "status": "completed"}
            for number in range(1, agent_count + 1)
        ]
        _write(condition_root / "results.json", {"results": results, "controller_errors": []})
        _write(condition_root / "index.json", {"status": "completed"})
        _write(condition_root / "artifacts" / "metrics.json", {
            "task_success_rate": 1.0,
            "U": 0.0,
            "total_tokens": 10,
            "total_turns": 2,
        })
        links = {}
        for number in range(1, agent_count + 1):
            agent_id = f"agent-{number}"
            artifact_path = condition_root / "agents" / agent_id / "artifacts" / "probability_artifacts.json"
            _write(artifact_path, _probability_artifact(number, condition, 1, partial=partial and number == 2))
            links[agent_id] = f"s0001/{condition}/agents/{agent_id}/artifacts/probability_artifacts.json"
        triplet_links["conditions"][condition] = {
            "index": f"s0001/{condition}/index.json",
            "probability_artifacts": links,
        }
    matrix = {
        "run_class": "experimental",
        "experimental_data": True,
        "run_uuid": invocation_uuid,
        "model": model,
        "triplets": [{"conditions": ["C0", "C1", "C2"], "artifacts": triplet_links}],
    }
    path = root / "matrix.json"
    _write(path, matrix)
    return path


class ControlledEntropyAnalysisTests(unittest.TestCase):
    def test_loader_requires_complete_two_agent_triplets_and_flattens_turns(self):
        with tempfile.TemporaryDirectory() as temporary:
            dataset = load_matrix(_matrix(Path(temporary)))
            rows = call_rows(dataset)
            self.assertEqual(len(dataset.triplets), 1)
            self.assertEqual(len(rows), 12)
            self.assertEqual({row["condition"] for row in rows}, {"C0", "C1", "C2"})
            self.assertEqual({row["agent"] for row in rows}, {"agent-1", "agent-2"})

    def test_loader_rejects_three_agent_matrix(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(AnalysisValidationError, "no complete two-agent"):
                load_matrix(_matrix(Path(temporary), agent_count=3))

    def test_loader_rejects_incomplete_probability_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(AnalysisValidationError, "incomplete or unavailable"):
                load_matrix(_matrix(Path(temporary), partial=True))

    def test_paired_contrasts_are_seed_level_and_replay_is_auditable(self):
        with tempfile.TemporaryDirectory() as temporary:
            dataset = load_matrix(_matrix(Path(temporary)))
            contrasts = paired_condition_contrasts(dataset, draws=200)
            self.assertEqual([row["contrast"] for row in contrasts], ["C1-C0", "C2-C0", "C1-C2"])
            self.assertTrue(all(row["n_seeds"] == 1 for row in contrasts))
            replay = replay_validation(dataset)
            self.assertEqual(len(replay), 6)
            self.assertTrue(all(row["valid"] for row in replay))
            self.assertTrue(all(row["max_abs_coverage_error"] == 0.0 for row in replay))

    def test_entropy_estimates_are_blocked_when_replay_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            dataset = load_matrix(_matrix(Path(temporary)))
            token = dataset.triplets[0].conditions["C0"].agents[0].document["turns"][0]["probability_artifact"]["tokens"][0]
            token["entropy"]["partial_entropy_bits"] += 0.01
            with self.assertRaisesRegex(AnalysisValidationError, "blocked by replay validation"):
                paired_condition_contrasts(dataset, draws=20)
            with self.assertRaises(AnalysisValidationError):
                require_replay_valid(dataset)

    def test_contrasts_drop_a_seed_with_an_unequal_requested_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            matrix_path = _matrix(root)
            artifact_path = root / "s0001" / "C2" / "agents" / "agent-2" / "artifacts" / "probability_artifacts.json"
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            artifact["turns"] = artifact["turns"][:1]
            artifact["coverage"] = {"turns": 1, "complete": 1, "partial": 0, "unavailable": 0}
            _write(artifact_path, artifact)
            dataset = load_matrix(matrix_path)
            contrasts = paired_condition_contrasts(dataset, turn_start=1, turn_stop=2, draws=20)
            self.assertTrue(all(row["n_seeds"] == 0 for row in contrasts))
            self.assertTrue(all(row["excluded_seeds"] == [1] for row in contrasts))

    def test_current_schema_analysis_stages_share_the_replay_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            dataset = load_matrix(_matrix(Path(temporary)))
            self.assertEqual(len(endpoint_analysis(dataset, post_windows=(1,))), 6)
            self.assertEqual(len(event_aligned_profile(dataset, event_turn=1, radius=1)), 9)
            self.assertEqual(len(coupling_proxy(dataset)), 3)
            self.assertTrue(functional_form_comparison(dataset))
            self.assertEqual(len(robustness_summary(dataset)), 3)

    def test_numpy_statistics_have_stable_definitions(self):
        self.assertAlmostEqual(entropy_bits([0.5, 0.5]), 1.0)
        self.assertAlmostEqual(sign_test_pvalue([1, 1, -1, -1]), 1.0)
        self.assertAlmostEqual(wilcoxon_signed_rank_pvalue([1, 2, 3]), 0.25)
        adjusted = benjamini_hochberg([0.01, 0.04, float("nan")])
        self.assertAlmostEqual(adjusted[0], 0.02)
        self.assertAlmostEqual(adjusted[1], 0.04)
        self.assertTrue(adjusted[2] != adjusted[2])


if __name__ == "__main__":
    unittest.main()
