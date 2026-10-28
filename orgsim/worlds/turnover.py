"""Turnover world: each industry's employees, grouped by tenure, deciding month by month whether to quit.

An industry (a series) is a population of employee agents. Each month new hires join; every employee's chance of
quitting combines:

  Habits.   level x drift(h) x season(month): the industry's established quit rate, fitted at each cutoff t0 from months
            before t0 only (robust penalised regression on a piecewise trend and month-of-year effects, the habit model
            of the demand world).
  Tenure.   an employee hired in the last `recent_months` months quits (1 + gamma) times as often as an established one,
            so the industry's quit rate is   base x (1 + gamma x recent-hire share).  The recent-hire share comes from the
            hires published before t0 and, for months after t0, from the industry's own hires habits.
  Openings. quits move with the job openings rate of the month before (elasticity beta): more openings, more outside
            offers. After t0 the last published openings rate is carried forward.

gamma and beta and the level and drift are chosen per industry by backtests whose targets end before t0, with the
one-standard-error rule (the simplest choice: no tenure effect, no openings effect, the last three months' level, no
drift). Each month every employee agent decides through the seat policy (rule: a draw from its quit probability)
whether to quit; the central path (expected decisions, every shock at its median) is the point prediction and the
stochastic runs give the ranges. After t0 the world reads nothing; quits after t0 are read only by evaluate().
Settings live in calibration/turnover.yaml; cutoffs, horizons and comparators in evaluation/protocol.yaml.
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
from .demand import fit_habits, pooled, _json_default

MONTH = pd.offsets.MonthBegin(1)


@dataclass
class TurnoverData:
    q: pd.DataFrame        # month x industry: quits rate (%)
    h: pd.DataFrame        # hires rate (%)
    o: pd.DataFrame        # job openings rate (%)
    ql: pd.DataFrame       # quits level (thousands)
    meta: pd.DataFrame     # index industry: label, scored


@lru_cache(maxsize=2)
def _load(root: str, mtime: float) -> TurnoverData:
    from pathlib import Path
    n = Path(root)
    d = pd.read_parquet(n / "jolts_monthly.parquet")
    p = lambda el: d[d.element == el].pivot_table(index="month", columns="industry", values="value").sort_index()  # noqa: E731
    q = p("QUR")
    idx = pd.date_range(q.index.min(), q.index.max(), freq="MS")
    meta = pd.read_parquet(n / "series.parquet").set_index("series_id")
    return TurnoverData(q.reindex(idx), p("HIR").reindex(idx), p("JOR").reindex(idx), p("QUL").reindex(idx), meta)


def load_data(ctx: InstanceContext) -> TurnoverData:
    p = ctx.data_normalized / "jolts_monthly.parquet"
    if not p.exists():
        raise FileNotFoundError(f"{p} missing; run `orgsim ingest {ctx.id}`")
    return _load(str(ctx.data_normalized), p.stat().st_mtime)


def truncate(d: TurnoverData, t0: pd.Timestamp) -> TurnoverData:
    """The data as known at t0: months before t0 only (used by the leak test)."""
    c = lambda x: x[x.index < t0]  # noqa: E731
    return TurnoverData(c(d.q), c(d.h), c(d.o), c(d.ql), d.meta)


def month_matrix(months: pd.DatetimeIndex) -> np.ndarray:
    return np.column_stack([(months.month == m).astype(float) for m in range(2, 13)])


# ------------------------------------------------------------------ habits (fitted before t0)

def fit_monthly(y: pd.Series, t0: pd.Timestamp, s: dict[str, Any], offset: np.ndarray | None = None) -> dict[str, Any] | None:
    """Robust fit of log y on a penalised piecewise trend and month effects over the months before t0."""
    lo = max(y.index.min(), t0 - int(s["history_months"]) * MONTH)
    x = y[(y.index >= lo) & (y.index < t0)]
    if x.notna().sum() < 36:
        return None
    logy = np.log(x.to_numpy(dtype=float))
    if offset is not None:
        logy = logy - offset[-len(logy):]
    X = month_matrix(x.index)
    beta, trend, resid = fit_habits(logy, X, int(s["knot_months"]), float(s["ridge_trend"]), float(s["ridge_cal"]), iters=4)   # knots every knot_months rows
    return {"months": x.index, "beta": beta, "trend": trend, "resid": resid}


def forecast_habit(f: dict[str, Any], months: pd.DatetimeIndex, level_months: int, drift: float, phi: float) -> np.ndarray:
    r = f["resid"][-level_months:]
    level = f["trend"][-1] + (float(np.nanmedian(r)) if np.isfinite(r).any() else 0.0)
    slope = (f["trend"][-1] - f["trend"][-13]) / 12 if len(f["trend"]) > 13 else 0.0
    h = np.arange(1, len(months) + 1)
    damp = np.cumsum(phi ** h) if phi < 1 else h.astype(float)
    return level + drift * slope * damp + month_matrix(months) @ f["beta"]


def recent_share(hires: pd.Series, months: pd.DatetimeIndex, R: int) -> np.ndarray:
    """Share of employment hired in the previous R months (hires rates summed, in shares)."""
    return np.array([np.nansum(hires.reindex([m - k * MONTH for k in range(1, R + 1)]).to_numpy()) / 100 for m in months])


SPEC_KEYS = ("level_months", "drift", "phi", "gamma", "beta")


def _predict(d: TurnoverData, ind: str, c: pd.Timestamp, sp: dict[str, Any], s: dict[str, Any], H: int,
             hires_fit: dict[str, Any] | None) -> np.ndarray | None:
    """Expected quits rate for H months from cutoff c under one specification (data before c only)."""
    q = d.q[ind][d.q.index < c]
    R = int(s["recent_months"])
    hist_months = q.index
    hires = d.h[ind][d.h.index < c]
    share_hist = recent_share(hires, hist_months, R)
    o = d.o[ind][d.o.index < c]
    lo_hist = np.log(o.reindex(hist_months - MONTH).to_numpy(dtype=float))
    o_ref = float(np.nanmean(np.log(o.iloc[-12:]))) if o.notna().any() else 0.0
    off = np.log1p(sp["gamma"] * share_hist) + sp["beta"] * np.nan_to_num(lo_hist - o_ref)
    f = fit_monthly(q, c, s, off)
    if f is None:
        return None
    months = pd.date_range(c, periods=H, freq="MS")
    base = forecast_habit(f, months, int(sp["level_months"]), float(sp["drift"]), float(sp["phi"]))
    # hires after c from the industry's own hires habits; before c as published
    if hires_fit is not None:
        h_f = pd.Series(np.exp(forecast_habit(hires_fit, months, 3, 0.0, 1.0)), index=months)
    else:
        h_f = pd.Series(float(hires.iloc[-12:].mean()), index=months)
    share = recent_share(pd.concat([hires, h_f]), months, R)
    o_last = float(np.log(o.iloc[-3:].mean())) if o.notna().any() else o_ref
    return np.exp(base + np.log1p(sp["gamma"] * share) + sp["beta"] * (o_last - o_ref))


def calibrate(d: TurnoverData, t0: pd.Timestamp, ind: str, s: dict[str, Any], H: int) -> dict[str, Any]:
    g = s["grid"]
    grid = [dict(zip(SPEC_KEYS, v)) for v in [(k, dr, ph, ga, be) for k in g["level_months"] for dr in g["drift"] for ph in (g["phi"] if dr > 0 else [1.0])
                                              for ga in g["gamma"] for be in g["beta"]]]
    simple = {"level_months": max(g["level_months"]), "drift": 0.0, "phi": 1.0, "gamma": 0.0, "beta": 0.0}
    errs: dict[tuple, list[float]] = {}
    logerr: dict[tuple, list[np.ndarray]] = {}
    for j in range(int(s["inner_cutoffs"])):
        c = t0 - (H + j * int(s["inner_step_months"])) * MONTH
        act = d.q[ind].reindex(pd.date_range(c, periods=H, freq="MS")).to_numpy(dtype=float)
        if np.isnan(act).any() or d.q[ind][d.q.index < c].notna().sum() < int(s["min_history_months"]):
            continue
        hf = fit_monthly(d.h[ind], c, s)
        for sp in grid:
            p = _predict(d, ind, c, sp, s, H, hf)
            if p is None:
                continue
            k = tuple(sp.values())
            errs.setdefault(k, []).append(float(np.abs(p - act).sum() / act.sum()))
            logerr.setdefault(k, []).append(np.log(act / p))
    key0 = tuple(simple.values())
    if key0 not in errs or len(errs[key0]) < 2:
        return {"spec": simple, "selection": "no backtest (short history)", "sigma": [0.08] * H, "inner_cutoffs": len(errs.get(key0, []))}
    full = [k for k, v in errs.items() if len(v) == len(errs[key0])]
    base = np.array(errs[key0])
    best = min(full, key=lambda k: np.mean(errs[k]))
    diff = base - np.array(errs[best])
    se = float(np.std(diff, ddof=1) / math.sqrt(len(diff)))
    rich = float(np.mean(diff)) > se and float(np.mean(diff)) > 0
    spec = dict(zip(SPEC_KEYS, best)) if rich else simple
    E = np.array(logerr[tuple(spec.values())])
    sig = np.maximum.accumulate(np.maximum(np.sqrt(np.mean((E - np.median(E, axis=0)) ** 2, axis=0)), 0.01))
    return {"spec": spec, "selection": "richer specification" if rich else "simplest specification (one-standard-error rule)",
            "inner_error": round(float(np.mean(errs[tuple(spec.values())])), 4), "inner_error_simplest": round(float(base.mean()), 4),
            "sigma": [round(float(x), 4) for x in sig], "inner_cutoffs": len(base)}


_CAL_CACHE: dict[tuple, tuple[TurnoverData, dict[str, Any]]] = {}


def cached_calibration(d: TurnoverData, t0: pd.Timestamp, ind: str, s: dict[str, Any], H: int) -> dict[str, Any]:
    key = (id(d), str(t0.date()), ind, json.dumps(s, sort_keys=True), H)
    hit = _CAL_CACHE.get(key)
    if hit is not None and hit[0] is d:
        return hit[1]
    if len(_CAL_CACHE) > 5000:
        _CAL_CACHE.clear()
    cal = calibrate(d, t0, ind, s, H)
    _CAL_CACHE[key] = (d, cal)
    return cal


# ------------------------------------------------------------------ world

class World(BaseWorld):
    @classmethod
    def from_instance(cls, ctx: InstanceContext, scenario: dict[str, Any], seed: int) -> "World":
        w = scenario.get("world", {})
        t0 = pd.Timestamp(w["t0"])
        H = int(w.get("horizon_months", 6))
        return cls(ctx, scenario, seed, t0.to_pydatetime(), (t0 + H * MONTH).to_pydatetime())

    def __init__(self, ctx: InstanceContext, scenario: dict[str, Any], seed: int, start: datetime, end: datetime) -> None:
        super().__init__(ctx, scenario, seed, start, end)
        t_start = time.time()
        self.rng = np.random.default_rng(seed)
        cfg = scenario.get("world", {})
        par = self.par = ctx.yaml("calibration/turnover.yaml")
        self.t0 = pd.Timestamp(cfg["t0"])
        self.H = int(cfg.get("horizon_months", par.get("horizon_months", 6)))
        self.registry = load_registry(ctx)
        d = self.d = load_data(ctx)
        self.s = {k: par.get(k) for k in ("history_months", "min_history_months", "knot_months", "ridge_trend", "ridge_cal", "inner_cutoffs", "inner_step_months",
                                          "recent_months", "grid")}
        self.M = int(par.get("employees_per_industry", 1000))
        self.hire_mult = 1.0
        for iv in scenario.get("interventions", []) or []:
            if iv.get("type") == "hires_multiplier":
                self.hire_mult *= float(iv.get("multiplier", 1.0))
        self.industries = [i for i in d.meta.index[d.meta.scored] if i in d.q.columns]
        self.months = pd.date_range(self.t0, periods=self.H, freq="MS")
        self.cal, self.paths = {}, {}
        for ind in self.industries:
            cal = cached_calibration(d, self.t0, ind, self.s, self.H)
            sp = cal["spec"]
            hf = fit_monthly(d.h[ind], self.t0, self.s)
            q = d.q[ind][d.q.index < self.t0]
            R = int(self.s["recent_months"])
            hires = d.h[ind][d.h.index < self.t0]
            o = d.o[ind][d.o.index < self.t0]
            o_ref = float(np.nanmean(np.log(o.iloc[-12:])))
            lo_hist = np.log(o.reindex(q.index - MONTH).to_numpy(dtype=float))
            off = np.log1p(sp["gamma"] * recent_share(hires, q.index, R)) + sp["beta"] * np.nan_to_num(lo_hist - o_ref)
            f = fit_monthly(q, self.t0, self.s, off)
            base = forecast_habit(f, self.months, int(sp["level_months"]), float(sp["drift"]), float(sp["phi"]))
            h_f = pd.Series(np.exp(forecast_habit(hf, self.months, 3, 0.0, 1.0)) * self.hire_mult if hf else float(hires.iloc[-12:].mean()), index=self.months)
            o_last = float(np.log(o.iloc[-3:].mean()))
            self.cal[ind] = cal
            # per month: the established employees' quit probability and the recent hires' share (central path)
            self.paths[ind] = {"base": np.exp(base + sp["beta"] * (o_last - o_ref)) / 100, "gamma": float(sp["gamma"]),
                               "hires": h_f.to_numpy() / 100, "hires_before": hires.iloc[-R:].to_numpy() / 100, "recent_months": R,
                               "last_quits_rate": float(q.dropna().iloc[-1]), "employment": float((d.ql[ind] / d.q[ind] * 100)[d.q.index < self.t0].dropna().iloc[-12:].mean())}
            self.agents[f"industry:{ind}"] = Agent(id=f"industry:{ind}", role="industry", org_unit=str(d.meta.loc[ind, "label"]),
                                                   attributes={"employees": self.M, "label": str(d.meta.loc[ind, "label"])}, seat="employee")
        self.calibration_s = time.time() - t_start

    def run(self, writer: RunWriter) -> RunSummary:
        self._writer = writer
        t_run = time.time()
        H = self.H
        pol = self.registry.for_seat("employee")
        out = []
        for ind in self.industries:
            p = self.paths[ind]
            R = p["recent_months"]
            sig = np.array(self.cal[ind]["sigma"][:H])
            walk = np.cumsum(self.rng.normal(0, 1, H)) / np.sqrt(np.arange(1, H + 1)) * sig
            # central path: expected decisions of a population whose recent-hire cohorts follow the hires path
            cohorts_c = list(p["hires_before"])                      # shares of employment hired 1..R months ago (oldest first)
            central = []
            for m in range(H):
                share = float(np.sum(cohorts_c[-R:]))
                central.append(100 * p["base"][m] * (1 + p["gamma"] * share))
                cohorts_c.append(p["hires"][m])
            # stochastic run: employee agents by tenure; each month each one decides whether to quit
            tenure = np.full(self.M, R + 1)
            n_recent = np.round(np.array(p["hires_before"]) * self.M).astype(int)
            pos = 0
            for k, nr in enumerate(n_recent):                       # tenure in months for the recent cohorts
                tenure[pos: pos + nr] = R - k
                pos += nr
            units = []
            for m in range(H):
                prob = p["base"][m] * math.exp(walk[m]) * np.where(tenure <= R, 1 + p["gamma"], 1.0)
                quit_ = np.zeros(self.M, bool)
                for tval in np.unique(tenure):
                    idx = np.flatnonzero(tenure == tval)
                    pr = float(min(prob[idx[0]], 1.0))
                    obs = Observation(agent_id=f"employee:{ind}:t{tval}", role="employee", sim_time=str(self.months[m].date()),
                                      context={"industry": ind, "tenure_months": int(tval)},
                                      options=[{"kind": "quit", "target": "quit", "weight": pr}, {"kind": "stay", "target": "stay", "weight": 1 - pr}])
                    # one decision per employee: the seat draws for each employee of this tenure
                    quit_[idx] = [pol.decide(obs, self.rng).target == "quit" for _ in idx]
                units.append(100 * quit_.mean())
                # quitters are replaced by hires this month; the month's hires join with tenure 0
                tenure = tenure + 1
                n_h = int(round(p["hires"][m] * self.M))
                replace = np.flatnonzero(quit_)
                extra = self.rng.choice(np.flatnonzero(~quit_), size=max(0, n_h - len(replace)), replace=False) if n_h > len(replace) else np.array([], int)
                newcomers = np.concatenate([replace[:n_h], extra]).astype(int)
                tenure[newcomers] = 1
                self.emit(agent_id=f"industry:{ind}", role="industry", org_unit=self.agents[f"industry:{ind}"].org_unit, activity="monthly_quits", action_type="state",
                          provenance="simulated", attributes={"month": str(self.months[m].date()), "quits_rate": units[-1], "quits_rate_central": central[m]})
            out.append({"industry": ind, "label": str(self.d.meta.loc[ind, "label"]), "central": [float(x) for x in central], "units": [float(x) for x in units],
                        "employment_thousands": p["employment"], "last_quits_rate": p["last_quits_rate"],
                        "calibration": self.cal[ind]})
        for _ in range(H * 730):
            if self.clock.done:
                break
            self.clock.advance()
        self.runtime_s = time.time() - t_run
        headline = {"t0": str(self.t0.date()), "horizon_months": H, "months": [str(m.date()) for m in self.months], "hires_multiplier": self.hire_mult, "industries": out}
        return RunSummary(run_id=writer.run_id, instance=self.ctx.id, scenario=self.scenario["id"], seed=self.seed, start=str(self.t0.date()),
                          end=str(self.months[-1].date()), ticks=self.clock.tick, events=self._n_events, headline=headline)


# ------------------------------------------------------------------ evaluation

COMPARATOR_LABELS = {
    "carry_forward": "No change: last month's quits rate carried forward",
    "seasonal_naive": "Same month last year",
    "trend": "Recent trend: the last twelve months' average grown at the 24-month log-linear trend",
    "ets": "Exponential smoothing (ETS): damped trend and monthly seasonality on the log rate, last ten years",
    "arima": "Seasonal ARIMA (0,1,1)(0,1,1)12, the airline model, on the log rate, last ten years",
}


def comparator_forecasts(hist: np.ndarray, H: int) -> dict[str, np.ndarray]:
    """Classical forecasts of a monthly series from its months before the cutoff only (fixed before scoring)."""
    import warnings
    out = {"carry_forward": np.full(H, hist[-1]), "seasonal_naive": np.array([hist[len(hist) - 12 + (h % 12)] for h in range(H)])}
    slope = float(np.polyfit(np.arange(24), np.log(hist[-24:]), 1)[0])
    out["trend"] = hist[-12:].mean() * np.exp(slope * (np.arange(H) + 6.5))
    y = np.log(hist[-120:])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            from statsmodels.tsa.holtwinters import ExponentialSmoothing
            out["ets"] = np.exp(ExponentialSmoothing(y, trend="add", damped_trend=True, seasonal="add", seasonal_periods=12, initialization_method="estimated").fit().forecast(H))
        except Exception:  # noqa: BLE001 -- recorded as missing, never replaced
            out["ets"] = np.full(H, np.nan)
        try:
            from statsmodels.tsa.statespace.sarimax import SARIMAX
            out["arima"] = np.exp(SARIMAX(y, order=(0, 1, 1), seasonal_order=(0, 1, 1, 12)).fit(disp=False).forecast(H))
        except Exception:  # noqa: BLE001
            out["arima"] = np.full(H, np.nan)
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


def summarize(rows: list[dict[str, Any]], who_all: list[str], horizons: list[int]) -> dict[str, Any]:
    comps = [k for k in who_all if k != "simulation"]

    def block(hs: list[int]) -> dict[str, Any]:
        sel = [{"actual": [r["actual"][h - 1] for h in hs], "predictions": {k: [r["predictions"][k][h - 1] for h in hs] for k in who_all}} for r in rows]
        v = {k: pooled(sel, k) for k in who_all}
        ok = [k for k in comps if v[k] is not None]
        best = min(ok, key=lambda k: v[k]["wape"]) if ok else None
        return {**v, "best_baseline": best, "error_reduction_pct": (1 - v["simulation"]["wape"] / v[best]["wape"]) * 100 if best else None}
    out = {"headline_horizons": block(horizons), "by_horizon": {str(h): block([h]) for h in range(1, len(rows[0]["actual"]) + 1)} if rows else {}}
    cov = [c for r in rows for h in horizons for c in [r["covered90"][h - 1]]]
    out["coverage90"] = 100 * float(np.mean(cov)) if cov else None
    out["n_predictions"] = len(rows) * len(horizons)
    out["n_windows"] = len({r["cutoff"] for r in rows})
    out["span"] = [min(r["cutoff"] for r in rows), max(r["cutoff"] for r in rows)] if rows else None
    return out


def evaluate(ctx: InstanceContext, scenario_ids: list[str], phase: str = "all") -> dict[str, Any]:
    """Score the simulation and the classical forecasts at every protocol cutoff (phase "dev": development cutoffs only)."""
    from ..scenarios import load_scenario
    proto = ctx.yaml("evaluation/protocol.yaml")
    d = load_data(ctx)
    H = int(proto.get("horizon_months", 6))
    horizons = [int(h) for h in proto.get("headline_horizons", [3, 6])]
    seeds = [int(s) for s in proto.get("seeds", [1, 2, 3])]
    all_cutoffs = [pd.Timestamp(c) for c in proto["cutoffs"]]
    n_dev = int(proto["dev_cutoffs"])
    cutoffs = all_cutoffs[:n_dev] if phase == "dev" else all_cutoffs
    base_id = proto.get("baseline_scenario", "baseline")
    alt_id = ctx.meta.get("scenarios", {}).get("alternative")
    base = load_scenario(ctx, base_id)
    who_all = ["simulation", *COMPARATOR_LABELS]
    rows, run_ids, windows = [], {base_id: []}, []
    for c in cutoffs:
        sims = [_run_world(ctx, base, sd, str(c.date())) for sd in seeds]
        run_ids[base_id] += [s.run_id for s in sims]
        by = [{x["industry"]: x for x in s.headline["industries"]} for s in sims]
        months = pd.date_range(c, periods=H, freq="MS")
        ph = "dev" if c in all_cutoffs[:n_dev] else "held_out"
        tot = {"actual": np.zeros(H), **{k: np.zeros(H) for k in who_all}}
        for ind in by[0]:
            act = d.q[ind].reindex(months).to_numpy(dtype=float)
            if np.isnan(act).any():
                continue
            hist = d.q[ind][d.q.index < c].dropna().to_numpy(dtype=float)
            comp = comparator_forecasts(hist, H)
            runs = np.array([b[ind]["units"] for b in by])
            lo, hi = np.percentile(runs, 5, axis=0), np.percentile(runs, 95, axis=0)
            preds = {"simulation": np.array(by[0][ind]["central"]), **comp}
            rows.append({"cutoff": str(c.date()), "phase": ph, "industry": ind, "label": by[0][ind]["label"], "actual": act.tolist(),
                         "predictions": {k: v.tolist() for k, v in preds.items()}, "interval": [lo.tolist(), hi.tolist()],
                         "covered90": [bool(x) for x in (act >= lo) & (act <= hi)], "employment_thousands": by[0][ind]["employment_thousands"]})
            emp = by[0][ind]["employment_thousands"]                       # employment known before the cutoff
            ql = d.ql[ind].reindex(months).to_numpy(dtype=float)
            tot["actual"] += np.nan_to_num(ql)
            for k, v in preds.items():
                tot[k] += v * emp / 100
        windows.append({"cutoff": str(c.date()), "phase": ph, "months": [str(m.date()) for m in months], "run_ids": [s.run_id for s in sims],
                        "quits_thousands": {k: v.tolist() for k, v in tot.items()}})
    if alt_id and alt_id in scenario_ids:
        alt = load_scenario(ctx, alt_id)
        run_ids[alt_id] = []
        for c in [pd.Timestamp(x) for x in proto.get("alternative_cutoffs", [])]:
            if c in cutoffs:
                for sd in seeds:
                    run_ids[alt_id].append(_run_world(ctx, alt, sd, str(c.date())).run_id)
    held = [r for r in rows if r["phase"] == "held_out"]
    accuracy = {"held_out": summarize(held, who_all, horizons) if held else None, "dev": summarize([r for r in rows if r["phase"] == "dev"], who_all, horizons),
                "all_cutoffs": summarize(rows, who_all, horizons)}
    for name, (a, b) in (proto.get("periods") or {}).items():
        sel = [r for r in held if a <= r["cutoff"] <= b]
        if sel:
            accuracy[f"period_{name}"] = summarize(sel, who_all, horizons)
    accuracy["by_industry"] = {ind: summarize([r for r in held or rows if r["industry"] == ind], who_all, horizons) for ind in sorted({r["industry"] for r in rows})}

    def bv() -> dict[str, Any]:
        sc = [w for w in windows if w["phase"] == "held_out"] or windows
        hz = [h - 1 for h in horizons]
        mae = {k: float(np.mean([abs(w["quits_thousands"][k][h] - w["quits_thousands"]["actual"][h]) for w in sc for h in hz])) for k in who_all}
        comps = [k for k in COMPARATOR_LABELS if np.isfinite(mae[k])]
        best = min(comps, key=mae.get)
        return {"id": "quits_thousands", "label": f"Quits in the {len({r['industry'] for r in rows})} industries, one month, {' and '.join(map(str, horizons))} months ahead (thousands)",
                "scope": sc[0]["phase"], "simulation_mae": mae["simulation"], "baseline_mae": {k: mae[k] for k in comps}, "best_baseline": best,
                "beats_best_baseline": mae["simulation"] < mae[best], "error_reduction_pct": (1 - mae["simulation"] / mae[best]) * 100,
                "mean_actual": float(np.mean([w["quits_thousands"]["actual"][h] for w in sc for h in hz])),
                "windows": [{"cutoff": w["cutoff"], "phase": w["phase"], "actual": [w["quits_thousands"]["actual"][h] for h in hz], "simulated": [w["quits_thousands"]["simulation"][h] for h in hz],
                             "baselines": {k: [w["quits_thousands"][k][h] for h in hz] for k in comps}} for w in windows]}
    scope = "held_out" if accuracy["held_out"] else "dev"
    A = accuracy[scope]["headline_horizons"]
    best = A["best_baseline"]
    out = {"instance": ctx.id, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "scenarios": scenario_ids, "phase": phase,
           "protocol": {"cutoffs": [str(c.date()) for c in cutoffs], "dev_cutoffs": proto["cutoffs"][:n_dev], "horizon_months": H, "headline_horizons": horizons,
                        "seeds": seeds, "runs": len(cutoffs) * len(seeds), "headline_scope": scope, "periods": proto.get("periods"),
                        "point": "central path (expected decisions, every shock at its median)", "interval": "5th-95th percentile across runs"},
           "run_ids": run_ids, "rows": rows, "windows": windows, "accuracy": accuracy, "comparator_labels": COMPARATOR_LABELS, "business_validation": [bv()]}
    out["headline"] = {
        "quits_rate_wape": {"label": f"Error in each industry's quits rate {' and '.join(map(str, horizons))} months ahead ({scope.replace('_', '-')} cutoffs, % of actual)",
                            "simulated": A["simulation"]["wape"], "baseline": A[best]["wape"], "best_baseline": best, "unit": "%", "better": "lower"},
        "quits_rate_mae": {"label": "Mean absolute error in the quits rate (percentage points)", "simulated": A["simulation"]["mae"], "baseline": A[best]["mae"], "unit": "pp", "better": "lower"},
        "coverage90": {"label": "Predictions whose actual fell inside the simulation's 90% range", "simulated": accuracy[scope]["coverage90"], "unit": "%", "better": "higher"},
    }
    ctx.runs_dir.mkdir(parents=True, exist_ok=True)
    (ctx.runs_dir / "evaluation.json").write_text(json.dumps(out, indent=1, default=_json_default))
    return out
