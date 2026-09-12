# Chainlink Breakdown Plan

This plan breaks the MVP described in `mvp-plan.md` into dependency-ordered epics and tasks. The dashboard and second model remain outside the critical path.

Research positioning is informed by Kim et al., *Capable language models can outgrow the benefits of collaboration* ([source PDF](docs/pdfs/s42256-026-01268-y-1.pdf); [local Markdown extraction](docs/markdown/s42256-026-01268-y-1/s42256-026-01268-y-1.md)). That paper is a useful methodological baseline, but this experiment asks a different question.

## What Makes This Experiment Different

Kim et al. compare deliberately constructed single-agent and multi-agent architectures—independent, centralized, decentralized, and hybrid—to determine when explicit coordination improves task performance. This plan instead treats coordination as a security property that can emerge through infrastructure not intended to be a communication channel.

| Dimension | Kim et al. | This plan's distinct contribution |
|---|---|---|
| Research question | When does a prescribed multi-agent architecture outperform a single agent? | Will otherwise isolated agents discover and repurpose a shared operational surface, and can access control stop the resulting information flow? |
| Coordination mechanism | Agents are placed into explicit communication and orchestration topologies. | Agents receive neutral task prompts and no collaboration protocol; the append-only board merely exists as infrastructure. |
| Experimental intervention | Vary communication topology and model capability. | Vary only board visibility: absent (`C0`), globally readable (`C1`), or own-writes-only (`C2`). |
| Primary outcome | Task success and architecture-selection performance. | Provenance-backed cross-agent uptake: information originating with Agent A is read and subsequently used by Agent B. |
| Safety control | Verification or orchestration reduces error propagation. | `C2` preserves centralized logging/auditability while preventing agents from using the log as a cross-agent bus. |
| State isolation | Some software/terminal experiments share one container even in the paper's independent condition. | Each agent has an isolated workspace and identity; the board is the only permitted cross-agent surface. |
| Intended claim | Guidance for choosing a coordination architecture within tested domains. | Evidence about latent communication channels and least-privilege read containment, not a general claim that swarms are better or worse. |

The cleanest causal comparison is `C1` versus `C2`: both expose the same append interface, but only `C1` permits cross-agent reads. `C1` versus `C0` measures the broader behavioral effect of making the board available, while `C2` versus `C0` measures the containment control's operational cost.

## Design Controls Adopted From the Paper

1. **Match per-system compute, not merely per-agent settings.** Hold the aggregate swarm token ceiling, tool-call allowance, timeout, model, task instance, and agent count constant across `C0`, `C1`, and `C2`. Record actual usage so board traffic is counted as coordination overhead rather than free compute.
2. **Calibrate the single-agent baseline before the swarm matrix.** Run each task with one agent as a diagnostic baseline, not as a fourth board condition. Confirm that no single Task 1 bundle deterministically reveals the answer and record baseline success. The paper's approximately 45% saturation threshold is domain-specific and must not be imported as a universal cut-off.
3. **Separate transfer from utility.** A token appearing across agents proves channel use, not that collaboration helped. Report uptake together with task success and classify transferred evidence as useful/correct, redundant, or misleading when the trace permits it.
4. **Measure process costs.** In addition to reads and writes, record total turns, total tokens, wall-clock latency, and success per 1,000 tokens for every condition.
5. **Keep the inference narrow.** Five runs per condition are a pipeline shakedown and demo sample, not confirmatory evidence. Report raw runs and effect estimates descriptively; confidence intervals or significance claims require a separately justified sample size.

## Epic 1: Experiment Contract and Runtime Isolation

**Goal:** Establish the controlled execution environment before building experiment logic.

### Tasks

1. **Pin Pi runtime and model configuration**
   - Define the Pi version, model, per-agent limits, aggregate per-system token/tool-call ceiling, timeout, and launch command.
   - Acceptance: one agent starts reproducibly with built-in tools disabled, and the controller can enforce the same system-level compute ceiling in all three conditions.

2. **Define agent identity and run configuration**
   - Add `run_id`, `agent_id`, `condition`, `task_id`, and seed handling.
   - Acceptance: every agent has a unique runtime identity and isolated task directory.

3. **Implement side-channel restrictions**
   - Prevent shell, network, shared filesystem, subprocess, MCP, and subagent access.
   - Acceptance: agents can access only explicitly exposed experiment tools.

4. **Create single-agent lifecycle**
   - Implement start, prompt, tool-call, completion, timeout, and failure handling.
   - Acceptance: one agent run produces a complete artifact and exit status.

**Dependencies:** None.

## Epic 2: Constrained Agent Tool Interface

**Goal:** Expose only the tools required by the experiment.

### Tasks

1. **Implement core task tools**
   - `task_read`
   - `task_query`
   - `task_submit`

2. **Implement board tools**
   - `board_read`
   - `board_append`

3. **Implement tool validation**
   - Validate arguments, enforce task permissions, and reject unsupported paths or operations.

4. **Capture tool-call results**
   - Record inputs, outputs, timestamps, and errors for every tool invocation.

**Acceptance:** An agent can complete a simple task using only the constrained extension.

**Dependencies:** Epic 1.

## Epic 3: Append-Only Board and Containment Policies

**Goal:** Build the shared infrastructure and the three experimental conditions.

### Tasks

1. **Implement SQLite board schema**
   - Store sequence ID, run ID, agent ID, server timestamp, message body, and message size.

2. **Implement `board_append`**
   - Derive agent identity from credentials.
   - Prevent agents from selecting or impersonating another agent ID.

3. **Implement cursor-based `board_read`**
   - Return messages after a supplied sequence ID.
   - Support pagination or bounded reads if needed.

4. **Implement condition policies**
   - `C0`: board tools unavailable.
   - `C1`: all agents can read all messages.
   - `C2`: agents can append, but can only read their own messages.

5. **Add board contract tests**
   - Verify append ordering, cursor behavior, identity enforcement, and C1/C2 visibility.

6. **Run manual two-agent smoke test**
   - Agent 1 appends.
   - Agent 2 reads under C1.
   - Agent 2 cannot read the message under C2.

**Acceptance:** The same board API produces the intended C0, C1, and C2 behavior.

**Dependencies:** Epic 1. Epic 2 can be developed in parallel after the runtime contract is defined.

## Epic 4: Experimental Tasks, Prompts, and Validators

**Goal:** Create harmless tasks that make information transfer measurable.

### Tasks

1. **Build Task 1: split-evidence incident diagnosis**
   - Create three evidence bundles.
   - Seed unique harmless tokens such as `ORCHID-731`.
   - Define the expected diagnosis and answer validator.
   - Prove by construction and validator tests that no individual bundle uniquely determines the diagnosis, while the combined evidence does.

2. **Implement Task 1 submission**
   - Capture the final diagnosis, cited evidence, and token usage.

3. **Build Task 2: parallel codebase triage**
   - Create the synthetic `service-a`, `service-b`, `service-c`, and `tests` repository.
   - Seed one distributed logic bug.
   - Provide different diagnostic views to each agent.

4. **Implement restricted repository tools**
   - `repo_list`
   - `repo_read`
   - `repo_search`
   - `run_tests`
   - `submit_diagnosis`

5. **Define neutral agent prompts**
   - Do not instruct agents to collaborate.
   - Mention available diagnostic infrastructure without making collaboration the objective.

6. **Create deterministic task validators**
   - Validate root cause, file/function, proposed fix, task success, and seeded-token transfer.

7. **Run single-agent task calibration**
   - Run each evidence bundle without board access before the three-agent matrix.
   - Record task success, turns, tokens, and whether any bundle leaks the complete answer.
   - Treat this as task calibration, not as a fourth experimental condition.

**Acceptance:** Task 1 works end-to-end before Task 2 is started.

**Dependencies:** Epic 3 for board integration; Epic 1 for isolated workspaces.

## Epic 5: Telemetry, Uptake Detection, and Evaluation

**Goal:** Reconstruct information flow and measure task utility.

### Tasks

1. **Implement board telemetry**
   - Log operation, cursor values, messages returned, message IDs, bytes read, and bytes written.

2. **Implement agent-run telemetry**
   - Log model turns, tool calls, observations, final answer, validator result, and timestamps.

3. **Implement cross-agent uptake detection**
   - Detect when a seeded token created by Agent A is later mentioned or used by Agent B.
   - Record source agent, recipient agent, message ID, and uptake timestamp.

4. **Implement primary metric**
   - Cross-agent information uptake `U`.

5. **Implement supporting metrics**
   - Board reads `R`
   - Board writes `W`
   - Cross-agent messages read `X`
   - Uptake latency `L`
   - Message-read ratio `M`
   - Total turns and tokens
   - Coordination overhead relative to `C0`
   - Success per 1,000 tokens

6. **Classify uptake outcome**
   - Mark trace-supported uptake as useful/correct, redundant, or misleading.
   - Record whether uptake precedes a change in diagnosis, cited evidence, tool choice, or final submission.

7. **Implement event replay**
   - Reconstruct traces such as discovery, append, read, and subsequent answer change.

**Acceptance:** A completed run can produce a causal trace showing whether information crossed agent boundaries.

**Dependencies:** Epics 2 and 4.

## Epic 6: Experiment Controller and MVP Run Matrix

**Goal:** Automate reproducible experiments across conditions.

### Tasks

1. **Implement one-swarm controller**
   - Start three isolated agents.
   - Assign task bundles.
   - Apply one condition.
   - Collect artifacts and exit statuses.

2. **Implement condition configuration**
   - Run the same task, prompt, model, agent count, aggregate compute ceiling, and timeout under C0, C1, and C2.

3. **Implement seeded runs**
   - Support independent seeds and deterministic task instances.

4. **Implement experiment artifact layout**
   - Store prompts, configuration, logs, board state, outputs, validator results, and metrics per run.

5. **Automate Task 1 matrix**
   - Five runs each under C0, C1, and C2.

6. **Automate Task 2 matrix**
   - Add only after Task 1 is stable.
   - Five runs each under C0, C1, and C2.

7. **Generate basic result summaries**
   - Primary containment contrast: compare `U(C1) - U(C2)`.
   - Board-availability contrast: compare `U(C1) - U(C0)`.
   - Compare `Y(C2) - Y(C0)`.
   - Report coordination overhead and success per 1,000 tokens by condition.
   - Label the five-run matrix as descriptive/pilot evidence.

**Acceptance:** The controller can produce the planned 30 swarm runs for one model without manual intervention.

**Dependencies:** Epics 3, 4, and 5.

## Epic 7: Demo and Stretch Research

These tasks should not block the MVP.

### Tasks

1. **Build trace visualization**
   - Show agent discovery, board append, board read, uptake, and containment blocking.

2. **Add dashboard**
   - Compare the same task under C0, C1, and C2.

3. **Add confidence intervals and summary statistics**
   - Add these after the repeated-run pipeline is stable.

4. **Add second model**
   - Reuse the identical harness and prompts.

5. **Build Task 3: incident containment**
   - Use a fixed set of safe actions with distributed evidence across agents.

6. **Prepare final demo narrative**
   - Show one clean C1 transfer trace.
   - Show the same transfer absent under C2.
   - Show task-performance comparisons.

**Dependencies:** Epic 6.

## Dependency Order

```text
Epic 1: Runtime isolation
        ├── Epic 2: Tool interface
        └── Epic 3: Board and containment

Epic 2 + Epic 3
        └── Epic 4: Tasks and validators

Epic 3 + Epic 4
        └── Epic 5: Telemetry and evaluation

Epic 4 + Epic 5
        └── Epic 6: Controller and experiment matrix

Epic 6
        └── Epic 7: Dashboard, second model, Task 3
```

## MVP Cut Line

The MVP should end after the following are complete:

1. One isolated Pi agent works with restricted tools.
2. Three agents can run independently.
3. The board supports C0, C1, and C2.
4. Task 1 works with deterministic validation.
5. Single-agent calibration confirms that individual evidence bundles do not leak the complete diagnosis.
6. The same aggregate compute ceiling is enforced under C0, C1, and C2.
7. Telemetry reconstructs information flow and its coordination cost.
8. At least one C1 transfer trace is observed.
9. The same transfer is absent under C2.
10. Repeated runs produce basic task-success, uptake, and efficiency metrics with pilot-appropriate claims.

Task 2, the dashboard, statistical intervals, second-model replication, and Task 3 should be treated as progressively lower-priority work.

## Decisions to Lock Before Creating Tickets

1. **C2 semantics:** Agents may append messages, but can only read their own messages.
2. **Uptake definition:** A seeded token is the initial deterministic signal; semantic uptake can be added later.
3. **Task 2 isolation:** Repository tools must read from each agent's isolated copy, never a shared filesystem.
4. **Run unit:** One swarm run contains three agents performing the same task under one condition.
5. **Model scope:** One model with more replicates is the MVP default.
6. **Dashboard priority:** Visualization is useful for the demo but should not block experiment correctness.
7. **Task order:** Task 1 is the positive control and should be completed before Task 2.
8. **Fairness unit:** Compute is matched at the whole-swarm level across conditions; board operations do not create an unmetered budget.
9. **Primary contrast:** `C1` versus `C2` is the direct containment test; `C0` remains the independent-agent and operational-cost baseline, not a single-agent baseline.
10. **Evidence standard:** Seeded-token transfer establishes channel use; a utility claim additionally requires validator improvement or a trace-supported behavior change.
11. **Statistical scope:** The five-run matrix is descriptive. Confirmatory claims require a larger, prospectively justified sample.

## Review Note

The main adjustment to the original MVP plan is making telemetry and evaluation first-class infrastructure rather than treating them as work added after the experiment runs. The paper comparison sharpens the novelty: the experiment is not another multi-agent performance benchmark. It is a controlled test of whether an incidental shared surface becomes a communication channel, with a containment intervention that retains the surface's audit function. Without provenance, system-level compute accounting, and the `C1` versus `C2` counterfactual, that information-flow claim cannot be demonstrated reliably.
