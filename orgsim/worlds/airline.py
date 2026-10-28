"""Airline world: carriers flying a published schedule through airports whose weather and air-traffic conditions vary
day by day; each carrier's operations control decides how hard to thin its schedule, and disruption carries over
through crews and aircraft out of position.

Layers, stepped one day at a time from a cutoff t0 for H days:

  Airports. Each modelled airport (and one group for all others) has a daily condition: the share of flights touching
  it that are hit by weather or the air traffic system (BTS cancellation codes B and C, or weather plus air-system
  delay of 15 minutes or more). Conditions are drawn from each airport's own distribution for that calendar month,
  measured over the years before t0, with day-to-day persistence, a national storm factor shared by all airports and a
  slow component that carries the airport's recent level forward (a staffing shortage, a closed runway).

  Carriers. Every carrier flies the schedule it published (scheduled departures per airport and arrivals per
  destination are exogenous inputs, like the actual incoming orders of the process world). At each airport-day its
  cancellation share and its share of flights not arriving on time respond to the origin airport's condition, the
  conditions at the carrier's destinations that day, the airport's scheduled load, the day of the week, and the
  carrier's own disruption memory: an exponentially fading stock of its recent cancellations (crews and aircraft out
  of position), whose fade rate is the carrier's recovery capacity.

  Operations control (seat `ops_control`, one per carrier). Each day the kernel offers the seat cancellation
  postures from "hold the schedule" to "thin hard", with the weights a carrier in that situation has historically
  used; the rule adapter draws from them, and a language-model seat is a configuration change. The chosen posture
  sets the carrier-day cancellation effect; delays follow from conditions and the posture (kernel-owned).

Every parameter is fitted at t0 from days strictly before it (calibration/airline.yaml fixes the window and the
choices); outcomes after t0 are read only by evaluate() for scoring. Each run simulates `paths` independent weather
paths; the point prediction is the mean over runs and paths.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import expit, logit, ndtr, ndtri

from ..instances import InstanceContext
from ..kernel.world import Agent, BaseWorld, RunSummary
from ..policies.base import Observation
from ..policies.registry import load_registry
from ..store.runs import RunWriter

DAY = pd.Timedelta(days=1)
OUTCOMES = ("canc", "late")                      # cancellation share; share of scheduled flights not arriving on time
POSTURES = ["hold schedule", "light thinning", "some thinning", "normal", "more thinning", "heavy thinning", "thin hard"]


# ------------------------------------------------------------------ data

@dataclass
class AirlineData:
    dates: pd.DatetimeIndex
    carriers: list[str]
    airports: list[str]
    sched: np.ndarray        # [day, carrier, airport] scheduled departures
    canc: np.ndarray         # cancelled
    ontime: np.ndarray       # arrived on time
    arr: np.ndarray          # [day, carrier, airport] scheduled arrivals (destinations)
    ap_n: np.ndarray         # [day, airport] flights touching the airport
    ap_exo: np.ndarray       # ... hit by weather or the air traffic system

    def idx(self, t: pd.Timestamp) -> int:
        return int(self.dates.searchsorted(pd.Timestamp(t)))


@lru_cache(maxsize=2)
def _load(root: str, mtime: float) -> AirlineData:
    from pathlib import Path
    n = Path(root)
    cell = pd.read_parquet(n / "cell_day.parquet", columns=["date", "carrier", "airport", "sched", "cancelled", "arr_ontime"])
    arr = pd.read_parquet(n / "arr_day.parquet")
    ap = pd.read_parquet(n / "airport_day.parquet")
    dates = pd.date_range(cell.date.min(), cell.date.max(), freq="D")
    carriers = sorted(cell.carrier.unique())
    airports = sorted(set(cell.airport) - {"OTHER"}) + ["OTHER"]
    D, C, A = len(dates), len(carriers), len(airports)
    ci = {c: i for i, c in enumerate(carriers)}; ai = {a: i for i, a in enumerate(airports)}
    def cube(df: pd.DataFrame, col: str) -> np.ndarray:
        out = np.zeros((D, C, A), dtype=np.float32)
        d = dates.get_indexer(df.date); c = df.carrier.map(ci).to_numpy(); a = df.airport.map(ai).to_numpy()
        np.add.at(out, (d, c, a), df[col].to_numpy(dtype=np.float32))
        return out
    sq = np.zeros((D, A), dtype=np.float32); ex = np.zeros((D, A), dtype=np.float32)
    d = dates.get_indexer(ap.date); a = ap.airport.map(ai).to_numpy()
    np.add.at(sq, (d, a), ap.n.to_numpy(dtype=np.float32)); np.add.at(ex, (d, a), ap.exo.to_numpy(dtype=np.float32))
    return AirlineData(dates, carriers, airports, cube(cell, "sched"), cube(cell, "cancelled"), cube(cell, "arr_ontime"), cube(arr, "sched_arr"), sq, ex)


def load_data(ctx: InstanceContext) -> AirlineData:
    p = ctx.data_normalized / "cell_day.parquet"
    if not p.exists():
        raise FileNotFoundError(f"{p} missing; run `orgsim ingest {ctx.id}`")
    return _load(str(ctx.data_normalized), p.stat().st_mtime)


def airport_index(n: np.ndarray, exo: np.ndarray) -> np.ndarray:
    """Logit of the share of an airport's flights hit by weather or the air traffic system (smoothed)."""
    return logit((exo + 0.5) / (n + 1.0))


def trailing_mean(x: np.ndarray, k: int) -> np.ndarray:
    """Mean of the k previous rows (excluding the current one) along axis 0; the first rows use what exists."""
    c = np.cumsum(np.concatenate([np.zeros((1,) + x.shape[1:]), x], axis=0), axis=0)
    i = np.arange(x.shape[0])
    lo = np.maximum(i - k, 0)
    cnt = np.maximum(i - lo, 1).reshape((-1,) + (1,) * (x.ndim - 1))
    return (c[i] - c[lo]) / cnt


def stock(series: np.ndarray, decay: float) -> np.ndarray:
    """S[d] = sum_{k>=1} decay^(k-1) * series[d-k]: what is still out of position from earlier days (axis 0 = days)."""
    out = np.zeros_like(series, dtype=float)
    for d in range(1, series.shape[0]):
        out[d] = decay * out[d - 1] + series[d - 1]
    return out


# ------------------------------------------------------------------ calibration at a cutoff

def _train_mask(dates: pd.DatetimeIndex, t0: pd.Timestamp, years: float, exclude: list[list[str]]) -> np.ndarray:
    m = (dates < t0) & (dates >= t0 - pd.Timedelta(days=int(365.25 * years)))
    for a, b in exclude:
        m &= ~((dates >= pd.Timestamp(a)) & (dates <= pd.Timestamp(b)))
    return np.asarray(m)


def _ar1(x: np.ndarray, ok: np.ndarray) -> tuple[float, float]:
    """AR(1) coefficient and innovation sd from consecutive pairs where both days are usable (axis 0 = days)."""
    pair = ok[1:] & ok[:-1]
    a, b = x[:-1][pair], x[1:][pair]
    if len(a) < 20 or np.var(a) <= 0:
        return 0.0, float(np.std(x[ok])) if ok.any() else 1.0
    rho = float(np.clip(np.cov(a, b)[0, 1] / np.var(a), -0.2, 0.98))
    sd = float(np.std(b - rho * a))
    return rho, sd


def fit_at(d: AirlineData, t0: pd.Timestamp, par: dict[str, Any]) -> dict[str, Any]:
    """Every parameter from days strictly before t0."""
    years = float(par.get("training_years", 3))
    exclude = par.get("exclude_periods", [])
    k = d.idx(t0)
    dates = d.dates[:k]
    tr = _train_mask(dates, t0, years, exclude)
    if tr.sum() < 365:
        raise ValueError(f"fewer than 365 training days before {t0.date()}")
    A = len(d.airports)
    u = airport_index(d.ap_n[:k], d.ap_exo[:k])                       # [day, airport]
    months = dates.month.to_numpy()
    # --- airport conditions: month-specific marginals, normal scores, national factor, slow and fast persistence
    qgrid = np.linspace(0, 1, 101)
    marg = np.zeros((12, A, 101))
    z = np.full(u.shape, np.nan)
    for m in range(1, 13):
        rows = tr & (months == m)
        if rows.sum() < 10:
            rows = tr
        mm = months == m
        for a in range(A):
            v = np.sort(u[rows, a])
            marg[m - 1, a] = np.quantile(v, qgrid)
            mid = (np.searchsorted(v, u[mm, a], side="left") + np.searchsorted(v, u[mm, a], side="right")) / 2
            z[mm, a] = ndtri(np.clip((mid + 0.5) / (len(v) + 1), 1e-4, 1 - 1e-4))
    ok = tr & np.isfinite(z).all(1)
    g = z.mean(1)
    lam = np.array([np.cov(z[ok, a], g[ok])[0, 1] / np.var(g[ok]) for a in range(A)])
    e = z - lam[None, :] * g[:, None]
    slow_days = int(par.get("slow_window_days", 28))
    use_slow = bool(par.get("airport_slow_level", True))
    e_slow = trailing_mean(np.nan_to_num(e), slow_days) if use_slow else np.zeros_like(e)
    e_fast = e - e_slow
    rho_g, sd_g = _ar1(g, ok)
    rho_e, sd_e = np.zeros(A), np.zeros(A)
    for a in range(A):
        rho_e[a], sd_e[a] = _ar1(e_fast[:, a], ok)
    # persistence of the slow level: how much of the trailing-window mean is still there one window later
    phi_slow = np.zeros(A)
    if use_slow:
        lagged = np.roll(e_slow, -slow_days, axis=0)
        okp = ok & np.roll(ok, -slow_days) & (np.arange(len(ok)) < len(ok) - slow_days)
        for a in range(A):
            x0, x1 = e_slow[okp, a], lagged[okp, a]
            phi_slow[a] = float(np.clip(np.cov(x0, x1)[0, 1] / np.var(x0), 0.0, 0.95)) if np.var(x0) > 0 else 0.0
    last = k - 1
    air = {"marg": marg, "lam": lam, "rho_g": rho_g, "sd_g": sd_g, "rho_e": rho_e, "sd_e": sd_e, "phi_slow": phi_slow,
           "g0": float(g[last]), "e0": np.nan_to_num(e_fast[last]),
           "slow0": np.nan_to_num(e[max(0, k - slow_days):k]).mean(0) if use_slow else np.zeros(A), "slow_days": slow_days}
    # --- carriers in scope: flying on nearly every one of the 28 days before t0, with enough training days
    recent = d.sched[k - 28:k].sum(2)                                   # [28, C]
    active = [c for c in range(len(d.carriers)) if (recent[:, c] > 0).mean() >= 0.9]
    load = np.log((d.sched[:k].sum(1) + 1) / (trailing_mean(d.sched[:k].sum(1), 28) + 1))       # [day, airport]
    dow = dates.dayofweek.to_numpy()
    decays = [float(x) for x in par.get("stock_decay_grid", [0.0, 0.3, 0.5, 0.7, 0.85])]
    min_n = int(par.get("min_cell_flights", 5))
    carriers: dict[str, Any] = {}
    for c in active:
        n = d.sched[:k, c, :]                                            # [day, airport]
        ntot = n.sum(1)
        if (tr & (ntot > 0)).sum() < int(par.get("min_training_days", 180)):
            continue
        share_canc = np.where(ntot > 0, d.canc[:k, c, :].sum(1) / np.maximum(ntot, 1), 0.0)
        warr = d.arr[:k, c, :]
        ud = np.where(warr.sum(1) > 0, (warr * u).sum(1) / np.maximum(warr.sum(1), 1), u.mean(1))
        cells = tr[:, None] & (n >= min_n)
        dd, aa = np.nonzero(cells)
        w = n[dd, aa]
        ys = {"canc": logit((d.canc[:k, c, :][dd, aa] + 0.5) / (w + 1)),
              "late": logit((w - d.ontime[:k, c, :][dd, aa] + 0.5) / (w + 1))}
        base_cols = [np.ones_like(w), u[dd, aa], ud[dd], load[dd, aa]] + [(dow[dd] == j).astype(float) for j in range(1, 7)]
        best = None
        for dec in decays:
            S = np.log1p(100 * stock(share_canc, dec))                    # stock in log points of percent-days
            X = np.column_stack(base_cols + [S[dd]])
            sw = np.sqrt(w)
            beta, *_ = np.linalg.lstsq(X * sw[:, None], ys["canc"] * sw, rcond=None)
            sse = float(np.sum(w * (ys["canc"] - X @ beta) ** 2))
            if best is None or sse < best[0]:
                best = (sse, dec, S, X)
        _, dec, S, X = best
        sw = np.sqrt(w)
        fit: dict[str, Any] = {"decay": dec, "n_cells": int(len(w))}
        resid = {}
        for y_id, y in ys.items():
            beta, *_ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)
            r = y - X @ beta
            fit[y_id] = {"beta": beta}
            resid[y_id] = r
        # carrier-day effect (weighted mean residual per day) and cell noise
        day_eff = {}
        for y_id, r in resid.items():
            num = np.bincount(dd, weights=w * r, minlength=k); den = np.bincount(dd, weights=w, minlength=k)
            eta = np.where(den > 0, num / np.maximum(den, 1e-9), 0.0)
            day_eff[y_id] = eta
            cell = r - eta[dd]
            fit[y_id]["sd_cell"] = float(np.sqrt(np.sum(w * cell ** 2) / np.sum(w)))
        okc = tr & (ntot > 0)
        use_slow_c = bool(par.get("carrier_slow_level", True))
        for y_id, eta in day_eff.items():
            slow = trailing_mean(eta, slow_days) if use_slow_c else np.zeros_like(eta)
            fast = eta - slow
            rho, sd = _ar1(fast, okc)
            phi = 0.0
            if use_slow_c:
                lag = np.roll(slow, -slow_days); okp = okc & np.roll(okc, -slow_days) & (np.arange(k) < k - slow_days)
                phi = float(np.clip(np.cov(slow[okp], lag[okp])[0, 1] / np.var(slow[okp]), 0.0, 0.95)) if np.var(slow[okp]) > 0 else 0.0
            fit[y_id].update({"rho": rho, "sd": sd, "phi_slow": phi, "eta0": float(fast[k - 1]),
                              "slow0": float(eta[max(0, k - slow_days):k].mean()) if use_slow_c else 0.0})
        fa = day_eff["canc"] - (trailing_mean(day_eff["canc"], slow_days) if use_slow_c else 0)
        fb = day_eff["late"] - (trailing_mean(day_eff["late"], slow_days) if use_slow_c else 0)
        pair = okc
        fit["corr"] = float(np.corrcoef(fa[pair], fb[pair])[0, 1]) if pair.sum() > 20 else 0.0
        fit["stock_hist"] = share_canc[-60:].tolist()                    # the last 60 days feed the stock forward
        fit["stock0"] = float(stock(share_canc, dec)[-1] * dec + share_canc[-1])
        carriers[d.carriers[c]] = fit
    return {"t0": str(t0.date()), "air": air, "carriers": carriers, "train_days": int(tr.sum()),
            "train_from": str(dates[tr][0].date()), "train_to": str(dates[tr][-1].date())}


_FIT_CACHE: dict[tuple, dict[str, Any]] = {}


def cached_fit(ctx: InstanceContext, d: AirlineData, t0: pd.Timestamp, par: dict[str, Any]) -> dict[str, Any]:
    key = (ctx.id, str(t0.date()), json.dumps(par, sort_keys=True), id(d))
    if key not in _FIT_CACHE:
        if len(_FIT_CACHE) > 4:
            _FIT_CACHE.clear()
        _FIT_CACHE[key] = fit_at(d, t0, par)
    return _FIT_CACHE[key]


# ------------------------------------------------------------------ the world

class World(BaseWorld):
    @classmethod
    def from_instance(cls, ctx: InstanceContext, scenario: dict[str, Any], seed: int) -> "World":
        w = scenario.get("world", {})
        t0 = pd.Timestamp(w["t0"])
        H = int(w.get("horizon_days", scenario.get("horizon_days", 28)))
        return cls(ctx, scenario, seed, t0.to_pydatetime(), (t0 + H * DAY).to_pydatetime())

    def __init__(self, ctx: InstanceContext, scenario: dict[str, Any], seed: int, start: datetime, end: datetime) -> None:
        super().__init__(ctx, scenario, seed, start, end)
        t_cal = time.time()
        self.rng = np.random.default_rng(seed)
        self.par = ctx.yaml("calibration/airline.yaml")
        self.t0 = pd.Timestamp(start)
        self.H = int(round((end - start) / timedelta(days=1)))
        self.P = int(scenario.get("world", {}).get("paths", self.par.get("paths", 100)))
        self.d = load_data(ctx)
        self.fit = cached_fit(ctx, self.d, self.t0, self.par)
        self.registry = load_registry(ctx)
        self.carriers = list(self.fit["carriers"])
        self.cidx = [self.d.carriers.index(c) for c in self.carriers]
        k0 = self.d.idx(self.t0)
        if k0 + self.H > len(self.d.dates):
            raise ValueError(f"schedule ends before {self.t0.date()} + {self.H} days")
        # exogenous schedule for the horizon (departures by origin, arrivals by destination); outcomes are not read
        self.sched = self.d.sched[k0:k0 + self.H][:, self.cidx, :].astype(float)
        self.arr = self.d.arr[k0:k0 + self.H][:, self.cidx, :].astype(float)
        tot = self.d.sched[:k0 + self.H].sum(1)
        self.load = np.log((tot + 1) / (trailing_mean(tot, 28) + 1))[k0:k0 + self.H]        # schedule-only feature
        self.days = self.d.dates[k0:k0 + self.H]
        # interventions: recovery capacity (stock fade) and thinning bias per carrier
        self.decay_override: dict[str, float] = {}
        self.posture_shift: dict[str, float] = {}
        for iv in scenario.get("interventions", []) or []:
            if iv.get("type") == "recovery":
                # recovery capacity: the fade rate of the carrier's disruption stock, set to a value or to the median of
                # the other carriers fitted at the same cutoff ("peer_median")
                for c in iv.get("carriers", []):
                    if c not in self.fit["carriers"]:
                        continue
                    if iv.get("decay") == "peer_median":
                        self.decay_override[c] = float(np.median([f["decay"] for k, f in self.fit["carriers"].items() if k != c]))
                    elif "decay" in iv:
                        self.decay_override[c] = float(iv["decay"])
            elif iv.get("type") == "posture_shift":
                for c in iv.get("carriers", []):
                    self.posture_shift[c] = float(iv.get("shift", 0.0))
        for c in self.carriers:
            self.agents[f"ops:{c}"] = Agent(id=f"ops:{c}", role="ops_control", org_unit=c, seat="ops_control")
        # posture options: equal-probability bins of the standard normal, represented by their conditional means
        K = len(POSTURES)
        edges = ndtri(np.linspace(0, 1, K + 1).clip(1e-9, 1 - 1e-9))
        pdf = lambda x: np.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)  # noqa: E731
        self.bin_mean = np.array([(pdf(edges[i]) - pdf(edges[i + 1])) * K for i in range(K)])
        self.bin_mean /= np.sqrt(np.mean(self.bin_mean ** 2))          # unit variance across the K options
        self.calibration_s = time.time() - t_cal

    def _airport_paths(self) -> np.ndarray:
        """Simulated airport condition index u[path, day, airport]."""
        air, P, H = self.fit["air"], self.P, self.H
        A = len(self.d.airports)
        g = np.full(P, air["g0"]); e = np.tile(air["e0"], (P, 1))
        slow0 = np.asarray(air["slow0"]); phi = np.asarray(air["phi_slow"]); L = air["slow_days"]
        out = np.zeros((P, H, A))
        for h in range(H):
            g = air["rho_g"] * g + air["sd_g"] * self.rng.standard_normal(P)
            e = air["rho_e"] * e + air["sd_e"] * self.rng.standard_normal((P, A))
            z = air["lam"][None, :] * g[:, None] + e + (phi ** ((h + 1) / L) * slow0)[None, :]
            p = ndtr(z)
            m = self.days[h].month - 1
            qg = air["marg"][m]                                          # [airport, 101]
            pos = p * 100
            lo = np.floor(pos).astype(int).clip(0, 99); fr = pos - lo
            out[:, h, :] = qg[np.arange(A)[None, :], lo] * (1 - fr) + qg[np.arange(A)[None, :], lo + 1] * fr
        return out

    def run(self, writer: RunWriter) -> RunSummary:
        self._writer = writer
        t_run = time.time()
        P, H, C = self.P, self.H, len(self.carriers)
        A = len(self.d.airports)
        u = self._airport_paths()                                        # [P, H, A]
        dows = self.days.dayofweek.to_numpy()
        pol = self.registry.for_seat("ops_control")
        canc = np.zeros((P, H, C, A)); ontime = np.zeros((P, H, C, A))
        posture_counts = np.zeros((C, len(POSTURES)), dtype=int)
        fits = [self.fit["carriers"][c] for c in self.carriers]
        decs = [self.decay_override.get(c, f["decay"]) for c, f in zip(self.carriers, fits)]
        S = [np.full(P, stock(np.asarray(f["stock_hist"]), dec)[-1] * dec + f["stock_hist"][-1]) for f, dec in zip(fits, decs)]   # stock entering day 0
        eta = [{y: np.full(P, f[y]["eta0"]) for y in OUTCOMES} for f in fits]
        L = self.fit["air"]["slow_days"]
        for h in range(H):
            dummies = [(dows[h] == j) * 1.0 for j in range(1, 7)]
            for ci, c in enumerate(self.carriers):
                f = fits[ci]
                n = self.sched[h, ci, :]                                  # [A]
                warr = self.arr[h, ci, :]
                ud = (u[:, h, :] * warr[None, :]).sum(1) / warr.sum() if warr.sum() > 0 else u[:, h, :].mean(1)   # [P]
                logS = np.log1p(100 * S[ci])
                # operations control chooses a cancellation posture on each weather path (rule adapter: draw by weight)
                zc = np.empty(P)
                for p_ in range(P):
                    obs = Observation(agent_id=f"ops:{c}", role="ops_control", sim_time=str(self.days[h].date()),
                                      context={"carrier": c, "scheduled_flights": int(n.sum()), "disrupted_stock_pct_days": round(float(100 * S[ci][p_]), 2),
                                               "worst_airport_condition": round(float(expit(u[p_, h, :].max())), 3)},
                                      options=[{"kind": "posture", "target": t, "weight": 1.0 / len(POSTURES)} for t in POSTURES])
                    act = pol.decide(obs, self.rng)
                    i = POSTURES.index(act.target) if act.target in POSTURES else int(self.rng.integers(len(POSTURES)))
                    posture_counts[ci, i] += 1
                    zc[p_] = self.bin_mean[i]
                    if p_ == 0:
                        self.emit(agent_id=f"ops:{c}", role="ops_control", org_unit=c, activity="posture", action_type="decide", provenance="simulated",
                                  attributes={"chosen": POSTURES[i], "stock_pct_days": round(float(100 * S[ci][0]), 2), "scheduled": int(n.sum())})
                zc = zc + self.posture_shift.get(c, 0.0)
                zl = f["corr"] * zc + math.sqrt(max(0.0, 1 - f["corr"] ** 2)) * self.rng.standard_normal(P)
                shares = {}
                for y, zz in (("canc", zc), ("late", zl)):
                    fy = f[y]
                    eta[ci][y] = fy["rho"] * eta[ci][y] + fy["sd"] * zz
                    slow = fy["phi_slow"] ** ((h + 1) / L) * fy["slow0"]
                    b = fy["beta"]
                    lin = (b[0] + b[1] * u[:, h, :] + b[2] * ud[:, None] + b[3] * self.load[h][None, :]
                           + sum(b[4 + j] * dummies[j] for j in range(6)) + b[10] * logS[:, None]
                           + (eta[ci][y] + slow)[:, None] + fy["sd_cell"] * self.rng.standard_normal((P, A)))
                    shares[y] = expit(lin)
                late = np.maximum(shares["late"], shares["canc"])
                canc[:, h, ci, :] = n[None, :] * shares["canc"]
                ontime[:, h, ci, :] = n[None, :] * (1 - late)
                S[ci] = decs[ci] * S[ci] + canc[:, h, ci, :].sum(1) / max(n.sum(), 1)
            for _ in range(24):
                self.clock.advance()
        self.runtime_s = time.time() - t_run
        weeks = max(1, H // 7)
        sched_c = self.sched.sum(2)                                      # [H, C]
        def weekly(x_pc: np.ndarray, den: np.ndarray) -> np.ndarray:
            """x[P, H, ...] -> rate per path and week [P, W, ...] with the scheduled flights as denominator."""
            xs = np.stack([x_pc[:, 7 * w:7 * (w + 1)].sum(1) for w in range(weeks)], axis=1)
            ds = np.stack([den[7 * w:7 * (w + 1)].sum(0) for w in range(weeks)], axis=0)
            return xs / np.maximum(ds, 1)[None]
        c_canc = weekly(canc.sum(3), sched_c); c_on = weekly(ontime.sum(3), sched_c)          # [P, W, C]
        sched_a = self.sched.sum(1)                                      # [H, A]
        a_canc = weekly(canc.sum(2), sched_a); a_on = weekly(ontime.sum(2), sched_a)          # [P, W, A]
        pct = lambda x: [np.round(100 * np.mean(x, 0), 4).tolist(), np.round(100 * np.percentile(x, 5, 0), 3).tolist(), np.round(100 * np.percentile(x, 95, 0), 3).tolist()]  # noqa: E731
        headline = {
            "t0": str(self.t0.date()), "horizon_days": H, "weeks": weeks, "paths": P, "carriers": self.carriers, "airports": self.d.airports,
            "carrier_ontime_pct": pct(c_on), "carrier_cancel_pct": pct(c_canc),
            "airport_ontime_pct": pct(a_on), "airport_cancel_pct": pct(a_canc),
            "carrier_sched": [[float(self.sched[7 * w:7 * (w + 1), ci].sum()) for ci in range(C)] for w in range(weeks)],
            "airport_sched": [[float(self.sched[7 * w:7 * (w + 1), :, ai].sum()) for ai in range(A)] for w in range(weeks)],
            "cancelled_flights": float(canc.sum((1, 2, 3)).mean()), "scheduled_flights": float(self.sched.sum()),
            "postures": {c: {POSTURES[i]: int(posture_counts[ci, i]) for i in range(len(POSTURES))} for ci, c in enumerate(self.carriers)},
            "recovery_decay": {c: self.decay_override.get(c, self.fit["carriers"][c]["decay"]) for c in self.carriers},
            "calibration": {"train_from": self.fit["train_from"], "train_to": self.fit["train_to"], "train_days": self.fit["train_days"],
                            "rho_storm": round(self.fit["air"]["rho_g"], 3)},
            "policies": self.registry.describe(), "runtime_s": round(self.runtime_s, 2), "calibration_s": round(self.calibration_s, 2),
        }
        return RunSummary(run_id=writer.run_id, instance=self.ctx.id, scenario=self.scenario.get("id", "baseline"), seed=self.seed,
                          start=str(self.t0.date()), end=str((self.t0 + H * DAY).date()), ticks=H * 24, events=self._n_events, headline=headline)


# ------------------------------------------------------------------ evaluation

COMPARATOR_LABELS = {
    "carry_forward": "No change: the week before the cutoff carried forward",
    "seasonal_naive": "Same week last year",
    "historical_average": "Historical average: the same weeks in the three previous years",
    "trend": "Recent trend: a straight line through the eight weeks before the cutoff",
    "ets": "Exponential smoothing (ETS, chosen by AICc on two years of weekly history)",
}
LEVELS = ("carrier", "airport")
METRICS = ("ontime", "cancel")


def protocol_cutoffs(proto: dict[str, Any]) -> list[pd.Timestamp]:
    if proto.get("cutoffs"):
        return [pd.Timestamp(c) for c in proto["cutoffs"]]
    g = proto["cutoff_grid"]
    return list(pd.date_range(g["start"], g["end"], freq=f"{int(g.get('step_days', 7))}D"))


def weekly_rates(d: AirlineData, start: int, weeks: int, cidx: list[int], level: str) -> dict[str, np.ndarray]:
    """Scheduled flights, on-time share (%) and cancellation share (%) per week from day index `start`, for the
    carriers in cidx (level 'carrier', columns = carriers) or every airport (level 'airport', departures of those carriers)."""
    out: dict[str, list] = {"sched": [], "ontime": [], "cancel": []}
    ax = (0, 2) if level == "carrier" else (0, 1)
    for w in range(weeks):
        s, e = start + 7 * w, start + 7 * (w + 1)
        n = d.sched[s:e][:, cidx, :].sum(ax); c = d.canc[s:e][:, cidx, :].sum(ax); o = d.ontime[s:e][:, cidx, :].sum(ax)
        out["sched"].append(n)
        with np.errstate(invalid="ignore", divide="ignore"):
            out["ontime"].append(100 * o / n); out["cancel"].append(100 * c / n)
    return {k: np.array(v, dtype=float) for k, v in out.items()}             # [weeks, units]


def comparators(d: AirlineData, t0: pd.Timestamp, cidx: list[int], level: str, W: int, exclude: list[list[str]]) -> dict[str, dict[str, np.ndarray]]:
    """Standard forecasts of each unit's weekly on-time and cancellation shares, from weeks before t0 only."""
    from ..evaluation.forecast import auto_ets, trend
    k0 = d.idx(t0)
    hist_w = 104
    hist = weekly_rates(d, k0 - 7 * hist_w, hist_w, cidx, level)                  # oldest first
    excl = np.zeros(len(d.dates), dtype=bool)
    for a, b in exclude:
        excl |= np.asarray((d.dates >= pd.Timestamp(a)) & (d.dates <= pd.Timestamp(b)))
    out: dict[str, dict[str, np.ndarray]] = {}
    for m in METRICS:
        h = hist[m]
        U = h.shape[1]
        cf = np.repeat(h[-1:], W, axis=0)
        sn = weekly_rates(d, k0 - 364, W, cidx, level)[m]
        ha = []
        for y in (1, 2, 3):
            s = k0 - 364 * y
            r = weekly_rates(d, s, W, cidx, level)[m]
            bad = np.array([excl[s + 7 * w: s + 7 * (w + 1)].any() for w in range(W)])
            r[bad] = np.nan
            ha.append(r)
        with np.errstate(all="ignore"):
            ha = np.nanmean(np.stack(ha), axis=0)
        ha = np.where(np.isfinite(ha), ha, cf)
        sn = np.where(np.isfinite(sn), sn, cf)
        tr = np.zeros((W, U)); et = np.zeros((W, U))
        for j in range(U):
            col = pd.Series(h[:, j]).ffill().bfill().fillna(0.0).to_numpy()
            tr[:, j] = np.clip(trend(col, W, window=8), 0, 100)
            p = np.clip(col / 100, 1e-4, 1 - 1e-4)
            et[:, j] = 100 * expit(np.clip(np.asarray(auto_ets(logit(p), W)), -50, 50))
        out[m] = {"carry_forward": cf, "seasonal_naive": sn, "historical_average": ha, "trend": tr, "ets": et}
    return out


def _run_world(ctx: InstanceContext, scenario: dict[str, Any], seed: int, t0: str) -> tuple[World, RunSummary]:
    sc = json.loads(json.dumps(scenario))
    sc.setdefault("world", {})["t0"] = t0
    writer = RunWriter(ctx.id, sc["id"], config={"instance": ctx.id, "scenario": sc, "seed": seed, "evaluation": True})
    world = World.from_instance(ctx, sc, seed)
    summary = world.run(writer)
    writer.close(summary.to_json())
    print(f"[{ctx.id}] {sc['id']} t0={t0} seed={seed} -> {writer.run_id} (calibration {world.calibration_s:.1f}s, run {world.runtime_s:.1f}s)", flush=True)
    return world, summary


def score_cutoff(d: AirlineData, t0: pd.Timestamp, headlines: list[dict[str, Any]], exclude: list[list[str]]) -> dict[str, Any]:
    """Actual outcomes after t0 (read here, for scoring only), the simulation's mean over runs, and the comparators."""
    h0 = headlines[0]
    W = int(h0["weeks"])
    cidx = [d.carriers.index(c) for c in h0["carriers"]]
    k0 = d.idx(t0)
    res: dict[str, Any] = {"cutoff": str(t0.date()), "carriers": h0["carriers"], "airports": h0["airports"], "weeks": W}
    for level, idx in (("carrier", cidx), ("airport", cidx)):              # airports: departures of the same carriers
        act = weekly_rates(d, k0, W, idx, level)
        before = weekly_rates(d, k0 - 7 * W, W, idx, level)
        comp = comparators(d, t0, idx, level, W, exclude)
        for m in METRICS:
            hk = f"{level}_{m}_pct"
            sims = np.array([h[hk][0] for h in headlines])                         # [runs, W, units]
            lo = np.array([h[hk][1] for h in headlines]).mean(0); hi = np.array([h[hk][2] for h in headlines]).mean(0)
            res[f"{level}_{m}"] = {"actual": act[m].round(4).tolist(), "simulation": sims.mean(0).round(4).tolist(),
                                   "interval": [lo.round(3).tolist(), hi.round(3).tolist()], "before": before[m].round(4).tolist(),
                                   **{k: v.round(4).tolist() for k, v in comp[m].items()}}
        sched = act["sched"].copy()
        if level == "airport" and "OTHER" in h0["airports"]:
            sched[:, h0["airports"].index("OTHER")] = 0.0                  # the group of all other airports is simulated, not scored
        res[f"{level}_sched"] = sched.round(1).tolist()
    return res


def _cutoff_job(job: tuple) -> dict[str, Any]:
    """All seeds of one cutoff (one process keeps the cutoff's fit in memory), then the scoring."""
    iid, scenario, t0s, seeds, exclude, score = job
    from ..instances import get_instance
    ctx = get_instance(iid)
    runs = [_run_world(ctx, scenario, sd, t0s)[1] for sd in seeds]
    if not score:
        return {"cutoff": t0s, "run_ids": [r.run_id for r in runs], "headlines": [r.headline for r in runs]}
    res = score_cutoff(load_data(ctx), pd.Timestamp(t0s), [r.headline for r in runs], exclude)
    res["run_ids"] = [r.run_id for r in runs]
    return res


def _jobs(ctx: InstanceContext, scenario: dict[str, Any], cutoffs: list[pd.Timestamp], seeds: list[int], exclude, workers: int, score: bool = True):
    jobs = [(ctx.id, scenario, str(c.date()), seeds, exclude, score) for c in cutoffs]
    if workers <= 1:
        yield from map(_cutoff_job, jobs)
    else:
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as ex:
            yield from ex.map(_cutoff_job, jobs)


def _errors(win: dict[str, Any], level: str, m: str, who: str, min_sched: float, weeks: list[int] | None = None) -> np.ndarray:
    """Absolute errors (percentage points) of one prediction for every unit-week with enough scheduled flights."""
    a = np.array(win[f"{level}_{m}"]["actual"], dtype=float); p = np.array(win[f"{level}_{m}"][who], dtype=float)
    n = np.array(win[f"{level}_sched"], dtype=float)
    if weeks is not None:
        a, p, n = a[weeks], p[weeks], n[weeks]
    ok = (n >= min_sched) & np.isfinite(a) & np.isfinite(p)
    return np.abs(p - a)[ok]


def score_windows(wins: list[dict[str, Any]], min_sched: float, weeks: list[int] | None = None) -> dict[str, Any]:
    """Mean absolute error per window (unit-weeks pooled inside a window), then averaged over windows; the mean actual
    level over the same unit-weeks gives accuracy = 100 x (1 - error / mean actual)."""
    whos = ["simulation"] + list(COMPARATOR_LABELS)
    out: dict[str, Any] = {}
    for level in LEVELS:
        for m in METRICS:
            per: dict[str, list[float]] = {w: [] for w in whos}
            act_mean, n_pred = [], 0
            for win in wins:
                for w in whos:
                    e = _errors(win, level, m, w, min_sched, weeks)
                    if len(e):
                        per[w].append(float(e.mean()))
                a = np.array(win[f"{level}_{m}"]["actual"], dtype=float); n = np.array(win[f"{level}_sched"], dtype=float)
                if weeks is not None:
                    a, n = a[weeks], n[weeks]
                ok = (n >= min_sched) & np.isfinite(a)
                if ok.any():
                    act_mean.append(float(a[ok].mean())); n_pred += int(ok.sum())
            mae = {w: float(np.mean(v)) for w, v in per.items() if v}
            if "simulation" not in mae:
                continue
            best = min(COMPARATOR_LABELS, key=lambda k: mae.get(k, np.inf))
            lvl = float(np.mean(act_mean))
            out[f"{level}_{m}"] = {"mae": mae, "best_comparator": best, "mean_actual": lvl, "windows": len(per["simulation"]), "predictions": n_pred,
                                   "error_reduction_pct": 100 * (1 - mae["simulation"] / mae[best]) if mae.get(best) else None,
                                   "accuracy_pct": {w: 100 * (1 - v / lvl) for w, v in mae.items()} if lvl else {}}
    return out


def business_validation(scored: list[dict[str, Any]], min_sched: float) -> list[dict[str, Any]]:
    """Per-window errors for the headline outcomes (the shape the process world uses)."""
    out = []
    for level, m, label in (("carrier", "ontime", "Share of each carrier's scheduled flights arriving on time, weekly (pp)"),
                            ("carrier", "cancel", "Share of each carrier's scheduled flights cancelled, weekly (pp)"),
                            ("airport", "ontime", "Share of each airport's departing flights arriving on time, weekly (pp)"),
                            ("airport", "cancel", "Share of each airport's departing flights cancelled, weekly (pp)")):
        rows = []
        for w in scored:
            e = {who: _errors(w, level, m, who, min_sched) for who in ["simulation"] + list(COMPARATOR_LABELS)}
            if len(e["simulation"]):
                rows.append({"cutoff": w["cutoff"], "simulation_mae": float(e["simulation"].mean()), "baselines": {k: float(v.mean()) for k, v in e.items() if k != "simulation"}})
        if not rows:
            continue
        sim = float(np.mean([r["simulation_mae"] for r in rows]))
        bm = {k: float(np.mean([r["baselines"][k] for r in rows])) for k in COMPARATOR_LABELS}
        best = min(bm, key=bm.get)
        out.append({"id": f"{level}_{m}", "label": label, "windows": rows, "simulation_mae": sim, "baseline_mae": bm, "best_baseline": best,
                    "beats_best_baseline": sim < bm[best], "error_reduction_pct": 100 * (1 - sim / bm[best]) if bm[best] > 0 else None})
    return out


def event_rows(wins: list[dict[str, Any]], ev: dict[str, Any]) -> dict[str, Any]:
    """One named event (a carrier or an airport over a run of cutoffs): every prediction, week by week."""
    sel = [w for w in wins if ev["cutoffs"][0] <= w["cutoff"] <= ev["cutoffs"][-1]]
    rows = []
    for w in sel:
        units = w["carriers"] if ev["level"] == "carrier" else w["airports"]
        if ev["unit"] not in units:
            continue
        j = units.index(ev["unit"])
        blk = {m: {k: [v[i][j] for i in range(w["weeks"])] for k, v in w[f"{ev['level']}_{m}"].items() if k != "interval"} for m in METRICS}
        rows.append({"cutoff": w["cutoff"], **blk, "sched": [w[f"{ev['level']}_sched"][i][j] for i in range(w["weeks"])]})
    whos = ["simulation"] + list(COMPARATOR_LABELS)
    mae = {m: {k: float(np.mean([np.mean(np.abs(np.array(r[m][k]) - np.array(r[m]["actual"]))) for r in rows])) for k in whos} for m in METRICS} if rows else {}
    return {**ev, "windows": rows, "mae": mae}


def evaluate(ctx: InstanceContext, scenario_ids: list[str]) -> dict[str, Any]:
    from ..scenarios import load_scenario
    proto = ctx.yaml("evaluation/protocol.yaml")
    par = ctx.yaml("calibration/airline.yaml")
    all_cut = protocol_cutoffs(proto)
    n_dev = int(proto.get("dev_cutoffs", max(2, len(all_cut) // 4)))
    only = proto.get("run_only")                                    # "dev" while the design is open; absent for the frozen run
    cutoffs = all_cut[:n_dev] if only == "dev" else all_cut
    seeds = [int(s) for s in proto.get("seeds", [1, 2, 3])]
    workers = max(1, int(proto.get("workers", 1)))
    min_sched = float(proto.get("min_weekly_flights", 200))
    exclude = par.get("exclude_periods", [])
    base_id = proto.get("baseline_scenario", "baseline")
    base = load_scenario(ctx, base_id)
    wins = list(_jobs(ctx, base, cutoffs, seeds, exclude, workers))
    dev_set = {str(c.date()) for c in all_cut[:n_dev]}
    dev = [w for w in wins if w["cutoff"] in dev_set]; held = [w for w in wins if w["cutoff"] not in dev_set]
    W = int(wins[0]["weeks"]) if wins else 4
    accuracy = {"all": score_windows(wins, min_sched), "dev": score_windows(dev, min_sched) if dev else None,
                "held_out": score_windows(held, min_sched) if held else None,
                "by_week_held_out": {str(w + 1): score_windows(held, min_sched, [w]) for w in range(W)} if held else None,
                "by_week_dev": {str(w + 1): score_windows(dev, min_sched, [w]) for w in range(W)} if dev else None}
    events = [event_rows(wins, ev) for ev in (proto.get("events") or [])]
    run_ids = {base_id: [r for w in wins for r in w["run_ids"]]}
    alt_id = ctx.meta.get("scenarios", {}).get("alternative")
    alt_rows = []
    if alt_id and alt_id in scenario_ids and only != "dev":
        alt = load_scenario(ctx, alt_id)
        alt_cuts = [pd.Timestamp(c) for c in (proto.get("alternative_cutoffs") or [])]
        run_ids[alt_id] = []
        for res in _jobs(ctx, alt, alt_cuts, seeds, exclude, workers, score=False):
            run_ids[alt_id] += res["run_ids"]
            alt_rows.append(res["cutoff"])
    result = {"instance": ctx.id, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
              "scenarios": [base_id] + ([alt_id] if alt_rows else []), "run_ids": run_ids,
              "protocol": {"cutoffs": [w["cutoff"] for w in wins], "dev_cutoffs": [w["cutoff"] for w in dev], "held_out_cutoffs": [w["cutoff"] for w in held],
                           "horizon_days": W * 7, "weeks": W, "seeds": seeds, "paths": int(par.get("paths", 100)),
                           "runs": sum(len(w["run_ids"]) for w in wins), "min_weekly_flights": min_sched, "run_only": only,
                           "alternative_cutoffs": alt_rows},
              "comparator_labels": COMPARATOR_LABELS, "accuracy": accuracy, "events": events,
              "business_validation": business_validation(held or wins, min_sched), "windows": wins}
    out = ctx.runs_dir / ("evaluation_dev.json" if only == "dev" else "evaluation.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, default=_json_default))
    return result


def _json_default(o: Any) -> Any:
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return None if np.isnan(o) else float(o)
    if isinstance(o, float) and math.isnan(o):
        return None
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.isoformat()
    return str(o)
