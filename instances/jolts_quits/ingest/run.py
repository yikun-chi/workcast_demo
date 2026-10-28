"""Normalize the JOLTS responses into monthly tables.

Reads data/raw/bls/*.json (written by ingest/fetch.py) and writes data/normalized/:

  jolts_monthly.parquet   month, industry, industry_label, element, value     every series, not seasonally adjusted
  series.parquet          series_id (industry code), label, level (supersector or sector), parent
  summary.json            Overview facts and charts

Values are as published in the current vintage (revisions included); the BLS footnote "P" (preliminary) is kept as a
flag. Nothing here is fitted.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import importlib.util

_spec = importlib.util.spec_from_file_location("jolts_fetch", Path(__file__).with_name("fetch.py"))
_fetch = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_fetch)  # type: ignore[union-attr]
INDUSTRIES, ELEMENTS = _fetch.INDUSTRIES, _fetch.ELEMENTS

# The industries scored: the published sectors that together make up total nonfarm (no aggregate counted twice).
SCORED = ["110099", "230000", "320000", "340000", "420000", "440000", "480099", "510000", "520000", "530000", "540099", "610000", "620000",
          "710000", "720000", "810000", "910000", "923000", "929000"]


def log(msg: str) -> None:
    print(f"[jolts_quits ingest] {msg}", flush=True)


def main(ctx) -> None:
    raw, out = ctx.data_raw / "bls", ctx.data_normalized
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for f in sorted(raw.glob("jolts_*.json")):
        for s in json.loads(f.read_text())["response"]["Results"]["series"]:
            sid = s["seriesID"]
            ind, el = sid[3:9], sid[-3:]
            for x in s["data"]:
                if not x["period"].startswith("M") or x["period"] == "M13" or x["value"] in ("-", ""):
                    continue
                rows.append({"month": pd.Timestamp(int(x["year"]), int(x["period"][1:]), 1), "industry": ind, "element": el, "value": float(x["value"]),
                             "preliminary": any(fn.get("code") == "P" for fn in x.get("footnotes", []) if fn)})
    d = pd.DataFrame(rows).drop_duplicates(["month", "industry", "element"]).sort_values(["industry", "element", "month"]).reset_index(drop=True)
    d["industry_label"] = d.industry.map(INDUSTRIES)
    d.to_parquet(out / "jolts_monthly.parquet", index=False)
    meta = pd.DataFrame({"series_id": list(INDUSTRIES), "label": list(INDUSTRIES.values())})
    meta["scored"] = meta.series_id.isin(SCORED)
    meta.to_parquet(out / "series.parquet", index=False)
    span = d.groupby(["industry", "element"]).month.agg(["min", "max", "size"])
    log(f"{len(d):,} values, {d.industry.nunique()} industries, {d.month.min().date()} .. {d.month.max().date()}; "
        f"shortest series {int(span['size'].min())} months")
    q = d[(d.element == "QUR")].pivot_table(index="month", columns="industry", values="value")
    tot = q["000000"]
    facts = [{"label": "Industries scored", "value": len(SCORED), "unit": ""},
             {"label": "Months of data", "value": int(q.shape[0]), "unit": ""},
             {"label": "Total nonfarm quits rate, latest month (%, not seasonally adjusted)", "value": float(tot.dropna().iloc[-1]), "unit": "%"}]
    chart = {"id": "quits_rate", "type": "line", "title": "Quits rate, total nonfarm (% of employment, not seasonally adjusted)", "x_label": "", "y_label": "%",
             "x": [str(m.date()) for m in tot.index], "series": [{"name": "Total nonfarm", "y": [None if pd.isna(v) else float(v) for v in tot]}],
             "note": "Actual outcome: BLS JOLTS, current vintage."}
    summary = {"title": "Quits by industry (BLS JOLTS)", "period": f"{d.month.min().date()} .. {d.month.max().date()}", "facts": facts,
               "org": {"units": [{"id": f"ou:{i}", "label": INDUSTRIES[i]} for i in SCORED], "roles": [], "systems": []}, "charts": [chart],
               "generated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from orgsim.instances import get_instance
    main(get_instance("jolts_quits"))
