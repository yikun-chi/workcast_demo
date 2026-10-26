"""Core checks; use pytest -m 'not data' before downloading the datasets."""
from datetime import datetime, timedelta

import numpy as np
import pytest

from orgsim.evaluation import MarkovNextActivity, accuracy, jensen_shannon, interval, coverage
from orgsim.kernel import CapacityPool, Clock, Scheduler
from orgsim.ontology import onet
from orgsim.ontology.schema import Graph, Node, NodeType, schema_graph
from orgsim.policies import Observation
from orgsim.policies.rule import RulePolicy
from orgsim.scenarios.loader import deep_merge
from orgsim.store import RunReader, RunWriter, TraceEvent
from orgsim.worlds.survival import aalen_johansen, week_slot


def test_clock_ticks_hourly():
    c = Clock(start=datetime(2018, 9, 3), end=datetime(2018, 9, 4))
    ticks = sum(1 for _ in c)
    assert ticks == 24 and c.tick == 24


def test_scheduler_orders_events():
    s = Scheduler(); t0 = datetime(2018, 1, 1)
    s.schedule(t0 + timedelta(hours=2), "b"); s.schedule(t0 + timedelta(hours=1), "a")
    assert [e.kind for e in s.due(t0 + timedelta(hours=2))] == ["a", "b"] and len(s) == 0


def test_capacity_queues_overflow():
    pool = CapacityPool(role="ap", headcount=1, actions_per_person_hour=2)
    for i in range(5):
        pool.enqueue(i, arrived_hour=0)
    served = []
    assert pool.drain(0, lambda item, wait: served.append(item)) == 2 and pool.backlog() == 3
    pool.reset_hour(); pool.drain(1, lambda item, wait: served.append(item))
    assert len(served) == 4 and pool.total_wait_hours == 2.0


def test_rule_policy_respects_weights():
    rng = np.random.default_rng(0)
    obs = Observation(agent_id="a", role="r", sim_time="t", options=[{"kind": "do_activity", "target": "x", "weight": 0}, {"kind": "do_activity", "target": "y", "weight": 1}])
    assert all(RulePolicy().decide(obs, rng).target == "y" for _ in range(20))


def test_run_writer_roundtrip(tmp_path, monkeypatch):
    import orgsim.store.runs as runs
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path)
    w = RunWriter("inst", "baseline", run_id="r1", config={"x": 1})
    w.write_event(TraceEvent(tick=0, sim_time=datetime(2018, 1, 1), activity="A", agent_id="u1", attributes={"k": 1}))
    w.close({"events": 1})
    r = RunReader("inst", "baseline", "r1")
    assert len(r.trace()) == 1 and r.json("summary.json")["events"] == 1 and runs.latest_run("inst", "baseline") == "r1"


def test_markov_baseline():
    m = MarkovNextActivity().fit([["a", "b", "c"], ["a", "b", "d"], ["a", "b", "c"]])
    assert m.predict(["a", "b"]) == "c" and abs(m.probs(["b"])["c"] - 2 / 3) < 1e-9


def test_metrics():
    assert accuracy(["a", "b"], ["a", "c"]) == 0.5
    assert jensen_shannon({"a": 1}, {"a": 1}) == 0.0
    lo, hi = interval([1, 2, 3, 4, 5], 0.9); assert lo <= 2 and hi >= 4 and coverage([1, 2, 3], 2)


def test_deep_merge():
    assert deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"b": 9}})["a"] == {"b": 9, "c": 2}


@pytest.mark.data
def test_schema_graph_and_onet():
    g = schema_graph(); assert g.stats()["nodes"] == len(NodeType)
    s = onet.summary(); assert s["occupations"] == 1016 and s["dwas"] == 2087
    g2 = Graph(); g2.add_node(Node(id="x", type=NodeType.ROLE, label="x")); g2.merge(onet.occupation_graph("43-3031.00", include_tasks=False))
    assert g2.stats()["nodes_by_type"]["Occupation"] == 1


def test_aalen_johansen_matches_kaplan_meier_and_splits_causes():
    # 4 observed events (2 of cause a at t=1,3; 2 of cause b at t=2,4) and 2 observations censored at t=2.5 and t=5
    times = np.array([1, 2, 2.5, 3, 4, 5.0]); obs = np.array([1, 1, 0, 1, 1, 0], bool); cause = np.array(list("abxaby"), object)
    F = aalen_johansen(times, obs, cause, grid=np.array([0, 1, 2, 3, 4, 10.0]))
    # hand-computed Kaplan-Meier: S(1)=5/6, S(2)=5/6*4/5=2/3, S(3)=2/3*2/3=4/9, S(4)=4/9*1/2=2/9
    S = 1 - np.array(F["a"]) - np.array(F["b"])
    assert np.allclose(S, [1, 5 / 6, 2 / 3, 4 / 9, 2 / 9, 2 / 9], atol=1e-6)
    assert np.allclose(F["a"], [0, 1 / 6, 1 / 6, 1 / 6 + 2 / 3 / 3, 1 / 6 + 2 / 9, 1 / 6 + 2 / 9], atol=1e-6)
    assert all(np.diff(F["b"]) >= 0) and "x" not in F and "y" not in F
    assert aalen_johansen(times, obs, cause, grid=np.array([10.0]), min_cause=3) == {}


def test_week_slot_payment_runs():
    import pandas as pd
    # first Thursday on/after the 5th (early) and on/after the 23rd (late); other weeks regular
    assert week_slot(pd.Timestamp("2018-09-03"), 5, 23) == "early"       # Thu Sep 6
    assert week_slot(pd.Timestamp("2018-09-10"), 5, 23) == "regular"     # Thu Sep 13
    assert week_slot(pd.Timestamp("2018-09-24"), 5, 23) == "late"        # Thu Sep 27
    assert week_slot(pd.Timestamp("2018-10-01"), 5, 23) == "regular"     # Thu Oct 4 is before the 5th
    assert week_slot(pd.Timestamp("2018-10-08"), 5, 23) == "early"       # Thu Oct 11
    assert week_slot(pd.Timestamp("2018-10-22"), 5, 23) == "late"        # Thu Oct 25


def test_process_calibration_backoff_and_survival_weights():
    from collections import Counter
    from orgsim.worlds.process import Calibration, END
    grid = [0, 24, 48, 96]
    raw = {"quantile_grid": [0.0, 0.5, 0.99], "state_flags": {"g": "G"}, "survival_min_events": 10,
           "families": {"fam": {"share": 1.0, "transitions": {"A|0": {"n": 50, "next": {"B": 0.8, END: 0.2}}, "A|1": {"n": 5, "next": {"C": 1.0}}},
                                "transitions_last": {"A": {"n": 60, "next": {"B": 0.7, "C": 0.1, END: 0.2}}},
                                "transitions2": {"Z|A|0": {"n": 30, "next": {"C": 0.9, END: 0.1}}}, "delays": {"A|B": {"n": 10, "q": [0, 24, 96]}}}},
           "activities": {}, "delays_all": {}, "delays_to": {},
           "survival": {"grid_h": grid, "families": {"fam": {"state": {"A|0": {"n": 50, "F": {"B": [0, 0.4, 0.6, 0.8]}}}, "last": {}}}, "pooled_last": {}},
           "same_user": {"p_same_role_overall": 0.5, "by_pair": {"A|A": {"n": 100, "p": 0.9}}, "by_role": {"r": {"n": 10, "p": 0.3}}},
           "calendar": {"x_early": 5, "x_late": 23, "activities": {"B": {"multipliers": {"early": 1.5, "late": 3.0, "regular": 0.25}}}}}
    c = Calibration(raw)
    # back-off: order-2 row when it has support, else the state row, else last activity (state row A|1 has n < MIN_STATE_N)
    assert c.next_probs("fam", "A", Counter(), prev="Z", order=2)[1] == "state2"
    assert c.next_probs("fam", "A", Counter(), prev="Z", order=1)[1] == "state"
    assert c.next_probs("fam", "A", Counter({"G": 1}), prev="Q", order=2)[1] == "last"
    # Aalen-Johansen conditional CDF: normalised by the plateau, interpolated on the grid
    G = c.gap_cdf("fam", "A", "B", Counter())
    assert G is not None and G[1] == "state" and abs(c.gap_cdf_at(G, None, 24.0) - 0.5) < 1e-9 and abs(c.gap_cdf_at(G, None, 36.0) - 0.625) < 1e-9
    assert abs(c.invert_gap_cdf(G, 0.5) - 24.0) < 1e-9
    masses, beyond = c.day_masses(G, None, 0.0)
    assert abs(masses.sum() + beyond - 1.0) < 1e-9 and abs(masses[0] - 0.5) < 1e-9
    masses_e, tail_e = c.day_masses(G, None, 30.0)      # conditioning removes elapsed mass, retaining the censored tail
    assert masses_e[0] == 0.0 and abs(masses_e.sum() + tail_e - (1 - c.gap_cdf_at(G, None, 30.0))) < 1e-9
    assert abs(tail_e - 0.01) < 1e-9 and c.gap_cdf_at(G, None, 1000) == 0.99
    # calendar multipliers cover 181 days and follow the week slots
    m = c.calendar_mult("B", datetime(2018, 9, 3))
    assert len(m) == 181 and m[0] == 1.5 and m[7] == 0.25 and m[21] == 3.0 and c.calendar_mult("C", datetime(2018, 9, 3)) is None
    # same-user stickiness: pair first, then role, then overall
    assert c.p_same_user("A", "A", "r") == 0.9 and c.p_same_user("A", "B", "r") == 0.3 and c.p_same_user("A", "B", "other") == 0.5


if __name__ == "__main__":
    import pytest, sys
    sys.exit(pytest.main(["-q", __file__]))


def test_workforce_namespace_trait_layer():
    """Trait-layer expressions used by the trip twin v2: std/median/quantile and boolean indexing inside expressions."""
    import numpy as np
    from orgsim.worlds.workforce import _Namespace
    ns = _Namespace(np.random.default_rng(0), 6)
    z = np.array([-2.0, -1.0, 0.0, 1.0, 2.0, 3.0])
    out = ns.eval("(x - mean(x)) / std(x)", {"x": z})
    assert abs(out.mean()) < 1e-9 and abs(out.std() - 1) < 1e-9
    val = ns.eval("exp(0.5 * x) / mean(exp(0.5 * x)[x > median(x)])", {"x": z})
    assert abs(val[z > np.median(z)].mean() - 1.0) < 1e-9 and val[0] < val[-1]
    # value share through (0,0), (2, s2), (5, 1) stays finite for s2 above one
    vs = ns.eval("where(d <= 2, s * d / 2, s + (1 - s) * (minimum(d, 5) - 2) / 3)", {"d": np.array([0, 1, 2, 3, 5, 7.0]), "s": 1.2})
    assert np.allclose(vs, [0, 0.6, 1.2, 1.1333333, 1.0, 1.0]) and np.isfinite(vs).all()


def test_ontology_schema_is_documented():
    from orgsim.ontology.schema import CONCEPTS, RELATIONS, EdgeType
    assert set(CONCEPTS) == set(NodeType) and all(CONCEPTS.values())
    assert set(RELATIONS) == set(EdgeType) and all(RELATIONS.values())
    g = schema_graph()
    ids = {n.id for n in g.nodes}
    assert all(e.source in ids and e.target in ids for e in g.edges)
    assert all(n.properties.get("description") for n in g.nodes) and all(e.properties.get("description") for e in g.edges)
    pairs = {(e.source, e.type, e.target) for e in g.edges}
    assert ("type:Person", "located_at", "type:Location") in pairs and ("type:Person", "hands_off_to", "type:Person") in pairs


@pytest.mark.data
def test_people_graph_and_ego():
    from orgsim.instances import get_instance
    from orgsim.ontology import people
    from orgsim.ontology.system import instance_concepts
    trip = get_instance("trip")
    g = people.people_graph(trip)
    assert g["world_type"] == "workforce" and g["persons_total"] == 1612
    assert {x["type"] for x in g["groups"]} >= {"OrgUnit", "Role", "Location"}
    page = people.people_page(trip, limit=3, sort="age", desc=True)
    assert page["total"] == 1612 and len(page["rows"]) == 3 and page["rows"][0]["age"] >= page["rows"][1]["age"]
    pid = page["rows"][0]["person_id"]
    ego = people.ego_graph(trip, pid, limit=5)
    assert ego["person"]["person_id"] == pid and ego["stats"]["edges_by_type"].get("same_manager", 0) <= 5
    assert ego["stats"]["edges_by_type"].get("located_at") == 2 and ego["stats"]["nodes_by_type"].get("LatentState") == 4
    team = ego["person"]["team_id"]
    assert people.people_page(trip, group=team)["total"] == next(x["size"] for x in g["groups"] if x["id"] == team)
    bpi = get_instance("bpi19")
    e2 = people.ego_graph(bpi, "user_002", limit=3)
    assert e2["stats"]["edges_by_type"].get("hands_off_to", 0) >= 3 and e2["connections"][0]["weight"] >= e2["connections"][-1]["weight"]
    ct, cb = instance_concepts(trip), instance_concepts(bpi)
    assert next(c for c in ct["concepts"] if c["type"] == "Person")["count"] == 1612
    assert next(c for c in cb["concepts"] if c["type"] == "Person")["count"] == 628
    assert next(r for r in ct["relations"] if r["source"] == "Person" and r["type"] == "located_at")["used"]
    assert not next(r for r in cb["relations"] if r["source"] == "Person" and r["type"] == "located_at")["used"]
    assert next(r for r in cb["relations"] if r["type"] == "hands_off_to")["count"] > 0 and ct["stats"]["concepts_used"] < ct["stats"]["concepts"]


@pytest.mark.data
def test_results_view_and_insights(tmp_path, monkeypatch):
    from orgsim.instances import get_instance
    from orgsim.worlds import world_module
    for iid in ("trip", "bpi19"):
        ctx = get_instance(iid)
        d = world_module(ctx).results_view(ctx)
        ids = [s["id"] for s in d["sources"]]
        assert ids[:2] == ["actual", "baseline"] and d["scenarios"]["baseline"]["id"] == "baseline"
        assert d["metrics"] and all(set(m["values"]) >= {"actual", "baseline"} for m in d["metrics"])
        assert all(s.get("source") in ids for c in d["charts"] for s in c["series"])
        story = d.get("story")
        if story:
            assert {"before", "change", "after", "metrics"} <= set(story) and all({"before_actual", "after_actual", "after_sim"} <= set(m) for m in story["metrics"])
    from orgsim.insights.interview import _wf_facts, _wf_topics, _wf_template
    tw = {"role": "customer_service_rep", "offered": False, "arm": 0, "eligible_days": 0, "wfh_days": 0, "quit_week": 9,
          "traits": {"sat_base": 7.0, "wlb_base": 7.0, "commute_2way_h": 2.4, "wfh_pref_z": 0.2}, "final_states": {"job_satisfaction": 5.8, "work_life_balance": 6.9, "relative_deprivation": 0.15, "attachment": 0.3},
          "profile": "Customer service representative. Has children at home. Baseline attachment to the job: low (quit-risk percentile 80)."}
    f = _wf_facts(tw, "Trip.com"); t = _wf_topics(f)
    assert {"long_commute", "not_offered_teammates_were", "satisfaction_down", "attachment_weak", "resigned", "family"} <= set(t)
    a = _wf_template(f, "attrition")
    assert "week 9" in a and "2.4 hours" in a and "teammates" not in a.lower() or "team" in a.lower()
