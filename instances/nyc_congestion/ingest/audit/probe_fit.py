"""Development check, not a reported result: one series' habit fit at one development cutoff. Prints the weekly
in-sample fit for the eight weeks before the cutoff and the first eight forecast weeks against the actual.

    python instances/nyc_congestion/ingest/audit/probe_fit.py yellow:within:day 2024-03-03
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from orgsim.instances import get_instance  # noqa: E402
from orgsim.worlds import demand as D  # noqa: E402


def main(sid: str, t0: str) -> None:
    ctx = get_instance("nyc_congestion")
    proto = ctx.yaml("evaluation/protocol.yaml")
    assert t0 in proto["cutoffs"][: int(proto["dev_cutoffs"])], "development cutoffs only"
    par = ctx.yaml("calibration/demand.yaml")
    s = {k: par.get(k) for k in ("history_days", "history_start", "min_history_days", "harmonics", "knot_days", "ridge_trend", "ridge_cal", "inner_cutoffs", "inner_step_days", "grid")}
    d = D.load_data(ctx)
    c = pd.Timestamp(t0)
    off = pd.Series(0.0, index=d.y.index[d.y.index < c])
    f = D.fit_series(d, sid, c, off, s)
    X, names = D.calendar_matrix(f.dates, s["harmonics"])
    fitted = np.exp(f.trend + X @ f.beta_cal) * f.smear
    y = d.y.loc[f.dates, sid].to_numpy()
    print("smear", round(f.smear, 4), "resid sd", round(float(np.nanstd(f.resid[-364:])), 4), "median last 28", round(float(np.nanmedian(f.resid[-28:])), 4))
    print("trend slope per year (last 13 weeks):", round((f.trend[-1] - f.trend[-92]) / 91 * 365, 4))
    for w in range(8, 0, -1):
        sl = slice(len(y) - 7 * w, len(y) - 7 * (w - 1) or None)
        print("in-sample week", -w, int(y[sl].sum()), int(fitted[sl].sum()), f"{fitted[sl].sum() / y[sl].sum() - 1:+.3f}")
    days = pd.date_range(c, periods=56, freq="D")
    p = np.exp(D.forecast_log(f, days, {"level_days": 28, "drift": 0.0, "phi": 1.0}, s["harmonics"])) - 1
    a = d.y.loc[days, sid].to_numpy()
    for w in range(8):
        sl = slice(7 * w, 7 * w + 7)
        print("forecast week", w + 1, int(a[sl].sum()), int(p[sl].sum()), f"{p[sl].sum() / a[sl].sum() - 1:+.3f}")
    hol = {n: round(float(b), 3) for n, b in zip(names, f.beta_cal) if n.startswith(("dow", "hol"))}
    print(hol)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
