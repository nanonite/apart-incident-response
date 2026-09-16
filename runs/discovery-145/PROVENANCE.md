# Discovery-145 artifact provenance

The checked-in `anchor_screen/` and `extended_screen/` `runs.jsonl`, `rows.json`,
and `analysis.json` files were produced by the earlier one-turn protocol and
are retained as protocol-debugging artifacts. They are not eligible for the
two-agent entropy or communication analysis.

The corrected runners use two turns and write to `runs.turns2.jsonl`,
`rows.turns2.json`, and `analysis.turns2.json`. The transfer and publisher
scripts read only those corrected row files, so an old one-turn result cannot
silently enter a new comparison.

The checked-in solvability gate, anchor, extended, six-family, and comparison
reports are marked `invalidated` because they were derived from the old
one-turn protocol and the FULL prompt exposed the controller-side joint
candidate labels. They must be rerun after the repaired prompt and
minimum-valid-run gate are in use.

No corrected live screen has been run or included in this checkout. The
corrected artifacts are therefore implementation-ready candidates rather than
new model evidence; the invalidated historical reports remain excluded from
analysis.

## Chainlink reconciliation

Main's `.chainlink/issues.db` is the canonical tracker. Main issue #145 is the
T1a discovery epic, with main issues #146-#150 as its open children. The
discovery worktree independently used IDs #145-#150 for different records;
the overlapping discovery #146-#150 titles were therefore not merged by ID,
and their closed statuses and parent links were not imported. The reconciliation
decision is also recorded in main Chainlink issue #145, while the discovery
branch history remains available in git.
