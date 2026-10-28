"""Service world: requesters file service requests with organisations, which work them under limited capacity.

Agents, carried forward week by week from a Monday cutoff t0 for H weeks:

  Requester segments. One agent per (organisation, segment): the consumers of one product at one company, or the
  residents filing one complaint type with one agency. Each has a weekly demand level, a growth rate that decays
  (damping phi) towards the typical growth of leading segments after a cutoff, an annual pattern (week of the year)
  and holiday weeks. Weekly requests are drawn around that demand; the central path, with every shock at its median,
  is the point prediction and the runs give the ranges.

  Organisations. Each works the requests its segments send. Its staffing is read from its throughput before the
  cutoff: the volume it handled in the base window. When a week's predicted load exceeds that base, work waits:
  the share answered on time falls (logit response kappa) and times to close stretch (elasticity eta). Its outcome
  for a week is the mix of its segments' outcomes weighted by their predicted volume, so a shift in what people
  complain about changes the organisation's on-time share and time to close even when its total does not move.

Calibration at each cutoff uses requests created before t0 only: their closures only when closed before t0, and the
on-time flag only once its deadline has passed before t0 (`Visible`). The demand specification (starting-level
window, damping, weight on own trend, weight on the annual pattern, forward drift) is chosen by backtests at earlier
cutoffs whose targets end before t0, with the one-standard-error rule towards the recent level held flat. Holiday
effects, annual patterns, base rates and the load responses are estimated from the same pre-cutoff weeks.

Instances supply data/normalized/requests.parquet (created, org, segment, optional closed, optional on_time),
calibration/service.yaml (settings and grids) and evaluation/protocol.yaml (cutoffs, horizon, seeds, comparators).
"""
from __future__ import annotations

import itertools
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd

from ..evaluation import forecast as fc
from ..evaluation.results import base_document, run_docs
from ..instances import InstanceContext
from ..kernel.world import Agent, BaseWorld, RunSummary
from ..store.runs import RunWriter
from .market import own_slope, wmedian
from .survival import aalen_johansen

EPOCH = np.datetime64("1970-01-05", "ns")          # a Monday; week index = whole weeks since EPOCH
NS_WEEK = np.int64(7 * 24 * 3600 * 10**9)
NS_HOUR = np.int64(3600 * 10**9)
NAT = np.iinfo(np.int64).min
CLOSE_GRID_H = np.array([0, 0.25, 0.5, 1, 2, 3, 4, 6, 8, 12, 16, 24, 36, 48, 72, 96, 120, 168, 240, 336, 504, 720, 1080, 1440, 2160, 2880, 4320], dtype=float)


def week_index(ts) -> int:
    return int((np.datetime64(pd.Timestamp(ts).to_datetime64(), "ns") - EPOCH) // NS_WEEK)


def week_start(i: int) -> pd.Timestamp:
    return pd.Timestamp(EPOCH + np.timedelta64(int(i) * 7, "D"))


# ------------------------------------------------------------------ data

@dataclass
class ServiceData:
    """Requests sorted by creation time, as numpy arrays (codes for organisations and segments)."""
    created: np.ndarray              # int64 ns
    week: np.ndarray                 # int32 week index
    org: np.ndarray                  # int32 code
    seg: np.ndarray                  # int32 code
    org_names: list[str]
    seg_names: list[str]
    closed: np.ndarray | None        # int64 ns, NAT if not closed
    on_time: np.ndarray | None       # float32, NaN if unknown

    @classmethod
    def from_frame(cls, df: pd.DataFrame) -> "ServiceData":
        df = df.sort_values("created", kind="stable")
        created = df.created.to_numpy("datetime64[ns]").astype(np.int64)
        org = pd.Categorical(df.org.astype(str)); seg = pd.Categorical(df.segment.astype(str))
        closed = df.closed.to_numpy("datetime64[ns]").astype(np.int64) if "closed" in df else None
        on_time = df.on_time.to_numpy(dtype=np.float32, na_value=np.nan) if "on_time" in df else None
        return cls(created=created, week=((created - EPOCH.astype(np.int64)) // NS_WEEK).astype(np.int32),
                   org=org.codes.astype(np.int32), seg=seg.codes.astype(np.int32), org_names=[str(x) for x in org.categories],
                   seg_names=[str(x) for x in seg.categories], closed=closed, on_time=on_time)


@lru_cache(maxsize=2)
def _load(path: str, mtime: float) -> ServiceData:
    return ServiceData.from_frame(pd.read_parquet(path))


def load_data(ctx: InstanceContext) -> ServiceData:
    p = ctx.data_normalized / "requests.parquet"
    if not p.exists():
        raise FileNotFoundError(f"{p} missing; run `orgsim ingest {ctx.id}`")
    return _load(str(p), p.stat().st_mtime)


class Visible:
    """What is known at cutoff t0: requests created before t0; a closure only if it happened before t0; an on-time
    flag only if the request's response deadline passed before t0. Every calibration reads data through this."""

    def __init__(self, d: ServiceData, t0: pd.Timestamp, deadline_days: float = 0.0) -> None:
        self.d, self.t0 = d, pd.Timestamp(t0)
        self.t0_ns = np.int64(self.t0.value)
        self.t0w = week_index(self.t0)
        self.n = int(np.searchsorted(d.created, self.t0_ns, side="left"))       # rows [0, n) were created before t0
        self.deadline_ns = np.int64(deadline_days * 24 * 3600 * 10**9)
        self.first_week = int(d.week[0]) + 1 if len(d.week) else self.t0w      # the first complete week of the data

    def rows_from_week(self, w: int) -> slice:
        lo = int(np.searchsorted(self.d.week[: self.n], w, side="left"))
        return slice(lo, self.n)

    def duration_h(self, sl: slice) -> tuple[np.ndarray, np.ndarray]:
        """Hours to close and an observed flag, censored at t0."""
        c, cl = self.d.created[sl], self.d.closed[sl]
        observed = (cl != NAT) & (cl < self.t0_ns)
        end = np.where(observed, cl, self.t0_ns)
        return np.maximum(end - c, 0) / NS_HOUR, observed

    def on_time(self, sl: slice) -> np.ndarray:
        """On-time flags known at t0 (NaN until the deadline has passed)."""
        ot = self.d.on_time[sl].astype(float)
        return np.where(self.d.created[sl] < self.t0_ns - self.deadline_ns, ot, np.nan)


# ------------------------------------------------------------------ holidays and calendar

@lru_cache(maxsize=1)
def holiday_weeks() -> dict[int, str]:
    """Week index -> U.S. federal holiday in that Monday-Sunday week (known in advance, so a legitimate input)."""
    from pandas.tseries.holiday import USFederalHolidayCalendar
    cal = USFederalHolidayCalendar()
    out: dict[int, str] = {}
    for r in cal.rules:
        for d in r.dates("2010-01-01", "2032-12-31"):
            out.setdefault(week_index(d), r.name)
    return out


@lru_cache(maxsize=1)
def _woy_table() -> np.ndarray:
    """Week of the year for every week index from 1990 to 2040 (looked up, not recomputed per call)."""
    w = np.arange(0, 3700)
    thu = pd.DatetimeIndex(EPOCH + (w.astype(np.int64) * 7 + 3).astype("timedelta64[D]"))
    return np.minimum(thu.isocalendar().week.to_numpy().astype(int), 52) - 1


def week_of_year(w: np.ndarray) -> np.ndarray:
    """0..51: the ISO week of the week's Thursday, week 53 folded into 52."""
    return _woy_table()[np.asarray(w, dtype=np.int64)]


# ------------------------------------------------------------------ the agents at a cutoff

@dataclass
class Units:
    orgs: list[int]                  # selected organisation codes
    unit_org: np.ndarray             # unit -> index into orgs
    unit_seg: list[int | None]       # unit -> segment code (None = the organisation's other segments)
    lookup: np.ndarray               # [org code, seg code] -> unit index or -1
    names: list[str]


def select_units(v: Visible, n_orgs: int, selection_weeks: int, min_share: float, share_weeks: int) -> Units:
    """Organisations with the most requests in the weeks before t0; inside each, segments with at least `min_share`
    of its requests in the last `share_weeks` weeks are their own agents, the rest share one."""
    d = v.d
    sl = v.rows_from_week(v.t0w - selection_weeks)
    counts = np.bincount(d.org[sl], minlength=len(d.org_names))
    orgs = [int(o) for o in np.argsort(-counts, kind="stable")[:n_orgs] if counts[o] > 0]
    sl2 = v.rows_from_week(v.t0w - share_weeks)
    pair = np.bincount(d.org[sl2].astype(np.int64) * len(d.seg_names) + d.seg[sl2], minlength=len(d.org_names) * len(d.seg_names)).reshape(len(d.org_names), len(d.seg_names))
    lookup = np.full((len(d.org_names), len(d.seg_names)), -1, dtype=np.int32)
    unit_org, unit_seg, names = [], [], []
    for i, o in enumerate(orgs):
        tot = pair[o].sum()
        big = [int(s) for s in np.argsort(-pair[o], kind="stable") if tot > 0 and pair[o, s] >= min_share * tot]
        for s in big:
            lookup[o, s] = len(unit_org); unit_org.append(i); unit_seg.append(s); names.append(f"{d.org_names[o]} | {d.seg_names[s]}")
        rest = [s for s in range(len(d.seg_names)) if s not in set(big)]
        if rest:
            lookup[o, rest] = len(unit_org); unit_org.append(i); unit_seg.append(None); names.append(f"{d.org_names[o]} | other")
    return Units(orgs=orgs, unit_org=np.asarray(unit_org, dtype=int), unit_seg=unit_seg, lookup=lookup, names=names)


def panel(v: Visible, u: Units, w0: int, w1: int) -> np.ndarray:
    """Requests per unit (rows) and week (columns) for weeks [w0, w1), w1 <= t0 week."""
    assert w1 <= v.t0w
    d = v.d
    sl = v.rows_from_week(w0)
    wk = d.week[sl]
    m = wk < w1
    uid = u.lookup[d.org[sl][m], d.seg[sl][m]]
    ok = uid >= 0
    n_u, n_w = len(u.unit_org), w1 - w0
    return np.bincount(uid[ok].astype(np.int64) * n_w + (wk[m][ok] - w0), minlength=n_u * n_w).reshape(n_u, n_w).astype(float)


def org_sum(x: np.ndarray, u: Units) -> np.ndarray:
    out = np.zeros((len(u.orgs),) + x.shape[1:])
    np.add.at(out, u.unit_org, x)
    return out


# ------------------------------------------------------------------ demand calibration (pre-cutoff only)

def holiday_effects(L: np.ndarray, weeks: np.ndarray, vol: np.ndarray) -> dict[str, float]:
    """Log effect of each federal holiday's week: the week against the two weeks either side, the volume-weighted
    median over units and years in the history."""
    hw = holiday_weeks()
    idx = {int(w): i for i, w in enumerate(weeks)}
    rows: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
    for w, name in hw.items():
        i = idx.get(w)
        if i is None or i < 2 or i > len(weeks) - 3:
            continue
        nb = [j for j in (i - 2, i - 1, i + 1, i + 2) if int(weeks[j]) not in hw]
        if len(nb) < 2:
            continue
        rows.setdefault(name, []).append((L[:, i] - L[:, nb].mean(1), vol))
    out = {}
    for name, rs in rows.items():
        v = np.concatenate([r[0] for r in rs]); wt = np.concatenate([r[1] for r in rs])
        ok = np.isfinite(v) & (wt > 0)
        out[name] = float(np.clip(wmedian(v[ok], wt[ok]), -1.0, 1.0)) if ok.sum() >= 3 else 0.0
    return out


@lru_cache(maxsize=1)
def _holiday_names() -> tuple[np.ndarray, list[str]]:
    hw = holiday_weeks()
    names = sorted(set(hw.values()))
    tab = np.full(3700, -1, dtype=int)
    for w, n in hw.items():
        if 0 <= w < 3700:
            tab[w] = names.index(n)
    return tab, names


def holiday_vector(weeks: np.ndarray, eff: dict[str, float]) -> np.ndarray:
    tab, names = _holiday_names()
    vals = np.array([eff.get(n, 0.0) for n in names] + [0.0])
    return vals[tab[np.asarray(weeks, dtype=np.int64)]]


def annual_profile(Lh: np.ndarray, weeks: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per unit, the mean log deviation of each week of the year from the centred 13-week average (holiday weeks
    already removed), smoothed over neighbouring weeks and centred; and the number of years behind each unit."""
    n_u, n_w = Lh.shape
    if n_w < 13 + 26:
        return np.zeros((n_u, 52)), np.zeros(n_u)
    k = np.ones(13) / 13
    cma = np.full_like(Lh, np.nan)
    for i in range(n_u):
        cma[i, 6:n_w - 6] = np.convolve(Lh[i], k, mode="valid")
    r = Lh - cma
    woy = week_of_year(weeks)
    prof = np.zeros((n_u, 52)); cnt = np.zeros(52)
    for j in range(52):
        cols = np.flatnonzero((woy == j) & np.isfinite(r[0]))
        cnt[j] = len(cols)
        if len(cols):
            prof[:, j] = r[:, cols].mean(1)
    sm = (np.roll(prof, 1, 1) + 2 * prof + np.roll(prof, -1, 1)) / 4
    sm -= sm.mean(1, keepdims=True)
    years = np.full(n_u, float(np.median(cnt)))
    return sm, years


@dataclass
class DemandFit:
    holidays: dict[str, float]
    profile: np.ndarray              # units x 52
    years: np.ndarray


def fit_seasonal(Y: np.ndarray, weeks: np.ndarray) -> DemandFit:
    L = np.log1p(Y)
    vol = Y[:, -26:].mean(1) + 1e-9
    eff = holiday_effects(L, weeks, vol)
    Lh = L - holiday_vector(weeks, eff)[None, :]
    prof, years = annual_profile(Lh, weeks)
    return DemandFit(eff, prof, years)


SPEC_KEYS = ("k_level", "phi", "w", "seasonal", "drift", "revert", "pool")
SPEC_DEFAULTS = {"k_level": 4, "phi": 0.0, "w": 0.0, "seasonal": 0.0, "drift": 0.0, "revert": 1.0, "pool": 0.0}
LONG_WEEKS = 26                     # the longer-run level a burst decays back towards


def demand_paths(Y: np.ndarray, weeks: np.ndarray, fit: DemandFit, H: int, spec: dict[str, Any], mu: np.ndarray | float, slope_weeks: int = 8,
                 groups: np.ndarray | None = None) -> np.ndarray:
    """Central log1p demand paths (units x H) for the H weeks after the history Y (units x weeks).

    The starting level is the mean of the last k weeks (holiday and annual pattern removed). With `pool` > 0 it is
    blended with the level borrowed from the segment's group (the same product or complaint type at the other
    organisations): the group's last-k-week level times the segment's 26-week share of the group. Growth starts at a
    mix of the segment's own recent growth and the typical forward drift and decays at rate phi. A departure of the
    starting level from the segment's 26-week level fades by the factor `revert` per week (1 = it persists)."""
    sw = float(spec["seasonal"]) * fit.years / (fit.years + 1.0)
    woy_h, woy_f = week_of_year(weeks), week_of_year(np.arange(weeks[-1] + 1, weeks[-1] + 1 + H))
    z = np.log1p(Y) - holiday_vector(weeks, fit.holidays)[None, :] - sw[:, None] * fit.profile[:, woy_h]
    k = int(spec["k_level"])
    lvl = np.log(np.mean(np.exp(z[:, -k:]), axis=1))
    beta = float(spec.get("pool", 0.0))
    if beta > 0 and groups is not None:
        ez = np.exp(z)
        pooled = lvl.copy()
        for g_ in np.unique(groups[groups >= 0]):
            m = groups == g_
            if m.sum() < 2:
                continue
            share = ez[m, -LONG_WEEKS:].sum(1) / max(ez[m, -LONG_WEEKS:].sum(), 1e-9)
            pooled[m] = np.log(np.maximum(share, 1e-9) * ez[m, -k:].sum(0).mean())
        lvl = (1 - beta) * lvl + beta * pooled
    long = np.log(np.mean(np.exp(z[:, -LONG_WEEKS:]), axis=1))
    rho = float(spec.get("revert", 1.0))
    mu_e = float(spec["drift"]) * np.asarray(mu, dtype=float)
    g = float(spec["w"]) * own_slope(z, slope_weeks) + (1 - float(spec["w"])) * mu_e
    phi = float(spec["phi"])
    out = np.empty((Y.shape[0], H))
    gap = lvl - long
    for h in range(H):
        g = phi * g + (1 - phi) * mu_e
        long = long + g
        gap = rho * gap
        out[:, h] = long + gap
    return out + sw[:, None] * fit.profile[:, woy_f] + holiday_vector(np.arange(weeks[-1] + 1, weeks[-1] + 1 + H), fit.holidays)[None, :]


def unit_groups(u: Units) -> np.ndarray:
    """Group of each segment for pooling: its segment code across organisations (-1 for an organisation's other segments)."""
    return np.array([-1 if s is None else int(s) for s in u.unit_seg])


def tiered_paths(Y: np.ndarray, weeks: np.ndarray, fit: DemandFit, H: int, specs: list[dict[str, Any]], mus: dict[int, float],
                 unit_tier: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """Each segment's path under its size tier's specification."""
    out = np.empty((Y.shape[0], H))
    for t in np.unique(unit_tier):
        m = unit_tier == t
        out[m] = demand_paths(Y, weeks, fit, H, specs[int(t)], mus[int(t)], groups=groups)[m]
    return out


def tier_of(org_level: np.ndarray, tiers: list[float]) -> np.ndarray:
    """0 for the largest organisations (weekly volume >= tiers[0]), 1 for the next band, ..."""
    t = np.zeros(len(org_level), dtype=int)
    for i, thr in enumerate(sorted(tiers, reverse=True)):
        t[org_level < thr] = i + 1
    return t


def forward_drift(folds: list[dict[str, Any]], k: int) -> float:
    """Typical realised weekly log growth after a cutoff of the units, against their k-week starting level,
    weighted by volume (selection on recent volume makes this include regression to the mean)."""
    S, V = [], []
    for f in folds:
        z = np.log1p(f["Y"]); l0 = np.log(np.mean(np.exp(z[:, -k:]), axis=1))
        r = np.log1p(f["A"]) - l0[:, None]
        hs = np.arange(1, r.shape[1] + 1)
        S.append((r * hs).sum(1) / (hs ** 2).sum()); V.append(np.expm1(l0) + 1)
    if not S:
        return 0.0
    return float(np.clip(wmedian(np.concatenate(S), np.concatenate(V)), -0.1, 0.1))


def fit_demand(v: Visible, u: Units, cfg: dict[str, Any], H: int) -> dict[str, Any]:
    """Choose the demand specification by backtests at earlier cutoffs (targets end before t0), per size tier."""
    hist = int(cfg.get("history_weeks", 156))
    inner, step = int(cfg.get("inner_cutoffs", 8)), int(cfg.get("inner_step_weeks", 4))
    grid = {k: list(cfg["grid"].get(k, [SPEC_DEFAULTS[k]])) for k in SPEC_KEYS}
    simple = {k: cfg["simplest"].get(k, SPEC_DEFAULTS[k]) for k in SPEC_KEYS}
    one_se = bool(cfg.get("one_se", True))
    tiers = list(cfg.get("tiers") or [])
    W0 = max(v.t0w - hist - H - step * (inner - 1), v.first_week)
    Yall = panel(v, u, W0, v.t0w)
    folds = []
    for j in range(inner):
        c = v.t0w - H - step * j
        lo = max(0, c - hist - W0)
        Y = Yall[:, lo:c - W0]; A = Yall[:, c - W0:c - W0 + H]
        if Y.shape[1] < 26:
            continue
        weeks = np.arange(W0 + lo, c)
        folds.append({"Y": Y, "A": A, "weeks": weeks, "fit": fit_seasonal(Y, weeks)})
    org_lvl = org_sum(Yall[:, -13:], u).mean(1)
    tier = tier_of(org_lvl, tiers)
    n_t = int(tier.max()) + 1 if len(tier) else 1
    specs = [dict(zip(SPEC_KEYS, s)) for s in itertools.product(*(grid[k] for k in SPEC_KEYS))]
    if simple not in specs:
        specs.append(simple)
    groups = unit_groups(u)
    res: dict[tuple, np.ndarray] = {}
    for i, f in enumerate(folds):
        others = folds[:i] + folds[i + 1:]
        mu_k = {k: forward_drift(others, k) for k in grid["k_level"]}
        Aorg = org_sum(f["A"], u)
        tot = Aorg.sum()
        for sp in specs:
            P = np.maximum(np.expm1(demand_paths(f["Y"], f["weeks"], f["fit"], H, sp, mu_k[int(sp["k_level"])], groups=groups)), 0)
            e = np.abs(org_sum(P, u) - Aorg).sum(1)
            r = res.setdefault(tuple(sp.values()), np.zeros((len(folds), n_t)))
            for t in range(n_t):
                r[i, t] = e[tier == t].sum() / tot if tot > 0 else 0.0
    chosen, selection, inner_err = [], [], []
    for t in range(n_t):
        if not folds:
            chosen.append(dict(simple)); selection.append("no backtests"); inner_err.append(None)
            continue
        best_key = min(res, key=lambda k_: float(res[k_][:, t].mean()))
        diff = res[tuple(simple.values())][:, t] - res[best_key][:, t]
        se = float(np.std(diff, ddof=1) / math.sqrt(len(diff))) if len(diff) > 1 else float("inf")
        rich = float(diff.mean()) > (se if one_se else 0.0) and float(diff.mean()) > 0
        chosen.append(dict(zip(SPEC_KEYS, best_key)) if rich else dict(simple))
        selection.append("richer specification" if rich else "simplest specification (one-standard-error rule)" if one_se else "simplest specification (lowest backtest error)")
        inner_err.append(round(float(res[best_key if rich else tuple(simple.values())][:, t].mean()), 4))
    mu = {t: forward_drift(folds, int(chosen[t]["k_level"])) for t in range(n_t)}
    # shock sizes by horizon: robust spread of unit log errors in the backtests with the chosen specs
    resid = []
    for f in folds:
        P = np.maximum(np.expm1(tiered_paths(f["Y"], f["weeks"], f["fit"], H, chosen, mu, tier[u.unit_org], groups)), 0)
        resid.append(np.log1p(org_sum(f["A"], u)) - np.log1p(org_sum(P, u)))      # organisation-level errors: shocks shared by its segments
    if resid:
        R = np.concatenate(resid, axis=0)
        sigma = (np.quantile(R, 0.95, axis=0) - np.quantile(R, 0.05, axis=0)) / (2 * 1.645)
    else:
        sigma = np.full(H, 0.3)
    return {"spec_by_tier": chosen, "mu_by_tier": {int(t): round(v_, 5) for t, v_ in mu.items()}, "selection": selection, "inner_error": inner_err,
            "tier_of_org": tier.tolist(), "tiers": tiers, "sigma": [round(float(s), 4) for s in sigma], "inner_cutoffs": len(folds)}


# ------------------------------------------------------------------ organisation calibration (pre-cutoff only)

def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def fit_on_time(v: Visible, u: Units, cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Base on-time rate per unit from requests whose deadline passed before t0 (shrunk to the organisation's rate
    and that to the overall rate), and the load response kappa pooled over organisation-weeks before t0."""
    oc = cfg.get("on_time")
    if not oc or v.d.on_time is None:
        return None
    base_w, prior = int(oc.get("base_weeks", 13)), float(oc.get("prior_n", 50))
    lag_w = int(math.ceil(float(oc["deadline_days"]) / 7.0))
    w_end = v.t0w - lag_w                                          # weeks before w_end are fully past their deadline
    lo = w_end - max(base_w, int(oc.get("response_weeks", 52)) + 13)
    sl = v.rows_from_week(lo)
    wk, ot = v.d.week[sl], v.on_time(sl)
    uid = u.lookup[v.d.org[sl], v.d.seg[sl]]
    known = np.isfinite(ot) & (wk < w_end)
    n_u = len(u.unit_org)
    inb = known & (wk >= w_end - base_w)
    g_k, g_n = float(np.nansum(ot[inb])), float(inb.sum())
    p_g = g_k / g_n if g_n else 0.95
    k_u = np.bincount(uid[inb & (uid >= 0)], weights=ot[inb & (uid >= 0)], minlength=n_u)
    n_u_ = np.bincount(uid[inb & (uid >= 0)], minlength=n_u).astype(float)
    k_o, n_o = org_sum(k_u, u), org_sum(n_u_, u)
    p_o = (k_o + prior * p_g) / (n_o + prior)
    p_u = (k_u + prior * p_o[u.unit_org]) / (n_u_ + prior)
    kappa = 0.0
    if oc.get("load_response", True):
        # organisation-week on-time against load (volume over its trailing 13-week mean), weeks before w_end
        m = known & (uid >= 0)
        o_idx = u.unit_org[uid[m]]
        n_w = w_end - lo
        key = o_idx * n_w + (wk[m] - lo)
        N = np.bincount(key, minlength=len(u.orgs) * n_w).reshape(len(u.orgs), n_w).astype(float)
        K = np.bincount(key, weights=ot[m], minlength=len(u.orgs) * n_w).reshape(len(u.orgs), n_w)
        xs, ys, ws = [], [], []
        for j in range(13, n_w):
            base_n = N[:, j - 13:j].mean(1); base_k = K[:, j - 13:j].sum(1); base_tot = N[:, j - 13:j].sum(1)
            ok = (base_n >= 5) & (N[:, j] >= 5)
            x = np.log(N[ok, j] / base_n[ok])
            y = logit((K[ok, j] + 0.5) / (N[ok, j] + 1)) - logit((base_k[ok] + 0.5) / (base_tot[ok] + 1))
            xs.append(np.maximum(x, 0)); ys.append(y); ws.append(np.sqrt(N[ok, j]))
        if xs:
            x, y, wt = np.concatenate(xs), np.concatenate(ys), np.concatenate(ws)
            if (x > 0).sum() >= 20 and (x ** 2 * wt).sum() > 0:
                kappa = float(np.clip(-(x * y * wt).sum() / (x ** 2 * wt).sum(), 0.0, 5.0))
    base_vol = org_sum(panel(v, u, v.t0w - 13, v.t0w), u).mean(1)
    return {"p_unit": p_u, "p_org": p_o, "p_global": p_g, "kappa": kappa, "base_volume": base_vol, "base_weeks": [int(w_end - base_w), int(w_end)]}


def km_cdf(t: np.ndarray, observed: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Kaplan-Meier cumulative probability of closure on the grid (right-censored at t0)."""
    if len(t) == 0:
        return np.zeros(len(grid))
    F = aalen_johansen(t, observed, np.full(len(t), "close", dtype=object), grid, 1)
    return np.asarray(F.get("close", np.zeros(len(grid))), dtype=float)


def fit_closure(v: Visible, u: Units, cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Time-to-close distribution per unit from requests created in the base window (censored at t0), shrunk to its
    organisation's when it holds few requests, and the closure-time elasticity eta to load, pooled before t0."""
    cc = cfg.get("closure")
    if not cc or v.d.closed is None:
        return None
    base_w, prior = int(cc.get("base_weeks", 8)), float(cc.get("prior_n", 30))
    grid = CLOSE_GRID_H
    sl = v.rows_from_week(v.t0w - base_w)
    dur, obs = v.duration_h(sl)
    uid = u.lookup[v.d.org[sl], v.d.seg[sl]]
    n_u = len(u.unit_org)
    F_org = np.zeros((len(u.orgs), len(grid)))
    for i, o in enumerate(u.orgs):
        m = (v.d.org[sl] == o)
        F_org[i] = km_cdf(dur[m], obs[m], grid)
    F_unit = np.zeros((n_u, len(grid))); n_unit = np.zeros(n_u)
    for i in range(n_u):
        m = uid == i
        n_unit[i] = m.sum()
        Fi = km_cdf(dur[m], obs[m], grid)
        F_unit[i] = (n_unit[i] * Fi + prior * F_org[u.unit_org[i]]) / (n_unit[i] + prior)
    eta = 0.0
    if cc.get("load_response", True):
        eta = closure_elasticity(v, u, cc)
    base_vol = panel(v, u, v.t0w - base_w, v.t0w).mean(1)
    return {"F_unit": F_unit, "grid": grid, "eta": eta, "base_volume_unit": base_vol, "n_unit": n_unit}


def closure_elasticity(v: Visible, u: Units, cc: dict[str, Any]) -> float:
    """Pooled slope of log weekly median time to close on log load (unit volume over its trailing 13-week mean),
    over unit-weeks whose median was known well before t0, load above the trailing mean only."""
    look = int(cc.get("response_weeks", 52))
    follow = int(cc.get("followup_weeks", 4))
    w_end = v.t0w - follow
    lo = w_end - look - 13
    sl = v.rows_from_week(lo)
    dur, obs = v.duration_h(sl)
    dur = np.where(obs, dur, np.inf)
    wk = v.d.week[sl]; uid = u.lookup[v.d.org[sl], v.d.seg[sl]]
    m = (uid >= 0) & (wk < w_end)
    df = pd.DataFrame({"u": uid[m], "w": wk[m], "d": dur[m]})
    g = df.groupby(["u", "w"]).d
    med = g.median().unstack().reindex(columns=range(lo, w_end))
    N = g.size().unstack().reindex(columns=range(lo, w_end)).fillna(0)
    xs, ys, ws = [], [], []
    for j in range(13, w_end - lo):
        base_n = N.iloc[:, j - 13:j].mean(1)
        base_m = med.iloc[:, j - 13:j].median(1)
        ok = (base_n >= 10) & (N.iloc[:, j] >= 10) & np.isfinite(med.iloc[:, j]) & np.isfinite(base_m) & (base_m > 0) & (med.iloc[:, j] > 0)
        if ok.sum() == 0:
            continue
        x = np.log(N.iloc[:, j][ok] / base_n[ok]).to_numpy()
        y = np.log(med.iloc[:, j][ok] / base_m[ok]).to_numpy()
        xs.append(np.maximum(x, 0)); ys.append(y); ws.append(np.sqrt(N.iloc[:, j][ok].to_numpy()))
    if not xs:
        return 0.0
    x, y, wt = np.concatenate(xs), np.concatenate(ys), np.concatenate(ws)
    if (x > 0).sum() < 20:
        return 0.0
    return float(np.clip((x * y * wt).sum() / (x ** 2 * wt).sum(), 0.0, 3.0))


def mixture_median(F: np.ndarray, weights: np.ndarray, scale: np.ndarray, grid: np.ndarray) -> float:
    """Median of the volume-weighted mixture of closure distributions, each unit's times stretched by `scale`."""
    if weights.sum() <= 0:
        return float("nan")
    tg = np.unique(np.concatenate([grid, grid[1:, None] * scale[None, :]]))
    mix = np.zeros(len(tg))
    for i in range(len(weights)):
        if weights[i] > 0:
            mix += weights[i] * np.interp(tg / scale[i], grid, F[i])
    mix /= weights.sum()
    if mix[-1] < 0.5:
        return float("nan")
    j = int(np.argmax(mix >= 0.5))
    if j == 0:
        return float(tg[0])
    return float(np.interp(0.5, mix[j - 1:j + 1], tg[j - 1:j + 1]))


# ------------------------------------------------------------------ calibration at a cutoff

@dataclass
class Calibrated:
    t0: pd.Timestamp
    H: int
    units: Units
    Y: np.ndarray                   # unit history (weeks before t0)
    weeks: np.ndarray
    seasonal: DemandFit
    demand: dict[str, Any]
    on_time: dict[str, Any] | None
    closure: dict[str, Any] | None
    seconds: float


def calibrate(d: ServiceData, t0: pd.Timestamp, cfg: dict[str, Any], H: int) -> Calibrated:
    t_start = time.time()
    oc = cfg.get("on_time") or {}
    v = Visible(d, t0, float(oc.get("deadline_days", 0.0)))
    u = select_units(v, int(cfg["n_orgs"]), int(cfg.get("selection_weeks", 13)), float(cfg.get("segment_min_share", 0.05)), int(cfg.get("share_weeks", 26)))
    hist = min(int(cfg.get("history_weeks", 156)), v.t0w - v.first_week)
    Y = panel(v, u, v.t0w - hist, v.t0w)
    weeks = np.arange(v.t0w - hist, v.t0w)
    seasonal = fit_seasonal(Y, weeks)
    demand = fit_demand(v, u, cfg, H)
    return Calibrated(t0=pd.Timestamp(t0), H=H, units=u, Y=Y, weeks=weeks, seasonal=seasonal, demand=demand,
                      on_time=fit_on_time(v, u, cfg), closure=fit_closure(v, u, cfg), seconds=time.time() - t_start)


@lru_cache(maxsize=4)
def _cached_calibration(path: str, mtime: float, t0: str, cfg_json: str, H: int) -> Calibrated:
    return calibrate(_load(path, mtime), pd.Timestamp(t0), json.loads(cfg_json), H)


def calibration_for(ctx: InstanceContext, t0: pd.Timestamp, cfg: dict[str, Any], H: int) -> Calibrated:
    p = ctx.data_normalized / "requests.parquet"
    return _cached_calibration(str(p), p.stat().st_mtime, str(pd.Timestamp(t0).date()), json.dumps(cfg, sort_keys=True), H)


# ------------------------------------------------------------------ simulation

def simulate(cal: Calibrated, seed: int, interventions: list[dict[str, Any]] | None = None, org_names: list[str] | None = None) -> dict[str, Any]:
    """Carry every segment and organisation forward H weeks. Returns per organisation the central path (point
    prediction) and one stochastic path: weekly requests, on-time share, median hours to close."""
    rng = np.random.default_rng(seed)
    u, H, dem = cal.units, cal.H, cal.demand
    n_u = len(u.unit_org)
    tier = np.asarray(dem["tier_of_org"])[u.unit_org]
    logp = tiered_paths(cal.Y, cal.weeks, cal.seasonal, H, dem["spec_by_tier"], {int(k): v for k, v in dem["mu_by_tier"].items()}, tier, unit_groups(u))
    demand_mult = np.ones(n_u); capacity = np.ones(len(u.orgs))
    names = org_names or []
    for iv in interventions or []:
        # which organisations: all, a list of names, or the leading `top` by recent volume
        target = iv.get("orgs", "all")
        if iv.get("top"):
            sel = list(range(min(int(iv["top"]), len(u.orgs))))
        elif target == "all":
            sel = list(range(len(u.orgs)))
        else:
            sel = [i for i, o in enumerate(u.orgs) if names and names[o] in set(target)]
        if iv.get("type") == "demand_multiplier":
            for i in sel:
                demand_mult[u.unit_org == i] *= float(iv.get("multiplier", 1.0))
        elif iv.get("type") == "capacity_multiplier":
            capacity[sel] *= float(iv.get("multiplier", 1.0))
    central = np.maximum(np.expm1(logp), 0) * demand_mult[:, None]
    # shocks: one random walk in log demand per organisation, shared by its segments, whose spread by weeks ahead matches
    # the organisation-level errors of the backtests; then Poisson arrivals
    sig = np.asarray(dem["sigma"], dtype=float)
    inc = np.sqrt(np.maximum(np.diff(np.concatenate([[0.0], sig ** 2])), 1e-8))
    walk = np.cumsum(rng.normal(0, 1, (len(u.orgs), H)) * inc[None, :], axis=1)[u.unit_org]
    lam = np.maximum(np.expm1(logp + walk), 0) * demand_mult[:, None]
    draws = rng.poisson(lam).astype(float)
    out: dict[str, Any] = {"central": {"volume": org_sum(central, u)}, "path": {"volume": org_sum(draws, u)}}
    for key, U in (("central", central), ("path", draws)):
        Vorg = org_sum(U, u)
        if cal.on_time:
            ot = cal.on_time
            load = np.log(np.maximum(Vorg, 1e-9) / np.maximum(ot["base_volume"][:, None] * capacity[:, None], 1e-9))
            p = sigmoid(logit(ot["p_unit"])[:, None] - ot["kappa"] * np.maximum(load[u.unit_org], 0))
            out[key]["on_time"] = org_sum(U * p, u) / np.maximum(Vorg, 1e-9) * 100
        if cal.closure:
            cl = cal.closure
            med = np.full((len(u.orgs), H), np.nan)
            for h in range(H):
                ld = np.maximum(U[:, h], 1e-9) / np.maximum(cl["base_volume_unit"] * capacity[u.unit_org], 1e-9)
                scale = np.maximum(ld, 1.0) ** cl["eta"]
                for i in range(len(u.orgs)):
                    m = u.unit_org == i
                    med[i, h] = mixture_median(cl["F_unit"][m], U[m, h], scale[m], cl["grid"])
            out[key]["median_close_h"] = med
    return out


class World(BaseWorld):
    @classmethod
    def from_instance(cls, ctx: InstanceContext, scenario: dict[str, Any], seed: int) -> "World":
        proto = ctx.yaml("evaluation/protocol.yaml")
        w = scenario.get("world", {})
        t0 = pd.Timestamp(w.get("t0", proto.get("cutoffs", ["2024-01-01"])[-1]))
        H = int(scenario.get("horizon_weeks", w.get("horizon_weeks", proto.get("horizon_weeks", 12))))
        return cls(ctx, scenario, seed, t0.to_pydatetime(), (t0 + pd.Timedelta(weeks=H)).to_pydatetime())

    def __init__(self, ctx: InstanceContext, scenario: dict[str, Any], seed: int, start: datetime, end: datetime, data: ServiceData | None = None) -> None:
        super().__init__(ctx, scenario, seed, start, end)
        self.t0 = pd.Timestamp(start)
        self.H = int(round((pd.Timestamp(end) - self.t0) / pd.Timedelta(weeks=1)))
        self.cfg = ctx.yaml("calibration/service.yaml")
        t_c = time.time()
        if data is None:
            self.data = load_data(ctx)
            self.cal = calibration_for(ctx, self.t0, self.cfg, self.H)
        else:
            self.data = data
            self.cal = calibrate(data, self.t0, self.cfg, self.H)
        self.calibration_s = time.time() - t_c
        for i, o in enumerate(self.cal.units.orgs):
            self.agents[f"org:{self.data.org_names[o]}"] = Agent(id=f"org:{self.data.org_names[o]}", role="organisation", org_unit=self.data.org_names[o])
        for j, name in enumerate(self.cal.units.names):
            self.agents[f"segment:{name}"] = Agent(id=f"segment:{name}", role="requester_segment", org_unit=self.data.org_names[self.cal.units.orgs[self.cal.units.unit_org[j]]])

    def run(self, writer: RunWriter) -> RunSummary:
        self._writer = writer
        t_run = time.time()
        sim = simulate(self.cal, self.seed, self.scenario.get("interventions"), self.data.org_names)
        u = self.cal.units
        orgs = [self.data.org_names[o] for o in u.orgs]
        for h in range(self.H):
            week = self.t0 + pd.Timedelta(weeks=h)
            for i, name in enumerate(orgs):
                attrs = {"week": str(week.date()), "requests": float(sim["path"]["volume"][i, h]), "requests_central": float(sim["central"]["volume"][i, h])}
                for k in ("on_time", "median_close_h"):
                    if k in sim["path"]:
                        attrs[k] = None if not np.isfinite(sim["path"][k][i, h]) else round(float(sim["path"][k][i, h]), 4)
                self.emit(agent_id=f"org:{name}", role="organisation", org_unit=name, activity="weekly_requests", action_type="state", provenance="simulated", attributes=attrs)
            for _ in range(168):
                if self.clock.done:
                    break
                self.clock.advance()
        self.runtime_s = time.time() - t_run
        f = lambda a: [None if not np.isfinite(x) else round(float(x), 4) for x in a]  # noqa: E731
        orgs_out = []
        for i, name in enumerate(orgs):
            row = {"org": name, "tier": int(self.cal.demand["tier_of_org"][i]), "segments": [self.cal.units.names[j].split(" | ", 1)[1] for j in np.flatnonzero(u.unit_org == i)],
                   "start_volume_week": round(float(org_sum(self.cal.Y[:, -4:], u)[i].mean()), 2)}
            for k in sim["central"]:
                row[f"{k}_central"] = f(sim["central"][k][i]); row[k] = f(sim["path"][k][i])
            orgs_out.append(row)
        dem = self.cal.demand
        headline = {"t0": str(self.t0.date()), "horizon_weeks": self.H, "n_orgs": len(orgs), "n_segments": len(u.unit_org), "orgs": orgs_out,
                    "calibration": {"spec_by_tier": dem["spec_by_tier"], "selection": dem["selection"], "mu_by_tier": dem["mu_by_tier"], "inner_error": dem["inner_error"],
                                    "tiers": dem["tiers"], "sigma": dem["sigma"], "inner_cutoffs": dem["inner_cutoffs"], "holidays": {k: round(v, 4) for k, v in self.cal.seasonal.holidays.items()},
                                    "kappa": (self.cal.on_time or {}).get("kappa"), "eta": (self.cal.closure or {}).get("eta"), "seconds": round(self.cal.seconds, 2)},
                    "total_volume": float(sim["path"]["volume"].sum()), "total_volume_central": float(sim["central"]["volume"].sum())}
        return RunSummary(run_id=writer.run_id, instance=self.ctx.id, scenario=self.scenario["id"], seed=self.seed, start=str(self.t0.date()),
                          end=str((self.t0 + pd.Timedelta(weeks=self.H)).date()), ticks=self.clock.tick, events=self._n_events, headline=headline)


# ------------------------------------------------------------------ actual outcomes and comparators

def org_weekly(d: ServiceData, org_codes: list[int], w0: int, w1: int, rows: slice | None = None) -> np.ndarray:
    """Requests per organisation and week for weeks [w0, w1) from the full data (scoring) or a visible slice."""
    lo = int(np.searchsorted(d.week, w0, side="left")); hi = int(np.searchsorted(d.week, w1, side="left"))
    look = np.full(len(d.org_names), -1); look[org_codes] = np.arange(len(org_codes))
    oi = look[d.org[lo:hi]]; ok = oi >= 0
    n_w = w1 - w0
    return np.bincount(oi[ok] * n_w + (d.week[lo:hi][ok] - w0), minlength=len(org_codes) * n_w).reshape(len(org_codes), n_w).astype(float)


def actual_outcomes(d: ServiceData, org_codes: list[int], t0w: int, H: int) -> dict[str, np.ndarray]:
    """Held-out truth: requests per organisation and week, the on-time share and the median hours to close of the
    requests created that week (requests never closed in the data count as not closed)."""
    out = {"volume": org_weekly(d, org_codes, t0w, t0w + H)}
    lo = int(np.searchsorted(d.week, t0w, side="left")); hi = int(np.searchsorted(d.week, t0w + H, side="left"))
    look = np.full(len(d.org_names), -1); look[org_codes] = np.arange(len(org_codes))
    oi = look[d.org[lo:hi]]; ok = oi >= 0
    wk = d.week[lo:hi][ok] - t0w
    if d.on_time is not None:
        ot = d.on_time[lo:hi][ok].astype(float); kn = np.isfinite(ot)
        key = oi[ok][kn] * H + wk[kn]
        n = np.bincount(key, minlength=len(org_codes) * H).reshape(len(org_codes), H)
        k = np.bincount(key, weights=ot[kn], minlength=len(org_codes) * H).reshape(len(org_codes), H)
        out["on_time"] = np.where(n > 0, 100 * k / np.maximum(n, 1), np.nan)
    if d.closed is not None:
        cl, cr = d.closed[lo:hi][ok], d.created[lo:hi][ok]
        dur = np.where(cl != NAT, (cl - cr) / NS_HOUR, np.inf)
        df = pd.DataFrame({"o": oi[ok], "w": wk, "d": dur})
        med = df.groupby(["o", "w"]).d.median().unstack().reindex(index=range(len(org_codes)), columns=range(H))
        out["median_close_h"] = np.where(np.isfinite(med.to_numpy()), med.to_numpy(), np.nan)
    return out


def visible_history(d: ServiceData, cal: Calibrated, cfg: dict[str, Any], hist: int) -> dict[str, np.ndarray]:
    """Each organisation's weekly series as known at t0, for the comparators."""
    oc = cfg.get("on_time") or {}
    v = Visible(d, cal.t0, float(oc.get("deadline_days", 0.0)))
    out = {"volume": org_weekly(d, cal.units.orgs, v.t0w - hist, v.t0w)}
    sl = v.rows_from_week(v.t0w - hist)
    look = np.full(len(d.org_names), -1); look[cal.units.orgs] = np.arange(len(cal.units.orgs))
    oi = look[d.org[sl]]; ok = oi >= 0
    wk = d.week[sl][ok] - (v.t0w - hist)
    n_o = len(cal.units.orgs)
    if d.on_time is not None and cal.on_time:
        ot = v.on_time(sl)[ok]; kn = np.isfinite(ot)
        key = oi[ok][kn] * hist + wk[kn]
        n = np.bincount(key, minlength=n_o * hist).reshape(n_o, hist); k = np.bincount(key, weights=ot[kn], minlength=n_o * hist).reshape(n_o, hist)
        lag = int(math.ceil(float(oc["deadline_days"]) / 7.0))
        s = np.where(n > 0, 100 * k / np.maximum(n, 1), np.nan)[:, :hist - lag]          # weeks fully past the deadline
        out["on_time"] = s
    if d.closed is not None and cal.closure:
        dur, obs = v.duration_h(sl)
        dur = np.where(obs, dur, np.inf)[ok]
        df = pd.DataFrame({"o": oi[ok], "w": wk, "d": dur})
        med = df.groupby(["o", "w"]).d.median().unstack().reindex(index=range(n_o), columns=range(hist)).to_numpy()
        out["median_close_h"] = np.where(np.isfinite(med), med, np.nan)
    return out


def _clean(y: np.ndarray) -> np.ndarray:
    """Forward- then back-fill missing weeks (a week whose median was not yet known at t0)."""
    s = pd.Series(y).ffill().bfill()
    return s.to_numpy() if s.notna().all() else np.zeros(len(y))


def comparator_forecasts(series: np.ndarray, H: int, kind: str, lag: int = 0) -> dict[str, np.ndarray]:
    """Classical forecasts per organisation (rows) for the H weeks after the cutoff. `lag` weeks between the last
    known week and the cutoff are forecast too and dropped (on-time flags are known only after their deadline)."""
    log = kind in ("volume", "median_close_h")
    K = H + lag
    out = {k: np.zeros((series.shape[0], H)) for k in ("carry_forward", "recent_average", "historical_average", "seasonal_naive", "trend", "ets")}
    for i, y in enumerate(series):
        y = _clean(np.asarray(y, dtype=float))
        y = np.maximum(y, 0)
        f = {"carry_forward": fc.carry_forward(y, K, 1, log=log),
             "recent_average": fc.carry_forward(y, K, 4, log=log),
             "historical_average": fc.carry_forward(y, K, 52, log=log),
             "seasonal_naive": fc.seasonal_naive(y, K, 52, log=log),
             "trend": fc.trend(y, K, 26, log=log)}
        try:
            f["ets"] = fc.auto_ets(y, K, 1, log=log, max_history=156)
        except (ValueError, FloatingPointError, OverflowError):
            f["ets"] = f["carry_forward"]
        for k, val in f.items():
            val = np.maximum(np.asarray(val, dtype=float), 0)
            out[k][i] = np.minimum(val, 100.0)[lag:] if kind == "on_time" else val[lag:]
    return out


COMPARATOR_LABELS = {"carry_forward": "Last week carried forward", "recent_average": "Average of the last four weeks",
                     "historical_average": "Average of the last 52 weeks", "seasonal_naive": "Same week last year",
                     "trend": "Trend of the last 26 weeks", "ets": "Exponential smoothing (ETS, AICc)"}


# ------------------------------------------------------------------ scoring helpers

def _wape(p: np.ndarray, a: np.ndarray) -> float:
    ok = np.isfinite(p) & np.isfinite(a)
    d = float(np.abs(a[ok]).sum())
    return float(np.abs(p[ok] - a[ok]).sum() / d) if d > 0 else float("nan")


def _mae(p: np.ndarray, a: np.ndarray) -> float:
    ok = np.isfinite(p) & np.isfinite(a)
    return float(np.abs(p[ok] - a[ok]).mean()) if ok.any() else float("nan")


def _mape(p: np.ndarray, a: np.ndarray) -> float:
    ok = np.isfinite(p) & np.isfinite(a) & (a > 0)
    return float((np.abs(p[ok] - a[ok]) / a[ok]).mean()) if ok.any() else float("nan")


SCORERS = {"wape": _wape, "mae": _mae, "mape": _mape}


def score_window(pred: dict[str, np.ndarray], comps: dict[str, dict[str, np.ndarray]], act: dict[str, np.ndarray], metrics: dict[str, dict[str, Any]],
                 groups: dict[str, np.ndarray]) -> dict[str, Any]:
    """Errors of the simulation and every comparator for one cutoff, per outcome and organisation group."""
    out: dict[str, Any] = {}
    for oc, spec in metrics.items():
        if oc not in act or oc not in pred:
            continue
        fn = SCORERS[spec["measure"]]
        for gname, gmask in groups.items():
            key = oc if gname == "all" else f"{oc}:{gname}"
            a = act[oc][gmask]
            row = {"simulation": fn(pred[oc][gmask], a), "actual_mean": float(np.nanmean(a)) if np.isfinite(a).any() else float("nan"), "n": int(np.isfinite(a).sum())}
            for c, f in comps[oc].items():
                row[c] = fn(f[gmask], a)
            if spec["measure"] == "wape":      # the same errors in units per organisation-week, for the staffing arithmetic
                row["mae_units"] = {"simulation": _mae(pred[oc][gmask], a), **{c: _mae(f[gmask], a) for c, f in comps[oc].items()}}
            out[key] = row
    return out


def _mean(xs) -> float:
    xs = [x for x in xs if x is not None and np.isfinite(x)]
    return float(np.mean(xs)) if xs else float("nan")


def summarise(windows: list[dict[str, Any]], keys: list[str], comparators: list[str]) -> dict[str, Any]:
    """Average each error over cutoffs (each cutoff weighs the same), name the best comparator, error reduction and
    accuracy = 100 x (1 - error / mean actual) (for WAPE and MAPE the error is already relative)."""
    out = {}
    for key in keys:
        rows = [w["scores"][key] for w in windows if key in w["scores"]]
        if not rows:
            continue
        s = {"simulation": _mean([r["simulation"] for r in rows])}
        for c in comparators:
            s[c] = _mean([r[c] for r in rows])
        best = min(comparators, key=lambda c: s[c] if np.isfinite(s[c]) else float("inf"))
        mean_actual = _mean([r["actual_mean"] for r in rows])
        rel = lambda e: e * 100 if key.split(":")[0] in RELATIVE else 100 * e / mean_actual  # noqa: E731
        out[key] = {"errors": s, "best_baseline": best, "error_reduction_pct": 100 * (1 - s["simulation"] / s[best]) if s[best] else None,
                    "beats_best_baseline": bool(s["simulation"] < s[best]), "mean_actual": mean_actual, "n_windows": len(rows),
                    "n_predictions": int(sum(r["n"] for r in rows)),
                    "accuracy_pct": {k: 100 - rel(v) for k, v in s.items()}}
        if all("mae_units" in r for r in rows):
            out[key]["mae_units"] = {k: _mean([r["mae_units"][k] for r in rows]) for k in ["simulation", *comparators]}
    return out


RELATIVE = {"volume", "median_close_h"}   # scored as WAPE / MAPE (already relative); on_time as MAE in points


# ------------------------------------------------------------------ evaluation

def _run_world(ctx: InstanceContext, scenario: dict[str, Any], seed: int, t0: str) -> RunSummary:
    sc = json.loads(json.dumps(scenario))
    sc.setdefault("world", {})["t0"] = t0
    writer = RunWriter(ctx.id, sc["id"], config={"instance": ctx.id, "scenario": sc, "seed": seed, "evaluation": True})
    world = World.from_instance(ctx, sc, seed)
    summary = world.run(writer)
    writer.close(summary.to_json())
    print(f"[{ctx.id}] eval run {sc['id']} t0={t0} seed={seed} -> {writer.run_id} (calibration {world.calibration_s:.1f}s, run {world.runtime_s:.1f}s)", flush=True)
    return summary


def org_groups(names: list[str], proto: dict[str, Any]) -> dict[str, np.ndarray]:
    g = {"all": np.ones(len(names), dtype=bool)}
    for gname, spec in (proto.get("groups") or {}).items():
        excl = set(spec.get("exclude", []))
        g[gname] = np.array([n not in excl for n in names])
    return g


def forecast_cutoff(ctx: InstanceContext, d: ServiceData, cutoff: str, cfg: dict[str, Any], proto: dict[str, Any], seeds: list[int],
                    scenario: dict[str, Any] | None = None, write_runs: bool = True, comp_cache: dict | None = None) -> dict[str, Any]:
    """One prediction window: simulate (central path + seeds), compute comparators from data before the cutoff and
    score both against the held-out weeks."""
    H = int(proto["horizon_weeks"])
    t0 = pd.Timestamp(cutoff)
    if write_runs:
        summaries = [_run_world(ctx, scenario, s, cutoff) for s in seeds]
        cal = calibration_for(ctx, t0, cfg, H)
        heads = [s.headline for s in summaries]
        run_ids = [s.run_id for s in summaries]
        pred = {k: np.array([o[f"{k}_central"] for o in heads[0]["orgs"]], dtype=float) for k in ("volume", "on_time", "median_close_h") if f"{k}_central" in heads[0]["orgs"][0]}
        paths = {k: np.stack([np.array([o[k] for o in h["orgs"]], dtype=float) for h in heads]) for k in pred}
    else:
        cal = calibrate(d, t0, cfg, H)
        sims = [simulate(cal, s) for s in seeds]
        run_ids = []
        pred = {k: np.asarray(v, dtype=float) for k, v in sims[0]["central"].items()}
        paths = {k: np.stack([s["path"][k] for s in sims]) for k in pred}
    names = [d.org_names[o] for o in cal.units.orgs]
    t0w = week_index(t0)
    act = actual_outcomes(d, cal.units.orgs, t0w, H)
    ckey = (cutoff, tuple(cal.units.orgs), tuple(sorted(pred)))
    if comp_cache is not None and ckey in comp_cache:
        comps = comp_cache[ckey]
    else:
        hist = visible_history(d, cal, cfg, int(proto.get("comparator_history_weeks", 156)))
        lag = int(math.ceil(float((cfg.get("on_time") or {}).get("deadline_days", 0)) / 7.0))
        comps = {k: comparator_forecasts(hist[k], H, k, lag if k == "on_time" else 0) for k in pred if k in hist}
        if comp_cache is not None:
            comp_cache[ckey] = comps
    groups = org_groups(names, proto)
    scores = score_window(pred, comps, act, proto["metrics"], groups)
    by_h = {}
    for hb, (a_, b_) in (proto.get("horizon_buckets") or {"1-4": [1, 4], "5-12": [5, 12]}).items():
        sl = slice(a_ - 1, b_)
        by_h[hb] = {"simulation": _wape(pred["volume"][:, sl], act["volume"][:, sl]), **{c: _wape(f[:, sl], act["volume"][:, sl]) for c, f in comps["volume"].items()}}
    lo, hi = np.nanquantile(paths["volume"], 0.05, axis=0), np.nanquantile(paths["volume"], 0.95, axis=0)
    cover = float(((act["volume"] >= lo) & (act["volume"] <= hi)).mean()) if len(seeds) > 1 else None
    per_org = [{"org": n, "tier": int(cal.demand["tier_of_org"][i]),
                **{f"{k}_actual": [None if not np.isfinite(x) else round(float(x), 3) for x in act[k][i]] for k in pred if k in act},
                **{f"{k}_simulation": [None if not np.isfinite(x) else round(float(x), 3) for x in pred[k][i]] for k in pred},
                **{f"{k}_{c}": [round(float(x), 3) for x in f[i]] for k in comps for c, f in comps[k].items()}} for i, n in enumerate(names)]
    return {"cutoff": str(t0.date()), "n_orgs": len(names), "orgs": names, "scores": scores, "by_horizon": by_h, "coverage90": cover, "run_ids": run_ids,
            "calibration": {"spec_by_tier": cal.demand["spec_by_tier"], "selection": cal.demand["selection"], "tier_of_org": cal.demand["tier_of_org"],
                            "kappa": (cal.on_time or {}).get("kappa"), "eta": (cal.closure or {}).get("eta"), "seconds": round(cal.seconds, 1)},
            "totals": {"actual": float(act["volume"].sum()), "simulation": float(pred["volume"].sum()), **{c: float(f.sum()) for c, f in comps["volume"].items()}},
            "per_org": per_org}


def evaluate(ctx: InstanceContext, scenario_ids: list[str]) -> dict[str, Any]:
    from ..scenarios import load_scenario
    proto = ctx.yaml("evaluation/protocol.yaml")
    cfg = ctx.yaml("calibration/service.yaml")
    d = load_data(ctx)
    cutoffs = [str(c) for c in proto["cutoffs"]]
    dev = set(str(c) for c in proto.get("dev_cutoffs", []))
    seeds = [int(s) for s in proto.get("seeds", [1])]
    base_id = proto.get("baseline_scenario", "baseline")
    base = load_scenario(ctx, base_id)
    windows = []
    for c in cutoffs:
        w = forecast_cutoff(ctx, d, c, cfg, proto, seeds, base, write_runs=True)
        w["split"] = "dev" if c in dev else "held_out"
        windows.append(w)
        s = w["scores"].get("volume", {})
        print(f"[{ctx.id}] {c} ({w['split']}): volume WAPE simulation {s.get('simulation', float('nan')):.3f}, ets {s.get('ets', float('nan')):.3f}, recent {s.get('recent_average', float('nan')):.3f}", flush=True)
    comparators = list(COMPARATOR_LABELS)
    keys = sorted({k for w in windows for k in w["scores"]})
    accuracy = {split: summarise([w for w in windows if split == "all" or w["split"] == split], keys, comparators) for split in ("held_out", "dev", "all")}
    by_h = {split: {hb: {k: _mean([w["by_horizon"][hb][k] for w in windows if split == "all" or w["split"] == split]) for k in ["simulation", *comparators]}
                    for hb in windows[0]["by_horizon"]} for split in ("held_out", "all")}
    coverage = {split: _mean([w["coverage90"] for w in windows if split == "all" or w["split"] == split]) for split in ("held_out", "all")}
    # the organisations' total weekly requests per window (one number per cutoff), for the staffing view
    bv_windows = [{"cutoff": w["cutoff"], "split": w["split"], "actual": w["totals"]["actual"] / proto["horizon_weeks"],
                   "simulated": w["totals"]["simulation"] / proto["horizon_weeks"], "baselines": {c: w["totals"][c] / proto["horizon_weeks"] for c in comparators}} for w in windows]
    business_validation = []
    for split in ("held_out", "all"):
        ws = [x for x in bv_windows if split == "all" or x["split"] == split]
        sim_mae = _mean([abs(x["simulated"] - x["actual"]) for x in ws])
        bmae = {c: _mean([abs(x["baselines"][c] - x["actual"]) for x in ws]) for c in comparators}
        best = min(bmae, key=bmae.get)
        business_validation.append({"id": f"total_weekly_volume_{split}", "split": split, "windows": ws, "simulation_mae": sim_mae, "baseline_mae": bmae, "best_baseline": best,
                                    "beats_best_baseline": sim_mae < bmae[best], "error_reduction_pct": 100 * (1 - sim_mae / bmae[best]) if bmae[best] else None,
                                    "mean_actual": _mean([x["actual"] for x in ws])})
    # alternative scenario at the last cutoffs, same seeds
    run_ids = {base_id: [r for w in windows for r in w["run_ids"]]}
    scen_rows = []
    alt_cut = cutoffs[-int(proto.get("alternative_cutoffs", 4)):]
    for sid in [s for s in scenario_ids if s != base_id]:
        sc = load_scenario(ctx, sid)
        run_ids[sid] = []
        heads = []
        for c in alt_cut:
            for s in seeds:
                summ = _run_world(ctx, sc, s, c)
                run_ids[sid].append(summ.run_id); heads.append(summ.headline)
        row = {"scenario": sid, "title": sc.get("title", sid), "short_title": sc.get("short_title", sid), "cutoffs": alt_cut, "runs": len(heads), "outcomes": {}}
        base_w = [w for w in windows if w["cutoff"] in alt_cut]
        for k in ("volume", "on_time", "median_close_h"):
            if f"{k}_central" not in heads[0]["orgs"][0]:
                continue
            alt_v = _mean([x for h in heads[:: len(seeds)] for o in h["orgs"] for x in o[f"{k}_central"] if x is not None])
            base_v = _mean([x for w in base_w for o in w["per_org"] for x in o[f"{k}_simulation"] if x is not None])
            row["outcomes"][k] = {"baseline": base_v, "alternative": alt_v}
        scen_rows.append(row)
    held = accuracy["held_out"]
    headline = {}
    for key, spec in proto["metrics"].items():
        if key in held:
            h = held[key]
            headline[key] = {"label": spec["label"], "unit": spec.get("unit", ""), "measure": spec["measure"], "simulated": h["errors"]["simulation"],
                             "baseline": h["errors"][h["best_baseline"]], "best_baseline": h["best_baseline"], "error_reduction_pct": h["error_reduction_pct"],
                             "accuracy_pct": h["accuracy_pct"]["simulation"], "mean_actual": h["mean_actual"], "better": "lower"}
    result = {"instance": ctx.id, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"), "scenarios": [base_id] + [s for s in scenario_ids if s != base_id],
              "protocol": {"cutoffs": cutoffs, "dev_cutoffs": sorted(dev), "held_out_cutoffs": [c for c in cutoffs if c not in dev], "horizon_weeks": proto["horizon_weeks"],
                           "seeds": seeds, "n_orgs": cfg["n_orgs"], "metrics": proto["metrics"], "groups": proto.get("groups", {}), "data_end": proto.get("data_end")},
              "comparator_labels": COMPARATOR_LABELS, "run_ids": run_ids, "headline": headline, "accuracy": accuracy, "by_horizon": by_h, "coverage90": coverage,
              "business_validation": business_validation, "scenario_comparison": scen_rows,
              "windows": [{k: v for k, v in w.items()} for w in windows]}
    out = ctx.runs_dir / "evaluation.json"
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


# ------------------------------------------------------------------ results view

def results_view(ctx: InstanceContext) -> dict[str, Any]:
    """Held-out accuracy first: actual weekly requests per organisation against the simulation and the best
    classical forecast, then the alternative."""
    doc = base_document(ctx)
    p = ctx.runs_dir / "evaluation.json"
    ev = json.loads(p.read_text()) if p.exists() else {}
    if not ev:
        doc.update({"sources": [], "metrics": [], "effects": [], "charts": [], "hero": {"kicker": "Not evaluated yet", "stats": [], "claim": "", "chart": None}})
        return doc
    proto = ev["protocol"]; labels = ev["comparator_labels"]
    held = ev["accuracy"]["held_out"]
    H = proto["horizon_weeks"]
    org = (proto["metrics"].get("volume") or {}).get("org_word", "organisation"); orgs = org[:-1] + "ies" if org.endswith("y") else org + "s"
    unit_word = (proto.get("metrics", {}).get("volume") or {}).get("unit_word", "requests")
    base = doc["scenarios"]["baseline"]; alt = doc["scenarios"].get("alternative")
    sources = [{"id": "actual", "label": "Actual outcome", "kind": "actual", "kind_label": "Actual outcome (actual data)", "short": "Actual outcome", "scenario": base["id"],
                "note": f"Weekly {unit_word} of each {org} in the {H} weeks after each of {len(proto['held_out_cutoffs'])} held-out cutoffs."},
               {"id": "baseline", "label": "Simulation prediction", "kind": "simulated", "kind_label": "Simulation prediction", "short": "Simulation prediction", "scenario": base["id"],
                "runs": len(ev["run_ids"].get(base["id"], [])), "note": "Central path of the simulation at each cutoff, calibrated on data before it."}]
    metrics = []
    for key, h in held.items():
        m = proto["metrics"].get(key.split(":")[0], {})
        grp = key.split(":")[1] if ":" in key else None
        best = h["best_baseline"]
        metrics.append({"id": key, "label": m.get("label", key) + (f" ({(proto.get('groups') or {}).get(grp, {}).get('label', grp)})" if grp else ""),
                        "unit": "%" if m.get("measure") in ("wape", "mape") else m.get("unit", ""), "better": "lower",
                        "values": {"baseline": round(100 * h["errors"]["simulation"], 2) if m.get("measure") in ("wape", "mape") else round(h["errors"]["simulation"], 3),
                                   "actual": None},
                        "intervals": {}, "note": f"Best classical forecast: {labels[best]} ({(100 * h['errors'][best]) if m.get('measure') in ('wape', 'mape') else h['errors'][best]:.2f}); error reduction {h['error_reduction_pct']:.1f}%."})
    # chart: per-cutoff error, simulation vs best comparator
    vol = held.get("volume")
    charts = []
    if vol:
        best = vol["best_baseline"]
        wins = ev["windows"]
        charts.append({"id": "volume_error_by_cutoff", "type": "line", "title": f"Error in each {org}'s weekly {unit_word}, by cutoff", "x_label": "cutoff", "y_label": "% of actual (WAPE)",
                       "x": [w["cutoff"] for w in wins], "series": [{"name": "Simulation prediction", "y": [round(100 * w["scores"]["volume"]["simulation"], 2) for w in wins], "source": "baseline"},
                                                                     {"name": labels[best], "y": [round(100 * w["scores"]["volume"][best], 2) for w in wins], "dashed": True, "source": "actual"}],
                       "note": "Cutoffs before " + (proto["held_out_cutoffs"][0] if proto["held_out_cutoffs"] else "") + " were used to make design choices; the rest are held out."})
        tot = [w for w in ev["windows"] if w["split"] == "held_out"]
        charts.append({"id": "total_weekly", "type": "line", "title": f"Weekly {unit_word} of the leading {orgs}, average over the {H} weeks after each cutoff", "x_label": "cutoff", "y_label": unit_word,
                       "x": [w["cutoff"] for w in tot], "series": [{"name": "Actual outcome", "y": [round(w["totals"]["actual"] / H, 1) for w in tot], "source": "actual"},
                                                                    {"name": "Simulation prediction", "y": [round(w["totals"]["simulation"] / H, 1) for w in tot], "source": "baseline"},
                                                                    {"name": labels[best], "y": [round(w["totals"][best] / H, 1) for w in tot], "dashed": True}], "note": ""})
    stats = []
    if vol:
        stats = [{"label": f"Error in weekly {unit_word} per {org}, simulation", "value": round(100 * vol["errors"]["simulation"], 1), "unit": "%"},
                 {"label": f"Best classical forecast ({labels[vol['best_baseline']]})", "value": round(100 * vol["errors"][vol["best_baseline"]], 1), "unit": "%"},
                 {"label": "Error reduction", "value": round(vol["error_reduction_pct"], 1), "unit": "%"},
                 {"label": "Accuracy, simulation", "value": round(vol["accuracy_pct"]["simulation"], 1), "unit": "%"}]
    hero = {"kicker": f"{len(proto['held_out_cutoffs'])} held-out cutoffs, {H} weeks each", "stats": stats,
            "claim": "Every prediction uses only data before its cutoff; design choices were made on the first quarter of cutoffs and frozen before the rest were scored.",
            "chart": "volume_error_by_cutoff"}
    doc.update({"sources": sources, "metrics": metrics, "effects": [], "charts": charts, "hero": hero, "evaluation": {"generated": ev.get("generated"), "protocol": proto}})
    row = next((r for r in ev.get("scenario_comparison", []) if alt and r["scenario"] == alt["id"]), None)
    if row and row["outcomes"]:
        names = {"volume": f"Weekly {unit_word} per {org}", "on_time": "Answered on time (%)", "median_close_h": "Median hours to close"}
        stats = [{"label": names[k], "value": f"{v['baseline']:.1f} → {v['alternative']:.1f}", "unit": ""} for k, v in row["outcomes"].items() if k != "volume"]
        doc["hero"]["alternative"] = {"kicker": f"Alternative: {alt['short_title']}", "stats": stats,
                                      "text": f"{alt.get('description', '').strip()} Simulated at the last {len(row['cutoffs'])} cutoffs with the same seeds; a model estimate, not an observed effect."}
        sources.append({"id": "alternative", "label": f"{alt['title']} · simulation prediction", "kind": "simulated", "kind_label": "Alternative simulation prediction",
                        "short": alt["short_title"], "scenario": alt["id"], "runs": row["runs"], "note": f"Cutoffs {', '.join(row['cutoffs'])}."})
        for k, v in row["outcomes"].items():
            doc["metrics"].append({"id": f"alt_{k}", "label": names[k] + " (simulated, last cutoffs)", "unit": "", "better": "", "values": {"baseline": round(v["baseline"], 2), "alternative": round(v["alternative"], 2), "actual": None},
                                   "intervals": {}, "note": "Simulated only; matching cutoffs and seeds."})
    return doc


def build_report(ctx: InstanceContext) -> dict[str, Any]:
    """reports/report.json for a service-world instance, every number read from runs/<id>/evaluation.json."""
    ev = json.loads((ctx.runs_dir / "evaluation.json").read_text())
    proto, labels, H = ev["protocol"], ev["comparator_labels"], ev["protocol"]["horizon_weeks"]
    held = ev["accuracy"]["held_out"]
    unit_word = (proto["metrics"].get("volume") or {}).get("unit_word", "requests")
    org = (proto["metrics"].get("volume") or {}).get("org_word", "organisation"); orgs = org[:-1] + "ies" if org.endswith("y") else org + "s"
    pct = lambda x: "n/a" if x is None else f"{x:.1f}%"  # noqa: E731
    v = held["volume"]; b = v["best_baseline"]
    takeaways = [f"On {len(proto['held_out_cutoffs'])} held-out cutoffs the simulation's error in each {org}'s weekly {unit_word} over the next {H} weeks was "
                 f"{pct(100 * v['errors']['simulation'])}, against {pct(100 * v['errors'][b])} for the best classical forecast ({labels[b]}): "
                 f"{pct(v['error_reduction_pct'])} lower error, accuracy {pct(v['accuracy_pct']['simulation'])}."]
    for key, s in held.items():
        if key == "volume":
            continue
        m = proto["metrics"][key.split(":")[0]]
        grp = (proto.get("groups") or {}).get(key.split(":")[1], {}).get("label") if ":" in key else None
        e = (lambda x: pct(100 * x)) if m["measure"] in ("wape", "mape") else (lambda x: f"{x:.2f} points")
        takeaways.append(f"{m['label']}{', ' + grp if grp else ''}: simulation {e(s['errors']['simulation'])}, best classical forecast ({labels[s['best_baseline']]}) "
                         f"{e(s['errors'][s['best_baseline']])}; error reduction {pct(s['error_reduction_pct'])}.")
    takeaways.append(f"The simulation's 90% range contained {pct(100 * ev['coverage90']['held_out'])} of actual {org}-weeks.")
    sections = [{"heading": "How the predictions were made", "body": (
        f"At each Monday cutoff the leading {orgs} are carried forward {H} weeks from data before the cutoff only. "
        f"The first {len(proto['dev_cutoffs'])} cutoffs were used to choose the design; the remaining {len(proto['held_out_cutoffs'])} were run once after it was frozen. "
        f"Classical forecasts of each {org}'s own weekly series are scored on the same weeks."), "charts": ["volume_error_by_cutoff"], "metrics": []}]
    report = {"title": ctx.meta.get("title", ctx.id), "subtitle": ctx.meta.get("problem", ""), "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "takeaways": takeaways, "sections": sections, "charts": [], "metrics": []}
    (ctx.reports_dir / "report.json").write_text(json.dumps(report, indent=1))
    return report
