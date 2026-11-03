"""Normalize the Anthropic Economic Index releases into each SOC major group's share of Claude.ai conversations.

Reads data/raw/ (written by ingest/audit/fetch.py) and writes data/normalized/:

  series.parquet     group, period, date, release, value, se   (value: the group's share of classified conversations;
                     one row per SOC major group and release; period 0 is the first release)
  groups.parquet     group, label, modelled, scored
  task_shares.parquet release, task, pct, mapped               (every task row used, for audit)
  summary.json       Overview facts and charts

Every release is reduced the same way: the global Claude.ai share of conversations by O*NET task; "none" and
"not_classified" are dropped; each task's share is split equally across the O*NET occupations that list that task
(matched on the task text, or for the June 2026 release on the O*NET task ID) and summed by SOC major group; shares are
renormalised over the mapped tasks. Task texts missing from the Index's own O*NET task list (newer O*NET tasks, used by
the June 2026 release) are mapped with the O*NET 31.0 task statements in data/onet/ (CC BY 4.0). The June 2026 release
publishes April and May 2026 separately; the two months are averaged into one release. Groups with no conversations in
any release are left out. Nothing is fitted here.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

RELEASES = [  # (release date, date used for the period: the release date, file, kind); data windows are in the file
    ("2025-02-10", "2025-02-10", "release_2025_02_10/onet_task_mappings.csv", "pct_table"),            # names where published
    ("2025-03-27", "2025-03-27", "release_2025_03_27/task_pct_v2.csv", "pct_table"),
    ("2025-09-15", "2025-09-15", "release_2025_09_15/data/intermediate/aei_raw_claude_ai_2025-08-04_to_2025-08-11.csv", "raw_v3"),
    ("2026-01-15", "2026-01-15", "release_2026_01_15/data/intermediate/aei_raw_claude_ai_2025-11-13_to_2025-11-20.csv", "raw_v3"),
    ("2026-03-24", "2026-03-24", "release_2026_03_24/data/aei_raw_claude_ai_2026-02-05_to_2026-02-12.csv", "raw_v3"),
    ("2026-06-26", "2026-06-26", "release_2026_06_26/data/aei_claude_ai_2026-06-26.csv", "monthly"),       # April and May 2026
]
DROP = {"none", "not_classified"}


def log(msg: str) -> None:
    print(f"[aei_tasks ingest] {msg}", flush=True)


def norm(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().str.rstrip(".")


def task_weights(st: pd.DataFrame) -> pd.DataFrame:
    """Each task text's weight on each SOC major group: an equal split across the occupations that list it."""
    occ = st.drop_duplicates(["task", "O*NET-SOC Code"])
    w = occ.groupby(["task", "major"]).size().rename("n").reset_index()
    w["w"] = w.n / w.groupby("task").n.transform("sum")
    return w


def task_rows(raw: Path, file: str, kind: str, stmts: pd.DataFrame) -> pd.DataFrame:
    """task (normalised text), pct for one release's global Claude.ai conversations."""
    if kind == "pct_table":
        d = pd.read_csv(raw / file)
        return pd.DataFrame({"task": norm(d.task_name), "pct": d.pct.astype(float)})
    if kind == "raw_v3":
        d = pd.read_csv(raw / file, low_memory=False)
        g = d[(d.geography == "global") & (d.facet == "onet_task") & (d.variable == "onet_task_pct")]
        return pd.DataFrame({"task": norm(g.cluster_name), "pct": g.value.astype(float)})
    d = pd.read_csv(raw / file, low_memory=False)
    g = d[(d.geo_level == "global") & (d.category_name == "onet") & (d.metric_id == "pct") & (d.hierarchy_level == 0)].copy()
    by_id = stmts.drop_duplicates("Task ID").set_index("Task ID").task
    g["task"] = pd.to_numeric(g.node_external_id, errors="coerce").map(by_id).fillna(norm(g.node_name))
    months = g.date_start.nunique()
    out = g.groupby("task", as_index=False).value.sum()
    out["pct"] = out.value / months                       # the mean of the published months
    return out[["task", "pct"]]


def main(ctx) -> None:
    raw = ctx.data_raw
    st = pd.read_csv(raw / "release_2025_09_15/data/intermediate/onet_task_statements.csv")
    st["task"] = norm(st.Task)
    st["major"] = st["O*NET-SOC Code"].str[:2]
    on = pd.read_csv(ctx.root.parents[1] / "data" / "onet" / "db_31_0_text" / "Task Statements.txt", sep="\t")
    on["task"] = norm(on.Task)
    on["major"] = on["O*NET-SOC Code"].str[:2]
    ids = pd.concat([on[["Task ID", "task"]], st[["Task ID", "task"]]]).drop_duplicates("Task ID")   # O*NET 31.0 first
    soc = pd.read_csv(raw / "release_2025_09_15/data/intermediate/soc_structure.csv")
    titles = soc[soc["Major Group"].notna()].assign(major=lambda x: x["Major Group"].str[:2]).set_index("major")["SOC or O*NET-SOC 2019 Title"].str.replace(" Occupations", "", regex=False).to_dict()
    # each task text's weight on each major group (the Index's own task list; O*NET 31.0 for texts it lacks)
    w_aei = task_weights(st)
    w31 = task_weights(on)
    w = pd.concat([w_aei, w31[~w31.task.isin(set(w_aei.task))]], ignore_index=True)
    rows, audit = [], []
    for p, (rel, start, file, kind) in enumerate(RELEASES):
        t = task_rows(raw, file, kind, ids)
        t = t[~t.task.isin(DROP)]
        t["mapped"] = t.task.isin(set(w.task))
        audit.append(t.assign(release=rel))
        m = t[t.mapped].merge(w[["task", "major", "w"]], on="task")
        share = (m.pct * m.w).groupby(m.major).sum()
        share = share / share.sum()
        unmapped = float(t.loc[~t.mapped, "pct"].sum() / t.pct.sum() * 100)
        log(f"{rel}: {len(t)} tasks, {unmapped:.2f}% of classified share unmapped, {len(share)} major groups")
        for g, v in share.items():
            rows.append({"group": g, "period": p, "date": pd.Timestamp(start), "release": rel, "value": float(v), "se": np.nan})
    s = pd.DataFrame(rows)
    groups_all = sorted(g for g in set(s.group) if s[s.group == g].value.sum() > 0)
    full = pd.MultiIndex.from_product([groups_all, range(len(RELEASES))], names=["group", "period"])
    s = s.set_index(["group", "period"]).reindex(full).reset_index()
    rel_by_p = {p: r for p, (r, *_ ) in enumerate(RELEASES)}
    start_by_p = {p: pd.Timestamp(r[1]) for p, r in enumerate(RELEASES)}
    s["release"] = s.period.map(rel_by_p); s["date"] = s.period.map(start_by_p); s["value"] = s.value.fillna(0.0); s["se"] = np.nan
    s = s[["group", "period", "date", "release", "value", "se"]].sort_values(["group", "period"]).reset_index(drop=True)
    groups = pd.DataFrame({"group": groups_all, "label": [titles.get(g, g) for g in groups_all], "modelled": True, "scored": True})
    out = ctx.data_normalized
    out.mkdir(parents=True, exist_ok=True)
    s.to_parquet(out / "series.parquet", index=False)
    groups.to_parquet(out / "groups.parquet", index=False)
    pd.concat(audit).to_parquet(out / "task_shares.parquet", index=False)
    last = s[s.period == s.period.max()].set_index("group").value.sort_values(ascending=False)
    first = s[s.period == 0].set_index("group").value
    summary = {
        "title": "Claude.ai conversations by occupation group (Anthropic Economic Index)",
        "period": f"releases {RELEASES[0][0]} .. {RELEASES[-1][0]}",
        "facts": [{"label": "Releases", "value": len(RELEASES), "unit": ""}, {"label": "SOC major groups", "value": len(groups_all), "unit": ""},
                  {"label": f"Largest group in the last release ({titles.get(last.index[0], last.index[0])})", "value": round(float(last.iloc[0]) * 100, 1), "unit": "%"}],
        "org": {"units": [{"id": g, "label": titles.get(g, g)} for g in groups_all], "roles": [], "systems": []},
        "charts": [{"id": "groups", "type": "hbar", "title": "Share of classified Claude.ai conversations by occupation group, first and last release (%)",
                    "x": [titles.get(g, g) for g in last.index], "x_label": "", "y_label": "%",
                    "series": [{"name": RELEASES[0][0], "y": [round(float(first.get(g, 0.0)) * 100, 2) for g in last.index]},
                               {"name": RELEASES[-1][0], "y": [round(float(last[g]) * 100, 2) for g in last.index]}], "note": "Tasks mapped to occupations by O*NET task text."}],
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    log(f"{len(groups_all)} groups x {len(RELEASES)} releases")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from orgsim.instances import get_instance
    main(get_instance("aei_tasks"))
