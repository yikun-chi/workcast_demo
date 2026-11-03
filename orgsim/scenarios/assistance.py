"""Explicit workload assumptions for exploratory AI assistance, shared by worlds.

This models expected effort across assisted and unassisted tasks. It does not
infer AI efficacy from the historical validation data or call a language model.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Assistance:
    activities: tuple[str, ...]
    coverage: float
    time_saved: float
    review_overhead: float
    rework_rate: float
    rework_effort: float

    @classmethod
    def from_dict(cls, value: dict) -> "Assistance":
        activities = value.get("activities")
        if not isinstance(activities, list) or not activities or any(not isinstance(a, str) or not a for a in activities):
            raise ValueError("AI assistance needs a nonempty list of activity IDs")
        numbers = {}
        for name, upper in (("coverage", 1), ("time_saved", 1), ("review_overhead", 2), ("rework_rate", 1), ("rework_effort", 3)):
            v = value.get(name)
            if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or not 0 <= v <= upper:
                raise ValueError(f"AI {name} must be a finite number between 0 and {upper}")
            numbers[name] = float(v)
        out = cls(tuple(activities), **numbers)
        if out.effort_factor <= 0:
            raise ValueError("AI assistance must retain positive human effort")
        return out

    @property
    def effort_factor(self) -> float:
        return 1 - self.coverage * (self.time_saved - self.review_overhead - self.rework_rate * self.rework_effort)


def assistance_by_activity(interventions: list[dict], known: set[str]) -> dict[str, Assistance]:
    out = {}
    for intervention in interventions:
        if intervention.get("type") != "ai_assist":
            continue
        rule = Assistance.from_dict(intervention)
        for activity in rule.activities:
            if activity not in known:
                raise ValueError(f"Unknown AI-assisted activity: {activity}")
            if activity in out:
                raise ValueError(f"Duplicate AI assistance for activity: {activity}")
            out[activity] = rule
    return out
