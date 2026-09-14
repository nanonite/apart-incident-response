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
        call_rows,
        discover_matrices,
        independence_baseline,
        load_matrix,
        outcome_summary,
        paired_condition_contrasts,
        replay_validation,
        turn_profile,
    )

    runs_root = Path(os.environ.get("APART_RUNS_ROOT", repo_root / "runs"))
    requested_matrix = os.environ.get("APART_MATRIX_PATH")
    return (
        AnalysisValidationError,
        Path,
        call_rows,
        discover_matrices,
        independence_baseline,
        load_matrix,
        mo,
        np,
        outcome_summary,
        paired_condition_contrasts,
        replay_validation,
        repo_root,
        requested_matrix,
        runs_root,
        turn_profile,
    )


@app.cell
def _(AnalysisValidationError, discover_matrices, load_matrix, mo, requested_matrix, runs_root):
    candidates = {}
    rejected = []
    paths = [requested_matrix] if requested_matrix else discover_matrices(runs_root)
    for raw_path in paths:
        path = raw_path if hasattr(raw_path, "read_text") else str(raw_path)
        try:
            _candidate = load_matrix(path, expected_agent_count=2)
        except AnalysisValidationError as exc:
            rejected.append({"matrix": str(path), "reason": str(exc)})
            continue
        candidates[str(_candidate.matrix_path)] = _candidate

    if not candidates:
        mo.stop(
            True,
            mo.callout(
                mo.md(
                    "No complete experimental two-agent matrix was found. "
                    "Set `APART_MATRIX_PATH` to a matrix JSON after the live run. "
                    f"Rejected candidates: {len(rejected)}."
                ),
                kind="warn",
            ),
        )
    return candidates, rejected


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
def _(call_rows, candidates, matrix_choice):
    dataset = candidates[matrix_choice.value]
    calls = call_rows(dataset)
    max_turn = max((int(row["turn"]) for row in calls), default=1)
    return calls, dataset, max_turn


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
def _(dataset, turn_profile):
    profile = turn_profile(dataset)
    return (profile,)


@app.cell
def _(mo, np, profile):
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(10, 4))
    colours = {"C0": "#4c78a8", "C1": "#f58518", "C2": "#54a24b"}
    for condition in ("C0", "C1", "C2"):
        values = [row for row in profile if row["condition"] == condition]
        if not values:
            continue
        x = np.asarray([row["turn"] for row in values])
        y = np.asarray([row["mean"] for row in values])
        low = np.asarray([row["ci_low"] for row in values])
        high = np.asarray([row["ci_high"] for row in values])
        axis.fill_between(x, low, high, color=colours[condition], alpha=0.16)
        axis.plot(x, y, marker="o", ms=3, color=colours[condition], label=condition)
    axis.set(
        title="Per-turn mean top-K partial entropy",
        xlabel="Measured assistant response ordinal",
        ylabel="Mean entropy (bits/token)",
    )
    axis.grid(alpha=0.25)
    axis.legend(title="Condition")
    figure.tight_layout()
    mo.vstack([mo.md("## Entropy trajectory"), figure])
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
        estimand and does not impute missing token probabilities. The old
        analysis branch's fixed event time, placebo donor, and soft action-class
        joint estimators require variables absent from this C0/C1/C2 schema.
        """
    )
    return


if __name__ == "__main__":
    app.run()
