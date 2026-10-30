"""Pin the OPM Federal Workforce Data files this instance uses and record their hashes in manifests/sources.json.

OPM republishes files with new version numbers, so the manifest names the exact version of each file. This script
lists the current versions through the public API (no key), downloads each file into data/raw/opm/, hashes it and
writes the manifest. instances/fedwork/ingest/run.py then downloads (if missing) and verifies exactly these files.

    .venv/bin/python instances/fedwork/ingest/audit/build_manifest.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
API = "https://data.opm.gov/api/v1/files"
SEPARATIONS = [(y, m) for y in range(2018, 2027) for m in range(1, 13) if (y, m) <= (2026, 8)]
EMPLOYMENT = [(y, 12) for y in range(2018, 2025)]          # December snapshots 2018-2024, all before the change


def main() -> None:
    from orgsim.instances import get_instance
    ctx = get_instance("fedwork")
    raw = ctx.data_raw / "opm"
    raw.mkdir(parents=True, exist_ok=True)
    files = []
    with httpx.Client(timeout=300, follow_redirects=True) as c:
        for dataset, months in (("separations", SEPARATIONS), ("employment", EMPLOYMENT)):
            listing = c.get(f"{API}/{dataset}", params={"current": "true"}).raise_for_status().json()
            cur = {(int(x["year"]), int(x["month"])): x for x in listing}
            for ym in months:
                x = cur[ym]
                url = f"{API}/{dataset}/{x['year']}/{x['month']}/{x['version']}/download"
                target = raw / f"{x['filename']}.parquet"
                if not target.exists():
                    tmp = target.with_suffix(".part")
                    with c.stream("GET", url) as r:
                        r.raise_for_status()
                        with tmp.open("wb") as f:
                            for chunk in r.iter_bytes():
                                f.write(chunk)
                    tmp.rename(target)
                files.append({"dataset": dataset, "year": int(x["year"]), "month": int(x["month"]), "version": int(x["version"]),
                              "filename": x["filename"], "published": x["publishDate"], "url": url, "bytes": target.stat().st_size,
                              "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
                print(f"{dataset} {ym} v{x['version']} {target.stat().st_size:,} bytes")
    man = {"source": "U.S. Office of Personnel Management, Federal Workforce Data (FWD), https://data.opm.gov",
           "api": API, "access": "public API, no key; files are parquet",
           "license": "No licence statement on the FWD pages. Work of the U.S. federal government (17 U.S.C. 105); released under OPM's Data Release Policy (December 2024), which withholds adverse-action codes and redacts sensitive fields.",
           "retrieval_date": date.today().isoformat(),
           "note": "OPM republishes files under new versions; this manifest pins the version of each file used.",
           "files": files}
    (ctx.root / "manifests" / "sources.json").write_text(json.dumps(man, indent=1))
    print(f"wrote manifest with {len(files)} files")


if __name__ == "__main__":
    main()
