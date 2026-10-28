"""orgsim command line.

  orgsim instances
  orgsim validate <instance>
  orgsim ingest <instance>                       # instance ingest module: instances/<id>/ingest/run.py:main(ctx)
  orgsim run <instance> [--scenario baseline] [--seed 1] [--seeds 1,2,3]
  orgsim evaluate <instance> [--scenarios baseline,...]
  orgsim insights <instance> [--n 24] [--model claude-sonnet-5-5]   # simulated interviews -> runs/<id>/insights.json
  orgsim demo [<instance>]                       # ingest + run every scenario + evaluate (what the demo needs)
  orgsim serve [--host 127.0.0.1] [--port 8000]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

from .instances import get_instance, list_instances
from .scenarios import list_scenarios, load_scenario
from .store import RunWriter


def _ingest(ctx) -> None:
    p = ctx.root / "ingest" / "run.py"
    if not p.exists():
        print(f"[{ctx.id}] no ingest/run.py; skipping")
        return
    spec = importlib.util.spec_from_file_location(f"{ctx.id}_ingest", p)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)  # type: ignore[union-attr]
    t = time.time(); mod.main(ctx); print(f"[{ctx.id}] ingest done in {time.time()-t:.1f}s")


def _run(ctx, scenario_id: str, seed: int) -> dict:
    from .worlds import world_class
    scenario = load_scenario(ctx, scenario_id)
    writer = RunWriter(ctx.id, scenario_id, config={"instance": ctx.id, "scenario": scenario, "seed": seed})
    t = time.time()
    world = world_class(ctx).from_instance(ctx, scenario, seed)
    summary = world.run(writer)
    writer.close(summary.to_json() if hasattr(summary, "to_json") else summary)
    print(f"[{ctx.id}] {scenario_id} seed={seed} -> {writer.run_id} ({writer.n_events} events, {time.time()-t:.1f}s)")
    return {"run_id": writer.run_id, "scenario": scenario_id, "seed": seed}


def _evaluate(ctx, scenario_ids: list[str], phase: str = "") -> dict:
    from .worlds import world_module
    t = time.time()
    # phase "dev" scores only the development cutoffs (demand worlds, whose protocol names them); default: every cutoff
    result = world_module(ctx).evaluate(ctx, scenario_ids, **({"phase": phase} if phase else {}))
    print(f"[{ctx.id}] evaluation written ({time.time()-t:.1f}s)")
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="orgsim")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("instances")
    s = sub.add_parser("validate"); s.add_argument("instance")
    s = sub.add_parser("ingest"); s.add_argument("instance")
    s = sub.add_parser("run"); s.add_argument("instance"); s.add_argument("--scenario", default="baseline"); s.add_argument("--seed", type=int, default=1); s.add_argument("--seeds", default="")
    s = sub.add_parser("evaluate"); s.add_argument("instance"); s.add_argument("--scenarios", default=""); s.add_argument("--phase", default="", choices=["", "dev", "all"])
    s = sub.add_parser("insights"); s.add_argument("instance"); s.add_argument("--n", type=int, default=24); s.add_argument("--model", default="")
    s = sub.add_parser("demo"); s.add_argument("instance", nargs="?"); s.add_argument("--skip-ingest", action="store_true")
    s = sub.add_parser("serve"); s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8000); s.add_argument("--reload", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "instances":
        for i in list_instances():
            print(f"{i.id:10s} {i.world_type:10s} {i.meta.get('title','')}")
        return 0
    if a.cmd == "validate":
        from .ontology.bindings import validate
        probs = validate(get_instance(a.instance))
        print("\n".join(probs) if probs else "ontology bindings valid")
        return 1 if probs else 0
    if a.cmd == "ingest":
        _ingest(get_instance(a.instance)); return 0
    if a.cmd == "run":
        ctx = get_instance(a.instance)
        seeds = [int(x) for x in a.seeds.split(",") if x] or [a.seed]
        for sd in seeds:
            _run(ctx, a.scenario, sd)
        return 0
    if a.cmd == "evaluate":
        ctx = get_instance(a.instance)
        ids = [x for x in a.scenarios.split(",") if x] or [s["id"] for s in list_scenarios(ctx)]
        print(json.dumps(_evaluate(ctx, ids, a.phase).get("headline", {}), indent=2, default=str)); return 0
    if a.cmd == "insights":
        from .insights import build_insights
        d = build_insights(get_instance(a.instance), n_per_scenario=a.n, model=a.model or None)
        for role, b in d["scenarios"].items():
            print(f"[{a.instance}] {role}: {b.get('n_interviews', 0)} interviews from run {b.get('run_id')} ({b.get('error') or d['method']})")
        return 0
    if a.cmd == "demo":
        insts = [get_instance(a.instance)] if a.instance else list_instances()
        for ctx in insts:
            if not a.skip_ingest:
                _ingest(ctx)
            for sc in list_scenarios(ctx):
                full = load_scenario(ctx, sc["id"])
                for sd in full.get("seeds", [1]):
                    _run(ctx, sc["id"], int(sd))
            _evaluate(ctx, [s["id"] for s in list_scenarios(ctx)])
            from .insights import build_insights
            build_insights(ctx)
            report_builder = ctx.reports_dir / "build_report.py"
            if report_builder.exists():
                import runpy
                runpy.run_path(str(report_builder), run_name="__main__")
        from . import REPO_ROOT
        docs_builder = REPO_ROOT / "scripts" / "build_validation_docs.py"
        if docs_builder.exists() and all((REPO_ROOT / "runs" / iid / "evaluation.json").exists() for iid in ("trip", "bpi19")):
            import runpy
            runpy.run_path(str(docs_builder), run_name="__main__")
        return 0
    if a.cmd == "serve":
        import uvicorn
        uvicorn.run("orgsim.server.app:app", host=a.host, port=a.port, reload=a.reload)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
