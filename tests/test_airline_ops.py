"""airline_ops: the prediction at a cutoff does not depend on anything that happened after it, and every protocol
cutoff is scored. Both need the normalized BTS tables (and the second the saved evaluation), so they carry the
`data` marker."""
from __future__ import annotations

import dataclasses
import json

import numpy as np
import pandas as pd
import pytest

from orgsim.instances import get_instance

pytestmark = pytest.mark.data


def _ctx():
    ctx = get_instance("airline_ops")
    if not (ctx.data_normalized / "cell_day.parquet").exists():
        pytest.skip("airline_ops normalized data missing (run orgsim ingest airline_ops)")
    return ctx


def _run(ctx, monkeypatch, data, t0: str, seed: int = 7):
    from orgsim.store.runs import RunWriter
    from orgsim.worlds import airline
    monkeypatch.setattr(airline, "load_data", lambda _ctx: data)
    sc = {"id": "leaktest", "world": {"t0": t0, "horizon_days": 14, "paths": 8}, "interventions": []}
    w = airline.World.from_instance(ctx, sc, seed)
    writer = RunWriter(ctx.id, "leaktest", config={"test": True})
    s = w.run(writer)
    writer.close(s.to_json())
    return s.headline


def test_deleting_outcomes_after_the_cutoff_leaves_the_prediction_unchanged(monkeypatch):
    from orgsim.worlds import airline
    ctx = _ctx()
    d = airline.load_data(ctx)
    t0 = "2022-12-26"
    k = d.idx(pd.Timestamp(t0))
    rng = np.random.default_rng(0)
    scrambled = dataclasses.replace(
        d,
        canc=np.concatenate([d.canc[:k], rng.random(d.canc[k:].shape).astype(np.float32) * d.sched[k:]]),
        ontime=np.concatenate([d.ontime[:k], np.zeros_like(d.ontime[k:])]),
        ap_exo=np.concatenate([d.ap_exo[:k], d.ap_n[k:]]))
    a = _run(ctx, monkeypatch, d, t0)
    b = _run(ctx, monkeypatch, scrambled, t0)
    for key in ("carrier_ontime_pct", "carrier_cancel_pct", "airport_ontime_pct", "airport_cancel_pct"):
        assert np.allclose(np.array(a[key][0]), np.array(b[key][0])), key
    # and the outcomes really were different, so the test can fail
    assert not np.allclose(d.canc[k:k + 14], scrambled.canc[k:k + 14])


def test_every_protocol_cutoff_is_scored():
    from orgsim.worlds.airline import protocol_cutoffs
    ctx = _ctx()
    p = ctx.runs_dir / "evaluation.json"
    if not p.exists():
        pytest.skip("no saved evaluation")
    ev = json.loads(p.read_text())
    proto = ctx.yaml("evaluation/protocol.yaml")
    assert proto.get("run_only") is None, "the frozen protocol runs every cutoff"
    expected = [str(c.date()) for c in protocol_cutoffs(proto)]
    assert ev["protocol"]["cutoffs"] == expected
    assert len(ev["protocol"]["dev_cutoffs"]) == int(proto["dev_cutoffs"])
    for w in ev["windows"]:
        n = np.array(w["carrier_sched"], dtype=float)
        a = np.array(w["carrier_ontime"]["actual"], dtype=float)
        s = np.array(w["carrier_ontime"]["simulation"], dtype=float)
        ok = n >= ev["protocol"]["min_weekly_flights"]
        assert ok.any() and np.isfinite(a[ok]).all() and np.isfinite(s[ok]).all(), w["cutoff"]
