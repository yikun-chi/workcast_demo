"""Write this week's advance forecast for the OpenRouter board, before any of the forecast weeks has happened.

The cutoff t0 is the Monday after the latest complete week in the data. The forecast is the market world's central
path (point) and the 5th-95th percentile of its runs (range) for every leading app's weekly tokens and spend, the
market total, and each segment's model mix, next to the standard forecasts made from the same data. The record
carries the code commit, the SHA-256 of every input table, and its own SHA-256; `board/stamp.sh` then anchors that
hash with OpenTimestamps. A record is never rewritten: an existing record for the same cutoff stops the run.

    .venv/bin/python board/forecast_openrouter.py --records /Volumes/PsychDynamicsData/workcast_board/records
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from orgsim.instances import get_instance
from orgsim.scenarios import load_scenario
from orgsim.store import RunWriter
from orgsim.worlds import market as M

SEEDS = range(1, 21)
MAX_LAG_DAYS = 2
# The board's headline method is E3 (Run 5 of docs/plans/astra_forecast_protocol.md, frozen 2026-11-01; chosen for the board
# by Sumer the same day): the mean of (a) a per-horizon blend of the WORKCAST central path, the language model and the
# bounded damped trend, weights chosen on every earlier cutoff whose horizon has elapsed, and (b) Timestral's forecast
# adjusted by the language model with the simulation's forecast in view. Cumulative tokens at 1, 2, 4 and 8 weeks.
STACK = ("workcast", "astra", "damped_trend")
ASTRA_CAP_USD = 10.0                                                   # live-board language-model spend, separate from the backtests
HISTORY_DIR = Path("/Volumes/PsychDynamicsData/workcast_board/astra")  # saved forecasts at the 25 backtest cutoffs
TIMESTRAL_PY = Path("/Volumes/PsychDynamicsData/workcast_board/.tsvenv/bin/python")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", required=True)
    ap.add_argument("--allow-late", action="store_true", help="dry runs into a test folder only: skip the publication-lag rule")
    ap.add_argument("--history", default=str(HISTORY_DIR), help="saved backtest forecasts the walk-forward weights learn from")
    ap.add_argument("--timestral-python", default=str(TIMESTRAL_PY))
    a = ap.parse_args()
    ctx = get_instance("openrouter")
    d = M.load_data(ctx)
    t0 = pd.Timestamp(d.aw.week.max()) + M.WEEK
    H = int(ctx.yaml("evaluation/protocol.yaml").get("horizon_weeks", 8))
    lag = pd.Timestamp.now(tz="UTC").tz_localize(None) - t0
    if lag > pd.Timedelta(days=MAX_LAG_DAYS) and not (a.allow_late and "test" in a.records):
        # an advance forecast must be published before its first week is under way; a late run is skipped, not backdated
        print(f"skip: cutoff {t0.date()} is {lag.days} days old (limit {MAX_LAG_DAYS}); waiting for the next complete week")
        return
    out = Path(a.records) / "openrouter" / f"{t0.date()}.json"
    if out.exists():
        print(f"forecast for {t0.date()} already recorded: {out}")
        return
    sc = load_scenario(ctx, "baseline"); sc["world"]["t0"] = str(t0.date())
    heads = []
    for seed in SEEDS:
        writer = RunWriter(ctx.id, "board", run_id=f"board-{t0.date()}-{seed}")
        try:
            heads.append(M.World.from_instance(ctx, sc, seed).run(writer).headline)
        finally:
            shutil.rmtree(writer.dir, ignore_errors=True)
    h0 = heads[0]
    ids = [x["app_id"] for x in h0["apps"]]
    segs = np.array([x["segment"] for x in h0["apps"]])
    prior_week = max(w for w in d.mw.week.unique() if w < t0)
    mix0 = {s: M.segment_mix(d, s, prior_week) for s in set(segs)}
    comp = M.comparators(d, t0, H, ids, segs, mix0)
    T = np.array([[x["tokens"] for x in hd["apps"]] for hd in heads])             # seeds x apps x H
    S = np.array([[x["spend_usd"] for x in hd["apps"]] for hd in heads])
    mk = d.mw.groupby("week").market_tokens.first()
    mk_last4 = float(mk[mk.index < t0].iloc[-4:].mean())
    weeks = [str((t0 + i * M.WEEK).date()) for i in range(H)]
    apps = []
    for i, x in enumerate(h0["apps"]):
        apps.append({"app_id": x["app_id"], "name": x["name"], "segment": x["segment"], "category": x["category"], "persistence": x["persistence"],
                     "recent_weekly_tokens": round(x["start_tokens_week"]),           # average of the four weeks before t0
                     "tokens": [round(v) for v in x["tokens_central"]], "spend_usd": [round(v, 2) for v in x["spend_central"]],
                     "tokens_total_range90": [round(float(np.percentile(T[:, i].sum(1), 5))), round(float(np.percentile(T[:, i].sum(1), 95)))],
                     "comparators_tokens": {k: [round(float(v_)) for v_ in v["tokens"][i]] for k, v in comp.items()}})
    # ---- cumulative forecasts at 1, 2, 4, 8 weeks: WORKCAST alone, the standards, the language model, Timestral adjusted by
    # the language model, and the combined method
    import subprocess
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import astra_backtest as A
    import combo3 as C3
    import combo4 as C4
    import combo5 as C5
    import combo_study as CS
    hist = [t0 - (A.HISTORY - i) * M.WEEK for i in range(A.HISTORY)]
    xh, _ = M.app_matrix(d, hist, ids)
    cumf = {"workcast": CS.cum(np.array([x["tokens_central"] for x in h0["apps"]])), "damped_trend": CS.cum(CS.damped_trend(xh)),
            **{k: CS.cum(v["tokens"]) for k, v in comp.items() if k != "damped_trend"}}
    notes = {}
    live = Path(a.records).parent / "astra_live"
    (live / "responses").mkdir(parents=True, exist_ok=True)
    ledger_path = live / "ledger.json"

    def ask(user: str) -> np.ndarray:
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else []
        rec = A.call(user, 1, live / "responses", ledger, ASTRA_CAP_USD)
        ledger_path.write_text(json.dumps(ledger, indent=1))
        f = json.loads(rec["text"])["forecasts"]
        return np.array([[float(f.get(str(i), [np.nan] * 4)[k]) for k in range(4)] for i in ids]) * 1e9
    try:
        cumf["astra"] = ask(A.prompt(d, t0, ids))
        notes["llm"] = "ok"
    except (Exception, SystemExit) as e:                              # no key, cap reached, API down: published without it, and said so
        notes["llm"] = f"language model unavailable ({type(e).__name__}: {str(e)[:60]})"
        print("language model step failed:", type(e).__name__, str(e)[:300], flush=True)
    try:
        c = str(t0.date())
        (live / "timestral_in").mkdir(exist_ok=True)
        np.savez(live / "timestral_in" / f"{c}.npz", ids=np.array(ids), logx=C4.history(d, t0, ids))
        subprocess.run([a.timestral_python, str(Path(__file__).resolve().parent / "timestral_run.py"), "--out", str(live)], check=True, capture_output=True,
                       env={**os.environ, "HF_HOME": "/Volumes/PsychDynamicsData/hf_cache"}, timeout=1800)
        ts = C4.timestral(live, c, np.array(ids))
        cumf["timestral"] = ts["median"]
        if "astra" in cumf:
            cumf["timestral_llm"] = ask(C4.adjust_prompt(d, t0, ids, ts, cumf["workcast"]))
            notes["timestral_llm"] = "ok"
        else:
            notes["timestral_llm"] = "not asked: language model unavailable"
    except (Exception, SystemExit) as e:
        notes["timestral_llm"] = f"Timestral step unavailable ({type(e).__name__}: {str(e)[:60]})"
        print("Timestral step failed:", type(e).__name__, str(e)[:300], flush=True)
    # walk-forward weights: every saved backtest cutoff and every earlier live record whose horizon has elapsed by t0
    rows = []
    for c in C3.DEV + C3.TEST:
        hids, F = C3.components(c, d, ctx, Path(a.history), 0.0)
        act, _ = C3.actual(c, d, hids)
        rows.append({"cutoff": c, "F": {k: F[k] for k in STACK}, "act": act})
    for p in sorted((Path(a.records) / "openrouter").glob("*.json")):
        r = json.loads(p.read_text())
        cf = r.get("cumulative_1_2_4_8", {})
        if all(k in cf for k in ("workcast", "llm", "damped_trend")):
            rids = np.array([x["app_id"] for x in r["apps"]])
            act, _ = C3.actual(r["t0"], d, rids)
            rows.append({"cutoff": r["t0"], "F": {"workcast": np.array(cf["workcast"], float), "astra": np.array(cf["llm"], float), "damped_trend": np.array(cf["damped_trend"], float)}, "act": act})
    keys = tuple(k for k in STACK if k in cumf)
    W = C5.walk_weights(rows, str(t0.date()), keys)
    e1 = C5.blend(cumf, keys, W)
    cumf["combined"] = (e1 + cumf["timestral_llm"]) / 2 if "timestral_llm" in cumf else e1
    notes["combined"] = ("E3: mean of the walk-forward blend and Timestral adjusted by the language model" if "timestral_llm" in cumf
                         else "walk-forward blend only: " + notes["timestral_llm"])
    rec = {
        "board": "openrouter",
        "headline_method": "combined: the mean of a walk-forward blend of the WORKCAST simulation, a large language model and the damped trend, "
                           "and a time-series foundation model's forecast adjusted by the language model",
        "notes": notes,
        "walk_forward_weights": {"history_cutoffs": len(rows), "per_horizon_1_2_4_8": {("llm" if k == "astra" else k): [round(float(w), 2) for w in W[i]] for i, k in enumerate(keys)}},
        "cumulative_1_2_4_8": {("llm" if k == "astra" else k): [[round(float(v_)) for v_ in row] for row in v] for k, v in cumf.items()}, "t0": str(t0.date()), "weeks": weeks, "horizon_weeks": H,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "published_hours_after_cutoff": round(lag.total_seconds() / 3600, 1),
        "code_commit": os.environ.get("BOARD_CODE_COMMIT", "unknown"),
        "inputs_sha256": {p.name: sha(p) for p in sorted(ctx.data_normalized.glob("*.parquet"))},
        "method": "WORKCAST market world, baseline scenario: central path (point) and 5th-95th percentile of 20 runs (range). "
                  "Standard forecasts: " + "; ".join(f"{k}: {v}" for k, v in M.COMPARATOR_LABELS.items()),
        "apps": apps,
        "market_tokens": {"simulation": [round(mk_last4 * float(np.exp(v))) for v in h0["market_log_change_central"]],
                          **{k: v["market"] for k, v in comp.items()}},
        "segment_mix_end": {s: dict(sorted(m.items(), key=lambda kv: -kv[1])[:15]) for s, m in h0["segment_mix_end_central"].items()},
        "top_spend_total_usd": {"simulation": round(float(np.array([x["spend_central"] for x in h0["apps"]]).sum()), 2),
                                "range90": [round(float(np.percentile(S.sum((1, 2)), 5)), 2), round(float(np.percentile(S.sum((1, 2)), 95)), 2)]},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(rec, indent=1, sort_keys=True)
    out.write_text(body)
    out.chmod(0o444)                                                              # records are append-only
    print(f"wrote {out} sha256 {hashlib.sha256(body.encode()).hexdigest()}")


if __name__ == "__main__":
    main()
