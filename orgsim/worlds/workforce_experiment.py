"""Scoring for workforce instances whose change is a randomized experiment with weekly output measures.

Selected by `kind: experiment` in an instance's evaluation/protocol.yaml (the workforce world dispatches here).
The protocol lists metrics of five kinds, each computed from the simulation's run metrics and from the reference
outcomes, which only this module reads:

  level             a measure's mean over the scored weeks in one arm (`measure`, `arm`)
  did / did_pct     the arms' difference in the change of a measure from the observed before period
                    (did_pct converts a log-measure difference to percent)
  attrition_level   the share of an arm who left by the end (`arm`), in percent
  attrition_effect  the difference in that share between the arms, in percentage points

The before period is observed data only: the simulation predicts the after period and the before-period means
come from the reference file. Comparators come from the instance's evaluation/comparators.py `compute(ctx)`, which
may read only data from before the change, and are fixed before scoring.
"""
from __future__ import annotations

import importlib.util
import json
import math
from datetime import datetime, timezone
from typing import Any

import numpy as np

from ..evaluation.metrics import coverage, interval
from ..instances import InstanceContext


def _dig(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _r(x: Any, nd: int = 4) -> Any:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else round(v, nd)


def load_comparators(ctx: InstanceContext) -> dict[str, Any]:
    p = ctx.evaluation_dir / "comparators.py"
    spec = importlib.util.spec_from_file_location(f"{ctx.id}_comparators", p)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.compute(ctx)


def simulated_value(m: dict[str, Any], spec: dict[str, Any], ref: dict[str, Any], point: bool = True) -> float | None:
    """One metric from one run's metrics.json. Attrition uses the expected-quit estimator for the point prediction."""
    kind = spec["kind"]
    if kind == "level":
        return _dig(m, f"measures.{spec['measure']}.all.{spec['arm']}")
    if kind in ("did", "did_pct"):
        post = [_dig(m, f"measures.{spec['measure']}.all.{a}") for a in ("1", "0")]
        pre = [_dig(ref, f"measures.{spec['measure']}.pre.{a}") for a in ("1", "0")]
        if any(v is None for v in post + pre):
            return None
        d = (post[0] - pre[0]) - (post[1] - pre[1])
        return 100.0 * (math.exp(d) - 1.0) if kind == "did_pct" else d
    base = "expected_attrition_pct" if point else "attrition_pct"
    if kind == "attrition_level":
        return _dig(m, f"{base}.all.{spec['arm']}")
    if kind == "attrition_effect":
        return _dig(m, f"{base}.all.itt")
    raise ValueError(f"unknown metric kind {kind!r}")


def actual_value(spec: dict[str, Any], ref: dict[str, Any]) -> tuple[float | None, float | None]:
    """The reference outcome and its standard error where the reference provides one."""
    kind = spec["kind"]
    if kind == "level":
        return _dig(ref, f"measures.{spec['measure']}.post.{spec['arm']}"), None
    if kind == "did":
        return _dig(ref, f"measures.{spec['measure']}.did"), _dig(ref, f"measures.{spec['measure']}.se_did")
    if kind == "did_pct":
        d, se = _dig(ref, f"measures.{spec['measure']}.did"), _dig(ref, f"measures.{spec['measure']}.se_did")
        return (100.0 * (math.exp(d) - 1.0) if d is not None else None), (100.0 * math.exp(d) * se if se is not None and d is not None else None)
    if kind == "attrition_level":
        return _dig(ref, f"attrition_pct.all.{spec['arm']}"), _dig(ref, f"attrition_pct.all.se.{spec['arm']}")
    if kind == "attrition_effect":
        return _dig(ref, "attrition_pct.all.itt"), _dig(ref, "attrition_pct.all.se.itt")
    return None, None


def before_value(spec: dict[str, Any], ref: dict[str, Any], comps: dict[str, Any]) -> float | None:
    if spec["kind"] == "level":
        return _dig(ref, f"measures.{spec['measure']}.pre.{spec['arm']}")
    if spec["kind"] == "attrition_level":
        return _dig(comps, f"no_change.values.{spec['id']}")
    return None


def evaluate(ctx: InstanceContext, scenario_ids: list[str]) -> dict[str, Any]:
    from ..scenarios.loader import deep_merge, load_scenario
    from .workforce import _run_once
    proto = ctx.yaml("evaluation/protocol.yaml")
    ref = json.loads((ctx.root / str(proto["reference"])).read_text())
    comps = load_comparators(ctx)
    seeds_cfg = proto.get("seeds") or {"start": 1, "count": 20}
    seeds = list(range(int(seeds_cfg["start"]), int(seeds_cfg["start"]) + int(seeds_cfg["count"])))
    scn = deep_merge(load_scenario(ctx, str(proto.get("scenario", "baseline"))), proto.get("overrides") or {})
    runs = [_run_once(ctx, scn, sd) for sd in seeds]

    metrics, index = [], {}
    for spec in proto["metrics"]:
        sims = [simulated_value(m, spec, ref) for m in runs]
        sims = [v for v in sims if v is not None]
        point = float(np.mean(sims)) if sims else None
        realized = [v for v in (simulated_value(m, spec, ref, point=False) for m in runs) if v is not None]
        lo, hi = interval(realized or sims) if (realized or sims) else (None, None)
        actual, se = actual_value(spec, ref)
        cvals = {cid: _dig(c, f"values.{spec['id']}") for cid, c in comps.items()}
        cvals = {k: v for k, v in cvals.items() if v is not None}
        e: dict[str, Any] = {"id": spec["id"], "label": spec["label"], "kind": spec["kind"], "unit": spec.get("unit", ""), "better": spec.get("better", "higher"),
                             "headline": bool(spec.get("headline")), "simulated": _r(point), "interval": [_r(lo), _r(hi)], "n_seeds": len(sims),
                             "actual": _r(actual), "actual_se": _r(se), "before": _r(before_value(spec, ref, comps)), "comparators": {k: _r(v) for k, v in cvals.items()}}
        if actual is not None and point is not None:
            e["error"] = _r(point - actual); e["abs_error"] = _r(abs(point - actual))
            e["comparator_errors"] = {k: _r(abs(v - actual)) for k, v in cvals.items()}
            if cvals:
                best = min(e["comparator_errors"], key=lambda k: e["comparator_errors"][k])
                be = e["comparator_errors"][best]
                e["best_comparator"] = best
                e["best_comparator_error"] = be
                e["beats_best_comparator"] = bool(abs(point - actual) < be)
                e["error_reduction_pct"] = _r(100.0 * (1.0 - abs(point - actual) / be), 2) if be else None
            if spec["kind"] in ("level", "attrition_level") and actual:
                e["accuracy_pct"] = _r(100.0 * (1.0 - abs(point - actual) / abs(actual)), 2)
                e["comparator_accuracy_pct"] = {k: _r(100.0 * (1.0 - abs(v - actual) / abs(actual)), 2) for k, v in cvals.items()}
            if se:
                e["actual_ci95"] = [_r(actual - 1.96 * se), _r(actual + 1.96 * se)]
                e["within_actual_ci95"] = bool(actual - 1.96 * se <= point <= actual + 1.96 * se)
            e["covered_90"] = bool(coverage(realized or sims, actual)) if (realized or sims) else None
        metrics.append(e); index[spec["id"]] = e

    # the alternative: matching seeds, the same metric definitions
    wi = proto.get("whatif") or {}
    wseeds = [int(s) for s in wi.get("seeds") or []]
    alt_runs: dict[str, list[dict[str, Any]]] = {}
    for sid in wi.get("scenarios") or []:
        if scenario_ids and sid not in scenario_ids:
            continue
        s2 = deep_merge(load_scenario(ctx, sid), wi.get("overrides") or {})
        alt_runs[sid] = [_run_once(ctx, s2, sd) for sd in wseeds]
    comparison = []
    for sid, rs in alt_runs.items():
        base = [m for m, sd in zip(runs, seeds) if sd in wseeds]
        row = {"scenario": sid, "seeds": wseeds, "metrics": {}}
        for spec in proto["metrics"]:
            a = [simulated_value(m, spec, ref) for m in rs]; b = [simulated_value(m, spec, ref) for m in base]
            diffs = [x - y for x, y in zip(a, b) if x is not None and y is not None]
            row["metrics"][spec["id"]] = {"alternative": _r(np.mean([x for x in a if x is not None])) if any(x is not None for x in a) else None,
                                          "baseline": _r(np.mean([x for x in b if x is not None])) if any(x is not None for x in b) else None,
                                          "difference": _r(np.mean(diffs)) if diffs else None, "interval": [_r(v) for v in interval(diffs)] if diffs else None}
        comparison.append(row)

    out = {"instance": ctx.id, "generated": datetime.now(timezone.utc).isoformat(), "kind": "experiment",
           "protocol": {"design": proto.get("design", ""), "t0": proto.get("t0"), "seeds": len(seeds), "whatif_seeds": len(wseeds), "scenario": scn.get("id"),
                        "freeze_rule": ctx.meta.get("evaluation", {}).get("freeze_rule", "")},
           "headline": {m["id"]: m for m in metrics if m["headline"]}, "metrics": metrics, "metric_index": index,
           "comparators": {k: {"label": v["label"], "description": v.get("description", ""), "values": v["values"]} for k, v in comps.items()},
           "comparator_labels": {k: v["label"] for k, v in comps.items()},
           "scenario_comparison": comparison, "run_ids": {"evaluation": [m["run_id"] for m in runs], **{sid: [m["run_id"] for m in rs] for sid, rs in alt_runs.items()}},
           "seeds": [{"seed": sd, **{s["id"]: _r(simulated_value(m, s, ref)) for s in proto["metrics"]}} for m, sd in zip(runs, seeds)],
           "priors": {k: {"central": v.get("central"), "range": v.get("range"), "source": v.get("source")} for k, v in (ctx.yaml("calibration/priors.yaml").get("parameters") or {}).items()},
           "reference_source": ref.get("source", ""), "population": {"n": _dig(ref, "attrition_pct.all.n")},
           "charts": charts(runs, ref, proto, alt_runs, wseeds, seeds)}
    out["value_inputs"] = value_inputs(out, proto)
    ctx.runs_dir.mkdir(parents=True, exist_ok=True)
    (ctx.runs_dir / "evaluation.json").write_text(json.dumps(out, indent=1, default=str))
    (ctx.runs_dir / "value_inputs.json").write_text(json.dumps(out["value_inputs"], indent=1, default=str))
    return out


def value_inputs(ev: dict[str, Any], proto: dict[str, Any]) -> dict[str, Any]:
    """The figures a value case cites, each with its exact path inside evaluation.json."""
    vi = proto.get("value_inputs") or {}
    out: dict[str, Any] = {"instance": ev["instance"], "evaluation": f"runs/{ev['instance']}/evaluation.json", "generated": ev["generated"], "figures": []}
    def fig(name: str, path: str) -> None:
        out["figures"].append({"name": name, "path": path, "value": _dig(ev, path)})
    for mid in vi.get("metrics") or []:
        e = ev["metric_index"].get(mid) or {}
        fig(f"{mid}: simulation", f"metric_index.{mid}.simulated")
        fig(f"{mid}: actual", f"metric_index.{mid}.actual")
        for c in sorted(e.get("comparators") or {}):
            fig(f"{mid}: {c}", f"metric_index.{mid}.comparators.{c}")
            fig(f"{mid}: {c} error", f"metric_index.{mid}.comparator_errors.{c}")
        for k in ("abs_error", "best_comparator", "best_comparator_error", "error_reduction_pct", "accuracy_pct"):
            if k in e:
                fig(f"{mid}: {k}", f"metric_index.{mid}.{k}")
    for name, path in (vi.get("extra") or {}).items():
        fig(name, path)
    return out


def charts(runs: list[dict[str, Any]], ref: dict[str, Any], proto: dict[str, Any], alt_runs: dict[str, list[dict[str, Any]]], wseeds: list[int], seeds: list[int]) -> list[dict[str, Any]]:
    arms = {str(k): str(v) for k, v in (proto.get("arms") or {}).items()}
    out = []
    for c in proto.get("charts") or []:
        if c["type"] == "measure_weekly":
            meas = c["measure"]
            keys = (runs[0].get("measures") or {}).get(meas, {}).get("weekly", {}).get("keys", [])
            xs = [str(k) for k in keys]
            series = []
            rw = (ref.get("weekly") or {}).get(meas) or {}
            pos = {str(k): i for i, k in enumerate(rw.get("keys", []))}
            for a, label in arms.items():
                st = np.array([[np.nan if v is None else v for v in m["measures"][meas]["weekly"].get(a, [])][:len(keys)] for m in runs], dtype=float)
                series.append({"name": f"{label} · simulation prediction", "y": [_r(v, 3) for v in np.nanmean(st, 0)], "band": [[_r(v, 3) for v in np.nanquantile(st, 0.05, 0)], [_r(v, 3) for v in np.nanquantile(st, 0.95, 0)]], "source": "baseline", "arm": label})
                if rw:
                    series.append({"name": f"{label} · actual outcome", "y": [_r(rw[a][pos[x]], 3) if x in pos else None for x in xs], "source": "actual", "arm": label, "dashed": a == "0"})
                for sid, rs in alt_runs.items():
                    sa = np.array([[np.nan if v is None else v for v in m["measures"][meas]["weekly"].get(a, [])][:len(keys)] for m in rs], dtype=float)
                    series.append({"name": f"{label} · alternative", "y": [_r(v, 3) for v in np.nanmean(sa, 0)], "source": "alternative", "arm": label})
            out.append({"id": c["id"], "type": "line", "title": c["title"], "x_label": "week", "y_label": c.get("y_label", ""), "x": xs, "series": series, "note": c.get("note", "")})
        elif c["type"] == "cumulative_attrition":
            weeks = runs[0]["cumulative_attrition_pct"]["weeks"]
            series = []
            rc = ref.get("cumulative_attrition_pct") or {}
            for a, label in arms.items():
                st = np.array([m["cumulative_attrition_pct"][a] for m in runs], dtype=float)
                series.append({"name": f"{label} · simulation prediction", "y": [_r(v, 3) for v in st.mean(0)], "band": [[_r(v, 3) for v in np.quantile(st, 0.05, 0)], [_r(v, 3) for v in np.quantile(st, 0.95, 0)]], "source": "baseline", "arm": label})
                if rc.get(a):
                    ys = rc[a]
                    series.append({"name": f"{label} · actual outcome", "y": [ys[min(i, len(ys) - 1)] if i < len(ys) else None for i in range(len(weeks))], "source": "actual", "arm": label, "dashed": a == "0"})
                for sid, rs in alt_runs.items():
                    sa = np.array([m["cumulative_attrition_pct"][a] for m in rs], dtype=float)
                    series.append({"name": f"{label} · alternative", "y": [_r(v, 3) for v in sa.mean(0)], "source": "alternative", "arm": label})
            out.append({"id": c["id"], "type": "line", "title": c["title"], "x_label": "week ending", "y_label": "% who left", "x": weeks, "series": series, "note": c.get("note", "")})
    return out


def results_view(ctx: InstanceContext) -> dict[str, Any]:
    from ..evaluation.results import base_document, run_docs
    doc = base_document(ctx)
    ev_path = ctx.runs_dir / "evaluation.json"
    ev = json.loads(ev_path.read_text()) if ev_path.exists() else {}
    proto = ctx.yaml("evaluation/protocol.yaml")
    st = proto.get("story") or {}
    base = doc["scenarios"]["baseline"]; alt = doc["scenarios"].get("alternative")
    idx = ev.get("metric_index") or {}
    comps = ev.get("comparators") or {}
    order = [c for c in (proto.get("comparator_order") or comps.keys()) if c in comps]
    alt_row = next((r for r in ev.get("scenario_comparison") or [] if alt and r["scenario"] == alt["id"]), None)
    doc["design"] = st.get("design", "")
    sources = [{"id": "actual", "label": f"{base['title']} · actual outcome", "kind": "actual", "kind_label": "Actual outcome (actual data)", "short": "Actual outcome", "scenario": base["id"], "note": ev.get("reference_source", "")},
               {"id": "baseline", "label": f"{base['title']} · simulation prediction", "kind": "simulated", "kind_label": "Simulation prediction", "short": "Simulation prediction", "scenario": base["id"],
                "runs": (ev.get("protocol") or {}).get("seeds"), "note": f"Mean over {(ev.get('protocol') or {}).get('seeds', '?')} runs; ranges cover the middle 90% of runs."}]
    if alt:
        sources.append({"id": "alternative", "label": f"{alt['title']} · simulation prediction", "kind": "simulated", "kind_label": "Alternative simulation prediction", "short": alt["short_title"], "scenario": alt["id"],
                        "runs": len((alt_row or {}).get("seeds", [])), "note": f"Mean over {len((alt_row or {}).get('seeds', []))} runs with the same seeds as the simulation of what happened."})
    metrics = []
    for spec in proto["metrics"]:
        e = idx.get(spec["id"]) or {}
        am = ((alt_row or {}).get("metrics") or {}).get(spec["id"]) or {}
        metrics.append({"id": spec["id"], "label": spec["label"], "unit": spec.get("unit", ""), "better": spec.get("better", "higher"),
                        "values": {"actual": e.get("actual"), "baseline": e.get("simulated"), "alternative": am.get("alternative")},
                        "intervals": {"baseline": e.get("interval")} if e.get("interval") and e["interval"][0] is not None else {},
                        "paired_baseline": am.get("baseline"), "note": spec.get("note", "")})
    story_metrics = [{"id": m["id"], "label": m["label"], "unit": m["unit"], "better": m["better"], "before_actual": (idx.get(m["id"]) or {}).get("before"),
                      "after_actual": m["values"]["actual"], "after_sim": m["values"]["baseline"], "intervals": {"after_sim": (idx.get(m["id"]) or {}).get("interval")}, "note": m["note"]} for m in metrics]
    baselines = [{"id": c, "label": comps[c]["label"], "values": {k: v for k, v in comps[c]["values"].items() if k in idx}} for c in order]
    heads = [e for e in (ev.get("metrics") or []) if e.get("headline")]
    hero_stats = []
    for e in heads:
        hero_stats += [{"label": f"{e['label']}: simulation prediction", "value": e.get("simulated"), "unit": e.get("unit")},
                       {"label": "Actual outcome", "value": e.get("actual"), "unit": e.get("unit")}]
    doc["story"] = {"before": {"label": st.get("before_label", "Before the change"), "sublabel": st.get("before_sublabel", "")},
                    "change": {"label": st.get("change_label", ""), "description": st.get("change_description", ""), "stats": st.get("change_stats", [])},
                    "after": {"label": st.get("after_label", "After the change"), "sublabel": st.get("after_sublabel", "")},
                    "columns": {"before_actual": "Actual outcome", "after_actual": "Actual outcome", "after_sim": "Simulation prediction"},
                    "metrics": story_metrics, "chart": st.get("chart"), "baselines": baselines, "baseline_basis": "outcome",
                    "comparator_explanation": {"paragraphs": [comps[c].get("description", "") for c in order if comps[c].get("description")], "formula": st.get("comparator_formula", ""),
                                               "sources": st.get("comparator_sources", [])},
                    "fidelity": [x for e in heads for x in ({"label": f"{e['label']}: simulation", "value": e.get("simulated"), "unit": e.get("unit")},
                                                             {"label": "Actual", "value": e.get("actual"), "unit": e.get("unit")},
                                                             {"label": f"Best other prediction ({ev.get('comparator_labels', {}).get(e.get('best_comparator'), '')})",
                                                              "value": (e.get("comparators") or {}).get(e.get("best_comparator")), "unit": e.get("unit")})]}
    hero = {"kicker": st.get("hero_kicker", "Simulation compared with the experiment"), "stats": hero_stats, "claim": st.get("claim", ""), "chart": st.get("chart")}
    if alt and alt_row:
        hs = []
        for mid in st.get("alternative_metrics", []):
            am = alt_row["metrics"].get(mid) or {}
            lab = (idx.get(mid) or {}).get("label", mid); unit = (idx.get(mid) or {}).get("unit", "")
            hs.append({"label": lab, "value": f"{am.get('baseline')} → {am.get('alternative')}" + (f" {unit}" if unit else ""), "unit": ""})
        hero["alternative"] = {"kicker": f"Alternative: {alt['short_title']}", "stats": hs, "text": st.get("alternative_text", "")}
    doc.update({"sources": sources, "metrics": metrics, "effects": [], "charts": ev.get("charts", []), "hero": hero,
                "evaluation": {"generated": ev.get("generated"), "protocol": ev.get("protocol")}})
    return doc
