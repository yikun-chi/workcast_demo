"""Download the article list and the daily pageviews for the wiki_ai_traffic instance; record every file in the manifest.

Sources
  English Wikipedia, "Wikipedia:Vital articles/Level 3", revision 756347162 (2016-12-23): the 1,000 core reference
  topics as listed before every evaluation cutoff (MediaWiki API; page text CC BY-SA 4.0, used only to choose titles).
  Title resolution: the MediaWiki API's redirect target of each listed title today, so that views of an article that
  was renamed are summed over its old and new titles (retrieval date recorded).
  Wikimedia Analytics pageviews API (CC0 1.0; User-Agent required):
    per-article/en.wikipedia/{desktop,mobile-web,mobile-app}/user/<title>/daily/<start>/<end>
    aggregate/en.wikipedia/{desktop,mobile-web,mobile-app}/user/daily/<start>/<end>

Every response is saved unchanged (gzip) under data/raw/ and never overwritten; manifests/sources.json lists each
file with its URL, retrieval time, size and SHA-256.

  python -I instances/wiki_ai_traffic/ingest/download.py [--workers 4]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
MANIFEST = ROOT / "manifests" / "sources.json"
UA = "orgsim-data/0.1 (WORKCAST retrodiction research; contact svaid@hbs.edu)"
VITAL_REV = 756347162
START, END = "20150701", "20260930"
ACCESS = ("desktop", "mobile-web", "mobile-app")
API = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
MW = "https://en.wikipedia.org/w/api.php"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def get(url: str, tries: int = 5) -> bytes:
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b'{"items": [], "status": 404}'
            time.sleep(2 * (k + 1))
        except OSError:
            time.sleep(2 * (k + 1))
    raise SystemExit(f"failed: {url}")


def save(rel: str, url: str, body: bytes, files: dict) -> None:
    p = RAW / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        tmp = p.with_suffix(p.suffix + ".part")
        tmp.write_bytes(gzip.compress(body, mtime=0))
        tmp.replace(p)
    files[rel] = {"path": rel, "url": url, "retrieved": datetime.now(timezone.utc).isoformat(timespec="seconds"), "bytes": p.stat().st_size, "sha256": sha256(p)}


def safe(title: str) -> str:
    return urllib.parse.quote(title.replace(" ", "_"), safe="")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    man = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    files = {f["path"]: f for f in man.get("files", [])}
    # 1. the article list at a fixed revision
    url = f"{MW}?action=query&prop=revisions&revids={VITAL_REV}&rvprop=ids%7Ctimestamp%7Ccontent&rvslots=main&format=json&formatversion=2"
    rel = f"vital_level3_rev{VITAL_REV}.json.gz"
    if not (RAW / rel).exists():
        save(rel, url, get(url), files)
    rev = json.loads(gzip.decompress((RAW / rel).read_bytes()))["query"]["pages"][0]["revisions"][0]
    text = rev["slots"]["main"]["content"]
    titles = []
    for t in re.findall(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]", text):
        t = t.strip()
        if ":" not in t and t not in titles:
            titles.append(t)
    print(f"{len(titles)} titles in revision {VITAL_REV} ({rev['timestamp']})", flush=True)
    # 2. today's redirect targets (renamed articles), 50 titles per request
    rel = "title_resolution.json.gz"
    if not (RAW / rel).exists():
        out = []
        for i in range(0, len(titles), 50):
            u = f"{MW}?action=query&redirects=1&format=json&formatversion=2&titles=" + urllib.parse.quote("|".join(titles[i:i + 50]))
            out.append({"url": u, "response": json.loads(get(u))})
        save(rel, f"{MW}?action=query&redirects=1&titles=<50 at a time>", json.dumps(out).encode(), files)
    res = json.loads(gzip.decompress((RAW / rel).read_bytes()))
    norm, redir = {}, {}
    for blk in res:
        q = blk["response"]["query"]
        for n in q.get("normalized", []):
            norm[n["from"]] = n["to"]
        for r in q.get("redirects", []):
            redir[r["from"]] = r["to"]
    fetch = set()
    for t in titles:
        n = norm.get(t, t)
        fetch.add(n)
        if n in redir:
            fetch.add(redir[n])
    print(f"{len(fetch)} titles to fetch (listed titles plus today's targets of renamed ones)", flush=True)
    # 3. per-article daily views by access method, and the project aggregate
    jobs = [(f"pageviews/{a}/{safe(t)}.json.gz", f"{API}/per-article/en.wikipedia/{a}/user/{safe(t)}/daily/{START}00/{END}00") for t in sorted(fetch) for a in ACCESS]
    jobs += [(f"aggregate/{a}.json.gz", f"{API}/aggregate/en.wikipedia/{a}/user/daily/{START}00/{END}00") for a in ACCESS]

    def one(job: tuple[str, str]) -> tuple[str, dict] | None:
        rel, u = job
        if (RAW / rel).exists() and rel in files:
            return None
        body = get(u) if not (RAW / rel).exists() else gzip.decompress((RAW / rel).read_bytes())
        local: dict = {}
        save(rel, u, body, local)
        time.sleep(0.05)
        return rel, local[rel]

    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for r in ex.map(one, jobs):
            if r:
                files[r[0]] = r[1]
            done += 1
            if done % 500 == 0:
                print(f"{done}/{len(jobs)}", flush=True)
    man.update({"dataset": "Wikimedia pageviews (daily, user agent) for the English Wikipedia Vital articles (Level 3)",
                "sources": [{"name": "Wikimedia Analytics pageviews API", "url": API, "license": "CC0 1.0",
                             "terms": "https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/documentation/access-policy.html"},
                            {"name": "Wikipedia:Vital articles/Level 3", "revision": VITAL_REV, "revision_timestamp": rev["timestamp"],
                             "license": "CC BY-SA 4.0 (page text; used only to select titles)"}],
                "titles_listed": len(titles), "titles_fetched": len(fetch), "period": f"{START} .. {END}",
                "n_files": len(files), "files": [files[k] for k in sorted(files)]})
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(man, indent=1) + "\n")
    print(f"manifest: {len(files)} files", flush=True)


if __name__ == "__main__":
    main()
