"""Optional LangGraph fan-out adapter. SDK objects never escape this module.

The default worker is a deterministic fixture, not an LLM. A custom worker must
return a typed Proposal; change worker_version when changing its model or prompt.
Framework checkpoints resume execution; the application journal owns decisions.
"""
import operator
from pathlib import Path
from typing import Annotated, Callable, TypedDict

from .rule_planner import assign_task
from ..workflow.contracts import Observation, Plan, Proposal, Task, digest


class GraphState(TypedDict):
    observation: dict
    proposals: Annotated[list[dict], operator.add]


class LangGraphPlanner:
    def __init__(self, checkpoint_path: Path, *, worker: Callable[[Observation, Task], Proposal] = assign_task,
                 worker_version: str = "fastest-skilled-worker-v1", max_concurrency: int = 4):
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if worker is not assign_task and worker_version == "fastest-skilled-worker-v1":
            raise ValueError("Custom workers must declare their model/prompt version")
        self.checkpoint_path = checkpoint_path
        self.worker = worker
        self.worker_version = worker_version
        self.max_concurrency = max_concurrency

    @property
    def identity(self) -> dict[str, str]:
        return {"adapter": "langgraph", "policy": self.worker_version, "graph": "assignment-fanout-v1"}

    def plan(self, observation: Observation) -> Plan:
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
            from langgraph.graph import END, START, StateGraph
            from langgraph.types import Send
        except ImportError as error:
            raise RuntimeError("Install the optional planner: uv sync --extra dev --extra langgraph") from error

        def dispatch(state):
            return [Send("worker", {"observation": state["observation"], "task": task})
                    for task in state["observation"]["tasks"]] or END

        def work(state):
            obs = Observation.model_validate(state["observation"])
            proposal = self.worker(obs, Task.model_validate(state["task"]))
            return {"proposals": [proposal.model_dump(mode="json")]}

        builder = StateGraph(GraphState)
        builder.add_node("dispatch", lambda state: {})
        builder.add_node("worker", work)
        builder.add_edge(START, "dispatch")
        builder.add_conditional_edges("dispatch", dispatch, ["worker", END])
        builder.add_edge("worker", END)
        thread_id = digest({"observation": digest(observation), "planner": self.identity})
        config = {"configurable": {"thread_id": thread_id}, "max_concurrency": self.max_concurrency}
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        with SqliteSaver.from_conn_string(str(self.checkpoint_path)) as saver:
            graph = builder.compile(checkpointer=saver)
            checkpoint = graph.get_state(config)
            if checkpoint.values and not checkpoint.next:
                result = checkpoint.values
            else:
                initial = None if checkpoint.values else {"observation": observation.model_dump(mode="json"), "proposals": []}
                result = graph.invoke(initial, config, durability="sync")
        proposals = tuple(sorted((Proposal.model_validate(p) for p in result["proposals"]), key=lambda p: p.task_id))
        fixture = self.worker is assign_task
        return Plan(proposals=proposals, model="deterministic" if fixture else self.worker_version,
                    prompt_version="none" if fixture else self.worker_version,
                    input_tokens=0 if fixture else None, output_tokens=0 if fixture else None,
                    planning_cost=0 if fixture else None)
