"""Demand world and NYC congestion pricing checks. Tests marked `data` need the normalized TLC tables and a saved
evaluation."""
import json
import shutil

import numpy as np
import pandas as pd
import pytest

from orgsim.worlds import demand as D


def test_holiday_calendar_dates():
    h = D.holidays(2025)
    assert h["thanksgiving"] == pd.Timestamp("2025-11-27") and h["black_friday"] == pd.Timestamp("2025-11-28")
    assert h["memorial"] == pd.Timestamp("2025-05-26") and h["labor"] == pd.Timestamp("2025-09-01")
    assert h["easter"] == pd.Timestamp("2025-04-20") and D.holidays(2024)["easter"] == pd.Timestamp("2024-03-31")


def test_customers_keep_buying_without_a_charge_and_less_with_one():
    m = D.gamma_quantiles(200, 4.0)
    assert m.mean() == pytest.approx(1.0)
    k = D.keep_probability(np.array([0.0, 0.75, 1.5]), 20.0, -0.3, m).mean(1)
    assert k[0] == pytest.approx(1.0) and 1.0 > k[1] > k[2]
    # a constant elasticity: the share kept is close to ((P + c) / P) ** e
    assert k[1] == pytest.approx((20.75 / 20.0) ** -0.3, rel=1e-3)


def test_charge_schedule_applies_from_its_start_to_charged_series_only():
    meta = pd.DataFrame({"service": ["yellow", "yellow", "hvfhv"], "charged": [True, False, True]}, index=["y:in", "y:out", "h:in"])
    par = {"charges": [{"from": "2025-01-05", "where": {"service": "yellow", "charged": True}, "amount": 0.75},
                       {"from": "2025-01-05", "where": {"service": "hvfhv", "charged": True}, "amount": 1.5}]}
    days = pd.date_range("2025-01-03", periods=4, freq="D")
    c = D.charge_schedule(par, meta, days, multiplier=2.0)
    assert c.loc["2025-01-04"].sum() == 0
    assert c.loc["2025-01-05", "y:in"] == 1.5 and c.loc["2025-01-05", "y:out"] == 0 and c.loc["2025-01-05", "h:in"] == 3.0


def test_habit_fit_recovers_a_weekday_pattern():
    days = pd.date_range("2023-01-01", periods=730, freq="D")
    X, names = D.calendar_matrix(days, 2)
    true = np.zeros(len(names)); true[names.index("dow_5")] = 0.3
    y = 8.0 + X @ true
    beta, trend, resid = D.fit_habits(y, X, 56, 1.0, 0.001)
    assert beta[names.index("dow_5")] == pytest.approx(0.3, abs=0.01)
    assert np.nanmax(np.abs(resid)) < 0.01


def test_comparators_use_only_the_history_given():
    hist = np.exp(np.sin(np.arange(130) / 52 * 2 * np.pi)) * 1000
    c = D.comparator_forecasts(hist, 26)
    assert c["carry_forward"][0] == pytest.approx(hist[-4:].mean())
    assert c["seasonal_naive"][0] == pytest.approx(hist[-52] * hist[-8:].sum() / hist[-60:-52].sum())
    assert set(c) == set(D.COMPARATOR_LABELS)


@pytest.mark.data
def test_prediction_does_not_read_trips_after_the_cutoff(monkeypatch):
    from orgsim.instances import get_instance
    from orgsim.scenarios import load_scenario
    from orgsim.store import RunWriter
    ctx = get_instance("nyc_congestion")
    proto = ctx.yaml("evaluation/protocol.yaml")
    t0 = pd.Timestamp(proto["change_cutoff"])
    sc = load_scenario(ctx, "baseline"); sc["world"]["t0"] = str(t0.date())

    def central(data):
        D._CAL_CACHE.clear()
        monkeypatch.setattr(D, "load_data", lambda c: data)
        w = D.World.from_instance(ctx, sc, 1)
        writer = RunWriter(ctx.id, "baseline", run_id=f"test-leak-{len(data.y)}")
        try:
            s = w.run(writer)
        finally:
            shutil.rmtree(writer.dir, ignore_errors=True)
        return np.array([x["central"] for x in s.headline["series"]])

    full = D.load_data(ctx)
    a, b = central(full), central(D.truncate(full, t0))
    D._CAL_CACHE.clear()
    assert np.allclose(a, b)


@pytest.mark.data
def test_evaluation_scores_every_protocol_cutoff():
    from orgsim.instances import get_instance
    ctx = get_instance("nyc_congestion")
    ev = json.loads((ctx.runs_dir / "evaluation.json").read_text())
    proto = ctx.yaml("evaluation/protocol.yaml")
    assert ev["phase"] == "all"
    assert [w["cutoff"] for w in ev["windows"]] == proto["cutoffs"]
    for w in ev["windows"]:
        for g in proto["groups"]:
            assert set(w["groups"][g["id"]]["wape"]) == {"simulation", *D.COMPARATOR_LABELS}
            assert w["groups"][g["id"]]["scored_weeks"] > 0
    assert ev["accuracy"]["held_out"]["n_windows"] == len(proto["cutoffs"]) - proto["dev_cutoffs"]


@pytest.mark.data
def test_value_inputs_point_at_the_evaluation():
    from orgsim.instances import get_instance
    from orgsim.evaluation.results import dig
    ctx = get_instance("nyc_congestion")
    ev = json.loads((ctx.runs_dir / "evaluation.json").read_text())
    vi = json.loads((ctx.runs_dir / "value_inputs.json").read_text())
    for f in vi["figures"]:
        if f.get("path"):
            assert dig(ev, f["path"]) == pytest.approx(f["value"])
