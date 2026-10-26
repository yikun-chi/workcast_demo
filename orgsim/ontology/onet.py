"""O*NET 31.0 loader: occupations, GWA -> IWA -> DWA hierarchy, tasks, task -> DWA links.

Reads the tab-delimited text release under data/onet/db_31_0_text/. Cached per process.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

from .. import DATA_DIR
from .schema import Edge, EdgeType, Graph, Node, NodeType

ONET_DIR = DATA_DIR / "onet" / "db_31_0_text"


def _read(name: str) -> pd.DataFrame:
    p = ONET_DIR / name
    if not p.exists():
        raise FileNotFoundError(f"O*NET file missing: {p}. See data/manifests/onet_31_0.json to re-download.")
    return pd.read_csv(p, sep="\t", dtype=str, keep_default_na=False, encoding="utf-8")


@lru_cache(maxsize=1)
def occupations() -> pd.DataFrame:
    return _read("Occupation Data.txt").rename(columns={"O*NET-SOC Code": "code", "Title": "title", "Description": "description"})


@lru_cache(maxsize=1)
def tasks() -> pd.DataFrame:
    t = _read("Task Statements.txt").rename(columns={"O*NET-SOC Code": "code", "Task ID": "task_id", "Task": "task", "Task Type": "task_type"})
    return t[["code", "task_id", "task", "task_type"]]


@lru_cache(maxsize=1)
def tasks_to_dwas() -> pd.DataFrame:
    return _read("Tasks to DWAs.txt").rename(columns={"O*NET-SOC Code": "code", "Task ID": "task_id", "DWA Element ID": "dwa_id"})[["code", "task_id", "dwa_id"]]


@lru_cache(maxsize=1)
def activity_hierarchy() -> pd.DataFrame:
    """One row per DWA with its IWA and GWA ids and names."""
    d = _read("GWAs to IWAs to DWAs.txt").rename(columns={"GWA Element ID": "gwa_id", "IWA Element ID": "iwa_id", "DWA Element ID": "dwa_id", "DWA Element Name": "dwa"})
    i = _read("GWAs to IWAs.txt").rename(columns={"GWA Element ID": "gwa_id", "IWA Element ID": "iwa_id", "IWA Element Name": "iwa"})[["iwa_id", "iwa"]]
    ref = _read("Content Model Reference.txt").rename(columns={"Element ID": "gwa_id", "Element Name": "gwa"})[["gwa_id", "gwa"]]
    return d.merge(i, on="iwa_id", how="left").merge(ref, on="gwa_id", how="left")


def occupation(code: str) -> dict:
    occ = occupations()
    row = occ[occ.code == code]
    if row.empty:
        raise KeyError(f"unknown O*NET-SOC code {code}")
    r = row.iloc[0]
    t = tasks()[tasks().code == code]
    td = tasks_to_dwas()[tasks_to_dwas().code == code]
    h = activity_hierarchy()
    dwa_ids = sorted(set(td.dwa_id))
    hh = h[h.dwa_id.isin(dwa_ids)]
    return {
        "code": code, "title": r.title, "description": r.description,
        "tasks": t[["task_id", "task", "task_type"]].to_dict("records"),
        "task_to_dwa": td[["task_id", "dwa_id"]].to_dict("records"),
        "dwas": hh[["dwa_id", "dwa", "iwa_id", "iwa", "gwa_id", "gwa"]].drop_duplicates("dwa_id").to_dict("records"),
        "counts": {"tasks": int(len(t)), "dwas": len(dwa_ids), "iwas": int(hh.iwa_id.nunique()), "gwas": int(hh.gwa_id.nunique())},
    }


def occupation_graph(code: str, include_tasks: bool = True) -> Graph:
    """Occupation -> Tasks -> DWAs -> IWAs -> GWAs as a graph."""
    info = occupation(code)
    g = Graph()
    occ_id = f"onet:{code}"
    g.add_node(Node(id=occ_id, type=NodeType.OCCUPATION, label=info["title"], properties={"code": code, "description": info["description"]}))
    for d in info["dwas"]:
        g.add_node(Node(id=f"gwa:{d['gwa_id']}", type=NodeType.GWA, label=d["gwa"], properties={"element_id": d["gwa_id"]}))
        g.add_node(Node(id=f"iwa:{d['iwa_id']}", type=NodeType.IWA, label=d["iwa"], properties={"element_id": d["iwa_id"]}))
        g.add_node(Node(id=f"dwa:{d['dwa_id']}", type=NodeType.DWA, label=d["dwa"], properties={"element_id": d["dwa_id"]}))
        g.add_edge(Edge(source=f"iwa:{d['iwa_id']}", target=f"gwa:{d['gwa_id']}", type=EdgeType.PART_OF))
        g.add_edge(Edge(source=f"dwa:{d['dwa_id']}", target=f"iwa:{d['iwa_id']}", type=EdgeType.PART_OF))
    if include_tasks:
        by_task = {}
        for m in info["task_to_dwa"]:
            by_task.setdefault(m["task_id"], []).append(m["dwa_id"])
        for t in info["tasks"]:
            tid = f"task:{t['task_id']}"
            g.add_node(Node(id=tid, type=NodeType.TASK, label=t["task"], properties={"task_id": t["task_id"], "task_type": t["task_type"], "code": code}))
            g.add_edge(Edge(source=occ_id, target=tid, type=EdgeType.PERFORMS))
            for dwa in by_task.get(t["task_id"], []):
                g.add_edge(Edge(source=tid, target=f"dwa:{dwa}", type=EdgeType.MAPS_TO))
    else:
        for d in info["dwas"]:
            g.add_edge(Edge(source=occ_id, target=f"dwa:{d['dwa_id']}", type=EdgeType.PERFORMS))
    return g


def dwa(dwa_id: str) -> dict:
    h = activity_hierarchy()
    row = h[h.dwa_id == dwa_id]
    if row.empty:
        raise KeyError(f"unknown DWA {dwa_id}")
    return row.iloc[0].to_dict()


def search_dwas(query: str, limit: int = 25) -> list[dict]:
    h = activity_hierarchy()
    q = query.lower()
    hits = h[h.dwa.str.lower().str.contains(q, regex=False)]
    return hits.head(limit)[["dwa_id", "dwa", "iwa", "gwa"]].to_dict("records")


def summary() -> dict:
    h = activity_hierarchy()
    return {
        "version": "31.0", "occupations": int(len(occupations())), "tasks": int(len(tasks())),
        "gwas": int(h.gwa_id.nunique()), "iwas": int(h.iwa_id.nunique()), "dwas": int(h.dwa_id.nunique()),
        "task_dwa_links": int(len(tasks_to_dwas())), "path": str(ONET_DIR),
    }
