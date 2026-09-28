# Jev hypothesis:low discovery — authorization gate brief (#206)

Decision brief prepared for a human. **Preparing this document and the
accompanying record grants no authority of any kind.**

Protocol: [hypotheses and sequential discovery/confirmation plan](jev-discovery-confirmation-plan.md).
Family: `hypothesis:low` (pilot, k = 4, descriptive only).

| Artifact | Path | State |
|---|---|---|
| P04 registration | [`runs/next-phase/jev-p04-discovery-registration-v1.json`](../runs/next-phase/jev-p04-discovery-registration-v1.json) | `registration_hash 6fa61497…dacfac`, review items resolved (see below) |
| P04 registration review | [`runs/next-phase/jev-p04-discovery-registration-review-v1.json`](../runs/next-phase/jev-p04-discovery-registration-review-v1.json) | **approved**, 4/4 items, 24 checks, no blocking findings |
| P05 lock | [`runs/next-phase/jev-p05-discovery-lock-v1.json`](../runs/next-phase/jev-p05-discovery-lock-v1.json) | `lock_hash 9de4a61f…a18b3`, `locked_pending_separate_live_authorization` |
| P05 lock review | [`runs/next-phase/jev-p05-discovery-lock-review-v1.json`](../runs/next-phase/jev-p05-discovery-lock-review-v1.json) | **approved**, 16 checks, no blocking findings |
| **Authorization record** | [`runs/next-phase/jev-discovery-authorization-record-v1.json`](../runs/next-phase/jev-discovery-authorization-record-v1.json) | **`awaiting_explicit_reference`**, `authorized: false`, `reference: null` |

Full identifiers for audit:

- `lock_hash` = `9de4a61f9d46c47b55bbe7b8da9903c677c6461bf4af353007277835ed6a18b3`
- `registration_hash` = `6fa6149770b620cd3a026a6415f8e4d97e800e8af5237794de7b29fca6dacfac`
- registration `file_sha256` = `78f7cd03c3afc12c94c3ba09839e4ac6ba667a3f68b96871571b274ae7d3ab11`
- `scope_digest_sha256` = `938da9116805967253417c53709cd85d56d1913ac0142032d0d4732f50c04061`

## 1. Outstanding P04 registration review — resolved

An independent read-only reviewer (which did not build the registration)
decided all four `authorization.pending_review` items. Verdict **`approved`**,
`requires_new_version: false`, zero blocking findings — so **no new
registration version and no new lock review were required**.

1. design classification (k = 4, floor 0.125, pilot) — **approved**
2. fixed-N discovery manifest and selection rule — **approved**
3. treatment/route, budgets, stops, paths and coverage rules — **approved**
4. separate explicit live authorization reference required before any provider
   call — **approved as a standing requirement**, i.e. confirmed as correctly
   recorded and *not* granted

The registration document itself was **not altered**: its `file_sha256`
`78f7cd03…ab11` and `registration_hash` `6fa61497…dacfac` are pinned by the
P05 lock, so editing even its `status` field would invalidate the lock. The
resolution therefore lives in the separate review record, which states
`registration_bytes_unchanged: true`. Its in-document `status` field remains
`draft_pending_review` by construction.

Reviewer non-blocking notes (recorded, none require action): path-location
deviation from the protocol's `runs/epic-126/next-phase/…` example is
rationaled in `path_lifecycle.location_note`; `k_bands` says "pilot" where the
protocol table says "descriptive/estimation only" (substantively equivalent);
the `manifest_matches_200_audit_primary_block` CLI check only asserts a
self-declared boolean, so the reviewer recomputed the structural comparison
independently; `runs/container-isolation.json` stays permission-denied and is
carried as a recorded audit exception, never as an empty set.

## 2. What you are being asked to decide

Supply an **explicit live authorization reference** covering exactly the
stage, the paid OpenRouter SKU and Jev route, the retry-inclusive request
caps, and the cost caps below. Until you do: **zero provider calls, #206 stays
open, #207 stays blocked, all four live output paths stay absent.**

### Stage
`hypothesis:low discovery screen and optional exploratory replay` — family
`hypothesis`, regime `N`, one block of N = 16 (4 instances × 4 forms).

### Route (paid)
| Role | Endpoint | Model / codec | Notable pins |
|---|---|---|---|
| Writer | `https://openrouter.ai/api/v1/chat/completions` (**paid** OpenRouter SKU; free SKU not routable) | `inclusionai/ling-3.0-flash-vl` | temperature 0.0, token budget 1024, pacing 3.25 s between physical attempts, `max_retries 2` |
| Receiver | `https://api.typesafe.ai/v1/systemone` | `jev-1.13.0`, codec `jev-choice-wire-v2` | protocol key `jev-choice-wire-v2\|75190e25…969d7aa0`, normalization policy `292ac217…b7e1e9`, hard ceiling **0.05** |

### Request caps (retry-inclusive: ≤ 3 physical attempts per logical call)
| Stage | Planned | Physical |
|---|---|---|
| Discovery collection | 64 Ling + 16 Jev (80) | 192 Ling + 48 Jev (240) |
| Exploratory replay (≤ 16 events × 3 branches) | 48 Jev | 144 Jev |
| **Program** (one block) | 64 Ling + 64 Jev (128) | 192 Ling + 192 Jev (384) |

### Cost caps
| Stage | Ceiling | Worst case |
|---|---|---|
| Discovery collection | ≤ **$0.20** | $0.146276352 |
| Exploratory replay | ≤ **$0.10** | $0.049545216 |
| **Program** | ≤ **$0.30** | **$0.195821568** |

Next-call reservation before each call: Ling `$0.00202752`, Jev `$0.001032192`.
Stop *before the next call* whenever a request or cost cap would be exceeded,
plus the registered drift / malformed-vector / normalization > 0.05 / argmax
shift / output-collision / writer-terminal-error / two-consecutive-failure
stops.

The whole scope is carried verbatim in the authorization record with
`scope_digest_sha256 = 938da9116805967253417c53709cd85d56d1913ac0142032d0d4732f50c04061`,
so a reference can pin the exact scope it covers.

## 3. What to supply

Edit **only** `runs/next-phase/jev-discovery-authorization-record-v1.json` and
fill in:

```
state:              "authorized"          (currently "awaiting_explicit_reference")
authorized:         true                  (currently false)
reference:          "<opaque reference>"
supplied_by:        "<who issued it>"
supplied_at:        "<ISO-8601>"
decision:           "<what you approved>"
```
and echo `scope_digest_sha256` in your reference so it is bound to this exact
stage/route/request/cost scope.

Any change to stage, route, request caps or cost caps requires a **new version
of the record plus fresh registration and lock review** — not an edit here. A
stopped run requires a new registration and fresh paths.

## 4. Not authorization

This brief, the record's existence, the P05 lock, the two `approved` review
verdicts, credentials present in the environment, and the reserved output
paths are **all explicitly listed as things authorization may not be inferred
from**. The reviews approved *the offline artifacts*, not live execution.

## 5. Current gate status

- **#206 open** (`closed_at: null`) — not closed, by design.
- **#207 (P06) blocked** by #206 — no successor started.
- **Zero provider calls** at every step; the P05 preflight (51 checks) and
  verification (44 checks) both report `provider_calls: 0`.
- All four live output paths under `runs/next-phase/hypothesis/jev-discovery-v1/`
  **do not exist**; `runs/next-phase/hypothesis/` does not exist.
- The discovery loop has **not** been relaunched.
