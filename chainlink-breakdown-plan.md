# Chainlink Breakdown Plan

This plan breaks the MVP described in `mvp-plan.md` into dependency-ordered epics and tasks. The dashboard and second model remain outside the critical path.

## Epic 1: Experiment Contract and Runtime Isolation

**Goal:** Establish the controlled execution environment before building experiment logic.

### Tasks

1. **Pin Pi runtime and model configuration**
   - Define the Pi version, model, token budget, timeout, and launch command.
   - Acceptance: one agent starts reproducibly with built-in tools disabled.

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

6. **Implement event replay**
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
   - Run the same task, prompt, model, agent count, and token budget under C0, C1, and C2.

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
   - Compare `U(C1) - U(C0)`.
   - Compare `U(C1) - U(C2)`.
   - Compare `Y(C2) - Y(C0)`.

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
5. Telemetry reconstructs information flow.
6. At least one C1 transfer trace is observed.
7. The same transfer is absent under C2.
8. Repeated runs produce basic task-success and uptake metrics.

Task 2, the dashboard, statistical intervals, second-model replication, and Task 3 should be treated as progressively lower-priority work.

## Decisions to Lock Before Creating Tickets

1. **C2 semantics:** Agents may append messages, but can only read their own messages.
2. **Uptake definition:** A seeded token is the initial deterministic signal; semantic uptake can be added later.
3. **Task 2 isolation:** Repository tools must read from each agent's isolated copy, never a shared filesystem.
4. **Run unit:** One swarm run contains three agents performing the same task under one condition.
5. **Model scope:** One model with more replicates is the MVP default.
6. **Dashboard priority:** Visualization is useful for the demo but should not block experiment correctness.
7. **Task order:** Task 1 is the positive control and should be completed before Task 2.

## Review Note

The main adjustment to the original MVP plan is making telemetry and evaluation first-class infrastructure rather than treating them as work added after the experiment runs. Without that, the core information-flow claim cannot be demonstrated reliably.
