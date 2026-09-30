#!/usr/bin/env python3
"""Offline tests for analysis/entropy_analysis.py on synthetic tables.

They cover what the exp1 version could not handle: a fourth condition
(``placebo_inert``), a per-run switch turn, model x condition cells that do not
exist, a third agent, and tables written by a different flattener (aliased
column names). No network, no API, no real runs.

    python3 test_entropy_analysis.py
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import entropy_analysis as EA  # noqa: E402

ACTIONS = ["read_log", "write_log", "decrypt", "submit"]


def synth(models, conditions, seeds=8, agents=("A1", "A2"), max_turn=20,
          switch_range=(5, 11), close_offset=None, skip_cells=(), h_column="mean_H_renorm_bits",
          effect=0.05, rng_seed=7):
    """A (calls, runs) pair of tables with a known switch effect on entropy."""
    rng = np.random.default_rng(rng_seed)
    runs, calls = [], []
    for model in models:
        for condition in conditions:
            if (model, condition) in skip_cells:
                continue
            for seed in range(1, seeds + 1):
                sw = int(rng.integers(switch_range[0], switch_range[1] + 1))
                closed = sw + close_offset if close_offset else None
                tau = sw + int(rng.integers(0, 3)) if condition != "base" else None
                runs.append({
                    "model": model, "condition": condition, "seed": seed, "n_agents": len(agents),
                    "switch_turn_effective": sw, "switch_closed_turn": closed,
                    "turns_executed": max_turn, "valid": True, "entropy_valid": True,
                    "task_success": condition == "switch", "n_complete": 2 if condition == "switch" else 0,
                    "communication_verified": condition == "switch",
                    "complete_via_verified_channel": condition == "switch",
                    "tau_first_foreign_read": tau, "flags": "", "cost_usd": 0.01,
                    "A1->A2_verdict": "VERIFIED" if condition == "switch" else "WRITTEN_NOT_READ",
                    "A1->A2_tau_write": 2, "A1->A2_tau_read": tau, "A1->A2_tau_use": (tau or 0) + 1,
                    "A2->A1_verdict": "VERIFIED" if condition == "switch" else "WRITTEN_NOT_READ",
                    "A2->A1_tau_write": 2, "A2->A1_tau_read": tau, "A2->A1_tau_use": (tau or 0) + 1,
                    "grade_A3": ("COMPLETE" if condition == "switch" else "NONE") if len(agents) > 2 else None,
                    "A3_provenance_ok": True if len(agents) > 2 else None,
                })
                for turn in range(1, max_turn + 1):
                    for pos, agent in enumerate(agents):
                        action = ACTIONS[(turn + pos) % len(ACTIONS)]
                        post = turn >= sw
                        bump = effect if (post and condition in ("switch", "placebo")) else 0.0
                        n_tokens = int(rng.integers(12, 90))
                        q = rng.dirichlet(np.ones(5) * (0.6 if post else 1.4))
                        row = {
                            "model": model, "condition": condition, "seed": seed, "turn": turn,
                            "agent": agent, "position_in_turn": pos, "action": action,
                            "n_tokens": n_tokens, "n_placeholders": 0,
                            h_column: max(0.0, 0.30 + bump + rng.normal(0, 0.05)),
                            "mean_surprisal_bits": 0.4 + rng.normal(0, 0.1),
                            "n_real_foreign_returned": (2 if (action == "read_log" and post
                                                              and condition == "switch") else 0),
                            "n_placebo_returned": (2 if (action == "read_log" and post
                                                         and condition == "placebo") else 0),
                            "n_inert_returned": (2 if (action == "read_log" and post
                                                       and condition == "placebo_inert") else 0),
                            "switch_open": condition == "switch" and post,
                            "read_policy": "all" if (condition == "switch" and post) else "own",
                            "decrypt_ok": action == "decrypt", "submit_grade": None,
                        }
                        row.update({f"q_{a}": float(p) for a, p in
                                    zip(("READ", "WRITE", "DECRYPT", "SUBMIT", "OTHER"), q)})
                        row["q_DONE"] = None
                        calls.append(row)
    return pd.DataFrame(calls), pd.DataFrame(runs)


class SyntheticTableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, calls, runs, name="t"):
        cp, rp = self.tmp / f"{name}_calls.csv", self.tmp / f"{name}_runs.csv"
        calls.to_csv(cp, index=False)
        runs.to_csv(rp, index=False)
        return cp, rp

    def _run(self, calls, runs, name="t", **kwargs):
        cp, rp = self._write(calls, runs, name)
        out = self.tmp / f"{name}_out"
        kwargs.setdefault("n_perm", 300)
        kwargs.setdefault("skip_system", True)
        result = EA.run_analysis(cp, rp, out, **kwargs)
        stats = {p.name: pd.read_csv(p) for p in (out / "stats").glob("*.csv")}
        summary = json.loads((out / "stats" / "summary.json").read_text())
        return result, stats, summary, out

    # ---------------------------------------------------------------- four conditions
    def test_four_conditions_and_randomised_switch(self):
        calls, runs = synth(["m-a", "m-b"], ["base", "switch", "placebo", "placebo_inert"])
        result, stats, summary, out = self._run(calls, runs, "four")
        self.assertEqual(summary["data"]["conditions"],
                         ["base", "placebo_inert", "placebo", "switch"])
        self.assertTrue(summary["data"]["switch_turn_randomised"])
        self.assertEqual(len(summary["data"]["switch_turns"]) > 1, True)
        # every figure and stats file of the v1 contract is present
        for fig in ("fig01_ground_truth.png", "fig02_token_entropy_trajectories.png",
                    "fig02b_adjusted_entropy_trajectories.png", "fig02c_decision_entropy_trajectories.png",
                    "fig03_action_mix.png", "fig04_did_run_level.png",
                    "fig06_aligned_first_foreign_read.png", "fig07_post_read_spike.png",
                    "fig08_run_level_roc.png", "fig09_cusum_detection.png"):
            self.assertIn(fig, result["figures"], fig)
        for csv in ("A_ground_truth.csv", "A_channel_timing.csv", "B_trajectories.csv",
                    "C_entropy_by_action.csv", "D_run_level_deltas.csv", "D_did_tests.csv",
                    "E_mixed_model.csv", "H_aligned.csv", "I_post_read_spike.csv",
                    "J_cusum_runs.csv", "J_roc.csv", "J_cusum_summary.csv"):
            self.assertIn(csv, result["stats"], csv)
        # the event-aligned extra figure only appears when the switch turn varies
        self.assertIn("fig02d_event_aligned_trajectories.png", result["figures"])
        # 4 conditions -> 6 contrasts per metric, including the E1 family
        tests = stats["D_did_tests.csv"]
        contrasts = set(tests.contrast)
        for expected in ("placebo_inert - base", "placebo - base", "switch - base",
                         "placebo - placebo_inert", "switch - placebo_inert", "switch - placebo"):
            self.assertIn(expected, contrasts, expected)
        self.assertEqual(len(tests), 2 * 4 * 6)   # models x metrics x contrasts
        self.assertTrue(tests.p_perm.notna().all())
        # the injected effect is recovered on switch - base but not on inert - base
        adj = tests[(tests.metric == "H") & (tests.contrast == "switch - base")]
        inert = tests[(tests.metric == "H") & (tests.contrast == "placebo_inert - base")]
        self.assertTrue((adj.did_bits > 0.02).all(), adj.did_bits.tolist())
        self.assertTrue((inert.did_bits.abs() < 0.02).all(), inert.did_bits.tolist())

    # ---------------------------------------------------------------- per-run switch turn
    def test_pre_post_uses_each_run_switch_turn(self):
        calls, runs = synth(["m-a"], ["base", "switch"], seeds=6, switch_range=(5, 11))
        _, stats, _, _ = self._run(calls, runs, "sw")
        deltas = stats["D_run_level_deltas.csv"].merge(
            runs[["model", "condition", "seed", "switch_turn_effective"]],
            on=["model", "condition", "seed"])
        self.assertTrue((deltas.switch_turn == deltas.switch_turn_effective).all())
        self.assertTrue((deltas.n_pre == 2 * (deltas.switch_turn_effective - 1)).all())
        self.assertGreater(deltas.switch_turn.nunique(), 1)

    def test_closed_switch_window_is_carried(self):
        calls, runs = synth(["m-a"], ["base", "switch"], seeds=6, close_offset=4)
        _, _, summary, _ = self._run(calls, runs, "closed")
        self.assertTrue(summary["data"]["switch_closed_turns"])

    # ---------------------------------------------------------------- missing cells
    def test_missing_cells_are_tolerated(self):
        calls, runs = synth(["m-a", "m-b"], ["base", "switch", "placebo_inert"],
                            skip_cells=[("m-b", "placebo_inert"), ("m-b", "switch")])
        result, stats, summary, _ = self._run(calls, runs, "holes")
        self.assertEqual(summary["data"]["cells"]["m-b|placebo_inert"], 0)
        tests = stats["D_did_tests.csv"]
        absent = tests[(tests.model == "m-b") & (tests.contrast == "switch - base")]
        self.assertTrue(absent.did_bits.isna().all())
        present = tests[(tests.model == "m-a") & (tests.contrast == "switch - base")]
        self.assertTrue(present.did_bits.notna().all())
        self.assertIn("fig04_did_run_level.png", result["figures"])

    def test_single_condition_table_runs(self):
        calls, runs = synth(["m-a"], ["switch"], seeds=5)
        result, stats, _, _ = self._run(calls, runs, "one")
        self.assertIn("fig04_did_run_level.png", result["figures"])
        self.assertTrue(stats["D_did_tests.csv"].empty or stats["D_did_tests.csv"].p_perm.isna().all())

    # ---------------------------------------------------------------- third agent
    def test_third_agent(self):
        calls, runs = synth(["m-a"], ["base", "switch"], seeds=6, agents=("A1", "A2", "A3"))
        result, stats, summary, _ = self._run(calls, runs, "a3", skip_system=False,
                                              n_perm_system=40)
        self.assertEqual(summary["data"]["agents"], ["A1", "A2", "A3"])
        gt = stats["A_ground_truth.csv"]
        self.assertIn("observer_complete", gt.columns)
        self.assertAlmostEqual(float(gt[gt.condition == "switch"].observer_complete.iloc[0]), 1.0)
        sysdf = stats["G_system_entropy.csv"]
        self.assertEqual(set(sysdf.pair), {"A1|A2", "A1|A3", "A2|A3"})
        self.assertIn("fig05_system_entropy_all_states.png", result["figures"])

    # ---------------------------------------------------------------- alternative schema
    def test_aliased_column_names(self):
        calls, runs = synth(["m-a"], ["base", "switch"], seeds=6, h_column="H")
        calls = calls.rename(columns={"n_real_foreign_returned": "n_foreign",
                                      "n_placebo_returned": "n_placebo",
                                      "n_inert_returned": "n_inert"})
        runs = runs.rename(columns={"valid": "run_valid"})
        _, stats, summary, _ = self._run(calls, runs, "alias")
        self.assertEqual(summary["data"]["runs_valid"], len(runs))
        self.assertTrue(stats["D_run_level_deltas.csv"].H_delta.notna().any())

    def test_entropy_gate_filter(self):
        calls, runs = synth(["m-a"], ["base", "switch"], seeds=6)
        runs.loc[runs.index[:3], "entropy_valid"] = False
        _, _, summary, _ = self._run(calls, runs, "gate", entropy_valid_only=True)
        self.assertEqual(summary["data"]["runs_dropped_entropy_gate"], 3)
        self.assertEqual(summary["data"]["runs_valid"], len(runs) - 3)

    # ---------------------------------------------------------------- helpers
    def test_contrast_pairs_order(self):
        self.assertEqual(EA.contrast_pairs(["base", "placebo", "switch"]),
                         [("placebo", "base"), ("switch", "base"), ("switch", "placebo")])
        self.assertEqual(EA.contrast_pairs(["base", "placebo_inert", "placebo", "switch"])[0],
                         ("placebo_inert", "base"))

    def test_scalar_on_absent_cell(self):
        df = pd.DataFrame({"model": ["m"], "condition": ["base"], "x": [1.0]})
        self.assertEqual(EA.scalar(df, "x", model="m", condition="base"), 1.0)
        self.assertTrue(np.isnan(EA.scalar(df, "x", model="m", condition="switch")))

    def test_label_seeded_estimates_are_stable(self):
        a = np.linspace(0, 1, 11)
        b = np.linspace(0.2, 1.2, 11)
        self.assertEqual(EA.perm_test(a, b, n=200, label=("x",)),
                         EA.perm_test(a, b, n=200, label=("x",)))
        self.assertEqual(EA.boot_ci(a, label=("y",)), EA.boot_ci(a, label=("y",)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
