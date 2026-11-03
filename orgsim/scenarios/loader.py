"""Scenario YAMLs under instances/<id>/scenarios/. `baseline.yaml` is the reference; others override it.

scenario.yaml:
  id: baseline
  title: ...
  description: ...
  extends: baseline            # optional; deep-merged over the parent
  horizon_days: 14
  seeds: [1, 2, 3]
  world: {...}                 # world-type specific parameters (passed to World.from_instance)
  interventions: [...]         # free-form, interpreted by the world type
"""
from __future__ import annotations

import copy
from typing import Any

import yaml

from ..instances import InstanceContext


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def scenario_roles(ctx: InstanceContext) -> dict[str, str]:
    """Named baseline, primary alternative, and additional alternatives shown in the UI."""
    roles = ctx.meta.get("scenarios") or {}
    out = {str(roles.get("baseline", "baseline")): "baseline"}
    if roles.get("alternative"):
        out[str(roles["alternative"])] = "alternative"
    for number, scenario in enumerate(roles.get("additional_alternatives") or [], start=2):
        if str(scenario) in out:
            raise ValueError(f"Duplicate named scenario: {scenario}")
        out[str(scenario)] = f"alternative_{number}"
    return out


def list_scenarios(ctx: InstanceContext) -> list[dict[str, Any]]:
    out = []
    roles = scenario_roles(ctx)
    if ctx.scenarios_dir.exists():
        for p in sorted(ctx.scenarios_dir.glob("*.yaml")):
            d = yaml.safe_load(p.read_text()) or {}
            d.setdefault("id", p.stem)
            out.append({"id": d["id"], "title": d.get("title", d["id"]), "short_title": d.get("short_title", d.get("title", d["id"])), "summary": d.get("summary", ""), "description": d.get("description", ""), "extends": d.get("extends"), "file": p.name,
                        "role": roles.get(d["id"], "other")})
    order = {"baseline": 0, "alternative": 1, "other": 2}
    return sorted(out, key=lambda s: (order.get(s["role"], 1), s["role"], s["id"]))


def load_scenario(ctx: InstanceContext, scenario_id: str, _depth: int = 0) -> dict[str, Any]:
    p = ctx.scenarios_dir / f"{scenario_id}.yaml"
    if not p.exists():
        raise FileNotFoundError(p)
    d = yaml.safe_load(p.read_text()) or {}
    d.setdefault("id", scenario_id)
    parent = d.get("extends")
    if parent and _depth < 5:
        base = load_scenario(ctx, parent, _depth + 1)
        merged = deep_merge(base, {k: v for k, v in d.items() if k != "extends"})
        merged["id"] = d["id"]
        merged["extends"] = parent
        return merged
    return d
