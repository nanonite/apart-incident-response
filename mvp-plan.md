# Hackathon MVP: Response Dynamics Under Restricted Communication

## 1. Status and source of truth

This document replaces the previous three-agent accidental-board protocol. The user confirmed replacement, retention of Section 8, and retrospective C2 access to earlier permitted updates plus future updates. No context.md was found; this document is the restricted-setting source of truth.

Use protocol ID `response_dynamics_v1` with every condition ID. Old C2 meant permanent own-entry reads; current C2 means scheduled unlock. Never relabel historical artifacts. There is one active hackathon protocol, not two parallel studies.

Confirmed: two agents; C0/C1/C2 first; C3 optional and deferred; constant researcher logging; mandatory discrete updates; fixed configuration within each run. Proposed defaults below remain distinguishable from confirmed decisions.

## 2. Research questions

1. What changes in evolving solution distributions when information exchange becomes possible?
2. Does one agent's information affect the other's behavior under an intervention?
3. Can offline textual feedback improve configuration for the next batch?

Measure response diversity, convergence, task success, and influence separately. Communication need not increase entropy or improve performance. Low entropy can mean correct agreement or shared error. A semantic-distance change alone is a proxy, not a complete causal metric.

## 3. Observation is not visibility

One controller-owned append-only event log exists in every condition. Agents receive filtered projections and cannot access storage, dashboard, evaluators, or analysis artifacts directly.

```text
frozen task/config -> global event log -> completed-step snapshot
                                               |          |
                                          visibility A visibility B
                                               |          |
                                            agent A    agent B
                                               |          |
                                            update A   update B
                                               +-----+----+
                                                     |
                                             commit checkpoint
                                                     |
                                  semantic samples / evaluation / exports
                                                     |
                                      probability model -> metrics
```

Store exact application-supplied contexts, tool definitions, hashes, and delivered event IDs. Provider-internal prompts/state may not be observable; record that limitation. Researcher annotations, hidden task truth, private tool observations, embeddings, and metrics are excluded from peer projections unless a future protocol explicitly permits them.

## 4. Conditions

| Condition | Peer visibility | Intervention |
|---|---|---|
| C0 isolation | Original task, own updates, permitted own observations; no peer history | None |
| C1 shared from start | Permitted shared history available each checkpoint | Enabled at step 0 |
| C2 scheduled unlock | C0 before k; earlier permitted peer updates plus future permitted updates from k onward | t_unlock = k |
| C3 sandboxed emergent communication | Normal sharing disabled; bounded simulated alternate surface | Agent discovers/uses an in-sandbox affordance |

C3 is independently configurable and deferred. It cannot expose real host escape, external networks, shared files, or broader tools. C1/C2 automatic exposure cannot be labeled emergent discovery.

C2 uses `history_scope = retrospective_permitted_history` (confirmed). Under the recommended synchronous schedule, observation k includes eligible peer updates through k-1; step k output becomes eligible at k+1. Retrospective access is not permission to expose the entire researcher log.

The communication policy specifies event allowlist, serializer/version, ordering, bandwidth, delay, and tool availability. Proposed default: peer response text and explicit board entries, chronologically serialized. The exact relationship between automatic projection and explicit board reads, plus bandwidth, still needs configuration. Distinguish available, delivered, sent/read, and demonstrably used information.

## 5. Discrete-step protocol

Recommended: synchronous information semantics. Both observations derive from the same committed snapshot through t-1, plus predeclared step input. All peer-facing tool reads use that cutoff.

1. Check remaining budget and record phase/intervention events.
2. Construct and record observations for A and B.
3. Execute restricted turns under bounded call/tool limits.
4. Validate one structured TaskUpdate from each agent.
5. Append raw attempts, responses and metadata; commit only after both valid updates exist.
6. Compute/enqueue representations and evaluations; record communication events.
7. Advance the checkpoint.

Physical inference may run serially to save memory without creating A_t -> B_t visibility. Record physical order/timings. Sequential information semantics require an explicit separate configuration.

An unchanged answer is valid. Early answer completion does not excuse later updates. Failure, timeout, invalid output, or exhausted budgets/retries creates recorded incomplete state; never fabricate an update or silently carry one forward. Partial checkpoints remain visible in exports.

## 6. Stable data contracts

Use versioned strict JSON Schemas and explicit nullability. Shared contracts must not import the runtime. Controller identity, visibility, timing and usage cannot be overridden by model output.

| Contract | Required content |
|---|---|
| ExperimentConfig | Protocol/batch, tasks, two agent configs, conditions, steps, repetitions, prompt/input versions, schedule, budgets/retries, pipeline references, config hash |
| RunConfig | Run/experiment/task/condition, replicate/pairing IDs, resolved config, requested/effective stochastic settings, seed support, code/environment provenance |
| CommunicationPolicy | Version, condition, unlock, history scope, event allowlist, serializer/order, bandwidth/delay, tools, optional affordance |
| AgentObservation | Snapshot, exact context/tool definitions, inputs, visible event/message IDs, context hash/tokens, communication availability, truncation |
| TaskUpdate | Agent answer payload plus controller envelope below |
| CommunicationEvent | Message ID, source, eligible/delivered recipients, channel, content/hash, send/delivery step, bytes/tokens, visibility decision, source update |
| ExperimentEvent | Version, ID, run-local sequence, kind, actor, step/phase, logical/wall time, parents, typed payload, integrity hash |
| RepresentationArtifact (optional) | Source update, raw/normalized text, normalizer/version, vector/reference, dimensions, embedding model/revision, preprocessing, status/error |
| SemanticSampleSet / SemanticJudgment / SemanticPartition | Sample scope/context, source answers, directional judgments, membership, algorithm/judge versions, counts/status and provenance; see semantic-entropy-live-plan.md |
| EvaluatorResult | Sources, evaluator/version/rubric, score name/value/range, correctness, evidence, uptake classification, evaluation visibility |
| ProbabilityState | Source semantic samples/partition (or optional representations), state-space/model versions, partition/reference hash, labels/probabilities, sampling/aggregate scope, counts/weights, missingness |
| MetricResult | Metric/version, value/unit/log base, grouping, exact source manifest, estimator parameters, uncertainty method, validity/proxy labels |
| TextualFeedback | Completed batch, sources, objective, critic/prompt versions, target, critique, evidence, limitations |
| OptimizationProposal | Parent hash, feedback IDs, patch, candidate hash, permitted targets, acceptance actor/time/decision, next batch |

TaskUpdate agent payload: nonempty response_text; nullable final_answer_if_any; nullable confidence_if_requested in [0,1]. Request confidence only in an explicitly configured condition.

Controller envelope: run_id, experiment_id, condition_id, task_id, step, agent_id, prompt_version, agent_config_version, timestamps, phase, observation_id, visible_event_ids, visible_message_ids, communication_available, communication_used, tool-call references, model_metadata, token counts, latency, attempt_id, termination_state.

communication_used denotes a recorded channel operation or delivery, not cognitive uptake. Preserve detailed communication events. Entropy and evaluator annotations are separate artifacts. Preserve raw output even when parsing fails.

## 7. Runtime and storage boundaries

Use two identities with isolated task state and sessions. Provider connections and credentials belong to the controller, not agent-accessible HTTP tools. Agents cannot launch inference jobs, additional agents, installers or services, change budgets, or edit the harness. Validate arguments and derive identity from runtime authorization.

Pi was an earlier runtime proposal; final choice remains pending teammate integration and provider checks. Section 8's original text is retained below; its Pi API statement is historical guidance requiring validation if Pi is selected.

Proposed storage: controller-only append-only events, immutable JSONL exports, separately versioned derived artifacts. No agent SQL/file access. Hash chains provide tamper evidence, not absolute physical immutability. Preserve restart/retry attempt provenance and sequence integrity.

# 8. Agent tool surface

For the simplest tasks:

```text
task_read
task_query
task_submit

board_read
board_append
```

That is it.

Do **not** initially expose:

```text
bash
write
edit
network access
shared filesystem
git remote
general HTTP
MCP servers
subagents
shared memory
```

Otherwise you will spend the hackathon wondering whether information moved through some side channel.

Pi's custom-tool API is sufficient to implement this constrained interface directly.


---

## 9. Team ownership

| Owner | Modules/responsibility | Boundary |
|---|---|---|
| Harness/containment | experiment, agents, communication, storage, config loading | Produces contracts; no entropy math |
| Alejandro | tasks, input progression, representation, exports | No containment or physics changes required |
| Juan Camilo | probability, entropy, divergence, trajectories, aggregation, influence | Reads artifacts without executing agents |
| Evaluation/optimization | evaluators, critic, proposals | Cannot mutate active configs |
| Panel contributors | Control, timeline, agents, representation, physics, communication, optimization views | Shared artifact IDs/read models |

Use a small language-neutral contracts boundary. Runtime/language and teammate-owned interfaces remain pending. This checkout has no implemented agent runtime.

## 10. Semantic analysis and optional representations

The semantic-entropy approach now takes priority over the proposed embedding/codebook path. Sampled answers -> contextual semantic equivalence -> semantic groups -> empirical probabilities -> entropy. Probability and metric layers remain separate; embeddings are optional for trajectory/distance views.

See [semantic-entropy-live-plan.md](semantic-entropy-live-plan.md) for the paper-grounded adaptation, contracts and live observer design. Cross-run response diversity remains distinct from fixed-checkpoint resampling uncertainty. Alejandro's input implementation is reportedly almost solved but has not been inspected or integrated in this checkout.

Juan Camilo owns semantic partitions, probability estimation and metrics; a replaceable entailment adapter supplies recorded judgments. Pin judge/rule versions and audit task-specific validity. Retain alternative probability models behind the existing interface.

## 11. Offline optimization

Frozen P0 -> completed batch A -> evaluator L -> critic g -> candidate P1 -> next frozen batch. A standalone critic is TextGrad-inspired, not automatically actual TextGrad.

Proposed default: prompt-only proposals with researcher acceptance recorded. Task truth, containment, evaluation and metric definitions remain fixed; changes create explicit new versions. Never mutate running configs. Tune on calibration data, preserve held-out evaluation data.

## 12. Observability panel

All views share experiment/task/run/step selection: controls/resolved budgets; checkpoint/intervention timeline; exact contexts and updates; full researcher log; Alejandro's input/embedding pipeline; probability/entropy/trajectory plots; visibility/delivery/uptake; separate offline feedback/proposals.

Every plotted point links to source manifests and updates. Controls create new runs. Live observation is now a priority: show committed raw events immediately and semantic metrics asynchronously with sample count, data cutoff, analysis lag and provisional/final status. The observer cannot affect forward-run behavior. Frontend framework and operator needs remain pending.

## 13. Reproducibility and compute

Freeze task, system/agent prompts, model/revision/parameters, tools, condition/policy, unlock, schedule, serializer, steps, truncation and retries within a run. Derived artifacts record embedding/evaluator/probability/metric versions and exact source manifests. Record code revision and dirty-tree status.

User budget: approximately USD 100 total. Treat USD 100 as a conservative project spending ceiling, not a target to exhaust. Local inference first. Remote GPU endpoint compatibility is required at the adapter boundary; cluster provisioning and Modal deployment are deferred. No automatic remote fallback.

Suggested initial allowance: USD 10 smoke-test/calibration, USD 60 experiment batches, USD 10 semantic judging/evaluation, USD 20 reserve. These allocations are proposed, and paid execution requires a resolved connection and request-cost estimate. Account-wide spending outside the harness is not observable by its local ledger.

User reports OpenAI access through a subscription. Do not assume this establishes separately billed API-key access or Astra availability in the intended harness. Verify supported authentication and billing before paid calls; do not repurpose subscription credentials as arbitrary API keys. Codex subscription and API-key authentication are distinct documented paths: https://developers.openai.com/codex/auth/ .

Enforce per-request/step/run/batch inference, tool, token, wall-time, concurrency and estimated-dollar limits. Reserve worst-case configured request cost before dispatch; include retries, reasoning usage where available and shared history overhead. Exhaustion creates an explicit incomplete run; no unlimited continuation or hidden provider fallback.

Keep local/remote transport behind the model adapter with configurable endpoint and secret reference, model identity, request/response normalization, capability metadata, health checks, timeouts and usage accounting. Experimental agents never choose endpoints or credentials. Pin local weights, quantization, tokenizer/chat template and inference runtime. Equal token limits across model families are not equal physical compute.

Record requested versus supported/effective sampling controls, context lengths/truncation, tool availability, serialization, physical scheduling, rate limits/retries, failures and provider-hidden-state limitations. Avoid automatic summarization; if needed its policy must be fixed and recorded. Treat compute restriction as a separate communication-by-budget experiment if it becomes a research variable.

## 14. Decisions and pilot proposal

Confirmed: replace old protocol; retain Section 8; retrospective C2 access; approximately USD 100 ceiling; local models first; remote compatibility without making deployment a priority.

Pending before a research batch: primary hypothesis/falsification criterion and probability space; task/evidence allocation; success criteria; verified model connection; teammate-owned files/interfaces. Finalize shared-event selection, explicit board use versus automatic delivery, serializer and bandwidth before dependent implementation.

Proposed defaults: six updates (steps 0–5), unlock at 3, same model/prompt within each run, synchronous observations, no early termination, one objective synthetic diagnosis task, five repetitions/condition, bits, pinned semantic judge/equivalence rule, live raw-event panel with asynchronous derived metrics, no optimizer initially.

This is 15 two-agent runs and 180 updates/model. Tool turns, retries, calibration and derived analysis add compute. Five repeats are descriptive pipeline validation, not confirmatory evidence. Check local memory/GPU and task calibration before selecting open-model size.

## 15. Build order and exclusions

1. Resolve contracts/ownership; environment plus deterministic fake adapter.
2. Reliable two-agent lifecycle, one global log and C0/C1/C2 visibility.
3. Mandatory TaskUpdates, exact contexts, retries and budget enforcement.
4. Raw text, scoring and repeated-run exports; embeddings optional.
5. Semantic grouping, discrete entropy and live communication/intervention timeline; fixed-checkpoint probes optional and budgeted separately.
6. Basic counterfactual replay, then offline critic.

Defer C3, adaptive control, actual TextGrad integration, arbitrary topologies, delegation, extra tools, code execution, remote deployment, large model sweeps, transfer entropy, high-dimensional mutual information and unsupported physics curve fitting.

Success is a reliable, traceable experiment regardless of effect direction. It does not require entropy growth, communication uptake or improved task performance.
