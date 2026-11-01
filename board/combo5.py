"""Run 5 of docs/plans/astra_forecast_protocol.md: walk-forward recombination of saved forecasts. Makes no API calls.

    --stage dev               E1-E5 and the standards on the 18 development cutoffs
    --stage test --design EN  refuses unless the protocol file names EN as frozen; scores the 7 re-used test cutoffs
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

import combo3 as C3
import combo4 as C4
import combo_study as S

H = (1, 2, 4, 8)
STANDARDS = ("D4", "T3", "damped_trend", "astra", "workcast", "T1", "recent_trend", "carry_forward", "market_growth")


def saved_t3(out: Path, ids, ledger: list[dict], pos: int) -> np.ndarray:
    rec = json.loads((out / "responses" / f"{ledger[pos]['request_sha256']}.json").read_text())
    f = json.loads(rec["text"])["forecasts"]
    return np.array([[float(f.get(str(i), [np.nan] * 4)[k]) for k in range(4)] for i in ids]) * 1e9


def grid(n: int) -> list[np.ndarray]:
    return [np.array(w) / 10 for w in itertools.product(range(0, 11), repeat=n) if sum(w) == 10]


def blend(F: dict, keys: tuple[str, ...], w: np.ndarray) -> np.ndarray:
    return np.einsum("kh,kah->ah", w, np.stack([np.nan_to_num(F[k], nan=0.0) for k in keys]))


def elapsed(history: list[dict], c: str, j: int) -> list[dict]:
    return [r for r in history if pd.Timestamp(r["cutoff"]) + H[j] * M.WEEK <= pd.Timestamp(c) and not np.isnan(r["act"][:, j]).all()]


def walk_weights(history: list[dict], c: str, keys: tuple[str, ...]) -> np.ndarray:
    W = np.full((len(keys), 4), 1 / len(keys))
    g = grid(len(keys))
    for j in range(4):
        past = elapsed(history, c, j)
        if len(past) >= 3:
            X = [(np.stack([np.nan_to_num(r["F"][k], nan=0.0)[:, j] for k in keys]), r["act"][:, j]) for r in past]
            W[:, j] = min(g, key=lambda w: np.mean([M.wape(np.tensordot(w, x, axes=1), a) for x, a in X]))
    return W


def level(history: list[dict], c: str, keys: tuple[str, ...]) -> np.ndarray:
    """Half the log ratio of total actual to total forecast, last four elapsed cutoffs, each with that cutoff's walk-forward weights."""
    out = np.ones(4)
    for j in range(4):
        past = elapsed(history, c, j)[-4:]
        if len(past) >= 3:
            ratios = []
            for r in past:
                p = blend(r["F"], keys, walk_weights([x for x in history if x["cutoff"] < r["cutoff"]], r["cutoff"], keys))
                ratios.append(np.log(r["act"][:, j].sum() / p[:, j].sum()))
            out[j] = float(np.exp(0.5 * np.mean(ratios)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("dev", "test"), required=True)
    ap.add_argument("--design")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    ctx = get_instance("openrouter"); d = M.load_data(ctx)
    if a.stage == "test":
        m = re.search(r"RUN 5 FROZEN DESIGN: (E\d)", S.PROTOCOL.read_text())
        if not m or m.group(1) != a.design:
            raise SystemExit("protocol file does not name this design as the frozen Run 5 design")
    ledger = json.loads((out / "ledger.json").read_text())
    d4 = np.array(json.loads((out / "run3_dev.json").read_text())["stack_weights"])
    frozen = {p["cutoff"]: p["errors"] for f in ("run4_dev.json", "run4_test.json") for p in json.loads((out / f).read_text())["per_cutoff"]}
    rows, gaps = [], {}
    for i, c in enumerate(C3.DEV + C3.TEST):
        ids, F = C3.components(c, d, ctx, out, 0.0)                   # cap 0: components are saved, and nothing can be bought
        F = dict(F)
        F["T3"] = saved_t3(out, ids, ledger, 60 + 2 * i + 1 if c in C3.DEV else 96 + (i - len(C3.DEV)))
        F["T1"] = C4.timestral(out, c, ids)["median"]
        F["D4"] = C3.combine(F, d4)
        act, _ = C3.actual(c, d, ids)
        r = {"cutoff": c, "F": F, "act": act}
        rows.append(r)
        for k in ("D4", "T3"):
            key = "d4" if k == "D4" else k
            for j, h in enumerate(C3.HZ):
                fr = frozen[c].get(key, {}).get(h)
                e = C3.err(F[k], act, j)
                if fr is not None and e is not None:
                    gaps[f"{c} {k} {h}w"] = round(abs(fr - e), 3)
    target = C3.DEV if a.stage == "dev" else C3.TEST
    W3, W4 = ("workcast", "astra", "damped_trend"), ("workcast", "astra", "damped_trend", "T3")
    per = []
    for r in rows:
        c = r["cutoff"]
        if c not in target:
            continue
        hist = [x for x in rows if x["cutoff"] < c]
        P = {k: r["F"][k] for k in STANDARDS}
        e1, e2 = blend(r["F"], W3, walk_weights(hist, c, W3)), blend(r["F"], W4, walk_weights(hist, c, W4))
        cand = {"E1": e1, "E2": e2, "E3": (e1 + r["F"]["T3"]) / 2, "E4": e2 * level(hist, c, W4), "E5": e1 * level(hist, c, W3)}
        P |= cand if a.stage == "dev" else {a.design: cand[a.design]}
        per.append({"cutoff": c, "errors": {k: {h: C3.err(v, r["act"], j) for j, h in enumerate(C3.HZ)} for k, v in P.items()}})
        print(c, {k: round(v["1"], 1) for k, v in per[-1]["errors"].items() if k in ("D4", "E1", "E2", "E3", "E4", "E5")}, flush=True)
    mean = {}
    for k in per[0]["errors"]:
        mean[k] = {h: (float(np.mean(v)) if (v := [p["errors"][k][h] for p in per if p["errors"][k][h] is not None]) else None) for h in C3.HZ}
        mean[k]["sel_mean"] = float(np.mean([mean[k][h] for h in C3.SEL]))
    res = {"stage": a.stage, "design": a.design, "mean": mean, "per_cutoff": per, "gate_max_gap_points": max(gaps.values()), "gate_worst": sorted(gaps.items(), key=lambda kv: -kv[1])[:5]}
    (out / f"run5_{a.stage}.json").write_text(json.dumps(res, indent=1))
    for k, v in sorted(mean.items(), key=lambda kv: kv[1]["sel_mean"]):
        print(f"{k:14s} " + "  ".join(f"{h}w {v[h]:5.2f}" if v[h] is not None else f"{h}w    –  " for h in C3.HZ) + f"  mean {v['sel_mean']:5.2f}")
    print("gate worst gaps:", res["gate_worst"])


if __name__ == "__main__":
    main()
