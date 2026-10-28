"""Service world (cfpb_complaints, nyc311): no prediction may depend on data after its cutoff, and every protocol
cutoff must be scored. Both need the normalized data; the second also needs the saved evaluation."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from orgsim.instances import get_instance
from orgsim.worlds import service as sv

INSTANCES = ["cfpb_complaints", "nyc311"]


def _have(iid: str, name: str) -> bool:
    ctx = get_instance(iid)
    return (ctx.data_normalized / "requests.parquet").exists() if name == "data" else (ctx.runs_dir / "evaluation.json").exists()


def _by_name(cal: sv.Calibrated, d: sv.ServiceData, sim: dict) -> dict[str, dict[str, np.ndarray]]:
    names = [d.org_names[o] for o in cal.units.orgs]
    return {k: {n: np.asarray(sim["central"][k][i]) for i, n in enumerate(names)} for k in sim["central"]} | \
           {f"path_{k}": {n: np.asarray(sim["path"][k][i]) for i, n in enumerate(names)} for k in sim["path"]}


@pytest.mark.data
@pytest.mark.parametrize("iid", INSTANCES)
def test_deleting_data_after_the_cutoff_leaves_the_prediction_unchanged(iid: str) -> None:
    if not _have(iid, "data"):
        pytest.skip(f"{iid}: normalized data missing")
    ctx = get_instance(iid)
    cfg, proto = ctx.yaml("calibration/service.yaml"), ctx.yaml("evaluation/protocol.yaml")
    H = int(proto["horizon_weeks"])
    t0 = pd.Timestamp(proto["cutoffs"][len(proto["dev_cutoffs"])])          # the first held-out cutoff
    df = pd.read_parquet(ctx.data_normalized / "requests.parquet")
    cut = df[df.created < t0].copy()                                        # delete every request created after t0 ...
    if "closed" in cut:
        cut.loc[cut.closed >= t0, "closed"] = pd.NaT                         # ... every closure after t0 ...
    if "on_time" in cut:
        deadline = pd.Timedelta(days=float(cfg["on_time"]["deadline_days"]))
        cut.loc[cut.created >= t0 - deadline, "on_time"] = np.nan            # ... and every on-time flag settled after t0
    full_d, cut_d = sv.ServiceData.from_frame(df), sv.ServiceData.from_frame(cut)
    del df, cut
    cal_f, cal_c = sv.calibrate(full_d, t0, cfg, H), sv.calibrate(cut_d, t0, cfg, H)
    assert [full_d.org_names[o] for o in cal_f.units.orgs] == [cut_d.org_names[o] for o in cal_c.units.orgs]
    a, b = _by_name(cal_f, full_d, sv.simulate(cal_f, 1)), _by_name(cal_c, cut_d, sv.simulate(cal_c, 1))
    assert a.keys() == b.keys()
    for k in a:
        for n in a[k]:
            np.testing.assert_allclose(a[k][n], b[k][n], rtol=1e-9, atol=1e-9, equal_nan=True, err_msg=f"{iid} {k} {n}")
    # the comparators see the same history too
    hf, hc = sv.visible_history(full_d, cal_f, cfg, 156), sv.visible_history(cut_d, cal_c, cfg, 156)
    for k in hf:
        np.testing.assert_allclose(hf[k], hc[k], equal_nan=True, err_msg=f"{iid} comparator history {k}")


@pytest.mark.data
@pytest.mark.parametrize("iid", INSTANCES)
def test_every_protocol_cutoff_is_scored(iid: str) -> None:
    if not _have(iid, "evaluation"):
        pytest.skip(f"{iid}: evaluation missing")
    ctx = get_instance(iid)
    proto = ctx.yaml("evaluation/protocol.yaml")
    ev = json.loads((ctx.runs_dir / "evaluation.json").read_text())
    cutoffs = [str(c) for c in proto["cutoffs"]]
    dev = [str(c) for c in proto["dev_cutoffs"]]
    assert [w["cutoff"] for w in ev["windows"]] == cutoffs
    assert dev == cutoffs[:len(dev)] and len(dev) == -(-len(cutoffs) // 4)
    for w in ev["windows"]:
        assert w["split"] == ("dev" if w["cutoff"] in dev else "held_out")
        for key in proto["metrics"]:
            assert key in w["scores"] and w["scores"][key]["n"] > 0, (w["cutoff"], key)
        assert pd.Timestamp(w["cutoff"]) + pd.Timedelta(weeks=int(proto["horizon_weeks"])) <= pd.Timestamp(proto["data_end"]) + pd.Timedelta(days=1)
    assert ev["accuracy"]["held_out"]["volume"]["n_windows"] == len(cutoffs) - len(dev)
