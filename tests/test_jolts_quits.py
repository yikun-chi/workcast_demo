"""Turnover world and JOLTS quits checks. Tests marked `data` need the normalized JOLTS tables and a saved evaluation."""
import json
import shutil

import numpy as np
import pandas as pd
import pytest

from orgsim.worlds import turnover as T


def test_recent_share_sums_the_previous_months_hires():
    m = pd.date_range("2020-01-01", periods=12, freq="MS")
    hires = pd.Series(np.arange(1, 13, dtype=float), index=m)
    s = T.recent_share(hires, pd.DatetimeIndex([pd.Timestamp("2020-08-01")]), 3)
    assert s[0] == pytest.approx((5 + 6 + 7) / 100)


def test_comparators_use_only_the_history_given():
    hist = 2 + np.sin(np.arange(150) / 12 * 2 * np.pi) * 0.3
    c = T.comparator_forecasts(hist, 6)
    assert c["carry_forward"][0] == hist[-1] and c["seasonal_naive"][0] == hist[-12] and c["seasonal_naive"][5] == hist[-7]
    assert set(c) == set(T.COMPARATOR_LABELS)
    assert np.allclose(c["arima"], hist[-12:-6], rtol=0.05)


@pytest.mark.data
def test_prediction_does_not_read_months_after_the_cutoff(monkeypatch):
    from orgsim.instances import get_instance
    from orgsim.scenarios import load_scenario
    from orgsim.store import RunWriter
    ctx = get_instance("jolts_quits")
    proto = ctx.yaml("evaluation/protocol.yaml")
    t0 = pd.Timestamp(proto["cutoffs"][len(proto["cutoffs"]) // 2])
    sc = load_scenario(ctx, "baseline"); sc["world"]["t0"] = str(t0.date())

    def central(data):
        T._CAL_CACHE.clear()
        monkeypatch.setattr(T, "load_data", lambda c: data)
        w = T.World.from_instance(ctx, sc, 1)
        writer = RunWriter(ctx.id, "baseline", run_id=f"test-leak-{len(data.q)}")
        try:
            s = w.run(writer)
        finally:
            shutil.rmtree(writer.dir, ignore_errors=True)
        return np.array([x["central"] for x in s.headline["industries"]])

    full = T.load_data(ctx)
    a, b = central(full), central(T.truncate(full, t0))
    T._CAL_CACHE.clear()
    assert np.allclose(a, b)


@pytest.mark.data
def test_evaluation_scores_every_protocol_cutoff():
    from orgsim.instances import get_instance
    ctx = get_instance("jolts_quits")
    ev = json.loads((ctx.runs_dir / "evaluation.json").read_text())
    proto = ctx.yaml("evaluation/protocol.yaml")
    assert ev["phase"] == "all"
    assert [w["cutoff"] for w in ev["windows"]] == proto["cutoffs"]
    n_ind = len({r["industry"] for r in ev["rows"]})
    assert n_ind == 19
    assert len(ev["rows"]) == n_ind * len(proto["cutoffs"])
    assert all(set(r["predictions"]) == {"simulation", *T.COMPARATOR_LABELS} for r in ev["rows"])


@pytest.mark.data
def test_value_inputs_point_at_the_evaluation():
    from orgsim.instances import get_instance
    from orgsim.evaluation.results import dig
    ctx = get_instance("jolts_quits")
    ev = json.loads((ctx.runs_dir / "evaluation.json").read_text())
    vi = json.loads((ctx.runs_dir / "value_inputs.json").read_text())
    for f in vi["figures"]:
        if f.get("path"):
            assert dig(ev, f["path"]) == pytest.approx(f["value"])
