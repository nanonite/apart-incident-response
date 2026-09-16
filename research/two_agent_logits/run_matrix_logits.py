"""Run conditions x seeds in parallel threads and flatten the capture.

Per run directory (<out>/<condition>/s<seed>/) the harness already writes:
    turns.jsonl         one row per agent-turn (full context sent, completion,
                        action, harness reply, timing, switch state)
    logprobs_raw.jsonl  RAW log-probabilities per token (as returned)
    topk_softmax.jsonl  top-k renormalised distribution per token
    log_events.jsonl    every shared-log append (agent writes + placebo)
    api_raw/*.json      full API response body per call
    meta.json           run-level metadata, final log, submissions

This runner adds, at <out>/:
    turns_index.csv     one row per agent-turn WITHOUT the prompt text
    tokens.csv.gz       one row per generated token (raw logprob + coverage)
    topk_long.csv.gz    one row per (token, alternative) with softmax prob
    log_events.csv      all shared-log entries
    run_summary.json    counts, errors, usage
"""
from __future__ import annotations

import csv
import gzip
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any

import mas_log_harness as H

_lock = threading.Lock()

TURN_INDEX_COLS = [
    "run_id", "scenario_id", "condition", "seed", "turn", "agent", "acts_first_in_turn",
    "call_index", "switch_open", "read_policy_this_turn", "placebo_injected_so_far",
    "log_size_before_action", "model_requested", "model_returned", "temperature",
    "top_logprobs_requested", "max_tokens", "api_seed", "t_request_utc", "t_response_utc",
    "latency_s", "turn_wall_s", "attempts", "finish_reason", "n_tokens_with_logprobs",
    "prompt_tokens", "completion_tokens", "action", "action_line", "decrypt_ok",
    "password_was_own", "seq", "contains_own_password", "read_policy", "n_returned",
    "n_foreign_returned", "n_system_returned", "submission_chars", "markers_db",
    "markers_branding", "unlocked_after", "submitted_after", "api_error",
]


def _turn_index_row(t: dict[str, Any]) -> dict[str, Any]:
    u = t.get("usage") or {}
    mk = t.get("markers_present") or {}
    return {
        **{k: t.get(k) for k in TURN_INDEX_COLS if k in t},
        "prompt_tokens": u.get("prompt_tokens"),
        "completion_tokens": u.get("completion_tokens"),
        "n_returned": len(t["returned_seqs"]) if "returned_seqs" in t else None,
        "n_foreign_returned": len(t["foreign_returned_seqs"]) if "foreign_returned_seqs" in t else None,
        "n_system_returned": len(t["system_returned_seqs"]) if "system_returned_seqs" in t else None,
        "markers_db": len(mk.get("DB", [])) if mk else None,
        "markers_branding": len(mk.get("BRANDING", [])) if mk else None,
        "unlocked_after": "|".join(t.get("unlocked_after") or []),
        "action_line": (t.get("action_line") or "").replace("\n", " "),
    }


def flatten(out: Path) -> dict[str, int]:
    """Read every run directory back and write the flat tables."""
    idx_rows: list[dict[str, Any]] = []
    n_tok = n_alt = 0
    log_rows: list[dict[str, Any]] = []
    with gzip.open(out / "tokens.csv.gz", "wt", newline="", encoding="utf8") as ftok, \
         gzip.open(out / "topk_long.csv.gz", "wt", newline="", encoding="utf8") as falt:
        wtok = csv.writer(ftok)
        wtok.writerow(["run_id", "condition", "seed", "turn", "agent", "call_index", "action",
                       "pos", "token", "logprob_raw_ln", "prob_full_vocab", "k", "coverage_topk",
                       "chosen_in_topk"])
        walt = csv.writer(falt)
        walt.writerow(["run_id", "condition", "seed", "turn", "agent", "call_index", "pos",
                       "rank", "alt_token", "alt_logprob_raw_ln", "alt_prob_softmax_topk"])
        for run_dir in sorted(p for p in out.glob("*/s*") if p.is_dir()):
            turns = [json.loads(l) for l in (run_dir / "turns.jsonl").read_text(encoding="utf8").splitlines()]
            action_by_call = {t["call_index"]: t.get("action") for t in turns}
            idx_rows.extend(_turn_index_row(t) for t in turns)
            raw_lines = (run_dir / "logprobs_raw.jsonl").read_text(encoding="utf8").splitlines()
            sm_lines = (run_dir / "topk_softmax.jsonl").read_text(encoding="utf8").splitlines()
            for rl, sl in zip(raw_lines, sm_lines):
                r, s = json.loads(rl), json.loads(sl)
                assert (r["call_index"], r["turn"], r["agent"]) == (s["call_index"], s["turn"], s["agent"])
                key = [r["run_id"], r["condition"], r["seed"], r["turn"], r["agent"], r["call_index"]]
                act = action_by_call.get(r["call_index"])
                for rt, st in zip(r["tokens"], s["tokens"]):
                    wtok.writerow(key + [act, st["pos"], rt.get("token", ""), rt.get("logprob"),
                                         st["chosen_prob_full_vocab"], st["k"], st["coverage"],
                                         st["chosen_in_topk"]])
                    n_tok += 1
                    for rank, (ra, sa) in enumerate(zip(rt.get("top_logprobs") or [], st["topk"])):
                        walt.writerow(key + [st["pos"], rank, ra.get("token", ""), ra.get("logprob"), sa["prob"]])
                        n_alt += 1
            ev = run_dir / "log_events.jsonl"
            if ev.exists():
                log_rows.extend(json.loads(l) for l in ev.read_text(encoding="utf8").splitlines())
    cols = TURN_INDEX_COLS
    with (out / "turns_index.csv").open("w", newline="", encoding="utf8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(idx_rows)
    if log_rows:
        with (out / "log_events.csv").open("w", newline="", encoding="utf8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(log_rows[0].keys()), extrasaction="ignore")
            w.writeheader()
            w.writerows(log_rows)
    return {"agent_turns": len(idx_rows), "tokens": n_tok, "alternatives": n_alt, "log_entries": len(log_rows)}


def main(out_dir: str, cfg: H.Config, sc: H.Scenario | None = None, workers: int = 8,
         conditions=H.CONDITIONS) -> dict[str, Any]:
    assert os.environ.get("OPENROUTER_API_KEY"), "key must be in the environment"
    sc = sc or H.default_scenario()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(c, s) for c in conditions for s in cfg.seeds]
    t0 = time.time()
    metas, failed = [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(H.run_one, condition=c, seed=s, sc=sc, cfg=cfg, out_root=out): (c, s)
                for c, s in jobs}
        for fut in as_completed(futs):
            key = futs[fut]
            try:
                m = fut.result()
            except Exception as exc:  # one dead cell must not kill the matrix
                failed.append({"cell": key, "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
                with _lock:
                    print(f"  FAILED {key}: {type(exc).__name__}", flush=True)
                continue
            metas.append(m)
            with _lock:
                print(f"  {m['condition']:8s} s{m['seed']:<3d} calls={m['calls']:3d} "
                      f"tok={m['tokens_with_logprobs']:4d} submitted={m['submitted_turn']} "
                      f"errors={sum(len(v) for v in m['api_errors'].values())}", flush=True)
    counts = flatten(out)
    summary = {
        "scenario_id": sc.scenario_id,
        "config": asdict(cfg),
        "conditions": list(conditions),
        "cells_planned": len(jobs),
        "cells_completed": len(metas),
        "cells_failed": failed,
        "calls": sum(m["calls"] for m in metas),
        "api_errors": sum(len(v) for m in metas for v in m["api_errors"].values()),
        "submissions": sum(1 for m in metas for v in m["submitted"].values() if v),
        "wall_s": time.time() - t0,
        **counts,
    }
    (out / "run_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf8")
    (out / "scenario.json").write_text(json.dumps({
        **{k: v for k, v in asdict(sc).items() if k != "passwords"},
        "password_sha256": sc.hashes(),
        "note": "passwords omitted here; they appear verbatim inside the agents' private "
                "materials in turns.jsonl (messages_sent) because the agents were given them",
    }, indent=1, ensure_ascii=False), encoding="utf8")
    return summary
