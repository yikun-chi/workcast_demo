"""Generic time-to-event helpers shared by process-world ingests and the process engine.

aalen_johansen  cumulative incidence of competing causes under right-censoring (the Kaplan-Meier survival is
                1 - sum of the causes). Used to condition an open case's next step on the time already elapsed.
week_slot       calendar slot of a Mon-Sun week for periodic batch runs ("early"/"late"/"regular"), used by
                instances whose activity volume follows a payment-run calendar.
"""
from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd


def aalen_johansen(times: np.ndarray, observed: np.ndarray, causes: np.ndarray, grid: np.ndarray, min_cause: int = 1) -> dict[str, list[float]]:
    """Cumulative incidence F_cause(t) on `grid` for right-censored competing-risk data.

    times     time to the event (observed=True) or to censoring (observed=False)
    causes    cause label of each observation (ignored when censored)
    Returns {cause: [F_cause(t) for t in grid]}; sum over causes of F_cause(t) = 1 - S_KM(t). Causes with fewer than
    `min_cause` observed events are left out.
    """
    times = np.asarray(times, dtype=float); observed = np.asarray(observed, dtype=bool); causes = np.asarray(causes, dtype=object)
    grid = np.asarray(grid, dtype=float)
    if len(times) == 0:
        return {}
    order = np.argsort(times, kind="stable")
    t, o, c = times[order], observed[order], causes[order]
    n = len(t)
    ut, idx = np.unique(t, return_index=True)
    at_risk = (n - idx).astype(float)
    d = np.add.reduceat(o.astype(float), idx)
    s_after = np.cumprod(1.0 - d / at_risk)
    s_before = np.concatenate([[1.0], s_after[:-1]])
    pos = np.searchsorted(ut, grid, side="right") - 1
    out: dict[str, list[float]] = {}
    for cause, n_c in Counter(c[o]).items():
        if n_c < min_cause:
            continue
        dc = np.add.reduceat((o & (c == cause)).astype(float), idx)
        inc = np.cumsum(s_before * dc / at_risk)
        out[str(cause)] = [round(float(v), 6) for v in np.where(pos >= 0, inc[np.clip(pos, 0, None)], 0.0)]
    return out


def week_slot(monday: pd.Timestamp, x_early: int, x_late: int) -> str:
    """Slot of the Mon-Sun week starting `monday`: 'early' if it holds the first Thursday on/after day `x_early` of a
    month, 'late' if it holds the first Thursday on/after day `x_late`, else 'regular'."""
    thu = pd.Timestamp(monday) + pd.Timedelta(days=3)
    prev = thu - pd.Timedelta(days=7)
    for x, name in ((x_early, "early"), (x_late, "late")):
        if thu.day >= x and (prev.month != thu.month or prev.day < x):
            return name
    return "regular"
