"""Data graph: the individuals an instance simulates and how they are connected.

The ontology schema says what a Person *is* and how it *can* relate to units, roles, locations and other people
(`schema.py`). This module answers the other question for one instance: who are the people, and who is each one
connected to. It reads only `data/normalized/*` and `ontology/bindings.yaml`, never run outputs or reference
outcomes, and is generic over world type:

  workforce  one row per employee in population.parquet; connections are team membership (same_manager edges are
             implied by team_id), role, division and the division's location
  market     one row per app (company) in apps.parquet; grouped by app category and use-case segment
  process    one row per user in user_roles.csv; connections are hand-offs (consecutive events on the same case by
             different users) aggregated from events_clean.parquet
  adoption   one row per group (a sector or role) in groups.parquet: a population of simulated adopters, with the
             group's first and last observed share or volume from series.parquet

Served by /api/instances/{id}/people (paged table), /people/graph (groups and links) and /people/{pid}/ego
(one person's neighbourhood as a Graph the ontology viewer can draw).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..instances import InstanceContext
from .schema import Edge, EdgeType, Graph, Node, NodeType

_CACHE: dict[tuple[Any, ...], Any] = {}


def _cached(key: tuple[Any, ...], paths: list[Path], build):
    stamp = tuple((str(p), p.stat().st_mtime_ns if p.exists() else None) for p in paths)
    hit = _CACHE.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    value = build()
    _CACHE[key] = (stamp, value)
    return value


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_float_dtype(out[c]):
            out[c] = out[c].astype(float).round(3)
        elif pd.api.types.is_bool_dtype(out[c]):
            out[c] = out[c].astype(bool)
    return json.loads(out.to_json(orient="records", date_format="iso"))


def _bindings(ctx: InstanceContext) -> dict[str, Any]:
    return ctx.yaml("ontology/bindings.yaml")


def _labels(b: dict[str, Any], key: str) -> dict[str, str]:
    return {x["id"]: x.get("label", x["id"]) for x in b.get(key, [])}


# ----------------------------------------------------------------------------- per world type

def _workforce(ctx: InstanceContext) -> dict[str, Any]:
    pop_p = ctx.data_normalized / "population.parquet"
    teams_p = ctx.data_normalized / "teams.parquet"
    b = _bindings(ctx)
    pop = pd.read_parquet(pop_p)
    teams = pd.read_parquet(teams_p) if teams_p.exists() else pop.groupby(["team_id", "org_unit"]).size().rename("size").reset_index()
    unit_label, role_label = _labels(b, "org_units"), _labels(b, "roles")
    unit_loc = {u["id"]: u.get("location") for u in b.get("org_units", [])}
    loc_label = _labels(b, "locations")

    cols = ["person_id", "role_id", "org_unit", "team_id", "seat", "treat", "managerial", "age", "tenure_years", "grad", "children_ind",
            "commute_hour", "commute_imputed", "volunteer", "prior_performance", "female"]
    persons = pop[[c for c in cols if c in pop.columns]].copy()
    persons.insert(1, "label", persons["person_id"])
    persons["arm"] = np.where(persons["treat"] == 1, "treatment", "control") if "treat" in persons else "n/a"
    persons["role_label"] = persons["role_id"].map(role_label).fillna(persons["role_id"])
    persons["org_unit_label"] = persons["org_unit"].map(unit_label).fillna(persons["org_unit"])
    persons["location"] = persons["org_unit"].map(unit_loc).map(loc_label)

    groups: list[dict[str, Any]] = []
    for u in b.get("org_units", []):
        n = int((pop.org_unit == u["id"]).sum())
        groups.append({"id": u["id"], "type": "OrgUnit", "kind": "division", "label": u["label"], "parent": None, "size": n,
                       "location": loc_label.get(u.get("location")), "properties": {k: v for k, v in (u.get("properties") or {}).items()}})
    for loc in b.get("locations", []):
        groups.append({"id": loc["id"], "type": "Location", "kind": (loc.get("properties") or {}).get("kind", "location"), "label": loc["label"], "parent": None,
                       "size": int(pop.org_unit.isin([u for u, l in unit_loc.items() if l == loc["id"]]).sum()), "properties": loc.get("properties") or {}})
    for r in b.get("roles", []):
        groups.append({"id": r["id"], "type": "Role", "kind": "role", "label": r["label"], "parent": r.get("org_unit"), "size": int((pop.role_id == r["id"]).sum()),
                       "properties": {"onet_code": r.get("onet_code")}})
    for t in teams.itertuples(index=False):
        groups.append({"id": t.team_id, "type": "OrgUnit", "kind": "team", "label": f"Team {t.team_id}", "parent": t.org_unit, "size": int(t.size),
                       "properties": {"offered_wfh": int(getattr(t, "treated", 0)), "managers": int(getattr(t, "managers", 0))}})
    links = [{"source": g["id"], "target": g["parent"], "type": "part_of" if g["kind"] == "team" else "member_of"} for g in groups if g.get("parent")]
    links += [{"source": u["id"], "target": u["location"], "type": "located_at"} for u in b.get("org_units", []) if u.get("location")]
    sizes = teams["size"].to_numpy()
    person_links = [{"type": "same_manager", "basis": "same team_id (teams are synthetic groups of about 10 within a division; the deposit has no team identity)",
                     "count": int((sizes * (sizes - 1) // 2).sum())}]
    person_links.append({"type": "located_at", "basis": "division location", "count": int(persons["location"].notna().sum())})
    return {
        "persons": persons,
        "columns": [{"id": c, "label": l} for c, l in [("person_id", "Person"), ("arm", "Arm"), ("managerial", "Manager"), ("role_label", "Role"), ("org_unit_label", "Division"),
                                                        ("team_id", "Team"), ("age", "Age"), ("tenure_years", "Tenure (y)"), ("commute_hour", "Commute (h, one way)"), ("children_ind", "Children"),
                                                        ("grad", "Graduate degree"), ("volunteer", "Volunteered"), ("prior_performance", "Prior grade"), ("location", "Location"), ("female", "Female")]
                    if c in persons.columns],
        "groups": groups, "links": links, "person_links": person_links,
        "notes": ["Every row is a real trial employee (Harvard Dataverse doi:10.7910/DVN/6X4ZZL); role split within non-managers, team membership and person ids are synthetic.",
                  "Gender is shown because it is in the data; it enters no behavioral function or prompt.",
                  "Teammates (same_manager) are not stored as rows: select a person to see their team."],
        "excluded_from_behavior": ["female"],
    }


def _process(ctx: InstanceContext) -> dict[str, Any]:
    ur_p = ctx.data_normalized / "user_roles.csv"
    b = _bindings(ctx)
    ur = pd.read_csv(ur_p)
    unit_label, role_label = _labels(b, "org_units"), _labels(b, "roles")
    role_unit = {r["id"]: r.get("org_unit") for r in b.get("roles", [])}
    persons = ur.rename(columns={"user": "person_id"}).copy()
    persons.insert(1, "label", persons["person_id"])
    persons["role_id"] = persons["role"]
    persons["role_label"] = persons["role_id"].map(role_label).fillna(persons["role_id"])
    persons["org_unit"] = persons["role_id"].map(role_unit)
    persons["org_unit_label"] = persons["org_unit"].map(unit_label).fillna(persons["org_unit"])
    persons["kind"] = np.select([persons.role_id.eq("batch"), persons.role_id.eq("vendor")], ["batch job", "external (vendor)"], "human")
    if "activity_shares" in persons.columns:
        persons = persons.drop(columns=["activity_shares"])
    groups = [{"id": u["id"], "type": "OrgUnit", "kind": "unit", "label": u["label"], "parent": None, "size": int(persons.org_unit.eq(u["id"]).sum()), "properties": u.get("properties") or {}}
              for u in b.get("org_units", [])]
    groups += [{"id": r["id"], "type": "Role", "kind": "role", "label": r["label"], "parent": r.get("org_unit"), "size": int(persons.role_id.eq(r["id"]).sum()),
                "properties": {"onet_code": r.get("onet_code"), "headcount_bindings": r.get("headcount")}} for r in b.get("roles", [])]
    links = [{"source": g["id"], "target": g["parent"], "type": "member_of"} for g in groups if g.get("parent")]
    ho = _handoffs(ctx)
    person_links = [{"type": "hands_off_to", "basis": "consecutive events on the same case by different users, whole normalized log", "count": int(len(ho)),
                     "total_handoffs": int(ho["weight"].sum()) if len(ho) else 0}]
    return {
        "persons": persons,
        "columns": [{"id": c, "label": l} for c, l in [("person_id", "User"), ("kind", "Kind"), ("role_label", "Role"), ("org_unit_label", "Unit"), ("role_share", "Role share"),
                                                        ("events_train", "Events (train window)"), ("n_activities", "Distinct activities"), ("top_activity", "Top activity"), ("top_activity_share", "Top share")]
                    if c in persons.columns],
        "groups": groups, "links": links, "person_links": person_links,
        "notes": ["Users are the anonymized resource ids of the BPI Challenge 2019 log; roles are inferred from each user's activity mix in the training window.",
                  "Connections are hand-offs: how often a purchase-order item moved from one user to the next."],
        "excluded_from_behavior": [],
    }


def _market(ctx: InstanceContext) -> dict[str, Any]:
    """Companies are the apps OpenRouter ranks; each belongs to an app category (unit) and a use-case segment (role)."""
    b = _bindings(ctx)
    apps = pd.read_parquet(ctx.data_normalized / "apps.parquet")
    unit_label, role_label = _labels(b, "org_units"), _labels(b, "roles")
    seg_role = {(r.get("properties") or {}).get("segment"): r["id"] for r in b.get("roles", [])}
    seg = apps.category.map({"coding": "programming", "creative": "roleplay", "entertainment": "roleplay"}).fillna("market")
    persons = pd.DataFrame({"person_id": "app:" + apps.app_id.astype(str), "label": apps.app_name})
    persons["app_name"] = apps.app_name
    persons["org_unit"] = ("ou:" + apps.category).where(apps.category.isin(["coding", "creative", "productivity", "entertainment"]))
    persons["org_unit_label"] = persons.org_unit.map(unit_label).fillna("Unclassified")
    persons["role_id"] = seg.map(seg_role)
    persons["role_label"] = persons.role_id.map(role_label)
    persons["subcategory"] = apps.subcategory
    persons["first_week"] = apps.first_week.dt.date.astype(str)
    persons["last_week"] = apps.last_week.dt.date.astype(str)
    persons["weeks_ranked"] = apps.weeks_ranked
    persons["peak_billion_tokens"] = (apps.peak_tokens / 1e9).round(2)
    persons = persons.sort_values("peak_billion_tokens", ascending=False).reset_index(drop=True)
    groups = [{"id": u["id"], "type": "OrgUnit", "kind": "unit", "label": u["label"], "parent": None, "size": int(persons.org_unit.eq(u["id"]).sum()), "properties": u.get("properties") or {}}
              for u in b.get("org_units", [])]
    groups += [{"id": r["id"], "type": "Role", "kind": "role", "label": r["label"], "parent": r.get("org_unit"), "size": int(persons.role_id.eq(r["id"]).sum()),
                "properties": {"onet_code": r.get("onet_code"), **(r.get("properties") or {})}} for r in b.get("roles", [])]
    links = [{"source": g["id"], "target": g["parent"], "type": "member_of"} for g in groups if g.get("parent")]
    return {
        "persons": persons,
        "columns": [{"id": c, "label": l} for c, l in [("person_id", "Company"), ("app_name", "App"), ("org_unit_label", "Category"), ("subcategory", "Subcategory"), ("role_label", "Segment"),
                                                        ("first_week", "First ranked"), ("last_week", "Last ranked"), ("weeks_ranked", "Weeks ranked"), ("peak_billion_tokens", "Peak week (billion tokens)")]],
        "groups": groups, "links": links, "person_links": [],
        "notes": ["Each row is an app OpenRouter ranked in a weekly top 200 (OpenRouter Datasets API, CC BY 4.0). Categories come from OpenRouter's app classification; unclassified apps are often one-off jobs.",
                  "Apps are linked to each other only through the models their segments use; select an app to see its category and segment."],
        "excluded_from_behavior": [],
    }


def _adoption(ctx: InstanceContext) -> dict[str, Any]:
    """Each row is a group (a sector, a role, a site): a population of simulated adopters, not one person."""
    groups = pd.read_parquet(ctx.data_normalized / "groups.parquet")
    s = pd.read_parquet(ctx.data_normalized / "series.parquet").sort_values("period")
    cfg = ctx.yaml("calibration/adoption.yaml")
    agents = int(cfg.get("agents_per_group", 1000))
    first = s.dropna(subset=["value"]).groupby("group").first()
    last = s.dropna(subset=["value"]).groupby("group").last()
    share = cfg.get("outcome", "share") == "share"
    fmt = (lambda v: round(float(v) * 100, 2)) if share else (lambda v: round(float(v)))  # noqa: E731
    persons = pd.DataFrame({"person_id": "group:" + groups.group.astype(str), "label": groups.label.astype(str)})
    persons["group_label"] = groups.label.astype(str).to_numpy()
    persons["org_unit"] = ("ou:" + groups.group.astype(str)).to_numpy()
    persons["org_unit_label"] = persons.group_label
    persons["role_id"] = None
    persons["role_label"] = "Population of simulated adopters"
    persons["agents"] = [agents if bool(m) else 0 for m in groups.get("modelled", pd.Series(True, index=groups.index))]
    persons["scored"] = [bool(x) for x in groups.get("scored", pd.Series(True, index=groups.index))]
    persons["first_date"] = [str(pd.Timestamp(first.date.get(g)).date()) if g in first.index else None for g in groups.group]
    persons["first_value"] = [fmt(first.value.get(g)) if g in first.index else None for g in groups.group]
    persons["last_date"] = [str(pd.Timestamp(last.date.get(g)).date()) if g in last.index else None for g in groups.group]
    persons["last_value"] = [fmt(last.value.get(g)) if g in last.index else None for g in groups.group]
    b = _bindings(ctx)
    gs = [{"id": u["id"], "type": "OrgUnit", "kind": "unit", "label": u["label"], "parent": None, "size": int(persons.org_unit.eq(u["id"]).sum()), "properties": u.get("properties") or {}}
          for u in b.get("org_units", [])]
    unit = " (%)" if share else ""
    return {
        "persons": persons,
        "columns": [{"id": c, "label": l} for c, l in [("person_id", "Group"), ("group_label", "Name"), ("agents", "Simulated agents"), ("scored", "Scored"),
                                                        ("first_date", "First period"), ("first_value", f"First value{unit}"),
                                                        ("last_date", "Last period"), ("last_value", f"Last value{unit}")]],
        "groups": gs, "links": [], "person_links": [],
        "notes": ["Each row is a group, simulated as a population of agents that each adopt or not; the values are the published aggregates the simulation is calibrated on and scored against.",
                  "Groups are linked through the economy-wide or site-wide adoption they imitate, not person to person."],
        "excluded_from_behavior": [],
    }


def _handoffs(ctx: InstanceContext) -> pd.DataFrame:
    ev_p = ctx.data_normalized / "events_clean.parquet"

    def build() -> pd.DataFrame:
        if not ev_p.exists():
            return pd.DataFrame(columns=["source", "target", "weight"])
        e = pd.read_parquet(ev_p, columns=["case_id", "resource", "ts_eff", "pos"]).sort_values(["case_id", "ts_eff", "pos"])
        prev = e.groupby("case_id")["resource"].shift()
        m = prev.notna() & e["resource"].notna() & (prev != e["resource"])
        pairs = pd.DataFrame({"source": prev[m].to_numpy(), "target": e.loc[m, "resource"].to_numpy()})
        return pairs.groupby(["source", "target"]).size().rename("weight").reset_index().sort_values("weight", ascending=False)

    return _cached((ctx.id, "handoffs"), [ev_p], build)


def _build(ctx: InstanceContext) -> dict[str, Any]:
    wt = ctx.world_type
    paths = [ctx.root / "ontology" / "bindings.yaml", ctx.data_normalized / "population.parquet", ctx.data_normalized / "teams.parquet", ctx.data_normalized / "user_roles.csv"]
    if wt == "workforce":
        return _cached((ctx.id, "people"), paths, lambda: _workforce(ctx))
    if wt == "process":
        return _cached((ctx.id, "people"), paths, lambda: _process(ctx))
    if wt == "market":
        return _cached((ctx.id, "people"), paths + [ctx.data_normalized / "apps.parquet"], lambda: _market(ctx))
    if wt == "adoption":
        return _cached((ctx.id, "people"), paths + [ctx.data_normalized / "groups.parquet", ctx.data_normalized / "series.parquet"], lambda: _adoption(ctx))
    raise FileNotFoundError(f"no people view for world type {wt!r}")


# ----------------------------------------------------------------------------- public API

def people_graph(ctx: InstanceContext) -> dict[str, Any]:
    d = _build(ctx)
    persons: pd.DataFrame = d["persons"]
    by_group: dict[str, int] = {}
    for g in d["groups"]:
        by_group[g["type"]] = by_group.get(g["type"], 0) + 1
    return {"instance": ctx.id, "world_type": ctx.world_type, "persons_total": int(len(persons)), "columns": d["columns"], "groups": d["groups"], "links": d["links"],
            "person_links": d["person_links"], "notes": d["notes"], "excluded_from_behavior": d["excluded_from_behavior"],
            "stats": {"persons": int(len(persons)), "groups_by_type": by_group, "person_links": {pl["type"]: pl["count"] for pl in d["person_links"]}}}


def people_page(ctx: InstanceContext, offset: int = 0, limit: int = 50, q: str = "", sort: str = "", desc: bool = False, group: str = "") -> dict[str, Any]:
    d = _build(ctx)
    df: pd.DataFrame = d["persons"]
    if group:
        df = df[(df.get("team_id", pd.Series("", index=df.index)) == group) | (df["org_unit"] == group) | (df["role_id"] == group)]
    if q:
        mask = pd.Series(False, index=df.index)
        for c in df.columns:
            mask |= df[c].astype(str).str.contains(q, case=False, regex=False, na=False)
        df = df[mask]
    if sort and sort in df.columns:
        df = df.sort_values(sort, ascending=not desc, na_position="last")
    page = df.iloc[offset: offset + limit]
    return {"total": int(len(df)), "offset": offset, "limit": limit, "columns": [c["id"] for c in d["columns"]], "rows": _records(page)}


def person(ctx: InstanceContext, person_id: str) -> dict[str, Any] | None:
    df: pd.DataFrame = _build(ctx)["persons"]
    row = df[df.person_id == person_id]
    return _records(row)[0] if len(row) else None


def ego_graph(ctx: InstanceContext, person_id: str, limit: int = 40) -> dict[str, Any]:
    """One person's neighbourhood as an ontology-typed Graph: units, role, location, states and connected people."""
    d = _build(ctx)
    df: pd.DataFrame = d["persons"]
    row = df[df.person_id == person_id]
    if row.empty:
        raise KeyError(person_id)
    me = _records(row)[0]
    b = _bindings(ctx)
    groups = {g["id"]: g for g in d["groups"]}
    g = Graph()
    g.add_node(Node(id=person_id, type=NodeType.PERSON, label=person_id, properties={k: v for k, v in me.items() if k not in ("label",) and v is not None}))

    def grp(gid: str | None) -> None:
        if gid and gid in groups and not any(n.id == gid for n in g.nodes):
            x = groups[gid]
            g.add_node(Node(id=gid, type=NodeType(x["type"]), label=x["label"], properties={"kind": x["kind"], "size": x["size"], **{k: v for k, v in (x.get("properties") or {}).items() if v is not None}}))

    role_id, unit, team = me.get("role_id"), me.get("org_unit"), me.get("team_id")
    for gid in (role_id, unit, team):
        grp(gid)
    if role_id in groups:
        g.add_edge(Edge(source=person_id, target=role_id, type=EdgeType.HAS_ROLE))
        if unit in groups:
            g.add_edge(Edge(source=role_id, target=unit, type=EdgeType.MEMBER_OF))
    if team in groups:
        g.add_edge(Edge(source=person_id, target=team, type=EdgeType.MEMBER_OF))
        if unit in groups:
            g.add_edge(Edge(source=team, target=unit, type=EdgeType.PART_OF))
    elif unit in groups:
        g.add_edge(Edge(source=person_id, target=unit, type=EdgeType.MEMBER_OF))
    for u in b.get("org_units", []):
        if u["id"] == unit and u.get("location"):
            grp(u["location"])
            if u["location"] in groups:
                g.add_edge(Edge(source=unit, target=u["location"], type=EdgeType.LOCATED_AT))
                g.add_edge(Edge(source=person_id, target=u["location"], type=EdgeType.LOCATED_AT))
    for st in b.get("latent_states", []):
        g.add_node(Node(id=f"state:{st['id']}", type=NodeType.STATE, label=st["label"], properties=st.get("properties") or {}))
        g.add_edge(Edge(source=person_id, target=f"state:{st['id']}", type=EdgeType.HAS_STATE))
    for pol in b.get("policies", []):
        if role_id in (pol.get("affects") or []):
            g.add_node(Node(id=pol["id"], type=NodeType.POLICY, label=pol["label"], properties=pol.get("properties") or {}))
            g.add_edge(Edge(source=pol["id"], target=role_id, type=EdgeType.AFFECTS))

    connections: list[dict[str, Any]] = []
    if ctx.world_type == "workforce" and team:
        mates = df[(df.team_id == team) & (df.person_id != person_id)]
        for m in _records(mates.head(limit)):
            g.add_node(Node(id=m["person_id"], type=NodeType.PERSON, label=m["person_id"], properties={"role": m.get("role_label"), "arm": m.get("arm"), "managerial": m.get("managerial")}))
            g.add_edge(Edge(source=person_id, target=m["person_id"], type=EdgeType.SAME_MANAGER, properties={"basis": "same team"}))
            connections.append({"person_id": m["person_id"], "type": "same_manager", "role": m.get("role_label"), "arm": m.get("arm")})
    elif ctx.world_type == "process":
        ho = _handoffs(ctx)
        out = ho[ho.source == person_id].rename(columns={"target": "other"}).assign(direction="to")
        inc = ho[ho.target == person_id].rename(columns={"source": "other"}).assign(direction="from")
        both = pd.concat([out[["other", "weight", "direction"]], inc[["other", "weight", "direction"]]]).groupby(["other", "direction"])["weight"].sum().reset_index()
        tot = both.groupby("other")["weight"].sum().sort_values(ascending=False)
        role_of = df.set_index("person_id")["role_label"].to_dict()
        for other in tot.index[:limit]:
            g.add_node(Node(id=str(other), type=NodeType.PERSON, label=str(other), properties={"role": role_of.get(other, "")}))
            for _, r in both[both.other == other].iterrows():
                s, t = (person_id, str(other)) if r.direction == "to" else (str(other), person_id)
                g.add_edge(Edge(source=s, target=t, type=EdgeType.HANDS_OFF_TO, properties={"weight": int(r.weight)}))
            connections.append({"person_id": str(other), "type": "hands_off_to", "role": role_of.get(other, ""), "weight": int(tot[other]),
                                "to": int(both[(both.other == other) & (both.direction == "to")].weight.sum()), "from": int(both[(both.other == other) & (both.direction == "from")].weight.sum())})
    out = g.to_json()
    out.update({"person": me, "connections": connections, "connections_total": len(connections) if ctx.world_type == "workforce" else int(len(tot)) if ctx.world_type == "process" else 0})
    return out


def usage(ctx: InstanceContext) -> dict[str, Any]:
    """Counts the system ontology viewer shows per instance for the data layer (people, groups, person links)."""
    try:
        d = people_graph(ctx)
    except (FileNotFoundError, KeyError):
        return {}
    return {"Person": d["stats"]["persons"], **{f"{t}": n for t, n in d["stats"]["groups_by_type"].items()}, "person_links": d["stats"]["person_links"]}
