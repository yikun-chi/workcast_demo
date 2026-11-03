"""Package, verify and restore immutable dataset/run snapshots attached to a release."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "yikun-chi/workcast_demo"
TOKEN = re.compile(rb"(?:sk-or-v1-[a-f0-9]{40,}|sk-(?:proj|ant)-[A-Za-z0-9_-]{30,}|gh[pousr]_[A-Za-z0-9]{30,})")
EXCLUDED = {"__pycache__", ".DS_Store", ".exploration.lock"}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_relative(value: str) -> Path:
    p = PurePosixPath(value)
    if p.is_absolute() or ".." in p.parts or not p.parts or "\\" in value:
        raise ValueError(f"Unsafe archive path: {value}")
    allowed = (len(p.parts) >= 3 and p.parts[:2] == ("data", "onet")) or (
        len(p.parts) >= 4 and p.parts[0] == "instances" and p.parts[2] == "data") or (
        len(p.parts) >= 3 and p.parts[0] == "runs")
    if not allowed:
        raise ValueError(f"Path outside snapshot roots: {value}")
    if any(part.startswith(".") or part in EXCLUDED for part in p.parts):
        raise ValueError(f"Hidden/runtime file in snapshot: {value}")
    return Path(*p.parts)


def include(path: Path) -> bool:
    return not any(p.startswith(".") or p in EXCLUDED for p in path.parts) and path.suffix not in (".log", ".pyc") and not path.name.endswith(("-wal", "-shm", "-journal"))


def assert_no_credentials(path: Path) -> None:
    # Scan even binary payloads without loading large datasets into memory.
    with path.open("rb") as stream:
        tail = b""
        while block := stream.read(1024 * 1024):
            if TOKEN.search(tail + block):
                raise ValueError(f"Credential-like content found; review before publishing: {path.name}")
            tail = block[-512:]


def pack(root: Path, output: Path, tag: str, commit: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", tag):
        raise ValueError("Use a simple release tag containing letters, numbers, dots, dashes or underscores")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory; existing snapshots are never overwritten")
    if list((root / "runs").glob("*/.exploration.lock")):
        raise ValueError("Finish active explorations before taking a snapshot")
    for p in (root / "runs").rglob("*.sqlite-wal"):
        if p.stat().st_size:
            raise ValueError("Close workflow writers and checkpoint SQLite before packaging")
    ids = sorted(p.parent.name for p in (root / "instances").glob("*/instance.yaml") if not p.parent.name.startswith("_"))
    groups = [("data-onet", "data", root / "data/onet")]
    groups += [(f"data-{iid}", "data", root / "instances" / iid / "data") for iid in ids]
    groups += [(f"runs-{iid}", "runs", root / "runs" / iid) for iid in ids]
    if (root / "runs/workflow").exists():
        groups.append(("runs-workflow", "runs", root / "runs/workflow"))
    for _, _, source in groups:
        if not source.is_dir():
            raise FileNotFoundError(f"Missing snapshot input: {source}")
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": 1, "repository": REPOSITORY, "tag": tag, "source_commit": commit,
                "created_at": datetime.now(timezone.utc).isoformat(), "assets": [],
                "known_limitations": [{"issue": "https://github.com/yikun-chi/workcast_demo/issues/11",
                                       "note": "The preserved so_chatgpt evaluation has two reused run IDs. Existing artifacts are retained as-is; this snapshot does not repair the lost run lineage."}],
                "source_manifests": {}}
    for p in sorted((root / "data/manifests").glob("*.json")) + sorted((root / "instances").glob("*/manifests/sources.json")):
        manifest["source_manifests"][p.relative_to(root).as_posix()] = {"sha256": digest(p), "document": json.loads(p.read_text())}
    for name, kind, source in groups:
        files = {}
        archive = output / f"{name}.tar.gz"
        temporary = archive.with_suffix(".partial")
        with temporary.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=3) as zipped:
            with tarfile.open(fileobj=zipped, mode="w|") as tar:
                for path in sorted(source.rglob("*")):
                    if path.is_symlink():
                        raise ValueError(f"Symlinks are not snapshot inputs: {path}")
                    if not path.is_file() or not include(path.relative_to(root)):
                        continue
                    relative = path.relative_to(root).as_posix()
                    safe_relative(relative)
                    assert_no_credentials(path)
                    before = path.stat()
                    checksum = digest(path)
                    info = tar.gettarinfo(str(path), arcname=relative)
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    info.mode = 0o644
                    with path.open("rb") as stream:
                        tar.addfile(info, stream)
                    after = path.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise ValueError(f"Input changed during snapshot: {relative}")
                    files[relative] = {"bytes": before.st_size, "sha256": checksum}
        if temporary.stat().st_size >= 2 * 1024**3:
            raise ValueError(f"Release asset exceeds 2 GiB: {name}")
        temporary.replace(archive)
        asset = {"name": archive.name, "kind": kind, "bytes": archive.stat().st_size, "sha256": digest(archive), "files": files}
        manifest["assets"].append(asset)
        print(f"Packed {archive.name}: {len(files)} files, {asset['bytes']/1024**2:.1f} MiB", flush=True)
    (output / "snapshot.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (output / "SHA256SUMS").write_text("".join(f"{digest(p)}  {p.name}\n" for p in sorted(output.iterdir()) if p.is_file() and p.name != "SHA256SUMS"))
    return manifest


def stage_asset(archive: Path, asset: dict, staging: Path) -> list[Path]:
    if archive.stat().st_size != asset["bytes"] or digest(archive) != asset["sha256"]:
        raise ValueError(f"Archive checksum mismatch: {archive.name}")
    seen = set()
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            relative = safe_relative(member.name)
            key = relative.as_posix()
            if not member.isfile() or key in seen or key not in asset["files"]:
                raise ValueError(f"Unexpected archive member: {member.name}")
            entry = asset["files"][key]
            if member.size != entry["bytes"]:
                raise ValueError(f"Unexpected member size: {key}")
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            if digest(target) != entry["sha256"]:
                raise ValueError(f"File checksum mismatch: {key}")
            seen.add(key)
    if seen != set(asset["files"]):
        raise ValueError(f"Incomplete archive: {archive.name}")
    return [Path(p) for p in sorted(seen)]


def restore(snapshot: Path, destination: Path, kind: str = "all", verify_only: bool = False) -> None:
    manifest = json.loads((snapshot / "snapshot.json").read_text())
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported snapshot manifest")
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="workcast-restore-") as temporary:
        staging = Path(temporary)
        paths = []
        for asset in manifest["assets"]:
            if kind != "all" and asset["kind"] != kind:
                continue
            name = asset["name"]
            if Path(name).name != name:
                raise ValueError("Invalid asset filename")
            paths += stage_asset(snapshot / name, asset, staging)
            print(f"Verified {name}", flush=True)
        if len(paths) != len(set(paths)):
            raise ValueError("Overlapping snapshot assets")
        # Preflight every destination before copying anything. Existing data is never overwritten.
        for relative in paths:
            target = destination / relative
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError(f"Destination escapes checkout: {relative}")
            if target.exists() and (not target.is_file() or digest(target) != digest(staging / relative)):
                raise ValueError(f"Existing file differs: {relative}; restore into a fresh checkout")
        if not verify_only:
            for relative in paths:
                target = destination / relative
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as stream, (staging / relative).open("rb") as source:
                        shutil.copyfileobj(source, stream)
        print(f"{'Verified' if verify_only else 'Restored'} {len(paths)} files")


def download(tag: str, output: Path, kind: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", tag):
        raise ValueError("Invalid release tag")
    output.mkdir(parents=True, exist_ok=True)
    base = f"https://github.com/{REPOSITORY}/releases/download/{tag}/"
    def fetch(name):
        if Path(name).name != name:
            raise ValueError("Invalid asset filename")
        target = output / name
        if target.exists():
            return
        temp = target.with_suffix(target.suffix + ".partial")
        with urllib.request.urlopen(base + name, timeout=60) as source, temp.open("wb") as stream:
            shutil.copyfileobj(source, stream)
        temp.replace(target)
    fetch("snapshot.json")
    manifest = json.loads((output / "snapshot.json").read_text())
    if manifest.get("tag") != tag or manifest.get("repository") != REPOSITORY:
        raise ValueError("Release manifest identity mismatch")
    pin = ROOT / "data/manifests/snapshots" / f"{tag}.json"
    if pin.exists() and digest(output / "snapshot.json") != json.loads(pin.read_text())["manifest_sha256"]:
        raise ValueError("Release manifest differs from its committed checksum")
    for asset in manifest["assets"]:
        if kind == "all" or asset["kind"] == kind:
            fetch(asset["name"])
            if digest(output / asset["name"]) != asset["sha256"]:
                raise ValueError(f"Download checksum mismatch: {asset['name']}")
            print(f"Downloaded/verified {asset['name']}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("pack", "download", "restore", "verify"))
    parser.add_argument("--tag", default="snapshot-2026-11-03")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--destination", type=Path, default=ROOT)
    parser.add_argument("--kind", choices=("all", "data", "runs"), default="all")
    args = parser.parse_args()
    directory = args.directory or ROOT / "build/releases" / args.tag
    if args.command == "pack":
        if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
            parser.error("Commit source changes before creating a reproducible snapshot")
        record_path = ROOT / "data/manifests/snapshots" / f"{args.tag}.json"
        if record_path.exists():
            parser.error("This release tag already has a committed snapshot record; use a new tag")
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        manifest = pack(ROOT, directory, args.tag, commit)
        record = {k: manifest[k] for k in ("schema_version", "repository", "tag", "source_commit", "created_at")}
        record.update(manifest_sha256=digest(directory / "snapshot.json"),
                      release_url=f"https://github.com/{REPOSITORY}/releases/tag/{args.tag}",
                      assets=[{**{k: a[k] for k in ("name", "kind", "bytes", "sha256")}, "file_count": len(a["files"])} for a in manifest["assets"]])
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps(record, indent=2) + "\n")
        print(f"Review and commit {record_path.relative_to(ROOT)} after publishing the release")
    elif args.command == "download":
        download(args.tag, directory, args.kind)
    else:
        restore(directory, args.destination, args.kind, args.command == "verify")


if __name__ == "__main__":
    main()
