# Semantic entropy and live experiment observation

## Decision and research grounding

The user proposes moving entropy analysis away from embeddings using Farquhar et al., [Detecting hallucinations in large language models using semantic entropy](https://www.nature.com/articles/s41586-024-07421-0.pdf), Nature (2024).

The paper groups repeated answers by contextual semantic equivalence, operationalized through bidirectional entailment. Its discrete estimator uses cluster frequencies without token probabilities. Semantic entropy remains entropy of a probability distribution; it removes the need for an embedding-to-probability transformation. Its confabulation results do not establish a general correctness guarantee or validate a multi-agent coordination measure.

The [released estimator code](https://github.com/jlko/semantic_uncertainty/blob/master/semantic_uncertainty/uncertainty/uncertainty_measures/semantic_entropy.py) implements frequency-based cluster entropy using natural logarithms. It also exposes strict and relaxed entailment options; the helper defaults to relaxed. Pin the selected rule explicitly rather than assuming the helper enforces mutual entailment.

Our adaptation: discrete semantic entropy is the proposed first analysis path. Embeddings remain optional for trajectory visualization and distance proxies. Keep probability and metric contracts; replace the compulsory vector input with semantic sample/assignment artifacts. This is a design update, not an implemented or validated estimator.

## Two different sampling scopes

| Metric scope | Samples | Interpretation |
|---|---|---|
| cross_run_response | Actual updates at the same task/condition/step across repeated runs | Semantic diversity of evolving experiment outcomes; histories may differ |
| fixed_checkpoint | Repeated answer generations from one exact frozen answer-generation context | Conditional semantic variability at that checkpoint |

Keep agent roles separate by default. Pooling agents is an explicit additional grouping, not an estimate of either individual's uncertainty. Do not pool past checkpoints as if they were independent draws from one fixed prompt.

For M valid samples assigned to semantic groups, use p_k = n_k/M and H = -sum_k p_k log2(p_k). Bits are our reporting convention; convert values from implementations that return nats. This frequency estimator is distinct from likelihood-weighted variants.

A single observed answer does not provide a useful uncertainty estimate. With two equally weighted observed answers, the plug-in entropy can only be 0 or 1 bit depending on the grouping. Keep this labeled as two-answer agreement/diversity, not reliable uncertainty. Finite-sample estimates miss unseen meanings; show sample count and failures with every point.

## What Alejandro supplies

The input implementation is reportedly almost solved, but its location and interface have not been inspected. Do not replace it or claim integration is complete.

Minimum handoff record: task ID/version and text; run/condition/step/agent; exact observation reference/hash; current proposed answer and full raw response; visible event/message IDs; input/prompt/model/config versions; attempts/status; timestamps; token/latency data.

Prefer a concise current-answer field already present in the task output. If only long text exists, define a versioned observer-side extraction with source spans and failure status. That extraction measures the selected answer/claim, not the entire solution. Do not silently change agent prompts or require a new field mid-batch.

No embedding service is required for the entropy path. Alejandro continues to own task progression, output capture and provenance. Juan Camilo owns sample grouping, probability estimation, entropy and uncertainty analysis.

## Observer contracts

Add language-neutral contracts alongside the existing event schemas:

- SemanticSampleSet: ID, scope, task/question, source run/update IDs, frozen-context hash when applicable, target field/extractor version, model/sampler settings, requested/valid/failed counts, sampling-plan ID and budget.
- SemanticJudgment: sample pair, judging context/hash, judge model/revision/prompt, directional entailment outcomes, strictness rule, status and compute usage.
- SemanticPartition: sample-set ID, algorithm/version, deterministic sample order, membership IDs, representatives, judgment references, unresolved comparisons, partition version and data cutoff.
- ProbabilityState: partition/source IDs, labels/counts/probabilities, valid denominator, missingness policy and grouping scope. It need not reference embeddings.
- MetricResult: sources, sample scope, metric/version, log base/unit, value, status, sample counts, uncertainty method, partition version, data cutoff and computation time.

Use explicit pending, insufficient_samples, provisional, complete and failed states. Missing entropy is not zero. Sample/measurement events live in the same researcher event system, tagged as observations and never admitted by agent visibility policies.

## Live pipeline

```text
restricted agents -> committed TaskUpdates -> append-only event log
                                              |             |
                                      immediate UI      observer queue
                                                            |
                                                 answer/sample selection
                                                            |
                                                semantic judging/partition
                                                            |
                                               counts -> entropy -> UI
```

Raw updates, contexts, tool/message events and spend appear immediately. Entropy appears only when the configured sample group and judgments are available. Display measured step separately from computation time, sample progress, analysis lag, partition version and provisional/final status.

The observer can lag without blocking forward execution. It has no write route to agent contexts, communication policy or active config. No entropy-driven unlock or answer selection in the baseline. Keep checkpoint semantics and retrospective C2 unlock unchanged.

On the local machine, observer inference may compete with agent inference for memory/time. Give the runner priority, bound the queue and record measurement load. If capacity is inadequate, defer expensive judgments until the run finishes while keeping raw telemetry live. Do not let observer contention silently cause condition-specific timeouts.

## Sampling and measurement budget

First implement cross-run analysis of already-required TaskUpdates; no additional agent generations are needed for that metric. Judge calls still have cost and latency. Keep fixed-checkpoint probes optional and predeclared, initially around the unlock boundary.

Suggested probe pilot: M=5 at two checkpoints for both agents. This is a noisy diagnostic, not a sufficient sample size for strong uncertainty claims. Use a separate frozen pre-submission answer-generation context with identical sampler/settings. If full runtime replay cannot reproduce the exact generation boundary, label the measurement answer-only probing rather than full agent-policy uncertainty.

Probe requests are controller-owned measurement jobs, not autonomous subagents: no tools, state mutation, messages or access to extra evidence. They never replace the main update, choose the best sample, or enter future history. The continuation is designated before any analysis. Any difference between probe and forward decoding must be recorded and reflected in interpretation.

For 15 two-agent runs, probing both agents at two checkpoints with five additional draws costs 15*2*2*5 = 300 extra generations, on top of the proposed 180 forward updates. Probing all six checkpoints costs 900 extra generations. These counts exclude judgments and retries. Do not assume removing embeddings makes the experiment cheaper.

With five samples, exhaustive bidirectional pair comparisons require up to 20 directional judgments per set before caching/batching. Cache only identical question/context, answer pair and judge configuration; retain provenance and cap total observer compute under the USD 100 project ceiling. No paid probes until model access and actual costs are resolved.

## Clustering validity and cross-time comparison

Proposed initial rule: strict entailment in both directions, with a pinned judge and prompt. Test paraphrases, changed numbers, negation, partial answers and distinct proposed actions. Related subject matter is not equivalent meaning. Judge quality must be checked on task examples; deterministic decoding does not establish semantic correctness.

Judge predictions may violate transitivity. Record order and clustering algorithm, flag incompatible judgments, and audit sensitivity to ordering. Do not silently turn an undecidable comparison into equivalence. Refusals, invalid output and extraction failure have separate statuses; classify meaningful abstention under a predeclared rule.

Each arriving sample can change a provisional partition and score. Append a new version; keep the earlier displayed value and its data cutoff. Finalize using a reproducible partition over the specified sample set. Entropy comparisons require a consistent equivalence rule and scope; JSD and transition tracking additionally require an explicit shared state alignment, not coincidentally matching numeric cluster IDs.

Keep the judge blind to condition labels and evaluator truth where feasible. Supply the task/question and required interpretation context without turning judging into truth scoring. A low score can represent shared error. Keep task quality, evidence uptake and counterfactual influence separate.

## Implementation sequence

1. Inspect Alejandro's actual output and agree on the minimal handoff; retain his existing input code.
2. Build/verify the restricted two-agent runner, C0/C1/C2 and exact-context event logging using fixtures.
3. Add live raw-event/timeline inspection with observer pending states.
4. Implement semantic sample sets, a replaceable entailment adapter, partitioning and discrete entropy on stored updates; embeddings optional.
5. Validate grouping with manually checked task examples and verify source traceability, units, missingness, order sensitivity and no observer feedback.
6. Run the bounded local pilot; compare task performance and cross-run semantic diversity before adding selected checkpoint probes.
7. Add counterfactual influence and offline criticism later. Defer remote provisioning, C3 and adaptive control.

Pending decisions: location/format of completed input work; task and answer granularity; judge/model access; live frontend ownership. Cross-run response dynamics remains the primary scope from the original question; fixed-checkpoint uncertainty is an explicitly separate optional analysis.
