# Local reproduction status

The current local matrix was checked with `analysis_temperature_1/run_all.py`
on 2026-09-13:

```text
runs/openrouter/ling-3.0-flash-vl-free-2agent/
model: openrouter/inclusionai/ling-3.0-flash-vl:free
triplets: 6 (18 condition artifacts)
analysis_status: blocked
```

The matrix is marked `experimental_data=false`. Its condition results are
`budget_exhausted` or `failed`, and every probability artifact has zero
complete token turns and only unavailable turns. The pipeline therefore emits
the audit and refuses endpoint, event, coupling, detector, or robustness
estimates. This is the expected result for this pilot and avoids treating an
incomplete free-model run as entropy evidence.

After a complete two-agent C0/C1/C2 run is available, rerun the same command;
the JSON output will include the full stage set described in `README.md`.
