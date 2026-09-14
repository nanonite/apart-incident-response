"""Marimo view for the current UUID-based two-agent C0/C1/C2 experiment."""

import marimo

__generated_with = "0.24.0"
app = marimo.App(width="full")


@app.cell
def _():
    import os
    import sys
    from pathlib import Path

    import marimo as mo
    import numpy as np

    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))
    from apart_incident_response.controlled_entropy_analysis import (
        AnalysisValidationError,
        audit_matrix,
        call_rows,
        coupling_proxy,
        discover_matrices,
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

    runs_root = Path(os.environ.get("APART_RUNS_ROOT", repo_root / "runs"))
    requested_matrix = os.environ.get("APART_MATRIX_PATH")
    return (
        AnalysisValidationError,
        Path,
        audit_matrix,
        call_rows,
        coupling_proxy,
        discover_matrices,
        early_warning_detector,
        endpoint_analysis,
        event_aligned_profile,
        functional_form_comparison,
        independence_baseline,
        interrupted_series,
        load_matrix,
        mo,
        np,
        outcome_summary,
        paired_condition_contrasts,
        replay_validation,
        repo_root,
        requested_matrix,
        robustness_summary,
        runs_root,
        token_rows,
        turn_profile,
    )


@app.cell
def _(AnalysisValidationError, audit_matrix, discover_matrices, load_matrix, mo, requested_matrix, runs_root):
    candidates = {}
    rejected = []
    audits = []
    paths = [requested_matrix] if requested_matrix else discover_matrices(runs_root)
    for raw_path in paths:
        path = raw_path if hasattr(raw_path, "read_text") else str(raw_path)
        try:
            audits.append(audit_matrix(path))
        except AnalysisValidationError as exc:
            rejected.append({"matrix": str(path), "reason": str(exc)})
        try:
            _candidate = load_matrix(path, expected_agent_count=2)
        except AnalysisValidationError as exc:
            rejected.append({"matrix": str(path), "reason": str(exc)})
            continue
        candidates[str(_candidate.matrix_path)] = _candidate

    if not candidates:
        mo.stop(
            True,
            mo.vstack([
                mo.callout(
                    mo.md(
                        "No complete experimental two-agent matrix was found. "
                        "Set `APART_MATRIX_PATH` to a matrix JSON after the live run. "
                        f"Rejected candidates: {len(rejected)}."
                    ),
                    kind="warn",
                ),
                mo.md("### Local matrix audit"),
                mo.table([
                    {
                        "matrix": item["matrix"],
                        "experimental_data": item.get("experimental_data"),
                        "triplets": item.get("triplets"),
                        "entropy_ready": item.get("entropy_ready"),
                        "reasons": "; ".join(item.get("reasons", [])[:3]),
                    }
                    for item in audits
                ]),
            ]),
        )
    return audits, candidates, rejected


@app.cell
def _(candidates, mo):
    matrix_choice = mo.ui.dropdown(
        options=list(candidates),
        value=list(candidates)[0],
        label="Validated matrix",
    )
    mo.vstack([
        mo.md("## Matrix selection\nOnly matrices passing the two-agent C0/C1/C2 gate appear here."),
        matrix_choice,
    ])
    return (matrix_choice,)


@app.cell
def _(call_rows, candidates, matrix_choice, token_rows):
    dataset = candidates[matrix_choice.value]
    calls = call_rows(dataset)
    tokens = token_rows(dataset)
    max_turn = max((int(row["turn"]) for row in calls), default=1)
    return calls, dataset, max_turn, tokens


@app.cell
def _(mo, np, tokens):
    _summary = []
    for _condition in ("C0", "C1", "C2"):
        _values = [row for row in tokens if row["condition"] == _condition]
        _finite_entropy = [row["partial_entropy_bits"] for row in _values if np.isfinite(row["partial_entropy_bits"])]
        _finite_coverage = [row["covered_mass"] for row in _values if np.isfinite(row["covered_mass"])]
        _summary.append({
            "condition": _condition,
            "tokens": len(_values),
            "mean_partial_entropy_bits": float(np.mean(_finite_entropy)) if _finite_entropy else np.nan,
            "mean_top_k_entropy_bits": float(np.mean([row["top_k_entropy_bits"] for row in _values if np.isfinite(row["top_k_entropy_bits"])])) if _values else np.nan,
            "mean_coverage": float(np.mean(_finite_coverage)) if _finite_coverage else np.nan,
            "coverage_below_0_99": float(np.mean(np.asarray(_finite_coverage) < 0.99)) if _finite_coverage else np.nan,
        })
    mo.vstack([
        mo.md("## Token-level analysis\nEach row is one recorded token. Partial entropy is the provider top-K measure; coverage is the returned probability mass."),
        mo.table(_summary),
        mo.table(tokens[:100]),
    ])
    return


@app.cell
def _(mo, np, tokens):
    import matplotlib.pyplot as _plt

    _entropy = np.asarray([row["partial_entropy_bits"] for row in tokens], dtype=float)
    _coverage = np.asarray([row["covered_mass"] for row in tokens], dtype=float)
    _figure, _axes = _plt.subplots(1, 2, figsize=(10, 3.5))
    _axes[0].hist(_entropy[np.isfinite(_entropy)], bins=30, color="#4c78a8", alpha=0.85)
    _axes[0].set(title="Token partial entropy", xlabel="bits", ylabel="tokens")
    _axes[1].hist(_coverage[np.isfinite(_coverage)], bins=30, color="#54a24b", alpha=0.85)
    _axes[1].set(title="Returned probability coverage", xlabel="mass", ylabel="tokens")
    _figure.tight_layout()
    mo.vstack([mo.md("### Token distributions"), _figure])
    return


@app.cell
def _(dataset, mo, rejected):
    mo.md(
        f"""
        # Controlled entropy analysis

        **Model:** `{dataset.model}`<br>
        **Invocation UUID:** `{dataset.run_uuid}`<br>
        **Matched seeds:** `{", ".join(map(str, dataset.seeds))}`<br>
        **Triplets:** `{len(dataset.triplets)}` (each has C0, C1, and C2)<br>
        **Rejected discovery candidates:** `{len(rejected)}`

        C0 has no board channel, C1 exposes shared board history, and C2 exposes
        only each agent's own writes. The primary comparison is the matched
        **C1 − C2** contrast; C0 is the board-absent baseline. Seeds are the
        independent units for confidence intervals and paired tests.

        The token measure is provider-reported top-K **partial entropy** after
        normalizing the returned mass. It is not full-vocabulary entropy.
        """
    )
    return


@app.cell
def _(calls, max_turn, mo):
    turn_start = mo.ui.slider(
        start=1,
        stop=max_turn,
        value=1,
        step=1,
        label="First turn included in the selected window",
    )
    turn_stop = mo.ui.slider(
        start=1,
        stop=max_turn,
        value=max_turn,
        step=1,
        label="Last turn included in the selected window",
    )
    mo.vstack([
        mo.md("## Analysis window\nUse a full run for the primary endpoint or a late window for a descriptive trajectory check."),
        turn_start,
        turn_stop,
    ])
    return turn_start, turn_stop


@app.cell
def _(dataset, paired_condition_contrasts, turn_start, turn_stop):
    if turn_start.value <= turn_stop.value:
        contrasts = paired_condition_contrasts(
            dataset,
            turn_start=turn_start.value,
            turn_stop=turn_stop.value,
        )
    else:
        contrasts = []
    return (contrasts,)


@app.cell
def _(contrasts, mo):
    columns = [
        "contrast", "n_seeds", "estimate", "ci_low", "ci_high", "median",
        "n_positive", "p_sign", "p_wilcoxon", "p_wilcoxon_bh",
    ]
    _rows = [{key: row.get(key) for key in columns} for row in contrasts]
    mo.vstack([
        mo.md("## Matched condition contrasts\nBootstrap intervals and paired tests are descriptive with the available seed count."),
        mo.table(_rows),
    ])
    return


@app.cell
def _(dataset, endpoint_analysis, event_aligned_profile, interrupted_series):
    endpoints = endpoint_analysis(dataset)
    interrupted = interrupted_series(dataset)
    event_study = event_aligned_profile(dataset)
    return endpoints, event_study, interrupted


@app.cell
def _(endpoints, event_study, interrupted, mo):
    endpoint_columns = [
        "endpoint", "window", "contrast", "n_seeds", "estimate", "ci_low",
        "ci_high", "p_wilcoxon", "p_wilcoxon_bh", "excluded_seeds",
    ]
    mo.vstack([
        mo.md(
            "## Ported endpoint, interrupted-series, and event-study stages\n"
            "Endpoints use balanced raw entropy. The interrupted-series and event-study views use the declared turn boundary; current artifacts do not record an endogenous uptake event."
        ),
        mo.table([{key: row.get(key) for key in endpoint_columns} for row in endpoints]),
        mo.table(interrupted),
        mo.table(event_study),
    ])
    return


@app.cell
def _(dataset, turn_profile):
    profile = turn_profile(dataset)
    return (profile,)


@app.cell
def _(mo, np, profile):
    import matplotlib.pyplot as _plt

    _figure, _axis = _plt.subplots(figsize=(10, 4))
    _colours = {"C0": "#4c78a8", "C1": "#f58518", "C2": "#54a24b"}
    for _condition in ("C0", "C1", "C2"):
        _values = [row for row in profile if row["condition"] == _condition]
        if not _values:
            continue
        _x = np.asarray([row["turn"] for row in _values])
        _y = np.asarray([row["mean"] for row in _values])
        _low = np.asarray([row["ci_low"] for row in _values])
        _high = np.asarray([row["ci_high"] for row in _values])
        _axis.fill_between(_x, _low, _high, color=_colours[_condition], alpha=0.16)
        _axis.plot(_x, _y, marker="o", ms=3, color=_colours[_condition], label=_condition)
    _axis.set(
        title="Per-turn mean top-K partial entropy",
        xlabel="Measured assistant response ordinal",
        ylabel="Mean entropy (bits/token)",
    )
    _axis.grid(alpha=0.25)
    _axis.legend(title="Condition")
    _figure.tight_layout()
    mo.vstack([mo.md("## Entropy trajectory"), _figure])
    return


@app.cell
def _(dataset, independence_baseline, mo):
    _rows = independence_baseline(dataset)
    mo.vstack([
        mo.md(
            "## Two-agent independence baseline\n"
            "This is H(agent 1) + H(agent 2) for aligned responses. The current "
            "artifacts do not contain simultaneous joint token samples, so true "
            "joint entropy, mutual information, and total correlation are not estimated."
        ),
        mo.table(_rows),
    ])
    return


@app.cell
def _(coupling_proxy, dataset, early_warning_detector, functional_form_comparison, robustness_summary):
    coupling = coupling_proxy(dataset)
    detector = early_warning_detector(dataset)
    functional_form = functional_form_comparison(dataset)
    robustness = robustness_summary(dataset)
    return coupling, detector, functional_form, robustness


@app.cell
def _(coupling, detector, functional_form, mo, robustness):
    mo.vstack([
        mo.md(
            "## Coupling, functional form, detector, and robustness\n"
            "Coupling is the available aligned entropy trajectory proxy. The old action-class mutual information requires action-token distributions that are absent from this schema."
        ),
        mo.md("### Agent coupling proxy"),
        mo.table(coupling),
        mo.md("### Functional forms"),
        mo.table(functional_form),
        mo.md("### Fixed-boundary detector"),
        mo.table(detector),
        mo.md("### Entropy robustness"),
        mo.table(robustness),
    ])
    return


@app.cell
def _(dataset, mo, outcome_summary, replay_validation):
    outcomes = outcome_summary(dataset)
    replay = replay_validation(dataset)
    mo.vstack([
        mo.md("## Execution outcomes"),
        mo.table(outcomes),
        mo.md("## Entropy replay validation"),
        mo.table(replay),
    ])
    return


@app.cell
def _(calls, dataset, mo, repo_root):
    token_count = sum(int(row["token_count"]) for row in calls)
    mo.md(
        f"""
        ---
        **Source:** `{dataset.matrix_path}`<br>
        **Call observations:** `{len(calls)}`  · **Tokens:** `{token_count}`<br>
        **Notebook:** `{repo_root / "notebooks/controlled_entropy_analysis.py"}`

        The imported analysis keeps failed or incomplete matrices out of the
        estimand, gates entropy estimates on replay, and drops seeds whose
        requested window is not balanced across both agents and all conditions.
        The former branch's endogenous uptake event, action-class joint
        estimator, and action/prompt-length covariate adjustment require
        variables absent from this C0/C1/C2 schema; the notebook labels their
        current descriptive replacements accordingly.
        """
    )
    return


if __name__ == "__main__":
    app.run()
