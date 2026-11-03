"""Deterministic process scheduler. Only this module assigns simulated time.

Planners assign people/AI; the kernel owns effort, quality draws, capacity and
review/rework. Time is continuous operating hours, with no implied shift calendar.
"""
from dataclasses import dataclass
import math

from .contracts import Observation, Plan, Proposal, command_id, digest

KERNEL_VERSION = "task-workflow-v1"


def validate_plan(observation: Observation, plan: Plan) -> tuple[Proposal, ...]:
    resources = {r.id: r for r in observation.resources}
    tasks = {t.id: t for t in observation.tasks}
    commands: dict[str, Proposal] = {}
    for proposal in plan.proposals:
        old = commands.get(proposal.command_id)
        if old is not None and old != proposal:
            raise ValueError("Conflicting reuse of a command ID")
        commands[proposal.command_id] = proposal
        if proposal.task_id not in tasks or proposal.command_id != command_id(observation, proposal.task_id):
            raise ValueError("Unknown task or command ID for this observation")
        for field in ("assignee_id", "reviewer_id", "correction_assignee_id"):
            worker = resources.get(getattr(proposal, field))
            if worker is None or tasks[proposal.task_id].skill not in worker.skills:
                raise ValueError("Assignment references an unknown or unqualified resource")
            if field != "assignee_id" and worker.kind != "human":
                raise ValueError("Review and correction require human capacity")
    if {p.task_id for p in commands.values()} != set(tasks):
        raise ValueError("Plan must assign every visible task exactly once")
    return tuple(sorted(commands.values(), key=lambda p: p.task_id))


@dataclass(frozen=True)
class Operation:
    id: str
    task_id: str
    stage: str
    resource_id: str
    effort_h: float
    arrival_h: float
    dependencies: tuple[str, ...]


def simulate(observation: Observation, plan: Plan, seed: int) -> dict:
    proposals = validate_plan(observation, plan)  # validate the entire batch before any state changes
    resources = {r.id: r for r in observation.resources}
    tasks = {t.id: t for t in observation.tasks}
    needs_correction = {}
    for proposal in proposals:
        task, worker = tasks[proposal.task_id], resources[proposal.assignee_id]
        # A keyed draw gives matched randomness across policies and worker order.
        u = int(digest({"seed": seed, "task": task.id})[:13], 16) / 16**13
        needs_correction[task.id] = u < min(1, task.error_probability * worker.error_multiplier)
    terminal = {t.id: f"{t.id}:" + ("correction" if needs_correction[t.id] else "review") for t in observation.tasks}
    pending = {}
    for p in proposals:
        task = tasks[p.task_id]
        operations = [
            Operation(f"{task.id}:work", task.id, "work", p.assignee_id, task.work_h, task.arrival_h,
                      tuple(terminal[d] for d in task.depends_on)),
            Operation(f"{task.id}:review", task.id, "review", p.reviewer_id, task.review_h, task.arrival_h, (f"{task.id}:work",)),
        ]
        if needs_correction[task.id]:
            operations.append(Operation(f"{task.id}:correction", task.id, "correction", p.correction_assignee_id,
                                        task.rework_h, task.arrival_h, (f"{task.id}:review",)))
        pending.update({op.id: op for op in operations})
    slots = {r.id: [0.0] * r.capacity for r in observation.resources}
    finish: dict[str, float] = {}
    events = []
    while pending:
        ready = []
        for op in pending.values():
            if all(dep in finish for dep in op.dependencies):
                slot = min(range(len(slots[op.resource_id])), key=lambda i: (slots[op.resource_id][i], i))
                released = max([op.arrival_h, *(finish[d] for d in op.dependencies)])
                start = max(released, slots[op.resource_id][slot])
                ready.append((start, op.id, slot, released))
        if not ready:
            raise ValueError("Workflow has no executable operation")
        start, op_id, slot, released = min(ready)
        op = pending.pop(op_id)
        resource = resources[op.resource_id]
        duration = op.effort_h / resource.speed
        end = start + duration
        if not math.isfinite(end):
            raise ValueError("Non-finite simulated duration")
        slots[resource.id][slot] = end
        finish[op_id] = end
        if start < observation.horizon_h:
            performed = min(end, observation.horizon_h) - start
            events.append({"operation_id": op_id, "task_id": op.task_id, "stage": op.stage, "resource_id": resource.id,
                           "slot": slot, "start_h": start, "end_h": end, "performed_h": performed,
                           "wait_h": start - released, "complete": end <= observation.horizon_h})
    events.sort(key=lambda e: (e["start_h"], e["operation_id"]))
    completed = [t for t in observation.tasks if finish[terminal[t.id]] <= observation.horizon_h]
    reviewed = [t for t in observation.tasks if finish[f"{t.id}:review"] <= observation.horizon_h]
    cycles = [finish[terminal[t.id]] - t.arrival_h for t in completed]
    return {"kernel": KERNEL_VERSION, "seed": seed, "events": events,
            "applied_command_ids": [p.command_id for p in proposals],
            "outcomes": {"completed_tasks": len(completed), "throughput_per_hour": len(completed) / observation.horizon_h,
                         "mean_elapsed_h": sum(cycles) / len(cycles) if cycles else None,
                         "staff_effort_h": sum(e["performed_h"] for e in events if resources[e["resource_id"]].kind == "human"),
                         "correction_rate": sum(needs_correction[t.id] for t in reviewed) / len(reviewed) if reviewed else None,
                         "service_cost": sum(e["performed_h"] * resources[e["resource_id"]].hourly_cost for e in events
                                             if resources[e["resource_id"]].kind == "ai")}}
