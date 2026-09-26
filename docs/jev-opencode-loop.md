# Running the Jev Chainlink tasks with OpenCode

The reported failure was project resolution: sessions in `/home/framework` or
the scratch directory could not discover this repository's Chainlink database.
Setting the database alone is insufficient because workers must also edit the
correct checkout. The project launcher binds both cwd and `CHAINLINK_DB`.

Read-only verification, from any directory:

```bash
bash /home/framework/Workspace/apart-incident-response/scripts/jev_chainlink_loop.sh --dry-run
```

Start the scoped worker/reviewer loop when ready:

```bash
bash /home/framework/Workspace/apart-incident-response/scripts/jev_chainlink_loop.sh --run
```

This uses the installed plugin's deterministic CLI, with one explicit task per
invocation. It validates membership in #201, processes #202–#215 in order,
checks blockers, and stops if a task remains open. It never falls back to the
repository-wide queue. The default is dry-run, which starts no model session.
The installation-specific CLI path can be overridden with `JEV_LOOP_CLI`.

The launcher pauses at open gates #206 and #211. Prepare/review those gates
separately and record the explicit stage-specific live authorization required
by their descriptions before closing them. Then invoke the launcher again.
It does not grant authorization, infer it from credentials, or automatically
approve gates. The underlying plugin's `--auto` permission behavior is not
research authorization. Workers/reviewers must enforce the issue acceptance
criteria and the [research plan](jev-discovery-confirmation-plan.md).

Closed predecessor status is an operational check, not proof its scientific
gate passed. On a terminal failure, stop this launcher and follow #215's
terminal-report exception; do not close failed stages as successful or restart
the sequence through their descendants.

The user's OpenCode 2.0.18 report verifies `/chainlink` through the TUI and direct
command API. It also shows that `opencode run "/chainlink"` and a plain session
prompt send literal text rather than dispatching a slash command. This launcher
avoids that client-side routing difference entirely. No global plugin changes,
new Chainlink database, or plugin rebuild is required.
