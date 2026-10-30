"""Choose the twin-calibration specification on 2010 data only (development split), before the experiment is scored.

Two pseudo-changes inside 2010 (weeks 201027 and 201037): each candidate estimates every participant's performance level
from the weeks before the pseudo-change and predicts the weeks after it, up to week 201048. Nothing from the experiment
period (week 201049 onwards) is read. The exit-hazard window is chosen the same way on staff outside the experiment.

Selection rule, fixed in advance: the level estimator with the lowest sum, over the two pseudo-changes, of person-week
mean absolute error for the performance score and for log weekly calls, each divided by the error of the plain 2010 mean;
the exit-hazard spell threshold with the lowest mean absolute error in the share of employees leaving.

Writes instances/ctrip/calibration/selection.json.  Run: python instances/ctrip/ingest/audit/select_spec.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[4]))
spec_ = importlib.util.spec_from_file_location("ctrip_ingest", HERE.parents[1] / "run.py")
ING = importlib.util.module_from_spec(spec_); spec_.loader.exec_module(ING)  # type: ignore[union-attr]

PSEUDO_CUTS = [201027, 201037]
LAST_PRE = 201048
CANDIDATES = [{"estimator": "mean_all"}, {"estimator": "last_k", "k": 4}, {"estimator": "last_k", "k": 8}, {"estimator": "last_k", "k": 13},
              {"estimator": "shrink"}]
SPELLS = [0, 8, 13, 20]


def level_errors(panel: pd.DataFrame, ids: list[str], cut: int, cand: dict) -> dict:
    feats = ING.pre_features(panel, cut, cand, ids).set_index("person_id")
    out = {}
    test = panel[(panel.year_week >= cut) & (panel.year_week <= LAST_PRE) & panel.person_id.isin(ids)]
    for col, feat, valid in (("perform1", "perf_level", test.perform1.notna()), ("log_calls", "calls_level", test.calls_valid)):
        t = test[valid].join(feats[feat], on="person_id").dropna(subset=[feat, col])
        out[col] = {"mae": float((t[col] - t[feat]).abs().mean()),
                    "arm_error": {str(a): float(t[t.group == a][feat].mean() - t[t.group == a][col].mean()) for a in (0, 1)},
                    "n": int(len(t))}
    return out


def hazard_errors(panel: pd.DataFrame, cut: int, k: int, min_test_spell: int) -> dict:
    h = ING.exit_hazard(panel, cut, k)["weekly"]
    d = panel[panel.group.isin([2, 3]) & (panel.year_week <= LAST_PRE)]
    g = d.groupby("person_id").year_week
    first, last = g.min(), g.max()
    at_cut = (first < cut) & (last >= cut) & ((cut - first) >= min_test_spell)
    pop = first.index[at_cut]
    horizon = LAST_PRE - ING.EXIT_GAP     # exits observable in weeks cut .. horizon (same rule as the hazard)
    weeks = horizon - cut + 1
    actual = float((last[pop] <= horizon).mean())
    pred = 1.0 - (1.0 - h) ** weeks
    return {"hazard": h, "predicted_share": pred, "actual_share": actual, "abs_error_pp": 100 * abs(pred - actual), "n": int(len(pop))}


def main() -> None:
    from orgsim.instances import get_instance
    ctx = get_instance("ctrip")
    root = ING.fetch(ctx)
    panel = ING.build_panel(root)
    panel = panel[panel.year_week < ING.T0_WEEK]            # development uses 2010 only
    ids = sorted(panel[panel.group.isin([0, 1])].person_id.unique())
    rows = []
    for cand in CANDIDATES:
        errs = {cut: level_errors(panel, ids, cut, cand) for cut in PSEUDO_CUTS}
        rows.append({"candidate": cand, "errors": {str(c): e for c, e in errs.items()}})
    base = {str(c): {col: next(r for r in rows if r["candidate"]["estimator"] == "mean_all")["errors"][str(c)][col]["mae"] for col in ("perform1", "log_calls")} for c in PSEUDO_CUTS}
    for r in rows:
        r["score"] = round(sum(r["errors"][str(c)][col]["mae"] / base[str(c)][col] for c in PSEUDO_CUTS for col in ("perform1", "log_calls")), 5)
    best = min(rows, key=lambda r: r["score"])
    haz = []
    for k in SPELLS:
        e = [hazard_errors(panel, 201027, k, 20), hazard_errors(panel, 201037, k, 26)]
        haz.append({"min_spell": k, "pseudo": e, "mean_abs_error_pp": round(float(np.mean([x["abs_error_pp"] for x in e])), 4)})
    best_h = min(haz, key=lambda r: r["mean_abs_error_pp"])
    out = {"rule": "level estimator: lowest sum over pseudo-changes of person-week MAE (performance and log calls) relative to the plain 2010 mean; "
                   "exit hazard: lowest mean absolute error in the share leaving among staff with at least 20 (26) observed weeks",
           "pseudo_changes": PSEUDO_CUTS, "data": "2010 weeks 201001-201048 only",
           "candidates": rows, "hazard_candidates": haz,
           "selected": {**best["candidate"], "min_spell": best_h["min_spell"]}}
    (ctx.calibration_dir / "selection.json").write_text(json.dumps(out, indent=1))
    for r in rows:
        print(f"{json.dumps(r['candidate']):40s} score {r['score']:.4f}  " + "  ".join(f"{c}: perf {r['errors'][str(c)]['perform1']['mae']:.4f} calls {r['errors'][str(c)]['log_calls']['mae']:.4f}" for c in PSEUDO_CUTS))
    for h in haz:
        print(f"min_spell {h['min_spell']:2d}: mean abs error {h['mean_abs_error_pp']:.2f} pp  " + "  ".join(f"pred {x['predicted_share']:.3f} act {x['actual_share']:.3f} n {x['n']}" for x in h["pseudo"]))
    print("selected:", out["selected"])


if __name__ == "__main__":
    main()
