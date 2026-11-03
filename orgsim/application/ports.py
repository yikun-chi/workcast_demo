"""Business interfaces. No world, filesystem, HTTP or agent-framework imports.

Snapshot and planner ports are generic so each domain can expose a narrow, typed
observation rather than giving a planner access to a world or a data directory.
"""
from datetime import datetime
from typing import Any, Protocol


class DataSnapshot[T](Protocol):
    def read(self, as_of: datetime) -> T: ...


class TaskPlanner[Observation, Proposal](Protocol):
    @property
    def identity(self) -> dict[str, str]: ...

    def plan(self, observation: Observation) -> Proposal: ...


class RunSink(Protocol):
    run_id: str
    n_events: int

    def write_event(self, event: Any) -> None: ...
    def write_rows(self, rows: Any) -> None: ...
    def write_json(self, name: str, payload: Any) -> Any: ...
    def close(self, summary: dict) -> Any: ...
    def abort(self) -> None: ...


class RunRepository(Protocol):
    def begin(self, scenario: dict, seed: int, metadata: dict) -> RunSink: ...


class SimulationModel(Protocol):
    def run(self, scenario: dict, seed: int, sink: RunSink) -> dict: ...


class OutcomeScorer(Protocol):
    def evaluate(self, scenario_ids: list[str]) -> dict: ...


class ResultsPresenter(Protocol):
    def present(self) -> dict: ...


class DecisionRepository(Protocol):
    """Write-once journal: repeating identical writes is safe; conflicts fail."""
    def read(self, kind: str, key: str) -> dict | None: ...
    def write_once(self, kind: str, key: str, value: dict) -> None: ...
