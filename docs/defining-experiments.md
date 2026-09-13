# Defining an experiment

An experiment is a directory. Its specification names one task statement that
every agent receives verbatim, and the private context injected into each
agent's isolated task directory. `experiment_spec.py` describes and validates
that definition; it does not talk to a model, read the board, or know about
conditions beyond their names.

## Shape

```json
{
  "experiment_id": "cache-outage-v1",
  "task": {
    "task_id": "cache-outage",
    "statement": "<the single statement every agent reads, verbatim>",
    "acceptance_terms": ["<term>", "<term>", "<term>"]
  },
  "agents": [
    {
      "agent_id": "agent-1",
      "capability_profile": "task-diagnostic-v1",
      "context": [{"path": "application.log", "content": "<private evidence>"}],
      "canary": "<string that appears only in this agent's context>"
    }
  ],
  "conditions": ["C0", "C1", "C2"],
  "seeds": [1, 2, 3, 4, 5]
}
```

There is one `statement` field, so the shared part is shared by construction:
`statement_for(agent_id)` returns the same text for every agent. Per-agent
injection is the `context` list, and it is the only place where agents differ.

## Enforced invariants

A specification that violates any of these raises `ExperimentSpecError` at
construction, so a broken experiment cannot reach a run:

| Invariant | Why |
| --- | --- |
| No agent's context alone contains every acceptance term | Otherwise that agent succeeds without the others, its success is independent of the condition, and the primary contrast is diluted |
| Each canary appears in its own agent's context and in no other | A canary observed elsewhere is then evidence of transfer rather than of coincidence |
| Neither the statement nor the injected context names the arm or the channel | The agent must not be able to infer which condition it is in |
| Context paths are relative and contained | Injection cannot write outside the agent's own task directory |
| At least two agents, unique ids, resolvable capability profiles | Fails closed rather than silently running a degenerate cell |
| Conditions unique and ordered `C0, C1, C2`; seeds unique and positive | Keeps paired triplets comparable across arms |

## Choosing acceptance terms

List only what the *evidence* has to supply. A term that the statement already
provides is present in no agent's context, so it satisfies the interdependence
check for free and hides a self-sufficient agent. The current Task 1 fixture is
the worked example: with all five validator terms, including `outage`, which
only the statement supplies, the specification is accepted; with the four terms
the evidence must supply, it is rejected because `agent-2` holds them all.

## Layout

`write_experiment(spec, root)` creates the experiment's own folder, `0700`:

```
<root>/<experiment_id>/
  experiment.json     canonical specification
  digest.txt          sha256 of the canonical specification
  agents/<agent_id>/context/<path>
  runs/               where controller run roots go
```

Point the controller at that folder to keep a run beside the definition that
produced it:

```
python scripts/run_experiment.py --output experiments/<experiment_id>/runs/<label>
```

Writing the same specification twice is idempotent; writing a different one
into an occupied folder is refused, so a digest always identifies exactly one
definition.

## Use

```python
from apart_incident_response.experiment_spec import (
    load_experiment, materialize_agent_context, write_experiment,
)

spec = load_experiment("experiments/cache-outage-v1")
spec.sha256                       # pin this in the run manifest
spec.statement_for("agent-1")     # identical for every agent
spec.canaries()                   # per-agent, for uptake detection
materialize_agent_context(spec, workspace.task_dir, "agent-1")
```

`materialize_agent_context` writes only that agent's files, which is the
filesystem half of the isolation boundary.

Tests: `PYTHONPATH=src:. python -m unittest tests.test_experiment_spec`
