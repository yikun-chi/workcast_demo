# Task-planner exploration

`task_workflow.json` is an authored task-and-capacity example, separate from the
registered real-data instances. It contains assumed arrivals, effort, quality,
resources and service rates. It has no observed outcome or accuracy claim.

Run the deterministic planner with the base installation:

```bash
uv run orgsim workflow --planner rule
```

Run the same policy through the optional LangGraph adapter:

```bash
uv sync --locked --extra dev --extra langgraph
uv run --extra langgraph orgsim workflow --planner langgraph
```

Both commands hold tasks, resources and seed fixed. Their business outcomes should
match: this checks framework interchangeability, not an AI productivity improvement.
Changing the planner's software concurrency does not change business capacity:

```bash
uv run --extra langgraph orgsim workflow --planner langgraph --planner-options '{"max_concurrency": 1}'
```

The command prints a run key, artifact path, trace and computed outcomes. Outputs
stay in ignored `runs/workflow/`. `decisions.sqlite` stores the portable input,
planner identity, accepted plan and completed simulation; `langgraph.sqlite` is
framework execution state. Replay a printed run key without either the planner or
its SDK:

```bash
uv run orgsim workflow --replay <run-key>
```

Use `--spec path/to/scenario.json` for another authored workload. Unknown fields and
missing availability timestamps are rejected. Task versions after the cutoff do
not enter observations. Every task needs a skilled worker and a skilled human for
review/correction. Capacity is simultaneous work slots; time is continuous operating
hours with no inferred working-day calendar. Error rates, speeds and costs are
assumptions supplied in the file. Corrections consume human effort and are assumed
to resolve the error. There is no residual-quality or adoption model here.

The planner chooses assignments for a fixed task DAG. The kernel creates work,
review and conditional correction operations, enforces capacity and dependencies,
then computes:

- Completed tasks and throughput within the supplied horizon.
- Mean arrival-to-completion hours among completed tasks (null if none).
- Human hours actually worked within the horizon, including review and correction.
- Fraction of reviewed tasks requiring correction (null if none reviewed).
- AI service cost for work performed, using the supplied hourly rate.

Planning API costs are separate metadata, never added to simulated effort. The
builtin planners call no paid model; their planning usage/cost is zero. Custom
worker usage is unknown unless supplied through a full adapter.

## Plug in another planner

An installed module exports a factory taking `checkpoint_dir` and its options. Its
returned object needs only:

```python
from orgsim.workflow.contracts import Observation, Plan

class MyPlanner:
    @property
    def identity(self) -> dict[str, str]:
        return {"adapter": "my-framework", "policy": "my-policy", "model": "my-model", "prompt": "my-prompt"}

    def plan(self, observation: Observation) -> Plan:
        # Run your framework internally; translate its output into a validated
        # Plan, with command_id(observation, task.id) for each task.
        # Include actual provider usage/cost, or null when unknown.
        ...

def create(*, checkpoint_dir, **options):
    return MyPlanner()
```

The skeleton is an interface illustration; supply the implementation in your own
package. Then select it without modifying the kernel or application:

```bash
uv run orgsim workflow --planner my_package.planner:create --planner-options '{}'
```

This route supports an adapter implemented with Microsoft Agent Framework or any
other planner. No Microsoft SDK integration is bundled. SDK execution, credentials,
model calls and checkpoints stay inside that package; the simulation receives only
portable proposals. Change the planner identity whenever its behavior changes to
avoid reusing a decision for a different policy. Keep external calls idempotent for
retries; the demo journal does not guarantee exactly-once calls to external APIs.
