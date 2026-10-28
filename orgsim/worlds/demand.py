"""Demand world: populations of customers, grouped by segment, deciding how much to buy each day from their weekday,
holiday and seasonal habits, a level that drifts, and the price they pay.

A segment (a series) is one group of customers, for example the yellow-taxi riders whose trips end inside a charging
zone during the day. Its customers are agents with a shared calendar habit and individual price sensitivity:

  Habits. Expected purchases on day d are   level x drift(h) x weekday(d) x holiday(d) x season(day of year).
  The habits are fitted at each cutoff t0 from that segment's days before t0 only: a log-linear regression with a
  smooth piecewise trend, day-of-week effects, a named public-holiday calendar and annual harmonics, with robust
  (Huber) weights so that storms and outages do not set the habits.

  Level and drift. Where the segment stands at t0 (its recent days' level) and whether its trend continues are chosen
  per segment by backtests at earlier cutoffs whose targets end before t0, with the one-standard-error rule: the
  simplest choice (the last four weeks' level, no drift) is kept unless a richer one wins by more than one standard
  error. Shock sizes and the width of the range come from the same backtests.

  Price. Each customer i keeps buying at a new per-unit charge c with probability ((P + c) / P) ** (e * m_i), where P is
  the segment's average price before t0, e is the price elasticity measured on an earlier price change (an instance
  calibration file, never the scored period) and m_i spreads sensitivity across customers (Gamma quantiles, mean 1).
  Each week every charged customer decides through the seat policy (rule: a draw from those weights) whether to keep
  buying. The published charge schedule is an exogenous input, as arrivals are in the process world.

The point prediction is the central path (expected decisions, every shock at its median); stochastic runs give the
ranges. After t0 the world reads only the calendar and the charge schedule; demand after t0 is read only by evaluate().
Instance settings live in calibration/demand.yaml; the scored groups and comparators in evaluation/protocol.yaml.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd

from ..evaluation.results import base_document, run_docs
from ..instances import InstanceContext
from ..kernel.world import Agent, BaseWorld, RunSummary
from ..policies.base import Observation
from ..policies.registry import load_registry
from ..store.runs import RunWriter

DAY = pd.Timedelta(days=1)
WEEK = pd.Timedelta(days=7)


# ------------------------------------------------------------------ data

@dataclass
class DemandData:
    y: pd.DataFrame          # date x series_id: units per day (NaN where not recorded)
    price: pd.DataFrame      # date x series_id: average price per unit before the scheduled charge
    meta: pd.DataFrame       # index series_id: label and grouping attributes


@lru_cache(maxsize=2)
def _load(root: str, mtime: float) -> DemandData:
    from pathlib import Path
    n = Path(root)
    s = pd.read_parquet(n / "series_daily.parquet")
    y = s.pivot_table(index="date", columns="series_id", values="value", aggfunc="sum").sort_index()
    y = y.reindex(pd.date_range(y.index.min(), y.index.max(), freq="D"))
    p = n / "price_daily.parquet"
    price = pd.read_parquet(p).pivot_table(index="date", columns="series_id", values="price", aggfunc="mean").reindex(index=y.index, columns=y.columns) if p.exists() \
        else pd.DataFrame(np.nan, index=y.index, columns=y.columns)
    meta = pd.read_parquet(n / "series.parquet").set_index("series_id").reindex(y.columns)
    return DemandData(y, price, meta)


def load_data(ctx: InstanceContext) -> DemandData:
    p = ctx.data_normalized / "series_daily.parquet"
    if not p.exists():
        raise FileNotFoundError(f"{p} missing; run `orgsim ingest {ctx.id}`")
    return _load(str(ctx.data_normalized), p.stat().st_mtime)


def truncate(d: DemandData, t0: pd.Timestamp) -> DemandData:
    """The data as known at t0: demand and prices before t0 only (used by the leak test)."""
    return DemandData(d.y[d.y.index < t0], d.price[d.price.index < t0], d.meta)


# ------------------------------------------------------------------ calendar (published in advance)

def _nth_weekday(y: int, m: int, weekday: int, n: int) -> pd.Timestamp:
    first = pd.Timestamp(y, m, 1)
    return first + pd.Timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(y: int, m: int, weekday: int) -> pd.Timestamp:
    last = pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)
    return last - pd.Timedelta(days=(last.weekday() - weekday) % 7)


def _easter(y: int) -> pd.Timestamp:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = ((h + l_ - 7 * m + 114) % 31) + 1
    return pd.Timestamp(y, month, day)


def holidays(year: int) -> dict[str, pd.Timestamp]:
    """US public holidays and the days around them that change travel and shopping (actual dates, not observed)."""
    thanks = _nth_weekday(year, 11, 3, 4)
    h = {"new_year": pd.Timestamp(year, 1, 1), "jan_2": pd.Timestamp(year, 1, 2), "mlk": _nth_weekday(year, 1, 0, 3), "presidents": _nth_weekday(year, 2, 0, 3),
         "easter": _easter(year), "good_friday": _easter(year) - 2 * DAY, "memorial": _last_weekday(year, 5, 0), "juneteenth": pd.Timestamp(year, 6, 19),
         "july_3": pd.Timestamp(year, 7, 3), "independence": pd.Timestamp(year, 7, 4), "july_5": pd.Timestamp(year, 7, 5), "labor": _nth_weekday(year, 9, 0, 1),
         "columbus": _nth_weekday(year, 10, 0, 2), "halloween": pd.Timestamp(year, 10, 31), "veterans": pd.Timestamp(year, 11, 11),
         "thanksgiving_eve": thanks - DAY, "thanksgiving": thanks, "black_friday": thanks + DAY, "thanksgiving_sat": thanks + 2 * DAY,
         "christmas_eve": pd.Timestamp(year, 12, 24), "christmas": pd.Timestamp(year, 12, 25), "new_years_eve": pd.Timestamp(year, 12, 31)}
    for dd in range(26, 31):
        h[f"dec_{dd}"] = pd.Timestamp(year, 12, dd)
    for dd in range(18, 24):
        h[f"dec_{dd}"] = pd.Timestamp(year, 12, dd)
    return h


HOLIDAY_NAMES = list(holidays(2024))


def calendar_matrix(dates: pd.DatetimeIndex, harmonics: int, weekly: bool = True) -> tuple[np.ndarray, list[str]]:
    """Calendar features for each day: day of week (Monday the reference), one indicator per named holiday, and annual
    harmonics of the day of year. Everything here is known years in advance."""
    cols, names = [], []
    if weekly:
        for k in range(1, 7):
            cols.append((dates.dayofweek == k).astype(float)); names.append(f"dow_{k}")
    hol = {n: set() for n in HOLIDAY_NAMES}
    for y in range(dates.min().year, dates.max().year + 1):
        for n, d in holidays(y).items():
            hol[n].add(d)
    for n in HOLIDAY_NAMES:
        cols.append(np.isin(dates, list(hol[n])).astype(float)); names.append(f"hol_{n}")
    t = (dates.dayofyear.to_numpy() - 1) / 365.25 * 2 * np.pi
    for k in range(1, harmonics + 1):
        cols.append(np.sin(k * t)); names.append(f"sin_{k}")
        cols.append(np.cos(k * t)); names.append(f"cos_{k}")
    return np.column_stack(cols), names


# ------------------------------------------------------------------ price response

def gamma_quantiles(n: int, shape: float) -> np.ndarray:
    """Deterministic spread of price sensitivity across customers: Gamma(shape, 1/shape) quantiles, mean 1."""
    from scipy.stats import gamma
    q = gamma.ppf((np.arange(n) + 0.5) / n, a=shape, scale=1.0 / shape)
    return q / q.mean()


def keep_probability(charge: np.ndarray | float, price: float, elasticity: float, m: np.ndarray) -> np.ndarray:
    """Per customer (columns) and day (rows): probability of still buying when a charge is added to price."""
    c = np.atleast_1d(np.asarray(charge, dtype=float))
    ratio = np.log((price + c) / price) if price and price > 0 else np.zeros_like(c)
    return np.exp(ratio[:, None] * elasticity * m[None, :])


def charge_schedule(par: dict[str, Any], meta: pd.DataFrame, dates: pd.DatetimeIndex, multiplier: float = 1.0) -> pd.DataFrame:
    """The published per-unit charge in effect on each day for each series (calibration/demand.yaml `charges`)."""
    out = pd.DataFrame(0.0, index=dates, columns=meta.index)
    for ch in par.get("charges", []) or []:
        on = dates >= pd.Timestamp(ch["from"])
        if ch.get("until"):
            on &= dates < pd.Timestamp(ch["until"])
        sel = np.ones(len(meta), bool)
        for k, v in (ch.get("where") or {}).items():
            sel &= meta[k].isin(v if isinstance(v, list) else [v]).to_numpy()
        out.loc[on, meta.index[sel]] += float(ch["amount"]) * multiplier
    return out


# ------------------------------------------------------------------ habits (fitted before t0)

@dataclass
class Fit:
    dates: pd.DatetimeIndex
    beta_cal: np.ndarray
    trend: np.ndarray          # fitted trend (log) per training day
    resid: np.ndarray          # log residuals per training day (NaN where missing)
    smear: float               # mean of exp(residual): converts the log prediction to expected units
    fitted: np.ndarray         # trend + calendar (log) per training day
    level_mode: str = "ratio"  # ratio: recent actual / recent fitted, summed; median: median recent log residual + smear


def fit_habits(logy: np.ndarray, X: np.ndarray, knot_days: int, ridge_trend: float, ridge_cal: float, huber_k: float = 1.5, iters: int = 4) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Robust penalised regression of log demand on a piecewise-linear trend (hinges every `knot_days`, penalised) and
    the calendar features (lightly penalised). Returns (calendar coefficients, trend per day, residuals)."""
    n = len(logy)
    t = np.arange(n, dtype=float) / 365.25
    knots = np.arange(knot_days, n - knot_days // 2, knot_days) / 365.25
    H = np.maximum(0.0, t[:, None] - knots[None, :]) if len(knots) else np.zeros((n, 0))
    A = np.column_stack([np.ones(n), t, H, X])
    pen = np.concatenate([[0.0, 0.0], np.full(H.shape[1], ridge_trend), np.full(X.shape[1], ridge_cal)])
    ok = np.isfinite(logy)
    w = ok.astype(float)
    yv = np.where(ok, logy, 0.0)
    coef = np.zeros(A.shape[1])
    for _ in range(iters):
        sw = np.sqrt(w)
        lhs = np.vstack([A * sw[:, None], np.diag(np.sqrt(pen * max(ok.sum(), 1)))])
        rhs = np.concatenate([yv * sw, np.zeros(A.shape[1])])
        coef = np.linalg.lstsq(lhs, rhs, rcond=None)[0]
        r = yv - A @ coef
        s = 1.4826 * np.median(np.abs(r[ok] - np.median(r[ok]))) or 1e-6
        u = np.abs(r) / (huber_k * s)
        w = np.where(ok, np.where(u <= 1, 1.0, 1.0 / np.maximum(u, 1e-9)), 0.0)
    trend = A[:, : 2 + H.shape[1]] @ coef[: 2 + H.shape[1]]
    resid = np.where(ok, logy - A @ coef, np.nan)
    return coef[2 + H.shape[1]:], trend, resid


def fit_series(d: DemandData, sid: str, t0: pd.Timestamp, offset: pd.Series, s: dict[str, Any]) -> Fit | None:
    lo = max(d.y.index.min(), t0 - int(s["history_days"]) * DAY, pd.Timestamp(s.get("history_start") or d.y.index.min()))
    y = d.y.loc[(d.y.index >= lo) & (d.y.index < t0), sid]
    if y.notna().sum() < 180:
        return None
    dates = y.index
    logy = np.log(y.to_numpy(dtype=float) + 1.0) - offset.reindex(dates).fillna(0.0).to_numpy()
    X, _ = calendar_matrix(dates, int(s["harmonics"]))
    beta, trend, resid = fit_habits(logy, X, int(s["knot_days"]), float(s["ridge_trend"]), float(s["ridge_cal"]))
    r = resid[-364:]
    r = r[np.isfinite(r)]
    smear = float(np.mean(np.exp(r - np.median(r)))) if len(r) else 1.0
    return Fit(dates, beta, trend, resid, smear, trend + X @ beta, str(s.get("level_mode") or "ratio"))


SPEC_KEYS = ("level_days", "drift", "phi")


def forecast_log(fit: Fit, days: pd.DatetimeIndex, spec: dict[str, Any], harmonics: int) -> np.ndarray:
    """Log expected demand per future day before price: the level at t0, the damped trend, the calendar."""
    k = int(spec["level_days"])
    r = fit.resid[-k:]
    if fit.level_mode == "ratio":
        # where the segment stands: its actual purchases over the last k days against the habits' fitted purchases
        ok = np.isfinite(r)
        f_ = fit.fitted[-k:][ok]
        adj = math.log(float(np.exp(f_ + r[ok]).sum()) / float(np.exp(f_).sum())) if ok.any() else 0.0
        smear = 0.0
    else:
        adj = float(np.nanmedian(r)) if np.isfinite(r).any() else 0.0
        smear = math.log(fit.smear)
    level = fit.trend[-1] + adj
    slope = (fit.trend[-1] - fit.trend[-92]) / 91 if len(fit.trend) > 92 else 0.0          # per day, last 13 weeks of the trend
    h = np.arange(1, len(days) + 1)
    phi = float(spec["phi"]) ** (1 / 7)
    damp = np.cumsum(phi ** h) if phi < 1 else h.astype(float)
    X, _ = calendar_matrix(days, harmonics)
    return level + float(spec["drift"]) * slope * damp + X @ fit.beta_cal + smear


def weekly(x: np.ndarray, n_weeks: int) -> np.ndarray:
    return x[: n_weeks * 7].reshape(n_weeks, 7).sum(1)


def calibrate(d: DemandData, t0: pd.Timestamp, sid: str, offset: pd.Series, s: dict[str, Any], H: int) -> dict[str, Any]:
    """Fit the segment's habits at t0 and choose its level and drift by backtests whose targets end before t0."""
    grid = [dict(zip(SPEC_KEYS, v)) for v in
            [(k, dr, ph) for k in s["grid"]["level_days"] for dr in s["grid"]["drift"] for ph in (s["grid"]["phi"] if dr > 0 else [1.0])]]
    simple = {"level_days": max(s["grid"]["level_days"]), "drift": 0.0, "phi": 1.0}
    folds = []
    for j in range(int(s["inner_cutoffs"])):
        c = t0 - H * WEEK - j * int(s["inner_step_days"]) * DAY          # inner cutoff; its H-week targets end before t0
        f = fit_series(d, sid, c, offset, s)
        if f is None or len(f.dates) < int(s["min_history_days"]):
            continue
        days = pd.date_range(c, periods=7 * H, freq="D")
        act = d.y.loc[days, sid].to_numpy(dtype=float)
        if days[-1] >= t0 or np.isnan(act).mean() > 0.1:
            continue
        folds.append((f, days, weekly(act, H), offset.reindex(days).fillna(0.0).to_numpy()))     # outage weeks are NaN
    if not folds:
        return {"spec": simple, "selection": "no backtest (short history)", "sigma": [0.05 * math.sqrt(h + 1) for h in range(H)], "inner_cutoffs": 0, "logerr": []}
    pred = {tuple(sp.values()): [weekly(np.exp(forecast_log(f, days, sp, int(s["harmonics"])) + off) - 1.0, H) for f, days, _, off in folds] for sp in grid}
    errs = {k: [float(np.nansum(np.abs(p - fo[2])) / np.nansum(fo[2])) for p, fo in zip(v, folds)] for k, v in pred.items()}
    base = np.array(errs[tuple(simple.values())])
    best_key = min(errs, key=lambda k: np.mean(errs[k]))
    diff = base - np.array(errs[best_key])
    se = float(np.std(diff, ddof=1) / math.sqrt(len(diff))) if len(diff) > 1 else float("inf")
    rich = float(np.mean(diff)) > se and float(np.mean(diff)) > 0
    spec = dict(zip(SPEC_KEYS, best_key)) if rich else simple
    # shock sizes by week ahead from the chosen specification's backtest errors (log actual / predicted, weekly)
    E = np.array([np.log(fo[2] / p) for p, fo in zip(pred[tuple(spec.values())], folds)])
    sig = np.sqrt(np.nanmean((E - np.nanmedian(E, axis=0)) ** 2, axis=0)) if len(E) > 1 else np.full(H, 0.05)
    sig = np.maximum.accumulate(np.maximum(np.nan_to_num(sig, nan=0.05), 0.01))
    return {"spec": spec, "selection": "richer specification" if rich else "simplest specification (one-standard-error rule)",
            "inner_error": round(float(np.mean(errs[tuple(spec.values())])), 4), "inner_error_simplest": round(float(base.mean()), 4),
            "sigma": [round(float(x), 4) for x in sig], "inner_cutoffs": len(base), "logerr": np.where(np.isfinite(E), E, 0.0).tolist()}


_CAL_CACHE: dict[tuple, tuple[DemandData, dict[str, Any]]] = {}


def cached_calibration(d: DemandData, t0: pd.Timestamp, sid: str, offset: pd.Series, s: dict[str, Any], H: int) -> dict[str, Any]:
    """Calibration depends only on data before t0 and the settings, so every seed and scenario at a cutoff shares it
    (keyed on the data object itself, so a truncated copy is calibrated afresh)."""
    key = (id(d), str(t0.date()), sid, float(offset.sum()), json.dumps(s, sort_keys=True), H)
    hit = _CAL_CACHE.get(key)
    if hit is not None and hit[0] is d:
        return hit[1]
    if len(_CAL_CACHE) > 2000:
        _CAL_CACHE.clear()
    cal = calibrate(d, t0, sid, offset, s, H)
    _CAL_CACHE[key] = (d, cal)
    return cal


# ------------------------------------------------------------------ world

class World(BaseWorld):
    @classmethod
    def from_instance(cls, ctx: InstanceContext, scenario: dict[str, Any], seed: int) -> "World":
        w = scenario.get("world", {})
        t0 = pd.Timestamp(w["t0"])
        H = int(w.get("horizon_weeks", 26))
        return cls(ctx, scenario, seed, t0.to_pydatetime(), (t0 + H * WEEK).to_pydatetime())

    def __init__(self, ctx: InstanceContext, scenario: dict[str, Any], seed: int, start: datetime, end: datetime) -> None:
        super().__init__(ctx, scenario, seed, start, end)
        t_start = time.time()
        self.rng = np.random.default_rng(seed)
        cfg = scenario.get("world", {})
        par = self.par = ctx.yaml("calibration/demand.yaml")
        self.t0 = pd.Timestamp(cfg["t0"])
        self.H = int(cfg.get("horizon_weeks", par.get("horizon_weeks", 26)))
        self.registry = load_registry(ctx)
        d = self.d = load_data(ctx)
        self.s = {k: par.get(k) for k in ("history_days", "history_start", "min_history_days", "harmonics", "knot_days", "ridge_trend", "ridge_cal", "inner_cutoffs",
                                          "inner_step_days", "grid", "level_mode")}
        pr_path = ctx.root / par["price_response"] if par.get("price_response") else None      # no file: no price response
        pr = json.loads(pr_path.read_text()) if pr_path and pr_path.exists() else {}
        self.elasticity = float(pr.get("elasticity", 0.0))
        self.elasticity_range = [float(x) for x in pr.get("range", [self.elasticity, self.elasticity])]
        self.m = gamma_quantiles(int(par.get("customers_per_segment", 200)), float(par.get("sensitivity_shape", 4.0)))
        self.interventions = scenario.get("interventions", []) or []
        mult = 1.0
        for iv in self.interventions:
            if iv.get("type") == "charge_multiplier":
                mult *= float(iv.get("multiplier", 1.0))
        self.charge_mult = mult
        self.series = list(d.meta.index)
        days_all = pd.date_range(d.y.index.min(), self.t0 + self.H * WEEK - DAY, freq="D")
        self.charge_hist = charge_schedule(par, d.meta, days_all)                     # as published (the fitting offset)
        self.days = pd.date_range(self.t0, periods=7 * self.H, freq="D")
        self.charge_fwd = charge_schedule(par, d.meta, self.days, self.charge_mult)  # the scenario's schedule after t0
        # each segment's average price before t0 (52 weeks), the base the charge is set against
        win = (d.price.index >= self.t0 - 52 * WEEK) & (d.price.index < self.t0)
        self.P = {sid: float(np.nanmean(d.price.loc[win, sid])) if np.isfinite(d.price.loc[win, sid]).any() else float("nan") for sid in self.series}
        self.cal: dict[str, dict[str, Any]] = {}
        self.base_log: dict[str, np.ndarray] = {}
        for sid in self.series:
            off = self._offset(sid, self.charge_hist[sid], self.elasticity)
            off_hist = off[off.index < self.t0]
            cal = cached_calibration(d, self.t0, sid, off_hist, self.s, self.H)
            f = fit_series(d, sid, self.t0, off_hist, self.s)
            self.cal[sid] = cal
            self.base_log[sid] = forecast_log(f, self.days, cal["spec"], int(self.s["harmonics"])) if f is not None else np.full(len(self.days), np.nan)
            m = d.meta.loc[sid]
            self.agents[f"segment:{sid}"] = Agent(id=f"segment:{sid}", role=str(m.get("flow", "segment")), org_unit=str(m.get("service", "")),
                                                  attributes={"label": str(m.get("label", sid)), "price": self.P[sid], "customers": len(self.m)}, seat="customer")
        self.calibration_s = time.time() - t_start

    def _offset(self, sid: str, charge: pd.Series, elasticity: float) -> pd.Series:
        """Log of the expected share of purchases kept under the charge in effect (zero where no charge)."""
        P = self.P.get(sid, float("nan"))
        if not (P and np.isfinite(P)) or elasticity == 0:
            return pd.Series(0.0, index=charge.index)
        k = keep_probability(charge.to_numpy(), P, elasticity, self.m).mean(1)
        return pd.Series(np.log(k), index=charge.index)

    def run(self, writer: RunWriter) -> RunSummary:
        self._writer = writer
        t_run = time.time()
        H, S = self.H, len(self.series)
        pol = self.registry.for_seat("customer")
        # parameter uncertainty: each stochastic run draws its price sensitivity from the measured range
        e_run = float(self.rng.uniform(*self.elasticity_range)) if self.elasticity_range[1] > self.elasticity_range[0] else self.elasticity
        groups = sorted({str(self.d.meta.loc[s].get("service", "")) for s in self.series})
        # level shocks: a random walk per segment, partly shared within its group (service), sized by the backtests
        rho = float(self.par.get("shared_shock", 0.5))
        z_g = {g: np.cumsum(self.rng.normal(0, 1, H)) for g in groups}
        out_c, out_s, kept_share, charge_w, no_charge = {}, {}, {}, {}, {}
        for sid in self.series:
            sig = np.array(self.cal[sid]["sigma"][:H])
            z_i = np.cumsum(self.rng.normal(0, 1, H))
            g = str(self.d.meta.loc[sid].get("service", ""))
            # a unit random walk scaled to the backtested spread at each week ahead
            walk = (math.sqrt(rho) * z_g[g] + math.sqrt(1 - rho) * z_i) / np.sqrt(np.arange(1, H + 1)) * sig
            base = np.exp(self.base_log[sid]) - 1.0                                       # expected purchases per day before price
            ch = self.charge_fwd[sid].to_numpy()
            P = self.P[sid]
            charged = (ch > 0).any() and P and np.isfinite(P)
            k_c = keep_probability(ch, P, self.elasticity, self.m).mean(1) if charged else np.ones(len(ch))
            out_c[sid] = weekly(base * k_c, H)
            no_charge[sid] = weekly(base, H)
            # stochastic run: each week every customer decides whether to keep buying at the charge it faces
            daily = base * np.repeat(np.exp(walk), 7)
            kshare = np.ones(H)
            if charged:
                for h in range(H):
                    wk = slice(7 * h, 7 * h + 7)
                    p_keep = keep_probability(np.array([ch[wk].mean()]), P, e_run, self.m)[0]
                    if (p_keep >= 1).all():
                        continue
                    keep = np.empty(len(self.m), bool)
                    for i, p in enumerate(p_keep):
                        obs = Observation(agent_id=f"customer:{sid}:{i}", role="customer", sim_time=str((self.t0 + h * WEEK).date()),
                                          context={"segment": sid, "charge": float(ch[wk].mean()), "price": P},
                                          options=[{"kind": "keep", "target": "keep", "weight": float(p)}, {"kind": "stay_away", "target": "stay_away", "weight": float(1 - p)}])
                        keep[i] = pol.decide(obs, self.rng).target == "keep"
                    kshare[h] = keep.mean()
            out_s[sid] = weekly(daily, H) * kshare
            kept_share[sid] = kshare
            charge_w[sid] = [round(float(ch[7 * h: 7 * h + 7].mean()), 3) for h in range(H)]
            for h in range(H):
                self.emit(agent_id=f"segment:{sid}", role=self.agents[f"segment:{sid}"].role, org_unit=self.agents[f"segment:{sid}"].org_unit, activity="weekly_demand",
                          action_type="state", provenance="simulated",
                          attributes={"week": str((self.t0 + h * WEEK).date()), "units": float(out_s[sid][h]), "units_central": float(out_c[sid][h]),
                                      "kept_share": round(float(kshare[h]), 4), "charge": charge_w[sid][h]})
        for _ in range(H * 168):
            if self.clock.done:
                break
            self.clock.advance()
        self.runtime_s = time.time() - t_run
        headline = {
            "t0": str(self.t0.date()), "horizon_weeks": H, "elasticity": self.elasticity, "elasticity_run": e_run, "charge_multiplier": self.charge_mult,
            "weeks": [str((self.t0 + h * WEEK).date()) for h in range(H)],
            "series": [{"series_id": sid, **{k: (v if isinstance(v, (str, bool, int, float)) else str(v)) for k, v in self.d.meta.loc[sid].items()},
                        "price": self.P[sid], "central": [float(v) for v in out_c[sid]], "units": [float(v) for v in out_s[sid]],
                        "central_no_charge": [float(v) for v in no_charge[sid]],
                        "kept_share": [round(float(v), 4) for v in kept_share[sid]], "charge": charge_w[sid],
                        "calibration": {k: v for k, v in self.cal[sid].items() if k != "logerr"}} for sid in self.series],
        }
        return RunSummary(run_id=writer.run_id, instance=self.ctx.id, scenario=self.scenario["id"], seed=self.seed, start=str(self.t0.date()),
                          end=str((self.t0 + H * WEEK).date()), ticks=self.clock.tick, events=self._n_events, headline=headline)


# ------------------------------------------------------------------ evaluation

COMPARATOR_LABELS = {
    "carry_forward": "No change: the last four weeks' average carried forward",
    "seasonal_naive": "Same week last year: scaled by the last eight weeks against the same weeks a year earlier",
    "trend": "Recent trend: the last four weeks' average grown at the 52-week log-linear trend",
    "ets": "Exponential smoothing (ETS): damped trend and 52-week seasonality on log weekly volumes",
}
HORIZON_BUCKETS = {"1-4": (1, 4), "5-13": (5, 13), "14-26": (14, 26)}


def group_ids(meta: pd.DataFrame, where: dict[str, Any]) -> list[str]:
    sel = np.ones(len(meta), bool)
    for k, v in (where or {}).items():
        sel &= meta[k].isin(v if isinstance(v, list) else [v]).to_numpy()
    return list(meta.index[sel])


def weekly_history(d: DemandData, sids: list[str], t0: pd.Timestamp) -> np.ndarray:
    """Weekly totals (weeks aligned on t0's weekday) over every complete week before t0, oldest first. A day missing
    from the records (a recording outage) takes the same weekday's value a week earlier."""
    y = d.y.loc[d.y.index < t0, sids].sum(axis=1, min_count=len(sids))
    y = y.groupby(y.index.dayofweek).ffill()
    n = (len(y) // 7) * 7
    w = y.iloc[len(y) - n:].to_numpy(dtype=float).reshape(-1, 7)
    return w[~np.isnan(w).any(axis=1)].sum(1)


def comparator_forecasts(hist: np.ndarray, H: int) -> dict[str, np.ndarray]:
    """The classical forecasts of a weekly series, from its weeks before the cutoff only (fixed before scoring)."""
    import warnings
    out = {}
    last4 = float(hist[-4:].mean())
    out["carry_forward"] = np.full(H, last4)
    if len(hist) >= 60:
        scale = hist[-8:].sum() / hist[-60:-52].sum()
        out["seasonal_naive"] = np.array([hist[len(hist) - 52 + h] for h in range(H)]) * scale
    else:
        out["seasonal_naive"] = np.full(H, np.nan)
    k = min(52, len(hist))
    slope = float(np.polyfit(np.arange(k), np.log(hist[-k:]), 1)[0])
    out["trend"] = last4 * np.exp(slope * (np.arange(H) + 2.5))
    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m = ExponentialSmoothing(np.log(hist), trend="add", damped_trend=True, seasonal="add", seasonal_periods=52,
                                     initialization_method="estimated").fit(optimized=True)
            out["ets"] = np.exp(m.forecast(H))
    except Exception:  # noqa: BLE001 -- recorded as missing, never replaced
        out["ets"] = np.full(H, np.nan)
    return out


def _run_world(ctx: InstanceContext, scenario: dict[str, Any], seed: int, t0: str) -> RunSummary:
    sc = json.loads(json.dumps(scenario))
    sc.setdefault("world", {})["t0"] = t0
    writer = RunWriter(ctx.id, sc["id"], config={"instance": ctx.id, "scenario": sc, "seed": seed, "evaluation": True})
    world = World.from_instance(ctx, sc, seed)
    summary = world.run(writer)
    writer.close(summary.to_json())
    print(f"[{ctx.id}] eval run {sc['id']} t0={t0} seed={seed} -> {writer.run_id} (calibration {world.calibration_s:.1f}s, run {world.runtime_s:.1f}s)", flush=True)
    return summary


def pooled(rows: list[dict[str, Any]], who: str, weeks: tuple[int, int] | None = None) -> dict[str, float] | None:
    """Pooled error over windows, groups and weeks: WAPE (% of actual), MAE (units per week) and accuracy. Weeks with a
    recording outage in the actual are left out for every prediction alike."""
    ae = act = n = 0.0
    for r in rows:
        p = np.array(r["predictions"][who], dtype=float)
        a = np.array(r["actual"], dtype=float)
        sl = slice(weeks[0] - 1, weeks[1]) if weeks else slice(None)
        p, a = p[sl], a[sl]
        ok = ~np.isnan(a)
        p, a = p[ok], a[ok]
        if np.isnan(p).any():
            return None
        ae += float(np.abs(p - a).sum()); act += float(a.sum()); n += len(a)
    if not n:
        return None
    return {"wape": 100 * ae / act, "mae": ae / n, "mean_actual": act / n, "accuracy": 100 * (1 - ae / act), "n_weeks": int(n)}


def summarize(rows: list[dict[str, Any]], who_all: list[str]) -> dict[str, Any]:
    comps = [k for k in who_all if k != "simulation"]
    allw = {k: pooled(rows, k) for k in who_all}
    ok = [k for k in comps if allw[k] is not None]
    best = min(ok, key=lambda k: allw[k]["wape"]) if ok else None
    out: dict[str, Any] = {"all_weeks": {**allw, "best_baseline": best,
                                         "error_reduction_pct": (1 - allw["simulation"]["wape"] / allw[best]["wape"]) * 100 if best and allw["simulation"] else None}}
    out["by_horizon"] = {}
    for b, rng_ in HORIZON_BUCKETS.items():
        v = {k: pooled(rows, k, rng_) for k in who_all}
        okb = [k for k in comps if v[k] is not None]
        bb = min(okb, key=lambda k: v[k]["wape"]) if okb else None
        out["by_horizon"][b] = {**v, "best_baseline": bb, "error_reduction_pct": (1 - v["simulation"]["wape"] / v[bb]["wape"]) * 100 if bb else None}
    cov = [c for r in rows for c in r.get("covered90", [])]
    out["coverage90"] = 100 * float(np.mean(cov)) if cov else None
    out["n_predictions"] = int(sum(len(r["actual"]) for r in rows))
    out["n_windows"] = len({r["cutoff"] for r in rows})
    out["span"] = [min(r["cutoff"] for r in rows), max(r["cutoff"] for r in rows)] if rows else None
    return out


def evaluate(ctx: InstanceContext, scenario_ids: list[str], phase: str = "all") -> dict[str, Any]:
    """Score the simulation and the classical forecasts at every protocol cutoff. phase="dev" scores only the
    development cutoffs (used before the design is frozen); "all" scores every cutoff."""
    from ..scenarios import load_scenario
    proto = ctx.yaml("evaluation/protocol.yaml")
    d = load_data(ctx)
    H = int(proto.get("horizon_weeks", 26))
    seeds = [int(s) for s in proto.get("seeds", [1, 2, 3])]
    all_cutoffs = [pd.Timestamp(c) for c in proto["cutoffs"]]
    n_dev = int(proto["dev_cutoffs"])
    cutoffs = all_cutoffs[:n_dev] if phase == "dev" else all_cutoffs
    base_id = proto.get("baseline_scenario", "baseline")
    alt_id = ctx.meta.get("scenarios", {}).get("alternative")
    base = load_scenario(ctx, base_id)
    groups = proto["groups"]
    who_all = ["simulation", *COMPARATOR_LABELS]
    windows, run_ids, rows = [], {base_id: []}, []
    for c in cutoffs:
        sims = [_run_world(ctx, base, sd, str(c.date())) for sd in seeds]
        run_ids[base_id] += [s.run_id for s in sims]
        h0 = sims[0].headline
        by_sid = [{x["series_id"]: x for x in s.headline["series"]} for s in sims]
        win = {"cutoff": str(c.date()), "phase": "dev" if c in all_cutoffs[:n_dev] else "held_out", "weeks": h0["weeks"], "groups": {}, "run_ids": [s.run_id for s in sims]}
        days = pd.date_range(c, periods=7 * H, freq="D")
        for g in groups:
            sids = group_ids(d.meta, g.get("where"))
            act = d.y.loc[days, sids].sum(axis=1, min_count=len(sids)).to_numpy(dtype=float).reshape(H, 7).sum(1)
            central = np.sum([by_sid[0][s]["central"] for s in sids], axis=0)
            runs = np.array([np.sum([b[s]["units"] for s in sids], axis=0) for b in by_sid])
            lo, hi = np.percentile(runs, 5, axis=0), np.percentile(runs, 95, axis=0)
            hist = weekly_history(d, sids, c)
            comp = comparator_forecasts(hist, H)
            before = hist[-H:]
            ok = ~np.isnan(act)                                     # weeks with a recording outage are not scored
            nan_none = lambda a: [None if not np.isfinite(x) else float(x) for x in a]  # noqa: E731
            preds = {"simulation": central, **comp}
            row = {"cutoff": win["cutoff"], "phase": win["phase"], "group": g["id"], "headline": bool(g.get("headline")), "actual": nan_none(act),
                   "before": before.tolist(), "predictions": {k: nan_none(v) for k, v in preds.items()},
                   "interval": [lo.tolist(), hi.tolist()], "covered90": [bool(x) for x in ((act >= lo) & (act <= hi))[ok]]}
            rows.append(row)
            win["groups"][g["id"]] = {"scored_weeks": int(ok.sum()),
                                      "wape": {k: (100 * float(np.abs(v[ok] - act[ok]).sum() / act[ok].sum()) if not np.isnan(v).any() else None) for k, v in preds.items()},
                                      "total": {"actual": float(act[ok].sum()), "before": float(before.sum()), **{k: float(np.sum(v[ok])) for k, v in preds.items()},
                                                "interval": [float(np.percentile(runs[:, ok].sum(1), 5)), float(np.percentile(runs[:, ok].sum(1), 95))]},
                                      # the simulated effect of the charge: the central path against the same riders without it
                                      "charge_effect_pct": 100 * (float(central.sum()) / float(np.sum([by_sid[0][s]["central_no_charge"] for s in sids])) - 1),
                                      "price_per_unit": float(np.average([by_sid[0][s]["price"] for s in sids], weights=[sum(by_sid[0][s]["central"]) for s in sids]))}
        windows.append(win)
    # alternative: same seeds at the protocol's alternative cutoffs
    if alt_id and alt_id in scenario_ids:
        alt = load_scenario(ctx, alt_id)
        run_ids[alt_id] = []
        for c in [pd.Timestamp(x) for x in proto.get("alternative_cutoffs", [])]:
            if c in cutoffs:
                for sd in seeds:
                    run_ids[alt_id].append(_run_world(ctx, alt, sd, str(c.date())).run_id)
    head_rows = [r for r in rows if r["headline"]]
    held = [r for r in head_rows if r["phase"] == "held_out"]
    accuracy: dict[str, Any] = {"held_out": summarize(held, who_all) if held else None, "dev": summarize([r for r in head_rows if r["phase"] == "dev"], who_all),
                                "all_cutoffs": summarize(head_rows, who_all)}
    ch = proto.get("change_cutoff")
    if ch and any(r["cutoff"] == ch for r in head_rows):
        accuracy["change_window"] = summarize([r for r in head_rows if r["cutoff"] == ch], who_all)
    accuracy["by_group"] = {}
    for g in groups:
        gr = [r for r in rows if r["group"] == g["id"]]
        accuracy["by_group"][g["id"]] = {"held_out": summarize([r for r in gr if r["phase"] == "held_out"], who_all) if any(r["phase"] == "held_out" for r in gr) else None,
                                         "all_cutoffs": summarize(gr, who_all)}

    def bv(gid: str) -> dict[str, Any]:
        ws = [{"cutoff": w["cutoff"], "phase": w["phase"], "actual": w["groups"][gid]["total"]["actual"], "simulated": w["groups"][gid]["total"]["simulation"],
               "interval": w["groups"][gid]["total"]["interval"], "baselines": {k: w["groups"][gid]["total"][k] for k in COMPARATOR_LABELS}} for w in windows]
        sc = [x for x in ws if x["phase"] == "held_out"] or ws
        sim_mae = float(np.mean([abs(x["simulated"] - x["actual"]) for x in sc]))
        bm = {k: float(np.mean([abs(x["baselines"][k] - x["actual"]) for x in sc])) for k in COMPARATOR_LABELS if all(np.isfinite(x["baselines"][k]) for x in sc)}
        best = min(bm, key=bm.get)
        return {"id": gid, "label": next(g["label"] for g in groups if g["id"] == gid), "scope": sc[0]["phase"], "windows": ws, "simulation_mae": sim_mae,
                "baseline_mae": bm, "best_baseline": best, "beats_best_baseline": sim_mae < bm[best],
                "error_reduction_pct": (1 - sim_mae / bm[best]) * 100 if bm[best] > 0 else None, "mean_actual": float(np.mean([x["actual"] for x in sc]))}
    scope = "held_out" if accuracy["held_out"] else "dev"
    A = accuracy[scope]["all_weeks"]
    best = A["best_baseline"]
    out = {"instance": ctx.id, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "scenarios": scenario_ids, "phase": phase,
           "protocol": {"cutoffs": [str(c.date()) for c in cutoffs], "dev_cutoffs": proto["cutoffs"][:n_dev], "horizon_weeks": H, "seeds": seeds,
                        "runs": len(cutoffs) * len(seeds), "change_cutoff": ch, "groups": groups, "headline_scope": scope, "unit_label": proto.get("unit_label", "units"),
                        "point": "central path (expected decisions, every shock at its median)", "interval": "5th-95th percentile across runs"},
           "run_ids": run_ids, "windows": windows, "rows": rows, "accuracy": accuracy, "comparator_labels": COMPARATOR_LABELS,
           "business_validation": [bv(g["id"]) for g in groups if g.get("headline")]}
    # operating quantities the value case needs, per headline group: weekly volume, price per unit, simulated charge effect
    chw = next((w for w in windows if w["cutoff"] == ch), None)
    out["operations"] = {g["id"]: {"label": g["label"],
                                   "mean_weekly_actual": float(np.mean([w["groups"][g["id"]]["total"]["actual"] / w["groups"][g["id"]]["scored_weeks"] for w in windows if w["phase"] == scope])),
                                   **({"price_per_unit_at_change": chw["groups"][g["id"]]["price_per_unit"], "charge_effect_pct_at_change": chw["groups"][g["id"]]["charge_effect_pct"],
                                       "actual_26w_at_change": chw["groups"][g["id"]]["total"]["actual"], "before_26w_at_change": chw["groups"][g["id"]]["total"]["before"]} if chw else {})}
                         for g in groups if g.get("headline")}
    pr_file = ctx.root / (ctx.yaml("calibration/demand.yaml").get("price_response") or "")
    if pr_file.is_file():
        pr = json.loads(pr_file.read_text())
        out["operations"]["price_response"] = {"elasticity": pr["elasticity"], "range": pr["range"]}
    out["headline"] = {
        "weekly_wape": {"label": f"Error in weekly {proto.get('unit_label', 'units')} ({scope.replace('_', '-')} cutoffs, % of actual)", "simulated": A["simulation"]["wape"],
                        "baseline": A[best]["wape"] if best else None, "best_baseline": best, "unit": "%", "better": "lower"},
        "accuracy": {"label": "Accuracy, 100 x (1 - error / mean actual)", "simulated": A["simulation"]["accuracy"], "baseline": A[best]["accuracy"] if best else None,
                     "unit": "%", "better": "higher"},
        "coverage90": {"label": "Weeks whose actual fell inside the simulation's 90% range", "simulated": accuracy[scope]["coverage90"], "unit": "%", "better": "higher"},
    }
    ctx.runs_dir.mkdir(parents=True, exist_ok=True)
    (ctx.runs_dir / "evaluation.json").write_text(json.dumps(out, indent=1, default=_json_default))
    return out


def _json_default(o: Any) -> Any:
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return None if math.isnan(float(o)) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return str(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


# ------------------------------------------------------------------ results view

def _short(label: str) -> str:
    return label.split(":")[0]


def results_view(ctx: InstanceContext) -> dict[str, Any]:
    """Actual outcomes, the simulation and the classical forecasts over every cutoff, then the alternative at matching
    cutoffs and seeds. Uses only the current evaluation's run IDs."""
    doc = base_document(ctx)
    ev_path = ctx.runs_dir / "evaluation.json"
    ev = json.loads(ev_path.read_text()) if ev_path.exists() else {}
    base = doc["scenarios"]["baseline"]; alt = doc["scenarios"].get("alternative")
    proto = ev.get("protocol") or {}
    wins, rows, acc = ev.get("windows") or [], ev.get("rows") or [], ev.get("accuracy") or {}
    labels = ev.get("comparator_labels") or COMPARATOR_LABELS
    H = int(proto.get("horizon_weeks", 26))
    unit = proto.get("unit_label", "units")
    run_ids = ev.get("run_ids", {})
    scope = proto.get("headline_scope", "held_out")
    sources = [{"id": "actual", "label": "Actual outcome", "kind": "actual", "scenario": base["id"], "note": f"The {unit} recorded in each of the {H} weeks after each cutoff."},
               {"id": "baseline", "label": "Simulation prediction", "kind": "simulated", "scenario": base["id"], "runs": proto.get("runs"),
                "note": f"The central path of the simulation at each of {len(proto.get('cutoffs', []))} cutoffs; ranges are the 5th-95th percentile across {len(proto.get('seeds', []))} runs per cutoff. Each run reads only days before its cutoff, plus the published charge schedule and the holiday calendar."}]
    alt_docs = run_docs(ctx, alt["id"], "summary", run_ids.get(alt["id"], [])) if alt else []
    if alt:
        sources.append({"id": "alternative", "label": f"{alt['short_title']} · simulation prediction", "kind": "simulated", "scenario": alt["id"], "runs": len(alt_docs),
                        "note": f"{len(alt_docs)} runs at the same cutoff and seeds as the simulation of what happened."})
    for s_ in sources:
        s_["kind_label"] = {"actual": "Actual outcome (actual data)", "baseline": "Simulation prediction", "alternative": "Alternative simulation prediction"}[s_["id"]]
        s_["short"] = {"actual": "Actual outcome", "baseline": "Simulation prediction", "alternative": alt["short_title"] if alt else ""}[s_["id"]]
    if not wins:
        doc.update({"sources": sources, "metrics": [], "effects": [], "charts": [], "hero": {"kicker": "No evaluation yet", "stats": [], "claim": ""}})
        return doc
    comps = list(labels)
    groups = proto.get("groups", [])
    head_groups = [g for g in groups if g.get("headline")]
    scored = [w for w in wins if w["phase"] == scope] or wins
    mean = lambda xs: float(np.mean([x for x in xs if x is not None])) if any(x is not None for x in xs) else None  # noqa: E731
    wk = lambda w, gid, who: w["groups"][gid]["total"][who] / max(w["groups"][gid].get("scored_weeks", H), 1)          # noqa: E731
    story_metrics, baselines = [], []
    for g in head_groups:
        story_metrics.append({"id": g["id"], "label": f"{g['label']}, average week", "unit": "", "better": "higher",
                              "before_actual": mean([w["groups"][g["id"]]["total"]["before"] / H for w in scored]),
                              "after_actual": mean([wk(w, g["id"], "actual") for w in scored]), "after_sim": mean([wk(w, g["id"], "simulation") for w in scored]),
                              "intervals": {"after_sim": [mean([w["groups"][g["id"]]["total"]["interval"][0] / max(w["groups"][g["id"]].get("scored_weeks", H), 1) for w in scored]),
                                                          mean([w["groups"][g["id"]]["total"]["interval"][1] / max(w["groups"][g["id"]].get("scored_weeks", H), 1) for w in scored])]}})
    baselines = [{"id": k, "label": _short(labels[k]), "values": {g["id"]: mean([wk(w, g["id"], k) for w in scored]) for g in head_groups}} for k in comps]
    A = (acc.get(scope) or acc.get("all_cutoffs"))["all_weeks"]
    best = A["best_baseline"]
    ch_cut = proto.get("change_cutoff")
    CW = acc.get("change_window")
    first, last = scored[0]["cutoff"], scored[-1]["cutoff"]
    doc["design"] = (f"At each of {len(scored)} cutoffs from {first} to {last}, the simulation carried every rider group forward {H} weeks from its weekday, holiday and seasonal habits, "
                     f"its level and drift, and its response to the per-trip charge. Every habit is fitted from days before the cutoff; after the cutoff the simulation sees only the published "
                     f"charge schedule and the holiday calendar. Each week is scored against the {unit} recorded, next to four standard forecasts made from the same weeks.")
    bvs = ev.get("business_validation", [])
    story = {"before": {"label": f"The {H} weeks before each cutoff", "sublabel": f"Actual outcome, averaged over {len(scored)} cutoffs"},
             "change": {"label": "The congestion charge: $0.75 per taxi trip, $1.50 per Uber or Lyft trip, from 5 January 2025",
                        "description": "The charge schedule and the holiday calendar are supplied as published; the trips after each cutoff are hidden from the simulation.",
                        "stats": [{"label": "Cutoffs scored", "value": len(scored)}, {"label": "Weekly predictions scored", "value": (acc.get(scope) or {}).get("n_predictions")}]},
             "after": {"label": f"The {H} weeks after each cutoff", "sublabel": f"{len(scored) * len(proto.get('seeds', []))} runs"},
             "columns": {"before_actual": "Actual outcome", "after_actual": "Actual outcome", "after_sim": "Simulation prediction"},
             "metrics": story_metrics, "chart": "change_window", "baselines": baselines, "baseline_basis": "after",
             "business_validation": [{**b, "id": b["id"], "simulation_mae": b["simulation_mae"] / H, "baseline_mae": {k: v / H for k, v in b["baseline_mae"].items()}} for b in bvs],
             "fidelity": [{"label": f"Error in weekly {unit}, simulation", "value": A["simulation"]["wape"], "unit": "%"},
                          {"label": f"Best other prediction ({_short(labels[best])})", "value": A[best]["wape"], "unit": "%"},
                          {"label": "Accuracy, simulation", "value": A["simulation"]["accuracy"], "unit": "%"},
                          {"label": "Weeks inside the simulation's 90% range", "value": (acc.get(scope) or {}).get("coverage90"), "unit": "%"}]}
    doc["story"] = story
    metrics = []
    for gid, gacc in (acc.get("by_group") or {}).items():
        a_ = (gacc.get(scope) or gacc.get("all_cutoffs") or {}).get("all_weeks") or {}
        if not a_.get("simulation"):
            continue
        label = next((g["label"] for g in groups if g["id"] == gid), gid)
        metrics.append({"id": f"wape_{gid}", "label": f"Error in weekly {unit}: {label} (%)", "unit": "%", "better": "lower",
                        "values": {"actual": None, "baseline": a_["simulation"]["wape"], "alternative": None}, "intervals": {},
                        "note": " · ".join(f"{_short(labels[k])}: {a_[k]['wape']:.1f}%" for k in comps if a_.get(k))})
    for b, v in ((acc.get(scope) or {}).get("by_horizon") or {}).items():
        metrics.append({"id": f"wape_weeks_{b}", "label": f"Error in weekly {unit}, weeks {b} after the cutoff (%)", "unit": "%", "better": "lower",
                        "values": {"actual": None, "baseline": v["simulation"]["wape"], "alternative": None}, "intervals": {},
                        "note": " · ".join(f"{_short(labels[k])}: {v[k]['wape']:.1f}%" for k in comps if v.get(k))})
    charts = []
    if ch_cut:
        cr = [r for r in rows if r["cutoff"] == ch_cut and r["headline"]]
        if cr:
            x = next(w["weeks"] for w in wins if w["cutoff"] == ch_cut)
            sumv = lambda key, who=None: [float(np.nansum([((r[key][who] if who else r[key])[i] or np.nan) for r in cr])) for i in range(H)]  # noqa: E731
            lo = [float(sum(r["interval"][0][i] for r in cr)) for i in range(H)]
            hi = [float(sum(r["interval"][1][i] for r in cr)) for i in range(H)]
            bcw = (CW or {}).get("all_weeks", {}).get("best_baseline") or best
            charts.append({"id": "change_window", "type": "line", "title": f"Trips ending in the zone after the charge started, by week ({ch_cut} cutoff, both services)",
                           "x": x, "x_label": "", "y_label": unit,
                           "series": [{"name": "Actual outcome", "y": sumv("actual"), "source": "actual"},
                                      {"name": "Simulation prediction", "y": sumv("predictions", "simulation"), "band": [lo, hi], "source": "baseline"},
                                      {"name": f"Other prediction ({_short(labels[bcw])})", "y": sumv("predictions", bcw), "source": "actual", "dashed": True}],
                           "note": "Every prediction made from trip records before 5 January 2025; the band is the simulation's 5th-95th percentile."})
    cx = [w["cutoff"] for w in wins]
    pw = lambda w, who: mean([w["groups"][g["id"]]["wape"].get(who) for g in head_groups])  # noqa: E731
    charts.append({"id": "error_by_cutoff", "type": "line", "title": f"Error in weekly {unit} ending in the zone, by cutoff (%)", "x": cx, "x_label": "", "y_label": "%",
                   "series": [{"name": "Simulation prediction", "y": [pw(w, "simulation") for w in wins], "source": "baseline"},
                              {"name": f"Best other prediction ({_short(labels[best])})", "y": [pw(w, best) for w in wins], "source": "actual", "dashed": True}],
                   "note": "Lower is better. Average over the two services of each cutoff's 26-week error."})
    bh = (acc.get(scope) or {}).get("by_horizon") or {}
    if bh:
        charts.append({"id": "error_by_horizon", "type": "bar", "title": f"Error in weekly {unit}, by weeks after the cutoff (%)", "x": [f"weeks {b}" for b in bh], "x_label": "", "y_label": "%",
                       "series": [{"name": "Simulation prediction", "y": [bh[b]["simulation"]["wape"] for b in bh], "source": "baseline"},
                                  *[{"name": _short(labels[k]), "y": [bh[b][k]["wape"] if bh[b].get(k) else None for b in bh], "source": "actual"} for k in comps]],
                       "note": "Lower is better."})
    hero = {"kicker": f"Backtested: {(acc.get(scope) or {}).get('n_predictions')} weekly predictions over {len(scored)} cutoffs",
            "stats": [{"label": f"Less error than the best standard forecast ({_short(labels[best])}) on weekly {unit} ending in the zone", "value": A.get("error_reduction_pct"), "unit": "%"},
                      {"label": "Accuracy of the simulation, 100 x (1 - error / actual)", "value": A["simulation"]["accuracy"], "unit": "%"},
                      {"label": f"Accuracy of the best standard forecast", "value": A[best]["accuracy"], "unit": "%"},
                      *([{"label": "Less error in the 26 weeks after the charge started", "value": CW["all_weeks"].get("error_reduction_pct"), "unit": "%"}] if CW else []),
                      {"label": "Weeks inside the 90% range", "value": (acc.get(scope) or {}).get("coverage90"), "unit": "%"}],
            "claim": "Every prediction uses only trip records from before its cutoff; the charge schedule and holiday calendar are supplied as published.",
            "chart": "change_window"}
    if alt and alt_docs:
        keys = {(d_["headline"]["t0"], d_["seed"]) for d_ in alt_docs}
        base_docs = [d_ for d_ in run_docs(ctx, base["id"], "summary", run_ids.get(base["id"], [])) if (d_["headline"]["t0"], d_["seed"]) in keys]

        def agg(docs_, fn):
            vals = [fn(d_["headline"]) for d_ in docs_]
            return (float(np.mean(vals)), [float(np.percentile(vals, 5)), float(np.percentile(vals, 95))]) if vals else (None, None)

        def zone(h, service, key="central"):
            return sum(sum(s["central" if key == "central" else "units"]) for s in h["series"] if s.get("service") == service and s.get("flow") in ("within", "into"))

        def revenue(h):
            return sum(float(np.dot(s["central"], s["charge"])) for s in h["series"])
        rows_alt = [("yellow_zone_trips", f"Yellow taxi trips ending in the zone, {H} weeks", lambda h: zone(h, "yellow")),
                    ("hvfhv_zone_trips", f"Uber and Lyft trips ending in the zone, {H} weeks", lambda h: zone(h, "hvfhv")),
                    ("charge_revenue", f"Per-trip charges paid by riders, {H} weeks ($)", revenue)]
        for mid, label, fn in rows_alt:
            bm, bi = agg(base_docs, fn); am, ai = agg(alt_docs, fn)
            metrics.append({"id": mid, "label": label, "unit": "", "better": "", "values": {"actual": None, "baseline": bm, "alternative": am},
                            "intervals": {k: v for k, v in (("baseline", bi), ("alternative", ai)) if v}, "note": "Simulated only; matching cutoff and seeds."})
        mv = {m["id"]: m["values"] for m in metrics}
        y0, y1 = mv["yellow_zone_trips"]["baseline"], mv["yellow_zone_trips"]["alternative"]
        f0, f1 = mv["hvfhv_zone_trips"]["baseline"], mv["hvfhv_zone_trips"]["alternative"]
        r0, r1 = mv["charge_revenue"]["baseline"], mv["charge_revenue"]["alternative"]
        hero["alternative"] = {"kicker": f"Alternative: {alt['short_title']}",
                               "stats": [{"label": "Trips ending in the zone, both services", "value": f"{(y1 + f1) / (y0 + f0) * 100 - 100:+.1f}%", "unit": ""},
                                         {"label": f"Per-trip charges collected over {H} weeks", "value": f"${r0 / 1e6:.1f}M → ${r1 / 1e6:.1f}M", "unit": ""}],
                               "text": (f"Doubling the charge loses {100 - (y1 + f1) / (y0 + f0) * 100:.1f}% of the trips ending in the zone in the simulation and raises the per-trip charges "
                                        f"riders pay from ${r0 / 1e6:.1f}M to ${r1 / 1e6:.1f}M over {H} weeks. This is a simulated alternative, not an observed price change."),
                               "chart": None}
    doc.update({"sources": sources, "metrics": metrics, "effects": [], "charts": charts, "hero": hero, "evaluation": {"generated": ev.get("generated"), "protocol": proto}})
    return doc
