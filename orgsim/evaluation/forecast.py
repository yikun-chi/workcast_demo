"""Classical forecasts for aggregate series: the comparators a reviewer expects next to a simulation.

Every forecaster takes a 1-D history `y` (oldest first, finite values) and a horizon `H`, and returns a numpy array of
H point forecasts. `log=True` fits on log1p(y) and returns expm1 of the forecast (the median on the original scale),
for count series. Nothing here reads data after the end of `y`; callers cut the history at the cutoff.

  carry_forward    the last value (or the mean of the last `window` values) held flat
  seasonal_naive   the value one season earlier (period 7 for daily data, 52 for weekly); flat when history < period
  trend            straight-line drift fitted on the last `window` points (least squares), extrapolated
  ets              exponential smoothing with additive errors (Hyndman et al. 2008, ch. 2): trend None / additive /
                   damped additive, seasonality None / additive; smoothing parameters fitted by one-step squared error
                   with heuristic initial states
  auto_ets         chooses among the ets forms by AICc, the usual automatic rule

Reference: Hyndman, Koehler, Ord & Snyder (2008), Forecasting with Exponential Smoothing: The State Space Approach;
Hyndman & Athanasopoulos, Forecasting: Principles and Practice (3rd ed.), sections 5.2 and 8.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from scipy.optimize import minimize


def _prep(y, log: bool) -> np.ndarray:
    a = np.asarray(y, dtype=float).ravel()
    if a.size == 0 or not np.all(np.isfinite(a)):
        raise ValueError("history must be a non-empty, finite 1-D series")
    if log:
        if np.any(a < 0):
            raise ValueError("log=True needs non-negative values")
        a = np.log1p(a)
    return a


def _out(f: np.ndarray, log: bool) -> np.ndarray:
    return np.expm1(f) if log else f


def carry_forward(y, H: int, window: int = 1, log: bool = False) -> np.ndarray:
    a = _prep(y, log)
    return _out(np.full(H, float(np.mean(a[-max(1, window):]))), log)


def seasonal_naive(y, H: int, period: int, log: bool = False) -> np.ndarray:
    a = _prep(y, log)
    if period < 2 or a.size < period:
        return _out(np.full(H, a[-1]), log)
    last = a[-period:]
    return _out(np.array([last[h % period] for h in range(H)]), log)


def trend(y, H: int, window: int | None = None, log: bool = False) -> np.ndarray:
    """Least-squares line through the last `window` points (all points if None), extrapolated H steps."""
    a = _prep(y, log)
    w = a[-window:] if window else a
    if w.size < 2:
        return _out(np.full(H, a[-1]), log)
    x = np.arange(w.size, dtype=float)
    slope, icept = np.polyfit(x, w, 1)
    return _out(icept + slope * (w.size - 1 + np.arange(1, H + 1)), log)


# ------------------------------------------------------------------ exponential smoothing

@dataclass
class ETSFit:
    trend: str | None            # None, "A" or "Ad"
    seasonal: str | None         # None or "A"
    period: int
    alpha: float
    beta: float
    gamma: float
    phi: float
    level: float                 # states at the end of the history
    slope: float
    season: np.ndarray = field(repr=False)   # last `period` seasonal states, oldest first
    sse: float = float("nan")
    n: int = 0
    aicc: float = float("nan")
    log: bool = False

    def forecast(self, H: int) -> np.ndarray:
        h = np.arange(1, H + 1)
        if self.trend == "Ad":
            damp = np.cumsum(self.phi ** h)
        elif self.trend == "A":
            damp = h.astype(float)
        else:
            damp = np.zeros(H)
        f = self.level + damp * self.slope
        if self.seasonal == "A":
            f = f + self.season[(h - 1) % self.period]
        return _out(f, self.log)


def _initial_states(a: np.ndarray, trend: str | None, seasonal: str | None, m: int) -> tuple[float, float, np.ndarray]:
    """Heuristic initial states (Hyndman et al. 2008, sec. 2.6.1, simplified): a straight line through the first
    seasons (up to three) gives the level and slope; the seasonal states are the mean detrended deviation at each
    position of the season, centred to sum to zero. States are set one step before the first observation."""
    if seasonal == "A":
        k = min(a.size // m, 3)
        w = a[:k * m]
    else:
        w = a[:min(a.size, 10)]
    x = np.arange(w.size, dtype=float)
    slope, icept = np.polyfit(x, w, 1) if w.size >= 2 else (0.0, float(w[0]))
    if seasonal == "A":
        dev = (w - (icept + slope * x)).reshape(k, m).mean(axis=0)
        s0 = dev - dev.mean()
    else:
        s0 = np.zeros(max(m, 1))
    if trend:
        return float(icept - slope), float(slope), s0
    return float(w.mean()) if seasonal != "A" else float(icept + slope * (w.size - 1) / 2), 0.0, s0


def _run(a: np.ndarray, alpha: float, beta: float, gamma: float, phi: float, trend: str | None, seasonal: str | None, m: int,
         l0: float, b0: float, s0: np.ndarray) -> tuple[float, float, float, np.ndarray]:
    """One pass of the additive-error recursion. Returns (sse, level, slope, last season)."""
    l, b = l0, b0
    tr = trend is not None
    seas = seasonal == "A"
    ph = phi if trend == "Ad" else 1.0
    s = list(s0) if seas else None
    sse = 0.0
    for t in range(a.size):
        st = s[t % m] if seas else 0.0
        pred = l + ph * b + st
        e = a[t] - pred
        sse += e * e
        l_new = l + ph * b + alpha * e
        if tr:
            b = ph * b + beta * e
        if seas:
            s[t % m] = st + gamma * e
        l = l_new
    if seas:
        k = a.size % m                        # rotate so the returned season starts at the next period position
        season = np.array(s[k:] + s[:k])
    else:
        season = np.zeros(max(m, 1))
    return sse, l, b, season


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-min(max(float(x), -60.0), 60.0)))      # clipped: the optimizer may step far out


def fit_ets(y, trend: str | None = "Ad", seasonal: str | None = None, period: int = 1, log: bool = False,
            max_history: int | None = None, maxiter: int = 60) -> ETSFit:
    """Fit one ETS(A, trend, seasonal) form. Parameters are constrained as in the usual parameter space:
    0 < alpha < 1, 0 < beta < alpha, 0 < gamma < 1 - alpha, 0.8 <= phi <= 0.98."""
    a = _prep(y, log)
    if max_history:
        a = a[-max_history:]
    m = int(period) if seasonal == "A" else 1
    if seasonal == "A" and (m < 2 or a.size < 2 * m + 2):
        seasonal, m = None, 1                  # not enough seasons: fall back to the non-seasonal form
    l0, b0, s0 = _initial_states(a, trend, seasonal, m)

    def unpack(x: np.ndarray) -> tuple[float, float, float, float]:
        alpha = 0.0001 + 0.9998 * _sig(x[0])
        beta = alpha * _sig(x[1]) if trend else 0.0
        gamma = (1 - alpha) * _sig(x[2]) if seasonal == "A" else 0.0
        phi = 0.8 + 0.18 * _sig(x[3]) if trend == "Ad" else 1.0
        return alpha, beta, gamma, phi

    def obj(x: np.ndarray) -> float:
        al, be, ga, ph = unpack(x)
        sse = _run(a, al, be, ga, ph, trend, seasonal, m, l0, b0, s0)[0]
        return sse if math.isfinite(sse) else 1e300

    x0 = np.array([0.0, -2.0, -2.0, 1.0])
    res = minimize(obj, x0, method="L-BFGS-B", options={"maxiter": maxiter})
    al, be, ga, ph = unpack(res.x)
    sse, l, b, season = _run(a, al, be, ga, ph, trend, seasonal, m, l0, b0, s0)
    n = a.size
    k = 1 + (1 if trend else 0) + (1 if seasonal == "A" else 0) + (1 if trend == "Ad" else 0)   # smoothing parameters
    k += 1 + (1 if trend else 0) + ((m - 1) if seasonal == "A" else 0)                           # initial states
    sigma2 = max(sse / n, 1e-12)
    aicc = n * math.log(sigma2) + 2 * k + (2 * k * (k + 1) / (n - k - 1) if n - k - 1 > 0 else float("inf"))
    return ETSFit(trend=trend, seasonal=seasonal, period=m, alpha=al, beta=be, gamma=ga, phi=ph, level=l, slope=b,
                  season=season, sse=sse, n=n, aicc=aicc, log=log)


def ets(y, H: int, period: int = 1, trend: str | None = "Ad", seasonal: str | None = "A", log: bool = False,
        max_history: int | None = None) -> np.ndarray:
    return fit_ets(y, trend, seasonal if period > 1 else None, period, log, max_history).forecast(H)


def auto_ets(y, H: int, period: int = 1, log: bool = False, max_history: int | None = None,
             trends: tuple = (None, "A", "Ad")) -> np.ndarray:
    return select_ets(y, period, log, max_history, trends).forecast(H)


def select_ets(y, period: int = 1, log: bool = False, max_history: int | None = None, trends: tuple = (None, "A", "Ad")) -> ETSFit:
    """The ETS form with the lowest AICc among trend x (no season, additive season)."""
    seasons = (None, "A") if period > 1 else (None,)
    fits = [fit_ets(y, t, s, period, log, max_history) for t in trends for s in seasons]
    return min(fits, key=lambda f: f.aicc)


# ------------------------------------------------------------------ scoring

def mae(pred, actual) -> float:
    p, a = np.asarray(pred, dtype=float), np.asarray(actual, dtype=float)
    return float(np.mean(np.abs(p - a)))


def wape(pred, actual) -> float:
    """Sum of absolute errors over the sum of actuals (weighted absolute percentage error), as a fraction."""
    p, a = np.asarray(pred, dtype=float), np.asarray(actual, dtype=float)
    d = float(np.sum(np.abs(a)))
    return float(np.sum(np.abs(p - a)) / d) if d > 0 else float("nan")


def accuracy_pct(error: float, mean_actual: float) -> float:
    """100 x (1 - error / mean actual), the headline accuracy used in the validation docs."""
    return 100.0 * (1.0 - error / mean_actual) if mean_actual else float("nan")


def error_reduction_pct(sim_error: float, best_comparator_error: float) -> float:
    return 100.0 * (1.0 - sim_error / best_comparator_error) if best_comparator_error else float("nan")


COMPARATORS: dict[str, Callable[..., np.ndarray]] = {
    "carry_forward": carry_forward, "seasonal_naive": seasonal_naive, "trend": trend, "ets": auto_ets,
}
