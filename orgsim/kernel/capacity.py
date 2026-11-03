"""Bounded capacity per role (or team) per hour. Work that exceeds capacity waits in the queue.

VDT lineage: attention is finite, waiting is separate from labor.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable
import math


@dataclass
class CapacityPool:
    role: str
    headcount: float                     # active people (can be fractional for archetype pools)
    actions_per_person_hour: float       # throughput when working
    queue: deque = field(default_factory=deque)
    used_this_hour: float = 0.0
    total_served: int = 0
    total_wait_hours: float = 0.0
    utilization_log: list[float] = field(default_factory=list)

    @property
    def hourly_capacity(self) -> float:
        return self.headcount * self.actions_per_person_hour

    def reset_hour(self) -> None:
        cap = self.hourly_capacity
        self.utilization_log.append(min(1.0, self.used_this_hour / cap) if cap > 0 else 0.0)
        self.used_this_hour = 0.0

    def has_capacity(self) -> bool:
        return self.used_this_hour < self.hourly_capacity

    def enqueue(self, item: Any, arrived_hour: int) -> None:
        self.queue.append((arrived_hour, item))

    def drain(self, now_hour: int, serve: Callable[[Any, float], None], effort: Callable[[Any], float] | None = None) -> int:
        """Start queued actions while hourly capacity remains.

        Effort is measured in ordinary-action equivalents. The default retains
        the existing one-action accounting; assisted tasks can use less or more.
        As with ordinary tasks, the last action may finish across the hour boundary.
        """
        n = 0
        while self.queue and self.has_capacity():
            cost = float(effort(self.queue[0][1])) if effort else 1.0
            if not math.isfinite(cost) or cost <= 0:
                raise ValueError("Action effort must be positive and finite")
            arrived, item = self.queue.popleft()
            wait = float(now_hour - arrived)
            self.used_this_hour += cost
            self.total_served += 1
            self.total_wait_hours += wait
            serve(item, wait)
            n += 1
        return n

    def backlog(self) -> int:
        return len(self.queue)

    def mean_utilization(self) -> float:
        return sum(self.utilization_log) / len(self.utilization_log) if self.utilization_log else 0.0
