"""Federal workforce checks. Tests marked `data` need the normalized OPM tables and a saved evaluation."""
import importlib.util
import json
import shutil

import numpy as np
import pandas as pd
import pytest

from orgsim.instances import get_instance


def _ingest():
    ctx = get_instance("fedwork")
    spec = importlib.util.spec_from_file_location("fedwork_ingest_test", ctx.root / "ingest" / "run.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return ctx, mod


@pytest.mark.data
def test_prediction_does_not_read_records_after_the_cutoff(monkeypatch):
    """Deleting every record effective or published after the held-out cutoff leaves the twins, the comparators and
    the simulation's expected separations unchanged."""
    from orgsim.store import RunWriter
    from orgsim.worlds import workforce_forecast as F
    from orgsim.worlds.workforce import World
    ctx, ING = _ingest()
    proto = ctx.yaml("evaluation/protocol.yaml")
    c = next(x for x in proto["cutoffs"] if x["role"] == "held_out")
    seps = pd.read_parquet(ctx.data_normalized / "separations.parquet")
    heads = pd.read_parquet(ctx.data_normalized / "headcounts.parquet")
    cut = seps[(seps.effective_month <= c["cutoff"]) & (seps.file_month <= c["cutoff"])]
    assert len(cut) < len(seps)
    spec = json.loads((ctx.calibration_dir / "selection.json").read_text())["selected"]
    a, b = ING.build_twins(seps, heads, c["cutoff"], spec), ING.build_twins(cut, heads, c["cutoff"], spec)
    pd.testing.assert_frame_equal(a, b)
    saved = pd.read_parquet(ctx.data_normalized / f"twins_{c['cutoff']}.parquet")
    pd.testing.assert_frame_equal(a.reset_index(drop=True), saved.reset_index(drop=True), check_dtype=False)
    comps = F.comparators_module(ctx)
    months = F.scored_months(c["cutoff"], int(proto["score_months"]["first"]), int(proto["score_months"]["count"]))
    groups = sorted(set(ING.agency_groups(heads, c["cutoff"]).values()))
    full = comps.compute(ctx, c["cutoff"], months, groups)
    monkeypatch.setattr(comps, "load", lambda ctx: (cut, heads))
    trunc = comps.compute(ctx, c["cutoff"], months, groups)
    for k in full:
        pd.testing.assert_frame_equal(full[k]["pred"], trunc[k]["pred"])
    # the world reads only the cutoff's twins: one run equals the saved twins' run
    w = World.from_instance(ctx, F.cutoff_scenario(ctx, proto, c), 1)
    writer = RunWriter(ctx.id, "baseline", run_id="test-leak")
    try:
        w.run(writer)
    finally:
        shutil.rmtree(writer.dir, ignore_errors=True)
    assert w.metrics["separations"]["months"][0] > c["cutoff"]


@pytest.mark.data
def test_every_protocol_cutoff_is_scored_against_every_comparator():
    ctx = get_instance("fedwork")
    proto = ctx.yaml("evaluation/protocol.yaml")
    ev = json.loads((ctx.runs_dir / "evaluation.json").read_text())
    assert [w["cutoff"] for w in ev["windows"]] == [c["cutoff"] for c in proto["cutoffs"]]
    for w in ev["windows"]:
        assert set(w["scores"]) == {"simulation", *ev["comparator_labels"]}
        assert all(np.isfinite(v["group_month_wape"]) for v in w["scores"].values())
        assert w["scores"]["simulation"]["actual_total"] > 0
    vi = json.loads((ctx.runs_dir / "value_inputs.json").read_text())
    for f in vi["figures"]:
        node = ev
        for part in f["path"].split("."):
            node = node[int(part)] if isinstance(node, list) else node[part]
        assert node == f["value"]


def test_cohort_offer_moves_acceptors_to_the_effective_month(tmp_path, monkeypatch):
    """A cohort twin offered a certain exit leaves in the offer's effective month and nowhere else."""
    import yaml
    from orgsim import instances as I
    from orgsim.store import RunWriter
    from orgsim.worlds.workforce import World
    root = tmp_path / "toy"
    (root / "data" / "normalized").mkdir(parents=True)
    (root / "calibration").mkdir(); (root / "ontology").mkdir(); (root / "policies").mkdir()
    pd.DataFrame({"person_id": ["a", "b"], "role_id": "r", "org_unit": "u", "team_id": "", "seat": "employee",
                  "headcount": [100, 50], "grp": ["x", "y"]}).to_parquet(root / "data/normalized/population.parquet")
    (root / "calibration/dynamics.yaml").write_text(yaml.safe_dump({"derived": {"takeup_propensity": "0"},
        "hazards": {"quit": {"monthly": "0.0"}}, "offers": {"o": {"accept": "1.0"}}}))
    (root / "calibration/priors.yaml").write_text("parameters: {}\n")
    (root / "ontology/bindings.yaml").write_text("roles: [{id: r}]\nactivities: []\n")
    (root / "policies/seats.yaml").write_text("default: {adapter: rule}\n")
    ctx = I.InstanceContext(id="toy", root=root, meta={"world_type": "workforce"})
    from orgsim.store import runs
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / "runs")
    scn = {"id": "t", "world": {"start": "2025-01-01", "end": "2025-12-31", "count_by": "grp", "work_events": "none",
                                "offers": [{"id": "o", "decide": "2025-02-12", "effective": "2025-09-30", "who": "grp=x"}]}}
    w = World.from_instance(ctx, scn, 1)
    writer = RunWriter("toy", "t", run_id="toy")
    try:
        w.run(writer)
    finally:
        shutil.rmtree(writer.dir, ignore_errors=True)
    sep = w.metrics["separations"]
    assert sep["expected"]["o"] == {"2025-09": [100.0, 0.0]}
    assert sep["realized"]["o"] == {"2025-09": [100.0, 0.0]}
