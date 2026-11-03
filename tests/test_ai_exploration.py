"""AI workload assumptions, queue propagation, and neutral-policy invariants."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from orgsim.instances import get_instance
from orgsim.kernel import CapacityPool
from orgsim.scenarios import load_scenario, list_scenarios
from orgsim.scenarios.assistance import Assistance, assistance_by_activity


def assumption(**overrides):
    return {"type": "ai_assist", "activities": ["task"], "coverage": .6, "time_saved": .4,
            "review_overhead": .15, "rework_rate": .1, "rework_effort": 1., **overrides}


def test_assistance_accounts_for_unassisted_work_review_and_corrections():
    ai = Assistance.from_dict(assumption())
    assert ai.effort_factor == pytest.approx(.91)
    assert Assistance.from_dict(assumption(coverage=0)).effort_factor == 1
    assert Assistance.from_dict(assumption(review_overhead=.6)).effort_factor > 1
    for overrides in ({"coverage": 1.1}, {"time_saved": float("nan")}, {"rework_rate": -1}, {"coverage": True}):
        with pytest.raises(ValueError):
            Assistance.from_dict(assumption(**overrides))
    with pytest.raises(ValueError, match="Unknown"):
        assistance_by_activity([assumption()], {"different-task"})


def test_ai_effort_changes_queue_service_and_neutral_setting_is_identical():
    def run(cost):
        pool = CapacityPool(role="invoice", headcount=1, actions_per_person_hour=6)
        for i in range(20):
            pool.enqueue(i, 0)
        served = []
        pool.drain(2, lambda item, wait: served.append((item, wait)), cost)
        return served, pool.backlog(), pool.used_this_hour
    ordinary = run(None)
    assert run(lambda _: 1) == ordinary
    assert len(run(lambda _: .5)[0]) == 12
    assert len(run(lambda _: 1.5)[0]) == 4
    pool = CapacityPool(role="invoice", headcount=1, actions_per_person_hour=1)
    pool.enqueue("task", 0)
    with pytest.raises(ValueError):
        pool.drain(0, lambda *_: None, lambda _: 0)
    assert pool.backlog() == 1


def test_both_instances_expose_the_existing_and_ai_alternatives():
    for instance, existing in (("trip", "hybrid_for_all"), ("bpi19", "no_expansion")):
        ctx = get_instance(instance)
        roles = {s["id"]: s["role"] for s in list_scenarios(ctx)}
        assert roles[existing] == "alternative"
        assert roles["ai_assistant"] == "alternative_2"
        scenario = load_scenario(ctx, "ai_assistant")
        known = {a["id"] for a in ctx.yaml("ontology/bindings.yaml")["activities"]}
        assert assistance_by_activity(scenario["interventions"], known)


def test_saved_ai_results_are_hidden_when_settings_or_reference_change(tmp_path, monkeypatch):
    from orgsim.evaluation import exploration
    scenario = {"id": "ai", "interventions": [assumption()]}
    baseline = {"id": "baseline"}
    ctx = SimpleNamespace(runs_dir=tmp_path, world_type="workforce", meta={"scenarios": {"additional_alternatives": ["ai"]}})
    (tmp_path / "evaluation.json").write_text('{}')
    head = {"headcount": 10, "workload": {"human_hours": 100, "unassisted_hours": 100, "review_hours": 0, "rework_hours": 0}}
    ai_head = deepcopy(head); ai_head["workload"]["human_hours"] = 91
    record = {"config_hash": exploration._hash(scenario), "baseline_hash": exploration._hash(baseline), "model_hash": "model",
              "evaluation_hash": hashlib.sha256(b'{}').hexdigest(), "generated": "test", "seeds": [1], "cutoffs": ["test"],
              "pairs": [{"baseline": {"headline": head}, "alternative": {"headline": ai_head}}]}
    (tmp_path / "explorations.json").write_text(json.dumps({"ai": record}))
    monkeypatch.setattr(exploration, "load_scenario", lambda _ctx, sid: baseline if sid == "baseline" else scenario)
    monkeypatch.setattr(exploration, "model_fingerprint", lambda _ctx: "model")
    view = exploration.exploration_views(ctx)[0]
    assert view["state"] == "ready" and view["metrics"][0]["delta"] == -9
    scenario["interventions"][0]["coverage"] = .8
    view = exploration.exploration_views(ctx)[0]
    assert view["state"] == "stale" and view["metrics"] == []
    scenario["interventions"][0]["coverage"] = .6
    (tmp_path / "evaluation.json").write_text('{"changed": true}')
    view = exploration.exploration_views(ctx)[0]
    assert view["state"] == "stale" and view["metrics"] == []


def test_procurement_reference_reuse_requires_matching_model_and_inputs(tmp_path):
    from orgsim.evaluation.exploration import _saved_process_baselines
    ctx = SimpleNamespace(runs_dir=tmp_path)
    directory = tmp_path / "baseline" / "saved-run"
    directory.mkdir(parents=True)
    (directory / "config.json").write_text(json.dumps({"scenario": {"id": "baseline"}}))
    record = {"model_hash": "model", "evaluation_hash": "evaluation", "baseline_hash": "configuration",
              "pairs": [{"cutoff": "2018-09-03", "seed": 1, "baseline": {"scenario": "baseline", "run_id": "saved-run"}}]}
    (tmp_path / "explorations.json").write_text(json.dumps({"ai": record}))
    assert len(_saved_process_baselines(ctx, "model", "evaluation", "configuration")) == 1
    for values in (("changed", "evaluation", "configuration"), ("model", "changed", "configuration"), ("model", "evaluation", "changed")):
        assert _saved_process_baselines(ctx, *values) == {}
    (directory / "config.json").unlink()
    assert _saved_process_baselines(ctx, "model", "evaluation", "configuration") == {}


def test_ai_comparison_keeps_the_reference_policy_and_time_period():
    from orgsim.evaluation.exploration import _validate_ai_comparison
    for instance in ("trip", "bpi19"):
        ctx = get_instance(instance)
        baseline, ai = load_scenario(ctx, "baseline"), load_scenario(ctx, "ai_assistant")
        _validate_ai_comparison(baseline, ai)
        changed = deepcopy(ai)
        changed["horizon_days"] += 1
        with pytest.raises(ValueError, match="time period"):
            _validate_ai_comparison(baseline, changed)
        changed = deepcopy(ai)
        changed["interventions"].append({"type": "headcount_shift", "role": "all", "multiplier": .5})
        with pytest.raises(ValueError, match="staffing"):
            _validate_ai_comparison(baseline, changed)


@pytest.mark.data
def test_workforce_ai_effort_does_not_invent_retention_or_trace_effects():
    from orgsim.worlds.workforce import World
    class Writer:
        run_id = "test"
        def write_rows(self, rows): pass
        def write_json(self, name, data): pass
    ctx = get_instance("trip")
    baseline = load_scenario(ctx, "baseline")
    baseline["world"].update(end="2021-08-20", survey_dates=["2021-08-20"], review_period={"id": "test", "date": "2021-08-20"}, work_events="none")
    ai = deepcopy(baseline)
    ai["interventions"] = load_scenario(ctx, "ai_assistant")["interventions"]
    worlds = []
    for scenario in (baseline, ai):
        world = World.from_instance(ctx, scenario, 17)
        world.run(Writer())
        worlds.append(world)
    assert worlds[0].metrics == worlds[1].metrics
    assert worlds[1].workload["human_hours"].sum() < worlds[0].workload["human_hours"].sum()
    neutral = deepcopy(ai)
    neutral["interventions"][0]["coverage"] = 0
    world = World.from_instance(ctx, neutral, 17)
    world.run(Writer())
    assert world.metrics == worlds[0].metrics
    np.testing.assert_array_equal(world.workload["human_hours"], worlds[0].workload["human_hours"])
    traced = deepcopy(ai)
    traced["world"]["work_events"] = "all"
    world = World.from_instance(ctx, traced, 17)
    world.run(Writer())
    for key in world.workload:
        np.testing.assert_array_equal(world.workload[key], worlds[1].workload[key])
