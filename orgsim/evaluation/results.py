"""Results view: one document per instance that the Results tab renders.

Three sources side by side, selected by the viewer: the baseline's ground truth (the actual data the forecast is scored
against), the baseline as simulated, and the alternative scenario as simulated. Each world module provides
`results_view(ctx)` returning:

  sources   [{id, label, kind: actual|simulated, scenario, runs, note}]
  metrics   [{id, label, unit, better, values: {source_id: number|None}, intervals: {source_id: [lo, hi]}, note}]
  effects   [...]  optional: validation of treatment effects (workforce worlds), the headline entries of evaluation.json
  charts    [{id, title, type, x, x_label, y_label, series: [{name, y, band?, source, point?}], note}]  one series per source
  narrative {takeaways: [...], sections: [{heading, body}]}  from reports/report.json
  plugins   [{id, title, url}]  instance pages embedded as detailed views

This module holds the shared helpers: reading run summaries/metrics for a scenario and averaging them over seeds.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import numpy as np

from .. import RUNS_DIR
from ..instances import InstanceContext
from ..scenarios import list_scenarios, load_scenario, scenario_roles
from ..store import list_runs


def run_docs(ctx: InstanceContext, scenario_id: str, name: str = "summary", run_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Every completed run of a scenario -> its summary.json (or metrics.json) documents, newest first."""
    out = []
    for r in list_runs(ctx.id):
        if r["scenario"] != scenario_id or not r["complete"]:
            continue
        if run_ids is not None and r["run_id"] not in run_ids:
            continue
        p = RUNS_DIR / ctx.id / scenario_id / r["run_id"] / f"{name}.json"
        if p.exists():
            try:
                out.append(json.loads(p.read_text()))
            except (OSError, ValueError):
                continue
    return out


def dig(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def mean_of(docs: list[dict[str, Any]], path: str, nd: int = 3) -> float | None:
    vals = [v for v in (dig(d, path) for d in docs) if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return round(float(np.mean(vals)), nd) if vals else None


def interval_of(docs: list[dict[str, Any]], path: str, nd: int = 3) -> list[float] | None:
    vals = [v for v in (dig(d, path) for d in docs) if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(vals) < 2:
        return None
    return [round(float(np.quantile(vals, 0.05)), nd), round(float(np.quantile(vals, 0.95)), nd)]


def series_mean(docs: list[dict[str, Any]], getter, nd: int = 3) -> tuple[list[float], list[float], list[float]]:
    arrs = []
    for d in docs:
        try:
            a = np.array([np.nan if v is None else float(v) for v in getter(d)], dtype=float)
            arrs.append(a)
        except (KeyError, TypeError):
            continue
    if not arrs:
        return [], [], []
    L = min(len(a) for a in arrs)
    st = np.vstack([a[:L] for a in arrs])
    f = lambda a: [round(float(x), nd) for x in a]
    return f(np.nanmean(st, axis=0)), f(np.nanquantile(st, 0.05, axis=0)), f(np.nanquantile(st, 0.95, axis=0))


def scenario_meta(ctx: InstanceContext) -> dict[str, Any]:
    roles = scenario_roles(ctx)
    by_role = {v: k for k, v in roles.items()}
    titles = {s["id"]: s["title"] for s in list_scenarios(ctx)}
    shorts = {s["id"]: s.get("short_title", s["title"]) for s in list_scenarios(ctx)}
    bid = by_role.get("baseline", "baseline")
    out = {"baseline": {"id": bid, "title": titles.get(bid, "Baseline"), "short_title": shorts.get(bid, "Baseline")}}
    if by_role.get("alternative"):
        alt = by_role["alternative"]
        try:
            full = load_scenario(ctx, alt)
        except FileNotFoundError:
            full = {}
        out["alternative"] = {"id": alt, "title": titles.get(alt, alt), "short_title": shorts.get(alt, alt), "description": full.get("description", ""), "interventions": full.get("interventions", [])}
    return out


def narrative(ctx: InstanceContext, current_explorations: set[str] | None = None) -> dict[str, Any]:
    p = ctx.reports_dir / "report.json"
    if not p.exists():
        return {"takeaways": [], "sections": []}
    try:
        r = json.loads(p.read_text())
    except (OSError, ValueError):
        return {"takeaways": [], "sections": []}
    return {"title": r.get("title"), "subtitle": r.get("subtitle"), "generated": r.get("generated"), "takeaways": r.get("takeaways") or [],
            "sections": [{"heading": s.get("heading"), "body": s.get("body", "")} for s in r.get("sections") or []
                         if not s.get("exploration") or s["exploration"] in (current_explorations or set())]}


def plugins(ctx: InstanceContext) -> list[dict[str, Any]]:
    p = ctx.ui_dir / "pages.json"
    if not p.exists():
        return []
    try:
        pages = json.loads(p.read_text())
    except (OSError, ValueError):
        return []
    return [{"id": x.get("id"), "title": x.get("title"), "url": f"/instances/{ctx.id}/ui/{x.get('entry')}"} for x in pages if x.get("entry")]


def base_document(ctx: InstanceContext) -> dict[str, Any]:
    from .exploration import exploration_views
    views = exploration_views(ctx)
    return {"instance": ctx.id, "company": ctx.meta.get("company", ctx.meta.get("title", ctx.id)), "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "scenarios": scenario_meta(ctx), "narrative": narrative(ctx, {v["id"] for v in views if v["state"] == "ready"}), "plugins": plugins(ctx), "explorations": views}
