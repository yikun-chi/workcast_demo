"""Run 2 of docs/plans/astra_forecast_protocol.md: WORKCAST with GPT-6 Astra inside, against every gold standard.

    --stage dev               score the five candidate designs and the gold standards on the five development cutoffs
    --stage test --design CN  score the frozen design and the gold standards on the 13 held-out weekly cutoffs; refuses
                              to run unless the protocol file names CN as the frozen design

Every forecast is cumulative tokens per app over the first 1, 2, 4 and 8 weeks after the cutoff; the metric is the
board's WAPE. Astra calls go through board/astra_backtest.py's cached, capped caller and share its ledger.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from orgsim.instances import get_instance
from orgsim.scenarios import load_scenario
from orgsim.store import RunWriter
from orgsim.worlds import market as M

import astra_backtest as A

H = 8
CUM = np.array([1, 2, 4, 8])
DEV = ["2026-05-11", "2026-06-08", "2026-07-06", "2026-08-03", "2026-08-31"]
ALL = [str(d.date()) for d in pd.date_range("2026-05-04", "2026-08-31", freq="W-MON")]
TEST = [c for c in ALL if c not in DEV]
GOLD = ["carry_forward", "recent_trend", "market_growth", "damped_trend", "astra"]
PROTOCOL = Path(__file__).resolve().parents[1] / "docs/plans/astra_forecast_protocol.md"


def cum(weekly: np.ndarray) -> np.ndarray:
    """apps x H weekly -> apps x 4 cumulative at 1, 2, 4, 8 weeks."""
    c = np.cumsum(weekly, axis=1)
    return c[:, CUM - 1]


def damped_trend(x: np.ndarray) -> np.ndarray:
    """Holt's damped trend on log weekly tokens, per app; alpha, beta, phi chosen by one-step squared error on the history."""
    out = np.empty((x.shape[0], H))
    grid = [(a, b, p) for a in (0.2, 0.4, 0.6, 0.8) for b in (0.05, 0.1, 0.2) for p in (0.8, 0.9, 0.98)]
    for i, row in enumerate(np.log(x)):
        best = None
        for a, b, p in grid:
            lvl, tr, sse = row[0], row[1] - row[0], 0.0
            for y in row[1:]:
                f = lvl + p * tr
                sse += (y - f) ** 2
                new = a * y + (1 - a) * f
                tr = b * (new - lvl) + (1 - b) * p * tr
                lvl = new
            if best is None or sse < best[0]:
                best = (sse, lvl, tr, p)
        _, lvl, tr, p = best
        steps = np.cumsum([p ** k for k in range(1, H + 1)])
        out[i] = np.exp(lvl + steps * tr)
    return out


def astra(user: str, cache: Path, ledger: list, cap: float, ledger_path: Path, ids: list[int]) -> np.ndarray:
    preds = []
    for s in range(1, A.SAMPLES + 1):
        rec = A.call(user, s, cache, ledger, cap)
        ledger_path.write_text(json.dumps(ledger, indent=1))
        f = json.loads(rec["text"])["forecasts"]
        preds.append(np.array([[float(f.get(str(i), [np.nan] * 4)[k]) for k in range(4)] for i in ids]) * 1e9)
    return np.nanmean(np.stack(preds), axis=0)


def forecasts(c: str, d: M.MarketData, ctx, out: Path, cap: float, need_refine: bool) -> tuple[list[int], dict[str, np.ndarray]]:
    t0 = pd.Timestamp(c)
    sc = load_scenario(ctx, "baseline"); sc["world"]["t0"] = c
    writer = RunWriter(ctx.id, "board", run_id=f"combo-{c}")
    try:
        h0 = M.World.from_instance(ctx, sc, 1).run(writer).headline
    finally:
        import shutil; shutil.rmtree(writer.dir, ignore_errors=True)
    ids = [x["app_id"] for x in h0["apps"]]
    segs = np.array([x["segment"] for x in h0["apps"]])
    prior_week = max(w for w in d.mw.week.unique() if w < t0)
    comp = M.comparators(d, t0, H, ids, segs, {s: M.segment_mix(d, s, prior_week) for s in set(segs)})
    hist = [t0 - (A.HISTORY - i) * M.WEEK for i in range(A.HISTORY)]
    x, _ = M.app_matrix(d, hist, ids)
    F = {"workcast": cum(np.array([a_["tokens_central"] for a_ in h0["apps"]])), "damped_trend": cum(damped_trend(x)),
         **{k: cum(v["tokens"]) for k, v in comp.items()}}
    cache, ledger_path = out / "responses", out / "ledger.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else []
    user = A.prompt(d, t0, ids)
    F["astra"] = astra(user, cache, ledger, cap, ledger_path, ids)
    if need_refine:
        lines = ["", "WORKCAST simulation forecast for the same apps (cumulative billions over the first 1, 2, 4 and 8 weeks):", "id | w1 | w1_2 | w1_4 | w1_8"]
        lines += [f"{i} | " + " | ".join(f"{v / 1e9:.1f}" for v in F["workcast"][j]) for j, i in enumerate(ids)]
        lines += ["", "Use the simulation forecast as one input alongside the history. Return your final forecast in the same JSON format."]
        F["refine"] = astra(user + "\n".join(lines), cache, ledger, cap, ledger_path, ids)
    return ids, F


def designs(F: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    w, a = F["workcast"], F["astra"]
    stack = np.stack([w, a, F["carry_forward"], F["recent_trend"], F["market_growth"], F["damped_trend"]])
    out = {"C1": (w + a) / 2, "C2": np.sqrt(np.clip(w, 1, None) * np.clip(a, 1, None)), "C3": np.nanmedian(stack, axis=0), "C5": (w + a + F["carry_forward"]) / 3}
    if "refine" in F:
        out["C4"] = F["refine"]
    return out


def score(ids: list[int], c: str, d: M.MarketData, preds: dict[str, np.ndarray]) -> dict[str, dict[str, float]]:
    y, _ = M.app_matrix(d, [pd.Timestamp(c) + i * M.WEEK for i in range(H)], ids)
    act = cum(y)
    res = {}
    for k, p in preds.items():
        ok = ~np.isnan(p).any(1)
        res[k] = {str(h): M.wape(p[ok, j], act[ok, j]) for j, h in enumerate(CUM)}
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("dev", "test"), required=True)
    ap.add_argument("--design")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cap-usd", type=float, default=25)
    a = ap.parse_args()
    out = Path(a.out); (out / "responses").mkdir(parents=True, exist_ok=True)
    ctx = get_instance("openrouter"); d = M.load_data(ctx)
    if a.stage == "test":
        m = re.search(r"FROZEN DESIGN: (C\d)", PROTOCOL.read_text())
        if not m or m.group(1) != a.design:
            raise SystemExit("the protocol file does not name this design as frozen; freeze it before scoring held-out cutoffs")
    cutoffs = DEV if a.stage == "dev" else TEST
    per = []
    for c in cutoffs:
        ids, F = forecasts(c, d, ctx, out, a.cap_usd, need_refine=(a.stage == "dev" or a.design == "C4"))
        cand = designs(F)
        preds = {**{g: F[g] for g in GOLD}, "workcast": F["workcast"], **({k: v for k, v in cand.items()} if a.stage == "dev" else {a.design: cand[a.design]})}
        sc = score(ids, c, d, preds)
        per.append({"cutoff": c, "errors": sc})
        print(c, {k: round(v["1"], 1) for k, v in sc.items()}, flush=True)
    keys = per[0]["errors"].keys()
    mean = {k: {h: float(np.mean([p["errors"][k][h] for p in per])) for h in ("1", "2", "4", "8")} for k in keys}
    for k in mean:
        mean[k]["all"] = float(np.mean(list(mean[k].values())))
    res = {"stage": a.stage, "design": a.design, "cutoffs": cutoffs, "mean": mean, "per_cutoff": per,
           "spent_usd": sum(r["usd"] for r in json.loads((out / "ledger.json").read_text()))}
    (out / f"run2_{a.stage}.json").write_text(json.dumps(res, indent=1))
    for k, v in sorted(mean.items(), key=lambda kv: kv[1]["all"]):
        print(f"{k:14s} " + "  ".join(f"{h}w {v[h]:5.1f}" for h in ("1", "2", "4", "8")) + f"  mean {v['all']:5.1f}")
    print(f"spent so far ${res['spent_usd']:.2f}")


if __name__ == "__main__":
    main()
