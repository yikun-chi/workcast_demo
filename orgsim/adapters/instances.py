"""Compatibility adapters for the four existing scientific world modules.

These preserve their numerical behavior and artifacts. Existing evaluators still
own their batch runs and file-based calibration; this is an incremental boundary,
not a claim that their internal data-availability issues have been resolved.
"""
from dataclasses import dataclass

from ..application.ports import RunSink
from ..instances import InstanceContext
from ..store import RunWriter
from ..worlds import world_module


class LocalRunSink(RunWriter):
    def abort(self) -> None:
        # Release an open parquet stream without publishing a successful run.
        if self._writer is not None:
            self._writer.close()


@dataclass
class LocalRunRepository:
    ctx: InstanceContext

    def begin(self, scenario: dict, seed: int, metadata: dict) -> LocalRunSink:
        config = {**metadata, "instance": self.ctx.id, "scenario": scenario, "seed": seed}
        return LocalRunSink(self.ctx.id, scenario["id"], config=config)


@dataclass
class InstanceModel:
    ctx: InstanceContext

    def run(self, scenario: dict, seed: int, sink: RunSink) -> dict:
        summary = world_module(self.ctx).World.from_instance(self.ctx, scenario, seed).run(sink)
        return summary.to_json() if hasattr(summary, "to_json") else summary


@dataclass
class InstanceScorer:
    ctx: InstanceContext

    def evaluate(self, scenario_ids: list[str]) -> dict:
        additional = (self.ctx.meta.get("scenarios") or {}).get("additional_alternatives", [])
        result = world_module(self.ctx).evaluate(self.ctx, [sid for sid in scenario_ids if sid not in additional])
        from ..evaluation.exploration import build_exploration
        for sid in additional:
            if sid in scenario_ids:
                build_exploration(self.ctx, sid)
        return result


@dataclass
class InstancePresenter:
    ctx: InstanceContext

    def present(self) -> dict:
        return world_module(self.ctx).results_view(self.ctx)
