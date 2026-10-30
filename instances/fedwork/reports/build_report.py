"""Build instances/fedwork/reports/report.json from runs/fedwork/evaluation.json. Every number is read from the evaluation.

    .venv/bin/python instances/fedwork/reports/build_report.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from orgsim.instances import get_instance  # noqa: E402


def build(ctx) -> dict:
    ev = json.loads((ctx.runs_dir / "evaluation.json").read_text())
    labels = ev["comparator_labels"]
    held = next(w for w in ev["windows"] if w["role"] == "held_out")
    h = ev["accuracy"]["held_out"]["group_month_wape"]; d = ev["accuracy"]["development"]["group_month_wape"]
    series = [k for k in labels if k != "programme"]
    bs = min(series, key=lambda k: h[k])
    s = held["scores"]
    takeaways = [
        f"From {held['months'][0]} to {held['months'][1]}, the simulation's error in each agency's monthly separations was {h['simulation']:.1f}% "
        f"(accuracy {h['accuracy_pct']['simulation']:.1f}%), against {h[bs]:.1f}% for the best series method ({labels[bs]}).",
        f"The {labels['programme'].lower()} that applies the same published effects to whole agencies was at {h['programme']:.1f}%.",
        f"Total separations: actual {s['simulation']['actual_total']:,.0f}, simulation {s['simulation']['predicted_total']:,.0f}, {labels[bs]} {s[bs]['predicted_total']:,.0f}.",
        f"In the development years without a policy change the simulation's error was {d['simulation']:.1f}% against {d[d['best_comparator']]:.1f}% for {labels[d['best_comparator']]}.",
    ]
    alt = (ev.get("scenario_comparison") or [None])[0]
    if alt:
        takeaways.append(f"Alternative (no resignation offer): {alt['total']['alternative']:,.0f} separations instead of {alt['total']['baseline']:,.0f} with the same seeds.")
    rows = "\n".join(f"| {w['cutoff']} | {w['role']} | {w['scores']['simulation']['group_month_wape']:.1f}% | " + " | ".join(f"{w['scores'][k]['group_month_wape']:.1f}%" for k in labels) + " |" for w in ev["windows"])
    table = "| Cutoff | Role | Simulation | " + " | ".join(labels.values()) + " |\n|---|---|---:|" + "---:|" * len(labels) + "\n" + rows
    return {"title": "Federal workforce separations: simulation against OPM's records", "subtitle": "OPM Federal Workforce Data",
            "generated": datetime.now(timezone.utc).isoformat(), "takeaways": takeaways,
            "sections": [{"heading": "Error in each agency's monthly separations, by cutoff", "body": table, "charts": ["monthly_total", "agency_totals"], "metrics": []},
                         {"heading": "How the prediction was made", "body": ev["protocol"]["design"] + " " + ev["protocol"]["freeze_rule"] + "."}],
            "charts": [], "metrics": []}


def main() -> None:
    ctx = get_instance("fedwork")
    (ctx.reports_dir / "report.json").write_text(json.dumps(build(ctx), indent=1))
    print(f"wrote {ctx.reports_dir / 'report.json'}")


if __name__ == "__main__":
    main()
