"""Discrete-event scheduler bucketed to the hourly clock."""
from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(order=True)
class ScheduledEvent:
    when: datetime
    seq: int
    kind: str = field(compare=False)
    payload: dict[str, Any] = field(compare=False, default_factory=dict)


class Scheduler:
    def __init__(self) -> None:
        self._heap: list[ScheduledEvent] = []
        self._seq = itertools.count()

    def schedule(self, when: datetime, kind: str, **payload: Any) -> ScheduledEvent:
        ev = ScheduledEvent(when=when, seq=next(self._seq), kind=kind, payload=payload)
        heapq.heappush(self._heap, ev)
        return ev

    def due(self, until: datetime) -> list[ScheduledEvent]:
        """Pop every event with when <= until, in order."""
        out: list[ScheduledEvent] = []
        while self._heap and self._heap[0].when <= until:
            out.append(heapq.heappop(self._heap))
        return out

    def peek(self) -> datetime | None:
        return self._heap[0].when if self._heap else None

    def __len__(self) -> int:
        return len(self._heap)
