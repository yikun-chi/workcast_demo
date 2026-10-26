"""Reference policies: transparent stochastic rules. Default seat filler for every instance."""
from __future__ import annotations

from typing import Any, Callable

from .base import Action, Observation


class RulePolicy:
    """Choose among kernel-provided options using weights in option['weight'] (default: uniform)."""

    name = "rule"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = params or {}

    def decide(self, obs: Observation, rng: Any) -> Action:
        if not obs.options:
            return Action(kind="wait")
        weights = [float(o.get("weight", 1.0)) for o in obs.options]
        total = sum(weights)
        if total <= 0:
            choice = obs.options[0]
        else:
            r = rng.random() * total
            acc = 0.0
            choice = obs.options[-1]
            for o, w in zip(obs.options, weights):
                acc += w
                if r <= acc:
                    choice = o
                    break
        return Action(kind=choice.get("kind", "do_activity"), target=choice.get("target"), params=choice.get("params", {}))

    def describe(self) -> dict[str, Any]:
        return {"adapter": "rule", "params": self.params}


class CallablePolicy:
    """Wrap a world-specific function as a policy (keeps world logic swappable for an LLM seat)."""

    name = "callable"

    def __init__(self, fn: Callable[[Observation, Any], Action], label: str = "callable") -> None:
        self.fn, self.label = fn, label

    def decide(self, obs: Observation, rng: Any) -> Action:
        return self.fn(obs, rng)

    def describe(self) -> dict[str, Any]:
        return {"adapter": "callable", "label": self.label}
