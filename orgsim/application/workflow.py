"""Plan, validate, persist and simulate through framework-independent contracts."""
from dataclasses import dataclass
from datetime import datetime

from .ports import DataSnapshot, DecisionRepository, TaskPlanner
from ..workflow.contracts import Observation, Plan, digest
from ..workflow.kernel import KERNEL_VERSION, simulate, validate_plan


@dataclass
class WorkflowService:
    snapshot: DataSnapshot[Observation]
    planner: TaskPlanner[Observation, Plan]
    journal: DecisionRepository

    def run(self, as_of: datetime, seed: int) -> dict:
        observation = self.snapshot.read(as_of)
        identity = dict(self.planner.identity)
        decision_key = digest({"observation": digest(observation), "planner": identity})
        decision = self.journal.read("decision", decision_key)
        if decision is None:
            plan = self.planner.plan(observation)
            validate_plan(observation, plan)
            decision = {"observation": observation.model_dump(mode="json"), "planner": identity,
                        "plan": plan.model_dump(mode="json")}
            # Commit the decision before applying it to the simulation. If execution
            # fails afterwards, recovery uses exactly these proposals, with no calls.
            self.journal.write_once("decision", decision_key, decision)
        plan = Plan.model_validate(decision["plan"])
        run_key = digest({"decision": decision_key, "seed": seed, "kernel": KERNEL_VERSION})
        completed = self.journal.read("run", run_key)
        if completed is None:
            result = simulate(observation, plan, seed)
            completed = {"run_key": run_key, "decision_key": decision_key, "result": result}
            self.journal.write_once("run", run_key, completed)
        return completed


def replay(journal: DecisionRepository, run_key: str) -> dict:
    """Verify kernel replay without loading any planner, SDK or credentials."""
    saved = journal.read("run", run_key)
    if saved is None:
        raise ValueError(f"Unknown workflow run {run_key}")
    decision = journal.read("decision", saved["decision_key"])
    if decision is None:
        raise ValueError("Run is missing its recorded decision")
    if saved["result"]["kernel"] != KERNEL_VERSION:
        raise ValueError("Replay needs the recorded kernel version")
    result = simulate(Observation.model_validate(decision["observation"]), Plan.model_validate(decision["plan"]), saved["result"]["seed"])
    if result != saved["result"]:
        raise ValueError("Replay differs from the persisted simulation checkpoint")
    return saved
