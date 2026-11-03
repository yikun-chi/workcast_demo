"""Development check for the buyer seat: run the central path at the given cutoffs (seed 1) and print, per segment,
the distance of each predicted final-week model mix from the actual one and the share taken by newly listed models.
Prompt design uses only the first four protocol cutoffs; the rest are left for the scored evaluation.

    .venv/bin/python instances/openrouter/ingest/audit/probe_buyer.py 2025-07-07 2025-08-04 2025-09-01 2025-09-29
"""
from __future__ import annotations

import shutil
import sys

import numpy as np
import pandas as pd

from orgsim.instances import get_instance
from orgsim.scenarios import load_scenario
from orgsim.worlds import market as M


def main(cutoffs: list[str]) -> None:
    ctx = get_instance("openrouter")
    sc = load_scenario(ctx, "baseline")
    rows, ranks = [], []
    for c in cutoffs:
        w, s = M._run_world(ctx, sc, 1, c)
        h = s.headline
        act = M.actual_window(w.d, w.t0, w.H, [a["app_id"] for a in h["apps"]], w.app_seg)["mix_end"]
        mix0 = {sg: M.segment_mix(w.d, sg, w.prior_week) for sg in w.segments}
        for sg, v in M.share_scores(h, act, mix0).items():
            rows.append((c, sg, v))
            print(c, sg, {k: round(x, 1) for k, x in v["distance"].items()}, "new", {k: round(x, 1) for k, x in v["new_share"].items()}, flush=True)
        print(c, "buyer", h.get("buyer"), flush=True)
        # which launches win: buyer's judgment and the rule's provider prior against each new model's actual final-week share
        for sg in w.segments:
            judged = {m: v for (s_, _), j in w.judged.items() if s_ == sg and j for m, v in j.items()}
            lp = w.launch[sg]
            new = w.new_models.drop_duplicates("model")
            rule = {r.model: float(np.median(lp["by_provider"][r.provider] if len(lp["by_provider"].get(r.provider, [])) >= 3 else lp["all"])) for r in new.itertuples()}
            a = act[sg].reindex(list(rule)).fillna(0.0) if sg in act else None
            if a is None or a.sum() == 0:
                continue
            df = pd.DataFrame({"actual": a, "rule": pd.Series(rule), "buyer": pd.Series(judged)}).dropna()
            if len(df) > 3:
                corr = df.rank().corr()["actual"]
                ranks.append((sg, len(df), corr["rule"], corr["buyer"]))
                print(c, sg, "launch rank corr with actual: rule", round(corr["rule"], 2), "buyer", round(corr["buyer"], 2), "n", len(df), flush=True)
        shutil.rmtree(ctx.runs_dir / "baseline" / s.run_id, ignore_errors=True)
    who = sorted({k for _, _, v in rows for k in v["distance"]})
    print("mean distance", {k: round(float(np.mean([v["distance"][k] for _, _, v in rows])), 1) for k in who})
    if ranks:
        print("mean launch rank corr: rule", round(float(np.nanmean([r[2] for r in ranks])), 2), "buyer", round(float(np.nanmean([r[3] for r in ranks])), 2))
    print("mean new share", {k: round(float(np.mean([v["new_share"][k] for _, _, v in rows])), 1) for k in ["actual", *who]})


if __name__ == "__main__":
    main(sys.argv[1:])
