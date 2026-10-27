"""Market world: companies (apps) whose workloads run on AI models, priced by the published list prices.

Two layers, both carried forward week by week from a cutoff t0 for a horizon of H weeks:

  Companies. Each app in the leading N at t0 is an agent with a token volume (log level) and a growth rate. Weekly,
  growth decays towards its segment's typical growth (damping phi), the level moves by growth plus a shock that is
  partly shared with the whole market (loading kappa), and volume responds to the change in the segment's blended
  price (elasticity). Every parameter is fitted at t0 from weeks before t0 only: phi and the weight on the app's own
  recent growth are chosen by backtests whose targets also end before t0; shock sizes come from those backtest errors.

  Workloads. Each use-case segment (programming, roleplay, ...) holds K workload agents, each running on one model.
  Weekly a workload re-chooses with probability 1 - inertia; the kernel offers the models listed that week with logit
  weights from the model's standing at t0, its list price and, for models launched after t0, a launch prior learned
  from launches before t0. The seat policy (rule by default; an LLM seat is a configuration change) picks one option.
  Segment model mixes times list prices give each segment's blended price, and each company's spend is its tokens
  times its segment's blended price.

Inputs after t0 are the published price lists and the dates new models were listed (exogenous, as arrivals are in
the process world); usage after t0 is read only by evaluate() for scoring. Spend is at list prices: caching and
negotiated discounts make realised spend lower.
"""
from __future__ import annotations

import itertools
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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

WEEK = pd.Timedelta(days=7)
USAGE_SEGMENT = {"coding": "programming", "creative": "roleplay", "entertainment": "roleplay"}   # others: whole market


# ------------------------------------------------------------------ data

@dataclass
class MarketData:
    mw: pd.DataFrame        # model_weekly
    cw: pd.DataFrame        # category_weekly
    aw: pd.DataFrame        # app_weekly
    apps: pd.DataFrame
    thr: pd.DataFrame
    pw: pd.DataFrame        # price_weekly
    models: pd.DataFrame
    catalog: pd.DataFrame   # every listed model with its launch date (price lists)


@lru_cache(maxsize=2)
def _load(root: str, mtime: float) -> MarketData:
    from pathlib import Path
    n = Path(root)
    r = lambda name: pd.read_parquet(n / f"{name}.parquet")  # noqa: E731
    return MarketData(r("model_weekly"), r("category_weekly"), r("app_weekly"), r("apps"), r("rank_threshold"), r("price_weekly"), r("models"), r("catalog"))


def load_data(ctx: InstanceContext) -> MarketData:
    p = ctx.data_normalized / "app_weekly.parquet"
    if not p.exists():
        raise FileNotFoundError(f"{p} missing; run `orgsim ingest {ctx.id}`")
    return _load(str(ctx.data_normalized), p.stat().st_mtime)


def app_matrix(d: MarketData, weeks: list[pd.Timestamp], app_ids: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """tokens[app, week]; weeks where an app is outside the top 200 get half the 200th app's volume (flag = censored)."""
    a = d.aw[d.aw.week.isin(weeks) & d.aw.app_id.isin(app_ids)].pivot_table(index="app_id", columns="week", values="tokens", aggfunc="sum")
    a = a.reindex(index=app_ids, columns=weeks)
    cens = a.isna().to_numpy()
    thr = d.thr.set_index("week").tokens_rank200.reindex(weeks).to_numpy()
    fill = np.broadcast_to(0.5 * thr, a.shape)
    x = np.where(cens, fill, a.to_numpy())
    return x.astype(float), cens


def segment_of(apps: pd.DataFrame) -> pd.Series:
    return apps.category.map(USAGE_SEGMENT).fillna("market")


def segment_mix(d: MarketData, segment: str, week: pd.Timestamp) -> pd.Series:
    """Model shares of a segment in one week (programming/roleplay from the use-case data, else the whole market)."""
    src = d.mw[d.mw.model != "other"] if segment == "market" else d.cw[d.cw.category == segment]
    x = src[src.week == week].set_index("model").tokens
    if x.sum() <= 0:                                   # a week absent from the source: the latest earlier week
        prev = src[src.week < week].week.max()
        x = src[src.week == prev].set_index("model").tokens if pd.notna(prev) else x
    return x / x.sum() if x.sum() > 0 else x


def blended_price(mix: pd.Series, prices: pd.Series) -> float:
    """Token-weighted list price (USD per million tokens) over the models with a known price."""
    p = prices.reindex(mix.index)
    ok = p.notna()
    return float((mix[ok] * p[ok]).sum() / mix[ok].sum()) if ok.any() and mix[ok].sum() > 0 else float("nan")


# ------------------------------------------------------------------ calibration (pre-cutoff only)

def start_level(ylog: np.ndarray, k_level: int) -> np.ndarray:
    return np.log(np.mean(np.exp(ylog[:, -k_level:]), axis=1))


def own_slope(ylog: np.ndarray, slope_weeks: int = 6) -> np.ndarray:
    k = min(slope_weeks, ylog.shape[1] - 1)
    tt = np.arange(k + 1) - k / 2
    return ((ylog[:, -k - 1:] - ylog[:, -k - 1:].mean(1, keepdims=True)) * tt).sum(1) / (tt ** 2).sum()


def blended_start(ylog: np.ndarray, k_level: Any, alpha: np.ndarray) -> np.ndarray:
    """Starting log level per app: the mean of its last k weeks, blended (weight 1 - alpha) with its last four weeks."""
    k = np.broadcast_to(np.asarray(k_level), (ylog.shape[0],))
    lvl_k = np.empty(ylog.shape[0])
    for kk in np.unique(k):
        lvl_k[k == kk] = start_level(ylog[k == kk], int(kk))
    return alpha * lvl_k + (1 - alpha) * start_level(ylog, 4)


def damped_paths(ylog: np.ndarray, H: int, phi: Any, w: Any, mu: np.ndarray, k_level: Any = 2, alpha: Any = 1.0) -> np.ndarray:
    """Point paths of log volume for H weeks after the last column of ylog (apps x weeks). Parameters may be scalars or
    per-app arrays. alpha < 1 blends the path with the recent four-week level held flat (start level and growth shrink
    towards it); alpha = 1 is the pure damped path."""
    a = np.broadcast_to(np.asarray(alpha, dtype=float), (ylog.shape[0],))
    lvl = blended_start(ylog, k_level, a)
    mu_e = a * mu
    g = a * (w * own_slope(ylog) + (1 - w) * mu)
    out = np.empty((ylog.shape[0], H))
    for h in range(H):
        g = phi * g + (1 - phi) * mu_e
        lvl = lvl + g
        out[:, h] = lvl
    return out


def wmedian(v: np.ndarray, wt: np.ndarray) -> float:
    o = np.argsort(v)
    c = np.cumsum(wt[o])
    return float(v[o][np.searchsorted(c, 0.5 * c[-1])])


PERSISTENCE = ("burst", "recurring", "steady")


def persistence_class(d: MarketData, ids: list[int], t0: pd.Timestamp, weeks: int = 8) -> np.ndarray:
    """Weeks an app was ranked in the top 200 out of the `weeks` before t0: burst (1-3), recurring (4-7), steady (all).
    Many leading apps are one-off jobs (evaluations, data pipelines) that rank for a week or two and vanish."""
    recent = d.aw[(d.aw.week < t0) & (d.aw.week >= t0 - weeks * WEEK)]
    n = recent.groupby("app_id").week.nunique()
    k = np.array([n.get(i, 0) for i in ids])
    return np.where(k >= weeks, "steady", np.where(k >= 4, "recurring", "burst"))


def fill_level(d: MarketData, t0: pd.Timestamp) -> float:
    """Volume recorded for an app outside the top 200: half the 200th app's volume, its median over the 4 weeks before t0."""
    t = d.thr[(d.thr.week < t0) & (d.thr.week >= t0 - 4 * WEEK)].tokens_rank200
    return float(0.5 * t.median()) if len(t) else 0.0


def survival_curves(folds: list[dict[str, Any]], H: int) -> dict[str, list[float]]:
    """Share of leading apps of each persistence class still ranked h weeks after a cutoff (made non-increasing)."""
    out = {}
    for c in PERSISTENCE:
        rows = [~f["cens"][f["cls"] == c] for f in folds if (f["cls"] == c).any()]
        if not rows or sum(len(r) for r in rows) < 10:
            out[c] = [1.0] * H
            continue
        pres = np.concatenate(rows, axis=0).mean(0)
        out[c] = np.minimum.accumulate(pres).round(4).tolist()
    return out


def forward_drift(folds: list[dict[str, Any]], k: int, H: int) -> dict[str, float]:
    """Typical realised weekly log growth after a cutoff of leading apps that stay ranked, per persistence class,
    weighted by starting volume. Leading apps are chosen on recent volume, so this includes their regression."""
    hs = np.arange(1, H + 1)
    G, V, S = [], [], []
    for f in folds:
        l0 = start_level(f["ylog"], k)
        r = np.log(f["y"]) - l0[:, None]
        m = ~f["cens"]
        num = (np.where(m, r, 0) * hs).sum(1); den = (np.where(m, hs, 0) ** 2).sum(1)
        ok = den > 0
        G.append(f["cls"][ok]); V.append(np.exp(l0[ok])); S.append(num[ok] / den[ok])
    if not G:
        return {"_all": 0.0}
    G, V, S = np.concatenate(G), np.concatenate(V), np.concatenate(S)
    out = {"_all": float(np.clip(wmedian(S, V), -0.2, 0.2))}
    for c in PERSISTENCE:
        m = G == c
        out[c] = float(np.clip(wmedian(S[m], V[m]), -0.2, 0.2)) if m.sum() >= 20 else out["_all"]
    return out


SPEC_KEYS = ("k_level", "drift", "phi", "w", "alpha", "survival_point")


def class_arrays(cls: np.ndarray, spec: dict[str, dict[str, Any]], mu: dict[str, float]) -> dict[str, np.ndarray]:
    """Per-app parameter arrays from per-class specifications."""
    get = lambda key: np.array([spec[c][key] for c in cls])  # noqa: E731
    return {"k_level": get("k_level").astype(int), "phi": get("phi").astype(float), "w": get("w").astype(float), "alpha": get("alpha").astype(float),
            "expected": get("survival_point") == "expected", "mu": np.array([mu.get(c, mu["_all"]) for c in cls])}


def point_paths(f: dict[str, Any], H: int, arr: dict[str, np.ndarray], surv: dict[str, list[float]]) -> np.ndarray:
    """Point path of each app's weekly volume. While an app is more likely than not to stay ranked the point is its
    volume path, else the unranked volume ("median"); or the survival-weighted mix of the two ("expected")."""
    path = np.exp(damped_paths(f["ylog"], H, arr["phi"], arr["w"], arr["mu"], arr["k_level"], arr["alpha"]))
    s = np.array([surv[c] for c in f["cls"]])
    med = np.where(s >= 0.5, path, f["fill"])
    return np.where(arr["expected"][:, None], s * path + (1 - s) * f["fill"], med)


def fit_company_dynamics(d: MarketData, t0: pd.Timestamp, n_apps: int, H: int, grid: dict[str, list[float]], inner: int, history: int) -> dict[str, Any]:
    """Backtests at `inner` earlier cutoffs whose H-week targets end before t0 measure, per persistence class, how many
    leading apps stay ranked and how the survivors grow, and choose, separately for each persistence class, the
    starting-level window k, the weight on that drift, the growth damping phi, the weight w on an app's own recent
    growth, the blend alpha with the recent level held flat, and whether the point uses the survival-weighted mix.
    Each backtest is scored with curves measured on the other backtests. Score: absolute error of each app's H-week
    total, summed over the class and divided by the backtest's total tokens (so class choices add up to the total)."""
    weeks_all = sorted(w for w in d.aw.week.unique() if w < t0)
    folds = []
    for j in range(inner):
        c = t0 - (H + j) * WEEK                                   # inner cutoff; its targets are weeks [c, c+H) < t0
        hist = [w for w in weeks_all if c - history * WEEK <= w < c]
        tgt = [c + i * WEEK for i in range(H)]
        if len(hist) < 8 or any(t >= t0 for t in tgt):
            continue
        ids = top_apps(d, c, n_apps)
        x, _ = app_matrix(d, hist, ids)
        y, cens = app_matrix(d, tgt, ids)
        folds.append({"ylog": np.log(x), "y": y, "cens": cens, "cls": persistence_class(d, ids, c), "fill": fill_level(d, c)})
    simple = {"k_level": max(grid.get("k_level", [4])), "drift": 0.0, "phi": grid["phi"][0], "w": 0.0, "alpha": 1.0, "survival_point": "median"}
    if not folds:
        return {"spec": {c: dict(simple) for c in PERSISTENCE}, "mu": {"_all": 0.0}, "survival": {c: [1.0] * H for c in PERSISTENCE}, "sigma": [0.3] * H, "inner_cutoffs": 0}
    specs = [dict(zip(SPEC_KEYS, v)) for v in itertools.product(grid.get("k_level", [1, 2, 4]), grid.get("drift", [0.0, 0.5, 1.0]), grid["phi"], grid["w"],
                                                                   grid.get("alpha", [1.0]), grid.get("survival_point", ["median"]))]
    results: dict[tuple, dict[str, list[float]]] = {}
    for i, f in enumerate(folds):
        others = folds[:i] + folds[i + 1:]
        surv = survival_curves(others, H)
        drift_k = {k: forward_drift(others, k, H) for k in grid.get("k_level", [1, 2, 4])}
        tot = f["y"].sum()
        for sp in specs:
            mu = {c: sp["drift"] * v for c, v in drift_k[sp["k_level"]].items()}
            arr = class_arrays(f["cls"], {c: sp for c in PERSISTENCE}, mu)
            e = np.abs(point_paths(f, H, arr, surv).sum(1) - f["y"].sum(1))
            r = results.setdefault(tuple(sp.values()), {c: [] for c in PERSISTENCE})
            for c in PERSISTENCE:
                r[c].append(float(e[f["cls"] == c].sum() / tot))
    # One-standard-error rule, per class: keep the simplest specification (the recent four-week level, no drift, no own
    # trend, no blend) unless a richer one is better across the backtests by more than one standard error of the difference.
    chosen, inner_err, selection = {}, {}, {}
    for c in PERSISTENCE:
        best_key, best = min(results.items(), key=lambda kv: float(np.mean(kv[1][c])))
        base = results[tuple(simple.values())][c]
        diff = np.array(base) - np.array(best[c])
        se = float(np.std(diff, ddof=1) / math.sqrt(len(diff))) if len(diff) > 1 else float("inf")
        rich = float(np.mean(diff)) > se and float(np.mean(diff)) > 0
        chosen[c] = dict(zip(SPEC_KEYS, best_key)) if rich else dict(simple)
        inner_err[c] = round(float(np.mean(best[c] if rich else base)), 4)
        selection[c] = "richer specification" if rich else "simplest specification (one-standard-error rule)"
    surv = survival_curves(folds, H)
    mu_d = {"_all": 0.0}
    for c in PERSISTENCE:
        fd = forward_drift(folds, chosen[c]["k_level"], H)
        mu_d[c] = chosen[c]["drift"] * fd.get(c, fd["_all"])
    # Shock sizes for ranked apps: spread of log errors by horizon, after removing the market-wide part.
    res, tot = [], []
    for f in folds:
        arr = class_arrays(f["cls"], chosen, mu_d)
        r = np.log(f["y"]) - damped_paths(f["ylog"], H, arr["phi"], arr["w"], arr["mu"], arr["k_level"], arr["alpha"])
        r = np.where(f["cens"], np.nan, r)
        res.append(r - np.nanmedian(r, axis=0, keepdims=True))
        tot.append(np.log(f["y"].sum(1) / point_paths(f, H, arr, surv).sum(1)))
    R = np.concatenate(res, axis=0)
    mad = 1.4826 * np.nanmedian(np.abs(R - np.nanmedian(R, axis=0)), axis=0)
    # Range width: the backtests' spread of log(actual / predicted) for H-week totals sets how wide the simulated
    # range must be; the weekly shocks are scaled up when the shock sizes alone would give a narrower range.
    tot = np.concatenate(tot)
    half = float((np.quantile(tot, 0.95) - np.quantile(tot, 0.05)) / 2)
    mk = fit_market_factor(d, t0, history)
    implied = math.sqrt(float(np.mean(mad)) ** 2 + (mk["sd"] * math.sqrt(H / 2)) ** 2)
    scale = max(1.0, half / (1.645 * implied)) if implied > 0 else 1.0
    return {"sigma_scale": round(scale, 3), "backtest_total_q05_q95": [round(float(np.quantile(tot, 0.05)), 3), round(float(np.quantile(tot, 0.95)), 3)],
            "spec": chosen, "mu": mu_d, "survival": surv, "inner_error": inner_err, "selection": selection,
            "sigma": [round(float(x_), 4) for x_ in mad], "inner_cutoffs": len(folds)}


@lru_cache(maxsize=64)
def _cached_dynamics(root: str, mtime: float, t0: str, n_apps: int, H: int, grid: str, inner: int, history: int) -> dict[str, Any]:
    """Calibration depends only on data before t0 and the settings, so every seed at a cutoff shares it."""
    return fit_company_dynamics(_load(root, mtime), pd.Timestamp(t0), n_apps, H, json.loads(grid), inner, history)


def fit_market_factor(d: MarketData, t0: pd.Timestamp, history: int) -> dict[str, float]:
    m = d.mw.groupby("week").market_tokens.first()
    m = m[(m.index < t0) & (m.index >= t0 - history * WEEK)]
    dl = np.diff(np.log(m.to_numpy()))
    return {"mu": float(np.median(dl[-13:])) if len(dl) else 0.0, "sd": float(1.4826 * np.median(np.abs(dl - np.median(dl)))) if len(dl) > 3 else 0.05}


def top_apps(d: MarketData, t0: pd.Timestamp, n: int) -> list[int]:
    recent = d.aw[(d.aw.week < t0) & (d.aw.week >= t0 - 4 * WEEK)]
    return recent.groupby("app_id").tokens.sum().nlargest(n).index.astype(int).tolist()


def launch_prior(d: MarketData, segment: str, t0: pd.Timestamp, lookback_weeks: int = 39, weeks_after: int = 4) -> dict[str, Any]:
    """Every model listed in the `lookback_weeks` before t0 (and at least `weeks_after` weeks before it): its largest
    share of the segment within `weeks_after` weeks of listing relative to the segment leader's share, on a log scale.
    Models never used enough to be named in the usage data count at a floor (1e-5). Returned as an empirical list per
    provider and overall, so launches are drawn from what launches before t0 actually achieved."""
    src = d.mw[d.mw.model != "other"] if segment == "market" else d.cw[d.cw.category == segment]
    src = src[src.week < t0]
    lead = src.groupby("week").share.max()
    cat = d.catalog[(d.catalog.launch >= t0 - lookback_weeks * WEEK) & (d.catalog.launch < t0 - weeks_after * WEEK)]
    by_model = {m: g for m, g in src.groupby("model")}
    vals, by_provider, records = [], {}, []
    for r in cat.itertuples():
        lw = r.launch - pd.Timedelta(days=r.launch.weekday())
        lw = lw.normalize()
        g = by_model.get(r.usage_model) if isinstance(r.usage_model, str) else None
        if g is not None:
            win = g[(g.week >= lw) & (g.week < lw + weeks_after * WEEK)]
            peak = float(win.share.max()) if len(win) else 0.0
        else:
            peak = 0.0
        ld = lead[(lead.index >= lw) & (lead.index < lw + weeks_after * WEEK)].mean()
        if not ld or np.isnan(ld):
            continue
        v = math.log(max(peak, 1e-5) / ld)
        vals.append(v)
        by_provider.setdefault(r.provider, []).append(v)
        records.append({"model": r.usage_model if isinstance(r.usage_model, str) else r.id, "provider": str(r.provider), "launch": str(r.launch.date()), "peak": round(100 * peak, 2)})
    return {"all": vals or [math.log(1e-3)], "by_provider": by_provider, "n": len(vals), "records": records}


def launch_budget(d: MarketData, segment: str, t0: pd.Timestamp, listing: dict[str, tuple[str, pd.Timestamp]],
                  weeks: int = 26, window: int = 8) -> dict[str, float]:
    """Market memory at t0: for each of the `weeks` weeks before t0, the share of the segment's tokens on models first
    listed in the `window` weeks before that week, and how many models were listed in that window. Their medians give
    the share a typical listing carries once settled (per_launch)."""
    launches = pd.Series(sorted(x[1] for x in listing.values() if x[1] is not None and pd.notna(x[1])))
    shares, counts = [], []
    for i in range(1, weeks + 1):
        w = t0 - i * WEEK
        mix = segment_mix(d, segment, w)
        if not len(mix):
            continue
        lw = [listing.get(m) or listing.get(m.split(":")[0]) for m in mix.index]
        recent = np.array([bool(x and pd.notna(x[1]) and w - window * WEEK <= x[1] < w) for x in lw])
        shares.append(float(mix[recent].sum()))
        counts.append(int(((launches >= w - window * WEEK) & (launches < w)).sum()))
    if not shares or not max(counts):
        return {"share": 0.0, "listings": 0, "per_launch": 1e-3}
    share, n = float(np.median(shares)), max(1.0, float(np.median(counts)))
    return {"share": share, "listings": n, "per_launch": share / n}


def new_listings(d: MarketData, t0: pd.Timestamp, H: int) -> pd.DataFrame:
    """Models first listed in [t0, t0 + H weeks), named by their usage permaslug when one exists."""
    c = d.catalog[(d.catalog.launch >= t0) & (d.catalog.launch < t0 + H * WEEK)].copy()
    c["model"] = c.usage_model.where(c.usage_model.notna(), c.id)
    c["week"] = (c.launch - pd.to_timedelta(c.launch.dt.weekday, unit="D")).dt.normalize()
    return c[["model", "provider", "week", "id"]]


# ------------------------------------------------------------------ world

BUYER_TOP = 25                       # models shown to the buyer: the segment's leaders and the most successful recent launches
LAUNCH_LOOKBACK = 39                 # weeks of launches before the cutoff behind the launch prior and the buyer's market memory
REST = "all other models"
SEGMENT_TEXT = {"programming": "coding workloads (coding agents and IDE tools) of the companies",
                "roleplay": "roleplay and creative-writing chat workloads of the companies",
                "market": "workloads of every other kind of AI app (assistants, data pipelines, agents, translation and more)"}

class World(BaseWorld):
    @classmethod
    def from_instance(cls, ctx: InstanceContext, scenario: dict[str, Any], seed: int) -> "World":
        w = scenario.get("world", {})
        t0 = pd.Timestamp(w["t0"])
        H = int(w.get("horizon_weeks", 8))
        return cls(ctx, scenario, seed, t0.to_pydatetime(), (t0 + H * WEEK).to_pydatetime())

    def __init__(self, ctx: InstanceContext, scenario: dict[str, Any], seed: int, start: datetime, end: datetime) -> None:
        super().__init__(ctx, scenario, seed, start, end)
        t_start = time.time()
        self.rng = np.random.default_rng(seed)
        cfg = scenario.get("world", {})
        par = ctx.yaml("calibration/market.yaml")
        self.par = par
        self.t0 = pd.Timestamp(cfg["t0"])
        self.H = int(cfg.get("horizon_weeks", 8))
        self.n_apps = int(cfg.get("n_apps", par.get("n_apps", 100)))
        self.K = int(par.get("workloads_per_segment", 400))
        self.registry = load_registry(ctx)
        d = self.d = load_data(ctx)
        hist_weeks = int(par.get("history_weeks", 26))
        # --- companies
        self.app_ids = top_apps(d, self.t0, self.n_apps)
        meta = d.apps.set_index("app_id").reindex(self.app_ids)
        self.app_seg = segment_of(meta).to_numpy()
        hist = sorted(w for w in d.aw.week.unique() if self.t0 - hist_weeks * WEEK <= w < self.t0)
        x, _ = app_matrix(d, hist, self.app_ids)
        self.ylog = np.log(x)
        self.dyn = _cached_dynamics(str(ctx.data_normalized), (ctx.data_normalized / "app_weekly.parquet").stat().st_mtime, str(self.t0.date()), self.n_apps, self.H,
                                    json.dumps(par.get("grid", {"phi": [0.5, 0.7, 0.85, 0.95], "w": [0.0, 0.25, 0.5, 0.75, 1.0]}), sort_keys=True),
                                    int(par.get("inner_cutoffs", 6)), hist_weeks)
        self.app_cls = persistence_class(d, self.app_ids, self.t0)
        self.arr = class_arrays(self.app_cls, self.dyn["spec"], self.dyn["mu"])
        self.mu = self.arr["mu"]
        self.surv = np.array([self.dyn["survival"][c] for c in self.app_cls])            # apps x H
        self.fill = fill_level(d, self.t0)
        self.mkt = fit_market_factor(d, self.t0, hist_weeks)
        for i, aid in enumerate(self.app_ids):
            m = meta.iloc[i]
            self.agents[f"app:{aid}"] = Agent(id=f"app:{aid}", role=str(m.get("subcategory", "other")), org_unit=str(m.get("category", "other")),
                                              attributes={"app_id": int(aid), "name": str(m.get("app_name", aid)), "segment": self.app_seg[i]}, seat="company")
        # --- workloads per segment
        self.segments = sorted(set(self.app_seg))
        self.prices = d.pw.pivot_table(index="week", columns="model", values="blended_usd_mtok", aggfunc="first")
        self.prior_week = max(w for w in d.mw.week.unique() if w < self.t0)
        self.interventions = scenario.get("interventions", []) or []
        self.price_mult: dict[str, float] = {}
        for iv in self.interventions:
            if iv.get("type") == "price_multiplier":
                for m in self._resolve_models(iv):
                    self.price_mult[m] = self.price_mult.get(m, 1.0) * float(iv.get("multiplier", 1.0))
        self.beta = float(par.get("price_beta", 0.3))
        self.inertia = float(par.get("inertia", 0.8))
        self.elasticity = float(par.get("token_price_elasticity", -0.06))
        self.mix0, self.attract, self.attract_c, self.attract_r, self.assign, self.launch = {}, {}, {}, {}, {}, {}
        for s in self.segments:
            mix = self._observed_mix(s, self.prior_week, weeks=2)
            p0 = self._price_row(self.prior_week, apply_scenario=False).reindex(mix.index)
            # standing a_m reproduces the observed mix at t0 prices: a_m = log share_m + beta * log price_m
            a = np.log(mix.clip(lower=1e-6)) + self.beta * np.log(p0.fillna(p0.median() if p0.notna().any() else 1.0).clip(lower=0.01))
            self.mix0[s], self.attract[s] = mix, a
            self.attract_c[s] = a.copy()
            self.attract_r[s] = a.copy()
            self.assign[s] = self.rng.choice(mix.index.to_numpy(), size=self.K, p=(mix / mix.sum()).to_numpy())
            self.launch[s] = launch_prior(d, s, self.t0, LAUNCH_LOOKBACK)
        self.listing: dict[str, tuple[str, pd.Timestamp]] = {}
        for r in d.catalog.sort_values("launch").itertuples():
            m = r.usage_model if isinstance(r.usage_model, str) else r.id
            self.listing.setdefault(m, (str(r.provider), r.launch))
        self.budget = {s: launch_budget(d, s, self.t0, self.listing) for s in self.segments}
        self.new_models = new_listings(d, self.t0, self.H)
        # the buyer seat judges each newly listed model (rule: a draw from how earlier launches did)
        self.buyer = self.registry.for_seat("buyer")
        self.buyer_llm = self.buyer.name != "rule"
        # launch totals from market memory: required when a language model judges launches (its estimates only split them)
        self.memory = par.get("launch_total", "prior") == "memory" or self.buyer_llm
        self.judged: dict[tuple[str, str], dict[str, float] | None] = {}
        self.buyer_fallbacks = 0
        self.calibration_s = time.time() - t_start
        self.sim_rows: list[dict[str, Any]] = []

    # ---- helpers
    def _observed_mix(self, segment: str, week: pd.Timestamp, weeks: int = 1) -> pd.Series:
        ws = [week - i * WEEK for i in range(weeks)]
        mixes = [segment_mix(self.d, segment, w) for w in ws]
        m = pd.concat(mixes, axis=1).fillna(0).mean(axis=1)
        return m[m > 0] / m.sum()

    def _price_row(self, week: pd.Timestamp, apply_scenario: bool = True) -> pd.Series:
        wk = max([w for w in self.prices.index if w <= week], default=self.prices.index[0])
        p = self.prices.loc[wk].copy()
        if apply_scenario:
            for m, k in self.price_mult.items():
                if m in p.index:
                    p[m] = p[m] * k
        return p

    def _resolve_models(self, iv: dict[str, Any]) -> list[str]:
        if iv.get("model"):
            return [iv["model"]]
        if iv.get("model_rank") and iv.get("segment"):
            mix = self._observed_mix(iv["segment"], self.prior_week, weeks=2)
            p = self._price_row(self.prior_week, apply_scenario=False).reindex(mix.index)
            paid = mix[p > 0] if (p > 0).any() else mix
            return paid.sort_values(ascending=False).index[: int(iv["model_rank"])].tolist()[-1:]
        return []

    def _weights(self, s: str, week: pd.Timestamp, path: str = "stochastic") -> tuple[list[str], np.ndarray]:
        """Choice weights of a segment's workloads over the models listed by `week`. path: "central" (the point
        prediction), "formula" (the central path with the rule's launch judgment, kept for comparison when the buyer
        is a language model) or "stochastic"."""
        p = self._price_row(week)
        store = {"central": self.attract_c, "formula": self.attract_r}.get(path, self.attract)
        a = store[s].copy()
        arrivals = [r for r in self.new_models.itertuples() if r.week <= week and r.model not in a.index]
        judged = self._judge(s, week, arrivals) if (arrivals and self.buyer_llm and path != "formula") else None
        if arrivals and not self.memory:
            for r in arrivals:
                lp = self.launch[s]
                pool = lp["by_provider"].get(r.provider) if len(lp["by_provider"].get(r.provider, [])) >= 3 else lp["all"]
                # a new model's standing: the leader's standing plus a draw from what earlier launches achieved
                # (the central paths take the median launch)
                a[r.model] = float(a.max()) + (float(np.median(pool)) if path != "stochastic" else float(self.rng.choice(pool)))
        elif arrivals:
            # How much the week's new models take together comes from market memory (what launches took before the
            # cutoff, per launch); how it splits among them is the buyer's judgment, or for the rule the provider's
            # earlier launches (central paths: the median launch; stochastic runs: a draw).
            lp = self.launch[s]
            wts = []
            for r in arrivals:
                if judged and r.model in judged:
                    wts.append(max(judged[r.model], 1e-4))
                else:
                    pool = lp["by_provider"].get(r.provider) if len(lp["by_provider"].get(r.provider, [])) >= 3 else lp["all"]
                    wts.append(math.exp(float(np.median(pool)) if path != "stochastic" else float(self.rng.choice(pool))))
            wts = np.array(wts) / sum(wts)
            u0 = a.to_numpy() - self.beta * np.log(self._fill_prices(p, a.index))
            logS = float(u0.max()) + math.log(float(np.exp(u0 - u0.max()).sum()))
            for r, wt in zip(arrivals, wts):
                # standing that gives the share once workloads settle: u_m = logit(share) + log sum over the others
                sh = float(np.clip(len(arrivals) * self.budget[s]["per_launch"] * wt, 1e-5, 0.9))
                pm = float(self._fill_prices(p, pd.Index([r.model]))[0])
                a[r.model] = math.log(sh / (1 - sh)) + logS + self.beta * math.log(pm)
        store[s] = a
        names = a.index.tolist()
        u = a.to_numpy() - self.beta * np.log(self._fill_prices(p, a.index))
        e = np.exp(u - u.max())
        return names, e / e.sum()

    @staticmethod
    def _fill_prices(p: pd.Series, names: pd.Index) -> np.ndarray:
        pr = p.reindex(names)
        return pr.fillna(pr.median() if pr.notna().any() else 1.0).clip(lower=0.01).to_numpy()

    def _launch_scores(self) -> dict[str, dict[str, dict[str, float]]]:
        """Each new model's judgment per segment: the buyer's estimated share and the rule's provider prior (log scale)."""
        out = {}
        for s in self.segments:
            lp = self.launch[s]
            rule = {r.model: float(np.median(lp["by_provider"][r.provider] if len(lp["by_provider"].get(r.provider, [])) >= 3 else lp["all"]))
                    for r in self.new_models.drop_duplicates("model").itertuples()}
            buyer = {m: float(v) for (s_, _), j in self.judged.items() if s_ == s and j for m, v in j.items() if m in rule}
            out[s] = {"rule": rule, "buyer": buyer}
        return out

    def _listed(self, m: str) -> tuple[str | None, pd.Timestamp | None]:
        """Provider and first listing of a model; a free or other variant (suffix after ':') counts as its base model."""
        return self.listing.get(m) or self.listing.get(m.split(":")[0]) or (None, None)

    def _judge(self, s: str, week: pd.Timestamp, arrivals: list[Any]) -> dict[str, float] | None:
        """The buyer's judgment of the models listed this week: the share of the segment's tokens each will carry
        once workloads settle. One judgment per segment and week, shared by the central and stochastic paths."""
        key = (s, str(week.date()))
        if key in self.judged:
            return self.judged[key]
        new_now = [r for r in arrivals if r.week == week] or arrivals
        obs = self._buyer_obs(s, week, new_now)
        est = self.buyer.estimate(obs) if hasattr(self.buyer, "estimate") else None
        if est is None:
            self.buyer_fallbacks += 1
        self.judged[key] = {m: v / 100 for m, v in est.items()} if est else None
        return self.judged[key]

    def _buyer_obs(self, s: str, week: pd.Timestamp, arrivals: list[Any]) -> Observation:
        """What a buyer knows when a model is listed: the segment's model shares at the cutoff, how the models listed
        in the half year before the cutoff did in this segment, the models listed since, and the new models' prices.
        Everything is from before the cutoff, apart from the published listings and prices."""
        p = self._price_row(week)
        mix = self.mix0[s].drop(labels=[m for m in self.mix0[s].index if m == "other"])
        prov = lambda m: self._listed(m)[0] or m.split("/")[0]  # noqa: E731
        prov_share = mix.groupby([prov(m) for m in mix.index]).sum()
        top = mix.sort_values(ascending=False).head(BUYER_TOP)
        price = lambda m: f"{p[m]:.2f}" if m in p.index and pd.notna(p[m]) else "not listed"  # noqa: E731
        lines = [f"Date: {week.date()}. You judge newly listed AI models for the {SEGMENT_TEXT.get(s, s)} that run through OpenRouter.",
                 f"\nThis group's share of tokens by model in the week before {self.t0.date()} (list price now, US dollars per million tokens, input and output blended):"]
        lines += [f"- {m} ({prov(m)}): {100 * v:.1f}%, price {price(m)}" for m, v in top.items()]
        mem = self.launch[s].get("records", [])
        hits = sorted(mem, key=lambda r: -r["peak"])[:BUYER_TOP]
        lines.append(f"\nModels listed in the {LAUNCH_LOOKBACK} weeks before {self.t0.date()}: the largest share of this group's tokens each reached within "
                     f"4 weeks of listing ({len(mem)} launches; {sum(r['peak'] < 0.1 for r in mem)} of them stayed under 0.1%):")
        lines += [f"- {r['model']} ({r['provider']}, listed {r['launch']}): {r['peak']:.1f}%" for r in hits]
        since = [r.model for r in self.new_models.itertuples() if r.week < week]
        if since:
            lines.append(f"\nAlso listed since {self.t0.date()}: " + ", ".join(since[:40]) + ".")
        lines.append("\nFor each model listed this week, estimate the percent of this group's tokens it will carry once workloads have "
                     "settled, about eight weeks after listing.")
        opts = [{"kind": "use_model", "target": r.model, "show": {"provider": prov(r.model), "list price now": price(r.model),
                                                                  "provider's share at cutoff %": f"{100 * prov_share.get(prov(r.model), 0.0):.1f}"}}
                for r in arrivals]
        return Observation(agent_id=f"buyer:{s}", role="buyer", sim_time=str(week.date()),
                           context={"segment": s, "brief": "\n".join(lines), "answer_key": "estimate",
                                    "format": '{"estimate": {"<id>": <percent>, ...}, "reason": "<one sentence>"}'}, options=opts)

    # ---- run
    def run(self, writer: RunWriter) -> RunSummary:
        self._writer = writer
        t_run = time.time()
        H, n = self.H, len(self.app_ids)
        A = self.arr
        phi, w, alpha = A["phi"], A["w"], A["alpha"]
        sig = np.array(self.dyn.get("sigma") or [0.15] * H)
        sig_inc = float(self.dyn.get("sigma_scale", 1.0)) * np.sqrt(np.maximum(np.diff(np.concatenate([[0.0], sig ** 2])), 1e-6))  # per-week shock sizes
        lvl = blended_start(self.ylog, A["k_level"], alpha)
        start_week = np.exp(start_level(self.ylog, 4))
        mu_e = alpha * self.mu
        g = alpha * (w * own_slope(self.ylog) + (1 - w) * self.mu)
        kappa = float(self.par.get("market_loading", 1.0))
        p_seg0 = {s: blended_price(self.mix0[s], self._price_row(self.prior_week, apply_scenario=False)) for s in self.segments}
        tokens = np.zeros((n, H)); spend = np.zeros((n, H)); seg_price = {s: [] for s in self.segments}; seg_mix_hist = {s: [] for s in self.segments}
        market = np.zeros(H)
        mlog = 0.0
        last_dprice = np.zeros(n)
        u_alive = self.rng.random(n)                      # an app stays ranked while u < its class's survival curve
        # Central path: the same kernel with every shock at its median (no noise, median launch, expected model choice);
        # it is the point prediction, and the stochastic runs supply the ranges.
        lvl_c, g_c, last_dprice_c, mlog_c = lvl.copy(), g.copy(), np.zeros(n), 0.0
        mix_c = {s: self.mix0[s].copy() for s in self.segments}
        mix_r = {s: self.mix0[s].copy() for s in self.segments}      # the rule's launch judgment alongside a language-model buyer
        tokens_c = np.zeros((n, H)); spend_c = np.zeros((n, H)); seg_price_c = {s: [] for s in self.segments}
        seg_price_r = {s: [] for s in self.segments}; spend_r = np.zeros((n, H))
        for h in range(H):
            week = self.t0 + h * WEEK
            for s in self.segments:
                if self.buyer_llm:
                    rn, rw = self._weights(s, week, "formula")
                    mix_r[s] = self.inertia * mix_r[s].reindex(rn).fillna(0.0) + (1 - self.inertia) * pd.Series(rw, index=rn)
                    seg_price_r[s].append(blended_price(mix_r[s], self._price_row(week)))
                names, wts = self._weights(s, week, "central")
                dist = pd.Series(wts, index=names)
                prev = mix_c[s].reindex(names).fillna(0.0)
                mix_c[s] = self.inertia * prev + (1 - self.inertia) * dist
                seg_price_c[s].append(blended_price(mix_c[s], self._price_row(week)))
            mlog_c += self.mkt["mu"]
            g_c = phi * g_c + (1 - phi) * mu_e
            dp = np.array([math.log(seg_price_c[s][-1] / p_seg0[s]) if p_seg0[s] and seg_price_c[s][-1] and p_seg0[s] > 0 and seg_price_c[s][-1] > 0 else 0.0 for s in self.app_seg])
            lvl_c = lvl_c + g_c + self.elasticity * (dp - last_dprice_c)
            last_dprice_c = dp
            unranked = self.fill * math.exp(mlog_c)
            tokens_c[:, h] = np.where(A["expected"], self.surv[:, h] * np.exp(lvl_c) + (1 - self.surv[:, h]) * unranked,
                                      np.where(self.surv[:, h] >= 0.5, np.exp(lvl_c), unranked))
            spend_c[:, h] = tokens_c[:, h] * np.array([seg_price_c[s][-1] for s in self.app_seg]) / 1e6
            if self.buyer_llm:
                spend_r[:, h] = tokens_c[:, h] * np.array([seg_price_r[s][-1] for s in self.app_seg]) / 1e6
        for h in range(H):
            week = self.t0 + h * WEEK
            # workloads choose models (seat policy over kernel-offered options)
            for s in self.segments:
                names, wts = self._weights(s, week)
                seat = f"workload:{s}"
                pol = self.registry.for_seat("workload")
                movers = np.flatnonzero(self.rng.random(self.K) > self.inertia)
                for j in movers:
                    obs = Observation(agent_id=f"{seat}:{j}", role="workload", sim_time=str(week.date()),
                                      context={"segment": s, "current_model": str(self.assign[s][j])},
                                      options=[{"kind": "use_model", "target": m, "weight": float(x)} for m, x in zip(names, wts)])
                    act = pol.decide(obs, self.rng)
                    if act.target is not None:
                        self.assign[s][j] = act.target
                vc = pd.Series(self.assign[s]).value_counts(normalize=True)
                seg_mix_hist[s].append(vc)
                bp = blended_price(vc, self._price_row(week))
                seg_price[s].append(bp)
                self.emit(agent_id=seat, role="workload", org_unit=s, activity="model_mix", action_type="state", provenance="simulated",
                          attributes={"week": str(week.date()), "mix_top": {m: round(float(v), 4) for m, v in vc.head(8).items()}, "blended_usd_mtok": round(bp, 4), "moved": int(len(movers))})
            # companies
            z_m = float(self.rng.normal(0, 1))
            mlog += self.mkt["mu"] + self.mkt["sd"] * z_m
            market[h] = mlog
            g = phi * g + (1 - phi) * mu_e
            dprice = np.array([math.log(seg_price[s][-1] / p_seg0[s]) if p_seg0[s] and seg_price[s][-1] and p_seg0[s] > 0 and seg_price[s][-1] > 0 else 0.0 for s in self.app_seg])
            lvl = lvl + g + kappa * self.mkt["sd"] * z_m + sig_inc[h] * self.rng.normal(0, 1, n) + self.elasticity * (dprice - last_dprice)
            last_dprice = dprice
            tokens[:, h] = np.where(u_alive < self.surv[:, h], np.exp(lvl), self.fill * math.exp(mlog))
            spend[:, h] = tokens[:, h] * np.array([seg_price[s][-1] for s in self.app_seg]) / 1e6
            for i, aid in enumerate(self.app_ids):
                self.emit(agent_id=f"app:{aid}", role=self.agents[f"app:{aid}"].role, org_unit=self.agents[f"app:{aid}"].org_unit, activity="weekly_tokens",
                          action_type="state", provenance="simulated", attributes={"week": str(week.date()), "tokens": float(tokens[i, h]), "spend_usd": float(spend[i, h])})
            for _ in range(168):
                if self.clock.done:
                    break
                self.clock.advance()
        self.runtime_s = time.time() - t_run
        mix_end = {s: {m: round(float(v), 5) for m, v in seg_mix_hist[s][-1].items()} for s in self.segments}
        headline = {
            "t0": str(self.t0.date()), "horizon_weeks": H, "n_apps": n,
            "apps": [{"app_id": int(a), "name": self.agents[f"app:{a}"].attributes["name"], "segment": str(self.app_seg[i]), "persistence": str(self.app_cls[i]), "start_tokens_week": float(start_week[i]),
                      "category": self.agents[f"app:{a}"].org_unit, "subcategory": self.agents[f"app:{a}"].role,
                      "tokens": [float(v) for v in tokens[i]], "spend_usd": [float(v) for v in spend[i]],
                      "tokens_central": [float(v) for v in tokens_c[i]], "spend_central": [float(v) for v in spend_c[i]],
                      **({"spend_central_formula": [float(v) for v in spend_r[i]]} if self.buyer_llm else {})} for i, a in enumerate(self.app_ids)],
            "segment_price_central": {s: [round(float(v), 5) for v in seg_price_c[s]] for s in self.segments},
            "segment_mix_end_central": {s: {m: round(float(v), 5) for m, v in mix_c[s].items() if v >= 1e-4} for s in self.segments},
            **({"segment_mix_end_rule": {s: {m: round(float(v), 5) for m, v in mix_r[s].items() if v >= 1e-4} for s in self.segments},
                "buyer": {**self.buyer.describe(), "fallbacks": self.buyer_fallbacks}, "launch_scores": self._launch_scores()} if self.buyer_llm else {}),
            "market_log_change_central": [float(self.mkt["mu"] * (h + 1)) for h in range(H)],
            "segment_price": {s: [round(float(v), 5) for v in seg_price[s]] for s in self.segments},
            "segment_mix_end": mix_end,
            "segment_mix_weekly": {s: [{m: round(float(v), 5) for m, v in vc.items() if v >= 0.002} for vc in seg_mix_hist[s]] for s in self.segments},
            "market_log_change": [float(v) for v in market],
            "calibration": {"sigma_scale": self.dyn.get("sigma_scale"), "selection": self.dyn.get("selection"), "spec_by_class": self.dyn.get("spec"), "sigma": self.dyn.get("sigma"), "inner_error": self.dyn.get("inner_error"), "inner_cutoffs": self.dyn.get("inner_cutoffs"),
                            "drift_by_class": {k_: round(v, 4) for k_, v in self.dyn["mu"].items()},
                            "survival": self.dyn.get("survival"),
                            "launch_prior": {s: {"n": v["n"], "median": float(np.median(v["all"]))} for s, v in self.launch.items()}, "launch_budget": self.budget, "price_beta": self.beta, "inertia": self.inertia, "elasticity": self.elasticity},
            "price_multipliers": self.price_mult, "new_models_listed": self.new_models.model.tolist(),
            "total_tokens": float(tokens.sum()), "total_spend_usd": float(spend.sum()),
        }
        return RunSummary(run_id=writer.run_id, instance=self.ctx.id, scenario=self.scenario["id"], seed=self.seed, start=str(self.t0.date()),
                          end=str((self.t0 + H * WEEK).date()), ticks=self.clock.tick, events=self._n_events, headline=headline)


# ------------------------------------------------------------------ evaluation

def _run_world(ctx: InstanceContext, scenario: dict[str, Any], seed: int, t0: str) -> tuple[World, RunSummary]:
    sc = json.loads(json.dumps(scenario))
    sc.setdefault("world", {})["t0"] = t0
    writer = RunWriter(ctx.id, sc["id"], config={"instance": ctx.id, "scenario": sc, "seed": seed, "evaluation": True})
    world = World.from_instance(ctx, sc, seed)
    summary = world.run(writer)
    writer.close(summary.to_json())
    print(f"[{ctx.id}] eval run {sc['id']} t0={t0} seed={seed} -> {writer.run_id} (calibration {world.calibration_s:.1f}s, run {world.runtime_s:.1f}s)", flush=True)
    return world, summary


def actual_window(d: MarketData, t0: pd.Timestamp, H: int, app_ids: list[int], segs: np.ndarray) -> dict[str, Any]:
    """What really happened in [t0, t0 + H weeks): tokens per app, segment mixes and blended prices, spend."""
    weeks = [t0 + i * WEEK for i in range(H)]
    y, cens = app_matrix(d, weeks, app_ids)
    pw = d.pw.pivot_table(index="week", columns="model", values="blended_usd_mtok", aggfunc="first")
    sp = {}
    for s in set(segs):
        sp[s] = [blended_price(segment_mix(d, s, w), pw.loc[max([x for x in pw.index if x <= w])]) for w in weeks]
    price = np.array([[sp[s][h] for h in range(H)] for s in segs])
    spend = y * price / 1e6
    mk = d.mw.groupby("week").market_tokens.first()
    return {"tokens": y, "censored": cens, "spend": spend, "seg_price": sp, "market": float(mk.reindex(weeks).sum()),
            "mix_end": {s: segment_mix(d, s, weeks[-1]) for s in set(segs)}}


def comparators(d: MarketData, t0: pd.Timestamp, H: int, app_ids: list[int], segs: np.ndarray, mix0: dict[str, pd.Series]) -> dict[str, dict[str, Any]]:
    """Non-simulation predictions from the same pre-cutoff data and the same published price lists."""
    hist = sorted(w for w in d.aw.week.unique() if t0 - 8 * WEEK <= w < t0)
    x, _ = app_matrix(d, hist, app_ids)
    ylog = np.log(x)
    last4 = x[:, -4:].mean(1)
    tt = np.arange(8) - 3.5
    slope = np.clip(((ylog - ylog.mean(1, keepdims=True)) * tt).sum(1) / (tt ** 2).sum(), -0.15, 0.15)   # same bound as the simulation's drift
    mk = d.mw.groupby("week").market_tokens.first()
    mh = mk[(mk.index < t0) & (mk.index >= t0 - 9 * WEEK)]
    mslope = float(np.polyfit(np.arange(len(mh)), np.log(mh.to_numpy()), 1)[0]) if len(mh) > 2 else 0.0
    hs = np.arange(1, H + 1)
    pw = d.pw.pivot_table(index="week", columns="model", values="blended_usd_mtok", aggfunc="first")
    weeks = [t0 + i * WEEK for i in range(H)]
    price = np.array([[blended_price(mix0[s], pw.loc[max([q for q in pw.index if q <= w])]) for w in weeks] for s in segs])
    preds = {
        "carry_forward": np.repeat(last4[:, None], H, axis=1),
        "recent_trend": np.exp(np.log(last4)[:, None] + slope[:, None] * (hs[None, :] + 1.5)),
        "market_growth": last4[:, None] * np.exp(mslope * (hs[None, :] + 1.5)),
    }
    mk_last4 = float(mk[(mk.index < t0)].iloc[-4:].mean())
    market = {"carry_forward": mk_last4 * H, "recent_trend": float(np.sum(mk_last4 * np.exp(mslope * (hs + 1.5)))), "market_growth": float(np.sum(mk_last4 * np.exp(mslope * (hs + 1.5))))}
    return {k: {"tokens": v, "spend": v * price / 1e6, "market": market[k]} for k, v in preds.items()}


COMPARATOR_LABELS = {"carry_forward": "No change: the last four weeks carried forward",
                     "recent_trend": "Recent trend: each company's eight-week growth rate extended (at most 15% a week)",
                     "market_growth": "Market growth: each company grows at the market's recent rate"}


def wape(pred: np.ndarray, act: np.ndarray) -> float:
    return float(np.abs(pred - act).sum() / act.sum() * 100)


HORIZONS = (1, 2, 4, 8)
DEV_CUTOFFS = 4      # the buyer seat's prompt was designed on the first four cutoffs (docs/plans/buyer_seat_protocol.md)


def share_distance(p: dict[str, float] | pd.Series, q: dict[str, float] | pd.Series) -> float:
    """Half the summed absolute difference between two model-share vectors, in percentage points (0 = identical mix,
    100 = no overlap): the share of a segment's tokens that would have to move to turn one mix into the other."""
    a, b = pd.Series(p, dtype=float), pd.Series(q, dtype=float)
    a, b = a / a.sum(), b / b.sum()
    idx = a.index.union(b.index)
    return float(50 * (a.reindex(idx, fill_value=0) - b.reindex(idx, fill_value=0)).abs().sum())


def share_scores(h0: dict[str, Any], mix_end: dict[str, pd.Series], mix0: dict[str, pd.Series]) -> dict[str, Any]:
    """Each segment's model mix in the final week: distance of each prediction from the actual mix, and the share the
    models first listed after the cutoff took. Predictions: the simulation's central path, the price-formula choice
    (when the seat is a language model, the same kernel run with the formula alongside), and no change."""
    new = set(h0.get("new_models_listed") or [])
    out = {}
    for sg, act in mix_end.items():
        if act is None or not len(act) or act.sum() <= 0:
            continue
        preds = {"simulation": h0["segment_mix_end_central"].get(sg), "no_change": mix0.get(sg)}
        if h0.get("segment_mix_end_rule"):
            preds["price_formula"] = h0["segment_mix_end_rule"].get(sg)
        preds = {k: v for k, v in preds.items() if v is not None and len(v)}
        nshare = lambda m: float(100 * sum(v for k, v in dict(m).items() if k in new) / sum(dict(m).values()))  # noqa: E731
        out[sg] = {"distance": {k: share_distance(v, act) for k, v in preds.items()},
                   "new_share": {"actual": nshare(act), **{k: nshare(v) for k, v in preds.items()}}}
    return out


def evaluate(ctx: InstanceContext, scenario_ids: list[str]) -> dict[str, Any]:
    from ..scenarios import load_scenario
    proto = ctx.yaml("evaluation/protocol.yaml")
    d = load_data(ctx)
    H = int(proto.get("horizon_weeks", 8))
    seeds = [int(s) for s in proto.get("seeds", [1, 2, 3])]
    cutoffs = [pd.Timestamp(c) for c in proto["cutoffs"]]
    base_id = proto.get("baseline_scenario", "baseline")
    alt_id = ctx.meta.get("scenarios", {}).get("alternative")
    base = load_scenario(ctx, base_id)
    windows, run_ids = [], {base_id: []}
    scatter = []
    for c in cutoffs:
        sims = [_run_world(ctx, base, sd, str(c.date()))[1] for sd in seeds]
        run_ids[base_id] += [s.run_id for s in sims]
        h0 = sims[0].headline
        ids = [a["app_id"] for a in h0["apps"]]
        segs = np.array([a["segment"] for a in h0["apps"]])
        T = np.array([[a["tokens"] for a in s.headline["apps"]] for s in sims])       # seeds x apps x H
        S = np.array([[a["spend_usd"] for a in s.headline["apps"]] for s in sims])
        act = actual_window(d, c, H, ids, segs)
        prior_week = max(w for w in d.mw.week.unique() if w < c)
        mix0 = {s: segment_mix(d, s, prior_week) for s in set(segs)}
        comp = comparators(d, c, H, ids, segs, mix0)
        Tc = np.array([a["tokens_central"] for a in h0["apps"]]); Sc = np.array([a["spend_central"] for a in h0["apps"]])
        tot_sim = Tc.sum(1); tot_act = act["tokens"].sum(1)                            # point: the central path
        spd_sim = Sc.sum(1); spd_act = act["spend"].sum(1)
        lo, hi = np.percentile(T.sum(2), 5, axis=0), np.percentile(T.sum(2), 95, axis=0)
        before = sorted(w for w in d.aw.week.unique() if c - H * WEEK <= w < c)
        xb, _ = app_matrix(d, before, ids)
        pwb = d.pw.pivot_table(index="week", columns="model", values="blended_usd_mtok", aggfunc="first")
        bp = {s_: [blended_price(segment_mix(d, s_, w_), pwb.loc[max([q for q in pwb.index if q <= w_])]) for w_ in before] for s_ in set(segs)}
        spend_before = float(np.nansum(xb * np.array([bp[s_] for s_ in segs])) / 1e6)
        mk = d.mw.groupby("week").market_tokens.first()
        sim_market = float(mk[mk.index < c].iloc[-4:].mean() * np.exp(np.array(h0["market_log_change_central"])).sum())
        prog_leader = mix0.get("programming", pd.Series(dtype=float)).idxmax() if "programming" in mix0 and len(mix0["programming"]) else None
        def share_of(mixd, seg, m):
            x = mixd.get(seg)
            return float(x.get(m, 0.0)) * 100 if x is not None else None
        sim_lead = float(h0["segment_mix_end_central"].get("programming", {}).get(prog_leader, 0.0)) * 100 if prog_leader else None
        win = {
            "cutoff": str(c.date()), "n_apps": len(ids), "censored_pct": round(float(act["censored"].mean() * 100), 2),
            "company_tokens_wape": {"simulation": wape(tot_sim, tot_act), **{k: wape(v["tokens"].sum(1), tot_act) for k, v in comp.items()}},
            "company_spend_wape": {"simulation": wape(spd_sim, spd_act), **{k: wape(v["spend"].sum(1), spd_act) for k, v in comp.items()}},
            "company_tokens_mdape": {"simulation": float(np.median(np.abs(tot_sim - tot_act) / tot_act) * 100), **{k: float(np.median(np.abs(v["tokens"].sum(1) - tot_act) / tot_act) * 100) for k, v in comp.items()}},
            "coverage90": float(np.mean((tot_act >= lo) & (tot_act <= hi)) * 100),
            "direction_hit": {"simulation": float(np.mean(np.sign(tot_sim - xb.sum(1)) == np.sign(tot_act - xb.sum(1))) * 100),
                              **{k: float(np.mean(np.sign(v["tokens"].sum(1) - xb.sum(1)) == np.sign(tot_act - xb.sum(1))) * 100) for k, v in comp.items()}},
            "levels": {
                "top_tokens": {"before": float(xb.sum() / 1e12), "actual": float(tot_act.sum() / 1e12), "simulation": float(tot_sim.sum() / 1e12),
                               "interval": [float(np.percentile(T.sum((1, 2)), 5) / 1e12), float(np.percentile(T.sum((1, 2)), 95) / 1e12)],
                               **{k: float(v["tokens"].sum() / 1e12) for k, v in comp.items()}},
                "top_spend": {"before": spend_before / 1e6, "actual": float(spd_act.sum() / 1e6), "simulation": float(spd_sim.sum() / 1e6),
                              "interval": [float(np.percentile(S.sum((1, 2)), 5) / 1e6), float(np.percentile(S.sum((1, 2)), 95) / 1e6)],
                              **{k: float(v["spend"].sum() / 1e6) for k, v in comp.items()}},
                "market_tokens": {"before": float(mk[(mk.index < c) & (mk.index >= c - H * WEEK)].sum() / 1e12), "actual": act["market"] / 1e12, "simulation": sim_market / 1e12,
                                  **{k: v["market"] / 1e12 for k, v in comp.items()}},
                "prog_leader_share": {"model": prog_leader, "before": share_of(mix0, "programming", prog_leader), "actual": share_of(act["mix_end"], "programming", prog_leader), "simulation": sim_lead,
                                      **{k: share_of(mix0, "programming", prog_leader) for k in comp}},
            },
            "run_ids": [s.run_id for s in sims],
        }
        # the same predictions scored at shorter horizons (the first h weeks of each run) and within persistence classes
        win["by_horizon"] = {str(hh): {"simulation": wape(Tc[:, :hh].sum(1), act["tokens"][:, :hh].sum(1)),
                                       **{k: wape(v["tokens"][:, :hh].sum(1), act["tokens"][:, :hh].sum(1)) for k, v in comp.items()}}
                             for hh in HORIZONS if hh <= H}
        cls = np.array([a["persistence"] for a in h0["apps"]])
        win["by_class"] = {c: {"n": int((cls == c).sum()), "simulation": wape(tot_sim[cls == c], tot_act[cls == c]),
                               **{k: wape(v["tokens"].sum(1)[cls == c], tot_act[cls == c]) for k, v in comp.items()}}
                           for c in PERSISTENCE if (cls == c).any()}
        win["model_shares"] = share_scores(h0, act["mix_end"], mix0)
        if h0.get("launch_scores"):
            win["launch_rank"] = {}
            for sg, sc_ in h0["launch_scores"].items():
                a_ = act["mix_end"].get(sg)
                df = pd.DataFrame({"actual": (a_ if a_ is not None else pd.Series(dtype=float)).reindex(list(sc_["rule"])).fillna(0.0),
                                   "rule": pd.Series(sc_["rule"], dtype=float), "buyer": pd.Series(sc_["buyer"], dtype=float)}).dropna()
                if len(df) > 3 and df["actual"].sum() > 0:
                    r_ = df.rank().corr()["actual"]
                    win["launch_rank"][sg] = {"n": len(df), "rule": float(r_["rule"]), "buyer": float(r_["buyer"])}
        if "spend_central_formula" in h0["apps"][0]:
            win["spend_formula_wape"] = wape(np.array([a["spend_central_formula"] for a in h0["apps"]]).sum(1), spd_act)
        windows.append(win)
        for i, a in enumerate(h0["apps"]):
            scatter.append({"cutoff": win["cutoff"], "app": a["name"], "segment": a["segment"], "actual": float(tot_act[i]), "simulation": float(tot_sim[i]),
                            "lo": float(lo[i]), "hi": float(hi[i]), "carry_forward": float(comp["carry_forward"]["tokens"].sum(1)[i]),
                            "spend_actual": float(spd_act[i]), "spend_simulation": float(spd_sim[i])})
    # alternative: same cutoffs and seeds
    alt_rows = []
    if alt_id and alt_id in scenario_ids:
        alt = load_scenario(ctx, alt_id)
        run_ids[alt_id] = []
        for c in cutoffs[-int(proto.get("alternative_cutoffs", 3)):]:
            for sd in seeds:
                _, s = _run_world(ctx, alt, sd, str(c.date()))
                run_ids[alt_id].append(s.run_id)
                alt_rows.append(s.run_id)
    comps = list(COMPARATOR_LABELS)
    def mean_over(key: str, who: str) -> float:
        return float(np.mean([w[key][who] for w in windows]))
    def level_rows(key: str) -> list[dict[str, Any]]:
        return [{"cutoff": w["cutoff"], "actual": w["levels"][key]["actual"], "simulated": w["levels"][key]["simulation"],
                 "baselines": {k: w["levels"][key][k] for k in comps}} for w in windows]
    def bv(key: str) -> dict[str, Any]:
        rows = level_rows(key)
        ok = [r for r in rows if r["actual"] is not None and r["simulated"] is not None]
        sim_mae = float(np.mean([abs(r["simulated"] - r["actual"]) for r in ok]))
        bmae = {k: float(np.mean([abs(r["baselines"][k] - r["actual"]) for r in ok if r["baselines"][k] is not None])) for k in comps}
        best = min(bmae, key=bmae.get)
        return {"id": key, "windows": rows, "simulation_mae": sim_mae, "baseline_mae": bmae, "best_baseline": best,
                "beats_best_baseline": sim_mae < bmae[best], "error_reduction_pct": (1 - sim_mae / bmae[best]) * 100 if bmae[best] > 0 else None}
    accuracy = {}
    for key in ("company_tokens_wape", "company_spend_wape", "company_tokens_mdape", "direction_hit"):
        vals = {"simulation": mean_over(key, "simulation"), **{k: mean_over(key, k) for k in comps}}
        better_high = key == "direction_hit"
        best = (max if better_high else min)(comps, key=lambda k: vals[k])
        accuracy[key] = {**vals, "best_baseline": best,
                         "error_reduction_pct": None if better_high else (1 - vals["simulation"] / vals[best]) * 100}
    accuracy["coverage90"] = float(np.mean([w["coverage90"] for w in windows]))
    who_all = ["simulation", *comps]
    accuracy["by_horizon"] = {hh: {k: float(np.mean([w["by_horizon"][hh][k] for w in windows])) for k in who_all} for hh in windows[0]["by_horizon"]}
    accuracy["by_class"] = {c: {"n": int(sum(w["by_class"][c]["n"] for w in windows if c in w["by_class"])),
                                **{k: float(np.mean([w["by_class"][c][k] for w in windows if c in w["by_class"]])) for k in who_all}}
                            for c in PERSISTENCE if any(c in w["by_class"] for w in windows)}
    lr = [v for w in windows for v in (w.get("launch_rank") or {}).values()]
    if lr:
        accuracy["launch_rank"] = {"rule": float(np.nanmean([v["rule"] for v in lr])), "buyer": float(np.nanmean([v["buyer"] for v in lr])), "n": len(lr),
                                   "buyer_higher": int(sum(v["buyer"] > v["rule"] for v in lr))}
        held = [v for w in windows[DEV_CUTOFFS:] for v in (w.get("launch_rank") or {}).values()]
        if held:
            accuracy["launch_rank_held_out"] = {"rule": float(np.nanmean([v["rule"] for v in held])), "buyer": float(np.nanmean([v["buyer"] for v in held])), "n": len(held),
                                                "buyer_higher": int(sum(v["buyer"] > v["rule"] for v in held))}
    if all("spend_formula_wape" in w for w in windows):
        accuracy["company_spend_wape_formula"] = float(np.mean([w["spend_formula_wape"] for w in windows]))
    share_who = sorted({k for w in windows for seg in w["model_shares"].values() for k in seg["distance"]})
    accuracy["model_shares"] = {
        "distance": {k: float(np.mean([seg["distance"][k] for w in windows for seg in w["model_shares"].values() if k in seg["distance"]])) for k in share_who},
        "new_models_share": {k: float(np.mean([seg["new_share"][k] for w in windows for seg in w["model_shares"].values() if k in seg["new_share"]])) for k in ["actual", *share_who]},
        "by_segment": {sg: {k: float(np.mean([w["model_shares"][sg]["distance"][k] for w in windows if sg in w["model_shares"]])) for k in share_who}
                       for sg in sorted({sg for w in windows for sg in w["model_shares"]})}}
    out = {"instance": ctx.id, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "scenarios": scenario_ids,
           "protocol": {"cutoffs": [str(c.date()) for c in cutoffs], "horizon_weeks": H, "seeds": seeds, "n_apps": windows[0]["n_apps"] if windows else None,
                        "runs": len(cutoffs) * len(seeds), "point": "central path (every shock at its median)", "interval": "5th-95th percentile across runs"},
           "run_ids": run_ids, "windows": windows, "accuracy": accuracy,
           "business_validation": [bv(k) for k in ("top_tokens", "top_spend", "market_tokens")],
           "comparator_labels": COMPARATOR_LABELS, "scatter": scatter}
    out["headline"] = {
        "company_tokens_wape": {"label": "Error in each company's 8-week tokens (token-weighted, % of actual)", "simulated": accuracy["company_tokens_wape"]["simulation"],
                                "baseline": accuracy["company_tokens_wape"][accuracy["company_tokens_wape"]["best_baseline"]], "unit": "%", "better": "lower"},
        "company_spend_wape": {"label": "Error in each company's 8-week spend (spend-weighted, % of actual)", "simulated": accuracy["company_spend_wape"]["simulation"],
                               "baseline": accuracy["company_spend_wape"][accuracy["company_spend_wape"]["best_baseline"]], "unit": "%", "better": "lower"},
        "coverage90": {"label": "Companies whose actual tokens fell inside the 90% range", "simulated": accuracy["coverage90"], "unit": "%", "better": "higher"},
    }
    ctx.runs_dir.mkdir(parents=True, exist_ok=True)
    (ctx.runs_dir / "evaluation.json").write_text(json.dumps(out, indent=1, default=_json_default))
    return out


def _json_default(o: Any) -> Any:
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if math.isnan(float(o)) else float(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return str(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


# ------------------------------------------------------------------ results view

def _fmt_money(v: float | None) -> str:
    if v is None:
        return "–"
    return f"${v / 1e6:.2f}M" if v >= 1e6 else f"${v / 1e3:.0f}K"


def results_view(ctx: InstanceContext) -> dict[str, Any]:
    """Actual outcomes, the simulation and the other predictions over every cutoff, then the alternative at matching
    cutoffs and seeds. Uses only the current evaluation's run IDs."""
    doc = base_document(ctx)
    ev_path = ctx.runs_dir / "evaluation.json"
    ev = json.loads(ev_path.read_text()) if ev_path.exists() else {}
    base = doc["scenarios"]["baseline"]; alt = doc["scenarios"].get("alternative")
    proto = ev.get("protocol") or {}
    wins = ev.get("windows") or []
    acc = ev.get("accuracy") or {}
    labels = ev.get("comparator_labels") or COMPARATOR_LABELS
    H = int(proto.get("horizon_weeks", 8))
    run_ids = ev.get("run_ids", {})
    sources = [{"id": "actual", "label": "Actual outcome", "kind": "actual", "scenario": base["id"],
                "note": f"OpenRouter's recorded tokens for each company in the {H} weeks after each cutoff; spend is those tokens times the published list prices of the models its segment actually used."},
               {"id": "baseline", "label": "Simulation prediction", "kind": "simulated", "scenario": base["id"], "runs": proto.get("runs"),
                "note": f"The central path of the simulation (every random shock at its median) at each of {len(proto.get('cutoffs', []))} cutoffs; ranges are the 5th-95th percentile across {len(proto.get('seeds', []))} runs per cutoff. Each run reads only weeks before its cutoff, plus the published price lists and listing dates."}]
    alt_docs = run_docs(ctx, alt["id"], "summary", run_ids.get(alt["id"], [])) if alt else []
    if alt:
        sources.append({"id": "alternative", "label": f"{alt['short_title']} · simulation prediction", "kind": "simulated", "scenario": alt["id"], "runs": len(alt_docs),
                        "note": f"{len(alt_docs)} runs at the last {len({d['headline']['t0'] for d in alt_docs})} cutoffs with the same seeds as the simulation of what happened."})
    for s_ in sources:
        s_["kind_label"] = {"actual": "Actual outcome (actual data)", "baseline": "Simulation prediction", "alternative": "Alternative simulation prediction"}[s_["id"]]
        s_["short"] = {"actual": "Actual outcome", "baseline": "Simulation prediction", "alternative": alt["short_title"] if alt else ""}[s_["id"]]
    if not wins:
        doc.update({"sources": sources, "metrics": [], "effects": [], "charts": [], "hero": {"kicker": "No evaluation yet", "stats": [], "claim": ""}})
        return doc
    comps = list(labels)
    mean = lambda xs: float(np.mean([x for x in xs if x is not None])) if any(x is not None for x in xs) else None  # noqa: E731
    def lv(key: str, who: str):
        return mean([w["levels"][key].get(who) for w in wins])
    iv = lambda key: [mean([w["levels"][key]["interval"][0] for w in wins]), mean([w["levels"][key]["interval"][1] for w in wins])]  # noqa: E731
    story_metrics = [
        {"id": "top_tokens", "label": f"Tokens used by the {proto.get('n_apps', 100)} leading companies, {H} weeks (trillions)", "unit": "", "better": "higher",
         "before_actual": lv("top_tokens", "before"), "after_actual": lv("top_tokens", "actual"), "after_sim": lv("top_tokens", "simulation"), "intervals": {"after_sim": iv("top_tokens")}},
        {"id": "top_spend", "label": f"Their spend at list prices, {H} weeks ($ millions)", "unit": "", "better": "higher",
         "before_actual": lv("top_spend", "before"), "after_actual": lv("top_spend", "actual"), "after_sim": lv("top_spend", "simulation"), "intervals": {"after_sim": iv("top_spend")}},
        {"id": "market_tokens", "label": f"All tokens on OpenRouter, {H} weeks (trillions)", "unit": "", "better": "higher",
         "before_actual": lv("market_tokens", "before"), "after_actual": lv("market_tokens", "actual"), "after_sim": lv("market_tokens", "simulation"), "intervals": {}},
        {"id": "prog_leader_share", "label": "Programming tokens on the cutoff's leading coding model, final week (%)", "unit": "%", "better": "higher",
         "before_actual": lv("prog_leader_share", "before"), "after_actual": lv("prog_leader_share", "actual"), "after_sim": lv("prog_leader_share", "simulation"), "intervals": {},
         "note": "The leading model differs by cutoff; values are averages over cutoffs."},
    ]
    baselines = [{"id": k, "label": labels[k], "values": {m["id"]: lv(m["id"], k) for m in story_metrics}} for k in comps]
    ct, cs = acc.get("company_tokens_wape", {}), acc.get("company_spend_wape", {})
    best_t, best_s = ct.get("best_baseline"), cs.get("best_baseline")
    first = wins[0]["cutoff"]; last = wins[-1]["cutoff"]
    doc["design"] = (f"At each of {len(wins)} cutoffs from {first} to {last}, the simulation took the {proto.get('n_apps', 100)} companies with the most tokens in the previous four weeks and "
                     f"carried each forward for {H} weeks: its growth, the models its workloads moved to as new models were listed and prices changed, and its spend. "
                     f"Every parameter is fitted from weeks before the cutoff; after the cutoff the simulation sees only the published price lists and the dates new models were listed. "
                     f"Each prediction is then scored against what the company actually used, next to three standard forecasts made from the same data.")
    story = {"before": {"label": f"The {H} weeks before each cutoff", "sublabel": f"Actual outcome, averaged over {len(wins)} cutoffs"},
             "change": {"label": "The next eight weeks: new models and new prices", "description": "Model launches and list-price changes are supplied as published; the companies' usage after the cutoff is hidden from the simulation.",
                        "stats": [{"label": "Cutoffs scored", "value": len(wins)}, {"label": "Company predictions scored", "value": sum(w["n_apps"] for w in wins)}]},
             "after": {"label": f"The {H} weeks after each cutoff", "sublabel": f"{proto.get('runs')} runs"},
             "columns": {"before_actual": "Actual outcome", "after_actual": "Actual outcome", "after_sim": "Simulation prediction"},
             "metrics": story_metrics, "chart": "company_scatter", "baselines": baselines, "baseline_basis": "after",
             "business_validation": ev.get("business_validation", []),
             "fidelity": [{"label": f"Error in each company's {H}-week tokens, simulation", "value": ct.get("simulation"), "unit": "%"},
                          {"label": f"Best other prediction ({labels.get(best_t, best_t).split(':')[0]})", "value": ct.get(best_t), "unit": "%"},
                          {"label": f"Error in each company's {H}-week spend, simulation", "value": cs.get("simulation"), "unit": "%"},
                          {"label": "Companies inside the simulation's 90% range", "value": acc.get("coverage90"), "unit": "%"}]}
    doc["story"] = story
    # metrics table (company-level accuracy, all predictions)
    metrics = []
    for key, label in (("company_tokens_wape", f"Error in each company's {H}-week tokens (% of actual, token-weighted)"),
                       ("company_spend_wape", f"Error in each company's {H}-week spend (% of actual, spend-weighted)"),
                       ("company_tokens_mdape", f"Median company's error in {H}-week tokens (%)"),
                       ("direction_hit", "Companies whose growth or decline was called correctly (%)")):
        a = acc.get(key, {})
        metrics.append({"id": key, "label": label, "unit": "%", "better": "higher" if key == "direction_hit" else "lower",
                        "values": {"actual": None, "baseline": a.get("simulation"), "alternative": None},
                        "intervals": {}, "note": " · ".join(f"{labels[k].split(':')[0]}: {a.get(k):.1f}%" for k in comps if a.get(k) is not None)})
    for hh, v in (acc.get("by_horizon") or {}).items():
        if str(hh) == str(H):
            continue
        best = min(comps, key=lambda k: v[k])
        metrics.append({"id": f"tokens_wape_{hh}w", "label": f"Error in each company's tokens over the first {hh} week{'s' if str(hh) != '1' else ''} (% of actual, token-weighted)",
                        "unit": "%", "better": "lower", "values": {"actual": None, "baseline": v["simulation"], "alternative": None}, "intervals": {},
                        "note": " · ".join(f"{labels[k].split(':')[0]}: {v[k]:.1f}%" for k in comps) + f" · best other: {labels[best].split(':')[0]}"})
    cls_label = {"steady": "established companies (ranked all eight weeks before the cutoff)", "recurring": "recurring companies (ranked four to seven of those weeks)",
                 "burst": "one-off jobs (ranked one to three of those weeks)"}
    for c, v in (acc.get("by_class") or {}).items():
        metrics.append({"id": f"tokens_wape_{c}", "label": f"Error in {H}-week tokens, {cls_label.get(c, c)} (%; {v['n']:,} predictions)", "unit": "%", "better": "lower",
                        "values": {"actual": None, "baseline": v["simulation"], "alternative": None}, "intervals": {},
                        "note": " · ".join(f"{labels[k].split(':')[0]}: {v[k]:.1f}%" for k in comps)})
    # charts
    sc = ev.get("scatter") or []
    charts = []
    if sc:
        xs = [r["actual"] / 1e9 for r in sc]; ys = [r["simulation"] / 1e9 for r in sc]
        charts.append({"id": "company_scatter", "type": "scatter", "title": f"Each company's {H}-week tokens: simulation prediction against actual (billions, log scale)",
                       "x_label": "Actual outcome", "y_label": "Simulation prediction", "x_log": True, "y_log": True, "x": xs,
                       "series": [{"name": "Simulation prediction", "x": xs, "y": ys, "source": "baseline"}, {"name": "Actual outcome (diagonal)", "x": xs, "y": xs, "source": "actual"}],
                       "note": f"{len(sc)} company predictions over {len(wins)} cutoffs. Points on the grey diagonal would be exact."})
        sx = [r["spend_actual"] for r in sc if r["spend_actual"] > 0]; sy = [r["spend_simulation"] for r in sc if r["spend_actual"] > 0]
        charts.append({"id": "spend_scatter", "type": "scatter", "title": f"Each company's {H}-week spend at list prices: simulation against actual (USD, log scale)",
                       "x_label": "Actual outcome", "y_label": "Simulation prediction", "x_log": True, "y_log": True, "x": sx,
                       "series": [{"name": "Simulation prediction", "x": sx, "y": sy, "source": "baseline"}, {"name": "Actual outcome (diagonal)", "x": sx, "y": sx, "source": "actual"}], "note": ""})
    cx = [w["cutoff"] for w in wins]
    charts.append({"id": "error_by_cutoff", "type": "line", "title": f"Error in each company's {H}-week tokens, by cutoff (%)", "x": cx, "x_label": "", "y_label": "%",
                   "series": [{"name": "Simulation prediction", "y": [round(w["company_tokens_wape"]["simulation"], 1) for w in wins], "source": "baseline"},
                              {"name": f"Best other prediction ({labels.get(best_t, best_t).split(':')[0]})", "y": [round(w["company_tokens_wape"][best_t], 1) for w in wins], "source": "actual", "dashed": True}],
                   "note": "Lower is better. Token-weighted absolute error over the leading companies at each cutoff."})
    if acc.get("by_horizon"):
        hz = list(acc["by_horizon"])
        charts.append({"id": "error_by_horizon", "type": "line", "title": "Error in each company's tokens, by weeks ahead (%)", "x": [f"{h_} wk" for h_ in hz], "x_label": "", "y_label": "%",
                       "series": [{"name": "Simulation prediction", "y": [round(acc["by_horizon"][h_]["simulation"], 1) for h_ in hz], "source": "baseline"},
                                  *[{"name": labels[k].split(":")[0], "y": [round(acc["by_horizon"][h_][k], 1) for h_ in hz], "source": "actual", "dashed": True} for k in comps]],
                       "note": "Lower is better. The same runs, scored on the first weeks after each cutoff."})
    charts.append({"id": "top_tokens_by_cutoff", "type": "line", "title": f"Tokens of the leading companies, {H} weeks after each cutoff (trillions)", "x": cx, "x_label": "", "y_label": "trillion tokens",
                   "series": [{"name": "Simulation prediction", "y": [w["levels"]["top_tokens"]["simulation"] for w in wins], "band": [[w["levels"]["top_tokens"]["interval"][0] for w in wins], [w["levels"]["top_tokens"]["interval"][1] for w in wins]], "source": "baseline"},
                              {"name": "Actual outcome", "y": [w["levels"]["top_tokens"]["actual"] for w in wins], "source": "actual"}], "note": ""})
    hero = {"kicker": f"{sum(w['n_apps'] for w in wins):,} company predictions over {len(wins)} cutoffs, {H} weeks ahead",
            "stats": [{"label": f"Error in each company's {H}-week tokens", "value": ct.get("simulation"), "unit": "%"},
                      {"label": "Best standard forecast", "value": ct.get(best_t), "unit": "%"},
                      {"label": f"Error in each company's {H}-week spend", "value": cs.get("simulation"), "unit": "%"},
                      {"label": "Companies inside the 90% range", "value": acc.get("coverage90"), "unit": "%"}],
            "claim": "Every prediction uses only data from before its cutoff; published list prices and model listing dates are supplied as they happened. Spend is at list prices.",
            "chart": "company_scatter"}
    # alternative vs the simulation of what happened, at matching cutoffs and seeds
    if alt and alt_docs:
        keys = {(d_["headline"]["t0"], d_["seed"]) for d_ in alt_docs}
        base_docs = [d_ for d_ in run_docs(ctx, base["id"], "summary", run_ids.get(base["id"], [])) if (d_["headline"]["t0"], d_["seed"]) in keys]
        def agg(docs_, fn):
            vals = [fn(d_["headline"]) for d_ in docs_]
            return (float(np.mean(vals)), [float(np.percentile(vals, 5)), float(np.percentile(vals, 95))]) if vals else (None, None)
        coding = lambda h: [a for a in h["apps"] if a["segment"] == "programming"]  # noqa: E731
        f_spend = lambda h: sum(sum(a["spend_usd"]) for a in coding(h)) / 1e6  # noqa: E731
        f_tok = lambda h: sum(sum(a["tokens"]) for a in coding(h)) / 1e12  # noqa: E731
        f_all = lambda h: h["total_spend_usd"] / 1e6  # noqa: E731
        f_price = lambda h: float(np.mean(h["segment_price"].get("programming", [np.nan])))  # noqa: E731
        def f_lead(h):
            mult = h.get("price_multipliers") or {}
            mix = h["segment_mix_end"].get("programming", {})
            return 100 * sum(mix.get(m, 0.0) for m in mult) if mult else None
        lead_models = sorted({m for d_ in alt_docs for m in (d_["headline"].get("price_multipliers") or {})})
        def f_lead_base(h, t0):
            ms = {m for d_ in alt_docs if d_["headline"]["t0"] == t0 for m in (d_["headline"].get("price_multipliers") or {})}
            mix = h["segment_mix_end"].get("programming", {})
            return 100 * sum(mix.get(m, 0.0) for m in ms)
        rows = [("coding_spend", f"Spend of the coding companies, {H} weeks ($ millions)", "lower", f_spend),
                ("coding_tokens", f"Tokens of the coding companies, {H} weeks (trillions)", "higher", f_tok),
                ("coding_price", "Blended list price of programming workloads (USD per million tokens)", "lower", f_price),
                ("all_spend", f"Spend of all {proto.get('n_apps', 100)} leading companies, {H} weeks ($ millions)", "lower", f_all)]
        for mid, label, better, fn in rows:
            bm, bi = agg(base_docs, fn); am, ai = agg(alt_docs, fn)
            metrics.append({"id": mid, "label": label, "unit": "", "better": better, "values": {"actual": None, "baseline": bm, "alternative": am},
                            "intervals": {k: v for k, v in (("baseline", bi), ("alternative", ai)) if v}, "note": "Simulated only; matching cutoffs and seeds."})
        lb = float(np.mean([f_lead_base(d_["headline"], d_["headline"]["t0"]) for d_ in base_docs])) if base_docs else None
        la = float(np.mean([f_lead(d_["headline"]) for d_ in alt_docs]))
        metrics.append({"id": "leader_share", "label": "Programming tokens on the repriced model, final week (%)", "unit": "%", "better": "",
                        "values": {"actual": None, "baseline": lb, "alternative": la}, "intervals": {}, "note": "Simulated only. Repriced model(s): " + ", ".join(lead_models)})
        mv = {m["id"]: m["values"] for m in metrics}
        cb, ca_ = mv["coding_spend"]["baseline"], mv["coding_spend"]["alternative"]
        hero["alternative"] = {"kicker": f"Alternative: {alt['short_title']}",
                               "stats": [{"label": "Coding companies' spend", "value": f"${cb:.2f}M → ${ca_:.2f}M ({(ca_ / cb - 1) * 100:+.0f}%)" if cb else None, "unit": ""},
                                         {"label": "Programming tokens on the repriced model", "value": f"{lb:.1f}% → {la:.1f}%" if lb is not None else None, "unit": ""}],
                               "text": (f"Doubling the leading paid coding model's list price moves some coding workloads to other models, and the coding companies' spend at list prices "
                                        f"changes from ${cb:.2f}M to ${ca_:.2f}M over {H} weeks in the simulation. This is a simulated alternative, not an observed price change."),
                               "chart": "alt_mix"}
        # chart: programming share of repriced model by week
        def weekly_share(docs_, alt_side):
            out = []
            for d_ in docs_:
                ms = set(d_["headline"].get("price_multipliers") or {}) if alt_side else {m for a_ in alt_docs if a_["headline"]["t0"] == d_["headline"]["t0"] for m in (a_["headline"].get("price_multipliers") or {})}
                out.append([100 * sum(wk.get(m, 0.0) for m in ms) for wk in d_["headline"]["segment_mix_weekly"].get("programming", [])])
            return np.mean(out, axis=0).round(2).tolist() if out else []
        charts.append({"id": "alt_mix", "type": "line", "title": "Programming tokens on the repriced model, by week after the cutoff (%)", "x": [f"week {i + 1}" for i in range(H)], "x_label": "", "y_label": "%",
                       "series": [{"name": "As it happened (simulated)", "y": weekly_share(base_docs, False), "source": "baseline"}, {"name": alt["short_title"], "y": weekly_share(alt_docs, True), "source": "alternative"}],
                       "note": "Matching cutoffs and seeds."})
    doc.update({"sources": sources, "metrics": metrics, "effects": [], "charts": charts, "hero": hero, "evaluation": {"generated": ev.get("generated"), "protocol": proto}})
    return doc
