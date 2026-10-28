"""Download the BTS Reporting Carrier On-Time Performance monthly files and record them in manifests/sources.json.

Source: U.S. Department of Transportation, Bureau of Transportation Statistics, TranStats "Reporting Carrier On-Time
Performance (1987-present)", prezipped monthly files:
  https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_<YYYY>_<M>.zip
A work of the U.S. federal government (public domain, 17 U.S.C. 105).

Each file is downloaded once into data/raw/ (a partial download never takes the final name) and never overwritten.
A file already listed in the manifest is checked against its SHA-256; a mismatch stops the run. New files are
added to the manifest with URL, retrieval time, Last-Modified header, byte size and SHA-256.

  python -I instances/airline_ops/ingest/download.py [--start 2015-01] [--end 2026-08]
"""
from __future__ import annotations

import argparse
import hashlib
from concurrent.futures import ThreadPoolExecutor
import json
import os
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
MANIFEST = ROOT / "manifests" / "sources.json"
URL = "https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{y}_{m}.zip"
START, END = "2015-01", "2026-08"


def sha256(p: Path) -> str:
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def months(start: str, end: str) -> list[tuple[int, int]]:
    y, m = map(int, start.split("-")); ye, me = map(int, end.split("-"))
    out = []
    while (y, m) <= (ye, me):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {}


def fetch(url: str, dest: Path) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".part-")
        os.close(fd)
        part = Path(tmp)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "orgsim-data/0.1 (research retrodiction)"})
            with urllib.request.urlopen(req, timeout=300) as r, part.open("wb") as f:
                last_mod = r.headers.get("Last-Modified")
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            if part.stat().st_size < 1_000_000:
                raise OSError(f"suspiciously small download ({part.stat().st_size} bytes)")
            part.replace(dest)
            return {"last_modified": last_mod}
        except OSError as e:
            print(f"  retry {attempt + 1}: {e}", flush=True)
            time.sleep(5 * (attempt + 1))
        finally:
            part.unlink(missing_ok=True)
    raise SystemExit(f"download failed: {url}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    ap.add_argument("--workers", type=int, default=4, help="parallel downloads (the server is slow per connection)")
    args = ap.parse_args()
    man = load_manifest()
    files = {f["name"]: f for f in man.get("files", [])}

    def one(ym: tuple[int, int]) -> dict:
        y, m = ym
        name = f"ontime_{y}_{m:02d}.zip"
        p = RAW / name
        url = URL.format(y=y, m=m)
        if p.exists():
            h = sha256(p)
            if name in files and files[name]["sha256"] != h:
                raise SystemExit(f"hash mismatch for {p}; move it aside before retrying")
            print(f"have {name}", flush=True)
            return files.get(name) or {"name": name, "url": url, "retrieved": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
                                       "last_modified": None, "bytes": p.stat().st_size, "sha256": h}
        info = fetch(url, p)
        print(f"got {name} {p.stat().st_size:,} bytes", flush=True)
        return {"name": name, "url": url, "retrieved": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "last_modified": info["last_modified"], "bytes": p.stat().st_size, "sha256": sha256(p)}

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for rec in ex.map(one, months(args.start, args.end)):
            files[rec["name"]] = rec
    man.update({
        "dataset": "BTS Reporting Carrier On-Time Performance (1987-present)",
        "publisher": "U.S. Department of Transportation, Bureau of Transportation Statistics (TranStats)",
        "landing_page": "https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FGJ&QO_fu146_anzr=b0-gvzr",
        "license": "Public domain: work of the U.S. federal government (17 U.S.C. 105)",
        "raw_dir": "instances/airline_ops/data/raw/",
        "n_files": len(files),
        "files": [files[k] for k in sorted(files)],
    })
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(man, indent=1) + "\n")
    print(f"manifest: {len(files)} files", flush=True)


if __name__ == "__main__":
    main()
