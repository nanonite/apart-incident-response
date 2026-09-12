# Build Plan: Restricted Two-Agent Response Dynamics

## Protocol replacement

[mvp-plan.md](mvp-plan.md) replaces the old three-agent protocol. Section 8 remains intact. C2 is scheduled unlock revealing earlier permitted peer updates plus future updates, not permanent own-entry reads. Use response_dynamics_v1 provenance to prevent historical label collisions.

The existing Chainlink implementation tickets were drafted against the old protocol. Their historical wording is superseded; update acceptance criteria before executing them. Do not mark unimplemented features complete. Task/provider decisions and teammate ownership are still pending.

## 1. Contracts and environment

- Freeze strict shared contracts listed in mvp-plan.md; keep analysis independent of runtime imports.
- Confirm task/evidence allocation, primary probability space, teammate interfaces and provider authentication.
- Prepare a pinned environment, fake adapter and model capability metadata. Runtime/language choice is pending; Pi is not an established dependency.
- Plan local inference first, with configurable remote endpoint transport later. No cluster or Modal provisioning in the MVP.
- Enforce the approximately USD 100 overall ceiling with bounded requests, per-run/batch accounting and reserve before dispatch. Distinguish subscription access from API-key billing.

Acceptance: a deterministic fixture validates observation/update/artifact contracts without paid inference. Ownership boundaries and unresolved research choices are explicit.

## 2. Runner, containment and event log

- Exactly two identities with separate task/session state and Section 8-only tools.
- One append-only researcher event log; constant logging across conditions.
- Fixed checkpoint count/config; bounded tools, retries, timeouts and token/cost usage.
- Proposed synchronous snapshot semantics; physical serial calls may save memory.
- Every completed checkpoint has two valid TaskUpdates. Preserve malformed raw output and incomplete checkpoints rather than inventing answers.

Acceptance: fake agents cannot access peer data except through permitted projections, impersonate identities, alter budgets or use broader tools. All attempts and usage are traceable.

## 3. Visibility and C0/C1/C2

- Implement policies over the same global log, with configured event allowlist/serializer/bandwidth.
- C0: own history only; C1: permitted shared history from start.
- C2: no peer access before k; at k reveal eligible prior updates through k-1, then future eligible updates at subsequent checkpoints.
- Enforce the peer snapshot cutoff in board reads as well as initial observations.
- Record availability, send/read, delivery and uptake independently; record exact delivered IDs/context.

Acceptance: tests cover C0 leakage, C1 delivery, retrospective C2 unlock, step-0 boundary, no same-step visibility, excluded researcher/private events, and invalid unlock settings. For an intervention run require an interior unlock; boundary settings can be explicit equivalence/control checks.

## 4. Task updates, scoring and semantic samples

- Alejandro owns task/input progression and representation. Start with one objective synthetic task once selected.
- Bound task tools to private data; make same versus complementary evidence allocation explicit.
- Inspect and reuse Alejandro's nearly completed input work once its location is supplied. Preserve raw/current answers and exact context provenance. Embeddings are optional; see semantic-entropy-live-plan.md.
- Evaluator emits separate task quality, evidence and uptake annotations; no feedback into agent context by default.

Acceptance: every successful update is traceable to its exact observation and exported semantic sample/evaluation. Analysis failure remains visible and does not overwrite the update.

## 5. Repeated runs and analysis

- Proposed smoke matrix: one task, three conditions, five repeats, two agents, six steps = 180 updates/model, before tools/retries/calibration.
- Export run/replicate/pair IDs, resolved config hashes and incomplete-run metadata.
- Juan Camilo owns replaceable probability and metric plugins reading stored artifacts.
- Proposed first path: contextual semantic equivalence, recorded partitions, cluster frequencies and entropy in bits. Keep per-agent and pooled distributions separate.
- Distinguish cross-run response diversity from optional fixed-checkpoint uncertainty probes. Budget extra generations and judging explicitly.
- Keep source manifests, missingness, aggregation weights and estimator provenance.

Acceptance: recompute a plotted entropy point without invoking the runtime. Reject invalid probabilities and incompatible state spaces. Label the pilot descriptive, not confirmatory.

## 6. Panel and intervention inspection

- Shared experiment/task/run/step selection with modular controls, timeline, agents, global log, representation, physics, communication and optimization views.
- Expose C2 unlock, first delivery, task scores, failures and exact source context.
- Live raw events with asynchronous semantic metrics, pending/provisional states, sample counts and analysis lag; avoid active-run mutation. Bound observer resource use so it cannot silently perturb the local runner.

Acceptance: click a point/checkpoint to inspect the underlying runs, probabilities, updates and communication events.

## 7. Later influence and optimization

- Add visible/masked replay branches from a pre-exposure checkpoint with independent provider state.
- Label single-response semantic/action/evaluator differences as proxies; use repeated samples for distribution comparisons.
- Add TextGrad-inspired offline critic only after completed batches. Produce a reviewable candidate configuration for the next batch; no intra-run changes.

Acceptance: replay intervention and source provenance are explicit; critic cannot mutate running configs.

## Priority and exclusions

Runner -> global log/visibility -> C0/C1/C2 -> mandatory updates -> raw/semantic sample export -> aggregation -> live semantic entropy panel -> intervention markers -> influence -> offline critic.

Defer C3, adaptive policies, extra agent tools, actual TextGrad integration, general orchestration, large model sweeps and remote infrastructure deployment. A successful build does not require communication to help or entropy to increase.
