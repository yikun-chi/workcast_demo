"""Scoring for workforce instances that forecast separations by group and month from cohort twins at rolling cutoffs.

Selected by `kind: forecast` in an instance's evaluation/protocol.yaml (the workforce world dispatches here). For each
protocol cutoff the world runs from the first day after the cutoff with that cutoff's twins (`twins_<cutoff>.parquet`,
built from records published by the cutoff); the point prediction is the expected separations along each run's path,
averaged over seeds. Development cutoffs come first and choose the specification; the held-out cutoff is scored once.

The instance supplies `evaluation/comparators.py` with
    compute(ctx, cutoff: str, months: list[str], groups: list[str]) -> {name: {"label", "description", "pred": DataFrame}}
(columns group, month, n; reading only records visible at the cutoff) and
    actual(ctx, cutoff: str, months: list[str]) -> DataFrame(group, month, type, n)
which only this module calls, after the predictions are made.
"""
from __future__ import annotations

import importlib.util
import json
import math
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from ..evaluation.metrics import interval
from ..instances import InstanceContext


def _r(x: Any, nd: int = 4) -> Any:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else round(v, nd)


def comparators_module(ctx: InstanceContext):
    spec = importlib.util.spec_from_file_location(f"{ctx.id}_comparators", ctx.evaluation_dir / "comparators.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def scored_months(cutoff: str, first: int, count: int) -> list[str]:
    p = pd.Period(cutoff, "M")
    return [str(p + first + i) for i in range(count)]


def cutoff_scenario(ctx: InstanceContext, proto: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    from ..scenarios.loader import deep_merge, load_scenario
    p = pd.Period(c["cutoff"], "M")
    start = (p + 1).start_time.date().isoformat()
    end = (p + int(proto.get("horizon_months", 12))).end_time.date().isoformat()
    scn = load_scenario(ctx, str(c.get("scenario", proto.get("scenario", "baseline"))))
    over = {"world": {"start": start, "end": end, "population_file": f"twins_{c['cutoff']}.parquet"}}
    return deep_merge(deep_merge(scn, proto.get("overrides") or {}), deep_merge(over, c.get("overrides") or {}))


def run_frame(m: dict[str, Any], which: str = "expected") -> pd.DataFrame:
    """One run's separations as rows (group, month, type, n)."""
    s = m["separations"]
    rows = []
    for kind, by_month in s[which].items():
        for month, vals in by_month.items():
            for g, v in zip(s["groups"], vals):
                rows.append((g, month, kind, float(v)))
    return pd.DataFrame(rows, columns=["group", "month", "type", "n"])


def total(df: pd.DataFrame, groups: list[str], months: list[str]) -> pd.DataFrame:
    """Sum over types, on the full group x month grid (missing cells are zero)."""
    g = df.groupby(["group", "month"]).n.sum()
    idx = pd.MultiIndex.from_product([groups, months], names=["group", "month"])
    return g.reindex(idx, fill_value=0.0).rename("n").reset_index()


def score(pred: pd.DataFrame, act: pd.DataFrame) -> dict[str, float]:
    """Errors of one prediction on the group x month grid (both frames from `total`)."""
    m = pred.merge(act, on=["group", "month"], suffixes=("_p", "_a"))
    A = float(m.n_a.sum())
    gm = float((m.n_p - m.n_a).abs().sum()) / A if A else float("nan")
    gt = m.groupby("group")[["n_p", "n_a"]].sum()
    tot_m = m.groupby("month")[["n_p", "n_a"]].sum()
    return {"group_month_wape": 100.0 * gm, "group_total_wape": 100.0 * float((gt.n_p - gt.n_a).abs().sum()) / A if A else float("nan"),
            "total_error_pct": 100.0 * float(m.n_p.sum() - A) / A if A else float("nan"),
            "total_month_wape": 100.0 * float((tot_m.n_p - tot_m.n_a).abs().sum()) / A if A else float("nan"),
            "actual_total": A, "predicted_total": float(m.n_p.sum())}


def run_cutoff(ctx: InstanceContext, proto: dict[str, Any], c: dict[str, Any], seeds: list[int], scenario: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    from .workforce import _run_once
    scn = scenario or cutoff_scenario(ctx, proto, c)
    return [_run_once(ctx, scn, sd) for sd in seeds]


def evaluate(ctx: InstanceContext, scenario_ids: list[str]) -> dict[str, Any]:
    proto = ctx.yaml("evaluation/protocol.yaml")
    comp_mod = comparators_module(ctx)
    seeds = list(range(int(proto["seeds"]["start"]), int(proto["seeds"]["start"]) + int(proto["seeds"]["count"])))
    first, count = int(proto["score_months"]["first"]), int(proto["score_months"]["count"])
    windows, run_ids, scatter = [], {"baseline": []}, []
    for c in proto["cutoffs"]:
        months = scored_months(c["cutoff"], first, count)
        runs = run_cutoff(ctx, proto, c, seeds)
        run_ids["baseline"] += [m["run_id"] for m in runs]
        groups = runs[0]["separations"]["groups"]
        per_seed = [total(run_frame(m), groups, months) for m in runs]
        sim = per_seed[0][["group", "month"]].copy()
        sim["n"] = np.mean([p.n.to_numpy() for p in per_seed], axis=0)
        comps = comp_mod.compute(ctx, c["cutoff"], months, groups)          # predictions first, from records visible at the cutoff
        act_types = comp_mod.actual(ctx, c["cutoff"], months)               # then the outcome, for scoring only
        act = total(act_types, groups, months)
        res = {"simulation": score(sim, act), **{k: score(total(v["pred"], groups, months), act) for k, v in comps.items()}}
        seed_scores = [score(p, act)["group_month_wape"] for p in per_seed]
        act_by_type = act_types[act_types.month.isin(months)].groupby("type").n.sum()
        sim_types = pd.concat([run_frame(m)[lambda d: d.month.isin(months)] for m in runs]).groupby("type").n.sum() / len(runs)
        best = min(comps, key=lambda k: res[k]["group_month_wape"])
        w = {"cutoff": c["cutoff"], "role": c["role"], "months": [months[0], months[-1]], "n_groups": len(groups),
             "headcount_start": _r(sum(runs[0]["separations"]["headcount_start"]), 0),
             "scores": {k: {kk: _r(vv, 3) for kk, vv in v.items()} for k, v in res.items()},
             "best_comparator": best,
             "error_reduction_pct": _r(100.0 * (1 - res["simulation"]["group_month_wape"] / res[best]["group_month_wape"]), 2),
             "best_comparator_total": min(comps, key=lambda k: res[k]["group_total_wape"]),
             "seed_interval_group_month_wape": [_r(v, 3) for v in interval(seed_scores)],
             "by_type": {t: {"simulation": _r(sim_types.get(t, 0.0), 1), "actual": _r(act_by_type.get(t, 0.0), 1)} for t in sorted(set(sim_types.index) | set(act_by_type.index))},
             "monthly": {"months": months, "actual": [_r(v, 1) for v in act.groupby("month").n.sum().reindex(months).to_numpy()],
                         "simulation": [_r(v, 1) for v in sim.groupby("month").n.sum().reindex(months).to_numpy()],
                         "simulation_band": [[_r(v, 1) for v in np.quantile([p.groupby("month").n.sum().reindex(months).to_numpy() for p in per_seed], q, axis=0)] for q in (0.05, 0.95)],
                         **{k: [_r(x, 1) for x in total(v["pred"], groups, months).groupby("month").n.sum().reindex(months).to_numpy()] for k, v in comps.items()}},
             "groups": {}}
        gt_a = act.groupby("group").n.sum(); gt_s = sim.groupby("group").n.sum()
        gt_c = {k: total(v["pred"], groups, months).groupby("group").n.sum() for k, v in comps.items()}
        for g in groups:
            w["groups"][g] = {"actual": _r(gt_a.get(g, 0.0), 1), "simulation": _r(gt_s.get(g, 0.0), 1), **{k: _r(gt_c[k].get(g, 0.0), 1) for k in comps}}
            scatter.append({"cutoff": c["cutoff"], "group": g, "actual": _r(gt_a.get(g, 0.0), 1), "simulation": _r(gt_s.get(g, 0.0), 1), **{k: _r(gt_c[k].get(g, 0.0), 1) for k in comps}})
        windows.append(w)
        labels = {k: v["label"] for k, v in comps.items()}
        descriptions = {k: v.get("description", "") for k, v in comps.items()}

    def summary(ws: list[dict[str, Any]]) -> dict[str, Any]:
        keys = ["simulation", *labels]
        out: dict[str, Any] = {}
        for metric in ("group_month_wape", "group_total_wape", "total_month_wape"):
            vals = {k: _r(np.mean([w["scores"][k][metric] for w in ws]), 3) for k in keys}
            best = min(labels, key=lambda k: vals[k])
            out[metric] = {**vals, "best_comparator": best, "error_reduction_pct": _r(100.0 * (1 - vals["simulation"] / vals[best]), 2) if vals[best] else None,
                           "accuracy_pct": {k: _r(100.0 - v, 2) for k, v in vals.items()}}
        out["n_windows"] = len(ws); out["n_predictions"] = sum(w["n_groups"] * len(w["monthly"]["months"]) for w in ws)
        out["actual_total"] = _r(sum(w["scores"]["simulation"]["actual_total"] for w in ws), 1)
        out["mean_actual_per_group_month"] = _r(out["actual_total"] / out["n_predictions"], 2) if out["n_predictions"] else None
        return out

    held = [w for w in windows if w["role"] == "held_out"]
    dev = [w for w in windows if w["role"] == "development"]
    accuracy = {"held_out": summary(held), "development": summary(dev), "all": summary(windows)}

    # the alternative on the held-out cutoff, with the same seeds
    alt_rows = []
    wi = proto.get("whatif") or {}
    wseeds = [int(s) for s in wi.get("seeds") or []]
    from ..scenarios.loader import deep_merge, load_scenario
    for sid in wi.get("scenarios") or []:
        if scenario_ids and sid not in scenario_ids:
            continue
        c = next(x for x in proto["cutoffs"] if x["role"] == "held_out")
        base_scn = cutoff_scenario(ctx, proto, c)
        alt_scn = deep_merge(base_scn, {k: v for k, v in load_scenario(ctx, sid).items() if k in ("world", "interventions", "id", "title")})
        months = scored_months(c["cutoff"], first, count)
        alt_runs = run_cutoff(ctx, proto, c, wseeds, alt_scn)
        run_ids[sid] = [m["run_id"] for m in alt_runs]
        groups = alt_runs[0]["separations"]["groups"]
        base_runs = [m for m in run_cutoff(ctx, proto, c, wseeds, base_scn)]
        run_ids.setdefault("baseline_paired", []).extend(m["run_id"] for m in base_runs)
        a_tot = [total(run_frame(m), groups, months) for m in alt_runs]; b_tot = [total(run_frame(m), groups, months) for m in base_runs]
        diffs = [float(a.n.sum() - b.n.sum()) for a, b in zip(a_tot, b_tot)]
        alt_rows.append({"scenario": sid, "cutoff": c["cutoff"], "seeds": wseeds,
                         "total": {"baseline": _r(np.mean([b.n.sum() for b in b_tot]), 1), "alternative": _r(np.mean([a.n.sum() for a in a_tot]), 1),
                                   "difference": _r(np.mean(diffs), 1), "interval": [_r(v, 1) for v in interval(diffs)]},
                         "monthly": {"months": months, "baseline": [_r(v, 1) for v in np.mean([b.groupby("month").n.sum().reindex(months).to_numpy() for b in b_tot], axis=0)],
                                     "alternative": [_r(v, 1) for v in np.mean([a.groupby("month").n.sum().reindex(months).to_numpy() for a in a_tot], axis=0)]},
                         "groups": {g: {"baseline": _r(np.mean([b[b.group == g].n.sum() for b in b_tot]), 1), "alternative": _r(np.mean([a[a.group == g].n.sum() for a in a_tot]), 1)} for g in groups}})

    out = {"instance": ctx.id, "generated": datetime.now(timezone.utc).isoformat(), "kind": "forecast",
           "protocol": {"design": proto.get("design", ""), "cutoffs": [c["cutoff"] for c in proto["cutoffs"]], "roles": {c["cutoff"]: c["role"] for c in proto["cutoffs"]},
                        "seeds": len(seeds), "score_months": proto["score_months"], "freeze_rule": ctx.meta.get("evaluation", {}).get("freeze_rule", "")},
           "windows": windows, "accuracy": accuracy, "comparator_labels": labels, "comparator_descriptions": descriptions,
           "scenario_comparison": alt_rows, "scatter": scatter, "run_ids": run_ids,
           "priors": {k: {"central": v.get("central"), "range": v.get("range"), "source": v.get("source")} for k, v in (ctx.yaml("calibration/priors.yaml").get("parameters") or {}).items()}}
    out["business_validation"] = [{"id": "group_month", "windows": [{"cutoff": w["cutoff"], "actual": w["scores"]["simulation"]["actual_total"]} for w in windows],
                                   "simulation_mae": accuracy["held_out"]["group_month_wape"]["simulation"],
                                   "baseline_mae": {k: accuracy["held_out"]["group_month_wape"][k] for k in labels},
                                   "best_baseline": accuracy["held_out"]["group_month_wape"]["best_comparator"],
                                   "beats_best_baseline": accuracy["held_out"]["group_month_wape"]["simulation"] < accuracy["held_out"]["group_month_wape"][accuracy["held_out"]["group_month_wape"]["best_comparator"]],
                                   "error_reduction_pct": accuracy["held_out"]["group_month_wape"]["error_reduction_pct"]}]
    out["value_inputs"] = value_inputs(out, proto)
    ctx.runs_dir.mkdir(parents=True, exist_ok=True)
    (ctx.runs_dir / "evaluation.json").write_text(json.dumps(out, indent=1, default=str))
    (ctx.runs_dir / "value_inputs.json").write_text(json.dumps(out["value_inputs"], indent=1, default=str))
    return out


def _dig(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def value_inputs(ev: dict[str, Any], proto: dict[str, Any]) -> dict[str, Any]:
    """The figures a value case cites, each with its exact path inside evaluation.json."""
    out: dict[str, Any] = {"instance": ev["instance"], "evaluation": f"runs/{ev['instance']}/evaluation.json", "generated": ev["generated"], "figures": []}
    def fig(name: str, path: str) -> None:
        out["figures"].append({"name": name, "path": path, "value": _dig(ev, path)})
    for scope in ("held_out", "all"):
        for metric in ("group_month_wape", "group_total_wape"):
            base = f"accuracy.{scope}.{metric}"
            for k in ["simulation", *ev["comparator_labels"]]:
                fig(f"{scope} {metric}: {k}", f"{base}.{k}")
            for k in ("best_comparator", "error_reduction_pct"):
                fig(f"{scope} {metric}: {k}", f"{base}.{k}")
            fig(f"{scope} {metric}: simulation accuracy", f"{base}.accuracy_pct.simulation")
        for k in ("n_windows", "n_predictions", "actual_total", "mean_actual_per_group_month"):
            fig(f"{scope}: {k}", f"accuracy.{scope}.{k}")
    for i, w in enumerate(ev["windows"]):
        fig(f"window {w['cutoff']}: months", f"windows.{i}.months")
        fig(f"window {w['cutoff']}: actual separations", f"windows.{i}.scores.simulation.actual_total")
    for name, path in ((proto.get("value_inputs") or {}).get("extra") or {}).items():
        fig(name, path)
    return out


def results_view(ctx: InstanceContext) -> dict[str, Any]:
    from ..evaluation.results import base_document
    doc = base_document(ctx)
    ev_path = ctx.runs_dir / "evaluation.json"
    ev = json.loads(ev_path.read_text()) if ev_path.exists() else {}
    proto = ctx.yaml("evaluation/protocol.yaml")
    st = proto.get("story") or {}
    labels = ev.get("comparator_labels") or {}
    base = doc["scenarios"]["baseline"]; alt = doc["scenarios"].get("alternative")
    held = next((w for w in ev.get("windows", []) if w["role"] == "held_out"), None)
    acc = (ev.get("accuracy") or {}).get("held_out") or {}
    gm = acc.get("group_month_wape") or {}
    doc["design"] = st.get("design", "")
    sources = [{"id": "actual", "label": "Separations recorded by OPM · actual outcome", "kind": "actual", "kind_label": "Actual outcome (actual data)", "short": "Actual outcome", "scenario": base["id"],
                "note": "OPM Federal Workforce Data, separations by effective month (pinned file versions in manifests/sources.json)."},
               {"id": "baseline", "label": f"{base['title']} · simulation prediction", "kind": "simulated", "kind_label": "Simulation prediction", "short": "Simulation prediction", "scenario": base["id"],
                "runs": (ev.get("protocol") or {}).get("seeds"), "note": f"Mean expected separations over {(ev.get('protocol') or {}).get('seeds', '?')} runs per cutoff; ranges cover 90% of runs."}]
    alt_row = (ev.get("scenario_comparison") or [None])[0]
    if alt:
        sources.append({"id": "alternative", "label": f"{alt['title']} · simulation prediction", "kind": "simulated", "kind_label": "Alternative simulation prediction", "short": alt["short_title"], "scenario": alt["id"],
                        "runs": len((alt_row or {}).get("seeds", [])), "note": "Same seeds and cutoff as the simulation of what happened."})
    metrics, charts = [], []
    if held:
        s = held["scores"]
        sim_tot = s["simulation"]["predicted_total"]; act_tot = s["simulation"]["actual_total"]
        metrics.append({"id": "total", "label": f"Separations, {held['months'][0]} to {held['months'][1]}, all agencies", "unit": "", "better": "lower",
                        "values": {"actual": _r(act_tot, 0), "baseline": _r(sim_tot, 0), "alternative": (alt_row or {}).get("total", {}).get("alternative")},
                        "intervals": {}, "paired_baseline": (alt_row or {}).get("total", {}).get("baseline"), "note": ""})
        metrics.append({"id": "group_month_wape", "label": "Error in each agency's monthly separations (percent of actual)", "unit": "%", "better": "lower",
                        "values": {"actual": None, "baseline": gm.get("simulation"), "alternative": None}, "intervals": {}, "note": ""})
        months = held["monthly"]["months"]
        series = [{"name": "Actual outcome", "y": held["monthly"]["actual"], "source": "actual"},
                  {"name": "Simulation prediction", "y": held["monthly"]["simulation"], "band": held["monthly"]["simulation_band"], "source": "baseline"}]
        for k in labels:
            series.append({"name": labels[k], "y": held["monthly"][k], "source": "comparator", "dashed": True})
        if alt_row:
            series.append({"name": alt["short_title"], "y": alt_row["monthly"]["alternative"], "source": "alternative"})
            series[1]["paired_y"] = alt_row["monthly"]["baseline"]
        charts.append({"id": "monthly_total", "type": "line", "title": "Separations from all agencies per month", "x_label": "month", "y_label": "separations", "x": months, "series": series,
                       "note": "Band: middle 90% of simulation runs."})
        top = sorted(held["groups"].items(), key=lambda kv: -(kv[1]["actual"] or 0))[: int(st.get("top_groups", 15))]
        names = json.loads((ctx.data_normalized / "agencies.json").read_text())["names"] if (ctx.data_normalized / "agencies.json").exists() else {}
        best = held["best_comparator"]
        gseries = [{"name": "Actual outcome", "y": [v["actual"] for _, v in top], "source": "actual"},
                   {"name": "Simulation prediction", "y": [v["simulation"] for _, v in top], "source": "baseline"},
                   {"name": labels.get(best, best), "y": [v[best] for _, v in top], "source": "comparator"}]
        if alt_row:
            gseries.append({"name": alt["short_title"], "y": [alt_row["groups"].get(g, {}).get("alternative") for g, _ in top], "source": "alternative"})
            gseries[1]["paired_y"] = [alt_row["groups"].get(g, {}).get("baseline") for g, _ in top]
        charts.append({"id": "agency_totals", "type": "hbar", "title": f"Separations by agency, {held['months'][0]} to {held['months'][1]}", "x_label": "", "y_label": "separations",
                       "x": [names.get(g, "Other agencies") if g != "OTHER" else "Other agencies" for g, _ in top], "series": gseries, "note": f"The {len(top)} agencies with the most separations."})
    story_metrics = []
    if held:
        story_metrics.append({"id": "total", "label": "Separations, all agencies", "unit": "", "better": "lower", "before_actual": _r(st_before(ev), 0),
                              "after_actual": metrics[0]["values"]["actual"], "after_sim": metrics[0]["values"]["baseline"], "intervals": {}})
    doc["story"] = {"before": {"label": st.get("before_label", "Before the change"), "sublabel": st.get("before_sublabel", "")},
                    "change": {"label": st.get("change_label", ""), "description": st.get("change_description", ""), "stats": _change_stats(ctx, held)},
                    "after": {"label": st.get("after_label", "After the change"), "sublabel": st.get("after_sublabel", "")},
                    "columns": {"before_actual": "Actual outcome", "after_actual": "Actual outcome", "after_sim": "Simulation prediction"},
                    "metrics": story_metrics, "chart": "monthly_total",
                    "baselines": [{"id": k, "label": labels[k], "values": {"total": _r(held["scores"][k]["predicted_total"], 0) if held else None}} for k in labels],
                    "baseline_basis": "outcome",
                    "comparator_explanation": {"paragraphs": [v for v in (ev.get("comparator_descriptions") or {}).values() if v], "formula": st.get("comparator_formula", ""), "sources": st.get("comparator_sources", [])},
                    "business_validation": [{"id": "total", "simulation_mae": gm.get("simulation"), "baseline_mae": {k: gm.get(k) for k in labels}, "best_baseline": gm.get("best_comparator"),
                                             "beats_best_baseline": (gm.get("simulation") or 1e9) < (gm.get(gm.get("best_comparator")) or 0), "error_reduction_pct": gm.get("error_reduction_pct")}],
                    "fidelity": [{"label": "Simulation: error in each agency's monthly separations", "value": gm.get("simulation"), "unit": "%"},
                                 {"label": f"Best other prediction ({labels.get(gm.get('best_comparator'), '')})", "value": gm.get(gm.get("best_comparator")), "unit": "%"},
                                 {"label": "Error reduction", "value": gm.get("error_reduction_pct"), "unit": "%"}]}
    hero = {"kicker": st.get("hero_kicker", ""), "stats": doc["story"]["fidelity"], "claim": st.get("claim", ""), "chart": "monthly_total"}
    if alt and alt_row:
        t = alt_row["total"]
        hero["alternative"] = {"kicker": f"Alternative: {alt['short_title']}", "stats": [{"label": "Separations, all agencies", "value": f"{t['baseline']:,.0f} → {t['alternative']:,.0f}", "unit": ""}],
                               "text": st.get("alternative_text", "")}
    doc.update({"sources": sources, "metrics": metrics, "effects": [], "charts": charts, "hero": hero, "windows": ev.get("windows", []), "accuracy": ev.get("accuracy"),
                "evaluation": {"generated": ev.get("generated"), "protocol": ev.get("protocol")}})
    return doc


def st_before(ev: dict[str, Any]) -> float | None:
    """Separations in the same months of the year before the held-out window (the seasonal comparator's basis is
    the latest observed year): read from the held-out window's same-months-last-year prediction."""
    held = next((w for w in ev.get("windows", []) if w["role"] == "held_out"), None)
    if not held or "seasonal_naive" not in held["scores"]:
        return None
    return held["scores"]["seasonal_naive"]["predicted_total"]


def _change_stats(ctx: InstanceContext, held: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Employees at the held-out cutoff and the offers' effective dates, read from the evaluation and the scenario."""
    from ..scenarios.loader import load_scenario
    out = []
    if held:
        out.append({"label": f"Employees at the cutoff ({held['cutoff']})", "value": f"{held['headcount_start']:,.0f}"})
    try:
        for o in (load_scenario(ctx, ctx.meta["scenarios"]["baseline"]).get("world") or {}).get("offers") or []:
            out.append({"label": "Offer decided / separations effective", "value": f"{o['decide']} / {o['effective']}"})
    except (FileNotFoundError, KeyError):
        pass
    return out
