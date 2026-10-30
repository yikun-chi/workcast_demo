"""Acquire the OpenRouter public usage datasets and the archived model price lists.

Every response is saved unchanged under data/raw/ and never overwritten, so a fetch interrupted by the daily
request limit resumes where it stopped. After each run, manifests/sources.json records every file with its
request URL (no key), retrieval time, the dataset's own `as_of`, byte size and SHA-256.

Sources
  OpenRouter Datasets API (CC BY 4.0, "Source: OpenRouter (openrouter.ai/rankings), as of {as_of}")
    /api/v1/datasets/rankings-daily   tokens per model per day / week, by category and language type
    /api/v1/datasets/app-rankings     tokens and requests per app per window, by category and subcategory
    /api/v1/datasets/session-cost     median session cost by harness and model (current weekly window)
  Internet Archive snapshots of https://openrouter.ai/api/v1/models (prices, context, creation date)
  Anthropic Economic Index, 1P API sample (Hugging Face Anthropic/EconomicIndex at a pinned revision; data CC BY):
    share of API records and indexed prompt tokens, completion tokens and cost per O*NET task

Key: OPENROUTER_API_KEY or ~/.secrets/openrouter.key. Limits: 30 requests/minute/key, 500/day/account.

  python instances/openrouter/ingest/audit/fetch.py [--budget 450] [--only rankings,apps,session,wayback]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
MANIFEST = ROOT / "manifests" / "sources.json"
API = "https://openrouter.ai/api/v1/datasets"
START = date(2025, 1, 1)                       # first date the datasets cover
FIRST_MONDAY = date(2025, 1, 6)
CATEGORIES = ["programming", "roleplay", "marketing", "marketing/seo", "technology", "science", "translation",
              "legal", "finance", "health", "trivia", "academia"]
LANGUAGE_TYPES = ["natural", "programming"]
APP_CATEGORIES = ["coding", "creative", "productivity", "entertainment"]
APP_SUBCATEGORIES = ["cli-agent", "ide-extension", "cloud-agent", "programming-app", "native-app-builder",
                     "creative-writing", "video-gen", "image-gen", "audio-gen", "roleplay", "game",
                     "writing-assistant", "general-chat", "personal-agent", "legal"]
MIN_INTERVAL_S = 2.1                            # stays under 30 requests per minute
LICENSE = "CC BY 4.0"
AEI_REVISION = "4e5f69fab13a9c3f7d0dcc31a6f893a9818738f6"
AEI_FILES = ["release_2026_03_24/data/aei_raw_1p_api_2026-02-05_to_2026-02-12.csv", "release_2026_03_24/data_documentation.md"]


def api_key() -> str:
    k = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not k:
        p = Path.home() / ".secrets" / "openrouter.key"
        k = p.read_text().strip() if p.exists() else ""
    if not k:
        sys.exit("No OpenRouter key: set OPENROUTER_API_KEY or write ~/.secrets/openrouter.key")
    return k


class Fetcher:
    def __init__(self, budget: int) -> None:
        self.budget, self.used, self._last = budget, 0, 0.0
        self.client = httpx.Client(timeout=90, headers={"User-Agent": "orgsim-data/0.1"})
        self.key: str | None = None

    def get(self, url: str, path: Path, auth: bool) -> dict | None:
        """Save the response body to `path` unless it already exists; returns parsed JSON or None when out of budget."""
        if path.exists():
            return json.loads(path.read_text())
        if auth and self.used >= self.budget:
            return None
        headers = {}
        if auth:
            self.key = self.key or api_key()
            headers["Authorization"] = f"Bearer {self.key}"
            wait = MIN_INTERVAL_S - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
        for attempt in range(4):
            r = self.client.get(url, headers=headers)
            self._last = time.time()
            if auth:
                self.used += 1
            if r.status_code == 429:
                time.sleep(30 * (attempt + 1))
                continue
            if r.status_code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code} for {url}: {r.text[:300]}")
            body = r.content
            if body[:2] == b"\x1f\x8b":            # some archived captures store the gzip body without its header
                body = gzip.decompress(body)
            payload = json.loads(body)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            tmp.write_bytes(body)
            tmp.replace(path)
            return payload
        raise RuntimeError(f"gave up after retries: {url}")


def latest_complete_day(f: Fetcher) -> date:
    probe = f.get(f"{API}/rankings-daily?" + urlencode({"period": "day"}), RAW / "probe" / f"latest_{date.today()}.json", True)
    if probe is None:
        sys.exit("request budget exhausted before the probe")
    return date.fromisoformat(probe["meta"]["end_date"])


def months(a: date, b: date):
    d = a.replace(day=1)
    while d <= b:
        nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        yield max(d, a), min(nxt - timedelta(days=1), b)
        d = nxt


def chunks(end: date, days: int = 182):
    """Monday-aligned windows of at most `days` days (the API rejects ranges over 366 days)."""
    a = FIRST_MONDAY
    while a <= end:
        b = min(a + timedelta(days=days - 1), end)
        yield a, b
        a = b + timedelta(days=1)


SUPERSEDED = RAW / "_superseded"


def refresh(path: Path, window_end: date, cutoff: date | None) -> None:
    """For a live run: a window that was still open when it was last fetched is fetched again. The earlier file is
    moved under raw/_superseded/<today>/, never deleted, so every forecast's inputs stay recoverable."""
    if cutoff is not None and window_end >= cutoff and path.exists():
        dest = SUPERSEDED / date.today().isoformat() / path.relative_to(RAW)
        dest.parent.mkdir(parents=True, exist_ok=True)
        path.replace(dest)


def fetch_live_models(f: Fetcher) -> None:
    """The current model list (prices, listing dates) saved beside the archived captures, named by fetch time."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    f.get("https://openrouter.ai/api/v1/models", RAW / "wayback" / "models" / f"{stamp}.json", False)


def fetch_rankings(f: Fetcher, end: date, cutoff: date | None = None) -> None:
    for a, b in months(START, end):
        refresh(RAW / "rankings" / "daily" / f"{a:%Y-%m}.json", b, cutoff)
        q = {"period": "day", "start_date": a.isoformat(), "end_date": b.isoformat()}
        f.get(f"{API}/rankings-daily?{urlencode(q)}", RAW / "rankings" / "daily" / f"{a:%Y-%m}.json", True)
    for a, b in chunks(end):
        for cat in CATEGORIES:
            refresh(RAW / "rankings" / "category" / f"{cat.replace('/', '_')}_{a}.json", b, cutoff)
            q = {"period": "week", "category": cat, "start_date": a.isoformat(), "end_date": b.isoformat()}
            f.get(f"{API}/rankings-daily?{urlencode(q)}", RAW / "rankings" / "category" / f"{cat.replace('/', '_')}_{a}.json", True)
        for lt in LANGUAGE_TYPES:
            refresh(RAW / "rankings" / "language" / f"{lt}_{a}.json", b, cutoff)
            q = {"period": "week", "language_type": lt, "start_date": a.isoformat(), "end_date": b.isoformat()}
            f.get(f"{API}/rankings-daily?{urlencode(q)}", RAW / "rankings" / "language" / f"{lt}_{a}.json", True)


def fetch_apps(f: Fetcher, end: date, cutoff: date | None = None) -> None:
    # Weekly panel: Monday-Sunday windows, ranks 1-200 (limit 100, offsets 0 and 100).
    wk = FIRST_MONDAY
    while wk + timedelta(days=6) <= end:
        for off in (0, 100):
            q = {"sort": "popular", "start_date": wk.isoformat(), "end_date": (wk + timedelta(days=6)).isoformat(), "limit": 100, "offset": off}
            if f.get(f"{API}/app-rankings?{urlencode(q)}", RAW / "apps" / "weekly" / f"{wk}_o{off}.json", True) is None:
                return
        wk += timedelta(days=7)
    # App classification: category and subcategory membership, one window per calendar year (ranges <= 366 days).
    for a, b in ((START, min(date(2025, 12, 31), end)), (date(2026, 1, 1), end)):
        for kind, values in (("category", APP_CATEGORIES), ("subcategory", APP_SUBCATEGORIES)):
            for v in values:
                for off in (0, 100):
                    refresh(RAW / "apps" / kind / f"{v}_{a.year}_o{off}.json", b, cutoff)
                    q = {"sort": "popular", kind: v, "start_date": a.isoformat(), "end_date": b.isoformat(), "limit": 100, "offset": off}
                    if f.get(f"{API}/app-rankings?{urlencode(q)}", RAW / "apps" / kind / f"{v}_{a.year}_o{off}.json", True) is None:
                        return


def fetch_session_cost(f: Fetcher) -> None:
    stamp = date.today().isoformat()
    off = 0
    while off <= 5000:
        q = {"limit": 500, "offset": off}
        d = f.get(f"{API}/session-cost?{urlencode(q)}", RAW / "session_cost" / stamp / f"o{off}.json", True)
        if d is None or len(d.get("data", [])) < 500:
            return
        off += 500


def fetch_wayback(f: Fetcher) -> None:
    cdx = ("https://web.archive.org/cdx/search/cdx?" +
           urlencode({"url": "openrouter.ai/api/v1/models", "output": "json", "from": "2024", "fl": "timestamp,statuscode",
                      "filter": "statuscode:200", "collapse": "timestamp:8"}))
    idx_path = RAW / "wayback" / f"cdx_{date.today()}.json"
    rows = f.get(cdx, idx_path, False)[1:]
    for ts, _ in rows:
        p = RAW / "wayback" / "models" / f"{ts}.json"
        if p.exists():
            continue
        try:
            f.get(f"https://web.archive.org/web/{ts}id_/https://openrouter.ai/api/v1/models", p, False)
        except (RuntimeError, ValueError, OSError, httpx.HTTPError) as e:   # a broken capture is skipped and listed
            print(f"skip wayback {ts}: {e}", flush=True)
        time.sleep(1.0)


def fetch_aei() -> None:
    for name in AEI_FILES:
        p = RAW / "aei" / name
        if p.exists():
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/datasets/Anthropic/EconomicIndex/resolve/{AEI_REVISION}/{name}"
        with httpx.stream("GET", url, follow_redirects=True, timeout=300) as r:
            r.raise_for_status()
            tmp = p.with_suffix(".part")
            with tmp.open("wb") as out:
                for chunk in r.iter_bytes():
                    out.write(chunk)
            tmp.replace(p)


def write_manifest() -> None:
    files = []
    for p in sorted(x for x in RAW.rglob("*") if x.is_file() and x.suffix in (".json", ".csv", ".md")):
        rel = p.relative_to(ROOT).as_posix()
        try:
            meta = json.loads(p.read_text()).get("meta", {}) if p.suffix == ".json" else {}
        except (json.JSONDecodeError, AttributeError):
            meta = {}
        files.append({"path": rel, "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                      "retrieved": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
                      "as_of": meta.get("as_of") if isinstance(meta, dict) else None})
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({
        "sources": [
            {"id": "openrouter_datasets", "url": "https://openrouter.ai/docs/api/api-reference/datasets", "license": LICENSE,
             "attribution": "Source: OpenRouter (openrouter.ai/rankings), as of {as_of}."},
            {"id": "wayback_models", "url": "https://web.archive.org/web/*/openrouter.ai/api/v1/models",
             "license": "Archived public API responses (facts: model ids, prices, creation dates)"},
            {"id": "anthropic_economic_index", "url": f"https://huggingface.co/datasets/Anthropic/EconomicIndex/tree/{AEI_REVISION}",
             "license": "Data CC BY (data_documentation.md); dataset card metadata lists MIT", "revision": AEI_REVISION},
        ],
        "n_files": len(files), "total_bytes": sum(x["bytes"] for x in files), "files": files}, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=int, default=450, help="authenticated requests allowed in this run (account limit 500/day)")
    ap.add_argument("--only", default="aei,wayback,rankings,apps,session")
    ap.add_argument("--refresh-days", type=int, default=0, help="live runs: refetch windows ending within this many days of the latest complete day")
    a = ap.parse_args()
    parts = set(a.only.split(","))
    f = Fetcher(a.budget)
    if "aei" in parts:
        fetch_aei()
    if "wayback" in parts:
        fetch_wayback(f)
    if parts & {"rankings", "apps", "session"}:
        end = latest_complete_day(f)
        print(f"datasets cover {START} .. {end}", flush=True)
        cutoff = end - timedelta(days=a.refresh_days) if a.refresh_days else None
        if "rankings" in parts:
            fetch_rankings(f, end, cutoff)
        if "apps" in parts:
            fetch_apps(f, end, cutoff)
    if "live" in parts:
        fetch_live_models(f)
        if "session" in parts:
            fetch_session_cost(f)
    write_manifest()
    print(f"authenticated requests used: {f.used}/{a.budget}", flush=True)


if __name__ == "__main__":
    main()
