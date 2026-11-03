"""Print each Economic Index release's structure: the task or occupation facets available for Claude.ai conversations,
their row counts and the share left unclassified. An audit of the raw files; nothing is written.

  python instances/aei_tasks/ingest/audit/inspect_releases.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"


def main() -> None:
    for name in ("release_2025_02_10/onet_task_mappings.csv", "release_2025_03_27/task_pct_v2.csv"):
        d = pd.read_csv(RAW / name)
        print("=====", name, d.shape, list(d.columns))
        print(d.sort_values(d.columns[-1], ascending=False).head(5).to_string()[:800])
        print("  sum pct:", d[d.columns[-1]].sum(), "| none-like:", d[d.iloc[:, 0].astype(str).str.lower().isin(["none", "not_classified"])].to_dict("records"))
    for name in ("release_2025_09_15/data/intermediate/aei_raw_claude_ai_2025-08-04_to_2025-08-11.csv",
                 "release_2026_01_15/data/intermediate/aei_raw_claude_ai_2025-11-13_to_2025-11-20.csv",
                 "release_2026_03_24/data/aei_raw_claude_ai_2026-02-05_to_2026-02-12.csv"):
        d = pd.read_csv(RAW / name, low_memory=False)
        print("=====", name, d.shape, list(d.columns))
        for c in ("geography", "facet", "variable", "level"):
            if c in d:
                print("  ", c, d[c].value_counts().head(12).to_dict())
        g = d[(d.get("geography", "global") == "global") & (d.facet == "onet_task") & (d.variable == "onet_task_pct")] if "facet" in d else d
        print("  global onet_task_pct rows:", len(g), "sum:", g.value.sum() if "value" in g else None)
        print(g.sort_values("value", ascending=False).head(6)[["cluster_name", "value"]].to_string()[:800] if "cluster_name" in g else g.head())
        for f in ("soc_occupation", "onet_occupation", "occupation"):
            if "facet" in d and (d.facet == f).any():
                print("  facet", f, d[d.facet == f].variable.value_counts().head().to_dict())
    d = pd.read_csv(RAW / "release_2026_06_26/data/aei_claude_ai_2026-06-26.csv", low_memory=False)
    print("===== 2026-06-26", d.shape, list(d.columns))
    print(d.groupby(["date_start", "date_end"]).size().to_dict())
    print(d.category_name.value_counts().to_dict())
    s = d[(d.geo_level == "global") & (d.category_name == "soc_occupation") & (d.metric_id == "pct")]
    print(s.groupby(["date_start", "hierarchy_level"]).value.agg(["count", "sum"]).to_string())
    print(s[s.hierarchy_level == 1].sort_values("value", ascending=False).head(25)[["date_start", "node_name", "node_external_id", "value"]].to_string())
    o = d[(d.geo_level == "global") & (d.category_name == "onet") & (d.metric_id == "pct") & (d.hierarchy_level == 0)]
    print("onet task level rows by month:", o.groupby("date_start").value.agg(["count", "sum"]).to_dict())


if __name__ == "__main__":
    main()
