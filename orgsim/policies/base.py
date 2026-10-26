"""Behavioral policy interface. A policy observes and proposes; the kernel validates and applies.

Every AI seat (employee archetype, team, executive) is a Policy behind this interface so that a
rule-based policy, a hosted LLM, or a local fine-tuned model can be swapped by configuration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class Observation:
    """What a seat is allowed to see at a choice point. Must never contain held-out truth."""
    agent_id: str
    role: str
    sim_time: str
    context: dict[str, Any] = field(default_factory=dict)   # queue, case prefix, state, colleagues ...
    options: list[dict[str, Any]] = field(default_factory=list)  # candidate actions the kernel considers valid


@dataclass
class Action:
    kind: str                      # e.g. "do_activity", "handoff", "wait", "take_up_wfh", "quit", "message"
    target: str | None = None      # activity id / agent id / case id, kind-specific
    params: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""            # free text from LLM seats; stored in the trace, never scored


@runtime_checkable
class Policy(Protocol):
    name: str

    def decide(self, obs: Observation, rng: Any) -> Action: ...

    def describe(self) -> dict[str, Any]: ...
