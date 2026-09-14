# Model–Harness Swarm Scaling: Consolidated Experimental Plan

**Status:** research plan / pre-registration scaffold

**Active hackathon scope:** [mvp-plan.md](mvp-plan.md) is the current two-agent response-dynamics protocol and replaces the former three-agent board-containment MVP. Its Section 8 restrictions remain authoritative. C2 now means scheduled unlock with retrospective permitted history. This broader scaling document is background/future research, not the implementation scope or condition dictionary for the hackathon.
**Primary objective:** measure, validate, and ultimately benchmark how adversarial capability changes as a function of compute, independent breadth, concurrency, shared-state interaction, explicit communication, and harness mechanisms.

---

# 0. Epistemic status and scope

This document uses three tags:

* **[LIT]** — supported by published or publicly available prior work.
* **[CONS]** — constructed experimental proposal or interpretation.
* **[OPEN]** — unresolved empirical or methodological question.

The project has five layers:

1. **Stage 0 — Pilot and nuisance-parameter estimation**
2. **Phase 0 — Instrument validation**
3. **Phase I — Defender comparison benchmark**
4. **Phase II — Harness swarm testing**
5. **Phase III — Adaptive harness search**

The first three belong to the benchmark program.

Phase II is a mechanistic study.

Phase III is adaptive red teaming and should not be treated as a stable benchmark.

The central principle is:

> **Do not infer swarm capability from a single scaling curve. Decompose the system into compute, breadth, concurrency, stigmergy, explicit communication, and harness mechanisms, and intervene on them separately.**

---

# 1. Core abstraction

## 1.1 The system is model + harness

Represent an agent system as:

$$
S=(M,H)
$$

where:

* \(M\) = model weights and inference configuration;
* \(H\) = executable harness controlling context, tools, state, retries, communication, delegation, scheduling, and action policy.

For attack and defense:

$$
A=(M_A,H_A)
$$

$$
D=(M_D,H_D)
$$

The measured outcome is:

$$
Y
=
f(
M_A,H_A,
M_D,H_D,
N,C,E,
B_A,B_D
)
$$

where:

* \(N\) = attacker population size;
* \(C\) = explicit communication condition;
* \(E\) = environment;
* \(B_A\) = attacker resource vector;
* \(B_D\) = defender resource vector.

This equation defines the causal state space.

A single experiment should vary only a small subset of these variables.

---

# 2. Distinguish model effects from system effects

A released model does not possess a unique inherent attacker or defender harness.

Define model evaluation under reference harnesses as:

$$
A_{\theta|\mathrm{ref}}
=
(M_\theta,H_{A,\mathrm{ref}})
$$

$$
D_{\theta|\mathrm{ref}}
=
(M_\theta,H_{D,\mathrm{ref}})
$$

These support claims about the model under standardized execution conditions.

Separately define deployed systems:

$$
A_\theta^{\mathrm{sys}}
=
(M_\theta,H_{A,\theta})
$$

$$
D_\theta^{\mathrm{sys}}
=
(M_\theta,H_{D,\theta})
$$

These support claims about complete systems.

Do not report model-level and system-level results under the same score label.

---

# 3. Central scientific question

The primary causal question is:

$$
\boxed{
\text{At matched resources, what capability is attributable to}
}
$$

$$
\boxed{
\text{depth}
\rightarrow
\text{breadth}
\rightarrow
\text{concurrency}
\rightarrow
\text{stigmergy}
\rightarrow
\text{explicit communication}
\rightarrow
\text{specific harness mechanisms}
}
$$

The project should remain useful even if there is:

* no critical phase transition;
* no universal \(N^*\);
* no superlinear scaling;
* no emergent organization;
* no large-\(N\) discontinuity.

A negative or saturating result is scientifically meaningful if the decomposition is identifiable.

---

# 4. Reference systems and vintages

## 4.1 Versioned reference systems

Do not use one eternal “golden attacker.”

Maintain:

$$
A_{\mathrm{ref}}^{(1)},
A_{\mathrm{ref}}^{(2)},
A_{\mathrm{ref}}^{(3)},\ldots
$$

and, where needed:

$$
D_{\mathrm{ref}}^{(1)},
D_{\mathrm{ref}}^{(2)},\ldots
$$

Each benchmark vintage is explicitly pinned.

---

## 4.2 Archival tuple

Each archival reference system should specify:

$$
R=
(M,H,I,T,E,S)
$$

where:

* \(M\) = model / weights / exact model version;
* \(H\) = harness commit or container;
* \(I\) = inference stack and decoding configuration;
* \(T\) = tools, feeds, and dependency versions;
* \(E\) = environment snapshot;
* \(S\) = seed and randomization policy.

An API-only reference that cannot be exactly replayed must be labeled:

> **non-archival reference system**

and should not be the sole longitudinal anchor.

---

## 4.3 Vintage bridge

When replacing:

$$
A_{\mathrm{ref}}^{(k)}
$$

with:

$$
A_{\mathrm{ref}}^{(k+1)},
$$

run both against a shared set of archived defenders and environments.

The overlap is a calibration bridge.

Do not assume direct score equivalence across vintages.

---

# 5. Outcome

## 5.1 Primary binary outcome

Define:

$$
Y_A
=
\mathbf 1(
\text{validated attacker success before cutoff}
).
$$

Define:

$$
Y_D=1-Y_A.
$$

A success must satisfy a prewritten validator specification.

---

## 5.2 Validator

The validator \(V\) should be:

* unreachable by the attacker;
* deterministic where possible;
* based on ground truth or a clearly specified scoring rule;
* audited on a random human-reviewed subset.

Record validator–human agreement.

Any evidence that agents target or exploit the validator should be separately logged.

---

# 6. Primary statistical scale

Use risk difference as the primary effect scale:

$$
\Delta_{a:b}
=
P(Y=1|a)
-
P(Y=1|b).
$$

Use:

* log-odds;
* odds ratio;
* alternative links;

as sensitivity analyses.

Do not require sign agreement across every transformed scale.

---

# 7. Environment structure

Represent environment properties explicitly:

$$
E=(d,p,s,a)
$$

where:

* \(d\) = divisibility;
* \(p\) = partial observability;
* \(s\) = shared-state dependence;
* \(a\) = adaptive/adversarial response.

At least two environment families should differ materially in divisibility or shared-state structure.

This prevents a benchmark from reducing to a measurement of embarrassingly parallel search.

---

# 8. Three-way environment split

Construct one environment pool.

Randomize instances at construction time into:

$$
E_{\mathrm{cal}}
$$

$$
E_{\mathrm{public}}
$$

$$
E_{\mathrm{private}}.
$$

Stratify assignment by task family and difficulty-generating process.

Record the assignment seed.

---

## 8.1 Calibration pool

Use:

$$
E_{\mathrm{cal}}
$$

to tune environment difficulty.

Aim for reference-system outcome probabilities roughly inside:

$$
Y\in[0.2,0.8].
$$

This is a design heuristic intended to avoid floor and ceiling compression.

---

## 8.2 Public pool

May be released for:

* development;
* debugging;
* public reproducibility.

Expect increasing exposure over time.

---

## 8.3 Private pool

Reserve for hidden evaluation.

Do not repeatedly tune benchmark parameters against it.

---

# 9. Resource vectors

## 9.1 Attacker budget

Define:

$$
B_A
=
(
T_{\mathrm{tok}},
N_{\mathrm{infer}},
N_{\mathrm{tool}},
N_{\mathrm{env}},
t_{\mathrm{wall}},
c_{\mathrm{conc}}
)
$$

where appropriate.

At least one resource dimension should be designated as binding.

---

## 9.2 Defender budget

Define:

$$
B_D
$$

including:

* tokens;
* inference budget;
* concurrency;
* latency;
* rate limits;
* memory;
* tool permissions;
* wall-clock response limits.

A fixed defender population is acceptable.

But all scaling results are conditional on \(B_D\).

---

# 10. Stage 0 — pilot

## 10.1 Purpose

Stage 0 estimates nuisance parameters needed to power and cost the main study.

It is a pilot, not confirmatory evidence.

Preregister Stage 0 separately.

---

## 10.2 Minimal Stage-0 design

Run:

$$
A5
$$

and:

$$
A7
$$

at:

$$
N=10
$$

on approximately:

$$
50
$$

paired blocks in one representative environment.

Also run infrastructure stress tests at:

$$
N\in\{1,10,30\}.
$$

---

## 10.3 Stage-0 deliverables

Estimate:

* baseline success probability \(p_0\);
* paired discordance rate \(p_d\);
* task-family intra-cluster correlation;
* realized attacker resource use;
* realized defender resource use;
* infrastructure error rate;
* agent timeout rate;
* canary recovery / leakage rate;
* placebo attention rate;
* validator disagreement rate.

These quantities determine the final main-study \(n\), cost, and thresholds.

---

# 11. Phase 0 — instrument validation

Phase 0 asks:

> **Does the measurement instrument behave in ways required of a benchmark instrument?**

It does not yet rank defenders.

The required validity battery has three legs:

1. sensitivity;
2. discrimination;
3. reliability.

---

# 12. Phase-0 arm ladder

For attacker population size \(N\), define:

| ID | Population | Execution                           | Explicit comms | Environment coupling | Attacker budget | Purpose                           |
| -- | ---------: | ----------------------------------- | -------------- | -------------------- | --------------: | --------------------------------- |
| A0 |          1 | single                              | none           | isolated             |           \(b\) | baseline                          |
| A1 |          1 | serial, long-context primary policy | none           | isolated             |          \(Nb\) | depth                             |
| A2 |          1 | serial, alternate context policy    | none           | isolated             |          \(Nb\) | depth sensitivity                 |
| A3 |      \(N\) | sequential replicas                 | none           | isolated             |          \(Nb\) | breadth                           |
| A4 |      \(N\) | concurrent                          | none           | isolated             |          \(Nb\) | concurrency                       |
| A5 |      \(N\) | concurrent                          | none           | shared mutable       |          \(Nb\) | stigmergy                         |
| A6 |      \(N\) | concurrent                          | placebo        | shared mutable       |          \(Nb\) | communication activity / overhead |
| A7 |      \(N\) | concurrent                          | real           | shared mutable       |          \(Nb\) | semantic communication            |

A1 is the primary depth control.

A2 is a sensitivity control for long-context policy.

---

# 13. Depth

Estimate:

$$
\Delta_{\mathrm{depth}}
=
Y(A1)-Y(A0).
$$

This asks:

> How much performance comes from giving one trajectory \(N\)-times the resource budget?

A2 provides sensitivity to the serial context-handling policy.

---

# 14. Breadth

Estimate:

$$
\Delta_{\mathrm{breadth}}
=
Y(A3)-Y(A1).
$$

This compares:

* one long trajectory;

against:

* \(N\) independent trajectories;

at approximately matched total attacker budget.

This is **breadth**, not concurrency.

---

# 15. Concurrency

Estimate:

$$
\Delta_{\mathrm{concurrency}}
=
Y(A4)-Y(A3).
$$

This isolates simultaneous execution from multiple independent starts.

The concurrency arm may be omitted if it is zero by construction, for example when:

* each trajectory operates on a stateless isolated clone;
* the defender is time-invariant;
* no rate limits or timing channels create a concurrency pathway.

If omitted, state and justify the condition.

---

# 16. Stigmergy

Estimate:

$$
\Delta_{\mathrm{stigmergy}}
=
Y(A5)-Y(A4).
$$

This measures capability attributable to interaction through shared mutable environment state without an explicit communication channel.

Examples include:

* shared files;
* modified services;
* visible artifacts;
* environment side effects;
* persistent external state.

---

# 17. Explicit communication

## 17.1 Real versus null

Estimate:

$$
\Delta_{\mathrm{real:null}}
=
Y(A7)-Y(A5).
$$

Both arms use the same shared environment.

The difference therefore targets explicit communication rather than mixing communication with stigmergy.

---

## 17.2 Real versus placebo

Estimate:

$$
\Delta_{\mathrm{real:placebo}}
=
Y(A7)-Y(A6).
$$

This measures semantic/content-specific communication benefit relative to non-semantic communication activity.

---

## 17.3 Placebo cost

Estimate:

$$
\Delta_{\mathrm{placebo:null}}
=
Y(A6)-Y(A5).
$$

This measures overhead or disruption from the placebo channel itself.

Do not describe the two communication contrasts as bounds on one latent effect.

---

# 18. Communication treatment specification

Represent communication as:

$$
C=(b_c,\ell,\tau,p,a)
$$

where:

* \(b_c\) = communication budget;
* \(\ell\) = latency;
* \(\tau\) = topology;
* \(p\) = persistence;
* \(a\) = artifact types.

Possible communication primitives include:

* pairwise messaging;
* broadcast;
* persistent scratchpad;
* shared artifacts;
* explicit task delegation;
* supervisor-mediated routing.

---

# 19. Leakage tests

The null condition may still leak information through:

* shared mutable state;
* tool side effects;
* logs;
* timing;
* external feeds;
* observable agent actions.

Use canary probes and dedicated leakage tests.

Predefine a leakage tolerance.

If leakage exceeds tolerance, communication contrasts are not interpretable.

---

# 20. Positive controls

Use **graded** positive controls.

Construct at least three levels of known communication dependence:

$$
q_{\mathrm{low}},
q_{\mathrm{MDE}},
q_{\mathrm{high}}.
$$

Calibrate one level to induce approximately the minimum detectable effect.

The instrument passes sensitivity validation only if it can detect the MDE-scale control.

A trivially enormous positive-control effect is insufficient by itself.

---

# 21. Discrimination control

Instrument validation should include a control where defender ordering is known by construction.

Do not assume harness ablations produce monotone weakness.

Construct synthetic defenders such as:

$$
D_{\mathrm{weak}}
<
D_{\mathrm{medium}}
<
D_{\mathrm{strong}}
$$

using controlled differences such as:

* strict observation deprivation;
* explicit resource limits;
* deliberately delayed information;
* additional oracle information for the strongest defender.

Pre-register the expected rank order.

The instrument should recover it.

---

# 22. Reliability

Evaluate test–retest reliability using fresh seeds and repeated blocks.

Possible metrics depend on analysis level:

* paired agreement for binary outcomes;
* kappa where appropriate;
* rank stability across defender systems;
* variance components from logistic mixed models;
* ICC only for aggregated continuous scores where appropriate.

The benchmark-level reliability target is:

> Does the relative ordering of systems replicate across fresh draws?

---

# 23. Initial population levels

Use:

$$
N\in\{1,3,10,30\}
$$

for initial work.

Do not include:

$$
N=100
$$

by default.

Adding \(N=100\) increases raw population-weighted inference cost by roughly:

$$
\frac{1+3+10+30+100}
{1+3+10+30}
=
\frac{144}{44}
\approx3.27.
$$

Treat \(N=100\) as a formal expansion/funding decision triggered by lower-\(N\) results.

---

# 24. Experimental unit and blocking

Primary experimental unit:

$$
\text{task instance}
\times
\text{environment initialization}
\times
\text{seed}.
$$

Block on:

$$
(\text{task instance},\text{environment initialization}).
$$

Run each relevant arm on each block.

Randomize arm execution order within block.

Reset:

* environment;
* caches;
* credentials;
* mutable external state;

between runs where appropriate.

Analyse comparisons as paired where the design permits.

Cluster standard errors at the task-family level where needed.

---

# 25. Paired power

For binary paired comparisons, power depends strongly on the discordance probability:

$$
p_d
=
P(Y_a\neq Y_b).
$$

Stage 0 should estimate \(p_d\).

Do not assume that blocking automatically produces large sample-size savings.

Use the actual paired estimator in the final power calculation.

---

# 26. Superiority versus equivalence

These are different hypotheses.

## 26.1 Superiority

For example:

$$
H_0:\Delta=0
$$

versus:

$$
H_1:\Delta=\delta.
$$

Use this when asking whether an effect exists.

---

## 26.2 Equivalence

For a negligible-effect margin \(\epsilon\):

$$
H_0:
|\Delta|\geq\epsilon
$$

versus:

$$
H_1:
|\Delta|<\epsilon.
$$

Use this if claiming an effect is practically negligible.

A non-significant superiority test does not establish equivalence.

---

## 26.3 Budget consequence

Equivalence at a small margin can require substantially more observations than superiority testing.

Compute the exact required \(n\) after Stage 0 using:

* \(p_0\);
* paired discordance;
* cluster structure;
* attrition;
* planned estimator.

If the study cannot afford equivalence testing at:

$$
\epsilon=0.05,
$$

state explicitly:

> the study is powered to detect effects of the declared MDE but cannot establish practical equivalence within ±0.05.

---

# 27. Attrition and failures

## 27.1 Agent failure

Treat the following as treatment outcomes:

* agent timeout;
* token exhaustion;
* tool exhaustion;
* policy crash inside the tested system;
* failure to act before deadline.

For attacker evaluation:

$$
Y_A=0.
$$

Use an intention-to-treat interpretation.

---

## 27.2 Infrastructure error

Examples:

* evaluation scheduler crash;
* VM corruption;
* unrelated service outage;
* validator infrastructure failure.

Mark as invalid technical runs.

Report error rates by arm and \(N\).

---

## 27.3 Rerun policy

Pre-register a limited rerun policy for genuine infrastructure errors.

Where possible, rerun with:

* same seed;
* same environment initialization;
* same system image.

---

## 27.4 Sensitivity analysis

For excluded technical failures, report extreme-case sensitivity:

1. treat all as failures;
2. treat all as successes.

This bounds the possible impact of differential attrition.

---

# 28. Phase-0 progression gate

Proceed to Phase I only if:

1. graded positive control near the MDE is detected;
2. leakage is below the pre-registered tolerance;
3. outcome probabilities are not saturated;
4. known-ordering defender control is correctly ranked;
5. reliability is acceptable under the chosen metric;
6. infrastructure error rates are tolerable and reported;
7. resource budgets are measurable and enforceable;
8. at least one scientifically relevant contrast is estimable at planned precision.

If the instrument fails these tests, redesign it before calling it a benchmark.

---

# 29. Phase I — defender comparison benchmark

Phase I asks:

$$
\boxed{
\text{Does the validated instrument distinguish defender systems?}
}
$$

This is the first phase that deserves to be called the benchmark.

---

# 30. Phase-I design

Fix:

$$
A_{\mathrm{ref}}
$$

$$
N
$$

$$
C
$$

$$
E
$$

$$
B_A
$$

$$
B_D
$$

and vary defender systems:

$$
D_1,D_2,\ldots,D_K.
$$

Candidate model-level comparison:

$$
D_{i|\mathrm{ref}}
=
(M_i,H_{D,\mathrm{ref}}).
$$

Candidate system-level comparison:

$$
D_i^{\mathrm{sys}}
=
(M_i,H_{D,i}).
$$

Report these separately.

---

# 31. RQ0 — benchmark discrimination

Add the explicit question:

> **RQ0: At the declared sample size and environment distribution, does the instrument distinguish defender systems with useful precision and reliability?**

A benchmark that cannot separate plausible defenders is not useful even if its causal decomposition is theoretically clean.

---

# 32. Defender comparison reporting

For each defender report:

* reference vintage;
* model version;
* harness version;
* \(B_D\);
* success probability;
* uncertainty interval;
* relative performance against anchor;
* performance by \(N\);
* performance by environment;
* public/private split;
* test–retest rank stability.

Do not collapse all results into a single scalar unless an explicit aggregation rule is justified.

---

# 33. Optional threshold statistic

Define, if useful:

$$
N^*
=
\min
\{
N:
P_{\mathrm{defend}}(N)<\theta
\}.
$$

Interpret only as:

> threshold crossing under the specified reference attacker, defender budget, harness, communication condition, and environment distribution.

Do not treat \(N^*\) as an intrinsic model property.

---

# 34. Scaling shape

Treat \(N\) as categorical in early analyses.

Do not assume:

* power law;
* logarithmic response;
* logistic transition;
* threshold;
* percolation.

Fit smooth functional forms only after examining the empirical response.

---

# 35. Phase II — harness swarm testing

Phase II asks:

> **Which harness mechanisms causally change performance as population size increases?**

Freeze model weights.

Vary harness capabilities.

This phase is mechanistic and may produce sensitive operational information.

---

# 36. Harness factorization

Represent the attacker harness as:

$$
H_A
=
(
H_A^{\mathrm{base}},
H_A^{\mathrm{coord}}
).
$$

Where feasible:

* \(H_A^{\mathrm{base}}\) contains general execution infrastructure;
* \(H_A^{\mathrm{coord}}\) contains coordination-relevant mechanisms.

Then conceptualize intervention as:

$$
C:=do(H_A^{\mathrm{coord}}=c).
$$

---

# 37. Harness capability taxonomy

Potential attacker-side features:

* broadcast;
* pairwise communication;
* persistent shared memory;
* shared scratchpad;
* shared artifacts;
* explicit delegation;
* supervisor routing;
* role specialization;
* task partitioning;
* rediscovery suppression;
* retries/reflection.

Potential defender-side features:

* incident memory;
* alert aggregation;
* triage;
* evidence sharing;
* rollback;
* escalation;
* cross-agent verification;
* response delegation;
* policy enforcement.

Each feature must have an executable operational definition.

---

# 38. Feasibility lattice

Harness features may have dependency constraints.

For example:

* delegation may require communication;
* broadcast may require a message bus;
* shared-memory search may require persistence.

Therefore the configuration space may be:

$$
\mathcal F
\subsetneq
\{0,1\}^k.
$$

Do not assume every binary combination is valid.

For benchmark v1, define the causal estimand over the feasible configuration set:

$$
\mathcal F.
$$

Avoid unnecessary game-theoretic attribution machinery unless later justified.

---

# 39. Harness omission design

Let:

$$
H_{\mathrm{full}}
=
\{h_1,\ldots,h_k\}.
$$

Construct valid variants:

$$
H^{(r)}
=
H_{\mathrm{full}}\setminus Z_r
$$

subject to:

$$
H^{(r)}\in\mathcal F.
$$

Use randomized feature omission over feasible configurations.

---

# 40. Banzhaf and Shapley terminology

If features are independently included with:

$$
P(z_j=1)=1/2
$$

over the unrestricted hypercube, resulting effects are Banzhaf-like.

Do not call them Shapley values.

If the feasible set is constrained, neither plain Banzhaf nor plain Shapley applies without modification.

The simplest approach is:

> define effects relative to the actual feasible intervention distribution.

---

# 41. Feature specification test

For a coordination-only feature \(h_j\), evaluate its effect at:

$$
N=1.
$$

Define:

$$
\Delta_j(1)
=
Y(H_{\mathrm{full}},1)
-
Y(H_{-j},1).
$$

A coordination-only feature should be approximately inert at \(N=1\).

Pre-register a specification tolerance:

$$
\epsilon_{\mathrm{spec}}.
$$

Test equivalence inside:

$$
[-\epsilon_{\mathrm{spec}},
+\epsilon_{\mathrm{spec}}].
$$

If equivalence fails, the ablation is not surgically isolating coordination and the swarm-specific interpretation becomes questionable.

---

# 42. Harness-mediated scaling effect

For feature \(h_j\):

$$
\Delta_j(N)
=
Y(H_{\mathrm{full}},N)
-
Y(H_{-j},N).
$$

Define:

$$
\boxed{
\Gamma_j(N)
=
\Delta_j(N)
-
\Delta_j(1)
}
$$

Interpretation:

* \(\Gamma_j(N)\approx0\): feature helps single agents and swarms similarly;
* \(\Gamma_j(N)>0\): feature becomes disproportionately valuable at larger \(N\);
* \(\Gamma_j(N)<0\): feature creates interference or scaling overhead.

Only interpret \(\Gamma_j\) mechanistically if the \(N=1\) specification test passes.

---

# 43. Phase-II population sizes

Use at least:

$$
N\in\{1,3,10,30\}.
$$

Treat \(N\) categorically.

Do not begin with a hard-coded:

$$
z_j\log N
$$

interaction.

Estimate effects separately by population level.

---

# 44. Phase-II analysis

An initial model may take the form:

$$
Y
=
\alpha
+
\sum_j \beta_jz_j
+
\sum_{n\neq1}\gamma_nI(N=n)
+
\sum_j
\sum_{n\neq1}
\delta_{jn}
z_jI(N=n)
+
\epsilon.
$$

The \(\delta_{jn}\) terms identify feature effects that vary with population size.

Do not interpret this as evidence for any specific smooth scaling law.

---

# 45. Multiplicity

Predefine hypothesis families, for example:

$$
\mathcal H_1
=
\{\text{main harness effects}\}
$$

$$
\mathcal H_2
=
\{\text{harness}\times N\text{ effects}\}
$$

$$
\mathcal H_3
=
\{\text{targeted pairwise interactions}\}.
$$

Use an explicit FDR procedure such as Benjamini–Hochberg within predeclared families where appropriate.

Do not silently treat dozens of exploratory coefficients as independent confirmatory findings.

---

# 46. Screening and confirmation

Phase II should have separate stages.

## B1 — screening

Use randomized valid harness configurations.

Identify candidate features.

---

## B2 — confirmation

Test a small number of selected features on:

* held-out tasks;
* fresh seeds.

Power confirmation using a shrunken estimate rather than the raw screening point estimate.

---

## B3 — targeted interactions

Test a small number of theoretically motivated feature pairs.

Examples:

$$
\text{broadcast}
\times
\text{shared memory}
$$

$$
\text{delegation}
\times
\text{supervisor}.
$$

---

# 47. Phase-II disclosure and access policy

Before Phase II begins, define:

* who may access raw \(\Gamma_j\) results;
* where artifacts are stored;
* review authority;
* release criteria;
* sanitization criteria;
* controlled-access criteria;
* withholding criteria.

Possible disposition:

$$
\text{result}
\rightarrow
\begin{cases}
\text{public}\\
\text{sanitized}\\
\text{controlled access}\\
\text{withheld}
\end{cases}
$$

Evaluate results based on:

* attacker uplift;
* defensive value;
* operational specificity;
* rediscoverability;
* availability of mitigation.

Do not assume that mechanistic results have zero defensive value.

---

# 48. Public/private exposure diagnostic

Report:

$$
\Delta_{\mathrm{exposure}}
=
Y(E_{\mathrm{public}})
-
Y(E_{\mathrm{private}}).
$$

This is an exposure diagnostic.

Do not interpret it as a pure causal estimate of training-data contamination.

Use canaries and memorization probes only as supporting diagnostics.

---

# 49. Cross-model replication

With two models:

> cross-model replication case study.

Do not estimate population-level between-model variance.

For preliminary model-level heterogeneity analysis, use at least:

$$
4+
$$

meaningfully different models.

Then examine:

$$
\Gamma_j(N|M).
$$

Keep generalization conservative.

---

# 50. Phase III — adaptive harness search

Only after static harness mechanisms are identified should an optimizer modify the harness.

Define:

$$
H_{t+1}
=
\mathcal O(M,H_t,Y_t).
$$

Possible attacker objective:

$$
H_A^*
=
\arg\max_H
\left[
P_{\mathrm{attack}}(M_A,H,N)
-
\lambda\mathrm{Cost}(H)
\right].
$$

Adaptive search adds variables such as:

* meta-model;
* optimizer harness;
* search budget;
* allowable edit surface;
* objective;
* acceptance rule;
* number of iterations.

Treat this as:

> **adaptive red teaming**

rather than a stable benchmark.

---

# 51. Disclosure timing registry

Retain:

$$
T_e
=
\text{existence disclosure}
$$

$$
T_v
=
\text{vulnerability / mitigation disclosure}
$$

$$
T_m
=
\text{mechanism disclosure}
$$

$$
T_a
=
\text{attribution disclosure}.
$$

The registry is descriptive.

It supports institutional comparison and accountability.

It does not identify counterfactual attack probabilities.

---

# 52. Information-asymmetry layer

Let:

* \(A\) = full attack mechanism;
* \(D\) = disclosed artifact;
* \(P\) = protective information.

Define conceptually:

$$
U(D)=I(A;D)
$$

$$
\Delta(D)
=
\frac{H(A|D)}
{H(A)}
$$

$$
S(D)
=
\frac{I(P;D)}
{H(P)}.
$$

Then the conceptual disclosure problem is:

$$
\max_D S(D)
$$

subject to:

$$
\Delta(D)\geq\Delta_{\min}.
$$

These remain conceptual until operational estimators are developed.

---

# 53. Disclosure cost

Use a counterfactual formulation such as:

$$
K_{\mathrm{disc}}
=
\int
\left[
P(A_t|D)
-
P(A_t|\neg D)
\right]
L_t\,dt.
$$

Long-run formulations must include some combination of:

* finite horizon;
* discounting;
* technique obsolescence;
* finite exposed population.

The relevant harm is incremental harm relative to independent rediscovery.

---

# 54. Costing

Cost should be calculated from actual arm structure, not only from \(N\).

For each arm \(r\), define:

$$
C_r
=
n_r
\times
B_{A,r}
+
n_r
\times
B_{D,r}
+
C_{\mathrm{validator},r}
+
C_{\mathrm{human},r}.
$$

Then:

$$
C_{\mathrm{total}}
=
\sum_r C_r
+
C_{\mathrm{pilot}}
+
C_{\mathrm{rerun}}.
$$

Include an explicit rerun allowance.

---

## 54.1 Important correction to prior estimate

A design with:

* 1 baseline cell;
* 14 full-ladder cells at \(N=3,10\);
* 3 cells at \(N=30\);
* 6 graded-positive-control cells;
* 6 discrimination-control cells;

contains approximately:

$$
30
$$

cells per environment.

If the primary ladder contributes:

$$
182b
$$

of attacker budget per replicate, the 12 additional \(N=10\) control cells add:

$$
120b.
$$

Thus the stated design is approximately:

$$
302b
$$

per replicate per environment before defender, validator, human-audit, and rerun costs.

At:

$$
n=200,
$$

two environments, and:

$$
b=2\times10^5
$$

tokens:

$$
302
\times
200
\times
2
\times
2\times10^5
\approx
2.4\times10^{10}
$$

attacker tokens.

This is illustrative only.

Final costing must use Stage-0 realized consumption and final sample size.

---

# 55. Phase-0 cost reduction

Do not automatically run every arm at every \(N\).

A cost-conscious schedule may use:

* full ladder at \(N=3\) and \(N=10\);
* selected primary arms at \(N=30\);
* no \(N=100\) until an explicit expansion decision.

Dropping the concurrency arm where it is zero by construction may reduce cost further.

---

# 56. Primary preregistration variables

Before the confirmatory study, fix:

| Symbol                       | Definition                               |
| ---------------------------- | ---------------------------------------- |
| \(Y_A\)                      | validated attacker success               |
| \(V\)                        | validator specification                  |
| \(B_A\)                      | attacker resource vector                 |
| \(B_D\)                      | defender resource vector                 |
| \(b\)                        | base per-agent budget                    |
| \(\pi_{\mathrm{long}}\)      | primary serial-context policy            |
| \(\epsilon\)                 | negligible-effect margin                 |
| MDE                          | minimum detectable risk difference       |
| \(\epsilon_{\mathrm{spec}}\) | harness-ablation specification tolerance |
| \(\epsilon_{\mathrm{leak}}\) | communication-leakage tolerance          |
| \(p_d\)                      | paired discordance estimate from Stage 0 |
| ICC / clustering parameter   | task-family dependence estimate          |
| rerun policy                 | infrastructure-failure handling          |
| multiplicity families        | preregistered hypothesis groups          |

---

# 57. Reporting table

Report one row per cell.

Include at minimum:

| Field                             |
| --------------------------------- |
| Reference vintage                 |
| Archival / non-archival status    |
| Model identifier                  |
| Harness commit                    |
| Inference stack                   |
| Tool versions                     |
| Environment snapshot              |
| Seed policy                       |
| Arm ID                            |
| \(N\)                             |
| Communication condition           |
| Environment coupling              |
| Environment class                 |
| Calibration/public/private status |
| Declared \(B_A\)                  |
| Realized \(B_A\)                  |
| Declared \(B_D\)                  |
| Realized \(B_D\)                  |
| Blocks attempted                  |
| Agent failures                    |
| Infrastructure errors             |
| Valid runs                        |
| Successes                         |
| \(P(Y_A=1)\)                      |
| Confidence interval               |
| Paired contrasts                  |
| Discordant pairs                  |
| Reliability measure               |
| Leakage/canary rate               |
| Placebo attention rate            |
| Validator–human agreement         |
| Validator-targeting events        |
| Multiplicity method               |

Do not summarize the full benchmark into one opaque scalar.

---

# 58. Kill criteria

## Stage 0 / Phase 0

Redesign or stop if:

* leakage cannot be controlled;
* positive-control effects cannot be detected near the MDE;
* infrastructure error rises prohibitively with \(N\);
* resource matching cannot be enforced;
* known-ordering control cannot be recovered;
* reliability is too low for system comparison.

---

## Phase I

Do not claim a useful defender benchmark if:

* defender rankings are unstable across fresh seeds;
* differences are dominated by floor/ceiling effects;
* uncertainty is too wide to distinguish plausible systems;
* rankings reverse unpredictably across minor benchmark perturbations.

---

## Phase II

Stop or narrow if:

* Phase-I communication effects are negligible at the resolution the study can establish;
* \(\Gamma_j\) effects fail the \(N=1\) specification test;
* feature effects are dominated by environment-specific artifacts;
* sensitive mechanism results cannot be governed under the prewritten access policy.

---

# 59. Claims benchmark v1 must not make

Do not claim:

* that Phase 0 ranks defender systems;
* that a non-significant communication result proves no meaningful effect;
* that practical equivalence has been established unless the equivalence test was powered;
* that \(N^*\) is an intrinsic property of a model;
* that \(A3-A1\) measures concurrency;
* that explicit communication is isolated when null and treatment arms use different environment coupling;
* that \(\Gamma_j\) is mechanistically interpretable if the \(N=1\) specification test fails;
* that Banzhaf or Shapley values apply over an infeasible feature lattice without adjustment;
* that two-model replication establishes cross-model generality;
* that canary probes identify the exact source of benchmark contamination;
* that unique-attack union counts demonstrate superlinear swarm capability;
* that Phase III adaptive harness search is directly comparable to the static benchmark.

---

# 60. Research questions

### RQ0 — Benchmark validity

Can the validated instrument reliably distinguish defender systems?

### RQ1 — Depth

How much capability comes from giving one agent more total compute?

### RQ2 — Breadth

At matched total budget, how much capability comes from multiple independent trajectories?

### RQ3 — Concurrency

How much additional capability comes from executing those trajectories simultaneously?

### RQ4 — Stigmergy

How much capability comes from interaction through shared mutable state without explicit messaging?

### RQ5 — Explicit communication

How much additional capability comes from an explicit semantic communication channel?

### RQ6 — Communication overhead

How does placebo/non-semantic communication affect performance?

### RQ7 — Environment dependence

How do divisibility, shared state, and partial observability change these effects?

### RQ8 — Defender discrimination

Which defender systems perform better under standardized swarm pressure?

### RQ9 — Harness mediation

Which harness features have:

$$
\Gamma_j(N)\neq0?
$$

### RQ10 — Harness interaction

Which harness mechanisms are complementary, redundant, or suppressive?

### RQ11 — Cross-model dependence

How stable are harness-mediated scaling effects across models?

### RQ12 — Benchmark exposure

How different are performance profiles on public versus private environments?

### RQ13 — Adaptive search

Can harness optimization discover stronger swarm configurations than static human-designed harnesses?

### RQ14 — Disclosure

Which mechanistic results can be released without unnecessarily increasing adversarial capability?

---

# 61. Final research sequence

1. Write validator specification.
2. Define attacker and defender resource vectors.
3. Build environment pool.
4. Stratify and randomize into calibration/public/private sets.
5. Implement archival reference systems.
6. Build A5/A7 pilot.
7. Run Stage 0.
8. Estimate nuisance parameters and realized cost.
9. Finalize MDE, equivalence margin, and sample size.
10. Freeze confirmatory preregistration.
11. Run Phase 0 instrument validation.
12. Confirm sensitivity, discrimination, and reliability.
13. Proceed to Phase I defender comparison.
14. Establish benchmark ranking stability.
15. Finalize Phase-II disclosure/access policy.
16. Run harness-feature screening.
17. Confirm selected \(\Gamma_j\) effects on held-out tasks.
18. Replicate high-value findings across additional models.
19. Only then consider adaptive harness search.
20. Treat \(N=100\) and larger as explicit expansion decisions.

---

# 62. Conservative contribution statement

The strongest defensible initial contribution is:

> **We introduce a controlled evaluation framework for adversarial model–harness systems that decomposes apparent swarm capability into single-agent depth, independent breadth, concurrency, shared-state stigmergy, explicit communication, and specific harness mechanisms. Before using the framework as a defender benchmark, we validate its sensitivity, discrimination, and reliability, and then evaluate defender systems under fixed reference attacker conditions and explicit resource budgets.**

A stronger claim about emergence, critical swarm size, or general swarm intelligence should only follow if supported empirically.

---

# 63. One-paragraph summary

The project should no longer begin by asking whether a large swarm crosses a dramatic capability threshold. It should first establish a valid measurement instrument. Stage 0 estimates nuisance parameters, resource consumption, leakage, attrition, and paired discordance. Phase 0 then decomposes performance into depth, breadth, concurrency, stigmergy, and explicit communication using matched-resource controls, shared-state nulls, graded positive controls, known-ordering discrimination controls, and reliability testing. Only after that instrument passes validation does Phase I use it to compare defender systems under a fixed archival reference attacker. Phase II then freezes model weights and systematically removes feasible harness capabilities to estimate swarm-specific mechanism effects \(\Gamma_j(N)\), subject to a prewritten disclosure and access policy. Phase III permits adaptive harness optimization and is treated as adversarial search rather than a stable benchmark. The resulting framework is intended to support causal measurement even if no sharp swarm-emergence phenomenon exists.
