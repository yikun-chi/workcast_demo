"""Download the CFPB Consumer Complaint Database (full CSV ZIP) and record its SHA-256 in manifests/sources.json.

Source: https://files.consumerfinance.gov/ccdb/complaints.csv.zip, linked from
https://www.consumerfinance.gov/data-research/consumer-complaints/ ("All complaint data we publish is freely
available for anyone to use, analyze, and build on."). The file is regenerated daily; the manifest records the
retrieval date, Last-Modified header, size and hash of the copy actually used.

Usage: python instances/cfpb_complaints/ingest/download.py [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
URL = "https://files.consumerfinance.gov/ccdb/complaints.csv.zip"


def sha256(p: Path) -> str:
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    p = RAW / "complaints.csv.zip"
    hdr_path = RAW / "headers.json"
    if a.force or not p.exists():
        # The CDN refuses Python's urllib; curl is used for the transfer (headers saved for the manifest).
        tmp = p.with_suffix(".part")
        subprocess.run(["curl", "-sSL", "--fail", "-m", "3000", "-D", str(RAW / "headers.txt"), "-o", str(tmp), URL], check=True)
        lines = (RAW / "headers.txt").read_text().splitlines()
        hdr_path.write_text(json.dumps(dict(l.split(": ", 1) for l in lines if ": " in l), indent=1))
        tmp.replace(p)
    headers = json.loads(hdr_path.read_text()) if hdr_path.exists() else {}
    manifest = {"dataset": "CFPB Consumer Complaint Database", "publisher": "Consumer Financial Protection Bureau",
                "landing_page": "https://www.consumerfinance.gov/data-research/consumer-complaints/",
                "field_reference": "https://www.consumerfinance.gov/complaint/data-use/",
                "license": {"name": "Freely available for anyone to use, analyze, and build on (U.S. federal government data)",
                            "source": "https://www.consumerfinance.gov/data-research/consumer-complaints/"},
                "publication_rule": "Complaints are published after the company responds or after 15 days, whichever comes first; only complaints sent to companies for response are published (landing page).",
                "caveat": "Not a statistical sample of consumers' experiences (landing page).",
                "files": [{"name": p.name, "url": URL, "size_bytes": p.stat().st_size, "sha256": sha256(p),
                           "last_modified": headers.get("last-modified") or headers.get("Last-Modified"),
                           "retrieved": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")}],
                "generated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (ROOT / "manifests").mkdir(exist_ok=True)
    (ROOT / "manifests" / "sources.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps(manifest["files"], indent=1))


if __name__ == "__main__":
    main()
