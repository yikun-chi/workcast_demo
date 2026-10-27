"""Market world checks. Tests marked `data` need the normalized OpenRouter tables and a saved evaluation."""
import json
import shutil

import numpy as np
import pandas as pd
import pytest

from orgsim.worlds import market as M

W = pd.Timedelta(days=7)


def test_damped_path_without_growth_holds_the_level():
    ylog = np.log(np.array([[10.0, 10.0, 10.0, 10.0], [5.0, 6.0, 7.0, 8.0]]))
    p = M.damped_paths(ylog, 4, phi=0.7, w=0.0, mu=np.zeros(2), k_level=1)
    assert np.allclose(np.exp(p[0]), 10.0) and np.allclose(np.exp(p[1]), 8.0)


def test_weighted_median_follows_the_weight():
    assert M.wmedian(np.array([1.0, 2.0, 3.0]), np.array([1.0, 1.0, 10.0])) == 3.0
    assert M.wmedian(np.array([1.0, 2.0, 3.0]), np.array([1.0, 1.0, 1.0])) == 2.0


def test_survival_curves_never_rise():
    rng = np.random.default_rng(0)
    folds = [{"cens": rng.random((30, 8)) < 0.3, "cls": np.array(["burst"] * 10 + ["recurring"] * 10 + ["steady"] * 10)} for _ in range(4)]
    for curve in M.survival_curves(folds, 8).values():
        assert all(b <= a for a, b in zip(curve, curve[1:]))


def test_blended_price_ignores_unpriced_models():
    mix = pd.Series({"a": 0.5, "b": 0.25, "c": 0.25})
    prices = pd.Series({"a": 1.0, "b": 3.0})
    assert M.blended_price(mix, prices) == pytest.approx((0.5 * 1.0 + 0.25 * 3.0) / 0.75)


def _truncate(d: M.MarketData, t0: pd.Timestamp) -> M.MarketData:
    """Usage after t0 removed; price lists and listing dates are exogenous inputs and stay."""
    return M.MarketData(d.mw[d.mw.week < t0], d.cw[d.cw.week < t0], d.aw[d.aw.week < t0], d.apps, d.thr[d.thr.week < t0], d.pw, d.models, d.catalog)


@pytest.mark.data
def test_prediction_does_not_read_usage_after_the_cutoff(monkeypatch):
    from orgsim.instances import get_instance
    from orgsim.scenarios import load_scenario
    from orgsim.store import RunWriter
    ctx = get_instance("openrouter")
    proto = ctx.yaml("evaluation/protocol.yaml")
    t0 = pd.Timestamp(proto["cutoffs"][len(proto["cutoffs"]) // 2])
    sc = load_scenario(ctx, "baseline"); sc["world"]["t0"] = str(t0.date())

    load_orig, dyn_cache = M._load, M._cached_dynamics

    def central(data):
        dyn_cache.cache_clear(); load_orig.cache_clear()
        monkeypatch.setattr(M, "load_data", lambda c: data)
        monkeypatch.setattr(M, "_load", lambda root, mtime: data)
        w = M.World.from_instance(ctx, sc, 1)
        writer = RunWriter(ctx.id, "baseline", run_id=f"test-leak-{len(data.aw)}")
        try:
            s = w.run(writer)
        finally:
            shutil.rmtree(writer.dir, ignore_errors=True)
        return np.array([a["tokens_central"] for a in s.headline["apps"]])

    full = load_orig(str(ctx.data_normalized), (ctx.data_normalized / "app_weekly.parquet").stat().st_mtime)
    a, b = central(full), central(_truncate(full, t0))
    dyn_cache.cache_clear(); load_orig.cache_clear()
    assert np.allclose(a, b)


@pytest.mark.data
def test_alternative_changes_the_outcome():
    from orgsim.instances import get_instance
    from orgsim.evaluation.results import run_docs
    ctx = get_instance("openrouter")
    ev = json.loads((ctx.runs_dir / "evaluation.json").read_text())
    alt_id = ctx.meta["scenarios"]["alternative"]
    alt = {(d["headline"]["t0"], d["seed"]): d["headline"] for d in run_docs(ctx, alt_id, "summary", ev["run_ids"][alt_id])}
    base = {(d["headline"]["t0"], d["seed"]): d["headline"] for d in run_docs(ctx, "baseline", "summary", ev["run_ids"]["baseline"]) if (d["headline"]["t0"], d["seed"]) in alt}
    assert alt and len(base) == len(alt)
    coding = lambda h: sum(sum(a["spend_central"]) for a in h["apps"] if a["segment"] == "programming")  # noqa: E731
    diffs = np.array([coding(alt[k]) / coding(base[k]) - 1 for k in alt])
    # paired by cutoff and seed: the repriced segment's spend moves in every pair, beyond rounding
    assert (np.abs(diffs) > 0.005).all()


@pytest.mark.data
def test_evaluation_scores_every_cutoff_with_matching_comparators():
    from orgsim.instances import get_instance
    ctx = get_instance("openrouter")
    ev = json.loads((ctx.runs_dir / "evaluation.json").read_text())
    proto = ctx.yaml("evaluation/protocol.yaml")
    assert [w["cutoff"] for w in ev["windows"]] == proto["cutoffs"]
    for w in ev["windows"]:
        assert set(w["company_tokens_wape"]) == {"simulation", *M.COMPARATOR_LABELS}
        assert all(np.isfinite(v) for v in w["company_spend_wape"].values())
