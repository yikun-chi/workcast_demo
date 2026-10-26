"""Refresh comparison calculations and presentation from saved predictions, without rerunning or fitting the model."""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from orgsim.instances import get_instance
from orgsim.worlds import workforce as W


def main():
    ctx = get_instance("trip")
    path = ctx.runs_dir / "evaluation.json"
    doc = json.loads(path.read_text())
    proto = ctx.yaml("evaluation/protocol.yaml")
    specs = {m["id"]: m for m in proto["metrics"]}
    for m in doc["metrics"]:
        spec = specs[m["id"]]
        m["label"] = spec["label"]
        m["baselines"] = W.comparison_values(ctx, spec)
        m["baseline"] = m["baselines"].get("zero_effect", next(iter(m["baselines"].values()), None))
        m["baseline_errors"] = {k: round(abs(v - m["actual"]), 4) for k, v in m["baselines"].items() if v is not None and m["actual"] is not None}
        if m["id"] in doc["headline"]:
            doc["headline"][m["id"]].update(label=m["label"], baseline=m["baseline"])
    metrics = [json.loads((ctx.runs_dir / "evaluation" / rid / "metrics.json").read_text()) for rid in doc["run_ids"]["evaluation"]]
    ref = json.loads((ctx.root / proto["reference"]).read_text())
    doc["charts"] = W._charts(metrics, ref, {str(k): v for k, v in proto["arms"].items()}, doc["paired_comparison"], doc["metrics"])
    from orgsim.scenarios import load_scenario
    for key in ("scenario_comparison", "paired_comparison"):
        for row in doc.get(key, []):
            row["title"] = load_scenario(ctx, row["scenario"]).get("short_title", row["title"])
    doc["comparators"] = W.attrition_comparators(ctx)
    doc["protocol"]["freeze_rule"] = ctx.meta["evaluation"]["freeze_rule"]
    doc["protocol"]["design"] = proto["design"]
    path.write_text(json.dumps(doc, indent=1))
    # Overview labels use the same observed population, without rebuilding it.
    import pandas as pd
    spec = importlib.util.spec_from_file_location("trip_ingest", ctx.root / "ingest/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    pop = pd.read_parquet(ctx.data_normalized / "population.parquet")
    summary = mod.build_summary(pop, ref)
    (ctx.data_normalized / "summary.json").write_text(json.dumps(summary, indent=1))
    print("Trip presentation refreshed from saved predictions; simulation values unchanged.")


if __name__ == "__main__":
    main()
