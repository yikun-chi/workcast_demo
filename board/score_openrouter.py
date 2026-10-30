"""Score every OpenRouter board forecast against the weeks that have since been published.

Scoring rules are fixed here and apply to every record alike: for each horizon h in 1, 2, 4 and 8 weeks that has fully
elapsed, the token-weighted error of each app's first-h-week tokens (WAPE, the validation's company metric) for the
simulation and each standard forecast, and the error in total market tokens; at the full horizon, the share of apps
whose actual tokens fell inside the forecast's 90% range. Weeks where an app is outside the published top 200 count at
half the 200th app's volume, as in the validation. Writes scores/openrouter/<t0>.json and scoreboard.json.

    .venv/bin/python board/score_openrouter.py --records /Volumes/PsychDynamicsData/workcast_board/records
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from orgsim.instances import get_instance
from orgsim.worlds import market as M

HORIZONS = (1, 2, 4, 8)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", required=True)
    a = ap.parse_args()
    root = Path(a.records)
    d = M.load_data(get_instance("openrouter"))
    last = pd.Timestamp(d.aw.week.max())
    mk = d.mw.groupby("week").market_tokens.first()
    board = []
    for f in sorted((root / "openrouter").glob("*.json")):
        rec = json.loads(f.read_text())
        t0 = pd.Timestamp(rec["t0"])
        done = int((last - t0) / M.WEEK) + 1                       # weeks of the horizon already published
        sc = {"t0": rec["t0"], "weeks_published": max(0, min(done, rec["horizon_weeks"])), "horizons": {}}
        if done >= 1:
            ids = [x["app_id"] for x in rec["apps"]]
            weeks = [t0 + i * M.WEEK for i in range(min(done, rec["horizon_weeks"]))]
            y, _ = M.app_matrix(d, weeks, ids)
            sim = np.array([x["tokens"] for x in rec["apps"]], dtype=float)
            comps = {k: np.array([x["comparators_tokens"][k] for x in rec["apps"]], dtype=float) for k in rec["apps"][0]["comparators_tokens"]}
            for h in HORIZONS:
                if h > len(weeks):
                    continue
                act = y[:, :h].sum(1)
                row = {"simulation": M.wape(sim[:, :h].sum(1), act), **{k: M.wape(v[:, :h].sum(1), act) for k, v in comps.items()}}
                best = min((k for k in row if k != "simulation"), key=row.get)
                am = float(mk.reindex(weeks[:h]).sum())
                sc["horizons"][str(h)] = {"company_tokens_wape": row, "best_standard": best,
                                          "error_reduction_pct": 100 * (1 - row["simulation"] / row[best]) if row[best] else None,
                                          "market_tokens_actual": am,
                                          "market_tokens_error_pct": {"simulation": 100 * abs(sum(rec["market_tokens"]["simulation"][:h]) - am) / am}}
            cf = rec.get("cumulative_1_2_4_8")
            if cf:
                cy = np.cumsum(y, axis=1)
                for j, h in enumerate(HORIZONS):
                    if h > len(weeks):
                        continue
                    act = cy[:, h - 1]
                    row = {k: M.wape(np.array(v, dtype=float)[:, j], act) for k, v in cf.items()}
                    best = min((k for k in row if k not in ("combined",)), key=row.get)
                    sc["horizons"].setdefault(str(h), {})["methods_wape"] = row
                    sc["horizons"][str(h)]["best_other"] = best
            if len(weeks) >= rec["horizon_weeks"]:
                tot = y.sum(1)
                lo = np.array([x["tokens_total_range90"][0] for x in rec["apps"]]); hi = np.array([x["tokens_total_range90"][1] for x in rec["apps"]])
                sc["coverage90_pct"] = float(np.mean((tot >= lo) & (tot <= hi)) * 100)
        out = root.parent / "scores" / "openrouter" / f.name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(sc, indent=1))
        board.append(sc)
    # running record: every scored horizon pooled over forecasts (mean of per-forecast errors, as in the validation)
    agg = {}
    for h in map(str, HORIZONS):
        rows = [s["horizons"][h] for s in board if h in s["horizons"]]
        if rows:
            who = rows[0]["company_tokens_wape"].keys()
            agg[h] = {"n_forecasts": len(rows), **{k: float(np.mean([r["company_tokens_wape"][k] for r in rows])) for k in who}}
            best = min((k for k in agg[h] if k not in ("simulation", "n_forecasts")), key=agg[h].get)
            agg[h]["best_standard"] = best
            agg[h]["error_reduction_pct"] = 100 * (1 - agg[h]["simulation"] / agg[h][best])
    agg_m = {}
    for h in map(str, HORIZONS):
        rows = [s["horizons"][h]["methods_wape"] for s in board if h in s["horizons"] and "methods_wape" in s["horizons"][h]]
        if rows:
            agg_m[h] = {"n_forecasts": len(rows), **{k: float(np.mean([r[k] for r in rows if k in r])) for k in rows[0]}}
            best = min((k for k in agg_m[h] if k not in ("combined", "n_forecasts")), key=agg_m[h].get)
            agg_m[h]["best_other"] = best
            agg_m[h]["error_reduction_pct"] = 100 * (1 - agg_m[h]["combined"] / agg_m[h][best])
    (root.parent / "scoreboard_methods.json").write_text(json.dumps(agg_m, indent=1))
    (root.parent / "scoreboard.json").write_text(json.dumps({"latest_data_week": str(last.date()), "forecasts": len(board), "by_horizon": agg, "records": board}, indent=1))
    print(f"scored {len(board)} forecasts; latest data week {last.date()}")


if __name__ == "__main__":
    main()
