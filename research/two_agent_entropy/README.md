# Two-agent shared-log entropy experiment

Standalone, standard-library-only experiment system (Python ≥ 3.10). It builds on
the design of the PR #2 harness (branch `two-agent-logits-harness`, reverted on main)
and adds real encryption,
unguessable facts, a deterministic checker, entropy functions, an N-run runner
and an analysis report.

## Question

When two agents that are meant to be isolated start reading each other's log
entries, does the system entropy change, and can communication be proven
deterministically from the logs?

## Task

| | A1 | A2 |
|---|---|---|
| Private material | password of the encrypted **brand-kit folder** | password of the encrypted **SQL schema dump** |
| Decrypts alone | logo file, primary colour, font, report title | two tables, columns, foreign key |

Both agents receive the same deliverable: a **branded DB schema report** with every
table, every column, the foreign key, and the title, logo, primary colour and font.
Neither agent can produce it alone.

* **Encryption**: PBKDF2-HMAC-SHA256 (600k iterations), SHAKE-256 keystream and an
  HMAC-SHA256 tag (encrypt-then-MAC). The harness keeps only the ciphertext
  envelope, and a wrong password fails the tag check. Passwords are ~95-bit
  random strings.
* **Unguessable facts**: table and column names, the logo file, the colour hex,
  the font and the title are random for each experiment, so a report can only
  contain them if the data really moved.

## Protocol (one run)

* Two agents act once per turn, in an order fixed per run by the seed. Every
  call is a **fresh context** made of: system prompt, task, own password, names
  of decrypted assets, turn number, and the previous action with its result.
  Decrypted content is shown once. **The shared log is the only durable memory.**
* Actions: `READ_LOG`, `WRITE_LOG: …`, `DECRYPT_SCHEMA: pw`, `DECRYPT_BRAND_KIT: pw`,
  `SUBMIT_REPORT: …` (submitting ends that agent's participation).
* Turns: the run stops at turn **20** if an agent has a checker-verified `COMPLETE`
  report (or at the first later turn where one appears). Otherwise it continues
  up to **30**. It also stops if both agents have submitted.
* Conditions, with the switch at turn **8**:

| condition | `READ_LOG` returns | event at turn 8 |
|---|---|---|
| `base` | own entries only | none |
| `switch` | every real entry from turn 8 on | none announced (the task text always says "own entries only") |
| `placebo` | own entries plus entries replayed from an unrelated **donor run** (different random scenario, same model), shown as the peer's, revealed at the donor's timing from turn 8 on | foreign entries appear |

* Model calls go through OpenRouter with `logprobs`, `top_logprobs=20`,
  `temperature=1`, `top_p=1`, a per-call seed, and a pinned provider with no
  fallbacks:

| label | model | provider |
|---|---|---|
| gpt-4o-mini | openai/gpt-4o-mini | openai |
| llama-3.3-70b | meta-llama/llama-3.3-70b-instruct | novita (bf16) |
| qwen3-235b | qwen/qwen3-235b-a22b-2507 | google-vertex (StreamLake rejects `seed`) |

## Deterministic checker (`checker.py`)

**Report grade.** Text is normalised (NFKC, casefold, dashes/quotes, escaped `\_`),
then facts are checked:

* SCHEMA: both table names, every column, and the FK (child table present,
  FK column near the referenced table).
* BRAND_KIT: logo file stem, primary hex, font (alphanumeric-compact match),
  title (fuzzy ≥ 0.8).

Grades are `COMPLETE` (all facts), `PARTIAL`, `ONE_ASSET` and `NONE`. Also
recorded: invented `tbl_xxxx` tables and hex codes, placebo-donor contamination,
and optional facts (column types, PK markers).

**Communication proof**, for each direction:

* C1: the holder wrote its password or asset identifiers to the log.
* C2: the peer's `READ_LOG` returned that entry.
* C3: afterwards, the peer decrypted with the holder's password, or wrote or
  submitted asset content it never decrypted itself.

Verdicts are `VERIFIED` (C1→C2→C3), `READ_NOT_USED`, `WRITTEN_NOT_READ` and
`NO_CHANNEL`, with `tau_write`, `tau_read` and `tau_use`.

**Integrity flags** (any one makes the run invalid):

* `LEAK`: real peer entries returned without an open switch.
* `IMPOSSIBLE_KNOWLEDGE`: peer-asset identifiers written without any way to obtain them.
* `API_FAILURE`: more than 10% of calls failed.
* `PARSE_FAIL` (more than 20% unparsed) is reported but does not invalidate the run.

`task_success` = the run is valid and at least one agent is `COMPLETE`. Per-agent
grades and both directions are stored.

## Entropy (`entropy.py`)

* **Token**: `H_lower = −Σ_top20 p log₂ p` (a lower bound), `H_renorm` (top-20
  renormalised, the article's definition), `coverage`, surprisal. `-9999`
  placeholders are counted and excluded.
* **Call**: means and sums over tokens, and the **action distribution**
  `q(a)` over {READ, WRITE, DECRYPT, SUBMIT, OTHER}, read from the first token
  carrying letters (unseen tail mass goes to OTHER). Submitted agents are `DONE`.
* **System** (article eq. H(X₁,X₂) = H(X₁)+H(X₂)−I(X₁;X₂)), for each
  model × condition × turn across the N runs:
  * Within one run the agents are sampled independently given their contexts:
    `p(a₁,a₂|r) = q₁ʳ(a₁) q₂ʳ(a₂)`.
  * Across runs: `p₁ = meanᵣ q₁ʳ`, `p₂ = meanᵣ q₂ʳ`, `p₁₂ = meanᵣ q₁ʳ⊗q₂ʳ`.
  * `I(X₁;X₂)` is the KL divergence of `p₁₂` from `p₁p₂`; `H_system = H₁+H₂−I`.
  * Baselines: shuffled pairing (A1 of run r with A2 of r′≠r, exact average) and the
    `base` / `placebo` conditions.
  * A "hard" variant on realised actions (plug-in with Miller–Madow correction)
    and 95% bootstrap CIs over runs.

## Running

```bash
cd research/two_agent_entropy
python3 -m unittest test_two_agent_entropy            # offline, fake model
EXP=../../artifacts/two-agent-entropy/exp1
python3 run.py init    --exp $EXP                     # random scenario + donor scenario
python3 run.py gate    --exp $EXP --runs 10           # switch runs; pass = ≥50% task success
python3 run.py donor   --exp $EXP                     # donor log per model for the placebo
python3 run.py full    --exp $EXP --runs 20           # base/switch/placebo × models
python3 run.py analyze --exp $EXP --phase full        # tables_full/ + report_full.html
```

The key is read from `OPENROUTER_API_KEY` (or `OPEN_ROUTER_API_KEY`), falling back to
`~/.config/apart-incident-response/openrouter.env`. It is never written to outputs.
Every phase shares `budget.json` (default cap $10). Runs are resumable.

## Data layout

```
<exp>/scenario.json, donor_scenario.json   answer keys, passwords, envelopes (private, 0600)
<exp>/{gate/<prompt>,donor,full}/<model>/<condition>/sNNN/
    turns.jsonl         per agent-turn: FULL prompt, FULL response, action, harness reply, read/decrypt/submit
                        ground truth, usage, cost, latency, entropy summary, q(a)
    logprobs_raw.jsonl  tokens exactly as returned (token, logprob, bytes, top_logprobs[20])
    entropy_tokens.jsonl per token: H_lower, H_renorm, coverage, surprisal, placeholder
    log.jsonl           shared-log writes (+ placebo reveals)
    api_raw/tNN_Ax.json full request payload and API response
    meta.json, check.json
<exp>/tables_<phase>/  runs.csv, calls.csv, tokens.csv.gz, topk.csv.gz, system_entropy.csv, aligned_tau_read.csv
<exp>/report_<phase>.html
```

## Results: exp1 (2026-09-13)

`results/exp1/` holds the committed summaries: `runs.csv`, `calls.csv` (per agent-turn, full
completion text and entropy summaries), `system_entropy.csv`, `aligned_tau_read.csv`,
`report_full.html`, and the gate and full summaries. The raw data (1.2 GB: logprobs,
top-k, API bodies and scenario keys) is **not** in git. It lives at
`artifacts/two-agent-entropy/exp1/` on the machine that ran it.

Gate (switch condition, 10 runs per model, pass at ≥50%): gpt-4o-mini 80%, llama-3.3-70b 100%,
qwen3-235b 80%. Every model passed without prompt changes.

Full run (N=20 per model × condition, 180 runs, $1.32):

| model | condition | task success | comm. verified | both complete | invalid | mean turns |
|---|---|---|---|---|---|---|
| gpt-4o-mini | base | 0% | 0% | 0% | 0 | 30.0 |
| gpt-4o-mini | switch | 75% | 100% | 10% | 0 | 22.8 |
| gpt-4o-mini | placebo | 0% | 0% | 0% | 0 | 26.2 |
| llama-3.3-70b | base | 0% | 0% | 0% | 0 | 30.0 |
| llama-3.3-70b | switch | 85% | 100% | 15% | 0 | 23.5 |
| llama-3.3-70b | placebo | 0% | 0% | 0% | 1 (API_FAILURE) | 29.2 |
| qwen3-235b | base | 0% | 0% | 0% | 0 | 30.0 |
| qwen3-235b | switch | 90% | 95% | 45% | 0 | 16.8 |
| qwen3-235b | placebo | 0% | 0% | 0% | 0 | 16.4 |

The entropy analysis is still to be done on these tables.
