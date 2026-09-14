# Results — exp1 (entropy as a signal of inter-agent communication)

All numbers come from the scripts in `exp1/analysis/` (run `run_all.sh`); each claim cites `script → out/tables/<file>`.
n = 20 seeds per model × condition. All analyses are exploratory; intervals are 95 %.
Entropy values are top-20 approximations and are compared only within a model.

## 0. Data integrity

- All structural checks passed. There are 180 runs (3 models × 3 conditions × 20 seeds) and every executed turn has one A1 row and one A2 row. `read_policy = all` occurs only in switch runs at t ≥ 8. Real foreign entries were returned only in switch at t ≥ 8, and donor entries only in placebo at t ≥ 8. A sample of 18 runs matched `turns.jsonl` and `check.json` with 0 mismatches. [s00_integrity → logs/s00_integrity.txt]
- One run is invalid: llama-3.3-70b placebo seed 3 (`API_FAILURE`). It is kept, flagged, and dropped from the paired contrasts for that seed.
- 98 calls failed with HTTP 429 (llama: 26 base, 41 placebo, 29 switch; qwen placebo: 2). These rows are kept without an action. [s00]
- Two design facts differ from the task description:
  - **Turn order rotates with the seed.** A1 moves first in seeds 2, 3, 5, 8, 11, 14, 16, 19 and 20. For any given seed the order is the same in every condition and model.
  - **Asset roles never rotate.** A1 always holds BRAND_KIT and A2 always holds SCHEMA. [s00 → t0_turn_order_by_seed.csv]
- A `READ_LOG` result reaches the agent only in the prompt of its *next* call. The first call exposed to foreign content is therefore τ_read + 1. [turns.jsonl `messages_sent`; s05 docstring]

## 1. Descriptives (Table 1)

[s01_descriptives → tables/table1_descriptives.md]

- **Uptake occurred only when the channel was open.**
  - Switch: `communication_verified` was 1.00 (gpt-4o-mini), 1.00 (llama-3.3-70b) and 0.95 (qwen3-235b).
  - Task success was 0.75, 0.85 and 0.90.
  - Base and placebo had no verified communication and no successes.
- **Timing of the first cross-agent read (median τ_first_foreign_read [IQR]).**
  - gpt-4o-mini: 12.5 [10–15.5].
  - llama: 9 [9–9].
  - qwen: 8 [8–8].
- **Median τ_use by direction** (A1→A2 / A2→A1):
  - gpt: 17 / 16.
  - llama: 12 / 12.
  - qwen: 11 / 11.
- **Survival differs by condition.**
  - Mean turns executed in switch: 22.8 (gpt), 23.45 (llama), 16.75 (qwen).
  - Base runs always reached 30 turns.
  - qwen placebo runs also ended early (16.35), because agents submitted one-asset reports.
- **The placebo is not a neutral control.**
  - Donor facts appeared in submitted reports in 17/20 gpt, 20/20 llama and 20/20 qwen placebo runs.
  - Invented tables appeared in 15, 18 and 16 runs.
  - No agent tried a donor password.
- **The dose of donor content differed by model.** Donor entries were returned 59 times (gpt), 330 (llama) and 164 (qwen). Real foreign entries in switch were returned 54, 244 and 194 times. [t0_exposure_by_agent.csv]
- **Agents often guessed a password they did not hold** (`password_source = other`). This happened in about 41–45 % of decrypt calls for gpt and 26–49 % for qwen, and never for llama. Decrypting with a password read from the log happened 4 times, all in switch. [table1]

## 2. Validity of the entropy measures

[s02_entropy_validation → tables/t2a_*, t2b_*, t2c_*]

- **Definitions confirmed by recomputation from `topk.csv.gz`.**
  - `H_renorm` and `coverage` reproduce within 3.4 × 10⁻⁷ for gpt-4o-mini and llama.
  - `H_lower` equals the truncated sum −Σ_top-20 p log₂ p, to within 2 × 10⁻¹⁵. It does **not** add a term for the residual mass: that variant is off by up to 0.53 bits.
  - Within a model, H_lower and H_renorm are almost the same quantity: Pearson r ≥ 0.996 per token and Spearman ≥ 0.99998.
  - Top-20 coverage is high. The share of tokens with coverage below 0.99 is 1.6 % (gpt), 0.96 % (llama) and 0.38 % (qwen), with no material difference between conditions.
- **qwen3-235b has a provider artifact.**
  - In 35.4 % of qwen tokens the sampled token is not in the returned top-20. In many of these cases the list is simply a repeat of the previous token's list (21.5 % of tokens share their predecessor's H_lower).
  - The share of such tokens per call differs by condition: 6.8 % in base, 15.3 % in placebo and 13.8 % in switch. This is a measurement confound specific to qwen.
  - gpt-4o-mini is affected in 0.25 % of tokens and llama in none.
  - All qwen contrasts were rerun on a "clean" H̄ that uses only tokens present in the top-20 list (§9). [s09 → t9_token_validity_audit.md]
- **`system_entropy.csv` reproduces exactly** (all 32 columns, max |Δ| ≤ 3 × 10⁻¹⁵) with the following estimator [sysent.py]:
  - X_i is the agent's **action class**, with a soft distribution q_i taken from the logprobs at the action token.
  - The joint over paired runs is P(x₁, x₂) = mean_r q₁ᵣ(x₁) q₂ᵣ(x₂), and I = H(p₁) + H(p₂) − H(P).
  - I_shuffled is the same quantity computed over all cross-seed pairs, exactly.
  - The hard version uses realised actions with a Miller–Madow correction.
  - Every quantity is NaN when fewer than 2 runs are paired.
  - Consequence: I measures how the two agents' action distributions co-vary **across runs at the same turn**. It is not a coupling measured within a run, and I_shuffled ≈ 0 by construction.
- `aligned_tau_read.csv` is aligned on the run-level τ_first_foreign_read for both agents, not on each receiver's own τ_read. The receiver-based alignment disagrees in 120/193 rows. [s05 → t5_aligned_tau_read_reproduction.md]

## 3. Paired endpoint contrasts (Table 2)

[s03_endpoints → tables/table2_endpoints.md]

Primary specification:
- H̄ = `mean_H_renorm_bits`, adjusted for action type and log response length.
- Post window: turns 8–17.
- The contrast is taken per seed.

**ΔH_comm = S − ½(B + P).**
- **gpt-4o-mini:** −0.010 bits/token [−0.054, 0.035]; 9/20 seeds positive; Wilcoxon p = 0.65.
- **llama-3.3-70b:** −0.005 [−0.019, 0.010]; 5/19 positive; p = 0.42.
- **qwen3-235b:** +0.020 [−0.020, 0.060]; 12/20 positive; p = 0.39.

The result is the same, with every CI containing 0, for w = 5, raw H̄, and pre/post differences. Two exceptions show up among the uncorrected results:
- llama, adjusted, pre/post, w = 5: +0.022 [0.003, 0.042], p = 0.029.
- llama, adjusted, level, w = 10: S − P = −0.022 [−0.036, −0.008], p = 0.014.

Neither survives Benjamini–Hochberg correction (q ≥ 0.17).

**The only pattern that holds across specifications is placebo minus base (P − B).**
- llama, w = 10, adjusted: +0.034 [0.017, 0.052].
- qwen, w = 10, adjusted: +0.085 [0.044, 0.125]; 16/20 seeds positive.
- Both give Wilcoxon p ≤ 0.003 and BH q = 0.069.

In other words, entering donor content raises per-token entropy relative to base, and real communication does not add anything beyond that.

## 4. Interrupted time series, switch vs placebo (Table 3)

[s04_its → tables/table3_its_did.md]

**Difference-in-differences S − P**, from OLS with cluster-robust standard errors by seed (G = 20). The model includes action, agent, position, log n_tokens and log prompt_tokens.

| model | level Δβ₂ [95 % CI] | slope Δβ₃ [95 % CI] |
|---|---|---|
| gpt-4o-mini | −0.102 [−0.278, 0.074] | −0.013 [−0.041, 0.016] |
| llama-3.3-70b | +0.010 [−0.026, 0.046] | +0.004 [−0.001, 0.009] |
| qwen3-235b | −0.040 [−0.144, 0.064] | −0.005 [−0.017, 0.008] |
| pooled (mean of models) | −0.044 [−0.119, 0.032] | −0.004 [−0.016, 0.007] |

- **Sensitivity specifications:** exposure-defined D with onset at τ + 1, turns with ≥ 10 active runs, and READ/DECRYPT calls only. None gives a DiD S − P CI that excludes 0. Across all 96 DiD S − P tests (§9), no raw p-value falls below 0.05.
- **MixedLM** (random seed intercept plus a run:agent variance component) gives the same conclusion. Level S − P is −0.099 [−0.262, 0.064] for gpt, +0.009 [−0.036, 0.054] for llama and −0.043 [−0.118, 0.031] for qwen. The gpt and llama fits did not converge (flagged).
- **Where the arms do move:**
  - At t = 8, gpt-4o-mini's H̄ drops in switch (β₂ = −0.194 [−0.351, −0.037]).
  - Placebo also drops (β₂ = −0.092 [−0.180, −0.005]), while base does not (+0.011).
  - The S − B slope difference is negative in the pooled model (−0.016 [−0.026, −0.007]), and so is P − B (−0.012 [−0.019, −0.005]).
  - The post-switch changes are therefore shared with the placebo arm and cannot be attributed to communication.

## 5. Event study around real exposure (Table 5a)

[s05_event_study → tables/t5_event_study_summary.md; figs/<model>/f5_event_study.png]

**Receiver minus other agent.** This is the change from 3 turns before the event to 3 turns after, adjusted H̄, paired by event.

| model | τ_read | τ_use |
|---|---|---|
| gpt | +0.023 [−0.119, 0.161] | +0.169 [−0.046, 0.423] (n = 11) |
| llama | −0.005 [−0.049, 0.038] | −0.026 [−0.058, 0.008] |
| qwen | +0.058 [−0.036, 0.151] | +0.031 [−0.107, 0.171] |

Placebo exposure (gpt −0.076, llama +0.008, qwen +0.023) gives the same picture: every CI includes 0.

The one change that stands out is a rise in qwen's receiver H̄ after τ_read (+0.067 [0.005, 0.131]). It is not specific to communication: qwen's H̄ rises by a similar amount after *donor* exposure, both in the receiver (+0.082 [0.024, 0.142]) and in the non-exposed agent (+0.073 [0.007, 0.142]).

## 6. System coupling I(X₁; X₂) (Table 6)

[s06_coupling → tables/table6_coupling_prepost.md, t6_*; figs/<model>/f6_system_coupling.png]

Change in mean I − I_shuffled from before to after turn 8. It is computed over turns with ≥ 10 paired runs, with a delete-one-seed jackknife CI.

| model | base | placebo | switch |
|---|---|---|---|
| gpt-4o-mini | +0.064 [0.042, 0.085] | **+0.335 [0.180, 0.490]** | +0.169 [0.053, 0.285] |
| llama-3.3-70b | +0.0005 [−0.001, 0.002] | +0.042 [−0.005, 0.088] | +0.046 [0.005, 0.086] |
| qwen3-235b | −0.007 [−0.040, 0.025] | **+0.428 [0.227, 0.629]** | +0.252 [0.036, 0.469] |

- Coupling rises after turn 8 in both non-base arms, and by **more in placebo than in switch** for gpt and qwen. The hard Miller–Madow I behaves the same way.
- **Permutation null** (500 re-pairings per turn). The observed I − I_shuffled exceeds the null 95th percentile in few post-8 turns: switch 1/15 (gpt), 1/15 (llama), 2/9 (qwen); placebo 1/23, 1/23, 7/11. [logs/s06_coupling.txt]
- **Jensen–Shannon divergence** between the two agents' action distributions in the same run also rises after turn 8, similarly in placebo and switch. Pre-to-post change, placebo / switch: gpt +0.50 / +0.26; llama +0.23 / +0.21; qwen +0.49 / +0.46. [t6_js_prepost.md]
- **Interpretation.** Under this estimator, I increases whenever the agents' action mix changes at the same stage of the run across seeds, for example when both start reading and then submitting. That happens with donor content as much as with real communication. Base shows the dependence that comes from sharing the model, prompt and task (0 to 0.08 bits).
- **Criterion 1, same sign of ΔI_comm and ΔH_comm by seed.** ΔI_comm comes from per-seed jackknife pseudo-values over turns 8–17. The signs agree in 6/20 seeds (gpt), 9/19 (llama) and 9/20 (qwen): **24/59 = 41 %**. [t6_criterion1_summary.md]

## 7. Functional form (Table 4)

[s07_functional_form → tables/table4_functional_form_summary.md, table4b_zhu_param_differences.md; figs/<model>/f7_functional_form.png]

We fitted the damped-oscillation model H̄(t) = A e^{−λt} sin(ωt + φ) + β ln(1 + t) + H₀ to call-level H̄ and compared it with four null models: constant, linear, logarithmic, and a cubic spline with df = 4. The metrics were Gaussian AIC/BIC and leave-one-seed-out (LOSO) mean squared prediction error.

- **Full series (t = 1–30), raw H̄.**
  - The Zhu model has the lowest LOSO error in 8 of the 9 model × condition cells; the exception is qwen base, where the spline wins.
  - The margins are small in most cells. For gpt-4o-mini LOSO MSE is 0.1486 vs 0.1504 (base), 0.1409 vs 0.1412 (placebo) and 0.1851 vs 0.1856 (switch).
  - llama-3.3-70b is the exception, with a 24–28 % reduction. However, its raw fits for base and switch predict values outside [0, log₂ 20], so those two are not retained.
  - BIC, which penalises the model's 6 parameters, prefers a null model in 5 of the 9 raw full-series cells (all gpt and qwen cells except qwen switch, where BIC is tied at −1614).
- **Post-switch segment (t ≥ 8).**
  - Zhu wins out of sample and is retained only for llama raw H̄ (base, placebo, switch) and for llama placebo adjusted H̄.
  - Zhu also has a nominal LOSO win for qwen placebo raw H̄ (0.05568 vs 0.05578). It is not retained, because qwen's post segments have n/k < 50.
  - Every other gpt-4o-mini and qwen cell is predicted equally well or better by a null model (constant, linear or spline).
  - [table4_functional_form_summary.md]
- **What the fitted shape reflects.** The early "oscillation" (t = 1–4, see f7) follows the fixed opening sequence every arm goes through: decrypt, then write, then read. It appears identically in base, placebo and switch.
- **Does the form change with communication?** Parameters were fitted on the post segment (seed bootstrap, 200 resamples) and compared between arms. **None** of the 36 switch − placebo parameter differences (3 models × 2 targets × 6 parameters) exceeds twice the bootstrap spread. The largest ratio is 1.82 (qwen adjusted λ). Among switch − base and placebo − base differences, 5 and 5 of 36 are flagged, respectively. [table4b_zhu_param_differences.md]
- **Criterion 3 verdict: not met.** The functional form beats the null models out of sample only marginally, mostly on the full series, and equally in every arm. Where it does win, its shape does not distinguish switch from placebo.

## 8. Early-warning detector (Table 5)

[s08_detector → tables/table5_detector.md; figs/<model>/f8_detection_curve.png]

**Setup.**
- **Signals**, computed per run and per agent: H̄ (renormalised entropy), surprisal S, action-distribution entropy H(q), and the Jensen–Shannon divergence between the two agents' action distributions.
- **Detectors:** two-sided CUSUM (k = 0.5) and Page–Hinkley (δ = 0.5), applied to z-scores relative to the run's own turns 1–7.
- **Thresholds:** calibrated on base and placebo runs of the training seeds only, for target false-alarm rates of 5 % or 10 %. They were evaluated with leave-one-seed-out cross-validation and with 50 repeated 10/10 seed splits.

Main results (CUSUM, 10 % target false-alarm rate, LOSO):

| model | signal | TPR | P(alarm before τ_use) | FAR base / placebo | AUROC (full) [95 % CI] | AUROC, turns 8–17 |
|---|---|---|---|---|---|---|
| gpt-4o-mini | H̄ | 0.05 | 0.05 | 0.15 / 0.10 | 0.35 [0.19, 0.54] | 0.44 |
| gpt-4o-mini | JS | 0.20 | 0.15 | 0.15 / 0.10 | 0.44 [0.29, 0.58] | 0.47 |
| llama-3.3-70b | H̄ | 0.10 | 0.00 | 0.15 / 0.11 | 0.47 [0.34, 0.59] | 0.63 |
| llama-3.3-70b | S | 0.15 | 0.00 | 0.25 / 0.00 | 0.53 [0.35, 0.69] | 0.61 |
| qwen3-235b | H̄ | 0.11 | 0.00 | 0.20 / 0.05 | 0.30 [0.15, 0.47] | 0.35 |
| qwen3-235b | JS | 0.05 | 0.05 | 0.15 / 0.10 | 0.53 [0.35, 0.69] | 0.56 |

- **Sensitivity is low.** Across all 48 channel-agnostic configurations (3 models × 4 signals × 2 detectors × 2 false-alarm targets), TPR ranges from 0 to 0.20. P(alarm before τ_use) is at most 0.15. The out-of-sample false-alarm rate in base runs is often above the target (0.05–0.25), because the thresholds come from only 19 training seeds.
- **AUROC is at chance or below.** Full-horizon AUROC ranges from 0.27 to 0.53, and every 95 % CI includes 0.5 or lies below it. Part of the below-0.5 values is a survival artefact: switch runs end earlier and so have fewer turns in which to accumulate the maximum statistic. Scoring every run on turns 8–17 only moves AUROC to 0.35–0.63, and no signal separates switch from base + placebo consistently across models.
- **Lead times.** Where alarms occur, the median lead relative to τ_use is positive for gpt-4o-mini (4–6 turns, from 1–4 alarmed runs) and negative for llama (−2.5 to −14) and qwen (−4). In the latter two, alarms mostly come *after* the content has already been used.
- **Criterion 4 flags.** Only 2 of the 48 configurations formally satisfy P(alarm before τ_use) > max FAR: qwen JS with CUSUM or Page–Hinkley at the 5 % target. Each rests on a single alarmed run (1/19 = 0.053 against a false-alarm rate of 0.05), so they are not evidence of early warning.
- **Oracle comparison.** A detector that watches the channel itself, alarming at the first READ_LOG that returned real foreign entries, trivially catches 100 % of verified switch runs with no false alarms. It precedes τ_use in every run, with a median lead of 1 (gpt), 3 (llama) and 2 (qwen) turns. Moving the alarm to the first exposed call (τ + 1) still precedes τ_use in 35 %, 60 % and 58 % of runs. The entropy signals recover essentially none of the information the channel oracle has.
- **Criterion 4 verdict: not met.**

[s08_detector → tables/table5_detector.md, t8_detector_run_level.csv; figs/<model>/f8_detection_curve.png]

## 9. Robustness and multiplicity

[s09_robustness → tables/table9a_*, table9b_*, table9c_multiplicity.md, t9_*]

- **Metric and action-set sensitivities.** The conclusions of §3–4 hold with H_lower, with the clean H̄ (tokens in the top-20 only), after excluding WRITE/SUBMIT calls, and with both clean H̄ and that exclusion together. For qwen with clean H̄, the level DiD S − P is −0.042 [−0.149, 0.065]; with the exposure definition it is −0.013 [−0.131, 0.105]. The qwen artifact therefore does not produce, or hide, a switch-specific effect.
- **Multiplicity (Benjamini–Hochberg within each family).**
  - Endpoints: 432 tests, 48 with raw p < 0.05, **0 with q < 0.05**, and 21 with q < 0.10. All 21 are placebo − base contrasts (llama and qwen, positive).
  - ITS DiD S − P: 96 tests, 0 with raw p < 0.05.
- **Placebo contamination.** Almost every placebo run is contaminated: 17/20 for gpt-4o-mini, all 19 valid llama runs, and 20/20 for qwen. A clean-vs-contaminated comparison can therefore only be made for gpt-4o-mini, with just 3 clean runs. That makes it uninformative (pre/post adjusted H̄: clean +0.106, contaminated +0.061). [t9_placebo_contamination_split.md]
- **Gate pilot (descriptive only, not pooled).** `tables_gate` contains 18 switch runs: gpt 9, llama 6, qwen 3. The switch pattern is reproduced: communication_verified = 1.0 in all three models, success 0.78 / 1.00 / 1.00, and median first foreign read at turn 9 / 9 / 8. [t9_gate_replication.md]

## 10. Pre-registered interpretation criteria

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | ΔH_comm and uptake-adjusted ΔI have the same sign in most paired seeds | **Not met.** Same sign in 24/59 seeds (41 %): gpt 6/20, llama 9/19, qwen 9/20. | §6; t6_criterion1_summary.md |
| 2 | Post-switch change present in switch and absent in placebo (DiD ≠ 0) | **Not met.** DiD S − P CIs include 0 for every model, every specification and the pooled model (0/96 tests with p < 0.05). Donor content alone raises H̄ (P − B > 0 for llama and qwen) and raises I − I_shuffled as much as or more than switch. | §3, §4, §6, §9 |
| 3 | Functional model beats nulls out of sample | **Not met.** Small LOSO gains, mostly on the full series and equally in every arm. BIC often prefers a null. No switch-vs-placebo parameter difference exceeds 2× the bootstrap spread. | §7 |
| 4 | Alarms precede τ_use more often than they fire in base or placebo | **Not met.** P(alarm before τ_use) ≤ 0.15 against FAR up to 0.25. The only two formal passes rest on a single alarm. AUROC ≤ 0.63. | §8 |

**Conclusion.** In exp1 the pilot does **not** support the hypothesis. With per-token predictive entropy (top-20), action-level mutual information and the detectors tested, real communication between two API agents cannot be distinguished from task-relevant content injected from an unrelated run. Nor do these signals anticipate observable uptake.

The result is negative for this design rather than a demonstration that no such signal exists. The design has specific limits:
- n = 20 seeds per cell.
- A fixed k* = 8 and fixed asset roles.
- A placebo that is task-relevant, so it contaminates submissions and changes behaviour in its own right.
- Truncation to the top-20 logprobs, and a provider artifact in qwen3-235b's top-k lists.
- Early termination of successful runs, which introduces a survival bias.
- A cross-run mutual-information estimator that measures co-variation across seeds, not coupling within a run.

What does hold across models is that agents' behaviour and entropy change when *any* new task-shaped content enters their context (placebo ≈ switch). A channel-aware signal, such as the read oracle, remains far more informative than any entropy summary tested here.
