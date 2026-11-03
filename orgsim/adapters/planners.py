"""Planner composition and extension loading; the domain never imports SDKs."""
import importlib
from pathlib import Path


def load_planner(name: str, directory: Path, options: dict | None = None):
    options = options or {}
    if name == "rule":
        from .rule_planner import RulePlanner
        if options:
            raise ValueError("The rule planner has no options")
        return RulePlanner()
    if name == "langgraph":
        from .langgraph_planner import LangGraphPlanner
        return LangGraphPlanner(directory / "langgraph.sqlite", **options)
    if ":" not in name:
        raise ValueError("Planner must be rule, langgraph, or an installed module:factory")
    # Explicit local configuration only, never an HTTP/untrusted-input endpoint.
    module, factory = name.split(":", 1)
    planner = getattr(importlib.import_module(module), factory)(checkpoint_dir=directory, **options)
    if not callable(getattr(planner, "plan", None)) or not isinstance(getattr(planner, "identity", None), dict):
        raise TypeError("Planner factory must return the TaskPlanner contract")
    return planner
