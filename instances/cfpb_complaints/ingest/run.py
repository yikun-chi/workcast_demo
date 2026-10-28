"""Normalize the CFPB complaint CSV into one row per complaint (the columns the instance uses).

Writes data/normalized/requests.parquet with the service world's request schema:
  created      date the CFPB received the complaint (day resolution)
  org          the company the complaint was sent to (the servicing organisation)
  segment      the consumer product (the requester segment inside the organisation)
  on_time      1 if the company gave a timely response, 0 if not, NaN while in progress
  channel      how the complaint was submitted
and summary.json for the Overview tab. Nothing is fitted here; the world calibrates at each cutoff from rows
received before it.
"""
from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone

import numpy as np
import pandas as pd

START = pd.Timestamp("2017-01-02")       # first Monday of 2017; the product taxonomy changed on 2017-04-24 (merged below)
# The CFPB renamed several products on 2017-04-24; map the old names to the current ones so a segment is one
# series across the change (https://www.consumerfinance.gov/data-research/consumer-complaints/ "Past product and issue changes").
PRODUCT_MAP = {
    "Credit reporting": "Credit reporting or other personal consumer reports",
    "Credit reporting, credit repair services, or other personal consumer reports": "Credit reporting or other personal consumer reports",
    "Credit card": "Credit card",
    "Credit card or prepaid card": "Credit card",
    "Prepaid card": "Prepaid card",
    "Bank account or service": "Checking or savings account",
    "Checking or savings account": "Checking or savings account",
    "Consumer Loan": "Vehicle loan or lease",
    "Vehicle loan or lease": "Vehicle loan or lease",
    "Payday loan": "Payday loan, title loan, or personal loan",
    "Payday loan, title loan, or personal loan": "Payday loan, title loan, or personal loan",
    "Payday loan, title loan, personal loan, or advance loan": "Payday loan, title loan, or personal loan",
    "Money transfers": "Money transfer, virtual currency, or money service",
    "Virtual currency": "Money transfer, virtual currency, or money service",
    "Money transfer, virtual currency, or money service": "Money transfer, virtual currency, or money service",
    "Other financial service": "Money transfer, virtual currency, or money service",
}


def log(msg: str) -> None:
    print(f"[cfpb_complaints ingest] {msg}", flush=True)


def main(ctx) -> None:
    raw = ctx.data_raw / "complaints.csv.zip"
    norm = ctx.data_normalized
    norm.mkdir(parents=True, exist_ok=True)
    cols = ["Date received", "Product", "Company", "Submitted via", "Timely response?", "Company response to consumer", "Complaint ID"]
    parts = []
    n_raw = 0
    with zipfile.ZipFile(raw) as z, z.open("complaints.csv") as f:
        for ch in pd.read_csv(f, usecols=cols, dtype=str, chunksize=1_000_000):
            n_raw += len(ch)
            ch["created"] = pd.to_datetime(ch["Date received"], errors="coerce")
            ch = ch[ch.created >= START]
            parts.append(pd.DataFrame({
                "created": ch.created.values,
                "org": ch["Company"].fillna("(missing)").values,
                "segment": ch["Product"].map(lambda p: PRODUCT_MAP.get(p, p)).fillna("(missing)").values,
                "on_time": ch["Timely response?"].map({"Yes": 1.0, "No": 0.0}).values,
                "response": ch["Company response to consumer"].fillna("").values,
                "channel": ch["Submitted via"].fillna("").values,
                "request_id": pd.to_numeric(ch["Complaint ID"], errors="coerce").values}))
            log(f"read {n_raw:,} rows")
    df = pd.concat(parts, ignore_index=True)
    dup = df.duplicated("request_id")
    df = df[~dup].sort_values(["created", "request_id"]).reset_index(drop=True)
    for c in ("org", "segment", "response", "channel"):
        df[c] = df[c].astype("category")
    df.to_parquet(norm / "requests.parquet", index=False)
    last = df.created.max()
    log(f"{len(df):,} complaints from {START.date()} to {last.date()} ({int(dup.sum())} duplicate IDs dropped); {df.org.nunique():,} companies")

    wk = df.created.dt.to_period("W-SUN").dt.start_time
    weekly = df.groupby(wk).size()
    top = df[df.created >= last - pd.Timedelta(days=364)].org.value_counts().head(12)
    prod = df.segment.value_counts().head(10)
    summary = {
        "title": ctx.meta.get("title", ctx.id), "period": f"{START.date()} .. {last.date()}",
        "facts": [
            {"label": "Complaints (since 2017)", "value": int(len(df)), "unit": ""},
            {"label": "Companies", "value": int(df.org.nunique()), "unit": ""},
            {"label": "Products", "value": int(df.segment.nunique()), "unit": ""},
            {"label": "Answered on time (all years)", "value": round(100 * float(df.on_time.mean()), 1), "unit": "%"},
            {"label": "Complaints in the last 52 weeks", "value": int((df.created > last - pd.Timedelta(days=364)).sum()), "unit": ""},
        ],
        "org": {"units": [], "roles": [], "systems": []},
        "charts": [
            {"id": "weekly_complaints", "type": "line", "title": "Complaints received per week", "x_label": "week", "y_label": "complaints",
             "x": [d.strftime("%Y-%m-%d") for d in weekly.index], "series": [{"name": "Complaints", "y": [int(v) for v in weekly.values]}], "note": "All companies; the last weeks are incomplete until companies respond or 15 days pass."},
            {"id": "top_companies", "type": "hbar", "title": "Companies with the most complaints, last 52 weeks", "x_label": "complaints", "y_label": "",
             "x": list(top.index), "series": [{"name": "Complaints", "y": [int(v) for v in top.values]}], "note": ""},
            {"id": "products", "type": "hbar", "title": "Complaints by product since 2017", "x_label": "complaints", "y_label": "",
             "x": list(prod.index), "series": [{"name": "Complaints", "y": [int(v) for v in prod.values]}], "note": "Product names before 24 April 2017 mapped to the current categories."},
        ],
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (norm / "summary.json").write_text(json.dumps(summary, indent=1, default=lambda o: o.item() if isinstance(o, np.generic) else str(o)))


if __name__ == "__main__":
    from orgsim.instances import get_instance
    main(get_instance("cfpb_complaints"))
