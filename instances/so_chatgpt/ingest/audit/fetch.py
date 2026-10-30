"""Acquire weekly counts of new Stack Overflow questions from the public Stack Exchange API.

One request per Monday-to-Monday week: /2.3/questions?site=stackoverflow&fromdate=<monday>&todate=<next monday>&filter=total
returns {"total": n}, the number of questions created that week that still exist (the API, like the data dumps, omits
deleted questions). Every response is saved unchanged under data/raw/weekly/<monday>.json and never overwritten, so a
run stopped by the daily request quota (300 a day without an app key) resumes where it stopped. Weeks are fetched
newest first, so the weeks after the ChatGPT launch are complete before the older history.

Licence: Stack Overflow content is CC BY-SA (2.5 / 3.0 / 4.0 by posting date; https://stackoverflow.com/help/licensing).
The counts are facts derived from it. The official data dump has required a login since 2024 and its terms exclude
training language models; this instance uses only the public API counts.

  python instances/so_chatgpt/ingest/audit/fetch.py [--start 2021-01-04] [--end <last complete Monday>] [--reserve 5]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
MANIFEST = ROOT / "manifests" / "sources.json"
API = "https://api.stackexchange.com/2.3/questions"
LICENSE = "CC BY-SA 2.5/3.0/4.0 by posting date (https://stackoverflow.com/help/licensing); counts are derived facts"


def epoch(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def mondays(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        out.append(d)
        d += timedelta(days=7)
    return out


def fetch(start: date, end: date, reserve: int) -> int:
    client = httpx.Client(timeout=60, headers={"User-Agent": "orgsim-data/0.1", "Accept-Encoding": "gzip"})
    used = 0
    for wk in reversed(mondays(start, end)):
        p = RAW / "weekly" / f"{wk}.json"
        if p.exists():
            continue
        url = f"{API}?site=stackoverflow&fromdate={epoch(wk)}&todate={epoch(wk + timedelta(days=7)) - 1}&filter=total"
        r = client.get(url)
        used += 1
        body = r.content
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        payload = json.loads(body)
        if r.status_code != 200 or "total" not in payload:
            print(f"stop at {wk}: HTTP {r.status_code} {payload}", flush=True)
            break
        p.parent.mkdir(parents=True, exist_ok=True)
        payload["_request"] = {"url": url, "retrieved": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        p.write_text(json.dumps(payload))
        quota = payload.get("quota_remaining")
        if payload.get("backoff"):
            time.sleep(int(payload["backoff"]) + 1)
        time.sleep(0.6)
        if quota is not None and quota <= reserve:
            print(f"quota reserve reached after {wk} (remaining {quota}); rerun tomorrow to continue", flush=True)
            break
    return used


def write_manifest() -> None:
    files = []
    for p in sorted(x for x in RAW.rglob("*.json") if x.is_file()):
        files.append({"path": p.relative_to(ROOT).as_posix(), "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                      "retrieved": json.loads(p.read_text()).get("_request", {}).get("retrieved")})
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({
        "sources": [{"id": "stackexchange_api", "url": "https://api.stackexchange.com/docs/questions", "license": LICENSE,
                     "attribution": "Stack Overflow (stackoverflow.com), via the Stack Exchange API v2.3",
                     "note": "Counts exclude deleted questions. Official data dump: login required since 2024, terms exclude LLM training; not used."}],
        "n_files": len(files), "total_bytes": sum(x["bytes"] for x in files), "files": files}, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    today = date.today()
    last_complete = today - timedelta(days=today.weekday() + 7)
    ap.add_argument("--start", default="2021-01-04")
    ap.add_argument("--end", default=str(last_complete))
    ap.add_argument("--reserve", type=int, default=5)
    a = ap.parse_args()
    n = fetch(date.fromisoformat(a.start), date.fromisoformat(a.end), a.reserve)
    write_manifest()
    print(f"requests used: {n}", flush=True)


if __name__ == "__main__":
    main()
