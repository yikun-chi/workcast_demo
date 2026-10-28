"""Attention world: readers with information needs on reference topics, choosing each day whether a need ends on a
Wikipedia article (and through which access method) or somewhere else.

Layers, stepped one day at a time from a cutoff t0 for H days:

  Needs. Every article has a daily need: its recent level, its own seasonal shape over the year (the school year, the
  holidays, anniversaries), measured on the years before t0 and pooled with the other articles of its section, and its
  weekly rhythm. Unexpected attention (news, a death, a film) arrives as shocks that fade.

  Readers (seat `readers`, one per section of the topic list and access method: desktop, mobile web, app). Each week
  the kernel offers the section's readers how strongly to keep coming to Wikipedia, from "drift away fast" to "come
  back", with the weights implied by how their habit has drifted in the years before t0; the rule adapter draws one,
  and a language-model seat is a configuration change. Alternatives add a new channel (an AI answer engine) that takes
  a share of the needs it reaches.

Every parameter is fitted at t0 from days strictly before it (calibration/attention.yaml fixes the windows and the
pooling); views after t0 are read only by evaluate() for scoring. Each run simulates `paths` independent paths; the
point prediction is the mean over runs and paths.
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
from scipy.special import ndtri

from ..instances import InstanceContext
from ..kernel.world import Agent, BaseWorld, RunSummary
from ..policies.base import Observation
from ..policies.registry import load_registry
from ..store.runs import RunWriter

DAY = pd.Timedelta(days=1)
ACCESS = ("desktop", "mobile-web", "mobile-app")
HABITS = ["drift away fast", "drift away", "drift away slowly", "hold", "drift back slowly", "drift back", "come back"]


@dataclass
class AttentionData:
    dates: pd.DatetimeIndex
    articles: pd.DataFrame          # article_id, title, section, ...
    views: np.ndarray               # [day, article, access] float32

    def idx(self, t: pd.Timestamp) -> int:
        return int(self.dates.searchsorted(pd.Timestamp(t)))


@lru_cache(maxsize=2)
def _load(root: str, mtime: float) -> AttentionData:
    from pathlib import Path
    n = Path(root)
    arts = pd.read_parquet(n / "articles.parquet").sort_values("article_id").reset_index(drop=True)
    v = pd.read_parquet(n / "views.parquet")
    dates = pd.date_range(v.date.min(), v.date.max(), freq="D")
    cube = np.zeros((len(dates), len(arts), len(ACCESS)), dtype=np.float32)
    ai = {a: i for i, a in enumerate(ACCESS)}
    np.add.at(cube, (dates.get_indexer(v.date), v.article_id.to_numpy(), v.access.astype(str).map(ai).to_numpy()), v.views.to_numpy(dtype=np.float32))
    return AttentionData(dates, arts, cube)


def load_data(ctx: InstanceContext) -> AttentionData:
    p = ctx.data_normalized / "views.parquet"
    if not p.exists():
        raise FileNotFoundError(f"{p} missing; run `orgsim ingest {ctx.id}`")
    return _load(str(ctx.data_normalized), p.stat().st_mtime)


def _shrink(x: np.ndarray, groups: np.ndarray, weight: float) -> np.ndarray:
    """Pull each article's estimate (axis 1 = articles) toward its section mean: weight on the article's own value."""
    out = x.copy()
    for g in np.unique(groups):
        m = groups == g
        out[:, m] = weight * x[:, m] + (1 - weight) * x[:, m].mean(1, keepdims=True)
    return out


def fit_at(d: AttentionData, t0: pd.Timestamp, par: dict[str, Any]) -> dict[str, Any]:
    """Every parameter from days strictly before t0. Seasonal positions are aligned to t0: position p of a year block
    is the week p after the same calendar date one, two, ... years earlier."""
    k = d.idx(t0)
    years = int(par.get("season_years", 4))
    blocks = [j for j in range(1, years + 1) if k - 364 * j >= 0]
    if len(blocks) < 2:
        raise ValueError(f"fewer than two years of views before {t0.date()}")
    y = np.log1p(d.views[:k].astype(float))                      # [day, article, access]
    groups = d.articles.section.to_numpy()
    w_season = float(par.get("season_article_weight", 0.5))
    # annual shape by week position: weekly medians relative to each block's mean, averaged over blocks
    profs = []
    for j in blocks:
        blk = y[k - 364 * j:k - 364 * (j - 1)]                    # [364, N, A]
        wk = np.median(blk.reshape(52, 7, *blk.shape[1:]), axis=1)  # [52, N, A]
        profs.append(wk - wk.mean(0, keepdims=True))
    prof = np.mean(profs, axis=0)
    prof = (np.roll(prof, 1, 0) + prof + np.roll(prof, -1, 0)) / 3   # three-week smoothing (circular)
    prof = np.stack([_shrink(prof[:, :, a], groups, w_season) for a in range(len(ACCESS))], axis=2)
    # weekly rhythm from the last year: day-of-week medians of the residual from the weekly level
    last = y[k - 364:k]
    lw = last.reshape(52, 7, *last.shape[1:])
    rhythm_by_pos = np.median(lw - lw.mean(1, keepdims=True), axis=0)   # [7, N, A] by position within the block's weeks
    dow0 = d.dates[k - 364].dayofweek
    rhythm = np.zeros_like(rhythm_by_pos)
    for p_ in range(7):
        rhythm[(dow0 + p_) % 7] = rhythm_by_pos[p_]
    rhythm = np.stack([_shrink(rhythm[:, :, a], groups, float(par.get("rhythm_article_weight", 0.5))) for a in range(len(ACCESS))], axis=2)
    # level: deseasonalized median of the last `level_days`
    L = int(par.get("level_days", 28))
    dd = np.arange(k - L, k)
    pos = (dd - (k - 364)) // 7
    des = y[dd] - prof[pos] - rhythm[d.dates[dd].dayofweek.to_numpy()]
    level = np.median(des, axis=0)                                # [N, A]
    # yearly drift of each section's habit (log change per year of block means), and its spread across blocks
    means = np.array([y[k - 364 * j:k - 364 * (j - 1)].mean(0) for j in blocks])          # [J, N, A]
    changes = means[:-1] - means[1:]                              # year-on-year log changes, newest first
    secs = sorted(set(groups))
    sec_idx = np.array([secs.index(g) for g in groups])
    drift_hist = np.array([[np.median(changes[j][sec_idx == s], axis=0) for s in range(len(secs))] for j in range(len(changes))])   # [J-1, S, A]
    nd = int(par.get("drift_years", 2))
    drift = drift_hist[:nd].mean(0) * float(par.get("drift_damping", 0.5))            # [S, A]
    drift_sd = np.maximum(drift_hist.std(0) if len(drift_hist) > 1 else np.abs(drift) * 0.5, 0.02)
    # shocks: residuals of the last year after level, shape and rhythm; AR(1) per article and access
    pos_l = (np.arange(k - 364, k) - (k - 364)) // 7
    fitted_l = level[None] - (0) + prof[pos_l] + rhythm[d.dates[k - 364:k].dayofweek.to_numpy()]
    res = last - fitted_l - (last - fitted_l).mean(0, keepdims=True)
    a0, a1 = res[:-1], res[1:]
    rho = np.clip((a0 * a1).sum(0) / np.maximum((a0 * a0).sum(0), 1e-9), 0.0, 0.95)
    sd = np.sqrt(np.maximum((a1 - rho * a0).var(0), 1e-6))
    shock0 = res[-1]
    return {"t0": str(t0.date()), "prof": prof, "rhythm": rhythm, "level": level, "drift": drift, "drift_sd": drift_sd,
            "sections": secs, "sec_idx": sec_idx, "rho": rho, "sd": sd, "shock0": shock0, "blocks": len(blocks)}


_FIT_CACHE: dict[tuple, dict[str, Any]] = {}


def cached_fit(ctx: InstanceContext, d: AttentionData, t0: pd.Timestamp, par: dict[str, Any]) -> dict[str, Any]:
    key = (ctx.id, str(t0.date()), json.dumps(par, sort_keys=True), id(d))
    if key not in _FIT_CACHE:
        if len(_FIT_CACHE) > 4:
            _FIT_CACHE.clear()
        _FIT_CACHE[key] = fit_at(d, t0, par)
    return _FIT_CACHE[key]


class World(BaseWorld):
    @classmethod
    def from_instance(cls, ctx: InstanceContext, scenario: dict[str, Any], seed: int) -> "World":
        w = scenario.get("world", {})
        t0 = pd.Timestamp(w["t0"])
        H = int(w.get("horizon_days", scenario.get("horizon_days", 182)))
        return cls(ctx, scenario, seed, t0.to_pydatetime(), (t0 + H * DAY).to_pydatetime())

    def __init__(self, ctx: InstanceContext, scenario: dict[str, Any], seed: int, start: datetime, end: datetime) -> None:
        super().__init__(ctx, scenario, seed, start, end)
        t_cal = time.time()
        self.rng = np.random.default_rng(seed)
        self.par = ctx.yaml("calibration/attention.yaml")
        self.t0 = pd.Timestamp(start)
        self.H = int(round((end - start) / timedelta(days=1)))
        self.P = int(scenario.get("world", {}).get("paths", self.par.get("paths", 20)))
        self.d = load_data(ctx)
        self.fit = cached_fit(ctx, self.d, self.t0, self.par)
        self.registry = load_registry(ctx)
        self.days = pd.date_range(self.t0, periods=self.H, freq="D")
        self.ai = [iv for iv in (scenario.get("interventions") or []) if iv.get("type") == "ai_channel"]
        for s in self.fit["sections"]:
            for a in ACCESS:
                self.agents[f"readers:{s}:{a}"] = Agent(id=f"readers:{s}:{a}", role="readers", org_unit=s, attributes={"access": a}, seat="readers")
        K = len(HABITS)
        from scipy.stats import norm
        edges = ndtri(np.linspace(0, 1, K + 1).clip(1e-9, 1 - 1e-9))
        self.bin_mean = (norm.pdf(edges[:-1]) - norm.pdf(edges[1:])) * K
        self.bin_mean /= np.sqrt(np.mean(self.bin_mean ** 2))
        self.calibration_s = time.time() - t_cal

    def _ai_take(self, day: pd.Timestamp, s: str, a: str) -> float:
        """Share of needs an AI answer channel (scenario) takes on this day for section s and access a."""
        take = 0.0
        for iv in self.ai:
            start = pd.Timestamp(iv["start"]); full = pd.Timestamp(iv.get("full", iv["start"]))
            if day < start:
                continue
            ramp = 1.0 if day >= full else (day - start) / max(full - start, DAY)
            if iv.get("access") and a not in iv["access"]:
                continue
            take += float(iv.get("share", 0.0)) * float(ramp) * float((iv.get("by_section") or {}).get(s, 1.0))
        return min(take, 0.95)

    def run(self, writer: RunWriter) -> RunSummary:
        self._writer = writer
        t_run = time.time()
        f, P, H = self.fit, self.P, self.H
        N, A = f["level"].shape
        S = len(f["sections"])
        pol = self.registry.for_seat("readers")
        shock = np.tile(f["shock0"], (P, 1, 1))                          # [P, N, A]
        habit = np.zeros((P, S, A))                                      # cumulative log change of each section's habit
        weekly_draw = np.zeros((P, S, A))
        month_keys = sorted({(dd.year, dd.month) for dd in self.days})
        mi = {m: i for i, m in enumerate(month_keys)}
        months = np.zeros((P, len(month_keys), N))                       # views per path, month and article (all access)
        months_acc = np.zeros((P, len(month_keys), A))
        habit_counts = np.zeros((S, len(HABITS)), dtype=int)
        for h, day in enumerate(self.days):
            if h % 7 == 0:
                # each section's readers choose this week's habit (rule: draw by weight) on every path
                for si, s in enumerate(f["sections"]):
                    for ai_, a in enumerate(ACCESS):
                        for p_ in range(P):
                            obs = Observation(agent_id=f"readers:{s}:{a}", role="readers", sim_time=str(day.date()),
                                              context={"section": s, "access": a, "yearly_drift": round(float(f["drift"][si, ai_]), 4)},
                                              options=[{"kind": "habit", "target": t, "weight": 1.0 / len(HABITS)} for t in HABITS])
                            act = pol.decide(obs, self.rng)
                            i = HABITS.index(act.target) if act.target in HABITS else int(self.rng.integers(len(HABITS)))
                            habit_counts[si, i] += 1
                            weekly_draw[p_, si, ai_] = self.bin_mean[i]
                            if p_ == 0 and ai_ == 0:
                                self.emit(agent_id=f"readers:{s}:{a}", role="readers", org_unit=s, activity="habit", action_type="decide",
                                          provenance="simulated", attributes={"chosen": HABITS[i], "week": str(day.date())})
            # habit: the fitted yearly drift spread over the days, plus the chosen weekly deviation (random walk)
            habit += f["drift"][None] / 365.0 + (f["drift_sd"][None] / math.sqrt(52.0)) * weekly_draw / 7.0
            shock = f["rho"][None] * shock + f["sd"][None] * self.rng.standard_normal(shock.shape)
            pos = (h // 7) % 52
            mean = f["level"][None] + f["prof"][pos][None] + f["rhythm"][day.dayofweek][None] + habit[:, f["sec_idx"], :] + shock
            v = np.expm1(mean).clip(min=0)                                 # [P, N, A]
            if self.ai:
                take = np.array([[self._ai_take(day, s, a) for a in ACCESS] for s in f["sections"]])   # [S, A]
                v = v * (1 - take[f["sec_idx"]])[None]
            months[:, mi[(day.year, day.month)], :] += v.sum(2)
            months_acc[:, mi[(day.year, day.month)], :] += v.sum(1)
            for _ in range(24):
                self.clock.advance()
        self.runtime_s = time.time() - t_run
        mean_m = months.mean(0)                                            # [M, N]
        tot = months.sum(2)                                                # [P, M]
        headline = {
            "t0": str(self.t0.date()), "horizon_days": H, "paths": P, "months": [f"{y}-{m:02d}" for y, m in month_keys],
            "month_days": [int(sum(1 for dd in self.days if (dd.year, dd.month) == k_)) for k_ in month_keys],
            "article_views": np.round(mean_m, 1).tolist(),
            "total_views": np.round(tot.mean(0), 0).tolist(), "total_interval": [np.round(np.percentile(tot, 5, 0), 0).tolist(), np.round(np.percentile(tot, 95, 0), 0).tolist()],
            "access_views": np.round(months_acc.mean(0), 0).tolist(),
            "sections": f["sections"], "section_drift": np.round(f["drift"], 4).tolist(),
            "habits": {s: {HABITS[i]: int(habit_counts[si, i]) for i in range(len(HABITS))} for si, s in enumerate(f["sections"])},
            "ai_channels": self.ai, "policies": self.registry.describe(), "runtime_s": round(self.runtime_s, 2), "calibration_s": round(self.calibration_s, 2),
        }
        return RunSummary(run_id=writer.run_id, instance=self.ctx.id, scenario=self.scenario.get("id", "baseline"), seed=self.seed,
                          start=str(self.t0.date()), end=str((self.t0 + H * DAY).date()), ticks=H * 24, events=self._n_events, headline=headline)


# ------------------------------------------------------------------ evaluation

COMPARATOR_LABELS = {
    "carry_forward": "No change: the last month's daily views carried forward",
    "seasonal_naive": "Same month last year",
    "historical_average": "Historical average: the same month in the three previous years",
    "trend": "Recent trend: a straight line through the logs of the last twelve months",
    "ets": "Exponential smoothing (ETS with yearly seasonality, chosen by AICc on four years of months)",
}


def protocol_cutoffs(proto: dict[str, Any]) -> list[pd.Timestamp]:
    if proto.get("cutoffs"):
        return [pd.Timestamp(c) for c in proto["cutoffs"]]
    g = proto["cutoff_grid"]
    return list(pd.date_range(g["start"], g["end"], freq="MS"))


def monthly(d: AttentionData, start: pd.Timestamp, end: pd.Timestamp) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Calendar months in [start, end): labels, days per month, views per month and article (all access methods)."""
    i0, i1 = d.idx(start), d.idx(end)
    v = d.views[i0:i1].sum(2)                                            # [days, N]
    per = d.dates[i0:i1].to_period("M")
    labels = sorted(set(str(p) for p in per))
    out = np.zeros((len(labels), v.shape[1])); days = np.zeros(len(labels))
    for j, lab in enumerate(labels):
        m = np.asarray([str(p) == lab for p in per])
        out[j] = v[m].sum(0); days[j] = m.sum()
    return labels, days, out


def comparators(d: AttentionData, t0: pd.Timestamp, months: list[str], days: np.ndarray, hist_months: int) -> dict[str, np.ndarray]:
    """Monthly views per article and in total (last column) from months before t0 only."""
    from ..evaluation.forecast import auto_ets, trend
    H = len(months)
    labs, hd, hv = monthly(d, t0 - pd.DateOffset(months=hist_months), t0)
    hv = np.column_stack([hv, hv.sum(1)])                                # articles + total
    U = hv.shape[1]
    per_day = hv / hd[:, None]
    cf = np.repeat(per_day[-1:], H, axis=0) * days[:, None]
    def same_month(back: int) -> np.ndarray:
        out = np.full((H, U), np.nan)
        for j, m in enumerate(months):
            lab = str(pd.Period(m) - 12 * back)
            if lab in labs:
                i = labs.index(lab)
                out[j] = per_day[i] * days[j]
        return out
    sn = same_month(1)
    with np.errstate(all="ignore"):
        ha = np.nanmean(np.stack([same_month(b) for b in (1, 2, 3)]), axis=0)
    sn = np.where(np.isfinite(sn), sn, cf); ha = np.where(np.isfinite(ha), ha, cf)
    tr = np.zeros((H, U)); et = np.zeros((H, U))
    lg = np.log1p(per_day)
    for u in range(U):
        tr[:, u] = np.expm1(trend(lg[-12:, u], H)) * days
        et[:, u] = np.expm1(np.asarray(auto_ets(lg[-48:, u], H, period=12))) * days
    return {"carry_forward": cf, "seasonal_naive": sn, "historical_average": ha, "trend": np.clip(tr, 0, None), "ets": np.clip(et, 0, None)}


def _run_world(ctx: InstanceContext, scenario: dict[str, Any], seed: int, t0: str) -> RunSummary:
    sc = json.loads(json.dumps(scenario))
    sc.setdefault("world", {})["t0"] = t0
    writer = RunWriter(ctx.id, sc["id"], config={"instance": ctx.id, "scenario": sc, "seed": seed, "evaluation": True})
    world = World.from_instance(ctx, sc, seed)
    summary = world.run(writer)
    writer.close(summary.to_json())
    print(f"[{ctx.id}] {sc['id']} t0={t0} seed={seed} -> {writer.run_id} (calibration {world.calibration_s:.1f}s, run {world.runtime_s:.1f}s)", flush=True)
    return summary


def score_cutoff(d: AttentionData, t0: pd.Timestamp, headlines: list[dict[str, Any]], hist_months: int) -> dict[str, Any]:
    h0 = headlines[0]
    months = h0["months"]; days = np.array(h0["month_days"], dtype=float)
    end = t0 + pd.Timedelta(days=int(h0["horizon_days"]))
    _, _, act = monthly(d, t0, end)                                      # scoring only: views after t0
    sim = np.mean([np.array(h["article_views"]) for h in headlines], axis=0)
    comp = comparators(d, t0, months, days, hist_months)
    _, bd, before = monthly(d, t0 - pd.DateOffset(months=len(months)), t0)
    lo = np.mean([h["total_interval"][0] for h in headlines], axis=0); hi = np.mean([h["total_interval"][1] for h in headlines], axis=0)
    return {"cutoff": str(t0.date()), "months": months, "month_days": days.tolist(),
            "total": {"actual": act.sum(1).tolist(), "simulation": sim.sum(1).tolist(), "interval": [lo.tolist(), hi.tolist()],
                      "before": before.sum(1).tolist(), **{k: v[:, -1].tolist() for k, v in comp.items()}},
            "articles": {"actual": np.round(act, 1).tolist(), "simulation": np.round(sim, 1).tolist(), **{k: np.round(v[:, :-1], 1).tolist() for k, v in comp.items()}}}


def _cutoff_job(job: tuple) -> dict[str, Any]:
    iid, scenario, t0s, seeds, hist_months, score = job
    from ..instances import get_instance
    ctx = get_instance(iid)
    runs = [_run_world(ctx, scenario, sd, t0s) for sd in seeds]
    if not score:
        return {"cutoff": t0s, "run_ids": [r.run_id for r in runs], "headlines": [r.headline for r in runs]}
    res = score_cutoff(load_data(ctx), pd.Timestamp(t0s), [r.headline for r in runs], hist_months)
    res["run_ids"] = [r.run_id for r in runs]
    return res


def _jobs(ctx, scenario, cutoffs, seeds, hist_months, workers, score=True):
    jobs = [(ctx.id, scenario, str(c.date()), seeds, hist_months, score) for c in cutoffs]
    if workers <= 1:
        yield from map(_cutoff_job, jobs)
    else:
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as ex:
            yield from ex.map(_cutoff_job, jobs)


WHO = ["simulation"] + list(COMPARATOR_LABELS)


def window_errors(w: dict[str, Any], months: list[int] | None = None) -> dict[str, dict[str, float]]:
    """Per prediction: error in total monthly views (% of actual, mean over months) and article-level WAPE (%)."""
    sel = slice(None) if months is None else months
    ta = np.array(w["total"]["actual"])[sel]
    aa = np.array(w["articles"]["actual"])[sel]
    out = {}
    for k in WHO:
        tp = np.array(w["total"][k])[sel]; ap = np.array(w["articles"][k])[sel]
        out[k] = {"total_ape": float(np.mean(np.abs(tp - ta) / ta) * 100), "total_ae": float(np.mean(np.abs(tp - ta))),
                  "article_wape": float(np.abs(ap - aa).sum() / aa.sum() * 100)}
    out["_actual_total_mean"] = float(ta.mean())
    return out


def score_windows(wins: list[dict[str, Any]], months: list[int] | None = None) -> dict[str, Any]:
    errs = [window_errors(w, months) for w in wins]
    out = {}
    for key in ("total_ape", "total_ae", "article_wape"):
        mae = {k: float(np.mean([e[k][key] for e in errs])) for k in WHO}
        best = min(COMPARATOR_LABELS, key=lambda k: mae[k])
        out[key] = {"mae": mae, "best_comparator": best, "windows": len(errs),
                    "error_reduction_pct": 100 * (1 - mae["simulation"] / mae[best]) if mae[best] else None}
    lvl = float(np.mean([e["_actual_total_mean"] for e in errs]))
    out["total_ae"]["mean_actual"] = lvl
    out["total_ae"]["accuracy_pct"] = {k: 100 * (1 - v / lvl) for k, v in out["total_ae"]["mae"].items()}
    out["total_ape"]["accuracy_pct"] = {k: 100 - v for k, v in out["total_ape"]["mae"].items()}
    out["article_wape"]["accuracy_pct"] = {k: 100 - v for k, v in out["article_wape"]["mae"].items()}
    return out


def evaluate(ctx: InstanceContext, scenario_ids: list[str]) -> dict[str, Any]:
    from ..scenarios import load_scenario
    proto = ctx.yaml("evaluation/protocol.yaml")
    all_cut = protocol_cutoffs(proto)
    n_dev = int(proto.get("dev_cutoffs", max(2, len(all_cut) // 4)))
    only = proto.get("run_only")
    cutoffs = all_cut[:n_dev] if only == "dev" else all_cut
    seeds = [int(s) for s in proto.get("seeds", [1, 2, 3])]
    workers = max(1, int(proto.get("workers", 1)))
    hist_months = int(proto.get("comparator_history_months", 48))
    base_id = proto.get("baseline_scenario", "baseline")
    base = load_scenario(ctx, base_id)
    wins = list(_jobs(ctx, base, cutoffs, seeds, hist_months, workers))
    dev_set = {str(c.date()) for c in all_cut[:n_dev]}
    dev = [w for w in wins if w["cutoff"] in dev_set]; held = [w for w in wins if w["cutoff"] not in dev_set]
    M = len(wins[0]["months"]) if wins else 6
    accuracy = {"all": score_windows(wins), "dev": score_windows(dev) if dev else None, "held_out": score_windows(held) if held else None,
                "by_month_held_out": {str(m + 1): score_windows(held, [m]) for m in range(M)} if held else None,
                "by_month_dev": {str(m + 1): score_windows(dev, [m]) for m in range(M)} if dev else None}
    events = []
    for ev in proto.get("events") or []:
        sel = [w for w in wins if w["cutoff"] in ev["cutoffs"]]
        events.append({**ev, "windows": [{"cutoff": w["cutoff"], "months": w["months"], "total": w["total"], "errors": window_errors(w)} for w in sel]})
    run_ids = {base_id: [r for w in wins for r in w["run_ids"]]}
    alt_id = ctx.meta.get("scenarios", {}).get("alternative")
    alt_cuts = []
    if alt_id and alt_id in scenario_ids and only != "dev":
        alt = load_scenario(ctx, alt_id)
        run_ids[alt_id] = []
        for res in _jobs(ctx, alt, [pd.Timestamp(c) for c in proto.get("alternative_cutoffs") or []], seeds, hist_months, workers, score=False):
            run_ids[alt_id] += res["run_ids"]; alt_cuts.append(res["cutoff"])
    bv = []
    for key, label in (("total_ae", "Monthly views of the 1,000 reference articles (all access methods)"),):
        rows = [{"cutoff": w["cutoff"], "simulation_mae": window_errors(w)["simulation"][key], "baselines": {k: window_errors(w)[k][key] for k in COMPARATOR_LABELS}} for w in (held or wins)]
        sim = float(np.mean([r["simulation_mae"] for r in rows])); bm = {k: float(np.mean([r["baselines"][k] for r in rows])) for k in COMPARATOR_LABELS}
        best = min(bm, key=bm.get)
        bv.append({"id": key, "label": label, "windows": rows, "simulation_mae": sim, "baseline_mae": bm, "best_baseline": best,
                   "beats_best_baseline": sim < bm[best], "error_reduction_pct": 100 * (1 - sim / bm[best])})
    result = {"instance": ctx.id, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
              "scenarios": [base_id] + ([alt_id] if alt_cuts else []), "run_ids": run_ids,
              "protocol": {"cutoffs": [w["cutoff"] for w in wins], "dev_cutoffs": [w["cutoff"] for w in dev], "held_out_cutoffs": [w["cutoff"] for w in held],
                           "horizon_months": M, "seeds": seeds, "paths": int(ctx.yaml("calibration/attention.yaml").get("paths", 20)),
                           "runs": sum(len(w["run_ids"]) for w in wins), "run_only": only, "alternative_cutoffs": alt_cuts},
              "comparator_labels": COMPARATOR_LABELS, "accuracy": accuracy, "events": events, "business_validation": bv,
              "windows": [{k: v for k, v in w.items() if k != "articles"} for w in wins]}
    out = ctx.runs_dir / ("evaluation_dev.json" if only == "dev" else "evaluation.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, default=lambda o: o.tolist() if isinstance(o, np.ndarray) else (None if isinstance(o, float) and math.isnan(o) else str(o))))
    return result
