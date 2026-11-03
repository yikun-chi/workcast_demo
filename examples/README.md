# Runnable examples

[task_workflow.json](task_workflow.json) is an authored task-and-capacity scenario,
separate from the registered real-data instances. Its inputs are assumptions;
it has no observed outcome or accuracy claim.

From the repository root, after [installation](../docs/setup.md#installation):

```bash
uv run orgsim workflow --planner rule
```

Outputs go to ignored `runs/workflow/`. See the
[task-planner guide](../docs/task-planners.md) for optional LangGraph installation,
framework adapters, outcome definitions and replay.
