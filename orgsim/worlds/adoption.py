"""Adoption world: populations of agents (firms, developers, askers) in groups (sectors, roles) taking up a technology.

Each group holds N agents. Every period the kernel offers each agent that does not use the technology the option to
start and each agent that uses it the option to stop, with hazards set so that the group's expected share of users
follows a diffusion path; the seat policy (rule by default) makes the choice. The path has two hazard forms:

  imitation   the log-odds of use grows by a rate g each period (logistic diffusion: adopters recruit adopters, and
              growth saturates as the pool of non-users empties; Bass diffusion with imitation only)
  external    the log of the non-user share falls by g each period (a constant hazard on the remaining non-users;
              Bass diffusion with external influence only)

The growth rate g blends the group's own recent growth with the whole population's (imitation across groups, weight
w), is scaled by a drift weight, and decays by a factor phi each period (damping). The starting level averages the
last k periods, which smooths sampling noise in survey estimates.

Two outcome kinds (calibration/adoption.yaml `outcome`):

  share      the outcome is the share of agents using (BTOS: the share of firms that used AI in the last two weeks)
  displaced  the outcome is a volume the adoption displaces: baseline volume x (1 - share), the baseline being a trend
             with seasonality fitted on periods before the change (Stack Overflow questions not asked because the
             asker used an AI assistant instead)

Calibration at each cutoff uses periods before it only: inner backtests at earlier cutoffs whose targets also fall
before it score every specification in the grid (starting window k, drift weight, pooling weight w, damping phi,
hazard form), and the one-standard-error rule keeps the instance's default diffusion specification unless another
is better by more than one standard error of the difference across backtests. The ranges come from the
same backtests' errors by horizon. Outcomes after the cutoff are read only by evaluate() for scoring.
"""
from __future__ import annotations

import itertools
import json
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from ..evaluation.results import base_document, run_docs
from ..instances import InstanceContext
from ..kernel.world import Agent, BaseWorld, RunSummary
from ..policies.base import Observation
from ..policies.registry import load_registry
from ..store.runs import RunWriter

EPS = 1e-3


# ------------------------------------------------------------------ data

@dataclass
class AdoptionData:
    series: pd.DataFrame     # group, period (consecutive int), date, value, se
    groups: pd.DataFrame     # group, label, scored, ... (instance-specific columns)

    def matrix(self, groups: list[str], periods: list[int]) -> np.ndarray:
        """value[group, period]; NaN where a period is missing or suppressed."""
        m = self.series.pivot_table(index="group", columns="period", values="value", aggfunc="first")
        return m.reindex(index=groups, columns=periods).to_numpy(dtype=float)

    def dates(self) -> pd.Series:
        return self.series.drop_duplicates("period").set_index("period").date.sort_index()


@lru_cache(maxsize=4)
def _load(root: str, mtime: float) -> AdoptionData:
    n = Path(root)
    s = pd.read_parquet(n / "series.parquet")
    s["date"] = pd.to_datetime(s.date)
    return AdoptionData(s.sort_values(["group", "period"]).reset_index(drop=True), pd.read_parquet(n / "groups.parquet"))


def load_data(ctx: InstanceContext) -> AdoptionData:
    p = ctx.data_normalized / "series.parquet"
    if not p.exists():
        raise FileNotFoundError(f"{p} missing; run `orgsim ingest {ctx.id}`")
    return _load(str(ctx.data_normalized), p.stat().st_mtime)


def truncate(d: AdoptionData, cutoff: int) -> AdoptionData:
    """The data a prediction at `cutoff` may see: every period before it."""
    return AdoptionData(d.series[d.series.period < cutoff].copy(), d.groups)


# ------------------------------------------------------------------ transforms

def to_z(a: np.ndarray, form: str) -> np.ndarray:
    a = np.clip(a, EPS, 1 - EPS)
    return np.log(a / (1 - a)) if form == "imitation" else np.log(1 - a)


def from_z(z: np.ndarray, form: str) -> np.ndarray:
    return 1 / (1 + np.exp(-z)) if form == "imitation" else 1 - np.exp(np.minimum(z, 0.0))


def nan_slope(y: np.ndarray, window: int) -> np.ndarray:
    """OLS slope per row over the last `window` columns, ignoring missing values (0 when fewer than 3 points)."""
    y = y[:, -window:]
    t = np.arange(y.shape[1], dtype=float)
    out = np.zeros(y.shape[0])
    for i, row in enumerate(y):
        ok = np.isfinite(row)
        if ok.sum() >= 3:
            tt = t[ok] - t[ok].mean()
            out[i] = float((tt * (row[ok] - row[ok].mean())).sum() / (tt ** 2).sum())
    return out


def nan_level(z: np.ndarray, k: int, slope: np.ndarray) -> np.ndarray:
    """Starting level at the last period: the mean of the last k observed values, moved forward by the slope to the
    last period (the mean of k values sits (k - 1) / 2 periods back)."""
    out = np.empty(z.shape[0])
    for i, row in enumerate(z):
        obs = np.flatnonzero(np.isfinite(row))
        if not len(obs):
            out[i] = np.nan
            continue
        last = obs[-k:]
        out[i] = float(row[last].mean() + slope[i] * (z.shape[1] - 1 - last.mean()))
    return out


# ------------------------------------------------------------------ baseline volume (displaced outcomes)

def fourier(t: np.ndarray, season: int, K: int) -> np.ndarray:
    cols = [np.ones_like(t, dtype=float), t / season]
    for k in range(1, K + 1):
        cols += [np.sin(2 * np.pi * k * t / season), np.cos(2 * np.pi * k * t / season)]
    return np.column_stack(cols)


def fit_baseline(v: np.ndarray, periods: np.ndarray, change: int, season: int, K: int, window: int) -> np.ndarray:
    """Log-linear trend with K Fourier seasonal terms, fitted on the `window` periods before the change; returns
    coefficients. Nothing at or after the change enters the fit."""
    m = (periods < change) & (periods >= change - window) & np.isfinite(v) & (v > 0)
    X = fourier(periods[m].astype(float), season, K)
    coef, *_ = np.linalg.lstsq(X, np.log(v[m]), rcond=None)
    return coef


def baseline_at(coef: np.ndarray, periods: np.ndarray, season: int, K: int) -> np.ndarray:
    return np.exp(fourier(np.asarray(periods, dtype=float), season, K) @ coef)


# ------------------------------------------------------------------ the observed adoption share

class View:
    """Everything a prediction at cutoff c may use, on the adoption-share scale: A[group, period] for periods < c."""

    def __init__(self, d: AdoptionData, cfg: dict[str, Any], groups: list[str], cutoff: int) -> None:
        self.cfg, self.groups, self.cutoff = cfg, groups, cutoff
        per = sorted(p for p in d.series.period.unique() if p < cutoff)
        self.periods = np.array(per, dtype=int)
        V = d.matrix(groups, per)
        self.value = V
        self.outcome = cfg.get("outcome", "share")
        agg = cfg.get("aggregate_group")
        self.pool = d.matrix([agg], per)[0] if agg and agg in set(d.series.group) else None
        if self.outcome == "displaced":
            ch = cfg["change"]
            self.change = int(ch["period"])
            self.season, self.K = int(ch.get("season_periods", 52)), int(ch.get("fourier", 3))
            self.coef = [fit_baseline(V[i], self.periods, self.change, self.season, self.K, int(ch.get("baseline_periods", 104))) for i in range(len(groups))]
            B = np.array([baseline_at(c_, self.periods, self.season, self.K) for c_ in self.coef])
            A = 1 - V / B
            A[:, self.periods < self.change] = np.nan          # no adoption is read from before the change
            self.A = A
            self.start = self.change
            if self.pool is not None:
                pc = fit_baseline(self.pool, self.periods, self.change, self.season, self.K, int(ch.get("baseline_periods", 104)))
                pa = 1 - self.pool / baseline_at(pc, self.periods, self.season, self.K)
                pa[self.periods < self.change] = np.nan
                self.pool = pa
        else:
            self.A = V
            self.start = int(self.periods[0]) if len(self.periods) else cutoff
        self.n_adopt = int(np.sum(self.periods >= self.start))

    def baseline(self, periods: np.ndarray) -> np.ndarray | None:
        if self.outcome != "displaced":
            return None
        return np.array([baseline_at(c_, periods, self.season, self.K) for c_ in self.coef])

    def outcome_from_share(self, A: np.ndarray, periods: np.ndarray) -> np.ndarray:
        """groups x horizons on the outcome scale."""
        if self.outcome == "displaced":
            return self.baseline(periods) * (1 - A)
        return A


# ------------------------------------------------------------------ diffusion paths

SPEC_KEYS = ("k_level", "drift", "w", "phi", "form")


def spec_list(grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    return [dict(zip(SPEC_KEYS, v)) for v in itertools.product(grid.get("k_level", [1, 2, 4]), grid.get("drift", [0.0, 0.5, 1.0]), grid.get("w", [0.0, 0.5, 1.0]),
                                                               grid.get("phi", [1.0, 0.9]), grid.get("form", ["imitation", "external"]))]


def central_share(A: np.ndarray, pool: np.ndarray | None, H: int, spec: dict[str, Any], slope_periods: int) -> np.ndarray:
    """Expected share per group for horizons 1..H after the last column of A (groups x periods)."""
    form = spec["form"]
    if A.shape[1] == 0:
        A = np.full((A.shape[0], 1), np.nan)
    z = np.where(np.isfinite(A), to_z(np.nan_to_num(A, nan=0.5), form), np.nan)
    own = nan_slope(z, slope_periods)
    if pool is not None and np.isfinite(pool).sum() >= 3:
        pz = np.where(np.isfinite(pool), to_z(np.nan_to_num(pool, nan=0.5), form), np.nan)
        pooled = float(nan_slope(pz[None, :], slope_periods)[0])
    else:
        pooled = float(np.median(own)) if len(own) else 0.0
    g = spec["drift"] * (spec["w"] * own + (1 - spec["w"]) * pooled)
    lvl = nan_level(z, int(spec["k_level"]), g if spec["drift"] > 0 else np.zeros_like(g))
    lvl = np.where(np.isfinite(lvl), lvl, float(to_z(np.array([EPS]), form)[0]))   # no adoption observed yet: none
    out = np.empty((A.shape[0], H))
    cum = np.zeros(A.shape[0])
    for h in range(H):
        g = spec["phi"] * g
        cum = cum + g
        out[:, h] = from_z(lvl + cum, form)
    return out


def _fold_errors(v: View, c: int, H: int, specs: list[dict[str, Any]], slope_periods: int, d: AdoptionData, groups: list[str]) -> list[dict[str, Any]]:
    """One inner backtest at cutoff c (a View truncated at c): each specification's outcome predictions for the horizons
    whose target periods fall before the outer cutoff, against what happened."""
    hs = np.array([h for h in range(1, H + 1) if c - 1 + h < v.cutoff])
    if not len(hs):
        return []
    sub = View(d, v.cfg, groups, c)
    if sub.n_adopt < int(v.cfg.get("min_history", 6)):
        return []
    tgt_p = np.array([c - 1 + h for h in hs])
    pos = np.searchsorted(v.periods, tgt_p)
    actual = v.value[:, pos]
    A_hist = sub.A[:, sub.periods >= sub.start]
    pool = sub.pool[sub.periods >= sub.start] if sub.pool is not None else None
    out = []
    for sp in specs:
        Ac = central_share(A_hist, pool, int(hs.max()), sp, slope_periods)[:, hs - 1]
        pred = sub.outcome_from_share(Ac, tgt_p)
        out.append({"pred": pred, "actual": actual, "hs": hs, "z_pred": to_z(Ac, sp["form"]),
                    "z_act": to_z(np.clip(1 - actual / sub.baseline(tgt_p), EPS, 1 - EPS), sp["form"]) if v.outcome == "displaced" else to_z(actual, sp["form"])})
    return out


def error_of(pred: np.ndarray, actual: np.ndarray, outcome: str) -> float:
    """Mean absolute error over groups and horizons; displaced volumes are scored relative to the actual volume."""
    ok = np.isfinite(actual) & np.isfinite(pred)
    if not ok.any():
        return float("nan")
    if outcome == "displaced":
        return float(np.mean(np.abs(pred[ok] - actual[ok]) / actual[ok]))
    return float(np.mean(np.abs(pred[ok] - actual[ok])))


def fit_dynamics(d: AdoptionData, cfg: dict[str, Any], groups: list[str], cutoff: int, H: int) -> dict[str, Any]:
    """Choose the diffusion specification at `cutoff` from inner backtests that end before it (one-standard-error rule)
    and measure the range width by horizon from the same backtests."""
    grid = cfg.get("grid", {})
    simple = dict(cfg.get("default_spec", {"k_level": 4, "drift": 0.0, "w": 0.0, "phi": 1.0, "form": "imitation"}))
    specs = spec_list(grid)
    key = lambda sp: tuple(sp[k] for k in SPEC_KEYS)  # noqa: E731
    if key(simple) not in {key(s) for s in specs}:
        specs.append(simple)
    slope_periods = int(cfg.get("slope_periods", 0))
    v = View(d, cfg, groups, cutoff)
    step, inner = int(cfg.get("inner_step", 1)), int(cfg.get("inner_cutoffs", 8))
    folds = []
    for j in range(inner):
        c = cutoff - step * (j + 1)
        if c <= v.start:
            break
        f = _fold_errors(v, c, H, specs, slope_periods, d, groups)
        if f:
            folds.append(f)
    outcome = v.outcome
    if len(folds) < 2:
        return {"spec": simple, "selection": "default specification (fewer than two backtests)", "inner_cutoffs": len(folds),
                "sigma": [float(cfg.get("default_sigma", 0.3)) * math.sqrt(h) for h in range(1, H + 1)], "inner_error": None}
    E = np.array([[error_of(f[i]["pred"], f[i]["actual"], outcome) for i in range(len(specs))] for f in folds])   # folds x specs
    mean = np.nanmean(E, axis=0)
    best = int(np.nanargmin(mean))
    si = next(i for i, s in enumerate(specs) if key(s) == key(simple))
    diff = E[:, si] - E[:, best]
    diff = diff[np.isfinite(diff)]
    se = float(np.std(diff, ddof=1) / math.sqrt(len(diff))) if len(diff) > 1 else float("inf")
    rich = float(np.mean(diff)) > se and float(np.mean(diff)) > 0
    chosen = specs[best] if rich else simple
    ci = best if rich else si
    # range width: spread of log-odds (or log non-user share) errors at each horizon, from the chosen specification
    by_h: dict[int, list[float]] = {}
    for f in folds:
        r = f[ci]
        res = r["z_act"] - r["z_pred"]
        for j, h in enumerate(r["hs"]):
            by_h.setdefault(int(h), []).extend([x for x in res[:, j] if np.isfinite(x)])
    sig = []
    for h in range(1, H + 1):
        xs = np.array(by_h.get(h, []))
        if len(xs) >= 5:
            sig.append(float(1.4826 * np.median(np.abs(xs - np.median(xs)))))
        elif sig:
            sig.append(sig[-1] * math.sqrt(h / (h - 1)))
        else:
            sig.append(float(cfg.get("default_sigma", 0.3)))
    sig = np.maximum.accumulate(np.array(sig)).tolist()
    return {"spec": {k: (float(chosen[k]) if k != "form" else chosen[k]) for k in SPEC_KEYS}, "selection": "other specification" if rich else "default specification (one-standard-error rule)",
            "inner_cutoffs": len(folds), "inner_error": {"chosen": float(mean[ci]), "default": float(mean[si]), "best": float(mean[best]), "se_diff": se},
            "sigma": [round(s, 4) for s in sig]}


@lru_cache(maxsize=64)
def _cached_dynamics(root: str, mtime: float, cfg: str, groups: str, cutoff: int, H: int) -> dict[str, Any]:
    """Calibration depends only on periods before the cutoff and the settings, so every seed at a cutoff shares it."""
    return fit_dynamics(_load(root, mtime), json.loads(cfg), json.loads(groups), cutoff, H)


# ------------------------------------------------------------------ world

def model_groups(d: AdoptionData, cfg: dict[str, Any]) -> list[str]:
    g = d.groups
    return g[g.modelled.astype(bool)].group.astype(str).tolist() if "modelled" in g else g.group.astype(str).tolist()


class World(BaseWorld):
    @classmethod
    def from_instance(cls, ctx: InstanceContext, scenario: dict[str, Any], seed: int) -> "World":
        w = scenario.get("world", {})
        d = load_data(ctx)
        dates = d.dates()
        t0 = int(w["cutoff"])
        H = int(w.get("horizon_periods", 13))
        start = dates.get(t0, dates.iloc[-1])
        step = pd.Timedelta(days=int(ctx.yaml("calibration/adoption.yaml").get("period_days", 7)))
        return cls(ctx, scenario, seed, pd.Timestamp(start).to_pydatetime(), (pd.Timestamp(start) + H * step).to_pydatetime())

    def __init__(self, ctx: InstanceContext, scenario: dict[str, Any], seed: int, start: datetime, end: datetime) -> None:
        super().__init__(ctx, scenario, seed, start, end)
        t_start = time.time()
        self.rng = np.random.default_rng(seed)
        w = scenario.get("world", {})
        self.cfg = ctx.yaml("calibration/adoption.yaml")
        self.t0 = int(w["cutoff"])
        self.H = int(w.get("horizon_periods", 13))
        self.N = int(self.cfg.get("agents_per_group", 1000))
        self.registry = load_registry(ctx)
        self.d = d = load_data(ctx)
        self.groups = model_groups(d, self.cfg)
        self.view = View(d, self.cfg, self.groups, self.t0)
        p = ctx.data_normalized / "series.parquet"
        self.dyn = _cached_dynamics(str(ctx.data_normalized), p.stat().st_mtime, json.dumps(self.cfg, sort_keys=True, default=str), json.dumps(self.groups), self.t0, self.H)
        v = self.view
        A_hist = v.A[:, v.periods >= v.start]
        pool = v.pool[v.periods >= v.start] if v.pool is not None else None
        self.central_A = central_share(A_hist, pool, self.H, self.dyn["spec"], int(self.cfg.get("slope_periods", 0)))
        self.target_periods = np.arange(self.t0, self.t0 + self.H)
        self.interventions = scenario.get("interventions", []) or []
        # an intervention scales the adoption hazard of non-users in some groups from the cutoff (alternative scenarios)
        self.hazard_mult = np.ones(len(self.groups))
        for iv in self.interventions:
            if iv.get("type") == "adoption_hazard_multiplier":
                sel = iv.get("groups") or self.groups
                for i, g in enumerate(self.groups):
                    if g in sel:
                        self.hazard_mult[i] *= float(iv.get("multiplier", 1.0))
        labels = d.groups.set_index("group").label.to_dict() if "label" in d.groups else {}
        self.labels = {g: str(labels.get(g, g)) for g in self.groups}
        for g in self.groups:
            self.agents[f"group:{g}"] = Agent(id=f"group:{g}", role="group", org_unit=str(g), attributes={"label": self.labels[g], "agents": self.N}, seat="adopter")
        self.calibration_s = time.time() - t_start

    def _altered(self, A: np.ndarray, A0: np.ndarray) -> np.ndarray:
        """Shares when the non-users' adoption hazard is scaled: each period's gain over the last period is scaled."""
        if np.all(self.hazard_mult == 1.0):
            return A
        out = np.empty_like(A)
        prev_c, prev_a = A0.copy(), A0.copy()
        for h in range(A.shape[1]):
            gain = A[:, h] - prev_c
            hz = np.where(gain > 0, gain / np.maximum(1 - prev_c, 1e-9), 0.0)
            loss = np.where(gain < 0, -gain / np.maximum(prev_c, 1e-9), 0.0)
            hz = np.clip(hz * self.hazard_mult, 0, 1)
            nxt = prev_a + hz * (1 - prev_a) - loss * prev_a
            out[:, h] = nxt
            prev_c, prev_a = A[:, h], nxt
        return out

    def run(self, writer: RunWriter) -> RunSummary:
        self._writer = writer
        t_run = time.time()
        H, G, N = self.H, len(self.groups), self.N
        form = self.dyn["spec"]["form"]
        v = self.view
        A0 = np.array([row[np.isfinite(row)][-1] if np.isfinite(row).any() else EPS for row in v.A])
        # Central path: every shock at its median; it is the point prediction. Stochastic path: shocks drawn so that the
        # spread at each horizon matches the backtests' errors.
        central = self._altered(self.central_A, A0)
        sig = np.array(self.dyn["sigma"][:H])
        inc = np.sqrt(np.maximum(np.diff(np.concatenate([[0.0], sig ** 2])), 1e-8))
        common = self.rng.normal(0, 1, H)
        own = self.rng.normal(0, 1, (G, H))
        rho = float(self.cfg.get("shock_common_share", 0.5))
        shock = np.cumsum(inc[None, :] * (math.sqrt(rho) * common[None, :] + math.sqrt(1 - rho) * own), axis=1)
        target = from_z(to_z(self.central_A, form) + shock, form)
        target = self._altered(target, A0)
        # Agents: each group's N agents start from the last observed share; each period the kernel offers non-users
        # "start" and users "stop" with the hazards that move the expected share to the path; the seat chooses.
        pol = self.registry.for_seat("adopter")
        using = self.rng.random((G, N)) < A0[:, None]
        shares = np.zeros((G, H))
        for h in range(H):
            for i in range(G):
                cur = using[i].mean()
                tgt = target[i, h]
                p_start = max(tgt - cur, 0.0) / max(1 - cur, 1e-9)
                p_stop = max(cur - tgt, 0.0) / max(cur, 1e-9)
                idx_non, idx_use = np.flatnonzero(~using[i]), np.flatnonzero(using[i])
                if pol.name == "rule":           # the rule draws from the offered weights; vectorised, same draws per agent
                    start_now = idx_non[self.rng.random(len(idx_non)) < p_start]
                    stop_now = idx_use[self.rng.random(len(idx_use)) < p_stop]
                else:
                    start_now = [j for j in idx_non if pol.decide(self._obs(i, j, h, "start", p_start), self.rng).target == "start"]
                    stop_now = [j for j in idx_use if pol.decide(self._obs(i, j, h, "stop", p_stop), self.rng).target == "stop"]
                using[i, start_now] = True
                using[i, stop_now] = False
                shares[i, h] = using[i].mean()
                self.emit(agent_id=f"group:{self.groups[i]}", role="group", org_unit=str(self.groups[i]), activity="adoption", action_type="state", provenance="simulated",
                          attributes={"period": int(self.t0 + h), "share": round(float(shares[i, h]), 5), "started": int(len(start_now)), "stopped": int(len(stop_now))})
            for _ in range(int(self.cfg.get("period_days", 7)) * 24):
                if self.clock.done:
                    break
                self.clock.advance()
        self.runtime_s = time.time() - t_run
        out_c = v.outcome_from_share(central, self.target_periods)
        out_r = v.outcome_from_share(shares, self.target_periods)
        dates = self.d.dates()
        headline = {
            "cutoff": int(self.t0), "cutoff_date": str(pd.Timestamp(dates.get(self.t0, dates.iloc[-1])).date()) if len(dates) else None, "horizon_periods": H,
            "outcome": v.outcome, "agents_per_group": N,
            "groups": [{"group": g, "label": self.labels[g], "start_share": float(A0[i]), "central": [float(x) for x in out_c[i]], "run": [float(x) for x in out_r[i]],
                        "central_share": [float(x) for x in central[i]], "run_share": [float(x) for x in shares[i]]} for i, g in enumerate(self.groups)],
            "calibration": self.dyn, "hazard_multipliers": {g: float(m) for g, m in zip(self.groups, self.hazard_mult) if m != 1.0},
            "baseline_volume": v.baseline(self.target_periods).tolist() if v.outcome == "displaced" else None,
        }
        return RunSummary(run_id=writer.run_id, instance=self.ctx.id, scenario=self.scenario["id"], seed=self.seed, start=str(self.clock.start.date()),
                          end=str(self.clock.end.date()), ticks=self.clock.tick, events=self._n_events, headline=headline)

    def _obs(self, i: int, j: int, h: int, kind: str, p: float) -> Observation:
        return Observation(agent_id=f"adopter:{self.groups[i]}:{j}", role="adopter", sim_time=str(self.t0 + h),
                           context={"group": self.labels[self.groups[i]]},
                           options=[{"kind": "adoption", "target": kind, "weight": p}, {"kind": "adoption", "target": "stay", "weight": 1 - p}])


# ------------------------------------------------------------------ comparators (fixed before scoring)

def _bass_F(t: np.ndarray, p: float, q: float) -> np.ndarray:
    e = np.exp(-(p + q) * t)
    return (1 - e) / (1 + (q / p) * e)


def fit_bass(y: np.ndarray) -> tuple[float, float, float, float] | None:
    """Bass diffusion S(t) = m F(t + tau) by least squares over the observed periods, several starts; m <= 1."""
    t = np.arange(len(y), dtype=float)
    ok = np.isfinite(y)
    if ok.sum() < 5:
        return None
    t, y = t[ok], y[ok]
    best = None
    for p0, q0, tau0 in itertools.product([0.002, 0.01], [0.05, 0.2, 0.5], [5.0, 30.0]):
        m0 = min(0.99, max(1.5 * y.max(), 0.05))
        def res(x):
            m, p, q, tau = x
            return m * _bass_F(t + tau, p, q) - y
        try:
            r = least_squares(res, [m0, p0, q0, tau0], bounds=([max(y.max(), 1e-3), 1e-5, 0.0, 0.0], [1.0, 0.5, 2.0, 500.0]), max_nfev=400)
        except ValueError:
            continue
        if best is None or r.cost < best.cost:
            best = r
    return tuple(best.x) if best is not None else None


def holt_damped(y: np.ndarray, H: int) -> np.ndarray:
    """Damped-trend exponential smoothing (ETS A,Ad,N) with smoothing parameters chosen by one-step squared error."""
    y = y[np.isfinite(y)]
    if len(y) < 4:
        return np.repeat(y[-1] if len(y) else np.nan, H)
    best = None
    for a, b, ph in itertools.product([0.1, 0.2, 0.3, 0.5, 0.7, 0.9], [0.01, 0.05, 0.1, 0.2, 0.3], [0.8, 0.9, 0.95, 0.98]):
        lv, tr, sse = y[0], y[1] - y[0], 0.0
        for x in y[1:]:
            f = lv + ph * tr
            sse += (x - f) ** 2
            nl = a * x + (1 - a) * f
            tr = b * (nl - lv) + (1 - b) * ph * tr
            lv = nl
        if best is None or sse < best[0]:
            best = (sse, lv, tr, ph)
    _, lv, tr, ph = best
    return np.array([lv + tr * sum(ph ** i for i in range(1, h + 1)) for h in range(1, H + 1)])


COMPARATOR_LABELS = {
    "carry_forward": "No change: the last observed value carried forward",
    "recent_average": "Recent average: the mean of the last few periods carried forward",
    "linear_trend": "Linear trend: a straight line fitted to every period before the cutoff, extended",
    "holt_damped": "Damped trend: exponential smoothing with a damped trend (ETS)",
    "bass_diffusion": "Bass diffusion: the standard adoption curve fitted to every period before the cutoff",
    "seasonal_naive": "Same period last year",
}


def comparators(v: View, H: int, which: list[str], recent: int, season: int | None, trend_periods: int | None = None) -> dict[str, np.ndarray]:
    """Non-simulation predictions (groups x horizons, outcome scale) from the same periods before the cutoff. The
    linear trend uses the last `trend_periods` periods (None: every period)."""
    Y = v.value
    tgt = np.arange(v.cutoff, v.cutoff + H)
    hs = np.arange(1, H + 1, dtype=float)
    out: dict[str, np.ndarray] = {}
    hist = Y[:, v.periods >= (v.start if v.outcome == "share" else v.periods[0])]
    bound = (lambda x: np.clip(x, 0.0, 1.0)) if v.outcome == "share" else (lambda x: np.maximum(x, 0.0))  # noqa: E731
    for k in which:
        P = np.full((Y.shape[0], H), np.nan)
        for i, row in enumerate(Y):
            obs = row[np.isfinite(row)]
            if not len(obs):
                continue
            if k == "carry_forward":
                P[i] = obs[-1]
            elif k == "recent_average":
                P[i] = obs[-recent:].mean()
            elif k == "linear_trend":
                r = hist[i] if not trend_periods else row[-int(trend_periods):]
                t = np.arange(len(r), dtype=float)
                ok = np.isfinite(r)
                b1, b0 = np.polyfit(t[ok], r[ok], 1)
                P[i] = bound(b0 + b1 * (len(r) - 1 + hs))
            elif k == "holt_damped":
                P[i] = bound(holt_damped(row, H))
            elif k == "bass_diffusion":
                if v.outcome == "displaced":
                    a = v.A[i, v.periods >= v.start]
                    fit = fit_bass(a)
                    if fit is None:
                        P[i] = obs[-1]
                    else:
                        m, p, q, tau = fit
                        A = m * _bass_F(len(a) - 1 + hs + tau, p, q)
                        P[i] = v.baseline(tgt)[i] * (1 - A)
                else:
                    fit = fit_bass(hist[i])
                    if fit is None:
                        P[i] = obs[-1]
                    else:
                        m, p, q, tau = fit
                        P[i] = m * _bass_F(hist.shape[1] - 1 + hs + tau, p, q)
            elif k == "seasonal_naive" and season:
                pos = {p: j for j, p in enumerate(v.periods)}
                P[i] = [row[pos[t - season]] if (t - season) in pos else obs[-1] for t in tgt]
        out[k] = P
    return out


# ------------------------------------------------------------------ evaluation

def _run_world(ctx: InstanceContext, scenario: dict[str, Any], seed: int, cutoff: int, H: int) -> RunSummary:
    sc = json.loads(json.dumps(scenario))
    sc.setdefault("world", {}).update({"cutoff": int(cutoff), "horizon_periods": int(H)})
    writer = RunWriter(ctx.id, sc["id"], config={"instance": ctx.id, "scenario": sc, "seed": seed, "evaluation": True})
    world = World.from_instance(ctx, sc, seed)
    summary = world.run(writer)
    writer.close(summary.to_json())
    return summary


def block_value(x: np.ndarray, blk: dict[str, Any], agg: str) -> np.ndarray:
    """groups x horizons -> one value per group for a block of horizons [from, to] (mean for shares, sum for volumes)."""
    sl = x[:, int(blk["from"]) - 1:int(blk["to"])]
    return np.nansum(sl, axis=1) if agg == "sum" else np.nanmean(sl, axis=1)


def cutoff_list(proto: dict[str, Any], d: AdoptionData) -> list[int]:
    """Protocol cutoffs: explicit periods, or every `step` periods from `first` to `last`."""
    c = proto["cutoffs"]
    if isinstance(c, dict):
        return list(range(int(c["first"]), int(c["last"]) + 1, int(c.get("step", 1))))
    return [int(x) for x in c]


def evaluate(ctx: InstanceContext, scenario_ids: list[str]) -> dict[str, Any]:
    from ..scenarios import load_scenario
    proto = ctx.yaml("evaluation/protocol.yaml")
    cfg = ctx.yaml("calibration/adoption.yaml")
    d = load_data(ctx)
    cutoffs = cutoff_list(proto, d)
    if os.environ.get("ADOPTION_CUTOFFS") == "dev":     # development runs: the first quarter of the cutoffs only
        cutoffs = cutoffs[: dev_count(proto, len(cutoff_list(proto, d)))]
    blocks = proto["blocks"]
    H = max(int(b["to"]) for b in blocks)
    seeds = [int(s) for s in proto.get("seeds", [1, 2, 3])]
    agg = "sum" if cfg.get("outcome") == "displaced" else "mean"
    comps_which = list(proto.get("comparators", ["carry_forward", "recent_average", "linear_trend", "holt_damped", "bass_diffusion"]))
    recent = int(proto.get("recent_periods", 6))
    season = proto.get("season_periods")
    groups = model_groups(d, cfg)
    scored = d.groups[d.groups.scored.astype(bool)].group.astype(str).tolist() if "scored" in d.groups else groups
    gi = [groups.index(g) for g in scored]
    labels = d.groups.set_index("group").label.astype(str).to_dict()
    last_period = int(d.series.period.max())
    dates = d.dates()
    base_id = proto.get("baseline_scenario", "baseline")
    base = load_scenario(ctx, base_id)
    run_ids: dict[str, list[str]] = {base_id: []}
    windows, rows = [], []
    for c in cutoffs:
        sims = [_run_world(ctx, base, sd, c, H) for sd in seeds]
        run_ids[base_id] += [s.run_id for s in sims]
        h0 = sims[0].headline
        print(f"[{ctx.id}] cutoff {c} ({h0['cutoff_date']}): {h0['calibration']['selection']} {h0['calibration']['spec']}", flush=True)
        Pc = np.array([g["central"] for g in h0["groups"]])
        R = np.array([[g["run"] for g in s.headline["groups"]] for s in sims])          # seeds x groups x H
        v = View(d, cfg, groups, c)
        comp = comparators(v, H, comps_which, recent, int(season) if season else None, proto.get("trend_periods"))
        A = d.matrix(groups, list(range(c, c + H)))           # actual outcomes: read only here, for scoring
        win = {"cutoff": int(c), "cutoff_date": h0["cutoff_date"], "last_observed": str(pd.Timestamp(dates.get(c - 1)).date()) if (c - 1) in dates.index else None,
               "selection": h0["calibration"]["selection"], "spec": h0["calibration"]["spec"], "inner_cutoffs": h0["calibration"]["inner_cutoffs"], "blocks": {}, "run_ids": [s.run_id for s in sims]}
        for b in blocks:
            if c - 1 + int(b["to"]) > last_period:
                continue                                         # the block's target periods are not published yet
            act = block_value(A, b, agg)[gi]
            if not np.isfinite(act).any():
                continue
            sim = block_value(Pc, b, agg)[gi]
            runs = np.array([block_value(R[s], b, agg)[gi] for s in range(len(seeds))])
            lo, hi = np.nanpercentile(runs, 5, axis=0), np.nanpercentile(runs, 95, axis=0)
            preds = {"simulation": sim, **{k: block_value(P, b, agg)[gi] for k, P in comp.items()}}
            ok = np.isfinite(act)
            errs = {k: float(np.mean(np.abs(p[ok] - act[ok]))) for k, p in preds.items()}
            win["blocks"][b["id"]] = {"mae": errs, "mean_actual": float(np.mean(act[ok])), "n": int(ok.sum()), "coverage90": float(np.mean((act[ok] >= lo[ok]) & (act[ok] <= hi[ok])) * 100),
                                      "target_from": str(pd.Timestamp(dates.get(c - 1 + int(b["from"]))).date()) if (c - 1 + int(b["from"])) in dates.index else None,
                                      "target_to": str(pd.Timestamp(dates.get(c - 1 + int(b["to"]))).date()) if (c - 1 + int(b["to"])) in dates.index else None}
            for j, g in enumerate(scored):
                if np.isfinite(act[j]):
                    rows.append({"cutoff": int(c), "block": b["id"], "group": g, "label": labels.get(g, g), "actual": float(act[j]), "simulation": float(sim[j]), "lo": float(lo[j]), "hi": float(hi[j]),
                                 **{k: float(p[j]) for k, p in preds.items() if k != "simulation"}})
        windows.append(win)
    who = ["simulation", *comps_which]
    ndev = dev_count(proto, len(cutoff_list(proto, d)))
    dev_set = set(cutoff_list(proto, d)[:ndev])

    def summarise(sel: list[dict[str, Any]], bid: str) -> dict[str, Any] | None:
        ws = [w for w in sel if bid in w["blocks"]]
        if not ws:
            return None
        rs = [r for r in rows if r["block"] == bid and r["cutoff"] in {w["cutoff"] for w in ws}]
        mae = {k: float(np.mean([abs(r[k] - r["actual"]) for r in rs])) for k in who}
        level = float(np.mean([r["actual"] for r in rs]))
        best = min(comps_which, key=lambda k: mae[k])
        return {"mae": mae, "mean_actual": level, "n_predictions": len(rs), "n_cutoffs": len(ws), "best_baseline": best,
                "error_reduction_pct": (1 - mae["simulation"] / mae[best]) * 100 if mae[best] > 0 else None,
                "accuracy_pct": {k: 100 * (1 - mae[k] / level) for k in who} if level else None,
                "coverage90": float(np.mean([w["blocks"][bid]["coverage90"] for w in ws])),
                "cutoffs_simulation_better": int(sum(w["blocks"][bid]["mae"]["simulation"] < w["blocks"][bid]["mae"][best] for w in ws)),
                "first_cutoff": ws[0]["cutoff_date"], "last_cutoff": ws[-1]["cutoff_date"]}

    accuracy = {}
    for part, sel in (("all", windows), ("dev", [w for w in windows if w["cutoff"] in dev_set]), ("held_out", [w for w in windows if w["cutoff"] not in dev_set])):
        accuracy[part] = {b["id"]: summarise(sel, b["id"]) for b in blocks}
        hb = proto.get("headline_blocks", [b["id"] for b in blocks])
        rs = [r for r in rows if r["block"] in hb and r["cutoff"] in {w["cutoff"] for w in sel}]
        if rs:
            mae = {k: float(np.mean([abs(r[k] - r["actual"]) for r in rs])) for k in who}
            level = float(np.mean([r["actual"] for r in rs]))
            best = min(comps_which, key=lambda k: mae[k])
            accuracy[part]["headline"] = {"mae": mae, "mean_actual": level, "n_predictions": len(rs), "best_baseline": best,
                                          "error_reduction_pct": (1 - mae["simulation"] / mae[best]) * 100 if mae[best] > 0 else None,
                                          "accuracy_pct": {k: 100 * (1 - mae[k] / level) for k in who}, "blocks": hb}
    # by group, held-out cutoffs, headline blocks
    hb = proto.get("headline_blocks", [b["id"] for b in blocks])
    by_group = {}
    for g in scored:
        rs = [r for r in rows if r["group"] == g and r["block"] in hb and r["cutoff"] not in dev_set]
        if rs:
            by_group[g] = {"label": labels.get(g, g), "n": len(rs), "mean_actual": float(np.mean([r["actual"] for r in rs])),
                           **{k: float(np.mean([abs(r[k] - r["actual"]) for r in rs])) for k in who}}
    alt_id = ctx.meta.get("scenarios", {}).get("alternative")
    if alt_id and alt_id in scenario_ids:
        alt = load_scenario(ctx, alt_id)
        run_ids[alt_id] = []
        for c in cutoffs[-int(proto.get("alternative_cutoffs", 2)):]:
            for sd in seeds:
                run_ids[alt_id].append(_run_world(ctx, alt, sd, c, H).run_id)
    out = {"instance": ctx.id, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "scenarios": scenario_ids,
           "protocol": {"cutoffs": [w["cutoff"] for w in windows], "cutoff_dates": [w["cutoff_date"] for w in windows], "dev_cutoffs": sorted(dev_set & {w["cutoff"] for w in windows}),
                        "blocks": blocks, "headline_blocks": hb, "seeds": seeds, "runs": len(windows) * len(seeds), "outcome": cfg.get("outcome", "share"),
                        "scored_groups": scored, "point": "central path (every shock at its median)", "interval": "5th-95th percentile across runs",
                        "unit": proto.get("unit", ""), "scale": proto.get("scale", 1.0)},
           "run_ids": run_ids, "windows": windows, "accuracy": accuracy, "by_group": by_group, "rows": rows, "comparator_labels": {k: COMPARATOR_LABELS[k] for k in comps_which}}
    head = accuracy["held_out"].get("headline") or accuracy["all"].get("headline") or {}
    sc_ = float(proto.get("scale", 1.0))
    out["headline"] = {
        "mae": {"label": proto.get("headline_label", "Mean absolute error"), "simulated": head.get("mae", {}).get("simulation", np.nan) * sc_,
                "baseline": head.get("mae", {}).get(head.get("best_baseline"), np.nan) * sc_ if head else None, "unit": proto.get("unit", ""), "better": "lower"},
        "accuracy": {"label": "Accuracy: 100 x (1 - error / mean actual)", "simulated": (head.get("accuracy_pct") or {}).get("simulation"),
                     "baseline": (head.get("accuracy_pct") or {}).get(head.get("best_baseline")), "unit": "%", "better": "higher"},
    }
    ctx.runs_dir.mkdir(parents=True, exist_ok=True)
    (ctx.runs_dir / "evaluation.json").write_text(json.dumps(out, indent=1, default=_json_default))
    return out


def dev_count(proto: dict[str, Any], n: int) -> int:
    """The first quarter of the cutoffs (at least two) is for development."""
    return int(proto.get("dev_cutoffs", max(2, math.ceil(n / 4))))


def _json_default(o: Any) -> Any:
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return None if math.isnan(float(o)) else float(o)
    if isinstance(o, float) and math.isnan(o):
        return None
    if isinstance(o, (pd.Timestamp, datetime)):
        return str(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


# ------------------------------------------------------------------ results view

def results_view(ctx: InstanceContext) -> dict[str, Any]:
    """Actual outcomes, the simulation and the other predictions at every cutoff (held-out cutoffs lead), then the
    alternative at matching cutoffs and seeds."""
    doc = base_document(ctx)
    p = ctx.runs_dir / "evaluation.json"
    ev = json.loads(p.read_text()) if p.exists() else {}
    base = doc["scenarios"]["baseline"]; alt = doc["scenarios"].get("alternative")
    proto = ev.get("protocol") or {}
    acc = ev.get("accuracy") or {}
    labels = ev.get("comparator_labels") or {}
    unit, scale = proto.get("unit", ""), float(proto.get("scale", 1.0))
    sources = [{"id": "actual", "label": "Actual outcome", "kind": "actual", "scenario": base["id"], "note": ctx.meta.get("data_used", "")},
               {"id": "baseline", "label": "Simulation prediction", "kind": "simulated", "scenario": base["id"], "runs": proto.get("runs"),
                "note": f"The central path of the simulation at each of {len(proto.get('cutoffs', []))} cutoffs; ranges are the 5th-95th percentile across {len(proto.get('seeds', []))} runs per cutoff. Each run reads only periods before its cutoff."}]
    alt_docs = run_docs(ctx, alt["id"], "summary", (ev.get("run_ids") or {}).get(alt["id"], [])) if alt else []
    if alt:
        sources.append({"id": "alternative", "label": f"{alt['short_title']} · simulation prediction", "kind": "simulated", "scenario": alt["id"], "runs": len(alt_docs), "note": "Same cutoffs and seeds as the simulation of what happened."})
    for s_ in sources:
        s_["kind_label"] = {"actual": "Actual outcome (actual data)", "baseline": "Simulation prediction", "alternative": "Alternative simulation prediction"}[s_["id"]]
        s_["short"] = {"actual": "Actual outcome", "baseline": "Simulation prediction", "alternative": alt["short_title"] if alt else ""}[s_["id"]]
    if not ev:
        doc.update({"sources": sources, "metrics": [], "effects": [], "charts": [], "hero": {"kicker": "No evaluation yet", "stats": [], "claim": ""}})
        return doc
    blocks = {b["id"]: b for b in proto.get("blocks", [])}
    held = acc.get("held_out") or {}
    allc = acc.get("all") or {}
    hh = held.get("headline") or allc.get("headline") or {}
    best = hh.get("best_baseline")
    short = lambda k: labels.get(k, k).split(":")[0]  # noqa: E731
    fmt = lambda x: f"{x * scale:,.2f}" if abs(x * scale) < 100 else f"{x * scale:,.0f}"  # noqa: E731
    metrics = []
    for part, label in (("held_out", "held-out cutoffs"), ("all", "all cutoffs")):
        for bid, b in blocks.items():
            a = (acc.get(part) or {}).get(bid)
            if not a:
                continue
            metrics.append({"id": f"mae_{bid}_{part}", "label": f"{proto.get('headline_label', 'Mean absolute error')}, {b['label']} ({label}; {a['n_predictions']} predictions)", "unit": unit, "better": "lower",
                            "values": {"actual": None, "baseline": a["mae"]["simulation"] * scale, "alternative": None}, "intervals": {},
                            "note": " · ".join(f"{short(k)}: {fmt(a['mae'][k])}" for k in labels) + f" · best other: {short(a['best_baseline'])}"})
            metrics.append({"id": f"acc_{bid}_{part}", "label": f"Accuracy, {b['label']} ({label})", "unit": "%", "better": "higher",
                            "values": {"actual": None, "baseline": a["accuracy_pct"]["simulation"], "alternative": None}, "intervals": {},
                            "note": " · ".join(f"{short(k)}: {a['accuracy_pct'][k]:.1f}%" for k in labels)})
    rows = ev.get("rows") or []
    charts = []
    for bid, b in blocks.items():
        rs = [r for r in rows if r["block"] == bid]
        if not rs:
            continue
        cuts = sorted({r["cutoff"] for r in rs})
        cd = {w["cutoff"]: w["cutoff_date"] for w in ev.get("windows", [])}
        series_m = lambda key: [float(np.mean([r[key] for r in rs if r["cutoff"] == c])) * scale for c in cuts]  # noqa: E731
        charts.append({"id": f"level_{bid}", "type": "line", "title": f"{proto.get('chart_label', 'Outcome')}, {b['label']}, by cutoff", "x": [cd.get(c, str(c)) for c in cuts], "x_label": "cutoff", "y_label": unit,
                       "series": [{"name": "Actual outcome", "y": series_m("actual"), "source": "actual"},
                                  {"name": "Simulation prediction", "y": series_m("simulation"), "source": "baseline", "band": [series_m("lo"), series_m("hi")]},
                                  *[{"name": short(k), "y": series_m(k), "source": "actual", "dashed": True} for k in labels]],
                       "note": "Averages over the scored groups at each cutoff."})
        charts.append({"id": f"error_{bid}", "type": "line", "title": f"{proto.get('headline_label', 'Error')}, {b['label']}, by cutoff", "x": [cd.get(c, str(c)) for c in cuts], "x_label": "cutoff", "y_label": unit,
                       "series": [{"name": "Simulation prediction", "y": [float(np.mean([abs(r['simulation'] - r['actual']) for r in rs if r['cutoff'] == c])) * scale for c in cuts], "source": "baseline"},
                                  *[{"name": short(k), "y": [float(np.mean([abs(r[k] - r['actual']) for r in rs if r['cutoff'] == c])) * scale for c in cuts], "source": "actual", "dashed": True} for k in labels]],
                       "note": "Lower is better."})
    bg = ev.get("by_group") or {}
    if bg:
        gs = sorted(bg, key=lambda g: -bg[g]["mean_actual"])
        charts.append({"id": "by_group", "type": "hbar", "title": f"{proto.get('headline_label', 'Error')} by group, held-out cutoffs", "x": [bg[g]["label"] for g in gs], "x_label": "", "y_label": unit,
                       "series": [{"name": "Simulation prediction", "y": [bg[g]["simulation"] * scale for g in gs], "source": "baseline"},
                                  {"name": f"Best other prediction ({short(best)})", "y": [bg[g][best] * scale for g in gs], "source": "actual"}], "note": ""})
    n_held = sum(1 for w in ev.get("windows", []) if w["cutoff"] not in set(proto.get("dev_cutoffs", [])))
    hero = {"kicker": f"Backtested: {hh.get('n_predictions', 0):,} held-out predictions at {n_held} cutoffs",
            "stats": [{"label": f"Less error than the best standard method ({short(best)})", "value": hh.get("error_reduction_pct"), "unit": "%"},
                      {"label": f"Simulation error ({unit})", "value": (hh.get("mae") or {}).get("simulation", 0) * scale, "unit": ""},
                      {"label": f"Best standard method error ({unit})", "value": (hh.get("mae") or {}).get(best, 0) * scale, "unit": ""},
                      {"label": "Simulation accuracy", "value": (hh.get("accuracy_pct") or {}).get("simulation"), "unit": "%"}],
            "claim": "Every prediction uses only periods before its cutoff; the design was frozen on the first quarter of the cutoffs before the rest were run.",
            "chart": next((c["id"] for c in charts if c["id"].startswith("level_")), None)}
    if alt and alt_docs:
        keys = {(d_["headline"]["cutoff"], d_["seed"]) for d_ in alt_docs}
        base_docs = [d_ for d_ in run_docs(ctx, base["id"], "summary", (ev.get("run_ids") or {}).get(base["id"], [])) if (d_["headline"]["cutoff"], d_["seed"]) in keys]
        f = lambda h: float(np.mean([g["central"][-1] for g in h["groups"]])) * scale  # noqa: E731
        bm = float(np.mean([f(d_["headline"]) for d_ in base_docs])) if base_docs else None
        am = float(np.mean([f(d_["headline"]) for d_ in alt_docs]))
        metrics.append({"id": "alt_end_level", "label": f"{proto.get('chart_label', 'Outcome')} at the end of the horizon (simulated)", "unit": unit, "better": "",
                        "values": {"actual": None, "baseline": bm, "alternative": am}, "intervals": {}, "note": "Simulated only; matching cutoffs and seeds."})
        hero["alternative"] = {"kicker": f"Alternative: {alt['short_title']}", "stats": [{"label": proto.get("chart_label", "Outcome"), "value": f"{bm:,.2f} → {am:,.2f} {unit}" if bm is not None else None, "unit": ""}],
                               "text": alt.get("summary") or alt.get("description", "")}
    doc["design"] = ctx.meta.get("intro", "")
    doc.update({"sources": sources, "metrics": metrics, "effects": [], "charts": charts, "hero": hero, "evaluation": {"generated": ev.get("generated"), "protocol": proto}})
    return doc
