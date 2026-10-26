"""World base classes. The kernel owns state mutation; policies only propose actions."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from ..instances import InstanceContext
from ..store.trace import TraceEvent
from ..store.runs import RunWriter
from .clock import Clock
from .scheduler import Scheduler


@dataclass
class Agent:
    id: str
    role: str
    org_unit: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)   # demographic + psychological, editable
    state: dict[str, Any] = field(default_factory=dict)        # latent, mutable during the run
    seat: str = ""                                            # policy seat name (model assignment)


@dataclass
class WorkItem:
    id: str
    kind: str
    created_at: datetime
    attributes: dict[str, Any] = field(default_factory=dict)
    history: list[str] = field(default_factory=list)          # activity ids so far
    state: dict[str, Any] = field(default_factory=dict)
    closed_at: datetime | None = None


@dataclass
class RunSummary:
    run_id: str
    instance: str
    scenario: str
    seed: int
    start: str
    end: str
    ticks: int
    events: int
    headline: dict[str, Any] = field(default_factory=dict)   # world-specific key numbers for the UI

    def to_json(self) -> dict[str, Any]:
        return self.__dict__


@runtime_checkable
class World(Protocol):
    """Every world type implements this. Instances configure a world type; they never subclass it."""

    @classmethod
    def from_instance(cls, ctx: InstanceContext, scenario: dict[str, Any], seed: int) -> "World": ...

    def run(self, writer: RunWriter) -> RunSummary: ...


class BaseWorld:
    """Convenience base: clock, scheduler, trace emission."""

    def __init__(self, ctx: InstanceContext, scenario: dict[str, Any], seed: int, start: datetime, end: datetime) -> None:
        self.ctx = ctx
        self.scenario = scenario
        self.seed = seed
        self.clock = Clock(start=start, end=end)
        self.scheduler = Scheduler()
        self.agents: dict[str, Agent] = {}
        self.items: dict[str, WorkItem] = {}
        self._writer: RunWriter | None = None
        self._n_events = 0

    def emit(self, **kw: Any) -> TraceEvent:
        ev = TraceEvent(tick=self.clock.tick, sim_time=self.clock.now, **kw)
        assert self._writer is not None, "emit() called before run()"
        self._writer.write_event(ev)
        self._n_events += 1
        return ev
