"""Publish six-family combined analysis (#121-122, #126).

Merges anchor_screen (hypothesis, reference) + extended_screen (planning, poetry, legal, lexicon)
and produces:
  1. runs/discovery-145/six_family/analysis.json  — per-family C_need/eta_comm/D_idx summary
  2. runs/discovery-145/six_family/per_run_data.json — all rows machine-readable

Estimands:
  C_need = P(success|FULL) - P(success|ISO)
  eta_comm = (P(COMM)-P(ISO)) / C_need  [only when |C_need| >= 0.1]
  D_idx, useful_bits, Wilson CIs
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "src"))

from apart_incident_response.communication_protocol import c_need, eta_comm
from apart_incident_response.communication_analysis import wilson_interval

ANCHOR_ROWS   = _repo_root / "runs" / "discovery-145" / "anchor_screen" / "rows.turns2.json"
EXTENDED_ROWS = _repo_root / "runs" / "discovery-145" / "extended_screen" / "rows.turns2.json"
OUT_DIR       = _repo_root / "runs" / "discovery-145" / "six_family"

ETA_COMM_MIN_DENOMINATOR = 0.1


def load_all_rows() -> list[dict]:
    rows = []
    for path in (ANCHOR_ROWS, EXTENDED_ROWS):
        if path.exists():
            rows.extend(json.loads(path.read_text()))
        else:
            print(f"  WARNING: {path} not found — skipping")
    return rows


def family_summary(rows: list[dict]) -> list[dict]:
    """Per-family aggregate across regimes and complexities (N-regime focus for C_need)."""
    by_cell: dict = defaultdict(dict)
    for row in rows:
        if not row.get("valid"):
            continue
        key = (row["family"], row["regime_hint"], row["complexity"], row["seed"])
        by_cell[key][row["condition"]] = row

    cell_metrics = []
    for (family, regime, complexity, seed), conds in sorted(by_cell.items()):
        iso  = conds.get("ISO")
        full = conds.get("FULL")
        comm = conds.get("COMM")
        p_iso  = float(iso["task_success"])  if iso  else None
        p_full = float(full["task_success"]) if full else None
        p_comm = float(comm["task_success"]) if comm else None
        cn = c_need(p_full, p_iso) if p_full is not None and p_iso is not None else None
        ec = (eta_comm(p_comm, p_iso, p_full)
              if p_comm is not None and cn is not None and abs(cn) >= ETA_COMM_MIN_DENOMINATOR
              else None)
        d  = (full or iso or comm or {}).get("d_idx")
        cell_metrics.append({
            "family": family, "regime_hint": regime, "complexity": complexity, "seed": seed,
            "p_iso": p_iso, "p_full": p_full, "p_comm": p_comm,
            "c_need": cn, "eta_comm": ec, "d_idx": d,
            "regime_measured": (full or iso or comm or {}).get("regime_measured"),
            "useful_bits": (comm or {}).get("useful_bits", 0.0),
        })

    # aggregate per (family, regime, complexity)
    agg: dict = defaultdict(lambda: {"iso":[], "full":[], "comm":[], "c_need":[], "eta_comm":[], "d_idx":[], "useful_bits":[]})
    for m in cell_metrics:
        k = (m["family"], m["regime_hint"], m["complexity"])
        if m["p_iso"]  is not None: agg[k]["iso"].append(m["p_iso"])
        if m["p_full"] is not None: agg[k]["full"].append(m["p_full"])
        if m["p_comm"] is not None: agg[k]["comm"].append(m["p_comm"])
        if m["c_need"] is not None: agg[k]["c_need"].append(m["c_need"])
        if m["eta_comm"] is not None: agg[k]["eta_comm"].append(m["eta_comm"])
        if m["d_idx"]  is not None: agg[k]["d_idx"].append(m["d_idx"])
        agg[k]["useful_bits"].append(m.get("useful_bits", 0.0))

    agg_rows = []
    for (family, regime, complexity), vals in sorted(agg.items()):
        def mean(v): return sum(v)/len(v) if v else None
        p_iso_m  = mean(vals["iso"])
        p_full_m = mean(vals["full"])
        p_comm_m = mean(vals["comm"])
        cn_m  = c_need(p_full_m, p_iso_m) if p_full_m is not None and p_iso_m is not None else None
        ec_m  = (eta_comm(p_comm_m, p_iso_m, p_full_m)
                 if p_comm_m is not None and cn_m is not None and abs(cn_m) >= ETA_COMM_MIN_DENOMINATOR
                 else None)
        agg_rows.append({
            "family": family, "regime_hint": regime, "complexity": complexity,
            "n_seeds": len(vals["full"]) or len(vals["iso"]) or len(vals["comm"]),
            "p_iso_mean": p_iso_m, "p_full_mean": p_full_m, "p_comm_mean": p_comm_m,
            "c_need_mean": cn_m, "eta_comm_mean": ec_m,
            "d_idx_mean": mean(vals["d_idx"]),
            "total_useful_bits": sum(vals["useful_bits"]),
            "eta_comm_denominator_supported": cn_m is not None and abs(cn_m) >= ETA_COMM_MIN_DENOMINATOR,
            "ci_iso":  wilson_interval(round(sum(vals["iso"])),  len(vals["iso"]))  if vals["iso"]  else None,
            "ci_full": wilson_interval(round(sum(vals["full"])), len(vals["full"])) if vals["full"] else None,
            "ci_comm": wilson_interval(round(sum(vals["comm"])), len(vals["comm"])) if vals["comm"] else None,
        })

    return cell_metrics, agg_rows


def per_family_n_regime_summary(agg_rows: list[dict]) -> list[dict]:
    """N-regime summary per family — most informative for C_need."""
    summaries = []
    families = sorted(set(r["family"] for r in agg_rows))
    for family in families:
        n_rows = [r for r in agg_rows if r["family"] == family and r["regime_hint"] == "N"]
        cn_vals = [r["c_need_mean"] for r in n_rows if r["c_need_mean"] is not None]
        ec_vals = [r["eta_comm_mean"] for r in n_rows if r["eta_comm_mean"] is not None]
        pf_vals = [r["p_full_mean"] for r in n_rows if r["p_full_mean"] is not None]
        summaries.append({
            "family": family,
            "n_cells": len(n_rows),
            "mean_c_need_N": sum(cn_vals)/len(cn_vals) if cn_vals else None,
            "mean_eta_comm_N": sum(ec_vals)/len(ec_vals) if ec_vals else None,
            "mean_p_full_N": sum(pf_vals)/len(pf_vals) if pf_vals else None,
            "cells_with_supported_eta_comm": sum(1 for r in n_rows if r.get("eta_comm_denominator_supported")),
        })
    return summaries


def publish() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_all_rows()
    if not rows:
        print("No rows found.")
        return {}

    families = sorted(set(r["family"] for r in rows))
    print(f"Families: {families}")
    print(f"Total rows: {len(rows)}  valid: {sum(1 for r in rows if r.get('valid'))}  "
          f"invalid: {sum(1 for r in rows if not r.get('valid'))}")
    print()

    cell_metrics, agg_rows = family_summary(rows)
    n_summaries = per_family_n_regime_summary(agg_rows)

    per_run = [{
        "family": r["family"], "model": r.get("model", "ling"),
        "regime_hint": r.get("regime_hint"), "complexity": r.get("complexity"),
        "seed": r["seed"], "condition": r["condition"],
        "instance_id": r["instance_id"], "task_success": r["task_success"],
        "valid": r["valid"], "d_idx": r.get("d_idx"),
        "regime_measured": r.get("regime_measured"),
        "useful_bits": r.get("useful_bits", 0.0),
        "communication_tokens": r.get("communication_tokens", 0),
    } for r in rows]

    report = {
        "schema": "six-family-analysis-v1",
        "families": families,
        "total_rows": len(rows),
        "valid_rows": sum(1 for r in rows if r.get("valid")),
        "invalid_rows": sum(1 for r in rows if not r.get("valid")),
        "cell_metrics": cell_metrics,
        "aggregate_rows": agg_rows,
        "n_regime_summaries": n_summaries,
        "per_run_data": per_run,
        "notes": {
            "c_need": "unclipped P(FULL)-P(ISO); negative means ISO outperforms FULL",
            "eta_comm": f"only when |C_need| >= {ETA_COMM_MIN_DENOMINATOR}",
            "invalid_runs": "valid=False preserved in denominators; task_success=False",
        },
    }

    analysis_path = OUT_DIR / "analysis.json"
    per_run_path  = OUT_DIR / "per_run_data.json"
    analysis_path.write_text(json.dumps(report, indent=2))
    per_run_path.write_text(json.dumps(per_run, indent=2))

    print("═" * 60)
    print(f"{'Family':12s}  {'C_need(N)':>10s}  {'eta_comm(N)':>12s}  {'p_full(N)':>10s}")
    for s in n_summaries:
        cn  = f"{s['mean_c_need_N']:.3f}"   if s['mean_c_need_N']   is not None else "n/a"
        ec  = f"{s['mean_eta_comm_N']:.3f}" if s['mean_eta_comm_N'] is not None else "n/a"
        pf  = f"{s['mean_p_full_N']:.3f}"   if s['mean_p_full_N']   is not None else "n/a"
        print(f"  {s['family']:12s}  {cn:>10s}  {ec:>12s}  {pf:>10s}")

    print()
    print(f"Analysis:  {analysis_path}")
    print(f"Per-run:   {per_run_path}")
    return report


if __name__ == "__main__":
    publish()
