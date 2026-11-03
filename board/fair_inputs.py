"""Equal-information check: does the damped trend do better when it sees the same history as WORKCAST?

The damped trend in Runs 2-4 sees each app's last 12 weeks; WORKCAST sees everything since 2025-01-06. This scores the
damped trend on both windows, next to WORKCAST and the three standards, at the 16 backtest cutoffs of
runs/openrouter/evaluation.json and the 25 weekly cutoffs of Runs 3-4. No API calls: where Run 3's cached components
exist they supply the app set and WORKCAST's forecast; elsewhere the baseline world is run once (seed 1).

Gate: WORKCAST's error recomputed here must match evaluation.json's at the backtest cutoffs, so the app set and actuals
are the ones the published backtest scored.

    .venv/bin/python board/fair_inputs.py --out /Volumes/PsychDynamicsData/workcast_board/astra
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from orgsim.instances import get_instance
from orgsim.scenarios import load_scenario
from orgsim.store import RunWriter
from orgsim.worlds import market as M

import combo3 as C3
import combo4 as C4
import combo_study as S

METHODS = ("workcast", "damped_12w", "damped_full", "carry_forward", "recent_trend", "market_growth")


def world_forecasts(c: str, d, ctx) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    t0 = pd.Timestamp(c)
    sc = load_scenario(ctx, "baseline"); sc["world"]["t0"] = c
    writer = RunWriter(ctx.id, "board", run_id=f"fair-{c}")
    try:
        h0 = M.World.from_instance(ctx, sc, 1).run(writer).headline
    finally:
        shutil.rmtree(writer.dir, ignore_errors=True)
    ids = [x["app_id"] for x in h0["apps"]]
    segs = np.array([x["segment"] for x in h0["apps"]])
    prior_week = max(w for w in d.mw.week.unique() if w < t0)
    comp = M.comparators(d, t0, S.H, ids, segs, {s: M.segment_mix(d, s, prior_week) for s in set(segs)})
    return np.array(ids), {"workcast": S.cum(np.array([a["tokens_central"] for a in h0["apps"]])), **{k: S.cum(v["tokens"]) for k, v in comp.items()}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    ctx = get_instance("openrouter"); d = M.load_data(ctx)
    ev = json.loads((ctx.runs_dir / "evaluation.json").read_text())
    backtest = [w["cutoff"] for w in ev["windows"]]
    per = []
    for c in sorted(set(backtest) | set(C3.DEV + C3.TEST)):
        t0 = pd.Timestamp(c)
        cached = out / "components" / f"{c}.npz"
        if cached.exists():
            z = np.load(cached)
            ids, F = z["ids"], {k: z[k] for k in ("workcast", "carry_forward", "recent_trend", "market_growth")}
        else:
            ids, F = world_forecasts(c, d, ctx)
        hist12 = [t0 - (12 - i) * M.WEEK for i in range(12)]
        F["damped_12w"] = S.cum(S.damped_trend(M.app_matrix(d, hist12, list(ids))[0]))
        F["damped_full"] = S.cum(S.damped_trend(np.exp(C4.history(d, t0, ids))))
        act, n = C3.actual(c, d, ids)
        per.append({"cutoff": c, "sets": [s for s, cs in (("backtest", backtest), ("run3_dev", C3.DEV), ("run3_test", C3.TEST)) if c in cs],
                    "history_weeks": len(pd.date_range(C4.START, t0 - M.WEEK, freq="W-MON")),
                    "errors": {k: {h: C3.err(F[k], act, j) for j, h in enumerate(C3.HZ)} for k in METHODS}})
        print(c, {k: round(v["1"], 1) for k, v in per[-1]["errors"].items()}, flush=True)
    gate = {h: (float(np.mean([p["errors"]["workcast"][h] for p in per if "backtest" in p["sets"]])), ev["accuracy"]["by_horizon"][h]["simulation"]) for h in C3.HZ}
    summary = {}
    for s in ("backtest", "run3_dev", "run3_test"):
        rows = [p for p in per if s in p["sets"]]
        summary[s] = {k: {h: (float(np.mean(v)) if (v := [p["errors"][k][h] for p in rows if p["errors"][k][h] is not None]) else None) for h in C3.HZ} for k in METHODS}
        summary[s]["n_cutoffs"] = len(rows)
    res = {"purpose": "damped trend on 12 weeks vs full history (same history WORKCAST sees)", "gate_workcast_recomputed_vs_evaluation": gate,
           "summary": summary, "per_cutoff": per}
    (out / "fair_inputs.json").write_text(json.dumps(res, indent=1))
    print("gate (recomputed, evaluation.json):", {h: tuple(round(x, 2) for x in v) for h, v in gate.items()})
    for s, m in summary.items():
        print(f"\n{s} ({m['n_cutoffs']} cutoffs)")
        for k in METHODS:
            print(f"  {k:14s} " + "  ".join(f"{h}w {m[k][h]:5.1f}" if m[k][h] is not None else f"{h}w   –  " for h in C3.HZ))


if __name__ == "__main__":
    main()
