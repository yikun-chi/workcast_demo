"""Deterministic assignment policy, also usable as a framework worker fixture."""
from ..workflow.contracts import Observation, Plan, Proposal, Task, command_id


def assign_task(observation: Observation, task: Task) -> Proposal:
    eligible = [r for r in observation.resources if task.skill in r.skills]
    humans = [r for r in eligible if r.kind == "human"]
    if not eligible or not humans:
        raise ValueError(f"Task {task.id} needs a skilled worker and human reviewer")
    worker = min(eligible, key=lambda r: (task.work_h / r.speed, r.id))
    reviewer = min(humans, key=lambda r: (task.review_h / r.speed, r.id))
    return Proposal(command_id=command_id(observation, task.id), task_id=task.id,
                    assignee_id=worker.id, reviewer_id=reviewer.id, correction_assignee_id=reviewer.id,
                    rationale="Fastest eligible worker; human review and correction required")


class RulePlanner:
    @property
    def identity(self) -> dict[str, str]:
        return {"adapter": "rule", "policy": "fastest-skilled-worker-v1"}

    def plan(self, observation: Observation) -> Plan:
        return Plan(proposals=tuple(assign_task(observation, task) for task in observation.tasks),
                    model="deterministic", prompt_version="none", input_tokens=0, output_tokens=0, planning_cost=0)
