"""Other predictions of separations per agency and month, fixed before scoring. Each reads only separation records
effective and published by the cutoff (the same records the twins are fitted on) and the December headcount at the
cutoff. Called by orgsim.worlds.workforce_forecast.

  seasonal_naive   each agency's count in the same month a year earlier
  average          each agency's average monthly count over the last 12 months
  trend            a regression on the last 36 months with a linear trend and month-of-year effects, extended forward
  ets              additive Holt-Winters exponential smoothing with a damped trend (the standard method for monthly series),
                   smoothing constants chosen on the development cutoffs (calibration/selection.json)
  programme        for a cutoff followed by an announced policy: same month a year earlier, quits and retirements raised by
                   the published return-to-office effect, plus the resignation offer as a lump in its effective month sized
                   by the published early-retirement window effect on each agency's own voluntary leaving rate
"""
from __future__ import annotations

import importlib.util
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

_spec = importlib.util.spec_from_file_location("fedwork_ingest", Path(__file__).resolve().parents[1] / "ingest" / "run.py")
ING = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ING)  # type: ignore[union-attr]


@lru_cache(maxsize=2)
def _load(root: str, mtime: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = Path(root)
    return pd.read_parquet(d / "separations.parquet"), pd.read_parquet(d / "headcounts.parquet")


def load(ctx) -> tuple[pd.DataFrame, pd.DataFrame]:
    p = ctx.data_normalized / "separations.parquet"
    return _load(str(ctx.data_normalized), p.stat().st_mtime)


def history(seps: pd.DataFrame, heads: pd.DataFrame, cutoff: str, groups: list[str]) -> pd.DataFrame:
    """Monthly counts per group and type from records visible at the cutoff, from January 2018."""
    gmap = ING.agency_groups(heads, cutoff)
    s = ING.visible(seps, cutoff)
    s = s[s.effective_month >= "2018-01"].assign(group=lambda d: d.agency_code.map(gmap).fillna("OTHER"))
    months = [str(p) for p in pd.period_range("2018-01", cutoff, freq="M")]
    g = s.groupby(["group", "effective_month", "type"]).n.sum().unstack("type", fill_value=0)
    idx = pd.MultiIndex.from_product([groups, months], names=["group", "effective_month"])
    return g.reindex(idx, fill_value=0).reindex(columns=ING.TYPES, fill_value=0)


def holt_winters(y: np.ndarray, h: int, alpha: float, beta: float, gamma: float, phi: float, m: int = 12) -> np.ndarray:
    """Additive Holt-Winters with a damped trend; initial level, trend and season from the first two years."""
    y = np.asarray(y, dtype=float)
    level = y[:m].mean(); trend = (y[m:2 * m].mean() - y[:m].mean()) / m
    season = list(y[:m] - level)
    for t in range(len(y)):
        s = season[t % m]
        prev_level = level
        level = alpha * (y[t] - s) + (1 - alpha) * (level + phi * trend)
        trend = beta * (level - prev_level) + (1 - beta) * phi * trend
        season[t % m] = gamma * (y[t] - level) + (1 - gamma) * s
    out = []
    damp = 0.0
    for k in range(1, h + 1):
        damp += phi ** k
        out.append(level + damp * trend + season[(len(y) + k - 1) % m])
    return np.maximum(np.array(out), 0.0)


def _frame(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["group", "month", "n"])


def compute(ctx, cutoff: str, months: list[str], groups: list[str], ets_params: dict | None = None) -> dict:
    seps, heads = load(ctx)
    hist = history(seps, heads, cutoff, groups)
    tot = hist.sum(axis=1)
    all_months = [str(p) for p in pd.period_range("2018-01", cutoff, freq="M")]
    p_cut = pd.Period(cutoff, "M")
    h = max(int((pd.Period(m, "M") - p_cut).n) for m in months)
    if ets_params is None:
        sel = json.loads((ctx.calibration_dir / "selection.json").read_text())
        ets_params = sel["comparators"]["ets"]
    out: dict = {}
    rows_sn, rows_avg, rows_tr, rows_ets = [], [], [], []
    for g in groups:
        y = tot.loc[g].reindex(all_months).to_numpy(dtype=float)
        last = dict(zip(all_months, y))
        for m in months:
            rows_sn.append((g, m, last.get(str(pd.Period(m, "M") - 12), 0.0)))
            rows_avg.append((g, m, float(np.mean(y[-12:]))))
        yy = y[-36:]
        t = np.arange(36)
        moy = np.array([int(x[5:7]) for x in all_months[-36:]])
        X = np.column_stack([t] + [(moy == k).astype(float) for k in range(1, 13)])
        b, *_ = np.linalg.lstsq(X, yy, rcond=None)
        for m in months:
            k = int((pd.Period(m, "M") - p_cut).n)
            mm = int(m[5:7])
            rows_tr.append((g, m, max(0.0, float(b[0] * (35 + k) + b[mm]))))
        fc = holt_winters(y, h, **ets_params)
        for m in months:
            rows_ets.append((g, m, float(fc[int((pd.Period(m, "M") - p_cut).n) - 1])))
    out["seasonal_naive"] = {"label": "Same month last year", "pred": _frame(rows_sn),
                             "description": "Same month last year repeats each agency's count from the same month of the previous year."}
    out["average"] = {"label": "Last 12-month average", "pred": _frame(rows_avg),
                      "description": "Last 12-month average gives each agency its average monthly count over the year before the cutoff."}
    out["trend"] = {"label": "Recent trend", "pred": _frame(rows_tr),
                    "description": "Recent trend fits each agency's last 36 months with a straight line and month-of-year effects and extends it."}
    out["ets"] = {"label": "Exponential smoothing", "pred": _frame(rows_ets),
                  "description": "Exponential smoothing is additive Holt-Winters with a damped trend, the standard method for monthly series, with its smoothing constants chosen on the development years."}
    proto = ctx.yaml("evaluation/protocol.yaml")
    policy = next((c for c in proto["cutoffs"] if c["cutoff"] == cutoff), {}).get("policy")
    pri = {k: float(v["central"]) for k, v in ctx.yaml("calibration/priors.yaml")["parameters"].items()}
    rows_pg = []
    gmap = ING.agency_groups(heads, cutoff)
    hc = heads[heads.snapshot == cutoff].assign(group=lambda d: d.agency_code.map(gmap).fillna("OTHER"))
    ft = hc[hc.fulltime == 1].groupby("group").headcount.sum()
    allh = hc.groupby("group").headcount.sum()
    for g in groups:
        by_t = hist.loc[g]
        vol_12 = float(by_t[["quit", "retire"]].iloc[-12:].to_numpy().sum()) / 12.0
        v = vol_12 / max(float(allh.get(g, 0.0)), 1.0)
        lump = (pri["drp_window_mult"] - 1.0) * (1.0 - (1.0 - v) ** pri["drp_window_months"]) * float(ft.get(g, 0.0)) * pri["drp_reach"]
        for m in months:
            prev = str(pd.Period(m, "M") - 12)
            row = by_t.loc[prev] if prev in by_t.index else pd.Series(0.0, index=ING.TYPES)
            if policy:
                base = float(row.sum() + (pri["rto_mult"] - 1.0) * (row["quit"] + row["retire"]))
                base += lump if m == policy["offer_effective_month"] else 0.0
            else:
                base = float(row.sum())
            rows_pg.append((g, m, base))
    out["programme"] = {"label": "Programme calculation", "pred": _frame(rows_pg),
                        "description": (f"Programme calculation takes the same month last year, raises quits and retirements by the published {100 * (pri['rto_mult'] - 1):.0f}% return-to-office effect, "
                                        "and adds the resignation offer in its effective month as each agency's own voluntary leaving rate over the offer window times the published "
                                        f"early-retirement window effect (a {100 * (pri['drp_window_mult'] - 1):.0f}% rise in departures), applied to its full-time staff. Without an announced policy it equals the same month last year.")}
    return out


def actual(ctx, cutoff: str, months: list[str]) -> pd.DataFrame:
    """Recorded separations per group, month and type (deferred resignations as their own type); scoring only."""
    seps, heads = load(ctx)
    gmap = ING.agency_groups(heads, cutoff)
    s = seps[seps.effective_month.isin(months)].assign(group=lambda d: d.agency_code.map(gmap).fillna("OTHER"),
                                                      type=lambda d: np.where(d.drp == 1, "drp", d.type))
    return s.groupby(["group", "effective_month", "type"]).n.sum().rename("n").reset_index().rename(columns={"effective_month": "month"})
