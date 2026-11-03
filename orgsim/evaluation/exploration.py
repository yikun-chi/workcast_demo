"""Matched AI alternatives, stored separately from historical accuracy evaluation."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import uuid

import numpy as np

from .. import REPO_ROOT
from ..instances import get_instance
from ..scenarios import load_scenario
from ..scenarios.assistance import assistance_by_activity
from ..store import RunWriter


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


@lru_cache(maxsize=128)
def _file_hash(path: str, modified: int, size: int) -> str:
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def model_fingerprint(ctx) -> str:
    paths = list(ctx.calibration_dir.glob("*")) + [ctx.root / "ontology/bindings.yaml", ctx.root / "policies/seats.yaml"]
    for directory in ("worlds", "kernel", "policies", "scenarios"):
        paths += list((REPO_ROOT / "orgsim" / directory).glob("*.py"))
    names = ("population.parquet", "teams.parquet") if ctx.world_type == "workforce" else ("events_clean.parquet", "cases_clean.parquet")
    paths += [ctx.data_normalized / name for name in names]
    values = []
    for path in sorted(set(paths)):
        if path.is_file():
            stat = path.stat()
            values.append((str(path.relative_to(REPO_ROOT)), _file_hash(str(path), stat.st_mtime_ns, stat.st_size)))
    return _hash(values)


def _save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, indent=1, allow_nan=False))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _run_one(instance: str, scenario: dict, seed: int) -> dict:
    from ..worlds import world_class
    ctx = get_instance(instance)
    writer = RunWriter(instance, scenario["id"], config={"instance": instance, "scenario": scenario, "seed": seed, "purpose": "exploration"})
    world = world_class(ctx).from_instance(ctx, scenario, seed)
    summary = world.run(writer)
    writer.close(summary.to_json())
    print(f"[{instance}] exploration {scenario['id']} seed={seed} -> {writer.run_id}", flush=True)
    return {"scenario": scenario["id"], "run_id": writer.run_id, "seed": seed, "headline": summary.headline}


def _pair_job(job: dict) -> dict:
    baseline = job.get("baseline_saved") or _run_one(job["instance"], job["baseline"], job["seed"])
    alternative = _run_one(job["instance"], job["alternative"], job["seed"])
    return {"cutoff": job["cutoff"], "seed": job["seed"], "baseline": baseline, "alternative": alternative}


def _saved_process_baselines(ctx, fingerprint: str, evaluation_hash: str, baseline_hash: str) -> dict:
    """Reuse references only when their model and inputs are known to match."""
    path = ctx.runs_dir / "explorations.json"
    saved = json.loads(path.read_text()) if path.exists() else {}
    result = {}
    for comparison in saved.values():
        if (comparison.get("model_hash"), comparison.get("evaluation_hash"), comparison.get("baseline_hash")) != (fingerprint, evaluation_hash, baseline_hash):
            continue
        for pair in comparison["pairs"]:
            baseline = deepcopy(pair["baseline"])
            config_path = ctx.runs_dir / baseline["scenario"] / baseline["run_id"] / "config.json"
            if not config_path.exists():
                continue
            baseline["configuration"] = json.loads(config_path.read_text())["scenario"]
            result[(pair["cutoff"], pair["seed"])] = baseline
    return result


def _behavior(configuration: dict) -> dict:
    return {k: v for k, v in configuration.items() if k not in {"id", "title", "short_title", "summary", "description", "extends", "seeds", "exploration"}}


def _validate_ai_comparison(baseline: dict, alternative: dict) -> None:
    def reference(configuration):
        result = deepcopy(_behavior(configuration))
        result["interventions"] = [iv for iv in result.get("interventions", []) if iv.get("type") != "ai_assist"]
        for key in ("work_events", "work_events_sample"):
            result.get("world", {}).pop(key, None)
        return result
    if reference(baseline) != reference(alternative):
        raise ValueError("The AI comparison must keep the current policy, time period, and staffing. Adjust only AI assumptions; use the other scenarios to explore policy changes.")


def build_exploration(ctx, scenario_id: str, job_id: str | None = None) -> dict:
    job_id = job_id or uuid.uuid4().hex
    try:
        return _build_exploration(ctx, scenario_id, job_id)
    except Exception as error:
        _save(ctx.runs_dir / "exploration_status.json", {"job_id": job_id, "scenario": scenario_id, "state": "failed", "error": str(error)})
        raise


def _build_exploration(ctx, scenario_id: str, job_id: str) -> dict:
    from ..scenarios import scenario_roles
    if scenario_id not in (ctx.meta.get("scenarios") or {}).get("additional_alternatives", []):
        raise ValueError("Choose a named additional alternative")
    alternative = load_scenario(ctx, scenario_id)
    known = {a["id"] for a in ctx.yaml("ontology/bindings.yaml")["activities"]}
    if not assistance_by_activity(alternative.get("interventions") or [], known):
        raise ValueError("This comparison requires an AI-assistance intervention")
    baseline = load_scenario(ctx, next(k for k, role in scenario_roles(ctx).items() if role == "baseline"))
    _validate_ai_comparison(baseline, alternative)
    evaluation_path = ctx.runs_dir / "evaluation.json"
    evaluation = json.loads(evaluation_path.read_text())
    evaluation_hash = hashlib.sha256(evaluation_path.read_bytes()).hexdigest()
    fingerprint = model_fingerprint(ctx)
    config_hash = _hash(alternative)
    status_path = ctx.runs_dir / "exploration_status.json"
    job_id = job_id or uuid.uuid4().hex
    status = {"job_id": job_id, "scenario": scenario_id, "state": "running"}
    ctx.runs_dir.mkdir(parents=True, exist_ok=True)
    lock = ctx.runs_dir / ".exploration.lock"
    handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(handle)
    try:
        _save(status_path, status)
        seeds = list(alternative.get("seeds") or [1])
        if any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seeds) or len(set(seeds)) != len(seeds):
            raise ValueError("Comparison seeds must be distinct non-negative integers")
        cutoffs = [baseline.get("world", {}).get("start")]
        saved = {}
        if ctx.world_type == "process":
            proto = ctx.yaml("evaluation/protocol.yaml")
            seeds, cutoffs = list(proto["seeds"]), list(proto["cutoffs"])
            calibration = json.loads((ctx.calibration_dir / "process.json").read_text())
            if evaluation.get("calibration_sha256") != calibration.get("sha256"):
                raise ValueError("Re-evaluate the current procurement model before exploring alternatives")
            saved = _saved_process_baselines(ctx, fingerprint, evaluation_hash, _hash(baseline))
        else:
            # Preserve the reference policy; sample trace detail for both sides.
            baseline.setdefault("world", {}).update(work_events="sample", work_events_sample=0.1)
        jobs = []
        for cutoff in cutoffs:
            for seed in seeds:
                base, alt = deepcopy(baseline), deepcopy(alternative)
                existing = saved.get((cutoff, seed))
                if ctx.world_type == "process":
                    for scenario in (base, alt):
                        scenario.setdefault("world", {})["t0"] = cutoff
                        scenario["horizon_days"] = evaluation["protocol"]["horizon_days"]
                    if existing and _behavior(existing["configuration"]) != _behavior(base):
                        existing = None
                jobs.append({"instance": ctx.id, "baseline": base, "alternative": alt, "seed": seed, "cutoff": cutoff, "baseline_saved": existing})
        workers = min(2, len(jobs))
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as pool:
            pairs = list(pool.map(_pair_job, jobs))
        if fingerprint != model_fingerprint(ctx) or config_hash != _hash(load_scenario(ctx, scenario_id)):
            raise ValueError("Inputs changed during the comparison; rerun with the saved settings")
        if evaluation_hash != hashlib.sha256(evaluation_path.read_bytes()).hexdigest():
            raise ValueError("The reference evaluation changed during the comparison; rerun")
        result = {"scenario": scenario_id, "generated": datetime.now(timezone.utc).isoformat(), "configuration": alternative,
                  "config_hash": config_hash, "baseline_hash": _hash(load_scenario(ctx, baseline["id"])), "model_hash": fingerprint,
                  "evaluation_hash": evaluation_hash, "seeds": seeds, "cutoffs": cutoffs, "pairs": pairs}
        path = ctx.runs_dir / "explorations.json"
        document = json.loads(path.read_text()) if path.exists() else {}
        document[scenario_id] = result
        _save(path, document)
        _save(status_path, {**status, "state": "complete", "generated": result["generated"]})
        return result
    except Exception as error:
        _save(status_path, {**status, "state": "failed", "error": str(error)})
        raise
    finally:
        lock.unlink(missing_ok=True)


def _metric(pairs: list[dict], key: str, label: str, unit: str, getter, better: str = "lower") -> dict:
    base = [float(getter(p["baseline"]["headline"])) for p in pairs]
    alt = [float(getter(p["alternative"]["headline"])) for p in pairs]
    delta = np.asarray(alt) - np.asarray(base)
    return {"id": key, "label": label, "unit": unit, "better": better,
            "baseline": float(np.mean(base)), "alternative": float(np.mean(alt)), "delta": float(np.mean(delta)),
            "delta_range": [float(np.quantile(delta, .05)), float(np.quantile(delta, .95))]}


def exploration_views(ctx) -> list[dict]:
    path = ctx.runs_dir / "explorations.json"
    saved = json.loads(path.read_text()) if path.exists() else {}
    output = []
    for scenario_id in (ctx.meta.get("scenarios") or {}).get("additional_alternatives", []):
        scenario = load_scenario(ctx, scenario_id)
        view = {"id": scenario_id, "title": scenario.get("short_title", scenario_id), "description": scenario.get("description", ""),
                **scenario.get("exploration", {}), "interventions": scenario.get("interventions", []), "state": "missing", "metrics": []}
        result = saved.get(scenario_id)
        if result:
            eval_path = ctx.runs_dir / "evaluation.json"
            current = (_hash(scenario) == result["config_hash"] and model_fingerprint(ctx) == result["model_hash"] and
                       _hash(load_scenario(ctx, "baseline")) == result["baseline_hash"] and eval_path.exists() and
                       hashlib.sha256(eval_path.read_bytes()).hexdigest() == result["evaluation_hash"])
            view.update(state="ready" if current else "stale", generated=result["generated"], runs=len(result["pairs"]),
                        seeds=result["seeds"], cutoffs=result["cutoffs"])
            if current:
                pairs = result["pairs"]
                metrics = [_metric(pairs, "human_hours", "Human effort for the work performed", "hours", lambda h: h["workload"]["human_hours"])]
                if ctx.world_type == "workforce":
                    metrics += [_metric(pairs, "hours_released", "Hours released per employee over six months", "hours",
                                        lambda h: (h["workload"]["unassisted_hours"] - h["workload"]["human_hours"]) / h["headcount"], "higher"),
                                _metric(pairs, "effort_reduction", "Share of staff time released for other work", "%",
                                        lambda h: 100 * (1 - h["workload"]["human_hours"] / h["workload"]["unassisted_hours"]), "higher")]
                else:
                    metrics += [_metric(pairs, "completion", "Live items completed in 14 days", "%", lambda h: h["completion_rate_14d"], "higher"),
                                _metric(pairs, "cycle", "Median cycle time of completed items", "hours", lambda h: h["median_cycle_hours_completed"]),
                                _metric(pairs, "queue", "Mean wait for human capacity", "hours", lambda h: h["mean_wait_h"]),
                                _metric(pairs, "utilization", "Invoice clerk capacity used", "%", lambda h: 100 * h["utilization"].get("ap_invoice", 0))]
                view["metrics"] = metrics
                view["review_hours"] = float(np.mean([p["alternative"]["headline"]["workload"]["review_hours"] for p in pairs]))
                view["rework_hours"] = float(np.mean([p["alternative"]["headline"]["workload"]["rework_hours"] for p in pairs]))
        output.append(view)
    return output


def report_sections(ctx) -> list[dict]:
    sections = []
    for view in exploration_views(ctx):
        if view["state"] != "ready":
            continue
        lines = [view["description"], "", f"{view['runs']} matched simulation comparisons. No observed AI outcome is available.", "",
                 "| Outcome | Current policy | AI alternative | Difference |", "|---|---:|---:|---:|"]
        for metric in view["metrics"]:
            unit = metric["unit"]
            delta_unit = "pp" if unit == "%" else unit
            lines.append(f"| {metric['label']} | {metric['baseline']:.2f} {unit} | {metric['alternative']:.2f} {unit} | {metric['delta']:+.2f} {delta_unit} |")
        lines += ["", view["assumption_basis"]]
        for intervention in view["interventions"]:
            if intervention.get("type") == "ai_assist":
                lines.append(f"Coverage {intervention['coverage']:.0%}; time saved before review {intervention['time_saved']:.0%}; "
                             f"review effort {intervention['review_overhead']:.0%}; correction rate {intervention['rework_rate']:.0%}; "
                             f"correction effort {intervention['rework_effort']:.0%} of the task's ordinary effort.")
        lines += ["", view["note"], "", " ".join(f"[{source['title']}]({source['url']}). {source['note']}" for source in view.get("sources", []))]
        sections.append({"heading": f"Exploratory alternative: {view['title']}", "body": "\n".join(lines), "exploration": view["id"]})
    return sections
