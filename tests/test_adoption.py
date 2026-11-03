"""Adoption world checks. Tests marked `data` need an instance's normalized tables and a saved evaluation."""
import json
import shutil

import numpy as np
import pandas as pd
import pytest

from orgsim.worlds import adoption as A

INSTANCES = ["btos_ai", "so_chatgpt", "aei_tasks"]
_LOAD, _DYN = A._load, A._cached_dynamics          # the cached originals (the leak test patches A._load)


def test_transforms_round_trip():
    a = np.array([0.01, 0.2, 0.5, 0.9])
    for form in ("imitation", "external"):
        assert np.allclose(A.from_z(A.to_z(a, form), form), a)


def test_flat_specification_holds_the_recent_level():
    hist = np.array([[0.10, 0.10, 0.10, 0.10], [0.20, 0.22, 0.18, 0.20]])
    p = A.central_share(hist, None, 5, {"k_level": 4, "drift": 0.0, "w": 1.0, "phi": 1.0, "form": "imitation"}, 0)
    assert np.allclose(p[0], 0.10)
    assert np.all(np.abs(p[1] - 0.20) < 0.01)


def test_imitation_growth_saturates_below_one():
    hist = np.array([[0.2, 0.3, 0.4, 0.5, 0.6]])
    p = A.central_share(hist, None, 60, {"k_level": 1, "drift": 1.0, "w": 1.0, "phi": 1.0, "form": "imitation"}, 0)
    assert np.all(np.diff(p[0]) > 0) and p[0, -1] < 1.0 and p[0, -1] > 0.99


def test_bass_fit_recovers_a_diffusion_curve():
    t = np.arange(40, dtype=float)
    y = 0.6 * A._bass_F(t + 3.0, 0.01, 0.15)
    m, p, q, tau = A.fit_bass(y)
    assert abs(m * A._bass_F(45 + tau, p, q) - 0.6 * A._bass_F(48.0, 0.01, 0.15)) < 0.01


def test_baseline_fit_ignores_periods_after_the_change():
    rng = np.random.default_rng(0)
    per = np.arange(200)
    v = np.exp(10 + 0.001 * per + 0.1 * np.sin(2 * np.pi * per / 52) + rng.normal(0, 0.01, 200))
    w = v.copy(); w[150:] = 1.0                      # whatever happens after the change
    assert np.allclose(A.fit_baseline(v, per, 150, 52, 3, 150), A.fit_baseline(w, per, 150, 52, 3, 150))


def _central(ctx, sc, data, monkeypatch):
    from orgsim.store import RunWriter
    _DYN.cache_clear(); _LOAD.cache_clear()
    monkeypatch.setattr(A, "load_data", lambda c: data)
    monkeypatch.setattr(A, "_load", lambda root, mtime: data)
    w = A.World.from_instance(ctx, sc, 1)
    writer = RunWriter(ctx.id, "baseline", run_id=f"test-leak-{len(data.series)}")
    try:
        s = w.run(writer)
    finally:
        shutil.rmtree(writer.dir, ignore_errors=True)
    return np.array([g["central"] for g in s.headline["groups"]]), s.headline["calibration"]


@pytest.mark.data
@pytest.mark.parametrize("iid", INSTANCES)
def test_prediction_does_not_read_outcomes_after_the_cutoff(iid, monkeypatch):
    from orgsim.instances import get_instance
    from orgsim.scenarios import load_scenario
    ctx = get_instance(iid)
    proto = ctx.yaml("evaluation/protocol.yaml")
    full = A.load_data(ctx)
    cuts = A.cutoff_list(proto, full)
    c = cuts[len(cuts) // 2]
    H = max(int(b["to"]) for b in proto["blocks"])
    sc = load_scenario(ctx, "baseline"); sc["world"].update({"cutoff": c, "horizon_periods": H})
    dates = full.dates()
    # the truncated data keeps the period calendar (dates) so the clock is the same; every outcome from the cutoff on is gone
    trunc = A.truncate(full, c)
    cal = full.series[full.series.period >= c].copy(); cal["value"] = np.nan
    trunc = A.AdoptionData(pd.concat([trunc.series, cal]).sort_values(["group", "period"]).reset_index(drop=True), full.groups)
    a, ca = _central(ctx, sc, full, monkeypatch)
    b, cb = _central(ctx, sc, trunc, monkeypatch)
    _DYN.cache_clear(); _LOAD.cache_clear()
    assert len(dates) and np.allclose(a, b) and ca == cb
    va, vb = A.View(full, ctx.yaml("calibration/adoption.yaml"), A.model_groups(full, {}), c), A.View(A.truncate(full, c), ctx.yaml("calibration/adoption.yaml"), A.model_groups(full, {}), c)
    ka = A.comparators(va, H, list(proto["comparators"]), int(proto.get("recent_periods", 6)), proto.get("season_periods"), proto.get("trend_periods"))
    kb = A.comparators(vb, H, list(proto["comparators"]), int(proto.get("recent_periods", 6)), proto.get("season_periods"), proto.get("trend_periods"))
    assert all(np.allclose(ka[k], kb[k], equal_nan=True) for k in ka)


@pytest.mark.data
@pytest.mark.parametrize("iid", INSTANCES)
def test_every_protocol_cutoff_is_scored(iid):
    from orgsim.instances import get_instance
    ctx = get_instance(iid)
    ev = json.loads((ctx.runs_dir / "evaluation.json").read_text())
    proto = ctx.yaml("evaluation/protocol.yaml")
    cuts = A.cutoff_list(proto, A.load_data(ctx))
    assert [w["cutoff"] for w in ev["windows"]] == cuts
    labels = set(ev["comparator_labels"])
    for w in ev["windows"]:
        assert w["blocks"], f"cutoff {w['cutoff']} has no scored block"
        for blk in w["blocks"].values():
            assert set(blk["mae"]) == {"simulation", *labels}
            assert all(np.isfinite(v) for v in blk["mae"].values())
    dev = A.dev_count(proto, len(cuts))
    assert ev["protocol"]["dev_cutoffs"] == cuts[:dev] and len(cuts) - dev >= 2
