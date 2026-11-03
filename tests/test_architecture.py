"""Application ports preserve existing world dispatch and run artifacts."""
import json
from types import SimpleNamespace

import pytest

from orgsim.application.simulation import SimulationService
from orgsim.composition import instance_service
from orgsim.instances import list_instances


@pytest.mark.parametrize("ctx", list_instances(), ids=lambda ctx: ctx.id)
def test_existing_instances_use_same_world_and_artifacts(ctx, monkeypatch, tmp_path):
    from orgsim.worlds import world_module
    import orgsim.store.runs as store
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path)
    calls = []

    class World:
        @classmethod
        def from_instance(cls, instance, scenario, seed):
            calls.append((instance, scenario, seed))
            return cls()

        def run(self, sink):
            sink.write_json("metrics.json", {"output": 42})
            return SimpleNamespace(to_json=lambda: {"headline": {"output": 42}, "seed": 7})

    module = world_module(ctx)
    monkeypatch.setattr(module, "World", World)
    monkeypatch.setattr(module, "evaluate", lambda c, ids: {"ids": ids, "instance": c.id})
    monkeypatch.setattr(module, "results_view", lambda c: {"instance": c.id, "before": "observed"})
    service = instance_service(ctx)
    scenario = {"id": "baseline", "world": {"setting": 1}}
    result = service.run(scenario, 7, metadata={"purpose": "test"})
    assert calls == [(ctx, scenario, 7)]
    path = tmp_path / ctx.id / "baseline" / result.run_id
    assert json.loads((path / "config.json").read_text()) == {"instance": ctx.id, "scenario": scenario, "seed": 7, "purpose": "test"}
    assert json.loads((path / "summary.json").read_text()) == result.summary
    assert json.loads((path / "metrics.json").read_text()) == {"output": 42}
    assert (path / "trace.parquet").exists()
    assert service.evaluate(["baseline"]) == {"instance": ctx.id, "ids": ["baseline"]}
    assert service.results() == {"instance": ctx.id, "before": "observed"}


def test_failed_model_aborts_without_publishing_success():
    calls = []
    sink = SimpleNamespace(close=lambda s: calls.append("closed"), abort=lambda: calls.append("aborted"))
    def fail(*args):
        raise ValueError("invalid model input")
    service = SimulationService(SimpleNamespace(run=fail), SimpleNamespace(begin=lambda *args: sink), None, None)
    with pytest.raises(ValueError, match="invalid model input"):
        service.run({"id": "baseline"}, 1)
    assert calls == ["aborted"]


def test_cli_and_exploration_use_application_service(monkeypatch):
    from orgsim import cli
    from orgsim.evaluation import exploration
    calls = []
    def run(scenario, seed, **kwargs):
        calls.append((scenario, seed, kwargs))
        return SimpleNamespace(run_id="test-run", n_events=2, summary={"headline": {"n": 2}})
    service = SimpleNamespace(run=run)
    monkeypatch.setattr(cli, "instance_service", lambda ctx: service)
    monkeypatch.setattr(exploration, "instance_service", lambda ctx: service)
    ctx = list_instances()[0]
    cli._run(ctx, "baseline", 1)
    assert exploration._run_one(ctx.id, {"id": "baseline"}, 2)["headline"] == {"n": 2}
    assert calls[1] == ({"id": "baseline"}, 2, {"metadata": {"purpose": "exploration"}})


def test_http_presenter_uses_application_service(monkeypatch):
    from orgsim.server import app
    monkeypatch.setattr(app, "instance_service", lambda ctx: SimpleNamespace(results=lambda: {"instance": ctx.id}))
    assert app.results("trip") == {"instance": "trip"}


def test_core_has_no_framework_or_storage_dependency():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "orgsim"
    for folder in ("application", "workflow"):
        for file in (root / folder).glob("*.py"):
            if file.name == "cli.py":  # inbound adapter
                continue
            tree = ast.parse(file.read_text())
            for node in ast.walk(tree):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
                assert all(not any(part in name.split(".") for part in ("adapters", "langgraph", "langchain", "agent_framework", "fastapi", "sqlite3", "worlds", "store")) for name in names), file


@pytest.mark.data
def test_real_workforce_run_matches_direct_execution(tmp_path, monkeypatch):
    """Same numerical outputs and trace through the new boundary, using real twins."""
    import pandas as pd
    from orgsim.instances import get_instance
    from orgsim.scenarios import load_scenario
    from orgsim.worlds.workforce import World
    import orgsim.store.runs as store
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path)
    ctx = get_instance("trip")
    scenario = load_scenario(ctx, "baseline")
    scenario["world"].update(end="2021-08-20", survey_dates=["2021-08-20"],
                             review_period={"id": "test", "date": "2021-08-20"}, work_events="none")
    direct = store.RunWriter(ctx.id, scenario["id"], run_id="reference")
    expected = World.from_instance(ctx, scenario, 17).run(direct).to_json()
    direct.close(expected)
    actual = instance_service(ctx).run(scenario, 17)
    assert {k: v for k, v in expected.items() if k != "run_id"} == {k: v for k, v in actual.summary.items() if k != "run_id"}
    path = tmp_path / ctx.id / scenario["id"] / actual.run_id
    for filename in ("metrics.json", "twins.json"):
        assert json.loads((path / filename).read_text()) == json.loads((direct.dir / filename).read_text())
    pd.testing.assert_frame_equal(pd.read_parquet(path / "trace.parquet"), pd.read_parquet(direct.dir / "trace.parquet"))
