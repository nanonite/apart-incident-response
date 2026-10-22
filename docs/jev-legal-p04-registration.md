# L04 — Fresh legal discovery registration (draft pending review)

Task: Chainlink **#222** under **#218** under **#159**. Family `legal:low`,
milestone **L04**, predecessor **#221** (L03, the design decision), successor
**#223** (L05), with the approved offline cross-family audit **#227**
consumed immediately before this task (`#221 → #227 → #222`). Protocol:
[hypotheses and sequential discovery/confirmation plan](jev-discovery-confirmation-plan.md);
family chain: [legal sequential research chain](jev-legal-task-sequence.md);
program direction: [cross-family entropy program v1 amendment](jev-cross-family-entropy-program-v1.md).

Offline registration build only — **no provider call**, no probe, no live
journal and no network event of any kind; a process-wide audit hook observed
**zero network events** while the artifact was assembled. L03 classified
`legal:low` at k = 4 as **descriptive discovery** (no-go is off the table), so
this task freezes a runnable registration — and registers only: status stays
`draft_pending_review`, authorization stays **pending**, and only the
separate, scope-bound L07 gate (**#225**) can later supply the explicit user
authorization. Nothing here closes **#222** by itself, and nothing here opens
or advances **#223**.

Machine-readable artifact:
[`runs/next-phase/legal/jev-legal-p04-discovery-registration-v1.json`](../runs/next-phase/legal/jev-legal-p04-discovery-registration-v1.json)
(registered version
`jev-legal-p04-discovery-registration-v1`, self-recorded `registration_hash`
`5f31630bae7fe414f054f78e1c4bb5ebf3b525d083cd3f91b81e1f89b427bde1`), rebuilt byte-for-byte by
`python -m apart_incident_response.jev_legal_p04_registration --repo-root .`
(fail closed on drift; creation is `open("x")` and never overwrites).

## 1. Input evidence (recomputed from disk on every build)

Every digest below was recomputed from the bytes on disk and pinned in full;
a mismatch on any single byte fails the build closed. The final two rows are
**non-reuse controls**: the stopped hypothesis:low registration and its
authorization record are pinned byte-for-byte, and no seed window, manifest,
route, authorization or outcome carries forward from them into any field of
this registration.

| Input | Role | sha256 (recomputed) |
| --- | --- | --- |
| `docs/jev-discovery-confirmation-plan.md` | research protocol (pin `501e21b6`) | `501e21b6dea760371b0bf368046d8bacd203f6b92f0af754a7955d1f738677f7` |
| `docs/jev-legal-task-sequence.md` | legal family task sequence (#218) (pin `884b0ed4`) | `884b0ed4329cc47888e797478f8f00b57f7f5c9d679998d154f5a789397d0394` |
| `docs/jev-cross-family-entropy-program-v1.md` | cross-family program amendment (2026-09-29) | `d9acace24a0cdbfc9a41e331b1fd422f07f22e3fc01480e6408af78d9de4be05` |
| `runs/epic-126/replication/jev-replication-form-audit-v1.json` | #200 frozen form-capacity audit (pin `cb529cd6`) | `cb529cd61e0e662bfa19fc4998e89fa59a0bf0d63e14f77498035466d6bce89d` |
| `runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection.jsonl` | #207 terminal P06 discovery journal (pin `4e8de096`) | `4e8de096f2c30a6a36a94a0f79e5f450c2e196123e3eafe1c310a92c4f334c83` |
| `runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection-report.json` | #207 terminal P06 collection report (pin `3086ceac`) | `3086ceac558ff922bd083db3795f5f1aa5c7127813daba8bfd71ae1fbef09d3c` |
| `docs/jev-hypothesis-low-terminal-decision.md` | #215 terminal family report (pin `89ef2aaf`) | `89ef2aafb5e28f12d0db707499c583d89cdcc490d105c23c3c56b39e11818d0b` |
| `runs/next-phase/legal/jev-legal-p01-evidence-v1.json` | L01 evidence index (#219, pin `b2d07266`) | `b2d0726619f5a18ce1ed5a54c5197d51709b1e0473b58ee129c74592b7b707e3` |
| `docs/jev-legal-p01-baseline.md` | L01 baseline narrative (#219, pin `8926f48d`) | `8926f48d85338163fae0f9434f63c62b380f6402580bb57cd1d35b25d0471870` |
| `runs/next-phase/legal/jev-legal-p02-form-census-v1.json` | L02 form census (#220, pin `4bffa5cd`) | `4bffa5cda2433a81efb41025f42fdd82c585c41798ff2c55e9d853aa45681d24` |
| `docs/jev-legal-p02-capacity.md` | L02 capacity narrative (#220, pin `25fac868`) | `25fac868d502b05ede479fa7e68161f8f4fd4db33267a0f01d710f2d0adec2fa` |
| `runs/next-phase/legal/jev-legal-p03-design-v1.json` | L03 design decision (#221, predecessor handoff, pin `688bc787`) | `688bc7875ff7b81bb70d60076e137b0274559b484d597f6f643ae2fb48c827ab` |
| `docs/jev-legal-p03-design.md` | L03 design narrative (#221, pin `24bd6d7e`) | `24bd6d7e8cec205bf5b5cee96f98f09afad17c85a1e825c012b536e3a2716f79` |
| `research/jev/cross-family/jev-cross-family-capacity-v1.json` | #227 approved cross-family capacity audit (machine-readable, pin `13c52676`) | `13c526761c1f10e71382a5c5d142e47585539bad66238d3a6bfd49646b17271e` |
| `docs/jev-cross-family-capacity-audit-v1.md` | #227 audit narrative (pin `ca8a3fef`) | `ca8a3fefac6221b862245ed2a8bac9b43b5411dc9447e00016375192ca16c75f` |
| `runs/next-phase/jev-p04-discovery-registration-v1.json` | stopped hypothesis:low registration — **non-reuse control, never inherited** (pin `78f7cd03`) | `78f7cd03c3afc12c94c3ba09839e4ac6ba667a3f68b96871571b274ae7d3ab11` |
| `runs/next-phase/jev-discovery-authorization-record-v1.json` | stopped hypothesis:low authorization record — **non-reuse control, never inherited** (pin `77962311`) | `77962311dc723b7bf0eab0bda042078ec5d8a903120dd37b023c7b93d2e6d8eb` |

The predecessor artifacts carry their own self-recorded content hashes, all of
which recompute from their bytes at build time: the L02 census
`b01aa7de17cb21d18b7dd83a12764da7ff265a18b7089f2c2be7eaaf6b72b775`, the L03
design `adf52cb7b7d62e532acc0b8f26c000582e4a291767f737558f016fdf9eafed06`, the
#227 audit `e71252a607f35cde67dbaf5e66f3abbc8d57c3064cbb88d79a90ff0e31175684`,
the stopped hypothesis registration
`6fa6149770b620cd3a026a6415f8e4d97e800e8af5237794de7b29fca6dacfac` and the
stopped authorization record scope digest
`938da9116805967253417c53709cd85d56d1913ac0142032d0d4732f50c04061`. Every
digest recorded by L03's own `input_evidence` re-digests from disk, so the
frozen #200 and terminal #207/#215 files are byte-identical across
L01 → L02 → L03 → L04. Generator and hashing sources are pinned the same way
(10 modules, all re-hashed before and after the build, including this chain's
L03 module, the #227 audit module and the stopped hypothesis classifier).

## 2. What the registration freezes

**Design classification (carried from L03, never re-decided).** L03's
`descriptive_discovery` decision at k = 4 is cited, not re-derived: the exact
two-sided cluster sign-flip floor is 2/2^4 = 2/16 = 1/8 = 0.125, strictly
above alpha = 0.05, so no dichotomous rejection is attainable at any effect
size on this closed four-form version. The registered family hypothesis set
is exactly `[legal:low]`; audit #227's 7-8-family Holm arithmetic is carried
as prospective program context only and cannot promote legal:low toward a
confirmatory design.

**Fixed-N discovery manifest.** The registered manifest is exactly the L03
screen (self-recorded manifest hash
`1eeda0eacc2d891e8117e2816c7a7bf2c65c3962c8e1fa102acdc4766deefb26`):
first **4 seeds per form in ascending seed order** inside the L02 discovery
window **88000-88511**, k = 4 forms, **fixed N = 16**, outcome-blind with an
empty `consulted_outcomes` list. The closure-probe window 89000-89511 is
never selectable, the reserved hypothesis spans 85000-85511, 86000-86511 and
87000-87511 stay untouched, and **no held-out or confirmation window is
registered by this task**.

**L4X treatment bytes and the writer output policy.** The original
communication-bridge treatment is registered unchanged: mode
`exact-original-comm-bridge` at rung **L4X**, 2 turns, agents A and B,
one-way B→A primary direction with A as final receiver via the Jev Choice
wire v2, peer-only board visibility with exact `instance.holds_claim`
ownership, and the writer prompt binding (grammar `ANSWER: <label> + optional
MESSAGE: <claim>…`, temperature 0.0, sha256-truncated-signed31 seed
algorithm). The registered `max_tokens` is **1024**, explicitly justified on
L01's own terms: L01 (#219) diagnosed the stopped hypothesis:low stop as an
HTTP-200 writer output-cap classification (`http_200_writer_output_cap`,
non-empty content with `finish_reason: length` at the registered 1024-token
budget, which was the binding constraint of that call), with exactly one
attempted seed (from 16 planned) and no counterfactual — so 1024 is kept not
as evidence-based repair but because the task sequence preserves the original
treatment. `truncated_output` is retained as a registered terminal writer
error: stop before the next call, no automatic continuation, no automatic
budget escalation, no mid-run repair, and truncated content is never parsed
into an event. Any future budget repair is a new registration version with
fresh paths, its own review and its own L07 authorization.

**Route (registered for the first time, independently chosen and costed).**
The writer is the paid OpenRouter Ling SKU (`prv7.PAID_LING_MODEL`, the free
SKU is not routable) at `pr.LING_ENDPOINT` with the `_api_key` loader,
temperature 0.0 and max_tokens 1024; the receiver is the Typesafe Jev replay
model at `pr.JEV_REPLAY_ENDPOINT` with the Jev Choice v2 codec, the frozen
protocol key and the registered normalization policy (tiers
`exact` / `complete_renormalized`, hard ceiling 0.05, argmax-after-normalize)
recomputed from its module. The legal family has no prior registered or
authorized route (L01 pins `registered: false`, `authorized: false`), nothing
is imported or extended from the stopped hypothesis-family registration, and
OpenCode Zen/Go are not substituted for the registered experimental routes.

**Budgets, request caps and hard ceilings.** The cost arithmetic recomputes
from the chain's frozen rate card (L03 planning precedent, re-derived here:
Ling and Jev ceilings × per-Mtok rates), and the L03-selected scenario
(16 seeds/form, `selected_fixed_n = 16`) carries verbatim: collection
planned **80 logical calls** (64 Ling + 16 Jev) × retry multiplier 3 =
**240 physical**, worst case **$0.146276352** under the registered
**$0.20** hard ceiling; optional exploratory replay **≤16 events × 3 Jev
branches = 48 logical / 144 physical**, worst case **$0.049545216** under
**$0.10**; program worst case **$0.195821568 = 0.146276352 + 0.049545216**
under the registered **$0.30** program ceiling, with a combined
retry-inclusive physical cap of **384 requests** (128 logical × 3). Pacing is
carried from the registered Ling transport and Jev backoff constants, every
bound counts physical requests including retries, the reservations are the
retry-inclusive worst cost of one more logical call per role, and unused
budgets authorize no carry-over.

**Stops, paths, ownership and coverage.** The L03 terminal stop list carries
verbatim (request/cost cap before the next call, fixed-schedule completion,
model/endpoint and request/option identity drift, malformed or
non-option-matched receiver vectors, normalization violations, writer
terminal errors including `truncated_output` and rate limiting as a distinct
429 class, two consecutive terminal provider failures, output collision, and
any audit exception breaking provenance). Registered live paths stay fresh,
unique, currently absent and scoped to `runs/next-phase/legal/`, with an
explicit **no-resume / no-append / no-overwrite / no-path-override**
lifecycle: a stopped run requires a new registration, a new review and fresh
paths; every silence, failure and not-attempted row is retained in an
immutable journal. The ownership/read-after-write contract is registered
(exact B authorship, byte-exact claim match, accepted write then a strictly
later A `peer_read_exposure` with nonempty exposure id; one deduplicated
informative claim per state; the A-known placebo is inert with I_m = 0), and
the L03 prospective coverage rule freezes verbatim with
`frozen_before_collection`, no imputation, no seed replacement, no form
removal after outcomes and no replenishment from spare capacity.

**Authorization (everything pending, nothing inferred).** The registration
authorizes nothing beyond L05 planning; `route_authorized` stays false, the
loop halts before #225, and the L07 gate must cover the exact stage, route,
pacing, retry-inclusive request caps and dollar caps. Reviewing or locking
this registration is not authorization, and a failed or stopped predecessor
never authorizes its successor.

## 3. Handoff to L05 (#223) and explicit non-claims

L05 must consume exactly this registration with a fail-closed, offline-tested
runner and preflight: zero provider calls, refusal of any drift from the
registered manifest/treatment/route/caps, missing live output paths failing
closed, and no run without both the L06 reviewed lock (#224) and the
separate explicit L07 authorization reference (#225). This artifact does not
open or advance #223; #222 is closed only by the plugin after reviewer
approval. Non-claims include: no provider call or live journal was made or
authorized here; no confirmatory claim for legal:low at k = 4; no
population-level generalization beyond the four registered forms; no
effect-size prior from planning-low, hypothesis-low or the motivating paper;
no cross-family pooling or winner selection; no reuse of the stopped
hypothesis registration or its windows; #227's proposed families are design
backlog only and count toward no target here.

## 4. Limitations

Offline only, and draft pending review only: L06 review/lock and an explicit
L07 authorization remain required before any call. Descriptive by design
(floor 0.125 > 0.05), with form-level exchangeability assumption-dependent
and labeled. Cost figures recompute from the frozen rate card; observed spend
depends on a future L07-authorized run. Seed/instance-id disjointness is
inherited from the hash-pinned L02 inventory, whose 20 recorded inaccessible
locations remain open audit exceptions, never empty sets. The build is
deterministic and byte-reproducible, and it fails closed on any drift of the
pinned inputs, the L03 screen manifest, the treatment bytes, the #227 audit
pins or the network audit.
