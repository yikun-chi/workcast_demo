"""Choose the twin specification and the exponential-smoothing constants on the development cutoffs only.

Development cutoffs are December 2021, 2022 and 2023 (no announced policy change followed them); each predicts
February-December of the next year. Nothing after December 2024 is read: every development window ends in 2024.

Twin candidates: rate window (12, 24, 36 months) x shrinkage toward agency-scaled demographic rates (0, 120, 1,200
person-months) x month-of-year pattern (none, government-wide by type, each agency's own shrunk toward government-wide)
x stock (depleting, constant). Each candidate runs
the workforce world once per cutoff at the priors' central values.
Exponential-smoothing candidates: alpha (0.1, 0.3, 0.5) x beta (0, 0.05) x gamma (0.1, 0.3) x phi (0.9, 1.0).

Selection rule, fixed in advance: the lowest mean over the development cutoffs of the error in each agency's monthly
separations (sum of absolute errors over agency-months divided by actual separations).

Writes instances/fedwork/calibration/selection.json.   Run: python instances/fedwork/ingest/audit/select_spec.py
"""
from __future__ import annotations

import importlib.util
import itertools
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[4]))
_s = importlib.util.spec_from_file_location("fedwork_ingest", HERE.parents[1] / "run.py")
ING = importlib.util.module_from_spec(_s); _s.loader.exec_module(ING)  # type: ignore[union-attr]

WINDOWS, SHRINK, SEASON, STOCK = [12, 24, 36], [0, 120, 1200], ["none", "government", "agency"], ["depleting", "constant"]
ETS_GRID = [{"alpha": a, "beta": b, "gamma": g, "phi": p} for a, b, g, p in itertools.product([0.1, 0.3, 0.5], [0.0, 0.05], [0.1, 0.3], [0.9, 1.0])]


def main() -> None:
    from orgsim.instances import get_instance
    from orgsim.scenarios.loader import deep_merge
    from orgsim.store import RunWriter
    from orgsim.worlds import workforce_forecast as F
    from orgsim.worlds.workforce import World
    ctx = get_instance("fedwork")
    proto = ctx.yaml("evaluation/protocol.yaml")
    comps = F.comparators_module(ctx)
    seps, heads = comps.load(ctx)
    dev = [c for c in proto["cutoffs"] if c["role"] == "development"]
    assert all(c["cutoff"] < "2024-12" for c in dev)
    first, count = int(proto["score_months"]["first"]), int(proto["score_months"]["count"])
    tmp = ctx.data_normalized / "dev"
    tmp.mkdir(exist_ok=True)
    acts = {}
    for c in dev:
        months = F.scored_months(c["cutoff"], first, count)
        assert months[-1] <= "2024-12"
        acts[c["cutoff"]] = (months, comps.actual(ctx, c["cutoff"], months))
    rows = []
    for W, a, season in itertools.product(WINDOWS, SHRINK, SEASON):
        spec = {"window_months": W, "shrink": a, "season": season}
        for c in dev:
            twins = ING.build_twins(seps, heads, c["cutoff"], spec)
            name = f"dev/twins_{c['cutoff']}_{W}_{a}_{season}.parquet"
            twins.to_parquet(ctx.data_normalized / name, index=False)
        for stock in STOCK:
            scores = []
            for c in dev:
                months, act_t = acts[c["cutoff"]]
                scn = deep_merge(F.cutoff_scenario(ctx, proto, c), {"world": {"population_file": f"dev/twins_{c['cutoff']}_{W}_{a}_{season}.parquet", "stock": stock, "priors": "central", "twins_sample": 1}})
                t = time.time()
                w = World.from_instance(ctx, scn, 1)
                writer = RunWriter(ctx.id, "development", run_id=f"select-{c['cutoff']}-{W}-{a}-{season}-{stock}")
                try:
                    w.run(writer)
                finally:
                    shutil.rmtree(writer.dir, ignore_errors=True)
                groups = w.metrics["separations"]["groups"]
                pred = F.total(F.run_frame(w.metrics), groups, months)
                act = F.total(act_t, groups, months)
                s = F.score(pred, act)
                scores.append({"cutoff": c["cutoff"], **{k: round(v, 3) for k, v in s.items()}})
                print(f"W={W} a={a} season={season} stock={stock} {c['cutoff']}: group-month error {s['group_month_wape']:.2f}% total {s['total_error_pct']:+.2f}% ({time.time() - t:.0f}s)", flush=True)
            rows.append({"spec": {**spec, "stock": stock}, "windows": scores, "mean_group_month_wape": round(float(np.mean([x["group_month_wape"] for x in scores])), 3)})
    best = min(rows, key=lambda r: r["mean_group_month_wape"])
    ets_rows = []
    for p in ETS_GRID:
        sc = []
        for c in dev:
            months, act_t = acts[c["cutoff"]]
            groups = sorted(set(ING.agency_groups(heads, c["cutoff"]).values()))
            pred = comps.compute(ctx, c["cutoff"], months, groups, ets_params=p)["ets"]["pred"]
            sc.append(F.score(F.total(pred, groups, months), F.total(act_t, groups, months))["group_month_wape"])
        ets_rows.append({"params": p, "mean_group_month_wape": round(float(np.mean(sc)), 3)})
    best_ets = min(ets_rows, key=lambda r: r["mean_group_month_wape"])
    out = {"rule": "lowest mean over the development cutoffs of the error in each agency's monthly separations",
           "development_cutoffs": [c["cutoff"] for c in dev], "candidates": rows, "ets_candidates": ets_rows,
           "selected": {k: best["spec"][k] for k in ("window_months", "shrink", "season")}, "selected_stock": best["spec"]["stock"],
           "comparators": {"ets": best_ets["params"]}}
    (ctx.calibration_dir / "selection.json").write_text(json.dumps(out, indent=1))
    shutil.rmtree(tmp, ignore_errors=True)
    print("selected:", best["spec"], best["mean_group_month_wape"], "ets:", best_ets)


if __name__ == "__main__":
    main()
