# J4 — board-necessity selection decision (#157)

Status: offline selection memo for review. No live calls. This is a decision on
the **selection** of board-necessary candidates; it does not authorize #158 and
does not establish calibration or causal board uptake.

Sources: `runs/epic-126/jev-choice-capability.jsonl` and `-report.json` (#180),
`runs/epic-126/jev-cell-selection-v1.json` and `confirmatory-v3*` (Ling screen),
`docs/jev-cell-selection-memo.md`, and the frozen generator channel audit.
Reproduced artifact: `runs/epic-126/jev-board-necessity-selection.json`.

## Constructs, kept separate

| Construct | Value | Source |
|---|---|---|
| Structural peer-information need | finalizer needs peer 17/17; channel complete 17/17 | generator audit |
| Ling C_need (ISO→FULL success) | +0.588, McNemar exact p=0.00195, **Holm 0.0098** | confirmatory-v3, planning:low |
| Voluntary board use (COMM) | used_board 14/17, 20 messages, 31.70 bits, rejected writes 0, post-read correlation 2/17 | confirmatory-v3 |
| Jev ISO target probability | mean p_target 0.451; accepted 8/17 | #180 journal |
| Jev FULL target probability | mean p_target 0.9994; accepted 17/17 | #180 journal |
| Jev decision entropy H(Choice p) | ISO 1.285 bits; FULL 0.0048 bits; Δ 1.281 bits | recomputed from saved vectors |
| ISO mass on clue-consistent set | 0.9835 | recomputed from saved vectors |

The Jev gate is a **repeated-query capability check**: 34 cases contain only
**12 distinct request hashes** (6 ISO/FULL prompt forms); 10/34 match the wire
smoke. It is not 17 independent confirmations, and a small p-value is not an
entropy gate.

## The ceiling question

Jev FULL is near ceiling (mean p_target 0.9994, mean H 0.0048 bits). Does that
disqualify planning-low for the intended entropy experiment?

**No — advance, on the following post-hoc criterion (not preregistered):**

1. structural need complete (finalizer needs peer 17/17);
2. Ling C_need Holm-significant (0.0098) on the selection screen;
3. ISO entropy above a floor (mean H ≥ 1.0 bit; observed 1.285);
4. FULL entropy near ceiling as the expected saturated bound (mean H ≤ 0.1 bit; observed 0.0048);
5. large ISO→FULL entropy contrast (Δ ≥ 1.0 bit; observed 1.281);
6. ISO mass concentrated on the true clue-consistent set (≥ 0.90; observed 0.9835).

**Rationale.** The entropy experiment (#159) operates on the receiver's
**pre-read (ISO-like)** state and uses FULL as the saturated upper bound, so a
near-ceiling FULL is the expected manipulation check, not the measurement cell.
The ceiling would disqualify the cell only if ISO entropy were near zero (no room
for a message to move the distribution) or ISO mass were not on the consistent
set (the residual entropy would reflect a failure to narrow, not genuine
within-feasible-set uncertainty). Neither holds: ISO retains 1.285 bits with
0.9835 mass on the three consistent candidates, i.e. the receiver narrows
correctly but remains uncertain **within** the feasible set — exactly the regime
a peer message should collapse.

## Decisions

- **Advance `planning:low`** as the Jev entropy-contrast candidate.
- **Hold `hypothesis:medium`** (Holm 0.0625, not significant).
- **Hold `planning:high`** (validity repaired separately; outside the Jev scope).
- **Hold `hypothesis:low`** (0.4531) and **`reference:low`** (0.5000): little joint-information benefit.

## What remains unknown about causal board uptake

- confirmatory-v3 COMM shows voluntary use but only 2/17 post-read correlation
  events and confounds board use with the extra finalizer turn.
- No matched real/placebo/null receiver replay has been run; causal uptake is
  unestablished.
- Jev has no COMM data; the message effect on H(Choice p) is untested.

## Proposed #158 manifest, thresholds, and caps (draft for review — not authorization)

- **Manifest**: planning-low, regime N, seed base **72000**, 17 instances,
  disjoint from the planning-low manifest (70000), the J3 block (71000), and the
  wire smoke. Manifest hash `27e0c9fa…`.
- **Arms**: ISO (Jev receiver pre-read), FULL (saturated bound), COMM optional
  board (Ling writer / Jev receiver), and matched **real/placebo/null** receiver
  replay on the same pre-read state.
- **Primary contrast**: paired change in H(Choice p) and p_target from pre-read
  to post-read, real vs matched placebo/null, complete-pair reporting.
- **Thresholds (draft)**: at least one accepted, owner-exact write that reaches
  the receiver; causal uptake only if the Newcombe interval for the
  real-vs-placebo paired change excludes 0 at α=0.05; no p-value-only entropy gate.
- **Caps (draft)**: ≤ 300 physical requests; ≤ $1 Jev cost; pinned free Ling
  model on OpenRouter free quota; stop rules request_cap / cost_cap /
  repeated_http_failure / contract_mismatch / model_drift / missing_checker_evidence.

## Caveats

- The selection criterion above is **post-hoc**; it must be preregistered before
  #158 and is not retroactively presented as preregistered.
- J3 outcomes are **not** held-out J5 evidence; the #158 manifest is disjoint.
- Jev capability at the treatment level is shown, not calibration.

## Choices needed before #158

1. Accept **advance `planning:low`** and the post-hoc criterion (to be frozen in
   the #158 registration).
2. Accept the proposed **72000 manifest**, or specify a different size/base.
3. Set the real/placebo/null **sample size** from expected discordant pairs, and
   confirm the ≤300-request / $1 caps.
