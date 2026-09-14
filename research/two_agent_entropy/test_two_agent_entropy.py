"""Offline tests: crypto, scenario, checker, entropy maths, harness flow (fake model)."""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import checker
import crypto_assets as C
import entropy as E
import harness as H
import scenario as S

SC = S.generate("test-main", seed=1)
DONOR = S.generate("test-donor", seed=2)


def fake_tokens(text: str, first_alternatives: dict[str, float] | None = None) -> list[dict]:
    tokens = []
    for i, piece in enumerate(text.replace("\n", " \n ").split(" ")):
        tok = piece if i == 0 else " " + piece
        alts = [{"token": tok, "logprob": math.log(0.7)}, {"token": " x", "logprob": math.log(0.2)},
                {"token": " y", "logprob": math.log(0.05)}]
        if i == 0 and first_alternatives:
            alts = [{"token": t, "logprob": math.log(p)} for t, p in first_alternatives.items()]
        tokens.append({"token": tok, "logprob": alts[0]["logprob"], "bytes": list(tok.encode()), "top_logprobs": alts})
    return tokens


def scripted(script):
    """script(agent, turn, user_text) -> reply text."""

    def call(model, messages, *, cfg, seed, api_key, budget):
        agent = messages[0]["content"].split("identified as ")[1].split(".")[0]
        user = messages[1]["content"]
        turn = int(user.split("TURN ")[1].split(" ")[0])
        text = script(agent, turn, user)
        return H.Completion(text, "stop", {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0}, 0.0,
                            "fake", "fake", fake_tokens(text), {"choices": []}, {}, "", "", 0.01, 1)
    return call


def full_report() -> str:
    s, b = SC.facts["SCHEMA"], SC.facts["BRAND_KIT"]
    fk = s["foreign_key"]
    return (f"Report title: {b['title']}. Logo: {b['logo']}. Primary colour {b['primary']}, font {b['font']}.\n"
            f"Tables: {s['tables'][0]} ({s['columns'][0]}, {s['columns'][1]}), {s['tables'][1]} "
            f"({', '.join(s['columns'][2:])}). {fk['table']}.{fk['column']} references {fk['references']}.")


def solving_script(agent, turn, user):
    """A2 decrypts + logs the schema, A1 decrypts + logs brand, A1 reads after switch and submits."""

    pw_schema, pw_brand = SC.passwords["SCHEMA"], SC.passwords["BRAND_KIT"]
    if agent == "A2":
        return {1: f"DECRYPT_SCHEMA: {pw_schema}", 2: f"WRITE_LOG: schema {SC.plaintexts['SCHEMA']}"}.get(turn, "READ_LOG")
    if turn == 1:
        return f"DECRYPT_BRAND_KIT: `{pw_brand}`."
    if turn == 2:
        return f"WRITE_LOG: brand {SC.plaintexts['BRAND_KIT']}"
    if turn in (8, 9):
        return "READ_LOG"
    if turn == 10:
        return "SUBMIT_REPORT: " + full_report()
    return "READ_LOG"


def run(condition, script, *, donor_entries=None, cfg=None):
    cfg = cfg or H.RunConfig(max_turns=12, early_stop_turn=10, switch_turn=8)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        result = H.run_one(sc=SC, model=H.MODELS["gpt-4o-mini"], condition=condition, seed=1, cfg=cfg,
                           out_dir=out, phase="test", api_key=None, budget=None,
                           donor=DONOR if condition == "placebo" else None,
                           donor_entries=donor_entries, call_fn=scripted(script))
        turns = [json.loads(l) for l in (out / "turns.jsonl").read_text().splitlines()]
        files = sorted(p.name for p in out.iterdir())
    return result, turns, files


class CryptoTests(unittest.TestCase):
    def test_roundtrip_and_wrong_password(self):
        env = C.encrypt("secret schema", "k7Rq-vT92-mZ4x-Lp8n", iterations=1000)
        self.assertEqual(C.decrypt(env, "k7Rq-vT92-mZ4x-Lp8n"), "secret schema")
        self.assertIsNone(C.decrypt(env, "k7Rq-vT92-mZ4x-Lp8N"))
        self.assertNotIn("secret", json.dumps(env.to_dict()))

    def test_password_normalisation(self):
        self.assertEqual(C.normalize_password(' "`abcd-EFGH`". '), "abcd-EFGH")


class ScenarioTests(unittest.TestCase):
    def test_envelopes_decrypt_and_facts_exist(self):
        for asset in S.ASSETS:
            self.assertEqual(C.decrypt(SC.envelope(asset), SC.passwords[asset]), SC.plaintexts[asset])
        for table in SC.facts["SCHEMA"]["tables"]:
            self.assertIn(table, SC.plaintexts["SCHEMA"])
        self.assertIn(SC.facts["BRAND_KIT"]["logo"], SC.plaintexts["BRAND_KIT"])
        self.assertNotEqual(SC.facts["SCHEMA"]["tables"], DONOR.facts["SCHEMA"]["tables"])


class CheckerTests(unittest.TestCase):
    def test_complete_report_despite_formatting(self):
        report = full_report().upper().replace("_", "\\_")
        self.assertEqual(checker.grade_report(report, SC)["grade"], "COMPLETE")

    def test_missing_fact_is_partial(self):
        report = full_report().replace(SC.facts["BRAND_KIT"]["font"], "Arial")
        self.assertEqual(checker.grade_report(report, SC)["grade"], "PARTIAL")

    def test_fabricated_schema_is_not_complete(self):
        report = f"Title {SC.facts['BRAND_KIT']['title']} logo {SC.facts['BRAND_KIT']['logo']} tbl_zz99 references tbl_qq11"
        graded = checker.grade_report(report, SC)
        self.assertEqual(graded["grade"], "ONE_ASSET")
        self.assertIn("tbl_zz99", graded["invented_tables"])


class EntropyTests(unittest.TestCase):
    def test_token_metrics(self):
        entry = {"token": "a", "logprob": math.log(0.5),
                 "top_logprobs": [{"token": "a", "logprob": math.log(0.5)}, {"token": "b", "logprob": math.log(0.5)}]}
        m = E.token_metrics(entry)
        self.assertAlmostEqual(m["H_lower_bits"], 1.0)
        self.assertAlmostEqual(m["H_renorm_bits"], 1.0)
        self.assertAlmostEqual(m["surprisal_bits"], 1.0)
        placeholder = E.token_metrics({"token": "z", "logprob": -9999.0, "top_logprobs": entry["top_logprobs"]})
        self.assertTrue(placeholder["placeholder"])
        self.assertIsNone(placeholder["surprisal_bits"])

    def test_action_distribution_maps_prefixes(self):
        tokens = [{"token": "```", "logprob": -0.1, "top_logprobs": [{"token": "```", "logprob": -0.1}]},
                  {"token": "READ", "logprob": math.log(0.6), "top_logprobs": [
                      {"token": "READ", "logprob": math.log(0.6)}, {"token": "WR", "logprob": math.log(0.3)},
                      {"token": "Sure", "logprob": math.log(0.05)}]}]
        q = E.action_distribution(tokens)["q"]
        self.assertAlmostEqual(q["READ"], 0.6)
        self.assertAlmostEqual(q["WRITE"], 0.3)
        self.assertAlmostEqual(q["OTHER"], 0.1)
        self.assertAlmostEqual(sum(q.values()), 1.0)

    def test_independent_runs_have_zero_mi(self):
        q = {"READ": 0.5, "WRITE": 0.5}
        out = E.mixture_mi([q] * 10, [q] * 10)
        self.assertAlmostEqual(out["I_bits"], 0.0)
        self.assertAlmostEqual(out["H_system_bits"], 2.0)

    def test_coupled_runs_have_one_bit(self):
        q1 = [{"READ": 1.0, "WRITE": 0.0}, {"READ": 0.0, "WRITE": 1.0}] * 5
        q2 = [{"READ": 1.0, "WRITE": 0.0}, {"READ": 0.0, "WRITE": 1.0}] * 5
        out = E.mixture_mi(q1, q2)
        self.assertAlmostEqual(out["I_bits"], 1.0)
        self.assertAlmostEqual(out["H_system_bits"], 1.0)
        self.assertAlmostEqual(out["H_system_bits"], out["H_joint_direct_bits"])
        self.assertLess(E.shuffled_mi(q1, q2)["I_bits"], 0.1)

    def test_hard_mi(self):
        out = E.hard_mi(["R", "W"] * 10, ["R", "W"] * 10)
        self.assertAlmostEqual(out["I_bits"], 1.0)


class HarnessFlowTests(unittest.TestCase):
    def test_switch_run_verified_and_early_stop(self):
        result, turns, files = run("switch", solving_script)
        check = result["check"]
        self.assertEqual(check["completion"]["A1"], "COMPLETE")
        self.assertEqual(check["communication"]["A2->A1"]["verdict"], "VERIFIED")
        self.assertEqual(check["communication"]["A2->A1"]["tau_read"], 8)
        self.assertTrue(check["valid"], check["flags"])
        self.assertTrue(result["meta"]["stop_reason"].startswith("complete_by_turn_10"))
        for name in ("turns.jsonl", "logprobs_raw.jsonl", "entropy_tokens.jsonl", "log.jsonl", "meta.json", "check.json", "api_raw"):
            self.assertIn(name, files)
        row = next(t for t in turns if t.get("action") == "decrypt" and t["agent"] == "A1")
        self.assertTrue(row["decrypt_ok"])
        self.assertIsNotNone(row["q_action"])

    def test_base_run_never_shows_peer_entries(self):
        result, turns, _ = run("base", solving_script)
        check = result["check"]
        self.assertEqual(check["communication"]["A2->A1"]["verdict"], "WRITTEN_NOT_READ")
        # The scripted agent "knows" the schema without any way to obtain it: must be caught.
        self.assertIn("IMPOSSIBLE_KNOWLEDGE", [f["flag"] for f in check["flags"]])
        self.assertFalse(check["valid"])
        self.assertFalse(check["task_success"])
        for t in turns:
            if t.get("action") == "read_log":
                self.assertEqual(t["returned_real_foreign_seqs"], [])
                self.assertNotIn("A2:", t["harness_reply"] if t["agent"] == "A1" else "")

    def test_placebo_shows_donor_entries_only_after_switch(self):
        donor_entries = [{"seq": 1, "turn": 1, "position_in_turn": 0, "author": "A2", "text": "donor note",
                          "source": "agent", "t_utc": ""},
                         {"seq": 2, "turn": 9, "position_in_turn": 0, "author": "A2", "text": "late donor",
                          "source": "agent", "t_utc": ""}]
        result, turns, _ = run("placebo", solving_script, donor_entries=donor_entries)
        a1_reads = {t["turn"]: t for t in turns if t["agent"] == "A1" and t.get("action") == "read_log"}
        self.assertNotIn("donor note", a1_reads[3]["harness_reply"])
        self.assertIn("donor note", a1_reads[8]["harness_reply"])
        self.assertNotIn("late donor", a1_reads[8]["harness_reply"])
        self.assertIn("late donor", a1_reads[9]["harness_reply"])
        self.assertEqual(a1_reads[8]["returned_real_foreign_seqs"], [])
        self.assertNotIn("LEAK", [f["flag"] for f in result["check"]["flags"]])
        self.assertFalse(result["check"]["task_success"])

    def test_leak_is_flagged(self):
        turns = [{"turn": 3, "position_in_turn": 0, "agent": "A1", "action": "read_log",
                  "returned_real_seqs": [1, 2], "returned_real_foreign_seqs": [2]}]
        verdict = checker.check_run(turns, [], SC, condition="base")
        self.assertIn("LEAK", [f["flag"] for f in verdict["flags"]])
        self.assertFalse(verdict["valid"])

    def test_parse_action_variants(self):
        self.assertEqual(H.parse_action("**READ_LOG**")["name"], "READ_LOG")
        p = H.parse_action("Sure.\nWRITE_LOG: note\nmore")
        self.assertEqual((p["name"], p["body"], p["parse_mode"]), ("WRITE_LOG", "note\nmore", "recovered"))
        self.assertIsNone(H.parse_action("I will read the log")["name"])


if __name__ == "__main__":
    unittest.main()
