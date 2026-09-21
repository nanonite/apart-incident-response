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
**12 distinct request hashes** (6 ISO/FULL prompt forms), with form sizes
**[7, 4, 2, 2, 1, 1]**; 10/34 match the wire smoke. It is not 17 independent
confirmations, and a small p-value is not an entropy gate.

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

## Prompt-form estimand decision

New Chainlink epic **#181** owns the Choice-only continuous replay contract;
#182–#185 break out the estimand, event schema, analysis, and preregistration.
The later packet/Noul/Score tasks #173 and #175 keep their separate scope.

For a matched replay event, hold the receiver's pre-read state C, options,
model, and target fixed and evaluate real, inert-placebo, and null branches:

- H_real = H(Y | C, M_real), H_placebo = H(Y | C, M_placebo), H_null = H(Y | C).
- The primary per-event difference is H_real − H_placebo. Average complete
  event differences within each distinct model-visible pre-read prompt form,
  then give each form equal weight. The directional prediction is **negative**.
- The null branch cancels algebraically from that primary contrast. Retain it
  to show real-minus-null and placebo-minus-null separately and to detect
  entropy changes caused merely by adding foreign text.

With the current generator the experimental unit is the prompt form, **k=6**,
not the 17 instance IDs. Repeated IDs estimate within-form response variation;
they do not add independent states. The proposed primary interval is a t
interval on the six form means (df=5), paired with an exact two-sided
cluster sign-flip test over all 2^6 assignments. Its smallest two-sided p is
2/64 = 0.03125. This inference is conditional on the six frozen forms and on
the test's exchangeability/symmetry assumptions. At k=6, hierarchical-model,
form-bootstrap, and Wilcoxon results are sensitivity checks, not rescue
evidence. An instance-weighted estimate is secondary.

As a **method demonstration only**, applying equal-form aggregation to the
existing Jev ISO-minus-FULL entropy differences gives form means about
[1.292, 1.145, 1.139, 1.606, 1.180, 1.472] bits. Their equal-form mean is
1.306 bits, between-form SD 0.193, SE 0.079, t95 interval [1.103, 1.509],
and exact two-sided sign-flip p=0.03125. This is neither a real-placebo
effect nor a power estimate for that effect.

An entropy drop alone cannot establish useful information: a receiver could
become confidently wrong. The preregistration must separately define
real-versus-placebo target-probability and clue-consistent-mass guards, with
their direction and thresholds fixed before collection. Objective claim I_m
remains separate from Jev entropy reduction. Primary pairs require valid real
and placebo results on the identical C; report planned, valid, and complete
pairs by branch and prompt form, with no primary imputation. Differential
missingness must be flagged as a threat to interpretation.

Newcombe method 10 and McNemar remain appropriate for **binary** paired
checker-success outcomes. They are not the primary uncertainty method for
continuous entropy or target-probability differences.

## Proposed #158/#159 manifest, thresholds, and caps (draft for review — not authorization)

- **Manifest**: planning-low, regime N, seed base **72000**, 17 instance IDs,
  disjoint by ID from the planning-low manifest (70000), J3 (71000), and the
  wire smoke. Manifest hash `27e0c9fa…`. It is **not** prompt-form-disjoint:
  all 34 proposed ISO/FULL request bodies match J3 hashes. Decide whether to
  test new messages conditional on the six known forms or redesign the
  generator and preregister genuinely new forms.
- **Arms**: ISO (Jev receiver pre-read), FULL (saturated bound), COMM optional
  board (Ling writer / Jev receiver), and matched **real/placebo/null** receiver
  replay on the same pre-read state.
- **Primary contrast**: equal-weight mean across prompt forms of paired
  H_real − H_placebo, using complete real/placebo events from the same C;
  t interval on form means and exact cluster sign-flip. Report p_target and
  feasible-set mass alongside entropy. Keep Newcombe/McNemar for a separately
  defined binary outcome.
- **Thresholds (draft)**: at least one accepted, owner-exact write that reaches
  the receiver; form-level entropy interval below zero and a registered
  sign-flip rule, plus separately frozen useful-information guards. A p-value
  alone is not an entropy or causal-uptake gate.
- **Caps (draft)**: ≤ 300 physical requests; ≤ $1 Jev cost; pinned free Ling
  model on OpenRouter free quota; stop rules request_cap / cost_cap /
  repeated_http_failure / contract_mismatch / model_drift / missing_checker_evidence.
- **Form-level registration**: the frozen estimand is in
  `docs/jev-prompt-form-estimand.md`; the form-capacity audit (6 paired forms;
  72000 repeats all J3 forms) and the draft registration are in
  `runs/epic-126/jev-choice-replay-preregistration.json` (#185). Do not lock or
  run live until the reviewer resolves the pending decisions.

## Caveats

- The selection criterion above is **post-hoc**; it must be preregistered before
  #158 and is not retroactively presented as preregistered.
- J3 outcomes are **not** held-out J5 evidence. The proposed #158 IDs are
  disjoint, but their baseline prompts repeat J3 forms; claims about new
  prompt forms require generator redesign.
- Jev capability at the treatment level is shown, not calibration.

## Choices needed before #158

1. Accept **advance `planning:low`** and the post-hoc criterion (to be frozen in
   the #158 registration).
2. Choose a study conditional on the six known prompt forms or a richer
   generator yielding new forms. Seed-base change alone will not do so.
3. Freeze the real/placebo/null eligibility, useful-information guards,
   distinct-form k target, missingness rule, and power analysis based on
   between-form variation. Do not size continuous entropy from binary
   discordant pairs. Confirm caps in a separate registration; none are live
   approvals here.
