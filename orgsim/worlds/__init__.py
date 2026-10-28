"""World types. An instance's instance.yaml names one via `world_type`; the world reads the instance's configs.

  process    - cases flow through activities performed by role pools under capacity and process constraints
               (event-log instances such as bpi19; later the demo firm's work processes)
  workforce  - a population of employees with latent states reacting to policies over time
               (randomized-trial instances such as trip; later the demo firm's people dynamics)
  market     - companies whose AI workloads run on models at published list prices (openrouter)
  demand     - customer segments buying each day from calendar habits, a drifting level and the price they pay
               (nyc_congestion)
  turnover   - each industry's employees by tenure, deciding monthly whether to quit (jolts_quits)

Each module exposes:  World class (orgsim.kernel.world.World protocol)
                      evaluate(ctx, scenario_ids: list[str]) -> dict   (writes runs/<id>/evaluation.json)
"""
from __future__ import annotations

import importlib
from typing import Any

from ..instances import InstanceContext

WORLD_MODULES = {"process": "orgsim.worlds.process", "workforce": "orgsim.worlds.workforce", "market": "orgsim.worlds.market",
                 "demand": "orgsim.worlds.demand", "turnover": "orgsim.worlds.turnover"}


def world_module(ctx: InstanceContext):
    wt = ctx.world_type
    if wt not in WORLD_MODULES:
        raise ValueError(f"instance {ctx.id}: unknown or missing world_type {wt!r}; expected one of {list(WORLD_MODULES)}")
    return importlib.import_module(WORLD_MODULES[wt])


def world_class(ctx: InstanceContext) -> Any:
    return getattr(world_module(ctx), "World")
