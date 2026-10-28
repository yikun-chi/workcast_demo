"""Development check, not a reported result: the simulation's central path against the classical forecasts on the
development cutoffs only (the first `dev_cutoffs` in evaluation/protocol.yaml), with optional setting overrides.

    python instances/nyc_congestion/ingest/audit/probe_dev.py [--set harmonics=6 --set knot_days=91] [--groups yellow_zone,hvfhv_zone]

Prints pooled WAPE per group and over the headline groups. Never reads a held-out cutoff.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from orgsim.instances import InstanceContext, get_instance  # noqa: E402
from orgsim.scenarios import load_scenario  # noqa: E402
from orgsim.store import RunWriter  # noqa: E402
from orgsim.worlds import demand as D  # noqa: E402


@dataclasses.dataclass(frozen=True)
class ProbeCtx(InstanceContext):
    overrides: str = "{}"

    def yaml(self, relpath: str):
        d = super().yaml(relpath)
        if relpath == "calibration/demand.yaml":
            for k, v in json.loads(self.overrides).items():
                cur = d
                *path, last = k.split(".")
                for p in path:
                    cur = cur[p]
                cur[last] = v
        return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--groups", default="")
    a = ap.parse_args()
    base = get_instance("nyc_congestion")
    ov = {kv.split("=", 1)[0]: yaml.safe_load(kv.split("=", 1)[1]) for kv in a.set}
    ctx = ProbeCtx(base.id, base.root, base.meta, json.dumps(ov, default=str))
    proto = ctx.yaml("evaluation/protocol.yaml")
    cutoffs = proto["cutoffs"][: int(proto["dev_cutoffs"])]
    H = int(proto["horizon_weeks"])
    groups = [g for g in proto["groups"] if not a.groups or g["id"] in a.groups.split(",")]
    d = D.load_data(ctx)
    sc = load_scenario(ctx, "baseline")
    rows = []
    for c in cutoffs:
        sc["world"]["t0"] = c
        w = D.World.from_instance(ctx, sc, 1)
        writer = RunWriter(ctx.id, "probe", run_id=f"probe-{c}")
        try:
            s = w.run(writer)
        finally:
            shutil.rmtree(writer.dir.parent, ignore_errors=True)
        by = {x["series_id"]: x for x in s.headline["series"]}
        days = pd.date_range(pd.Timestamp(c), periods=7 * H, freq="D")
        for g in groups:
            sids = D.group_ids(d.meta, g.get("where"))
            act = d.y.loc[days, sids].sum(axis=1).to_numpy().reshape(H, 7).sum(1)
            comp = D.comparator_forecasts(D.weekly_history(d, sids, pd.Timestamp(c)), H)
            rows.append({"cutoff": c, "group": g["id"], "headline": bool(g.get("headline")), "phase": "dev", "actual": act.tolist(),
                         "predictions": {"simulation": np.sum([by[x]["central"] for x in sids], axis=0).tolist(), **{k: v.tolist() for k, v in comp.items()}}})
        specs = {sid: by[sid]["calibration"]["spec"] for sid in by}
        print(c, {k: f"{v['level_days']}/{v['drift']}/{v['phi']}" for k, v in specs.items()}, flush=True)
    who = ["simulation", *D.COMPARATOR_LABELS]
    print("overrides:", ov)
    for g in groups:
        r = [x for x in rows if x["group"] == g["id"]]
        print(f"{g['id']:16s}", "  ".join(f"{k}={D.pooled(r, k)['wape']:.2f}" if D.pooled(r, k) else f"{k}=n/a" for k in who))
    for g in groups:
        r = [x for x in rows if x["group"] == g["id"]]
        for k in ("simulation", "ets", "seasonal_naive"):
            bias = np.mean([np.array(x["predictions"][k]) / np.array(x["actual"]) - 1 for x in r], axis=0) * 100
            print(f"  bias {g['id']:14s} {k:15s}", " ".join(f"{b:+.1f}" for b in bias[[0, 1, 2, 3, 7, 12, 18, 25]]))
        print("  by cutoff sim/ets/sn:", " ".join(f"{x['cutoff'][2:]}:{D.pooled([x], 'simulation')['wape']:.1f}/{D.pooled([x], 'ets')['wape']:.1f}/{D.pooled([x], 'seasonal_naive')['wape']:.1f}" for x in r))
    hr = [x for x in rows if x["headline"]]
    if hr:
        s = D.summarize(hr, who)
        print("HEADLINE", "  ".join(f"{k}={s['all_weeks'][k]['wape']:.2f}" for k in who if s["all_weeks"][k]),
              "| by horizon", {b: round(v["simulation"]["wape"], 2) for b, v in s["by_horizon"].items()},
              {b: (v["best_baseline"], round(v[v["best_baseline"]]["wape"], 2)) for b, v in s["by_horizon"].items()})


if __name__ == "__main__":
    main()
