"""Build instances/trip/reports/report.json (investor-facing) from runs/trip/evaluation.json and the normalized data.

Every number in the report is read from the evaluation output or the ingest outputs; nothing is typed in.
Usage: .venv/bin/python instances/trip/reports/build_report.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from orgsim.instances import get_instance  # noqa: E402
from orgsim.worlds.workforce import attrition_comparators  # noqa: E402


def _m(ev: dict, mid: str) -> dict:
    return next((m for m in ev["metrics"] if m["id"] == mid), {})


def _sc(ev: dict, sid: str) -> dict:
    return next((r for r in ev.get("paired_comparison", ev.get("scenario_comparison", [])) if r["scenario"] == sid), {})


def sgn(x, nd=1, unit=""):
    if x is None:
        return "n/a"
    return f"{x:+.{nd}f}{unit}"


def fmt(x, nd=1, unit=""):
    return "n/a" if x is None else f"{x:.{nd}f}{unit}"


def main() -> None:
    ctx = get_instance("trip")
    ev = json.loads((ctx.runs_dir / "evaluation.json").read_text())
    summ = json.loads((ctx.data_normalized / "summary.json").read_text())
    pri = json.loads((ctx.data_normalized / "reference_outcomes.json").read_text())
    bind = ctx.yaml("ontology/bindings.yaml")
    priors = ctx.yaml("calibration/priors.yaml").get("parameters", {})
    comp = attrition_comparators(ctx)

    att, sat, nm, mg = _m(ev, "attrition_itt_pp"), _m(ev, "work_satisfaction_itt"), _m(ev, "attrition_itt_nonmanagers_pp"), _m(ev, "attrition_itt_managers_pp")
    perf, tk, wlb = _m(ev, "performance_2021H2_itt"), _m(ev, "takeup_treatment"), _m(ev, "work_life_balance_itt")
    ac, at = _m(ev, "attrition_control_pct"), _m(ev, "attrition_treatment_pct")
    far, near = _m(ev, "attrition_itt_long_commute_pp"), _m(ev, "attrition_itt_short_commute_pp")
    fem, male = _m(ev, "attrition_itt_female_pp"), _m(ev, "attrition_itt_male_pp")
    base, all_ = _sc(ev, "baseline"), _sc(ev, "hybrid_for_all")
    n_seeds = ev["protocol"]["seeds"]
    ctrl_act = pri["attrition_pct"]["all"]["0"]; treat_act = pri["attrition_pct"]["all"]["1"]
    rel = 100 * att["simulated"] / ac["simulated"] if ac.get("simulated") else None
    rel_act = 100 * att["actual"] / ctrl_act
    n_act = len([m for m in ev["metrics"] if m.get("primary")])
    n_cov = len([m for m in ev["metrics"] if m.get("primary") and m.get("covered_90")])
    # direction is scored only where the experiment itself detected an effect (|actual| > 1.96 SE); null effects have no direction to get right
    sig = [m for m in ev["metrics"] if m.get("primary") and m.get("actual_se") and abs(m["actual"]) > 1.96 * m["actual_se"]]
    n_sign = len([m for m in sig if m.get("sign_correct")])
    n_sign_total = len(sig)
    n_ci = len([m for m in ev["metrics"] if m.get("primary") and m.get("within_trial_ci95")])
    n_ci_total = len([m for m in ev["metrics"] if m.get("primary") and m.get("within_trial_ci95") is not None])
    perf_ci = perf.get("trial_ci95") or [None, None]
    headcount = summ["facts"][0]["value"]
    activities = len(bind.get("activities", []))
    dwas = len({d for a in bind.get("activities", []) for d in a.get("dwa_ids", [])})
    saved_quits = None
    if base.get("quits_total") is not None and all_.get("quits_total") is not None:
        saved_quits = base["quits_total"] - all_["quits_total"]

    takeaways = [
        f"The simulation predicts a {abs(att['simulated']):.2f} percentage-point reduction in six-month attrition from offering two home days a week. The actual reduction was {abs(att['actual']):.2f} points, comparing the hybrid and office-only groups.",
        f"Six-month attrition: the simulation predicts {fmt(ac['simulated'])}% for office-only employees and {fmt(at['simulated'])}% for employees offered hybrid work. Actual outcomes were {fmt(ctrl_act)}% and {fmt(treat_act)}%, respectively. Both simulated rates are too high.",
        f"The simulation predicts work satisfaction increasing by {sat['simulated']:+.2f} points on the 0-10 scale; the actual increase was {sat['actual']:+.2f}. Work-life balance: simulation prediction {wlb['simulated']:+.2f}, actual outcome {wlb['actual']:+.2f}.",
        f"The retention gain concentrates among non-managers: prediction {nm['simulated']:+.1f} points for non-managers and {mg['simulated']:+.1f} for managers; the experiment measured {nm['actual']:+.1f} and {mg['actual']:+.1f}.",
        f"For performance grades, the simulation predicts a change of {perf['simulated']:+.2f} points; the actual change was {perf['actual']:+.2f}. Both estimates are small.",
        f"Simulated employees used {tk['simulated'] * 100:.0f}% of their eligible WFH days; the experiment recorded {tk['actual'] * 100:.0f}%.",
        "This is a retrospective comparison with published outcomes. Earlier model choices had already been compared with those results; the close overall impact does not establish accuracy on new companies or policies.",
    ]
    if saved_quits is not None and base.get("attrition_pct_all") is not None:
        takeaways.append(f"Extending the offer to everyone takes company-wide six-month attrition from {fmt(base['attrition_pct_all'])}% (the experiment as run, simulated) to {fmt(all_['attrition_pct_all'])}%, about {saved_quits:.0f} fewer resignations among {headcount} employees.")

    sections = [
        {"heading": "What was simulated", "charts": ["cumulative_attrition", "takeup_series"], "metrics": ["attrition_control_pct", "attrition_treatment_pct", "takeup_treatment"],
         "body": (f"{headcount} employees of Trip.com's Airfare and IT divisions, rebuilt one by one from the experiment's real pretreatment data (age, gender, tenure, graduate degree, children, commute time, "
                  f"volunteer status, prior performance grade, manager flag) and assigned to the arms exactly as the birthday lottery did: {summ['facts'][1]['value']} office-only / offered hybrid work. "
                  f"Each employee works an hourly schedule from 9 Aug 2021 to 23 Jan 2022, performing O*NET-bound activities of their role, commuting on office days and, in the group offered hybrid work, deciding every Wednesday and Friday "
                  f"whether to work from home. Latent commute burden, work-life balance, job satisfaction and attachment update weekly; a weekly quit hazard turns those states into resignations. "
                  f"The endline survey (21 Jan 2022) and the 2021H2 performance review are simulated as the company recorded them. The prediction was run over {n_seeds} seeds with every behavioral parameter drawn from its prior range, "
                  f"so the intervals reflect prior uncertainty and simulated outcome variation. This is a retrospective evaluation, not an untouched prospective test.")},
        {"heading": "What the prediction got right", "charts": ["itt_forecast_vs_actual", "attrition_by_arm", "satisfaction_by_arm"], "metrics": ["attrition_itt_pp", "work_satisfaction_itt", "work_life_balance_itt", "performance_2021H2_itt"],
         "body": (f"Attrition: prediction {att['simulated']:+.2f} points (90% interval {att['interval'][0]:+.2f} to {att['interval'][1]:+.2f}), experiment {att['actual']:+.2f}. "
                  f"Work satisfaction: prediction {sat['simulated']:+.2f}, experiment {sat['actual']:+.2f}. Work-life balance: prediction {wlb['simulated']:+.2f}, experiment {wlb['actual']:+.2f}. "
                  f"Performance grade: prediction {perf['simulated']:+.2f}, experiment {perf['actual']:+.2f} (experiment 95% CI {sgn(perf_ci[0], 2)} to {sgn(perf_ci[1], 2)}; the prediction {'sits inside' if perf.get('within_trial_ci95') else 'sits outside'} it). Take-up: prediction {tk['simulated'] * 100:.0f}% of eligible days, experiment {tk['actual'] * 100:.0f}%.\n\n"
                  f"The no-change prediction assumes zero policy impact. The simple two-day calculation predicts {att['baselines']['proportional_days']:+.2f} percentage points, "
                  f"with an error of {att['baseline_errors']['proportional_days']:.2f} points. This comparison applies only to overall attrition.")},
        {"heading": "Where effects concentrate", "charts": ["manager_contrast"], "metrics": ["attrition_itt_nonmanagers_pp", "attrition_itt_managers_pp", "attrition_itt_long_commute_pp", "attrition_itt_short_commute_pp", "attrition_itt_female_pp", "attrition_itt_male_pp"],
         "body": (f"Managers versus non-managers. Non-managers: prediction {nm['simulated']:+.1f} points, experiment {nm['actual']:+.1f}. Managers: prediction {mg['simulated']:+.1f}, experiment {mg['actual']:+.1f}. "
                  f"The model produces this split from two independent facts: managers have lower baseline quit rates (older, longer tenure, management multiplier) and schedule-control gains are smaller where baseline autonomy is already high.\n\n"
                  f"Commute. Employees with a two-way commute over 90 minutes: prediction {far['simulated']:+.1f} points, experiment {far['actual']:+.1f}; up to 90 minutes: prediction {near['simulated']:+.1f}, experiment {near['actual']:+.1f}. "
                  f"Long commuters both take up WFH more and gain more from each day at home.\n\n"
                  f"Gender. Women: prediction {fem['simulated']:+.1f} points, experiment {fem['actual']:+.1f}; men: prediction {male['simulated']:+.1f}, experiment {male['actual']:+.1f}. "
                  f"Group differences arise from observed employee information from before the policy. Gender is excluded from behavior, commute imputation and synthetic role assignment.")},
        {"heading": "What the policy variants show", "charts": ["scenario_bars", "scenario_satisfaction"], "metrics": [],
         "body": (f"Run on the same workforce with the same priors ({base.get('seeds')} matching simulation runs; attrition estimated by summing weekly hazards while employees remain at risk):\n\n"
                  f"- The experiment as run: {fmt(base.get('attrition_pct_control'))}% office-only, {fmt(base.get('attrition_pct_treatment'))}% offered hybrid work, {fmt(base.get('attrition_pct_all'))}% overall.\n"
                  f"- Hybrid for all: {fmt(all_.get('attrition_pct_all'))}% company-wide, satisfaction {fmt(all_.get('satisfaction_treatment'), 2)}, take-up {fmt((all_.get('take_up_treatment') or 0) * 100, 0)}%.\n"
                  f"Trip.com extended hybrid work to the whole company after the experiment; the 'hybrid for all' row is the simulation's prediction of that decision.")},
        {"heading": "How it works", "charts": [], "metrics": [],
         "body": (f"- Digital twins from real people: every simulated employee carries the real pretreatment covariate vector of one experiment employee, so the workforce has the experiment's exact joint distribution of commute, children, tenure, gender, education and role.\n"
                  f"- O*NET-bound activities: {len(bind.get('roles', []))} roles bound to O*NET-SOC occupations, {activities} activities mapped to {dwas} detailed work activities, performed hour by hour and recorded in the run trace.\n"
                  f"- Latent states: commute burden, work-life balance, job satisfaction and attachment evolve weekly from the policy exposure each person actually experiences, with weak sentiment spillover inside teams.\n"
                  f"- Swappable policies: every WFH take-up and every stay-or-quit choice goes through a seat policy that picks among options the simulation supplies; a seat can be a transparent rule or a language model, by configuration.\n"
                  f"- Digital twins with a trait layer: each employee carries fixed traits computed once per run (baseline satisfaction, baseline quit hazard, a WFH-preference trait that drives both how often they take a WFH day and how much each day is worth to them), a text profile built from those traits, and weekly latent states with inertia. The same twin feeds every seat policy, rule or language model.\n"
                  f"- Team comparison: employees who are not offered WFH while their teammates are lose satisfaction in proportion to the share of teammates offered; arms were assigned within teams by birthday, so the comparison was salient.\n"
                  f"- Independent priors: {len(priors)} behavioral parameters, each with a central value, a range and a cited source (the 2015 Ctrip full-time WFH experiment, turnover and commuting meta-analyses, the Survey of Working Arrangements and Attitudes, willingness-to-pay studies of flexible work, peer-comparison studies, industry turnover rates). The simulation reads neither arm's experiment outcomes. The inherited prior specification has been compared with this experiment before, so the results are retrospective, not a prospective validation.")},
    ]
    sections.insert(1, {"heading": "Before the policy and the other predictions", "body": (
        f"The [published study]({comp['history']['source_url']}) reports {comp['no_change_pct']:.1f}% attrition in the Airfare and IT divisions during the preceding six months. "
        "This is a division-level aggregate; the downloadable data does not supply an individual departure history or the earlier denominator. "
        "It provides historical context, while policy impact compares the two groups during the same later period.\n\n"
        f"No change predicts {comp['no_change_pct']:.1f}% attrition. The [earlier Ctrip study]({comp['study']['source_url']}) found about a "
        f"{100*comp['study']['relative_attrition_reduction']:.0f}% relative reduction with {comp['study']['home_days_per_week']} home days a week among volunteer call-center staff. "
        f"The simple two-day calculation assumes a proportional benefit: {comp['no_change_pct']:.1f}% × (1 − "
        f"{100*comp['study']['relative_attrition_reduction']:.0f}% × {comp['home_days']}/{comp['study']['home_days_per_week']}) = {comp['proportional_days_pct']:.2f}%. "
        "Scaling between different jobs, periods and schedules is an assumption. No after-policy outcomes enter either calculation. "
        "The simulation still uses its existing external turnover assumptions; the historical rate has not been used to refit those predictions.")})
    report = {
        "title": "Hybrid work at Trip.com: simulation prediction and actual outcome",
        "subtitle": f"{headcount} employees, six months, two WFH days a week offered to half of them. Simulation from pretreatment inputs and assumptions from earlier research; compared with Bloom, Han & Liang (Nature 2024).",
        "generated": datetime.now(timezone.utc).isoformat(),
        "takeaways": takeaways,
        "sections": sections,
        "charts": ev["charts"],
        "metrics": ev["metrics"],
        "scenario_comparison": ev.get("paired_comparison", ev.get("scenario_comparison", [])),
        "sources": {"experiment": pri.get("source", ""), "priors": "instances/trip/calibration/priors.yaml", "evaluation": "runs/trip/evaluation.json"},
    }
    out = ctx.reports_dir / "report.json"
    out.write_text(json.dumps(report, indent=1))
    print(f"wrote {out}")
    for t in takeaways:
        print(" -", t)


if __name__ == "__main__":
    main()
