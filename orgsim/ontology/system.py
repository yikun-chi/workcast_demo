"""Instance concept graph: the ontology schema as used by one instance, with definitions and counts.

Two different questions are answered by two different graphs, both inside the instance:
  * this module: which concepts the instance uses (Person, Role, Activity, Location, ...), what each means and how
    they connect, with how many of each the instance has; served at /api/instances/{id}/ontology/concepts and drawn
    by the Ontology tab's Concepts view (the Bindings view draws the entity graph from bindings.py);
  * ontology/people.py: who the actual people are and who they are connected to (the data graph), served under
    /api/instances/{id}/people and drawn by the Data tab's People view.
"""
from __future__ import annotations

from typing import Any

from ..instances import InstanceContext
from . import people
from .bindings import build_graph
from .schema import CONCEPTS, RELATIONS, EdgeType, NodeType, schema_graph

RUNTIME = {NodeType.EVENT, NodeType.WORK_ITEM, NodeType.MESSAGE}   # created during runs (trace), never bound in bindings.yaml
ONET = {NodeType.OCCUPATION, NodeType.GWA, NodeType.IWA, NodeType.DWA, NodeType.TASK}
LAYERS = {"bound": "declared in ontology/bindings.yaml or present in the normalized data",
          "onet": "O*NET 31.0 vocabulary merged in through role bindings",
          "runtime": "created by the kernel during a run and stored in the trace"}


def instance_usage(ctx: InstanceContext) -> dict[str, Any]:
    """Node and edge counts per concept and relation: bindings (+ O*NET subgraph) plus the data layer (people, teams, links)."""
    try:
        stats = build_graph(ctx, include_onet=True, include_tasks=False).stats()
    except Exception as e:  # noqa: BLE001  (missing bindings or O*NET files: report, do not fail the page)
        stats = {"nodes_by_type": {}, "edges_by_type": {}, "error": str(e)}
    nodes = dict(stats.get("nodes_by_type", {}))
    edges = dict(stats.get("edges_by_type", {}))
    data = people.usage(ctx)
    for t in ("Person", "OrgUnit", "Location", "Role"):
        if data.get(t):
            nodes[t] = max(nodes.get(t, 0), int(data[t]))   # data layer: real people, teams as well as bound units, locations
    for rel, n in (data.get("person_links") or {}).items():
        edges[rel] = edges.get(rel, 0) + int(n)
    if data.get("Person"):
        edges["has_role"] = edges.get("has_role", 0) + int(data["Person"])
        edges["member_of"] = edges.get("member_of", 0) + int(data["Person"])
        n_states = len(ctx.yaml("ontology/bindings.yaml").get("latent_states", []) or [])
        if n_states:
            edges["has_state"] = edges.get("has_state", 0) + int(data["Person"]) * n_states
    return {"nodes": nodes, "edges": edges, "error": stats.get("error")}


def instance_concepts(ctx: InstanceContext) -> dict[str, Any]:
    g = schema_graph()
    u = instance_usage(ctx)
    concepts, used = [], {}
    for t in NodeType:
        layer = "runtime" if t in RUNTIME else "onet" if t in ONET else "bound"
        n = int(u["nodes"].get(str(t), 0))
        used[str(t)] = n > 0 or layer == "runtime"
        concepts.append({"type": str(t), "description": CONCEPTS[t], "layer": layer, "count": n, "used": used[str(t)]})
    relations = []
    for e in g.edges:
        et = EdgeType(e.type)
        s, t = e.source.removeprefix("type:"), e.target.removeprefix("type:")
        n = int(u["edges"].get(str(et), 0))
        runtime = s in {str(x) for x in RUNTIME} or t in {str(x) for x in RUNTIME}
        relations.append({"source": s, "type": str(et), "target": t, "description": RELATIONS[et], "count": n,
                          "used": used[s] and used[t] and (n > 0 or runtime)})
    return {"instance": ctx.id, "schema": g.to_json(), "concepts": concepts, "relations": relations, "layers": LAYERS, "error": u.get("error"),
            "stats": {"concepts_used": sum(1 for c in concepts if c["used"]), "concepts": len(concepts),
                      "relations_used": sum(1 for r in relations if r["used"]), "relations": len(relations)}}
