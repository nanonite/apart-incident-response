"""Publish model-relative communication-pressure comparison (#150).

Reads anchor screen (Ling) and transfer (Nemotron) rows, then produces:
  1. analysis.json — per-model per-cell metrics + comparison table
  2. per_run_data.json — machine-readable per-run data with invalid denominators

Estimands reported:
  C_need = P(success|FULL) - P(success|ISO)  [unclipped, can be negative]
  eta_comm = (P(COMM)-P(ISO)) / C_need        [only when |C_need| > 0.1]
  D_idx (measured feasible-set reduction, from instance structure)
  sum_m DeltaI_m (verified useful bits, from COMM event log)
  Raw R/H/N rates, latency, tokens, cost per model
  Wilson CIs on each proportion
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "src"))

from apart_incident_response.communication_protocol import c_need, eta_comm
from apart_incident_response.communication_analysis import wilson_interval

ANCHOR_ROWS   = _repo_root / "runs" / "discovery-145" / "anchor_screen" / "rows.turns2.json"
TRANSFER_ROWS = _repo_root / "runs" / "discovery-145" / "transfer" / "rows.turns2.json"
OUT_DIR       = _repo_root / "runs" / "discovery-145" / "comparison"

ETA_COMM_MIN_DENOMINATOR = 0.1   # only compute eta_comm when |C_need| > this


def load_rows() -> list[dict]:
    rows = []
    for path in (ANCHOR_ROWS, TRANSFER_ROWS):
        if path.exists():
            rows.extend(json.loads(path.read_text()))
    return rows


def compute_cell_metrics(rows: list[dict]) -> list[dict]:
    """Compute per (model, family, regime_hint, complexity, seed) metrics."""
    # group by (model, family, regime_hint, complexity, seed) → condition → row
    by_cell: dict = defaultdict(dict)
    for row in rows:
        key = (row["model"], row["family"], row["regime_hint"], row["complexity"], row["seed"])
        by_cell[key][row["condition"]] = row

    metrics = []
    for (model, family, regime, complexity, seed), conds in sorted(by_cell.items()):
        iso_row  = conds.get("ISO")
        full_row = conds.get("FULL")
        comm_row = conds.get("COMM")

        def safe_p(row):
            if row is None or not row.get("valid", False):
                return None
            return float(row["task_success"])

        p_iso  = safe_p(iso_row)
        p_full = safe_p(full_row)
        p_comm = safe_p(comm_row)

        cn = c_need(p_full, p_iso) if p_full is not None and p_iso is not None else None
        ec = (eta_comm(p_comm, p_iso, p_full)
              if p_comm is not None and cn is not None and abs(cn) >= ETA_COMM_MIN_DENOMINATOR
              else None)

        d = (full_row or iso_row or comm_row or {}).get("d_idx")
        regime_m = (full_row or iso_row or comm_row or {}).get("regime_measured")
        post_read_correlated_bits = (comm_row or {}).get("post_read_correlated_bits", 0.0)

        metrics.append({
            "model": model, "family": family, "regime_hint": regime,
            "complexity": complexity, "seed": seed,
            "p_iso": p_iso, "p_full": p_full, "p_comm": p_comm,
            "c_need": cn, "eta_comm": ec,
            "d_idx": d, "regime_measured": regime_m,
            "post_read_correlated_bits": post_read_correlated_bits,
            "valid_iso": iso_row is not None and iso_row.get("valid", False),
            "valid_full": full_row is not None and full_row.get("valid", False),
            "valid_comm": comm_row is not None and comm_row.get("valid", False),
        })
    return metrics


def aggregate_by_model(metrics: list[dict]) -> list[dict]:
    """Aggregate metrics per (model, family, regime_hint, complexity)."""
    groups: dict = defaultdict(list)
    for m in metrics:
        key = (m["model"], m["family"], m["regime_hint"], m["complexity"])
        groups[key].append(m)

    agg_rows = []
    for (model, family, regime, complexity), cells in sorted(groups.items()):
        iso_vals  = [m["p_iso"]  for m in cells if m["p_iso"]  is not None]
        full_vals = [m["p_full"] for m in cells if m["p_full"] is not None]
        comm_vals = [m["p_comm"] for m in cells if m["p_comm"] is not None]
        cn_vals   = [m["c_need"] for m in cells if m["c_need"] is not None]

        n = len(cells)

        def mean_or_none(vals):
            return sum(vals)/len(vals) if vals else None

        p_iso_m  = mean_or_none(iso_vals)
        p_full_m = mean_or_none(full_vals)
        p_comm_m = mean_or_none(comm_vals)

        cn_m  = c_need(p_full_m, p_iso_m) if p_full_m is not None and p_iso_m is not None else None
        ec_m  = (eta_comm(p_comm_m, p_iso_m, p_full_m)
                 if p_comm_m is not None and cn_m is not None and abs(cn_m) >= ETA_COMM_MIN_DENOMINATOR
                 else None)

        total_bits = sum(m.get("post_read_correlated_bits", 0.0) for m in cells)
        regime_counts = defaultdict(int)
        for m in cells:
            r = m.get("regime_measured")
            if r:
                regime_counts[r] += 1

        agg_rows.append({
            "model": model, "family": family, "regime_hint": regime,
            "complexity": complexity, "n_instances": n,
            "n_valid_iso": len(iso_vals), "n_valid_full": len(full_vals),
            "n_valid_comm": len(comm_vals),
            "p_iso_mean": p_iso_m, "p_full_mean": p_full_m, "p_comm_mean": p_comm_m,
            "ci_iso":  wilson_interval(round(sum(iso_vals)),  len(iso_vals))  if iso_vals  else None,
            "ci_full": wilson_interval(round(sum(full_vals)), len(full_vals)) if full_vals else None,
            "ci_comm": wilson_interval(round(sum(comm_vals)), len(comm_vals)) if comm_vals else None,
            "c_need_mean": cn_m,
            "eta_comm_mean": ec_m,
            "eta_comm_denominator_supported": (cn_m is not None and abs(cn_m) >= ETA_COMM_MIN_DENOMINATOR),
            "total_post_read_correlated_bits": total_bits,
            "regime_measured_counts": dict(regime_counts),
        })
    return agg_rows


def model_summary(agg_rows: list[dict], model: str) -> dict:
    """Summary statistics for one model across all cells."""
    model_rows = [r for r in agg_rows if r["model"] == model]
    if not model_rows:
        return {"model": model, "status": "no_data"}

    cn_vals = [r["c_need_mean"] for r in model_rows if r["c_need_mean"] is not None]
    ec_vals = [r["eta_comm_mean"] for r in model_rows if r["eta_comm_mean"] is not None]
    p_full_vals = [r["p_full_mean"] for r in model_rows if r["p_full_mean"] is not None]
    bits_total = sum(r["total_post_read_correlated_bits"] for r in model_rows)

    return {
        "model": model,
        "n_cells": len(model_rows),
        "mean_c_need": sum(cn_vals)/len(cn_vals) if cn_vals else None,
        "mean_eta_comm": sum(ec_vals)/len(ec_vals) if ec_vals else None,
        "mean_p_full": sum(p_full_vals)/len(p_full_vals) if p_full_vals else None,
        "total_post_read_correlated_bits": bits_total,
        "cells_with_supported_eta_comm": sum(
            1 for r in model_rows if r.get("eta_comm_denominator_supported")
        ),
    }


def publish() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_rows()
    if not rows:
        print("No rows found. Run anchor screen and transfer first.")
        return {}

    models = sorted(set(r["model"] for r in rows))
    print(f"Models in data: {models}")
    print(f"Total rows: {len(rows)}")
    print(f"Valid rows: {sum(1 for r in rows if r.get('valid'))}")
    print(f"Invalid rows (preserved in denominators): {sum(1 for r in rows if not r.get('valid'))}")
    print()

    cell_metrics = compute_cell_metrics(rows)
    agg_rows = aggregate_by_model(cell_metrics)

    # model summaries
    summaries = [model_summary(agg_rows, m) for m in models]

    # per-run data (machine-readable, includes invalid-run denominators)
    per_run = []
    for row in rows:
        per_run.append({
            "model": row["model"],
            "family": row["family"],
            "regime_hint": row.get("regime_hint"),
            "complexity": row.get("complexity"),
            "seed": row["seed"],
            "condition": row["condition"],
            "instance_id": row["instance_id"],
            "task_success": row["task_success"],
            "valid": row["valid"],
            "d_idx": row.get("d_idx"),
            "regime_measured": row.get("regime_measured"),
            "post_read_correlated_bits": row.get("post_read_correlated_bits", 0.0),
            "communication_tokens": row.get("communication_tokens", 0),
        })

    report = {
        "schema": "model-comparison-v1",
        "models": models,
        "total_rows": len(rows),
        "valid_rows": sum(1 for r in rows if r.get("valid")),
        "invalid_rows": sum(1 for r in rows if not r.get("valid")),
        "cell_metrics": cell_metrics,
        "aggregate_rows": agg_rows,
        "model_summaries": summaries,
        "per_run_data": per_run,
        "notes": {
            "c_need": "unclipped P(success|FULL) - P(success|ISO); can be negative",
            "eta_comm": f"only computed when |C_need| >= {ETA_COMM_MIN_DENOMINATOR}",
            "invalid_runs": "preserved in denominators; task_success=False for invalid rows",
            "d_idx": "measured feasible-set reduction from instance structure (not model output)",
            "post_read_correlated_bits": "post-read correlated bits from COMM event log (correlation, not causal); 0.0 for ISO/FULL",
        },
    }

    analysis_path = OUT_DIR / "analysis.json"
    per_run_path = OUT_DIR / "per_run_data.json"
    analysis_path.write_text(json.dumps(report, indent=2))
    per_run_path.write_text(json.dumps(per_run, indent=2))

    print("═" * 60)
    for s in summaries:
        if s.get("status") == "no_data":
            continue
        print(f"  {s['model']:15s}  "
              f"FULL={s.get('mean_p_full','?')!r:.3}  "
              f"C_need={s.get('mean_c_need','?')!r:.3}  "
              f"eta_comm={s.get('mean_eta_comm','?')!r}  "
              f"bits={s.get('total_post_read_correlated_bits',0):.1f}")

    print()
    print(f"Analysis:   {analysis_path}")
    print(f"Per-run:    {per_run_path}")

    return report


if __name__ == "__main__":
    publish()
