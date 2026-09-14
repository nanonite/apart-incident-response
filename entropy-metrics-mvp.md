# Response Distributions and Entropy for the Restricted Two-Agent MVP

## 1. Scope

This replaces the earlier evidence/board-entropy MVP note. The active protocol is [mvp-plan.md](mvp-plan.md): two agents, constant global logging, C0 isolation, C1 shared from start, C2 scheduled unlock with earlier permitted updates plus future updates. C3 is deferred. C2 no longer means permanent read containment.

The primary experimental object is the evolving response state. Benchmark evidence uncertainty, provenance entropy and tool-selection entropy are different optional quantities. The scheduling distribution in the [local entropy-dynamics paper](docs/markdown/2606.01351v1/2606.01351v1.md) must not be substituted for a response distribution or used to assume an entropy trajectory.

## 2. Semantic grouping, probabilities and metrics

The user supplied Farquhar et al. (Nature, 2024) as the basis for replacing the mandatory embedding-to-probability path. See [semantic-entropy-live-plan.md](semantic-entropy-live-plan.md) for sources, estimator distinctions, observer contracts and implementation details.

Primary path: raw answers -> semantic equivalence judgments -> partition -> cluster frequencies -> Shannon entropy. Embeddings remain optional for distance/trajectory metrics. This changes how semantic states are obtained; it does not eliminate probability estimation.

For M valid answers with semantic assignments g(x), define:

\[
p_k=\frac{1}{M}\sum_{m=1}^{M}\mathbf{1}[g(x_m)=k],
\qquad H(p)=-\sum_k p_k\log_2p_k.
\]

Proposed unit: bits. Define 0 log 0 = 0, validate finite nonnegative probabilities and sum-to-one tolerance, and record failed/missing samples. The frequency-based estimator is distinct from likelihood-weighted semantic entropy. An undefined value is not zero.

## 3. Replaceable interfaces

```text
SampleSelector.select(events, sampling_plan) -> SemanticSampleSet
EntailmentJudge.compare(question_context, answer_a, answer_b) -> SemanticJudgment
SemanticPartitioner.partition(sample_set, judgments) -> SemanticPartition
ProbabilityModel.estimate(partition, grouping_spec) -> ProbabilityState
Metric.compute(states, source_manifest) -> MetricResult
InfluenceMetric.compare(replay_pair_or_samples) -> MetricResult
RepresentationPipeline.transform(update) -> optional RepresentationArtifact
```

Analysis reads stored artifacts without importing the harness. Record judge/model/prompt, equivalence strictness, sample order, partition algorithm and unresolved judgments. Similar wording or topic is not semantic equivalence. Pin a rule, test task examples, and audit non-transitive judgments/order sensitivity.

Keep embedding-based assignments, hypotheses and reliable token probabilities as optional alternative probability models with distinct interpretations. Do not compute entropy over arbitrary embedding coordinates.

## 4. Sampling scope and aggregation

Distinguish cross_run_response (actual updates across repeated evolving runs) from fixed_checkpoint (repeated generations from an identical answer-generation context). Their conditioning differs. Do not pool them or call cross-run diversity the uncertainty of one exact checkpoint.

For R complete balanced runs, optional pooled-agent diversity is:

\[
p_{c,t,k}=\frac{1}{2R}\sum_{r=1}^{R}\sum_{i=1}^{2}\mathbf{1}[g(x_{i,t,r})=k].
\]

Report per-agent/role distributions first; pooling can hide role differences. Do not pool time steps as independent samples from one prompt. Preserve run or matched-run blocks in uncertainty resampling. Five repeats are descriptive; zero observed events does not prove zero probability.

Every point carries scope, task/condition/step, run/sample IDs, context hashes, model/sampler and prompt/config versions, communication/exposure state, source updates, judge/partition version, evaluator scores, weights/counts and missingness. Missing/failed updates are not unchanged answers. Predeclare the analysis population and report attrition by condition.

Live partitions/metrics are provisional and versioned as new samples arrive; preserve earlier values with their data cutoffs. JSD and state transitions require explicit alignment of meanings across groups, not matching numeric cluster IDs. Keep all measurement events hidden from agents.

## 5. Interventions and trajectories

C2 unlock occurs before observation construction at t*=k. Earlier permitted peer updates through k-1 become visible at k under synchronous semantics. Record availability, actual delivery and first demonstrated uptake separately.

\[
\Delta H_c=H_c(t^*+\delta)-H_c(t^*-\delta).
\]

Choose valid window endpoints prospectively. Its sign is not predetermined. Compare C2 changes with C0 changes over the same steps; pre/post change alone does not isolate communication from normal progression. Historical disclosure is an information bundle and cannot by itself identify the contribution of each earlier message.

Additional plugins may measure entropy slope, pre/post windows, Jensen-Shannon divergence on a common state space, between-agent semantic distance, within-agent displacement, cross-run variance, convergence/divergence, task success, communication timing/volume and information uptake. Do not mix semantic judge/partition definitions; recompute the comparison set if they change. Optional embedding-distance metrics likewise require compatible embeddings.

## 6. Cross-agent influence

Exposure, uptake, utility and causal influence are distinct. Seeded harmless information with controlled provenance can demonstrate transfer, but transfer alone does not establish improved coordination or performance.

Fork B's checkpoint before exposure into visible and hidden/masked branches. Hold task, own history, permitted tools, prompt/config and model fixed. Reconstruct independent requests with no retained peer information in provider state. Record parent checkpoint, manipulated message IDs, masking transformation, branch seeds/settings, budgets and sources.

A single semantic-distance, answer-class, action or evaluator difference is a response-change proxy. Repeated replay samples permit distribution comparisons. Shared seeds do not guarantee identical provider randomness. A hidden branch changes context length too; add a separately specified length/position control if identifying content-specific effects.

## 7. Reproducibility

Every MetricResult identifies source runs/updates, semantic sample sets/judgments/partitions (or optional representations), state model/reference data, grouping/weights, code revision, metric version, log base, estimator parameters and uncertainty procedure. Derived artifacts are append-only/versioned and recomputable. Run execution never depends on a recomputed metric in the static baseline.

## 8. Entropy must be paired with correctness

Low entropy may reflect correct convergence or collective error. Plot task/evaluator scores with response entropy. High provenance entropy does not establish quality. If calibrated beliefs are studied later, pair entropy with a proper scoring rule.

Benchmark evidence entropy P(diagnosis | available evidence) may be added under a justified likelihood model; label it separately from empirical response entropy and subjective model uncertainty. Do not count repeated/paraphrased evidence as new information.

## 9. Deferred research

Defer transfer entropy, high-dimensional mutual information, mediation models, damped-oscillation fitting, and claims about intrinsic model uncertainty until the state space, sample size and assumptions support them. Actual TextGrad and offline criticism belong to optimization, not entropy calculation. No textual feedback modifies a controlled run.
