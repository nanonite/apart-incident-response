"""Run the analysis-report-01 methods against current UUID matrices.

The original scripts consumed private flat CSV exports from a different
base/switch/placebo experiment.  This adapter keeps the analysis stages and
uses the current UUID/C0/C1/C2 artifacts as the source of truth.  It does not
silently turn an incomplete live run into entropy evidence.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from apart_incident_response.controlled_entropy_analysis import (
    AnalysisValidationError,
    audit_matrix,
    call_rows,
    coupling_proxy,
    early_warning_detector,
    endpoint_analysis,
    event_aligned_profile,
    functional_form_comparison,
    independence_baseline,
    interrupted_series,
    load_matrix,
    outcome_summary,
    paired_condition_contrasts,
    replay_validation,
    robustness_summary,
    token_rows,
    turn_profile,
)


def run_analysis(matrix_path: Path | str) -> dict[str, Any]:
    """Return an audit and, when eligible, every current-schema analysis."""

    audit = audit_matrix(matrix_path)
    report: dict[str, Any] = {"audit": audit, "analysis_status": "blocked"}
    try:
        dataset = load_matrix(matrix_path, expected_agent_count=2)
    except AnalysisValidationError as exc:
        report["blocking_error"] = str(exc)
        report["blocking_report"] = exc.report
        return report

    report["analysis_status"] = "complete"
    report["matrix"] = str(dataset.matrix_path)
    report["replay"] = replay_validation(dataset)
    report["tokens"] = token_rows(dataset)
    report["calls"] = call_rows(dataset)
    report["outcomes"] = outcome_summary(dataset)
    report["contrasts"] = paired_condition_contrasts(dataset, turn_start=1, turn_stop=None)
    report["endpoints"] = endpoint_analysis(dataset)
    report["turn_profile"] = turn_profile(dataset)
    report["interrupted_series"] = interrupted_series(dataset)
    report["event_study"] = event_aligned_profile(dataset)
    report["coupling"] = coupling_proxy(dataset)
    report["functional_form"] = functional_form_comparison(dataset)
    report["detector"] = early_warning_detector(dataset)
    report["robustness"] = robustness_summary(dataset)
    report["independence_baseline"] = independence_baseline(dataset)
    return report


def write_report(matrix_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    report = run_analysis(matrix_path)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(report), indent=2, allow_nan=False, default=_json_default), encoding="utf-8")
    return report


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
