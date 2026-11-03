"""Data behind the charts on the forecast board.

    --retro   once: the frozen retrospective results (board/results/charts_retro.json, committed). Errors are copied from
              the scored result files, never recomputed for display. Per-app points for the forecast-against-actual chart
              come from Run 3's cached forecasts and only for horizons the held-out test scored; the gate recomputes each
              method's error from those points and reports any gap to the scored value.
    --market  each run: weekly market tokens (written next to the astra folder, read by build_site.py).

    .venv/bin/python board/chart_data.py --retro --astra /Volumes/PsychDynamicsData/workcast_board/astra --out board/results/charts_retro.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from orgsim.instances import get_instance
from orgsim.worlds import market as M

import combo3 as C3

KEEP = ("combined", "T3", "damped_trend", "astra", "workcast", "T1", "recent_trend", "carry_forward", "market_growth")
SCATTER = ("combined", "damped_trend", "astra", "workcast", "carry_forward")
WEEKLY = ("combined", "damped_trend", "astra", "workcast", "carry_forward")


def renamed(mean: dict, design: str) -> dict:
    return {("combined" if k == design else k): v for k, v in mean.items()}


def retro(astra: Path, out: Path) -> None:
    load = lambda n: json.loads((astra / n).read_text())
    r3d, r3t, r4d, r4t, fair = load("run3_dev.json"), load("run3_test.json"), load("run4_dev.json"), load("run4_test.json"), load("fair_inputs.json")
    design = r3t["design"]
    ctx = get_instance("openrouter"); d = M.load_data(ctx)
    ev = json.loads((ctx.runs_dir / "evaluation.json").read_text())

    def merged(r3: dict, r4: dict) -> dict:
        m = renamed(r3["mean"], design)
        for k in ("T3", "T1"):
            m[k] = r4["mean"][k]
        return {k: {h: m[k][h] for h in C3.HZ} | {"mean": m[k]["sel_mean"]} for k in KEEP}

    fb = fair["summary"]["backtest"]
    backtest = {k: {h: fb[k][h] for h in C3.HZ} | {"mean": float(np.mean([fb[k][h] for h in C3.SEL]))} for k in fb if k != "n_cutoffs"}
    span = lambda r: {"n": len(r["cutoffs"]), "first": r["cutoffs"][0], "last": r["cutoffs"][-1]}
    sets = {"heldout": span(r3t) | {"mean": merged(r3t, r4t), "n_by_horizon": r3t["mean"]["astra"]["n"]},
            "earlier": span(r3d) | {"mean": merged(r3d, r4d), "n_by_horizon": r3d["mean"]["astra"]["n"]},
            "backtest": {"n": fb["n_cutoffs"], "first": ev["windows"][0]["cutoff"], "last": ev["windows"][-1]["cutoff"], "forecasts": sum(w["n_apps"] for w in ev["windows"]),
                         "mean": backtest}}
    # week by week, as scored
    per = renamed_per = r3d["per_cutoff"] + r3t["per_cutoff"]
    weekly = {"cutoffs": [p["cutoff"] for p in per], "heldout_from": r3t["cutoffs"][0],
              "series": {k: {h: [p["errors"]["D4" if k == "combined" else k][h] for p in renamed_per] for h in C3.HZ} for k in WEEKLY}}
    # forecast against actual per app, held-out cutoffs
    d4 = np.array(r3d["stack_weights"])
    names = d.apps.set_index("app_id").app_name
    scatter, gaps = [], {}
    for p in r3t["per_cutoff"]:
        c = p["cutoff"]
        z = np.load(astra / "components" / f"{c}.npz")
        ids = z["ids"]; F = {k: z[k] for k in z.files if k != "ids"}
        F["combined"] = C3.combine(F, d4)
        act, _ = C3.actual(c, d, ids)
        hz = [j for j, h in enumerate(C3.HZ) if p["errors"]["astra"][h] is not None]
        enc = lambda v: [int(round(float(np.log10(max(x, 1))) * 1000)) for x in v]
        entry = {"cutoff": c, "apps": [str(names.get(i, i)) for i in ids], "actual": {C3.HZ[j]: enc(act[:, j]) for j in hz},
                 "forecast": {k: {C3.HZ[j]: enc(F[k][:, j]) for j in hz} for k in SCATTER},
                 "error": {k: {C3.HZ[j]: p["errors"]["D4" if k == "combined" else k][C3.HZ[j]] for j in hz} for k in SCATTER}}
        scatter.append(entry)
        for k in SCATTER:
            for j in hz:
                gap = abs(M.wape(F[k][:, j], act[:, j]) - entry["error"][k][C3.HZ[j]])
                gaps[f"{c} {k} {C3.HZ[j]}w"] = round(gap, 3)
    res = {"sets": sets, "weekly": weekly, "scatter": scatter, "design": design, "weights": r3d["stack_weights"], "max_gate_gap_pct_points": max(gaps.values())}
    out.write_text(json.dumps(res, separators=(",", ":")))
    worst = sorted(gaps.items(), key=lambda kv: -kv[1])[:5]
    print(f"wrote {out} ({out.stat().st_size / 1e3:.0f} KB); gate, recomputed vs scored error, worst gaps (points): {worst}")


def market(path: Path) -> None:
    ctx = get_instance("openrouter"); d = M.load_data(ctx)
    mk = d.mw.groupby("week").market_tokens.first().sort_index()
    path.write_text(json.dumps({"weeks": [str(w.date()) for w in mk.index], "tokens": [float(v) for v in mk.to_numpy()]}))
    print(f"wrote {path}: {len(mk)} weeks to {mk.index[-1].date()}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retro", action="store_true")
    ap.add_argument("--astra")
    ap.add_argument("--out")
    ap.add_argument("--market")
    a = ap.parse_args()
    if a.retro:
        retro(Path(a.astra), Path(a.out))
    if a.market:
        market(Path(a.market))


if __name__ == "__main__":
    main()
