# METHODS_DELTA — what `metodology.tex` must change to describe exp1

Target file: `apart-incident-response/report/content/metodology.tex`.
Every item below is verified against the exp1 data; the script or file that shows it is given in brackets.

## 1. Opening paragraph
- Remove "written as a pre-registered protocol … before model data are collected" and "five-seed cells". exp1 has already been run:
  **3 models × 3 conditions × 20 seeds = 180 runs**, plus a 10-seed gate pilot and 3 donor runs. [s00_integrity; runs.csv]
- The analysis is exploratory (n = 20 seeds per cell). Keep the "no causal/significance claim" caveat but tie it to n = 20.

## 2. Environment and shared log (replace §Environment)
- There is **no Pi harness, sandbox, SQLite board, triggers, 8 KiB limit, 50-message page, or read cadence N**. Replace with the actual loop:
  - a controller calls the model once per agent per turn (OpenRouter chat completions), `max_turns = 30`, `max_tokens = 700`,
    `temperature = 1.0`, `top_p = 1.0`, `top_logprobs = 20`, prompt version `v1` [experiment.json];
  - **one action per message**, parsed from the first line: `READ_LOG`, `WRITE_LOG: <text>`, `DECRYPT_SCHEMA: <pwd>`,
    `DECRYPT_BRAND_KIT: <pwd>`, `SUBMIT_REPORT: <report>` (submit ends the agent's participation);
  - the agent's **context is wiped every turn**; the prompt shows only private materials, the list of decrypted assets, and the
    previous action with its result. The append-only log is the only persistent memory [turns.jsonl `messages_sent`];
  - consequence for timing: a `READ_LOG` result is shown in the prompt of the agent's **next** call, not in the call that issued it
    (the text generated at τ_read is produced before the entries are seen) [s05 docstring; turns.jsonl];
  - early stop: from turn 20 the run stops once a complete report exists (`complete_by_turn_20@N`); otherwise it stops when both agents
    submitted or at 30 turns [runs.csv `stop_reason`: 79 max_turns, 78 all_submitted, 23 complete_by_turn_20].
- Turn order: two agents act sequentially within a turn; the order **rotates with the seed** (A1 first in seeds 2, 3, 5, 8, 11, 14,
  16, 19, 20; A2 first otherwise) and is identical across conditions and models for a given seed [s00; t0_turn_order_by_seed.csv].
  Note: ANALYSIS_PROMPT.md stated "A1 always position 0", which is incorrect.

## 3. Task (replace §Task entirely)
- Not an incident diagnosis. Both agents must deliver the **same report**: the SQL schema (tables, typed columns, the foreign key) and
  the branding (title, logo, primary colour, font). Both assets are encrypted; each agent holds **one** password.
- **Roles are fixed, not rotated**: A1 always holds BRAND_KIT, A2 always holds SCHEMA, in all 180 runs [s00]. Agent identity is
  therefore confounded with asset role.
- A complete report **requires** information from the other agent (no single role suffices), unlike the "deployment role can succeed
  alone" caveat in the current text. Task success is therefore not independent of communication.
- Grading: deterministic checker with fact lists per asset (`facts` in scenario.json) → grades NONE / PARTIAL / ONE_ASSET / COMPLETE;
  also records invented tables / hex colours and donor contamination [check.json].
- Seeded traceable markers exist per asset (table/column names, logo file, hex colour, font); these replace `ORCHID-731`.

## 4. Conditions (replace the C0/C1/C2/S/P list)
| exp1 label | What READ_LOG returns | Methodology analogue |
|---|---|---|
| `base` | own entries only, turns 1–30 | C2 (private read) |
| `switch` | own entries in turns 1–7; **all** entries from turn 8 | S, but with **k\* = 8 fixed**, not randomised |
| `placebo` | own entries always; from turn 8 also entries of a **donor run** (switch run on `schema-brand-donor-v1`, same task, different facts) | P, but the injected content is **task-relevant in form**, not irrelevant, and it is many entries (all donor log entries), not one identical message |
- **C0 (no log) and C1 (shared from turn 1) were not run.** Remove them, or mark them as future work. ΔH_comm must be redefined as
  S − ½(B + P) over the post window.
- Placebo is imperfect: donor facts were copied into submissions in 17/20 (gpt-4o-mini), 20/20 (llama) and 20/20 (qwen) placebo runs
  [table1_descriptives `placebo_contaminated_runs`]. No agent tried to decrypt with donor passwords (0 attempts).
- Exposure actually delivered differs by model: donor entries reached gpt-4o-mini agents in 59 reads, llama in 330, qwen in 164;
  real foreign entries in switch: 54, 244, 194 reads [t0_exposure_by_agent.csv].
- Condition order was not rotated per seed at run time. Runs were executed in model × condition blocks, always in the order
  base → switch → placebo, with the 20 seeds of a block launched together. For example, gpt-4o-mini base started at 00:37,
  switch at 00:38 and placebo at 00:40 UTC, and the whole experiment ran from 00:37 to about 01:09. Condition is therefore
  confounded with wall-clock time and provider load at the scale of minutes. [meta.json `t_start_utc`]

## 5. Validity and missing data
- One invalid run (llama-3.3-70b placebo s3, `API_FAILURE`) and 98 HTTP-429 call failures (96 on llama) are kept and flagged;
  the invalid run is excluded from paired contrasts involving its seed [s00; s03 `missing_seeds`].

## 6. Models and configuration (replace Table `tab:configuration`)
- Agent models (via OpenRouter): `openai/gpt-4o-mini` (provider OpenAI), `meta-llama/llama-3.3-70b-instruct` (Novita),
  `qwen/qwen3-235b-a22b-2507` (returned provider Google). No `gpt-5.6-luna`, no reasoning effort, no factor levels for n, tool profile,
  difficulty or cadence: **n = 2 agents only**.
- Budget: total spend \$1.32 [budget.json; full.log].
- **There is no measurement model** (no Qwen3-8B, no teacher forcing, no full-vocabulary logits). Entropy comes from the acting
  agent's own API top-20 logprobs.

## 7. Measurements (rewrite §Measurements)
- Token entropy is computed from the top-k = 20 returned logprobs, not over the full vocabulary. Two variants, with their exact
  definitions as verified by recomputation [s02; t2a_token_entropy_recompute]:
  - `H_lower = −Σ_{top-k} p log2 p` (truncated sum; **no** term for the residual mass — the "block" variant does not match the data);
  - `H_renorm = −Σ_{top-k} p̃ log2 p̃`, p̃ = p / Σ_{top-k} p;
  - coverage = Σ_{top-k} p (median 1.0; 1.6 % / 1.0 % / 0.4 % of tokens below 0.99 for gpt / llama / qwen).
  Values are comparable only within a model, across conditions and turns.
- **Data-quality caveat for qwen3-235b**: in 35 % of qwen tokens the sampled token is not in the returned top-k list, often because
  the provider returned the previous token's list again; the builder then sets surprisal to 0 and coverage to 1. The share of affected
  tokens per call differs by condition (≈7 % base vs ≈14–15 % switch/placebo), so qwen entropy contrasts carry a measurement confound.
  Report the "clean" metric (valid tokens only) as a sensitivity [s09; t9_token_validity_audit].
- Step entropy H̄_{i,r,t} = mean token entropy of the call; response length, prompt length and action type are recorded.
- System level: **the random variable X_i is the agent's action class** (READ/WRITE/DECRYPT/SUBMIT/OTHER/DONE), with a soft
  distribution q from the logprobs at the action token. Not quantile bins of step entropy. The estimator actually used
  (reproduced to 1e-15) [sysent.py; s02; t2b]:
  - p_i = mean over paired runs of q_i; joint P(x1,x2) = mean_r q1_r(x1) q2_r(x2); I = H(p1) + H(p2) − H(P);
  - I_shuffled uses all cross-seed pairs (exact, not sampled); hard I uses realised actions with a Miller–Madow correction;
  - statistics are NaN when fewer than 2 paired runs remain.
  State explicitly that this I measures co-variation of the two agents' action distributions **across runs at the same turn**
  (a run-index effect), not within-run coupling, and that I_shuffled is ≈ 0 by construction, so I − I_shuffled ≈ I.
- Uptake: replace the four-condition token rule with the checker's directional chain **C1_written → C2_read → C3_used** per
  direction (A1→A2, A2→A1), with verdicts WRITTEN_NOT_READ / READ_NOT_USED / VERIFIED and event times τ_write, τ_read, τ_use;
  `communication_verified` = at least one VERIFIED direction. Also `password_source = peer` (4 successful decrypts with a password
  read from the log) [check.json; runs.csv].

## 8. Analysis (edit §Analysis)
- Endpoint contrast: C1/C0/C2 → S/B/P, post window fixed at turns 8..8+w−1 (w ∈ {5, 10}), adjusted for action and response length;
  pre/post variant; bootstrap over seeds, sign and Wilcoxon tests [s03].
- ITS: k* is fixed (8) for all runs; D_{r,t} = 1[t ≥ 8]; covariates log n_tokens, log prompt_tokens, action, agent, within-turn
  position; base included as the natural-trend arm; exposure-defined D with onset at τ+1 as sensitivity [s04].
  MixedLM with seed intercept + run:agent variance component did not converge for gpt-4o-mini and llama (reported); cluster-robust
  OLS by seed is the primary estimator.
- The "Validation as an early-warning signal" item must say that the baseline window (turns 1–7) uses knowledge of k*, thresholds
  are calibrated on base + placebo (not C0/C2), and that switch runs are shorter than base runs (survival), which is handled by a
  truncated false-alarm rate [s08].
- Remove "execution order of the conditions is rotated with the seed" unless it can be shown.
- Replace "five seeds" everywhere with 20; bootstrap intervals are still descriptive.

## 9. Limitations to add
- Fixed k* = 8 (switch confounded with within-run time); fixed roles; placebo is task-relevant and contaminates submissions;
  top-20 truncation; qwen top-k artifact; survival/censoring (switch and qwen placebo runs end early); n = 2 agents only;
  API nondeterminism and 429 retries.
