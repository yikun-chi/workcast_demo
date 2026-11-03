"""Run 4 of docs/plans/astra_forecast_protocol.md: Timestral forecasts, GPT-6 Astra adjusts.

    --stage export            each cutoff's app histories (log weekly tokens from 2025-01-06) for board/timestral_run.py
    --stage dev               T1-T4 and the standards on the 18 development cutoffs (Astra answers are cached)
    --stage test --design TN  refuses unless the protocol file names TN as frozen; scores the 7 re-used test cutoffs

The app set at each cutoff and the standards (WORKCAST, Astra, damped trend, carry-forward, recent trend, market growth)
come from Run 3's cached components; D4 uses Run 3's frozen weights. Astra calls share astra_backtest.py's ledger.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from orgsim.instances import get_instance
from orgsim.worlds import market as M

import astra_backtest as A
import combo3 as C3
import combo_study as S

START = pd.Timestamp("2025-01-06")
DESIGNS = ("T1", "T2", "T3", "T4")
STANDARDS = ("d4",) + C3.STANDARDS


def history(d: M.MarketData, t0: pd.Timestamp, ids) -> np.ndarray:
    weeks = list(pd.date_range(START, t0 - M.WEEK, freq="W-MON"))
    x, _ = M.app_matrix(d, weeks, list(ids))
    return np.log(np.clip(x, 1, None))


def timestral(out: Path, c: str, ids) -> dict[str, np.ndarray]:
    z = np.load(out / "timestral_out" / f"{c}.npz")
    assert (z["ids"] == ids).all(), c
    return {k: S.cum(np.exp(z[k])) for k in ("median", "q10", "q90")}   # the 10/90 sums are an approximate cumulative range


def adjust_prompt(d, t0, ids, ts: dict[str, np.ndarray], workcast: np.ndarray | None) -> str:
    lines = ["", "Timestral, a time-series foundation model, forecast the same apps from each app's full weekly history since January 2025 "
             "(cumulative billions over the first 1, 2, 4 and 8 weeks; median, and in brackets the sum of its weekly 10% and 90% quantiles):",
             "id | w1 | w1_2 | w1_4 | w1_8"]
    lines += [f"{i} | " + " | ".join(f"{ts['median'][j, k] / 1e9:.1f} [{ts['q10'][j, k] / 1e9:.1f}-{ts['q90'][j, k] / 1e9:.1f}]" for k in range(4))
              for j, i in enumerate(ids)]
    if workcast is not None:
        lines += ["", "WORKCAST simulation forecast for the same apps (cumulative billions over the first 1, 2, 4 and 8 weeks):", "id | w1 | w1_2 | w1_4 | w1_8"]
        lines += [f"{i} | " + " | ".join(f"{v / 1e9:.1f}" for v in workcast[j]) for j, i in enumerate(ids)]
    lines += ["", "Start from the Timestral forecast and adjust each app where the history or your knowledge gives a reason to. "
              "Return your final forecast in the same JSON format."]
    return A.prompt(d, t0, list(ids)) + "\n".join(lines)


def astra_one(user: str, out: Path, ids, cap: float) -> np.ndarray:
    ledger_path = out / "ledger.json"
    ledger = json.loads(ledger_path.read_text())
    rec = A.call(user, 1, out / "responses", ledger, cap)
    ledger_path.write_text(json.dumps(ledger, indent=1))
    f = json.loads(rec["text"])["forecasts"]
    return np.array([[float(f.get(str(i), [np.nan] * 4)[k]) for k in range(4)] for i in ids]) * 1e9


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("export", "dev", "test"), required=True)
    ap.add_argument("--design")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cap-usd", type=float, default=25)
    a = ap.parse_args()
    out = Path(a.out)
    # the 36 development calls cost at most $0.301 each; reserving twice that per call (not the theoretical $2.50) lets the
    # 7 test calls run inside the $25 total cap, which still stops the run before any call that could pass it
    A.WORST_CALL_USD = 0.60
    ctx = get_instance("openrouter"); d = M.load_data(ctx)
    cutoffs = C3.DEV + C3.TEST
    if a.stage == "export":
        (out / "timestral_in").mkdir(parents=True, exist_ok=True)
        for c in cutoffs:
            ids, _ = C3.components(c, d, ctx, out, a.cap_usd)
            lx = history(d, pd.Timestamp(c), ids)
            np.savez(out / "timestral_in" / f"{c}.npz", ids=ids, logx=lx)
            print(c, lx.shape)
        return
    if a.stage == "test":
        m = re.search(r"RUN 4 FROZEN DESIGN: (T\d)", S.PROTOCOL.read_text())
        if not m or m.group(1) != a.design:
            raise SystemExit("protocol file does not name this design as the frozen Run 4 design")
    d4 = np.array(json.loads((out / "run3_dev.json").read_text())["stack_weights"])
    need = set(DESIGNS) if a.stage == "dev" else {a.design}
    per = []
    for c in (C3.DEV if a.stage == "dev" else C3.TEST):
        t0 = pd.Timestamp(c)
        ids, F = C3.components(c, d, ctx, out, a.cap_usd)
        act, n = C3.actual(c, d, ids)
        ts = timestral(out, c, ids)
        P = {"d4": C3.combine(F, d4), **{k: F[k] for k in C3.STANDARDS}, "T1": ts["median"]}
        if need & {"T2"}:
            P["T2"] = astra_one(adjust_prompt(d, t0, ids, ts, None), out, ids, a.cap_usd)
        if need & {"T3", "T4"}:
            P["T3"] = astra_one(adjust_prompt(d, t0, ids, ts, F["workcast"]), out, ids, a.cap_usd)
            P["T4"] = (P["T3"] + ts["median"]) / 2
        P = {k: v for k, v in P.items() if k in STANDARDS or k == "T1" or k in need}
        per.append({"cutoff": c, "published_weeks": n, "missing_from_answer": {k: int(np.isnan(v).any(1).sum()) for k, v in P.items()},
                    "errors": {k: {h: C3.err(v, act, j) for j, h in enumerate(C3.HZ)} for k, v in P.items()}})
        print(c, {k: round(v["1"], 1) for k, v in per[-1]["errors"].items()}, flush=True)
    mean = {}
    for k in per[0]["errors"]:
        mean[k] = {h: (float(np.mean(v)) if (v := [p["errors"][k][h] for p in per if p["errors"][k][h] is not None]) else None) for h in C3.HZ}
        mean[k]["n"] = {h: sum(p["errors"][k][h] is not None for p in per) for h in C3.HZ}
        mean[k]["sel_mean"] = float(np.mean([mean[k][h] for h in C3.SEL if mean[k][h] is not None]))
    res = {"stage": a.stage, "design": a.design, "base_model": "mistralai/Timestral-209M", "cutoffs": [p["cutoff"] for p in per], "mean": mean,
           "per_cutoff": per, "spent_usd": sum(r["usd"] for r in json.loads((out / "ledger.json").read_text()))}
    (out / f"run4_{a.stage}.json").write_text(json.dumps(res, indent=1))
    for k, v in sorted(mean.items(), key=lambda kv: kv[1]["sel_mean"]):
        print(f"{k:14s} " + "  ".join(f"{h}w {v[h]:5.1f}" if v[h] is not None else f"{h}w   –  " for h in C3.HZ) + f"  mean(1,2,4) {v['sel_mean']:5.2f}  n={v['n']}")
    print(f"spent ${res['spent_usd']:.2f} (backtest ledger)")


if __name__ == "__main__":
    main()
