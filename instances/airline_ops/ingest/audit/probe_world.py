"""Development probe: fit the airline world at one cutoff and run one seed; prints timings, fitted parameters and the
first week's predictions next to the actual outcome. Use only on development cutoffs (protocol dev_cutoffs).

  python instances/airline_ops/ingest/audit/probe_world.py 2022-01-03 [paths]
"""
from __future__ import annotations

import sys
import time

import numpy as np
import pandas as pd

from orgsim.instances import get_instance
from orgsim.store.runs import RunWriter
from orgsim.worlds import airline


def main() -> None:
    t0 = sys.argv[1]
    P = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    ctx = get_instance("airline_ops")
    proto = ctx.yaml("evaluation/protocol.yaml")
    dev = [str(c.date()) for c in airline.protocol_cutoffs(proto)[:int(proto["dev_cutoffs"])]]
    if t0 not in dev:
        raise SystemExit(f"{t0} is not a development cutoff")
    t = time.time()
    d = airline.load_data(ctx)
    print(f"load {time.time() - t:.1f}s; {len(d.dates)} days, {len(d.carriers)} carriers, {len(d.airports)} airports")
    t = time.time()
    fit = airline.cached_fit(ctx, d, pd.Timestamp(t0), ctx.yaml("calibration/airline.yaml"))
    print(f"fit {time.time() - t:.1f}s; train {fit['train_from']} .. {fit['train_to']} ({fit['train_days']} days)")
    a = fit["air"]
    print(f"storm factor rho {a['rho_g']:.3f} sd {a['sd_g']:.3f}; airport rho median {np.median(a['rho_e']):.3f}; slow phi median {np.median(a['phi_slow']):.3f}")
    for c, f in fit["carriers"].items():
        print(f"  {c}: decay {f['decay']}, canc beta {np.round(f['canc']['beta'][[1, 2, 3, 10]], 3)}, rho {f['canc']['rho']:.2f} sd {f['canc']['sd']:.2f} cell {f['canc']['sd_cell']:.2f}"
              f" phi {f['canc']['phi_slow']:.2f} slow0 {f['canc']['slow0']:+.2f} | late rho {f['late']['rho']:.2f} sd {f['late']['sd']:.2f} slow0 {f['late']['slow0']:+.2f} corr {f['corr']:.2f}")
    sc = {"id": "probe", "world": {"t0": t0, "horizon_days": 28, "paths": P}, "interventions": []}
    w = airline.World.from_instance(ctx, sc, 1)
    wr = RunWriter(ctx.id, "probe", config={"probe": True})
    t = time.time()
    s = w.run(wr)
    wr.close(s.to_json())
    print(f"run {time.time() - t:.1f}s")
    res = airline.score_cutoff(d, pd.Timestamp(t0), [s.headline], ctx.yaml("calibration/airline.yaml").get("exclude_periods", []))
    for m in ("ontime", "cancel"):
        blk = res[f"carrier_{m}"]
        n = np.array(res["carrier_sched"])
        print(f"carrier {m}: MAE (pp) by week, scored carrier-weeks with >= 200 flights")
        for who in ["simulation", *airline.COMPARATOR_LABELS]:
            e = np.abs(np.array(blk[who]) - np.array(blk["actual"]))[n >= 200]
            print(f"   {who:20s} {e.mean():6.2f}")
    print("carrier, actual week1 on-time, sim, ets; cancel actual, sim")
    for j, c in enumerate(res["carriers"]):
        print(f"   {c:3s} {res['carrier_ontime']['actual'][0][j]:6.1f} {res['carrier_ontime']['simulation'][0][j]:6.1f} {res['carrier_ontime']['ets'][0][j]:6.1f} | "
              f"{res['carrier_cancel']['actual'][0][j]:5.2f} {res['carrier_cancel']['simulation'][0][j]:5.2f}")


if __name__ == "__main__":
    main()
