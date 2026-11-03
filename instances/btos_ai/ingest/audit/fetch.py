"""Download the Census Bureau Business Trends and Outlook Survey (BTOS) AI tables.

Files (https://www.census.gov/hfp/btos/data_downloads, public domain, U.S. Census Bureau):
  AI Core Questions.xlsx             the AI questions with the original wording ("in producing goods or services"),
                                     biweekly from 2023-09-11 to the change of wording on 2025-11-17: national, sector,
                                     subsector, size class, state and metro estimates with standard errors
  AI Question Wording Updates.pdf    Census note of 2025-12-03 on the new wording and the level shift it caused
  Sector.xlsx                        the current tables (new wording from 2025-11-17); kept for the record, not scored

Each file is saved unchanged under data/raw/ with a date stamp and never overwritten. manifests/sources.json records
every file with its URL, retrieval time, size and SHA-256.

  python instances/btos_ai/ingest/audit/fetch.py
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
MANIFEST = ROOT / "manifests" / "sources.json"
BASE = "https://www.census.gov/hfp/btos/downloads/"
FILES = ["AI Core Questions.xlsx", "AI Question Wording Updates.pdf", "Sector.xlsx"]


def main() -> None:
    stamp = date.today().isoformat()
    client = httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (orgsim-data)"})
    for name in FILES:
        if any(RAW.glob(f"*/{name}")):
            continue
        r = client.get(BASE + quote(name))
        r.raise_for_status()
        p = RAW / stamp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(r.content)
        (p.parent / (name + ".url")).write_text(BASE + quote(name) + "\n")
        print(f"saved {p} ({len(r.content):,} bytes)", flush=True)
    files = []
    for p in sorted(x for x in RAW.rglob("*") if x.is_file() and x.suffix in (".xlsx", ".pdf")):
        url = (p.parent / (p.name + ".url")).read_text().strip()
        files.append({"path": p.relative_to(ROOT).as_posix(), "url": url, "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                      "retrieved": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")})
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({
        "sources": [{"id": "census_btos", "url": "https://www.census.gov/hfp/btos/data_downloads",
                     "license": "Public domain (U.S. Census Bureau, a federal government work)",
                     "attribution": "U.S. Census Bureau, Business Trends and Outlook Survey",
                     "note": "AI use questions changed wording on 2025-11-17 with a level shift (AI Question Wording Updates.pdf); "
                             "the original-wording series (AI Core Questions.xlsx) is the one scored."}],
        "n_files": len(files), "total_bytes": sum(x["bytes"] for x in files), "files": files}, indent=1))


if __name__ == "__main__":
    main()
