"""Classical comparators in orgsim.evaluation.forecast: shapes, fallbacks and that ETS recovers simple structure."""
from __future__ import annotations

import numpy as np
import pytest

from orgsim.evaluation.forecast import (accuracy_pct, auto_ets, carry_forward, error_reduction_pct, fit_ets, seasonal_naive,
                                        select_ets, trend, wape)


def test_naive_forecasts_and_fallbacks():
    y = np.arange(1.0, 15.0)
    assert np.allclose(carry_forward(y, 3), 14.0)
    assert np.allclose(carry_forward(y, 2, window=2), 13.5)
    assert np.allclose(seasonal_naive(y, 9, 7), [8, 9, 10, 11, 12, 13, 14, 8, 9])
    assert np.allclose(seasonal_naive(y[:5], 3, 7), 5.0)            # shorter than a season: flat
    assert np.allclose(trend(y, 2, window=5), [15.0, 16.0])
    assert np.allclose(carry_forward([0.0, 9.0], 1, log=True), 9.0)
    with pytest.raises(ValueError):
        carry_forward([1.0, np.nan], 1)


def test_ets_recovers_trend_and_weekly_season():
    rng = np.random.default_rng(0)
    d = np.arange(700)
    truth = lambda t: 1000 + 0.5 * t + 80 * (t % 7 >= 5)  # noqa: E731
    y = truth(d) + rng.normal(0, 10, d.size)
    f = auto_ets(y, 14, 7)
    assert f.shape == (14,)
    assert wape(f, truth(np.arange(700, 714))) < 0.03
    fit = select_ets(y, 7)
    assert fit.seasonal == "A" and fit.trend in ("A", "Ad")


def test_ets_short_history_falls_back_to_non_seasonal():
    y = np.linspace(10, 20, 60)
    fit = fit_ets(y, "Ad", "A", 52)
    assert fit.seasonal is None
    assert np.all(np.isfinite(auto_ets(y, 8, 52)))


def test_scores():
    assert wape([1, 3], [2, 2]) == pytest.approx(0.5)
    assert accuracy_pct(5.0, 50.0) == pytest.approx(90.0)
    assert error_reduction_pct(4.0, 5.0) == pytest.approx(20.0)
