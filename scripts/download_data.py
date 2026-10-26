"""Fetch the pinned public datasets and verify their recorded checksums.

Run from an installed source checkout. Downloading/parsing does not fit a model;
follow with `orgsim ingest <instance>` or `orgsim demo <instance>`.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path, algorithm: str = "sha256") -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def verify(path: Path, checksum: str, algorithm: str = "sha256") -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Missing {path}; run scripts/download_data.py first")
    if digest(path, algorithm) != checksum:
        raise ValueError(f"Checksum mismatch: {path}. Move the file aside before retrying.")


def fetch(url: str, path: Path, checksum: str, algorithm: str = "sha256", *, verify_only: bool = False) -> None:
    if path.exists() or verify_only:
        verify(path, checksum, algorithm)
        print(f"Verified {path.relative_to(ROOT)}", flush=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        # Partial downloads never appear under the expected input filename.
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            partial = Path(stream.name)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "orgsim-data/0.1"})
            with urllib.request.urlopen(request, timeout=90) as response:
                with partial.open("wb") as stream:
                    shutil.copyfileobj(response, stream)
            verify(partial, checksum, algorithm)
            partial.replace(path)
            print(f"Downloaded {path.relative_to(ROOT)}", flush=True)
            return
        except (OSError, ValueError):
            if attempt == 2:
                raise
        finally:
            partial.unlink(missing_ok=True)
        time.sleep(2 * (attempt + 1))


def safe_path(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f"Source path escapes destination: {relative}")
    return target


def onet(verify_only: bool) -> None:
    manifest = json.loads((ROOT / "data/manifests/onet_31_0.json").read_text())
    archive = ROOT / "data/onet/db_31_0_text.zip"
    fetch(manifest["url"], archive, manifest["sha256"], verify_only=verify_only)
    dest = ROOT / manifest["extracted_to"]
    with zipfile.ZipFile(archive) as zipped:
        # Only extract the files in the pinned manifest, not arbitrary ZIP paths.
        for name in manifest["files"]:
            target = safe_path(dest, name)
            members = [m for m in zipped.namelist() if m == name or m.endswith("/" + name)]
            if len(members) != 1:
                raise ValueError(f"Expected one O*NET archive member for {name}")
            data = zipped.read(members[0])
            if target.exists():
                if target.read_bytes() != data:
                    raise ValueError(f"Extracted O*NET file differs from source: {target}")
            elif verify_only:
                raise FileNotFoundError(target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
    print("O*NET tables verified", flush=True)


def trip(verify_only: bool) -> None:
    manifest = json.loads((ROOT / "instances/trip/manifests/sources.json").read_text())
    dest = ROOT / "instances/trip/data/raw/6X4ZZL"
    for entry in manifest["files"]:
        # The simulation ingest needs original Stata tables, not source-code and
        # presentation files from the replication deposit.
        if not (entry.get("original_format") or "").startswith("application/x-stata"):
            continue
        directory = entry["directory"].removeprefix("Replication_nature_final").strip("/")
        name = Path(entry["name"]).with_suffix(".dta").name
        target = safe_path(dest, f"{directory}/{name}")
        url = f"https://dataverse.harvard.edu/api/access/datafile/{entry['dataverse_file_id']}?format=original"
        fetch(url, target, entry["dataverse_md5"], "md5", verify_only=verify_only)


def bpi19(verify_only: bool) -> None:
    manifest = json.loads((ROOT / "instances/bpi19/manifests/sources.json").read_text())
    dest = ROOT / "instances/bpi19/data/raw"
    compressed = dest / "log_IEEE.xes_.gz"
    xes = dest / "BPI_Challenge_2019_icpm.xes"
    fetch(manifest["retrieved_file"]["url"], compressed, manifest["retrieved_file"]["sha256"], verify_only=verify_only)
    expected = manifest["decompressed_file"]["sha256"]
    if xes.exists() or verify_only:
        verify(xes, expected)
    else:
        with tempfile.NamedTemporaryFile(dir=dest, delete=False) as stream:
            partial = Path(stream.name)
        try:
            with gzip.open(compressed, "rb") as source, partial.open("wb") as stream:
                shutil.copyfileobj(source, stream)
            verify(partial, expected)
            partial.replace(xes)
        finally:
            partial.unlink(missing_ok=True)
    norm = ROOT / "instances/bpi19/data/normalized"
    schema = norm / "schema.json"
    parsed = schema.exists() and (norm / "cases.parquet").exists() and (norm / "events.parquet").exists()
    if parsed:
        counts = json.loads(schema.read_text())
        if (counts["n_traces"], counts["n_events"]) != (manifest["counts"]["traces"], manifest["counts"]["events"]):
            raise ValueError("BPI parsed tables are incomplete; move them aside and rerun")
    elif verify_only:
        raise FileNotFoundError("BPI parsed tables missing; rerun scripts/download_data.py bpi19")
    else:
        norm.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="parse-", dir=dest) as temporary:
            staging = Path(temporary)
            subprocess.run([sys.executable, str(ROOT / "instances/bpi19/ingest/audit/parse_xes.py"), str(xes), str(staging)], check=True)
            for name in ("events.parquet", "cases.parquet", "schema.json"):
                if (norm / name).exists():
                    raise FileExistsError(f"Partial BPI parse exists: {norm / name}; move it aside before retrying")
            for name in ("events.parquet", "cases.parquet", "schema.json"):
                (staging / name).replace(norm / name)
    print("BPI source and parsed table counts verified", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", choices=("all", "onet", "trip", "bpi19"), default="all")
    parser.add_argument("--verify-only", action="store_true", help="Check existing inputs without downloading or parsing")
    args = parser.parse_args()
    for name in ("onet", "trip", "bpi19") if args.source == "all" else (args.source,):
        globals()[name](args.verify_only)


if __name__ == "__main__":
    main()
