"""Development check (not a reported result): simulation vs the three comparators at a few cutoffs.

  python instances/openrouter/ingest/audit/probe_accuracy.py 2025-09-29 2025-12-22 2026-02-16
"""
import sys

import numpy as np
import pandas as pd

from orgsim.instances import get_instance
from orgsim.scenarios import load_scenario
from orgsim.worlds import market as M

ctx = get_instance("openrouter"); sc = load_scenario(ctx, "baseline"); d = M.load_data(ctx)
for c in sys.argv[1:]:
    sims = [M._run_world(ctx, sc, sd, c)[1] for sd in (1, 2, 3)]
    ids = [a["app_id"] for a in sims[0].headline["apps"]]; segs = np.array([a["segment"] for a in sims[0].headline["apps"]])
    T = np.array([[a["tokens"] for a in s.headline["apps"]] for s in sims]); tot = np.median(T.sum(2), 0)
    t0 = pd.Timestamp(c); act = M.actual_window(d, t0, 8, ids, segs); ta = act["tokens"].sum(1)
    pw = max(w for w in d.mw.week.unique() if w < t0); mix0 = {s: M.segment_mix(d, s, pw) for s in set(segs)}
    comp = M.comparators(d, t0, 8, ids, segs, mix0)
    cal = sims[0].headline["calibration"]
    print(c, "censored%", round(act["censored"].mean() * 100, 1), "| WAPE sim", round(M.wape(tot, ta), 1),
          {k: round(M.wape(v["tokens"].sum(1), ta), 1) for k, v in comp.items()},
          "| k, phi, w", cal["k_level"], cal["phi"], cal["w"], "| median log(pred/actual) sim", round(float(np.median(np.log(tot / ta))), 3),
          "cf", round(float(np.median(np.log(comp["carry_forward"]["tokens"].sum(1) / ta))), 3), flush=True)
