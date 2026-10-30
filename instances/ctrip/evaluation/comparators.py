"""Other predictions for the Ctrip experiment, fixed before scoring. They read only weeks before the experiment
(data/normalized/panel.parquet filtered to weeks before 201049), calibration/fit.json (also 2010 only) and the central
values of the published estimates they cite. Called by orgsim.worlds.workforce_experiment through `compute(ctx)`.

  no_change       each group keeps its 2010 average; working at home changes nothing
  seasonal        each group's 2010 average moved by the 2010 same-week pattern of all staff
  trend           each group's 2010 weekly averages extended by a straight line
  literature      the earlier meta-analysis applied directly: performance up 0.36 standard deviations of the weekly
                  measure (Gajendran & Harrison 2007) and turnover intent down 0.17 SD carried to quits through the
                  intent-quit correlation of 0.38 (Griffeth, Hom & Gaertner 2000)
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
from scipy.special import ndtr, ndtri

T0_WEEK = 201049
SCORED = (201050, 201133)
HORIZON_WEEKS = 38
D_PERF, D_INTENT, RHO_INTENT = 0.36, -0.17, 0.38       # central published values (see calibration/priors.yaml)


def _scored_keys(fit: dict) -> list[int]:
    """The weeks the evaluation scores, as the simulation's weekly steps key them (Friday-based, 201050 .. 201133)."""
    keys = list(range(201050, 201053)) + list(range(201101, 201134))
    return keys


def compute(ctx) -> dict:
    panel = pd.read_parquet(ctx.data_normalized / "panel.parquet")
    pre = panel[(panel.year_week < T0_WEEK) & panel.group.isin([0, 1])]
    fit = json.loads((ctx.calibration_dir / "fit.json").read_text())
    keys = _scored_keys(fit)
    p0 = 100.0 * (1.0 - (1.0 - fit["exit_hazard"]["weekly"]) ** HORIZON_WEEKS)
    measures = {"perform1": pre.perform1.notna(), "log_calls": pre.calls_valid, "calls": pre.calls_valid}
    pre_mean = {m: {str(a): float(pre[v & (pre.group == a)][m].mean()) for a in (0, 1)} for m, v in measures.items()}

    def season_shift(m: str) -> float:
        s = fit["season"]["perform1" if m == "perform1" else "log_calls"]
        return float(np.mean([s.get(str(k), 0.0) for k in keys]))

    def trend_level(m: str, a: int) -> float:
        d = pre[measures[m] & (pre.group == a)].groupby("year_week")[m].mean()
        x = np.arange(len(d)); b = np.polyfit(x, d.to_numpy(), 1)
        future = np.arange(len(d) + 1, len(d) + 1 + len(keys))        # week 49 is the transition week
        return float(np.polyval(b, future).mean())

    def levels_from(level: dict) -> dict:
        v = {"perf_home": level["perform1"]["1"], "perf_office": level["perform1"]["0"],
             "calls_home": level["calls"]["1"], "calls_office": level["calls"]["0"]}
        v["perf_effect"] = (level["perform1"]["1"] - pre_mean["perform1"]["1"]) - (level["perform1"]["0"] - pre_mean["perform1"]["0"])
        d = (level["log_calls"]["1"] - pre_mean["log_calls"]["1"]) - (level["log_calls"]["0"] - pre_mean["log_calls"]["0"])
        v["calls_effect_pct"] = 100.0 * (math.exp(d) - 1.0)
        return v

    out = {}
    nc = levels_from(pre_mean)
    out["no_change"] = {"label": "No change", "values": {**nc, "attrition_home": p0, "attrition_office": p0, "attrition_effect_pp": 0.0},
                        "description": f"No change keeps each group at its 2010 average and its quits at the 2010 exit rate of staff ({p0:.1f}% over {HORIZON_WEEKS} weeks); working at home changes nothing."}
    seas = {"perform1": {a: pre_mean["perform1"][a] + season_shift("perform1") for a in ("0", "1")},
            "log_calls": {a: pre_mean["log_calls"][a] + season_shift("log_calls") for a in ("0", "1")},
            "calls": {a: pre_mean["calls"][a] * math.exp(season_shift("log_calls")) for a in ("0", "1")}}
    out["seasonal"] = {"label": "Same weeks last year", "values": {**levels_from(seas), "attrition_home": p0, "attrition_office": p0, "attrition_effect_pp": 0.0},
                       "description": "Same weeks last year moves each group's 2010 average by how all staff's output in the same weeks of 2010 differed from the end of 2010; no effect of working at home."}
    tr = {m: {str(a): trend_level(m, a) for a in (0, 1)} for m in measures}
    out["trend"] = {"label": "Recent trend", "values": levels_from(tr),
                    "description": "Recent trend extends a straight line through each group's 2010 weekly averages over the experiment weeks."}
    lit = {"perform1": {"0": pre_mean["perform1"]["0"], "1": pre_mean["perform1"]["1"] + D_PERF * fit["perform1"]["sd_person_week"]},
           "log_calls": {"0": pre_mean["log_calls"]["0"], "1": pre_mean["log_calls"]["1"] + D_PERF * fit["log_calls"]["sd_person_week"]},
           "calls": {"0": pre_mean["calls"]["0"], "1": pre_mean["calls"]["1"] * math.exp(D_PERF * fit["log_calls"]["sd_person_week"])}}
    p_home = 100.0 * float(ndtr(ndtri(p0 / 100.0) + RHO_INTENT * D_INTENT))
    out["literature"] = {"label": "Earlier research", "values": {**levels_from(lit), "attrition_home": p_home, "attrition_office": p0, "attrition_effect_pp": p_home - p0},
                         "description": (f"Earlier research applies a 2007 meta-analysis of 46 telecommuting studies directly: supervisor-rated or objective performance "
                                         f"{D_PERF:+.2f} standard deviations and turnover intent {D_INTENT:+.2f} standard deviations, carried to quits through the "
                                         f"intent-to-quit correlation of {RHO_INTENT:.2f} from a 2000 turnover meta-analysis. Both groups start from their 2010 averages.")}
    return out
