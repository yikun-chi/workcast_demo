"""Download the Stack Overflow Developer Survey public results, 2023-2026 (the waves that ask about AI tools).

Source: the StackExchange/Survey repository, packages/archive/<year>/ (files stored with Git LFS, fetched from the
LFS media host). Data licence: Open Database License (ODbL) 1.0, cell contents Database Contents License (DbCL) 1.0
(repository README, "License and data attribution"). Each file is saved unchanged under data/raw/<year>/ and never
overwritten; manifests/sources.json records URL, retrieval time, size and SHA-256.

  python instances/so_survey/ingest/audit/fetch.py
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
MANIFEST = ROOT / "manifests" / "sources.json"
MEDIA = "https://media." + "githubusercontent.com/media/StackExchange/Survey/main/packages/archive/"
FILES = {2023: ["results.csv", "schema.csv"], 2024: ["results.csv", "schema.csv"], 2025: ["results.csv", "schema.csv"],
         2026: ["survey_results_public.csv", "survey_results_schema.csv"]}


def main() -> None:
    client = httpx.Client(timeout=600, follow_redirects=True, headers={"User-Agent": "orgsim-data/0.1"})
    for year, names in FILES.items():
        for name in names:
            p = RAW / str(year) / name
            if p.exists():
                continue
            url = f"{MEDIA}{year}/{name}"
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".part")
            with client.stream("GET", url) as r:
                r.raise_for_status()
                with tmp.open("wb") as out:
                    for chunk in r.iter_bytes():
                        out.write(chunk)
            tmp.replace(p)
            (p.parent / (name + ".url")).write_text(url + "\n")
            print(f"saved {p} ({p.stat().st_size:,} bytes)", flush=True)
    files = []
    for p in sorted(RAW.rglob("*.csv")):
        files.append({"path": p.relative_to(ROOT).as_posix(), "url": (p.parent / (p.name + ".url")).read_text().strip(), "bytes": p.stat().st_size,
                      "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "retrieved": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")})
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({
        "sources": [{"id": "so_developer_survey", "url": "https://survey.stackoverflow.co/",
                     "license": "Open Database License (ODbL) 1.0; cell contents Database Contents License (DbCL) 1.0",
                     "attribution": "Stack Overflow Developer Survey (Stack Exchange, Inc.), https://survey.stackoverflow.co/"}],
        "n_files": len(files), "total_bytes": sum(x["bytes"] for x in files), "files": files}, indent=1))


if __name__ == "__main__":
    main()
