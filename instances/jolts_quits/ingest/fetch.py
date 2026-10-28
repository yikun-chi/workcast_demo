"""Acquire the BLS Job Openings and Labor Turnover Survey (JOLTS) series used by the quits case.

Not seasonally adjusted monthly series for 28 industries (total nonfarm, private, supersectors and sectors, government),
five data elements each: quits level and rate, hires level and rate, job openings rate. Fetched from the BLS Public
Data API v1 (no key; 25 series and ten years per request, 25 requests a day), so the 140 series come in 18 requests.
Every response is saved unchanged under data/raw/bls/ and never refetched once saved; manifests/sources.json records
each file with its request, retrieval time, size and SHA-256. BLS data are in the public domain.

    python instances/jolts_quits/ingest/fetch.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "bls"
MANIFEST = ROOT / "manifests" / "sources.json"
API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
INDUSTRIES = {
    "000000": "Total nonfarm", "100000": "Total private", "110099": "Mining and logging", "230000": "Construction",
    "300000": "Manufacturing", "320000": "Durable goods manufacturing", "340000": "Nondurable goods manufacturing",
    "400000": "Trade, transportation, and utilities", "420000": "Wholesale trade", "440000": "Retail trade",
    "480099": "Transportation, warehousing, and utilities", "510000": "Information", "510099": "Financial activities",
    "520000": "Finance and insurance", "530000": "Real estate and rental and leasing", "540099": "Professional and business services",
    "600000": "Private education and health services", "610000": "Private educational services", "620000": "Health care and social assistance",
    "700000": "Leisure and hospitality", "710000": "Arts, entertainment, and recreation", "720000": "Accommodation and food services",
    "810000": "Other services", "900000": "Government", "910000": "Federal", "920000": "State and local",
    "923000": "State and local government education", "929000": "State and local government, excluding education",
}
ELEMENTS = {"QUL": "quits, level (thousands)", "QUR": "quits rate (%)", "HIL": "hires, level (thousands)", "HIR": "hires rate (%)", "JOR": "job openings rate (%)"}
SPANS = [(2000, 2009), (2010, 2019), (2020, 2029)]
SOURCES = [{"id": "bls_jolts", "url": "https://www.bls.gov/jlt/", "api": API,
            "license": "Public domain (U.S. Bureau of Labor Statistics; https://www.bls.gov/opub/copyright-information.htm)",
            "series": "JTU<industry>000000000<element>: not seasonally adjusted, national, all size classes"}]


def series_ids() -> list[str]:
    return [f"JTU{ind}000000000{el}" for ind in INDUSTRIES for el in ELEMENTS]


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    ids = series_ids()
    batches = [ids[i: i + 25] for i in range(0, len(ids), 25)]
    with httpx.Client(timeout=60) as c:
        for a, b in SPANS:
            for k, batch in enumerate(batches):
                f = RAW / f"jolts_{a}_{b}_batch{k:02d}.json"
                if f.exists():
                    continue
                r = c.post(API, json={"seriesid": batch, "startyear": str(a), "endyear": str(b)})
                r.raise_for_status()
                d = r.json()
                if d.get("status") != "REQUEST_SUCCEEDED":
                    sys.exit(f"BLS API: {d.get('status')} {d.get('message')} (rerun tomorrow; saved files are kept)")
                f.write_text(json.dumps({"request": {"seriesid": batch, "startyear": str(a), "endyear": str(b)}, "response": d}, indent=1))
                print(f"  {f.name}: {len(d['Results']['series'])} series", flush=True)
                time.sleep(2)
    files = []
    for p in sorted(RAW.glob("*.json")):
        files.append({"path": str(p.relative_to(ROOT)), "url": API, "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                      "retrieved": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")})
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({"sources": SOURCES, "n_files": len(files), "total_bytes": sum(f["bytes"] for f in files), "files": files}, indent=1) + "\n")
    print(f"manifest: {len(files)} files")


if __name__ == "__main__":
    main()
