"""Portable JSON contracts; no planner-framework state crosses this boundary."""
import hashlib
import json
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Value(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class Resource(Value):
    id: str = Field(min_length=1)
    kind: Literal["human", "ai"]
    skills: tuple[str, ...]
    capacity: int = Field(default=1, gt=0, strict=True)
    speed: float = Field(default=1, gt=0)
    hourly_cost: float = Field(default=0, ge=0)
    error_multiplier: float = Field(default=1, ge=0)


class Task(Value):
    id: str = Field(min_length=1)
    skill: str
    arrival_h: float = Field(default=0, ge=0)
    work_h: float = Field(gt=0)
    review_h: float = Field(gt=0)
    rework_h: float = Field(gt=0)
    error_probability: float = Field(default=0, ge=0, le=1)
    depends_on: tuple[str, ...] = ()


class TaskRecord(Value):
    task: Task
    effective_at: AwareDatetime
    available_at: AwareDatetime


class Observation(Value):
    as_of: AwareDatetime
    tasks: tuple[Task, ...]
    resources: tuple[Resource, ...]
    horizon_h: float = Field(gt=0)

    @model_validator(mode="after")
    def valid_graph(self):
        task_ids = {t.id for t in self.tasks}
        if len(task_ids) != len(self.tasks) or len({r.id for r in self.resources}) != len(self.resources):
            raise ValueError("Task and resource IDs must be unique")
        remaining = {t.id: set(t.depends_on) for t in self.tasks}
        if any(not deps <= task_ids for deps in remaining.values()):
            raise ValueError("Task dependency missing from the available snapshot")
        done: set[str] = set()
        while remaining:
            ready = {key for key, deps in remaining.items() if deps <= done}
            if not ready:
                raise ValueError("Task dependencies contain a cycle")
            done |= ready
            remaining = {k: v for k, v in remaining.items() if k not in ready}
        return self


class Proposal(Value):
    command_id: str = Field(min_length=1)
    task_id: str
    assignee_id: str
    reviewer_id: str
    correction_assignee_id: str
    rationale: str = ""


class Plan(Value):
    proposals: tuple[Proposal, ...]
    model: str
    prompt_version: str
    input_tokens: int | None = Field(default=None, ge=0, strict=True)
    output_tokens: int | None = Field(default=None, ge=0, strict=True)
    planning_cost: float | None = Field(default=None, ge=0)
    fallback: str | None = None


class WorkflowSpec(Value):
    """Authored exploration inputs; never a registered real-data instance."""
    as_of: AwareDatetime
    records: tuple[TaskRecord, ...]
    resources: tuple[Resource, ...]
    horizon_h: float = Field(gt=0)
    seed: int = Field(default=1, strict=True)


def digest(value) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def command_id(observation: Observation, task_id: str) -> str:
    return digest({"observation": digest(observation), "task": task_id})
