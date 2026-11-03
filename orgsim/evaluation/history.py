"""Inspectable saved-run projections. No model calls, interpolated states or reruns."""
from __future__ import annotations

import json
import numpy as np
import pandas as pd

from ..store import list_runs
from .presentation import presented_scenarios


def saved_interviews(ctx):
    path = ctx.runs_dir / "insights.json"
    return json.loads(path.read_text()) if path.exists() else {}


def scenario_catalog(ctx):
    interviews = saved_interviews(ctx)
    blocks = {b.get("scenario"): b for b in interviews.get("scenarios", {}).values() if isinstance(b, dict)}
    runs = [r for r in list_runs(ctx.id) if r["complete"]]
    out = []
    for scenario in presented_scenarios(ctx):
        if scenario["role"] == "other":
            continue
        candidates = [r for r in runs if r["scenario"] == scenario["id"]]
        interview = blocks.get(scenario["id"], {})
        selected = next((r for r in candidates if r["run_id"] == interview.get("run_id")), candidates[0] if candidates else None)
        run = {k: selected[k] for k in ("scenario", "run_id", "complete", "summary")} if selected else None
        # Catalogs should remain small; large arrays are loaded in the detail view.
        if run:
            run["summary"] = {k: v for k, v in run["summary"].items() if k != "headline"}
        out.append({"scenario": scenario, "run": run, "runs_available": len(candidates),
                    "interviews": interview if selected and selected["run_id"] == interview.get("run_id") else None,
                    "interview_method": interviews.get("method"), "interview_note": interviews.get("note")})
    return out


def series(label, unit, times, values):
    return {"label": label, "unit": unit, "times": [str(t) for t in times],
            "values": [None if v is None or not np.isfinite(v) else float(v) for v in values]}


def metric(label, value, unit=""):
    return {"label": label, "value": value, "unit": unit}


def run_history(ctx, reader):
    summary = reader.json("summary.json") or {}
    head = summary.get("headline", {})
    metrics = reader.json("metrics.json") or {}
    trace = reader.trace()
    out = {"run_id": reader.run_id, "scenario": reader.scenario, "start": summary.get("start"), "end": summary.get("end"),
           "seed": summary.get("seed"), "trace_rows": len(trace), "metrics": [], "series": [], "entities": [],
           "raw_metrics": metrics, "configuration": reader.json("config.json"),
           "note": "One saved simulation run. Insights compares evaluation averages, which can differ from this run."}

    if head.get("groups"):
        # Adoption worlds store complete group paths even when event traces are empty.
        for group in head["groups"]:
            values = group["central"]
            unit = "questions" if head.get("outcome") == "displaced" else "%"
            scale = 1 if unit == "questions" else 100
            times = [f"Period {i + 1}" for i in range(len(values))]
            path = series("Questions" if unit == "questions" else "Usage share", unit, times, [x * scale for x in values])
            out["entities"].append({"id": f"group:{group['group']}", "label": group.get("label", group["group"]), "kind": "Group",
                                    "series": [path], "metrics": [metric("End of horizon", path["values"][-1], unit)], "details": group})
        paths = [e["series"][0] for e in out["entities"]]
        if head.get("outcome") == "displaced":
            values = np.sum([p["values"] for p in paths], axis=0)
            out["metrics"] = [metric("Questions over the horizon", float(sum(values)), "questions"), metric("Final period", float(values[-1]), "questions")]
            out["series"] = [series("Questions per period", "questions", paths[0]["times"], values)]
        else:
            # Occupation shares sum to 100%; a mean across groups is not an outcome.
            focus = next((e for e in out["entities"] if e["id"] == "group:43"), None) if ctx.id == "aei_tasks" else next((e for e in out["entities"] if e["id"] == "group:31"), out["entities"][0])
            out["metrics"] = [metric(f"{focus['label']} · end share", focus["series"][0]["values"][-1], "%"), metric("Groups modeled", len(paths))]
            out["series"] = [{**focus["series"][0], "label": f"{focus['label']} · usage share"}]
        out["note"] += " These are saved expected group paths at the model's period resolution; individual people and hourly states are not recorded."
        out["step_label"] = "Period"
    elif head.get("apps"):
        for app in head["apps"]:
            times = [str(pd.Timestamp(summary["start"]) + pd.Timedelta(weeks=i))[:10] for i in range(len(app["tokens"]))]
            out["entities"].append({"id": f"app:{app['app_id']}", "label": app["name"], "kind": "App",
                "metrics": [metric("Tokens", sum(app["tokens"]), "tokens"), metric("Spending", sum(app["spend_usd"]), "USD")],
                "series": [series("Tokens per week", "tokens", times, app["tokens"]), series("Spending per week", "USD", times, app["spend_usd"])], "details": app})
        out["metrics"] = [metric("Tokens", head["total_tokens"], "tokens"), metric("Spending at list prices", head["total_spend_usd"], "USD")]
        times = out["entities"][0]["series"][0]["times"]
        out["series"] = [series("Tokens per week", "tokens", times, np.sum([a["tokens"] for a in head["apps"]], axis=0)),
                         series("Spending per week", "USD", times, np.sum([a["spend_usd"] for a in head["apps"]], axis=0))]
        out["step_label"] = "Week"
    elif metrics.get("separations"):
        sep = metrics["separations"]
        times = sep["months"]
        values = np.zeros((len(times), len(sep["groups"])))
        for kind, months in sep["expected"].items():
            for i, month in enumerate(times):
                values[i] += np.asarray(months.get(month, [0] * len(sep["groups"])))
        for col, group in enumerate(sep["groups"]):
            out["entities"].append({"id": group, "label": group, "kind": "Agency",
                                    "metrics": [metric("Expected separations", float(values[:, col].sum()), "separations")],
                                    "series": [series("Expected separations per month", "separations", times, values[:, col])], "details": {"agency": group, "starting_headcount": sep["headcount_start"][col]}})
        out["metrics"] = [metric("Expected separations", float(values.sum()), "separations"), metric("Agencies", len(sep["groups"]))]
        out["series"] = [series("Expected separations per month", "separations", times, values.sum(axis=1))]
        out["note"] += " Entities are agencies, not individual employees. Monthly expected totals are separate from realized event counts."
        out["step_label"] = "Month"
    elif ctx.world_type == "workforce":
        out["metrics"] = [metric("Whole-workforce attrition", head.get("attrition_pct"), "%"), metric("Resignations · whole workforce", head.get("quits"), "people")]
        calls = metrics.get("measures", {}).get("calls", {}).get("all", {})
        counts = calls.get("n", {})
        if counts and sum(counts.values()):
            out["metrics"].insert(0, metric("Calls per worker-week · whole workforce", sum(calls[arm] * n for arm, n in counts.items()) / sum(counts.values()), "calls"))
        if head.get("workload", {}).get("unassisted_hours"):
            workload = head["workload"]
            if workload["human_hours"] != workload["unassisted_hours"]:
                out["metrics"].append(metric("Staff effort released", 100 * (1 - workload["human_hours"] / workload["unassisted_hours"]), "%"))
                out["note"] += " AI changes task effort; an AI effect on attrition or satisfaction is not modeled."
        cumulative = metrics.get("cumulative_attrition_pct", {})
        times = cumulative.get("weeks", [])
        sizes = metrics.get("attrition_pct", {}).get("all", {}).get("n", {})
        arms = [arm for arm in sizes if cumulative.get(arm)]
        if times and arms:
            values = np.average([cumulative[a] for a in arms], axis=0, weights=[sizes[a] for a in arms])
            out["series"] = [series("Whole-workforce cumulative attrition", "%", times, values)]
        twins = {t["agent_id"]: t for t in (reader.json("twins.json") or {}).get("twins", [])}
        states = trace[trace["activity"] == "latent_state"].sort_values("tick")
        by_person = {pid: rows for pid, rows in states.groupby("agent_id")}
        for pid, twin in twins.items():
            rows = by_person.get(pid)
            paths = []
            if rows is not None:
                attrs = [json.loads(a) for a in rows.attributes]
                keys = [k for k in ("job_satisfaction", "work_life_balance", "attachment", "home_share") if any(isinstance(a.get(k), (int, float)) for a in attrs)]
                paths = [series(k.replace("_", " ").capitalize(), "", rows.sim_time.astype(str), [a.get(k) for a in attrs]) for k in keys]
            out["entities"].append({"id": pid, "label": pid, "kind": "Person", "role": twin.get("role"), "series": paths,
                                    "metrics": [metric("Home-working days", twin.get("wfh_days")), metric("Resigned in week", twin.get("quit_week"))], "details": twin})
        out["note"] += " Work events are sampled where the saved run marks them as sampled; recorded state updates and outcomes remain inspectable."
        out["step_label"] = "Week"
    else:
        out["metrics"] = [metric("Completed within 14 days", head.get("completion_rate_14d"), "%"),
                          metric("Median completion time", head.get("median_cycle_hours_completed"), "hours"),
                          metric("Open orders at the end", head.get("backlog_end"))]
        completed = trace[trace.action_type == "complete"].copy()
        completed["day"] = completed.sim_time.dt.floor("D")
        grouped = completed.groupby("day").size().reindex(pd.date_range(summary["start"], summary["end"], freq="D", inclusive="left"), fill_value=0)
        out["series"] = [series("Completed actions per day", "actions", grouped.index.astype(str), grouped.values)]
        for pid, rows in trace[trace.agent_id != ""].groupby("agent_id", sort=True):
            done = rows[rows.action_type == "complete"]
            counts = done.groupby(done.sim_time.dt.floor("h")).size().reindex(pd.date_range(summary["start"], summary["end"], freq="h", inclusive="left"), fill_value=0)
            out["entities"].append({"id": pid, "label": pid, "kind": "Worker or system", "role": str(rows.role.iloc[0]),
                                    "metrics": [metric("Recorded events", len(rows)), metric("Completed actions", len(done))],
                                    "series": [series("Completed actions per hour", "actions", counts.index.astype(str), counts.values)] if len(counts) else [],
                                    "details": {"role": str(rows.role.iloc[0]), "org_unit": str(rows.org_unit.iloc[0])}})
        out["step_label"] = "Day"
    return out
