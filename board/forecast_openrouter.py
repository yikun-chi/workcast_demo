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


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", required=True)
    a = ap.parse_args()
    ctx = get_instance("openrouter")
    d = M.load_data(ctx)
    t0 = pd.Timestamp(d.aw.week.max()) + M.WEEK
    H = int(ctx.yaml("evaluation/protocol.yaml").get("horizon_weeks", 8))
    lag = pd.Timestamp.now(tz="UTC").tz_localize(None) - t0
    if lag > pd.Timedelta(days=MAX_LAG_DAYS):
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
    rec = {
        "board": "openrouter", "t0": str(t0.date()), "weeks": weeks, "horizon_weeks": H,
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
