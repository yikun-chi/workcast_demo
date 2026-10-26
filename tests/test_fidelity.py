"""Regression checks for temporal isolation, reproducibility and forecast math."""
from collections import Counter
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from orgsim.instances import get_instance
from orgsim.scenarios import load_scenario
from orgsim.worlds import process, workforce


class MemoryWriter:
    run_id = "test"

    def write_rows(self, rows):
        pass

    def write_json(self, name, data):
        pass


def test_other_predictions_do_not_read_post_policy_outcomes(monkeypatch):
    ctx = get_instance("trip")
    original = Path.read_text

    def guarded(path, *args, **kwargs):
        assert path.name not in ("reference_outcomes.json", "evaluation.json", "metrics.json")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    c = workforce.attrition_comparators(ctx)
    assert c["no_change_pct"] == 9.8
    assert np.isclose(c["proportional_days_pct"], 7.35)
    assert np.isclose(c["proportional_days_effect_pp"], -2.45)
    # The method must react to the proposed policy, not a fixed desired result.
    from orgsim import scenarios
    original_load = scenarios.load_scenario

    def office_only(*args, **kwargs):
        sc = deepcopy(original_load(*args, **kwargs))
        sc["world"]["policy"]["days"] = []
        return sc

    monkeypatch.setattr(scenarios, "load_scenario", office_only)
    c = workforce.attrition_comparators(ctx)
    assert c["proportional_days_pct"] == c["no_change_pct"]
    assert c["proportional_days_effect_pp"] == 0


@pytest.mark.data
def test_historical_attrition_is_separate_from_policy_impact():
    d = workforce.results_view(get_instance("trip"))
    a = next(m for m in d["story"]["metrics"] if m["id"] == "attrition")
    assert a["before_actual"] == 9.8
    assert a["reference_actual"] != a["before_actual"]
    assert abs(a["after_actual"] - a["reference_actual"] - (-2.3971)) < 0.001


@pytest.mark.data
def test_workforce_trace_detail_cannot_change_outcomes(monkeypatch):
    ctx = get_instance("trip")
    original = Path.read_text

    def guarded(path, *args, **kwargs):
        assert path.name != "reference_outcomes.json", "World must never read either trial arm's outcomes"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    scenario = load_scenario(ctx, "baseline")
    scenario["world"].update(end="2021-08-20", survey_dates=["2021-08-20"], review_period={"id": "test", "date": "2021-08-20"})
    outcomes = []
    for mode in ("none", "sample", "all"):
        sc = deepcopy(scenario)
        sc["world"]["work_events"] = mode
        w = workforce.World.from_instance(ctx, sc, seed=17)
        w.run(MemoryWriter())
        outcomes.append(w.metrics)
    assert outcomes[0] == outcomes[1] == outcomes[2]


@pytest.mark.data
def test_quit_estimate_sums_hazards_only_while_at_risk():
    ctx = get_instance("trip")
    sc = load_scenario(ctx, "baseline")
    sc["world"]["work_events"] = "none"
    w = workforce.World.from_instance(ctx, sc, seed=17)
    w.dyn["hazards"]["quit"]["weekly"] = "0.1"
    w._writer = MemoryWriter()
    w._weekly(datetime(2021, 8, 13).date(), datetime(2021, 8, 13))
    survived = w.active.copy()
    assert np.allclose(w.expected_quits, 0.1)
    w._weekly(datetime(2021, 8, 20).date(), datetime(2021, 8, 20))
    assert np.allclose(w.expected_quits, 0.1 + 0.1 * survived)


def test_ordinal_review_preserves_pre_policy_grade_distribution():
    prior = np.repeat([1., 2., 3., 4., 5.], [1000, 3000, 10000, 24000, 12000])
    out = workforce.ordinal_review(prior, 0.55, np.zeros(len(prior)), np.random.default_rng(12))
    assert np.max(np.abs(np.bincount(out, minlength=6)[1:] / len(out) - np.bincount(prior.astype(int), minlength=6)[1:] / len(prior))) < 0.008
    assert np.corrcoef(prior, out)[0, 1] > 0.4


@pytest.mark.data
def test_demographic_changes_cannot_change_imputation_or_synthetic_roles():
    import importlib.util
    ctx = get_instance("trip")
    spec = importlib.util.spec_from_file_location("trip_ingest_test", ctx.root / "ingest/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    pop = pd.read_parquet(ctx.data_normalized / "population.parquet")
    a = mod.build_population(pop.copy(), pop, np.random.default_rng(42))
    changed = pop.copy()
    changed["female"] = 1 - changed.female
    b = mod.build_population(changed, pop, np.random.default_rng(42))
    pd.testing.assert_frame_equal(a.drop(columns="female"), b.drop(columns="female"))


def test_process_metrics_score_only_the_declared_population_and_horizon():
    t0 = pd.Timestamp("2018-07-16")
    cases = pd.DataFrame({"case_id": ["live", "already_closed"], "first_ts": [t0, t0]})
    rows = pd.DataFrame({"case_id": ["live", "already_closed", "live"], "activity": ["done"] * 3,
                         "when": [t0 + pd.Timedelta(days=d) for d in [1, 1, 15]], "agent": ["a"] * 3, "resource_class": ["human"] * 3})
    m = process._window_metrics(rows, cases, t0, 14, {"live"}, {"done"}, set(), set())
    assert m["events"] == m["active_cases"] == m["completed"] == 1
    assert m["weekly_events"] == [1, 0]


def test_censored_tail_and_immediate_events_are_preserved():
    raw = {"quantile_grid": [0, 0.5, 0.99], "families": {"f": {"share": 1, "transitions_last": {}, "delays": {}}}, "activities": {}}
    c = process.Calibration(raw)
    c.surv_grid = np.array([0., 24., 48.])
    G = (np.array([0.3, 0.6, 0.9]), "state")
    masses, tail = c.day_masses(G, np.array([0., 24., 48.]), 0)
    assert abs(masses.sum() + tail - 1) < 1e-9
    assert abs(masses[0] - 0.6) < 1e-9
    # A case already older than p99 must not be scheduled backwards in time.
    assert c.sample_delay(np.random.default_rng(1), np.array([0., 24., 48.]), min_h=240) >= 240


def test_joint_censoring_retains_unobserved_mass():
    raw = {"families": {"f": {"share": 1, "transitions_last": {}, "delays": {}}}, "activities": {}, "state_flags": {},
           "survival": {"grid_h": [0, 24, 48], "families": {"f": {"state": {"A|": {"n": 200, "F": {"B": [0, 0.3, 0.6]}}}}}}}
    c = process.Calibration(raw)
    row, source = c.joint_row("f", "A", Counter())
    assert source == "state" and 1 - sum(v[-1] for v in row["F"].values()) == 0.4
    assert np.allclose(c.joint_gap("f", "A", "B", Counter())[0], [0, 0.5, 1])


def test_zero_mass_after_constraints_is_a_valid_no_step():
    from types import SimpleNamespace
    world = SimpleNamespace(
        state_order=2, t0_timing="joint", exception_acts=set(), exception_mult=1,
        calib=SimpleNamespace(next_probs=lambda *a, **kw: ({"B": 1.0}, "state")),
        _joint_curves=lambda item: ({"B": np.array([0., 1.])}, "state", np.array([0., 24.])),
        constraints=SimpleNamespace(allowed=lambda *a: (False, "blocked")),
    )
    item = SimpleNamespace(history=["A"], attributes={"family": "f"}, state={"counts": Counter()})
    options, rejected, _ = process.World._option_weights(world, item)
    assert options == [{"kind": "end", "target": process.END, "weight": 1.0}]
    assert rejected == ["B"]


def test_calendar_changes_hazards_and_preserves_probability_mass():
    from types import SimpleNamespace
    raw = {"families": {"f": {"share": 1, "transitions_last": {}, "delays": {}}}, "activities": {}, "state_flags": {},
           "survival": {"grid_h": [0, 24, 48], "families": {"f": {"state": {"A|": {"n": 200, "F": {"B": [0.1, 0.3, 0.5], "C": [0, 0.1, 0.2]}}}}}}}
    world = process.World.__new__(process.World)
    world.calib = process.Calibration(raw)
    world.state_order = 1
    world.use_calendar = True
    world.calendar_mode = "hazard"
    world._joint_base_cache = {}
    world._joint_current = (None, None)
    item = SimpleNamespace(id="case", history=["A"], attributes={"family": "f"}, state={"counts": Counter(), "last_ts": datetime(2018, 7, 16)})
    curves, _, grid = world._joint_curves(item)
    assert np.allclose(np.interp([0, 24, 48], grid, curves["B"]), [0.1, 0.3, 0.5])
    world.calib.calendar_mult = lambda a, since: np.full(181, 2.) if a == "B" else None
    world._joint_current = (None, None)
    changed, _, _ = world._joint_curves(item)
    assert changed["B"][-1] > curves["B"][-1]
    assert changed["C"][-1] < curves["C"][-1]
    assert sum(v[-1] for v in changed.values()) <= 1
    assert all(np.all(np.diff(v) >= 0) for v in changed.values())


def test_process_staffing_does_not_depend_on_future_user_history(tmp_path):
    from collections import defaultdict
    from types import SimpleNamespace
    cutoff = pd.Timestamp("2018-09-03")
    past = pd.DataFrame({"ts": [cutoff - pd.Timedelta(days=1)], "activity": ["A"], "resource": ["user"], "resource_class": ["human"]})
    future = pd.DataFrame({"ts": [cutoff + pd.Timedelta(days=1)] * 20, "activity": ["B"] * 20,
                           "resource": ["user"] * 20, "resource_class": ["human"] * 20})
    def build(events):
        w = SimpleNamespace(events=events, t0=cutoff, ctx=SimpleNamespace(data_normalized=tmp_path),
                            calib=SimpleNamespace(activities={"A": {"role": "buyer"}, "B": {"role": "payment"}}, raw={}),
                            capacity_mult=defaultdict(lambda: 1.), agents={}, role_unit={})
        process.World._build_workforce(w)
        return w.workforce
    assert build(past) == build(pd.concat([past, future], ignore_index=True))


def test_next_step_score_excludes_already_completed_background_work(tmp_path):
    from types import SimpleNamespace
    from orgsim.kernel import RunSummary
    from orgsim.evaluation import MarkovNextActivity
    t0 = pd.Timestamp("2018-09-03")
    when = t0 + pd.Timedelta(days=1)
    ev = pd.DataFrame({"case_id": ["open", "closed"], "ts": [when, when], "activity": ["B", "D"],
                       "resource": ["u", "v"], "resource_class": ["human", "human"]})
    cases = pd.DataFrame({"case_id": ["open", "closed"], "first_ts": [t0, t0]})
    world = SimpleNamespace(first_decision={"open": {"B": 1.}, "closed": {"wrong": 1.}},
                            items={cid: SimpleNamespace(state={"completed_before": cid == "closed"}, history=[act], attributes={"replayed_prefix": 1}) for cid, act in [("open", "A"), ("closed", "C")]},
                            sim_events=[("open", when, "B", "u", "r", "human", 0.)], seed=1, runtime_s=0.,
                            ctx=SimpleNamespace(runs_dir=tmp_path), scenario={"id": "baseline"})
    (tmp_path / "baseline" / "r").mkdir(parents=True)
    summary = RunSummary("r", "test", "baseline", 1, str(t0), str(when), 24, 1)
    mk = MarkovNextActivity().fit([["A", "B"], ["C", "D"]])
    row, _, _ = process.score_run(ev, cases, world, summary, t0, 14, mk, mk, {"B", "D"}, set(), set(), 1)
    assert row["scored_cases"] == 1 and row["next_acc"] == 1.
