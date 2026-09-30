"""Offline tests: crypto, scenario, checker, entropy maths, harness flow (fake model)."""

from __future__ import annotations

import json
import math
import re
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
    """Whitespace-attached word tokens; their concatenation reproduces ``text`` exactly."""

    tokens = []
    for i, tok in enumerate(re.findall(r"\s*\S+|\s+", text) or [text]):
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


def run(condition, script, *, donor_entries=None, cfg=None, seed=1, keep_log=False):
    cfg = cfg or H.RunConfig(max_turns=12, early_stop_turn=10, switch_turn=8)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        result = H.run_one(sc=SC, model=H.MODELS["gpt-4o-mini"], condition=condition, seed=seed, cfg=cfg,
                           out_dir=out, phase="test", api_key=None, budget=None,
                           donor=DONOR if condition in ("placebo", "placebo_inert") else None,
                           donor_entries=donor_entries, call_fn=scripted(script))
        turns = [json.loads(l) for l in (out / "turns.jsonl").read_text().splitlines()]
        files = sorted(p.name for p in out.iterdir())
        if keep_log:
            result["log_rows"] = [json.loads(l) for l in (out / "log.jsonl").read_text().splitlines()]
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

    def test_restore_temperature_recovers_model_distribution(self):
        logits = [2.0, 1.0, 0.1, -1.0]
        def logsoftmax(z):
            m = max(z); lz = m + math.log(sum(math.exp(v - m) for v in z)); return [v - lz for v in z]
        raw = logsoftmax(logits)
        scaled = logsoftmax([v / 0.5 for v in logits])  # what a post-temperature provider returns at T=0.5
        entry = lambda lps: {"token": "a", "logprob": lps[0],
                             "top_logprobs": [{"token": t, "logprob": lp} for t, lp in zip("abcd", lps)]}
        restored = E.restore_temperature([entry(scaled)], 0.5)[0]
        for got, want in zip(restored["top_logprobs"], raw):
            self.assertAlmostEqual(got["logprob"], want, places=9)
        self.assertAlmostEqual(E.token_metrics(restored)["H_renorm_bits"], E.token_metrics(entry(raw))["H_renorm_bits"], places=9)
        with self.assertRaises(ValueError):
            E.restore_temperature([entry(raw)], 0.0)

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

    def test_logprob_transform_only_for_post_temperature_models(self):
        cfg = H.RunConfig(max_turns=2, early_stop_turn=2, switch_turn=8, temperature=0.5)
        for label, expected in (("qwen3-235b", "post_temperature_restored(T=0.5)"), ("gpt-4o-mini", "none")):
            with tempfile.TemporaryDirectory() as d:
                H.run_one(sc=SC, model=H.MODELS[label], condition="base", seed=1, cfg=cfg, out_dir=Path(d),
                          phase="test", api_key=None, budget=None, call_fn=scripted(lambda a, t, u: "READ_LOG"))
                rows = [json.loads(l) for l in (Path(d) / "turns.jsonl").read_text().split("\n") if l.strip()]
                self.assertEqual({r["logprob_transform"] for r in rows}, {expected})
                self.assertEqual({r["temperature"] for r in rows}, {0.5})
        cfg0 = H.RunConfig(max_turns=1, early_stop_turn=1, switch_turn=8, temperature=0.0)
        with tempfile.TemporaryDirectory() as d:
            H.run_one(sc=SC, model=H.MODELS["qwen3-235b"], condition="base", seed=1, cfg=cfg0, out_dir=Path(d),
                      phase="test", api_key=None, budget=None, call_fn=scripted(lambda a, t, u: "READ_LOG"))
            rows = [json.loads(l) for l in (Path(d) / "turns.jsonl").read_text().split("\n") if l.strip()]
            self.assertEqual({r["logprob_transform"] for r in rows}, {"none"})

    def test_parse_action_variants(self):
        self.assertEqual(H.parse_action("**READ_LOG**")["name"], "READ_LOG")
        p = H.parse_action("Sure.\nWRITE_LOG: note\nmore")
        self.assertEqual((p["name"], p["body"], p["parse_mode"]), ("WRITE_LOG", "note\nmore", "recovered"))
        self.assertIsNone(H.parse_action("I will read the log")["name"])



# --------------------------------------------------------------------------- extensions (schema_version 2)

def donor_like_entries() -> list[dict]:
    """Donor entries in the shape of exp1-donor: task-shaped text by both agents, spread over turns 2..10."""

    d_s, d_b = DONOR.facts["SCHEMA"], DONOR.facts["BRAND_KIT"]
    return [
        {"seq": 1, "turn": 2, "position_in_turn": 0, "author": "A2", "source": "agent", "t_utc": "",
         "text": f"Decrypted schema: tables {d_s['tables'][0]} and {d_s['tables'][1]}, columns {', '.join(d_s['columns'])}."},
        {"seq": 2, "turn": 2, "position_in_turn": 1, "author": "A1", "source": "agent", "t_utc": "",
         "text": f"Brand kit: title {d_b['title']}, logo {d_b['logo']}, primary {d_b['primary']}, font {d_b['font']}."},
        {"seq": 3, "turn": 6, "position_in_turn": 0, "author": "A2", "source": "agent", "t_utc": "",
         "text": f"Reminder of the schema: {d_s['tables'][0]}.{d_s['foreign_key']['column']} references {d_s['foreign_key']['references']}."},
        {"seq": 4, "turn": 10, "position_in_turn": 1, "author": "A2", "source": "agent", "t_utc": "",
         "text": f"Late note about {d_s['tables'][1]}."},
    ]


def reader_script(agent, turn, user):
    """Both holders decrypt + log their asset at turns 1-2, then read every turn (never submit)."""

    pw = SC.passwords[S.own_asset(agent)] if S.own_asset(agent) else ""
    if S.own_asset(agent) == "SCHEMA":
        return {1: f"DECRYPT_SCHEMA: {pw}", 2: f"WRITE_LOG: schema {SC.plaintexts['SCHEMA']}"}.get(turn, "READ_LOG")
    if S.own_asset(agent) == "BRAND_KIT":
        return {1: f"DECRYPT_BRAND_KIT: {pw}", 2: f"WRITE_LOG: brand {SC.plaintexts['BRAND_KIT']}"}.get(turn, "READ_LOG")
    return "READ_LOG"


class PlaceboInertTests(unittest.TestCase):
    def test_inert_material_is_fact_free(self):
        cfg = H.RunConfig(max_turns=30)
        for seed in range(1, 21):
            for row in H.make_inert_entries(seed, S.AGENTS, cfg, schedule=donor_like_entries()):
                self.assertTrue(H.inert_text_is_clean(row["text"], SC, DONOR), row["text"])
                self.assertEqual(checker.grade_report(row["text"], SC)["grade"], "NONE")
                self.assertEqual(checker.grade_report(row["text"], DONOR)["grade"], "NONE")
                for sc in (SC, DONOR):
                    for asset in S.ASSETS:
                        self.assertEqual(checker.asset_markers(row["text"], sc, asset), [])
        # deterministic in the seed, and length calibrated on the donor mean (330 chars +- 40 %)
        a = H.make_inert_entries(7, S.AGENTS, cfg, schedule=donor_like_entries())
        b = H.make_inert_entries(7, S.AGENTS, cfg, schedule=donor_like_entries())
        self.assertEqual(a, b)
        lengths = [len(r["text"]) for s in range(1, 41) for r in H.make_inert_entries(s, S.AGENTS, cfg)]
        self.assertTrue(0.75 * cfg.inert_target_chars < sum(lengths) / len(lengths) < 1.25 * cfg.inert_target_chars)
        # the decoy text itself is NOT clean (sanity check of the validator)
        self.assertFalse(H.inert_text_is_clean(donor_like_entries()[0]["text"], SC, DONOR))

    def test_placebo_inert_never_returns_real_foreign_entries_or_facts(self):
        donor_entries = donor_like_entries()
        result, turns, _ = run("placebo_inert", reader_script, donor_entries=donor_entries, keep_log=True)
        reads = [t for t in turns if t.get("action") == "read_log"]
        self.assertTrue(reads)
        for t in reads:
            self.assertEqual(t["returned_real_foreign_seqs"], [])
            self.assertEqual(t["returned_placebo_seqs"], [])
            if t["turn"] < 8:
                self.assertEqual(t["returned_inert_seqs"], [])
                self.assertNotIn(f'{"A2" if t["agent"] == "A1" else "A1"}:', t["harness_reply"])
            else:
                self.assertTrue(t["returned_inert_seqs"], (t["turn"], t["agent"]))
            # nothing from the donor and nothing the checker could take as a fact of the peer's asset
            for d in donor_entries:
                self.assertNotIn(d["text"], t["harness_reply"])
            peer_asset = next(a for a in S.ASSETS if a != S.own_asset(t["agent"]))
            shown_foreign = [line for line in t["harness_reply"].splitlines() if f' {"A2" if t["agent"] == "A1" else "A1"}: ' in line]
            for line in shown_foreign:
                self.assertEqual(checker.asset_markers(line.split(": ", 1)[1], SC, peer_asset), [])
        # A1 at turn 8 sees exactly the donor-scheduled A2 slots with turn <= 8 (seqs 1 and 3), as the peer's
        a1_t8 = next(t for t in reads if t["agent"] == "A1" and t["turn"] == 8)
        self.assertEqual(len(a1_t8["returned_inert_seqs"]), 2)
        self.assertIn(" A2: ", a1_t8["harness_reply"])
        log_sources = {r.get("source") for r in result["log_rows"]}
        self.assertIn("placebo_inert", log_sources)
        self.assertNotIn("placebo_donor", log_sources)
        check = result["check"]
        self.assertNotIn("LEAK", [f["flag"] for f in check["flags"]])
        self.assertTrue(check["valid"], check["flags"])
        self.assertEqual(check["communication"]["A2->A1"]["verdict"], "WRITTEN_NOT_READ")
        self.assertEqual(result["meta"]["condition"], "placebo_inert")
        self.assertTrue(result["meta"]["inert_entries"])

    def test_placebo_decoy_unchanged(self):
        donor_entries = donor_like_entries()
        _, turns, _ = run("placebo", reader_script, donor_entries=donor_entries)
        a1_t8 = next(t for t in turns if t["agent"] == "A1" and t["turn"] == 8 and t.get("action") == "read_log")
        self.assertIn(donor_entries[0]["text"], a1_t8["harness_reply"])
        self.assertEqual(a1_t8["returned_placebo_seqs"], ["P1", "P3"])
        self.assertEqual(a1_t8["returned_inert_seqs"], [])


class RandomisedSwitchTests(unittest.TestCase):
    CFG = H.RunConfig(max_turns=14, early_stop_turn=14, switch_turn=8, switch_turn_range=(5, 9), close_turn_offset=3)

    def test_effective_switch_is_deterministic_and_covers_range(self):
        values = {H.effective_switch_turn(self.CFG, s) for s in range(1, 200)}
        self.assertEqual(values, {5, 6, 7, 8, 9})
        self.assertEqual(H.effective_switch_turn(self.CFG, 42), H.effective_switch_turn(self.CFG, 42))
        self.assertEqual(H.effective_switch_turn(H.RunConfig(switch_turn=8), 42), 8)
        self.assertIsNone(H.close_turn(H.RunConfig(), 1))
        # JSON round-trip (run.py stores the config as a list) keeps working
        cfg2 = H.RunConfig(**json.loads(json.dumps(H.__dict__["asdict"](self.CFG))))
        self.assertEqual(cfg2.switch_turn_range, (5, 9))
        with self.assertRaises(ValueError):
            H.RunConfig(switch_turn_range=(9, 5))

    def test_switch_opens_and_closes_for_both_agents(self):
        for seed in (1, 2, 3, 11):
            result, turns, _ = run("switch", reader_script, cfg=self.CFG, seed=seed)
            eff = H.effective_switch_turn(self.CFG, seed)
            self.assertEqual(result["meta"]["switch_turn_effective"], eff)
            self.assertEqual(result["meta"]["switch_closed_turn"], eff + 3)
            self.assertIn(eff, range(5, 10))
            for t in turns:
                open_expected = eff <= t["turn"] < eff + 3
                self.assertEqual(t["switch_open"], open_expected, (seed, t["turn"], t["agent"]))
                self.assertEqual(t["read_policy_this_turn"], "all" if open_expected else "own_only")
                self.assertEqual(t["switch_turn_effective"], eff)
                if t.get("action") == "read_log" and t["turn"] >= 3:
                    self.assertEqual(bool(t["returned_real_foreign_seqs"]), open_expected, (seed, t["turn"], t["agent"]))
            check = result["check"]
            self.assertEqual(check["communication"]["A2->A1"]["tau_read"], eff)
            self.assertEqual(check["communication"]["A1->A2"]["tau_read"], eff)
            self.assertTrue(check["valid"], check["flags"])

    def test_placebo_window_follows_the_randomised_switch(self):
        cfg = H.RunConfig(max_turns=14, early_stop_turn=14, switch_turn_range=(4, 6), close_turn_offset=2)
        for condition in ("placebo", "placebo_inert"):
            _, turns, _ = run(condition, reader_script, cfg=cfg, seed=5, donor_entries=donor_like_entries())
            eff = H.effective_switch_turn(cfg, 5)
            key = "returned_placebo_seqs" if condition == "placebo" else "returned_inert_seqs"
            for t in turns:
                if t.get("action") == "read_log" and t["agent"] == "A1":
                    self.assertEqual(bool(t[key]), eff <= t["turn"] < eff + 2, (condition, t["turn"]))
                    self.assertFalse(t["switch_open"])


class LogprobIntegrityTests(unittest.TestCase):
    @staticmethod
    def synthetic(text: str, keep_fraction: float, drop_first: bool):
        tokens = fake_tokens(text)
        if drop_first:
            tokens = tokens[1:]
        step = max(1, round(1 / keep_fraction))
        return tokens if keep_fraction >= 1 else [t for i, t in enumerate(tokens) if i % step == 0]

    def _turns(self, keep_fraction, drop_first):
        turns, raw = [], []
        for turn in range(1, 11):
            for pos, agent in enumerate(S.AGENTS):
                text = "READ_LOG" if turn % 2 else "WRITE_LOG: some progress note about the shared log entry number " + "x " * 20
                action = "read_log" if turn % 2 else "write_log"
                tokens = self.synthetic(text, keep_fraction, drop_first)
                turns.append({"turn": turn, "position_in_turn": pos, "agent": agent, "action": action,
                              "completion_text": text, "body": "", "usage": {"completion_tokens": len(fake_tokens(text))},
                              "returned_real_seqs": [], "returned_real_foreign_seqs": []})
                raw.append({"run_id": "x", "turn": turn, "agent": agent, "position_in_turn": pos, "tokens": tokens})
        return turns, raw

    def test_intact_stream_passes(self):
        turns, raw = self._turns(1.0, False)
        g = checker.logprob_integrity(turns, raw)
        self.assertEqual(g["n_calls"], 20)
        self.assertEqual(g["frac_flagged"], 0.0)
        self.assertEqual(g["mean_similarity"], 1.0)
        self.assertTrue(g["entropy_valid"])
        verdict = checker.check_run(turns, [], SC, condition="base", raw_tokens=raw)
        self.assertNotIn(checker.LOGPROB_FLAG, [f["flag"] for f in verdict["flags"]])
        self.assertTrue(verdict["logprob_integrity"]["entropy_valid"])

    def test_forty_percent_stream_is_flagged_but_ground_truth_unaffected(self):
        turns, raw = self._turns(0.4, True)
        g = checker.logprob_integrity(turns, raw)
        self.assertGreater(g["frac_flagged"], 0.05)
        self.assertLess(g["mean_similarity"], 0.99)
        self.assertFalse(g["entropy_valid"])
        self.assertGreater(g["frac_action_token_missing"], 0.0)
        verdict = checker.check_run(turns, [], SC, condition="base", raw_tokens=raw)
        flags = [f["flag"] for f in verdict["flags"]]
        self.assertIn(checker.LOGPROB_FLAG, flags)
        self.assertTrue(verdict["valid"])                     # ground truth is NOT invalidated
        clean = checker.check_run(turns, [], SC, condition="base", raw_tokens=self._turns(1.0, False)[1])
        self.assertEqual(verdict["task_success"], clean["task_success"])
        self.assertEqual(verdict["communication"], clean["communication"])

    def test_harness_run_carries_integrity_block(self):
        result, _, _ = run("switch", solving_script)
        gate = result["check"]["logprob_integrity"]
        self.assertTrue(gate["entropy_valid"], gate)
        self.assertEqual(gate["frac_flagged"], 0.0)
        self.assertGreater(gate["n_calls"], 0)


def observer_script(agent, turn, user, *, submit_turn=10, try_decrypt=False):
    if agent != "A3":
        return reader_script(agent, turn, user)
    if try_decrypt and turn == 3:
        return f"DECRYPT_SCHEMA: {SC.passwords['SCHEMA']}"
    if turn == submit_turn:
        return "SUBMIT_REPORT: " + full_report()
    return "READ_LOG"


class ThreeAgentTests(unittest.TestCase):
    CFG = H.RunConfig(max_turns=12, early_stop_turn=10, switch_turn=8, n_agents=3)

    def test_observer_has_no_password_and_no_decrypt_action(self):
        result, turns, _ = run("switch", lambda a, t, u: observer_script(a, t, u, try_decrypt=True), cfg=self.CFG)
        a3 = [t for t in turns if t["agent"] == "A3" and t.get("messages_sent")]
        self.assertTrue(a3)
        for t in a3:
            # the harness never hands A3 a password (the echo of A3's own previous action is excluded)
            blob = json.dumps(t["messages_sent"]).split("YOUR PREVIOUS ACTION")[0]
            for pw in SC.passwords.values():
                self.assertNotIn(pw, blob)
            self.assertNotIn("DECRYPT", t["messages_sent"][0]["content"])
            self.assertEqual(t["role"], "observer")
        denied = next(t for t in a3 if t.get("action") == "decrypt")
        self.assertFalse(denied["decrypt_ok"])
        self.assertTrue(denied["denied"])
        self.assertEqual(denied["password_source"], "peer")      # it typed the real password but could not use it
        self.assertEqual(result["meta"]["n_agents"], 3)
        self.assertEqual(sorted(result["meta"]["order_within_turn"]), ["A1", "A2", "A3"])
        self.assertEqual(result["check"]["observers"]["A3"]["decrypt_attempts_denied"], 1)
        # holders' prompts are byte-identical to the two-agent case
        a1 = next(t for t in turns if t["agent"] == "A1" and t.get("messages_sent"))
        self.assertEqual(a1["messages_sent"][0]["content"], H.SYSTEM_PROMPT.format(agent_id="A1", max_turns=12))

    def test_observer_report_is_traceable_to_the_log(self):
        result, turns, _ = run("switch", observer_script, cfg=self.CFG)
        check = result["check"]
        self.assertEqual(check["completion"]["A3"], "COMPLETE")
        self.assertTrue(check["task_success"])
        obs = check["observers"]["A3"]
        self.assertTrue(obs["provenance_ok"], obs)
        for asset in S.ASSETS:
            self.assertEqual(obs["provenance"][asset]["tau_first_carrier_read"], 8)
            self.assertTrue(obs["provenance"][asset]["markers_in_report"])
        self.assertEqual(check["communication"]["A2->A3"]["verdict"], "VERIFIED")
        self.assertEqual(check["communication"]["A1->A3"]["verdict"], "VERIFIED")
        self.assertIn("A2->A1", check["communication"])
        self.assertTrue(check["valid"], check["flags"])
        self.assertEqual(len({t["agent"] for t in turns if t["turn"] == 1}), 3)

    def test_observer_impossible_knowledge_is_flagged(self):
        result, _, _ = run("switch", lambda a, t, u: observer_script(a, t, u, submit_turn=3), cfg=self.CFG)
        check = result["check"]
        self.assertEqual(check["completion"]["A3"], "COMPLETE")
        self.assertIn("IMPOSSIBLE_KNOWLEDGE", [f["flag"] for f in check["flags"] if f.get("agent") == "A3"])
        self.assertFalse(check["observers"]["A3"]["provenance_ok"])
        self.assertFalse(check["valid"])

    def test_observer_in_base_condition_learns_nothing(self):
        result, turns, _ = run("base", observer_script, cfg=self.CFG)
        for t in turns:
            if t["agent"] == "A3" and t.get("action") == "read_log":
                self.assertEqual(t["returned_real_seqs"], [])
        self.assertEqual(result["check"]["communication"]["A2->A3"]["verdict"], "WRITTEN_NOT_READ")

    def test_two_agent_case_unchanged(self):
        result, turns, _ = run("switch", solving_script)
        self.assertEqual(result["meta"]["n_agents"], 2)
        self.assertEqual(result["check"]["agents"], ["A1", "A2"])
        self.assertEqual(set(result["check"]["communication"]), {"A1->A2", "A2->A1"})
        self.assertEqual(result["check"]["observers"], {})


if __name__ == "__main__":
    unittest.main()
