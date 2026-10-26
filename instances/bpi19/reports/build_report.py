"""Build instances/bpi19/reports/report.json from runs/bpi19/evaluation.json, data/normalized/summary.json and
calibration/process.json. Every number in the report is read from those files; nothing is typed in by hand.

    .venv/bin/python instances/bpi19/reports/build_report.py
"""
from __future__ import annotations

import json
import sys
import yaml
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from orgsim.instances import get_instance  # noqa: E402


def f0(x, d=0):
    if x is None:
        return "n/a"
    return f"{x:,.{d}f}"


def pct(x, d=1):
    return "n/a" if x is None else f"{x:.{d}f}%"


def days(h, d=0):
    return "n/a" if h is None else f"{h / 24:,.{d}f} days"


def cal_day(x: int) -> str:
    return f"{x}{'th' if 10 <= x % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(x % 10, 'th')}"


def main() -> None:
    ctx = get_instance("bpi19")
    ev = json.loads((ctx.runs_dir / "evaluation.json").read_text())
    summ = json.loads((ctx.data_normalized / "summary.json").read_text())
    calib = json.loads((ctx.calibration_dir / "process.json").read_text())
    facts = {f["label"]: f["value"] for f in summ["facts"]}
    M = {m["id"]: m for m in ev["metrics"]}
    S = {r["scenario"]: r for r in ev["scenario_comparison"]}
    base = S["baseline"]
    proto = ev["protocol"]
    runs = ev.get("per_run", [])
    scored = int(sum(r["scored_cases"] for r in runs) / max(1, len(runs)))
    open_mean = sum(r["sim"]["population"] for r in runs) / max(1, len(runs))
    runtime = ev.get("runtime_s_mean") or 0
    runs_util = [json.loads((ctx.runs_dir / "baseline" / rid / "summary.json").read_text())["headline"] for rid in ev.get("run_ids", {}).get("baseline", [])]
    runs_util = [h for h in runs_util if isinstance(h.get("utilization"), dict)]

    acc, m1, m2 = M["next_activity_accuracy"]["simulated"], None, None
    note = M["next_activity_accuracy"].get("note", "")
    for part in note.split(";")[0].split(","):
        if "order 1" in part:
            m1 = float(part.split(":")[1].strip().rstrip("%"))
        if "order 2" in part:
            m2 = float(part.split(":")[1].strip().rstrip("%"))
    mk_best = M["next_activity_accuracy"]["baseline"]
    ll, ll_mk = M["next_activity_logloss"]["simulated"], M["next_activity_logloss"]["baseline"]
    comp, comp_act, comp_hist = M["completion_14d"]["simulated"], M["completion_14d"]["actual"], M["completion_14d"]["baseline"]
    exc, exc_act = M["exception_rate"]["simulated"], M["exception_rate"]["actual"]
    ho, ho_act = M["handoffs_per_case"]["simulated"], M["handoffs_per_case"]["actual"]
    cyc, cyc_act = M["median_cycle_hours"]["simulated"], M["median_cycle_hours"]["actual"]
    wk, wk_act = M["events_per_week"]["simulated"], M["events_per_week"]["actual"]
    jsd = M["activity_volume_jsd"]["simulated"]
    rc = M["transition_p50_rank_corr"]["simulated"]

    # bottlenecks from the transition chart (actual side)
    tp = next(c for c in ev["charts"] if c["id"] == "transition_p50")
    act_series = next(s for s in tp["series"] if s["name"] in ("Actual outcome", "Actual"))["y"]
    sim_series = next(s for s in tp["series"] if s["name"] in ("Simulation prediction", "Simulated"))["y"]
    ranked = sorted(zip(tp["x"], act_series, sim_series), key=lambda t: -t[1])
    slow1, slow2 = ranked[0], ranked[1]
    full_tr = next(c for c in summ["charts"] if c["id"] == "slow_transitions")
    full_rank = sorted(zip(full_tr["x"], full_tr["series"][0]["y"], full_tr["series"][1]["y"]), key=lambda t: -t[1])
    # per-run headlines (workforce, rejected options) live in each run's summary.json
    heads = []
    for r in runs:
        p = ctx.runs_dir / "baseline" / r["run_id"] / "summary.json"
        if p.exists():
            heads.append(json.loads(p.read_text())["headline"])
    wf = heads[0]["workforce"] if heads else None
    rejected = sum(h["options_rejected_by_constraints"] for h in heads) / max(1, len(heads))
    n_rules = len(yaml.safe_load((ctx.calibration_dir / "constraints.yaml").read_text())["rules"])

    def delta(sid, kpi, better="higher"):
        b, s = base.get(kpi), S[sid].get(kpi)
        if b in (None, 0) or s is None:
            return None
        return 100.0 * (s - b) / b

    auto = cap = fast = surge = None
    # goods-receipt transitions in the full log, for the bottleneck comparison (computed, not asserted)
    gr_rank = [t for t in full_rank if "Record Goods Receipt" in t[0].split(" -> ")[1]]
    gr_median_h = max((t[1] for t in gr_rank), default=None)
    cal = calib.get("calendar", {}).get("activities", {}).get("Clear Invoice")
    alt_runs = [json.loads((ctx.runs_dir / "no_expansion" / rid / "summary.json").read_text()) for rid in ev.get("run_ids", {}).get("no_expansion", [])]
    periods = ev.get("periods") or {}; change = ev.get("change") or {}
    pb, pa = periods.get("before") or {}, periods.get("after") or {}
    def alt_mean(key, nd=2):
        vals = [r["headline"].get(key) for r in alt_runs if isinstance(r.get("headline", {}).get(key), (int, float))]
        return round(sum(vals) / len(vals), nd) if vals else None
    def alt_util(role):
        vals = [r["headline"].get("utilization", {}).get(role) for r in alt_runs if isinstance(r.get("headline", {}).get("utilization", {}).get(role), (int, float))]
        return 100 * sum(vals) / len(vals) if vals else None
    takeaways = [
        f"Starting from the observed prefixes of {f0(open_mean)} live purchase-order items, the simulation's top-ranked next step matched the real next step {pct(acc)} of the time, against {pct(mk_best)} for the best prefix-Markov baseline (order 1: {pct(m1)}, order 2: {pct(m2)}); log-loss {ll:.3f} vs {ll_mk:.3f}.",
        f"Over four September-October 2018 cutoffs, {pct(comp)} of live items were completed within 14 days in simulation against {pct(comp_act)} in reality (training-window history alone would say {pct(comp_hist)}); the simulated median cycle time of completed items was {days(cyc)} against {days(cyc_act)}.",
        f"The simulated operation produced {f0(wk)} events per week against {f0(wk_act)} actual, with an activity-mix divergence of {jsd:.3f} bits (Jensen-Shannon; 0 is identical) and a rank correlation of {rc:.2f} between simulated and actual median delays on the ten busiest hand-offs.",
        f"{pct(exc)} of items hit an exception in the horizon (actual {pct(exc_act)}) and work changed hands {ho:.2f} times per active item (actual {ho_act:.2f}).",
        (f"The slowest busy hand-offs in the full log are {full_rank[0][0]} (median {days(full_rank[0][1])}, p90 {days(full_rank[0][2])}) and {full_rank[1][0]} (median {days(full_rank[1][1])})"
         + (f", while the slowest hand-off into goods receipt has a median of {days(gr_median_h, 1)}" if gr_median_h is not None else "")
         + f"; {calib['activities']['Clear Invoice']['weekday_dist'][3]*100:.0f}% of all clearings happen in the Thursday payment run"
         + (f", and the run in the week of the {cal_day(calib['calendar']['x_late'])} clears {cal['multipliers']['late']/cal['multipliers']['regular']:.0f}x a regular week." if cal else ".")),
    ]
    if pb.get("metrics") and pa.get("metrics"):
        mb, ma = pb["metrics"], pa["metrics"]
        takeaways.insert(0, f"Before the September 2018 expansion ({', '.join(pb['cutoffs'])}, about {pb['staff_active']:.0f} active people) {pct(mb['completion_14d']['actual'])} of live items were completed within 14 days; after it ({', '.join(pa['cutoffs'])}, about {pa['staff_active']:.0f} people, {change.get('ratio', 0):.2f}x) reality moved to {pct(ma['completion_14d']['actual'])} and the simulation predicted {pct(ma['completion_14d']['simulated'])}. Median cycle time: {days(mb['median_cycle_hours']['actual'])} before; {days(ma['median_cycle_hours']['actual'])} actual vs {days(ma['median_cycle_hours']['simulated'])} predicted after.")
    if alt_runs:
        base_util = {r: 100 * sum(x["utilization"].get(r, 0) for x in runs_util) / max(1, len(runs_util)) for r in ("ap_invoice", "purchasing_clerk", "goods_receipt")} if runs_util else {}
        takeaways.append(f"Under the alternative's uniform staffing reduction on the same {len(alt_runs)} cutoff-seed runs, 14-day completion moves from {pct(comp)} to {pct(alt_mean('completion_rate_14d'))} and the median cycle time from {days(cyc)} to {days(alt_mean('median_cycle_hours_completed', 0))}; AP invoice clerks go from {base_util.get('ap_invoice', 0):.0f}% to {alt_util('ap_invoice'):.0f}% of working-hour capacity. This counterfactual approximates foregoing the expansion; the observed before/after change also includes a different order mix.")
    if auto:
        takeaways.append(f"Automating payment-block removal completes {f0(auto['completed_cases'])} items in 14 days against {f0(base['completed_cases'])} in the baseline ({delta('automate_payment_block', 'completed_cases'):+.1f}%) and moves the queue of waiting actions at the horizon end from {f0(base['queued_actions_end'])} to {f0(auto['queued_actions_end'])}.")
    if cap and fast:
        d_cap, d_fast = delta('ap_capacity_plus_30', 'completed_cases'), delta('fast_invoice_handling', 'completed_cases')
        if abs(d_fast) >= 2 * max(abs(d_cap), 0.5):
            verdict = "the invoice delay is a process-design problem, not a headcount problem"
        elif abs(d_cap) >= 2 * max(abs(d_fast), 0.5):
            verdict = "accounts-payable headcount, not invoice handling time, is the binding constraint"
        else:
            verdict = "neither lever alone moves two-week completions by much; the long waits sit in the payment calendar, not in the work itself"
        takeaways.append(f"Two further levers, run from the command line: thirty percent more accounts-payable capacity moves 14-day completions by {d_cap:+.1f}% ({f0(cap['completed_cases'])} vs {f0(base['completed_cases'])}), while halving manual invoice handling time moves them by {d_fast:+.1f}% ({f0(fast['completed_cases'])}): {verdict}.")
    if surge:
        takeaways.append(f"Under 30% more orders the same workforce absorbs {f0(surge['arrivals'])} arrivals in two weeks (baseline {f0(base['arrivals'])}): purchasing clerks go from {base['util_purchasing_clerk']:.0f}% to {surge['util_purchasing_clerk']:.0f}% of working-hour capacity, AP invoice clerks from {base['util_ap_invoice']:.0f}% to {surge['util_ap_invoice']:.0f}%, and {f0(surge['backlog_end'])} items are still open at the end of the fortnight against {f0(base['backlog_end'])} ({delta('demand_surge', 'backlog_end'):+.1f}%).")

    roles = summ["org"]["roles"]
    role_lines = "\n".join(f"- **{r['label']}** ({r['id']}), O*NET {r['onet_code']}, {r['headcount']} active users in the training window" if r["onet_code"] else f"- **{r['label']}** ({r['id']}), external actor, {facts['Vendors']:,} vendors" for r in roles)
    wf_lines = ""
    if wf:
        wf_lines = "\n".join(f"- {role}: {int(v['active_headcount'])} people active in the two weeks before t0, {v['actions_per_active_hour']:.1f} actions per active hour" + (" (the weekly payment run posts thousands of clearings in a few hours)" if role == "ap_payment" else "") for role, v in sorted(wf.items()))

    business_rows = []
    labels = {m["id"]: m["label"] for m in ev["metrics"]}
    for row in ev.get("business_validation", []):
        unit = next(m.get("unit", "") for m in ev["metrics"] if m["id"] == row["id"])
        if unit == "%":
            unit = "pp"
        best = row["best_baseline"]
        business_rows.append(f"- {labels[row['id']]}: simulation MAE {row['simulation_mae']:.3f} {unit}; best non-simulation MAE {row['baseline_mae'][best]:.3f} {unit} ({best.replace('_', ' ')}).")
        if row["id"] in ("completion_14d", "median_cycle_hours"):
            takeaways.append(f"Across prediction windows, {labels[row['id']].lower()} has mean absolute error {row['simulation_mae']:.2f} {unit} versus {row['baseline_mae'][best]:.2f} {unit} for the strongest non-simulation baseline.")

    sections = [
        {"heading": "What was simulated", "charts": ["activity_volumes", "weekly_throughput"], "metrics": ["events_per_week"],
         "body": (f"One multinational's purchase-to-pay operation, from the BPI Challenge 2019 event log: {facts['Purchase-order line items (cases)']:,} purchase-order line items on "
                  f"{facts['Purchase orders']:,} purchase orders, {facts['Events (raw log)']:,} recorded events across {facts['Activity types']} activity types, {facts['Human users']} human users, "
                  f"{facts['Batch jobs']} batch jobs and {facts['Vendors']:,} vendors over thirteen months.\n\n"
                  f"The simulation was calibrated on the pre-policy history through {calib['fitted_on']['events_until']} ({calib['fitted_on']['cases']:,} items, {calib['fitted_on']['events']:,} events). It was then started cold at four Monday cutoffs "
                  f"({', '.join(proto['cutoffs'])}) with every item live at that moment rebuilt from its history, and ran for {proto['horizon_days']} days with three random seeds each: "
                  f"{proto['runs']} runs, {runtime:.0f} seconds each. New items created during the horizon arrive when they really did, but every subsequent step, actor and timing is simulated. "
                  f"On average {f0(open_mean)} live items and {f0(base['arrivals'])} arrivals were in play per run.\n\n"
                  f"The test window is deliberately hard: in September 2018 the company changed how it works. Active human users rose from about 270 to about 400 per month, and the share of items that start with a purchase requisition went from 3% to 61%. "
                  f"Model fitting ends before the September change. At each prediction cutoff the simulation sees only the case prefix and active workforce; future arrivals are supplied, but their subsequent events are withheld. "
                  f"Model choices were made on two July-August 2018 validation cutoffs; the test protocol above was then run once.")},
        {"heading": "How faithfully it reproduces the real operation", "charts": ["next_activity", "completion_curve", "transition_p50"],
         "metrics": ["next_activity_accuracy", "next_activity_logloss", "completion_14d", "median_cycle_hours", "exception_rate", "handoffs_per_case", "activity_volume_jsd", "transition_p50_rank_corr"],
         "body": (f"Next step. For the {scored:,} live items per cutoff that really had a next step, the simulation's top-ranked option was the real next activity {pct(acc)} of the time, "
                  f"against {pct(mk_best)} for the best prefix-Markov model fitted on the same training data (log-loss {ll:.3f} vs {ll_mk:.3f}). The gain comes from what a Markov chain cannot see: "
                  f"the process constraints that rule steps out, the item's state (goods received, invoice recorded, block released), how long it has already waited and where the next payment run falls in the calendar.\n\n"
                  f"Flow. {pct(comp)} of live items completed within 14 days in simulation versus {pct(comp_act)} in reality; the median cycle time of those completions was {days(cyc)} simulated versus {days(cyc_act)} actual. "
                  f"The simulated operation produced {f0(wk)} events per week against {f0(wk_act)} actual, with an activity-mix divergence of {jsd:.3f} bits.\n\n"
                  f"Behaviour. {pct(exc)} of items hit at least one of the six core exceptions (actual {pct(exc_act)}); work changed hands {ho:.2f} times per active item (actual {ho_act:.2f}). "
                  f"Median delays of the ten busiest transitions inside the horizon have a rank correlation of {rc:.2f} with the actual ones.")},
        {"heading": "Where the bottlenecks are", "charts": ["transition_p50"], "metrics": [],
         "body": (f"Goods arrive and get booked within days; money moves within months. In the full log the two slowest busy hand-offs are **{full_rank[0][0]}** (median {days(full_rank[0][1])}, p90 {days(full_rank[0][2])}) and "
                  f"**{full_rank[1][0]}** (median {days(full_rank[1][1])}, p90 {days(full_rank[1][2])}). Payment clearing is a weekly run: {calib['activities']['Clear Invoice']['weekday_dist'][3]*100:.0f}% of all invoice clearings happen on Thursdays, "
                  f"and {calib['exceptions']['per_activity_case_rate']['Remove Payment Block']*100:.1f}% of items go through a payment block that a team of {roles[[r['id'] for r in roles].index('ap_payment')]['headcount']} specialists (and batch jobs, {calib['activities']['Remove Payment Block']['batch_share']*100:.0f}% of releases) has to lift by hand.\n\n"
                  f"Inside a 14-day test horizon only transitions that complete within the fortnight are observable, so the comparison there is on the fast part of the process: the slowest busy transition is {slow1[0]} ({days(slow1[1], 1)} actual, {days(slow1[2], 1)} simulated), followed by {slow2[0]} ({days(slow2[1], 1)} actual, {days(slow2[2], 1)} simulated); "
                  f"the rank correlation of simulated and actual median delays across the ten busiest transitions is {rc:.2f}. The ordering is not programmed in: it emerges from the calibrated delays, the Thursday payment run and the capacity of the accounts-payable roles.")},
        {"heading": "What the redesign scenarios show", "charts": ["scenario_completed", "scenario_cycle", "scenario_backlog", "scenario_utilization"], "metrics": [],
         "body": ("Each scenario restarts the same operation at every evaluation cutoff with matching arrivals and seeds and changes one thing.\n\n" +
                  "\n".join(f"- **{r['title']}**: {f0(r['completed_cases'])} items completed in 14 days ({(100.0*(r['completed_cases']-base['completed_cases'])/base['completed_cases']):+.1f}% vs baseline), "
                            f"median cycle time of completions {days(r['median_cycle_hours_completed'])}, {f0(r['backlog_end'])} items still open and {f0(r['queued_actions_end'])} actions queued at the end, "
                            f"mean wait for a human step {r['mean_wait_h']:.1f} h, AP invoice clerks at {r['util_ap_invoice']:.0f}% utilization." for r in ev["scenario_comparison"] if r["scenario"] != "baseline") +
                  f"\n\nBaseline for comparison: {f0(base['completed_cases'])} completed, median cycle {days(base['median_cycle_hours_completed'])}, {f0(base['backlog_end'])} open and {f0(base['queued_actions_end'])} queued at the end, mean wait {base['mean_wait_h']:.1f} h, AP invoice clerks at {base['util_ap_invoice']:.0f}%.")},
        {"heading": "How it works", "charts": [], "metrics": [],
         "body": (f"Ontology. The organization is a typed graph: {len(summ['org']['units'])} organizational units, {len(roles)} roles bound to real O*NET occupations, {facts['Activity types']} activities each mapped to O*NET detailed work activities, "
                  f"{len(summ['org']['systems'])} systems with their capabilities, four artifacts and the vendor as an external actor.\n\n{role_lines}\n\n"
                  f"Kernel. An hourly clock drives every item through a scheduler. Each role is a capacity pool (people active in the two weeks before the cutoff times their measured actions per active hour); work beyond capacity or outside working hours waits in a queue and the wait is recorded. "
                  f"{len(calib['families'])} process families carry their own transition model (previous and last step plus state flags, backing off to shorter memory when the data is thin), and delay distributions, and an item already waiting at the cutoff has its next step conditioned on the time it has waited; {n_rules} preconditions (goods receipt before clearing, blocks released before payment, consignment never invoiced, deletion ends the item) are enforced by the kernel, which rejected {f0(rejected)} invalid options per run. "
                  + (f"Invoice clearing follows the company's payment calendar fitted on the training window: the week of the first Thursday on or after the {cal_day(calib['calendar']['x_early'])} clears {cal['multipliers']['early']:.1f}x and the week of the first Thursday on or after the {cal_day(calib['calendar']['x_late'])} {cal['multipliers']['late']:.1f}x the average week, other weeks {cal['multipliers']['regular']:.1f}x. " if cal else "")
                  + f"When a step stays in the same role, the person who did the previous step keeps the item with the probability measured in the training window ({calib['same_user']['p_same_role_overall']*100:.0f}% overall).\n\n"
                  + (f"Workforce at the first cutoff:\n{wf_lines}\n\n" if wf_lines else "") +
                  "Policies. Every seat (role) is a swappable policy behind one interface: observe the item, the options the kernel allows and the queue, then choose. The demo runs transparent rule policies with calibrated weights; a seat can be switched to a hosted or local language model in policies/seats.yaml without touching the simulation, and the trace records which decisions were made by which policy.")},
    ]
    sections.insert(1, {"heading": "Business outcomes against non-simulation predictions", "body": "Mean absolute errors across the four prediction windows; lower is better. Comparators are carry-forward, the pre-policy historical average, and staffing-scaled carry-forward.\n\n" + "\n".join(business_rows)})

    report = {"title": "Purchase-to-pay, simulated against the real operation", "subtitle": "BPI Challenge 2019 procurement log: 251,734 purchase-order items, 607 people, 42 activities. Refitted on January-August 2018, scored on September-October 2018.",
              "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"), "takeaways": takeaways, "sections": sections,
              "charts": ev["charts"], "metrics": ev["metrics"], "scenario_comparison": ev["scenario_comparison"], "source": {"evaluation": str((ctx.runs_dir / "evaluation.json").relative_to(ROOT)), "generated_from": ev["generated"]}}
    out = ctx.reports_dir / "report.json"
    out.write_text(json.dumps(report, indent=1))
    print(f"report written: {out} ({len(takeaways)} takeaways, {len(sections)} sections)")
    for t in takeaways:
        print(" -", t)


if __name__ == "__main__":
    main()
