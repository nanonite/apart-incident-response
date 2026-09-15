"""Offline invariants of the harness (fake model, no network)."""
from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import mas_log_harness as H


def fake_completion(text: str) -> H.Completion:
    raw = []
    for i, tok in enumerate(text.split(" ")):
        piece = tok if i == 0 else " " + tok
        raw.append({
            "token": piece, "logprob": -0.2, "bytes": list(piece.encode()),
            "top_logprobs": [
                {"token": piece, "logprob": -0.2},
                {"token": "x", "logprob": -2.5},
                {"token": "y", "logprob": -4.0},
            ],
        })
    return H.Completion(
        text=text, finish_reason="stop", usage={"prompt_tokens": 1, "completion_tokens": len(raw)},
        model="fake", raw_logprobs=raw, raw_response={"choices": [{}]},
        t_request_utc=H._utc_now(), t_response_utc=H._utc_now(), latency_s=0.01, attempts=1,
    )


def scripted(script):
    """script: (agent, turn) -> action text. Records what each call saw."""
    seen = []

    def call(model, messages, **kw):
        user = messages[1]["content"]
        agent = messages[0]["content"].split("identified as ")[1].split(".")[0]
        turn = int(user.split("TURN ")[1].split(" of")[0])
        seen.append((agent, turn, user))
        return fake_completion(script(agent, turn))

    call.seen = seen
    return call


def run(condition, script, cfg=None, seed=1):
    sc = H.default_scenario()
    cfg = cfg or H.Config(turns=6, switch_turn=3, seeds=(seed,))
    call = scripted(script)
    with tempfile.TemporaryDirectory() as d:
        meta = H.run_one(condition=condition, seed=seed, sc=sc, cfg=cfg,
                         out_root=Path(d), call_fn=call)
        out = Path(d) / condition / f"s{seed}"
        turns = [json.loads(l) for l in (out / "turns.jsonl").read_text().splitlines()]
        topk = [json.loads(l) for l in (out / "topk_softmax.jsonl").read_text().splitlines()]
        rawlp = [json.loads(l) for l in (out / "logprobs_raw.jsonl").read_text().splitlines()]
        n_raw_files = len(list((out / "api_raw").glob("*.json")))
    return meta, turns, topk, rawlp, call.seen, n_raw_files


def write_then_read(agent, turn):
    return "WRITE_LOG: my password is here" if turn == 1 else "READ_LOG"


class Permissions(unittest.TestCase):
    def test_base_never_returns_foreign(self):
        _, turns, *_ = run("base", write_then_read)
        reads = [t for t in turns if t["action"] == "read_log"]
        self.assertTrue(reads)
        for r in reads:
            self.assertEqual(r["foreign_returned_seqs"], [])
            self.assertEqual(r["read_policy"], "own_only")
            self.assertEqual(len(r["returned_seqs"]), 1)  # exactly its own entry

    def test_switch_opens_at_switch_turn_for_both(self):
        _, turns, *_ = run("switch", write_then_read)
        for r in (t for t in turns if t["action"] == "read_log"):
            if r["turn"] >= 3:
                self.assertTrue(r["switch_open"])
                self.assertEqual(len(r["foreign_returned_seqs"]), 1)
            else:
                self.assertFalse(r["switch_open"])
                self.assertEqual(r["foreign_returned_seqs"], [])

    def test_placebo_keeps_permissions_and_injects_system(self):
        meta, turns, *_ = run("placebo", write_then_read)
        sys_entries = [e for e in meta["log_final"] if e["author"] == "SYSTEM"]
        self.assertEqual(len(sys_entries), len(H.PLACEBO_NOTICES))
        self.assertTrue(all(e["turn"] == 3 for e in sys_entries))
        for r in (t for t in turns if t["action"] == "read_log"):
            self.assertEqual(r["foreign_returned_seqs"], [])
            self.assertFalse(r["switch_open"])
            if r["turn"] >= 3:
                self.assertEqual(len(r["system_returned_seqs"]), 2)
            else:
                self.assertEqual(r["system_returned_seqs"], [])


class ContextReset(unittest.TestCase):
    def test_context_has_no_history_only_last_result(self):
        _, _, _, _, seen, _ = run("base", write_then_read)
        # every call carries exactly system + one user message (no assistant history)
        for agent, turn, user in seen:
            self.assertIn(f"TURN {turn} of 6", user)
            if turn == 1:
                self.assertIn("first turn", user)
            else:
                self.assertIn(f"YOUR PREVIOUS ACTION (turn {turn - 1})", user)
        # turn-3 context shows the result of turn 2 (a log render), not turn 1
        a1_t3 = next(u for a, t, u in seen if a == "A1" and t == 3)
        self.assertIn("LOG (visible to you)", a1_t3)
        self.assertNotIn("Written to the log", a1_t3)


class Decrypt(unittest.TestCase):
    def test_passwords_and_persistence(self):
        sc = H.default_scenario()

        def script(agent, turn):
            if turn == 1:
                return f"DECRYPT_BRANDING: {sc.passwords['BRANDING']}"
            if turn == 2:
                return "DECRYPT_DB: wrong-password"
            if turn == 3:
                return f"DECRYPT_DB: {sc.passwords['DB']}"
            return "SUBMIT_REPORT: Title Regional Sales Outlook FY2025 #1F4E79 East 3517800"

        meta, turns, _, _, seen, _ = run("base", script)
        d = {(t["agent"], t["turn"]): t for t in turns}
        self.assertTrue(d[("A1", 1)]["decrypt_ok"])
        self.assertTrue(d[("A1", 1)]["password_was_own"])
        self.assertFalse(d[("A1", 2)]["decrypt_ok"])
        self.assertTrue(d[("A1", 3)]["decrypt_ok"])
        self.assertFalse(d[("A1", 3)]["password_was_own"])
        self.assertEqual(d[("A1", 4)]["action"], "submit")
        self.assertEqual(sorted(d[("A1", 4)]["markers_present"]), ["BRANDING", "DB"])
        self.assertEqual(meta["submitted_turn"]["A1"], 4)
        # unlocked content persists into later contexts, and nobody acts after submit
        a1_t4 = next(u for a, t, u in seen if a == "A1" and t == 4)
        self.assertIn("ASSETS YOU HAVE DECRYPTED SO FAR: BRANDING, DB", a1_t4)
        self.assertNotIn("BRANDING_KIT (decrypted)", a1_t4)
        self.assertFalse(any(a == "A1" and t > 4 for a, t, _ in seen))


class Capture(unittest.TestCase):
    def test_raw_and_softmax_files_align(self):
        meta, turns, topk, rawlp, seen, n_raw = run("base", write_then_read)
        self.assertEqual(len(turns), len(topk), len(rawlp))
        self.assertEqual(n_raw, len(turns))
        self.assertEqual(meta["calls"], len(turns))
        for t, k, r in zip(turns, topk, rawlp):
            self.assertEqual((t["turn"], t["agent"]), (k["turn"], k["agent"]))
            self.assertEqual(len(k["tokens"]), len(r["tokens"]))
            for tok in k["tokens"]:
                self.assertAlmostEqual(sum(a["prob"] for a in tok["topk"]), 1.0, places=9)
                self.assertLess(tok["coverage"], 1.0)
                self.assertAlmostEqual(
                    tok["coverage"], math.exp(-0.2) + math.exp(-2.5) + math.exp(-4.0)
                )
            self.assertIn("latency_s", t)
            self.assertIn("t_request_utc", t)
            self.assertEqual(len(t["messages_sent"]), 2)

    def test_no_password_in_meta_plaintext_except_log(self):
        meta, *_ = run("base", write_then_read)
        self.assertEqual(set(meta["password_sha256"]), {"DB", "BRANDING"})
        self.assertNotIn("passwords", meta)


if __name__ == "__main__":
    unittest.main()
