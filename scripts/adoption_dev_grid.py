"""Development check for an adoption-world instance: on the development cutoffs only (the first quarter of the
protocol's cutoffs), score every fixed diffusion specification and growth window, and the per-cutoff selection, on the
protocol's blocks. Used to make design choices before the held-out cutoffs are run; it never reads held-out targets.

    .venv/bin/python scripts/adoption_dev_grid.py <instance> [--slopes 12,26,0] [--top 25]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orgsim.instances import get_instance  # noqa: E402
from orgsim.worlds import adoption as W  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("instance")
    ap.add_argument("--slopes", default="12,26,0", help="growth windows in periods (0: all history)")
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()
    ctx = get_instance(a.instance)
    proto, cfg = ctx.yaml("evaluation/protocol.yaml"), ctx.yaml("calibration/adoption.yaml")
    d = W.load_data(ctx)
    cuts = W.cutoff_list(proto, d)
    dev = cuts[: W.dev_count(proto, len(cuts))]
    groups = W.model_groups(d, cfg)
    scored = d.groups[d.groups.scored.astype(bool)].group.astype(str).tolist() if "scored" in d.groups else groups
    gi = [groups.index(g) for g in scored]
    blocks = proto["blocks"]
    H = max(int(b["to"]) for b in blocks)
    agg = "sum" if cfg.get("outcome") == "displaced" else "mean"
    last = int(d.series.period.max())
    specs = W.spec_list(cfg.get("grid", {}))
    res: dict[str, list[float]] = {}
    comp_res: dict[str, list[float]] = {}
    sel_res: dict[str, list[float]] = {}
    for c in dev:
        v = W.View(d, cfg, groups, c)
        A_hist = v.A[:, v.periods >= v.start]
        pool = v.pool[v.periods >= v.start] if v.pool is not None else None
        act_full = d.matrix(groups, list(range(c, c + H)))
        tgt = np.arange(c, c + H)
        comp = W.comparators(v, H, list(proto.get("comparators", [])), int(proto.get("recent_periods", 6)), proto.get("season_periods"), proto.get("trend_periods"))
        for b in blocks:
            if c - 1 + int(b["to"]) > last:
                continue
            act = W.block_value(act_full, b, agg)[gi]
            ok = np.isfinite(act)
            score = lambda P: float(np.mean(np.abs(W.block_value(P, b, agg)[gi][ok] - act[ok])))  # noqa: E731
            for k, P in comp.items():
                comp_res.setdefault(k, []).append(score(P))
            for sl in [int(x) for x in a.slopes.split(",")]:
                for sp in specs:
                    P = v.outcome_from_share(W.central_share(A_hist, pool, H, sp, sl), tgt)
                    res.setdefault(json.dumps({**sp, "slope": sl}), []).append(score(P))
                c2 = {**cfg, "slope_periods": sl}
                dyn = W.fit_dynamics(d, c2, groups, c, H)
                P = v.outcome_from_share(W.central_share(A_hist, pool, H, dyn["spec"], sl), tgt)
                sel_res.setdefault(f"selected (slope {sl})", []).append(score(P))
                print(f"cutoff {c} block {b['id']} slope {sl}: selected {dyn['spec']} ({dyn['selection']})", flush=True)
    sc = float(proto.get("scale", 1.0))
    print("\ncomparators:", {k: round(np.mean(v_) * sc, 3) for k, v_ in comp_res.items()})
    print("selection:", {k: round(np.mean(v_) * sc, 3) for k, v_ in sel_res.items()})
    print(f"\nbest fixed specifications of {len(res)} (mean over dev cutoffs and blocks):")
    for k, v_ in sorted(res.items(), key=lambda kv: np.mean(kv[1]))[: a.top]:
        print(round(np.mean(v_) * sc, 3), k)


if __name__ == "__main__":
    main()
