"""Validation harness for Demo 1: run the baseline at VALIDATION cutoffs (July-August 2018) and score it with the
same scorer as the preregistered protocol, without touching the test cutoffs or writing runs/bpi19/evaluation.json.

    .venv/bin/python instances/bpi19/ingest/audit/validate_cutoffs.py --cutoffs 2018-07-16,2018-08-06 --seeds 1 --tag v2
    ... --set calendar=false --set t0_timing=ipw --set state_order=1 --set same_user=false   (switch v2 components off)

Prints, per cutoff: next-step accuracy / log-loss (engine vs Markov 1/2), completion within the horizon, events, active
cases, exceptions, hand-offs per active case and median cycle time, each against the held-out actual value, plus the
share of open cases (not yet completed at t0) that produce at least one event in the horizon, by gap since their last
event (engine vs actual). Results are saved under runs/bpi19/validation/<tag>.json so variants can be compared.

Leakage: the engine is calibrated on January-June 2018 and reads nothing after t0; this script's actual values are
read by the scorer only. Every validation horizon must end before September 1. Calibration must end before every validation cutoff; refit with --training-end 2018-07-01 to reproduce selection.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from orgsim.instances import get_instance  # noqa: E402
from orgsim.scenarios import load_scenario  # noqa: E402
from orgsim.worlds import process as P  # noqa: E402

GAP_BUCKETS = [(0, 7), (7, 14), (14, 30), (30, 60), (60, 90)]


def activation_by_gap(world: P.World, ev: pd.DataFrame, t0: pd.Timestamp, H: int) -> list[dict]:
    """Share of open-at-t0, not-yet-completed cases with >= 1 event inside (t0, t0+H]: engine vs actual, by gap bucket."""
    oc = world.open_cases
    oc = oc[~oc.completed_before]
    gap_d = ((t0 - oc.last_ts) / pd.Timedelta(days=1)).values
    ids = oc.case_id.values
    end = t0 + pd.Timedelta(days=H)
    act_ids = set(ev[(ev.ts > t0) & (ev.ts <= end)].case_id.unique())
    sim_ids = {e[0] for e in world.sim_events}
    rows = []
    for lo, hi in GAP_BUCKETS:
        m = (gap_d >= lo) & (gap_d < hi)
        n = int(m.sum())
        if n == 0:
            continue
        sel = ids[m]
        rows.append({"gap_days": f"{lo}-{hi}", "n": n,
                     "sim_active": 100.0 * sum(1 for c in sel if c in sim_ids) / n,
                     "act_active": 100.0 * sum(1 for c in sel if c in act_ids) / n})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoffs", default="2018-07-16,2018-08-06")
    ap.add_argument("--seeds", default="1")
    ap.add_argument("--tag", default="pre_policy")
    ap.add_argument("--scenario", default="baseline")
    ap.add_argument("--horizon", type=int, default=14)
    ap.add_argument("--set", action="append", default=[], help="world flag override, e.g. --set state_order=1 --set calendar=false --set t0_timing=ipw")
    a = ap.parse_args()
    cutoffs = [c for c in a.cutoffs.split(",") if c]
    seeds = [int(s) for s in a.seeds.split(",") if s]
    ctx = get_instance("bpi19")
    H = a.horizon
    change_date = pd.Timestamp(ctx.yaml("evaluation/protocol.yaml").get("change_date", "2018-09-01"))
    if H <= 0:
        sys.exit("horizon must be positive")
    for c in cutoffs:
        if pd.Timestamp(c) < pd.Timestamp("2018-07-01") or pd.Timestamp(c) + pd.Timedelta(days=H) > change_date:
            sys.exit(f"validation window {c} + {H} days must follow training and end by {change_date.date()}")
    ev, cases = P.load_events(ctx)
    calib = json.loads((ctx.calibration_dir / "process.json").read_text())
    if pd.Timestamp(calib["fitted_on"]["events_until"]) >= min(pd.Timestamp(c) for c in cutoffs):
        sys.exit("Calibration overlaps validation. Refit with: python instances/bpi19/ingest/run.py --training-end 2018-07-01")
    bindings = ctx.yaml("ontology/bindings.yaml")
    act_props = {x["id"]: (x.get("properties") or {}) for x in bindings.get("activities", [])}
    cons = P.Constraints(ctx.yaml("calibration/constraints.yaml"), act_props)
    completing = {x for x, p in act_props.items() if p.get("completes_case")}
    exceptions = set(calib.get("exceptions", {}).get("core", []))
    mk1, mk2 = P.fit_markov_baselines(ev, cases, calib)
    scenario = load_scenario(ctx, a.scenario)
    scenario["horizon_days"] = H
    for kv in a.set:
        k, v = kv.split("=", 1)
        scenario.setdefault("world", {})[k] = {"true": True, "false": False}.get(v.lower(), int(v) if v.isdigit() else v)
    print(f"world flags: { {k: v for k, v in scenario.get('world', {}).items() if k not in ('t0', 'track')} }")

    out_rows = []
    for c in cutoffs:
        t0 = pd.Timestamp(c)
        truth_next = None
        for seed in seeds:
            world, summ = P._run_world(ctx, scenario, seed, t0=c)
            if truth_next is None:
                truth_next = P._first_actual_next(ev, t0, set(world.first_decision))
            row, sim, act = P.score_run(ev, cases, world, summ, t0, H, mk1, mk2, completing, cons.terminal, exceptions, 10, truth_next)
            row.pop("headline"); row.pop("top_keys")
            row["activation_by_gap"] = activation_by_gap(world, ev, t0, H)
            row["utilization"] = summ.headline["utilization"]
            row["ended_cases"] = summ.headline["ended_cases"]
            row["model"] = summ.headline.get("model")
            out_rows.append(row)

    # ---- print
    def line(label, sim, act, fmt="{:.1f}", extra=""):
        print(f"  {label:38s} sim {fmt.format(sim):>9s}   actual {fmt.format(act):>9s} {extra}")
    for r in out_rows:
        s, ac = r["sim"], r["act"]
        print(f"\n== {a.tag}: t0 {r['t0']} seed {r['seed']}  (scored {r['scored_cases']:,} open cases; population {s['population']:,}; run {r['runtime_s']:.0f}s)")
        print(f"  next-step top-1 accuracy               engine {100*r['next_acc']:.1f}%   markov1 {100*r['markov1_acc']:.1f}%   markov2 {100*r['markov2_acc']:.1f}%   (sampled step {100*r['next_acc_sampled']:.1f}%)")
        print(f"  next-step log-loss                     engine {r['next_logloss']:.3f}    markov1 {r['markov1_logloss']:.3f}    markov2 {r['markov2_logloss']:.3f}")
        line(f"completion within {H} d (%)", s["completion_rate"], ac["completion_rate"], "{:.2f}")
        line("median cycle time of completions (h)", s["median_cycle_h"], ac["median_cycle_h"], "{:.0f}")
        line("events in horizon", s["events"], ac["events"], "{:,.0f}")
        line("active cases in horizon", s["active_cases"], ac["active_cases"], "{:,.0f}")
        line("exception rate (%)", s["exception_rate"], ac["exception_rate"], "{:.2f}")
        line("hand-offs per active case", s["handoffs_per_active_case"], ac["handoffs_per_active_case"], "{:.3f}")
        print(f"  activity-mix JSD {r['jsd_activity']:.4f} bits; p50 rank corr (top 10) {r['p50_rank_corr']:.2f}; cases ended at decision {r['ended_cases']:,}")
        print("  activation of open cases by gap since last event (share with >= 1 event in horizon):")
        for g in r["activation_by_gap"]:
            print(f"    gap {g['gap_days']:>6s} d  n {g['n']:>6,}   engine {g['sim_active']:5.1f}%   actual {g['act_active']:5.1f}%")
    if len(out_rows) > 1:
        m = lambda k: float(np.mean([r[k] for r in out_rows]))  # noqa: E731
        ms = lambda k: float(np.nanmean([r["sim"][k] for r in out_rows]))  # noqa: E731
        ma = lambda k: float(np.nanmean([r["act"][k] for r in out_rows]))  # noqa: E731
        print(f"\n== {a.tag}: MEAN over {len(out_rows)} runs")
        print(f"  next_acc {100*m('next_acc'):.1f}% (mk1 {100*m('markov1_acc'):.1f}, mk2 {100*m('markov2_acc'):.1f})  logloss {m('next_logloss'):.3f} (mk1 {m('markov1_logloss'):.3f}, mk2 {m('markov2_logloss'):.3f})")
        print(f"  completion {ms('completion_rate'):.2f} vs {ma('completion_rate'):.2f} | cycle {ms('median_cycle_h'):.0f} vs {ma('median_cycle_h'):.0f} h | events {ms('events'):,.0f} vs {ma('events'):,.0f} | active {ms('active_cases'):,.0f} vs {ma('active_cases'):,.0f}")
        print(f"  exceptions {ms('exception_rate'):.2f} vs {ma('exception_rate'):.2f} | handoffs {ms('handoffs_per_active_case'):.3f} vs {ma('handoffs_per_active_case'):.3f} | JSD {m('jsd_activity'):.4f} | rank corr {m('p50_rank_corr'):.2f}")
    out_dir = ctx.runs_dir / "validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{a.tag}.json").write_text(json.dumps({"tag": a.tag, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "scenario": a.scenario,
                                                        "cutoffs": cutoffs, "seeds": seeds, "horizon_days": H, "calibration_sha256": calib.get("sha256"), "runs": out_rows},
                                                       indent=1, default=P._json_default))
    print(f"\nsaved {out_dir / (a.tag + '.json')}")


if __name__ == "__main__":
    main()
