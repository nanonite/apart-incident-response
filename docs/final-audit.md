# Restricted communication experiment audit

Date: 2026-09-13. Inspected base: `1d8af2f`. Baseline: 170 tests, two optional skips.

## 1. Existing architecture and data flow

`experiment.py` freezes a two-agent response_dynamics_v1 configuration, creates both observations from the previous committed checkpoint, executes physical inference serially, validates structured answers, and appends events. `events.py` uses SQLite transactions and a hash chain with no-update/no-delete triggers. These provide ordinary write protection and tamper evidence, not protection against a privileged host rewriting the database. `tasks.py` and `locked_database.py` own synthetic inputs; the latter verifies B's key against encrypted local data. `adapters.py` owns transport. `analysis.py` consumes stored dictionaries without running agents. `panel.py` projects the logs and exports them; vanilla dashboard views cover comparison, inspection, handoff, and per-agent visibility.

## 2. Section 8 requirements

Keep its text unchanged. It permits only bounded task/board tools and forbids shell, writes, edits, network, shared filesystem, git remote, general HTTP, external MCP, subagents, and uncontrolled shared memory. The response runner exposes no tools. Local model transport is controller-owned. New tasks must fit structured proposals and controller evaluation, not interactive real targets.

## 3. Conflicts and resolutions

The plan says no runtime exists although several runtimes now exist; legacy protocol C2 is different from response_dynamics_v1 C2. Historical records must retain their protocol identity. The plan links to missing semantic-entropy-live-plan.md; this audit documents the implemented adaptation. Five checkpoints are not minute-paced. The plan says never fabricate updates, while later user requirements explicitly demand stalled placeholders. Preserve those placeholders with empty response and controller origin, exclude them from answer distributions, and distinguish unattempted missing cells. The adapter's logprob fallback retries despite max_retries=0: remove silent retries and fail transparently. Prompt incentives are not learned reward optimization; neither requires or establishes model training. Frozen role schedules are predeclared input progression, not adaptive configuration mutation.

## 4. Failure modes and confounders

Controller timeouts can leave provider requests running, so additional requests can queue and contaminate timings. Request ownership and heartbeat are missing from the log. Transport timeouts, output token caps, context preflight, validation failures, and whole-run deadlines are independent. Raising only deadline_seconds does not change any other limit. Completed runs can contain stalled answers. Provider hidden prompts, KV cache, exact seed determinism and cancellation remain partly unobservable. Existing communication_used means delivery, and peer-reference detection is a lexical proxy. Context hashes in observations and grids used different serialization; unify future exports. Aggregate strata must separate roles and protocol/model provenance. Keys change across repeats, so their distributions describe seeded task families, not one fixed input. Context length and physical ordering require recorded controls. Global-state resource games could leak teammate activity in C0 and need a separate explicit task-state observation policy.

## 5. Supported claims

Fixture tests show C0 hides peer history, C2 delivers permitted prior messages at the unlock boundary, and the evaluator can verify a copied key. Completed fixture data is plumbing evidence only. The inspected older batch had 54 submitted and 66 missing planned updates with no batch terminal event. An earlier tiny Ollama probe delivered a key but B did not use it successfully. These data justify diagnostics, not a model ranking. Hash verification and export cutoffs make recorded outcomes auditable.

## 6. Unsupported claims

No established LLM collaboration improvement, attention measurement, causal influence, epistemic/aleatoric decomposition, or semantic-entropy result follows from the present traces. A longer wait is not extra reasoning unless the provider actually generates useful additional output. A constant entropy value can accompany a meaningful shift from unanimously wrong to unanimously correct. More dialogue is not automatically better coordination. Papers on general agent frameworks do not validate this restricted task environment.

## 7. Proposed experiments and hypotheses

| Study | Manipulation and matched control | Hypothesis / falsifying result |
|---|---|---|
| Evidence | Split clues vs identical complete evidence; C0/C2 | Sharing helps split evidence more; no interaction challenges the hypothesis |
| Roles | Planner/critic vs two solvers with the same evidence | Role-specific checks improve correctness; more references without improvement is insufficient |
| Contradiction | Require a counterexample vs neutral explanation | Invalid plans are rejected more often; shared wrong plans falsify the expected benefit |
| Bandwidth | Unlimited eligible history vs whole-message byte budget | Smaller context preserves useful uptake at lower cost; missing critical facts may reduce performance |
| Engagement | Neutral vs peer review vs required reference; separate batches | More valid evidence references improve task score; empty compliance does not count |
| Reward framing | Team score description vs team+individual score description | Prompt framing affects performance; these are fixed inference prompts, not trained rewards |
| Requested context | Predeclared request gate vs automatic delivery | Agent requests identify useful opportunities; delivery alone is not spontaneous cooperation |
| Role rotation | Predeclared role swap vs fixed roles; swap distinct from unlock | Transfer survives role changes; role violations or performance loss challenge robustness |
| Time | 300 vs 900 seconds, same model/output cap/request budget | Fewer deadline losses; unchanged performance after timely completions rejects a pure time explanation |
| Replay | Same frozen B observation with peer content visible/masked | Behavioral changes establish a controlled message intervention; one pair remains a noisy behavioral contrast |

Only two agents. Begin with one task, C2, five checkpoints, two repeats; fixture then local Ollama. Keep model, task seed, role schedule, serializer, prompt, bandwidth, and budgets fixed within a batch. Use held-out seeds after calibration. Change one factor at a time before a larger factorial study. Budgets cap execution; they do not guarantee every checkpoint is attempted.

## Task catalog and scoring design

| Family | Objective / observations | Contract and message | Individual / joint score | Redundancy and communication cost | Failure modes / truth |
|---|---|---|---|---|---|
| Complementary evidence | Identify fault from independent binary sensors; each agent sees one sensor; identical-complete control sees both | Solver cites evidence IDs and proposes fault | Correct answer per solver; fraction of correct solver answers | No redundancy penalty; logged optional byte cost | Guessing/leakage; unique truth table answer |
| Role investigation | Choose valid repair plan; both receive all requirements | Planner cites supporting constraints; critic supplies a counterexample to a rejected plan | Answer correctness plus separately scored cited constraints; joint mean | No default penalty; byte cost separately reported | Role labels without valid role actions; exact constraint oracle |
| Contradiction | Distinguish correlated change from failed controlled test; same evidence for both | Analyst proposes mechanism, critic cites disconfirmation | Correct diagnosis and check quality separately; joint mean | No default redundancy penalty | Sycophancy; exact synthetic diagnostic oracle |
| Resource allocation (design only) | Cover six synthetic checks with six total actions, two actions allowed per checkpoint | Agent proposes named check; controller resolves both proposals simultaneously | Unique findings per agent; joint coverage minus duplicates | Each duplicate consumes an action; configurable byte cost | Shared budget/progress can leak in C0. Must specify private vs public task observations before implementation |
| Communication cost | Apply byte limit/cost to any above task | Whole peer updates only; explicit eligible/delivered/omitted IDs; optional request gate | Base task scores unchanged; net utility exported separately | Cost per delivered UTF-8 byte, not token; repeated exposure counts again | Silence optimizes cost but fails task; exact byte ledger |
| Rotating roles | Same repair objective with fixed role swap checkpoint | Contracts swap according to stored schedule | Same per-role checks, stratified by actual role | Same communication policy in matched arms | Rotating at unlock confounds interventions; predeclare distinct steps |

Messages remain structured task proposals with source IDs. Prompting a request or reference never forces success. Raw task updates stay mandatory even when peer exposure is absent. No agent receives researcher scores during the baseline run.

## 8. Implementation order and contracts

1. Explicit request timeout, 900-second pilot preset, heartbeats and owner IDs, terminal attempt events, no silent retry; record unknown cancellation and stop scheduling more real requests after timeout.
2. Seeded complementary tasks, shared-evidence role tasks, role contract validation, whole-message communication filtering and byte/cost records.
3. Offline frozen-observation sampling/replay; artifact-only semantic judgments, complete partitions, probability models, uncertainty/confidence metadata and source IDs.
4. UI budget and policy controls; both task and batch clocks; calibration report and export additions.
5. Fixture-first tests, local bounded calibration, readable handoff; defer a statistical conclusion until enough matched valid runs exist.

Config additions: request_timeout_seconds (explicit override, otherwise legacy min(timeout_seconds, minute_seconds)); heartbeat_seconds; deadline_seconds (legacy 300; pilot 900); communication_budget_bytes (null = unlimited); communication_delay_steps; communication_cost_per_kib; communication_request_required; role_swap_step; engagement_mode; calibration preset. Record resolved values and hashes. Preserve legacy names. No changes to active configs.

Offline contracts: FrozenObservation with exact messages, task/version, prompt/config/model metadata, role, seed and source IDs; Sample with context hash, generation settings, raw and extracted response, attempt status and likelihood provenance; SemanticJudgment with both directional entailment decisions and judge version; Partition with exhaustive unique membership and rule/version; ProbabilityState with estimator/version, masses, coverage scope and source samples; Metric with base, sample count, optional bootstrap interval and limitations. A probability-weighted adapter must report whether it estimates the full model distribution or only normalized observed support.

## Metric catalog

Availability is a policy boolean; delivery is a recorded projection; source references are verifiable citations but not attention; exact correct-key copying is an uptake proxy; task success is evaluator truth. Answer-class entropy is a cross-run descriptive proxy. Fixed-context semantic entropy estimates diversity of meanings under a frozen prompt. Token surprise is sampled-token negative log probability, not vocabulary entropy. Top-k token data lack the full vocabulary. Replay answer changes are intervention contrasts with sample count and pairing metadata, not definitive causal estimates from a single seed. Latency, valid-output rate, stalls, omissions, context bytes, communication bytes/cost and role compliance accompany performance.

## Literature interpretation

Kuhn, Gal and Farquhar (2023), [Semantic Uncertainty](https://arxiv.org/abs/2302.09664), group fixed-input sampled answers by bidirectional entailment and aggregate meaning probabilities. Farquhar et al. (2024), [Nature semantic entropy](https://www.nature.com/articles/s41586-024-07421-0), also describe empirical semantic-cluster frequencies without token likelihoods. The interfaces here are an adaptation, not a replication of their QA results. Structured JSON wrappers and task-specific extraction complicate likelihood interpretation. Distinct evolving contexts cannot be pooled as fixed-input samples. Exact-string grouping is a lexical baseline only. Semantic judgments require a versioned human or model rule; no judge is silently substituted.

CAMEL and MetaGPT motivate role and workflow experiments; multi-agent debate motivates counterexample checks; sparse-topology work motivates communication cost. None implies that two prompted roles will beat two matched solvers here. No external websites were contacted during this audit; literature interpretation uses source content already available in this conversation. A current exhaustive SOTA review is outside this offline audit.

## 9. Planned file boundaries

Change: experiment.py, adapters.py, tasks.py, task_updates.py, analysis.py, panel.py, dashboard JS/HTML, focused tests and handoff docs. Add small collaboration task/communication, timing, offline sampling/semantic, and calibration modules. Preserve runtime.py, tests/test_runtime.py, bubblewrap, legacy tool/network bridges, existing event rows, credentials, and the preexisting dirty uv.lock/.chainlink/issues.db/analysis-extraction note. No C3, external targets, paid inference, or deployment.

Implementation results and exact changed files will be appended after verification. This preimplementation report distinguishes planned features from verified state.
