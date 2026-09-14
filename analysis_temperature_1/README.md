# Temperature-1 analysis on current UUID data

This directory recreates the analysis stages from `origin/analysis-report-01`
using the current two-agent UUID artifact contract. Run it from the repository
root with:

```bash
PYTHONPATH=src python analysis_temperature_1/run_all.py \
  --matrix runs/<model>/<invocation>/matrix.json \
  --output analysis_temperature_1/out/analysis.json
```

The pipeline is source-only and uses Python plus NumPy. It produces a JSON
audit before attempting estimates. A matrix is eligible only when it is an
experimental, complete two-agent C0/C1/C2 matrix, every requested probability
artifact replays, and every selected endpoint has the same response ordinals
for both agents and all three conditions.

The stage mapping is:

| Original stage | Current implementation |
| --- | --- |
| `s00_integrity` | `audit_matrix` and strict `load_matrix` |
| `s01_descriptives` | `outcome_summary`, `turn_profile` |
| `s02_entropy_validation` | `replay_validation`, `robustness_summary` |
| `s03_endpoints` | `endpoint_analysis`, `paired_condition_contrasts` |
| `s04_its` | `interrupted_series` at a declared boundary |
| `s05_event_study` | `event_aligned_profile` at a declared boundary |
| `s06_coupling` | `coupling_proxy` over aligned entropy trajectories |
| `s07_functional_form` | `functional_form_comparison` |
| `s08_detector` | `early_warning_detector` |
| `s09_robustness` | `robustness_summary` and replay gating |

The old endogenous `tau_read`/`tau_use` event study, soft action-class mutual
information, action and prompt-length adjustment, and detector oracle cannot
be reproduced from current probability artifacts because those inputs are not
recorded in the current schema. The replacement functions state this in their
output and keep their results descriptive.
