"""Print the frozen design's predictions for the held-out window before it is scored. Reads no record effective after
the cutoff: the simulation runs on the cutoff's twins and the comparators read records visible at the cutoff.

    .venv/bin/python instances/fedwork/ingest/audit/predict_heldout.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))


def main(seeds: int = 5) -> None:
    from orgsim.instances import get_instance
    from orgsim.store import RunWriter
    from orgsim.worlds import workforce_forecast as F
    from orgsim.worlds.workforce import World
    ctx = get_instance("fedwork")
    proto = ctx.yaml("evaluation/protocol.yaml")
    c = next(x for x in proto["cutoffs"] if x["role"] == "held_out")
    months = F.scored_months(c["cutoff"], int(proto["score_months"]["first"]), int(proto["score_months"]["count"]))
    totals, monthly, drp = [], [], []
    for sd in range(1, seeds + 1):
        w = World.from_instance(ctx, F.cutoff_scenario(ctx, proto, c), sd)
        writer = RunWriter(ctx.id, "baseline", run_id=f"predict-{sd}")
        try:
            w.run(writer)
        finally:
            shutil.rmtree(writer.dir, ignore_errors=True)
        groups = w.metrics["separations"]["groups"]
        fr = F.run_frame(w.metrics)
        fr = fr[fr.month.isin(months)]
        totals.append(fr.n.sum()); drp.append(fr[fr.type == "drp"].n.sum())
        monthly.append(fr.groupby("month").n.sum().reindex(months).to_numpy())
    print(f"simulation, {months[0]}..{months[-1]}: total {np.mean(totals):,.0f} (runs {min(totals):,.0f}-{max(totals):,.0f}); of which deferred resignations {np.mean(drp):,.0f}")
    print("simulation by month:", dict(zip(months, np.round(np.mean(monthly, axis=0)).astype(int).tolist())))
    comps = F.comparators_module(ctx).compute(ctx, c["cutoff"], months, groups)
    for k, v in comps.items():
        p = F.total(v["pred"], groups, months)
        print(f"{v['label']}: total {p.n.sum():,.0f}; September {p[p.month == c['policy']['offer_effective_month']].n.sum():,.0f}")


if __name__ == "__main__":
    main()
