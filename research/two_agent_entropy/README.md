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
top-k, API bodies and scenario keys) is **not** in git. It is published as zstd archives
(164 MB) on the GitHub release
[`exp1-raw-data`](https://github.com/nanonite/apart-incident-response/releases/tag/exp1-raw-data):

```bash
gh release download exp1-raw-data -R nanonite/apart-incident-response -D exp1-release
cd exp1-release && sha256sum -c SHA256SUMS.txt
mkdir -p ../artifacts/two-agent-entropy
for f in *.tar.zst; do zstd -dc --long=27 "$f" | tar -x -C ../artifacts/two-agent-entropy; done
```

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

## Extensiones (schema_version 2)

Añadidas sin romper el esquema de salida v1 (véase `CAMBIOS.md` en el paquete de entrega):

| Novedad | Dónde | Cómo se activa |
|---|---|---|
| Condición `placebo_inert` (entradas ajenas genéricas, sin hechos) | `harness.make_inert_entries`, `inert_text_is_clean` | `run.py full --conditions placebo_inert` |
| Switch aleatorizado por semilla y cerrable | `RunConfig.switch_turn_range`, `RunConfig.close_turn_offset`; `meta.json["switch_turn_effective"/"switch_closed_turn"]`; `turns.jsonl["read_policy_this_turn"/"switch_open"]` | `run.py init --switch-range 5,9 --close-offset 4` |
| Compuerta de integridad de logprobs | `checker.logprob_integrity` → `check.json["logprob_integrity"]`, bandera `LOGPROB_STREAM_INCOMPLETE` (no afecta a `valid`) | siempre; `python3 checker.py <run_dir>` para corridas antiguas |
| Tres agentes (observador A3 sin contraseña) | `RunConfig.n_agents=3`, `scenario.OBSERVER`, `check.json["observers"]` | `run.py init --n-agents 3` |
| Proveedor Llama con flujo íntegro | `MODELS["llama-3.3-70b-sambanova"]` (`sambanova-turbo`, `supports_seed=False`) | `--models llama-3.3-70b-sambanova` |

Matriz E1/E5/E8 (ejemplos; cada experimento en su propio directorio porque la configuración se congela en `init`):

```bash
python3 run.py init --exp artifacts/two-agent-entropy/exp_e1 --scenario-from artifacts/two-agent-entropy/exp1
python3 run.py full --exp artifacts/two-agent-entropy/exp_e1 --models gpt-4o-mini,qwen3-235b,llama-3.3-70b-sambanova --conditions base,switch,placebo,placebo_inert --runs 20
python3 run.py init --exp artifacts/two-agent-entropy/exp_e5 --scenario-from artifacts/two-agent-entropy/exp1 --switch-range 5,11 --close-offset 4
python3 run.py full --exp artifacts/two-agent-entropy/exp_e5 --models gpt-4o-mini,qwen3-235b --conditions base,switch,placebo_inert --runs 20
python3 run.py init --exp artifacts/two-agent-entropy/exp_e8 --scenario-from artifacts/two-agent-entropy/exp1 --n-agents 3
python3 run.py full --exp artifacts/two-agent-entropy/exp_e8 --models gpt-4o-mini,qwen3-235b --conditions base,switch --runs 20
python3 run.py analyze --exp artifacts/two-agent-entropy/exp_e1   # idem e5, e8
```

`placebo` y `placebo_inert` necesitan `donor/<modelo>/donor_log.json` en el directorio del experimento (cópielo del
exp1 o ejecute `run.py donor`); `placebo_inert` sólo usa el calendario del donante, nunca su texto.

## Analysis (`analysis/`)

| File | What it does |
|---|---|
| `entropy_analysis.py` | General descriptive + exploratory analysis (A–J) of one experiment. Same outputs as the exp1 version (`figures/*.png`, `stats/*.csv`, `stats/summary.json`). |
| `analisis_e1.py` | The **preregistered** E1 analysis: one inference path, one primary measure, declared secondaries, power. Spanish output tables. |
| `figuras_informe.py` | Publication-grade report figures built from the `E1_*.csv` tables (no statistics of its own). |
| `test_entropy_analysis.py` | 11 offline tests of the analysis on synthetic tables (no network, no API). |
| `build_results_page.py` | Static HTML results page. |

`entropy_analysis.py` is no longer wired to the exp1 matrix. It discovers the models and
conditions present in the tables (`placebo_inert` and any future arm included), tolerates
missing model × condition cells, cuts pre/post at each run's own `switch_turn_effective`
(so the randomised/closable switch of E5 works, and `fig02d_event_aligned_trajectories.png`
is added when the switch turn varies), handles a third agent (observer `A3`: ground-truth
columns, and the system decomposition over every agent pair), and seeds every Monte-Carlo
estimate from a label so a p-value does not depend on how many other cells exist. Column
names are resolved through aliases, so both `analyze.py` tables (`tables_full/calls.csv`)
and the flat `exp_*_calls.csv.gz` tables are accepted.

```bash
python3 analysis/entropy_analysis.py <exp_dir>                     # uses tables_full/
python3 analysis/entropy_analysis.py --calls exp_e1_calls.csv.gz --runs exp_e1_runs.csv \
    --out analysis_e1 [--skip-system] [--entropy-valid-only]
python3 analysis/analisis_e1.py --calls exp_e1_calls.csv.gz --runs exp_e1_runs.csv --out analisis_e1
python3 analysis/figuras_informe.py analisis_e1 --out figuras_informe
python3 analysis/test_entropy_analysis.py                          # offline, ~40 s
```

Reproduction check: run on the exp1 tables, the generalised script reproduces every
point estimate of the original version exactly (run-level deltas, DiD, Hedges' g, AUC,
mixed-model coefficients, post-read means) and the permutation p-values within
Monte-Carlo error (median |Δp| = 0,003, max 0,014 over 36 tests), with every
significance call at α = 0,05 unchanged.

The preregistered path in `analisis_e1.py`: per-run Δ = mean(post) − mean(pre) of the
adjusted per-token entropy (residual of `H ~ C(action) + log1p(n_tokens)`, fitted per
model); six contrasts per model (inert−base, switch−base, decoy−base, switch−inert,
switch−decoy, inert−decoy); 20 000-replicate permutation over runs; Holm over the whole
primary family; equivalence declared at δ = 0,02 bits/token; declared secondaries
(decision entropy, share of complete reports, verified communication, action mix, turn of
first delivery) corrected in their own family; power reported as observed per-run SD,
achieved power and the n per cell needed for 0,80.
