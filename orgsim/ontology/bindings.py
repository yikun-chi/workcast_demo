"""Instance ontology bindings: instances/<id>/ontology/bindings.yaml -> Graph (merged with O*NET subgraphs).

bindings.yaml schema (all lists optional):

organization: {id, label, properties}
org_units:      [{id, label, parent?, location?, properties?}]
roles:          [{id, label, onet_code, org_unit?, headcount?, properties?}]
persons:        [{id, label, role, org_unit?, location?, properties?}]        # archetypes or individuals
locations:      [{id, label, properties?}]                                    # offices, homes, sites (located_at)
activities:     [{id, label, roles: [role ids], dwa_ids: [..], task_ids: [..], system?: id,
                  produces?: artifact id, properties?}]
process_edges:  [{from: activity id, to: activity id, properties?}]    # precedes
systems:        [{id, label, capabilities: [{id, label, properties?}], properties?}]
artifacts:      [{id, label, properties?}]
external_actors:[{id, label, interacts_with: [activity ids], properties?}]
relationships:  [{type: shares_office|friend_of|reports_to|same_manager|located_at, source, target, properties?}]
policies:       [{id, label, affects: [node ids], properties?}]
latent_states:  [{id, label, person?: id, properties?}]
"""
from __future__ import annotations

from typing import Any

from ..instances import InstanceContext
from . import onet
from .schema import Edge, EdgeType, Graph, Node, NodeType


def _props(d: dict[str, Any], *skip: str) -> dict[str, Any]:
    p = dict(d.get("properties") or {})
    for k, v in d.items():
        if k not in skip and k != "properties":
            p.setdefault(k, v)
    return p


def build_graph(ctx: InstanceContext, include_onet: bool = True, include_tasks: bool = False) -> Graph:
    b = ctx.yaml("ontology/bindings.yaml")
    g = Graph()
    org = b.get("organization") or {"id": f"org:{ctx.id}", "label": ctx.meta.get("title", ctx.id)}
    org_id = org["id"]
    g.add_node(Node(id=org_id, type=NodeType.ORGANIZATION, label=org["label"], properties=_props(org, "id", "label")))

    for loc in b.get("locations", []):
        g.add_node(Node(id=loc["id"], type=NodeType.LOCATION, label=loc["label"], properties=_props(loc, "id", "label")))

    for u in b.get("org_units", []):
        g.add_node(Node(id=u["id"], type=NodeType.ORG_UNIT, label=u["label"], properties=_props(u, "id", "label", "parent", "location")))
        g.add_edge(Edge(source=u["id"], target=u.get("parent") or org_id, type=EdgeType.PART_OF))
        g.add_edge(Edge(source=u.get("parent") or org_id, target=u["id"], type=EdgeType.HAS))
        if u.get("location"):
            g.add_edge(Edge(source=u["id"], target=u["location"], type=EdgeType.LOCATED_AT))

    occ_codes: set[str] = set()
    for r in b.get("roles", []):
        g.add_node(Node(id=r["id"], type=NodeType.ROLE, label=r["label"], properties=_props(r, "id", "label")))
        if r.get("org_unit"):
            g.add_edge(Edge(source=r["id"], target=r["org_unit"], type=EdgeType.MEMBER_OF))
        code = r.get("onet_code")
        if code:
            occ_codes.add(code)
            g.add_edge(Edge(source=r["id"], target=f"onet:{code}", type=EdgeType.BOUND_TO))

    for p in b.get("persons", []):
        g.add_node(Node(id=p["id"], type=NodeType.PERSON, label=p["label"], properties=_props(p, "id", "label", "role", "org_unit", "location")))
        if p.get("role"):
            g.add_edge(Edge(source=p["id"], target=p["role"], type=EdgeType.HAS_ROLE))
        if p.get("org_unit"):
            g.add_edge(Edge(source=p["id"], target=p["org_unit"], type=EdgeType.MEMBER_OF))
        if p.get("location"):
            g.add_edge(Edge(source=p["id"], target=p["location"], type=EdgeType.LOCATED_AT))

    for s in b.get("systems", []):
        g.add_node(Node(id=s["id"], type=NodeType.SYSTEM, label=s["label"], properties=_props(s, "id", "label", "capabilities")))
        for c in s.get("capabilities", []):
            g.add_node(Node(id=c["id"], type=NodeType.CAPABILITY, label=c["label"], properties=_props(c, "id", "label")))
            g.add_edge(Edge(source=s["id"], target=c["id"], type=EdgeType.PROVIDES))

    for a in b.get("artifacts", []):
        g.add_node(Node(id=a["id"], type=NodeType.ARTIFACT, label=a["label"], properties=_props(a, "id", "label")))

    dwa_ids: set[str] = set()
    for a in b.get("activities", []):
        g.add_node(Node(id=a["id"], type=NodeType.ACTIVITY, label=a["label"], properties=_props(a, "id", "label", "roles", "dwa_ids", "task_ids", "system", "capability", "produces")))
        for role in a.get("roles", []):
            g.add_edge(Edge(source=role, target=a["id"], type=EdgeType.PERFORMS))
        for d in a.get("dwa_ids", []):
            dwa_ids.add(d)
            g.add_edge(Edge(source=a["id"], target=f"dwa:{d}", type=EdgeType.MAPS_TO))
        for t in a.get("task_ids", []):
            g.add_edge(Edge(source=a["id"], target=f"task:{t}", type=EdgeType.MAPS_TO))
        if a.get("capability"):
            g.add_edge(Edge(source=a["id"], target=a["capability"], type=EdgeType.USES))
        elif a.get("system"):
            g.add_edge(Edge(source=a["id"], target=a["system"], type=EdgeType.USES))
        if a.get("produces"):
            g.add_edge(Edge(source=a["id"], target=a["produces"], type=EdgeType.PRODUCES))

    for e in b.get("process_edges", []):
        g.add_edge(Edge(source=e["from"], target=e["to"], type=EdgeType.PRECEDES, properties=_props(e, "from", "to")))

    for x in b.get("external_actors", []):
        g.add_node(Node(id=x["id"], type=NodeType.EXTERNAL_ACTOR, label=x["label"], properties=_props(x, "id", "label", "interacts_with")))
        for a in x.get("interacts_with", []):
            g.add_edge(Edge(source=x["id"], target=a, type=EdgeType.INTERACTS_WITH))

    for rel in b.get("relationships", []):
        g.add_edge(Edge(source=rel["source"], target=rel["target"], type=EdgeType(rel["type"]), properties=_props(rel, "type", "source", "target")))

    for pol in b.get("policies", []):
        g.add_node(Node(id=pol["id"], type=NodeType.POLICY, label=pol["label"], properties=_props(pol, "id", "label", "affects")))
        for t in pol.get("affects", []):
            g.add_edge(Edge(source=pol["id"], target=t, type=EdgeType.AFFECTS))

    for st in b.get("latent_states", []):
        g.add_node(Node(id=st["id"], type=NodeType.STATE, label=st["label"], properties=_props(st, "id", "label", "person")))
        if st.get("person"):
            g.add_edge(Edge(source=st["person"], target=st["id"], type=EdgeType.HAS_STATE))

    if include_onet:
        for code in sorted(occ_codes):
            try:
                g.merge(onet.occupation_graph(code, include_tasks=include_tasks))
            except (FileNotFoundError, KeyError):
                g.add_node(Node(id=f"onet:{code}", type=NodeType.OCCUPATION, label=code, properties={"code": code}))
        # make sure DWAs referenced by activities exist even if their occupation subgraph was skipped
        try:
            h = onet.activity_hierarchy()
            for d in sorted(dwa_ids):
                if not any(n.id == f"dwa:{d}" for n in g.nodes):
                    row = h[h.dwa_id == d]
                    if not row.empty:
                        r = row.iloc[0]
                        g.add_node(Node(id=f"dwa:{d}", type=NodeType.DWA, label=r.dwa, properties={"element_id": d}))
                        g.add_node(Node(id=f"iwa:{r.iwa_id}", type=NodeType.IWA, label=r.iwa, properties={"element_id": r.iwa_id}))
                        g.add_node(Node(id=f"gwa:{r.gwa_id}", type=NodeType.GWA, label=r.gwa, properties={"element_id": r.gwa_id}))
                        g.add_edge(Edge(source=f"dwa:{d}", target=f"iwa:{r.iwa_id}", type=EdgeType.PART_OF))
                        g.add_edge(Edge(source=f"iwa:{r.iwa_id}", target=f"gwa:{r.gwa_id}", type=EdgeType.PART_OF))
        except FileNotFoundError:
            pass
    return g


def validate(ctx: InstanceContext) -> list[str]:
    """Return a list of problems (empty = valid)."""
    b = ctx.yaml("ontology/bindings.yaml")
    problems: list[str] = []
    ids: set[str] = set()
    for key in ("org_units", "roles", "persons", "locations", "activities", "systems", "artifacts", "external_actors", "policies", "latent_states"):
        for item in b.get(key, []):
            if "id" not in item or "label" not in item:
                problems.append(f"{key}: item without id/label: {item}")
            elif item["id"] in ids:
                problems.append(f"duplicate id {item['id']}")
            else:
                ids.add(item["id"])
        for s in b.get("systems", []):
            for c in s.get("capabilities", []):
                ids.add(c["id"])
    try:
        occ = set(onet.occupations().code)
        for r in b.get("roles", []):
            if r.get("onet_code") and r["onet_code"] not in occ:
                problems.append(f"role {r['id']}: unknown O*NET code {r['onet_code']}")
        dw = set(onet.activity_hierarchy().dwa_id)
        for a in b.get("activities", []):
            for d in a.get("dwa_ids", []):
                if d not in dw:
                    problems.append(f"activity {a['id']}: unknown DWA {d}")
    except FileNotFoundError as e:
        problems.append(str(e))
    for a in b.get("activities", []):
        for r in a.get("roles", []):
            if r not in ids:
                problems.append(f"activity {a['id']}: unknown role {r}")
    for e in b.get("process_edges", []):
        for k in ("from", "to"):
            if e.get(k) not in ids:
                problems.append(f"process edge references unknown activity {e.get(k)}")
    for rel in b.get("relationships", []):
        for k in ("source", "target"):
            if rel.get(k) not in ids:
                problems.append(f"relationship references unknown node {rel.get(k)}")
    for key in ("org_units", "persons"):
        for item in b.get(key, []):
            if item.get("location") and item["location"] not in ids:
                problems.append(f"{key} {item.get('id')}: unknown location {item['location']}")
    return problems
