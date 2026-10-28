"""Normalize the monthly NYC 311 CSVs into one row per service request (the service world's request schema).

  created    when the request was created
  closed     when it was closed (NaT while open, or when the recorded date cannot be a closure, see below)
  org        the responding agency (renamed agencies mapped to their current acronym)
  segment    the complaint type, upper-cased and trimmed so a type is one series across spelling changes

Cleaning rules (counts printed and stored in summary.json):
  1. exact duplicate unique_key rows (from the monthly split) are dropped;
  2. a closed date before the created date, or after the retrieval date, is not a closure: closed = NaT;
  3. requests created after the last complete Monday-week of the retrieval are dropped.
Nothing is fitted here; the world calibrates at each cutoff from requests created before it and closures before it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

AGENCY_MAP = {"DCA": "DCWP", "DOITT": "OTI"}


def log(msg: str) -> None:
    print(f"[nyc311 ingest] {msg}", flush=True)


def main(ctx) -> None:
    raw, norm = ctx.data_raw, ctx.data_normalized
    norm.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ctx.root / "manifests" / "sources.json").read_text())
    retrieved = max(pd.Timestamp(f["retrieved"]).tz_convert(None) for f in manifest["files"])
    parts = []
    for f in sorted(manifest["files"], key=lambda x: x["name"]):
        d = pd.read_csv(raw / f["name"], dtype={"unique_key": "int64", "agency": "string", "complaint_type": "string", "status": "string"},
                        usecols=["unique_key", "created_date", "closed_date", "agency", "complaint_type"])
        d["created"] = pd.to_datetime(d.created_date, errors="coerce", format="ISO8601")
        d["closed"] = pd.to_datetime(d.closed_date, errors="coerce", format="ISO8601")
        parts.append(d[["unique_key", "created", "closed", "agency", "complaint_type"]])
        log(f"{f['name']}: {len(d):,}")
    df = pd.concat(parts, ignore_index=True)
    n_raw = len(df)
    dup = df.duplicated("unique_key")
    df = df[~dup & df.created.notna()]
    bad_before = df.closed < df.created
    bad_after = df.closed > retrieved
    df.loc[bad_before | bad_after, "closed"] = pd.NaT
    last_monday = (retrieved.normalize() - pd.Timedelta(days=retrieved.dayofweek))
    late = df.created >= last_monday
    df = df[~late]
    out = pd.DataFrame({"created": df.created.values, "closed": df.closed.values,
                        "org": df.agency.fillna("(missing)").str.strip().str.upper().replace(AGENCY_MAP).astype("category").values,
                        "segment": df.complaint_type.fillna("(missing)").str.strip().str.upper().astype("category").values,
                        "request_id": df.unique_key.values})
    out = out.sort_values(["created", "request_id"]).reset_index(drop=True)
    out.to_parquet(norm / "requests.parquet", index=False)
    cleaning = {"rows_raw": int(n_raw), "duplicate_keys": int(dup.sum()), "closed_before_created": int(bad_before.sum()),
                "closed_after_retrieval": int(bad_after.sum()), "created_after_last_complete_week": int(late.sum()), "rows": int(len(out)),
                "retrieved": retrieved.isoformat(), "last_complete_week_ends": (last_monday - pd.Timedelta(days=1)).date().isoformat()}
    log(json.dumps(cleaning))

    wk = out.created.dt.to_period("W-SUN").dt.start_time
    weekly = out.groupby(wk).size()
    last = out.created.max()
    recent = out[out.created > last - pd.Timedelta(days=364)]
    top = recent.org.value_counts().head(12)
    hours = (recent.closed - recent.created) / pd.Timedelta(hours=1)
    med = recent.assign(h=hours.fillna(np.inf)).groupby("org", observed=True).h.median().reindex(top.index)
    summary = {
        "title": ctx.meta.get("title", ctx.id), "period": f"{out.created.min().date()} .. {last.date()}",
        "facts": [
            {"label": "Service requests", "value": int(len(out)), "unit": ""},
            {"label": "Agencies", "value": int(out.org.nunique()), "unit": ""},
            {"label": "Complaint types", "value": int(out.segment.nunique()), "unit": ""},
            {"label": "Requests in the last 52 weeks", "value": int(len(recent)), "unit": ""},
            {"label": "Closed (all years)", "value": round(100 * float(out.closed.notna().mean()), 1), "unit": "%"},
        ],
        "cleaning": cleaning,
        "org": {"units": [], "roles": [], "systems": []},
        "charts": [
            {"id": "weekly_requests", "type": "line", "title": "Service requests created per week", "x_label": "week", "y_label": "requests",
             "x": [d.strftime("%Y-%m-%d") for d in weekly.index], "series": [{"name": "Requests", "y": [int(v) for v in weekly.values]}], "note": "All agencies."},
            {"id": "top_agencies", "type": "hbar", "title": "Requests by agency, last 52 weeks", "x_label": "requests", "y_label": "",
             "x": list(top.index), "series": [{"name": "Requests", "y": [int(v) for v in top.values]}], "note": ""},
            {"id": "agency_closure", "type": "hbar", "title": "Median hours to close by agency, last 52 weeks", "x_label": "hours", "y_label": "",
             "x": list(med.index), "series": [{"name": "Median hours", "y": [None if not np.isfinite(v) else round(float(v), 1) for v in med.values]}], "note": "Requests still open count as not yet closed."},
        ],
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (norm / "summary.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    from orgsim.instances import get_instance
    main(get_instance("nyc311"))
