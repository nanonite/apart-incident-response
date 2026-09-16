# Discovery-145 artifact provenance

The checked-in `anchor_screen/` and `extended_screen/` `runs.jsonl`, `rows.json`,
and `analysis.json` files were produced by the earlier one-turn protocol and
are retained as protocol-debugging artifacts. They are not eligible for the
two-agent entropy or communication analysis.

The corrected runners use two turns and write to `runs.turns2.jsonl`,
`rows.turns2.json`, and `analysis.turns2.json`. The transfer and publisher
scripts read only those corrected row files, so an old one-turn result cannot
silently enter a new comparison.

The checked-in solvability gate report is marked `invalidated` because its
FULL prompt exposed the controller-side joint candidate labels. It must be
rerun after the repaired prompt and minimum-valid-run gate are in use.
