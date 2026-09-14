# Controlled C0/C1/C2 entropy analysis

The statistical-analysis branch was built for a separate `base/switch/placebo`
experiment with flat CSV tables. The reusable parts are now implemented for the
current UUID artifacts in
[`controlled_entropy_analysis.py`](../src/apart_incident_response/controlled_entropy_analysis.py)
and exposed through the Marimo notebook
[`controlled_entropy_analysis.py`](../notebooks/controlled_entropy_analysis.py).

The input is one `matrix.json` produced by the current controller. The loader
requires `run_class=experimental`, `experimental_data=true`, and a complete
matched set of C0, C1, and C2 condition links for every retained seed. Every
condition must have exactly two assigned agent directories, two completed raw
agent results, and two complete `agent-turn-probability-v1` artifacts. It also
checks that the seed, UUID, model, task, and agent assignment agree across the
triplet. A partially executed or three-agent matrix raises
`AnalysisValidationError`; it may remain stored as a diagnostic artifact but
cannot enter the metric.

The ported estimators are:

- per-token partial entropy, sampled surprise, coverage, and per-response
  summaries from the shared `partial-token-probability-v1` artifact;
- replay checks that recompute every stored partial entropy value;
- per-turn trajectories with seed-bootstrap intervals;
- matched seed-level C1-C0, C2-C0, and primary C1-C2 contrasts;
- percentile bootstrap intervals, exact sign tests, paired signed-rank tests,
  and Benjamini-Hochberg adjustment implemented with NumPy and the standard
  library; and
- controller outcome summaries kept separate from entropy, including task
  success, message delivery, uptake, tokens, and turns.

The probability measure is the Shannon entropy of the returned top-K mass after
normalization. It is a bounded provider measurement and cannot be reported as
full-vocabulary entropy. The two-agent panel also shows the additive
`H(agent-1) + H(agent-2)` independence baseline. Current artifacts do not
contain simultaneous joint token samples or action-class probability vectors,
so true joint entropy, mutual information, total correlation, and the branch's
soft action-coupling estimator are not calculated. The old fixed event-time ITS
and donor-placebo event study also do not transfer: C0/C1/C2 has no endogenous
switch time or donor run. The notebook presents these limits in the output.

Run the notebook after a live or imported matrix has been written:

```bash
APART_MATRIX_PATH=runs/openrouter/<model>/<uuid>/matrix.json \
  uv run marimo edit notebooks/controlled_entropy_analysis.py
```

Without `APART_MATRIX_PATH`, the notebook discovers `runs/**/matrix.json` and
offers only matrices that pass the strict two-agent experimental gate. It does
not import generated figures, CSV tables, or the branch's experiment data.
