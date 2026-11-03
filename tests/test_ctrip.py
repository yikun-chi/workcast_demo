"""Ctrip experiment checks. Tests marked `data` need the normalized Ctrip tables and a saved evaluation."""
import importlib.util
import json
import shutil

import numpy as np
import pandas as pd
import pytest

from orgsim.instances import get_instance


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


@pytest.mark.data
def test_prediction_does_not_read_the_experiment_period(monkeypatch):
    """Deleting every week from the experiment onwards leaves twins, calibration, comparators and a run unchanged."""
    from orgsim.scenarios import load_scenario
    from orgsim.store import RunWriter
    from orgsim.worlds.workforce import World
    ctx = get_instance("ctrip")
    ing = _module(ctx.root / "ingest" / "run.py", "ctrip_ingest_test")
    panel = pd.read_parquet(ctx.data_normalized / "panel.parquet")
    pre_only = panel[panel.year_week < ing.T0_WEEK].copy()
    assert len(pre_only) < len(panel)
    spec = json.loads((ctx.calibration_dir / "selection.json").read_text())["selected"]
    pop = pd.read_parquet(ctx.data_normalized / "population.parquet")
    ids = pop.person_id.tolist()
    pd.testing.assert_frame_equal(ing.pre_features(panel, ing.T0_WEEK, spec, ids), ing.pre_features(pre_only, ing.T0_WEEK, spec, ids))
    assert ing.fit_calibration(panel, pop, ing.T0_WEEK, spec) == ing.fit_calibration(pre_only, pop, ing.T0_WEEK, spec)
    comps = _module(ctx.evaluation_dir / "comparators.py", "ctrip_comparators_test")
    full = comps.compute(ctx)
    real_read = pd.read_parquet
    monkeypatch.setattr(comps.pd, "read_parquet", lambda p, *a, **k: pre_only if str(p).endswith("panel.parquet") else real_read(p, *a, **k))
    assert comps.compute(ctx) == full
    # the world reads the population and the 2010 calibration only: two runs with the same seed agree exactly
    sc = load_scenario(ctx, "evaluation")
    out = []
    for k in range(2):
        w = World.from_instance(ctx, sc, 7)
        writer = RunWriter(ctx.id, "evaluation", run_id=f"test-leak-{k}")
        try:
            w.run(writer)
        finally:
            shutil.rmtree(writer.dir, ignore_errors=True)
        out.append(w.metrics["measures"]["log_calls"]["all"])
    assert out[0] == out[1]


@pytest.mark.data
def test_every_protocol_metric_is_scored_against_every_comparator():
    ctx = get_instance("ctrip")
    proto = ctx.yaml("evaluation/protocol.yaml")
    ev = json.loads((ctx.runs_dir / "evaluation.json").read_text())
    assert [m["id"] for m in ev["metrics"]] == [m["id"] for m in proto["metrics"]]
    for m in ev["metrics"]:
        assert m["simulated"] is not None and m["actual"] is not None and m["n_seeds"] == proto["seeds"]["count"]
        assert m["comparators"] and all(np.isfinite(v) for v in m["comparators"].values())
        assert set(m["comparator_errors"]) == set(m["comparators"])
    vi = json.loads((ctx.runs_dir / "value_inputs.json").read_text())
    for f in vi["figures"]:
        node = ev
        for part in f["path"].split("."):
            node = node[part]
        assert node == f["value"]


def test_gender_enters_no_twin_expression():
    ctx = get_instance("ctrip")
    text = (ctx.calibration_dir / "dynamics.yaml").read_text()
    assert "female" not in text and "men" not in text.split()
