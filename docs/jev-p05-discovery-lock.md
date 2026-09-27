# P05 — Lock discovery design (offline)

Task: Chainlink **#206** under **#201** under **#159**. Offline only — no
provider call, no collection, no live run. **This lock is not live
authorization and grants no live authority.**
Protocol: [hypotheses and sequential discovery/confirmation plan](jev-discovery-confirmation-plan.md).
Family: `hypothesis:low` (classified as a pilot in P04, k = 4).

Versioned discovery lock:
[`runs/next-phase/jev-p05-discovery-lock-v1.json`](runs/next-phase/jev-p05-discovery-lock-v1.json)
with self-recorded `lock_hash`
**`9de4a61f9d46c47b55bbe7b8da9903c677c6461bf4af353007277835ed6a18b3`**,
locking the P04 registration
[`runs/next-phase/jev-p04-discovery-registration-v1.json`](runs/next-phase/jev-p04-discovery-registration-v1.json)
(`registration_hash`
**`6fa6149770b620cd3a026a6415f8e4d97e800e8af5237794de7b29fca6dacfac`**,
`status_at_lock = draft_pending_review`).

Independent review record:
[`runs/next-phase/jev-p05-discovery-lock-review-v1.json`](runs/next-phase/jev-p05-discovery-lock-review-v1.json)
— verdict **`approved`**, `reviewed_lock_hash` equal to the lock hash above.

Both records live outside `runs/epic-126/` so the frozen #200 audit's
byte-reproducibility scan (`runs/epic-126/**`) stays intact.

## 1. Evidence paths

All hashes recomputed from disk at build time; `verify_lock` re-derives every
one of them and fails closed on drift.

| Path | Role | sha256 |
|---|---|---|
| `runs/epic-126/replication/jev-replication-form-audit-v1.json` | #200 frozen form audit | `cb529cd61e0e662bfa19fc4998e89fa59a0bf0d63e14f77498035466d6bce89d` |
| `runs/epic-126/replication/jev-replication-preregistration-v1.json` | #200 frozen draft registration | `bddf46ed5fd87ec4da99532d645580a65e250d64639de80477002ff73d278f3c` |
| `runs/next-phase/jev-p02-scope-freeze.json` | P02 scope freeze | `c254c45c748a33d9f1514f2a497fe6fbc5d96fbb7553eb142d8fe22a4b64c474` |
| `runs/next-phase/jev-form-census-v1.json` | P03 form census | `da57b403d36fd91fd5d90aeb5ef5d7f894ee19fffbfc41a2d2b2dd95f922b34b` |
| `runs/next-phase/jev-p04-discovery-registration-v1.json` | P04 discovery registration (locked) | `78f7cd03c3afc12c94c3ba09839e4ac6ba667a3f68b96871571b274ae7d3ab11` |
| `docs/jev-p04-design-classification.md` | P04 narrative | `d110547c415f788920e14f4137910da36891907117ee3c7c6f98c0382324d762` |
| `docs/jev-discovery-confirmation-plan.md` | protocol | `501e21b6dea760371b0bf368046d8bacd203f6b92f0af754a7955d1f738677f7` |

## 2. Offline preflight (51 checks, `provider_calls: 0`)

`python -m apart_incident_response.jev_p05_discovery_lock --repo-root . --preflight`
→ exit 0, `ok: true`, `checks_run: 51`, `failed: []`, `provider_calls: 0`,
`status: offline`. It re-derives, fail closed:

- the P04 `registration_hash` and all four frozen input pins (#200 audit
  content hash, #200 `preregistration_hash`, P02 `content_hash`, P03
  `content_hash`) plus each file's `sha256`;
- the full P04 verification (41 checks) behind it;
- k = 4, floor 0.125, `pilot`, fresh-seed replication descriptive, H0/H1,
  estimand, guards-never-filter, no planning-low prior;
- fixed N = 16 (4 per form), window 85000–85511, `matches_200_audit_primary_block`,
  "no outcome-based stopping";
- treatment (original L4X, `exact-original-comm-bridge`, one-way B→A, regime N,
  2 turns, final receiver A via Jev Choice wire v2) and route (paid OpenRouter
  Ling SKU; Jev systemone `jev-1.13.0`, codec `jev-choice-wire-v2`,
  normalization policy `292ac217…`, hard ceiling 0.05);
- request caps, cost model rates, next-call reservations, ceilings vs
  worst cases;
- terminal stops, the four reserved live paths **absent**, paths outside
  `runs/epic-126/`, and the no-resume/no-append/no-overwrite lifecycle;
- coverage rules, exploratory-replay labelling, and the four authorization
  flags (`locking_is_not_authorization`,
  `approval_may_not_be_inferred_from_locking`,
  `separate_live_authorization_required_after_locking`,
  `approval_must_be_a_supplied_reference`).

**Discrepancies found and resolved** (both defects in the new P05 tool, caught
by this preflight before any lock was written; no repository data was wrong):

1. `p04_registration_hash_recomputes` failed — the shared hash helper excluded
   `lock_hash` instead of `registration_hash`, so it hashed the whole document
   (`3f41f528…`) rather than the registration's own convention (`6fa61497…`,
   which matches the pin). Split into `_lock_hash` / `_registration_hash`;
   the preflight then matched the pin.
2. The lock was not JSON-serializable because `REGISTRATION_PATH` is a
   `pathlib.Path`; coerced to `str` in the three document fields.

After the fixes: **51/51 green**.

## 3. What the lock fixes

The lock freezes the reviewed offline design and the exact scope a
*separate* authorization reference would have to cover. It records:

- `status = locked_pending_separate_live_authorization`;
- `authorization_reference.state = pending_not_supplied`, `reference: null`,
  `recorded_at: null`, with `must_cover = [stage, route, request_caps, cost_caps]`
  and `may_not_be_inferred_from` the lock, the locked registration, environment
  credentials, the task prompt/plan document, or the reserved output paths;
- `authorizes = "nothing beyond locking the reviewed offline discovery design;
  no provider call, no collection, no live run"`;
- preserved design: **k = 4**, floor **0.125**, classification **pilot**,
  descriptive only, fresh-seed replication descriptive, estimand
  equal-weight form mean of real-minus-placebo entropy, H0 `Delta = 0`,
  H1 `Delta < 0`, guards never filter, no planning-low effect-size prior;
- the two frozen #200 artifacts with their on-disk `sha256`, byte-unchanged;
- `blocks = "#207 (P06) remains blocked until a separate explicit reference is
  supplied and recorded"`.

## 4. Scope a separate authorization reference must cover

Verbatim from the locked registration's `authorization_scope` (verified field
by field against the P04 registration).

**Stage**
`hypothesis:low discovery screen and optional exploratory replay` — family
`hypothesis`, regime `N`, one discovery block.

**Route**
- **Writer:** Ling `inclusionai/ling-3.0-flash-vl` on the **paid** OpenRouter
  SKU, `https://openrouter.ai/api/v1/chat/completions`, temperature 0.0,
  token budget 1024, pacing `ling-writer-openrouter-pacing-v3` (3.25 s between
  physical attempts), `max_retries 2`.
- **Receiver:** Jev `jev-1.13.0` at `https://api.typesafe.ai/v1/systemone`,
  codec `jev-choice-wire-v2`, protocol key
  `jev-choice-wire-v2|75190e251aa2ecf8fdbb79fb0ae823992159c227dc47dfc378dad660969d7aa0`,
  normalization policy `292ac217f1cf54083252e6363a16a48596daab72a8ca06d4569c20f861b7e1e9`,
  hard normalization ceiling **0.05**.

**Request caps** (retry inclusive: up to 3 physical attempts per logical call)

| Stage | Planned | Physical |
|---|---|---|
| Discovery collection | 64 Ling + 16 Jev (80) | 192 Ling + 48 Jev (240) |
| Exploratory replay (≤16 events × 3 branches) | 48 Jev | 144 Jev |
| **Program** (one block) | 64 Ling + 64 Jev (128) | 192 Ling + 192 Jev (384) |

Fixed N = 16 (4 instances × 4 forms); `block_n = 16`.

**Cost caps**

| Stage | Ceiling | Worst case |
|---|---|---|
| Discovery collection | ≤ **$0.20** | $0.146276352 |
| Exploratory replay | ≤ **$0.10** | $0.049545216 |
| **Program** | ≤ **$0.30** | **$0.195821568** |

Next-call reservation: Ling `$0.00202752`, Jev `$0.001032192`. Stop **before
the next call** whenever a request or cost cap would be exceeded, plus the
registered model/protocol/identity/hash-drift, malformed-vector,
normalization (>0.05), argmax-shift, output-collision, writer-terminal-error
and two-consecutive-terminal-failure stops.

All four live output paths under
`runs/next-phase/hypothesis/jev-discovery-v1/` are **absent**; fresh paths
only, no resume, no append, no overwrite, no path overrides.

## 5. Independent review

The lock was reviewed by a separate, read-only agent session that did not
build it, against **#206** and **docs/jev-discovery-confirmation-plan.md**.
Verdict recorded in
[`runs/next-phase/jev-p05-discovery-lock-review-v1.json`](runs/next-phase/jev-p05-discovery-lock-review-v1.json):

- **verdict `approved`**, `blocking_findings: []`, 16 checks all `ok`,
  `provider_calls: 0`;
- `reviewed_lock_hash`
  `9de4a61f9d46c47b55bbe7b8da9903c677c6461bf4af353007277835ed6a18b3`
  independently recomputed (the reviewer confirmed the serialization is
  sort-keys excluding `lock_hash`, not the indent-2 byte form);
- 7/7 evidence `sha256` recomputed from disk; the two frozen #200 artifacts
  match the P04 pins byte for byte;
- preflight re-run under a `sys.addaudithook` watching
  `socket.connect` / `getaddrinfo` / `urllib.Request`: **0 network events**;
- full verification re-run: exit 2 with **exactly the 5 review-record checks
  failing** — the fail-closed behaviour — all other 38 passing;
- #206 `open` (gate not closed) and #207 `open` (no successor started);
  no authorization file exists anywhere under `runs/` or `docs/`;
- non-blocking observations: the P04 registration still sits at
  `draft_pending_review` with 4 `pending_review` items (recorded honestly), the
  artifacts were untracked pending this commit, and per-call `cost_model`
  rates are pinned indirectly via the registration `file_sha256`.

## 6. Checks (all offline, zero provider calls)

- Offline preflight: **51/51**, `provider_calls: 0`, `status: offline`.
- Lock verification: **44/44**, `ok: true`, `failed: []`,
  `provider_calls: 0`, including `lock_rebuilds_byte_for_byte`,
  `lock_file_is_byte_reproducible`, `embedded_preflight_matches_fresh`,
  `evidence_path_hashes_recompute`, `frozen_200_artifacts_preserved`,
  `k4_preserved`, `scope_*_match_registration`,
  `authorization_reference_pending`, `live_paths_still_absent`,
  `review_record_approved`, `review_record_matches_lock_hash`.
- Independent review: **16/16**, `approved`, no blocking findings.
- `lock_hash` recomputes to `9de4a61f…a18b3`; the artifact is byte
  reproducible (`write_lock` refuses to overwrite a differing artifact).
- Live output paths and `runs/next-phase/hypothesis/` do not exist.
- Issue #206 remains `open`; #207 remains `open` and blocked by #206.

## 7. Handoff

P05 is complete with evidence paths, hashes, checks and this handoff: the
offline preflight is green, the lock is built and independently reviewed, and
`lock_hash` is recorded.

**What is deliberately missing:** the separate explicit live authorization
reference. Its absence is recorded as `pending_not_supplied`, and
`verify_lock` fails closed without an approving review record for this exact
hash. The next step is a *separate* authorization decision that supplies a
reference covering **stage, route, request caps and cost caps** (§4) — this
document, the lock, and any credential present in the environment are not that
reference and may not be read as approval.

Until that reference is supplied and recorded, **#206 stays open** and
**#207 (P06, collection) stays blocked**. A predecessor closed as failed does
not authorize successor execution; nothing here authorizes any provider call,
collection, or the exploratory replay.
