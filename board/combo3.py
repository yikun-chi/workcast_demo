"""Run 3 of docs/plans/astra_forecast_protocol.md: combinations of WORKCAST (W), GPT-6 Astra (A) and the bounded damped
trend (D), selected on the 18 development cutoffs and scored once on the held-out cutoffs from 2026-09-07.

    --stage dev               component forecasts at the development cutoffs (Astra answers are cached), design scores
    --stage test --design DN  refuses unless the protocol file names DN as frozen; forecasts and scores held-out cutoffs

Component forecasts are cached per cutoff (components/<cutoff>.npz) so both stages and the online weights reuse them.
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from orgsim.instances import get_instance
from orgsim.worlds import market as M

import combo_study as S

DEV = [str(d.date()) for d in pd.date_range("2026-05-04", "2026-08-31", freq="W-MON")]
TEST = [str(d.date()) for d in pd.date_range("2026-09-07", "2026-10-19", freq="W-MON")]
HZ = ("1", "2", "4", "8")
SEL = ("1", "2", "4")
COMP = ("workcast", "astra", "damped_trend")
STANDARDS = ("astra", "damped_trend", "workcast", "carry_forward", "recent_trend", "market_growth")


def components(c: str, d, ctx, out: Path, cap: float) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    p = out / "components" / f"{c}.npz"
    if p.exists():
        z = np.load(p)
        return z["ids"], {k: z[k] for k in z.files if k != "ids"}
    ids, F = S.forecasts(c, d, ctx, out, cap, need_refine=False)
    p.parent.mkdir(parents=True, exist_ok=True)
    np.savez(p, ids=np.array(ids), **F)
    return np.array(ids), F


def actual(c: str, d, ids) -> tuple[np.ndarray, int]:
    """Cumulative actuals at 1, 2, 4, 8 weeks and how many weeks of the horizon are published."""
    last = pd.Timestamp(d.aw.week.max())
    weeks = [pd.Timestamp(c) + i * M.WEEK for i in range(8) if pd.Timestamp(c) + i * M.WEEK <= last]
    y, _ = M.app_matrix(d, weeks, list(ids))
    cumy = np.cumsum(y, axis=1)
    return np.array([cumy[:, h - 1] if h <= len(weeks) else np.full(len(ids), np.nan) for h in (1, 2, 4, 8)]).T, len(weeks)


def err(p: np.ndarray, act: np.ndarray, j: int) -> float | None:
    if np.isnan(act[:, j]).all():
        return None
    ok = ~np.isnan(p[:, j]) & ~np.isnan(act[:, j])
    return M.wape(p[ok, j], act[ok, j])


def combine(F, w: np.ndarray, geometric: bool = False) -> np.ndarray:
    X = np.stack([F[k] for k in COMP])                                   # 3 x apps x 4
    if geometric:
        return np.exp(np.tensordot(w, np.log(np.clip(X, 1, None)), axes=1)) if w.ndim == 1 else np.exp(np.einsum("kh,kah->ah", w, np.log(np.clip(X, 1, None))))
    return np.tensordot(w, X, axes=1) if w.ndim == 1 else np.einsum("kh,kah->ah", w, X)


def online_weights(history: list[dict], c: str) -> np.ndarray:
    """3 x 4 weights at cutoff c from components' errors at earlier cutoffs whose horizon had fully elapsed by c."""
    W = np.full((3, 4), 1 / 3)
    for j, h in enumerate((1, 2, 4, 8)):
        past = [r for r in history if pd.Timestamp(r["cutoff"]) + h * M.WEEK <= pd.Timestamp(c) and r["comp_err"][j] is not None]
        if len(past) >= 3:
            inv = np.array([1 / np.mean([r["comp_err"][j][k] for r in past]) for k in range(3)])
            W[:, j] = inv / inv.sum()
    return W


def stack_weights(rows: list[dict]) -> np.ndarray:
    grid = [np.array(w) / 10 for w in itertools.product(range(1, 9), repeat=3) if sum(w) == 10]
    W = np.zeros((3, 4))
    for j in range(4):
        best = min(grid, key=lambda w: np.mean([e for r in rows if (e := err(combine(r["F"], w), r["act"], j)) is not None]))
        W[:, j] = best
    return W


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("dev", "test"), required=True)
    ap.add_argument("--design")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cap-usd", type=float, default=25)
    a = ap.parse_args()
    out = Path(a.out)
    ctx = get_instance("openrouter"); d = M.load_data(ctx)
    if a.stage == "test":
        m = re.search(r"RUN 3 FROZEN DESIGN: (D\d)", S.PROTOCOL.read_text())
        if not m or m.group(1) != a.design:
            raise SystemExit("protocol file does not name this design as the frozen Run 3 design")
    rows = []
    for c in DEV + (TEST if a.stage == "test" else []):
        ids, F = components(c, d, ctx, out, a.cap_usd)
        act, n = actual(c, d, ids)
        rows.append({"cutoff": c, "F": F, "act": act, "published_weeks": n, "comp_err": [[err(F[k], act, j) for k in COMP] if not np.isnan(act[:, j]).all() else None for j in range(4)]})
    dev = [r for r in rows if r["cutoff"] in DEV]
    st = stack_weights(dev)
    def designs(r: dict, history: list[dict]) -> dict[str, np.ndarray]:
        eq = np.full(3, 1 / 3)
        return {"D1": combine(r["F"], eq), "D2": combine(r["F"], eq, geometric=True), "D3": combine(r["F"], online_weights(history, r["cutoff"])), "D4": combine(r["F"], st)}
    target = dev if a.stage == "dev" else [r for r in rows if r["cutoff"] in TEST]
    per = []
    for r in target:
        P = {**{k: r["F"][k] for k in STANDARDS}, **designs(r, [x for x in rows if x["cutoff"] < r["cutoff"]])}
        if a.stage == "test":
            P = {k: v for k, v in P.items() if k in STANDARDS or k == a.design}
        per.append({"cutoff": r["cutoff"], "published_weeks": r["published_weeks"], "errors": {k: {h: err(v, r["act"], j) for j, h in enumerate(HZ)} for k, v in P.items()}})
    mean = {}
    for k in per[0]["errors"]:
        mean[k] = {h: (float(np.mean(v)) if (v := [p["errors"][k][h] for p in per if p["errors"][k][h] is not None]) else None) for h in HZ}
        mean[k]["n"] = {h: sum(p["errors"][k][h] is not None for p in per) for h in HZ}
        mean[k]["sel_mean"] = float(np.mean([mean[k][h] for h in SEL if mean[k][h] is not None]))
    res = {"stage": a.stage, "design": a.design, "cutoffs": [p["cutoff"] for p in per], "stack_weights": st.round(2).tolist(), "mean": mean, "per_cutoff": per,
           "spent_usd": sum(r_["usd"] for r_ in json.loads((out / "ledger.json").read_text()))}
    (out / f"run3_{a.stage}.json").write_text(json.dumps(res, indent=1))
    for k, v in sorted(mean.items(), key=lambda kv: kv[1]["sel_mean"]):
        print(f"{k:14s} " + "  ".join(f"{h}w {v[h]:5.1f}" if v[h] is not None else f"{h}w   –  " for h in HZ) + f"  mean(1,2,4) {v['sel_mean']:5.2f}  n={v['n']}")
    print("stack weights (W, A, D) per horizon 1,2,4,8:", st.round(2).tolist(), f"| spent ${res['spent_usd']:.2f}")


if __name__ == "__main__":
    main()
