"""Development check, not a reported result: the simulation's central path against the classical forecasts on the
development cutoffs only (the first `dev_cutoffs` in evaluation/protocol.yaml), with optional setting overrides.

    python instances/jolts_quits/ingest/audit/probe_dev.py [--set knot_months=24 --set grid.gamma=[0,1]]
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from orgsim.instances import InstanceContext, get_instance  # noqa: E402
from orgsim.worlds import turnover as T  # noqa: E402


@dataclasses.dataclass(frozen=True)
class ProbeCtx(InstanceContext):
    overrides: str = "{}"

    def yaml(self, relpath: str):
        d = super().yaml(relpath)
        if relpath == "calibration/turnover.yaml":
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
    a = ap.parse_args()
    base = get_instance("jolts_quits")
    ov = {kv.split("=", 1)[0]: yaml.safe_load(kv.split("=", 1)[1]) for kv in a.set}
    ctx = ProbeCtx(base.id, base.root, base.meta, json.dumps(ov, default=str))
    proto = ctx.yaml("evaluation/protocol.yaml")
    cutoffs = proto["cutoffs"][: int(proto["dev_cutoffs"])]
    H = int(proto["horizon_months"])
    hz = [int(h) for h in proto["headline_horizons"]]
    d = T.load_data(ctx)
    par = ctx.yaml("calibration/turnover.yaml")
    rows, specs = [], []
    for c in cutoffs:
        w = T.World.from_instance(ctx, {"id": "probe", "world": {"t0": c, "horizon_months": H}}, 1)
        months = pd.date_range(pd.Timestamp(c), periods=H, freq="MS")
        for ind, p in w.paths.items():
            act = d.q[ind].reindex(months).to_numpy(dtype=float)
            R = p["recent_months"]
            coh = list(p["hires_before"]); central = []
            for m in range(H):
                central.append(100 * p["base"][m] * (1 + p["gamma"] * sum(coh[-R:]))); coh.append(p["hires"][m])
            comp = T.comparator_forecasts(d.q[ind][d.q.index < pd.Timestamp(c)].dropna().to_numpy(), H)
            rows.append({"cutoff": c, "industry": ind, "actual": act.tolist(), "covered90": [True] * H,
                         "predictions": {"simulation": central, **{k: v.tolist() for k, v in comp.items()}}})
            specs.append(w.cal[ind]["spec"])
        print(c, flush=True)
    who = ["simulation", *T.COMPARATOR_LABELS]
    s = T.summarize(rows, who, hz)
    print("overrides:", ov)
    print("HEADLINE h=3,6", "  ".join(f"{k}={s['headline_horizons'][k]['wape']:.2f}" for k in who if s["headline_horizons"][k]))
    for h in ("1", "3", "6"):
        print(f"  h={h}", "  ".join(f"{k}={s['by_horizon'][h][k]['wape']:.2f}" for k in who if s["by_horizon"][h][k]))
    sp = pd.DataFrame(specs)
    print("specs chosen:", {c: sp[c].value_counts().to_dict() for c in sp.columns})


if __name__ == "__main__":
    main()
