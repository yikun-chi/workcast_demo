"""Build instances/openrouter/reports/report.json from runs/openrouter/evaluation.json, the run summaries and
data/normalized/summary.json. Every number in the report is read from those files; nothing is typed in by hand.

    .venv/bin/python instances/openrouter/reports/build_report.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from orgsim.instances import get_instance  # noqa: E402
from orgsim.worlds.market import results_view  # noqa: E402


def pct(x, d=1):
    return "n/a" if x is None else f"{x:.{d}f}%"


def main() -> None:
    ctx = get_instance("openrouter")
    ev = json.loads((ctx.runs_dir / "evaluation.json").read_text())
    summ = json.loads((ctx.data_normalized / "summary.json").read_text())
    view = results_view(ctx)
    acc, proto, wins = ev["accuracy"], ev["protocol"], ev["windows"]
    labels = ev["comparator_labels"]
    H, n_cut = proto["horizon_weeks"], len(wins)
    n_pred = sum(w["n_apps"] for w in wins)
    ct, cs, md = acc["company_tokens_wape"], acc["company_spend_wape"], acc["company_tokens_mdape"]
    bt = ct["best_baseline"]; bs = cs["best_baseline"]
    short = lambda k: labels[k].split(":")[0]  # noqa: E731
    wins_tok = sum(1 for w in wins if w["company_tokens_wape"]["simulation"] < min(w["company_tokens_wape"][k] for k in labels))
    bv = {b["id"]: b for b in ev["business_validation"]}
    cens = float(np.mean([w["censored_pct"] for w in wins]))
    facts = {f["label"]: f["value"] for f in summ["facts"]}
    mets = {m["id"]: m for m in view["metrics"]}
    alt = view["scenarios"].get("alternative") or {}

    def vs(a: float, b: float) -> str:
        return "lower than" if a < b else "higher than" if a > b else "equal to"

    takeaways = [
        f"Across {n_cut} cutoffs and {n_pred:,} company predictions, the simulation's error in each company's {H}-week tokens was {pct(ct['simulation'])}, "
        f"{vs(ct['simulation'], ct[bt])} the best standard forecast ({short(bt)}, {pct(ct[bt])}).",
        f"The median company's error was {pct(md['simulation'])} for the simulation and {pct(md[md['best_baseline']])} for the best standard forecast.",
        f"Error in each company's {H}-week spend at list prices was {pct(cs['simulation'])} against {pct(cs[bs])} for the best standard forecast.",
        f"The simulation's 90% range contained the actual {H}-week tokens of {pct(acc['coverage90'])} of companies; the standard forecasts give no range.",
        f"For all tokens on OpenRouter over {H} weeks, the simulation's mean absolute error was {bv['market_tokens']['simulation_mae']:.1f} trillion against "
        f"{bv['market_tokens']['baseline_mae'][bv['market_tokens']['best_baseline']]:.1f} trillion for the best standard forecast.",
    ]
    if "coding_spend" in mets:
        v = mets["coding_spend"]["values"]
        takeaways.append(f"Alternative ({alt.get('short_title', '')}): the coding companies' simulated {H}-week spend changes from ${v['baseline']:.2f}M to ${v['alternative']:.2f}M "
                         f"({(v['alternative'] / v['baseline'] - 1) * 100:+.0f}%).")
    sections = [
        {"heading": "What was predicted", "body":
            f"At each of {n_cut} Monday cutoffs from {wins[0]['cutoff']} to {wins[-1]['cutoff']}, the simulation took the {proto['n_apps']} apps with the most tokens in the previous four weeks "
            f"and predicted each one's tokens and spend for the next {H} weeks. Every parameter comes from weeks before the cutoff. After the cutoff the simulation is given only the published "
            f"list prices and the dates new models were listed. {pct(cens)} of company-weeks after a cutoff fall outside OpenRouter's top 200 and are recorded at half the 200th app's volume, "
            f"on both the actual and the predicted side.",
         "charts": ["company_scatter"], "metrics": []},
        {"heading": "Accuracy against standard forecasts", "body":
            "| Measure | Simulation | " + " | ".join(short(k) for k in labels) + " |\n|---|---:|" + "---:|" * len(labels) + "\n" +
            "\n".join(f"| {name} | {pct(acc[key]['simulation'])} | " + " | ".join(pct(acc[key][k]) for k in labels) + " |"
                      for key, name in (("company_tokens_wape", f"Error in each company's {H}-week tokens (token-weighted)"),
                                        ("company_spend_wape", f"Error in each company's {H}-week spend (spend-weighted)"),
                                        ("company_tokens_mdape", "Median company's error"),
                                        ("direction_hit", "Growth or decline called correctly"))) +
            f"\n\nThe simulation had the lowest token error of all four methods at {wins_tok} of {n_cut} cutoffs.",
         "charts": ["error_by_cutoff"], "metrics": []},
        {"heading": "Why the companies are hard to predict", "body":
            f"Many of the leading apps in a given month are one-off jobs (evaluation runs, data pipelines, test agents) that rank for a week or two and disappear. "
            f"The simulation gives each company a persistence class from the weeks before the cutoff and learns from earlier cutoffs how often each class stays ranked. "
            f"Steady products carry most of the volume, and for them the last four weeks remain a strong guide.",
         "charts": [], "metrics": []},
    ]
    if "coding_spend" in mets:
        v = mets["coding_spend"]["values"]; ls = mets["leader_share"]["values"]
        sections.append({"heading": f"Alternative: {alt.get('short_title', '')}", "body":
            f"{alt.get('description', '').strip()} In the simulation the repriced model's share of programming tokens in the final week moves from {ls['baseline']:.1f}% to {ls['alternative']:.1f}%, "
            f"and the coding companies' {H}-week spend at list prices from ${v['baseline']:.2f}M to ${v['alternative']:.2f}M. This is a simulated alternative, not an observed price change.",
            "charts": ["alt_mix"], "metrics": []})
    report = {"title": "AI token demand and spend on OpenRouter", "subtitle": f"{n_pred:,} company predictions, {H} weeks ahead",
              "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "takeaways": takeaways, "sections": sections,
              "charts": [], "metrics": [], "data": {"weeks": facts.get("Weeks of model usage"), "apps": facts.get("Apps ranked in the weekly top 200 at least once")}}
    (ctx.reports_dir / "report.json").write_text(json.dumps(report, indent=1))
    print(f"wrote {ctx.reports_dir / 'report.json'}")


if __name__ == "__main__":
    main()
