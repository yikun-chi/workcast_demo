"""Hourly simulation clock. The hour is the finest tick; several activities may happen inside one."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

HOUR = timedelta(hours=1)


@dataclass
class Clock:
    start: datetime
    end: datetime
    tick: int = 0
    work_hours: tuple[int, int] = (8, 18)      # inclusive start, exclusive end, local hours considered "working"
    work_days: tuple[int, ...] = (0, 1, 2, 3, 4)  # Monday=0 .. Friday=4
    _now: datetime = field(init=False)

    def __post_init__(self) -> None:
        self._now = self.start

    @property
    def now(self) -> datetime:
        return self._now

    @property
    def done(self) -> bool:
        return self._now >= self.end

    def advance(self) -> datetime:
        self._now += HOUR
        self.tick += 1
        return self._now

    def is_working_hour(self, t: datetime | None = None) -> bool:
        t = t or self._now
        return t.weekday() in self.work_days and self.work_hours[0] <= t.hour < self.work_hours[1]

    def hours_until(self, t: datetime) -> float:
        return (t - self._now) / HOUR

    def __iter__(self):
        while not self.done:
            yield self._now
            self.advance()
