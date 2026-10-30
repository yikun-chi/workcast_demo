"""Build instances/ctrip/reports/report.json from runs/ctrip/evaluation.json. Every number is read from the evaluation.

    .venv/bin/python instances/ctrip/reports/build_report.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from orgsim.instances import get_instance  # noqa: E402


def fmt(v, unit: str) -> str:
    if v is None:
        return "n/a"
    if unit == "%":
        return f"{v:+.1f}%" if abs(v) < 100 else f"{v:.1f}%"
    if unit == "pp":
        return f"{v:+.1f} pp"
    if unit == "SD":
        return f"{v:+.2f} SD"
    return f"{v:,.1f} {unit}".strip()


def sentence(m: dict, labels: dict) -> str:
    best = m.get("best_comparator")
    beat = "closer than" if m.get("beats_best_comparator") else "further from the actual than"
    return (f"{m['label']}: the simulation predicted {fmt(m['simulated'], m['unit'])}; the experiment measured {fmt(m['actual'], m['unit'])}. "
            f"That is {beat} the best other prediction ({labels.get(best, best)}, {fmt(m['comparators'].get(best), m['unit'])}).")


def build(ctx) -> dict:
    ev = json.loads((ctx.runs_dir / "evaluation.json").read_text())
    labels = ev["comparator_labels"]
    idx = ev["metric_index"]
    heads = [m for m in ev["metrics"] if m["headline"]]
    takeaways = [sentence(m, labels) for m in heads] + [sentence(idx["perf_effect"], labels)]
    for mid in ("calls_home", "attrition_home"):
        m = idx[mid]
        takeaways.append(f"{m['label']}: simulation {fmt(m['simulated'], m['unit'])}, actual {fmt(m['actual'], m['unit'])}, accuracy {m['accuracy_pct']:.1f}%.")
    alt = (ev.get("scenario_comparison") or [{}])[0]
    if alt.get("metrics"):
        c = alt["metrics"]["calls_effect_pct"]; a = alt["metrics"]["attrition_effect_pp"]
        takeaways.append(f"Alternative (two home days): the simulated effect on calls changes from {fmt(c['baseline'], '%')} to {fmt(c['alternative'], '%')}, "
                         f"and on quits from {fmt(a['baseline'], 'pp')} to {fmt(a['alternative'], 'pp')} (matching runs).")
    rows = "\n".join(f"| {m['label']} | {fmt(m['actual'], m['unit'])} | {fmt(m['simulated'], m['unit'])} | " + " | ".join(fmt(m['comparators'].get(k), m['unit']) for k in labels) + " |"
                     for m in ev["metrics"])
    table = "| Measure | Actual | Simulation | " + " | ".join(labels.values()) + " |\n|---|---:|---:|" + "---:|" * len(labels) + "\n" + rows
    sections = [
        {"heading": "Actual outcomes and predictions", "body": table, "charts": ["weekly_calls", "cumulative_attrition"], "metrics": [m["id"] for m in heads]},
        {"heading": "How the prediction was made", "body": ev["protocol"]["design"] + " " + ev["protocol"]["freeze_rule"] + "."},
    ]
    return {"title": "Ctrip work-from-home experiment: simulation against the actual outcome", "subtitle": ev["reference_source"],
            "generated": datetime.now(timezone.utc).isoformat(), "takeaways": takeaways, "sections": sections, "charts": ev.get("charts", []), "metrics": ev["metrics"]}


def main() -> None:
    ctx = get_instance("ctrip")
    (ctx.reports_dir / "report.json").write_text(json.dumps(build(ctx), indent=1))
    print(f"wrote {ctx.reports_dir / 'report.json'}")


if __name__ == "__main__":
    main()
