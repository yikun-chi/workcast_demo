"""Acquire the NYC Taxi and Limousine Commission trip records and taxi zones needed for the congestion pricing case.

Every file is saved unchanged under data/raw/ and never overwritten once complete (a partial file is resumed from
scratch), so an interrupted fetch can be rerun. Afterwards manifests/sources.json records every file with its URL,
retrieval time, byte size and SHA-256.

Months fetched (and no others; monthly files are 60-500 MB):
  yellow taxi and high-volume for-hire (Uber, Lyft): 2022-01 .. LAST_MONTH   the before period and the scored after period
  yellow taxi: 2018-01 .. 2018-03 and 2019-01 .. 2019-03                     the 2019 state congestion surcharge
                                                                              (calibrates the riders' price response)
  taxi_zone_lookup.csv, taxi_zones.zip                                        zone names and boundaries

    python instances/nyc_congestion/ingest/fetch.py [--last 2026-08] [--only yellow,fhvhv,misc]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
MANIFEST = ROOT / "manifests" / "sources.json"
BASE = "https://d37ci6vzurychx.cloudfront.net"
FIRST = (2022, 1)
SURCHARGE_2019_MONTHS = [(2018, 1), (2018, 2), (2018, 3), (2019, 1), (2019, 2), (2019, 3)]
MISC = ["taxi_zone_lookup.csv", "taxi_zones.zip"]

SOURCES = [
    {"id": "tlc_trip_records", "url": "https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page",
     "license": "NYC Open Data, published by the NYC Taxi and Limousine Commission; free to use (NYC Open Data Terms of Use, https://opendata.cityofnewyork.us/overview/#termsofuse)",
     "files": f"{BASE}/trip-data/{{yellow|fhvhv}}_tripdata_YYYY-MM.parquet"},
    {"id": "tlc_taxi_zones", "url": f"{BASE}/misc/taxi_zones.zip", "license": "NYC Open Data"},
    {"id": "tlc_industry_notice_24_10", "url": "https://nyc.gov/assets/tlc/downloads/pdf/industry-notices/industry_notice_24_10_english.pdf",
     "fact": "From 5 January 2025, a per-trip charge paid by the passenger for each trip to, from, within or through the Congestion Relief Zone "
             "(Manhattan south of and including 60th Street, excluding the FDR Drive, West Side Highway/Route 9A and the Hugh L. Carey Tunnel "
             "connections): $1.50 for high-volume for-hire trips (Uber, Lyft), $0.75 for taxis. Notice dated 2024-12-05."},
    {"id": "nys_tax_notice_n19_2", "url": "https://tax.ny.gov/pdf/notices/n19-2.pdf",
     "fact": "The state congestion surcharge (Tax Law Article 29-C) is collected from 12:01 a.m. Saturday 2 February 2019."},
    {"id": "nys_tax_congestion_surcharge", "url": "https://www.tax.ny.gov/bus/cs/csidx.htm",
     "fact": "$2.50 per medallion taxi trip, $2.75 per for-hire trip, $0.75 per pool trip, for trips that begin in, end in or pass "
             "through Manhattan south of and excluding 96th Street."},
]


def months(first: tuple[int, int], last: tuple[int, int]) -> list[tuple[int, int]]:
    out, (y, m) = [], first
    while (y, m) <= last:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def download(client: httpx.Client, url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    head = client.head(url)
    head.raise_for_status()
    size = int(head.headers.get("content-length", -1))
    if dest.exists() and dest.stat().st_size == size:
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(4):
        try:
            with client.stream("GET", url) as r, tmp.open("wb") as f:
                r.raise_for_status()
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
            if tmp.stat().st_size != size:
                raise OSError(f"size {tmp.stat().st_size} != {size}")
            tmp.rename(dest)
            print(f"  {dest.relative_to(ROOT)} {size / 1e6:.0f} MB", flush=True)
            return
        except (httpx.HTTPError, OSError) as e:
            print(f"  retry {attempt + 1} {url}: {e}", flush=True)
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"failed: {url}")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest() -> None:
    old = {f["path"]: f for f in (json.loads(MANIFEST.read_text()).get("files", []) if MANIFEST.exists() else [])}
    files = []
    for p in sorted(RAW.rglob("*")):
        if not p.is_file() or p.suffix == ".part":
            continue
        rel = str(p.relative_to(ROOT))
        prev = old.get(rel)
        if prev and prev["bytes"] == p.stat().st_size and prev.get("sha256"):
            files.append(prev)
            continue
        url = f"{BASE}/misc/{p.name}" if p.parent.name == "misc" else f"{BASE}/trip-data/{p.name}"
        files.append({"path": rel, "url": url, "bytes": p.stat().st_size, "sha256": sha256(p),
                      "retrieved": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")})
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({"sources": SOURCES, "n_files": len(files), "total_bytes": sum(f["bytes"] for f in files), "files": files}, indent=1) + "\n")
    print(f"manifest: {len(files)} files, {sum(f['bytes'] for f in files) / 1e9:.2f} GB", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--last", default="2026-08", help="last month to fetch (YYYY-MM)")
    ap.add_argument("--only", default="misc,yellow,fhvhv")
    ap.add_argument("--manifest-only", action="store_true")
    a = ap.parse_args()
    if not a.manifest_only:
        last = tuple(int(x) for x in a.last.split("-"))
        only = set(a.only.split(","))
        with httpx.Client(timeout=httpx.Timeout(60, read=300), follow_redirects=True) as c:
            if "misc" in only:
                for name in MISC:
                    download(c, f"{BASE}/misc/{name}", RAW / "misc" / name)
            for kind in ("yellow", "fhvhv"):
                if kind not in only:
                    continue
                ms = months(FIRST, last) + (SURCHARGE_2019_MONTHS if kind == "yellow" else [])
                for y, m in sorted(ms):
                    name = f"{kind}_tripdata_{y}-{m:02d}.parquet"
                    download(c, f"{BASE}/trip-data/{name}", RAW / "trips" / kind / name)
    write_manifest()


if __name__ == "__main__":
    sys.exit(main())
