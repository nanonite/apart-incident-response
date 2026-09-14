# Controlled C0/C1/C2 entropy analysis

The statistical-analysis branch was built for a separate `base/switch/placebo`
experiment with flat CSV tables. Its reusable stages are now recreated for the
current UUID artifacts in
[`controlled_entropy_analysis.py`](../src/apart_incident_response/controlled_entropy_analysis.py)
and exposed through the Marimo notebook
[`controlled_entropy_analysis.py`](../notebooks/controlled_entropy_analysis.py).
A command-line runner is in
[`analysis_temperature_1/`](../analysis_temperature_1/), so the same analysis
can be regenerated without opening Marimo.

The input is one `matrix.json` produced by the current controller. The loader
requires `run_class=experimental`, `experimental_data=true`, and a complete
matched set of C0, C1, and C2 condition links for every retained seed. Every
condition must have exactly two assigned agent directories, two completed raw
agent results, and two complete `agent-turn-probability-v1` artifacts. It also
checks that the seed, UUID, model, task, and agent assignment agree across the
triplet. A partially executed or three-agent matrix raises
`AnalysisValidationError`; it may remain stored as a diagnostic artifact but
cannot enter the metric.

The ported analysis stages are:

- per-token partial entropy, sampled surprise, coverage, and per-response
  summaries from the shared `partial-token-probability-v1` artifact;
- replay checks that recompute every stored partial entropy value;
- per-turn trajectories and token distributions with seed-bootstrap intervals;
- matched seed-level C1-C0, C2-C0, and primary C1-C2 contrasts;
- post-window and pre/post endpoint tables;
- descriptive interrupted-series and declared-boundary event-study views;
- an aligned entropy trajectory coupling proxy;
- NumPy-only constant, linear, logarithmic, and cubic functional-form checks;
- a fixed-boundary z-score detector; and
- token-level robustness summaries for partial, top-K, residual-bucket entropy,
  and coverage;
- percentile bootstrap intervals, exact sign tests, paired signed-rank tests,
  and Benjamini-Hochberg adjustment implemented with NumPy and the standard
  library; and
- controller outcome summaries kept separate from entropy, including task
  success, message delivery, uptake, tokens, and turns.

The probability measure is the Shannon entropy of the returned top-K mass after
normalization. It is a bounded provider measurement and cannot be reported as
full-vocabulary entropy. Replay validation is a hard inclusion gate. Endpoint
estimates also require both agents and every requested response ordinal in all
three conditions; shorter or otherwise unbalanced seeds are reported as
excluded. The two-agent panel shows the additive
`H(agent-1) + H(agent-2)` independence baseline.

Current artifacts do not contain simultaneous joint token samples, action-class
probability vectors, action/prompt-length covariates, or endogenous uptake
timestamps. Therefore true joint entropy, mutual information, the old
action-coupling estimator, covariate-adjusted endpoints, and the old
`tau_read`/`tau_use` event study cannot be reproduced. The replacement
interrupted-series, event-aligned, coupling, and detector views are explicitly
descriptive and identify their fixed analysis boundary in their output.

Run the notebook after a live or imported matrix has been written:

```bash
APART_MATRIX_PATH=runs/openrouter/<model>/<uuid>/matrix.json \
  uv run marimo edit notebooks/controlled_entropy_analysis.py
```

Or write the complete local JSON report:

```bash
PYTHONPATH=src python analysis_temperature_1/run_all.py \
  --matrix runs/openrouter/<model>/<uuid>/matrix.json \
  --output analysis_temperature_1/out/analysis.json
```

Without `APART_MATRIX_PATH`, the notebook discovers `runs/**/matrix.json` and
offers only matrices that pass the strict two-agent experimental gate. It does
not import generated figures, CSV tables, or the branch's experiment data. The
command-line runner audits rejected matrices and returns exit status 2 until a
complete, replay-valid matrix is available.
