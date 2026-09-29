# Legal:low sequential research chain

Parent: Chainlink #218 under #159. The hypothesis:low terminal decision is
[P14/#215](jev-hypothesis-low-terminal-decision.md). This chain starts the
next family in the outcome-blind order frozen by P02. The [research protocol]
(jev-discovery-confirmation-plan.md) supplies the scientific contract. Task
creation and a registration lock authorize no provider call.

| Order | Issue | Deliverable | Release condition |
| --- | --- | --- | --- |
| L01 | #219 | Pinned baseline and offline diagnosis of P06 `truncated_output` | #215 closed |
| L02 | #220 | Reproducible legal form census, independence and fresh-window audit | #219 completed |
| L03 | #221 | Attainability, classification and outcome-blind discovery design | #220 completed |
| L04 | #222 | Fresh legal discovery registration or explicit no-go | #221 completed |
| L05 | #223 | Legal runner and fail-closed preflight, tested offline | #222 completed with runnable registration |
| L06 | #224 | Independent registration/runner review and hash lock | #223 completed |
| L07 | #225 | Separate, scope-bound **user** live authorization | #224 approved; loop stops here |
| L08 | #226 | Exactly one registered live discovery block | #225 explicitly authorized |

Chainlink `blocked_by` edges are #219←#215, then each task ← its immediate
predecessor. #218 is the parent, not a worker task. The installed OpenCode loop
must be called with one explicit issue ID at a time; never use its unscoped
queue fallback for this family. `scripts/jev_legal_chainlink_loop.sh` enforces
the IDs and halts before #225. It also halts if #222 yields a no-go instead of
a runnable registration. The loop uses MiMo Flash by default for worker and
reviewer sessions; `JEV_LEGAL_WORKER_MODEL` and
`JEV_LEGAL_REVIEWER_MODEL` allow an explicit alternate model. Do not dispatch
Space Bunny.

The source and output hashes in L01 must be recomputed rather than accepted
from issue text. L02 must not reuse the hypothesis 85000–87511 seed windows.
Legal form count, independence and closure are findings, not assumptions from
the old family audit. If `k < 6`, the exact two-sided sign-flip floor exceeds
0.05; adjusted multiplicity can demand more forms. Distinct seeds do not add
form units. Planning-low and hypothesis-low outcomes supply no legal-family
effect-size prior.

L04 must preserve the original L4X treatment unless it registers and reviews
a new treatment as a different design. Any changed token budget, route, model,
cost rate, request cap, or stop rule is a new registration field. In particular,
the paid OpenRouter Ling route pinned by the stopped hypothesis run does not
carry authorization into this family. OpenCode Go has no interchangeable Ling
route in the current registration. L07 must cover exact stage, route, retry-
inclusive physical request caps and dollar caps. No credentials, issue
closure, lock, old authorization or worker prompt imply that reference.

Any terminal L08 stop retains the whole fixed manifest as an immutable
journal, including failure and not-attempted rows. It routes to a terminal
family report; it does not release discovery estimates, replay work, or a
second live attempt. Future replay tasks should be specified only after valid
discovery evidence or an explicit terminal decision, using fresh registration,
paths and a separate authorization gate.
