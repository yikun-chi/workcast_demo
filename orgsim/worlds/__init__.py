"""World types. An instance's instance.yaml names one via `world_type`; the world reads the instance's configs.

  process    - cases flow through activities performed by role pools under capacity and process constraints
               (event-log instances such as bpi19; later the demo firm's work processes)
  workforce  - a population of employees with latent states reacting to policies over time
               (randomized-trial instances such as trip; later the demo firm's people dynamics)
  airline    - carriers flying a published schedule through airports with daily weather and air-traffic conditions;
               operations control chooses cancellation postures, disruption carries over (airline_ops)
  attention  - readers with daily information needs on reference articles and drifting habits of coming to them;
               alternatives add AI answer channels (wiki_ai_traffic)

Each module exposes:  World class (orgsim.kernel.world.World protocol)
                      evaluate(ctx, scenario_ids: list[str]) -> dict   (writes runs/<id>/evaluation.json)
"""
from __future__ import annotations

import importlib
from typing import Any

from ..instances import InstanceContext

WORLD_MODULES = {"process": "orgsim.worlds.process", "workforce": "orgsim.worlds.workforce", "market": "orgsim.worlds.market"}
WORLD_MODULES["airline"] = "orgsim.worlds.airline"          # carriers flying a schedule through airport conditions (airline_ops)
WORLD_MODULES["attention"] = "orgsim.worlds.attention"      # readers' needs and habits on reference articles (wiki_ai_traffic)


def world_module(ctx: InstanceContext):
    wt = ctx.world_type
    if wt not in WORLD_MODULES:
        raise ValueError(f"instance {ctx.id}: unknown or missing world_type {wt!r}; expected one of {list(WORLD_MODULES)}")
    return importlib.import_module(WORLD_MODULES[wt])


def world_class(ctx: InstanceContext) -> Any:
    return getattr(world_module(ctx), "World")
