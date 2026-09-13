# Neutral task prompts

The controller keeps task instructions in the runtime configuration under the
top-level `prompts` object, keyed by task ID. The checked-in configuration
defines the Task 1 prompt in `config/runtime.json`.

When `AgentRun.run()` receives no explicit prompt, it calls
`RuntimeConfig.prompt_for(task_id, seed)`. That selector validates the task and
seed, then resolves the configured task text. The condition is deliberately
not an input to prompt selection, so the same task and seed produce byte
identical prompts in C0, C1, and C2. The seed identifies the deterministic task
instance; the initial Task 1 catalog uses one neutral prompt for the task.

The Task 1 prompt asks the agent to diagnose the incident, determine the most
likely root cause, and submit a diagnosis with cited evidence. It identifies
the available diagnostic interface (`task_read`, `task_query`, and
`task_submit`) without suggesting collaboration, delegation, or board use.

The CLI accepts `--prompt` and `--prompt-file` for explicit controller test
overrides. Benchmark runs should omit both options so the configured task
prompt is selected and recorded in the run's `metadata.json`.
