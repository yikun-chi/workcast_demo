"""Download NYC 311 service requests (NYC Open Data) month by month and record every file's SHA-256.

Two public datasets cover the span: 76ig-c548 (2010-2019) and erm2-nwe9 (2020 to present). Only the columns the
instance uses are requested through the Socrata API (SoQL), one CSV per calendar month of created_date. The
datasets are updated daily (closed dates fill in), so manifests/sources.json records the retrieval date and the
hash of every file actually used; a rerun on a later day downloads a newer vintage with different hashes.

Licence: NYC Administrative Code 23-502(d): public data sets are made available "without any registration
requirement, license requirement or restrictions on their use"; a republisher may be asked to identify the source
and version and describe modifications (recorded in the manifest).

Usage: python instances/nyc311/ingest/download.py [--start 2018-01] [--end 2026-10] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
COLUMNS = ["unique_key", "created_date", "closed_date", "agency", "complaint_type", "status"]
DATASETS = [("76ig-c548", "311 Service Requests from 2010 to 2019", date(2010, 1, 1), date(2020, 1, 1)),
            ("erm2-nwe9", "311 Service Requests from 2020 to Present", date(2020, 1, 1), date(2100, 1, 1))]


def month_starts(start: str, end: str) -> list[date]:
    y, m = map(int, start.split("-")); ey, em = map(int, end.split("-"))
    out = []
    while (y, m) <= (ey, em):
        out.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def next_month(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


def url_for(dataset: str, d0: date, d1: date) -> str:
    q = {"$select": ",".join(COLUMNS), "$where": f'created_date >= "{d0.isoformat()}T00:00:00" AND created_date < "{d1.isoformat()}T00:00:00"',
         "$order": "unique_key", "$limit": "5000000"}
    return f"https://data.cityofnewyork.us/resource/{dataset}.csv?" + urllib.parse.urlencode(q)


def sha256(p: Path) -> str:
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2018-01")
    ap.add_argument("--end", default="2026-10")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--verify", action="store_true", help="compare each file's row count with the server's count")
    a = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    files = []
    for d0 in month_starts(a.start, a.end):
        ds = next(x for x in DATASETS if x[2] <= d0 < x[3])
        p = RAW / f"311_{d0:%Y-%m}.csv"
        url = url_for(ds[0], d0, next_month(d0))
        if a.force or not p.exists() or p.stat().st_size < 1000:
            for attempt in range(4):
                try:
                    tmp = p.with_suffix(".part")
                    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "orgsim-data/0.1"}), timeout=900) as r, tmp.open("wb") as f:
                        while chunk := r.read(1 << 20):
                            f.write(chunk)
                    tmp.replace(p)
                    break
                except OSError as e:
                    print(f"retry {d0:%Y-%m}: {e}", flush=True)
                    time.sleep(10 * (attempt + 1))
            else:
                raise RuntimeError(f"download failed for {d0:%Y-%m}")
        n = int(pd.read_csv(p, usecols=["unique_key"]).shape[0])
        row = {"name": p.name, "dataset_id": ds[0], "dataset_title": ds[1], "url": url, "rows": n, "size_bytes": p.stat().st_size,
               "sha256": sha256(p), "retrieved": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")}
        if a.verify:
            # the server's own count of the month's requests at verification time (the dataset grows only by late entries)
            q = {"$select": "count(*) as n", "$where": f'created_date >= "{d0.isoformat()}T00:00:00" AND created_date < "{next_month(d0).isoformat()}T00:00:00"'}
            cu = f"https://data.cityofnewyork.us/resource/{ds[0]}.json?" + urllib.parse.urlencode(q)
            with urllib.request.urlopen(urllib.request.Request(cu, headers={"User-Agent": "orgsim-data/0.1"}), timeout=300) as r:
                row["server_rows_at_verification"] = int(json.loads(r.read())[0]["n"])
            if row["server_rows_at_verification"] < n:
                raise RuntimeError(f"{p.name}: file has more rows than the server ({n} > {row['server_rows_at_verification']})")
        files.append(row)
        print(f"{p.name}: {n:,} rows" + (f" (server {row['server_rows_at_verification']:,})" if a.verify else ""), flush=True)
    manifest = {"dataset": "NYC 311 Service Requests (NYC Open Data)", "publisher": "NYC Office of Technology and Innovation (OTI)",
                "dataset_pages": [f"https://data.cityofnewyork.us/d/{d[0]}" for d in DATASETS],
                "license": {"name": "NYC Open Data Law: no registration, licence or use restrictions",
                            "source": "NYC Administrative Code section 23-502(d) (text read at https://nyc-laws.readthedocs.io/en/latest/nycadmincode/t23/c05/)",
                            "attribution_required": "identify source and version and describe modifications"},
                "columns": COLUMNS, "split": "one CSV per calendar month of created_date, via the Socrata SoQL API",
                "vintage_note": "Updated daily; closed dates fill in over time. Hashes identify this retrieval.",
                "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "files": files}
    (ROOT / "manifests").mkdir(exist_ok=True)
    (ROOT / "manifests" / "sources.json").write_text(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
